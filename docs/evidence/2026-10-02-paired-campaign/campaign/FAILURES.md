# Failed, excluded and retried attempts

Source of truth: `campaign/state.json` (every wave keeps its attempts; waves that were reset keep the earlier attempts in `history`),
`campaign/ledger.json` (spend per `<wave>#a<attempt>`), `campaign/run.log` and `campaign/supervisor.log`, the Forge daemon log
`~/Library/Logs/forge/daemon.err.log` (timestamps only; its other content is not published) and the macOS power log (`pmset -g log`).
Times are America/New_York (EDT, -04:00) and are the **start** of the attempt (creation time of its run directory); a failure time is only
given where an external event pins it.

## Summary

* 329 wave attempts in total: **280 accepted** (one per wave, 280 waves) and **49 failed**.
* Every failed attempt was an *infrastructure* failure (`transient`), none an agent or scenario failure; every wave was rerun until it completed. No wave is missing from the data.
* 10 waves were *excluded* by the harness after 3 failed attempts and then *reset* (`--reset-wave`) and rerun from attempt 4 (9 for the Forge session cap, 1 for the Mac sleeping); their 30 earlier attempts are the `history` entries in state.json. (Earlier notes counted all 10 as cap waves; state.json attributes 9 to the cap and 1, `markdown-tocclass-r1-opus`, to sleep.)
* The other 19 failed attempts were retried automatically by the harness and succeeded within 4 attempts.
* Spend on failed attempts: $103.9716 of $3527.29 total ledger spend; most failed attempts died before spending anything.
* Failed-attempt rows are not in `data/` (only the accepted attempt of a wave is extracted). The failed attempts' raw run directories exist in the raw tree.

| cause | failed attempts | sessions failed | ledger USD on them | how well established |
|---|---:|---:|---:|---|
| forge_session_cap | 31 | 119 | 0.0 | 27 recorded in reset notes; 4 inferred from timing |
| forge_daemon_restart | 11 | 37 | 48.5129 | recorded reason, each matches a `Shutting down daemon` entry in the Forge log |
| mac_sleep | 7 | 20 | 55.4587 | 3 recorded in a reset note; 4 inferred from timing |
| **total** | **49** | **176** | **103.9716** | |

## 1. Forge session cap (maxSessions 10) at `--parallel 32`

The Forge daemon allows `maxSessions` terminals (10 until Oct 2 09:20, then 26, then 30). At ~20:31 on Oct 1 the run was relaunched at `--parallel 32`; launches beyond the cap failed with `launch_error "Maximum sessions (10) reached"`, three times per wave, so the harness excluded the waves. This was a harness bug (it did not wait for capacity), fixed that evening (backup `state.json.bak-before-capacity-fix` is dated 20:40) but only committed as `dc1aa4e` on Oct 2 at 18:18, after the campaign ended ("Forge capacity waits, failure reasons, circuit breaker, launch stagger"); the run log of the later runs shows `waiting for Forge terminal capacity` and `--parallel 28 clamped to 23`. The excluded waves were reset and rerun as attempt 4. state.json before the fix is kept in the raw tree (`state.json.bak-before-capacity-fix`, not published).

Waves excluded for the cap (9): `config-matrix-r1-fable`, `go-dominoes-r2-opus`, `js-tournament-r2-opus`, `markdown-tocclass-r1-fable`, `ms-review-r1-fable`, `py-forth-r1-opus`, `rust-luhn-r2-opus`, `sales-orders-r1-fable`, `semver-review-r1-opus`.

Four more attempts (`toolz-interpose-r2-fable` a1-a2, `config-matrix-r1-opus` a1-a2) have no recorded reason but started at 20:33-20:34, inside the same burst and on the same ~40 s cadence as the recorded cap waves; they are classified as cap **by inference** and were retried successfully (not reset).

## 2. Forge daemon restarts

Attempts whose workers 'vanished mid-run' (Forge terminals closed under them). Each such attempt has a recorded `reason`, and each started shortly before a `Shutting down daemon...` entry in the Forge daemon log. Shutdowns in the campaign window (EDT): 10-02 05:05:52, 10-02 11:05:52, 10-02 15:55:26. No shutdown appears between the campaign start (Oct 1 10:24) and Oct 2 05:05. The first two Oct 2 shutdowns are exactly 6 h 00 m 00 s apart; the third is 4 h 50 m after the second. A ~6-hour period is therefore only evidenced twice, not as a steady cycle. The cause of the restarts is not recorded in any file I could read.

