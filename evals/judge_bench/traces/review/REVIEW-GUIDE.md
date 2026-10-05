# Review guide: trace-derived read-shortcut cases

You will label **70 decision points** taken from real agent sessions. Each case is a moment where the
fast-decisions judge had to decide one of two things:

- **an option key**: run one of a few prepared read-only actions right away (read a file, or a window of lines);
- **`reason`**: let the main model decide the next step itself.

Your label becomes part of the ground truth for scoring judges. Please work alone. **Do not confer** with the other
reviewer, and do not open `pool.json`, the session logs, or anything else under `evals/judge_bench/traces/` except
this folder.

## What you get (`blind_packet.json`)

Each entry contains:

- **`id`**: opaque, in random order. It carries no information about the answer.
- **`kind`**: always `read_shortcut`.
- **`question`**: exactly what the judge was shown.
  - `instructions`: the question the judge was asked.
  - `state`: the judge's evidence, `{"observations": [...], "instruction": "..."}`. It holds the user's task and the
    latest messages and tool results, clipped to a fixed budget (usually 2,048 chars, hence the `…` cuts). The
    `instruction` field inside the state is part of what the judge saw.
  - `options`: one entry per prepared action (`action`, `purpose` with the file path and line range, `tool`), plus
    `reason`.
- **`next_host_actions`**: up to two things the main model actually did next, as tool name + short argument summary.
  This is evidence about one strong agent's choice, **not** the answer. An agent may read something not on offer,
  read in parallel, or take a detour.

## What to answer (per case)

Fill in a copy of `responses_template.json` named `responses-<your-name>.json`:

| Field | Value |
|---|---|
| `label` | One option key from `options` (e.g. `win_f7afebd2552d`) **or** `"reason"` |
| `confidence` | `"high"`, `"medium"` or `"low"` |
| `unanswerable` | `true` if the payload cannot support any defensible answer. For example: the task was clipped away, the options cannot be told apart, or the decisive evidence is cut off. Still give your best `label` |
| `rationale` | **30 words or fewer**: why this option, or why `reason` |

**How to decide.** Pick an option only if that read is **clearly the most useful immediate next step** toward the
user's task, given the task and the latest evidence. Pick `reason` when any of these hold:

- no offered read is clearly sufficient;
- a different action is better (search, edit, run tests, answer);
- the choice between options needs judgment the state does not support.

Ties between near-identical options, such as two windows of the same file, go to the option that covers the region
the evidence points at.

## Things that will look odd (ignore them)

- Workspace paths inside the state contain run names (e.g. `…__laya-prepared__r1/workspace`). They are artefacts of
  the experiment harness and say nothing about the answer.
- Some states begin with a long `<system-reminders>` block. That is genuinely what the judge saw in sessions recorded
  before 2026-09-25. Judge the case as shown.
- Option keys are hashes. Only `action` and `purpose` describe what an option does.
- When an action entry reads `final reply (no tool call)`, the agent stopped and answered.

## What happens next

Your labels are compared with an outcome-derived proposal you do not see:

- Cases where both reviewers match the proposal are kept.
- Disagreements go to adjudication.
- Cases marked `unanswerable` by either reviewer are reviewed and dropped if confirmed. That drop count is reported.

Whole tasks were assigned to holdout or dev before review, and the holdout ids are preregistered before any judge
is scored. Expect roughly 1–2 minutes per case.
