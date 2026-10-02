#!/usr/bin/env python3
"""Live, read-only dashboard for a paired cost-measurement campaign (see evals/paired.py).

    paired_dashboard.py build --out <campaign> --html <path> [--json <path>] [--show-test]
    paired_dashboard.py serve --out <campaign> --port 8790 --interval 60

Reads schedule.json / state.json / ledger.json, per-session result.json and the session events.jsonl files,
and writes ONE self-contained HTML file (inline CSS/JS/SVG, no network). It never writes inside the campaign
directory, never launches or signals campaign processes and never runs scenario code. Per-session costs use the
same functions as `paired.py rows` (paired.parse_events / recompute_cost / tools_normalize) and are cached, so
each finished session is parsed once. `serve` limits parsing to ~1.2 s per refresh; a cold cache warms up over
a few refreshes (the page says how many sessions are costed so far).
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paired as P  # noqa: E402  (parse_events, recompute_cost, tools_normalize, cache_audit: one cost definition)

SLUG = re.compile(r"[^A-Za-z0-9._-]")          # mirrors scripts/forge_e2e._slug
STALE_S = 180
LOG_ERR = re.compile(r"error|traceback|exception|fail|exit\s*\d|killed|exclu|breaker|abort|budget", re.I)
ARM_ORDER = ["aa", "shipped", "sticky", "sonnet"]
ARM_LABEL = {"aa": "aa (noise floor: same config as anchor)", "shipped": "shipped", "sticky": "sticky",
             "sonnet": "sonnet (host-independent control)"}


# ------------------------------------------------------------------------------------------------ small helpers

def rj(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def ts(value):
    return P._ts(value)


def usd(x, nd=2):
    return "n/a" if x is None else f"{'-' if x < 0 else ''}${abs(x):,.{nd}f}"


def dur(sec):
    if sec is None:
        return "n/a"
    sec = int(max(sec, 0))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return (f"{d}d " if d else "") + (f"{h}h " if h or d else "") + f"{m}m" + ("" if (h or d) else f" {s}s")


def clock(t):
    return "n/a" if t is None else datetime.fromtimestamp(t).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def esc(x):
    return html.escape(str(x), quote=True)


def quantile(vals, q):
    v = sorted(vals)
    if not v:
        return None
    i = (len(v) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


# ------------------------------------------------------------------------------------------------ session cache

class Cache:
    """Persistent per-session cost cache: finished sessions are immutable, so each is parsed once."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        d = (rj(self.path, {}) or {}) if self.path else {}
        ok = d.get("v") == 1
        self.sessions = d.get("sessions", {}) if ok else {}
        self.attempts = d.get("attempts", {}) if ok else {}
        self.dirty = False

    def save(self):
        if not (self.path and self.dirty):
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"v": 1, "sessions": self.sessions, "attempts": self.attempts}), encoding="utf-8")
        os.replace(tmp, self.path)
        self.dirty = False


