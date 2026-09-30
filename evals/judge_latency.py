#!/usr/bin/env python3
"""Latency root-cause analysis for the decision judges in judge_comparison.

Splits each request into where its time goes, so a gap between arms can be
attributed to the service (server time) or to our client/network:

- cloud (Jev, GPT-6 Luna, GPT-6.1 Sol): httpcore trace events give connect
  (DNS+TCP), TLS, send, time-to-first-byte and body read; server time comes
  from response headers (openai-processing-ms; any timing header Jev sends).
  network ~= TTFB - server time. Fresh-connection vs keep-alive, plus Luna
  with service_tier=priority.
- local Ollama: /api/generate reports load / prefill / decode durations;
  /v1/systemone handler time is read from Ollama's own GIN access log.
  overhead = wall - server-reported time. Laya: wall (+ trace split) only.
- cold start after keep_alive=0 unload, and 1/4/8-in-flight concurrency.

Payloads are the frozen cases in the judge-comparison manifest; cloud bodies
are built by the same code as judge_comparison (LunaArm is driven against a
capturing client, so its body is exactly what the study sent).

    set -a; . ~/.amplifier/keys.env; set +a
    PYTHONPATH=src python3 evals/judge_latency.py --out DIR local
    ... cold | conc-local | rtt | cloud | conc-cloud | summarize
Records append to DIR/records.jsonl; summarize writes DIR/latency_summary.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from evals.judge_comparison import JEV_URL, LAYA_URL, OLLAMA_SYSTEMONE, OPENAI_URL, LunaArm  # noqa: E402

MANIFEST = ROOT / "docs/evidence/2026-09-30-judge-comparison/manifest.json"
OLLAMA = "http://127.0.0.1:11434"
GIN_LOG = Path.home() / ".ollama/logs/server.log"
UA = {"User-Agent": "amplifier-fast-decisions/0.1"}
PRICES = {"jev": (0.042, 0.0), "luna": (0.10, 0.50), "sol": (2.00, 10.00)}  # USD / M tokens
PRIORITY_MULT = 2.0  # assumed priority-tier multiplier, spend estimate only
WARMUPS = 2
TIMING_HEADER = re.compile(r"server-timing|processing|response-time|upstream-service-time|x-runtime|duration", re.I)


# ---------------------------------------------------------------- cases
def load_cases():
    cases = json.loads(MANIFEST.read_text())["cases"]
    return cases[::3][:30], cases[1::3]  # 30 measured (every 3rd: all kinds/screens); spares for warmups


def schedule(n=30):
    measured, spare = load_cases()
    return [(c, True) for c in spare[:WARMUPS]] + [(c, False) for c in measured[:n]]


# ---------------------------------------------------------------- request bodies
class _Captured(Exception):
    pass


class _CaptureClient:
    async def post(self, url, json=None, headers=None):
        raise _Captured(json)


def luna_body(payload, model, effort, max_tokens):
    """Drive LunaArm.decide until its post, so the body is exactly the study's."""
    coro = LunaArm(model, model, "x", effort=effort, max_tokens=max_tokens).decide(_CaptureClient(), payload)
    try:
        coro.send(None)
    except _Captured as captured:
        return captured.args[0]
    finally:
        coro.close()
    raise RuntimeError("LunaArm did not post")


def qwen_generate_body(model, payload):
    """One call of the bundle's OllamaBackend._answer_once (reverse=False)."""
    import amplifier_fast_decisions.local_backend as lb
    from amplifier_fast_decisions.contracts import Question
    spec = payload["questions"]["decision"]
    question = Question(name="decision", type=spec["type"], instructions=spec["instructions"],
                        criteria=dict(spec.get("criteria") or {}))
    saved, lb.SLOW = lb.SLOW, "\x00no-sentinel"  # same patch as judge_comparison.OllamaBackendArm
    try:
        prompt, _ = lb.build_question_prompt(json.loads(payload["state"]), question, reverse=False)
    finally:
        lb.SLOW = saved
    return {"model": model, "system": lb.QUESTION_SYSTEM, "prompt": prompt,
            "think": False, "stream": False, "logprobs": True, "top_logprobs": 20,
            "keep_alive": "10m", "options": {"temperature": 0, "num_predict": 1, "num_ctx": 4096}}


NONCE = {"on": True, "run": os.urandom(4).hex(), "n": 0}


