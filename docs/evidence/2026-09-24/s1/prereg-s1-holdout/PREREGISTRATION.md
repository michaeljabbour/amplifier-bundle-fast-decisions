# Preregistration: S1 holdout, orchestrator-primary shipped default

Written 2026-09-24, BEFORE the holdout pass is launched. Candidate: `feat/orchestrator-primary`
at the commit recorded in manifest.json (frozen snapshot).

**Cells:**
- `orch-router-rules`: the shipped default, with difficulty router, length rule, scope gate 300,
  by-tier effort and no judge.
- Anchor `plain`.
- Secondary anchor `plain-sonnet`.

Suite S1, split holdout (8 tasks never used for tuning), 3 reps, seeds from base 20260919.

**Primary hypothesis (H1), vs `plain`.** The shipped default is faster at non-inferior quality.
Decision rule (STUDY-DESIGN.md §8, unchanged), all of:
1. mechanism gate green on every rep
2. geometric-mean exec-time ratio <= 0.90
3. sign test p <= 0.05
4. cost ratio <= 1.00
5. successes >= plain - 1, with zero critical failures
6. >= 3 reps and >= 8 paired passing tasks

**Prediction** from the dev screen: time ratio ~0.55 (dev 0.55, 95% CI 0.44–0.69), cost ratio
~0.4, quality equal.

**Secondary (H2), vs `plain-sonnet`, descriptive only, no win claimed.** Time ratio ~1.0 (dev 0.95).
This is the model-confound check: on S1 the default is expected to equal "plain on the cheap model"
plus zero routing overhead.

**What would falsify H1:** a time ratio > 0.90, a p-value > 0.05, or more than one lost task.
