# Confirmatory analysis: paired campaign main-v1

Preregistration: `evals/paired/PREREGISTRATION-main-v1.md`. Test split only for everything under 'Confirmatory'. 294 test pairs, 23 test scenarios (expected 23). Ratios are arm / anchor (0.80 = 20% cheaper); 95% CIs from a scenario-cluster bootstrap (scenarios, then reps), 10,000 resamples, seed 20261002. Cost basis: tools-normalized.

Verdict rule (all hypotheses): confirmed = the 95% CI lies entirely on the hypothesis side of its preregistered threshold; contradicted = entirely on the other side; otherwise not confirmed.

## Verdicts

| hypothesis | non-inferiority reading | verdict |
|---|---|---|
| H1 | pair (primary) | confirmed |
| H2 | pair (primary) | confirmed |
| H3 | pair (primary) | confirmed |
| Quality | pair (primary) | confirmed |
| H1 | arm (sensitivity) | confirmed |
| H2 | arm (sensitivity) | confirmed |
| H3 | arm (sensitivity) | confirmed |
| Quality | arm (sensitivity) | confirmed |

Prediction model: **predictive**.

Decision (pair reading): fable: **route (sticky)** (H1 confirmed with non-inferior quality for sticky and shipped; H3 confirmed); opus: **do not route to Sonnet: plain host model** (H2 confirmed: sticky, shipped and sonnet all show no saving (CI lower > 0.95))

Decision (arm reading): fable: **route (sticky)** (H1 confirmed with non-inferior quality for sticky and shipped; H3 confirmed); opus: **do not route to Sonnet: plain host model** (H2 confirmed: sticky, shipped and sonnet all show no saving (CI lower > 0.95))

## Primary endpoint: cost ratio vs anchor (test split)

Pair reading keeps a pair only if its own delta turn-pass > -0.05 (in practice >= 0). Arm reading uses every cost-valid pair.

| host | arm | pairs kept (pair) | scen. | ratio (pair) | 95% CI (pair) | pairs (arm) | ratio (arm) | 95% CI (arm) |
|---|---|---|---|---|---|---|---|---|
| fable | shipped | 39/46 | 22 | 0.629 | 0.555 to 0.715 | 46 | 0.618 | 0.552 to 0.698 |
| fable | sticky | 38/46 | 21 | 0.558 | 0.493 to 0.643 | 46 | 0.537 | 0.481 to 0.614 |
| fable | sonnet | 39/46 | 22 | 0.577 | 0.516 to 0.654 | 46 | 0.590 | 0.529 to 0.663 |
| opus | shipped | 38/46 | 21 | 1.380 | 1.250 to 1.529 | 46 | 1.321 | 1.192 to 1.465 |
| opus | sticky | 38/46 | 22 | 1.249 | 1.125 to 1.389 | 46 | 1.203 | 1.085 to 1.334 |
| opus | sonnet | 40/46 | 22 | 1.433 | 1.253 to 1.640 | 46 | 1.457 | 1.280 to 1.666 |

## Hypotheses, pair reading

| hypothesis | host | arm | ratio | 95% CI | verdict |
|---|---|---|---|---|---|
| H1 (<1.0) | fable | sticky | 0.558 | 0.493 to 0.643 | confirmed |
| H1 (<1.0) | fable | shipped | 0.629 | 0.555 to 0.715 | confirmed |
| H2 (lower >0.95) | opus | sticky | 1.249 | 1.125 to 1.389 | confirmed |
| H2 (lower >0.95) | opus | shipped | 1.380 | 1.250 to 1.529 | confirmed |
| H2 (lower >0.95) | opus | sonnet | 1.433 | 1.253 to 1.640 | confirmed |
| H3 sticky/shipped (<=1.05) | fable | 35 triplets | 0.862 | 0.764 to 0.994 | confirmed |
| H3 sticky/shipped (<=1.05) | opus | 33 triplets | 0.917 | 0.848 to 0.991 | confirmed |

H1 **confirmed**, H2 **confirmed**, H3 **confirmed**, Quality **confirmed** (savings claims tested: shipped@fable, sticky@fable, sonnet@fable).

## Hypotheses, arm reading