def novel(payload):
    """Prefix the state with a unique key so no request can hit a prompt/KV cache.

    Ollama 0.35 caches prompt prefixes across requests (a repeated qwen3:8b prompt
    prefilled in ~13 ms vs ~67 ms novel), which would flatter repeated cases. "_n"
    sorts before every lowercase state key, so the divergence starts at the state.
    """
    if not NONCE["on"]:
        return payload
    NONCE["n"] += 1
    state = json.loads(payload["state"])
    return dict(payload, state=json.dumps({"_n": f'{NONCE["run"]}{NONCE["n"]:04d}', **state}))


def arm_request(arm, payload):
    """(url, body, headers, price_key) for an arm name."""
    payload = novel(payload)
    if arm == "jev":
        return (JEV_URL, dict(payload, model="jev-1.13.0"),
                dict(UA, Authorization="Bearer " + os.environ["TYPESAFE_API_KEY"]), "jev")
    if arm in ("luna", "luna-priority"):
        body = luna_body(payload, "gpt-6-luna", "none", 200)
        if arm == "luna-priority":
            body["service_tier"] = "priority"
        return OPENAI_URL, body, {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]}, "luna"
    if arm == "sol":
        return (OPENAI_URL, luna_body(payload, "gpt-6.1-sol", "low", 600),
                {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]}, "sol")
    if arm == "laya":
        return LAYA_URL, payload, {}, None
    kind, _, model = arm.partition(":")  # "so:tev1:0.8b" or "gen:qwen3:8b"
    if kind == "so":
        return OLLAMA_SYSTEMONE, dict(payload, model=model), dict(UA), None
    if kind == "gen":
        return OLLAMA + "/api/generate", qwen_generate_body(model, payload), {}, None
    raise ValueError(arm)


# ---------------------------------------------------------------- timing
def _ms(a, b):
    return None if a is None or b is None else round((b - a) * 1000, 3)


class GinTail:
    """Ollama logs '[GIN] ... | 200 | 186.4ms | 127.0.0.1 | POST "/v1/systemone"' per request."""

    UNITS = {"ns": 1e-6, "µs": 1e-3, "us": 1e-3, "ms": 1.0, "s": 1000.0, "m": 60000.0}
    LINE = re.compile(r"\[GIN\][^\n]*?\|\s*\d+\s*\|\s*([\d.]+)(ns|µs|us|ms|s|m)\s*\|[^\n]*?POST\s+\"([^\"]+)\"")

    def __init__(self):
        self.mark()

    def mark(self):
        self.pos = GIN_LOG.stat().st_size if GIN_LOG.exists() else 0

    async def take(self, path):
        for _ in range(30):
            if GIN_LOG.exists():
                with GIN_LOG.open("rb") as f:
                    f.seek(self.pos)
                    chunk = f.read().decode("utf-8", "replace")
                hits = [m for m in self.LINE.finditer(chunk) if m.group(3) == path]
                if hits:
                    self.mark()
                    value, unit, _ = hits[-1].groups()
                    return round(float(value) * self.UNITS[unit], 3)
            await asyncio.sleep(0.01)
        return None


async def timed_post(client, url, body, headers):
    marks = {}

    async def trace(name, info):
        marks.setdefault(name, time.perf_counter())

    t0 = time.perf_counter()
    response = await client.post(url, json=body, headers=headers, extensions={"trace": trace})
    t_read = time.perf_counter()
    data = response.json() if "json" in response.headers.get("content-type", "") else None
    t1 = time.perf_counter()
    g = marks.get
    first = min(marks.values()) if marks else t0
    rec = {
        "status": response.status_code,
        "wall_ms": _ms(t0, t1),
        "pool_ms": _ms(t0, first),
        "connect_ms": _ms(g("connection.connect_tcp.started"), g("connection.connect_tcp.complete")),
        "tls_ms": _ms(g("connection.start_tls.started"), g("connection.start_tls.complete")),
        "send_ms": _ms(g("http11.send_request_headers.started"), g("http11.send_request_body.complete")),
        "ttfb_ms": _ms(g("http11.send_request_body.complete"), g("http11.receive_response_headers.complete")),
        "body_ms": _ms(g("http11.receive_response_headers.complete"), g("http11.receive_response_body.complete")),
        "client_parse_ms": _ms(t_read, t1),
        "reused_connection": "connection.connect_tcp.started" not in marks,
    }
    return rec, response, data


def usage_cost(price_key, data, priority=False):
    if not price_key or not isinstance(data, dict):
        return None, None, 0.0
    u = data.get("usage") or {}
    i = u.get("prompt_tokens", u.get("input_tokens")) or 0
    o = u.get("completion_tokens", u.get("output_tokens")) or 0
    pi, po = PRICES[price_key]
    return i, o, (i * pi + o * po) / 1e6 * (PRIORITY_MULT if priority else 1.0)


