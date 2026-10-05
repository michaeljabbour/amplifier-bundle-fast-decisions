# Finding: the escalation/phase judge state's `task_prompt_head` is the `<system-reminders>` block, not the task

Status: **open, not fixed** (documented only; `src/` untouched). Found 2026-10-01 while rebuilding judge
payloads from session traces (`evals/judge_bench/traces/extract_traces.py`).

## What

`_judge_state` (`src/amplifier_fast_decisions/orchestrator.py:752-775`) builds the compact state for every
`_judge_state`-based question. Its task field is:

```python
# orchestrator.py:762
"task_prompt_head": _first_user_text(request)[:_JUDGE_STATE_TASK_PROMPT_CHARS],   # 300 chars (:501)
```

`_first_user_text` (`orchestrator.py:517-538`) returns the text of the **first** `role == "user"` message, unfiltered.
In Amplifier sessions that message is the injected `<system-reminders>` envelope. The real task is a later user
message. So the judge's 300-character "task" is always:

```
<system-reminders>
The blocks below were injected by the system. They are NOT from the user and are
NOT a request. They exist to help you assist the user. Proce
```

The same problem was already fixed for the read-shortcut state in `a3a2c03` (2026-09-25, `state.py`: "the judge's
task is the real user message, not an injected reminder envelope"). The difficulty router is unaffected: it uses
`_turn_user_text` (`orchestrator.py:541`), which skips reminder-only messages. `_first_user_text` has no other
caller, and no test asserts on `task_prompt_head`.

## Evidence

- **Corpus.** The first message of `transcript.jsonl` is a user message starting with `<system-reminders>` in
  **4,075 of 4,137** fast-decisions sessions:

  | Suite | Reminder first | Sessions |
  |---|---|---|
  | S1 | 2,485 | 2,547 |
  | S2 | 374 | 374 |
  | S3 | 145 | 145 |
  | other | 1,071 | 1,071 |

  The provider request has the same order. In the S3 session below, `llm:request.data.raw.messages[0]` is the
  1.7k-char reminders block; the task is `messages[1]`.
- **Direct call.** Calling the shipped `orchestrator._first_user_text` / `_judge_state` on the rebuilt request of
  `verified-v4/runs/django__django-13741__laya-prepared__r1` (session `5c43241e…`, step 4) gives
  `task_prompt_head = "<system-reminders>\nThe blocks below were injected…"`. In the same request,
  `orchestrator._turn_user_text` returns `"You are working in a git checkout of the django/django repository…"`.
- **Rebuilt payloads.** 20 of 20 escalation/phase payloads rebuilt in the survey
  (`.amplifier/evaluation/fast-decisions/20261001-realistic/traces/candidates.jsonl`) have the reminder head.

## Impact

- **Affected questions** (all opt-in):
  - HC05 escalation judge (`escalation_judge: judge`, `:1433-1484`)
  - HC05 phase judge (`effort_routing.phase_judge`, `:1343-1370`)
  - HC08 batched phase+escalation (`:1318-1335`)
  - HC10 decomposed escalation signals (`:1485-1528`)
- **Measured impact so far: none.** None of these ran in any logged session: there are 0 `escalation_judged`,
  `escalation_signals`, `phase_judged` or `decided_batch` events across `~/.amplifier/projects` and the
  fast-decisions telemetry.
- **If enabled.** The judge would decide "escalate?" or "which phase?" without seeing the task: only phase, counters,
  tool names and a 600-char tool excerpt. Any benchmark of these questions built from shipped payloads would measure
  that defect, not the judge. This is one reason escalation and phase are excluded from the trace split (`EXCLUDED.md`).

## Reproduce (read-only)

```bash
python3 - <<'EOF'
import sys; sys.dont_write_bytecode = True
sys.path[:0] = ["evals/judge_bench/traces", "src"]
import extract_traces as X
from amplifier_fast_decisions import orchestrator
p = next(f for f in X.events_files() if "django__django-13741__laya-prepared" in f and "verified-v4" in f)
info = X.session(p); ev, tr = X.parse_session(info); asst, routed, _ = X.step_map(ev, tr)
req = X.request_at(tr, asst, 3)
print(repr(orchestrator._first_user_text(req)[:80]))
print(repr(orchestrator._turn_user_text(req)[:80]))
EOF
```

## Suggested fix (not applied)

Take the head from the real user turn, either `_turn_user_text(request)` or the first message passing
`step_actions.is_user_turn`, as `state.py` has done since `a3a2c03`. Add a test with a reminder-first request. Any
HC05/HC08/HC10 evaluation should be re-baselined after the fix.
