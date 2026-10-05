"""Read-only caching survey for fast-decisions model routing.

Question: does switching models mid-session (turn-start routing, mid-turn escalation)
throw away the provider prompt cache so that the cheaper model's savings shrink or vanish
for longer sessions?  Measured from existing runs only: no model calls, no edits outside
this directory.

Sources (read-only):
  S1 / s1m   ~/dev/afast-ev/<campaign>/experiments/<exp>/runs/*/<run>/result.json
  S3 routing ~/dev/afast-orch-primary-20260924/swe-*/runs/<inst>__<arm>__rN/result.json
  S3 v4      ~/.amplifier/fast-decisions/studies/swebench-complete-20260928/verified-v4/runs/...
  sessions   ~/.amplifier/projects/<encoded workspace>/sessions/<uuid>/events.jsonl

Usage:  python3 caching_survey.py [--workers 8] [--boot 5000]
Writes: results.json, pairs.csv, sessions.csv next to this script.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import random
import re
import statistics
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

HOME = os.path.expanduser("~")
OUT = os.path.dirname(os.path.abspath(__file__))
S1_ROOT = f"{HOME}/dev/afast-ev"
S3R_ROOT = f"{HOME}/dev/afast-orch-primary-20260924"
S3V4_ROOT = f"{HOME}/.amplifier/fast-decisions/studies/swebench-complete-20260928/verified-v4"
PROJECTS = f"{HOME}/.amplifier/projects"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# ---------------------------------------------------------------- cell taxonomy
ROUTING_PRODUCT = re.compile(
    r"^(orch-default(-opus)?|orch-router-(rules|jev|local)|orch-planner-.*|orch-sonnetlow-opus|"
    r"orch-haiku-opus|orch-haiku-low-opus|orch-haiku-fable)$")
ROUTING_SHAPED = re.compile(r"^(orch-haiku-shaped-.*|orch-haiku-guided-opus|orch-sonnet-shaped-opus)$")
EFFORT_ONLY = re.compile(r"^(orch-primary-effort-only|orch-fablelow|orch-opuslow-opus|orch-strong-phase-effort)$")
MIDTURN_ESC = re.compile(r"^orch-primary$")
ANCHORS = {"plain", "plain-opus", "plain-matched"}


def cell_kind(cell: str) -> str:
    if cell in ANCHORS:
        return "anchor"
    if cell == "plain-sonnet":
        return "model_swap_control"
    if MIDTURN_ESC.match(cell):
        return "midturn_escalation"
    if ROUTING_PRODUCT.match(cell):
        return "routing"
    if ROUTING_SHAPED.match(cell):
        return "routing_plus_shaping"
    if EFFORT_ONLY.match(cell):
        return "effort_only"
    if cell in {"jev-prepared", "laya-prepared", "jevgrep"}:
        return "prepared_or_retrieval_same_model"
    return "other"


def s1_anchor(cell: str) -> str:
    return "plain-opus" if "opus" in cell else "plain"


# ---------------------------------------------------------------- session index
def index_sessions():
    by_id, by_proj = {}, defaultdict(list)
    for proj in os.scandir(PROJECTS):
        sd = os.path.join(proj.path, "sessions")
        if not os.path.isdir(sd):
            continue
        for s in os.scandir(sd):
            if s.is_dir():
                by_id[s.name] = s.path
                by_proj[proj.name].append(s.path)
    return by_id, by_proj


def resolve_session(run_dir, result, by_id, by_proj):
    """Return (session_dir, how)."""
    sid = result.get("session_id")
    if sid and sid in by_id:
        return by_id[sid], "result.session_id"
    mpath = os.path.join(run_dir, "measurements.json")
    if os.path.exists(mpath):
        try:
            sid = json.load(open(mpath))["scope"]["session_id"]
            if sid in by_id:
                return by_id[sid], "measurements.scope"
        except Exception:
            pass
    evd = os.path.join(run_dir, "events")
    if os.path.isdir(evd):
        for n in sorted(os.listdir(evd)):
            m = UUID.match(n)
            if m and m.group(0) in by_id:
                return by_id[m.group(0)], "run_events_filename"
    ws = os.path.join(run_dir, "workspace")
    cands = sorted(set(by_proj.get(ws.replace("/", "-"), []) + by_proj.get(ws.replace("/", "-").replace(".", "-"), [])))
    if len(cands) == 1:
        return cands[0], "workspace_project_dir"
    if cands:
        best = max(cands, key=lambda p: os.path.getsize(os.path.join(p, "events.jsonl"))
                   if os.path.exists(os.path.join(p, "events.jsonl")) else 0)
        return best, f"workspace_project_dir_largest_of_{len(cands)}"
    return None, "unresolved"


# ---------------------------------------------------------------- run discovery
def discover_s1(by_id, by_proj):
    runs = []
    for f in glob.glob(f"{S1_ROOT}/*/experiments/*/runs/*/*/result.json"):
        parts = f.split("/")
        camp = parts[parts.index("afast-ev") + 1]
        exp = parts[parts.index("experiments") + 1]
        run_dir = os.path.dirname(f)
        try:
            r = json.load(open(f))
        except Exception:
            continue
        m = re.match(r"(.+)-(s1m|s1)-(.+)-r(\d+)$", exp)
        if not m:
            continue
        cell, rep = m.group(1), int(m.group(4))
        sdir, how = resolve_session(run_dir, r, by_id, by_proj)
        runs.append(dict(
            family="S1-multi" if m.group(2) == "s1m" else "S1-single", campaign=camp, cell=cell,
            kind=cell_kind(cell), task=r.get("task"), rep=rep, attempt=r.get("attempt") or 1,
            infra=bool(r.get("infrastructure_failure")), passed=r.get("outcome_passed"),
            exec_ms=r.get("exec_time_ms"), wall_ms=r.get("wall_time_ms"),
            result_cost=r.get("cost_usd"), nturns_declared=len(r.get("turns") or []), run_dir=run_dir,
            session_dir=sdir, session_how=how, host="opus" if "opus" in cell else "fable"))
    # keep the counted attempt: latest non-infra attempt per (campaign, cell, task, rep)
    best = {}
    for x in runs:
        k = (x["campaign"], x["cell"], x["task"], x["rep"])
        cur = best.get(k)
        if cur is None or (cur["infra"] and not x["infra"]) or (
                x["attempt"] > cur["attempt"] and not x["infra"]):
            best[k] = x
    return list(best.values()), len(runs)


def load_swe_grading(root):
    resolved = {}
    for f in glob.glob(f"{root}/grading/*.json"):
        m = re.match(r"(.+)\.(.+)-r(\d+)\.json$", os.path.basename(f))
        if not m:
            continue
        try:
            g = json.load(open(f))
        except Exception:
            continue
        arm, rep = m.group(1), int(m.group(3))
        res = set(g.get("resolved_ids") or [])
        for i in g.get("submitted_ids") or g.get("completed_ids") or []:
            resolved[(arm, i, rep)] = i in res
    return resolved


def discover_s3(by_id, by_proj):
    runs = []
    for camp_dir in sorted(glob.glob(f"{S3R_ROOT}/swe-*")):
        if not os.path.isdir(camp_dir) or camp_dir.endswith("v1-invalid"):
            continue
        camp = os.path.basename(camp_dir)
        grade = load_swe_grading(camp_dir)
        for f in glob.glob(f"{camp_dir}/runs/*/result.json"):
            r = json.load(open(f))
            run_dir = os.path.dirname(f)
            arm, rep, inst = r["arm"], r["rep"], r["instance_id"]
            sdir, how = resolve_session(run_dir, r, by_id, by_proj)
            runs.append(dict(
                family="S3-routing", campaign=camp, cell=arm, kind=cell_kind(arm), task=inst, rep=rep,
                attempt=1, infra=bool(r.get("infrastructure_failure")), passed=grade.get((arm, inst, rep)),
                exec_ms=r.get("exec_time_ms"), wall_ms=r.get("wall_time_ms"), result_cost=r.get("cost_usd"),
                nturns_declared=1, run_dir=run_dir, session_dir=sdir, session_how=how, host="fable"))
    # v4: same model everywhere (claude-sonnet-5); prepared-action receipts live here
    rep_v4 = json.load(open(f"{S3V4_ROOT}/report.json"))["per_instance"]
    for f in glob.glob(f"{S3V4_ROOT}/runs/*/result.json"):
        r = json.load(open(f))
        run_dir = os.path.dirname(f)
        arm, rep, inst = r["arm"], r["rep"], r["instance_id"]
        pi = (rep_v4.get(f"{inst} r{rep}") or {}).get(arm) or {}
        sdir, how = resolve_session(run_dir, r, by_id, by_proj)
        cost = r.get("cost_usd")
        if cost is None:
            cost = r.get("provider_cost_usd")
        runs.append(dict(
            family="S3-v4-same-model", campaign="swebench-complete-v4", cell=arm, kind=cell_kind(arm),
            task=inst, rep=rep, attempt=1, infra=bool(r.get("infrastructure_failure")),
            passed=pi.get("resolved"), exec_ms=r.get("exec_time_ms"), wall_ms=r.get("wall_time_ms"),
            result_cost=cost, nturns_declared=1, run_dir=run_dir, session_dir=sdir,
            session_how=how, host="sonnet"))
    return runs


# ---------------------------------------------------------------- session parsing
KEEP = ('"llm:request"', '"llm:response"', '"prompt:submit"', '"fast_decisions:turn_planned"',
        '"fast_decisions:efficiency"')


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_session(session_dir):
    """Small per-response records; never returns message bodies."""
    path = os.path.join(session_dir, "events.jsonl")
    out = dict(session_dir=session_dir, responses=[], plans=[], efficiency=[], turns=0, error=None)
    if not os.path.exists(path):
        out["error"] = "no events.jsonl"
        return out
    pending = defaultdict(list)  # model -> FIFO of request meta
    turn = 0
    seen_eff = set()
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                if not any(k in line for k in KEEP):
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                e = ev.get("event")
                d = ev.get("data") or {}
                if isinstance(d.get("data"), dict) and "event" in d:  # fast_decisions receipts are nested
                    d = d["data"]
                if e == "prompt:submit":
                    turn += 1
                elif e == "llm:request":
                    raw = d.get("raw") if isinstance(d.get("raw"), dict) else {}
                    oc = raw.get("output_config")
                    pending[d.get("model")].append(dict(
                        main=bool(d.get("has_system")) and "tools" in raw,
                        thinking=(d.get("thinking_enabled"), d.get("thinking_budget")),
                        effort=oc.get("effort") if isinstance(oc, dict) else None))
                elif e == "llm:response":
                    u = d.get("usage") or {}
                    model = d.get("model")
                    req = pending[model].pop(0) if pending[model] else dict(main=True, thinking=(None, None), effort=None)
                    inp, rd, wr = _num(u.get("input_tokens")), _num(u.get("cache_read_tokens")), _num(u.get("cache_write_tokens"))
                    out["responses"].append(dict(
                        ts=ev.get("ts") or ev.get("timestamp"), model=model, turn=max(turn, 1), main=req["main"],
                        thinking=list(req["thinking"]), effort=req["effort"],
                        # provider convention (verified by the price fit): input_tokens includes cache reads,
                        # excludes cache writes
                        uncached=max(inp - rd, 0.0), read=rd, write=wr, output=_num(u.get("output_tokens")),
                        cost=_num(u.get("cost_usd")), has_cost=u.get("cost_usd") is not None))
                elif e == "fast_decisions:turn_planned":
                    out["plans"].append(dict(turn=turn, choice=d.get("choice"), host=d.get("host_model"),
                                             objective=d.get("objective"),
                                             options=[{k: o.get(k) for k in ("model", "cost", "lookahead_cost", "warm", "cold")}
                                                      for o in d.get("options") or []]))
                elif e == "fast_decisions:efficiency":
                    eid = ev.get("event_id")
                    if eid in seen_eff:
                        continue
                    seen_eff.add(eid)
                    out["efficiency"].append(dict(event_id=eid, lever=d.get("lever"), decision=d.get("decision"),
                                                  usd_saved=_num(d.get("usd_saved")),
                                                  seconds_saved=_num(d.get("seconds_saved"))))
    except Exception as exc:  # pragma: no cover
        out["error"] = repr(exc)
    out["turns"] = turn
    return out


def parse_run_efficiency(run_dir):
    """fast_decisions:efficiency receipts from the per-run events dir (deduped by event_id)."""
    seen, rows = set(), []
    for f in glob.glob(os.path.join(run_dir, "events", "*.jsonl")):
        with open(f, errors="replace") as fh:
            for line in fh:
                if "fast_decisions:efficiency" not in line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") != "fast_decisions:efficiency" or ev.get("event_id") in seen:
                    continue
                seen.add(ev.get("event_id"))
                d = ev.get("data") or {}
                rows.append(dict(event_id=ev.get("event_id"), lever=d.get("lever"), decision=d.get("decision"), usd_saved=_num(d.get("usd_saved")),
                                 seconds_saved=_num(d.get("seconds_saved"))))
    return rows


# ---------------------------------------------------------------- price inference
def infer_prices(sessions):
    """Least-squares per-model $/token for (uncached, read, write, output) from provider cost_usd."""
    import numpy as np
    by_model = defaultdict(list)
    for s in sessions:
        for r in s["responses"]:
            if r["has_cost"]:
                by_model[r["model"]].append((r["uncached"], r["read"], r["write"], r["output"], r["cost"]))
    prices = {}
    for m, rows in by_model.items():
        if len(rows) < 8:
            continue
        a = np.array([x[:4] for x in rows], dtype=float)
        y = np.array([x[4] for x in rows], dtype=float)
        coef, *_ = np.linalg.lstsq(a, y, rcond=None)
        pred = a @ coef
        prices[m] = dict(n=len(rows), usd_per_mtok=dict(zip(("uncached", "read", "write", "output"),
                                                            [round(float(c) * 1e6, 4) for c in coef])),
                         max_abs_resid_usd=float(np.max(np.abs(pred - y))),
                         total_rel_err=float(abs(pred.sum() - y.sum()) / max(y.sum(), 1e-9)))
    return prices


# ---------------------------------------------------------------- session metrics
def session_metrics(s, prices):
    main = [r for r in s["responses"] if r["main"]]
    allr = s["responses"]
    tok = lambda k, rs: sum(r[k] for r in rs)
    prompt = lambda r: r["uncached"] + r["read"] + r["write"]
    denom = tok("uncached", main) + tok("read", main) + tok("write", main)
    m = dict(
        n_req=len(main), n_bg=len(allr) - len(main), turns=s["turns"],
        cost_total=tok("cost", allr), cost_main=tok("cost", main),
        uncached=tok("uncached", main), read=tok("read", main), write=tok("write", main), output=tok("output", main),
        cache_hit_share=(tok("read", main) / denom) if denom else None,
        models=sorted({r["model"] for r in main}),
        first_req_read=main[0]["read"] if main else None,
        first_req_write=main[0]["write"] if main else None,
    )
    sw = cfg = 0
    switch_idx = []
    rb_write = rb_excess = rb_usd = rb_usd_full = 0.0
    cfg_excess = cfg_usd = 0.0
    turn_boundary_sw = midturn_sw = 0
    write_usd = 0.0
    noswitch_excess_usd = 0.0  # noise floor: excess writes on requests with no model/config change
    comp = defaultdict(float)  # cost by token class, priced with the inferred per-model prices
    for r in allr:
        pr = prices.get(r["model"], {}).get("usd_per_mtok")
        if pr:
            for k in ("uncached", "read", "write", "output"):
                comp[k] += r[k] * pr[k] / 1e6
    per_turn_cost = defaultdict(float)
    per_turn_rebuild = defaultdict(float)
    per_turn_switch = defaultdict(int)
    for r in allr:
        per_turn_cost[r["turn"]] += r["cost"]
    for i, r in enumerate(main):
        p = prices.get(r["model"], {}).get("usd_per_mtok")
        if p:
            write_usd += r["write"] * p["write"] / 1e6
        if i == 0:
            continue
        prev = main[i - 1]
        expected_new = max(prompt(r) - prompt(prev), 0.0)
        excess = max(r["write"] - expected_new, 0.0)
        if r["model"] != prev["model"]:
            switch_idx.append(i + 1)  # 1-based main-loop request index of the first request on the new model
            sw += 1
            if r["turn"] != prev["turn"]:
                turn_boundary_sw += 1
            else:
                midturn_sw += 1
            rb_write += r["write"]
            rb_excess += excess
            per_turn_switch[r["turn"]] += 1
            if p:
                rb_usd += excess * (p["write"] - p["read"]) / 1e6
                per_turn_rebuild[r["turn"]] += excess * (p["write"] - p["read"]) / 1e6
                rb_usd_full += r["write"] * p["write"] / 1e6
        elif (r["thinking"], r["effort"]) != (prev["thinking"], prev["effort"]):
            cfg += 1
            cfg_excess += excess
            if p:
                cfg_usd += excess * (p["write"] - p["read"]) / 1e6
        elif p:
            noswitch_excess_usd += excess * (p["write"] - p["read"]) / 1e6
    m.update(model_switches=sw, switches_turn_boundary=turn_boundary_sw, switches_midturn=midturn_sw,
             config_switches_same_model=cfg, rebuild_write_tokens=rb_write, rebuild_excess_write_tokens=rb_excess,
             rebuild_usd=rb_usd, rebuild_usd_full_write=rb_usd_full,
             config_switch_excess_write_tokens=cfg_excess, config_switch_usd=cfg_usd,
             cache_write_usd=write_usd, noswitch_excess_usd=noswitch_excess_usd,
             first_switch_req_index=switch_idx[0] if switch_idx else None,
             first_model=main[0]["model"] if main else None,
             **warmth_normalised(main, prices, tok("cost", allr)),
             cost_uncached=comp["uncached"], cost_read=comp["read"], cost_write=comp["write"], cost_output=comp["output"],
             per_turn_cost=dict(per_turn_cost),
             per_turn_rebuild=dict(per_turn_rebuild), per_turn_switch=dict(per_turn_switch))
    return m


def warmth_normalised(main, prices, cost_total):
    """Remove the cross-session cache-warmth difference on the session's first request.

    cold: the first request's cache reads re-priced as writes (nothing warmed by other runs).
    warm: computed later in apply_warm_prefix() -- the warmable prefix (median first-request cache
    read of warm sessions in the same campaign, cell and model) re-priced from write to read.
    Applied to both arms of a pair, the two give a range for the ratio.
    """
    if not main or main[0]["model"] not in prices:
        return dict(cost_cold=None, warm_delta_per_token=None)
    pr = prices[main[0]["model"]]["usd_per_mtok"]
    d = (pr["write"] - pr["read"]) / 1e6
    return dict(cost_cold=cost_total + main[0]["read"] * d, warm_delta_per_token=d)


def apply_warm_prefix(runs):
    """Second pass: warm-normalised cost needs the warmable prefix size estimated across sessions."""
    groups, fallback = defaultdict(list), defaultdict(list)
    for r in runs:
        if r.get("session_ok") and (r.get("first_req_read") or 0) > 0:
            groups[(r["campaign"], r["cell"], r["first_model"])].append(r["first_req_read"])
            fallback[(r["family"], r["cell"], r["first_model"])].append(r["first_req_read"])
    for r in runs:
        if not r.get("session_ok") or r.get("warm_delta_per_token") is None:
            continue
        v = groups.get((r["campaign"], r["cell"], r["first_model"])) or fallback.get((r["family"], r["cell"], r["first_model"]))
        prefix = statistics.median(v) if v else 0.0
        movable = min(r["first_req_write"] or 0.0, max(0.0, prefix - (r["first_req_read"] or 0.0)))
        r["warm_prefix_tokens"] = prefix
        r["cost_warm"] = r["cost_total"] - movable * r["warm_delta_per_token"]


def reprice(tokens, model, prices):
    pr = prices.get(model, {}).get("usd_per_mtok")
    if not pr:
        return None
    return sum(tokens[k] * pr[k] / 1e6 for k in ("uncached", "read", "write", "output"))


# ---------------------------------------------------------------- stats
def gmean(xs):
    return math.exp(statistics.fmean(math.log(x) for x in xs))


def cluster_boot(pairs, stat, nboot, seed=7):
    """Resample tasks (clusters) with replacement; pairs within a task stay together."""
    by = defaultdict(list)
    for p in pairs:
        by[(p["family"], p["task"])].append(p)
    keys = list(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(nboot):
        sample = [q for _k in range(len(keys)) for q in by[keys[rng.randrange(len(keys))]]]
        try:
            vals.append(stat(sample))
        except (ValueError, ZeroDivisionError, statistics.StatisticsError):
            pass
    vals.sort()
    if not vals:
        return None
    return [vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]]


def summarize(pairs, nboot, key="cost_ratio"):
    ps = [p for p in pairs if p.get(key) and p[key] > 0]
    if not ps:
        return dict(n_pairs=0)
    st = lambda s: gmean([p[key] for p in s])
    return dict(n_pairs=len(ps), n_tasks=len({(p["family"], p["task"]) for p in ps}),
                geomean=round(st(ps), 4), ci95=[round(v, 4) for v in (cluster_boot(ps, st, nboot) or [])])


def slope(pairs, xkey, ykey):
    xs = [math.log(p[xkey]) for p in pairs]
    ys = [math.log(p[ykey]) for p in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def pooled_ratio(num, den):
    return round(num / den, 4) if den else None


def corrections_section(runs, ok, routed, pairs, prices, nboot):
    out = {}
    # 1. price x volume: plain-sonnet vs plain-opus (single model each arm), 1-turn vs 4-turn
    pv = {}
    for fam in ("S1-single", "S1-multi"):
        ps = [p for p in ok if p["family"] == fam and p["cell"] == "plain-sonnet" and p["anchor"] == "plain-opus"
              and p["treat_model"] == "claude-sonnet-5" and p["anchor_model"] == "claude-opus-5-5"]
        if not ps:
            continue
        for p in ps:
            toks = dict(uncached=p["anchor_tok_uncached"], read=p["anchor_tok_read"], write=p["anchor_tok_write"],
                        output=p["anchor_tok_output"])
            a = reprice(toks, "claude-opus-5-5", prices)
            t = reprice(toks, "claude-sonnet-5", prices)
            p["price_factor"] = t / a if a else None
            p["volume_factor"] = p["cost_ratio"] / p["price_factor"] if p.get("price_factor") else None
        cls = {}
        for k in ("uncached", "read", "write", "output"):
            tot = sum(p[f"anchor_tok_{k}"] for p in ps)
            ra = prices["claude-opus-5-5"]["usd_per_mtok"][k]
            rs = prices["claude-sonnet-5"]["usd_per_mtok"][k]
            cls[k] = dict(sonnet_over_opus_price=round(rs / ra, 4),
                          share_of_opus_cost_on_anchor_tokens=round(tot * ra / 1e6, 4))
        a_tot = sum(v["share_of_opus_cost_on_anchor_tokens"] for v in cls.values())
        for v in cls.values():
            v["share_of_opus_cost_on_anchor_tokens"] = round(v["share_of_opus_cost_on_anchor_tokens"] / a_tot, 4)
        pooled_toks = {k: sum(p[f"anchor_tok_{k}"] for p in ps) for k in ("uncached", "read", "write", "output")}
        pv[fam] = dict(
            pairs=len(ps), tasks=len({p["task"] for p in ps}),
            cost_ratio=summarize(ps, nboot),
            price_factor_identical_tokens_pooled=pooled_ratio(reprice(pooled_toks, "claude-sonnet-5", prices),
                                                              reprice(pooled_toks, "claude-opus-5-5", prices)),
            price_factor_identical_tokens_geomean=summarize(ps, nboot, "price_factor"),
            volume_factor_geomean=summarize(ps, nboot, "volume_factor"),
            requests_ratio_pooled=pooled_ratio(sum(p["n_req_treat"] for p in ps), sum(p["n_req_anchor"] for p in ps)),
            requests_ratio_geomean=summarize(ps, nboot, "req_ratio"),
            cache_read_tokens_ratio_pooled=pooled_ratio(sum(p["treat_tok_read"] for p in ps), sum(p["anchor_tok_read"] for p in ps)),
            cache_read_tokens_ratio_geomean=summarize(ps, nboot, "read_ratio"),
            per_class=cls)
    if "S1-single" in pv and "S1-multi" in pv:
        g = lambda fam, k: pv[fam][k]["geomean"]
        d_cost = math.log(g("S1-multi", "cost_ratio") / g("S1-single", "cost_ratio"))
        d_price = math.log(g("S1-multi", "price_factor_identical_tokens_geomean") / g("S1-single", "price_factor_identical_tokens_geomean"))
        d_vol = math.log(g("S1-multi", "volume_factor_geomean") / g("S1-single", "volume_factor_geomean"))
        pv["change_1turn_to_4turn"] = dict(
            log_cost_change=round(d_cost, 4), log_price_change=round(d_price, 4), log_volume_change=round(d_vol, 4),
            price_share=round(d_price / d_cost, 3), volume_share=round(d_vol / d_cost, 3),
            note="log(cost ratio) = log(price factor on identical anchor tokens) + log(volume/mix factor); "
                 "shares split the 1-turn -> 4-turn change in the plain-sonnet/plain-opus geomean")
    out["price_volume_plain_sonnet_vs_plain_opus"] = pv

    # 2. same-cell length contrast (the pooled 1-turn vs 4-turn contrast is a suite contrast)
    sc = {}
    for cell, anchor in (("orch-default-opus", "plain-opus"), ("orch-default", "plain"),
                         ("plain-sonnet", "plain-opus"), ("plain-sonnet", "plain")):
        row = {}
        for fam in ("S1-single", "S1-multi"):
            ps = [p for p in ok if p["family"] == fam and p["cell"] == cell and p["anchor"] == anchor]
            row[fam] = dict(cost=summarize(ps, nboot), time=summarize(ps, nboot, "time_ratio"),
                            tasks=sorted({p["task"] for p in ps}) if fam == "S1-multi" else len({p["task"] for p in ps}))
        sc[f"{cell} vs {anchor}"] = row
    pools = {}
    for fam in ("S1-single", "S1-multi"):
        for host in ("fable", "opus"):
            ps = [p for p in routed if p["family"] == fam and p["host"] == host]
            c = defaultdict(int)
            for p in ps:
                c[p["cell"]] += 1
            pools[f"{fam}|{host}"] = dict(sorted(c.items()))
    out["same_cell_length_contrast"] = dict(cells=sc, routed_pool_composition=pools,
                                            note="1-turn (S1) and 4-turn (s1m) are different task suites; "
                                                 "Haiku-routed cells appear only in the 1-turn pool")

    # 3. planner per scenario
    pl = {}
    for cell, anchor in (("orch-planner-opus", "plain-opus"), ("orch-planner-value-opus", "plain-opus"),
                         ("orch-planner-v12-opus", "plain-opus"), ("orch-planner-fable", "plain"),
                         ("orch-planner-v12-fable", "plain"), ("orch-planner-value-fable", "plain")):
        ps = [p for p in ok if p["family"] == "S1-multi" and p["cell"] == cell and p["anchor"] == anchor]
        by = defaultdict(list)
        for p in ps:
            by[p["task"]].append(p)
        pl[f"{cell} vs {anchor}"] = dict(
            pairs=len(ps), scenarios=len(by),
            total_measured_saving_usd=round(sum(p["measured_saving_usd"] for p in ps), 4),
            total_planner_predicted_saving_usd=round(sum(p["planned_saving_usd"] or 0 for p in ps), 4),
            per_scenario={t: dict(pairs=len(v), measured_saving_usd=round(sum(p["measured_saving_usd"] for p in v), 4),
                                  predicted_saving_usd=round(sum(p["planned_saving_usd"] or 0 for p in v), 4))
                          for t, v in sorted(by.items())},
            scenarios_negative=sum(1 for v in by.values() if sum(p["measured_saving_usd"] for p in v) < 0))
    out["planner_per_scenario"] = pl

    # 4. first-request cache warmth imbalance
    wm = {}
    for label, sel in (
            ("S1-multi routed opus host", [p for p in routed if p["family"] == "S1-multi" and p["host"] == "opus"]),
            ("S1-multi routed fable host", [p for p in routed if p["family"] == "S1-multi" and p["host"] == "fable"]),
            ("S1-multi plain-sonnet vs plain-opus", [p for p in ok if p["family"] == "S1-multi" and p["cell"] == "plain-sonnet" and p["anchor"] == "plain-opus"]),
            ("S1-multi plain-sonnet vs plain", [p for p in ok if p["family"] == "S1-multi" and p["cell"] == "plain-sonnet" and p["anchor"] == "plain"]),
            ("S1-single routed opus host", [p for p in routed if p["family"] == "S1-single" and p["host"] == "opus"]),
            ("S1-single routed fable host", [p for p in routed if p["family"] == "S1-single" and p["host"] == "fable"]),
            ("S3 routed", [p for p in routed if p["family"] == "S3-routing"])):
        if not sel:
            continue
        raw, cold, warm = (summarize(sel, nboot, k) for k in ("cost_ratio", "cold_ratio", "warm_ratio"))
        wm[label] = dict(
            raw=raw, both_cold=cold, both_warm=warm,
            normalised_range=sorted([cold.get("geomean"), warm.get("geomean")]),
            treat_first_request_warm_share=round(statistics.fmean(p["treat_first_warm"] for p in sel), 3),
            anchor_first_request_warm_share=round(statistics.fmean(p["anchor_first_warm"] for p in sel), 3))
    out["first_request_warmth"] = dict(
        groups=wm, method="cold: each session's first request has its cache reads re-priced as writes; warm: the "
                          "warmable prefix (median first-request cache read among warm sessions of the same campaign, "
                          "cell and model) is re-priced from write to read where it was written; applied to both arms")

    # 5. scenario origin (dev tuning set vs holdout) in the 4-turn pools
    so = {}
    for host in ("fable", "opus"):
        ps = [p for p in routed if p["family"] == "S1-multi" and p["host"] == host]
        so[host] = dict(pairs=len(ps), dev_scenarios=sum(p["task"].startswith("scn_dev") for p in ps),
                        holdout_scenarios=sum(not p["task"].startswith("scn_dev") for p in ps),
                        scenarios=sorted({p["task"] for p in ps}),
                        campaigns=sorted({p["campaign"] for p in ps}))
    dev_camps = sorted({p["campaign"] for p in ok if p["family"] == "S1-multi" and p["task"].startswith("scn_dev")})
    so["dev_scenario_campaigns"] = dict(n=len(dev_camps), campaigns=dev_camps)
    out["multiturn_scenario_origin"] = so

    # 6. rebuild share per stratum; anchor reuse
    strata = {
        "S1 single-turn routed": [p for p in routed if p["family"] == "S1-single"],
        "S1 4-turn routed, Opus host": [p for p in routed if p["family"] == "S1-multi" and p["host"] == "opus"],
        "S1 4-turn routed, Fable host": [p for p in routed if p["family"] == "S1-multi" and p["host"] == "fable"],
        "S3 orch-primary (mid-turn escalation)": [p for p in routed if p["family"] == "S3-routing" and p["cell"] == "orch-primary"],
        "S3 turn-start routers (jev, local, rules)": [p for p in routed if p["family"] == "S3-routing" and p["cell"] != "orch-primary"],
    }
    rs = {}
    for k, ps in strata.items():
        tc = sum(p["cost_treat"] for p in ps)
        rb_ = sum(p["rebuild_usd"] for p in ps)
        cf = sum(p["config_switch_usd"] for p in ps)
        rs[k] = dict(pairs=len(ps), sessions_with_switch=sum(p["switches"] > 0 for p in ps),
                     routed_cost_usd=round(tc, 4), rebuild_usd=round(rb_, 4), effort_change_usd=round(cf, 4),
                     rebuild_share=round(rb_ / tc, 4) if tc else None,
                     rebuild_plus_effort_share=round((rb_ + cf) / tc, 4) if tc else None)
    uniq = {(p["family"], p["campaign"], p["anchor"], p["task"], p["rep"]) for p in routed}
    out["rebuild_by_stratum"] = dict(strata=rs, routed_pairs=len(routed), unique_anchor_runs=len(uniq),
                                     note="several routed cells share one anchor run, so pooled anchor cost double-counts")

    # 7. mid-turn switches by cell, and where they happen
    mt = defaultdict(lambda: dict(sessions=0, midturn_switches=0, first_switch_req_index=defaultdict(int),
                                  first_model=defaultdict(int)))
    for p in routed:
        if p["switches_midturn"]:
            e = mt[f'{p["family"]}|{p["cell"]}']
            e["sessions"] += 1
            e["midturn_switches"] += p["switches_midturn"]
            e["first_switch_req_index"][p["first_switch_req_index"]] += 1
            e["first_model"][p["treat_first_model"]] += 1
    out["midturn_switches_by_cell"] = {k: dict(v, first_switch_req_index=dict(v["first_switch_req_index"]),
                                               first_model=dict(v["first_model"])) for k, v in sorted(mt.items())}
    out["cost_source"] = ("cost_usd is the provider adapter's price-table estimate per response (it fits list prices "
                          "exactly); it is not billing")
    return out


def corr(xs, ys):
    if len(xs) < 3 or statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
        return None
    return round(statistics.correlation(xs, ys), 4)


def planner_saving(plans):
    """Planner's own predicted saving: host option minus chosen option (cost + lookahead)."""
    if not plans:
        return None
    tot = 0.0
    for pl in plans:
        opts = {o["model"]: (o.get("cost") or 0) + (o.get("lookahead_cost") or 0) for o in pl["options"]}
        if pl.get("host") in opts and pl.get("choice") in opts:
            tot += opts[pl["host"]] - opts[pl["choice"]]
    return tot


