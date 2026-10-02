# Preregistration provenance

| file | what | commit | commit time | subject | blob sha |
|---|---|---|---|---|---|
| `evals/paired/PREREGISTRATION-main-v1.md` | preregistration | `3aa2d1e0065d` | 2026-10-01T10:18:42-04:00 | Preregister the main-v1 paired measurement campaign | `6164d91cb612` |
| `evals/paired/scenarios/main-v1/SPLIT.md` | train/test split | `c1481d57743d` | 2026-10-01T08:42:47-04:00 | Main-v1 scenarios: preregistered train/test split, check fixes, refs consolidated, design main-v1.yaml | `d2135704d7db` |
| `evals/paired/scenarios/main-v1/split.json` | split (machine readable) | `c1481d57743d` | 2026-10-01T08:42:47-04:00 | Main-v1 scenarios: preregistered train/test split, check fixes, refs consolidated, design main-v1.yaml | `371725a74b89` |
| `evals/paired/main-v1.yaml` | campaign design | `c1481d57743d` | 2026-10-01T08:42:47-04:00 | Main-v1 scenarios: preregistered train/test split, check fixes, refs consolidated, design main-v1.yaml | `c2331de262a1` |

## Preregistration precedes the data

* preregistration commit time: 2026-10-01T10:18:42-04:00 (2026-10-01T14:18:42+00:00)
* schedule (`campaign/schedule.json`) created: 2026-10-01T14:19:34.085620+00:00
* first session `actual_start` in `data/sessions.jsonl`: 2026-10-01T14:24:54.609235+00:00
* gap: preregistration is 0:06:12.609235 before the first session started; **PASS**
* the split commit is earlier still (2026-10-01T08:42:47-04:00).
* the files are unchanged since: `git diff 3aa2d1e HEAD -- <prereg, SPLIT, split.json>` is empty (yes).
* `build_sha` in every session is `3aa2d1e0065d99f68dd6393097d988397515e2bf`, the preregistration commit itself: the candidate bundle under test was frozen at that commit.

Caveat: git commit times are author-controlled. The commit was pushed to `origin/eval/paired-measurement`; the push time is not recorded in the repo, so the ordering rests on commit timestamps plus the consistency of schedule creation (+52 s) and first session (+6 m 12 s) with them.

Harness changes after the preregistration (none edits the prereg, split or design). Note that the harness code which ran the campaign was not a commit: the Forge capacity wait (state backup dated Oct 1 20:40) and the failure-reason capture (present in state.json from Oct 2 04:59) were live in the working tree and were only committed as `dc1aa4e` on Oct 2 at 18:18, after the campaign ended. The candidate under test (`build_sha`) is a separate frozen copy, unaffected. Re-extracting rows with the committed harness reproduces the raw rows byte for byte (reproduce/README.md).

```
dc1aa4e 2026-10-02T18:18:18-04:00 Paired harness: Forge capacity waits, failure reasons, circuit breaker, launch stagger, caffeinate
7d67ef2 2026-10-02T09:44:42-04:00 Dashboard: work-weighted progress by arm x host, family, split and turn band; pairs complete; turns-based ETA
7e69a1d 2026-10-02T09:31:28-04:00 Live dashboard for paired campaigns (refreshes every 60 s, 127.0.0.1 only)
20fd152 2026-10-01T20:31:05-04:00 paired: settings guard ignores the CLI's updates.last_check timestamp; re-baseline legacy hashes on record
4c9ce44 2026-10-01T10:24:19-04:00 paired run/rows: load the design the schedule names, never fall back to the pilot design silently
```
