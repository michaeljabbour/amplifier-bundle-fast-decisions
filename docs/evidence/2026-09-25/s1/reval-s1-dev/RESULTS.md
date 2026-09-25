# Results -- s1 dev (reps=2)

## Verdict table (vs anchor)

| Cell | Anchor | Passed/Total | Ratio (95% CI) | sign-test p | Cost ratio | Quality delta | Gate | Verdict |
|---|---|---|---|---|---|---|---|---|
| orch-default | plain | 12/12 | 0.56 [0.45, 0.71] | 0.006348 | 0.54 | +0 | green | **screen** |
  - orch-default vs `plain-sonnet` (secondary): ratio=0.97 [0.80, 1.19]
| orch-default-opus | plain-opus | 12/12 | 0.83 [0.71, 0.98] | 0.03857 | 0.89 | +0 | green | **screen** |
  - orch-default-opus vs `plain-sonnet` (secondary): ratio=0.82 [0.71, 0.94]

## Evidence limits

- bootstrap_ci: 2000 resamples, seed=20260919
- confirmed requires >= 3 reps, >= 8 paired passing tasks, and split=holdout
- external_harness_exec_time_may_still_include_its_own_startup
- models_not_necessarily_matched_across_campaigns_or_harnesses
- models_not_necessarily_matched_across_harnesses
- n_tasks=12
- non_contemporaneous_runs_across_campaigns
- single_repetition_per_task_per_harness

