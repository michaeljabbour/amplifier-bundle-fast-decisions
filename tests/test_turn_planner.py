"""Turn planner: cache- and price-aware model choice per turn.

Spec: docs/proposals/TURN-PLANNER.md. No amplifier_core, no network.
"""

from __future__ import annotations

import time
import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace as NS
from typing import Any

from amplifier_fast_decisions import planner
from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import (
    DEFAULT_PLANNER_PRIORS,
    Policy,
    TurnState,
    effective_planner_config,
)
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response
from amplifier_fast_decisions.orchestrator import RoutedProvider
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.savings import DEFAULT_RATES
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter

BALANCED_CONFIG: dict[str, Any] = {
    "objective": "balanced",
    "cost_tolerance": 0.05,
    "cache_ttl_seconds": 300,
    "expected_calls": 3.5,
    "output_tokens_per_call": 170,
    "priors": DEFAULT_PLANNER_PRIORS,
}
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5"
FABLE = "claude-fable-5-1"


def config(**overrides) -> dict[str, Any]:
    return {**BALANCED_CONFIG, **overrides}


# ---------------------------------------------------------------------------
# Pure function: planner.plan_turn
# ---------------------------------------------------------------------------


class PlanTurnTests(unittest.TestCase):
    def test_fresh_session_opus_host_balanced_prefers_sonnet(self):
        """Both cold; Sonnet writes cheaper and is faster -- balanced picks it."""
        plan = planner.plan_turn(OPUS, [SONNET], {}, 60000, 0.0, config(), DEFAULT_RATES)
        self.assertFalse(plan["abstained"])
        by_model = {o["model"]: o for o in plan["options"]}
        self.assertLess(by_model[SONNET]["cost"], by_model[OPUS]["cost"])
        self.assertLess(by_model[SONNET]["time"], by_model[OPUS]["time"])
        self.assertEqual(plan["choice"], SONNET)

    def test_speed_and_cost_objectives_agree_when_one_model_wins_both(self):
        for objective in ("speed", "cost"):
            plan = planner.plan_turn(
                OPUS, [SONNET], {}, 60000, 0.0, config(objective=objective), DEFAULT_RATES
            )
            self.assertEqual(plan["choice"], SONNET, objective)

    def test_opus_warm_80k_cached_wins_over_cold_sonnet(self):
        """Same session later: Opus warm with 80k cached beats a cold Sonnet."""
        state = {OPUS: {"last_used_at": 0.0, "cached_tokens": 80000}}
        plan = planner.plan_turn(OPUS, [SONNET], state, 90000, 10.0, config(), DEFAULT_RATES)
        self.assertFalse(plan["abstained"])
        by_model = {o["model"]: o for o in plan["options"]}
        self.assertTrue(by_model[OPUS]["warm"])
        self.assertFalse(by_model[SONNET]["warm"])
        self.assertEqual(by_model[OPUS]["cold"], 10000)
        self.assertLess(by_model[OPUS]["cost"], by_model[SONNET]["cost"])
        self.assertEqual(plan["choice"], OPUS)

    def test_fable_warm_sonnet_cold_speed_vs_cost_diverge(self):
        """Fable host warm (cold=0) with Sonnet cold at 30k: speed picks the
        faster Sonnet, cost picks the cheaper (warm) Fable."""
        state = {FABLE: {"last_used_at": 0.0, "cached_tokens": 40000}}
        speed_plan = planner.plan_turn(
            FABLE, [SONNET], state, 30000, 10.0, config(objective="speed"), DEFAULT_RATES
        )
        cost_plan = planner.plan_turn(
            FABLE, [SONNET], state, 30000, 10.0, config(objective="cost"), DEFAULT_RATES
        )
        self.assertEqual(speed_plan["choice"], SONNET)
        self.assertEqual(cost_plan["choice"], FABLE)

    def test_unknown_host_price_abstains(self):
        plan = planner.plan_turn(
            "totally-unknown-model", [SONNET], {}, 1000, 0.0, config(), DEFAULT_RATES
        )
        self.assertTrue(plan["abstained"])
        self.assertIsNone(plan["choice"])
        self.assertEqual(plan["options"], [])

    def test_unknown_host_prior_also_abstains(self):
        """A price with no prior is equally not a candidate -- including the host."""
        rates = {**DEFAULT_RATES, "priced-no-prior": (1.0, 1.0, 1.0, 1.0)}
        plan = planner.plan_turn("priced-no-prior", [SONNET], {}, 1000, 0.0, config(), rates)
        self.assertTrue(plan["abstained"])

    def test_ttl_expiry_makes_a_model_cold(self):
        state = {OPUS: {"last_used_at": 0.0, "cached_tokens": 80000}}
        cfg = config(cache_ttl_seconds=300)
        warm_plan = planner.plan_turn(OPUS, [SONNET], state, 90000, 299.0, cfg, DEFAULT_RATES)
        cold_plan = planner.plan_turn(OPUS, [SONNET], state, 90000, 301.0, cfg, DEFAULT_RATES)
        by_model_warm = {o["model"]: o for o in warm_plan["options"]}
        by_model_cold = {o["model"]: o for o in cold_plan["options"]}
        self.assertTrue(by_model_warm[OPUS]["warm"])
        self.assertFalse(by_model_cold[OPUS]["warm"])
        self.assertEqual(by_model_cold[OPUS]["cold"], 90000)
        # Now cold, Opus is no longer cheap enough to stay eligible for balanced.
        self.assertEqual(warm_plan["choice"], OPUS)
        self.assertEqual(cold_plan["choice"], SONNET)

    def test_candidates_defaulting_and_dedup(self):
        """The host itself listed again as a candidate is not double-counted."""
        plan = planner.plan_turn(OPUS, [OPUS, SONNET, SONNET], {}, 60000, 0.0, config(), DEFAULT_RATES)
        models = [o["model"] for o in plan["options"]]
        self.assertEqual(len(models), len(set(models)))

    def test_ties_go_to_host(self):
        """Identical price/prior for host and candidate: a tie always picks the host."""
        rates = {**DEFAULT_RATES, "twin-model": DEFAULT_RATES[OPUS]}
        priors = {**DEFAULT_PLANNER_PRIORS, "twin-model": DEFAULT_PLANNER_PRIORS[OPUS]}
        plan = planner.plan_turn(
            OPUS, ["twin-model"], {}, 60000, 0.0, config(priors=priors), rates
        )
        self.assertEqual(plan["choice"], OPUS)