The harness response: `circuit breaker` (2 consecutive waves with infrastructure failure stop the run with exit 4 and no exclusion; `supervisor.log` shows an automatic resume 60 s later, 'breaker caused by Forge daemon restart at 2026-10-02T19:55:28.395Z'), and the next run adopted live sessions with `--resume`.

## 3. Mac clamshell sleep on battery

`pmset -g log` shows lid-closed sleeps while on battery, with periodic maintenance DarkWakes (the harness runs `caffeinate`, which cannot prevent clamshell sleep on battery):

* sleep 12:24:40 -> full wake 14:05:04 (EDT, on battery (97%))
* sleep 15:30:49 -> full wake 19:28:28 (EDT, on battery (100%))

Running sessions then logged `Connection error` retries and the Forge idle timeout (30 min in the Oct 2 config reload) closed them: the Forge log has 20 `Session idle timeout` entries between 12:57 and 19:22 on Oct 1. The recorded reset note for `markdown-tocclass-r1-opus` cites 'pmset 15:30-16:07'; the power log shows the second sleep lasting until 19:28 (with DarkWake maintenance windows), and that wave's third attempt started at 17:31, i.e. inside the sleep, so the note's window is the first interruption, not the whole outage.

Four attempts with no recorded reason (`rust-gradeschool-r2-fable` a1 12:14, `mistune-escape-r1-fable` a1 12:19, `pr-review-cart-r2-fable` a1 15:10 and a2 17:23) are classified as sleep **by inference**: each was running when a clamshell sleep began or was launched inside one, and all precede the harness gaining failure reasons.

## 4. Attempts with no recorded reason (honest accounting)

A preliminary tally spoke of 18 early attempts without a recorded reason. That number cannot be reproduced from the files; what they show:

* 38 failed attempts carry no per-attempt `reason` field: the 30 `history` attempts of the reset waves (explained only by a human-written, retrospective wave-level `reset_note`) and 8 attempts of waves that were retried automatically (the 4 cap-burst and 4 sleep attempts above). The reason field was added during Oct 2 (committed afterwards in `dc1aa4e`); only the 11 attempts from Oct 2 04:59 on have one.
* 18 = the 8 unannotated attempts + the 10 reset waves is the most plausible reading of that tally; if it meant something else it is not recoverable from these files.
* For none of the 38 is the cause *recorded at the time*. The classification above rests on the reset notes (30), start-time coincidence with the cap burst (4) and with clamshell-sleep windows (4). Treat those 8 as probable, not proven.

## 5. Process-level interruptions (`run.log`, `supervisor.log`)

* Oct 1, first lines of `run.log`, before the first session (timing inferred from the fix commit): `KeyError: 'api-docs'` (exit 1) because `run` fell back to the pilot design; fixed in `4c9ce44` (10:24:19), first session started 10:24:54.
* Oct 1 ~20:30: `settings.yaml changed since the campaign started` (exit 4): the CLI's `updates.last_check` timestamp changed the guarded hash. Re-baselined 20:31 with a recorded reason (`settings_rebaselined` in state.json); fixed in `20fd152`.
* Several `EXIT 143` (SIGTERM): the run was stopped by a signal. One is the 14:54 supervisor restart at `PARALLEL=28` (logged in `supervisor.log`); the cause of the others is not logged.
* Oct 2: `run.log` shows two circuit-breaker stops (exit 4), after the 11:05 and 15:55 Forge restarts. `supervisor.log` records run starts at 12:32:25, 14:54:19 (restart at `PARALLEL=28`) and 16:21:00 (automatic resume 60 s after the second stop was noticed), then `EXIT 0` and `campaign complete` at 17:39:07. `run.log` only holds the later runs; earlier output was overwritten.

## 6. Memory kill: `py-forth-r2-opus-aa`

