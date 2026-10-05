"""Forge terminal cap, non-empty failure reasons, capacity waits, circuit breaker, wave stagger, --parallel clamp.
Regression for the 2026-10-01 main-v1 run: --parallel 32 exceeded Forge's 10-terminal cap, every launch failed with
'Maximum sessions (10) reached', and 9 healthy waves were excluded after 3 identical attempts with an empty reason."""
from __future__ import annotations

import json
import shutil
import time
import tempfile
import unittest
from pathlib import Path

from paired_helpers import FakeBackend, make_design, paired, ps, write_inline_scenario

CAP_TEXT = "forge launch failed: Error: Maximum sessions (10) reached. Close a session first."


class CapBackend(FakeBackend):
    """Fails launches with Forge's cap error for the first ``fail_waves`` attempts of a wave, and models Forge terminals."""

    def __init__(self, *a, cap_failures=0, terminals=None, **k):
        super().__init__(*a, **k)
        self.cap_failures, self.terminals, self.reaped = cap_failures, terminals or {"total": 0, "ours": 0, "ours_exited": 0}, 0

    def start(self, root, name):
        if self.cap_failures > 0:
            self.cap_failures -= 1
            raise RuntimeError(CAP_TEXT)
        super().start(root, name)

    def wait(self, root, name, timeout):                 # no co-start barrier here: launches may fail before waiting
        time.sleep(self.hold)
        attempt = int(Path(root).name.rsplit("-a", 1)[1]) if "-a" in Path(root).name else 1
        self._write_result(Path(root), name, infra=name in self.always_fail)
        with self.lock:
            self.inflight -= 1
        return True

    def forge_max_sessions(self):
        return 10

    def forge_terminals(self, root=None):
        return dict(self.terminals)

    def forge_reap(self, root):
        self.reaped += 1
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scn = write_inline_scenario(self.tmp / "scn")
        write_inline_scenario(scn, id="tiny-two")
        write_inline_scenario(scn, id="tiny-three")
        self.design = make_design(self.tmp, scn)
        self.specs = {s.id: s for s in paired.load_specs(self.design)}

    def ctx(self, plan, **kw):
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        self.slept = []
        return paired.Ctx(out=out, design=self.design, cells_doc={}, suites_doc={}, specs=self.specs,
                          snapshots={sid: str(ps.materialize(s, self.tmp / "snaps")) for sid, s in self.specs.items()}, plan=plan,
                          campaign_root=self.tmp / "camp", candidate_source="x", candidate_sha=None, baseline_source="x", seed=1,
                          decide_fn=lambda p, w, c: "cheap", sleep=self.slept.append, **kw)

    def plan(self, scenarios, hosts=("opus",), arms=("anchor", "aa", "shipped", "sticky"), parallel=8):
        return paired.build_plan(self.design, list(self.specs.values()), reps=1, hosts=list(hosts), arms=list(arms), seed=3,
                                 budget_usd=None, parallel=parallel, scenarios=set(scenarios))

    def run_it(self, plan, be, **kw):
        ctx = self.ctx(plan)
        logs = []
        code = paired.run_campaign(ctx, be, budget_usd=10_000, parallel=kw.pop("parallel", 8), resume=False, policy_config={},
                                   log=logs.append, **kw)
        return ctx, code, logs


class ReasonAndCapacityTests(Base):
    def test_capacity_errors_do_not_count_as_failed_attempts_and_do_not_exclude(self):
        plan = self.plan(["tiny-demo"])
        be = CapBackend(self.tmp / "b", self.specs, cap_failures=9)           # first two attempts: every launch hits the cap
        ctx, code, logs = self.run_it(plan, be)
        self.assertEqual(code, 0)
        w = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual(w["status"], "done")
        self.assertEqual([a["status"] for a in w["attempts"]][-1], "done")
        self.assertTrue(all(a["status"] in ("capacity_wait", "done", "infra_failed") for a in w["attempts"]))
        self.assertFalse(any(a["status"] == "infra_failed" for a in w["attempts"]))
        self.assertTrue(w["capacity_waits"] >= 1)
        self.assertIn(paired.CAPACITY_WAIT_S, self.slept)
        self.assertGreaterEqual(be.reaped, 1)
        cap = next(a for a in w["attempts"] if a["status"] == "capacity_wait")
        self.assertIn("Maximum sessions", cap["reason"])

    def test_every_infra_failed_attempt_records_a_non_empty_reason_with_the_error_tail(self):
        plan = self.plan(["tiny-demo"])
        victim = "tiny-demo-r1-opus-anchor"
        diag = {victim: {"error_tail": "Traceback...\nOSError: [Errno 24] Too many open files", "model_calls": 0}}
        be = FakeBackend(self.tmp / "b", self.specs, always_fail={victim}, diag=diag)
        ctx, code, logs = self.run_it(plan, be, breaker=paired.CircuitBreaker(consecutive=99, max_excluded_per_hour=99))
        w = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual(w["status"], "excluded")
        for a in w["attempts"]:
            self.assertTrue(a["reason"].strip())
            self.assertIn(victim, a["reason"])
            self.assertIn("Too many open files", a["reason"])
        self.assertIn("Too many open files", w["excluded_reason"])

    def test_failure_reason_is_never_empty(self):
        self.assertTrue(paired.failure_reason([], {}, {}))
        self.assertIn("timeout", paired.failure_reason(["s1"], {"s1": "timeout"}, {"s1": {"error_tail": "", "worker_died": True}}))
        self.assertIn("worker vanished", paired.failure_reason(["s1"], {"s1": "timeout"}, {"s1": {"error_tail": "", "worker_died": True}}))


