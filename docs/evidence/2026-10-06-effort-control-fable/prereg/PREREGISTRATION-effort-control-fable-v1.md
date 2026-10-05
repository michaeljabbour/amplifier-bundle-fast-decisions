# Preregistration: effort-control-fable-v1 (2026-10-05)

Written and committed before the effort-control-fable-v1 schedule is created and before any of its sessions run. Design:
`evals/paired/effort-control-fable-v1.yaml`; analysis: `evals/paired_effort.py --design fable`; scenarios and split:
`evals/paired/scenarios/main-v1/SPLIT.md` (seed 20261002). Requested by the round-2 peer review as the Fable counterpart of
effort-control-v1 (Sonnet), run with the same harness.

## Question

Does plain Fable 5.1 at medium reasoning effort cost less than plain Fable 5.1 at the provider default effort, and at what
quality?

## Design

- Scenarios: the 23 TEST scenarios of main-v1 (`split.json`), 2 reps; none added, dropped or swapped after data.
- Arms (both plain Fable 5.1, host-independent, no fast-decisions): `fable` (anchor, provider-default effort, cell `plain`) and
  `fable_medium` (cell `plain-medium`). The two generated profiles differ in exactly one line, `reasoning_effort: medium`
  (`tests/test_effort_control.py`, `FableProfileDiffTests`). Both start together per scenario-rep from one frozen snapshot, each
  session with its own cache nonce. 92 sessions in 46 two-session waves; budget cap $700; parallel 8; memory-safety rules unchanged.
- Mechanism gate (a session failing it is excluded from the cost analysis): every MAIN request is served by Fable 5.1;
  `output_config.effort` on main requests is absent for `fable` and `medium` for `fable_medium`.
- Cost basis: `cost_usd_tools_normalized` (as main-v1).
- Feasibility check done before this document (disclosed): a 2-session preflight (`plain`, `plain-medium`, $1.73, scratch
  schedule in `~/dev/afast-paired/effort-control-fable-v1-preflight-scratch`, not the campaign schedule) showed Fable accepts the
  parameter: the llm:request payload carried `output_config.effort` = absent for `plain` and `medium` for `plain-medium`; both
  replies were served by claude-fable-5-1 with thinking enabled. Output tokens were 41 vs 43 on the trivial "Reply with OK" prompt,
  so the preflight cannot show whether medium changes behaviour; that is what the campaign measures.

## Hypothesis HF (primary, test split only)

Plain Fable at medium effort costs less than plain Fable at the default effort.

- Cost endpoint: geometric-mean ratio `fable_medium / fable`. Each scenario contributes the mean log ratio of its valid pairs
  (valid, mechanism_engaged, cache_audit_clean, cost_valid). Scenario-cluster bootstrap (resample the 23 scenarios with
  replacement), 10,000 resamples, seed **20261006**, 95% percentile interval. Supported iff the CI **upper bound < 1.0**.
- Quality endpoint (turn-pass non-inferiority, **unfiltered**: all pairs, including invalid ones): per scenario the mean
  `delta_turn_pass` (fable_medium minus fable); same bootstrap. Non-inferior iff the CI **lower bound > -0.05**.
- HF is supported only if both hold; otherwise it is reported as not supported. No second look, no redefinition.

## Exploratory (no decision rule)

- Final hidden-test pass: exact McNemar test of `fable_medium` vs `fable` matched on (scenario, rep); counts of discordant pairs reported.
- Per-task-type mean turn-pass delta (all pairs, scenario-level means).
- Secondary, not concurrent: `fable_medium` vs main-v1 `sticky` sessions on the Fable host, and vs main-v1 `anchor` sessions on the
  Fable host: per-scenario geometric-mean cost ratio with the same bootstrap. The main-v1 sessions ran at different times, so these
  are descriptive only.

## Not claimed

Nothing about other models, other effort levels or the train split. The pre-data cost estimate ($465.57, $502.82 with the 8% retry
reserve) assumes medium costs 0.85x default; that assumption is not evidence.
