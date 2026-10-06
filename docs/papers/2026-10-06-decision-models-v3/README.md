# What a fast decision model buys an AI agent (report v3)

Amplifier, Michael J. Jabbour and David Koleczek (Senior Applied Scientist), Microsoft, Office of the CTO.
Output: [`decision-models-v3.pdf`](decision-models-v3.pdf). Companion technical report (v2):
[`../2026-10-02-paired-measurement/`](../2026-10-02-paired-measurement/).

## Build

    make            # preview: regenerate every number from committed evidence, build the PDF (S1 box shows "pending" if absent)
    make FINAL=1    # final: fails unless the S1 result is committed
    make check      # figure geometry: labels nearest their markers, legends clear of plots, no overlapping text
    make clean      # remove intermediates, keep the PDF

Every number comes from `build_assets.py` (copied from the v2 build and extended with the observatory, the A0
counterfactual, the defaults replay and the S1 hook). It reads committed evidence only, plus `origin/main` refs via
`git show` / `git archive` (`jb_import.py`).

## S1 hook contract

Directory `docs/evidence/2026-10-06-holdout-v3/` (override for testing only: `S1_EVIDENCE=<dir>`). The build reads the
first of `s1_result.json`, `confirm.json`, `summary.json` that contains both `hypotheses` and `freeze` (the output
schema of `evals/v3/s1_analysis.py`, `fast-decisions-v3-s1-result/v1`). Fields used:

* `n_scenarios`; `health.n_sessions`
* `hypotheses.{H1,H2,H3,H3b,H4,H5,H6,H7}`: `estimate.gm_ratio`, `estimate.gm_ratio_ci95`, `estimate.d_turn_pass`,
  `estimate.d_turn_pass_ci95`, `p_holm`, `supported` (true / false / null = descriptive); `H2.decision`
* `freeze.{fable,opus}`: `chosen`, `selected_on_holdout`, `table[]` with `config`, `class`, `candidate`, `gm_ratio`,
  `gm_ratio_ci95`, `d_turn_pass_ci95`

A missing hypothesis renders as "not computed".