class Recorder:
    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.path = self.out / "records.jsonl"
        self.spend = 0.0

    def write(self, rec):
        self.spend += rec.get("cost_usd") or 0.0
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def note(self, obj):
        with (self.out / "notes.jsonl").open("a") as f:
            f.write(json.dumps(obj) + "\n")


def enrich(rec, arm, response, data):
    h = response.headers
    rec["server_headers"] = {k: v for k, v in h.items() if TIMING_HEADER.search(k)}
    server = None
    if "openai-processing-ms" in h:
        server = float(h["openai-processing-ms"])
    else:
        for k, v in h.items():
            if not TIMING_HEADER.search(k):
                continue
            m = re.search(r"dur=([\d.]+)", v) if k.lower() == "server-timing" else re.fullmatch(r"\s*([\d.]+)\s*(ms)?\s*", v)
            if m:
                server = float(m.group(1))
                break
    rec["server_ms"] = server
    rec["network_ms"] = (round(rec["ttfb_ms"] - server, 3)
                         if server is not None and rec["ttfb_ms"] is not None else None)
    if isinstance(data, dict):
        rec["service_tier"] = data.get("service_tier")
        rec["model"] = data.get("model")
        for k in ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration",
                  "eval_count", "eval_duration"):
            if k in data:
                rec[k] = data[k] / 1e6 if k.endswith("duration") else data[k]
        if "total_duration" in data:
            rec["ollama_overhead_ms"] = round(rec["wall_ms"] - rec["total_duration"], 3)
    return rec


async def one(client, arm, case, gin=None):
    url, body, headers, price_key = arm_request(arm, case["payload"])
    if gin:
        gin.mark()
    rec, response, data = await timed_post(client, url, body, headers)
    rec = enrich(rec, arm, response, data)
    rec["in_tok"], rec["out_tok"], rec["cost_usd"] = usage_cost(price_key, data, arm == "luna-priority")
    if gin and url.startswith(OLLAMA):
        rec["gin_ms"] = await gin.take(url[len(OLLAMA):])
        if rec["gin_ms"] is not None:
            rec["http_overhead_ms"] = round(rec["wall_ms"] - rec["gin_ms"], 3)
    return rec, response


def client(k=1):
    return httpx.AsyncClient(trust_env=False, timeout=120,
                             limits=httpx.Limits(max_connections=k + 2, max_keepalive_connections=k + 2))


async def sequential(rec_out, phase, arm, mode="keepalive", n=30, gin=False):
    tail = GinTail() if gin else None
    shared = client() if mode == "keepalive" else None
    dumped = False
    try:
        for i, (case, warm) in enumerate(schedule(n)):
            c = shared or client()
            response = None
            try:
                rec, response = await one(c, arm, case, tail)
            except Exception as exc:  # record and keep going
                rec = {"error": repr(exc)[:300]}
            finally:
                if not shared:
                    await c.aclose()
            if response is not None and not dumped and arm in ("jev", "luna", "sol"):
                rec_out.note({"arm": arm, "response_header_names": sorted(response.headers.keys())})
                dumped = True
            rec.update(phase=phase, arm=arm, mode=mode, i=i, case_id=case["id"], warmup=warm)
            rec_out.write(rec)
    finally:
        if shared:
            await shared.aclose()


# ---------------------------------------------------------------- phases
async def ollama_ps():
    async with httpx.AsyncClient(trust_env=False, timeout=10) as c:
        r = await c.get(OLLAMA + "/api/ps")
        return [{"name": m["name"], "size_vram": m.get("size_vram"), "expires_at": m.get("expires_at")}
                for m in r.json().get("models", [])]


def _resident(model, ps):
    names = {m["name"] for m in ps}
    return model in names or f"{model}:latest" in names


async def unload(model):
    async with httpx.AsyncClient(trust_env=False, timeout=60) as c:
        await c.post(OLLAMA + "/api/generate", json={"model": model, "keep_alive": 0})
    for _ in range(100):
        if not _resident(model, await ollama_ps()):
            return True
        await asyncio.sleep(0.2)
    return False


async def phase_local(r, args):
    for arm in ["gen:qwen3:0.6b", "gen:qwen3:8b", "gen:tev1:0.8b", "gen:tev1:4b", "gen:nimble",
                "so:tev1:0.8b", "so:tev1:4b", "so:nimble", "laya"]:
        print("local", arm, flush=True)
        await sequential(r, "local", arm, gin=True)
    r.note({"ollama_ps_after_local": await ollama_ps()})


