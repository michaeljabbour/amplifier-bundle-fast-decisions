#!/usr/bin/env python3
"""Markdown tables for the README, computed from each split's manifest/requests/run/summary.

    PYTHONPATH=src:. python3 docs/evidence/2026-10-04-clef-judges/tables.py docs/evidence/2026-10-04-clef-judges

Per-case majority over the 3 repetitions under the primary policy (bundle-read-shortcut), every manifest case in
the denominator, invalid rows counted as fallbacks. Latency is the client-side wall time of all valid requests.
Nothing here changes a verdict; it re-reads numbers the summary already holds.
"""
import json
import sys
from pathlib import Path

from evals.judge_bench import scoring, stats
from evals.judge_bench.summarize import Ctx

ARMS = ("clef", "clef-flash", "jev-1.13")
SPLITS = ("dev", "holdout", "trace-dev", "trace-holdout")


def load(split_dir):
    manifest = json.loads((split_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(x) for x in (split_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    run = json.loads((split_dir / "run.json").read_text(encoding="utf-8"))
    summary = json.loads((split_dir / "summary.json").read_text(encoding="utf-8"))
    return manifest, rows, run, summary


def f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def main(root):
    root = Path(root)
    policy = scoring.resolve_policy("bundle-read-shortcut")
    for split in SPLITS:
        manifest, rows, run, summary = load(root / split)
        ctx = Ctx(rows, manifest["cases"], manifest.get("tags") or {}, run["specs"])
        n = len(ctx.order_ids)
        print(f"### {split} ({n} cases, 3 reps x 2 option orders, label: {summary['label']})\n")
        print("| arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions | mean in tokens |")
        print("|---|---|---|---|---|---|---|---|---|")
        for arm in ARMS:
            o = ctx.outcomes(arm, policy)
            ok = sum(v["correct"] for v in o.values())
            wa = sum(v["automatic_error"] for v in o.values())
            auto = sum(v["automatic"] for v in o.values())
            arm_rows = [r for r in rows if r["arm"] == arm and r["id"] in ctx.by_case]
            invalid = sum(not r["valid"] for r in arm_rows)
            lat = [r["elapsed_ms"] for r in arm_rows if r["valid"]]
            cost = [rep["cost"]["usd_per_1m_decisions"] for rep in summary["arms"][arm]["reps"].values()]
            tokens = [rep["cost"]["mean_input_tokens"] for rep in summary["arms"][arm]["reps"].values()]
            lo, hi = stats.wilson(wa, n)
            print(f"| {arm} | {ok}/{n} = {ok / n:.3f} | {wa}/{n} = {wa / n:.3f} (Wilson upper {hi:.3f}) | "
                  f"{auto}/{n} = {auto / n:.3f} | {invalid}/{len(arm_rows)} | {stats.nearest_rank(lat, .5):.0f} | "
                  f"{stats.nearest_rank(lat, .95):.0f} | {sum(cost) / len(cost):.1f} | {sum(tokens) / len(tokens):.0f} |")
        print()
        print("Paired contrasts (McNemar exact on per-case majority; Holm over the rule-1 family of the two new arms; "
              "diff = first minus second):\n")
        print("| contrast | metric | first | second | diff [95% CI] | first only / second only | p | Holm p |")
        print("|---|---|---|---|---|---|---|---|")
        rule1 = summary["decisions"]["rule1_default_judge"]["candidates"]
        for arm in ("clef", "clef-flash"):
            for metric, key in (("accuracy", "accuracy"), ("wrong automatic", "wrong_automatic")):
                d = rule1[arm][key]
                lo, hi = d["diff_ci95"]
                print(f"| {arm} vs jev-1.13 | {metric} | {f(d['rate_candidate'])} | {f(d['rate_baseline'])} | "
                      f"{d['diff']:+.3f} [{lo:+.3f}, {hi:+.3f}] | {d['candidate_only']} / {d['baseline_only']} | "
                      f"{d['p']:.3f} | {d['p_holm']:.3f} |")
        for c in summary["pairwise"]["contrasts"]["correct"]:
            if (c["a"], c["b"]) == ("clef", "clef-flash"):
                d = c
                print(f"| clef vs clef-flash | accuracy | {f(d['rate_a'])} | {f(d['rate_b'])} | {d['diff']:+.3f} "
                      f"[{d['diff_ci95'][0]:+.3f}, {d['diff_ci95'][1]:+.3f}] | {d['a_only']} / {d['b_only']} | "
                      f"{d['p']:.3f} | {d['p_holm']:.3f} (pairwise family) |")
        print()
        print("Rule-1 (replace Jev as default) checks, all against the preregistered thresholds:\n")
        print("| arm | non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | "
              "superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |")
        print("|---|---|---|---|---|---|---|---|")
        for arm in ("clef", "clef-flash"):
            r = rule1[arm]
            print(f"| {arm} | {r['non_inferior_accuracy']} | {r['non_inferior_wrong_auto']} | "
                  f"{', '.join(r['superior_on']) or 'none'} | {r['p95_ok']} ({r['p95_ms']:.0f}) | "
                  f"{r['cost_ok']} (${r['cost_usd_per_1m']:.0f} vs ${r['cost_usd_per_1m_jev']:.0f}) | "
                  f"{r['valid_ok']} | {r['replaces_default']} |")
        print()


if __name__ == "__main__":
    main(sys.argv[1])
