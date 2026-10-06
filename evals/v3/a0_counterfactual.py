#!/usr/bin/env python3
"""A0: phase-0 potential-outcome counterfactual on main-v1 (docs/design/v3/PLAN.md, section A0). Offline, $0.

Logic. A decide-once decider makes ONE choice per session at session start, so every session it produces is either an
"always-host" session or an "always-cheap" session for that scenario-rep. Its policy value is therefore
sum_s cost(s, D(s)), computable from two pinned potential outcomes per (host, scenario, rep):

* host  = the plain anchor session (plain host model, provider-default effort). Using the anchor rather than the
          sticky-host session removes the effort-switch cache artifact (section 0.4) by construction.
* cheap = the sticky session when Jev routed it to cheap (Sonnet at `medium`, decided once; 124/140 per host);
          otherwise the plain Sonnet session x 0.821 (the preregistered Sonnet-medium / Sonnet-default ratio,
          2026-10-05-effort-control). Its quality is taken from the same session (unscaled).

Deciders priced: always-host, always-route, Jev's recorded decision (campaign/decisions.jsonl), the shipped decider
(Jev + price gate: the gate never routes an Opus 5.5 host), deterministic rule candidates fitted on the TRAIN split only,
and a cross-fitted oracle (choose on rep 1, evaluate on rep 2 and vice versa, so it is not optimistic).

Also re-derives the section 0.4 finding (effort changes rewrite the prompt cache) from requests.jsonl.gz with exact
numbers, and freezes R* and the candidate configs for S1 (evals/v3/frozen_rule.json).

Usage: nice -n 10 python3 -m evals.v3.a0_counterfactual [--out DIR] [--resamples 10000] [--freeze evals/v3/frozen_rule.json]
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from evals.v3 import rules as R
from evals.v3.common import (REPO_ROOT, cluster_bootstrap, cluster_mean, mean, quantile, sha256_file, write_csv,
                             write_json)

EVIDENCE = REPO_ROOT / "docs" / "evidence" / "2026-10-02-paired-campaign"
SCENARIOS = REPO_ROOT / "evals" / "paired" / "scenarios" / "main-v1"
OUT = REPO_ROOT / "docs" / "evidence" / "2026-10-v3-offline" / "a0-counterfactual"
FROZEN = REPO_ROOT / "evals" / "v3" / "frozen_rule.json"

SONNET_MEDIUM_FACTOR = 0.821      # 2026-10-05-effort-control RESULT: Sonnet medium / Sonnet default, GM cost ratio
FABLE_MEDIUM_FACTOR = 0.860       # 2026-10-06-effort-control-fable RESULT: Fable medium / Fable default
SONNET_MEDIUM_CI = (0.781, 0.861)
FABLE_MEDIUM_CI = (0.833, 0.885)
JEV_USD_PER_DECISION = 18.0 / 1_000_000   # $18 per 1M decisions (judge benchmark); added to Jev-decided sessions
QUALITY_FLOOR = -0.025            # first (a-priori) fit constraint: train mean turn-pass delta vs always-host >= -0.025
CV_FLOORS = (-1.0, -0.05, -0.025, -0.01, 0.0)   # candidate floors judged by inner cross-validation on train (-1 = none)
CV_FOLDS = 5
OCCAM_LOG_TOL = 0.01              # rules within 1% (log) of the best feasible cost: the simplest wins
SEED = 20261005
# price table (savings.DEFAULT_RATES at 8e7faf3, sha 9cb9b9134ab7fa08): $/M (input, output, cache_read, cache_write)
RATES = {"claude-fable-5-1": (10.0, 50.0, 0.25, 12.5), "claude-sonnet-5": (3.0, 15.0, 0.30, 3.75),
         "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0)}


# ------------------------------------------------------------------------------------------------------------ loading
def read_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def load_prompts(scen_dir: Path = SCENARIOS) -> dict[str, str]:
    """Turn-1 prompt per scenario id (used in memory for features only; never written out)."""
    import yaml  # test extra; only needed to read scenario files
    out = {}
    for f in sorted(scen_dir.glob("*/*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(d, dict) and "turns" in d:
            out[d["id"]] = d["turns"][0]["prompt"]
    return out


def build_units(sessions: list[dict], decisions: list[dict], prompts: dict[str, str],
                sonnet_factor: float = SONNET_MEDIUM_FACTOR, cheap_source: str = "sticky") -> list[dict]:
    """One unit per (host, scenario, rep) with both potential outcomes and the decision-time features.

    cheap_source="sticky" (primary): the sticky-cheap session where Jev routed, else plain Sonnet x factor.
    cheap_source="sonnet": plain Sonnet x factor everywhere (sensitivity)."""
    by = {(s["host"], s["arm"], s["scenario_id"], s["rep"]): s for s in sessions}
    jev = {(d["host"], d["scenario"], d["rep"]): d["decision"] for d in decisions}
    units = []
    for (host, arm, scen, rep), a in sorted(by.items()):
        if arm != "anchor" or not a.get("cost_valid", True):
            continue
        st = by.get((host, "sticky", scen, rep))
        son = by[("any", "sonnet", scen, rep)]
        if cheap_source == "sticky" and st is not None and st["sticky_decision"] == "cheap":
            c, src, c_cost = st, "sticky_cheap", st["cost_usd_tools_normalized"]
        else:
            c, src, c_cost = son, f"sonnet_x{sonnet_factor}", son["cost_usd_tools_normalized"] * sonnet_factor
        f = R.features(prompts[scen], a["workspace_files"])
        units.append({
            "host": host, "scenario": scen, "rep": rep, "split": a["split"], "task_type": a["task_type"],
            "cost_host": a["cost_usd_tools_normalized"], "tp_host": a["turn_pass_frac"],
            "final_host": bool(a["final_state_pass"]), "wall_host_min": a["wall_ms"] / 60000,
            "cost_cheap": c_cost, "tp_cheap": c["turn_pass_frac"], "final_cheap": bool(c["final_state_pass"]),
            "wall_cheap_min": c["wall_ms"] / 60000, "cheap_source": src,
            "jev": jev[(host, scen, rep)], **f,
        })
    return units


# --------------------------------------------------------------------------------------------------------- policies
def oracle_choice(u: dict, cost_only: bool = False) -> str:
    """Outcome-derived best choice for one unit: cheap iff cheaper and (unless cost_only) turn-pass not lower."""
    cheaper = u["cost_cheap"] < u["cost_host"]
    return "cheap" if cheaper and (cost_only or u["tp_cheap"] >= u["tp_host"]) else "host"


def cross_fit(units: list[dict], chooser) -> dict:
    """Choose on the other rep of the same (host, scenario); evaluate on this rep. Falls back to in-sample if alone."""
    groups = defaultdict(dict)
    for u in units:
        groups[(u["host"], u["scenario"])][u["rep"]] = u
    out = {}
    for (host, scen), reps in groups.items():
        for rep, u in reps.items():
            other = [v for r, v in reps.items() if r != rep]
            out[(host, scen, rep)] = chooser(other[0] if other else u)
    return out


def key(u: dict) -> tuple:
    return (u["host"], u["scenario"], u["rep"])


def policy_decisions(units: list[dict], rule: dict | None = None) -> dict[str, dict]:
    """Decision maps {policy name: {unit key: tier}} for the standard deciders (plus `rule` as R*)."""
    pol = {
        "always_host": {key(u): "host" for u in units},
        "always_route": {key(u): "cheap" for u in units},
        "jev_recorded": {key(u): u["jev"] for u in units},
        "shipped_jev_price_gate": {key(u): ("host" if u["host"] == "opus" else u["jev"]) for u in units},
        "oracle_xfit": cross_fit(units, oracle_choice),
        "oracle_cost_only_xfit": cross_fit(units, lambda u: oracle_choice(u, cost_only=True)),
        "oracle_in_sample": {key(u): oracle_choice(u) for u in units},
    }
    if rule is not None:
        pol["rule_R*"] = {key(u): R.decide(rule, u) for u in units}
    return pol


def outcome(u: dict, tier: str, host_factor: float = 1.0, decider_usd: float = 0.0) -> dict:
    if tier == "cheap":
        return {"cost": u["cost_cheap"] + decider_usd, "tp": u["tp_cheap"], "final": u["final_cheap"],
                "wall": u["wall_cheap_min"]}
    return {"cost": u["cost_host"] * host_factor + decider_usd, "tp": u["tp_host"], "final": u["final_host"],
            "wall": u["wall_host_min"]}


def evaluate(units: list[dict], dec: dict, *, host_factor: float = 1.0, decider_usd: float = 0.0,
             resamples: int = 10_000, seed: int = SEED) -> dict:
    """Policy value vs always-host (the plain anchor) with scenario-cluster bootstrap CIs."""
    lr, dtp, dfin = defaultdict(list), defaultdict(list), defaultdict(list)
    costs, walls, routed = [], [], 0
    for u in units:
        t = dec[key(u)]
        o = outcome(u, t, host_factor, decider_usd)
        routed += t == "cheap"
        costs.append(o["cost"])
        walls.append(o["wall"])
        lr[u["scenario"]].append(math.log(o["cost"] / u["cost_host"]))
        dtp[u["scenario"]].append(o["tp"] - u["tp_host"])
        dfin[u["scenario"]].append(float(o["final"]) - float(u["final_host"]))
    gm, lo, hi = cluster_bootstrap(lr, cluster_mean, n=resamples, seed=seed)
    tp, tlo, thi = cluster_bootstrap(dtp, cluster_mean, n=resamples, seed=seed + 1)
    return {
        "n_units": len(units), "n_scenarios": len(lr), "route_share": routed / len(units) if units else float("nan"),
        "mean_cost_usd": mean(costs), "usd_per_1000_sessions": 1000 * mean(costs),
        "total_cost_ratio": sum(costs) / sum(u["cost_host"] for u in units),
        "gm_cost_ratio": math.exp(gm), "gm_cost_ratio_ci95": [math.exp(lo), math.exp(hi)],
        "d_turn_pass": tp, "d_turn_pass_ci95": [tlo, thi],
        "d_final_pass": cluster_mean(list(dfin.values())), "mean_wall_min": mean(walls),
    }


# ------------------------------------------------------------------------------------------------------- rule search
def candidate_rules(train: list[dict], gate: int | None = 300) -> list[dict]:
    """Rule family searched on the train split: always-route; one length/workspace threshold (train deciles);
    an intent set (1-2 intents); and one threshold OR one intent. Every rule carries the shipped scope gate."""
    def q(feat):
        vals = [u[feat] for u in train]
        return sorted({round(quantile(vals, p / 10)) for p in range(1, 10)})
    nums = [{"feature": "turn1_prompt_chars", "op": op, "value": t} for t in q("turn1_prompt_chars") for op in (">", "<")]
    nums += [{"feature": "workspace_files", "op": op, "value": t} for t in q("workspace_files") for op in (">", "<")]
    intents = [{"feature": "intent", "op": "in", "value": list(c)}
               for k in (1, 2) for c in itertools.combinations(R.INTENTS, k)]
    singles = [{"feature": "intent", "op": "in", "value": [i]} for i in R.INTENTS]
    conds = [[]] + [[c] for c in nums + intents] + [[a, b] for a in nums for b in singles]
    return [{"host_if_any": c, "scope_gate_max_workspace_files": gate} for c in conds]


def fit_rule(train: list[dict], quality_floor: float = QUALITY_FLOOR, tol: float = OCCAM_LOG_TOL,
             gate: int | None = 300) -> tuple[dict, list[dict]]:
    """R* = the cheapest train rule (mean per-scenario log cost ratio vs always-host) whose train mean turn-pass delta is
    >= quality_floor; among rules within `tol` (log) of that cost, the simplest (then cheapest, then first) wins."""
    table = []
    for i, rule in enumerate(candidate_rules(train, gate)):
        lr, dtp = defaultdict(list), defaultdict(list)
        for u in train:
            o = outcome(u, R.decide(rule, u))
            lr[u["scenario"]].append(math.log(o["cost"] / u["cost_host"]))
            dtp[u["scenario"]].append(o["tp"] - u["tp_host"])
        table.append({"idx": i, "rule": R.describe(rule), "complexity": R.complexity(rule),
                      "train_log_ratio": cluster_mean(list(lr.values())),
                      "train_d_turn_pass": cluster_mean(list(dtp.values())),
                      "route_share": mean(R.decide(rule, u) == "cheap" for u in train), "_spec": rule})
    feas = [t for t in table if t["train_d_turn_pass"] >= quality_floor]
    best = min(t["train_log_ratio"] for t in feas)
    near = [t for t in feas if t["train_log_ratio"] <= best + tol]
    chosen = min(near, key=lambda t: (t["complexity"], t["train_log_ratio"], t["idx"]))
    for t in table:
        t["feasible"] = t["train_d_turn_pass"] >= quality_floor
        t["chosen"] = t is chosen
    return chosen["_spec"], table


def select_floor(train: list[dict], floors=CV_FLOORS, k: int = CV_FOLDS, seed: int = SEED,
                 quality_floor: float = QUALITY_FLOOR, tol: float = OCCAM_LOG_TOL) -> tuple[float, list[dict]]:
    """Train-only choice of the fitting floor by grouped k-fold cross-validation over scenarios.

    For each floor, fit on k-1 folds and score the held-out fold (mean per-scenario log cost ratio and turn-pass delta vs
    always-host, pooled over folds). The chosen floor is the one with the lowest out-of-fold cost whose out-of-fold
    turn-pass delta is >= quality_floor; among floors within `tol` of it, the most permissive (simplest procedure)."""
    import random
    scen = sorted({u["scenario"] for u in train})
    random.Random(seed).shuffle(scen)
    fold = {s: i % k for i, s in enumerate(scen)}
    rows = []
    for fl in floors:
        lr, dtp = defaultdict(list), defaultdict(list)
        for f in range(k):
            fit = [u for u in train if fold[u["scenario"]] != f]
            held = [u for u in train if fold[u["scenario"]] == f]
            rule, _ = fit_rule(fit, quality_floor=fl, tol=tol)
            for u in held:
                o = outcome(u, R.decide(rule, u))
                lr[u["scenario"]].append(math.log(o["cost"] / u["cost_host"]))
                dtp[u["scenario"]].append(o["tp"] - u["tp_host"])
        rows.append({"floor": fl, "oof_log_ratio": cluster_mean(list(lr.values())),
                     "oof_gm_cost_ratio": math.exp(cluster_mean(list(lr.values()))),
                     "oof_d_turn_pass": cluster_mean(list(dtp.values()))})
    feas = [r for r in rows if r["oof_d_turn_pass"] >= quality_floor] or rows
    best = min(r["oof_log_ratio"] for r in feas)
    chosen = min((r for r in feas if r["oof_log_ratio"] <= best + tol), key=lambda r: r["floor"])
    for r in rows:
        r["chosen"] = r is chosen
    return chosen["floor"], rows


def disagreement(units: list[dict], a: dict, b: dict) -> dict:
    """d(a, b) and the H2 identity: |mean cost difference| = d * |mean discordant difference|."""
    disc = [u for u in units if a[key(u)] != b[key(u)]]
    diffs = [outcome(u, a[key(u)])["cost"] - outcome(u, b[key(u)])["cost"] for u in disc]
    d = len(disc) / len(units)
    mdd = mean(diffs) if diffs else 0.0
    return {"d": d, "n_discordant": len(disc), "n_units": len(units), "mean_discordant_cost_diff_usd": mdd,
            "implied_mean_cost_diff_usd": d * mdd,
            "discordant_scenarios": sorted({u["scenario"] for u in disc})}


# --------------------------------------------------------------------------------------------- effort-switch finding
LONG_GAP_S = 300   # the 5-minute prompt-cache TTL: a turn after a gap this long starts cold whatever the effort


def position(prev: dict, cur: dict, gaps: dict) -> str:
    """Where a request sits: inside a turn, first of a turn after a short gap, or first after a long (TTL) gap."""
    if cur["turn_index"] == prev["turn_index"]:
        return "within_turn"
    g = gaps.get((cur["session_key"], cur["turn_index"])) or 0
    return "turn_first_long_gap" if g >= LONG_GAP_S else "turn_first_short_gap"


def effort_cache(requests_path: Path, sessions: list[dict], gaps: dict) -> tuple[dict, list[dict], list[dict]]:
    """Section 0.4: in sticky sessions that KEPT the host, the phase effort map changed effort between requests.
    Compare cache writes on requests after an effort change vs after none, by position (within a turn / first of a turn
    after a short gap / after a long gap that outlasts the cache TTL), with the plain anchor of the same scenario-rep
    (effort never changes) as a control. Streams the gzip; `gaps` maps (session_key, turn_index) -> idle seconds."""
    sk = {s["session_key"]: s for s in sessions}
    sticky_host = {k for k, s in sk.items() if s["arm"] == "sticky" and s["sticky_decision"] == "host"}
    cellkey = lambda s: (s["host"], s["scenario_id"], s["rep"])  # noqa: E731
    pairs = {cellkey(sk[k]) for k in sticky_host}
    anchor_of = {cellkey(s): k for k, s in sk.items() if s["arm"] == "anchor" and cellkey(s) in pairs}
    wanted = sticky_host | set(anchor_of.values())
    reqs = defaultdict(list)
    for r in read_jsonl(requests_path):
        if r["main"] and r["session_key"] in wanted:
            reqs[r["session_key"]].append(r)
    cells = defaultdict(list)          # (group, host, effort_changed, position) -> [(write, read)]
    per_session = {}
    for k, rs in reqs.items():
        rs.sort(key=lambda r: r["request_index"])
        group = "sticky_host" if k in sticky_host else "anchor"
        changes = 0
        for prev, cur in zip(rs, rs[1:]):
            changed = prev["effort"] != cur["effort"]
            changes += changed
            cells[(group, sk[k]["host"], changed, position(prev, cur, gaps))].append(
                (cur["tokens"]["cache_write"], cur["tokens"]["cache_read"]))
        per_session[k] = {"effort_changes": changes, "n_main": len(rs), "requests": rs,
                          "cache_write": sum(r["tokens"]["cache_write"] for r in rs)}
    positions = ("within_turn", "turn_first_short_gap", "turn_first_long_gap")
    agg = []
    for (group, host, changed, pos), v in sorted(cells.items()):
        ws = [w for w, _ in v]
        agg.append({"group": group, "host": host, "effort_changed": changed, "position": pos, "n": len(v),
                    "mean_cache_write": mean(ws), "median_cache_write": statistics.median(ws),
                    "mean_cache_read": mean(r for _, r in v)})

    def pooled(group, changed=None, pos=None, host=None):
        v = [x for (g, h, c, p), xs in cells.items() if g == group and (changed is None or c == changed)
             and (pos is None or p == pos) and (host is None or h == host) for x in xs]
        return {"n": len(v), "mean_cache_write": mean(w for w, _ in v)}

    # Premium (estimate): on changed requests that are NOT after a long gap, write tokens above a no-change baseline in
    # the same (host, position), repriced from the write rate to the read rate. Two baselines bracket it:
    # high = unchanged-effort requests of the same sticky sessions; low = the larger of that and the plain anchor's mean
    # (anchors write ~12k at short-gap turn starts, so `low` credits all of that to the turn start, not to the change).
    base = {(h, p): pooled("sticky_host", False, p, h)["mean_cache_write"] for h in ("fable", "opus")
            for p in positions[:2]}
    base_low = {(h, p): max(base[(h, p)], pooled("anchor", False, p, h)["mean_cache_write"]) for (h, p) in base}
    srows = []
    for k in sorted(sticky_host):
        s = sk[k]
        a = sk[anchor_of[cellkey(s)]]
        ps, pa = per_session[k], per_session[a["session_key"]]
        premium = premium_low = 0.0
        for prev, cur in zip(ps["requests"], ps["requests"][1:]):
            pos = position(prev, cur, gaps)
            if prev["effort"] != cur["effort"] and pos != "turn_first_long_gap":
                _, _, rd, wr = RATES[cur["model"]]
                w = cur["tokens"]["cache_write"]
                premium += max(0.0, w - base[(s["host"], pos)]) * (wr - rd) / 1e6
                premium_low += max(0.0, w - base_low[(s["host"], pos)]) * (wr - rd) / 1e6
        cost, acost = s["cost_usd_tools_normalized"], a["cost_usd_tools_normalized"]
        srows.append({"session_key": k, "host": s["host"], "scenario": s["scenario_id"], "rep": s["rep"],
                      "effort_changes": ps["effort_changes"], "n_main": ps["n_main"], "anchor_n_main": pa["n_main"],
                      "cache_write": ps["cache_write"], "anchor_cache_write": pa["cache_write"],
                      "cost": cost, "anchor_cost": acost, "cost_ratio": cost / acost,
                      "req_ratio": ps["n_main"] / pa["n_main"], "cache_write_ratio": ps["cache_write"] / pa["cache_write"],
                      "est_rewrite_premium_usd": premium, "est_rewrite_premium_usd_low": premium_low,
                      "est_cost_ratio_premium_removed": (cost - premium) / acost,
                      "est_cost_ratio_premium_low_removed": (cost - premium_low) / acost})

    def gm(host, field):
        return math.exp(mean(math.log(r[field]) for r in srows if r["host"] == host))

    def rom(host, num, den):
        rs = [r for r in srows if r["host"] == host]
        return sum(r[num] for r in rs) / sum(r[den] for r in rs)

    summary = {
        "requests_after_effort_change": pooled("sticky_host", True),
        "requests_effort_unchanged": pooled("sticky_host", False),
        "by_position": {f"{g}|{'changed' if c else 'unchanged'}|{p}": pooled(g, c, p)
                        for g in ("sticky_host", "anchor") for c in (True, False) for p in positions
                        if pooled(g, c, p)["n"]},
        "within_turn_ratio_changed_over_unchanged": pooled("sticky_host", True, "within_turn")["mean_cache_write"]
        / pooled("sticky_host", False, "within_turn")["mean_cache_write"],
        "sessions": {h: {"n": sum(r["host"] == h for r in srows),
                         "gm_cost_ratio": gm(h, "cost_ratio"), "gm_req_ratio": gm(h, "req_ratio"),
                         "gm_cache_write_ratio": gm(h, "cache_write_ratio"),
                         "ratio_of_sums_cost": rom(h, "cost", "anchor_cost"),
                         "ratio_of_sums_requests": rom(h, "n_main", "anchor_n_main"),
                         "ratio_of_sums_cache_write": rom(h, "cache_write", "anchor_cache_write"),
                         "mean_effort_changes": mean(r["effort_changes"] for r in srows if r["host"] == h),
                         "est_rewrite_premium_usd_total": sum(r["est_rewrite_premium_usd"] for r in srows
                                                              if r["host"] == h),
                         "est_rewrite_premium_share_of_cost": sum(r["est_rewrite_premium_usd"] for r in srows
                                                                  if r["host"] == h) / sum(r["cost"] for r in srows
                                                                                           if r["host"] == h),
                         "mean_req_ratio": mean(r["req_ratio"] for r in srows if r["host"] == h),
                         "mean_cache_write_ratio": mean(r["cache_write_ratio"] for r in srows if r["host"] == h),
                         "est_rewrite_premium_usd_total_low": sum(r["est_rewrite_premium_usd_low"] for r in srows
                                                                  if r["host"] == h),
                         "gm_est_cost_ratio_premium_removed": gm(h, "est_cost_ratio_premium_removed"),
                         "gm_est_cost_ratio_premium_low_removed": gm(h, "est_cost_ratio_premium_low_removed")}
                     for h in sorted({r["host"] for r in srows})},
        "baseline_write_unchanged": {f"{h}|{p}": v for (h, p), v in base.items()},
        "baseline_write_low": {f"{h}|{p}": v for (h, p), v in base_low.items()},
        "efforts_seen": dict(Counter(str(r["effort"]) for k in sticky_host for r in per_session[k]["requests"])),
        "long_gap_s": LONG_GAP_S,
    }
    return summary, agg, srows


# ---------------------------------------------------------------------------------------------------------- driver
def run(out: Path = OUT, freeze: Path | None = FROZEN, resamples: int = 10_000) -> dict:
    data = EVIDENCE / "data"
    sessions = list(read_jsonl(data / "sessions.jsonl"))
    decisions = list(read_jsonl(EVIDENCE / "campaign" / "decisions.jsonl"))
    prompts = load_prompts()
    units = build_units(sessions, decisions, prompts)
    units_sonnet = build_units(sessions, decisions, prompts, cheap_source="sonnet")

    fable_train = [u for u in units if u["host"] == "fable" and u["split"] == "train"]
    first_rule, _ = fit_rule(fable_train, quality_floor=QUALITY_FLOOR)       # a-priori objective, reported
    floor, cv_rows = select_floor(fable_train)
    rule, table = fit_rule(fable_train, quality_floor=floor)
    pols = policy_decisions(units, rule)
    pols["rule_first_objective"] = {key(u): R.decide(first_rule, u) for u in units}
    pols["always_route_scope_gate"] = {key(u): R.decide({"host_if_any": [], "scope_gate_max_workspace_files": 300}, u)
                                       for u in units}

    results = []
    for host in ("fable", "opus"):
        for split in ("train", "test", "all"):
            us = [u for u in units if u["host"] == host and (split == "all" or u["split"] == split)]
            for name, dec in pols.items():
                usd = JEV_USD_PER_DECISION if name.startswith(("jev", "shipped")) else 0.0
                ev = evaluate(us, dec, decider_usd=usd, resamples=resamples)
                results.append({"host": host, "split": split, "policy": name, **ev})
    oracle_cost = {(r["host"], r["split"]): r["mean_cost_usd"] for r in results if r["policy"] == "oracle_xfit"}
    for r in results:
        r["regret_usd_per_1000_vs_oracle_xfit"] = 1000 * (r["mean_cost_usd"] - oracle_cost[(r["host"], r["split"])])

    # sensitivity: cheap outcome = plain Sonnet x 0.821 for every unit
    sens = []
    pols_s = policy_decisions(units_sonnet, rule)
    for host in ("fable", "opus"):
        us = [u for u in units_sonnet if u["host"] == host]
        for name in ("always_route", "jev_recorded", "rule_R*", "oracle_xfit"):
            sens.append({"host": host, "split": "all", "policy": name, "cheap_source": "sonnet_x0.821",
                         **evaluate(us, pols_s[name], resamples=resamples)})

    # S1 predictions: candidate configs vs the plain host anchor. Strong medium scales host-kept sessions (estimate).
    preds = []
    for host in ("fable", "opus"):
        us = [u for u in units if u["host"] == host]
        for name in ("rule_R*", "jev_recorded", "always_route", "always_host"):
            for strong, fac in (("default", 1.0), ("medium", FABLE_MEDIUM_FACTOR)):
                ev = evaluate(us, pols[name], host_factor=fac, resamples=resamples)
                preds.append({"host": host, "decider": name, "strong_effort": strong,
                              "host_factor": fac, **ev})

    dis = {h: {"jev_vs_R*": disagreement([u for u in units if u["host"] == h], pols["jev_recorded"], pols["rule_R*"]),
               "jev_vs_always_route": disagreement([u for u in units if u["host"] == h], pols["jev_recorded"],
                                                   pols["always_route"]),
               "R*_vs_oracle_xfit": disagreement([u for u in units if u["host"] == h], pols["rule_R*"],
                                                 pols["oracle_xfit"])}
           for h in ("fable", "opus")}

    gaps = {(t["session_key"], t["turn_index"]): t["gap_before_s"] for t in read_jsonl(data / "turns.jsonl")}
    eff_summary, eff_agg, eff_sessions = effort_cache(data / "requests.jsonl.gz", sessions, gaps)

    intent_by_type = Counter((u["task_type"], u["intent"]) for u in units if u["host"] == "fable" and u["rep"] == 1)
    rows_units = []
    for u in units:
        row = {k: v for k, v in u.items()}
        for name, dec in pols.items():
            row[f"d_{name}"] = dec[key(u)]
        rows_units.append(row)

    by = lambda h, s, p: next(r for r in results if (r["host"], r["split"], r["policy"]) == (h, s, p))  # noqa: E731
    pred = lambda h, d, e: next(p for p in preds if (p["host"], p["decider"], p["strong_effort"]) == (h, d, e))  # noqa
    summary = {
        "inputs": {"sessions_sha256": sha256_file(data / "sessions.jsonl"),
                   "requests_sha256": sha256_file(data / "requests.jsonl.gz"),
                   "decisions_sha256": sha256_file(EVIDENCE / "campaign" / "decisions.jsonl"),
                   "cost_basis": "cost_usd_tools_normalized", "resamples": resamples, "seed": SEED},
        "potential_outcomes": {h: dict(Counter(u["cheap_source"] for u in units if u["host"] == h))
                               for h in ("fable", "opus")},
        "R*": {"spec": rule, "description": R.describe(rule), "complexity": R.complexity(rule),
               "fit": {"data": "main-v1 train split (47 scenarios x 2 reps), Fable host",
                       "objective": "min mean per-scenario log cost ratio vs always-host",
                       "constraint": f"train mean turn-pass delta >= floor; floor chosen by {CV_FOLDS}-fold grouped "
                                     f"CV on train from {list(CV_FLOORS)}: chosen {floor}",
                       "floor": floor, "cv": cv_rows,
                       "cv_any_floor_met_quality_out_of_fold": any(r["oof_d_turn_pass"] >= QUALITY_FLOOR
                                                                    for r in cv_rows),
                       "first_objective": {"floor": QUALITY_FLOOR, "rule": R.describe(first_rule),
                                           "note": "fixed a priori; reported because it was run first"},
                       "occam_tolerance_log": OCCAM_LOG_TOL, "candidates": len(table)}},
        "headline": {h: {p: {s: {k: by(h, s, p)[k] for k in ("gm_cost_ratio", "gm_cost_ratio_ci95", "d_turn_pass",
                                                             "d_turn_pass_ci95", "route_share",
                                                             "regret_usd_per_1000_vs_oracle_xfit")}
                             for s in ("train", "test", "all")}
                         for p in pols} for h in ("fable", "opus")},
        "disagreement": dis,
        "s1_predictions": {
            "C*_F": {"config": "bundle, decide-once, decider R*, price gate on, scope gate 300, cheap: medium, "
                               "strong: medium", **{k: pred("fable", "rule_R*", "medium")[k]
                                                    for k in ("gm_cost_ratio", "gm_cost_ratio_ci95", "d_turn_pass",
                                                              "d_turn_pass_ci95", "route_share")},
                     "label": "estimated: main-v1 potential outcomes; host-kept sessions x 0.860 (Fable medium)"},
            "C*_O": {"config": "shipped (price gate closed: never routes), strong: medium",
                     "gm_cost_ratio_prior": [SONNET_MEDIUM_FACTOR, FABLE_MEDIUM_FACTOR],
                     "label": "unmeasured: Opus medium has no data; prior band from Sonnet 0.821 and Fable 0.860"},
            "H5_Pc_over_A0O": {k: by("opus", "all", "always_route")[k] for k in ("gm_cost_ratio", "gm_cost_ratio_ci95")},
        },
        "effort_cache": eff_summary,
        "intent_vs_task_type_fable_rep1": {f"{a}|{b}": n for (a, b), n in sorted(intent_by_type.items())},
    }
    write_json(out / "summary.json", summary)
    write_csv(out / "policies.csv", results)
    write_csv(out / "policies_sensitivity_cheap_sonnet.csv", sens)
    write_csv(out / "s1_predictions.csv", preds)
    write_csv(out / "potential_outcomes.csv", rows_units)
    write_csv(out / "rule_cv.csv", cv_rows)
    write_csv(out / "rule_search.csv", [{k: v for k, v in t.items() if k != "_spec"} for t in table])
    write_csv(out / "effort_cache_requests.csv", eff_agg)
    write_csv(out / "effort_cache_sessions.csv", eff_sessions)
    if freeze is not None:
        frozen = {
            "schema": "fast-decisions-v3-frozen/v1",
            "R*": {"spec": rule, "description": R.describe(rule), "intent_classifier": R.INTENT_CLASSIFIER,
                   "classifier_source": "evals/v3/rules.py", "decision": "host if any condition or scope gate; "
                                                                     "else cheap; decided once at session start"},
            "fit": summary["R*"]["fit"], "inputs": summary["inputs"],
            "train_metrics_fable": summary["headline"]["fable"]["rule_R*"]["train"],
            "test_metrics_fable": summary["headline"]["fable"]["rule_R*"]["test"],
            "d_jev_vs_R*": {h: dis[h]["jev_vs_R*"]["d"] for h in dis},
            "candidate_configs": {
                "C*_F": {"host": "claude-fable-5-1", "routing": "decide-once", "decider": "R*",
                         "h2_comparator_decider": "jev-1.13.0", "price_gate": True,
                         "cheap_max_workspace_files": 300, "effort_by_tier": {"cheap": "medium", "strong": "medium"},
                         "cheap_model": "claude-sonnet-5", "keep_on_host": None,
                         "predicted": summary["s1_predictions"]["C*_F"]},
                "C*_O": {"host": "claude-opus-5-5", "routing": "decide-once", "decider": "R*",
                         "price_gate": True, "expected_routing": "never (gate closed on Opus 5.5)",
                         "effort_by_tier": {"cheap": "medium", "strong": "medium"},
                         "predicted": summary["s1_predictions"]["C*_O"]},
            },
            "constants": {"sonnet_medium_factor": SONNET_MEDIUM_FACTOR, "fable_medium_factor": FABLE_MEDIUM_FACTOR,
                          "jev_usd_per_decision": JEV_USD_PER_DECISION},
        }
        write_json(freeze, frozen)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--freeze", type=Path, default=FROZEN)
    ap.add_argument("--no-freeze", action="store_true")
    ap.add_argument("--resamples", type=int, default=10_000)
    a = ap.parse_args(argv)
    s = run(a.out, None if a.no_freeze else a.freeze, a.resamples)
    print(json.dumps({"R*": s["R*"]["description"], "d": {h: s["disagreement"][h]["jev_vs_R*"]["d"]
                                                            for h in ("fable", "opus")}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