def session_entry(cache: Cache, sdir: Path, tpt: float, deadline):
    """Cached summary of one finished session (None until its result.json exists)."""
    rp = sdir / "result.json"
    try:
        mt = rp.stat().st_mtime
    except OSError:
        return None
    key = str(sdir)
    e = cache.sessions.get(key)
    if e and e.get("mt") == mt and e.get("parsed"):
        return e
    if not e or e.get("mt") != mt:
        res = rj(rp)
        if not isinstance(res, dict):
            return None
        turns = res.get("turns") or []
        passes = [bool(t.get("turn_passed")) for t in turns]
        e = {"mt": mt, "sid": res.get("session_id"), "parsed": False,
             "status": "infra_fail" if res.get("infrastructure_failure")
             else ("ok" if res.get("outcome_passed") else "agent_fail"),
             "turns": len(turns), "pass_frac": (sum(passes) / len(passes)) if passes else 0.0,
             "started": ts(res.get("started_at")), "ended": ts(res.get("ended_at")),
             "killed": (sdir / P.KILL_MARKER).exists()}
        cache.sessions[key] = e
        cache.dirty = True
    if deadline is not None and time.monotonic() > deadline:
        return e                                    # costed on a later refresh
    parsed = P.parse_events(P.sessions_dir_for_workspace(sdir / "workspace") / (e.get("sid") or "none"))
    reqs = parsed["requests"]
    rec = [P.recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"]) for r in reqs]
    raw = sum(c for c in rec if c is not None)
    norm = P.tools_normalize(reqs, tpt) if tpt else {}
    e.update(parsed=True, events_error=parsed["error"], n_req=len(reqs), cost_raw=raw,
             cost_norm=raw + sum(v["delta_usd"] for v in norm.values()),
             cost_provider=sum(r["cost"] for r in reqs),
             audit_clean=bool(P.cache_audit(reqs, tpt)["cache_audit_clean"]))
    cache.dirty = True
    return e


# ------------------------------------------------------------------------------------------------ environment probes

def campaign_process(out: Path):
    """The `paired.py run` process of this campaign: {pid, etime, parallel} or None."""
    try:
        txt = subprocess.run(["ps", "-axo", "pid=,etime=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in txt.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", line)
        if not m or not re.search(r"paired\.py\s+run\b", m.group(3)) or "run_paired.sh" in m.group(3):
            continue
        mo = re.search(r"--out\s+(\S+)", m.group(3))
        if mo and Path(mo.group(1)).expanduser().resolve() != out:
            continue
        mp = re.search(r"--parallel\s+(\d+)", m.group(3))
        return {"pid": int(m.group(1)), "etime": P._etime_seconds(m.group(2)), "parallel": int(mp.group(1)) if mp else None}
    return None


def free_memory_gb():
    try:
        txt = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    page, pages = 4096, {}
    for line in txt.splitlines():
        if "page size of" in line:
            page = int(line.split("page size of")[1].split()[0])
        elif ":" in line:
            k, v = line.split(":", 1)
            d = "".join(c for c in v if c.isdigit())
            if d:
                pages[k.strip()] = int(d)
    if not pages:
        return None
    return page * (pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)) / 1e9


def forge_sessions():
    home = Path.home() / ".forge"
    cap = (rj(home / "settings.json", {}) or {}).get("maxSessions")
    lst = rj(home / "sessions.json", None)
    isl = isinstance(lst, list)
    return {"count": len(lst) if isl else None, "max": cap,
            "exited": sum(1 for s in lst if isinstance(s, dict) and s.get("status") == "exited") if isl else None}


def log_tail(out: Path, n=10):
    try:
        with (out / "run.log").open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(fh.tell() - 65536, 0))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return [], None
    floor = None
    for ln in lines:
        m = re.search(r"floor ([\d.]+) GB", ln)
        if m:
            floor = float(m.group(1))
    return [ln.strip()[:240] for ln in lines if LOG_ERR.search(ln)][-n:], floor


# ------------------------------------------------------------------------------------------------ collection

def attempt_by_n(wave, n):
    return next((a for a in (wave or {}).get("attempts", []) if a.get("attempt") == n), None)


def sdir_of(att, s) -> Path:
    return Path(att.get("root", "")) / SLUG.sub("-", s["key"])


def attempt_end(cache: Cache, att):
    root = att.get("root")
    if not root or att.get("status") == "running":
        return None
    if root in cache.attempts:
        return cache.attempts[root].get("end")
    ends = []
    for s in att.get("sessions", []):
        r = rj(sdir_of(att, s) / "result.json")
        if isinstance(r, dict) and ts(r.get("ended_at")):
            ends.append(ts(r["ended_at"]))
    try:
        end = max(ends) if ends else os.stat(root).st_mtime
    except OSError:
        return None
    cache.attempts[root] = {"end": end}
    cache.dirty = True
    return end


def geo(lst):
    return math.exp(sum(lst) / len(lst)) if lst else None


