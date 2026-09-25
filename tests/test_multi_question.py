"""HC08 ("one call per decision point") and HC09 ("stake-scaled confidence
gates"). No amplifier_core, no network. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.backends import BackendUnavailable, JevBackend
from amplifier_fast_decisions.contracts import (
    SLOW,
    Answer,
    Decision,
    DecisionResult,
    Policy,
    TurnState,
)
from amplifier_fast_decisions.demo import DemoProvider, demo_response
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


class RecordingJudgeBackend:
    """Full control over each named Question's Answer, one script entry per
    ask()/ask_many() call. Records every DecisionRequest it receives (the
    whole request, so a test can assert how many CALLS were made and how
    many QUESTIONS each call carried). A ``None`` entry raises
    ``BackendUnavailable``.
    """

    name = "recording-judge"

    def __init__(self, scripts, *, external=False, define_ask_many=False):
        self.scripts = list(scripts)
        self.external = external
        self.calls = 0
        self.requests = []
        if define_ask_many:
            # Bind an ask_many that mirrors JevBackend/ScriptedBackend's own
            # override: answer every question in ONE ask() call.
            self.ask_many = self._ask_many_override

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

    async def _ask_many_override(self, request):
        return await self.ask(request)

    async def close(self):
        pass


def setup_service(*, policy, backend):
    events = []
    emitter = Emitter("test-session", callback=events.append)
    service = DecisionService(policy, backend, emitter, coordinator=None, configured_candidates=[])
    service.turn = TurnState("test-turn")
    runtime = Runtime(service)
    return service, runtime, events


BATCHING_POLICY_KWARGS = dict(
    mode="off",
    decision_batching=True,
    effort_routing={"orient": "medium", "explore": "low", "implement": "high", "phase_judge": True},
    model_routing={
        "start_model": "claude-haiku-4-5",
        "escalation_judge": "judge",
    },
)


class NewPolicyKeyValidationTests(unittest.TestCase):
    def test_decision_batching_defaults_false(self):
        self.assertFalse(Policy().decision_batching)

    def test_decision_batching_non_bool_raises(self):
        with self.assertRaises(ValueError):
            Policy(decision_batching="yes")

    def test_decision_batching_bool_accepted(self):
        Policy(decision_batching=True)
        Policy(decision_batching=False)

    def test_confidence_gates_defaults_none(self):
        self.assertIsNone(Policy().confidence_gates)

    def test_confidence_gates_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            Policy(confidence_gates={"bogus": 0.5})

    def test_confidence_gates_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            Policy(confidence_gates={"phase": 1.5})
        with self.assertRaises(ValueError):
            Policy(confidence_gates={"escalation": 0.0})

    def test_confidence_gates_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            Policy(confidence_gates={"read_shortcut": "high"})

    def test_confidence_gates_valid_partial_accepted(self):
        Policy(confidence_gates={"phase": 0.6})
        Policy(confidence_gates={"read_shortcut": 0.7, "phase": 0.6, "escalation": 0.9})

    def test_confidence_gates_not_dict_raises(self):
        with self.assertRaises(ValueError):
            Policy(confidence_gates=["phase"])


class BatchingProducesOneCallTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, decision_batching):
        policy = Policy(**{**BATCHING_POLICY_KWARGS, "decision_batching": decision_batching})
        backend = RecordingJudgeBackend(
            [
                {"phase_classification": {"orient": 0.05, "explore": 0.05, "implement": 0.9}},
                {
                    "phase_classification": {"orient": 0.05, "explore": 0.05, "implement": 0.9},
                    "escalation_judge": {"escalate": 0.9, "continue_cheap": 0.1},
                },
            ],
            define_ask_many=True,
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req1 = request(explore_messages())
        await facade.complete(req1)  # phase_judge only due (escalation not yet due)
        req2 = request(explore_messages())
        await facade.complete(req2)  # both due -> batched when decision_batching=True

        return service, backend, events, req2

    async def test_batching_makes_one_call_carrying_both_questions(self):
        service, backend, events, req2 = await self._run(decision_batching=True)

        # Call 1: phase alone (single question). Call 2: BOTH questions in
        # ONE call -- this is the batched decision point.
        self.assertEqual(backend.calls, 2)
        self.assertEqual(len(backend.requests[0].questions), 1)
        self.assertEqual(len(backend.requests[1].questions), 2)
        self.assertEqual(
            {q.name for q in backend.requests[1].questions},
            {"phase_classification", "escalation_judge"},
        )

        decided_batch = [e for e in events if e["event"].endswith("decided_batch")]
        self.assertEqual(len(decided_batch), 1)
        self.assertEqual(decided_batch[0]["data"]["n_questions"], 2)
        self.assertEqual(
            sorted(decided_batch[0]["data"]["question_ids"]),
            ["escalation_judge", "phase_classification"],
        )
        self.assertEqual(decided_batch[0]["data"]["backend"], "recording-judge")

        self.assertEqual(req2.reasoning_effort, "high")  # judge said implement
        self.assertTrue(service.turn.escalated)
        self.assertEqual(service.turn.escalation_reason, "judge")
        self.assertEqual(service.turn.batch_fallbacks, 0)

    async def test_sequential_path_reaches_identical_decisions(self):
        """decision_batching=False takes the pre-HC08 sequential path (two
        separate ask() calls on the second request) but reaches the exact
        same routing decisions as the batched path above, on the same
        scripted answers."""
        service, backend, events, req2 = await self._run(decision_batching=False)

        self.assertEqual(backend.calls, 3)  # 1 (phase) + 2 (phase, escalation) sequential
        self.assertEqual([e for e in events if e["event"].endswith("decided_batch")], [])

        self.assertEqual(req2.reasoning_effort, "high")
        self.assertTrue(service.turn.escalated)
        self.assertEqual(service.turn.escalation_reason, "judge")
        self.assertEqual(service.turn.batch_fallbacks, 0)

    async def test_only_one_judge_due_never_batches(self):
        """Batching is a no-op when only one of the two judges is
        configured/due -- no decided_batch event, no behavior change."""
        policy = Policy(
            mode="off",
            decision_batching=True,
            effort_routing={"explore": "low", "phase_judge": True},
        )
        backend = RecordingJudgeBackend(
            [{"phase_classification": {"orient": 0.05, "explore": 0.9, "implement": 0.05}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))

        self.assertEqual(backend.calls, 1)
        self.assertEqual([e for e in events if e["event"].endswith("decided_batch")], [])

    async def test_batching_continues_past_six_requests_without_a_max(self):
        """No max_requests_before_escalation: the escalation judge stays due on
        every later request, so every one after the first is batched -- the
        pre-check must not invent a request cap."""
        policy = Policy(**BATCHING_POLICY_KWARGS)
        keep = {"phase_classification": {"orient": 0.05, "explore": 0.05, "implement": 0.9},
                "escalation_judge": {"escalate": 0.1, "continue_cheap": 0.9}}
        backend = RecordingJudgeBackend([keep], define_ask_many=True)
        service, runtime, events = setup_service(policy=policy, backend=backend)
        facade = RoutedProvider(DemoProvider(delay_ms=0), runtime, {}, demo_response)
        for _ in range(9):
            await facade.complete(request(explore_messages()))
        self.assertFalse(service.turn.escalated)
        self.assertEqual(len([e for e in events if e["event"].endswith("decided_batch")]), 8)
        self.assertEqual(backend.calls, 9)


class BatchingJevOneRequestTests(unittest.IsolatedAsyncioTestCase):
    class _FakeSDKClient:
        def __init__(self):
            self.calls = []

        async def system_one(self, *, state, questions, model, timeout):
            self.calls.append(list(questions))
            answers = {"next_action": {"probabilities": {SLOW: 1.0}, "confidence": 1.0}}
            if "phase_classification" in questions:
                answers["phase_classification"] = {
                    "probabilities": {"orient": 0.05, "explore": 0.05, "implement": 0.9},
                    "confidence": 0.9,
                }
            if "escalation_judge" in questions:
                answers["escalation_judge"] = {
                    "probabilities": {"escalate": 0.9, "continue_cheap": 0.1},
                    "confidence": 0.9,
                }
            return {"model": "fake-jev", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}

        async def aclose(self):
            pass

    async def test_jev_sends_one_combined_request(self):
        client = self._FakeSDKClient()
        backend = JevBackend(client=client)
        policy = Policy(
            **{**BATCHING_POLICY_KWARGS, "allow_external_state": True},
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))  # phase only
        req2 = request(explore_messages())
        await facade.complete(req2)  # both -> ONE combined system_one call

        self.assertEqual(len(client.calls), 2)  # call 1: phase alone; call 2: batched
        self.assertEqual(
            sorted(q for q in client.calls[1] if q != "next_action"),
            ["escalation_judge", "phase_classification"],
        )
        self.assertTrue(service.turn.escalated)
        self.assertEqual(req2.reasoning_effort, "high")


class BatchFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_failure_falls_back_to_sequential_and_counts(self):
        """A backend whose ask_many/ask always raises makes the batched
        call fail; the request falls back to the sequential per-question
        path (existing HC05 behavior: both judges abstain to their
        deterministic/rules fallback) and turn.batch_fallbacks is counted.
        """
        policy = Policy(**BATCHING_POLICY_KWARGS)
        backend = RecordingJudgeBackend([None, None, None])  # always raises
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertEqual(service.turn.batch_fallbacks, 1)
        self.assertEqual([e for e in events if e["event"].endswith("decided_batch")], [])
        # Sequential fallback still emits both judged events for req2.
        phase_judged = [e for e in events if e["event"].endswith("phase_judged")]
        escalation_judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(len(phase_judged), 2)  # once per request
        self.assertEqual(len(escalation_judged), 1)  # only due on req2
        self.assertEqual(escalation_judged[0]["data"]["decided"], "fallback_rules")
        self.assertFalse(service.turn.escalated)


class ConfidenceGateAppliedPerKindTests(unittest.IsolatedAsyncioTestCase):
    async def test_phase_gate_blocks_low_confidence_override(self):
        """HC09: an explicit phase gate above the judge's own probability
        keeps the deterministic classification in place, unlike the
        pre-HC09 default (any non-abstain choice always applied)."""
        policy = Policy(
            mode="off",
            effort_routing={
                "orient": "medium", "explore": "low", "implement": "high",
                "phase_judge": True,
            },
            confidence_gates={"phase": 0.95},
        )
        backend = RecordingJudgeBackend(
            [{"phase_classification": {"orient": 0.05, "explore": 0.05, "implement": 0.9}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req = request(explore_messages())
        await facade.complete(req)

        self.assertEqual(req.reasoning_effort, "low")  # deterministic "explore" stands
        judged = [e for e in events if e["event"].endswith("phase_judged")]
        self.assertEqual(judged[0]["data"]["choice"], "implement")
        self.assertEqual(judged[0]["data"]["gate"], 0.95)
        self.assertFalse(judged[0]["data"]["passed_gate"])

    async def test_confidence_gate_overrides_legacy_escalate_min_probability(self):
        """HC09: confidence_gates.escalation wins over the legacy
        escalate_min_probability alias when both are set."""
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "judge",
                "escalate_min_probability": 0.5,  # legacy alias would pass at 0.8
            },
            confidence_gates={"escalation": 0.95},  # gate wins: 0.8 does not clear it
        )
        backend = RecordingJudgeBackend(
            [{"escalation_judge": {"escalate": 0.8, "continue_cheap": 0.2}}]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertFalse(service.turn.escalated)
        judged = [e for e in events if e["event"].endswith("escalation_judged")]
        self.assertEqual(judged[0]["data"]["decided"], "continue")
        self.assertEqual(judged[0]["data"]["gate"], 0.95)
        self.assertFalse(judged[0]["data"]["passed_gate"])


if __name__ == "__main__":
    unittest.main()