| hypothesis | host | arm | ratio | 95% CI | verdict |
|---|---|---|---|---|---|
| H1 (<1.0) | fable | sticky | 0.537 | 0.481 to 0.614 | confirmed |
| H1 (<1.0) | fable | shipped | 0.618 | 0.552 to 0.698 | confirmed |
| H2 (lower >0.95) | opus | sticky | 1.203 | 1.085 to 1.334 | confirmed |
| H2 (lower >0.95) | opus | shipped | 1.321 | 1.192 to 1.465 | confirmed |
| H2 (lower >0.95) | opus | sonnet | 1.457 | 1.280 to 1.666 | confirmed |
| H3 sticky/shipped (<=1.05) | fable | 46 triplets | 0.869 | 0.779 to 0.983 | confirmed |
| H3 sticky/shipped (<=1.05) | opus | 46 triplets | 0.911 | 0.854 to 0.970 | confirmed |

H1 **confirmed**, H2 **confirmed**, H3 **confirmed**, Quality **confirmed** (savings claims tested: shipped@fable, sticky@fable, sonnet@fable).

## Quality: turn-pass non-inferiority (test split, all quality-valid pairs)

Mean of arm minus anchor turn-pass fraction; non-inferior when the 95% lower bound > -0.05.

| host | arm | pairs | mean delta | 95% CI | verdict |
|---|---|---|---|---|---|
| fable | shipped | 46 | 0.0031 | -0.0410 to 0.0538 | confirmed |
| fable | sticky | 46 | 0.0015 | -0.0465 to 0.0547 | confirmed |
| fable | sonnet | 46 | 0.009 | -0.0362 to 0.0611 | confirmed |
| opus | shipped | 46 | -0.001 | -0.0350 to 0.0370 | confirmed |
| opus | sticky | 46 | -0.0102 | -0.0582 to 0.0329 | not confirmed |
| opus | sonnet | 46 | 0.007 | -0.0357 to 0.0512 | confirmed |

## Prediction model check (preregistered bounds)

276 test pairs, 23 scenarios, 4000 draws (seed 0); re-run reproduces model/predictions.json: True.

| check | value | pass |
|---|---|---|
| 90% PI coverage, log ratio, in [0.80, 0.97] | 0.9601 | True |
| 90% PI coverage, saving $ (delta model), in [0.80, 0.97] | 0.9348 | True |
| test-total saving inside its 90% PI | $180.35 in 63.20 to 251.26 | True |
| (not preregistered) calibration slope | 0.829 |  |
| (not preregistered) coverage, saving $ via ratio model | 0.8732 |  |

Verdict: **predictive**. Sensitivity with draw seed 20261002: coverage log 0.9601, $ 0.9312, total PI 65.49 to 253.67.

| arm / host | pairs | coverage (log) | coverage ($) | observed total | PI90 total | inside |
|---|---|---|---|---|---|---|
| shipped / fable | 46 | 0.9565 | 0.9783 | $85.01 | 64.78 to 121.24 | True |
| shipped / opus | 46 | 1.0 | 0.9783 | -$31.48 | -45.42 to -20.50 | True |
| sonnet / fable | 46 | 0.9348 | 0.9348 | $94.95 | 39.53 to 95.29 | True |
| sonnet / opus | 46 | 0.9565 | 0.8261 | -$46.80 | -57.41 to -29.04 | True |
| sticky / fable | 46 | 0.913 | 0.9348 | $99.82 | 70.67 to 132.14 | True |
| sticky / opus | 46 | 1.0 | 0.9565 | -$21.15 | -42.03 to -16.57 | True |

## Deviations from the preregistration

