# What went wrong operationally, stated plainly

Source: `campaign/supervisor.log`, `campaign/run.log`, `campaign/state.json`, `campaign/ledger.json`. Times are US Eastern (EDT) unless marked Z.

* **Outcome:** 240 of 240 waves done, 1,224 sessions kept, 0 infrastructure-failed sessions among the kept rows. 135 earlier wave attempts failed on infrastructure and were rerun
  whole (state.json: 240 done, 135 `infra_failed`, 1 `capacity_wait` attempt records), so 36% of attempts were infra failures. The preregistered rule ("infra-failed waves above 10% of attempted: pause and diagnose") was exceeded
  and the pauses below are that diagnosis; every failed wave was rerun from its start, never relaxed or patched.
* **Forge outage 03:24 - 07:07:** the circuit breaker stopped the run 5 times (runs 1-4 each ended EXIT 4 on a Forge daemon restart at 03:56Z, 05:01Z, 06:10Z, 07:23Z; run 5 at 03:24 ended EXIT 1 "not caused by a daemon
  restart"). Cause: Forge was crash-looping with EMFILE (too many open files) because **943 `git fsmonitor` daemons** had been left running by the workspace repos. Fix at 07:07: killed them, disabled
  fsmonitor for `~/dev/afast-paired` through `includeIf`, raised the Forge launchd `NumberOfFiles` to 65536, `maxSessions` 100, resumed at `--parallel 96`.
* **Two waves excluded, then rerun:** the supervisor excluded 2 waves hit by the 03:24-07:07 outage as infrastructure, not scenario; they were rerun at 12:00 (finished 12:25, EXIT 0).
* **Unrecorded attempt directories:** a launch killed at 07:11 left `w122-a2` on disk without a state record, so the next resume failed with FileExistsError (08:22, EXIT 1). Moved the
  unrecorded attempt dirs aside at 09:00 and resumed. Moved, not deleted; they are not in the rows.
* **Admission stall:** at 10:50 admission stalled at 3 running / 33 pending; restarted with unbuffered logs. Completed 11:42 (EXIT 0).
* **Budget cap raised 5000 -> 6300** at 07:11 on 2026-10-06 (actual/estimate 1.42, projected total about $5,790). **Deviation** from the preregistered ledger hard stop at $5,000, made while running, disclosed in `prereg/PROVENANCE.md`.
  Final ledger: **$4,975.51**, i.e. under the original $5,000 cap by $24.49. Of it: $6.96 preflights, about $1,150.66 on attempts that failed on infrastructure and were rerun, $3,817.90 on the 1,224 kept sessions
  (provider-reported; tools-normalized $3,812.80). The preregistered estimate for the kept sessions was $4,087 (kept sessions actual / estimate 0.93). The 1.42 is the supervisor's mid-run ratio of spend to estimate at 07:11, when the failed attempts and the outage reruns were already in the ledger; I did not recompute it.
* **Concurrency changes (`--parallel`):** 16 (plan) -> 32 (23:04, Forge maxSessions 34) -> 28 (23:17, load 25.4/14.4) -> 48 (23:25, maxSessions 110) -> 96 (23:32) -> 160 (23:47, maxSessions 190; target finish ~6am) -> 96 after the
  outage at 07:07. The preregistration states only the minimum (7). Wall time was therefore not what the prereg estimated, and some waves ran with more concurrent sessions than others (`concurrent_sessions` is in every row).
* **Stop rules not met in the letter:** (1) budget cap changed (above); (2) mechanism-gate failures are detected at row extraction, not live, so the preregistered stop did not trigger on the bleach-sanitize-review failures
  (see `FLAGS.md`); (3) infra-failed waves 36% > 10%, diagnosed above. Nothing was stopped and resumed by relaxing a gate.
* **Provenance of the code that ran:** every session row has `build_sha` 6ea0fd3c52cba74aa770db13e9c27c5056de233d, the preregistration commit. The installed Amplifier commit was constant at 62061032 in `run.log`.
