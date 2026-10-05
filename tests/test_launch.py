"""`launch`: decide once, then start Claude Code, Codex or Copilot CLI with the chosen model and effort.
Offline: the harness is never started (dry run or an injected exec)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import launch as launch_lib, smart_cli  # noqa: E402
from amplifier_fast_decisions.decide import Decision  # noqa: E402


def decision(route=True, model="claude-sonnet-5", effort="medium"):
    return Decision(route=route, tier="cheap" if route else "strong", model=model, effort=effort, reason="judge_cheap",
                    host_model="claude-fable-5-1", start_model="claude-sonnet-5", decider="jev", gate={}, judge={})


class BuildArgvTests(unittest.TestCase):
    def test_claude(self):
        argv, applied = launch_lib.build_argv("claude", decision(), ["-p", "fix it"])
        self.assertEqual(argv, ["claude", "--model", "claude-sonnet-5", "--effort", "medium", "-p", "fix it"])
        self.assertEqual(applied, {"model_applied": True, "effort_applied": True})

    def test_codex_flags_follow_the_exec_subcommands(self):
        argv, _ = launch_lib.build_argv("codex", decision(), ["exec", "say hi"])
        self.assertEqual(argv, ["codex", "exec", "-c", 'model="claude-sonnet-5"', "-c", 'model_reasoning_effort="medium"', "say hi"])
        resumed, _ = launch_lib.build_argv("codex", decision(), ["exec", "resume", "SID", "next"])
        self.assertEqual(resumed[:3], ["codex", "exec", "resume"])
        self.assertEqual(resumed[-2:], ["SID", "next"])

    def test_copilot_has_no_effort_flag(self):
        argv, applied = launch_lib.build_argv("copilot", decision(), ["-p", "fix it"])
        self.assertEqual(argv, ["copilot", "--model", "claude-sonnet-5", "-p", "fix it"])
        self.assertEqual(applied, {"model_applied": True, "effort_applied": False})

    def test_staying_on_the_host_leaves_the_harness_model_alone(self):
        argv, applied = launch_lib.build_argv("claude", decision(route=False, model="claude-fable-5-1", effort=None), ["-p", "x"])
        self.assertEqual(argv, ["claude", "-p", "x"])
        self.assertEqual(applied, {"model_applied": False, "effort_applied": False})

    def test_task_extraction_is_conservative(self):
        self.assertEqual(launch_lib.extract_task("copilot", ["--allow-all-tools", "-p", "fix the typo"]), "fix the typo")
        self.assertEqual(launch_lib.extract_task("copilot", ["--prompt=fix"]), "fix")
        self.assertEqual(launch_lib.extract_task("claude", ["-p", "fix the typo"]), "fix the typo")
        self.assertEqual(launch_lib.extract_task("codex", ["exec", "fix the typo"]), "fix the typo")
        self.assertIsNone(launch_lib.extract_task("claude", ["--model", "sonnet", "-p", "fix"]))   # ambiguous: two positionals
        self.assertIsNone(launch_lib.extract_task("claude", []))

    def test_launch_replaces_the_process_only_when_the_binary_exists(self):
        calls = []
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            launch_lib.launch("claude", decision(), ["-p", "x"], _exec=lambda path, argv: calls.append((path, argv)))
        self.assertEqual(calls[0][0], "/usr/bin/claude")
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(FileNotFoundError):
                launch_lib.launch("claude", decision(), ["-p", "x"], _exec=lambda *a: calls.append(a))
            report = launch_lib.launch("claude", decision(), ["-p", "x"], dry_run=True)
        self.assertFalse(report["binary_found"])
        self.assertEqual(len(calls), 1)

    def test_unknown_harness(self):
        with self.assertRaises(ValueError):
            launch_lib.launch("vim", decision())


class CliTests(unittest.TestCase):
    ENV = {"AFAST_SETTINGS": "/nonexistent/s.yaml"}

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.ENV), redirect_stdout(out), mock.patch("sys.stderr", err):
            os.environ.pop("AFAST_HOST_MODEL", None)
            code = smart_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_decide_cli_prints_one_json_object(self):
        code, out, _ = self.run_cli(["decide", "--task", "fix the typo", "--host-model", "claude-opus-5-5", "--decider", "rules",
                                     "--workspace", str(ROOT / "docs" / "evidence" / "2026-10-05-defaults-replay")])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual((data["route"], data["model"], data["reason"]), (False, "claude-opus-5-5", "price_gate_strong"))

    def test_decide_library_validates_its_payload(self):
        import asyncio
        from amplifier_fast_decisions import smart_tool
        for bad in ({"task": "x"}, {"host_model": "m"}, {"task": "x", "host_model": "m", "extra": 1},
                    {"task": "x", "host_model": "bad model!"}, {"task": "", "host_model": "m"}, "text"):
            result = asyncio.run(smart_tool.decide(bad, decider="always-host"))
            self.assertEqual((result["ok"], result["reason_code"]), (False, "unsupported_request"), bad)
        good = asyncio.run(smart_tool.decide({"task": "x", "host_model": "claude-fable-5-1", "workspace": str(ROOT / "docs")},
                                             decider="always-host", use_settings=False))
        self.assertTrue(good["ok"])
        self.assertEqual(good["schema"], "fd-decision/1")

    def test_decide_cli_needs_a_task_and_a_host(self):
        self.assertEqual(self.run_cli(["decide", "--host-model", "m"])[0], 2)
        self.assertEqual(self.run_cli(["decide", "--task", "x"])[0], 2)

    def test_launch_dry_run_through_the_cli(self):
        code, out, _ = self.run_cli(["launch", "--harness", "claude", "--host-model", "claude-fable-5-1", "--decider", "always-cheap",
                                     "--dry-run", "--", "-p", "fix the typo"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["argv"][:5], ["claude", "--model", "claude-sonnet-5", "--effort", "medium"])
        self.assertEqual(report["argv"][-2:], ["-p", "fix the typo"])
        self.assertTrue(report["decision"]["route"])

    def test_interactive_launch_without_a_task_fails_clearly(self):
        code, _, err = self.run_cli(["launch", "--harness", "claude", "--host-model", "m", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("--task", err)

    def test_afast_alias_reaches_the_same_code(self):
        run = subprocess.run([sys.executable, "-m", "amplifier_fast_decisions.cli", "decide", "--task", "x", "--host-model",
                              "claude-opus-5-5", "--decider", "always-host"], capture_output=True, text=True, timeout=30,
                             env={**os.environ, "PYTHONPATH": str(ROOT / "src"), **self.ENV})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["reason"], "decider_always_host")

    def test_manifest_and_help_declare_the_new_capabilities(self):
        from amplifier_fast_decisions import smart_tool
        info = smart_tool.manifest()
        text = " ".join(info["use_cases"]) + info["description"]
        self.assertIn("model and effort", text)
        for cap in ("decide", "launch"):
            self.assertIn(cap, smart_tool.CAPABILITIES)
            self.assertIn(f"`{info['name']} <capability> --help`", smart_tool.skill())
            self.assertIn("<skill_content", smart_tool.skill(cap))
        self.assertIn("decide", smart_tool.skill())
        contract = smart_tool.describe()["decide"]
        self.assertEqual(set(contract["input_schema"]["properties"]), smart_tool.DECIDE_FIELDS)
        self.assertEqual(set(contract["input_schema"]["required"]), {"task", "host_model"})


if __name__ == "__main__":
    unittest.main()