- Coverage bounds: paired_model.py (PREREG constant) and MODEL.md use 0.83-0.97 plus a calibration-slope check 0.7-1.3; the preregistration says [0.80, 0.97] and has no slope check. The verdict here uses [0.80, 0.97]; the slope and paired_model's own checks are reported, not used.
- Coverage outcome: the prereg does not say which outcome's PI coverage is checked; both the log-ratio and the delta-$ model coverage must be in bounds here (stricter of the two readings).
- Primary-endpoint restriction is ambiguous (pair-level vs arm-level non-inferiority). Pair-level matches the text ('among pairs where ...') and is primary; arm-level is reported alongside. Pair-level filtering conditions on a post-treatment outcome and in this design keeps only pairs with delta_turn_pass >= 0 (steps are >= 1/16).
- Non-inferiority comparison: paired_model uses lower bound >= -0.05; the prereg says > -0.05, used here.
- 'Lower bound' for Quality is the 2.5th percentile (two-sided 95% bootstrap CI), consistent with the 95% CIs of the primary endpoint; the prereg does not state the level for this bound.
- 'Contradicted' is not defined in the prereg; defined here, before looking at test numbers, as the 95% CI lying entirely on the other side of the same preregistered threshold.
- H3 restriction: the prereg does not say which pairs enter the sticky/shipped ratio; pair reading keeps triplets where both sticky and shipped are pair-level non-inferior to the shared anchor; arm reading keeps all.
- Decision rule: 'H3 holds' is read as H3 as a whole (both hosts), and 'H1 holds' as both sticky and shipped.
- Model engine: statsmodels is not installed, so the fit used paired_model's numpy fallback (method-of-moments variance components + feasible GLS), not REML MixedLM. The model is the existing model.json (train only, fit-boot 400, seed 0); the PI check re-runs predict with its on-disk seed/draws and with seed 20261002 as a sensitivity check.
- Bootstrap: 10,000 resamples, seed 20261002 (per analysis instructions; the prereg names 20261002 as the split seed).

## Bootstrap-seed robustness

Every verdict re-derived under bootstrap seeds 20261003-20261022 (10,000 resamples each): no verdict changed.

# EXPLORATORY (not confirmatory)

## Final hidden-test pass rate and McNemar vs anchor (all splits)

| host | arm | pairs | arm pass | anchor pass (same pairs) | anchor-only / arm-only | McNemar p |
|---|---|---|---|---|---|---|
| fable | shipped | 140 | 0.9357 | 0.9786 | 7 / 1 | 0.0703 |
| fable | sticky | 140 | 0.9429 | 0.9786 | 6 / 1 | 0.125 |
| fable | sonnet | 140 | 0.9429 | 0.9786 | 5 / 0 | 0.0625 |
| fable | aa | 28 | 0.9643 | 1.0 | 1 / 0 | 1.0 |
| opus | shipped | 140 | 0.9357 | 0.9571 | 4 / 1 | 0.375 |
| opus | sticky | 140 | 0.9357 | 0.9571 | 5 / 2 | 0.4531 |
| opus | sonnet | 140 | 0.9429 | 0.9571 | 4 / 2 | 0.6875 |
| opus | aa | 28 | 0.9286 | 1.0 | 2 / 0 | 0.5 |

## A/A noise floor (anchor vs second anchor)

| split | host | pairs | ratio | mean log ratio 95% CI | SD log ratio | SD per session | centred on 0 |
|---|---|---|---|---|---|---|---|
| all | fable | 28 | 0.968 | -0.067 to 0.003 | 0.096974 | 0.068571 | True |
| all | opus | 27 | 1.049 | 0.007 to 0.089 | 0.103048 | 0.072866 | False |
| all | all | 55 | 1.007 | -0.027 to 0.041 | 0.107067 | 0.075708 | True |
| test | fable | 9 | 0.957 | -0.093 to 0.007 | 0.081581 | 0.057686 | True |
| test | opus | 9 | 1.035 | -0.039 to 0.097 | 0.103159 | 0.072945 | True |
| test | all | 18 | 0.995 | -0.059 to 0.045 | 0.098934 | 0.069957 | True |

## Interim vs final cost ratios

Pilot and interim are dashboard numbers seen during the run (interim = train only, partial). Final train/test are all cost-valid pairs (no quality restriction); the last column is the confirmatory pair-reading ratio.

| host | arm | pilot | interim (train, partial) | final train (95% CI) | final test (95% CI) | confirmatory test (pair) |
|---|---|---|---|---|---|---|
| fable | sticky | 0.53 | 0.6 | 0.571 (0.51 to 0.64) | 0.537 (0.48 to 0.61) | 0.558 |
| fable | shipped | 0.65 | 0.7 | 0.640 (0.58 to 0.70) | 0.618 (0.55 to 0.70) | 0.629 |
| fable | sonnet | 0.62 | 0.58 | 0.585 (0.54 to 0.63) | 0.590 (0.53 to 0.66) | 0.577 |
| fable | aa |  | 0.95 | 0.973 (0.93 to 1.02) | 0.957 (0.91 to 1.01) |  |
| opus | sticky | 1.46 | 1.11 | 1.199 (1.11 to 1.30) | 1.203 (1.09 to 1.33) | 1.249 |
| opus | shipped | 1.35 | 1.12 | 1.224 (1.13 to 1.33) | 1.321 (1.19 to 1.47) | 1.380 |
| opus | sonnet | 1.66 | 1.36 | 1.447 (1.31 to 1.60) | 1.457 (1.29 to 1.67) | 1.433 |
| opus | aa |  | 1.09 | 1.056 (1.00 to 1.11) | 1.035 (0.96 to 1.10) |  |

