"""Tests for evals/run.py -- the eval-suite driver over battery.py/campaign.py/
battery_report.py. No test invokes a real harness, provider, forge, or the
network: `run.invoke_tool` (the one subprocess seam) is monkeypatched with a
fake that records calls and returns canned JSON, exactly as the battery.py
tests substitute fakes for forge and the amplifier launcher.
"""
from __future__ import annotations

import json
import math
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


class AggregateTaskPairsTests(unittest.TestCase):
    def test_cross_style_comparison(self):
        comp = {"cross": {"baselines": {"amplifier-plain": {"per_task": {
            "t1": {"candidate_exec_s": 8.0, "candidate_passed": True,
                   "amplifier-plain_exec_s": 10.0, "amplifier-plain_passed": True},
        }}}}}
        pairs = run.aggregate_task_pairs([comp])
        self.assertEqual(pairs["t1"]["candidate_exec_s"], [8.0])
        self.assertEqual(pairs["t1"]["anchor_exec_s"], [10.0])
        self.assertEqual(pairs["t1"]["candidate_passed"], [True])

    def test_per_task_style_comparison_no_cross(self):
        comp = {"per_task": {"t1": {
            "amplifier-fd": {"penalized_ms": 8000.0, "outcome_passed": True},
            "amplifier-plain": {"penalized_ms": 10000.0, "outcome_passed": True},
        }}}
        pairs = run.aggregate_task_pairs([comp])
        self.assertAlmostEqual(pairs["t1"]["candidate_exec_s"][0], 8.0)
        self.assertAlmostEqual(pairs["t1"]["anchor_exec_s"][0], 10.0)

    def test_missing_comparison_entries_are_skipped(self):
        pairs = run.aggregate_task_pairs([None, {}])
        self.assertEqual(pairs, {})


class PerTaskLogRatiosAndQualityTests(unittest.TestCase):
    def test_median_across_reps_then_log_ratio(self):
        task_pairs = {"t1": {
            "candidate_exec_s": [8.0, 10.0, None], "candidate_passed": [True, True, False],
            "anchor_exec_s": [10.0, 12.0, 9.0], "anchor_passed": [True, True, True],
        }}
        ratios = run.per_task_log_ratios(task_pairs)
        # only reps where BOTH passed count: (8,10) and (10,12); medians 9.0/11.0
        self.assertAlmostEqual(ratios["t1"], math.log(9.0 / 11.0))

    def test_task_with_no_paired_passing_rep_excluded(self):
        task_pairs = {"t1": {
            "candidate_exec_s": [8.0], "candidate_passed": [False],
            "anchor_exec_s": [10.0], "anchor_passed": [True],
        }}
        self.assertEqual(run.per_task_log_ratios(task_pairs), {})

    def test_quality_counts_majority_vote(self):
        task_pairs = {
            "t1": {"candidate_passed": [True, True, False], "anchor_passed": [True, False, False],
                   "candidate_exec_s": [], "anchor_exec_s": []},
            "t2": {"candidate_passed": [False, False], "anchor_passed": [True, True],
                   "candidate_exec_s": [], "anchor_exec_s": []},
        }
        cand, anchor, n = run.quality_counts(task_pairs)
        self.assertEqual(cand, 1)   # t1 majority pass, t2 majority fail
        self.assertEqual(anchor, 1)  # t1 majority fail, t2 majority pass
        self.assertEqual(n, 2)