The watchdog killed the agent tree of this A/A session at 2026-10-01T15:56:30.393009+00:00 UTC (reason `session_cap`: RSS 9.51 GB > per-session cap 8.0 GB, 66.8 GB available system-wide). The kill landed in turn 9 (failed), turn 10 was skipped; turns 1-8 passed. Handling (`session_row` in `evals/paired.py`: a watchdog kill is a *task outcome*, the session is kept, but its cost is not comparable; memory safety limits are identical across arms per the preregistration):

* the session is **kept**: `status` `agent_fail`, `turn_pass_frac` 0.8, `final_state_pass` false, so it counts for quality analyses;
* its **cost is invalid**: `cost_valid` false and `killed_memory` true in sessions.jsonl; the single pair it forms (`py-forth` rep 2, host opus, arm aa) has `cost_valid` false and `valid` false and must be excluded from every cost estimate;
* the wave was not rerun (a rerun would not be comparable with the other 4 sessions of the same wave), and no other session was killed (`summary.json` -> `killed_memory`).

## 7. Every failed attempt

| wave | attempt | outcome | sessions failed | started (EDT) | cause | evidence | USD spent |
|---|---:|---|---:|---|---|---|---:|
| rust-gradeschool-r2-fable | 1 | infra_failed->retried | 2 | 2026-10-01T12:14:39-04:00 | mac_sleep | INFERRED from start time (Oct 1 clamshell-sleep window, Forge idle timeouts) | 15.8241 |
| mistune-escape-r1-fable | 1 | infra_failed->retried | 1 | 2026-10-01T12:19:42-04:00 | mac_sleep | INFERRED from start time (Oct 1 clamshell-sleep window, Forge idle timeouts) | 10.0233 |
| pr-review-cart-r2-fable | 1 | infra_failed->retried | 3 | 2026-10-01T15:10:24-04:00 | mac_sleep | INFERRED from start time (Oct 1 clamshell-sleep window, Forge idle timeouts) | 9.8044 |
| markdown-tocclass-r1-opus | 1 | excluded->reset | 5 | 2026-10-01T15:25:13-04:00 | mac_sleep | recorded (wave reset_note) | 3.5183 |
| markdown-tocclass-r1-opus | 2 | excluded->reset | 5 | 2026-10-01T15:58:50-04:00 | mac_sleep | recorded (wave reset_note) | 0.0000 |
| pr-review-cart-r2-fable | 2 | infra_failed->retried | 1 | 2026-10-01T17:23:33-04:00 | mac_sleep | INFERRED from start time (Oct 1 clamshell-sleep window, Forge idle timeouts) | 10.4334 |
| markdown-tocclass-r1-opus | 3 | excluded->reset | 3 | 2026-10-01T17:31:52-04:00 | mac_sleep | recorded (wave reset_note) | 5.8552 |
| markdown-tocclass-r1-fable | 1 | excluded->reset | 4 | 2026-10-01T20:31:12-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| ms-review-r1-fable | 1 | excluded->reset | 3 | 2026-10-01T20:31:12-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| js-tournament-r2-opus | 1 | excluded->reset | 4 | 2026-10-01T20:31:12-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| rust-luhn-r2-opus | 1 | excluded->reset | 5 | 2026-10-01T20:31:12-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| go-dominoes-r2-opus | 1 | excluded->reset | 5 | 2026-10-01T20:31:12-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| ms-review-r1-fable | 2 | excluded->reset | 3 | 2026-10-01T20:31:25-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| js-tournament-r2-opus | 2 | excluded->reset | 4 | 2026-10-01T20:31:33-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| rust-luhn-r2-opus | 2 | excluded->reset | 5 | 2026-10-01T20:31:43-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| go-dominoes-r2-opus | 2 | excluded->reset | 5 | 2026-10-01T20:31:53-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| markdown-tocclass-r1-fable | 2 | excluded->reset | 4 | 2026-10-01T20:32:01-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| ms-review-r1-fable | 3 | excluded->reset | 3 | 2026-10-01T20:32:07-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| js-tournament-r2-opus | 3 | excluded->reset | 4 | 2026-10-01T20:32:15-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| rust-luhn-r2-opus | 3 | excluded->reset | 5 | 2026-10-01T20:32:25-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| go-dominoes-r2-opus | 3 | excluded->reset | 5 | 2026-10-01T20:32:35-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| markdown-tocclass-r1-fable | 3 | excluded->reset | 4 | 2026-10-01T20:32:43-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| py-forth-r1-opus | 1 | excluded->reset | 4 | 2026-10-01T20:32:50-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| sales-orders-r1-fable | 1 | excluded->reset | 3 | 2026-10-01T20:32:58-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| semver-review-r1-opus | 1 | excluded->reset | 4 | 2026-10-01T20:33:08-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| toolz-interpose-r2-fable | 1 | infra_failed->retried | 3 | 2026-10-01T20:33:18-04:00 | forge_session_cap | INFERRED from start time (inside the 20:31-20:35 burst, same cadence as the recorded cap waves) | 0.0000 |
| config-matrix-r1-fable | 1 | excluded->reset | 3 | 2026-10-01T20:33:18-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| config-matrix-r1-opus | 1 | infra_failed->retried | 4 | 2026-10-01T20:33:26-04:00 | forge_session_cap | INFERRED from start time (inside the 20:31-20:35 burst, same cadence as the recorded cap waves) | 0.0000 |
| py-forth-r1-opus | 2 | excluded->reset | 4 | 2026-10-01T20:33:33-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| sales-orders-r1-fable | 2 | excluded->reset | 3 | 2026-10-01T20:33:39-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| semver-review-r1-opus | 2 | excluded->reset | 4 | 2026-10-01T20:33:47-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| config-matrix-r1-fable | 2 | excluded->reset | 3 | 2026-10-01T20:33:53-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| toolz-interpose-r2-fable | 2 | infra_failed->retried | 3 | 2026-10-01T20:33:59-04:00 | forge_session_cap | INFERRED from start time (inside the 20:31-20:35 burst, same cadence as the recorded cap waves) | 0.0000 |
| config-matrix-r1-opus | 2 | infra_failed->retried | 4 | 2026-10-01T20:34:07-04:00 | forge_session_cap | INFERRED from start time (inside the 20:31-20:35 burst, same cadence as the recorded cap waves) | 0.0000 |
| py-forth-r1-opus | 3 | excluded->reset | 4 | 2026-10-01T20:34:15-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| sales-orders-r1-fable | 3 | excluded->reset | 3 | 2026-10-01T20:34:21-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| semver-review-r1-opus | 3 | excluded->reset | 4 | 2026-10-01T20:34:30-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| config-matrix-r1-fable | 3 | excluded->reset | 3 | 2026-10-01T20:34:35-04:00 | forge_session_cap | recorded (wave reset_note) | 0.0000 |
| rust-gradeschool-r2-opus | 1 | infra_failed->retried | 4 | 2026-10-02T04:59:25-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 05:05:52 | 3.3704 |
| voluptuous-number-r1-opus | 1 | infra_failed->retried | 4 | 2026-10-02T10:46:42-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 11:05:52 | 7.8778 |
| sqlparse-realname-r1-opus | 1 | infra_failed->retried | 4 | 2026-10-02T11:00:27-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 11:05:52 | 6.3483 |
| support-workload-r2-opus | 1 | infra_failed->retried | 4 | 2026-10-02T11:03:56-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 11:05:52 | 2.6261 |
| pflag-mixed-r2-fable | 1 | infra_failed->retried | 3 | 2026-10-02T11:04:06-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 11:05:52 | 2.0466 |
| expense-anomaly-r1-fable | 1 | infra_failed->retried | 3 | 2026-10-02T11:04:15-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 11:05:52 | 2.6885 |
| cachetools-params-r1-opus | 1 | infra_failed->retried | 4 | 2026-10-02T15:44:05-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 15:55:26 | 6.6994 |
| survey-analysis-r2-fable | 1 | infra_failed->retried | 1 | 2026-10-02T15:47:36-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 15:55:26 | 8.0570 |
| discrepancy-docs-r2-fable | 1 | infra_failed->retried | 3 | 2026-10-02T15:48:03-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 15:55:26 | 4.3124 |
| pr-review-cart-r1-fable | 1 | infra_failed->retried | 3 | 2026-10-02T15:49:30-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 15:55:26 | 3.2081 |
| go-dominoes-r1-opus | 1 | infra_failed->retried | 4 | 2026-10-02T15:54:29-04:00 | forge_daemon_restart | recorded reason + daemon log shutdown 10-02 15:55:26 | 1.2783 |
