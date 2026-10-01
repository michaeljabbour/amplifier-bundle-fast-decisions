"""plan / run: waves co-start, bounded concurrency, seeded order, budget refusal (exit 3) and hard stop,
infra failure reruns the WHOLE wave with fresh nonces, --resume adopts finished sessions."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from paired_helpers import FakeBackend, make_design, paired, ps, write_inline_scenario


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.scn = write_inline_scenario(self.tmp / "scn")
        write_inline_scenario(self.scn, id="tiny-two")
        self.design = make_design(self.tmp, self.scn)
        self.specs = paired.load_specs(self.design)
        self.by_id = {s.id: s for s in self.specs}

    def plan(self, **kw):
        args = dict(reps=1, hosts=["opus", "fable"], arms=list(self.design["arms"]), seed=7, budget_usd=None, parallel=6)
        args.update(kw)
        return paired.build_plan(self.design, self.specs, **args)

    def ctx(self, plan, **kw):
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        snaps = {s.id: str(ps.materialize(s, self.tmp / "snaps")) for s in self.specs}
        return paired.Ctx(out=out, design=self.design, cells_doc={}, suites_doc={}, specs=self.by_id, snapshots=snaps, plan=plan,
                          campaign_root=self.tmp / "camp", candidate_source="x", candidate_sha=None, baseline_source="x", seed=7,
                          decide_fn=kw.pop("decide_fn", lambda p, w, c: "cheap"), sleep=lambda s: None, **kw)


class PlanTests(Base):
    def test_waves_group_arms_of_a_scenario_rep_host(self):
        plan = self.plan()
        self.assertEqual(plan["n_waves"], 2 * 1 * 2)
        for wid, sessions in plan["waves"].items():
            hosts = {s["host"] for s in sessions}
            self.assertLessEqual(len(hosts - {"any"}), 1, wid)
            self.assertEqual(len({s["scenario"] for s in sessions}), 1)
        # the host-independent control runs once per scenario-rep, in the first host's wave
        sonnet = [s for w in plan["waves"].values() for s in w if s["arm"] == "sonnet"]
        self.assertEqual(len(sonnet), 2)
        self.assertTrue(all(s["wave_id"].endswith("-opus") for s in sonnet))

    def test_wave_sizes_respect_parallel_or_plan_refuses(self):
        plan = self.plan()
        self.assertLessEqual(max(len(v) for v in plan["waves"].values()), 6)
        self.assertFalse(plan["control_waves_split"])
        with self.assertRaises(paired.PairedError) as cm:
            self.plan(parallel=3)
        self.assertEqual(cm.exception.code, paired.EXIT_PRECONDITION)

    def test_default_parallel_is_4_and_the_control_gets_its_own_wave_when_a_wave_would_not_fit(self):
        self.assertEqual(paired.DEFAULT_PARALLEL, 4)
        self.assertEqual(self.design["default_parallel"], 4)
        plan = self.plan(parallel=4)
        self.assertTrue(plan["control_waves_split"])
        self.assertLessEqual(max(len(v) for v in plan["waves"].values()), 4)
        control = [w for w, v in plan["waves"].items() if any(s["arm"] == "sonnet" for s in v)]
        self.assertTrue(all(w.endswith("-any") and len(plan["waves"][w]) == 1 for w in control))
        self.assertEqual(len(control), 2)                            # one per scenario-rep (2 scenarios x 1 rep)

    def test_seeded_order_is_deterministic_and_seed_dependent(self):
        a, b = self.plan(seed=1)["wave_order"], self.plan(seed=1)["wave_order"]
        self.assertEqual(a, b)
        orders = {tuple(self.plan(seed=s)["wave_order"]) for s in range(12)}
        self.assertGreater(len(orders), 1)

    def test_budget_refusal_exits_3(self):
        with self.assertRaises(paired.BudgetExceeded) as cm:
            self.plan(budget_usd=1.0)
        self.assertEqual(cm.exception.code, paired.EXIT_BUDGET)
        ok = self.plan(budget_usd=10_000.0)
        self.assertLess(ok["est_with_reserve_usd"], 10_000)

    def test_cli_exit_codes(self):
        cfg = self.tmp / "design.yaml"
        import yaml
        d = {k: v for k, v in self.design.items() if k != "_path"}
        cfg.write_text(yaml.safe_dump(d))
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            self.assertEqual(paired.main(["plan", "--design", str(cfg), "--dry-run", "--budget-usd", "1"]), 3)
            self.assertEqual(paired.main(["plan", "--design", str(cfg), "--dry-run", "--budget-usd", "5000"]), 0)
            self.assertEqual(paired.main(["plan", "--design", str(cfg), "--dry-run", "--parallel", "2"]), 4)
            self.assertEqual(paired.main(["plan", "--design", str(cfg)]), 4)         # --out required without --dry-run

    def test_dry_run_writes_nothing(self):
        cfg = self.tmp / "d.yaml"
        import yaml
        cfg.write_text(yaml.safe_dump({k: v for k, v in self.design.items() if k != "_path"}))
        before = set(self.tmp.rglob("*"))
        with redirect_stdout(io.StringIO()):
            paired.main(["plan", "--design", str(cfg), "--dry-run"])
        self.assertEqual(before | {cfg}, set(self.tmp.rglob("*")) | {cfg})

    def test_cost_estimate_scales_with_turns_and_gaps(self):
        spec = self.by_id["tiny-demo"]
        base = paired.estimate_session_usd(self.design, spec, "anchor", "opus")
        self.assertGreater(base, 0)
        self.assertLess(paired.estimate_session_usd(self.design, spec, "anchor", "opus"),
                        paired.estimate_session_usd(self.design, spec, "anchor", "fable"))

    def test_nonces_unique_per_session_and_attempt(self):
        plan = self.plan()
        nonces = [s["nonce"] for w in plan["waves"].values() for s in w]
        self.assertEqual(len(nonces), len(set(nonces)))
        self.assertNotEqual(paired.make_nonce("p", "k", 1), paired.make_nonce("p", "k", 2))
        self.assertEqual(paired.make_nonce("p", "k", 1), paired.make_nonce("p", "k", 1))

    def test_nonce_none_mode(self):
        self.design["nonce_mode"] = "none"
        self.assertTrue(all(s["nonce"] is None for w in self.plan()["waves"].values() for s in w))

    def test_prompt_hash_is_one_per_scenario(self):
        plan = self.plan()
        self.assertEqual(set(plan["scenarios"]), {"tiny-demo", "tiny-two"})
        self.assertEqual(plan["scenarios"]["tiny-demo"]["prompt_sha256"], ps.prompt_hash(self.by_id["tiny-demo"]))


class RunTests(Base):
    def run_it(self, plan, backend, **kw):
        ctx = self.ctx(plan)
        pc = kw.pop("parallel", 6)
        code = paired.run_campaign(ctx, backend, budget_usd=kw.pop("budget", 10_000), parallel=pc, resume=kw.pop("resume", False),
                                   policy_config={}, log=lambda *_: None, **kw)
        return ctx, code

    def test_waves_co_start_and_concurrency_is_bounded(self):
        plan = self.plan(scenarios={"tiny-demo"})
        be = FakeBackend(self.tmp / "b", self.specs)
        ctx, code = self.run_it(plan, be, parallel=6)
        self.assertEqual(code, 0)
        self.assertLessEqual(be.max_inflight, 6)
        self.assertGreaterEqual(be.max_inflight, 4)           # a whole wave was in flight at once
        state = paired.State(ctx.out / "state.json")
        self.assertTrue(all(w["status"] == "done" for w in state.d["waves"].values()))

    def test_parallel_bound_with_room_for_one_wave_only(self):
        plan = self.plan()
        be = FakeBackend(self.tmp / "b", self.specs, hold=0.02)
        _, code = self.run_it(plan, be, parallel=5)
        self.assertEqual(code, 0)
        self.assertLessEqual(be.max_inflight, 5)

    def test_infra_failure_reruns_the_whole_wave_with_fresh_nonces(self):
        plan = self.plan(scenarios={"tiny-demo"}, hosts=["opus"])
        victim = "tiny-demo-r1-opus-shipped"
        be = FakeBackend(self.tmp / "b", self.specs, fail_first={victim})
        ctx, code = self.run_it(plan, be)
        self.assertEqual(code, 0)
        state = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual([a["status"] for a in state["attempts"]], ["infra_failed", "done"])
        self.assertEqual(state["accepted_attempt"], 2)
        a1, a2 = (a["sessions"] for a in state["attempts"])
        self.assertEqual(len(a1), len(a2))                     # every arm reran, not just the victim
        for x, y in zip(a1, a2):
            self.assertNotEqual(x["nonce"], y["nonce"])
        starts = [n for (_, n, _) in be.started]
        self.assertEqual(len(starts), 2 * len(a1))

    def test_wave_excluded_after_max_attempts(self):
        plan = self.plan(scenarios={"tiny-demo"}, hosts=["opus"])
        be = FakeBackend(self.tmp / "b", self.specs, always_fail={"tiny-demo-r1-opus-anchor"})
        ctx, code = self.run_it(plan, be)
        state = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual(state["status"], "excluded")
        self.assertEqual(len(state["attempts"]), 3)
        self.assertEqual(list(paired.accepted_sessions(ctx.out)), [])

    def test_resume_adopts_finished_sessions(self):
        plan = self.plan(scenarios={"tiny-demo"}, hosts=["opus"])
        be = FakeBackend(self.tmp / "b", self.specs)
        ctx = self.ctx(plan)
        state = paired.State(ctx.out / "state.json")
        wid = "tiny-demo-r1-opus"
        sessions = [dict(s, attempt=1) for s in plan["waves"][wid]]
        for s in sessions:
            if s["kind"] == "sticky":
                paired.resolve_sticky(ctx, s, {})
        root = ctx.campaign_root / "w000-a1"
        be.prepare_wave(ctx, root, sessions)
        for s in sessions:
            be._write_result(root, s["key"], infra=False)      # a previous runner finished everything
        w = state.wave(wid)
        w.update(status="running", attempts=[{"attempt": 1, "root": str(root), "status": "running", "sessions": sessions}])
        state.save()
        ctx2, code = self.run_it(plan, be, resume=True)
        self.assertEqual(code, 0)
        self.assertEqual(be.started, [])                       # nothing was launched twice
        self.assertEqual(paired.State(ctx.out / "state.json").wave(wid)["status"], "done")

    def test_budget_hard_stop_launches_no_further_wave(self):
        plan = self.plan(scenarios={"tiny-demo"})
        first = sum(s["est_usd"] for s in plan["waves"][plan["wave_order"][0]])
        be = FakeBackend(self.tmp / "b", self.specs)
        with patch.object(paired, "wave_cost", lambda ctx, backend, root, sessions: sum(s["est_usd"] for s in sessions)):
            ctx, code = self.run_it(plan, be, budget=first + 0.01, parallel=6)
        self.assertEqual(code, paired.EXIT_BUDGET)
        done = [w for w in paired.State(ctx.out / "state.json").d["waves"].values() if w["status"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertLess(len(be.prepared), plan["n_waves"])

    def test_settings_change_is_refused(self):
        plan = self.plan(scenarios={"tiny-demo"}, hosts=["opus"])
        ctx = self.ctx(plan)
        paired._write_json(ctx.out / "state.json", {"settings_sha256": "stale", "waves": {}})
        with patch.object(paired, "settings_sha", return_value="fresh"):
            with self.assertRaises(paired.PairedError) as cm:
                paired.run_campaign(ctx, FakeBackend(self.tmp / "b", self.specs), budget_usd=100, parallel=6, resume=False, log=lambda *_: None)
        self.assertEqual(cm.exception.code, paired.EXIT_PRECONDITION)

    def test_prompt_hash_mismatch_refuses_launch(self):
        plan = self.plan(scenarios={"tiny-demo"}, hosts=["opus"])
        plan["scenarios"]["tiny-demo"]["prompt_sha256"] = "0" * 64
        be = FakeBackend(self.tmp / "b", self.specs)
        with self.assertRaises(paired.PairedError):
            self.run_it(plan, be)
        self.assertEqual(be.started, [])

    def test_path_length_guard(self):
        plan = self.plan()
        flat = [s for w in plan["waves"].values() for s in w]
        self.assertLess(paired.check_path_lengths(Path("/Users/me/dev/afast-paired/pilot"), flat), 240)
        with self.assertRaises(paired.PairedError):
            paired.check_path_lengths(Path("/x" * 120), flat)

class PlanWriteTests(Base):
    def test_non_dry_plan_freezes_schedule_snapshots_and_refuses_replan(self):
        import yaml
        cfg = self.tmp / "design.yaml"
        cfg.write_text(yaml.safe_dump({k: v for k, v in self.design.items() if k != "_path"}))
        out = self.tmp / "out"
        import battery
        fake = lambda src, d, candidate_sha=None: (str(self.tmp / "frozen"), {"git_sha": "abc123", "tree_sha256": "t"})
        with patch.object(battery, "_freeze_candidate_source", fake), redirect_stdout(io.StringIO()):
            self.assertEqual(paired.main(["plan", "--design", str(cfg), "--out", str(out), "--budget-usd", "5000"]), 0)
            sched = json.loads((out / "schedule.json").read_text())
            self.assertEqual(sched["candidate"]["info"]["git_sha"], "abc123")
            self.assertEqual(set(sched["snapshots"]), {"tiny-demo", "tiny-two"})
            self.assertTrue(all((Path(p) / "snapshot.json").exists() for p in sched["snapshots"].values()))
            self.assertLess(sched["max_encoded_workspace_len"], 240)
            self.assertTrue((out / "plan.txt").exists())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(paired.main(["plan", "--design", str(cfg), "--out", str(out)]), 4)   # plans are frozen


class LedgerTests(unittest.TestCase):
    def test_reserve_settle_release(self):
        with tempfile.TemporaryDirectory() as t:
            led = paired.Ledger(Path(t) / "l.json", 10.0)
            led.reserve("a", 6.0)
            with self.assertRaises(paired.BudgetExceeded):
                led.reserve("b", 5.0)
            led.settle("a", 3.0)
            led.reserve("b", 5.0)
            self.assertAlmostEqual(led.committed(), 8.0)
            led.release("b")
            self.assertAlmostEqual(paired.Ledger(Path(t) / "l.json", 10.0).committed(), 3.0)


if __name__ == "__main__":
    unittest.main()
