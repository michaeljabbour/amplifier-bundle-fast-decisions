"""HC04: opt-in model routing with escalation. No amplifier_core, no network."""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import Policy, TurnState
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response
from amplifier_fast_decisions.orchestrator import RoutedProvider
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter


def user(content="Fix the bug"):
    return {"role": "user", "content": content}


def assistant(tool_calls=None, content=""):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def tool_result(content="ok"):
    return {"role": "tool", "content": content}


def call(name, call_id="c1"):
    return {"id": call_id, "name": name}


def request(messages, model=None):
    kwargs = {"messages": messages, "tools": [], "tool_choice": "auto"}
    if model is not None:
        kwargs["model"] = model
    return NS(**kwargs)


def explore_messages():
    return [user(), assistant(tool_calls=[call("read_file")]), tool_result()]


def setup_service(*, policy=None):
    events = []
    coordinator = DemoCoordinator()
    policy = policy or Policy(
        mode="active", allowed_tools=("demo_inspect",), allow_synthetic_active=True
    )
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(
        policy, ScriptedBackend(delay_ms=0), emitter, coordinator, []
    )
    service.turn = TurnState("test-turn")
    runtime = Runtime(service)
    return service, runtime, events


class FailingProvider:
    """A provider that raises on complete(), for provider_error escalation tests."""

    name = "failing-provider"

    def __init__(self, exc=None):
        self.calls = 0
        self._exc = exc or RuntimeError("boom")

    def get_info(self):
        return NS(id=self.name, display_name=self.name, context_window=32000)

    async def list_models(self):
        return []

    def parse_tool_calls(self, response):
        return response.tool_calls

    async def complete(self, request, **kwargs):
        self.calls += 1
        raise self._exc


class ModelRoutingValidationTests(unittest.TestCase):
    def test_none_is_valid(self):
        Policy(model_routing=None)

    def test_empty_dict_is_invalid_start_model_required(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={})

    def test_missing_start_model_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_effort": "low"})

    def test_non_string_start_model_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": 123})

    def test_invalid_start_effort_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "start_effort": "ludicrous"})

    def test_invalid_max_requests_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={"start_model": "m", "max_requests_before_escalation": 0}
            )

    def test_non_bool_escalation_flags_raise(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={"start_model": "m", "escalate_on_test_failure": "yes"}
            )

    def test_unknown_keys_raise(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "bogus": True})

    def test_valid_full_config_accepted(self):
        Policy(
            model_routing={
                "start_model": "claude-sonnet-5",
                "start_effort": "medium",
                "max_requests_before_escalation": 8,
                "escalate_on_test_failure": True,
                "escalate_on_provider_error": True,
                "override_explicit_model": False,
            }
        )

    def test_decision_batching_default_false_does_not_affect_model_routing(self):
        """HC08's new key defaults to False and has no bearing on
        model_routing's own validation or defaults."""
        policy = Policy(model_routing={"start_model": "m"})
        self.assertFalse(policy.decision_batching)
        self.assertIsNone(policy.confidence_gates)


class ModelRoutingDisabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_leaves_request_untouched_and_emits_no_event(self):
        policy = Policy(mode="off", model_routing=None)
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request(explore_messages())

        await facade.complete(req)

        self.assertFalse(hasattr(req, "model"))
        self.assertFalse(any(e["event"].endswith("model_routed") for e in events))


class ModelRoutingEnabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_request_gets_start_model_and_effort(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "start_effort": "low",
                "max_requests_before_escalation": 8,
            },
        )
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request(explore_messages())

        await facade.complete(req)

        self.assertEqual(req.model, "claude-haiku-4-5")
        self.assertEqual(req.reasoning_effort, "low")
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["data"]["reason_code"], "start_model")
        self.assertEqual(routed[0]["data"]["requested_model"], "claude-haiku-4-5")
        self.assertEqual(routed[0]["data"]["requested_effort"], "low")
        self.assertFalse(routed[0]["data"]["escalated"])
        self.assertEqual(routed[0]["data"]["model_routed_requests"], 1)

    async def test_explicit_host_model_untouched_by_default(self):
        policy = Policy(mode="off", model_routing={"start_model": "claude-haiku-4-5"})
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request(explore_messages(), model="host-pinned-model")

        await facade.complete(req)

        self.assertEqual(req.model, "host-pinned-model")
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "host_pinned")
        self.assertIsNone(routed[0]["data"]["requested_model"])

    async def test_override_explicit_model_true_routes_anyway(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "override_explicit_model": True,
            },
        )
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request(explore_messages(), model="host-pinned-model")

        await facade.complete(req)

        self.assertEqual(req.model, "claude-haiku-4-5")
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "start_model")

    async def test_max_requests_escalation(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "max_requests_before_escalation": 2,
            },
        )
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        for _ in range(3):
            req = request(explore_messages())
            await facade.complete(req)

        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(len(routed), 3)
        self.assertEqual(
            [r["data"]["reason_code"] for r in routed],
            ["start_model", "start_model", "escalated_max_requests"],
        )
        self.assertTrue(routed[2]["data"]["escalated"])
        self.assertEqual(routed[2]["data"]["escalation_reason"], "max_requests")
        self.assertIsNone(routed[2]["data"]["requested_model"])

    async def test_test_failure_escalation(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalate_on_test_failure": True,
            },
        )
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        # First slow request routes normally.
        req1 = request(explore_messages())
        await facade.complete(req1)

        # A "bash" tool observed with a failing test run's output.
        service.turn.tool_decisions.clear()
        from amplifier_fast_decisions.orchestrator import ObservedTool

        class FakeBashTool:
            async def execute(self, input, **kwargs):
                return {
                    "success": True,
                    "output": "Ran 3 tests in 0.01s\n\nFAILED (failures=1)",
                }

        observed = ObservedTool(FakeBashTool(), runtime, "bash", workspace=None)
        await observed.execute({"command": "pytest"})

        self.assertTrue(service.turn.test_failure_seen)

        req2 = request(explore_messages())
        await facade.complete(req2)

        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[-1]["data"]["reason_code"], "escalated_test_failure")
        self.assertIsNone(routed[-1]["data"]["requested_model"])

    async def test_passing_test_output_does_not_escalate(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalate_on_test_failure": True,
            },
        )
        service, runtime, events = setup_service(policy=policy)
        from amplifier_fast_decisions.orchestrator import ObservedTool

        class FakeBashTool:
            async def execute(self, input, **kwargs):
                return {"success": True, "output": "Ran 3 tests in 0.01s\n\nOK"}

        observed = ObservedTool(FakeBashTool(), runtime, "bash", workspace=None)
        await observed.execute({"command": "pytest"})

        self.assertFalse(service.turn.test_failure_seen)

    async def test_provider_error_escalation(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalate_on_provider_error": True,
            },
        )
        service, runtime, events = setup_service(policy=policy)
        provider = FailingProvider()
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        with self.assertRaises(RuntimeError):
            await facade.complete(request(explore_messages()))

        self.assertTrue(service.turn.escalated)
        self.assertEqual(service.turn.escalation_reason, "provider_error")

        # The next request is left untouched (escalated).
        req2 = request(explore_messages())
        provider2 = DemoProvider(delay_ms=0)
        facade2 = RoutedProvider(provider2, runtime, {}, demo_response)
        await facade2.complete(req2)

        self.assertFalse(hasattr(req2, "model") and req2.model == "claude-haiku-4-5")
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[-1]["data"]["reason_code"], "escalated_provider_error")

    async def test_does_not_clobber_effort_already_routed_by_hc03(self):
        policy = Policy(
            mode="off",
            effort_routing={"explore": "medium"},
            model_routing={"start_model": "claude-haiku-4-5", "start_effort": "low"},
        )
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request(explore_messages())

        await facade.complete(req)

        # HC03 applied "medium" first; HC04 must not overwrite it with "low".
        self.assertEqual(req.reasoning_effort, "medium")
        self.assertEqual(req.model, "claude-haiku-4-5")

    async def test_turn_start_carries_model_routing_enabled(self):
        # HybridOrchestrator.execute emits turn_start with the flag; here we
        # exercise the same policy shape RoutedProvider consults directly.
        policy = Policy(mode="off", model_routing={"start_model": "m"})
        self.assertTrue(bool(policy.model_routing))
        policy_off = Policy(mode="off", model_routing=None)
        self.assertFalse(bool(policy_off.model_routing))


if __name__ == "__main__":
    unittest.main()
