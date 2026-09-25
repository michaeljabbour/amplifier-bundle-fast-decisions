# Preregistration: S1 holdout, corrected shipped default (Jev judge, decide once), Fable and Opus hosts

Written 2026-09-25 03:35 UTC, BEFORE the holdout pass is launched. Candidate: commit 52e0d29 (frozen snapshot,
recorded in manifest.json): Jev turn-start judge, scope gate 300, by-tier effort, no mid-turn escalation
except on provider error.

**Cells:**
- `orch-default` (host claude-fable-5-1), anchor `plain`.
- `orch-default-opus` (host claude-opus-5-5), anchor `plain-opus`.
- Secondary anchor for both: `plain-sonnet`.

Suite S1, split holdout (8 tasks never used for tuning), 3 reps, seeds from base 20260919.

**H1 (Fable host), vs `plain`.** Faster at non-inferior quality. Decision rule (STUDY-DESIGN.md §8), all of:
1. mechanism gate green on every rep
2. geometric-mean exec-time ratio <= 0.90
3. sign test p <= 0.05 (with 8 tasks this requires all 8 faster)
4. cost ratio <= 1.00
5. successes >= plain - 1, with zero critical failures
6. >= 3 reps and >= 8 paired passing tasks

**Prediction** from the dev screens (2 batches): time ~0.57, cost ~0.47, quality equal.

**H2 (Opus host), vs `plain-opus`.** Same six criteria. Prediction from dev: time ~0.80, cost ~0.86. The time
criterion (<= 0.90) is expected to pass narrowly; the sign test may fail.

**Secondary, vs `plain-sonnet`, descriptive only, no win claimed.**

**What would falsify:** H1 or H2 time ratio > 0.90, a p-value > 0.05, cost > 1.00, or more than one lost task.
A failed criterion will be reported as failed.