def tilde(text):
    """Replace the home-directory prefix with ~ so outputs carry no user name."""
    # session dirs embed the workspace path encoded with "-" (e.g. "-<home>-dev-..."); redact that too
    return (text.replace(HOME + "/", "~/").replace(HOME, "~")
            .replace(HOME.replace("/", "-") + "-", "-~-"))


def write_csv(path, rows):
    if not rows:
        return
    rows = [{k: tilde(v) if isinstance(v, str) else v for k, v in r.items()} for r in rows]
    keys = sorted({k for r in rows for k in r})
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def terciles(ps, key):
    xs = sorted(p[key] for p in ps)
    if len(xs) < 6:
        return None
    return xs[len(xs) // 3], xs[2 * len(xs) // 3]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--boot", type=int, default=3000)
    args = ap.parse_args()

    by_id, by_proj = index_sessions()
    s1, s1_raw_n = discover_s1(by_id, by_proj)
    s3 = discover_s3(by_id, by_proj)
    runs = s1 + s3
    todo = sorted({r["session_dir"] for r in runs if r["session_dir"]})
    with ProcessPoolExecutor(args.workers) as ex:
        parsed = dict(zip(todo, ex.map(parse_session, todo, chunksize=4)))
    prices = infer_prices(parsed.values())
    for r in runs:
        s = parsed.get(r["session_dir"])
        r["session_ok"] = bool(s and s["responses"] and not s["error"])
        if r["session_ok"]:
            r.update(session_metrics(s, prices))
            r["plans"] = s["plans"]
            eff = list({e["event_id"]: e for e in s["efficiency"] + parse_run_efficiency(r["run_dir"])}.values())
            r["efficiency_n"] = len(eff)
            r["efficiency_usd_saved"] = sum(e["usd_saved"] for e in eff)
            r["efficiency_seconds_saved"] = sum(e["seconds_saved"] for e in eff)
            r["cost_vs_result_rel"] = (abs(r["cost_total"] - r["result_cost"]) / r["result_cost"]
                                       if r.get("result_cost") else None)

    apply_warm_prefix(runs)
    idx = {(r["family"], r["campaign"], r["cell"], r["task"], r["rep"]): r for r in runs}
    pairs = []
    for r in runs:
        if r["kind"] == "anchor":
            continue
        if r["family"].startswith("S1"):
            anchors = [s1_anchor(r["cell"])] if r["cell"] != "plain-sonnet" else ["plain", "plain-opus"]
        elif r["family"] == "S3-routing":
            anchors = ["plain"]
        else:
            anchors = ["plain-matched"]
        for a in anchors:
            b = idx.get((r["family"], r["campaign"], a, r["task"], r["rep"]))
            if not b:
                continue
            ok = r.get("session_ok") and b.get("session_ok")
            p = dict(family=r["family"], campaign=r["campaign"], task=r["task"], rep=r["rep"], cell=r["cell"],
                     anchor=a, kind=r["kind"], host="opus" if a == "plain-opus" else r["host"],
                     treat_passed=r["passed"], anchor_passed=b["passed"], sessions_ok=bool(ok),
                     treat_infra=r["infra"], anchor_infra=b["infra"])
            if ok:
                p.update(
                    cost_treat=r["cost_total"], cost_anchor=b["cost_total"],
                    cost_ratio=r["cost_total"] / b["cost_total"] if b["cost_total"] else None,
                    result_cost_ratio=(r["result_cost"] / b["result_cost"]) if r.get("result_cost") and b.get("result_cost") else None,
                    time_ratio=(r["exec_ms"] / b["exec_ms"]) if r.get("exec_ms") and b.get("exec_ms") else None,
                    n_req_anchor=b["n_req"], n_req_treat=r["n_req"], turns=b["turns"],
                    switches=r["model_switches"], switches_turn_boundary=r["switches_turn_boundary"],
                    switches_midturn=r["switches_midturn"], cfg_switches=r["config_switches_same_model"],
                    rebuild_usd=r["rebuild_usd"], rebuild_usd_full_write=r["rebuild_usd_full_write"],
                    config_switch_usd=r["config_switch_usd"],
                    cost_ratio_ex_rebuild=((r["cost_total"] - r["rebuild_usd"] - r["config_switch_usd"]) / b["cost_total"])
                    if b["cost_total"] else None,
                    hit_treat=r["cache_hit_share"], hit_anchor=b["cache_hit_share"],
                    treat_models=r["models"], anchor_models=b["models"],
                    per_turn_cost_treat=r["per_turn_cost"], per_turn_cost_anchor=b["per_turn_cost"],
                    per_turn_rebuild=r["per_turn_rebuild"], per_turn_switch=r["per_turn_switch"],
                    efficiency_usd_saved=r.get("efficiency_usd_saved"), efficiency_n=r.get("efficiency_n"),
                    measured_saving_usd=b["cost_total"] - r["cost_total"],
                    anchor_model=b["models"][0] if len(b["models"]) == 1 else None,
                    treat_model=r["models"][0] if len(r["models"]) == 1 else None,
                    anchor_tok_uncached=b["uncached"], anchor_tok_read=b["read"], anchor_tok_write=b["write"],
                    anchor_tok_output=b["output"], treat_tok_read=r["read"],
                    req_ratio=r["n_req"] / b["n_req"] if b["n_req"] else None,
                    read_ratio=r["read"] / b["read"] if b["read"] else None,
                    cold_ratio=(r["cost_cold"] / b["cost_cold"]) if r.get("cost_cold") and b.get("cost_cold") else None,
                    warm_ratio=(r["cost_warm"] / b["cost_warm"]) if r.get("cost_warm") and b.get("cost_warm") and b["cost_warm"] > 0 and r["cost_warm"] > 0 else None,
                    treat_first_warm=(r["first_req_read"] or 0) > 0, anchor_first_warm=(b["first_req_read"] or 0) > 0,
                    first_switch_req_index=r["first_switch_req_index"], treat_first_model=r["first_model"],
                    planned_saving_usd=planner_saving(r.get("plans") or []), n_plans=len(r.get("plans") or []))
            pairs.append(p)

    tl = defaultdict(list)
    for r in runs:
        if r["kind"] == "anchor" and r.get("session_ok"):
            tl[(r["family"], r["cell"], r["task"])].append(r["n_req"])
    for p in pairs:
        v = tl.get((p["family"], p["anchor"], p["task"]))
        p["task_len"] = statistics.fmean(v) if v else None

    res = build_report(runs, pairs, prices, args.boot, s1_raw_n)
    res["invocation"] = dict(command=f"python3 caching_survey.py --workers {args.workers} --boot {args.boot}",
                             boot=args.boot, bootstrap_seed=7,
                             note="read-only: local result.json files and Amplifier session logs; no model calls")
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        fh.write(tilde(json.dumps(res, indent=1, default=str)))
    write_csv(os.path.join(OUT, "pairs.csv"), [
        {k: v for k, v in p.items() if not isinstance(v, (dict, list))} for p in pairs])
    write_csv(os.path.join(OUT, "sessions.csv"), [
        {k: v for k, v in r.items() if not isinstance(v, (dict, list))} for r in runs])
    print(json.dumps(res["headline"], indent=1, default=str))


def build_report(runs, pairs, prices, nboot, s1_raw_n):
    inv = defaultdict(lambda: dict(runs=0, session_ok=0))
    for r in runs:
        k = f'{r["family"]}|{r["campaign"]}|{r["cell"]}'
        inv[k]["runs"] += 1
        inv[k]["session_ok"] += int(bool(r.get("session_ok")))
    how = defaultdict(int)
    for r in runs:
        how[r["session_how"]] += 1
    cost_check = [r["cost_vs_result_rel"] for r in runs if r.get("cost_vs_result_rel") is not None]

    ok = [p for p in pairs if p["sessions_ok"] and p.get("cost_ratio")]
    groups = defaultdict(list)
    for p in ok:
        groups[(p["family"], p["kind"], p["host"])].append(p)
        groups[(p["family"], p["cell"] + "|vs|" + p["anchor"], "")].append(p)
    group_summ = {}
    for k, ps in sorted(groups.items()):
        group_summ["|".join(x for x in k if x)] = dict(
            cost=summarize(ps, nboot), time=summarize(ps, nboot, "time_ratio"),
            cost_ex_rebuild=summarize(ps, nboot, "cost_ratio_ex_rebuild"),
            treat_pass=sum(bool(p["treat_passed"]) for p in ps), anchor_pass=sum(bool(p["anchor_passed"]) for p in ps),
            sessions_with_switch=sum(p["switches"] > 0 for p in ps),
            switches=sum(p["switches"] for p in ps), rebuild_usd=round(sum(p["rebuild_usd"] for p in ps), 4),
            config_switch_usd=round(sum(p["config_switch_usd"] for p in ps), 4),
            treat_cost=round(sum(p["cost_treat"] for p in ps), 4), anchor_cost=round(sum(p["cost_anchor"] for p in ps), 4),
            median_n_req_anchor=statistics.median(p["n_req_anchor"] for p in ps),
            hit_share_treat=round(statistics.fmean(p["hit_treat"] for p in ps if p["hit_treat"] is not None), 4),
            hit_share_anchor=round(statistics.fmean(p["hit_anchor"] for p in ps if p["hit_anchor"] is not None), 4))

    ok = [p for p in ok if p.get("task_len")]
    routed = [p for p in ok if p["kind"] in ("routing", "midturn_escalation")]
    length = {}
    for label, sel in [("all_routed", routed),
                       ("all_routed_fable_host", [p for p in routed if p["host"] == "fable"]),
                       ("all_routed_opus_host", [p for p in routed if p["host"] == "opus"]),
                       ("S1-single_routed", [p for p in routed if p["family"] == "S1-single"]),
                       ("S1-multi_routed", [p for p in routed if p["family"] == "S1-multi"]),
                       ("S1-multi_routed_fable", [p for p in routed if p["family"] == "S1-multi" and p["host"] == "fable"]),
                       ("S1-multi_routed_opus", [p for p in routed if p["family"] == "S1-multi" and p["host"] == "opus"]),
                       ("S3_routed", [p for p in routed if p["family"] == "S3-routing"]),
                       ("model_swap_control_plain-sonnet", [p for p in ok if p["kind"] == "model_swap_control"])]:
        if not sel:
            continue
        t = terciles(sel, "task_len")
        entry = dict(all=summarize(sel, nboot), time_all=summarize(sel, nboot, "time_ratio"))
        if t:
            lo, hi = t
            bins = {"short": [p for p in sel if p["task_len"] < lo],
                    "mid": [p for p in sel if lo <= p["task_len"] < hi],
                    "long": [p for p in sel if p["task_len"] >= hi]}
            entry["tercile_cuts_task_mean_anchor_requests"] = [round(lo, 2), round(hi, 2)]
            for b, bp in bins.items():
                entry[b] = dict(cost=summarize(bp, nboot), time=summarize(bp, nboot, "time_ratio"),
                                cost_ex_rebuild=summarize(bp, nboot, "cost_ratio_ex_rebuild"),
                                task_len_range=[round(min((p["task_len"] for p in bp), default=0), 2),
                                                round(max((p["task_len"] for p in bp), default=0), 2)],
                                switch_sessions=sum(p["switches"] > 0 for p in bp),
                                rebuild_usd=round(sum(p["rebuild_usd"] for p in bp), 4),
                                treat_cost=round(sum(p["cost_treat"] for p in bp), 4),
                                anchor_cost=round(sum(p["cost_anchor"] for p in bp), 4))
        if len(sel) > 5 and len({p["task_len"] for p in sel}) > 2:
            for xkey, name in (("task_len", "slope_logcostratio_per_log_task_len"),
                               ("n_req_anchor", "slope_vs_pair_anchor_requests_BIASED_regression_to_mean")):
                b = slope(sel, xkey, "cost_ratio")
                ci = cluster_boot(sel, lambda s_, xk=xkey: slope(s_, xk, "cost_ratio"), nboot)
                entry[name] = dict(slope=round(b, 4), ci95=[round(x, 4) for x in ci or []])
        length[label] = entry

    per_turn = {}
    for host in ("fable", "opus"):
        mt = [p for p in routed if p["family"] == "S1-multi" and p["host"] == host]
        for t in (1, 2, 3, 4):
            sel = [dict(p, turn_ratio=p["per_turn_cost_treat"].get(t, 0) / p["per_turn_cost_anchor"][t])
                   for p in mt if p["per_turn_cost_anchor"].get(t) and p["per_turn_cost_treat"].get(t)]
            for q in sel:
                q["turn_ratio_ex_rebuild"] = max(q["per_turn_cost_treat"].get(t, 0) - q["per_turn_rebuild"].get(t, 0), 1e-9) / q["per_turn_cost_anchor"][t]
            per_turn[f"{host}_turn{t}"] = dict(
                cost=summarize(sel, nboot, "turn_ratio"), cost_ex_rebuild=summarize(sel, nboot, "turn_ratio_ex_rebuild"),
                switches_into_turn=sum(q["per_turn_switch"].get(t, 0) for q in sel),
                rebuild_usd=round(sum(q["per_turn_rebuild"].get(t, 0) for q in sel), 4),
                treat_cost=round(sum(q["per_turn_cost_treat"].get(t, 0) for q in sel), 4),
                anchor_cost=round(sum(q["per_turn_cost_anchor"][t] for q in sel), 4))

    rb = dict(
        routed_sessions=len(routed), routed_sessions_with_model_switch=sum(p["switches"] > 0 for p in routed),
        model_switches=sum(p["switches"] for p in routed),
        at_turn_boundary=sum(p["switches_turn_boundary"] for p in routed),
        midturn=sum(p["switches_midturn"] for p in routed),
        routed_cost_usd=round(sum(p["cost_treat"] for p in routed), 4),
        anchor_cost_usd=round(sum(p["cost_anchor"] for p in routed), 4),
        rebuild_usd_excess=round(sum(p["rebuild_usd"] for p in routed), 4),
        rebuild_usd_full_write=round(sum(p["rebuild_usd_full_write"] for p in routed), 4),
        same_model_config_switch_usd=round(sum(p["config_switch_usd"] for p in routed), 4))
    rb["rebuild_share_of_routed_cost"] = round(rb["rebuild_usd_excess"] / rb["routed_cost_usd"], 4) if rb["routed_cost_usd"] else None
    gap = rb["anchor_cost_usd"] - rb["routed_cost_usd"]
    rb["rebuild_as_share_of_gross_saving"] = round(rb["rebuild_usd_excess"] / (gap + rb["rebuild_usd_excess"]), 4) if gap + rb["rebuild_usd_excess"] else None
    rb_by = {}
    for key in sorted({(p["family"], p["host"], p["cell"]) for p in routed}):
        ps = [p for p in routed if (p["family"], p["host"], p["cell"]) == key]
        rb_by["|".join(key)] = dict(
            pairs=len(ps), switch_sessions=sum(p["switches"] > 0 for p in ps), switches=sum(p["switches"] for p in ps),
            routed_cost=round(sum(p["cost_treat"] for p in ps), 4), anchor_cost=round(sum(p["cost_anchor"] for p in ps), 4),
            rebuild_usd=round(sum(p["rebuild_usd"] for p in ps), 4),
            cfg_switch_usd=round(sum(p["config_switch_usd"] for p in ps), 4))
    rb["by_family_host_cell"] = rb_by

    rec = {}
    v4 = [p for p in ok if p["family"] == "S3-v4-same-model"]
    for cell in ("jev-prepared", "laya-prepared", "jevgrep"):
        ps = [p for p in v4 if p["cell"] == cell]
        if not ps:
            continue
        diff = lambda s: statistics.fmean(p["measured_saving_usd"] for p in s)
        rec[f"S3-v4 {cell} vs plain-matched"] = dict(
            pairs=len(ps), receipts_events=sum(p["efficiency_n"] or 0 for p in ps),
            sum_usd_saved_receipts=round(sum(p["efficiency_usd_saved"] or 0 for p in ps), 4),
            sum_measured_saving_usd=round(sum(p["measured_saving_usd"] for p in ps), 4),
            mean_measured_saving_per_pair=round(diff(ps), 4),
            mean_measured_saving_ci95=[round(x, 4) for x in cluster_boot(ps, diff, nboot) or []],
            corr_receipt_vs_measured=corr([p["efficiency_usd_saved"] or 0 for p in ps], [p["measured_saving_usd"] for p in ps]))
    planners = [p for p in ok if p["n_plans"] and p["planned_saving_usd"] is not None]
    for key in sorted({(p["family"], p["cell"], p["anchor"]) for p in planners}):
        ps = [p for p in planners if (p["family"], p["cell"], p["anchor"]) == key]
        diff = lambda s: statistics.fmean(p["measured_saving_usd"] for p in s)
        rec[f"planner-predicted {key[0]} {key[1]} vs {key[2]}"] = dict(
            pairs=len(ps), plans=sum(p["n_plans"] for p in ps),
            sum_planner_predicted_saving_usd=round(sum(p["planned_saving_usd"] for p in ps), 4),
            sum_measured_saving_usd=round(sum(p["measured_saving_usd"] for p in ps), 4),
            mean_measured_saving_ci95=[round(x, 4) for x in cluster_boot(ps, diff, nboot) or []],
            corr=corr([p["planned_saving_usd"] for p in ps], [p["measured_saving_usd"] for p in ps]))

    corrections = corrections_section(runs, ok, routed, pairs, prices, nboot)

    headline = dict(
        runs_indexed=len(runs), s1_result_files_before_attempt_dedupe=s1_raw_n,
        runs_with_parsed_session=sum(bool(r.get("session_ok")) for r in runs),
        pairs_total=len(pairs), pairs_with_sessions=len(ok), routed_pairs=len(routed),
        routed_pairs_with_efficiency_receipts=sum(1 for p in routed if (p.get("efficiency_n") or 0) > 0),
        length=length, rebuild=rb, per_turn_multiturn=per_turn, receipts=rec, corrections=corrections)
    return dict(
        headline=headline, inferred_prices=prices, inventory=dict(sorted(inv.items())),
        session_resolution=dict(how),
        session_cost_vs_result_json=dict(n=len(cost_check),
                                         median_rel_diff=statistics.median(cost_check) if cost_check else None,
                                         p95_rel_diff=sorted(cost_check)[int(.95 * len(cost_check))] if cost_check else None),
        groups=group_summ,
        definitions=dict(
            uncached="input_tokens - cache_read_tokens (provider input_tokens includes reads, excludes writes; verified by price fit)",
            cache_hit_share="cache_read / (uncached + cache_read + cache_write), main-loop requests",
            main_loop="llm:request with a system prompt and tools; background calls (e.g. session naming) excluded from switch counts, included in cost",
            model_switch="main-loop request whose model differs from the previous main-loop request",
            rebuild_excess_write="max(0, cache_write_i - max(0, prompt_i - prompt_{i-1})): writes beyond the new conversation tail",
            rebuild_usd="rebuild_excess_write x (write price - read price) of the new model: extra paid vs a warm read",
            config_switch="same model, thinking/effort changed (Anthropic also invalidates the message cache)",
            cost="sum of provider-reported cost_usd over all llm:response in the session (estimate, not billing)",
            time_ratio="result.json exec_time_ms (first request to last response), treat/anchor",
            ci="95% percentile bootstrap, resampling tasks (clusters) with replacement"))


if __name__ == "__main__":
    main()