def collect(out, cache_path=None, parse_budget_s=None, show_test=False, now=None) -> dict:
    out = Path(out).expanduser().resolve()
    now = now or time.time()
    deadline = None if parse_budget_s is None else time.monotonic() + parse_budget_s
    sched = rj(out / "schedule.json", {}) or {}
    state = rj(out / "state.json", {}) or {}
    ledger = rj(out / "ledger.json", {}) or {}
    cache = Cache(cache_path)
    warnings = []
    for name, d in (("schedule.json", sched), ("state.json", state), ("ledger.json", ledger)):
        if not d:
            warnings.append(f"{name} is missing or unreadable; the sections that need it are partial.")
    scen = sched.get("scenarios") or {}
    swaves = sched.get("waves") or {}
    swave = state.get("waves") or {}
    design = None
    if sched.get("design"):
        try:
            design = P.load_design(P.REPO_ROOT / "evals" / "paired" / f"{sched['design']}.yaml")
        except Exception as exc:  # noqa: BLE001 -- the dashboard must keep rendering
            warnings.append(f"design file not readable ({exc}); costs are on the raw recomputed basis (no tools normalization).")
    tpt = float(((design or {}).get("cache_audit") or {}).get("tools_prefix_tokens", 0) or 0)
    wave_ids = list(sched.get("wave_order") or swaves or swave)
    for wid in swave:
        if wid not in wave_ids:
            wave_ids.append(wid)

    def wsplit(wid):
        ss = swaves.get(wid) or []
        return (scen.get(ss[0]["scenario"], {}).get("split") if ss else None) or "unknown"

    def whost(wid):
        hs = [s["host"] for s in swaves.get(wid) or [] if s.get("host") not in (None, "any")]
        return hs[0] if hs else "any"

    def west(wid):
        return sum(s.get("est_usd") or 0 for s in swaves.get(wid) or [])

    status = {wid: (swave.get(wid) or {}).get("status", "pending") for wid in wave_ids}
    counts = {k: sum(1 for v in status.values() if v == k) for k in ("done", "running", "pending", "excluded", "config_error")}
    counts["other"] = len(status) - sum(counts.values())

    # ---- per-session costs for accepted attempts of done waves
    entries, uncosted, no_result = [], 0, 0
    wave_end, wave_start = {}, {}
    for wid in wave_ids:
        w = swave.get(wid) or {}
        att = attempt_by_n(w, w.get("accepted_attempt")) if status.get(wid) == "done" else None
        if not att:
            continue
        for s in att.get("sessions", []):
            e = session_entry(cache, sdir_of(att, s), tpt, deadline)
            if e is None:
                no_result += 1
                continue
            uncosted += 0 if e.get("parsed") else 1
            entries.append({"wid": wid, "s": s, "e": e, "wave_valid": att.get("wave_valid", True)})
            if e.get("ended"):
                wave_end[wid] = max(wave_end.get(wid, 0), e["ended"])
            if e.get("started"):
                wave_start[wid] = min(wave_start.get(wid, 1e18), e["started"])
    costed = [x for x in entries if x["e"].get("parsed") and x["e"].get("cost_norm") is not None]
    first_start = min(wave_start.values(), default=None)

    # ---- running waves
    running = []
    for wid in wave_ids:
        if status.get(wid) != "running":
            continue
        att = ((swave.get(wid) or {}).get("attempts") or [{}])[-1]
        sess = []
        for s in att.get("sessions", []):
            d = sdir_of(att, s)
            rf = rj(d / "running.json", {}) or {}
            fin = (d / "result.json").exists()
            alive = None
            if rf.get("controller_pid") and not fin:
                try:
                    os.kill(rf["controller_pid"], 0)       # signal 0: existence check only
                    alive = True
                except ProcessLookupError:
                    alive = False
                except OSError:
                    alive = True
            started = ts(rf.get("started_at"))
            if started and (first_start is None or started < first_start):
                first_start = started
            sess.append({"arm": s["arm"], "host": s["host"], "turn": rf.get("turn"),
                         "turns": (scen.get(s["scenario"]) or {}).get("turns"),
                         "elapsed": (now - started) if started and not fin else None,
                         "state": "finished" if fin else ("running" if alive else ("not alive" if alive is False else "starting"))})
        running.append({"wid": wid, "attempt": att.get("attempt"), "sessions": sess})

    # ---- progress
    groups = {}
    for wid in wave_ids:
        g = groups.setdefault((wsplit(wid), whost(wid)), {"waves": 0, "done": 0, "sessions": 0, "sdone": 0})
        n = len(swaves.get(wid) or [])
        g["waves"] += 1
        g["sessions"] += n
        if status.get(wid) == "done":
            g["done"] += 1
            g["sdone"] += n
    total_waves = len(wave_ids)
    total_sessions = sum(len(swaves.get(w) or []) for w in wave_ids)
    done_sessions = sum(len(swaves.get(w) or []) for w in wave_ids if status.get(w) == "done")
    ends = sorted(wave_end.values())
    elapsed = (now - first_start) if first_start else None
    span60 = min(3600, elapsed) if elapsed else 3600
    rate60 = sum(1 for t in ends if t >= now - 3600) / (span60 / 3600)
    rate_all = (counts["done"] / (elapsed / 3600)) if elapsed and elapsed > 0 else None
    remaining = counts["pending"] + counts["running"]
    eta = {k: (remaining / r * 3600 if r else None) for k, r in (("recent", rate60), ("overall", rate_all))}

    # ---- spend
    spent_map, reserved_map = ledger.get("spent") or {}, ledger.get("reserved") or {}
    budget = ledger.get("budget_usd") or sched.get("budget_usd")
    spent, reserved = sum(spent_map.values()), sum(reserved_map.values())
    by_wave, series_raw, pre = {}, [], 0.0
    for k, v in spent_map.items():
        m = re.match(r"^(.*)#a(\d+)$", k)
        if not m:
            pre += v
            continue
        by_wave[m.group(1)] = by_wave.get(m.group(1), 0.0) + v
        att = attempt_by_n(swave.get(m.group(1)), int(m.group(2)))
        t = attempt_end(cache, att) if att else None
        if t:
            series_raw.append((t, v))
    series, acc = [], pre
    for t, v in sorted(series_raw):
        acc += v
        series.append((t, acc))
    done_ids = [w for w in wave_ids if status.get(w) == "done"]
    ratios = [by_wave[w] / west(w) for w in done_ids if w in by_wave and west(w) > 0]
    est_done = sum(west(w) for w in done_ids if w in by_wave)
    ratio_mid = (sum(by_wave[w] for w in done_ids if w in by_wave) / est_done) if est_done else None
    est_pending = sum(west(w) for w in wave_ids if status.get(w) == "pending")
    proj = {}
    if ratio_mid is not None:
        lo_r = min(quantile(ratios, 0.25) or ratio_mid, ratio_mid)
        hi_r = max(quantile(ratios, 0.75) or ratio_mid, ratio_mid)
        base = spent + reserved
        proj = {"mid": base + ratio_mid * est_pending, "low": base + lo_r * est_pending,
                "high": base + hi_r * est_pending, "ratio": ratio_mid}
    spend = {"spent": spent, "reserved": reserved, "budget": budget, "preflight": pre,
             "per_wave": (sum(by_wave.values()) / len(done_ids)) if done_ids else None,
             "sched_est_total": sched.get("est_total_usd"), "est_pending": est_pending, "proj": proj,
             "series": series, "measured_norm": sum(x["e"]["cost_norm"] for x in costed),
             "measured_raw": sum(x["e"]["cost_raw"] for x in costed),
             "measured_provider": sum(x["e"]["cost_provider"] for x in costed),
             "costed": len(costed), "entries": len(entries), "uncosted": uncosted, "no_result": no_result}

    # ---- health
    failed, excluded, kills = [], [], []
    attempts_total = 0
    for wid in wave_ids:
        atts = (swave.get(wid) or {}).get("attempts", [])
        for a in atts:
            attempts_total += 1
            if a.get("status") not in ("done", "running"):
                kinds = a.get("failure_kinds") or {}
                failed.append({"wid": wid, "attempt": a.get("attempt"), "status": a.get("status"),
                               "reason": a.get("reason") or ", ".join(f"{k.rsplit('-', 1)[-1]}: {v}" for k, v in kinds.items()) or "n/a"})
            for s in a.get("sessions", []):
                kp = sdir_of(a, s) / P.KILL_MARKER
                if kp.exists():
                    k = rj(kp, {}) or {}
                    kills.append({"wid": wid, "arm": s["arm"], "reason": k.get("reason"), "rss_gb": k.get("rss_gb")})
        if status.get(wid) in ("excluded", "config_error"):
            last = (atts or [{}])[-1]
            excluded.append({"wid": wid, "status": status[wid], "reason": last.get("reason") or last.get("status") or "n/a"})
    errs, floor = log_tail(out)
    health = {"failed_attempts": failed, "attempts_total": attempts_total, "excluded": excluded, "kills": kills,
              "audit_flagged": [f"{x['wid']}/{x['s']['arm']}" for x in costed if not x["e"].get("audit_clean", True)],
              "audit_checked": len(costed), "free_gb": free_memory_gb(), "floor_gb": floor,
              "forge": forge_sessions(), "log_errors": errs}

    # ---- interim results (every split except TEST unless show_test)
    anchors = {(x["s"]["scenario"], x["s"]["rep"], x["s"]["host"]): x for x in costed if x["s"]["arm"] == "anchor"}
    pair_rows = {}
    for x in costed:
        s = x["s"]
        if s["arm"] == "anchor" or (not show_test and (scen.get(s["scenario"]) or {}).get("split") == "test"):
            continue
        for host in ([s["host"]] if s["host"] != "any" else sorted({h for (_, _, h) in anchors})):
            a = anchors.get((s["scenario"], s["rep"], host))
            if a is None:
                continue
            if not (x["wave_valid"] and a["wave_valid"] and "infra_fail" not in (x["e"]["status"], a["e"]["status"])
                    and not x["e"]["killed"] and not a["e"]["killed"]):
                continue
            c, ac = x["e"]["cost_norm"], a["e"]["cost_norm"]
            pr = pair_rows.setdefault((host, s["arm"]), {"lr": [], "saved": [], "q": [], "aq": []})
            if c > 0 and ac > 0:
                pr["lr"].append(math.log(c / ac))
            pr["saved"].append(ac - c)
            pr["q"].append(x["e"]["pass_frac"])
            pr["aq"].append(a["e"]["pass_frac"])
    interim = []
    for (host, arm), pr in sorted(pair_rows.items(), key=lambda kv: (kv[0][0], ARM_ORDER.index(kv[0][1]) if kv[0][1] in ARM_ORDER else 9)):
        n = len(pr["lr"])
        mean = sum(pr["lr"]) / n if n else None
        se = (math.sqrt(sum((v - mean) ** 2 for v in pr["lr"]) / (n - 1)) / math.sqrt(n)) if n > 1 else None
        interim.append({"host": host, "arm": arm, "n": len(pr["saved"]), "gm": geo(pr["lr"]),
                        "gm_lo": math.exp(mean - se) if se is not None else None,
                        "gm_hi": math.exp(mean + se) if se is not None else None,
                        "saved": sum(pr["saved"]) / len(pr["saved"]),
                        "q_arm": sum(pr["q"]) / len(pr["q"]), "q_anchor": sum(pr["aq"]) / len(pr["aq"])})

    cache.save()
    sf = out / "state.json"
    proc = campaign_process(out)
    return {
        "generated": now, "campaign": str(out), "plan_id": sched.get("plan_id"), "design": sched.get("design"),
        "created_at": sched.get("created_at"), "started": first_start, "elapsed": elapsed, "process": proc,
        "state_mtime": sf.stat().st_mtime if sf.exists() else None,
        "parallel": (proc or {}).get("parallel"), "sched_parallel": sched.get("parallel"),
        "counts": counts, "total_waves": total_waves, "total_sessions": total_sessions, "done_sessions": done_sessions,
        "groups": {f"{k[0]}|{k[1]}": v for k, v in sorted(groups.items())},
        "rate60": rate60, "rate_all": rate_all, "eta": eta, "wave_done_times": ends,
        "spend": spend, "health": health, "running": running, "interim": interim, "show_test": show_test,
        "basis": "tools-normalized, as `paired.py rows`" if tpt else "raw recomputed (tools prefix allowance unavailable)",
        "warnings": warnings}