# ---------------------------------------------------------------------------
# Config validation (contracts.py)
# ---------------------------------------------------------------------------


class PlannerValidationTests(unittest.TestCase):
    def test_absent_planner_key_is_valid(self):
        Policy(model_routing={"start_model": SONNET})

    def test_planner_none_is_valid(self):
        Policy(model_routing={"start_model": SONNET, "planner": None})

    def test_planner_must_be_dict(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": SONNET, "planner": "yes"})

    def test_unknown_planner_key_raises(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": SONNET, "planner": {"bogus": True}})

    def test_enabled_must_be_bool(self):
        with self.assertRaises(ValueError):
            Policy(model_routing={"start_model": SONNET, "planner": {"enabled": "yes"}})

    def test_invalid_objective_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": SONNET,
                    "planner": {"enabled": True, "objective": "fastest"},
                }
            )

    def test_negative_cost_tolerance_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": SONNET,
                    "planner": {"enabled": True, "cost_tolerance": -0.1},
                }
            )

    def test_candidates_must_be_strings(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": SONNET,
                    "planner": {"enabled": True, "candidates": [1, 2]},
                }
            )

    def test_non_positive_cache_ttl_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": SONNET,
                    "planner": {"enabled": True, "cache_ttl_seconds": 0},
                }
            )

    def test_priors_unknown_model_key_shape_ok_but_bad_field_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": SONNET,
                    "planner": {
                        "enabled": True,
                        "priors": {"my-model": {"latency_s": -1.0}},
                    },
                }
            )

    def test_priors_unknown_prior_key_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                model_routing={
                    "start_model": SONNET,
                    "planner": {
                        "enabled": True,
                        "priors": {"my-model": {"bogus": 1.0}},
                    },
                }
            )

    def test_valid_full_planner_config_accepted(self):
        Policy(
            model_routing={
                "start_model": SONNET,
                "planner": {
                    "enabled": True,
                    "objective": "speed",
                    "cost_tolerance": 0.1,
                    "candidates": [SONNET, "claude-haiku-4-5"],
                    "cache_ttl_seconds": 120,
                    "expected_calls": 2.0,
                    "output_tokens_per_call": 100,
                    "priors": {SONNET: {"latency_s": 1.0}},
                },
            }
        )


