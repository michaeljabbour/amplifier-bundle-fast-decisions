# Preregistration: paired measurement campaign main-v1 (2026-10-01)

Written and committed before any main-v1 session runs. Design: `evals/paired/main-v1.yaml`; method:
`docs/design/parallel-measurement-mode.md` (v2); split: `evals/paired/scenarios/main-v1/SPLIT.md` (seed 20261002;
47 train / 23 test scenarios); analysis: `evals/paired_model.py`.

## What is being measured

Measured (not estimated) cost of each fast-decisions policy against a plain host-model anchor, on the same scripted
8-16-turn session started from the same frozen workspace, all arms concurrently, each session with its own cache
nonce. Arms: `shipped` (orch-default profile), `sticky` (model chosen once at session start, never switched),
`sonnet` (plain cheap model, control), `aa` (second anchor, 20% subsample, noise floor). Hosts: Opus 5.5, Fable 5.1.
2 repetitions. Cost basis: tools-normalized provider-priced cost (`rows`); raw cost reported alongside.

## Pilot (screen, 5 scenarios x 1 rep, pilot-v1, not part of the analysis)

A/A noise SD of log ratio 0.10 (Fable) and 0.18 (Opus), centred on zero; cache audit clean; mechanism gates green;
no memory kills. Geometric-mean cost ratios vs anchor: Fable host sticky 0.53, shipped 0.65, sonnet 0.62; Opus host
sticky 1.46, shipped 1.35, sonnet 1.66. Quality: no arm worse than its anchor on final pass. These directions are
hypotheses below, not findings.

## Hypotheses and primary endpoints (test split only)

Primary endpoint: geometric-mean cost ratio arm/anchor per host, scenario-cluster bootstrap 95% CI, among pairs where
quality is non-inferior (turn-pass fraction margin -0.05).
- **H1 (Fable host):** `sticky` and `shipped` cost less than the anchor (CI upper bound < 1.0).
- **H2 (Opus host):** routing to Sonnet does not save money: `sticky`, `shipped` and `sonnet` ratios >= 1.0
  (CI lower bound > 0.95 counts as confirmed "no saving").
- **H3:** on both hosts `sticky` costs no more than `shipped` (paired ratio sticky/shipped CI upper bound <= 1.05),
  i.e. no mid-session switching is at least as cheap.
- **Quality:** each savings claim requires non-inferior turn-pass fraction (bootstrap lower bound > -0.05).

## Prediction model (the deliverable)

Fit on train only (`paired_model.py fit`): mixed model on log cost ratio (and delta-$ normalized by predicted anchor
cost) with fixed effects arm, host, task type, scripted turns, long-gap indicator, log turn-1 prompt size; scenario
and scenario:rep:host random intercepts. Validate on test (`predict`): 90% prediction-interval coverage must fall in
[0.80, 0.97] and the test-total saving must lie inside its PI; otherwise the model is reported as not predictive and
only the descriptive per-stratum ratios are quoted.

## Decision rules

- Recommend a per-host default: on a host where H1 holds with non-inferior quality, route (prefer `sticky` if H3
  holds); on a host where H2 holds, do not route to Sonnet.
- Anything from train, the pilot, or post-hoc slices is labeled exploratory.

## Integrity

Build frozen at plan time (source worktree sha recorded per session); model ids and price table recorded per session.
Budget: $6,500 ledger hard stop. A disappointing test result is not re-run; a changed design needs new scenarios.
Memory safety (memguard, watchdog, floors) is fixed and identical across arms.
