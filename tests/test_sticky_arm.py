"""A2 sticky: the model is decided ONCE in the harness (read-only turn-start decision), recorded, mapped to a pin
cell; the orchestrator is untouched. Also: cell -> side translation reuses evals/run.cell_to_argv, resume/rerun
reuse the stored decision, regrade determinism, render-check."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from paired_helpers import FakeBackend, REPO_ROOT, make_design, paired, ps, write_inline_scenario

import run as evals_run


class StickyDecisionTests(unittest.TestCase):
    def test_tier_maps_to_host_or_cheap_deterministically(self):
        calls = []

        def fake(prompt, workspace, config):
            calls.append((prompt, workspace))
            return "cheap" if "small" in prompt else "strong"
        self.assertEqual(paired.sticky_decision("a small fix", {}, workspace_dir="/w", decide_fn=fake), "cheap")
        self.assertEqual(paired.sticky_decision("redesign the whole thing", {}, workspace_dir="/w", decide_fn=fake), "host")
        self.assertEqual(paired.sticky_decision("a small fix", {}, workspace_dir="/w", decide_fn=fake), "cheap")
        self.assertEqual(calls[0], calls[2])

    def test_unknown_tier_is_an_error(self):
        with self.assertRaises(paired.PairedError):
            paired.sticky_decision("x", {}, workspace_dir="/w", decide_fn=lambda *_: "weird")

    def test_default_decider_reads_the_real_orchestrator_without_a_model(self):
        """decide_start_tier with start_policy=rules (no judge, no network): prompt length decides."""
        cfg = {"model_routing": {"start_model": "claude-sonnet-5", "start_policy": "rules", "complex_min_prompt_chars": 2000},
               "backend": "deterministic"}
        try:
            short = paired._decide_with_orchestrator("fix the typo", str(REPO_ROOT), cfg)
            long_ = paired._decide_with_orchestrator("x" * 2500, str(REPO_ROOT), cfg)
        except ModuleNotFoundError as exc:
            self.skipTest(f"orchestrator deps unavailable: {exc}")
        self.assertEqual((short, long_), ("cheap", "strong"))


class ResolveStickyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scn = write_inline_scenario(self.tmp / "scn")
        self.design = make_design(self.tmp, scn)
        specs = {s.id: s for s in paired.load_specs(self.design)}
        snaps = {sid: str(ps.materialize(s, self.tmp / "snaps")) for sid, s in specs.items()}
        out = self.tmp / "out"
        out.mkdir()
        self.verdict = ["cheap"]
        self.ctx = paired.Ctx(out=out, design=self.design, cells_doc={}, suites_doc={}, specs=specs, snapshots=snaps, plan={},
                              campaign_root=self.tmp / "c", candidate_source="x", candidate_sha=None, baseline_source="x", seed=1,
                              decide_fn=lambda p, w, c: self.verdict[0])

    def sess(self, host):
        return {"scenario": "tiny-demo", "rep": 1, "host": host, "arm": "sticky", "kind": "sticky", "cell": None}

    def test_decision_maps_to_the_right_pin_cell_per_host(self):
        for host, want_host, want_cheap in (("opus", "orch-pin-host-opus", "orch-pin-cheap-opus"), ("fable", "orch-pin-host", "orch-pin-cheap")):
            s = self.sess(host)
            self.verdict[0] = "cheap"
            paired.resolve_sticky(self.ctx, s, {})
            self.assertEqual((s["sticky_decision"], s["cell"], s["expected_main_model"]), ("cheap", want_cheap, "claude-sonnet-5"))
        (self.ctx.out / "decisions.jsonl").unlink()
        s = self.sess("opus")
        self.verdict[0] = "strong"
        paired.resolve_sticky(self.ctx, s, {})
        self.assertEqual((s["sticky_decision"], s["cell"], s["expected_main_model"]), ("host", "orch-pin-host-opus", "claude-opus-5-5"))

    def test_decision_is_made_once_and_reused_on_rerun_and_resume(self):
        a = self.sess("opus")
        paired.resolve_sticky(self.ctx, a, {})
        self.verdict[0] = "strong"                      # the judge would answer differently now
        b = self.sess("opus")
        paired.resolve_sticky(self.ctx, b, {})
        self.assertEqual((a["sticky_decision"], a["cell"]), (b["sticky_decision"], b["cell"]))
        lines = (self.ctx.out / "decisions.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["policy_cell"], "orch-default")
        self.assertEqual(len(rec["turn1_prompt_sha256"]), 64)

    def test_decision_is_recorded_in_the_session_that_runs(self):
        plan = paired.build_plan(self.design, list(self.ctx.specs.values()), reps=1, hosts=["opus"], arms=["anchor", "sticky"],
                                 seed=1, budget_usd=None, parallel=6)
        self.ctx.plan = plan
        be = FakeBackend(self.tmp / "b", [])
        code = paired.run_campaign(self.ctx, be, budget_usd=1000, parallel=6, resume=False, policy_config={}, log=lambda *_: None)
        self.assertEqual(code, 0)
        prepared = {s["arm"]: s for _, ss in be.prepared for s in ss}
        self.assertEqual(prepared["sticky"]["cell"], "orch-pin-cheap-opus")
        self.assertEqual(prepared["anchor"]["cell"], "plain-opus")


class CellToSideTests(unittest.TestCase):
    def setUp(self):
        self.cells = evals_run.load_cells(REPO_ROOT / "evals" / "cells.yaml")
        self.suites = evals_run.load_suites()

    def side(self, cell):
        return paired.cell_to_side(cell, self.cells, self.suites, baseline_source="/b", candidate_source="/c", candidate_sha="deadbeef")

    def test_plain_cells_are_mode_off_on_their_model(self):
        side, model, _ = self.side("plain-opus")
        self.assertEqual((side["mode"], model), ("off", "claude-opus-5-5"))
        self.assertEqual(self.side("plain")[1], "claude-fable-5-1")
        self.assertEqual(self.side("plain-sonnet")[1], "claude-sonnet-5")

    def test_shipped_cell_is_composed_with_the_jev_judge(self):
        side, model, _ = self.side("orch-default-opus")
        self.assertEqual((side["mode"], side["composition"], model), ("active", "composed", "claude-opus-5-5"))
        self.assertEqual(side["decision_overrides"].get("backend"), "jev")
        self.assertTrue(side["decision_overrides"].get("allow_external_state"))

    def test_pin_host_removes_model_routing_and_pin_cheap_never_judges_or_escalates(self):
        host, _, _ = self.side("orch-pin-host-opus")
        self.assertIn("model_routing", host["decision_overrides"])
        self.assertIsNone(host["decision_overrides"]["model_routing"])
        cheap, _, _ = self.side("orch-pin-cheap-opus")
        mr = cheap["decision_overrides"]["model_routing"]
        self.assertEqual((mr["start_policy"], mr["start_model"], mr["max_requests_before_escalation"]), ("cheap", "claude-sonnet-5", None))
        self.assertFalse(mr["escalate_on_test_failure"])
        self.assertTrue(mr["escalate_on_provider_error"])
        self.assertNotIn("backend", cheap["decision_overrides"])        # no judge call inside the session

    def test_every_design_cell_exists(self):
        d = paired.load_design()
        for arm, a in d["arms"].items():
            for host, c in a["cells"].items():
                for cell in (c.values() if isinstance(c, dict) else [c]):
                    self.assertIn(cell, self.cells["cells"], f"{arm}/{host}")


class RegradeAndRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_render_check_flags_nonce_not_first_and_prompt_drift(self):
        out = self.tmp / "out"
        out.mkdir()
        sessions = [{"key": f"k{i}", "kind": "plain", "nonce": f"n{i}"} for i in range(3)]
        (out / "state.json").write_text(json.dumps({"waves": {"w": {"accepted_attempt": 1, "attempts": [
            {"attempt": 1, "root": str(self.tmp / "r"), "sessions": sessions}]}}}))
        be = FakeBackend(self.tmp, [])
        good = lambda p, w: f"run-nonce: {p.parent.name.replace('k', 'n')}\n\nSAME PROMPT"
        rep = paired.render_check(out, be, renderer=good)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["groups"]["plain"]["distinct_prompt_hashes"], 1)
        drift = lambda p, w: f"run-nonce: {p.parent.name.replace('k', 'n')}\n\nPROMPT {p.parent.name}"
        self.assertFalse(paired.render_check(out, be, renderer=drift)["ok"])
        buried = lambda p, w: f"intro\nrun-nonce: {p.parent.name.replace('k', 'n')}\n"
        self.assertFalse(paired.render_check(out, be, renderer=buried)["ok"])

    def test_regrade_from_turn_snapshots_is_deterministic_and_matches_recorded(self):
        import tarfile
        scn = write_inline_scenario(self.tmp / "scn")
        spec = ps.load_dir(scn)[0]
        snap = ps.materialize(spec, self.tmp / "snaps")
        root = self.tmp / "camp" / "w000-a1"
        key = "tiny-demo-r1-opus-anchor"
        ws = self.tmp / "ws" / "ws"
        shutil.copytree(snap / "workspace", ws)
        (ws / "solution.py").write_text("def f():\n    return 1\n")
        (root / key).mkdir(parents=True)
        (root / key / "turn-snapshots").mkdir()
        with tarfile.open(root / key / "turn-snapshots" / "t1.tar.gz", "w:gz") as tf:
            tf.add(ws, arcname="ws")
        recorded = ps.grade_turn(spec, 1, ws, "", snap)
        (root / key / "result.json").write_text(json.dumps({"turns": [{"index": 1, "final_message": "", "quality": recorded}]}))
        out = self.tmp / "out"
        out.mkdir()
        (out / "state.json").write_text(json.dumps({"waves": {"w": {"accepted_attempt": 1, "attempts": [
            {"attempt": 1, "root": str(root), "sessions": [{"key": key, "scenario": "tiny-demo"}]}]}}}))
        summary = paired.regrade(out, FakeBackend(self.tmp, []), {"tiny-demo": spec}, {"tiny-demo": snap}, passes=3)
        self.assertEqual((summary["graded_turns"], summary["deterministic"], summary["differs_from_recorded"]), (1, True, []))


if __name__ == "__main__":
    unittest.main()
