"""One set of defaults: behaviors/fast-decisions.yaml is the source; the registry behavior and every
bundles/active*.yaml carry the same orchestrator config. Also: no per-phase effort map is shipped anywhere."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import config as fd_config  # noqa: E402
from amplifier_fast_decisions.contracts import Policy  # noqa: E402

PHASE_KEYS = ("orient", "explore", "implement", "max_explore_requests", "escalate_after_provider_errors")


def _doc(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def _orchestrator_config(rel: str) -> dict:
    return _doc(rel)["session"]["orchestrator"]["config"]


def _registry_config() -> dict:
    hook = next(h for h in _doc("behaviors/fast-decisions-registry.yaml")["hooks"] if h["module"] == "hooks-fast-decisions-router")
    return hook["config"]


class ConfigParityTests(unittest.TestCase):
    def test_registry_behavior_equals_orchestrator_behavior(self):
        self.assertEqual(_registry_config(), _orchestrator_config("behaviors/fast-decisions.yaml"))

    def test_active_bundles_equal_the_behavior_except_for_their_declared_differences(self):
        base = _orchestrator_config("behaviors/fast-decisions.yaml")
        for rel, extra in (("bundles/active.yaml", {"upstream"}), ("bundles/active-routing.yaml", set()),
                           ("bundles/active-mlx.yaml", {"model", "mlx_url"})):
            config = _orchestrator_config(rel)
            differing = {k for k in set(config) | set(base) if config.get(k) != base.get(k)}
            declared = extra | ({"backend", "model_routing"} if rel.endswith("mlx.yaml") else set())
            self.assertEqual(differing, declared, rel)
        mlx = _orchestrator_config("bundles/active-mlx.yaml")
        self.assertEqual((mlx["backend"], mlx["allow_external_state"]), ("mlx", False))
        self.assertEqual(mlx["model_routing"]["start_policy"], "judge")  # the rung that asks a local judge

    def test_every_orchestrator_config_is_a_valid_policy(self):
        for rel in ("behaviors/fast-decisions.yaml", "bundles/active.yaml", "bundles/active-routing.yaml", "bundles/active-mlx.yaml"):
            Policy.from_config(_orchestrator_config(rel))
        Policy.from_config(_registry_config())

    def test_no_shipped_config_carries_a_per_phase_effort_map(self):
        configs = {rel: _orchestrator_config(rel) for rel in
                   ("behaviors/fast-decisions.yaml", "bundles/active.yaml", "bundles/active-routing.yaml", "bundles/active-mlx.yaml")}
        configs["registry"] = _registry_config()
        for name, config in configs.items():
            effort = config.get("effort_routing") or {}
            self.assertEqual([k for k in PHASE_KEYS if k in effort], [], name)
            self.assertEqual(effort.get("by_tier"), {"cheap": "medium", "strong": None}, name)
            self.assertEqual(effort.get("by_host"), {"claude-fable-5-1": {"strong": "medium"}}, name)

    def test_sync_script_finds_nothing_to_do(self):
        run = subprocess.run([sys.executable, str(ROOT / "scripts/sync_active_bundles.py"), "--check"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_loader_reads_the_same_file_the_tests_parse(self):
        self.assertEqual(fd_config.shipped_config(), _orchestrator_config("behaviors/fast-decisions.yaml"))

    def test_user_overlay_is_deep_merged_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay = Path(tmp) / "settings.yaml"
            overlay.write_text("timeout_ms: 1200\nmodel_routing:\n  cheap_max_workspace_files: 500\n", encoding="utf-8")
            eff = fd_config.effective_config(settings=overlay)
            self.assertEqual(eff.policy.timeout_ms, 1200)
            self.assertEqual(eff.model_routing["cheap_max_workspace_files"], 500)
            self.assertEqual(eff.model_routing["start_model"], "claude-sonnet-5")   # untouched keys survive
            self.assertEqual(len(eff.sources), 2)
            overlay.write_text("timeout_ms: 5\n", encoding="utf-8")
            with self.assertRaises(fd_config.ConfigError):
                fd_config.effective_config(settings=overlay)
            overlay.write_text("- not a mapping\n", encoding="utf-8")
            with self.assertRaises(fd_config.ConfigError):
                fd_config.effective_config(settings=overlay)

    def test_configure_active_keeps_the_shipped_timeout_unless_one_is_given(self):
        from amplifier_fast_decisions.cli import configure
        with tempfile.TemporaryDirectory() as tmp:
            def run(timeout):
                out = Path(tmp) / f"p{timeout}.md"
                configure(SimpleNamespace(bundle_root=str(ROOT), workspace=tmp, mode="active", allow_external_state=True,
                                          events=str(Path(tmp) / "events"), timeout_ms=timeout, output=str(out), backend=None))
                text = out.read_text(encoding="utf-8").split("---")[1]
                return yaml.safe_load(text)["session"]["orchestrator"]["config"]
            default, explicit = run(None), run(900)
            self.assertEqual(default["timeout_ms"], 3000)
            self.assertEqual(default["backend"], "jev")
            self.assertEqual(default["model_routing"]["decision_scope"], "session")
            self.assertEqual(default["effort_routing"], {"by_tier": {"cheap": "medium", "strong": None}, "by_host": {"claude-fable-5-1": {"strong": "medium"}}})
            self.assertEqual(explicit["timeout_ms"], 900)

    def test_configure_active_external_backend_requires_consent(self):
        from amplifier_fast_decisions.cli import configure
        with tempfile.TemporaryDirectory() as tmp:
            for backend in ("jev", "clef", "clef-flash"):
                with self.assertRaises(ValueError):
                    configure(SimpleNamespace(bundle_root=str(ROOT), workspace=tmp, mode="active", allow_external_state=False,
                                              events=tmp, timeout_ms=None, output=str(Path(tmp) / "x.md"), backend=backend))

    def test_stale_laya_default_claims_are_gone(self):
        for rel in ("docs/GOAL.md", "docs/JEV-CUA.md", "docs/JEVGREP.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            lowered = text.lower()
            for stale in ("defaults to local laya", "default judge is local laya", "(local laya by default)", "defaults to laya",
                          "now defaults to local laya"):
                self.assertNotIn(stale, lowered, rel)
            self.assertIn("jev", lowered, rel)


if __name__ == "__main__":
    unittest.main()