## Raw cost basis (test split, sensitivity)

| host | arm | ratio (pair) | 95% CI | ratio (arm) | 95% CI |
|---|---|---|---|---|---|
| fable | shipped | 0.625 | 0.550 to 0.709 | 0.615 | 0.548 to 0.691 |
| fable | sticky | 0.552 | 0.490 to 0.638 | 0.532 | 0.476 to 0.608 |
| fable | sonnet | 0.574 | 0.513 to 0.647 | 0.586 | 0.525 to 0.661 |
| opus | shipped | 1.358 | 1.223 to 1.509 | 1.304 | 1.178 to 1.444 |
| opus | sticky | 1.234 | 1.111 to 1.375 | 1.189 | 1.074 to 1.317 |
| opus | sonnet | 1.421 | 1.247 to 1.635 | 1.443 | 1.273 to 1.644 |

## Savings per 1,000 sessions: delta-$ model (paired_model workload)

Saving = anchor cost - arm cost (positive = saved), 90% prediction ranges. Stated mix: for each task type, that type's own scenario mix across all 70 campaign scenarios (scripted-turn distribution, long-gap share, median turn-1 prompt chars); 'campaign mix' row uses the campaign's task-type shares `{"bugfix": 0.2571, "docs": 0.0571, "explain": 0.0429, "feature": 0.1857, "mixed": 0.4, "review": 0.0571}`, long-gap share 0.3286, median turn-1 chars 461.

Caution: the preregistered model has additive arm, host and task-type effects (no arm x host or host x task interaction), so an arm or task-type effect is shared by both hosts. The model point lies outside the empirical 90% range (next table) in 28 of 42 cells (campaign-mix rows outside: shipped@fable, sonnet@fable, sticky@fable). The preregistered check validates pooled pair-level coverage and the pooled test total, not per-arm-per-host levels; on the test mix itself:

| arm / host | model per 1,000 (test mix) | 90% PI | observed test per 1,000 | inside |
|---|---|---|---|---|
| shipped / fable | $2,081.64 | 1,594 to 2,447 | $1,848.04 | True |
| shipped / opus | -$687.74 | -909 to -528 | -$684.35 | True |
| sonnet / fable | $1,548.89 | 1,072 to 1,903 | $2,064.13 | False |
| sonnet / opus | -$905.43 | -1,193 to -698 | -$1,017.39 | True |
| sticky / fable | $2,282.82 | 1,720 to 2,730 | $2,170.00 | True |
| sticky / opus | -$605.53 | -829 to -436 | -$459.78 | True |

Use the empirical table for per-host x task-type x arm figures; the model rows are shown as preregistered output.

