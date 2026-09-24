# Results -- s1 holdout (reps=3)

## Verdict table (vs anchor)

| Cell | Anchor | Passed/Total | Ratio (95% CI) | sign-test p | Cost ratio | Quality delta | Gate | Verdict |
|---|---|---|---|---|---|---|---|---|
| orch-router-rules | plain | 8/8 | 0.61 [0.47, 0.78] | 0.07031 | 0.39 | +0 | green | **screen** |
  - orch-router-rules vs `plain-sonnet` (secondary): ratio=0.81 [0.64, 0.99]

## Q4 -- holdout confirmation

- orch-router-rules: verdict=screen

## Evidence limits

- bootstrap_ci: 2000 resamples, seed=20260919
- confirmed requires >= 3 reps, >= 8 paired passing tasks, and split=holdout
- external_harness_exec_time_may_still_include_its_own_startup
- models_not_necessarily_matched_across_campaigns_or_harnesses
- models_not_necessarily_matched_across_harnesses
- n_tasks=8
- non_contemporaneous_runs_across_campaigns
- single_repetition_per_task_per_harness

