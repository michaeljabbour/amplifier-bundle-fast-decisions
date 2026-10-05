#!/usr/bin/env python3
"""A3 inputs: a PROVISIONAL real-workload projection (docs/design/v3/PLAN.md, section A3; RQ11). Offline, $0.

S1 has not run, so this is not the A3 result. It assembles the projection inputs from A1 (the production workload the
observatory recorded: host-model spend mix, the start-tier decision mix) and A0 / the effort studies (per-host ratios),
and shows what they imply for the GOAL target (<= 0.50x cost), with every ratio labelled measured / estimated / prior.

    projected ratio = sum_h spend_share_h * ratio_h            (spend shares from recorded slow_end cost, production)
    Fable what-if    = scope_share * host_ratio + (1 - scope_share) * routed_ratio

Usage: python3 -m evals.v3.a3_projection [--a0 DIR] [--a1 DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.v3.common import REPO_ROOT, write_csv, write_json

BASE = REPO_ROOT / "docs" / "evidence" / "2026-10-v3-offline"
WASTE_CENSUS_30D_USD = 13924.0     # docs/evidence/2026-09-25/waste-census/README.md (2026-08-26..09-25)
GOAL_COST = 0.50

# per-host ratio vs that host's plain default, by config: (low, point, high, label)
RATIOS = {
    "opus": {"shipped (gate closed, strong default)": (1.0, 1.0, 1.0, "expected, unmeasured (S1 H3)"),
             "C*_O (strong medium)": (0.821, 0.84, 0.860, "prior band from Sonnet 0.821 / Fable 0.860; unmeasured")},
    "sonnet": {"shipped (strong default)": (1.0, 1.0, 1.0, "no lever applies to a Sonnet host by default"),
               "plain medium": (0.781, 0.821, 0.861, "measured, preregistered (2026-10-05-effort-control)")},
    "other": {"shipped (strong default)": (1.0, 1.0, 1.0, "no lever"), "plain medium": (1.0, 1.0, 1.0, "no data")},
}


def host_family(model: str) -> str:
    m = (model or "").lower()
    return "opus" if "opus" in m else "sonnet" if "sonnet" in m else "fable" if "fable" in m else "other"


def project(workload: list[dict], start_tier: list[dict], a0: dict) -> dict:
    prod = [w for w in workload if w["traffic"] == "production"]
    spend = {}
    for w in prod:
        spend[host_family(w["host_model"])] = spend.get(host_family(w["host_model"]), 0.0) + w["recorded_cost_usd"]
    total = sum(spend.values())
    shares = {h: v / total for h, v in spend.items()} if total else {}
    scen = {}
    for cfg_o, cfg_s in (("shipped (gate closed, strong default)", "shipped (strong default)"),
                         ("C*_O (strong medium)", "plain medium")):
        name = "shipped" if cfg_o.startswith("shipped") else "C*"
        lo = pt = hi = 0.0
        for h, sh in shares.items():
            r = RATIOS["opus"][cfg_o] if h == "opus" else RATIOS["sonnet"][cfg_s] if h == "sonnet" else (1, 1, 1, "")
            lo, pt, hi = lo + sh * r[0], pt + sh * r[1], hi + sh * r[2]
        scen[name] = {"ratio": pt, "band": [lo, hi], "meets_goal_cost": hi <= GOAL_COST}
    st = [r for r in start_tier if r["traffic"] == "production"]
    n = sum(r["sessions"] for r in st)
    scope = sum(r["sessions"] for r in st if str(r["reason_code"]).startswith("scope_"))
    cheap = sum(r["sessions"] for r in st if str(r["reason_code"]).endswith("_cheap"))
    hf = a0["s1_predictions"]["C*_F"]
    routed = a0["headline"]["fable"]["always_route"]["all"]["gm_cost_ratio"]
    scope_share = scope / n if n else None
    what_if = None
    if scope_share is not None:
        what_if = {"routed_ratio_main_v1": routed, "host_ratio_strong_medium": 0.860,
                   "ratio_R*_strong_medium": scope_share * 0.860 + (1 - scope_share) * routed,
                   "ratio_R*_strong_default": scope_share * 1.0 + (1 - scope_share) * routed,
                   "label": "ESTIMATED: main-v1 (small workspaces) routed ratio applied to the production share the "
                            "scope gate would leave routable; assumes the owner hosted on Fable"}
    return {
        "label": "PROVISIONAL (pre-S1) projection inputs; not the A3 result",
        "production_recorded_spend_usd_by_host": spend, "spend_share_by_host": shares,
        "waste_census_30d_usd": WASTE_CENSUS_30D_USD,
        "start_tier_production": {"sessions": n, "scope_gate_share": scope_share,
                                  "routed_cheap_share": cheap / n if n else None},
        "main_v1_comparison": {"jev_route_share_main_v1_fable": a0["headline"]["fable"]["jev_recorded"]["all"]["route_share"],
                               "C*_F_predicted": {k: hf[k] for k in ("gm_cost_ratio", "gm_cost_ratio_ci95")}},
        "projection_on_recorded_mix": scen, "fable_host_what_if": what_if,
        "monthly_usd_at_waste_census_scale": {k: {"projected_usd": WASTE_CENSUS_30D_USD * v["ratio"],
                                                  "saved_usd": WASTE_CENSUS_30D_USD * (1 - v["ratio"])}
                                              for k, v in scen.items()},
        "ratios_used": {h: {c: {"low": r[0], "point": r[1], "high": r[2], "label": r[3]} for c, r in v.items()}
                        for h, v in RATIOS.items()},
        "goal_cost_target": GOAL_COST,
    }


def run(a0_dir: Path = BASE / "a0-counterfactual", a1_dir: Path = BASE / "a1-observatory",
        out: Path = BASE / "a3-projection-inputs") -> dict:
    a0 = json.loads((a0_dir / "summary.json").read_text())
    a1 = json.loads((a1_dir / "observatory-summary.json").read_text())
    res = project(a1["a3_inputs"]["workload"], a1["a3_inputs"]["start_tier_first_per_session"], a0)
    write_json(out / "projection.json", res)
    write_csv(out / "projection.csv", [{"scenario": k, "ratio": v["ratio"], "low": v["band"][0], "high": v["band"][1],
                                        "meets_goal_cost": v["meets_goal_cost"]}
                                       for k, v in res["projection_on_recorded_mix"].items()])
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a0", type=Path, default=BASE / "a0-counterfactual")
    ap.add_argument("--a1", type=Path, default=BASE / "a1-observatory")
    ap.add_argument("--out", type=Path, default=BASE / "a3-projection-inputs")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.a0, a.a1, a.out), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
