# Excluded from the trace-derived split, and why

The trace split (`pool.json`) contains **read-shortcut only**. All other decision kinds were surveyed (counts,
method and file:line references are in
`.amplifier/evaluation/fast-decisions/20261001-realistic/traces/survey.md`). Each was excluded for one of two
reasons: its payload is unfit, or no honest label exists.

| Kind | Why excluded | Evidence |
|---|---|---|
| **difficulty** (`task_difficulty`) | **No honest complex side, from traces or otherwise.** S1/S2 outcome labels are degenerate. On SWE-bench Verified, every human-annotated complex instance is in the set the difficulty question was tuned on | S1/S2: of 93 graded tasks, 86 simple / 1 complex / 6 ambiguous; 3,020 of 3,212 graded runs passed. SWE-bench Verified (500): 194 `<15 min`, 261 `15 min-1 h`, 42 `1-4 h`, 3 `>4 h`. **All 45** `1-4 h`/`>4 h` instances are in `~/dev/afast-ev/difficulty-dataset.jsonl`, which tuned `DIFFICULTY_INSTRUCTIONS/CRITERIA` (`evals/difficulty/probe.py`, AUC 0.83). Outside it: 0 complex. In the traced S3 runs (v4), both `1-4 h` instances (`pytest-dev__pytest-6197`, `django__django-15503`) are tuning-set members. A simple-only slice cannot measure discrimination, so nothing was included |
| **escalation** (`escalation_judge`) | Never ran live, so payloads are counterfactual. Its state is broken. Labels are rule echoes | 0 `escalation_judged` / `escalation_signals` / `decided_batch` events in the corpus. `task_prompt_head` is the `<system-reminders>` block (`FINDING-judge-state-task-head.md`). `last_tool_result_excerpt` is a `ToolResult` stringification the transcript cannot reproduce exactly. Positive labels = the `escalated_test_failure` rule firing; negatives inherit the ~94% pass ceiling; the step a human would escalate at is unknowable |
| **phase** (`phase_classification`) | Never ran live. The label is definitional. Same broken state | 0 `phase_judged` events. `effort.PHASE_CRITERIA` restates the deterministic classifier; the rebuilt rule matches the logged phase in 1,863 of 1,868 points, so a "label" only tests recovery of the rule from a lossy state. The next host action contradicts the rule often (n=300 sessions: rule `explore` but next call an edit, 211; rule `implement` but next call a read, 136) |
| **tool-risk** (`destructive` / `touches_production` / `category`) | Never ran live. The label cannot be determined from the payload | The state is `{tool, argument_keys}`, with values redacted by design (`orchestrator.py:994-1001`). There are 107 distinct payloads over 43,627 tool calls. **41%** of calls (18,095) share their payload with the opposite label: `bash:[command]` alone is 13,359 not destructive / 1,479 destructive. Any judge is capped at the per-payload majority |

## Excluded within read-shortcut

| Subset | Count | Why |
|---|---|---|
| Fast-routed steps | 226 decisions | The executed action was the logged judge's own pick. The host model never saw the step, so the label would be circular |
| Suite X (ad-hoc tooling runs) | 176 sessions | Most workspaces lived in `/private/tmp` and are gone, so candidates cannot be regenerated or verified; not a benchmark suite |
| Rebuild not exact | 17 decisions | At least one of the 5 state scalars or the candidate ids / order hash failed to match |
| Exact duplicates | 271 decisions | Same state (modulo workspace path) and same candidates as a kept decision, usually another arm or rep of the same task |
| Shadow-mode proposals (`shadow_proposed`) | 1,646 | Built by a different path (`observer._snapshot`) that was not rebuilt or verified. The logged `shadow_agreement` requires an exact tool + argument-hash match, so `read_file` never matches a `fast_workspace` candidate |

## What would unblock them

- **difficulty**: an annotated source disjoint from the tuning set, or a suite with a cheap-model arm where the cheap tier actually fails.
- **escalation / phase**: fix the task head first (see the finding), then run the judges live in shadow so real payloads are logged.
- **tool-risk**: a payload that carries a redacted command shape, not just argument keys.
