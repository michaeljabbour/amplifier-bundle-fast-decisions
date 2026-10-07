#!/usr/bin/env python3
"""Markdown tables for the README and summary.json, computed from each split's manifest/requests/run/summary.

    PYTHONPATH=src:. python3 docs/evidence/2026-10-06-openai-decisions/tables.py docs/evidence/2026-10-06-openai-decisions

Per-case majority over the 3 repetitions under the primary policy (bundle-read-shortcut: 0.90 and 0.20 margin and
the bundle's real 3 s deadline, `decision_timeout`), every manifest case in the denominator, invalid rows counted as
fallbacks. The same answers are ALSO scored with no deadline (the transport timeout was 30 s, so slow answers are
recorded). Latency is client wall time of all valid requests; `server_ms` is the `openai-processing-ms` header.
Writes <root>/summary.json. Nothing here changes a verdict; it re-reads numbers the summary already holds.
"""
import json
import sys
from pathlib import Path

from evals.judge_bench import scoring, stats
from evals.judge_bench.summarize import Ctx

ARMS = ("luna-decisions", "jev-1.13")
SPLITS = ("dev", "holdout", "trace-dev", "trace-holdout")
DESCRIPTION = ("OpenAI Decisions API (POST /v1/decisions, model gpt-6-luna, public beta) as a post-hoc judge arm "
               "(luna-decisions) against the in-run Jev reference (jev-1.13), 3 repetitions x 2 option orders on "
               "dev (90), holdout (63), trace-dev (21), trace-holdout (42). Primary policy bundle-read-shortcut "
               "(0.90 / 0.20 margin / 3 s deadline), per-case majority over repetitions, every case in the "
               "denominator. Latency is client wall time from a Mac over the network, not server time. "
               "holdout and trace-holdout are post-hoc for luna-decisions: no preregistered verdict applies.")


def load(split_dir):
    manifest = json.loads((split_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(x) for x in (split_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    run = json.loads((split_dir / "run.json").read_text(encoding="utf-8"))
    summary = json.loads((split_dir / "summary.json").read_text(encoding="utf-8"))
    return manifest, rows, run, summary


def totals(ctx, arm, policy):
    o = ctx.outcomes(arm, policy)
    return (sum(v["correct"] for v in o.values()), sum(v["automatic"] for v in o.values()),
            sum(v["automatic_error"] for v in o.values()))


def pct(vals, q):
    v = stats.nearest_rank(vals, q)
    return None if v is None else round(v, 1)


def main(root):
    root = Path(root)
    policy = scoring.resolve_policy("bundle-read-shortcut")
    open_policy = dict(policy, name="bundle-read-shortcut+no-deadline", timeout_ms=float("inf"))
    out = {"description": DESCRIPTION, "rows": [], "no_deadline_rows": [], "contrasts": [], "latency": [],
           "invalid": []}
    for split in SPLITS:
        manifest, rows, run, summary = load(root / split)
        ctx = Ctx(rows, manifest["cases"], manifest.get("tags") or {}, run["specs"])
        n = len(ctx.order_ids)
        print(f"### {split} ({n} cases, 3 reps x 2 option orders, label: {summary['label']})\n")
        print("| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |")
        print("|---|---|---|---|---|---|---|---|---|")
        for arm in ARMS:
            arm_rows = [r for r in rows if r["arm"] == arm and r["id"] in ctx.by_case]
            invalid = [r for r in arm_rows if not r["valid"]]
            lat = [r["elapsed_ms"] for r in arm_rows if r["valid"]]
            srv = [r["timing"]["server_ms"] for r in arm_rows if r["valid"] and (r.get("timing") or {}).get("server_ms")]
            cost = [rep["cost"]["usd_per_1m_decisions"] for rep in summary["arms"][arm]["reps"].values()]
            usd = sum(cost) / len(cost)
            for view, pol, bucket in (("3 s deadline", policy, "rows"), ("no deadline", open_policy, "no_deadline_rows")):
                ok, auto, wa = totals(ctx, arm, pol)
                lo, hi = stats.wilson(wa, n)
                print(f"| {arm} | {view} | {ok}/{n} = {ok / n:.3f} | {wa}/{n} = {wa / n:.3f} (Wilson upper {hi:.3f}) | "
                      f"{auto}/{n} = {auto / n:.3f} | {len(invalid)}/{len(arm_rows)} | {pct(lat, .5):.0f} | "
                      f"{pct(lat, .95):.0f} | {usd:.1f} |")
                out[bucket].append({"split": split, "arm": arm, "accuracy": round(ok / n, 4), "n": n,
                                    "wrong_automatic": round(wa / n, 4), "coverage": round(auto / n, 4),
                                    "p50_ms": pct(lat, .5), "p95_ms": pct(lat, .95), "usd_per_1m": round(usd, 2)})
            out["latency"].append({
                "split": split, "arm": arm, "n_valid": len(lat), "n_requests": len(arm_rows),
                "client_wall_ms": {"p50": pct(lat, .5), "p90": pct(lat, .9), "p95": pct(lat, .95),
                                   "p99": pct(lat, .99), "max": pct(lat, 1.0), "min": pct(lat, 0.0)},
                "server_ms": {"n": len(srv), "p50": pct(srv, .5), "p95": pct(srv, .95), "max": pct(srv, 1.0)},
                "valid_over_3000ms": sum(x > 3000 for x in lat),
                "share_valid_over_3000ms": round(sum(x > 3000 for x in lat) / len(lat), 4) if lat else None})
            out["invalid"].extend({"split": split, "arm": arm, "rep": r["rep"], "id": r["id"],
                                   "elapsed_ms": round(r["elapsed_ms"]), "error": r.get("error")} for r in invalid)
        print()
        print("Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; "
              "diff = luna-decisions minus jev-1.13):\n")
        print("| metric | luna-decisions | jev-1.13 | diff [95% CI] | luna only / jev only | p | Holm p |")
        print("|---|---|---|---|---|---|---|")
        rule1 = summary["decisions"]["rule1_default_judge"]["candidates"]["luna-decisions"]
        for metric, key in (("accuracy", "accuracy"), ("wrong automatic", "wrong_automatic")):
            d = rule1[key]
            lo, hi = d["diff_ci95"]
            print(f"| {metric} | {d['rate_candidate']:.3f} | {d['rate_baseline']:.3f} | {d['diff']:+.3f} "
                  f"[{lo:+.3f}, {hi:+.3f}] | {d['candidate_only']} / {d['baseline_only']} | {d['p']:.3f} | "
                  f"{d['p_holm']:.3f} |")
            out["contrasts"].append({"split": split, "a": "luna-decisions", "b": "jev-1.13", "metric": metric,
                                     "a_rate": d["rate_candidate"], "b_rate": d["rate_baseline"], "diff": d["diff"],
                                     "diff_ci95": d["diff_ci95"], "a_only": d["candidate_only"],
                                     "b_only": d["baseline_only"], "p": d["p"], "p_holm": d["p_holm"]})
        print()
        print("Rule-1 (replace Jev as default) checks against the preregistered thresholds:\n")
        print("| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | "
              "p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |")
        print("|---|---|---|---|---|---|---|")
        r = rule1
        print(f"| {r['non_inferior_accuracy']} | {r['non_inferior_wrong_auto']} | {', '.join(r['superior_on']) or 'none'} | "
              f"{r['p95_ok']} ({r['p95_ms']:.0f}) | {r['cost_ok']} (${r['cost_usd_per_1m']:.0f} vs "
              f"${r['cost_usd_per_1m_jev']:.0f}) | {r['valid_ok']} | {r['replaces_default']} |")
        print()
    (root / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