async def phase_cold(r, args):
    measured, _ = load_cases()
    for model in ["tev1:0.8b", "nimble", "qwen3:8b"]:
        for path in (("gen", "so") if model != "qwen3:8b" else ("gen",)):
            ok = await unload(model)
            ps_before = await ollama_ps()
            arm = f"{path}:{model}"
            print("cold", arm, "unloaded" if ok else "STILL RESIDENT", flush=True)
            tail = GinTail()
            async with client() as c:
                for i in range(6):
                    rec, _ = await one(c, arm, measured[i], tail)
                    rec.update(phase="cold", arm=arm, i=i, case_id=measured[i]["id"], warmup=False,
                               unloaded=ok, first=(i == 0))
                    if i == 0:
                        rec["ps_before"] = ps_before
                        rec["ps_after"] = await ollama_ps()
                    r.write(rec)


async def concurrent(r, phase, arm, k, n):
    measured, spare = load_cases()
    async with client(k) as c:
        for case in spare[:WARMUPS]:  # warm model and connection; not recorded
            try:
                await one(c, arm, case)
            except Exception:
                pass
        sem = asyncio.Semaphore(k)
        t0 = time.perf_counter()

        async def job(i, case):
            async with sem:
                started = time.perf_counter()
                try:
                    rec, _ = await one(c, arm, case)
                except Exception as exc:
                    rec = {"error": repr(exc)[:300]}
                rec.update(phase=phase, arm=arm, in_flight=k, i=i, case_id=case["id"], warmup=False,
                           start_offset_ms=round((started - t0) * 1000, 3))
                return rec

        recs = await asyncio.gather(*(job(i, measured[i % len(measured)]) for i in range(n)))
        elapsed = time.perf_counter() - t0
    for rec in recs:
        rec["batch_elapsed_s"] = round(elapsed, 4)
        r.write(rec)


async def phase_conc_local(r, args):
    for arm in ["so:tev1:0.8b", "so:nimble", "gen:qwen3:8b", "laya"]:
        for k in (1, 4, 8):
            print("conc", arm, k, flush=True)
            await concurrent(r, "concurrency", arm, k, 24)


async def phase_cloud(r, args):
    for arm in ["jev", "luna", "sol"]:
        print("cloud keepalive", arm, flush=True)
        await sequential(r, "cloud", arm, "keepalive", 30)
        print("cloud fresh", arm, flush=True)
        await sequential(r, "cloud", arm, "fresh", 10)
    print("cloud priority", flush=True)
    await sequential(r, "cloud", "luna-priority", "keepalive", 20)
    print(f"spend this run ${r.spend:.4f}", flush=True)


async def phase_conc_cloud(r, args):
    for arm, levels, n in [("jev", (1, 4, 8), 24), ("luna", (1, 4, 8), 24), ("sol", (1, 4), 12)]:
        for k in levels:
            print("conc", arm, k, flush=True)
            await concurrent(r, "concurrency", arm, k, n)
    print(f"spend this run ${r.spend:.4f}", flush=True)


def phase_rtt(r, args):
    fmt = "%{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}"
    for host, url in [("api.typesafe.ai", "https://api.typesafe.ai/"),
                      ("api.openai.com", "https://api.openai.com/v1/models")]:
        for i in range(5):
            out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", fmt, "--max-time", "10", url],
                                 capture_output=True, text=True).stdout.split()
            dns, tcp, tls, ttfb, total = (float(x) * 1000 for x in out)
            r.write({"phase": "rtt", "arm": host, "i": i, "warmup": False, "dns_ms": round(dns, 3),
                     "tcp_rtt_ms": round(tcp - dns, 3), "tls_ms": round(tls - tcp, 3),
                     "ttfb_after_tls_ms": round(ttfb - tls, 3), "total_ms": round(total, 3)})
        ping = subprocess.run(["ping", "-c", "5", "-t", "8", host], capture_output=True, text=True).stdout
        m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", ping)
        loss = re.search(r"([\d.]+)% packet loss", ping)
        r.note({"ping": host, "min_avg_max_ms": [float(x) for x in m.groups()] if m else None,
                "loss_pct": loss.group(1) if loss else None})


# ---------------------------------------------------------------- summary
def pct(values, p):
    """Nearest-rank percentile."""
    v = sorted(x for x in values if x is not None)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)] if v else None


