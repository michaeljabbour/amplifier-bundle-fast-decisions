# Goal

**Make Amplifier drastically cheaper and faster on real work, at equal quality, by putting a fast judge
(Jev, ~0.15 s per typed decision) in charge of the small decisions an agent loop makes at every step.**

"Real work" means the owner's actual sessions (large repos, long multi-step requests, helper agents), not only
small benchmark tasks. The measured baseline on 2026-09-25 (two real projects, one day): 2,882 model calls,
about $362 provider-reported cost, a median of 24 model calls per request (p90 112, max 258), 4,172 bash calls,
93 helper-agent launches, and every call re-reading a 100k+ token prompt (~$0.13 per call on Opus 5.5).

## What the judge decides (per step, not per request)

At each point where the loop would call the model, the judge chooses the cheapest action that keeps quality:

1. **Skip the model:** run a prepared, deterministic action (read the file just named, re-run the command that
   just failed, answer from a tool result) when the next step is predictable.
2. **Cheaper model for this step:** routine continuations (read a tool result, issue the obvious next call) on
   Sonnet or Haiku, accounting for each model's own prompt cache so switching does not cost more than it saves.
3. **Block or right-size waste:** a helper-agent launch that could be done inline, a repeated or looping call,
   an oversized tool output.
4. **Full model:** anything that needs real reasoning, planning, or a code change in a large repo.

Choosing one model for a whole request (what shipped first) is only a special case of (2) and, with Opus 5.5 as
the default model, saves almost nothing.

## Success criteria (all measured, all at equal quality)

On the owner's real workload (replayed from recorded sessions where possible) **and** on preregistered
benchmarks with fresh held-out tasks, alternating run order, and the answering model recorded per call:

| Metric | Target vs plain Amplifier on the same default model |
|---|---|
| Cost per request | **≤ 0.50×** |
| Model calls per request (full-model calls) | **≤ 0.60×** |
| Wall time per request | **≤ 0.70×** |
| Quality | Task pass rate and SWE-bench resolved count within run-to-run noise (non-inferiority as in `evals/STUDY-DESIGN.md` §8) |

Plus: the dashboard's savings numbers must match recomputation from stored records, per project, and exclude
test/benchmark traffic.

## Method

1. Measure first: classify every model call in real sessions (routine continuation, exploration, reasoning,
   final answer, delegation, loop) and price each bucket, including the cache cost of switching models.
2. Build the per-step router behind settings, with a receipt for every decision (what was decided, by whom, what
   it saved).
3. Screen on the large-repo and multi-turn suites with the owner's default model; confirm on fresh preregistered
   holdouts; keep quality guards (large-repo edits stay on the full model unless evidence says otherwise).
4. Ship only what is confirmed; report savings honestly, including where it does not help.

## Status

See `docs/RESULTS-2026-09-24.md` (top update) for what has been measured so far. As of 2026-09-25 the goal is
**not met**: the shipped router picks one model per request and saved close to nothing on the owner's real work.