class EffectivePlannerConfigTests(unittest.TestCase):
    def test_none_model_routing_returns_none(self):
        self.assertIsNone(effective_planner_config(None))

    def test_missing_planner_key_returns_none(self):
        self.assertIsNone(effective_planner_config({"start_model": SONNET}))

    def test_disabled_returns_none(self):
        self.assertIsNone(
            effective_planner_config({"start_model": SONNET, "planner": {"enabled": False}})
        )

    def test_enabled_merges_defaults(self):
        merged = effective_planner_config(
            {"start_model": SONNET, "planner": {"enabled": True}}
        )
        self.assertIsNotNone(merged)
        self.assertEqual(merged["objective"], "balanced")
        self.assertEqual(merged["priors"], DEFAULT_PLANNER_PRIORS)

    def test_custom_prior_overrides_only_that_model(self):
        merged = effective_planner_config(
            {
                "start_model": SONNET,
                "planner": {"enabled": True, "priors": {SONNET: {"latency_s": 9.9}}},
            }
        )
        self.assertEqual(merged["priors"][SONNET], {"latency_s": 9.9})
        self.assertEqual(merged["priors"][OPUS], DEFAULT_PLANNER_PRIORS[OPUS])


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


def user(content="Fix the bug"):
    return {"role": "user", "content": content}


def request(messages, model=None):
    kwargs = {"messages": messages, "tools": [], "tool_choice": "auto"}
    if model is not None:
        kwargs["model"] = model
    return NS(**kwargs)


def setup_service(*, policy=None):
    events = []
    coordinator = DemoCoordinator()
    policy = policy or Policy(mode="off")
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(policy, ScriptedBackend(delay_ms=0), emitter, coordinator, [])
    service.turn = TurnState("test-turn")
    runtime = Runtime(service)
    return service, runtime, events


@dataclass
class PricedResponse:
    content: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    model: str = ""
    usage: Any = None


class PricedProvider:
    """Contract double: reports a controllable served model and usage
    (input/cache_read/cache_write tokens) per call, in call order -- lets a
    test drive the turn planner's per-model cache state precisely."""

    name = "priced-provider"

    def __init__(self, default_model: str, usage_by_call: list[dict] | None = None):
        self.default_model = default_model
        self.calls = 0
        self.requests: list[Any] = []
        self.usage_by_call = usage_by_call or []

    def get_info(self):
        return NS(id=self.name, display_name=self.name, context_window=200000)

    async def list_models(self):
        return []

    def parse_tool_calls(self, response):
        return response.tool_calls

    async def complete(self, request, **kwargs):
        self.requests.append(request)
        served = kwargs.get("model") or self.default_model
        idx = self.calls
        self.calls += 1
        spec = self.usage_by_call[idx] if idx < len(self.usage_by_call) else {}
        usage = NS(
            input_tokens=spec.get("input_tokens", 100),
            output_tokens=spec.get("output_tokens", 50),
            total_tokens=spec.get("input_tokens", 100) + spec.get("output_tokens", 50),
            cache_read_tokens=spec.get("cache_read_tokens", 0),
            cache_write_tokens=spec.get("cache_write_tokens", 0),
        )
        return PricedResponse(model=served, usage=usage)


def planner_policy(**planner_overrides) -> Policy:
    return Policy(
        mode="off",
        model_routing={
            "start_model": SONNET,
            "planner": {"enabled": True, "objective": "balanced", **planner_overrides},
        },
    )


class PlannerDisabledByteIdenticalTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_planner_key_is_byte_identical_to_pre_planner_hc04(self):
        policy = Policy(mode="off", model_routing={"start_model": SONNET})
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user()])

        await facade.complete(req)

        self.assertEqual(req.model, SONNET)
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "start_model")
        self.assertFalse(any(e["event"].endswith("turn_planned") for e in events))

    async def test_planner_enabled_false_is_byte_identical(self):
        policy = Policy(
            mode="off",
            model_routing={"start_model": SONNET, "planner": {"enabled": False}},
        )
        _service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user()])

        await facade.complete(req)

        self.assertEqual(req.model, SONNET)
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "start_model")
        self.assertFalse(any(e["event"].endswith("turn_planned") for e in events))


class PlannerOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_abstain_falls_back_to_start_model_unchanged(self):
        policy = planner_policy()
        _service, runtime, events = setup_service(policy=policy)
        # A host with no price/prior in DEFAULT_RATES/DEFAULT_PLANNER_PRIORS.
        provider = PricedProvider(default_model="totally-unpriced-model")
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user()])

        await facade.complete(req)

        self.assertEqual(req.model, SONNET)
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "start_model")
        self.assertFalse(any(e["event"].endswith("turn_planned") for e in events))

    async def test_planner_chooses_candidate_and_emits_turn_planned(self):
        policy = planner_policy()
        _service, runtime, events = setup_service(policy=policy)
        provider = PricedProvider(default_model=OPUS, usage_by_call=[{"input_tokens": 60000}])
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user()])

        await facade.complete(req)

        self.assertEqual(req.model, SONNET)
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "planner_balanced")
        self.assertEqual(routed[0]["data"]["requested_model"], SONNET)
        planned = [e for e in events if e["event"].endswith("turn_planned")]
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["data"]["choice"], SONNET)
        self.assertEqual(planned[0]["data"]["host_model"], OPUS)

    async def test_planner_chooses_host_applies_no_model_override(self):
        policy = planner_policy()
        _service, runtime, events = setup_service(policy=policy)
        # Opus warm with 80k cached beats a cold Sonnet -- see PlanTurnTests.
        # last_used_at is wall-clock time.time(), matching what the
        # orchestrator itself records (see RoutedProvider.complete).
        runtime.planner_state[OPUS] = {"last_used_at": time.time(), "cached_tokens": 80000}
        runtime.planner_last_ctx = 90000
        provider = PricedProvider(default_model=OPUS, usage_by_call=[{"input_tokens": 90000}])
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user()])

        await facade.complete(req)

        self.assertFalse(hasattr(req, "model"))
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "planner_host")
        self.assertIsNone(routed[0]["data"]["requested_model"])
        planned = [e for e in events if e["event"].endswith("turn_planned")]
        self.assertEqual(planned[0]["data"]["choice"], OPUS)

    async def test_hard_turn_never_consults_planner(self):
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": SONNET,
                "start_policy": "rules",
                "complex_min_prompt_chars": 20,
                "planner": {"enabled": True},
            },
        )
        service, runtime, events = setup_service(policy=policy)
        provider = PricedProvider(default_model=OPUS, usage_by_call=[{"input_tokens": 75000}])
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user("A" * 60)])  # exceeds complex_min_prompt_chars

        await facade.complete(req)

        self.assertFalse(hasattr(req, "model"))
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "start_strong")
        self.assertFalse(service.turn.planner_decided)
        self.assertFalse(any(e["event"].endswith("turn_planned") for e in events))

    async def test_host_pinned_turn_never_consults_planner(self):
        policy = planner_policy()
        service, runtime, events = setup_service(policy=policy)
        provider = PricedProvider(default_model=OPUS, usage_by_call=[{"input_tokens": 60000}])
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        req = request([user()], model="host-pinned-model")

        await facade.complete(req)

        self.assertEqual(req.model, "host-pinned-model")
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "host_pinned")
        self.assertFalse(service.turn.planner_decided)
        self.assertFalse(any(e["event"].endswith("turn_planned") for e in events))

    async def test_decided_once_per_turn(self):
        policy = planner_policy()
        _service, runtime, events = setup_service(policy=policy)
        provider = PricedProvider(
            default_model=OPUS,
            usage_by_call=[{"input_tokens": 60000}, {"input_tokens": 5000}],
        )
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        req_a = request([user()])
        req_b = request([user()])
        await facade.complete(req_a)
        await facade.complete(req_b)

        planned = [e for e in events if e["event"].endswith("turn_planned")]
        self.assertEqual(len(planned), 1)  # decided once, not recomputed on 2nd call
        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(len(routed), 2)
        self.assertEqual(routed[0]["data"]["requested_model"], routed[1]["data"]["requested_model"])
        self.assertEqual(req_a.model, req_b.model)

    async def test_cache_state_updated_from_provider_response(self):
        policy = planner_policy()
        _service, runtime, _events = setup_service(policy=policy)
        provider = PricedProvider(
            default_model=OPUS,
            usage_by_call=[{"input_tokens": 55000, "cache_read_tokens": 3000, "cache_write_tokens": 2000}],
        )
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request([user()]))

        # Sonnet was chosen (fresh session, balanced) -- its cache state now reflects usage.
        entry = runtime.planner_state[SONNET]
        self.assertEqual(entry["cached_tokens"], 55000 + 3000 + 2000)
        self.assertIsInstance(entry["last_used_at"], float)
        self.assertEqual(runtime.planner_last_ctx, 60000)

    async def test_planner_host_suppresses_easy_turn_shaping(self):
        """HC12 shaping must not fire on a request the planner routed to the
        host, even though turn.start_tier still reads "cheap"."""
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": SONNET,
                "planner": {"enabled": True},
                "easy_turn_guidance": "Batch your tool calls.",
            },
        )
        _service, runtime, events = setup_service(policy=policy)
        runtime.planner_state[OPUS] = {"last_used_at": time.time(), "cached_tokens": 80000}
        runtime.planner_last_ctx = 90000
        provider = PricedProvider(default_model=OPUS, usage_by_call=[{"input_tokens": 90000}])
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        await facade.complete(request([{"role": "system", "content": "sys"}, user()]))

        self.assertFalse(any(e["event"].endswith("easy_turn_shaped") for e in events))
        # The provider received the ORIGINAL request (no guidance appended).
        self.assertEqual(provider.requests[0].messages[0]["content"], "sys")


