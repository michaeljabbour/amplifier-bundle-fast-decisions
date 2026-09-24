# Results -- s1 dev (reps=1)

## Verdict table (vs anchor)

| Cell | Anchor | Passed/Total | Ratio (95% CI) | sign-test p | Cost ratio | Quality delta | Gate | Verdict |
|---|---|---|---|---|---|---|---|---|
| orch-primary | plain | 12/12 | 0.48 [0.40, 0.57] | 0.0004883 | 0.79 | +0 | green | **screen** |
  - orch-primary vs `plain-sonnet` (secondary): ratio=0.81 [0.57, 1.03]
| orch-primary-effort-only | plain | 12/12 | 0.77 [0.66, 0.89] | 0.006348 | 1.11 | +0 | green | **screen** |
  - orch-primary-effort-only vs `orch-primary` (secondary): ratio=n/a

## Evidence limits

- bootstrap_ci: 2000 resamples, seed=20260919
- confirmed requires >= 3 reps, >= 8 paired passing tasks, and split=holdout
- external_harness_exec_time_may_still_include_its_own_startup
- models_not_necessarily_matched_across_campaigns_or_harnesses
- models_not_necessarily_matched_across_harnesses
- n_tasks=12
- non_contemporaneous_runs_across_campaigns
- single_repetition_per_task_per_harness