| host | task type | scenarios | arm | saving / 1,000 | 90% PI | share of anchor spend | empirical / 1,000 | model inside empirical 90% |
|---|---|---|---|---|---|---|---|---|
| fable | bugfix | 18 | shipped | $64.35 | -421 to 467 | 1.57% | $797.41 | NO |
| fable | bugfix | 18 | sonnet | -$352.15 | -811 to 90 | -8.61% | $870.52 | NO |
| fable | bugfix | 18 | sticky | $221.64 | -281 to 689 | 5.42% | $1,345.94 | NO |
| fable | docs | 4 | shipped | $3,444.52 | 2,837 to 4,001 | 61.2% | $2,263.39 | NO |
| fable | docs | 4 | sonnet | $2,871.33 | 2,282 to 3,407 | 51.02% | $2,245.95 | yes |
| fable | docs | 4 | sticky | $3,660.99 | 2,996 to 4,303 | 65.05% | $2,615.49 | NO |
| fable | explain | 3 | shipped | $2,742.83 | 1,451 to 2,909 | 78.64% | $2,244.34 | NO |
| fable | explain | 3 | sonnet | $2,387.59 | 1,077 to 2,519 | 68.45% | $2,367.04 | yes |
| fable | explain | 3 | sticky | $2,876.98 | 1,587 to 3,088 | 82.48% | $2,314.75 | NO |
| fable | feature | 13 | shipped | $2,603.92 | 2,025 to 3,084 | 46.31% | $2,019.48 | yes |
| fable | feature | 13 | sonnet | $2,031.18 | 1,559 to 2,417 | 36.12% | $2,895.11 | NO |
| fable | feature | 13 | sticky | $2,820.20 | 2,207 to 3,395 | 50.15% | $2,182.91 | yes |
| fable | mixed | 28 | shipped | $2,552.56 | 1,941 to 3,111 | 44.98% | $1,941.39 | NO |
| fable | mixed | 28 | sonnet | $1,974.61 | 1,327 to 2,523 | 34.8% | $2,405.48 | NO |
| fable | mixed | 28 | sticky | $2,770.82 | 2,052 to 3,391 | 48.83% | $2,020.28 | NO |
| fable | review | 4 | shipped | $3,612.79 | 2,881 to 4,121 | 57.92% | $3,010.65 | NO |
| fable | review | 4 | sonnet | $2,977.45 | 2,242 to 3,344 | 47.73% | $2,388.69 | NO |
| fable | review | 4 | sticky | $3,852.72 | 3,020 to 4,404 | 61.76% | $3,007.05 | NO |
| fable | campaign mix | 70 | shipped | $2,313.55 | 1,834 to 2,758 | 41.01% | $1,754.21 | NO |
| fable | campaign mix | 70 | sonnet | $1,738.95 | 1,306 to 2,141 | 30.82% | $2,089.98 | NO |
| fable | campaign mix | 70 | sticky | $2,530.55 | 1,942 to 3,062 | 44.85% | $1,980.10 | NO |
| opus | bugfix | 18 | shipped | -$1,176.37 | -1,385 to -956 | -70.4% | -$1,239.98 | yes |
| opus | bugfix | 18 | sonnet | -$1,346.56 | -1,586 to -1,095 | -80.58% | -$1,947.83 | NO |
| opus | bugfix | 18 | sticky | -$1,112.10 | -1,318 to -894 | -66.55% | -$1,037.00 | yes |
| opus | docs | 4 | shipped | -$247.66 | -504 to -51 | -10.77% | $162.40 | NO |
| opus | docs | 4 | sonnet | -$481.88 | -791 to -238 | -20.95% | -$128.58 | NO |
| opus | docs | 4 | sticky | -$159.21 | -424 to 42 | -6.92% | $263.56 | NO |
| opus | explain | 3 | shipped | $94.99 | -484 to 169 | 6.66% | $234.70 | yes |
| opus | explain | 3 | sonnet | -$50.17 | -643 to 60 | -3.52% | $242.13 | NO |
| opus | explain | 3 | sticky | $149.81 | -429 to 213 | 10.51% | $340.99 | NO |
| opus | feature | 13 | shipped | -$589.81 | -771 to -429 | -25.67% | -$490.04 | yes |
| opus | feature | 13 | sonnet | -$823.83 | -1,053 to -639 | -35.85% | -$1,098.95 | NO |
| opus | feature | 13 | sticky | -$501.43 | -676 to -320 | -21.82% | -$574.13 | yes |
| opus | mixed | 28 | shipped | -$625.86 | -911 to -381 | -26.99% | -$401.07 | NO |
| opus | mixed | 28 | sonnet | -$862.03 | -1,221 to -575 | -37.18% | -$814.67 | yes |
| opus | mixed | 28 | sticky | -$536.68 | -829 to -291 | -23.15% | -$303.07 | NO |
| opus | review | 4 | shipped | -$358.33 | -697 to -203 | -14.06% | -$642.03 | NO |
| opus | review | 4 | sonnet | -$617.94 | -964 to -418 | -24.24% | -$1,193.34 | NO |
| opus | review | 4 | sticky | -$260.29 | -596 to -120 | -10.21% | -$425.40 | yes |
| opus | campaign mix | 70 | shipped | -$713.86 | -934 to -549 | -30.97% | -$587.64 | yes |
| opus | campaign mix | 70 | sonnet | -$948.66 | -1,206 to -745 | -41.15% | -$1,095.99 | yes |
| opus | campaign mix | 70 | sticky | -$625.20 | -842 to -451 | -27.12% | -$489.14 | yes |