class BootstrapCiTests(unittest.TestCase):
    def test_empty_returns_none_triplet(self):
        self.assertEqual(run.bootstrap_ci_log_ratio({}), (None, None, None))

    def test_identical_ratios_collapse_ci_to_point(self):
        log_ratios = {"t1": math.log(0.8), "t2": math.log(0.8), "t3": math.log(0.8)}
        point, lo, hi = run.bootstrap_ci_log_ratio(log_ratios)
        self.assertAlmostEqual(point, 0.8)
        self.assertAlmostEqual(lo, 0.8)
        self.assertAlmostEqual(hi, 0.8)

    def test_deterministic_with_fixed_seed(self):
        log_ratios = {"t1": math.log(0.7), "t2": math.log(1.3), "t3": math.log(0.9), "t4": math.log(1.1)}
        first = run.bootstrap_ci_log_ratio(log_ratios, seed=42)
        second = run.bootstrap_ci_log_ratio(log_ratios, seed=42)
        self.assertEqual(first, second)

    def test_ci_bounds_bracket_the_point_for_mixed_data(self):
        log_ratios = {"t1": math.log(0.5), "t2": math.log(2.0), "t3": math.log(0.6), "t4": math.log(1.8)}
        point, lo, hi = run.bootstrap_ci_log_ratio(log_ratios)
        self.assertLessEqual(lo, point)
        self.assertGreaterEqual(hi, point)


class SignTestAndCostRatioTests(unittest.TestCase):
    def test_sign_test_p_from_log_ratios_all_negative(self):
        log_ratios = {"t1": -0.1, "t2": -0.2}
        p = run.sign_test_p_from_log_ratios(log_ratios)
        self.assertAlmostEqual(p, 0.5)

    def test_cost_ratio_from_per_harness(self):
        candidate = [{"per_harness": {"amplifier-fd": {"mean_cost_known_usd": 0.5, "unknown_cost_count": 0}}}]
        anchor = [{"per_harness": {"amplifier-plain": {"mean_cost_known_usd": 1.0, "unknown_cost_count": 1}}}]
        ratio, unknown = run.cost_ratio_from_cell_comparisons(candidate, anchor)
        self.assertAlmostEqual(ratio, 0.5)
        self.assertEqual(unknown, 1)

    def test_cost_ratio_none_when_unavailable(self):
        ratio, unknown = run.cost_ratio_from_cell_comparisons([{"per_harness": {}}], [{"per_harness": {}}])
        self.assertIsNone(ratio)
        self.assertEqual(unknown, 0)


class ClassifyVerdictTests(unittest.TestCase):
    BASE = dict(reps=3, split="holdout", gate_passed=True, quality_non_inferior=True,
                ratio_point=0.85, ratio_ci_low=0.75, ratio_ci_high=0.95, sign_p=0.01,
                paired_task_count=10, cost_ratio=0.9)

    def test_gate_failed_takes_priority(self):
        kwargs = {**self.BASE, "gate_passed": False}
        self.assertEqual(run.classify_verdict(**kwargs), "gate-failed")

    def test_quality_regressed(self):
        kwargs = {**self.BASE, "quality_non_inferior": False}
        self.assertEqual(run.classify_verdict(**kwargs), "quality-regressed")

    def test_confirmed_on_holdout_with_full_bar(self):
        self.assertEqual(run.classify_verdict(**self.BASE), "confirmed")

    def test_screen_on_dev_split_even_with_good_numbers(self):
        kwargs = {**self.BASE, "split": "dev"}
        self.assertEqual(run.classify_verdict(**kwargs), "screen")

    def test_screen_when_ci_includes_one(self):
        kwargs = {**self.BASE, "ratio_ci_high": 1.05}
        self.assertEqual(run.classify_verdict(**kwargs), "screen")

    def test_screen_when_fewer_than_3_reps(self):
        kwargs = {**self.BASE, "reps": 1}
        self.assertEqual(run.classify_verdict(**kwargs), "screen")

    def test_no_effect_when_ratio_near_one_with_enough_evidence(self):
        kwargs = {**self.BASE, "ratio_point": 1.0, "ratio_ci_high": 1.05, "sign_p": 0.8}
        self.assertEqual(run.classify_verdict(**kwargs), "no-effect")


