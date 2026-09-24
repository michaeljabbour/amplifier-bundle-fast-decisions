"""Orchestrator-primary composition: loop-fast-decisions replacing the host's
loop-streaming. No amplifier_core, no network -- contract doubles only."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import Policy, TurnState
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response
from amplifier_fast_decisions.observer import install_auto_observatory
from amplifier_fast_decisions.orchestrator import (
    HybridOrchestrator,
    RoutedProvider,
    _register_upstream_capabilities,
    upstream_config,
)
from amplifier_fast_decisions.runtime import Runtime, get_runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter


def routed_request():
    return NS(messages=[{"role": "user", "content": "Fix the bug"}], tools=[], tool_choice="auto")


def setup_service(policy):
    events = []
    coordinator = DemoCoordinator()
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(policy, ScriptedBackend(delay_ms=0), emitter, coordinator, [])
    service.turn = TurnState("t")
    return service, Runtime(service), events


class UpstreamConfigTests(unittest.TestCase):
    def test_root_loop_streaming_keys_are_forwarded(self):
        # What the kernel's deep merge leaves behind when this module replaces
        # foundation's loop-streaming: its settings sit at the top level.
        config = {"mode": "active", "backend": "none", "extended_thinking": True,
                  "max_iterations": 40, "goal_stall_threshold": 2,
                  "model_routing": {"start_model": "m"}}
        self.assertEqual(upstream_config(config), {
            "extended_thinking": True, "max_iterations": 40, "goal_stall_threshold": 2})

    def test_explicit_upstream_block_wins(self):
        config = {"extended_thinking": True, "upstream": {"extended_thinking": False, "stream_delay": 0}}
        self.assertEqual(upstream_config(config), {"extended_thinking": False, "stream_delay": 0})

    def test_decision_policy_keys_never_forwarded(self):
        forwarded = upstream_config({"mode": "active", "timeout_ms": 500, "allowed_tools": ["x"],
                                     "effort_routing": {"explore": "low"}, "observatory": {}})
        self.assertEqual(forwarded, {})

    def test_hybrid_builds_upstream_with_forwarded_config(self):
        seen = {}

        class FakeLoop:
            def __init__(self, config):
                seen.update(config)

        import amplifier_fast_decisions.orchestrator as orch
        original = orch._import_upstream_loop
        orch._import_upstream_loop = lambda: FakeLoop
        try:
            _, runtime, _ = setup_service(Policy(mode="active"))
            HybridOrchestrator({"extended_thinking": True, "mode": "active"}, DemoCoordinator(), runtime)
        finally:
            orch._import_upstream_loop = original
        self.assertEqual(seen, {"extended_thinking": True})


class UpstreamCapabilityTests(unittest.TestCase):
    def test_steer_pin_and_event_names_registered(self):
        import sys
        import types

        module = types.ModuleType("fake_loop_streaming_for_test")

        class ConversationProviderPin:
            def __init__(self, orchestrator, coordinator):
                self.orchestrator, self.coordinator = orchestrator, coordinator

        class StreamingOrchestrator:
            def steer(self, message):
                return message

        StreamingOrchestrator.__module__ = module.__name__
        setattr(module, "ConversationProviderPin", ConversationProviderPin)
        setattr(module, "StreamingOrchestrator", StreamingOrchestrator)
        sys.modules[module.__name__] = module
        try:
            coordinator = DemoCoordinator()
            upstream = StreamingOrchestrator()
            registered = _register_upstream_capabilities(coordinator, upstream)
        finally:
            del sys.modules[module.__name__]
        self.assertEqual(registered, ["session.steer", "conversation.provider_pin"])
        self.assertEqual(coordinator.get_capability("session.steer")("x"), "x")
        pin = coordinator.get_capability("conversation.provider_pin")
        self.assertIs(pin.orchestrator, upstream)
        names = [n for cb in coordinator.contributors["observability.events"] for n in cb()]
        self.assertIn("execution:end", names)

    def test_missing_upstream_features_are_tolerated(self):
        coordinator = DemoCoordinator()
        self.assertEqual(_register_upstream_capabilities(coordinator, object()), [])


class ExecutionEndBackfillTests(unittest.IsolatedAsyncioTestCase):
    """The orchestrator contract requires execution:end on every exit path;
    loop-streaming skips it on early returns and exceptions."""

    async def _run(self, upstream_execute):
        coordinator = DemoCoordinator()
        hooks = coordinator.hooks

        class Upstream:
            async def execute(self, prompt, context, providers, tools, hooks, **kwargs):
                return await upstream_execute(hooks)

        with tempfile.TemporaryDirectory() as tmp:
            config = {"backend": "none", "events_dir": tmp}
            runtime, _ = get_runtime(coordinator, config, owner=True)
            orch = HybridOrchestrator(config, coordinator, runtime, upstream=Upstream())
            orch.register_lifecycle_hooks(hooks)
            try:
                try:
                    await orch.execute("hi", NS(), {}, {}, hooks)
                except RuntimeError:
                    pass
            finally:
                await runtime.close()
        return [(e, d) for e, d in hooks.events if e == "execution:end"]

    async def test_backfills_when_upstream_raises_after_start(self):
        async def upstream(hooks):
            await hooks.emit("execution:start", {"prompt": "hi"})
            raise RuntimeError("provider exploded")

        ends = await self._run(upstream)
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0][1]["status"], "error")
        self.assertEqual(ends[0][1]["source"], "loop-fast-decisions")

    async def test_no_duplicate_when_upstream_emits_end(self):
        async def upstream(hooks):
            await hooks.emit("execution:start", {"prompt": "hi"})
            await hooks.emit("execution:end", {"response": "", "status": "completed"})
            return "done"

        ends = await self._run(upstream)
        self.assertEqual(len(ends), 1)
        self.assertNotIn("source", ends[0][1])

    async def test_no_end_without_start(self):
        async def upstream(hooks):
            return "Operation denied"  # prompt:submit denied before execution:start

        self.assertEqual(await self._run(upstream), [])


class ProviderMatchTests(unittest.IsolatedAsyncioTestCase):
    def test_validation(self):
        Policy(model_routing={"start_model": "m", "provider_match": "anthropic"})
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "provider_match": ""})

    async def test_non_matching_provider_keeps_its_model(self):
        policy = Policy(mode="off", model_routing={"start_model": "claude-sonnet-5",
                                                   "provider_match": "anthropic"})
        _, runtime, events = setup_service(policy)
        facade = RoutedProvider(DemoProvider(delay_ms=0), runtime, {}, demo_response, "openai-primary")
        req = routed_request()
        await facade.complete(req)
        self.assertFalse(hasattr(req, "model"))
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[-1]["data"]["reason_code"], "provider_not_matched")

    async def test_matching_provider_is_routed(self):
        policy = Policy(mode="off", model_routing={"start_model": "claude-sonnet-5",
                                                   "provider_match": "anthropic"})
        _, runtime, events = setup_service(policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response, "anthropic-primary")
        req = routed_request()
        await facade.complete(req)
        self.assertEqual(req.model, "claude-sonnet-5")


class JudgeDisabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_backend_routes_slow_without_backend_call(self):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = get_runtime(coordinator, {"backend": "none", "mode": "active",
                                                   "events_dir": tmp}, owner=True)
            try:
                service = runtime.service
                self.assertEqual(service.backend.name, "unavailable")
                service.turn = TurnState("t")
                req = NS(messages=[{"role": "user", "content": "read README.md"}],
                         tools=[{"name": "fast_workspace"}], tool_choice="auto")
                self.assertIsNone(await service.choose(req, {}))
                self.assertLess(service.unhealthy_until, 1)  # circuit breaker never tripped
            finally:
                await runtime.close()


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_owner_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DemoCoordinator()
            hook_runtime, _ = get_runtime(coordinator, {"backend": "none", "events_dir": tmp})
            self.assertFalse(hook_runtime.orchestrator_owned)
            runtime, _ = get_runtime(coordinator, {"backend": "none", "events_dir": tmp}, owner=True)
            self.assertIs(runtime, hook_runtime)
            self.assertTrue(runtime.orchestrator_owned)
            await runtime.close()

    async def test_shadow_scorer_stands_down_under_orchestrator(self):
        from amplifier_fast_decisions.observer import ShadowScorer

        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DemoCoordinator()
            runtime, _ = get_runtime(coordinator, {"backend": "deterministic", "mode": "active",
                                                   "events_dir": tmp}, owner=True)
            scorer = ShadowScorer(runtime, coordinator, {})
            called = []

            async def snapshot():
                called.append(True)

            scorer._snapshot = snapshot
            await scorer.on_tool_pre("tool:pre", {"tool_name": "read_file"})
            await runtime.close()
        self.assertEqual(called, [])


class ObservatoryOnceTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_install_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DemoCoordinator()
            runtime, _ = get_runtime(coordinator, {"backend": "none", "events_dir": tmp}, owner=True)
            tasks: list[asyncio.Task] = []
            first = install_auto_observatory(coordinator, runtime, {}, tmp, tasks)
            second = install_auto_observatory(coordinator, runtime, {}, tmp, tasks)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertEqual(len(coordinator.hooks.handlers["session:start"]), 1)
            await runtime.close()


if __name__ == "__main__":
    unittest.main()


class MonotonicEffortTests(unittest.IsolatedAsyncioTestCase):
    """effort_routing.monotonic: effort never steps down within a turn, so the
    thinking budget (and with it the provider's message cache) is not churned
    by orient -> explore -> implement -> explore phase flips."""

    @staticmethod
    def _request(messages):
        return NS(messages=messages, tools=[], tool_choice="auto")

    async def _efforts(self, monotonic):
        policy = Policy(mode="off", effort_routing={"orient": "medium", "explore": "low",
                                                    "implement": "high", "monotonic": monotonic})
        _, runtime, events = setup_service(policy)
        facade = RoutedProvider(DemoProvider(delay_ms=0), runtime, {}, demo_response)
        user = {"role": "user", "content": "fix it"}
        read = {"role": "assistant", "content": "", "tool_calls": [{"id": "r", "name": "read_file"}]}
        write = {"role": "assistant", "content": "", "tool_calls": [{"id": "w", "name": "edit_file"}]}
        result = {"role": "tool", "content": "ok"}
        sequences = [[user], [user, read, result], [user, read, result, write, result]]
        applied = []
        for messages in sequences:
            req = self._request(messages)
            await facade.complete(req)
            applied.append(getattr(req, "reasoning_effort", None))
        reasons = [e["data"]["reason_code"] for e in events if e["event"].endswith("effort_routed")]
        return applied, reasons

    async def test_without_monotonic_effort_follows_phase(self):
        applied, _ = await self._efforts(False)
        self.assertEqual(applied, ["medium", "low", "high"])

    async def test_monotonic_holds_the_highest_effort(self):
        applied, reasons = await self._efforts(True)
        self.assertEqual(applied, ["medium", "medium", "high"])
        self.assertEqual(reasons[1], "monotonic_hold")

    def test_validation(self):
        Policy(effort_routing={"explore": "low", "monotonic": True})
        with self.assertRaises(ValueError):
            Policy(effort_routing={"explore": "low", "monotonic": "yes"})


class DifficultyRouterTests(unittest.IsolatedAsyncioTestCase):
    """model_routing.start_policy: decide the start tier once per turn."""

    class FakeJudge:
        name = "fake-judge"
        external = False

        def __init__(self, p_complex=None, fail=False):
            self.p_complex, self.fail, self.calls = p_complex, fail, 0

        async def ask(self, request):
            from amplifier_fast_decisions.contracts import Answer, Decision, DecisionResult, SLOW
            self.calls += 1
            if self.fail:
                raise RuntimeError("judge down")
            probs = {"simple": 1 - self.p_complex, "complex": self.p_complex}
            return DecisionResult(action=Decision(choice=SLOW, probabilities={SLOW: 1.0}),
                                  answers={"task_difficulty": Answer(probabilities=probs)})

        async def close(self):
            pass

    def _setup(self, routing, judge=None):
        events = []
        coordinator = DemoCoordinator()
        emitter = Emitter(coordinator.session_id, callback=events.append)
        policy = Policy(mode="off", model_routing=routing, read_shortcut=False)
        service = DecisionService(policy, judge or ScriptedBackend(delay_ms=0), emitter, coordinator, [])
        service.turn = TurnState("t")
        return service, Runtime(service), events

    async def _run(self, routing, prompt, judge=None, requests=3):
        service, runtime, events = self._setup(routing, judge)
        facade = RoutedProvider(DemoProvider(delay_ms=0), runtime, {}, demo_response, "anthropic-primary")
        models = []
        for _ in range(requests):
            req = NS(messages=[{"role": "user", "content": prompt}], tools=[], tool_choice="auto")
            await facade.complete(req)
            models.append(getattr(req, "model", None))
        judged = [e["data"] for e in events if e["event"].endswith("difficulty_judged")]
        return models, judged, service.turn

    ROUTING = {"start_model": "claude-sonnet-5", "provider_match": "anthropic",
               "max_requests_before_escalation": 1}

    async def test_default_policy_is_cheap_and_silent(self):
        models, judged, _ = await self._run(dict(self.ROUTING, max_requests_before_escalation=6), "fix typo")
        self.assertEqual(models, ["claude-sonnet-5"] * 3)
        self.assertEqual(judged, [])

    async def test_judge_complex_starts_strong_and_never_escalates_or_switches(self):
        judge = self.FakeJudge(p_complex=0.9)
        models, judged, turn = await self._run(dict(self.ROUTING, start_policy="judge"), "big bug", judge)
        self.assertEqual(models, [None, None, None])      # host model throughout
        self.assertEqual(judge.calls, 1)                  # decided once per turn
        self.assertEqual(judged[0]["reason_code"], "judge_strong")
        self.assertFalse(turn.escalated)

    async def test_judge_simple_starts_cheap(self):
        judge = self.FakeJudge(p_complex=0.1)
        models, judged, _ = await self._run(dict(self.ROUTING, start_policy="judge",
                                                 max_requests_before_escalation=6), "typo", judge)
        self.assertEqual(models, ["claude-sonnet-5"] * 3)
        self.assertEqual(judged[0]["reason_code"], "judge_cheap")

    async def test_judge_failure_falls_back_to_rules(self):
        judge = self.FakeJudge(fail=True)
        long_prompt = "x" * 2500
        models, judged, _ = await self._run(dict(self.ROUTING, start_policy="judge"), long_prompt, judge)
        self.assertEqual(judged[0]["reason_code"], "rules_strong")
        self.assertEqual(models[0], None)

    def test_validation(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "start_policy": "vibes"})
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "complex_min_probability": 1.5})
        with self.assertRaises(ValueError):
            Policy(read_shortcut="no")


class EffortByTierTests(DifficultyRouterTests):
    """effort_routing.by_tier: one effort for the whole turn, chosen by the router's tier."""

    async def _efforts(self, p_complex):
        events = []
        coordinator = DemoCoordinator()
        emitter = Emitter(coordinator.session_id, callback=events.append)
        policy = Policy(mode="off", read_shortcut=False,
                        effort_routing={"orient": "medium", "explore": "low", "implement": "high",
                                        "by_tier": {"cheap": "medium", "strong": None}},
                        model_routing={"start_model": "claude-sonnet-5", "start_policy": "judge",
                                       "max_requests_before_escalation": 6})
        service = DecisionService(policy, self.FakeJudge(p_complex=p_complex), emitter, coordinator, [])
        service.turn = TurnState("t")
        facade = RoutedProvider(DemoProvider(delay_ms=0), Runtime(service), {}, demo_response, "anthropic")
        user = {"role": "user", "content": "task"}
        read = {"role": "assistant", "content": "", "tool_calls": [{"id": "r", "name": "read_file"}]}
        write = {"role": "assistant", "content": "", "tool_calls": [{"id": "w", "name": "edit_file"}]}
        result = {"role": "tool", "content": "ok"}
        applied = []
        for messages in ([user], [user, read, result], [user, read, result, write, result]):
            req = NS(messages=messages, tools=[], tool_choice="auto")
            await facade.complete(req)
            applied.append(getattr(req, "reasoning_effort", None))
        return applied

    async def test_cheap_turn_holds_one_effort_across_phases(self):
        self.assertEqual(await self._efforts(0.1), ["medium", "medium", "medium"])

    async def test_strong_turn_leaves_provider_default(self):
        self.assertEqual(await self._efforts(0.9), [None, None, None])

    def test_validation(self):
        with self.assertRaises(ValueError):
            Policy(effort_routing={"by_tier": {"huge": "low"}})
        with self.assertRaises(ValueError):
            Policy(effort_routing={"by_tier": {"cheap": "turbo"}})