FIELDS = ["wall_ms", "pool_ms", "connect_ms", "tls_ms", "send_ms", "ttfb_ms", "body_ms", "client_parse_ms",
          "server_ms", "network_ms", "gin_ms", "http_overhead_ms", "total_duration", "load_duration",
          "prompt_eval_duration", "eval_duration", "ollama_overhead_ms", "prompt_eval_count", "eval_count",
          "in_tok", "out_tok", "dns_ms", "tcp_rtt_ms", "tls_ms", "ttfb_after_tls_ms", "total_ms"]


def _ok(x):
    return not x.get("error") and x.get("status", 200) == 200


def stats(group):
    ok = [x for x in group if _ok(x)]
    s = {"n": len(ok), "errors": len(group) - len(ok)}
    for f in dict.fromkeys(FIELDS):
        vals = [x[f] for x in ok if x.get(f) is not None]
        if vals:
            s[f] = {"p50": pct(vals, 50), "p95": pct(vals, 95)}
    tiers = sorted({x.get("service_tier") for x in ok if x.get("service_tier")})
    if tiers:
        s["service_tier"] = tiers
    return s


def summarize(out):
    rows = [json.loads(line) for line in (Path(out) / "records.jsonl").read_text().splitlines() if line]
    summary = {"percentiles": "nearest-rank; warmups excluded", "sequential": {}, "cold": {},
               "concurrency": {}, "rtt": {}, "errors": {}, "spend_usd": {}}
    for row in rows:
        if not _ok(row):
            summary["errors"].setdefault(f'{row["phase"]}/{row["arm"]}', []).append(row.get("error") or row.get("status"))
        if row.get("cost_usd"):
            summary["spend_usd"][row["arm"]] = round(summary["spend_usd"].get(row["arm"], 0) + row["cost_usd"], 6)
    summary["spend_usd"]["total"] = round(sum(summary["spend_usd"].values()), 6)
    groups = {}
    for row in rows:
        if row.get("warmup"):
            continue
        if row["phase"] in ("local", "cloud"):
            groups.setdefault(("sequential", f'{row["arm"]}|{row.get("mode", "keepalive")}'), []).append(row)
        elif row["phase"] == "rtt":
            groups.setdefault(("rtt", row["arm"]), []).append(row)
        elif row["phase"] == "concurrency":
            groups.setdefault(("concurrency", f'{row["arm"]}|k={row["in_flight"]}'), []).append(row)
    for (section, key), group in groups.items():
        s = stats(group)
        if section == "concurrency":
            s = {"n": s["n"], "errors": s["errors"], "wall_ms": s.get("wall_ms"), "server_ms": s.get("server_ms"),
                 "throughput_rps": round(len(group) / group[0]["batch_elapsed_s"], 3),
                 "batch_elapsed_s": group[0]["batch_elapsed_s"]}
            ok = [x for x in group if _ok(x)]
            if len(ok) < len(group) and ok:  # a stalled request dominates the batch; show the rest too
                makespan = max(x["start_offset_ms"] + x["wall_ms"] for x in ok) / 1000
                s["ok_only_throughput_rps"] = round(len(ok) / makespan, 3)
        summary[section][key] = s
    for row in rows:
        if row["phase"] == "cold":
            summary["cold"].setdefault(row["arm"], []).append(
                {k: row.get(k) for k in ("i", "wall_ms", "load_duration", "total_duration", "gin_ms", "unloaded",
                                         "ps_before", "ps_after") if row.get(k) is not None})
    notes = Path(out) / "notes.jsonl"
    summary["notes"] = [json.loads(x) for x in notes.read_text().splitlines()] if notes.exists() else []
    (Path(out) / "latency_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-nonce", action="store_true", help="send case payloads unmodified (cache hits possible)")
    ap.add_argument("phase", choices=["local", "cold", "conc-local", "rtt", "cloud", "conc-cloud", "summarize"])
    args = ap.parse_args()
    r = Recorder(args.out)
    NONCE["on"] = not args.no_nonce
    if args.phase != "summarize":
        r.note({"phase": args.phase, "nonce": NONCE["on"], "nonce_run": NONCE["run"]})
    if args.phase == "summarize":
        print(json.dumps(summarize(args.out)["spend_usd"]))
    elif args.phase == "rtt":
        phase_rtt(r, args)
    else:
        runner = {"local": phase_local, "cold": phase_cold, "conc-local": phase_conc_local,
                  "cloud": phase_cloud, "conc-cloud": phase_conc_cloud}[args.phase]
        asyncio.run(runner(r, args))
    print("done", args.phase, flush=True)


if __name__ == "__main__":
    main()
