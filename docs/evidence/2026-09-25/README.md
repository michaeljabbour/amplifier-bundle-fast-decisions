# Evidence: re-validation of the corrected default (2026-09-25)

Summaries only: no prompts, no patches, no final assistant messages, no secrets; home paths shown as `~`.
`MANIFEST.json` holds a SHA-256 for every file here.

| Path | What | Used for |
|---|---|---|
| `s1/reval-s1-dev/` | S1 dev, 12 tasks x 2 reps: plain, plain-sonnet, orch-default (Fable host), plain-opus, orch-default-opus; per-run results, comparisons, gates, `mechanism-summary.json` | README / report tuning-task numbers (0.559x/0.484x Fable; 0.825x/0.895x Opus) |
| `s1/reval-s1-dev-batch2/` | Replicate, 1 rep (launched as a reversed-order check; ran in declared order -- see NOTE.md) | 0.574x/0.460x Fable; 0.757x/0.822x Opus |
| `s1/prereg2-s1-holdout/` | Holdout (criteria per STUDY-DESIGN §8; see Limits on the preregistration timestamp), 8 unseen tasks x 3 reps, same five cells, with `PREREGISTRATION.md` | Headline: Fable 0.42x [0.35-0.50] / 0.50x, 8/8, p = 0.0078, confirmed; Opus 1.01x / 0.98x, no effect |
| `difficulty/difficulty-report-*.json` | Judge re-test on the same 110-item dataset (ids, labels, p(complex), latency; no texts) | "each landed within a point or two" |
| `routing-cost-check.json` | Provider cost of every live call vs Sonnet 5 / Opus 5.5 list prices (identifies the served model) | RESULTS follow-ups |
| `surface-checks.json` | One easy prompt each in the CLI, amplifier-runtime serve and the TUI | README/report surface claims |
| `startup/startup-profile.json` | cProfile of one trivial request, top items, plus two unprofiled runs | Report Fig. 8 |

Candidate commit for all S1 runs: `52e0d29` (frozen snapshot; see each `manifest.json`).

## Recomputing

- Time/cost ratio: geometric mean over tasks of (median candidate / median anchor) using `runs/**/result.json`
  `exec_time_ms` and `cost_usd`, excluding `infrastructure_failure` runs. The pipeline's own `results.json` uses a
  different cost estimator (holdout Fable: 0.54x vs 0.50x here).
- Sign test: two-sided binomial over per-task faster/slower. CI: bootstrap over tasks.
- Mechanism: `mechanism-summary.json` counts `difficulty_judged` and `model_routed` reasons in the per-run event files.

## Limits

- One Apple-silicon Mac, provider `anthropic`, cheap model `claude-sonnet-5`.
- Cells ran in `cells.yaml` order, back to back (~10 min apart); within-batch order was not randomized.
- Provider-reported cost is an estimate, not billing.
- PREREGISTRATION.md states 03:35 UTC; the first holdout run started at 03:29:22 UTC. The local original was created at
  03:29:08 UTC (filesystem birth time, unchanged since); it was committed together with the results. The decision
  criteria are the standing rule in evals/STUDY-DESIGN.md §8, committed before this study.
- `routing-cost-check.json` and `surface-checks.json` come from live sessions on the author's machine (event
  summaries only).