class BuildCellResultTests(unittest.TestCase):
    def test_end_to_end_confirmed(self):
        comparisons = [{"cross": {"baselines": {"amplifier-plain": {"per_task": {
            f"t{i}": {"candidate_exec_s": 8.0, "candidate_passed": True,
                      "amplifier-plain_exec_s": 10.0, "amplifier-plain_passed": True}
            for i in range(10)
        }}}}, "per_harness": {"amplifier-fd": {"mean_cost_known_usd": 0.4, "unknown_cost_count": 0}}}] * 3
        anchor_comparisons = [{"per_harness": {"amplifier-plain": {"mean_cost_known_usd": 0.5,
                                                                    "unknown_cost_count": 0}}}] * 3
        row = run.build_cell_result("judge-local+effort", "plain", comparisons, anchor_comparisons,
                                     True, "holdout", 3)
        self.assertEqual(row["verdict"], "confirmed")
        self.assertAlmostEqual(row["exec_time_ratio"]["geomean"], 0.8)
        self.assertAlmostEqual(row["cost_ratio"], 0.8)
        self.assertEqual(row["quality"]["candidate_successes"], 10)


class Q3ComparisonTests(unittest.TestCase):
    def test_ranks_champion_against_external_harness(self):
        champion_comparisons = [{"per_task": {
            "t1": {"amplifier-fd": {"penalized_ms": 8000.0, "outcome_passed": True}},
        }}]
        externals_comparisons = [{
            "per_harness": {"codex": {}, "amplifier-plain": {}, "amplifier-fd": {}},
            "per_task": {"t1": {"codex": {"penalized_ms": 10000.0, "outcome_passed": True}}},
        }]
        result = run.q3_comparison(champion_comparisons, externals_comparisons)
        self.assertIn("codex", result)
        self.assertAlmostEqual(result["codex"]["ratio"], 0.8)
        self.assertEqual(result["codex"]["n_paired"], 1)


class DesignRecommendationTests(unittest.TestCase):
    def _cell_row(self, cell, anchor, verdict, ratio=0.9, ci_high=0.95, p=0.01, cost_ratio=0.9,
                  gate_passed=True, vs_plain=None):
        row = {
            "cell": cell, "anchor": anchor, "reps": 3, "split": "holdout", "gate_passed": gate_passed,
            "paired_task_count": 10,
            "exec_time_ratio": {"geomean": ratio, "ci95_low": ratio - 0.1, "ci95_high": ci_high,
                                 "sign_test_p": p},
            "cost_ratio": cost_ratio, "unknown_cost_count": 0,
            "quality": {"candidate_successes": 10, "anchor_successes": 10, "non_inferior": True},
            "verdict": verdict,
        }
        if vs_plain:
            row["vs_plain"] = vs_plain
        return row

    def test_routing_beats_plain_but_not_plain_sonnet_recommends_pinning_model(self):
        results = {
            "suite": "s1", "split": "holdout", "reps": 3,
            "cells": [
                self._cell_row("judge-local+effort", "plain", "screen"),
                self._cell_row("judge-local+effort+route", "plain-sonnet", "no-effect",
                               ratio=0.99, ci_high=1.05, p=0.9,
                               vs_plain={"anchor": "plain",
                                         "exec_time_ratio": {"geomean": 0.6, "ci95_low": 0.5,
                                                              "ci95_high": 0.7, "sign_test_p": 0.001},
                                         "cost_ratio": 0.5, "quality": {}}),
            ],
            "q3": None, "evidence_limits": [],
        }
        text = run.design_recommendation_text(results, run.load_cells())
        self.assertIn("pin the cheaper model", text)
        self.assertNotIn("recommend `on`", text)

    def test_routing_beats_plain_sonnet_recommends_on(self):
        results = {
            "suite": "s1", "split": "holdout", "reps": 3,
            "cells": [
                self._cell_row("judge-local+effort", "plain", "screen"),
                self._cell_row("judge-local+effort+route", "plain-sonnet", "confirmed",
                               ratio=0.8, ci_high=0.9, p=0.01, cost_ratio=0.9),
            ],
            "q3": None, "evidence_limits": [],
        }
        text = run.design_recommendation_text(results, run.load_cells())
        self.assertIn("recommend `on`", text)

    def test_champion_confirmed_recommends_active_mode(self):
        results = {
            "suite": "s1", "split": "holdout", "reps": 3,
            "cells": [self._cell_row("judge-local+effort", "plain", "confirmed")],
            "q3": None, "evidence_limits": [],
        }
        text = run.design_recommendation_text(results, run.load_cells())
        self.assertIn("recommend `active`", text)