class BreakerTests(Base):
    def test_breaker_trips_on_two_consecutive_infra_failed_waves_and_excludes_nothing(self):
        plan = self.plan(["tiny-demo", "tiny-two", "tiny-three"])
        bad = {f"{sid}-r1-opus-anchor" for sid in ("tiny-demo", "tiny-two", "tiny-three")}
        be = FakeBackend(self.tmp / "b", self.specs, always_fail=bad)
        ctx, code, logs = self.run_it(plan, be, parallel=4)                    # one 4-session wave at a time
        self.assertEqual(code, paired.EXIT_PRECONDITION)
        waves = paired.State(ctx.out / "state.json").d["waves"]
        # run one wave at a time: the first wave exhausts its own 3 attempts (legitimately excluded), the SECOND wave's first
        # infra failure makes two in a row -> trip: it stays pending and the third wave is never launched
        self.assertLessEqual(sum(1 for w in waves.values() if w["status"] == "excluded"), 1)
        self.assertTrue(any("circuit breaker" in l for l in logs))
        self.assertTrue(any("STOPPED" in l for l in logs))
        started = [w for w in waves.values() if w["attempts"]]
        self.assertLessEqual(len(started), 2)                                    # the third wave was never launched
        self.assertTrue(any(w["status"] == "pending" for w in started))          # the tripped wave is left runnable

    def test_a_clean_wave_resets_the_streak(self):
        b = paired.CircuitBreaker()
        self.assertIsNone(b.note_infra("a"))
        b.note_clean("x")
        self.assertIsNone(b.note_infra("b"))
        self.assertIsNotNone(b.note_infra("c"))

    def test_more_than_n_exclusions_per_hour_trips_and_old_ones_expire(self):
        t = [1000.0]
        b = paired.CircuitBreaker(consecutive=99, max_excluded_per_hour=2, now=lambda: t[0])
        self.assertIsNone(b.note_excluded("a"))
        self.assertIsNone(b.note_excluded("b"))
        t[0] += 3601
        self.assertIsNone(b.note_excluded("c"))                                  # a and b expired
        self.assertIsNone(b.note_excluded("d"))
        self.assertIsNotNone(b.note_excluded("e"))


class ClampAndStaggerTests(Base):
    def test_parallel_is_clamped_to_forge_capacity_minus_reserve_and_foreign_terminals(self):
        be = CapBackend(self.tmp / "b", self.specs, terminals={"total": 3, "ours": 0, "ours_exited": 0})
        logs = []
        self.assertEqual(paired.forge_clamp(be, self.tmp, 32, logs.append), 10 - paired.FORGE_RESERVE - 3)
        self.assertTrue(any("clamped" in l for l in logs))
        self.assertEqual(paired.forge_clamp(be, self.tmp, 4, logs.append), 4)
        self.assertEqual(paired.forge_clamp(FakeBackend(self.tmp / "c", self.specs), self.tmp, 32), 32)    # no Forge: untouched

    def test_our_own_terminals_do_not_reduce_capacity(self):
        be = CapBackend(self.tmp / "b", self.specs, terminals={"total": 6, "ours": 6, "ours_exited": 6})
        self.assertEqual(paired.forge_clamp(be, self.tmp, 32), 10 - paired.FORGE_RESERVE)

    def test_a_wave_larger_than_the_clamped_capacity_is_refused_loudly(self):
        plan = self.plan(["tiny-demo"], arms=("anchor", "aa", "shipped", "sticky"))
        be = CapBackend(self.tmp / "b", self.specs, terminals={"total": 7, "ours": 0, "ours_exited": 0})    # allows 1
        with self.assertRaises(paired.PairedError):
            self.run_it(plan, be, parallel=32)

    def test_waves_are_staggered_by_their_launch_time(self):
        plan = self.plan(["tiny-demo", "tiny-two"])
        be = FakeBackend(self.tmp / "b", self.specs)
        ctx = self.ctx(plan)
        clock = [100.0]
        ctx.now = lambda: clock[0]
        ctx.sleep = lambda s: (self.slept.append(s), clock.__setitem__(0, clock[0] + s))
        paired.run_campaign(ctx, be, budget_usd=10_000, parallel=8, resume=False, policy_config={}, log=lambda *_: None)
        self.assertTrue(any(abs(s - (4 * 2.0 + 2.0)) < 1e-6 for s in self.slept), self.slept)       # 4 sessions x 2 s + 2 s margin

    def test_capacity_wait_before_admitting_a_wave_when_forge_is_full(self):
        plan = self.plan(["tiny-demo"])
        be = CapBackend(self.tmp / "b", self.specs, terminals={"total": 9, "ours": 9, "ours_exited": 9})
        calls = {"n": 0}
        orig = be.forge_terminals

        def terminals(root=None):
            calls["n"] += 1
            if calls["n"] > 3:
                return {"total": 0, "ours": 0, "ours_exited": 0}                 # the daemon freed its terminals
            return orig(root)
        be.forge_terminals = terminals
        ctx, code, logs = self.run_it(plan, be, parallel=8)
        self.assertEqual(code, 0)
        self.assertTrue(any("waiting for Forge terminal capacity" in l for l in logs))


class ForgeBackendTests(unittest.TestCase):
    def test_max_sessions_reads_the_forge_settings_with_a_default(self):
        from unittest.mock import patch
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".forge").mkdir()
        (tmp / ".forge" / "settings.json").write_text(json.dumps({"maxSessions": 24}))
        with patch.object(Path, "home", lambda: tmp):
            self.assertEqual(paired.ForgeBackend().forge_max_sessions(), 24)
        (tmp / ".forge" / "settings.json").write_text("{}")
        with patch.object(Path, "home", lambda: tmp):
            self.assertEqual(paired.ForgeBackend().forge_max_sessions(), 10)


if __name__ == "__main__":
    unittest.main()
