# Preregistration provenance

| file | commit | commit time | subject | blob sha |
|---|---|---|---|---|
| `evals/paired/PREREGISTRATION-effort-control-v1.md` | `b92a4dcf38d0` | 2026-10-05T00:15:44-04:00 | Effort-control follow-up: plain Sonnet at medium vs default effort on the 23 test scenarios (preregistered) | `3494a283274d` |

## Preregistration precedes the data

* preregistration commit time: 2026-10-05T00:15:44-04:00 (2026-10-05T04:15:44+00:00)
* schedule (`campaign/schedule.json`) created: 2026-10-05T04:09:00.364628+00:00
* first session `actual_start` in `data/sessions.jsonl`: 2026-10-05T04:16:00.047969+00:00
* gap: the preregistration commit is 0:00:16.047969 before the first session started; **PASS**
* the file is unchanged since that commit: `git diff b92a4dc HEAD -- evals/paired/PREREGISTRATION-effort-control-v1.md` is empty (yes).

Caveats, stated plainly:
* The schedule (and `plan.txt`) were created 0:06:43.635372 BEFORE the preregistration was committed (schedule first). The design file `evals/paired/effort-control-v1.yaml` and the analysis `evals/paired_effort.py` were first committed in the same commit as the preregistration, so the schedule was built from working-tree copies of them; this package cannot show that those copies equal the committed ones. The recorded order is: preflight smoke session (2 sessions, $0.52, mechanism check only, not analysed), schedule built, preregistration committed, first analysed session started. No outcome data from the analysed sessions existed before the commit.
* The first session started only 0:00:16.047969 after the commit. Git commit times are author-controlled and the push time is not recorded in the repo, so the ordering rests on commit timestamps alone.
* The run order within the schedule is seeded and was fixed at schedule creation.