class RenderResultsMarkdownTests(unittest.TestCase):
    def test_contains_verdict_and_evidence_limits(self):
        results = {
            "suite": "s1", "split": "dev", "reps": 3,
            "cells": [{
                "cell": "judge-local+effort", "anchor": "plain", "reps": 3, "split": "dev",
                "gate_passed": True, "paired_task_count": 10,
                "exec_time_ratio": {"geomean": 0.85, "ci95_low": 0.7, "ci95_high": 0.95, "sign_test_p": 0.02},
                "cost_ratio": 0.9, "unknown_cost_count": 0,
                "quality": {"candidate_successes": 10, "anchor_successes": 10, "non_inferior": True},
                "verdict": "screen",
            }],
            "q3": None, "evidence_limits": ["n_tasks=10"],
        }
        md = run.render_results_markdown(results)
        self.assertIn("judge-local+effort", md)
        self.assertIn("screen", md)
        self.assertIn("n_tasks=10", md)


class ScanIncompleteRunsTests(unittest.TestCase):
    def test_missing_result_and_no_running_json_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exp_dir = root / "experiments" / "EXP"
            (exp_dir / "runs").mkdir(parents=True)
            (exp_dir / "runs" / "manifest.json").write_text(json.dumps({
                "run_order": ["r1"], "runs": {"r1": {"harness": "codex"}},
            }))
            incomplete = run.scan_incomplete_runs(root, ["EXP"])
            self.assertEqual(incomplete, {"EXP": ["r1"]})

    def test_result_present_is_not_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exp_dir = root / "experiments" / "EXP"
            run_dir = exp_dir / "runs" / "r1"
            run_dir.mkdir(parents=True)
            (run_dir / "result.json").write_text("{}")
            (exp_dir / "runs" / "manifest.json").write_text(json.dumps({
                "run_order": ["r1"], "runs": {"r1": {"harness": "codex"}},
            }))
            self.assertEqual(run.scan_incomplete_runs(root, ["EXP"]), {})

    def test_live_worker_is_not_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exp_dir = root / "experiments" / "EXP"
            run_dir = exp_dir / "runs" / "r1"
            run_dir.mkdir(parents=True)
            (run_dir / "running.json").write_text(json.dumps({"pid": 999999}))
            (exp_dir / "runs" / "manifest.json").write_text(json.dumps({
                "run_order": ["r1"], "runs": {"r1": {"harness": "codex"}},
            }))
            incomplete = run.scan_incomplete_runs(root, ["EXP"], pid_alive=lambda pid: True)
            self.assertEqual(incomplete, {})

    def test_missing_manifest_is_skipped_not_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run.scan_incomplete_runs(Path(tmp), ["NOPE"]), {})