# ------------------------------------------------------------------------------------------------ rendering

CSS = """
:root{--bg:#fff;--fg:#1b1f23;--mut:#4a5159;--card:#f5f6f8;--line:#c9ced6;--ok:#0b6b2f;--warn:#8a5300;--bad:#a4120f;--acc:#0b57b7;--bar:#d9dde3}
@media (prefers-color-scheme:dark){:root{--bg:#101215;--fg:#e7eaee;--mut:#a9b0ba;--card:#181b20;--line:#363c45;--ok:#5fd68a;--warn:#f0b35a;--bad:#ff8a84;--acc:#7db4ff;--bar:#2a2f37}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1240px;margin:0 auto;padding:12px 16px 40px}h1{font-size:1.35rem;margin:.2rem 0}h2{font-size:1.1rem;margin:0 0 .5rem}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:14px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.kpi{border:1px solid var(--line);border-radius:6px;padding:8px 10px;background:var(--bg)}
.kpi b{display:block;font-size:1.25rem}.kpi span{color:var(--mut);font-size:.82rem}.note{color:var(--mut);font-size:.88rem;margin:.4rem 0}
.wrap{overflow-x:auto;margin:8px 0}table{border-collapse:collapse;width:100%;font-size:.88rem}caption{text-align:left;font-weight:600;padding:4px 0;color:var(--mut)}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.bar{display:flex;height:16px;border-radius:8px;overflow:hidden;background:var(--bar);margin:6px 0}
.bar i{display:block;height:100%}.banner{border:2px solid var(--bad);color:var(--bad);padding:8px 12px;border-radius:8px;font-weight:700;margin:10px 0}
.interim{border:2px dashed var(--warn)}code,pre{font:12px ui-monospace,Menlo,monospace}pre{white-space:pre-wrap;word-break:break-word;margin:0}
svg{width:100%;height:auto;max-height:220px}svg text{fill:var(--mut);font-size:11px}
@media (max-width:600px){body{font-size:14px}main{padding:8px}.grid{grid-template-columns:repeat(2,1fr)}}
"""

