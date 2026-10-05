# Result: does reasoning effort `medium` make plain Fable 5.1 cheaper?

**Yes, by about 14%, with no measurable loss in turn-level quality.** The preregistered hypothesis HF is supported.

## What was compared

Plain Fable 5.1, no fast-decisions routing, on the 23 test-split scenarios of main-v1, each run twice (46 pairs, 92 sessions). One arm used the provider's
default reasoning effort (`fable`), the other set effort to `medium` (`fable_medium`). Nothing else differed. Each pair started together from the same frozen
workspace, with separate cache nonces. This is the Fable counterpart of the Sonnet follow-up (`../2026-10-05-effort-control/`), requested by the round-2 peer review.

## Primary result (confirmatory, preregistered)

| endpoint | estimate | 95% CI | rule | verdict |
|---|---|---|---|---|
| cost, geometric-mean ratio medium / default | **0.860** | 0.833 to 0.885 | upper bound < 1.0 | supported (about 14% cheaper) |
| turn-pass, mean difference medium minus default | +0.033 | -0.002 to +0.080 | lower bound > -0.05 | non-inferior |

23 scenarios, 2 repetitions, 46 pairs, **45 cost-valid** (the pair whose default-effort session was stopped by the memory watchdog is cost-invalid; see
`FLAGS.md`). Intervals are 95% percentile intervals from 10,000 scenario-cluster bootstrap resamples, seed 20261006. The quality endpoint is unfiltered (all 46
pairs). Raw sums over the 45 cost-valid pairs: $189.06 (medium) vs $219.27 (default) tools-normalized, ratio 0.862; medium was cheaper in 42 of 46 pairs.
Mean turn-pass was 0.969 (medium) vs 0.936 (default); final state passed in 46 of 46 medium sessions and 45 of 46 default sessions.

## Exploratory (no decision rule)

* **Final hidden-test pass, exact McNemar:** 45 pairs both pass, 1 only medium passes, 0 only default passes (p = 1.0). The one medium-only pair is the memory-killed default session.
* **Per-task-type turn-pass delta (medium minus default, scenario-level means):** bugfix +0.063 (6 scenarios), mixed +0.044 (10), feature 0.000 (3), explain 0.000 (2), review -0.025 (2). Small groups; read as descriptive.
* **Medium Fable vs main-v1 sticky sessions on the Fable host (non-concurrent):** ratio **1.546**, 95% CI 1.343 to 1.759, 23 scenarios. Main-v1's sticky arm decided between
  Fable and Sonnet once per session and was on average much cheaper than plain Fable, so medium effort alone does not reach the sticky saving on this host.
* **Medium Fable vs main-v1 plain-Fable anchor (non-concurrent):** ratio **0.829**, 95% CI 0.790 to 0.866, 23 scenarios; consistent with the concurrent 0.860.
  The sessions ran on different dates, so both comparisons are descriptive only.

## Checks and flags

* Mechanism gate passed on all 92 sessions (served by Fable 5.1; effort absent for `fable`, `medium` for `fable_medium`). No cost mismatches, infrastructure failures or retries.
* Two flagged sessions, both in the default-effort arm, detailed in `FLAGS.md`: a cache-audit flag on go-linkedlist-r1-any-fable (421 surplus read tokens, about $0.005; its pair was kept
  because the pair row copied only the arm's flag) and a memory kill on py-go-counting-r2-any-fable (the agent's own verification script, turn 6).
  Sensitivity excluding the flagged-anchor pair: cost ratio 0.854 (0.825-0.882); also dropping the killed pair from quality: turn-pass +0.019 (-0.004 to +0.057). HF is supported in every variant.
* Spend $421.71 (ledger; includes a preflight), under the $700 cap.

## Not claimed

Nothing about other models, other effort levels, or the train split. The preregistration (`prereg/`) states this; ordering and the disclosed scratch preflight are in `prereg/PROVENANCE.md`.
