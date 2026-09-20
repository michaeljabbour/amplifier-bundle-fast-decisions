"""Tests for evals/run.py -- the eval-suite driver over battery.py/campaign.py/
battery_report.py. No test invokes a real harness, provider, forge, or the
network: `run.invoke_tool` (the one subprocess seam) is monkeypatched with a
fake that records calls and returns canned JSON, exactly as the battery.py
tests substitute fakes for forge and the amplifier launcher.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run


def _load_test_cells():
    return run.load_cells(REPO_ROOT / "evals" / "cells.yaml")


def _load_test_suites():
    return run.load_suites(REPO_ROOT / "evals" / "suites.yaml")


COMMON = {
    "out_root": "/out", "base_seed": 20260919, "baseline_source": "/baseline",
    "candidate_source": "/candidate", "candidate_sha": "deadbeef", "polyglot_root": "/poly",
}


class CellToArgvTests(unittest.TestCase):
    def setUp(self):
        self.cells = _load_test_cells()
        self.suites = _load_test_suites()

    def test_every_cell_produces_argv_without_error(self):
        for cid in self.cells["cells"]:
            argv = run.cell_to_argv(cid, self.cells, self.suites, "s1", "dev", 1, **COMMON)
            self.assertIn("--experiment", argv)
            self.assertIn(f"{cid}-s1-dev-r1", argv)

    def test_judge_off_cell_emits_fd_override_backend_unavailable(self):
        argv = run.cell_to_argv("effort-only", self.cells, self.suites, "s1", "dev", 1, **COMMON)
        self.assertIn("--fd-override", argv)
        idx = argv.index("--fd-override")
        self.assertIn("backend=unavailable", argv[idx:])
        self.assertNotIn("--fd-backend", argv)

    def test_jev_cell_emits_backend_and_allow_external_state_together(self):
        argv = run.cell_to_argv("judge-jev+effort", self.cells, self.suites, "s1", "dev", 1, **COMMON)
        self.assertIn("--fd-backend", argv)
        self.assertEqual(argv[argv.index("--fd-backend") + 1], "jev")
        self.assertIn("--allow-external-state", argv)

    def test_compact_json_effort_routing_is_single_argv_element(self):
        argv = run.cell_to_argv("judge-local+effort", self.cells, self.suites, "s1", "dev", 1, **COMMON)
        overrides = [argv[i + 1] for i, a in enumerate(argv) if a == "--fd-override"]
        effort = [o for o in overrides if o.startswith("effort_routing=")]
        self.assertEqual(len(effort), 1)
        payload = json.loads(effort[0].split("=", 1)[1])
        self.assertEqual(payload, {"orient": "medium", "explore": "low", "implement": "high"})

    def test_model_routing_profile_is_single_argv_element(self):
        argv = run.cell_to_argv("judge-local+effort+route", self.cells, self.suites, "s1", "dev", 1, **COMMON)
        overrides = [argv[i + 1] for i, a in enumerate(argv) if a == "--fd-override"]
        routing = [o for o in overrides if o.startswith("model_routing=")]
        self.assertEqual(len(routing), 1)
        payload = json.loads(routing[0].split("=", 1)[1])
        self.assertEqual(payload["start_model"], "claude-sonnet-5")

    def test_every_cell_gets_explicit_bypass_permissions(self):
        for cid in self.cells["cells"]:
            argv = run.cell_to_argv(cid, self.cells, self.suites, "s1", "dev", 1, **COMMON)
            idx = argv.index("--claude-permission-mode")
            self.assertEqual(argv[idx + 1], "bypassPermissions")

    def test_s1_uses_tasks_flag(self):
        argv = run.cell_to_argv("plain", self.cells, self.suites, "s1", "dev", 1, **COMMON)
        self.assertIn("--tasks", argv)
        self.assertEqual(argv[argv.index("--tasks") + 1], "dev")
        self.assertNotIn("--task-source", argv)

    def test_s2_uses_task_source_polyglot_and_split_not_tasks(self):
        argv = run.cell_to_argv("plain", self.cells, self.suites, "s2", "holdout", 1, **COMMON)
        self.assertIn("--task-source", argv)
        self.assertEqual(argv[argv.index("--task-source") + 1], "polyglot")
        self.assertIn("--split", argv)
        self.assertEqual(argv[argv.index("--split") + 1], "holdout")
        self.assertNotIn("--tasks", argv)


class SeriesLabelTests(unittest.TestCase):
    def setUp(self):
        self.cells = _load_test_cells()

    def test_label_names_all_four_axes(self):
        cell = self.cells["cells"]["judge-local+effort"]
        label = run.series_label("judge-local+effort", 1, "amplifier-fd", cell,
                                  self.cells["defaults"], self.cells["effort_profiles"],
                                  self.cells["model_routing_profiles"])
        self.assertIn("judge=", label)
        self.assertIn("effort ", label)
        self.assertIn("model routing:", label)
        self.assertIn("model=", label)

    def test_plain_cell_label_shows_everything_off(self):
        cell = self.cells["cells"]["plain"]
        label = run.series_label("plain", 2, "amplifier-plain", cell, self.cells["defaults"],
                                  self.cells["effort_profiles"], self.cells["model_routing_profiles"])
        self.assertIn("judge=off", label)
        self.assertIn("effort off", label)
        self.assertIn("model routing: off", label)

    def test_label_missing_an_axis_is_rejected(self):
        with self.assertRaises(run.EvalsError) as ctx:
            run.validate_series_label("plain r1 amplifier-plain [judge=off; model=x]")
        self.assertEqual(ctx.exception.code, 4)

    def test_cross_check_agrees_on_judge_effort_routing(self):
        declared = ("judge-local+effort r1 amplifier-fd [judge=ollama qwen3:0.6b; "
                    "effort orient->medium, explore->low, implement->high; model routing: off; "
                    "model=claude-fable-5-1]")
        recorded = ("amplifier-fd [judge=ollama qwen3:0.6b; "
                    "effort orient->medium, explore->low, implement->high; model routing: off]")
        self.assertTrue(run.cross_check_series_label(declared, recorded))

    def test_cross_check_disagreement_raises_exit_4(self):
        declared = "x r1 amplifier-fd [judge=ollama qwen3:0.6b; effort off; model routing: off; model=m]"
        recorded = "amplifier-fd [judge=jev jev-remote; effort off; model routing: off]"
        with self.assertRaises(run.EvalsError) as ctx:
            run.cross_check_series_label(declared, recorded)
        self.assertEqual(ctx.exception.code, 4)


class VerifyPromptsTests(unittest.TestCase):
    def test_passes_on_matched_hashes(self):
        result = run.verify_prompts(
            tasks=["t1"], resolve_task=lambda n: SimpleNamespace(prompt="hello"),
            get_task_prompt=lambda t: t.prompt,
            amplifier_prompts={"t1": {"amplifier-plain": "hello", "amplifier-fd": "hello"}},
            external_harnesses={"t1": ["claude"]},
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["tasks"]["t1"]["ok"])
        self.assertEqual(result["tasks"]["t1"]["harnesses"]["claude"]["source"], "static-fallback")

    def test_fails_on_mismatched_amplifier_prompt(self):
        result = run.verify_prompts(
            tasks=["t1"], resolve_task=lambda n: SimpleNamespace(prompt="hello"),
            get_task_prompt=lambda t: t.prompt,
            amplifier_prompts={"t1": {"amplifier-fd": "goodbye"}},
            external_harnesses={},
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["tasks"]["t1"]["harnesses"]["amplifier-fd"]["matched"])

    def test_fails_on_unresolvable_task(self):
        result = run.verify_prompts(
            tasks=["missing"], resolve_task=lambda n: None, get_task_prompt=lambda t: None,
            amplifier_prompts={}, external_harnesses={},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["tasks"]["missing"]["reason"], "unresolvable task")

    def test_fails_on_empty_prompt(self):
        result = run.verify_prompts(
            tasks=["t1"], resolve_task=lambda n: SimpleNamespace(prompt=""), get_task_prompt=lambda t: None,
            amplifier_prompts={}, external_harnesses={},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["tasks"]["t1"]["reason"], "empty/unresolvable prompt")


class GateEvalTests(unittest.TestCase):
    def test_jev_configured_but_never_scored_fails(self):
        gate = run.gate_eval({"scored_backend": "jev", "min_scored": 1},
                              {"mechanism_engaged": False, "mechanism_reason": "external backend 'jev' refused",
                               "scored_by_backend": {}, "fallback_count": 9, "routed_by_route": {},
                               "effort_routed_by_phase_effort": {}, "model_routed_requested_models": {},
                               "model_routed_escalations_by_reason": {}})
        self.assertFalse(gate["passed"])

    def test_judge_off_with_scores_fails(self):
        gate = run.gate_eval({"max_scored": 0},
                              {"mechanism_engaged": True, "mechanism_reason": None,
                               "scored_by_backend": {"unavailable": 1}, "fallback_count": 0,
                               "routed_by_route": {}, "effort_routed_by_phase_effort": {},
                               "model_routed_requested_models": {}, "model_routed_escalations_by_reason": {}})
        self.assertFalse(gate["passed"])

    def test_effort_phase_missing_fails(self):
        gate = run.gate_eval({"require_effort_phases": ["implement:high"]},
                              {"mechanism_engaged": True, "mechanism_reason": None,
                               "scored_by_backend": {}, "fallback_count": 0, "routed_by_route": {},
                               "effort_routed_by_phase_effort": {}, "model_routed_requested_models": {},
                               "model_routed_escalations_by_reason": {}})
        self.assertFalse(gate["passed"])

    def test_zero_escalations_flags_but_does_not_fail(self):
        gate = run.gate_eval({"model_routed_model": "claude-sonnet-5", "min_model_routed": 1,
                               "flag_if_zero_escalations": "confounded_with_plain_sonnet"},
                              {"mechanism_engaged": True, "mechanism_reason": None,
                               "scored_by_backend": {}, "fallback_count": 0, "routed_by_route": {},
                               "effort_routed_by_phase_effort": {},
                               "model_routed_requested_models": {"claude-sonnet-5": 3},
                               "model_routed_escalations_by_reason": {}})
        self.assertTrue(gate["passed"])
        self.assertIn("confounded_with_plain_sonnet", gate["flags"])

    def test_mechanism_engaged_false_fails_regardless_of_other_keys(self):
        gate = run.gate_eval({"scored_backend": "ollama", "min_scored": 1},
                              {"mechanism_engaged": False, "mechanism_reason": "boom",
                               "scored_by_backend": {"ollama": 5}, "fallback_count": 0,
                               "routed_by_route": {}, "effort_routed_by_phase_effort": {},
                               "model_routed_requested_models": {}, "model_routed_escalations_by_reason": {}})
        self.assertFalse(gate["passed"])

    def test_no_fd_receipts_true_when_mechanism_is_none(self):
        gate = run.gate_eval({"no_fd_receipts": True}, None)
        self.assertTrue(gate["passed"])

    def test_no_fd_receipts_fails_when_receipts_leaked(self):
        gate = run.gate_eval({"no_fd_receipts": True},
                              {"mechanism_engaged": True, "mechanism_reason": None,
                               "scored_by_backend": {"ollama": 1}, "fallback_count": 0,
                               "routed_by_route": {}, "effort_routed_by_phase_effort": {},
                               "model_routed_requested_models": {}, "model_routed_escalations_by_reason": {}})
        self.assertFalse(gate["passed"])


class ResumeDetectionTests(unittest.TestCase):
    def test_no_proposal_means_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            action, reason = run.resume_detection(Path(tmp) / "exp1", ["--seed", "1"])
            self.assertEqual(action, "prepare")
            self.assertIsNone(reason)

    def test_matching_recorded_argv_reuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "exp1"
            d.mkdir()
            (d / "proposal.json").write_text("{}")
            (d / "run-argv.json").write_text(json.dumps(["--seed", "1"]))
            action, reason = run.resume_detection(d, ["--seed", "1"])
            self.assertEqual(action, "reuse")

    def test_changed_cell_definition_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "exp1"
            d.mkdir()
            (d / "proposal.json").write_text("{}")
            (d / "run-argv.json").write_text(json.dumps(["--seed", "1"]))
            action, error_reason = run.resume_detection(d, ["--seed", "2"])
            self.assertEqual(action, "error")
            self.assertIn("changed", error_reason)


class ExitCodeTests(unittest.TestCase):
    def _run(self, argv, calls):
        def fake_invoke(tool, targv):
            calls.append((tool, targv))
            raise AssertionError("no invoke_tool call should happen before a pre-launch failure")

        orig = run.invoke_tool
        run.invoke_tool = fake_invoke
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / "out")
                return run.main(argv + ["--out", out])
        finally:
            run.invoke_tool = orig

    def test_unknown_cell_exits_2_with_zero_launches(self):
        calls = []
        rc = self._run(["--suite", "s1", "--split", "dev", "--cells", "not-a-cell",
                         "--candidate-sha", "deadbeef", "--baseline-source", "/b"], calls)
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])

    def test_routing_cell_without_control_exits_2_with_zero_launches(self):
        calls = []
        rc = self._run(["--suite", "s1", "--split", "dev", "--cells", "judge-local+effort+route",
                         "--candidate-sha", "deadbeef", "--baseline-source", "/b"], calls)
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])

    def test_jev_cell_without_consent_flag_exits_2_with_zero_launches(self):
        calls = []
        rc = self._run(["--suite", "s1", "--split", "dev", "--cells", "judge-jev+effort",
                         "--candidate-sha", "deadbeef", "--baseline-source", "/b"], calls)
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])

    def test_holdout_without_preregistration_exits_2_with_zero_launches(self):
        calls = []
        rc = self._run(["--suite", "s1", "--split", "holdout", "--cells", "plain",
                         "--candidate-sha", "deadbeef", "--baseline-source", "/b"], calls)
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])

    def test_missing_candidate_sha_exits_2_with_zero_launches(self):
        calls = []
        rc = self._run(["--suite", "s1", "--split", "dev", "--cells", "plain",
                         "--baseline-source", "/b"], calls)
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])


class CostEstimateTests(unittest.TestCase):
    def test_deterministic_estimate_from_runs_times_per_launch(self):
        cells = _load_test_cells()
        est = run.cost_estimate(3, 2, cells)
        self.assertEqual(est["experiments"], 6)
        self.assertEqual(est["estimated_usd"], 6 * cells["budget"]["per_launch_usd"])

    def test_dry_run_touches_no_filesystem_state_outside_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            rc = run.main(["--suite", "s1", "--split", "dev", "--cells", "plain", "--reps", "1",
                           "--out", out, "--baseline-source", "/b", "--candidate-sha", "deadbeef",
                           "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse(Path(out).exists())


class ManifestShapeTests(unittest.TestCase):
    def test_required_keys_present(self):
        manifest = run.build_manifest(
            argv=["x"], suite_id="s1", split="dev", reps=1, suite_doc={},
            candidate={"source": "s"}, baseline={"source": "b"}, cells_report=[],
            budget_report={}, tool_shas={"battery.py": "abc"},
        )
        run.validate_manifest_shape(manifest)  # must not raise

    def test_missing_key_raises_exit_4(self):
        manifest = {"schema": run.SCHEMA_MANIFEST}
        with self.assertRaises(run.EvalsError) as ctx:
            run.validate_manifest_shape(manifest)
        self.assertEqual(ctx.exception.code, 4)

    def test_changed_tool_sha_on_resume_exits_4(self):
        with self.assertRaises(run.EvalsError) as ctx:
            run.verify_tool_shas({"battery.py": "old"}, {"battery.py": "new"})
        self.assertEqual(ctx.exception.code, 4)

    def test_matching_tool_shas_do_not_raise(self):
        self.assertTrue(run.verify_tool_shas({"battery.py": "same"}, {"battery.py": "same"}))


class EndToEndTwoCellTests(unittest.TestCase):
    """Two-cell, one-rep, drives init -> prepare -> verify -> run -> reevaluate ->
    evaluate -> gate -> report with a fake `invoke_tool`, asserting call order and
    that runs never overlap (serial)."""

    def test_full_sequence_with_fakes(self):
        calls = []

        def fake_invoke(tool, argv):
            calls.append((tool, list(argv)))
            if tool == "campaign" and argv[0] == "init":
                root = Path(argv[argv.index("--root") + 1])
                root.mkdir(parents=True, exist_ok=True)
                (root / "protocol.json").write_text("{}")
                return {"initialized": str(root)}
            if tool == "campaign" and argv[:2] == ["budget", "status"]:
                return {"remaining": 1000.0}
            if tool == "battery" and argv[0] == "prepare":
                flags = {}
                it = iter(argv[1:])
                for a in it:
                    if a.startswith("--"):
                        flags[a] = next(it, True)
                exp_dir = Path(flags["--root"]) / "experiments" / flags["--experiment"]
                exp_dir.mkdir(parents=True, exist_ok=True)
                (exp_dir / "proposal.json").write_text(json.dumps({
                    "tasks": ["t1"], "claude_permission_mode": "bypassPermissions",
                    "commands": {}, "task_source": None, "candidate_source_snapshot": None,
                    "frozen_run_schedule": [],
                }))
                return {"prepared": str(exp_dir)}
            if tool == "battery" and argv[0] == "run":
                return {"experiment": argv[argv.index("--experiment") + 1]}
            if tool == "battery" and argv[0] == "reevaluate":
                return {"experiment": argv[argv.index("--experiment") + 1], "changed": []}
            if tool == "battery" and argv[0] == "evaluate":
                exp = argv[argv.index("--experiment") + 1]
                if exp.startswith("plain-"):
                    mechanism = None
                else:
                    mechanism = {
                        "mechanism_engaged": True, "mechanism_reason": None,
                        "scored_by_backend": {"ollama": 1}, "fallback_count": 0,
                        "routed_by_route": {}, "effort_routed_by_phase_effort": {"implement:high": 1},
                        "model_routed_requested_models": {}, "model_routed_escalations_by_reason": {},
                    }
                return {"experiment": exp, "mechanism": mechanism, "amplifier_fd_series_label": None}
            if tool == "battery_report":
                return {"report": str(Path(argv[argv.index("--out") + 1]))}
            raise AssertionError(f"unexpected invoke_tool call: {tool} {argv}")

        orig_invoke = run.invoke_tool
        orig_verify = run.run_verification
        run.invoke_tool = fake_invoke
        run.run_verification = lambda *a, **k: (True, {"checks": {}}, {"ok": True, "tasks": {}})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / "out")
                rc = run.main([
                    "--suite", "s1", "--split", "dev", "--cells", "plain,judge-local+effort",
                    "--reps", "1", "--out", out, "--baseline-source", "/b",
                    "--candidate-source", "/c", "--candidate-sha", "deadbeef",
                    "--installed-cache", "/ic", "--history-index", "/hi",
                    "--events-dir", "/ev",
                ])
                self.assertEqual(rc, 0)
                manifest = json.loads((Path(out) / "manifest.json").read_text())
                self.assertEqual(manifest["schema"], run.SCHEMA_MANIFEST)
                self.assertTrue((Path(out) / "gates.json").exists())
        finally:
            run.invoke_tool = orig_invoke
            run.run_verification = orig_verify

        tool_order = [c[0] for c in calls]
        self.assertEqual(tool_order[0], "campaign")  # init first
        # every prepare precedes its own run/reevaluate/evaluate, no interleave of two runs
        run_indices = [i for i, c in enumerate(calls) if c[0] == "battery" and c[1][0] == "run"]
        self.assertEqual(len(run_indices), 2)


if __name__ == "__main__":
    unittest.main()
