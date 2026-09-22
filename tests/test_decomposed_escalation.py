"""HC10: decomposed escalation signals (model_routing.escalation_judge:
"decomposed"). Five atomic yes/no signals asked in ONE batched ask_many()
call, combined in code via a weighted sum -- never a single trusted
verdict. No amplifier_core, no network. See docs/ARCHITECTURE.md's HC10
section and orchestrator.py.
"""

from __future__ import annotations

import unittest

from amplifier_fast_decisions.contracts import (
    DECOMPOSED_ESCALATION_SIGNALS,
    DEFAULT_ESCALATION_WEIGHTS,
    Policy,
    TurnState,
)
from amplifier_fast_decisions.demo import DemoProvider, demo_response
from amplifier_fast_decisions.orchestrator import ObservedTool, RoutedProvider
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter

# Reuse the exact same fixtures/fake backend the HC05 suite already
# validated against -- same request/turn plumbing, same batched-ask
# semantics (FakeJudgeBackend answers every named Question in one call).
from test_judged_decisions import (
    FakeJudgeBackend,
    assistant,
    call,
    request,
    tool_result,
    user,
)


def explore_messages():
    return [user(), assistant(tool_calls=[call("read_file")]), tool_result()]


def setup_service(*, policy, backend):
    events = []
    emitter = Emitter("test-session", callback=events.append)
    service = DecisionService(policy, backend, emitter, coordinator=None, configured_candidates=[])
    service.turn = TurnState("test-turn")
    runtime = Runtime(service)
    return service, runtime, events


def _signals(**overrides) -> dict:
    """One FakeJudgeBackend script entry answering every named signal with
    the given yes-probability; a signal omitted from ``overrides`` is left
    unanswered (simulates an abstain for that one signal)."""
    return {
        name: {"yes": p, "no": 1.0 - p}
        for name, p in overrides.items()
        if name in DECOMPOSED_ESCALATION_SIGNALS
    }


class DecomposedEscalationValidationTests(unittest.TestCase):
    def test_decomposed_is_a_valid_escalation_judge_mode(self):
        Policy(model_routing={"start_model": "m", "escalation_judge": "decomposed"})

    def test_default_escalation_weights_are_unused_unless_decomposed(self):
        policy = Policy(model_routing={"start_model": "m"})
        self.assertIsNone(policy.model_routing.get("escalation_weights"))

    def test_valid_escalation_weights_accepted(self):
        Policy(
            model_routing={
                "start_model": "m",
                "escalation_judge": "decomposed",
                "escalation_weights": {"tests_failing": 0.5, "plan_derailed": 0.5},
            }
        )

    def test_unknown_escalation_weight_key_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": "m",
                    "escalation_weights": {"bogus_signal": 0.5},
                }
            )

    def test_out_of_range_escalation_weight_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": "m",
                    "escalation_weights": {"tests_failing": 1.5},
                }
            )

    def test_non_dict_escalation_weights_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": "m", "escalation_weights": "nope"})

    def test_default_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(DEFAULT_ESCALATION_WEIGHTS.values()), 1.0)
        self.assertEqual(set(DEFAULT_ESCALATION_WEIGHTS), set(DECOMPOSED_ESCALATION_SIGNALS))


class DecomposedEscalationTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_signals_escalate(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
            },
        )
        # All five signals at yes=1.0 -> weighted score 1.0, well above the
        # default gate (0.7) + the 0.1 uncertain band.
        backend = FakeJudgeBackend(
            [
                _signals(
                    plan_derailed=1.0,
                    repeated_tool_errors=1.0,
                    tests_failing=1.0,
                    unfamiliar_code=1.0,
                    beyond_tier=1.0,
                )
            ]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        self.assertEqual(backend.calls, 0)  # not asked on the turn's first slow request
        req2 = request(explore_messages())
        await facade.complete(req2)

        # FakeJudgeBackend has no ask_many() of its own, so backends.ask_many()
        # falls back to one ask() call per question -- five, one per signal.
        self.assertEqual(backend.calls, 5)
        self.assertTrue(service.turn.escalated)
        self.assertEqual(service.turn.escalation_reason, "decomposed")
        self.assertEqual(service.turn.escalations_by_judge, 1)
        self.assertEqual(service.turn.escalation_judgements, 1)

        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(len(signals), 1)
        data = signals[0]["data"]
        self.assertEqual(data["decided"], "escalate")
        self.assertAlmostEqual(data["score"], 1.0)
        self.assertEqual(data["gate"], 0.7)
        self.assertAlmostEqual(data["band"], 0.1)
        self.assertEqual(set(data["signal_probabilities"]), set(DECOMPOSED_ESCALATION_SIGNALS))
        for probability in data["signal_probabilities"].values():
            self.assertAlmostEqual(probability, 1.0)

        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[-1]["data"]["reason_code"], "escalated_decomposed")

    async def test_low_signals_continue(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
            },
        )
        backend = FakeJudgeBackend(
            [
                _signals(
                    plan_derailed=0.0,
                    repeated_tool_errors=0.0,
                    tests_failing=0.0,
                    unfamiliar_code=0.0,
                    beyond_tier=0.0,
                )
            ]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertFalse(service.turn.escalated)
        self.assertEqual(req2.model, "claude-haiku-4-5")  # still pinned

        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(signals[0]["data"]["decided"], "continue")
        self.assertAlmostEqual(signals[0]["data"]["score"], 0.0)

    async def test_score_inside_uncertain_band_does_not_act(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
            },
        )
        # tests_failing(0.30) + repeated_tool_errors(0.25) + 0.75*plan_derailed(0.20)
        # = 0.30 + 0.25 + 0.15 = 0.70 -- strictly between gate-band (0.6)
        # and gate+band (0.8).
        backend = FakeJudgeBackend(
            [
                _signals(
                    tests_failing=1.0,
                    repeated_tool_errors=1.0,
                    plan_derailed=0.75,
                    unfamiliar_code=0.0,
                    beyond_tier=0.0,
                )
            ]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertFalse(service.turn.escalated)
        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(signals[0]["data"]["decided"], "uncertain_rules_only")
        self.assertAlmostEqual(signals[0]["data"]["score"], 0.70)

    async def test_all_signals_abstain_falls_back_to_rules(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
            },
        )
        backend = FakeJudgeBackend([{}])  # no signal answered -> every signal abstains
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        req2 = request(explore_messages())
        await facade.complete(req2)

        self.assertFalse(service.turn.escalated)
        self.assertEqual(req2.model, "claude-haiku-4-5")
        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(signals[0]["data"]["decided"], "fallback_rules")
        for probability in signals[0]["data"]["signal_probabilities"].values():
            self.assertIsNone(probability)

    async def test_backend_error_falls_back_to_rules(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
            },
        )
        backend = FakeJudgeBackend([None])  # raises BackendUnavailable
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        await facade.complete(request(explore_messages()))

        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(signals[0]["data"]["decided"], "fallback_rules")
        self.assertFalse(service.turn.escalated)

    async def test_custom_weights_change_the_score(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
                # Put ALL weight on unfamiliar_code (default weight 0.10) so
                # a yes=1.0 there alone crosses the default gate + band.
                "escalation_weights": {"unfamiliar_code": 1.0},
            },
        )
        backend = FakeJudgeBackend(
            [
                _signals(
                    plan_derailed=0.0,
                    repeated_tool_errors=0.0,
                    tests_failing=0.0,
                    beyond_tier=0.0,
                    unfamiliar_code=1.0,
                )
            ]
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        await facade.complete(request(explore_messages()))

        self.assertTrue(service.turn.escalated)
        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertAlmostEqual(signals[0]["data"]["score"], 1.0)

    async def test_deterministic_test_failure_floor_preempts_decomposed(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "escalation_judge": "decomposed",
                "escalate_on_test_failure": True,
            },
        )
        # Scripted so it would NOT escalate if it were ever asked -- proves
        # the deterministic trigger preempts asking the signals at all.
        backend = FakeJudgeBackend(
            [
                _signals(
                    plan_derailed=0.0,
                    repeated_tool_errors=0.0,
                    tests_failing=0.0,
                    unfamiliar_code=0.0,
                    beyond_tier=0.0,
                )
            ]
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
        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(signals, [])

    async def test_external_backend_without_allow_external_state_is_blocked(self):
        policy = Policy(
            mode="off",
            model_routing={"start_model": "claude-haiku-4-5", "escalation_judge": "decomposed"},
            allow_external_state=False,
        )
        backend = FakeJudgeBackend(
            [_signals(plan_derailed=1.0, repeated_tool_errors=1.0, tests_failing=1.0,
                      unfamiliar_code=1.0, beyond_tier=1.0)],
            external=True,
        )
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        await facade.complete(request(explore_messages()))

        self.assertEqual(backend.calls, 0)  # no external call ever attempted
        self.assertFalse(service.turn.escalated)
        signals = [e for e in events if e["event"].endswith("escalation_signals")]
        self.assertEqual(signals[0]["data"]["decided"], "fallback_rules")
        for probability in signals[0]["data"]["signal_probabilities"].values():
            self.assertIsNone(probability)

    async def test_disabled_by_default_never_asks_and_never_emits(self):
        """escalation_judge defaults to "rules" -- decomposed is fully opt-in."""
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": "claude-haiku-4-5",
                "max_requests_before_escalation": 100,
            },
        )
        backend = FakeJudgeBackend([_signals(tests_failing=1.0)])
        service, runtime, events = setup_service(policy=policy, backend=backend)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request(explore_messages()))
        await facade.complete(request(explore_messages()))

        self.assertEqual(backend.calls, 0)
        self.assertFalse(service.turn.escalated)
        self.assertEqual(
            [e for e in events if e["event"].endswith("escalation_signals")], []
        )


if __name__ == "__main__":
    unittest.main()
