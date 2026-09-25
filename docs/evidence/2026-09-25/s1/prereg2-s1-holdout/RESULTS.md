# Results -- s1 holdout (reps=3)

## Verdict table (vs anchor)

| Cell | Anchor | Passed/Total | Ratio (95% CI) | sign-test p | Cost ratio | Quality delta | Gate | Verdict |
|---|---|---|---|---|---|---|---|---|
| orch-default | plain | 8/8 | 0.42 [0.35, 0.50] | 0.007812 | 0.54 | +0 | green | **confirmed** |
  - orch-default vs `plain-sonnet` (secondary): ratio=0.91 [0.77, 1.08]
| orch-default-opus | plain-opus | 8/8 | 1.01 [0.86, 1.17] | 0.2891 | 0.97 | +0 | green | **no-effect** |
  - orch-default-opus vs `plain-sonnet` (secondary): ratio=0.86 [0.75, 0.99]

## Q4 -- holdout confirmation

- orch-default: verdict=confirmed
- orch-default-opus: verdict=no-effect

## Evidence limits

- bootstrap_ci: 2000 resamples, seed=20260919
- confirmed requires >= 3 reps, >= 8 paired passing tasks, and split=holdout
- external_harness_exec_time_may_still_include_its_own_startup
- models_not_necessarily_matched_across_campaigns_or_harnesses
- models_not_necessarily_matched_across_harnesses
- n_tasks=8
- non_contemporaneous_runs_across_campaigns
- single_repetition_per_task_per_harness

