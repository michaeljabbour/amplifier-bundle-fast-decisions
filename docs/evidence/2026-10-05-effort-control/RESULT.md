# Result: does reasoning effort `medium` make plain Sonnet cheaper?

**Yes, by about 18%, with no measurable loss in turn-level quality.** The preregistered hypothesis HE is supported.

## What was compared

Plain Sonnet 5, no fast-decisions routing, on the 23 test-split scenarios of main-v1, each run twice (46 pairs, 92 sessions).
One arm used the provider's default reasoning effort (`sonnet`), the other set effort to `medium` (`sonnet_medium`). Nothing else differed.
Each pair started together from the same frozen workspace, with separate cache nonces.

Why: in main-v1 every routed or sticky Sonnet request ran at `medium` effort, while the plain-Sonnet control ran at the default. Sticky-on-Sonnet cost
0.83-0.86x plain Sonnet. This follow-up asks how much of that gap is the effort setting alone.

## Primary result (confirmatory, preregistered)

| endpoint | estimate | 95% CI | rule | verdict |
|---|---|---|---|---|
| cost, geometric-mean ratio medium / default | **0.821** | 0.781 to 0.861 | upper bound < 1.0 | supported (about 18% cheaper) |
| turn-pass, mean difference medium minus default | -0.003 | -0.026 to +0.021 | lower bound > -0.05 | non-inferior |

23 scenarios, 2 repetitions, 46 pairs (all 46 cost-valid). Intervals are 95% percentile intervals from 10,000 scenario-cluster bootstrap resamples,
seed 20261005. The quality endpoint is unfiltered (all pairs). Raw sums over the 46 sessions of each arm agree: $112.22 (medium) vs $137.14 (default)
tools-normalized, ratio 0.818; medium was cheaper in 42 of 46 pairs. Mean turn-pass was 0.953 (medium) vs 0.957 (default); every session of both arms
ended with a passing final state and none was flagged critical.

## Exploratory, non-concurrent comparison (no decision rule)

Medium plain Sonnet vs the main-v1 sticky sessions that chose Sonnet ("sticky-on-Sonnet", also at medium effort): ratio **0.958**, 95% CI 0.913 to 0.999,
22 scenarios (py-go-counting has no sticky-on-Sonnet session). A ratio near 1 means the effort setting explains most of the sticky-vs-plain-Sonnet cost gap.
The two sets of sessions ran on different dates, so this is descriptive only and the interval touches 1.0.

## Checks

* Mechanism gate passed on all 92 sessions (served by Sonnet 5; effort absent for `sonnet`, `medium` for `sonnet_medium`).
* Cache audit clean on all sessions; no cost mismatches; no infrastructure failures, retries or memory kills.
* Spend $250.13 (ledger; includes a $0.52 preflight), under the $400 cap.

## Not claimed

Nothing about other models, other effort levels, or the train split. The preregistration (`prereg/`) states this; note the timing caveat in
`prereg/PROVENANCE.md` (schedule built 6 min 43 s before the preregistration commit; first analysed session 16 s after it).