class PlannerMultiTurnHandComputedTests(unittest.IsolatedAsyncioTestCase):
    async def test_opus_host_four_turn_sequence(self):
        """Hand-computed sequence on an Opus host, balanced objective,
        Sonnet as the only candidate (default DEFAULT_PLANNER_PRIORS):

        - turn1 (easy, fresh, ctx=60k): both cold -- Sonnet is cheaper AND
          faster (0.2897 vs 0.3419 USD, 10.05s vs 12.72s) -> chosen: SONNET.
        - turn2 (hard, ctx=75k): the difficulty router sends it straight to
          the host (Opus); the planner is never consulted. This warms Opus's
          cache to 75k tokens.
        - turn3 (easy, ctx=90k): Opus is now warm (cold=15k, cost 0.1469)
          while Sonnet is cold at 90k (cost 0.2224) -- outside balanced's 5%
          cost-tolerance budget (0.1469 * 1.05 = 0.1542) -- so only Opus is
          eligible -> chosen: OPUS (host, via the planner, reason_code
          planner_host).
        - turn4 (easy, ctx=100k): Opus stays warm (cold=10k, cost 0.1299);
          Sonnet is still cold at 100k (cost 0.2690), again outside budget
          (0.1299 * 1.05 = 0.1364) -> chosen: OPUS again.

        This demonstrates the mechanism the spec names explicitly: a host
        kept warm by intervening hard turns can out-compete a cheap
        candidate that never gets to build its own cache.
        """
        policy = Policy(
            mode="off",
            model_routing={
                "start_model": SONNET,
                "start_policy": "rules",
                "complex_min_prompt_chars": 20,
                "planner": {"enabled": True, "objective": "balanced"},
            },
        )
        service, runtime, events = setup_service(policy=policy)
        provider = PricedProvider(
            default_model=OPUS,
            usage_by_call=[
                {"input_tokens": 60000},  # turn1
                {"input_tokens": 75000},  # turn2 (hard, host)
                {"input_tokens": 90000},  # turn3
                {"input_tokens": 100000},  # turn4
            ],
        )
        facade = RoutedProvider(provider, runtime, {}, demo_response)

        # turn1: easy, fresh ctx 60k.
        service.turn = TurnState("t1")
        runtime.planner_last_ctx = 60000
        req1 = request([user("Fix bug")])
        await facade.complete(req1)
        self.assertEqual(req1.model, SONNET)

        # turn2: hard (long prompt) ctx 75k -- runs on the host, untouched.
        service.turn = TurnState("t2")
        req2 = request([user("A" * 60)])
        await facade.complete(req2)
        self.assertFalse(hasattr(req2, "model"))

        # turn3: easy ctx 90k -- Opus (warm) beats a cold Sonnet.
        service.turn = TurnState("t3")
        runtime.planner_last_ctx = 90000
        req3 = request([user("Fix bug")])
        await facade.complete(req3)
        self.assertFalse(hasattr(req3, "model"))  # host chosen -- no override

        # turn4: easy ctx 100k -- Opus stays warm enough to win again.
        service.turn = TurnState("t4")
        runtime.planner_last_ctx = 100000
        req4 = request([user("Fix bug")])
        await facade.complete(req4)
        self.assertFalse(hasattr(req4, "model"))

        routed = [e for e in events if e["event"].endswith("model_routed")]
        self.assertEqual(
            [r["data"]["reason_code"] for r in routed],
            ["planner_balanced", "start_strong", "planner_host", "planner_host"],
        )
        planned = [e for e in events if e["event"].endswith("turn_planned")]
        self.assertEqual(len(planned), 3)  # turn2 never invokes the planner
        self.assertEqual([p["data"]["choice"] for p in planned], [SONNET, OPUS, OPUS])
        self.assertAlmostEqual(planned[0]["data"]["options"][1]["cost"], 0.289714, places=5)
        self.assertAlmostEqual(planned[1]["data"]["options"][0]["cost"], 0.1469, places=4)
        self.assertAlmostEqual(planned[2]["data"]["options"][0]["cost"], 0.1299, places=4)


if __name__ == "__main__":
    unittest.main()