JS = """
(function(){var G=%d*1000,u=document.getElementById('age'),w=document.getElementById('stale');
function f(s){s=Math.max(0,Math.round(s));return s<90?s+' s':Math.floor(s/60)+' min '+(s%%60)+' s'}
function t(){var a=(Date.now()-G)/1000;u.textContent=f(a)+' ago';w.hidden=a<=%d}
t();setInterval(t,1000);})();
"""


def table(caption, headers, rows, numeric=()):
    th = "".join(f'<th scope="col"{" class=n" if i in numeric else ""}>{esc(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f"<td{' class=n' if i in numeric else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">none</td></tr>'
    return f'<div class="wrap" tabindex="0"><table><caption>{esc(caption)}</caption><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def kpi(label, value, sub="", cls=""):
    return f'<div class="kpi"><b class="{cls}">{value}</b><span>{esc(label)}{(" - " + esc(sub)) if sub else ""}</span></div>'


def spend_svg(series, projected, now):
    if len(series) < 2:
        return '<p class="note">Not enough finished attempts to draw the spend line yet.</p>'
    W, H, L, B = 640, 180, 52, 22
    t0, t1 = series[0][0], max(series[-1][0], now)
    top = max(series[-1][1], projected or 0)
    ymax = top * 1.05 or 1
    X = lambda t: L + (t - t0) / max(t1 - t0, 1) * (W - L - 8)
    Y = lambda v: H - B - v / ymax * (H - B - 8)
    pts = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in series)
    proj = (f'<line x1="{L}" x2="{W - 8}" y1="{Y(projected):.1f}" y2="{Y(projected):.1f}" stroke="var(--warn)" stroke-dasharray="5 4"/>'
            f'<text x="{L + 4}" y="{Y(projected) + 12:.1f}">projected total {usd(projected, 0)}</text>') if projected else ""
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Cumulative spend over time, now {usd(series[-1][1])}">'
            f'<line x1="{L}" x2="{L}" y1="8" y2="{H - B}" stroke="var(--line)"/><line x1="{L}" x2="{W - 8}" y1="{H - B}" y2="{H - B}" stroke="var(--line)"/>'
            f'<polyline fill="none" stroke="var(--acc)" stroke-width="2" points="{pts}"/>{proj}'
            f'<text x="2" y="14">{usd(top, 0)}</text><text x="2" y="{H - B}">$0</text>'
            f'<text x="{L}" y="{H - 6}">{esc(datetime.fromtimestamp(t0).strftime("%m-%d %H:%M"))}</text>'
            f'<text x="{W - 8}" y="{H - 6}" text-anchor="end">{esc(datetime.fromtimestamp(t1).strftime("%m-%d %H:%M"))}</text></svg>')


