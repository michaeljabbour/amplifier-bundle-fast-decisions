"""Campaign memory watchdog, launch gate, safety preflight, parallel default. Fake process tables only: nothing here
allocates memory, kills a real process or runs scenario code."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from paired_helpers import FakeBackend, FakeProbe, make_design, paired, ps, write_events, write_inline_scenario
from test_paired_rows import SPEC, T0, meta, result_doc

import memguard

GB = 2 ** 30


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "camp"
        self.kills = []

    def session_dir(self, wave, sess, worker_pid=101):
        d = self.root / wave / sess
        (d / "workspace").mkdir(parents=True)
        (d / "running.json").write_text(json.dumps({"controller_pid": worker_pid}))
        return d

    def rows_for(self, wave, sess, base_pid, agent_gb, started=1000.0, worker_gb=0.1):
        ws = str(self.root / wave / sess / "workspace")
        return [{"pid": base_pid, "ppid": 1, "rss": int(0.01 * GB), "cwd": ws, "started": started},                   # zsh
                {"pid": base_pid + 1, "ppid": base_pid, "rss": int(worker_gb * GB), "cwd": ws, "started": started},   # forge worker
                {"pid": base_pid + 2, "ppid": base_pid + 1, "rss": int(1.0 * GB), "cwd": ws, "started": started + 1},  # amplifier
                {"pid": base_pid + 3, "ppid": base_pid + 2, "rss": int(agent_gb * GB), "cwd": ws + "/pkg", "started": started + 2}]  # go test

    def campaign(self, parallel=6, watchdog=None):
        scn = write_inline_scenario(self.tmp / "scn")
        design = make_design(self.tmp, scn)
        specs = {s.id: s for s in paired.load_specs(design)}
        plan = paired.build_plan(design, list(specs.values()), reps=1, hosts=["opus"], arms=["anchor", "aa"], seed=1, budget_usd=None,
                                 parallel=6, scenarios={"tiny-demo"})
        out = self.tmp / "out"
        out.mkdir()
        ctx = paired.Ctx(out=out, design=design, cells_doc={}, suites_doc={}, specs=specs,
                         snapshots={sid: str(ps.materialize(s, self.tmp / "snaps")) for sid, s in specs.items()}, plan=plan,
                         campaign_root=self.tmp / "camp2", candidate_source="x", candidate_sha=None, baseline_source="x", seed=1,
                         decide_fn=lambda p, w, c: "cheap", sleep=lambda s: None)
        return ctx, FakeBackend(self.tmp / "b", specs)

    def wd(self, probe, **kw):
        def kill(pids, *a, **k):
            self.kills.append(sorted(pids))
            probe.rows = [r for r in probe.rows if r["pid"] not in pids]
            probe.avail += kw.pop("reclaim_gb", 0) * GB if False else 0
        logs = []
        w = paired.Watchdog(self.root, probe=probe, kill=kw.pop("kill", kill), log=logs.append, **kw)
        w.logs = logs
        return w


class SessionCapTests(Base):
    def test_over_cap_session_is_killed_below_the_worker_and_marked(self):
        d = self.session_dir("w000-a1", "s-anchor", worker_pid=101)
        self.session_dir("w000-a1", "s-aa", worker_pid=201)
        probe = FakeProbe(self.rows_for("w000-a1", "s-anchor", 100, agent_gb=9.0) + self.rows_for("w000-a1", "s-aa", 200, agent_gb=2.0)
                          + [{"pid": 999, "ppid": 1, "rss": 50 * GB, "cwd": "/Users/x/elsewhere", "started": 1.0}])    # unrelated: never touched
        w = self.wd(probe, session_cap_gb=8)
        info = w.tick()
        self.assertEqual(self.kills, [[102, 103]])                       # amplifier + go test only: NOT zsh 100, NOT worker 101
        marker = json.loads((d / paired.KILL_MARKER).read_text())
        self.assertEqual((marker["reason"], marker["pids"]), ("session_cap", [102, 103]))
        self.assertGreater(marker["rss_gb"], 8)
        self.assertEqual([k["session"] for k in w.killed], ["w000-a1/s-anchor"])
        self.assertFalse((self.root / "w000-a1" / "s-aa" / paired.KILL_MARKER).exists())
        self.assertTrue(any("WATCHDOG killed w000-a1/s-anchor" in l for l in w.logs))
        self.assertIn("w000-a1/s-aa", info["sessions"])

    def test_under_cap_is_left_alone_and_peak_is_tracked(self):
        self.session_dir("w000-a1", "s-anchor")
        probe = FakeProbe(self.rows_for("w000-a1", "s-anchor", 100, agent_gb=3.0))
        w = self.wd(probe, session_cap_gb=8)
        w.tick()
        probe.rows = self.rows_for("w000-a1", "s-anchor", 100, agent_gb=5.0)
        w.tick()
        probe.rows = self.rows_for("w000-a1", "s-anchor", 100, agent_gb=1.0)
        w.tick()
        self.assertEqual((self.kills, w.killed), ([], []))
        self.assertAlmostEqual(w.peak["w000-a1/s-anchor"] / GB, 6.0, places=1)

    def test_children_with_a_cwd_outside_the_root_belong_to_their_parents_session(self):
        self.session_dir("w000-a1", "s-anchor")
        rows = self.rows_for("w000-a1", "s-anchor", 100, agent_gb=0.5)
        rows.append({"pid": 110, "ppid": 103, "rss": 9 * GB, "cwd": "/tmp/go-build123", "started": 1003.0})     # go build in a temp dir
        w = self.wd(FakeProbe(rows), session_cap_gb=8)
        w.tick()
        self.assertEqual(self.kills, [[102, 103, 110]])

    def test_a_session_without_running_json_has_no_protected_worker_and_is_still_capped(self):
        d = self.root / "w000-a1" / "s-x" / "workspace"
        d.mkdir(parents=True)
        w = self.wd(FakeProbe(self.rows_for("w000-a1", "s-x", 100, agent_gb=9)), session_cap_gb=8)
        w.tick()
        self.assertEqual(len(self.kills), 1)

    def test_sessions_maps_cwd_to_wave_and_session_only_inside_the_root(self):
        rows = self.rows_for("w000-a1", "s-anchor", 100, 1) + [{"pid": 5, "ppid": 1, "rss": 1, "cwd": str(self.tmp / "other"), "started": 1}]
        groups = self.wd(FakeProbe(rows)).sessions(rows)
        self.assertEqual(list(groups), ["w000-a1/s-anchor"])
        self.assertEqual(len(groups["w000-a1/s-anchor"]["rows"]), 4)


class SystemMemoryTests(Base):
    def test_pause_below_the_floor_and_resume_above(self):
        self.session_dir("w000-a1", "s-anchor")
        probe = FakeProbe(self.rows_for("w000-a1", "s-anchor", 100, 1), available_gb=20)
        w = self.wd(probe, pause_floor_gb=32, hard_floor_gb=8)
        self.assertTrue(w.tick()["paused"])
        self.assertFalse(w.ok_to_launch.is_set())
        self.assertEqual(len(w.paused_log), 1)
        w.tick()
        self.assertEqual(len(w.paused_log), 1)                           # announced once
        probe.avail = 60 * GB
        self.assertFalse(w.tick()["paused"])
        self.assertTrue(w.ok_to_launch.is_set())
        self.assertTrue(any("resuming" in l for l in w.logs))
        self.assertEqual(self.kills, [])                                  # pausing never kills

    def test_default_pause_floor_is_max_32gb_or_25_percent(self):
        self.assertEqual(paired.pause_floor_bytes(128 * GB), 32 * GB)
        self.assertEqual(paired.pause_floor_bytes(256 * GB), 64 * GB)
        self.assertEqual(paired.pause_floor_bytes(16 * GB), 32 * GB)
        self.assertEqual(paired.Watchdog(self.root, probe=FakeProbe(total_gb=128)).pause_floor, 32 * GB)
        self.assertEqual((paired.SESSION_CAP_GB, paired.HARD_FLOOR_GB), (8.0, 16.0))

    def test_hard_floor_kills_the_newest_session_one_per_tick_until_recovered(self):
        for sess in ("s-old", "s-mid", "s-new"):
            self.session_dir("w000-a1", sess, worker_pid={"s-old": 101, "s-mid": 201, "s-new": 301}[sess])
        rows = (self.rows_for("w000-a1", "s-old", 100, 1, started=1000) + self.rows_for("w000-a1", "s-mid", 200, 1, started=2000)
                + self.rows_for("w000-a1", "s-new", 300, 1, started=3000))
        probe = FakeProbe(rows, available_gb=10)

        def kill(pids, *a, **k):
            self.kills.append(sorted(pids))
            probe.rows = [r for r in probe.rows if r["pid"] not in pids]
            probe.avail += 7 * GB                                          # freeing one session returns 7 GB
        w = self.wd(probe, kill=kill, pause_floor_gb=32, hard_floor_gb=16)
        w.tick()
        self.assertEqual([k["session"] for k in w.killed], ["w000-a1/s-new"])        # newest first
        w.tick()                                                                      # 17 GB available: above the hard floor
        self.assertEqual([k["session"] for k in w.killed], ["w000-a1/s-new"])
        probe.avail = 9 * GB
        w.tick()
        self.assertEqual([k["session"] for k in w.killed], ["w000-a1/s-new", "w000-a1/s-mid"])
        self.assertEqual(json.loads((self.root / "w000-a1" / "s-new" / paired.KILL_MARKER).read_text())["reason"], "system_floor")
        self.assertFalse((self.root / "w000-a1" / "s-old" / paired.KILL_MARKER).exists())

    def test_max_system_use_pauses_then_kills_newest_at_115_percent(self):
        for sess, wp in (("s-a", 101), ("s-b", 201)):
            self.session_dir("w000-a1", sess, worker_pid=wp)
        rows = self.rows_for("w000-a1", "s-a", 100, 6, started=1000) + self.rows_for("w000-a1", "s-b", 200, 6, started=2000)   # ~7 GB agent each
        probe = FakeProbe(rows, available_gb=100)
        w = self.wd(probe, max_system_use_gb=13, session_cap_gb=20, pause_floor_gb=32, hard_floor_gb=16)
        self.assertTrue(w.tick()["paused"])                                           # ~14.2 GB > 13
        self.assertEqual(self.kills, [])                                              # but < 115%: no kill
        w.max_use = int(10 * GB)                                                      # 14.2 > 11.5 (115%): now kill the newest
        w.tick()
        self.assertEqual([k["session"] for k in w.killed], ["w000-a1/s-b"])


class GateAndCampaignTests(Base):
    def test_gate_blocks_until_memory_recovers(self):
        probe = FakeProbe([], available_gb=10)
        w = self.wd(probe, pause_floor_gb=32, hard_floor_gb=4)
        w.tick()
        waits = []

        def fake_sleep(_):
            waits.append(1)
            probe.avail = 60 * GB
            w.tick()
        w.sleep = fake_sleep
        w.gate(lambda m: self.kills.append(m))
        self.assertEqual(len(waits), 1)
        self.assertTrue(w.ok_to_launch.is_set())
        self.assertTrue(any("waiting for system memory" in str(k) for k in self.kills))

    def test_no_wave_is_launched_while_memory_is_short(self):
        ctx, be = self.campaign()
        probe = FakeProbe([], available_gb=10)
        w = paired.Watchdog(self.tmp / "camp2", probe=probe, pause_floor_gb=32, hard_floor_gb=4, interval=0.02, sleep=lambda s: time.sleep(0.02),
                            log=lambda m: None)
        result = {}
        th = threading.Thread(target=lambda: result.update(code=paired.run_campaign(ctx, be, budget_usd=1000, parallel=6, resume=False,
                                                                                    policy_config={}, watchdog=w, log=lambda *_: None)))
        th.start()
        time.sleep(0.5)
        self.assertEqual(be.prepared, [])                                  # paused: nothing launched
        probe.avail = 80 * GB
        th.join(timeout=30)
        self.assertFalse(th.is_alive())
        self.assertEqual((result["code"], len(be.prepared)), (0, 1))
        self.assertFalse(w.is_alive() and not w.stop_event.is_set())

    def test_a_wave_larger_than_parallel_is_refused_not_deadlocked(self):
        ctx, be = self.campaign()
        with self.assertRaises(paired.PairedError) as cm:
            paired.run_campaign(ctx, be, budget_usd=1000, parallel=1, resume=False, policy_config={}, log=lambda *_: None)
        self.assertEqual(cm.exception.code, paired.EXIT_PRECONDITION)
        self.assertIn("--parallel", cm.exception.reason)
        self.assertEqual(be.prepared, [])


class SafetyPreflightTests(Base):
    def test_refuses_when_available_memory_is_below_the_floor_and_lists_top_consumers(self):
        rows = [{"pid": 1, "ppid": 0, "rss": 3 * GB, "cwd": "/a", "started": 1}, {"pid": 2, "ppid": 0, "rss": 9 * GB, "cwd": "/big", "started": 1}]
        with self.assertRaises(paired.PairedError) as cm:
            paired.memory_safety_check(FakeProbe(rows, available_gb=20, total_gb=128))
        self.assertEqual(cm.exception.code, paired.EXIT_PRECONDITION)
        msg = cm.exception.reason
        self.assertIn("20.0 GB", msg)
        self.assertLess(msg.index("pid 2"), msg.index("pid 1"))            # biggest first
        self.assertIn("/big", msg)

    def test_passes_with_room_and_honours_an_explicit_floor(self):
        self.assertTrue(paired.memory_safety_check(FakeProbe(available_gb=90))["ok"])
        with self.assertRaises(paired.PairedError):
            paired.memory_safety_check(FakeProbe(available_gb=90), floor_bytes=100 * GB)

    def test_cmd_run_refuses_before_touching_forge(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        ctx, be = self.campaign()
        low = FakeProbe([{"pid": 7, "ppid": 1, "rss": 40 * GB, "cwd": "/hog", "started": 1}], available_gb=10)
        with patch.object(paired, "_ctx_from_schedule", lambda out, args=None: ctx), patch.object(paired, "RealProbe", lambda: low), \
                patch.object(paired, "ForgeBackend", lambda: be), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = paired.main(["run", "--out", str(ctx.out), "--budget-usd", "100"])
        self.assertEqual(code, paired.EXIT_PRECONDITION)
        self.assertIn("refusing to start", err.getvalue())
        self.assertIn("/hog", err.getvalue())
        self.assertEqual(be.prepared, [])


class RealProbeTests(unittest.TestCase):
    def test_real_table_has_this_process_with_cwd_and_rss(self):
        rows = paired.RealProbe().table(Path.cwd())
        me = next(r for r in rows if r["pid"] == os.getpid())
        self.assertGreater(me["rss"], 0)
        self.assertEqual(Path(me["cwd"]).resolve(), Path.cwd().resolve())

    def test_lsof_fallback_without_psutil(self):
        with patch.object(memguard, "psutil", None):
            rows = paired.RealProbe().table(Path.cwd())
        me = next(r for r in rows if r["pid"] == os.getpid())
        self.assertGreater(me["rss"], 0)
        self.assertTrue(me["cwd"])

    def test_etime_parsing(self):
        self.assertEqual(paired._etime_seconds("01:02"), 62)
        self.assertEqual(paired._etime_seconds("1-00:00:05"), 86405)
        self.assertEqual(paired._etime_seconds("3:04:05"), 3 * 3600 + 4 * 60 + 5)


class RowsKilledMemoryTests(Base):
    def test_killed_memory_sessions_are_kept_flagged_and_invalid_for_cost(self):
        sess_root, root = self.tmp / "sessions", self.tmp / "camp3" / "w000-a1"
        sessions = []
        for arm, kind in (("anchor", "plain"), ("shipped", "fd")):
            key = f"tiny-demo-r1-opus-{arm}"
            sessions.append(meta(key=key, arm=arm, kind=kind, nonce=f"n-{arm}"))
            (root / key / "workspace").mkdir(parents=True)
            (root / key / "result.json").write_text(json.dumps(result_doc([(T0, T0 + 10), (T0 + 20, T0 + 30)], sid=f"sid-{arm}")))
            extra = [{"ts": "2026-10-01T00:00:00+00:00", "event": "fast_decisions:difficulty_judged", "event_id": "e1", "data": {}}] if kind == "fd" else []
            write_events(sess_root / f"sid-{arm}" / "events.jsonl", [
                {"t": T0 + 1, "model": "claude-opus-5-5", "uncached": 10, "read": 0, "write": 100, "output": 5},
                {"t": T0 + 21, "model": "claude-opus-5-5", "uncached": 10, "read": 100, "write": 10, "output": 5}], extra)
        (root / "tiny-demo-r1-opus-shipped" / paired.KILL_MARKER).write_text(json.dumps({"reason": "session_cap", "rss_gb": 9.1}))
        out = self.tmp / "out2"
        out.mkdir()
        (out / "schedule.json").write_text(json.dumps({"nonce_mode": "per_session", "plan_id": "p", "scenarios": {"tiny-demo": {"scenario_hash": "h"}}}))
        (out / "state.json").write_text(json.dumps({"waves": {"w": {"status": "done", "accepted_attempt": 1, "attempts": [
            {"attempt": 1, "root": str(root), "status": "done", "sessions": sessions, "wave_valid": True}]}}}))
        with patch.object(paired, "sessions_dir_for_workspace", lambda ws: sess_root):
            summary = paired.extract_rows(out, FakeBackend(self.tmp / "b", []), specs={"tiny-demo": SPEC}, snap_stats={})
        self.assertEqual(summary["killed_memory"], ["tiny-demo-r1-opus-shipped"])
        rows = {json.loads(l)["arm"]: json.loads(l) for l in (out / "rows" / "sessions.jsonl").read_text().splitlines()}
        self.assertEqual((rows["shipped"]["killed_memory"], rows["shipped"]["cost_valid"]), (True, False))
        self.assertEqual((rows["anchor"]["killed_memory"], rows["anchor"]["cost_valid"]), (False, True))
        self.assertEqual(rows["shipped"]["killed_memory_info"]["reason"], "session_cap")
        pair = json.loads((out / "rows" / "pairs.jsonl").read_text().splitlines()[0])
        self.assertEqual((pair["cost_valid"], pair["valid"]), (False, False))


class GraderGuardTests(unittest.TestCase):
    """Scenario graders run under memguard: a memory kill is a failed check labelled resource_limit."""

    def test_defaults_are_4gb_and_300s(self):
        self.assertEqual(os.environ.get(memguard.ENV_CAP), "4.0")
        self.assertEqual(os.environ.get(memguard.ENV_TIMEOUT), "300")

    def test_cmd_check_that_blows_the_cap_fails_as_resource_limit_not_infra(self):
        import copy
        from paired_helpers import INLINE_SCENARIO
        d = copy.deepcopy(INLINE_SCENARIO)
        d["id"] = "tiny-hog"
        d["workspace"]["files"]["hog.py"] = "import time\nc = []\nfor i in range(40):\n    c.append(b'a' * (25 * 2**20))\n    time.sleep(0.05)\ntime.sleep(20)\n"
        d["turns"][0]["checks"] = [{"kind": "tests", "runner": "cmd", "cmd": "python3 hog.py"}]
        spec = ps.parse(d)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        snap = ps.materialize(spec, tmp / "snaps")
        ws = tmp / "ws"
        shutil.copytree(snap / "workspace", ws)
        with patch.dict(os.environ, {memguard.ENV_CAP: "0.3"}):
            q = ps.grade_turn(spec, 1, ws, "", snap)
        self.assertIn("resource_limit", q["failure_labels"])
        self.assertGreaterEqual(q["failed"], 1)
        self.assertFalse(any(l.startswith("evaluate_error") for l in q["failure_labels"]))

    def test_polyglot_runners_turn_a_resource_limit_into_a_failed_check(self):
        import polyglot_tasks
        def boom(*a, **k):
            raise memguard.ResourceLimit(memguard.GuardResult(killed="memory", peak_rss_gb=5.0))
        with patch.object(memguard, "run", boom):
            for fn in (polyglot_tasks._go_run, polyglot_tasks._rust_run, polyglot_tasks._js_run, polyglot_tasks._cpp_run):
                tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, tmp, True)
                (tmp / "CMakeLists.txt").write_text("")
                (tmp / "package.json").write_text("{}")
                self.assertEqual(fn(tmp, []), {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["resource_limit"]}, fn.__name__)

    def test_polyglot_timeouts_still_use_the_timeout_label_and_the_300s_policy(self):
        import polyglot_tasks, subprocess
        seen = {}

        def slow(cmd, **kw):
            seen.update(kw)
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with patch.object(memguard, "run", slow):
            self.assertEqual(polyglot_tasks._go_run(tmp, [])["failure_labels"], ["timeout"])
        self.assertEqual(seen["timeout"], 300.0)                           # the campaign policy raises S2's 120 s

    def test_the_session_environment_gets_the_runtime_limits(self):
        import forge_e2e
        env = memguard.resource_env(forge_e2e.SESSION_MEM_CAP_GB, {"PATH": "/bin"})
        self.assertEqual((env["GOMEMLIMIT"], env["GOFLAGS"], env["CARGO_BUILD_JOBS"], env["NODE_OPTIONS"]),
                         ("4096MiB", "-p=2", "2", "--max-old-space-size=4096"))


if __name__ == "__main__":
    unittest.main()
