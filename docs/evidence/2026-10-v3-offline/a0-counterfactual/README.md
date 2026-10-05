# A0: phase-0 counterfactual on main-v1 (offline, $0)

Plan: `docs/design/v3/PLAN.md` section A0. Code: `evals/v3/a0_counterfactual.py` (+ `evals/v3/rules.py`). Input: the
published main-v1 rows (`docs/evidence/2026-10-02-paired-campaign/data/`, sha256 in `summary.json` -> `inputs`) and
`campaign/decisions.jsonl`. Cost basis: `cost_usd_tools_normalized`. CIs: scenario-cluster bootstrap, 10,000 resamples,
seed 20261005. No model calls.

**Measured vs estimated.** Every cost and turn-pass number below is computed from measured sessions. Two things are
estimates and labelled as such: the cheap outcome for the 16 scenario-reps per host where Jev kept the host (plain
Sonnet x 0.821, the preregistered Sonnet-medium ratio), and anything multiplied by the Fable-medium factor 0.860.

## Method (potential outcomes)

A decide-once decider makes one choice per session, so each of its sessions is an always-host or an always-cheap
session for that scenario-rep. Per (host, scenario, rep): **host** = the plain anchor (provider-default effort; this
removes the effort-switch artifact below by construction); **cheap** = the sticky session where Jev routed it (Sonnet at
`medium`, decided once; 124 of 140 per host), else plain Sonnet x 0.821 (16 per host). A policy's value is the sum of
the chosen outcomes. Oracle: cheap iff cheaper AND turn-pass not lower ("equal quality"), chosen on the other rep of
the same scenario (cross-fitted, so not optimistic); a cost-only oracle and an in-sample oracle are reported too.

## Results (all 70 scenarios x 2 reps; per-split rows in `policies.csv`)

Geometric-mean cost ratio vs the plain host, turn-pass delta vs the plain host (95% CI), $ per 1,000 sessions.

| host | policy | route share | cost ratio | turn-pass delta | $ / 1,000 sessions | regret vs x-fit oracle |
|---|---|---:|---:|---:|---:|---:|
| Fable | always host (plain) | 0% | 1.000 | 0 | 5,311 | +2,043 |
| Fable | Jev recorded = shipped | 89% | 0.545 [0.510, 0.585] | -0.019 [-0.052, +0.010] | 3,108 | -160 |
| Fable | **R\* = always route + scope gate** | 99% | **0.509 [0.484, 0.538]** | -0.019 [-0.052, +0.010] | 2,739 | -529 |
| Fable | oracle, equal quality, cross-fitted | 81% | 0.583 [0.544, 0.627] | +0.012 [-0.004, +0.030] | 3,268 | 0 |
| Opus | shipped (Jev + price gate: never routes) | 0% | 1.000 | 0 | 2,125 | +1 |
| Opus | Jev recorded, ungated | 89% | 1.159 [1.092, 1.232] | -0.009 [-0.033, +0.013] | 2,498 | +374 |
| Opus | always route (= Pc/A0O, H5) | 100% | 1.197 [1.125, 1.273] | -0.005 [-0.030, +0.019] | 2,620 | +496 |
| Opus | oracle, equal quality, cross-fitted | 22% | 0.991 [0.975, 1.008] | 0.000 [-0.011, +0.009] | 2,124 | 0 |

Negative regret means cheaper than the oracle, bought with lower quality: the equal-quality oracle keeps 19% of Fable
sessions on the host and gains +0.03 turn-pass over always-route.

Findings:

1. **On Fable, Jev's 11% "keep on host" calls bought nothing on main-v1.** In all 16 scenario-reps where Jev kept the
   host, the routed (Sonnet) session scored exactly the anchor's turn-pass. Always-route is 7% cheaper than Jev
   (0.509 vs 0.545; $369 per 1,000 sessions) at an identical turn-pass delta.
2. **d(Jev, R\*) = 0.10 on both hosts** (14/140 scenario-reps; 7 scenarios on Fable). Under PLAN H2's identity the
   deciders differ by at most d x the mean discordant difference = $0.37 per session on Fable (R\* cheaper). d < 0.15:
   by the plan's own rule the deciders cannot differ materially by construction.
3. **On Opus the price gate is at the oracle:** the shipped (never-route) policy is $1 per 1,000 sessions from the
   cross-fitted oracle; ungated Jev would cost +$374 per 1,000 sessions. Routing to Sonnet on Opus is 1.20x (H5 prior).
