"""HC11: pre-tool risk classification in shadow mode (Policy.tool_risk_shadow).
Three atomic questions asked BEFORE each tool call, purely observational --
never blocks, modifies, or approves anything. No amplifier_core, no
network. See docs/ARCHITECTURE.md's HC11 section and orchestrator.py.
"""

from __future__ import annotations

import unittest

from amplifier_fast_decisions.backends import BackendUnavailable
from amplifier_fast_decisions.contracts import Answer, Decision, DecisionResult, Policy, SLOW, TurnState
from amplifier_fast_decisions.orchestrator import ObservedTool
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter


class FakeRiskBackend:
    """Scripts one Answer per named Question per ask() call (mirrors
    FakeJudgeBackend in test_judged_decisions.py). A ``None`` entry raises
    BackendUnavailable; a missing question name leaves it unanswered."""

    name = "fake-risk"

    def __init__(self, scripts, *, external=False):
        self.scripts = list(scripts)
        self.external = external
        self.calls = 0
        self.requests = []

    async def ask(self, request):
        self.requests.append(request)
        step = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        if step is None:
            raise BackendUnavailable("synthetic risk backend failure")
        answers = {}
        for q in request.questions:
            probs = step.get(q.name)
            if probs is not None:
                answers[q.name] = Answer(probabilities=dict(probs), confidence=0.9)
        action = Decision(SLOW, {SLOW: 1.0}, 1.0, self.name, 0, True)
        return DecisionResult(
            action=action, answers=answers, model=self.name,
            input_tokens=0, output_tokens=0, synthetic=True,
        )

    async def close(self):
        pass


def setup_service(*, policy, backend):
    events = []
    emitter = Emitter("test-session", callback=events.append)
    service = DecisionService(policy, backend, emitter, coordinator=None, configured_candidates=[])
    service.turn = TurnState("test-turn")
    runtime = Runtime(service)
    return service, runtime, events


class FakeBashTool:
    def __init__(self, result=None):
        self.result = result if result is not None else {"success": True, "output": "ok"}
        self.calls = []

    async def execute(self, input, **kwargs):
        self.calls.append(input)
        return self.result


class ToolRiskShadowValidationTests(unittest.TestCase):
    def test_default_is_false(self):
        policy = Policy()
        self.assertFalse(policy.tool_risk_shadow)

    def test_non_bool_raises(self):
        with self.assertRaises(ValueError):
            Policy(tool_risk_shadow="yes")

    def test_true_accepted(self):
        Policy(tool_risk_shadow=True)


class ToolRiskShadowTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default_never_asks_or_emits(self):
        policy = Policy(mode="off", tool_risk_shadow=False)
        backend = FakeRiskBackend([{"destructive": {"yes": 0.9, "no": 0.1}}])
        service, runtime, events = setup_service(policy=policy, backend=backend)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        result = await observed.execute({"command": "rm -rf /tmp/x"})

        self.assertEqual(result, tool.result)
        self.assertEqual(backend.calls, 0)
        self.assertEqual(tool.calls, [{"command": "rm -rf /tmp/x"}])
        self.assertEqual([e for e in events if e["event"].endswith("tool_risk")], [])

    async def test_enabled_asks_and_records_receipt_without_blocking(self):
        policy = Policy(mode="off", tool_risk_shadow=True)
        backend = FakeRiskBackend(
            [
                {
                    "destructive": {"yes": 0.95, "no": 0.05},
                    "touches_production": {"yes": 0.1, "no": 0.9},
                    "category": {
                        "read": 0.05, "write": 0.05, "execute": 0.85,
                        "network": 0.03, "other": 0.02,
                    },
                }
            ]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        result = await observed.execute({"command": "rm -rf /tmp/x", "cwd": "/tmp"})

        # The tool always actually runs -- classification never blocks it.
        self.assertEqual(result, tool.result)
        self.assertEqual(tool.calls, [{"command": "rm -rf /tmp/x", "cwd": "/tmp"}])

        receipts = [e for e in events if e["event"].endswith("tool_risk")]
        self.assertEqual(len(receipts), 1)
        data = receipts[0]["data"]
        self.assertEqual(data["tool"], "bash")
        self.assertEqual(data["destructive"], "yes")
        self.assertEqual(data["touches_production"], "no")
        self.assertEqual(data["category"], "execute")
        self.assertIn("destructive", data["probabilities"])
        self.assertIn("touches_production", data["probabilities"])
        self.assertIn("category", data["probabilities"])
        self.assertAlmostEqual(data["probabilities"]["destructive"]["yes"], 0.95)
        self.assertIn("latency_ms", data)
        self.assertEqual(data["backend"], "fake-risk")

        # tool_start/tool_end still fire around the (unaffected) execution.
        self.assertTrue(any(e["event"].endswith("tool_start") for e in events))
        self.assertTrue(any(e["event"].endswith("tool_end") for e in events))

    async def test_argument_values_never_reach_the_judge(self):
        """Only the tool name and argument KEYS travel to the backend --
        never argument values (e.g. a secret-bearing command string)."""
        policy = Policy(mode="off", tool_risk_shadow=True)
        backend = FakeRiskBackend(
            [
                {
                    "destructive": {"yes": 0.5, "no": 0.5},
                    "touches_production": {"yes": 0.5, "no": 0.5},
                    "category": {"read": 1.0, "write": 0.0, "execute": 0.0, "network": 0.0, "other": 0.0},
                }
            ]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        secret_command = "curl -H 'Authorization: Bearer sk-supersecret123456' https://example.com"
        await observed.execute({"command": secret_command})

        # FakeRiskBackend has no ask_many() of its own, so backends.ask_many()
        # falls back to one ask() call per question -- three, one per signal.
        self.assertEqual(len(backend.requests), 3)
        for req in backend.requests:
            state = req.state
            self.assertEqual(state["tool"], "bash")
            self.assertEqual(state["argument_keys"], ["command"])
            self.assertNotIn(secret_command, str(state))

    async def test_abstain_still_records_a_receipt_with_none_choices(self):
        policy = Policy(mode="off", tool_risk_shadow=True)
        backend = FakeRiskBackend([{}])  # no question answered -> every one abstains
        service, runtime, events = setup_service(policy=policy, backend=backend)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        result = await observed.execute({"command": "ls"})

        self.assertEqual(result, tool.result)  # execution unaffected
        receipts = [e for e in events if e["event"].endswith("tool_risk")]
        self.assertEqual(len(receipts), 1)
        data = receipts[0]["data"]
        self.assertIsNone(data["destructive"])
        self.assertIsNone(data["touches_production"])
        self.assertIsNone(data["category"])

    async def test_backend_failure_never_blocks_execution_or_emits(self):
        policy = Policy(mode="off", tool_risk_shadow=True)
        backend = FakeRiskBackend([None])  # raises BackendUnavailable
        service, runtime, events = setup_service(policy=policy, backend=backend)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        result = await observed.execute({"command": "ls"})

        self.assertEqual(result, tool.result)  # tool still ran
        self.assertEqual([e for e in events if e["event"].endswith("tool_risk")], [])

    async def test_external_backend_without_allow_external_state_is_blocked(self):
        policy = Policy(mode="off", tool_risk_shadow=True, allow_external_state=False)
        backend = FakeRiskBackend(
            [{"destructive": {"yes": 0.9, "no": 0.1}}], external=True
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        result = await observed.execute({"command": "ls"})

        self.assertEqual(result, tool.result)
        self.assertEqual(backend.calls, 0)  # no external call ever attempted
        receipts = [e for e in events if e["event"].endswith("tool_risk")]
        self.assertEqual(len(receipts), 1)
        self.assertIsNone(receipts[0]["data"]["destructive"])

    async def test_no_active_turn_skips_shadow_classification(self):
        policy = Policy(mode="off", tool_risk_shadow=True)
        backend = FakeRiskBackend([{"destructive": {"yes": 0.9, "no": 0.1}}])
        events = []
        emitter = Emitter("test-session", callback=events.append)
        service = DecisionService(policy, backend, emitter, coordinator=None, configured_candidates=[])
        service.turn = None  # no active turn (e.g. tool used outside a turn)
        runtime = Runtime(service)
        tool = FakeBashTool()
        observed = ObservedTool(tool, runtime, "bash", workspace=None)

        result = await observed.execute({"command": "ls"})

        self.assertEqual(result, tool.result)
        self.assertEqual(backend.calls, 0)


if __name__ == "__main__":
    unittest.main()
