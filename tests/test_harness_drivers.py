"""evals/harness_drivers.py: multi-turn resume drivers for Claude Code, Codex and Copilot CLI (study S4).

Offline: a fake `runner` returns recorded-shape output; no harness is started and no model is called. The recorded
shapes come from one-sentence smoke runs (docs/evidence/2026-10-05-harness-drivers/SMOKE.md)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import harness_drivers as hd  # noqa: E402


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class Recorder:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return self.outputs.pop(0)


CLAUDE_OK = json.dumps({"type": "result", "is_error": False, "result": "ok", "session_id": "S1", "total_cost_usd": 0.0426,
                        "num_turns": 1, "modelUsage": {"claude-sonnet-5": {}},
                        "usage": {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 10466,
                                  "cache_creation_input_tokens": 17496}})


def codex_events(thread, cumulative, text="ok"):
    return "\n".join(json.dumps(e) for e in [
        {"type": "thread.started", "thread_id": thread},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": cumulative}])


class ClaudeTests(unittest.TestCase):
    def test_start_and_resume_argv_and_cost_extraction(self):
        run = Recorder(done(CLAUDE_OK), done(CLAUDE_OK))
        driver = hd.ClaudeDriver(model="claude-sonnet-5", effort="medium", runner=run)
        first = driver.start("hello", "/w")
        second = driver.resume(first.session_id, "again", "/w")
        argv1, argv2 = run.calls[0][0], run.calls[1][0]
        self.assertEqual(argv1[:5], ["claude", "-p", "hello", "--output-format", "json"])
        self.assertIn("--effort", argv1)
        self.assertNotIn("--resume", argv1)
        self.assertEqual(argv2[argv2.index("--resume") + 1], "S1")
        self.assertEqual((first.session_id, first.text, first.cost_usd, first.cost_basis, first.model),
                         ("S1", "ok", 0.0426, "reported", "claude-sonnet-5"))
        self.assertEqual(first.usage["cache_write"], 17496)
        self.assertEqual(run.calls[0][1]["cwd"], "/w")

    def test_bad_output_and_failures_are_results_not_exceptions(self):
        bad = hd.ClaudeDriver(runner=Recorder(done("not json", 1, "boom"))).start("x", "/w")
        self.assertEqual((bad.exit_code, bad.session_id, bad.cost_usd), (1, None, None))
        self.assertIn("boom", bad.error)
        err = json.dumps({"is_error": True, "result": "rate limited", "session_id": "S2"})
        self.assertEqual(hd.ClaudeDriver(runner=Recorder(done(err))).start("x", "/w").error, "rate limited")

    def test_timeout_and_missing_binary_become_failed_turns(self):
        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)
        t = hd.ClaudeDriver(runner=slow, timeout_s=1).start("x", "/w")
        self.assertEqual((t.exit_code, t.cost_usd), (124, None))
        def missing(argv, **kw):
            raise FileNotFoundError(argv[0])
        self.assertEqual(hd.ClaudeDriver(runner=missing).start("x", "/w").exit_code, 127)


class CodexTests(unittest.TestCase):
    RATES = {"input": 1.0, "cached_input": 0.1, "output": 10.0}

    def test_usage_is_the_delta_of_the_cumulative_thread_total(self):
        first = {"input_tokens": 31113, "cached_input_tokens": 13184, "output_tokens": 5, "reasoning_output_tokens": 0}
        second = {"input_tokens": 73053, "cached_input_tokens": 44160, "output_tokens": 10, "reasoning_output_tokens": 0}
        run = Recorder(done(codex_events("T1", first)), done(codex_events("T1", second, "again")))
        driver = hd.CodexDriver(effort="low", rates=self.RATES, extra_args=["-s", "read-only"], runner=run)
        a = driver.start("one", "/w")
        b = driver.resume(a.session_id, "two", "/w")
        self.assertEqual(a.usage["input_tokens"], 31113)
        self.assertEqual((b.usage["input_tokens"], b.usage["cached_input_tokens"], b.usage["output_tokens"]), (41940, 30976, 5))
        self.assertAlmostEqual(b.cost_usd, ((41940 - 30976) * 1.0 + 30976 * 0.1 + 5 * 10.0) / 1e6)
        self.assertEqual(b.cost_basis, "tokens_x_rates")
        start_argv, resume_argv = run.calls[0][0], run.calls[1][0]
        self.assertEqual(start_argv[:3], ["codex", "exec", "--json"])
        self.assertIn("-s", start_argv)
        self.assertEqual(resume_argv[:3], ["codex", "exec", "resume"])
        self.assertNotIn("-s", resume_argv)          # `exec resume` rejects -s (found in the smoke run)
        self.assertEqual(resume_argv[-2:], ["T1", "two"])
        self.assertIn('model_reasoning_effort="low"', resume_argv)

    def test_without_rates_cost_is_none_not_guessed(self):
        usage = {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}
        r = hd.CodexDriver(runner=Recorder(done(codex_events("T", usage)))).start("x", "/w")
        self.assertEqual((r.cost_usd, r.cost_basis), (None, None))
        self.assertEqual(r.usage["input_tokens"], 10)

    def test_failure_events_surface_as_an_error(self):
        out = "\n".join(json.dumps(e) for e in [{"type": "thread.started", "thread_id": "T"},
                                                {"type": "turn.failed", "error": {"message": "quota exceeded"}}])
        r = hd.CodexDriver(runner=Recorder(done(out, 1))).start("x", "/w")
        self.assertEqual((r.exit_code, r.error), (1, "quota exceeded"))


class CopilotTests(unittest.TestCase):
    def test_session_id_is_allocated_once_and_reused_and_cost_is_premium_requests(self):
        run = Recorder(done("ok\n"), done("pelican\n"))
        driver = hd.CopilotDriver(model="claude-sonnet-4.6", runner=run)
        a = driver.start("remember", "/w")
        b = driver.resume(a.session_id, "recall", "/w")
        argv = run.calls[0][0]
        self.assertEqual(argv[argv.index("--resume") + 1], a.session_id)
        self.assertEqual(run.calls[1][0][run.calls[1][0].index("--resume") + 1], a.session_id)
        self.assertEqual((a.text, b.text), ("ok", "pelican"))
        self.assertEqual((a.cost_basis, a.usage["premium_requests"]), ("premium_requests", 1))
        self.assertAlmostEqual(a.cost_usd, 1.0 * hd.COPILOT_PREMIUM_USD)

    def test_unknown_model_multiplier_leaves_cost_unstated(self):
        r = hd.CopilotDriver(model="mystery-9", runner=Recorder(done("x"))).start("x", "/w")
        self.assertEqual((r.cost_usd, r.cost_basis), (None, None))

    def test_free_model_costs_zero(self):
        self.assertEqual(hd.CopilotDriver(model="gpt-5-mini", runner=Recorder(done("x"))).start("x", "/w").cost_usd, 0.0)


class ScriptedSessionTests(unittest.TestCase):
    def test_runs_turns_in_one_session_with_a_validator_hook(self):
        run = Recorder(done(CLAUDE_OK), done(CLAUDE_OK), done(CLAUDE_OK))
        seen = []
        out = hd.run_scripted_session(hd.ClaudeDriver(runner=run), ["a", "b", "c"], "/w", after_turn=lambda i, r: seen.append((i, r.text)))
        self.assertEqual((out["complete"], len(out["turns"]), seen), (True, 3, [(0, "ok"), (1, "ok"), (2, "ok")]))
        self.assertAlmostEqual(out["cost_usd"], 3 * 0.0426)
        self.assertEqual(out["cost_basis"], "reported")

    def test_stops_at_the_first_failed_turn_and_states_no_cost_for_a_partial_session(self):
        run = Recorder(done(CLAUDE_OK), done("", 1, "boom"))
        out = hd.run_scripted_session(hd.ClaudeDriver(runner=run), ["a", "b", "c"], "/w")
        self.assertEqual((out["complete"], len(out["turns"]), out["cost_usd"]), (False, 2, None))

    def test_unreadable_cost_on_any_turn_means_no_session_cost(self):
        usage = {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}
        out = hd.run_scripted_session(hd.CodexDriver(runner=Recorder(done(codex_events("T", usage)))), ["a"], "/w")
        self.assertEqual((out["complete"], out["cost_usd"]), (True, None))

    def test_factory(self):
        self.assertIsInstance(hd.make_driver("copilot"), hd.CopilotDriver)
        with self.assertRaises(ValueError):
            hd.make_driver("vim")


if __name__ == "__main__":
    unittest.main()
