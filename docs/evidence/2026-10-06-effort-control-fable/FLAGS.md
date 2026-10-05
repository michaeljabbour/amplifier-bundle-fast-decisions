# The two flags in this campaign

Both are in `data/summary.json` (`cache_audit_flagged_sessions`, `killed_memory`). Neither changes the verdict: HF is supported as preregistered, and
in each sensitivity below.

## 1. Cache audit: go-linkedlist-r1-any-fable (the default-effort ANCHOR session)

* **What the audit saw:** 7 consecutive main requests (request_index 5-11, turns 2-4) each read **421 more cache tokens** than the session's own earlier writes
  plus the shared tools prefix could explain (cache_read 77,279 = 44,829 own + 32,029 shared tools prefix + 421). The surplus appears at request 5 and stays
  constant afterwards, i.e. it is one discrepancy that persists, not seven independent events.
* **Where it comes from, from the raw requests:** request 5 is the first of turn 2 and reports `cache_write` 0 with 4 uncached input tokens, although it adds a
  new user message (about 420 tokens) to the prompt; its sibling in the medium arm wrote 420 tokens at the same point. So those tokens were counted as a read
  instead of a write. Plausible causes, none provable from the logs: the new turn-2 user message was already cached by an earlier call the audit cannot see
  (a request not in `requests.jsonl`, e.g. the session-naming call), or the provider attributed a write to a read for that block.
  A cross-session leak is not plausible: the two arms carry different cache nonces in the system prompt (everything after it is a different prefix) and the
  surplus equals one user-message block, not a shared prefix. The tools-prefix allowance (32,100 tokens) was applied and is not the source.
* **Cost impact:** at Fable's rates (read $0.25/M, write $12.5/M) 421 tokens differ by $0.005 per session; at most $0.03 even if each of the 7 requests were
  mispriced. The pair's log cost ratio is -0.027 (arm $10.04 vs anchor $10.31).
* **How the analysis treated it:** `pairs.jsonl` copied only the ARM session's audit flag, so this pair was counted as audit-clean and cost-valid (45 valid
  pairs). Under the preregistered validity rule (both sessions audit-clean) it should have been excluded. That was a harness gap, now fixed in `evals/paired.py`
  (`build_pairs`; test `PairAuditPropagationTests`). The published rows are the unmodified campaign output.
* **Sensitivity, strict rule (this pair excluded, 44 pairs)** (`result/sensitivity.json`): geometric-mean ratio **0.854** (95% CI 0.825-0.882) vs the
  as-run 0.860 (0.833-0.885). HF supported either way.

## 2. Memory kill: py-go-counting-r2-any-fable (the default-effort ANCHOR session)

* **What happened** (`campaign/killed_memory.py-go-counting-r2-any-fable.json`): at 13:46:47Z the campaign watchdog stopped the session's agent process tree
  (4 processes) because it reached **8.19 GB** (cap 8.0 GB; the machine had 58.5 GB available). It was **turn 6**; the offending bash command had started at 13:46:16Z, about
  31 s earlier; turns 1-5 had passed. The worker survived, the turn ended with exit -15, and turns 7-14 were skipped.
* **Which process:** the agent's own bash tool call, a verification command it wrote itself: after a passing `pytest` run it executed a Python differential test of
  its refactored `go_counting.py` against a saved copy of the old version on 500 random boards plus a 150x150 board, calling the old implementation for every cell
  (a flood fill per cell). That script, not the harness, grew past the cap. It is agent behaviour in the default-effort arm, a task outcome, not an
  infrastructure failure.
* **How the analysis treated it:** the session is kept in `sessions.jsonl` with `killed_memory: true` and `cost_valid: false`; its pair (`py-go-counting`, rep 2)
  is `cost_valid: false`, so it is excluded from the cost endpoint (hence **45 of 46** cost-valid pairs; confirmed from `pairs.jsonl`). The quality endpoint is
  preregistered as **unfiltered**, so the pair is included there: the killed anchor scored turn-pass 0.357 and a failed final state against 1.0 for its medium
  partner. That is the one "medium-only" final pass in the McNemar table (45 both / 1 / 0), and it is +0.64 for that pair (+0.32 on the scenario's mean over its two reps).
* **Sensitivity, quality without the killed pair** (strict 44 pairs, killed pair dropped): mean turn-pass delta **+0.019** (95% CI -0.004 to +0.057) vs the
  as-run +0.033 (-0.002 to +0.080); still non-inferior (lower bound > -0.05). Cost is unchanged because the pair was already cost-invalid.

## Summary of the three analyses

| analysis | cost-valid pairs | cost ratio medium/default (95% CI) | turn-pass delta (95% CI) | HF |
|---|---:|---|---|---|
| as run (preregistered) | 45 | 0.860 (0.833-0.885) | +0.033 (-0.002 to +0.080) | supported |
| strict: also exclude the flagged-anchor pair | 44 | 0.854 (0.825-0.882) | +0.033 (-0.002 to +0.080) | supported |
| strict + killed pair dropped from quality | 44 | 0.854 (0.825-0.882) | +0.019 (-0.004 to +0.057) | supported |