def render(m: dict) -> str:
    c, sp, h, now = m["counts"], m["spend"], m["health"], m["generated"]
    tot = max(m["total_waves"], 1)
    proc = m["process"]
    stat = (f'<span class="ok">running</span> (pid {proc["pid"]}, up {dur(proc["etime"])})' if proc
            else '<span class="bad">stopped</span> (no paired.py run process)')
    seg = lambda n, col, lab: f'<i style="width:{n / tot * 100:.2f}%;background:{col}" title="{esc(lab)}: {n}"></i>'
    bar = (f'<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="{m["total_waves"]}" aria-valuenow="{c["done"]}" '
           f'aria-label="Waves done">{seg(c["done"], "var(--ok)", "done")}{seg(c["running"], "var(--acc)", "running")}'
           f'{seg(c["excluded"] + c["config_error"], "var(--bad)", "excluded")}</div>')
    gr = [(k.split("|")[0], k.split("|")[1], v) for k, v in m["groups"].items()]
    prog = table("Waves and sessions finished, by split and host (a wave = one scenario run by all its arms together)",
                 ["Split", "Host", "Waves done / total", "Sessions done / total"],
                 [[esc(s), esc(hh), f'{v["done"]} / {v["waves"]}', f'{v["sdone"]} / {v["sessions"]}'] for s, hh, v in gr], (2, 3))
    fm = lambda x, u: "n/a" if x is None else f"{x:.2f}{u}"
    pj = sp["proj"]
    over = bool(pj and sp["budget"] and pj["high"] > sp["budget"])
    run_rows = [[esc(r["wid"]), esc(s["arm"]), esc(s["host"]), f'{s["turn"] if s["turn"] is not None else "?"} / {s["turns"] or "?"}',
                 dur(s["elapsed"]) if s["elapsed"] is not None else "n/a",
                 f'<span class="{"bad" if s["state"] == "not alive" else ""}">{esc(s["state"])}</span>']
                for r in m["running"] for s in r["sessions"]]
    f2 = lambda x: "n/a" if x is None else f"{x:.2f}"
    fp = lambda x: "n/a" if x is None else f"{x * 100:.0f}%"
    ir = []
    for r in m["interim"]:
        rng = f' ({f2(r["gm_lo"])}-{f2(r["gm_hi"])})' if r["gm_lo"] is not None else ""
        ir.append([esc(r["host"]), esc(ARM_LABEL.get(r["arm"], r["arm"])), str(r["n"]), f2(r["gm"]) + rng,
                   usd(r["saved"], 3), f'{fp(r["q_arm"])} vs {fp(r["q_anchor"])}'])
    fails = [[esc(x["wid"]), str(x["attempt"]), esc(x["status"]), esc(x["reason"])] for x in h["failed_attempts"][-12:]]
    exc = [[esc(x["wid"]), esc(x["status"]), esc(x["reason"])] for x in h["excluded"]]
    kills = [[esc(k["wid"]), esc(k["arm"]), esc(k["reason"]), esc(k["rss_gb"])] for k in h["kills"][-8:]]
    forge = h["forge"]
    fcls = "bad" if forge["count"] is not None and forge["max"] and forge["count"] >= forge["max"] else ""
    memcls = "warn" if (h["free_gb"] is not None and h["floor_gb"] and h["free_gb"] < h["floor_gb"] * 1.25) else ""
    age_state = f'state.json changed {dur(now - m["state_mtime"])} before this update' if m["state_mtime"] else "state.json not found"
    warns = "".join(f'<p class="warn">{esc(w)}</p>' for w in m["warnings"])
    test_note = ("Test split shown (--show-test): this breaks the preregistered blinding for interim reading."
                 if m["show_test"] else "Test split is hidden on purpose (preregistration): only TRAIN (non-test) waves appear here.")
    par = m["parallel"] if m["parallel"] is not None else "n/a"
    par_sub = f"scheduled {m['sched_parallel']}" if m["sched_parallel"] not in (None, m["parallel"]) else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60"><title>Paired campaign {esc(m["plan_id"] or "")} dashboard</title><style>{CSS}</style></head><body><main>
