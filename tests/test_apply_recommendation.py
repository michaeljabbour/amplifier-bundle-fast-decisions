"""Tests for evals/apply_recommendation.py -- confirmed-only application of
DESIGN-BRIDGE.md's decision rules onto bundle YAML. No test touches the real
repo's behaviors/ files: each test builds an isolated --repo tempdir seeded
with the real evals/cells.yaml (so fd/effort_profiles/model_routing_profiles
match the exact definitions battery.py/run.py already use) and a copy of
behaviors/fast-decisions.yaml.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals"))

import apply_recommendation as ar
import yaml


def _make_repo(tmp):
    repo = Path(tmp) / "repo"
    (repo / "evals").mkdir(parents=True)
    (repo / "behaviors").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "evals" / "cells.yaml", repo / "evals" / "cells.yaml")
    shutil.copy(REPO_ROOT / "behaviors" / "fast-decisions.yaml", repo / "behaviors" / "fast-decisions.yaml")
    return repo


def _write_out(tmp, name, results, gates=None):
    out = Path(tmp) / name
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(results), encoding="utf-8")
    if gates is not None:
        (out / "gates.json").write_text(json.dumps(gates), encoding="utf-8")
    return out


def _cell_row(cell, anchor, verdict, gate_passed=True, geomean=0.6, ci_low=0.5, ci_high=0.75,
              candidate_successes=10, anchor_successes=10):
    return {
        "cell": cell, "anchor": anchor, "reps": 5, "split": "holdout", "gate_passed": gate_passed,
        "paired_task_count": 10,
        "exec_time_ratio": {"geomean": geomean, "ci95_low": ci_low, "ci95_high": ci_high, "sign_test_p": 0.01},
        "cost_ratio": 0.9, "unknown_cost_count": 0,
        "quality": {"candidate_successes": candidate_successes, "anchor_successes": anchor_successes,
                    "non_inferior": True},
        "verdict": verdict,
    }


def _results_doc(cells, split="holdout"):
    return {"schema": ar.RESULTS_SCHEMA, "suite": "s1", "split": split, "reps": 5,
            "cells": cells, "q3": None, "evidence_limits": []}


class NothingConfirmedTests(unittest.TestCase):
    def test_exit_2_and_no_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([_cell_row(ar.MODE_CELL, "plain", "screen")])
            out = _write_out(tmp, "out", results)
            active_path = repo / ar.ACTIVE_BEHAVIOR_RELPATH
            default_before = (repo / ar.DEFAULT_BEHAVIOR_RELPATH).read_text(encoding="utf-8")

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--dry-run"])

            self.assertEqual(rc, 2)
            self.assertFalse(active_path.exists())
            self.assertEqual((repo / ar.DEFAULT_BEHAVIOR_RELPATH).read_text(encoding="utf-8"), default_before)

    def test_apply_also_exits_2_with_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([_cell_row(ar.MODE_CELL, "plain", "screen")])
            out = _write_out(tmp, "out", results)

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--apply"])

            self.assertEqual(rc, 2)
            self.assertFalse((repo / ar.ACTIVE_BEHAVIOR_RELPATH).exists())


class IncumbentConfirmedTests(unittest.TestCase):
    def test_active_behavior_written_with_expected_keys_default_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([_cell_row(ar.MODE_CELL, "plain", "confirmed")])
            out = _write_out(tmp, "out", results)
            default_before = (repo / ar.DEFAULT_BEHAVIOR_RELPATH).read_text(encoding="utf-8")

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--apply"])

            self.assertEqual(rc, 0)
            active_path = repo / ar.ACTIVE_BEHAVIOR_RELPATH
            self.assertTrue(active_path.exists())
            doc = yaml.safe_load(active_path.read_text(encoding="utf-8"))
            config = doc["session"]["orchestrator"]["config"]
            self.assertEqual(config["mode"], "active")
            self.assertEqual(config["backend"], "ollama")
            self.assertIn("effort_routing", config)
            self.assertNotIn("model_routing", config)
            self.assertNotIn("allow_external_state", config)
            self.assertEqual((repo / ar.DEFAULT_BEHAVIOR_RELPATH).read_text(encoding="utf-8"), default_before)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([_cell_row(ar.MODE_CELL, "plain", "confirmed")])
            out = _write_out(tmp, "out", results)

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--dry-run"])

            self.assertEqual(rc, 0)
            self.assertFalse((repo / ar.ACTIVE_BEHAVIOR_RELPATH).exists())


class RoutingRuleTests(unittest.TestCase):
    def test_confirmed_vs_plain_sonnet_with_escalations_includes_model_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([
                _cell_row(ar.MODE_CELL, "plain", "confirmed"),
                _cell_row(ar.ROUTING_CELL, ar.ROUTING_ANCHOR, "confirmed"),
            ])
            gates = {ar.ROUTING_CELL: {"passed": True, "flags": []}}
            out = _write_out(tmp, "out", results, gates)

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--apply"])

            self.assertEqual(rc, 0)
            doc = yaml.safe_load((repo / ar.ACTIVE_BEHAVIOR_RELPATH).read_text(encoding="utf-8"))
            config = doc["session"]["orchestrator"]["config"]
            self.assertIn("model_routing", config)

    def test_confirmed_but_zero_escalations_excluded_with_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([
                _cell_row(ar.MODE_CELL, "plain", "confirmed"),
                _cell_row(ar.ROUTING_CELL, ar.ROUTING_ANCHOR, "confirmed"),
            ])
            gates = {ar.ROUTING_CELL: {"passed": True, "flags": [ar.CONFOUNDED_FLAG]}}
            out = _write_out(tmp, "out", results, gates)

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--apply"])

            self.assertEqual(rc, 0)
            doc = yaml.safe_load((repo / ar.ACTIVE_BEHAVIOR_RELPATH).read_text(encoding="utf-8"))
            config = doc["session"]["orchestrator"]["config"]
            self.assertNotIn("model_routing", config)
            active_text = (repo / ar.ACTIVE_BEHAVIOR_RELPATH).read_text(encoding="utf-8")
            self.assertIn("pin the cheaper model", active_text)


class JevJudgeBackendTests(unittest.TestCase):
    def test_jev_twin_confirmed_and_within_latency_adds_note_never_flips_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            results = _results_doc([
                _cell_row(ar.MODE_CELL, "plain", "confirmed"),
                _cell_row(ar.JEV_MODE_TWIN_CELL, "plain", "confirmed"),
            ])
            gates = {ar.JEV_MODE_TWIN_CELL: {"passed": True, "flags": [], "latency_within_budget": True}}
            out = _write_out(tmp, "out", results, gates)

            rc = ar.main(["--results", str(out), "--repo", str(repo), "--apply", "--promote-default"])

            self.assertEqual(rc, 0)
            active_text = (repo / ar.ACTIVE_BEHAVIOR_RELPATH).read_text(encoding="utf-8")
            self.assertIn("backend: auto", active_text)
            default_doc = yaml.safe_load((repo / ar.DEFAULT_BEHAVIOR_RELPATH).read_text(encoding="utf-8"))
            fd_hook = next(h for h in default_doc["hooks"] if h["module"] == "hooks-fast-decisions")
            self.assertFalse(fd_hook["config"]["allow_external_state"])
            self.assertEqual(fd_hook["config"]["backend"], "ollama")
            self.assertEqual(fd_hook["config"]["mode"], "active")


class MalformedInputTests(unittest.TestCase):
    def test_missing_results_json_exits_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            out = Path(tmp) / "out"
            out.mkdir()
            rc = ar.main(["--results", str(out), "--repo", str(repo), "--dry-run"])
            self.assertEqual(rc, 4)

    def test_bad_schema_exits_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "results.json").write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
            rc = ar.main(["--results", str(out), "--repo", str(repo), "--dry-run"])
            self.assertEqual(rc, 4)


if __name__ == "__main__":
    unittest.main()
