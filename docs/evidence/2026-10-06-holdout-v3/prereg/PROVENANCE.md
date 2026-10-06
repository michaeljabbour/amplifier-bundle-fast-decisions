# Preregistration provenance

| file | commit | commit time | subject | blob sha |
|---|---|---|---|---|
| `evals/paired/PREREGISTRATION-holdout-v3.md` | `6ea0fd3c52cb` | 2026-10-05T21:28:41-04:00 | Preregister S1 (holdout-v3): hypotheses H1-H7, config-freeze rule, stop rules; frozen panel 7356cf52 | `c3aa1fb1d4d0` |

## Preregistration precedes the schedule and the data

* preregistration commit time: 2026-10-05T21:28:41-04:00 (2026-10-06T01:28:41+00:00)
* schedule (`campaign/schedule.json`) created: 2026-10-06T01:29:00.667896+00:00  (0:00:19.667896 AFTER the preregistration commit)
* first session `actual_start` in `data/sessions.jsonl`: 2026-10-06T01:29:39.919472+00:00
* the preregistration commit is 0:00:58.919472 before the first session started; **PASS** (commit < schedule < first session)
* every session row carries `build_sha` = `6ea0fd3c52cba74aa770db13e9c27c5056de233d`: the campaign ran the code at the preregistration commit.

## Frozen inputs, checked against the preregistration commit (`git diff 6ea0fd3 HEAD`)

| file | sha256 (first 16) | status |
|---|---|---|
| `evals/paired/PREREGISTRATION-holdout-v3.md` | `7184ac23185bc38d` | unchanged since the commit |
| `evals/paired/holdout-v3.yaml` | `b91705ef1159b2db` | unchanged since the commit |
| `evals/cells.yaml` | `b4e7862abee705d8` | unchanged since the commit |
| `evals/paired.py` | `3d77225b1011e96e` | unchanged since the commit |
| `evals/v3/s1_analysis.py` | `5e81763045216531` | unchanged since the commit |
| `evals/v3/frozen_rule.json` | `fa01f97b26273a35` | unchanged since the commit |
| `evals/v3/rules.py` | `9ff0e82c58d11c94` | unchanged since the commit |
| `evals/paired/scenarios/holdout-v3/scenario-hashes.json` | `ea28711e37bc9bbb` | unchanged since the commit |

Stated plainly:
* Commit `6ea0fd3` is the preregistration; the design, cells, analysis script, frozen rule and scenario hashes were committed before it (`a11c24e`, `180c7cf`) and are unchanged since.
* Disclosed before the commit and never analysed: the 60-session smoke (`evals/paired/holdout-v3-smoke.yaml`), and a 10-cell preflight ($4.78; `evals/paired/holdout-v3-preflight.json`).
  The campaign also ran its own 8-session preflight before wave 1 (`campaign/preflight.json`); preflights are in the ledger ($6.96 for the two preflight entries).
* The run did NOT follow the preregistered stop rules in two ways, disclosed in `FAILURES.md` and `FLAGS.md`: the budget cap was raised 5000 -> 6300 on 2026-10-06 07:11 EDT, and mechanism-gate failures
  were not detected live (the gate is evaluated when rows are extracted), so the preregistered "stop" did not occur.
* Git commit times are author-controlled and the push time is not recorded in the repo, so ordering rests on commit timestamps.
