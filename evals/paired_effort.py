#!/usr/bin/env python3
"""Preregistered analysis of effort-control-v1 (evals/paired/PREREGISTRATION-effort-control-v1.md), on `paired.py rows` output.

HE: plain Sonnet at medium effort (`sonnet_medium`) costs less than plain Sonnet at the provider default (`sonnet`, the anchor).
  * cost: geometric-mean ratio over scenarios; each scenario contributes the mean log cost ratio of its VALID pairs (valid,
    mechanism_engaged, cache_audit_clean, cost_valid); scenario-cluster bootstrap (resample scenarios with replacement),
    10,000 resamples, seed 20261005; 95% percentile CI; supported iff the CI upper bound < 1.0.
  * quality: turn-pass non-inferiority on ALL pairs (unfiltered): per scenario the mean delta_turn_pass (arm - anchor);
    same bootstrap; supported iff the CI lower bound > -0.05.
  HE is supported only if both hold. Secondary (exploratory, not concurrent): sonnet_medium vs main-v1 sticky-on-Sonnet.
Parametrized by --design: `sonnet` (default, effort-control-v1, hypothesis HE, seed 20261005) or `fable` (effort-control-fable-v1,
hypothesis HF, arm fable_medium vs fable, seed 20261006, plus exploratory McNemar on the final hidden-test pass, per-task-type
turn-pass deltas, and fable_medium vs main-v1 sticky (Fable host) and anchor (Fable host)).
Usage: python3 evals/paired_effort.py [--design sonnet|fable] --rows <out>/rows [--main-sessions docs/evidence/2026-10-02-paired-campaign/data/sessions.jsonl] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

SEED = 20261005
RESAMPLES = 10_000
ARM = "sonnet_medium"
NONINFERIORITY = -0.05
CONFIGS = {"sonnet": {"arm": "sonnet_medium", "anchor": "sonnet", "seed": 20261005, "hypothesis": "HE"},
           "fable": {"arm": "fable_medium", "anchor": "fable", "seed": 20261006, "hypothesis": "HF"}}


def read_jsonl(path) -> list:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def valid_cost_pair(p: dict) -> bool:
    return bool(p.get("valid") and p.get("mechanism_engaged") and p.get("cache_audit_clean") and p.get("cost_valid", True)
                and p.get("log_cost_ratio") is not None)


def scenario_means(pairs: list, field: str, keep, arm: str = ARM) -> dict:
    by = defaultdict(list)
    for p in pairs:
        if p.get("arm") == arm and keep(p) and p.get(field) is not None:
            by[p["scenario_id"]].append(p[field])
    return {sid: sum(v) / len(v) for sid, v in by.items()}


def cluster_bootstrap(means: dict, *, seed: int = SEED, resamples: int = RESAMPLES) -> dict:
    """Percentile 95% CI of the mean of per-scenario values, resampling scenarios (the cluster) with replacement."""
    vals = [means[k] for k in sorted(means)]
    n = len(vals)
    if n == 0:
        return {"n_scenarios": 0, "mean": None, "lo": None, "hi": None}
    rng = random.Random(seed)
    stats = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return {"n_scenarios": n, "mean": sum(vals) / n, "lo": stats[int(0.025 * resamples)], "hi": stats[int(0.975 * resamples) - 1]}


def analyse(pairs: list, *, seed: int | None = None, resamples: int = RESAMPLES, design: str = "sonnet") -> dict:
    cfg = CONFIGS[design]
    arm = cfg["arm"]
    seed = cfg["seed"] if seed is None else seed
    cost = cluster_bootstrap(scenario_means(pairs, "log_cost_ratio", valid_cost_pair, arm), seed=seed, resamples=resamples)
    qual = cluster_bootstrap(scenario_means(pairs, "delta_turn_pass", lambda p: True, arm), seed=seed, resamples=resamples)
    out = {"hypothesis": cfg["hypothesis"], "arm": arm, "seed": seed, "resamples": resamples, "cost": {}, "quality": {}}
    if cost["mean"] is not None:
        out["cost"] = {"n_scenarios": cost["n_scenarios"], "geo_mean_ratio": math.exp(cost["mean"]),
                       "ci95": [math.exp(cost["lo"]), math.exp(cost["hi"])], "supported": math.exp(cost["hi"]) < 1.0}
    if qual["mean"] is not None:
        out["quality"] = {"n_scenarios": qual["n_scenarios"], "mean_delta_turn_pass": qual["mean"], "ci95": [qual["lo"], qual["hi"]],
                          "non_inferior": qual["lo"] > NONINFERIORITY, "margin": NONINFERIORITY}
    out["n_pairs"] = sum(1 for p in pairs if p.get("arm") == arm)
    out["n_valid_cost_pairs"] = sum(1 for p in pairs if p.get("arm") == arm and valid_cost_pair(p))
    out[f"{cfg['hypothesis']}_supported"] = bool(out["cost"].get("supported") and out["quality"].get("non_inferior"))
    return out


def mcnemar(sessions: list, design: str = "fable") -> dict:
    """EXPLORATORY: exact McNemar on the final hidden-test pass of the arm vs its anchor, matched on (scenario, rep)."""
    cfg = CONFIGS[design]
    by = defaultdict(dict)
    for r in sessions:
        if r.get("arm") in (cfg["arm"], cfg["anchor"]) and r.get("final_state_pass") is not None:
            by[(r["scenario_id"], r["rep"])][r["arm"]] = bool(r["final_state_pass"])
    b = sum(1 for v in by.values() if v.get(cfg["arm"]) is True and v.get(cfg["anchor"]) is False)    # only the medium arm passed
    c = sum(1 for v in by.values() if v.get(cfg["arm"]) is False and v.get(cfg["anchor"]) is True)    # only the default arm passed
    n = b + c
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n)
    both = sum(1 for v in by.values() if v.get(cfg["arm"]) and v.get(cfg["anchor"]))
    return {"exploratory": True, "n_matched": sum(1 for v in by.values() if len(v) == 2), "both_pass": both,
            "only_medium_passes": b, "only_default_passes": c, "exact_p_two_sided": p}


def per_task_type(pairs: list, design: str = "fable") -> dict:
    """EXPLORATORY: mean per-scenario turn-pass delta by task type (all pairs, unfiltered)."""
    arm = CONFIGS[design]["arm"]
    by_scn = defaultdict(list)
    types = {}
    for p in pairs:
        if p.get("arm") == arm and p.get("delta_turn_pass") is not None:
            by_scn[p["scenario_id"]].append(p["delta_turn_pass"])
            types[p["scenario_id"]] = p.get("task_type")
    by_type = defaultdict(list)
    for sid, v in by_scn.items():
        by_type[types[sid]].append(sum(v) / len(v))
    return {t: {"n_scenarios": len(v), "mean_delta_turn_pass": sum(v) / len(v)} for t, v in sorted(by_type.items(), key=lambda kv: str(kv[0]))}


def vs_main(sessions: list, main_sessions: list, *, arm: str, keep_main, seed: int = SEED, resamples: int = RESAMPLES) -> dict:
    """EXPLORATORY (not concurrent): per scenario, mean tools-normalized cost of ``arm`` vs the main-v1 sessions selected by
    ``keep_main``; geometric-mean ratio with the scenario-cluster bootstrap. Valid sessions only."""
    def per_scn(rows, keep):
        by = defaultdict(list)
        for r in rows:
            if keep(r) and r.get("cost_valid", True) and r.get("cost_usd_tools_normalized"):
                by[r["scenario_id"]].append(r["cost_usd_tools_normalized"])
        return {k: sum(v) / len(v) for k, v in by.items()}
    a = per_scn(sessions, lambda r: r.get("arm") == arm)
    b = per_scn(main_sessions, keep_main)
    both = {k: math.log(a[k] / b[k]) for k in a if k in b}
    res = cluster_bootstrap(both, seed=seed, resamples=resamples)
    if res["mean"] is None:
        return {"exploratory": True, "n_scenarios": 0}
    return {"exploratory": True, "n_scenarios": res["n_scenarios"], "geo_mean_ratio": math.exp(res["mean"]),
            "ci95": [math.exp(res["lo"]), math.exp(res["hi"])]}


def vs_sticky(sessions: list, main_sessions: list, *, seed: int = SEED, resamples: int = RESAMPLES) -> dict:
    """EXPLORATORY (sonnet design): sonnet_medium vs main-v1 sticky sessions that decided `cheap` (sticky-on-Sonnet at medium)."""
    r = vs_main(sessions, main_sessions, arm=ARM, keep_main=lambda x: x.get("arm") == "sticky" and x.get("sticky_decision") == "cheap",
                seed=seed, resamples=resamples)
    if "geo_mean_ratio" in r:
        r["geo_mean_ratio_medium_over_sticky_cheap"] = r.pop("geo_mean_ratio")
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", choices=sorted(CONFIGS), default="sonnet")
    ap.add_argument("--rows", required=True, help="directory with pairs.jsonl and sessions.jsonl (paired.py rows)")
    ap.add_argument("--main-sessions", help="main-v1 sessions.jsonl for the exploratory comparisons")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rows = Path(a.rows).expanduser()
    pairs = read_jsonl(rows / "pairs.jsonl")
    res = analyse(pairs, design=a.design)
    if a.design == "sonnet":
        if a.main_sessions:
            res["secondary_vs_main_v1_sticky_sonnet"] = vs_sticky(read_jsonl(rows / "sessions.jsonl"), read_jsonl(a.main_sessions))
    else:
        sess = read_jsonl(rows / "sessions.jsonl")
        res["exploratory_mcnemar_final_pass"] = mcnemar(sess, a.design)
        res["exploratory_per_task_type_turn_pass"] = per_task_type(pairs, a.design)
        if a.main_sessions:
            main = read_jsonl(a.main_sessions)
            arm = CONFIGS[a.design]["arm"]
            res["secondary_vs_main_v1_sticky_fable_host"] = vs_main(sess, main, arm=arm,
                                                                    keep_main=lambda x: x.get("arm") == "sticky" and x.get("host") == "fable")
            res["secondary_vs_main_v1_anchor_fable_host"] = vs_main(sess, main, arm=arm,
                                                                    keep_main=lambda x: x.get("arm") == "anchor" and x.get("host") == "fable")
    print(json.dumps(res, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
