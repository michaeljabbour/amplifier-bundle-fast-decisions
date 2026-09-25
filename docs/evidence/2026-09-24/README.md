# Evidence: orchestrator-primary fast-decisions study (2026-09-24)

These are the records behind `docs/RESULTS-2026-09-24.md`, `evals/STUDY-DESIGN.md` §18 and
`docs/report/fast-decisions-report.html`. `MANIFEST.json` holds a SHA-256 for every file here.

## What is in this folder (committed; summaries only)

This folder holds no prompts, no patches, no assistant final messages and no secrets.

| Path | What | Used for |
|---|---|---|
| `s1/screen-s1-dev/` | S1 dev screen, 1 rep: plain, plain-sonnet, orch-primary, orch-primary-effort-only | Report fig. 2–3 (first version, effort-only) |
| `s1/router-s1-dev/` | S1 dev screen, 1 rep: plain, plain-sonnet, orch-router-jev | Report "Recommended · Jev decides" |
| `s1/router-rules-s1-dev/` | S1 dev screen, 1 rep: plain, plain-sonnet, orch-router-rules (the shipped default) | Report headline 0.55× / 0.38× |
| `s1/prereg-s1-holdout/` | **Preregistered** S1 holdout, 3 reps, 8 unseen tasks, with `PREREGISTRATION.md` | Report "How sure we are": 0.61×, 0.40× (geometric mean), p = 0.07, 5 of 6 criteria, not confirmed |
| `s1/*/runs/**/result.json` | per-run outcome, times, cost, model (final message removed) | recomputation |
| `s1/*/comparisons/*.json` | battery.py comparisons with mechanism receipts | gates |
| `swe/swe-check2/` | 1-instance pipeline check (3 arms) | runner validation |
| `swe/swe-screen10/` | SWE-bench Verified, 10 instances × {plain, plain-sonnet, orch-primary}, 1 rep | fig. 4–5 (cheaper model, first version) |
| `swe/swe-router10/` | 10 × {plain, orch-router-jev, orch-router-local}, 1 rep | Jev and local router rows |
| `swe/swe-router-reps/` | 10 × {plain, orch-router-jev}, 2 more reps | 3-rep router result (19/30 vs 23/30) |
| `swe/swe-complex-speed/` | 10 × {plain, orch-router-rules, orch-strong-phase-effort}, 2 reps | fig. 4–5 (recommended, lower thinking level) |
| `swe/swe-router-smoke/` | router smoke on 1 instance | mechanism check |
| `swe/*/grading/*.json` | official swebench 4.x reports (resolved / unresolved ids) | quality numbers |
| `swe/*/runs/*.json` | per-run result: times, cost, tokens, models served, patch size | time and cost ratios |
| `difficulty/difficulty-report*.json` | judge probe: per-item p(complex), latency | fig. 6 |
| `difficulty/surface-feature-auc.json` | AUC of simple surface features of the issue text (length, files named, code blocks, ...) on 410 held-out instances | "no surface feature beats length" |
| `followups/followups.json` | Same-day follow-ups: model speed and list prices, trivial-prompt timings with/without the four add-ons, per-surface routing checks, upstream PR link | Report "Which default model benefits", start-up add-on paragraph, "Try it" |
| `difficulty/dataset-index.json` | probe items: id, source, label, human difficulty (texts are public: SWE-bench Verified / S1) | fig. 6 |

## What is kept locally (not committed: contains full prompts and responses)

| Location | Size | SHA-256 |
|---|---|---|
| `~/dev/afast-orch-primary-20260924/archive/raw-records-20260924.tar.gz`: run dirs (results, receipts, events, logs, manifests), excluding repository checkouts | 9.4 MB | `e3e7f9aa27be222a082d4029746f968d83ca7311978d3c6949d2349c04fde6e2` |
| `~/dev/afast-orch-primary-20260924/archive/session-logs-20260924.tar.gz`: 362 Amplifier session logs (`~/.amplifier/projects/*afast*`), the source of every exec-time figure | 604 MB | `efb87619da640506e90fcdef96fcd031c828f89fbc4679b33ac951593b12d248` |
| Live roots: `~/dev/afast-orch-primary-20260924/`, `~/dev/afast-ev/{screen-s1-dev,router-s1-dev,router-rules-s1-dev,prereg-s1-holdout}` | ~6.5 GB with checkouts | — |

## Recomputing the headline numbers

- **S1:** `evals/run.py --report-only --out <root>` regenerates `RESULTS.md` from the campaign root.
  It needs the live root (it checks `frozen_git_sha` against the frozen source there); from this
  folder alone, recompute from `s1/*/runs/**/result.json`. The
  per-task ratio is candidate exec time over anchor exec time, and the aggregate is their geometric
  mean (STUDY-DESIGN.md §8).
- **SWE:** `evals/swebench/forge_swebench.py report --root <root>` regenerates `report.json`.
  "Resolved" is `resolved_ids` in the swebench grading reports.
- **Judges:** AUC is the probability that a random "complex" item scores a higher p(complex) than a
  random "simple" one, computed over `difficulty-report*.json` rows with `source == swe-verified`.

## Known limits

- All runs were on one Apple-silicon Mac, provider `anthropic`. Host model `claude-fable-5-1`; cheap
  model `claude-sonnet-5`.
- Provider-reported cost is an estimate, not billing. Every time and cost ratio in the report is the
  geometric mean of per-task ratios against standard Amplifier in the same batch.
- The S1 dev screens of the shipped default ran on build 43ed54e, before the scope gate; the gate does
  not fire on S1 (small workspaces), so the routing is the same.
- SWE instances ran emulated (x86 images on arm64), which inflates tool time equally across arms.
