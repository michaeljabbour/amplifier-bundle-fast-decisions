"""`afast doctor` and the smart tool's `diagnose` load and validate the effective configuration and report it
(backend, consent, scope gate, effort, price-gate result). Both call config.config_report, so they agree."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import cli, config as fd_config, operations  # noqa: E402

SNAPSHOT = {
    "ok": True,
    "backend": {"name": "jev", "external": True, "opt_in": False, "credentials_present": {"TYPESAFE_API_KEY": False}},
    "consent": {"allow_external_state": True, "env_FAST_DECISIONS_ALLOW_EXTERNAL_STATE": None,
                "note": "decide/select take consent from their argument or the environment variable, never from this file"},
    "decision": {"start_policy": "judge", "decision_scope": "session", "start_model": "claude-sonnet-5",
                 "provider_match": "anthropic", "keep_on_host": None},
    "scope_gate": {"cheap_max_workspace_files": 300},
    "effort": {"by_tier": {"cheap": "medium", "strong": None}, "phase_map": [], "constant_within_session": True},
    "read_shortcut": False, "timeout_ms": 3000, "thresholds": {"min_probability": 0.9, "min_margin": 0.2},
    "price_gate": [
        {"host_model": "claude-opus-5-5", "route": False, "reason": "price_gate_host", "predicted_cost_ratio": 1.3656,
         "request_multiplier": 1.38, "multiplier_source": "table"},
        {"host_model": "claude-fable-5-1", "route": True, "reason": "price_gate_route", "predicted_cost_ratio": 0.5229,
         "request_multiplier": 1.11, "multiplier_source": "table"}],
    "warnings": ["missing credential environment variable(s): TYPESAFE_API_KEY"],
}


def _report(**kw):
    kw.setdefault("env", {})
    report = fd_config.config_report(use_settings=False, **kw)
    report.pop("config_sha")
    report.pop("sources")
    return report


class ConfigReportTests(unittest.TestCase):
    def test_snapshot_of_the_shipped_configuration(self):
        self.assertEqual(_report(), SNAPSHOT)

    def test_host_model_from_argument_or_environment_narrows_the_price_gate(self):
        for report in (_report(host_model="claude-opus-5-5"), _report(env={"AFAST_HOST_MODEL": "claude-opus-5-5"})):
            self.assertEqual([g["host_model"] for g in report["price_gate"]], ["claude-opus-5-5"])
            self.assertFalse(report["price_gate"][0]["route"])

    def test_credentials_are_reported_present_never_by_value(self):
        report = _report(env={"TYPESAFE_API_KEY": "SECRET-VALUE-123"})
        self.assertEqual(report["backend"]["credentials_present"], {"TYPESAFE_API_KEY": True})
        self.assertNotIn("SECRET-VALUE-123", json.dumps(report))
        self.assertEqual(report["warnings"], [])

    def test_an_opt_in_external_backend_without_consent_warns(self):
        report = _report(overrides={"backend": "clef", "allow_external_state": False})
        self.assertEqual(report["backend"]["name"], "clef")
        self.assertTrue(report["backend"]["opt_in"])
        joined = " ".join(report["warnings"])
        for needle in ("allow_external_state is false", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "opt-in"):
            self.assertIn(needle, joined)

    def test_invalid_overrides_are_reported_not_raised(self):
        report = fd_config.config_report(overrides={"timeout_ms": 1}, use_settings=False, env={})
        self.assertFalse(report["ok"])
        self.assertIn("timeout_ms", report["error"])

    def test_user_settings_overlay_shows_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay = Path(tmp) / "s.yaml"
            overlay.write_text("backend: clef-flash\nmodel_routing:\n  cheap_max_workspace_files: 700\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"AFAST_SETTINGS": str(overlay)}):
                report = fd_config.config_report(env={})
        self.assertEqual(report["backend"]["name"], "clef-flash")
        self.assertEqual(report["scope_gate"]["cheap_max_workspace_files"], 700)
        self.assertEqual(len(report["sources"]), 2)


class DoctorAndDiagnoseTests(unittest.TestCase):
    def _doctor(self, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            os.environ.pop("AFAST_SETTINGS", None)
            os.environ["AFAST_SETTINGS"] = "/nonexistent/settings.yaml"
            cli.doctor()
        return json.loads(out.getvalue())

    def test_doctor_prints_the_effective_config_and_price_gate_for_the_real_host(self):
        data = self._doctor({"AFAST_HOST_MODEL": "claude-fable-5-1"})
        check = next(c for c in data["checks"] if c["check"] == "fast_decisions_config")
        self.assertTrue(check["ok"])
        report = check["report"]
        self.assertEqual(report["backend"]["name"], "jev")
        self.assertEqual(report["scope_gate"], {"cheap_max_workspace_files": 300})
        self.assertEqual(report["effort"]["by_tier"], {"cheap": "medium", "strong": None})
        self.assertEqual([g["host_model"] for g in report["price_gate"]], ["claude-fable-5-1"])
        gate = next(c for c in data["checks"] if c["check"] == "price_gate[claude-fable-5-1]")
        self.assertEqual(gate["value"], "route")

    def test_doctor_without_a_host_checks_both_priced_hosts(self):
        env = {k: v for k, v in os.environ.items() if k != "AFAST_HOST_MODEL"}
        with mock.patch.dict(os.environ, env, clear=True):
            data = self._doctor({})
        values = {c["check"]: c["value"] for c in data["checks"] if c["check"].startswith("price_gate[")}
        self.assertEqual(values, {"price_gate[claude-opus-5-5]": "host", "price_gate[claude-fable-5-1]": "route"})

    def test_diagnose_reports_the_same_configuration_as_doctor(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AFAST_SETTINGS": "/nonexistent/s.yaml", "AFAST_HOST_MODEL": "claude-opus-5-5"}):
            diagnosed = operations.diagnose(events_dir=tmp, probe=False)["config"]
        doctored = self._doctor({"AFAST_HOST_MODEL": "claude-opus-5-5"})
        reported = next(c for c in doctored["checks"] if c["check"] == "fast_decisions_config")["report"]
        self.assertEqual(diagnosed, reported)

    def test_diagnose_surfaces_configuration_warnings_as_next_actions(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AFAST_SETTINGS": "/nonexistent/s.yaml"}):
            os.environ.pop("TYPESAFE_API_KEY", None)
            result = operations.diagnose(events_dir=tmp, probe=False)
        self.assertTrue(any(a.startswith("Configuration:") and "TYPESAFE_API_KEY" in a for a in result["next_actions"]))


if __name__ == "__main__":
    unittest.main()
