"""HC05: judge-driven escalation (model_routing.escalation_judge) and
judge-driven phase classification (effort_routing.phase_judge). No
amplifier_core, no network. See docs/ARCHITECTURE.md's HC05 section.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.backends import BackendUnavailable
from amplifier_fast_decisions.contracts import (
    SLOW,
    Answer,
    Decision,
    DecisionResult,
    Policy,
    TurnState,
)
from amplifier_fast_decisions.demo import DemoProvider, demo_response
from amplifier_fast_decisions.orchestrator import ObservedTool, RoutedProvider
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


class FakeJudgeBackend:
    """Full control over each named Question's Answer, one script entry per
    ask() call (the last entry repeats if more calls happen than scripted).
    A ``None`` entry raises ``BackendUnavailable`` (simulates an
    unavailable/erroring backend); an entry missing a question's name
    leaves that question unanswered (simulates an abstain)."""

    name = "fake-judge"

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
            raise BackendUnavailable("synthetic judge failure")
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


class EscalationJudgeValidationTests(unittest.TestCase):
    def test_default_escalation_judge_is_rules_shape(self):
        policy = Policy(model_routing={"start_model": "m"})
        self.assertIsNone(policy.model_routing.get("escalation_judge"))

    def test_invalid_escalation_judge_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "escalation_judge": "bogus"})

    def test_valid_escalation_judge_accepted(self):
        Policy(model_routing={"start_model": "m", "escalation_judge": "judge"})
        Policy(model_routing={"start_model": "m", "escalation_judge": "rules"})

    def test_non_numeric_escalate_min_probability_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "escalate_min_probability": "high"})

    def test_out_of_range_escalate_min_probability_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "escalate_min_probability": 1.5})

    def test_valid_escalate_min_probability_accepted(self):
        Policy(model_routing={"start_model": "m", "escalate_min_probability": 0.7})

    def test_non_bool_phase_judge_raises(self):
        with self.assertRaises(ValueError):
            Policy(effort_routing={"explore": "low", "phase_judge": "yes"})

    def test_valid_phase_judge_accepted(self):
        Policy(effort_routing={"explore": "low", "phase_judge": True})


class EscalationJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_judge_escalates_when_probability_at_or_above_threshold(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "judge",
            },
        )
        backend = FakeJudgeBackend(
            [{"escalation_judge": {"escalate": 0.9, "continue_cheap": 0.1}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req1 = request(explore_messages())
        await facade.complete(req1)
        self.assertEqual(req1.model, "claude-haiku-4-5")
        self.assertEqual(backend.calls, 0)  # not asked on the turn's first slow request

        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertEqual(backend.calls, 1)
        self.assertTrue(service.turn.escalated)
        self.assertEqual(service.turn.escalation_reason, "judge")
        self.assertEqual(service.turn.escalation_judgements, 1)
        self.assertEqual(service.turn.escalations_by_judge, 1)
        # Escalation takes effect starting the SAME request the judge
        # escalated on -- req2 is left untouched (host/provider default).
        self.assertFalse(hasattr(req2, "model") and req2.model == "claude-haiku-4-5")

        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(len(judged), 1)
        self.assertEqual(judged[0]["data"]["choice"], "escalate")
        self.assertEqual(judged[0]["data"]["decided"], "escalate")
        self.assertAlmostEqual(judged[0]["data"]["probability"], 0.9)
        self.assertEqual(judged[0]["data"]["slow_requests_seen"], 2)
        self.assertEqual(judged[0]["data"]["backend"], "fake-judge")

        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[-1]["data"]["reason_code"], "escalated_judge")
        self.assertEqual(routed[-1]["data"]["escalation_reason"], "judge")

    async def test_judge_continues_when_probability_below_threshold(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "judge",
                "escalate_min_probability": 0.7,
            },
        )
        backend = FakeJudgeBackend(
            [{"escalation_judge": {"escalate": 0.6, "continue_cheap": 0.4}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertFalse(service.turn.escalated)
        self.assertEqual(service.turn.escalations_by_judge, 0)
        self.assertEqual(service.turn.escalation_judgements, 1)
        self.assertEqual(req2.model, "claude-haiku-4-5")  # still pinned

        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(judged[0]["data"]["choice"], "escalate")
        self.assertEqual(judged[0]["data"]["decided"], "continue")
        self.assertAlmostEqual(judged[0]["data"]["probability"], 0.6)

    async def test_abstain_falls_back_to_rules(self):
        policy = Policy(
            mode="off",
            model_routing={"start_model": "claude-haiku-4-5", "escalation_judge": "judge"},
        )
        backend = FakeJudgeBackend([{}])  # no "escalation_judge" key -> abstain
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertFalse(service.turn.escalated)
        self.assertEqual(req2.model, "claude-haiku-4-5")
        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(judged[0]["data"]["choice"], None)
        self.assertEqual(judged[0]["data"]["decided"], "fallback_rules")
        self.assertEqual(judged[0]["data"]["probability"], None)

    async def test_backend_error_falls_back_to_rules(self):
        policy = Policy(
            mode="off",
            model_routing={"start_model": "claude-haiku-4-5", "escalation_judge": "judge"},
        )
        backend = FakeJudgeBackend([None])  # raises BackendUnavailable
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        await facade.complete(request(explore_messages()))

        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(judged[0]["data"]["decided"], "fallback_rules")
        self.assertFalse(service.turn.escalated)

    async def test_deterministic_test_failure_floor_preempts_the_judge(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "judge",
                "escalate_on_test_failure": True,
            },
        )
        # Scripted to say "continue" if it were ever asked -- the assertion
        # that backend.calls stays 0 proves the deterministic trigger
        # preempts asking the judge at all, not merely that it overrides
        # a "continue" answer.
        backend = FakeJudgeBackend(
            [{"escalation_judge": {"escalate": 0.1, "continue_cheap": 0.9}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))

        class FakeBashTool:
            async def execute(self, input, **kwargs):
                return {"success": True, "output": "Ran 3 tests\n\nFAILED (failures=1)"}

        observed = ObservedTool(FakeBashTool(), runtime, "bash", workspace=None)
        await observed.execute({"command": "pytest"})
        self.assertTrue(service.turn.test_failure_seen)

        await facade.complete(request(explore_messages()))

        self.assertTrue(service.turn.escalated)
        self.assertEqual(service.turn.escalation_reason, "test_failure")
        self.assertEqual(backend.calls, 0)
        self.assertEqual(service.turn.escalation_judgements, 0)
        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(judged, [])

    async def test_jev_backend_without_allow_external_state_is_blocked_no_call(self):
        policy = Policy(
            mode="off",
            model_routing={"start_model": "claude-haiku-4-5", "escalation_judge": "judge"},
            allow_external_state=False,
        )
        backend = FakeJudgeBackend(
            [{"escalation_judge": {"escalate": 0.99, "continue_cheap": 0.01}}],
            external=True,
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        await facade.complete(request(explore_messages()))

        self.assertEqual(backend.calls, 0)  # no external call ever attempted
        self.assertFalse(service.turn.escalated)
        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(judged[0]["data"]["decided"], "fallback_rules")
        self.assertEqual(judged[0]["data"]["choice"], None)
        self.assertEqual(judged[0]["data"]["duration_ms"], 0.0)


class PhaseJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_confident_judge_overrides_and_flags_disagreement(self):
        policy = Policy(
            mode="off",
            effort_routing={
                "orient": "medium", "explore": "low", "implement": "high",
                "phase_judge": True,
            },
        )
        # Deterministic classify_phase(explore_messages()) == "explore";
        # the judge confidently says "implement" instead.
        backend = FakeJudgeBackend(
            [{"phase_classification": {"orient": 0.05, "explore": 0.05, "implement": 0.9}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req = request(explore_messages())
        await facade.complete(req)

        self.assertEqual(req.reasoning_effort, "high")  # implement's effort, not explore's
        judged = [e for e in events if e["event"].endswith("phase_judged")]
        self.assertEqual(len(judged), 1)
        self.assertEqual(judged[0]["data"]["choice"], "implement")
        self.assertFalse(judged[0]["data"]["agreed_with_rules"])
        routed = [e for e in events if e["event"].endswith("effort_routed")]
        self.assertEqual(routed[0]["data"]["phase"], "implement")

    async def test_confident_judge_agrees_with_rules(self):
        policy = Policy(
            mode="off",
            effort_routing={
                "orient": "medium", "explore": "low", "implement": "high",
                "phase_judge": True,
            },
        )
        backend = FakeJudgeBackend(
            [{"phase_classification": {"orient": 0.05, "explore": 0.9, "implement": 0.05}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req = request(explore_messages())
        await facade.complete(req)

        self.assertEqual(req.reasoning_effort, "low")
        judged = [e for e in events if e["event"].endswith("phase_judged")]
        self.assertTrue(judged[0]["data"]["agreed_with_rules"])

    async def test_abstain_leaves_deterministic_phase_in_place(self):
        policy = Policy(
            mode="off",
            effort_routing={
                "orient": "medium", "explore": "low", "implement": "high",
                "phase_judge": True,
            },
        )
        backend = FakeJudgeBackend([{}])  # no "phase_classification" key -> abstain
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req = request(explore_messages())
        await facade.complete(req)

        self.assertEqual(req.reasoning_effort, "low")  # deterministic "explore" stands
        judged = [e for e in events if e["event"].endswith("phase_judged")]
        self.assertIsNone(judged[0]["data"]["choice"])
        self.assertIsNone(judged[0]["data"]["agreed_with_rules"])

    async def test_disabled_by_default_emits_no_phase_judged_event(self):
        policy = Policy(mode="off", effort_routing={"explore": "low"})
        backend = FakeJudgeBackend([{"phase_classification": {"orient": 1.0}}])
        _service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))

        self.assertEqual(backend.calls, 0)
        self.assertFalse(any(e["event"].endswith("phase_judged") for e in events))


if __name__ == "__main__":
    unittest.main()