<div id="stale" class="banner" role="alert" hidden>STALE: this page's data is more than 3 minutes old. The dashboard server may have stopped.</div>
<header><h1>Paired campaign dashboard: {esc(m["design"] or "?")} / {esc(m["plan_id"] or "?")}</h1>
<p class="note">Updated {esc(clock(now))} (<span id="age">now</span>); reloads itself every 60 s. {esc(age_state)}.</p>{warns}
<div class="grid">{kpi("campaign status", stat)}{kpi("started (first session)", esc(clock(m["started"])))}{kpi("elapsed", dur(m["elapsed"]))}
{kpi("--parallel (sessions at once)", esc(par), par_sub)}</div></header>

<section aria-labelledby="h-prog"><h2 id="h-prog">1. Progress</h2>{bar}
<div class="grid">{kpi("waves done", f'{c["done"]} / {m["total_waves"]}', f'{c["done"] / tot * 100:.1f}%')}{kpi("running now", c["running"])}{kpi("pending", c["pending"])}
{kpi("excluded / config error", f'{c["excluded"]} / {c["config_error"]}', "", "bad" if c["excluded"] + c["config_error"] else "")}
{kpi("sessions done", f'{m["done_sessions"]} / {m["total_sessions"]}')}{kpi("throughput, last 60 min", fm(m["rate60"], " waves/h"))}{kpi("throughput, overall", fm(m["rate_all"], " waves/h"), "since first session")}
{kpi("ETA, " + str(c["pending"] + c["running"]) + " waves left", dur(m["eta"]["recent"]), "at recent rate; at overall rate " + dur(m["eta"]["overall"]))}</div>
{prog}</section>

<section aria-labelledby="h-spend"><h2 id="h-spend">2. Spend</h2>
<div class="grid">{kpi("spent (ledger, settled)", usd(sp["spent"]), f'{sp["spent"] / sp["budget"] * 100:.1f}% of budget {usd(sp["budget"], 0)}' if sp["budget"] else "")}
{kpi("reserved (waves in flight)", usd(sp["reserved"]))}{kpi("per finished wave", usd(sp["per_wave"]), "all attempts incl. retries")}
{kpi("projected total", usd(pj.get("mid"), 0) if pj else "n/a", f'range {usd(pj["low"], 0)} to {usd(pj["high"], 0)}' if pj else "needs a finished wave", "bad" if over else "")}
{kpi("schedule estimate", usd(sp["sched_est_total"], 0), "before retries")}{kpi("actual / estimate so far", f'{pj["ratio"]:.2f}x' if pj else "n/a", "on finished waves")}</div>
{spend_svg(sp["series"], pj.get("mid") if pj else None, now)}
<p class="note">Projection = spent + reserved + (actual/estimate ratio of finished waves) x schedule estimate of pending waves ({usd(sp["est_pending"], 0)}); the range uses the middle half (25th to 75th percentile) of per-wave ratios.
Sessions costed from events so far: {sp["costed"]} of {sp["entries"]} finished; their measured cost {usd(sp["measured_norm"])} ({esc(m["basis"])}), provider-reported {usd(sp["measured_provider"])}.</p></section>

<section aria-labelledby="h-health"><h2 id="h-health">3. Health</h2>
<div class="grid">{kpi("failed attempts (retried)", len(h["failed_attempts"]), f'of {h["attempts_total"]} attempts')}{kpi("excluded waves", len(h["excluded"]), "", "bad" if h["excluded"] else "ok")}
{kpi("memory kills", len(h["kills"]), "", "warn" if h["kills"] else "ok")}{kpi("cache-audit flags", len(h["audit_flagged"]), f'of {h["audit_checked"]} costed sessions', "bad" if h["audit_flagged"] else "ok")}
{kpi("system free memory", "n/a" if h["free_gb"] is None else f'{h["free_gb"]:.0f} GB', f'campaign floor {h["floor_gb"]:.0f} GB' if h["floor_gb"] else "free + inactive", memcls)}
{kpi("Forge terminals", f'{forge["count"] if forge["count"] is not None else "n/a"} / {forge["max"] or "?"}', f'{forge["exited"]} exited' if forge["exited"] is not None else "", fcls)}</div>
{table("Excluded / config-error waves", ["Wave", "Status", "Reason"], exc)}
{table("Failed attempts (latest 12; an infrastructure failure retries the wave)", ["Wave", "Attempt", "Status", "Reason / failure kind per session"], fails)}
{table("Memory kills (latest 8)", ["Wave", "Arm", "Reason", "RSS GB"], kills)}
{("<p class=note>Cache-audit flagged: " + esc(", ".join(h["audit_flagged"][:8])) + "</p>") if h["audit_flagged"] else ""}
<h3 style="font-size:.95rem">Recent run.log lines matching error words</h3><pre>{esc(chr(10).join(h["log_errors"]) or "none")}</pre></section>