class RepsDefaultTests(unittest.TestCase):
    def test_dev_defaults_to_3_reps(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            rc = run.main(["--suite", "s1", "--split", "dev", "--cells", "plain",
                           "--out", out, "--baseline-source", "/b", "--candidate-sha", "deadbeef",
                           "--dry-run"])
            self.assertEqual(rc, 0)

    def test_holdout_defaults_to_5_reps_in_dry_run_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out"
            out_path.mkdir()
            (out_path / "PREREGISTRATION.md").write_text("x")
            out = str(out_path)
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run.main(["--suite", "s1", "--split", "holdout", "--cells", "plain",
                               "--out", out, "--baseline-source", "/b", "--candidate-sha", "deadbeef",
                               "--dry-run"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(payload["estimate"]["experiments"], 5)


class ExitCodeThreeAndSixTests(unittest.TestCase):
    def test_budget_refused_exits_3_with_partial_manifest(self):
        def fake_invoke(tool, targv):
            if tool == "campaign" and targv[0] == "init":
                root = Path(targv[targv.index("--root") + 1])
                root.mkdir(parents=True, exist_ok=True)
                (root / "protocol.json").write_text("{}")
                return {"initialized": str(root)}
            if tool == "campaign" and targv[:2] == ["budget", "status"]:
                return {"remaining": 1000.0}
            if tool == "battery" and targv[0] == "prepare":
                flags = {}
                it = iter(targv[1:])
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
            if tool == "battery" and targv[0] == "run":
                raise run.EvalsError(3, "budget")
            raise AssertionError(f"unexpected invoke_tool call: {tool} {targv}")

        orig_invoke = run.invoke_tool
        orig_verify = run.run_verification
        run.invoke_tool = fake_invoke
        run.run_verification = lambda *a, **k: (True, {"checks": {}}, {"ok": True, "tasks": {}})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / "out")
                rc = run.main([
                    "--suite", "s1", "--split", "dev", "--cells", "plain",
                    "--reps", "1", "--out", out, "--baseline-source", "/b",
                    "--candidate-source", "/c", "--candidate-sha", "deadbeef",
                    "--installed-cache", "/ic", "--history-index", "/hi", "--events-dir", "/ev",
                ])
                self.assertEqual(rc, 3)
                manifest = json.loads((Path(out) / "manifest.json").read_text())
                self.assertEqual(manifest["cells"][0]["id"], "plain")
                self.assertFalse((Path(out) / "results.json").exists())
        finally:
            run.invoke_tool = orig_invoke
            run.run_verification = orig_verify

    def test_resume_with_incomplete_run_exits_6(self):
        # Build a minimal --out dir with a pre-existing manifest.json (as if a
        # prior pass completed normally) then monkeypatch scan_incomplete_runs
        # to report a gap, exercising the exit-6 wiring in main() without
        # needing a full fake battery.py pipeline.
        def fake_invoke(tool, targv):
            if tool == "campaign" and targv[0] == "init":
                return {"adopted": True}
            if tool == "campaign" and targv[:2] == ["budget", "status"]:
                return {"remaining": 1000.0}
            if tool == "battery" and targv[0] == "prepare":
                return {"prepared": True}
            if tool == "battery" and targv[0] == "run":
                return {"done": True}
            if tool == "battery" and targv[0] == "reevaluate":
                return {"changed": []}
            if tool == "battery" and targv[0] == "evaluate":
                exp = targv[targv.index("--experiment") + 1]
                mechanism = None if exp.startswith("plain-") else {
                    "mechanism_engaged": True, "mechanism_reason": None,
                    "scored_by_backend": {"ollama": 1}, "fallback_count": 0,
                    "routed_by_route": {}, "effort_routed_by_phase_effort": {"implement:high": 1},
                    "model_routed_requested_models": {}, "model_routed_escalations_by_reason": {},
                }
                return {"experiment": exp, "mechanism": mechanism, "amplifier_fd_series_label": None,
                        "per_harness": {}, "cross": None, "evidence_limits": []}
            if tool == "battery_report":
                return {"report": "ok"}
            raise AssertionError(f"unexpected invoke_tool call: {tool} {targv}")

        orig_invoke = run.invoke_tool
        orig_verify = run.run_verification
        orig_resume = run.resume_detection
        orig_scan = run.scan_incomplete_runs
        run.invoke_tool = fake_invoke
        run.run_verification = lambda *a, **k: (True, {"checks": {}}, {"ok": True, "tasks": {}})
        run.resume_detection = lambda *a, **k: ("reuse", None)
        run.scan_incomplete_runs = lambda campaign_root, exps: {"plain-s1-dev-r1": ["EXP-t1-a1"]}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                out.mkdir()
                (out / "campaign").mkdir()
                exp_dir = out / "campaign" / "experiments" / "plain-s1-dev-r1"
                exp_dir.mkdir(parents=True)
                (exp_dir / "proposal.json").write_text("{}")
                (exp_dir / "run-argv.json").write_text(json.dumps(
                    run.cell_to_argv("plain", _load_test_cells(), _load_test_suites(), "s1", "dev", 1,
                                      out_root=out, base_seed=20260919, baseline_source="/b",
                                      candidate_source="/c", candidate_sha="deadbeef", polyglot_root=None)
                ))
                manifest = run.build_manifest(
                    argv=["x"], suite_id="s1", split="dev", reps=1,
                    suite_doc=_load_test_suites()["suites"]["s1"],
                    candidate={"source": "/c", "requested_sha": "deadbeef", "frozen_git_sha": "deadbeef"},
                    baseline={"source": "/b"},
                    cells_report=[{"id": "plain", "experiments": ["plain-s1-dev-r1"], "seeds": [20260920],
                                   "gate": {"passed": True, "flags": []}, "excluded_from_claims": False}],
                    budget_report={}, tool_shas=run.compute_tool_shas(),
                )
                (out / "manifest.json").write_text(json.dumps(manifest))
                rc = run.main(["--resume", "--out", str(out)])
                self.assertEqual(rc, 6)
        finally:
            run.invoke_tool = orig_invoke
            run.run_verification = orig_verify
            run.resume_detection = orig_resume
            run.scan_incomplete_runs = orig_scan


class EndToEndResultsArtifactsTests(unittest.TestCase):
    """Drives the same two-cell sequence as EndToEndTwoCellTests, but with a
    realistic 'evaluate' fake (cross-comparison data) to exercise the new
    results.json/RESULTS.md/DESIGN-RECOMMENDATION.md generation end to end."""

    def test_results_artifacts_written(self):
        def fake_invoke(tool, argv):
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
                    "tasks": ["t1", "t2"], "claude_permission_mode": "bypassPermissions",
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
                    return {"experiment": exp, "mechanism": None, "amplifier_fd_series_label": None,
                            "per_harness": {"amplifier-plain": {"mean_cost_known_usd": 1.0,
                                                                 "unknown_cost_count": 0}},
                            "per_task": {}, "cross": None, "evidence_limits": ["n_tasks=2"]}
                mechanism = {
                    "mechanism_engaged": True, "mechanism_reason": None,
                    "scored_by_backend": {"ollama": 2}, "fallback_count": 0,
                    "routed_by_route": {}, "effort_routed_by_phase_effort": {"implement:high": 2},
                    "model_routed_requested_models": {}, "model_routed_escalations_by_reason": {},
                }
                cross = {"baselines": {"amplifier-plain": {"per_task": {
                    "t1": {"candidate_exec_s": 8.0, "candidate_passed": True,
                           "amplifier-plain_exec_s": 10.0, "amplifier-plain_passed": True},
                    "t2": {"candidate_exec_s": 9.0, "candidate_passed": True,
                           "amplifier-plain_exec_s": 11.0, "amplifier-plain_passed": True},
                }}}, "evidence_limits": ["cross_campaign"]}
                return {"experiment": exp, "mechanism": mechanism, "amplifier_fd_series_label": None,
                        "per_harness": {"amplifier-fd": {"mean_cost_known_usd": 0.5, "unknown_cost_count": 0}},
                        "per_task": {}, "cross": cross, "evidence_limits": ["n_tasks=2"]}
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
                    "--installed-cache", "/ic", "--history-index", "/hi", "--events-dir", "/ev",
                ])
                self.assertEqual(rc, 0)
                results = json.loads((Path(out) / "results.json").read_text())
                row = next(r for r in results["cells"] if r["cell"] == "judge-local+effort")
                self.assertAlmostEqual(row["exec_time_ratio"]["geomean"], (8.0 / 10.0 * 9.0 / 11.0) ** 0.5)
                self.assertAlmostEqual(row["cost_ratio"], 0.5)
                self.assertTrue((Path(out) / "RESULTS.md").exists())
                self.assertTrue((Path(out) / "DESIGN-RECOMMENDATION.md").exists())
                md = (Path(out) / "RESULTS.md").read_text()
                self.assertIn("judge-local+effort", md)
                rec = (Path(out) / "DESIGN-RECOMMENDATION.md").read_text()
                self.assertIn("mode", rec)
        finally:
            run.invoke_tool = orig_invoke
            run.run_verification = orig_verify


if __name__ == "__main__":
    unittest.main()
