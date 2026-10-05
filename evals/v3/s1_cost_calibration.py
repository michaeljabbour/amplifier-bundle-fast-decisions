#!/usr/bin/env python3
"""Cost-model calibration for the S1 design (evals/paired/holdout-v3.yaml) from the main-v1 sessions ($0, offline).

The paired harness estimates a session as  unit_usd_4turn[cell] x turn_scaling(turns) x type_factor[task type] x gap factor.
This script derives, from the 1,036 main-v1 sessions (docs/evidence/2026-10-02-paired-campaign/data/sessions.jsonl,
cost_usd_tools_normalized):

  1. type factors: per host, the mean plain-anchor cost per turn-scale unit by task type relative to the host's overall mean
     (n per type is small: review 8, explain 6, docs 8 per host), then averaged over the two hosts;
  2. units: for each base cell (plain Fable, plain Opus, plain Sonnet) the mean of cost / (turn scaling x type factor x gap
     factor), so that the harness reproduces the main-v1 mean cost on the main-v1 panel.

Run:  python3 evals/v3/s1_cost_calibration.py            (prints; --json PATH writes the numbers)
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "evals"), str(REPO / "scripts"), str(REPO)]
import paired  # noqa: E402

SESSIONS = REPO / "docs/evidence/2026-10-02-paired-campaign/data/sessions.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    design = paired.load_design(REPO / "evals/paired/main-v1.yaml")
    specs = {s.id: s for s in paired.load_specs(design)}
    cm = design["cost_model"]
    rows = [json.loads(line) for line in SESSIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("cost_valid", True) and r["status"] != "infra_fail"]

    def tscale(r):
        s = specs[r["scenario_id"]]
        return paired._turn_scale(cm["turn_scaling"], len(s.turns)) * (1 + cm["long_gap_extra_fraction"] * s.n_long_gaps)

    # 1. type factors from the plain anchors
    per = collections.defaultdict(list)
    for r in rows:
        if r["arm"] == "anchor":
            per[(r["host"], r["task_type"])].append(r["cost_usd_tools_normalized"] / tscale(r))
    rel = collections.defaultdict(list)
    for host in ("fable", "opus"):
        allv = [v for (h, _), vs in per.items() if h == host for v in vs]
        for (h, t), vs in per.items():
            if h == host:
                rel[t].append(st.mean(vs) / st.mean(allv))
    type_factor = {t: round(st.mean(v), 3) for t, v in sorted(rel.items())}
    type_factor["knowledge"] = 1.0           # a family label, never a task type of a holdout-v3 scenario

    # 2. units from the base cells with the NEW type factors
    def unit(host, arm):
        v = [r["cost_usd_tools_normalized"] / (tscale(r) * type_factor[r["task_type"]])
             for r in rows if r["host"] == host and r["arm"] == arm]
        return round(st.mean(v), 3), len(v)
    units = {"plain": unit("fable", "anchor"), "plain-opus": unit("opus", "anchor"), "plain-sonnet": unit("any", "sonnet")}
    out = {"type_factor": type_factor, "unit_usd_4turn": {k: {"usd": u, "n": n} for k, (u, n) in units.items()},
           "n_by_type_host": {f"{h}/{t}": len(v) for (h, t), v in sorted(per.items())}}
    print(json.dumps(out, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