<section aria-labelledby="h-run"><h2 id="h-run">4. Running now</h2>
{table("Sessions of waves in flight (turn = current scripted turn / total turns)", ["Wave", "Arm", "Host", "Turn", "Elapsed", "State"], run_rows, (3, 4))}</section>

<section class="interim" aria-labelledby="h-int"><h2 id="h-int">5. Interim results: INTERIM, NOT CONFIRMATORY</h2>
<p class="note"><b>{esc(test_note)}</b> Based on finished valid TRAIN waves only; this is not the preregistered analysis. Cost basis: {esc(m["basis"])}.
Cost ratio below 1 means the arm was cheaper than the anchor in the same wave (geometric mean over pairs; the bracket is +/- 1 standard error). "$ saved" = anchor cost minus arm cost per session, so positive is cheaper.
The aa row is the noise floor: it is the same configuration as the anchor, so any distance from 1.00 there is chance.
Quality = share of scripted turns whose checks passed (arm vs anchor on the same pairs). The sonnet control is paired against each host's anchor, so it repeats under both hosts.</p>
{table("Per host and arm, versus the anchor of the same scenario/rep/host", ["Host", "Arm", "Pairs (n)", "Cost ratio vs anchor", "Mean $ saved / session", "Turn-pass: arm vs anchor"], ir, (2, 3, 4))}</section>
<p class="note">Read-only view of {esc(m["campaign"])}. Source: evals/paired_dashboard.py.</p>
</main><script>{JS % (int(now), STALE_S)}</script></body></html>"""


# ------------------------------------------------------------------------------------------------ commands

def atomic_write(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def default_paths(out: Path, html_arg=None):
    html_path = Path(html_arg).expanduser() if html_arg else out.parent / f"dashboard-{out.name}.html"
    return html_path, html_path.with_name(html_path.name + ".cache.json")


def build_once(out, html_path, cache_path, budget=None, show_test=False, json_path=None):
    m = collect(out, cache_path, budget, show_test)
    atomic_write(html_path, render(m))
    if json_path:
        atomic_write(Path(json_path), json.dumps(m, indent=1, default=str))
    return m


def cmd_build(a) -> int:
    out = Path(a.out).expanduser().resolve()
    html_path, cache_path = default_paths(out, a.html)
    m = build_once(out, html_path, cache_path, a.parse_budget_s, a.show_test, a.json)
    print(f"wrote {html_path} ({html_path.stat().st_size} bytes); waves done {m['counts']['done']}/{m['total_waves']}; "
          f"costed {m['spend']['costed']}/{m['spend']['entries']}")
    return 0


def cmd_serve(a) -> int:
    out = Path(a.out).expanduser().resolve()
    html_path, cache_path = default_paths(out, a.html)
    json_path = html_path.with_suffix(".json")

    def loop():
        while True:
            t0 = time.monotonic()
            try:
                build_once(out, html_path, cache_path, a.parse_budget_s, a.show_test, json_path)
            except Exception as exc:  # noqa: BLE001 -- keep serving the last good page; it will show as stale
                print(f"{datetime.now():%F %T} refresh failed: {exc!r}", file=sys.stderr, flush=True)
            time.sleep(max(a.interval - (time.monotonic() - t0), 1))

    if not html_path.exists():          # first request must not 404 while the first refresh runs
        atomic_write(html_path, "<!doctype html><meta http-equiv=refresh content=5><p>Dashboard is starting...</p>")
    threading.Thread(target=loop, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            p = self.path.split("?")[0]
            if p not in ("/", "/index.html", "/data.json"):
                self.send_error(404)
                return
            f, ctype = (json_path, "application/json") if p == "/data.json" else (html_path, "text/html; charset=utf-8")
            try:
                body = f.read_bytes()
            except OSError:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"serving http://127.0.0.1:{a.port}/ (refresh every {a.interval}s) for {out}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("build", cmd_build), ("serve", cmd_serve)):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True, help="campaign directory (read-only)")
        p.add_argument("--html", help="output HTML path (default: <campaign parent>/dashboard-<name>.html)")
        p.add_argument("--show-test", action="store_true", help="also show TEST-split interim results (breaks blinding)")
        p.set_defaults(fn=fn)
        if name == "build":
            p.add_argument("--json", help="also dump the numbers shown as JSON")
            p.add_argument("--parse-budget-s", type=float, default=None, help="max seconds spent parsing events (default: no limit)")
        else:
            p.add_argument("--port", type=int, default=8790)
            p.add_argument("--interval", type=float, default=60.0)
            p.add_argument("--parse-budget-s", type=float, default=1.2, help="max seconds of event parsing per refresh")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
