#!/usr/bin/env python3
"""Preregistered analysis of effort-control-v1 (evals/paired/PREREGISTRATION-effort-control-v1.md), on `paired.py rows` output.

HE: plain Sonnet at medium effort (`sonnet_medium`) costs less than plain Sonnet at the provider default (`sonnet`, the anchor).
  * cost: geometric-mean ratio over scenarios; each scenario contributes the mean log cost ratio of its VALID pairs (valid,
    mechanism_engaged, cache_audit_clean, cost_valid); scenario-cluster bootstrap (resample scenarios with replacement),
    10,000 resamples, seed 20261005; 95% percentile CI; supported iff the CI upper bound < 1.0.
  * quality: turn-pass non-inferiority on ALL pairs (unfiltered): per scenario the mean delta_turn_pass (arm - anchor);
    same bootstrap; supported iff the CI lower bound > -0.05.
  HE is supported only if both hold. Secondary (exploratory, not concurrent): sonnet_medium vs main-v1 sticky-on-Sonnet.
Usage: python3 evals/paired_effort.py --rows <out>/rows [--main-sessions docs/evidence/2026-10-02-paired-campaign/data/sessions.jsonl] [--json out.json]
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


def read_jsonl(path) -> list:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def valid_cost_pair(p: dict) -> bool:
    return bool(p.get("valid") and p.get("mechanism_engaged") and p.get("cache_audit_clean") and p.get("cost_valid", True)
                and p.get("log_cost_ratio") is not None)


def scenario_means(pairs: list, field: str, keep) -> dict:
    by = defaultdict(list)
    for p in pairs:
        if p.get("arm") == ARM and keep(p) and p.get(field) is not None:
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


def analyse(pairs: list, *, seed: int = SEED, resamples: int = RESAMPLES) -> dict:
    cost = cluster_bootstrap(scenario_means(pairs, "log_cost_ratio", valid_cost_pair), seed=seed, resamples=resamples)
    qual = cluster_bootstrap(scenario_means(pairs, "delta_turn_pass", lambda p: True), seed=seed, resamples=resamples)
    out = {"hypothesis": "HE", "arm": ARM, "seed": seed, "resamples": resamples, "cost": {}, "quality": {}}
    if cost["mean"] is not None:
        out["cost"] = {"n_scenarios": cost["n_scenarios"], "geo_mean_ratio": math.exp(cost["mean"]),
                       "ci95": [math.exp(cost["lo"]), math.exp(cost["hi"])], "supported": math.exp(cost["hi"]) < 1.0}
    if qual["mean"] is not None:
        out["quality"] = {"n_scenarios": qual["n_scenarios"], "mean_delta_turn_pass": qual["mean"], "ci95": [qual["lo"], qual["hi"]],
                          "non_inferior": qual["lo"] > NONINFERIORITY, "margin": NONINFERIORITY}
    out["n_pairs"] = sum(1 for p in pairs if p.get("arm") == ARM)
    out["n_valid_cost_pairs"] = sum(1 for p in pairs if p.get("arm") == ARM and valid_cost_pair(p))
    out["HE_supported"] = bool(out["cost"].get("supported") and out["quality"].get("non_inferior"))
    return out


def vs_sticky(sessions: list, main_sessions: list, *, seed: int = SEED, resamples: int = RESAMPLES) -> dict:
    """EXPLORATORY (not concurrent): per scenario, mean cost of sonnet_medium vs main-v1 sticky sessions that decided `cheap`
    (sticky-on-Sonnet at medium). Same bootstrap; both sides tools-normalized cost, valid sessions only."""
    def per_scn(rows, keep):
        by = defaultdict(list)
        for r in rows:
            if keep(r) and r.get("cost_valid", True) and r.get("cost_usd_tools_normalized"):
                by[r["scenario_id"]].append(r["cost_usd_tools_normalized"])
        return {k: sum(v) / len(v) for k, v in by.items()}
    a = per_scn(sessions, lambda r: r.get("arm") == ARM)
    b = per_scn(main_sessions, lambda r: r.get("arm") == "sticky" and r.get("sticky_decision") == "cheap")
    both = {k: math.log(a[k] / b[k]) for k in a if k in b}
    res = cluster_bootstrap(both, seed=seed, resamples=resamples)
    if res["mean"] is None:
        return {"exploratory": True, "n_scenarios": 0}
    return {"exploratory": True, "n_scenarios": res["n_scenarios"], "geo_mean_ratio_medium_over_sticky_cheap": math.exp(res["mean"]),
            "ci95": [math.exp(res["lo"]), math.exp(res["hi"])]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, help="directory with pairs.jsonl and sessions.jsonl (paired.py rows)")
    ap.add_argument("--main-sessions", help="main-v1 sessions.jsonl for the exploratory comparison")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rows = Path(a.rows).expanduser()
    res = analyse(read_jsonl(rows / "pairs.jsonl"))
    if a.main_sessions:
        res["secondary_vs_main_v1_sticky_sonnet"] = vs_sticky(read_jsonl(rows / "sessions.jsonl"), read_jsonl(a.main_sessions))
    print(json.dumps(res, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
