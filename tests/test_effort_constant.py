"""Invariant: effort is constant within a session, on every tier, under the shipped configuration.

The v3 study found that every effort change between requests rewrites the provider's prompt cache (requests after a
change wrote 15,642 cache tokens vs 900 unchanged). A session's effort is therefore a session-level decision. These
tests drive the real orchestrator over requests that move through orient, explore and implement phases and across
several turns, and require exactly one effort value per session.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import config as fd_config, orchestrator  # noqa: E402
from amplifier_fast_decisions.contracts import Answer, Decision, DecisionResult, Policy, SLOW, TurnState  # noqa: E402
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response  # noqa: E402
from amplifier_fast_decisions.runtime import Runtime  # noqa: E402
from amplifier_fast_decisions.service import DecisionService  # noqa: E402
from amplifier_fast_decisions.telemetry import Emitter  # noqa: E402

HOST = "claude-fable-5-1"   # priced so that the gate routes: both tiers are reachable


class Judge:
    name, external = "fake", False

    def __init__(self, p_complex):
        self.p = p_complex

    async def ask(self, request):
        return DecisionResult(action=Decision(choice=SLOW, probabilities={SLOW: 1.0}),
                              answers={"task_difficulty": Answer(probabilities={"simple": 1 - self.p, "complex": self.p})})

    ask_many = ask

    async def close(self):
        pass


def _messages(phase: int):
    user = {"role": "user", "content": "task"}
    read = {"role": "assistant", "content": "", "tool_calls": [{"id": "r", "name": "read_file"}]}
    write = {"role": "assistant", "content": "", "tool_calls": [{"id": "w", "name": "edit_file"}]}
    result = {"role": "tool", "content": "ok"}
    return [[user], [user, read, result], [user, read, result, read, result], [user, read, result, write, result]][phase]


async def session_efforts(config: dict, p_complex: float, *, turns: int = 3) -> list:
    """The effort set on every request of one session: `turns` turns, each moving orient -> explore -> implement."""
    coordinator = DemoCoordinator()
    emitter = Emitter(coordinator.session_id, callback=lambda e: None)
    policy = Policy.from_config({**config, "mode": "off", "read_shortcut": False})
    service = DecisionService(policy, Judge(p_complex), emitter, coordinator, [])
    provider = DemoProvider(delay_ms=0)
    provider.default_model = HOST
    facade = orchestrator.RoutedProvider(provider, Runtime(service), {}, demo_response, "anthropic-primary")
    seen = []
    with mock.patch.object(orchestrator, "workspace_file_count", lambda root, limit: 10):
        for t in range(turns):
            service.turn = TurnState(f"t{t}")
            for phase in range(4):
                req = NS(messages=_messages(phase), tools=[], tool_choice="auto")
                await facade.complete(req)
                seen.append((getattr(req, "model", None), getattr(req, "reasoning_effort", None)))
    return seen


class EffortConstantTests(unittest.TestCase):
    def test_cheap_tier_session_has_one_model_and_one_effort(self):
        seen = asyncio.run(session_efforts(fd_config.shipped_config(), 0.1))
        self.assertEqual(len(seen), 12)
        self.assertEqual(set(seen), {("claude-sonnet-5", "medium")})

    def test_strong_tier_session_has_one_effort(self):
        seen = asyncio.run(session_efforts(fd_config.shipped_config(), 0.9))
        self.assertEqual(set(seen), {(None, None)})

    def test_opt_in_host_effort_is_still_constant(self):
        cfg = fd_config.deep_merge(fd_config.shipped_config(), {"effort_routing": {"by_tier": {"strong": "medium"}}})
        self.assertEqual(set(asyncio.run(session_efforts(cfg, 0.9))), {(None, "medium")})

    def test_the_deleted_phase_map_would_have_varied_effort(self):
        """Why the map is gone: with it and without by_tier, effort moves between requests of one session."""
        cfg = fd_config.shipped_config()
        cfg["effort_routing"] = {"orient": "medium", "explore": "low", "implement": "high"}
        efforts = {e for _, e in asyncio.run(session_efforts(cfg, 0.9))}
        self.assertGreater(len(efforts), 1)

    def test_the_shipped_config_has_no_phase_map(self):
        effort = fd_config.shipped_config()["effort_routing"]
        self.assertEqual(set(effort), {"by_tier"})
        self.assertEqual(fd_config.config_report()["effort"]["phase_map"], [])

    def test_doctor_report_flags_a_phase_map(self):
        report = fd_config.config_report(overrides={"effort_routing": {"orient": "medium", "implement": "high"}}, use_settings=False)
        self.assertEqual(report["effort"]["phase_map"], ["orient", "implement"])
        self.assertFalse(report["effort"]["constant_within_session"])
        self.assertTrue(any("prompt cache" in w for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
