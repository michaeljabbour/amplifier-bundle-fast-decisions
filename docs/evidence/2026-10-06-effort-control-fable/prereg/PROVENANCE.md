# Preregistration provenance

| file | commit | commit time | subject | blob sha |
|---|---|---|---|---|
| `evals/paired/PREREGISTRATION-effort-control-fable-v1.md` | `249941c2e4d0` | 2026-10-05T08:33:19-04:00 | Preregister effort-control-fable-v1: design, plain-medium cell, preregistration | `5947b609ea91` |

## Preregistration precedes the schedule and the data

* preregistration commit time: 2026-10-05T08:33:19-04:00 (2026-10-05T12:33:19+00:00)
* schedule (`campaign/schedule.json`) created: 2026-10-05T12:33:29.355495+00:00  (0:00:10.355495 AFTER the preregistration commit)
* first session `actual_start` in `data/sessions.jsonl`: 2026-10-05T12:40:48.271845+00:00
* the preregistration commit is 0:07:29.271845 before the first session started; **PASS** (commit < schedule < first session)
* the file is unchanged since that commit: `git diff 249941c HEAD -- evals/paired/PREREGISTRATION-effort-control-fable-v1.md` is empty (yes).

What was committed when, stated plainly:
* Commit `249941c` contained the design (`evals/paired/effort-control-fable-v1.yaml`), the `plain-medium` cell (`evals/cells.yaml`) and the preregistration. The analysis script change (`evals/paired_effort.py`, Fable design, seed 20261006, McNemar and per-task-type blocks) and its tests were committed 7 s later in `fd6289e`, still before the schedule was created. The schedule was built from a clean working tree at `fd6289e`.
* Disclosed scratch feasibility check, run BEFORE the preregistration commit: a throwaway schedule in `~/dev/afast-paired/effort-control-fable-v1-preflight-scratch` (not the campaign schedule; not published) and a 2-session preflight (`plain`, `plain-medium`, $1.73) that confirmed Fable accepts the `reasoning_effort` parameter (`output_config.effort` absent vs `medium` on the main request). It was mechanism-only and produced no analysed outcome. The campaign itself ran its own 2-session preflight (`campaign/preflight.json`) before wave 1.
* The preregistration states the analysis rules (endpoints, bootstrap, seed 20261006, margins, exploratory items) before any analysed session; the run order inside the schedule is seeded and was fixed at schedule creation.
* One post-hoc item, labelled as such: the pair rows copied only the arm's cache-audit flag, so the pair whose ANCHOR session was flagged was kept as cost-valid. `FLAGS.md` reports the preregistered (as-run) result AND the strict sensitivity; the harness bug is fixed in a later commit (`build_pairs` now requires both sessions to be audit-clean) and the campaign rows were not regenerated.
* Git commit times are author-controlled and the push time is not recorded in the repo, so ordering rests on commit timestamps.
