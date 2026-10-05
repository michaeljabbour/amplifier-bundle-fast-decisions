# Preregistration: effort-control-v1 (2026-10-05)

Written and committed before any effort-control-v1 session runs. Design: `evals/paired/effort-control-v1.yaml`; analysis:
`evals/paired_effort.py`; scenarios and split: `evals/paired/scenarios/main-v1/SPLIT.md` (seed 20261002).

## Question

In main-v1 every routed or sticky Sonnet request ran at reasoning effort `medium`, while the plain-sonnet control set no effort
(provider default). Sticky-on-Sonnet cost 0.83-0.86x plain Sonnet. How much of that gap is the effort setting alone?

## Design

- Scenarios: the 23 TEST scenarios of main-v1 (`split.json`), 2 reps. No scenario is added, dropped or swapped after data.
- Arms (both plain Sonnet 5, host-independent, no fast-decisions): `sonnet` (anchor, provider-default effort, cell
  `plain-sonnet`) and `sonnet_medium` (cell `plain-sonnet-medium`). The two profiles differ in exactly one line,
  `reasoning_effort: medium` (checked by `tests/test_effort_control.py`). Both start together per scenario-rep from one frozen
  snapshot; each session has its own cache nonce. 92 sessions, 46 two-session waves, budget cap $400.
- Mechanism gate (a session failing it is excluded from the cost analysis): every main request is served by Sonnet 5;
  `output_config.effort` on main requests is absent for `sonnet` and `medium` for `sonnet_medium`.
- Cost basis: `cost_usd_tools_normalized` (as main-v1). Memory-safety rules and the watchdog are unchanged.

## Hypothesis HE (primary, test split only)

Plain Sonnet at medium effort costs less than plain Sonnet at the default effort.

- Cost endpoint: geometric-mean ratio `sonnet_medium / sonnet`. Each scenario contributes the mean log ratio of its valid pairs
  (valid, mechanism_engaged, cache_audit_clean, cost_valid). Scenario-cluster bootstrap (resample the 23 scenarios with
  replacement), 10,000 resamples, seed 20261005, 95% percentile interval. Supported iff the CI **upper bound < 1.0**.
- Quality endpoint (turn-pass non-inferiority, **unfiltered**: all pairs, including invalid ones): per scenario the mean
  `delta_turn_pass` (sonnet_medium minus sonnet); same bootstrap. Non-inferior iff the CI **lower bound > -0.05**.
- HE is supported only if both hold. Otherwise it is reported as not supported; there is no second look and no re-definition.

## Secondary (exploratory, not concurrent, no decision rule)

`sonnet_medium` vs the main-v1 `sticky` sessions that decided `cheap` (sticky-on-Sonnet at medium): per-scenario geometric-mean
cost ratio with the same bootstrap. The sessions ran at different times, so this is descriptive only. A ratio near 1 would mean
the effort setting explains the sticky-vs-plain-Sonnet gap; a ratio well below 1 would mean other factors do.

## Not claimed

No claim about other models, other effort levels, or the train split. Cost estimate before data: $279 (+8% retry reserve),
assuming medium costs 0.85x default; that assumption is not evidence.
