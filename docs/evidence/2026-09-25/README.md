# Evidence: re-validation of the corrected default (2026-09-25)

Summaries only: no prompts, no patches, no final assistant messages, no secrets; home paths shown as `~`.
`MANIFEST.json` holds a SHA-256 for every file here.

| Path | What | Used for |
|---|---|---|
| `s1/reval-s1-dev/` | S1 dev, 12 tasks x 2 reps: plain, plain-sonnet, orch-default (Fable host), plain-opus, orch-default-opus; per-run results, comparisons, gates, `mechanism-summary.json` | README / report tuning-task numbers (0.559x/0.484x Fable; 0.825x/0.895x Opus) |
| `s1/reval-s1-dev-batch2/` | Replicate, 1 rep (launched as a reversed-order check; ran in declared order -- see NOTE.md) | 0.574x/0.460x Fable; 0.757x/0.822x Opus |
| `s1/prereg2-s1-holdout/` | Holdout (criteria per STUDY-DESIGN §8; see Limits on the preregistration timestamp), 8 unseen tasks x 3 reps, same five cells, with `PREREGISTRATION.md` | Headline: Fable 0.42x [0.35-0.50] / 0.50x, 8/8, p = 0.0078, passed all 6 criteria on a reused holdout (not a confirmation; see Limits); Opus 1.01x / 0.98x, no measurable gain |
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
- Holdout reuse: `prereg2-s1-holdout` used the same 8 task IDs as the 2026-09-24 `prereg-s1-holdout`, and the
  corrected default was designed after that holdout's results were seen. STUDY-DESIGN §3/§8 spend a holdout once and
  require a new split for a changed configuration, so the Fable result is not a confirmation. It is being re-run on a
  fresh 12-task split, `holdout2` (`scripts/battery_tasks.py`; 4 of its tasks are longer).
- Cell order: all three batches ran cells in the fixed order plain → plain-sonnet → orch-default → plain-opus →
  orch-default-opus, plain always first, back to back (~10 min apart). Runs share the provider's prompt cache across
  cells (native events show large `cache_read` on the first call of a run), so order can bias time and cost.
  `evals/run.py` now shuffles cell order per rep (seeded, recorded in manifest `invocation.cell_order`;
  `--cell-order declared` reproduces the old behaviour).
- One raw run failed on infrastructure and was retried per R6: `reval-s1-dev` plain-opus r2 `edit_dequeue_validation`
  attempt a1 (`infrastructure_failure: true`, `no_result_json`); the counted result is attempt a2 (passed).
- `result.json` does not record which model served each call; only per-batch counts (e.g. Opus holdout: 18 of 24
  turns judged easy and started on Sonnet). Opus conclusions rely on these aggregate counts. New runs record `routing`
  (turn decisions, per-call requested model/effort, provider-reported model and cost under
  `native_served_model_counts` / `native_cost_usd_by_model`).
- Provider-reported cost is an estimate, not billing.
- PREREGISTRATION.md states 03:35 UTC; the first holdout run started at 03:29:22 UTC. The local original was created at
  03:29:08 UTC (filesystem birth time, unchanged since); it was committed together with the results. The decision
  criteria are the standing rule in evals/STUDY-DESIGN.md §8, committed before this study.
- `routing-cost-check.json` and `surface-checks.json` come from live sessions on the author's machine (event
  summaries only).
