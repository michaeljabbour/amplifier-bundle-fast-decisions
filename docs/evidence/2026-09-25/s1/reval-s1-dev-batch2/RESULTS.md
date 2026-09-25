# Results -- s1 dev (reps=1)

## Verdict table (vs anchor)

| Cell | Anchor | Passed/Total | Ratio (95% CI) | sign-test p | Cost ratio | Quality delta | Gate | Verdict |
|---|---|---|---|---|---|---|---|---|
| orch-default | plain | 12/12 | 0.57 [0.44, 0.77] | 0.03857 | 0.49 | +0 | green | **screen** |
  - orch-default vs `plain-sonnet` (secondary): ratio=1.09 [0.91, 1.37]
| orch-default-opus | plain-opus | 12/12 | 0.76 [0.62, 0.91] | 0.146 | 0.80 | +0 | green | **screen** |
  - orch-default-opus vs `plain-sonnet` (secondary): ratio=0.89 [0.74, 1.11]

## Evidence limits

- bootstrap_ci: 2000 resamples, seed=20260919
- confirmed requires >= 3 reps, >= 8 paired passing tasks, and split=holdout
- external_harness_exec_time_may_still_include_its_own_startup
- models_not_necessarily_matched_across_campaigns_or_harnesses
- models_not_necessarily_matched_across_harnesses
- n_tasks=12
- non_contemporaneous_runs_across_campaigns
- single_repetition_per_task_per_harness