4. **Decider headroom is small and lives in quality, not cost.** The equal-quality oracle routes 81% on Fable and costs
   0.583x, with +0.031 turn-pass over Jev. No decision-time feature captured that out of sample (next section).

## R\* (frozen; `evals/v3/frozen_rule.json`)

Fitted on the **train split only** (47 scenarios x 2 reps, Fable host), from 181 candidate rules: always-route; one
threshold on turn-1 prompt length or workspace file count (train deciles, both directions); a set of 1-2 keyword
intents of the turn-1 prompt (`implement` / `question` / `fix` / `other`, `rules.classify_intent`); one threshold OR
one intent. Every rule carries the shipped scope gate (more than 300 workspace files -> host).

* **First objective, fixed a priori** (cheapest rule with train turn-pass delta >= -0.025): `host if turn1_prompt_chars
  > 243`. It did not generalise: on the test split it cost 0.628x vs 0.513x for always-route, with a worse turn-pass
  delta (-0.012 vs +0.002). Reported, not used.
* **Final selection (train only): the fitting floor chosen by 5-fold grouped cross-validation over train scenarios**
  (`rule_cv.csv`). Out of fold, no floor improved quality (-0.026 to -0.031 vs -0.029 for no floor) while every
  floor raised cost (0.58-0.75x vs 0.51x). The procedure therefore selects no floor: **R\* = always route, subject to
  the scope gate.** Test split: 0.513x, turn-pass +0.002.

Candidate configs frozen for S1: **C\*_F** = bundle, decide-once, R\*, price gate on, scope gate 300, `cheap: medium`,
`strong: medium` (predicted 0.508x [0.483, 0.536], turn-pass -0.019 [-0.052, +0.010]; estimated). **C\*_O** = shipped
(gate closed) + `strong: medium`: unmeasured; prior band 0.821-0.860 from the Sonnet and Fable effort studies.

Sensitivity (`policies_sensitivity_cheap_sonnet.csv`): pricing every cheap outcome as plain Sonnet x 0.821 gives the
same ordering (Fable: always-route 0.482, R\* 0.488, Jev 0.523, oracle 0.548).

## The effort-switch cache finding (PLAN section 0.4), confirmed with exact numbers

The 32 sticky sessions that kept the host (16 per host) ran the phase effort map (high 1,178 / medium 410 / low 167
requests). Main requests after the first: `effort_cache_requests.csv`.

| requests | n | mean cache-write tokens |
|---|---:|---:|
| after an effort change | **823** | **15,641.6** |
| effort unchanged | **900** | **900.0** |
| within a turn, effort changed | 486 | 11,650.4 |
| within a turn, unchanged | 859 | 899.9 |
| within a turn, plain anchor (control) | 1,331 | 1,132.6 |
| first of a turn after a short gap, changed / unchanged / anchor | 313 / 41 / 354 | 17,959.6 / 901.2 / 12,467.2 |
| first of a turn after a >= 5 min gap, changed / anchor | 24 / 24 | 66,235.0 / 67,819.5 |

The headline (15,642 vs 900) reproduces exactly. Part of it is a turn-boundary confound (turn starts write more even
in plain anchors, and long gaps expire the cache whatever the effort), so the clean contrast is **within a turn:
11,650 vs 900 tokens, 12.9x**. Session level (`effort_cache_sessions.csv`): cost **1.255x** (Fable) and **1.357x**
(Opus) the same-scenario anchor (geometric mean); requests 0.98x / 1.09x (mean of ratios; GM 0.963 / 1.076); cache
writes 1.63x / 1.74x (ratio of sums); about 26 effort changes per session. Estimated rewrite premium (writes above a
no-change baseline, repriced write -> read, long-gap turns excluded): Fable $59-71 over 16 sessions (up to 47% of
their cost), Opus $19-23; removing it puts these sessions at 0.69-0.79x (Fable) and 0.87-0.95x (Opus) of the anchor
(estimate; the remaining gap also reflects the lower phase efforts). The premium more than accounts for the penalty.

## Files

`summary.json` (all headline numbers), `policies.csv`, `policies_sensitivity_cheap_sonnet.csv`, `s1_predictions.csv`,
`potential_outcomes.csv` (one row per host x scenario x rep with both outcomes, features and every policy's choice;
figure data), `rule_search.csv`, `rule_cv.csv`, `effort_cache_requests.csv`, `effort_cache_sessions.csv`.
Reproduce: `nice -n 10 python3 -m evals.v3.a0_counterfactual` (about 10 s).