## Savings per 1,000 sessions: empirical (all splits, EXPLORATORY)

-(mean delta $) x 1000 per host x task type x arm; 90% range from the scenario-cluster bootstrap.

| host | task type | arm | pairs | scenarios | saving / 1,000 | 90% range |
|---|---|---|---|---|---|---|
| fable | bugfix | shipped | 36 | 18 | $797.41 | 385 to 1,232 |
| fable | bugfix | sticky | 36 | 18 | $1,345.94 | 848 to 1,882 |
| fable | bugfix | sonnet | 36 | 18 | $870.52 | 486 to 1,270 |
| fable | docs | shipped | 8 | 4 | $2,263.39 | 1,924 to 2,683 |
| fable | docs | sticky | 8 | 4 | $2,615.49 | 2,045 to 3,326 |
| fable | docs | sonnet | 8 | 4 | $2,245.95 | 1,711 to 3,049 |
| fable | explain | shipped | 6 | 3 | $2,244.34 | 1,671 to 2,723 |
| fable | explain | sticky | 6 | 3 | $2,314.75 | 1,945 to 2,703 |
| fable | explain | sonnet | 6 | 3 | $2,367.04 | 2,058 to 2,668 |
| fable | feature | shipped | 26 | 13 | $2,019.48 | 1,254 to 2,784 |
| fable | feature | sticky | 26 | 13 | $2,182.91 | 1,095 to 3,188 |
| fable | feature | sonnet | 26 | 13 | $2,895.11 | 2,350 to 3,484 |
| fable | mixed | shipped | 56 | 28 | $1,941.39 | 1,532 to 2,355 |
| fable | mixed | sticky | 56 | 28 | $2,020.28 | 1,241 to 2,720 |
| fable | mixed | sonnet | 56 | 28 | $2,405.48 | 2,065 to 2,740 |
| fable | review | shipped | 8 | 4 | $3,010.65 | 2,456 to 3,522 |
| fable | review | sticky | 8 | 4 | $3,007.05 | 2,469 to 3,509 |
| fable | review | sonnet | 8 | 4 | $2,388.69 | 1,863 to 2,797 |
| fable | all | shipped | 140 | 70 | $1,754.21 | 1,481 to 2,032 |
| fable | all | sticky | 140 | 70 | $1,980.10 | 1,577 to 2,368 |
| fable | all | sonnet | 140 | 70 | $2,089.98 | 1,834 to 2,340 |
| opus | bugfix | shipped | 36 | 18 | -$1,239.98 | -1,501 to -996 |
| opus | bugfix | sticky | 36 | 18 | -$1,037.00 | -1,339 to -752 |
| opus | bugfix | sonnet | 36 | 18 | -$1,947.83 | -2,300 to -1,626 |
| opus | docs | shipped | 8 | 4 | $162.40 | 1 to 321 |
| opus | docs | sticky | 8 | 4 | $263.56 | 99 to 500 |
| opus | docs | sonnet | 8 | 4 | -$128.58 | -458 to 185 |
| opus | explain | shipped | 6 | 3 | $234.70 | 14 to 397 |
| opus | explain | sticky | 6 | 3 | $340.99 | 227 to 434 |
| opus | explain | sonnet | 6 | 3 | $242.13 | 66 to 399 |
| opus | feature | shipped | 26 | 13 | -$490.04 | -708 to -301 |
| opus | feature | sticky | 26 | 13 | -$574.13 | -776 to -385 |
| opus | feature | sonnet | 26 | 13 | -$1,098.95 | -1,376 to -839 |
| opus | mixed | shipped | 56 | 28 | -$401.07 | -597 to -212 |
| opus | mixed | sticky | 56 | 28 | -$303.07 | -511 to -104 |
| opus | mixed | sonnet | 56 | 28 | -$814.67 | -1,257 to -458 |
| opus | review | shipped | 8 | 4 | -$642.03 | -900 to -393 |
| opus | review | sticky | 8 | 4 | -$425.40 | -838 to -29 |
| opus | review | sonnet | 8 | 4 | -$1,193.34 | -1,568 to -830 |
| opus | all | shipped | 140 | 70 | -$587.64 | -726 to -456 |
| opus | all | sticky | 140 | 70 | -$489.14 | -639 to -342 |
| opus | all | sonnet | 140 | 70 | -$1,095.99 | -1,329 to -881 |

