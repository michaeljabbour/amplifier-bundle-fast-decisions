"""Unit tests for the shadow-only model-role router (P4, docs/design/redesign-2026-09-17.md).

All offline; no real kernel, no network. RoleRouter.eligible_roles is called
directly in most tests to make the router's probing/caching deterministic
and synchronous to assert on; on_delegate_pre/on_delegate_post are exercised
separately for the fire-and-forget hook wiring.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import Policy
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions.router import (
    PROVIDER_PIN_CAPABILITY,
    ROLE_RESOLVER_CAPABILITY,
    RoleRouter,
)
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter


def make_runtime(events):
    coordinator = DemoCoordinator()
    policy = Policy(mode="shadow")
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(
        policy, ScriptedBackend(delay_ms=0), emitter, coordinator, []
    )
    return Runtime(service), coordinator


class RoleRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_role_abstains(self):
        events = []
        runtime, coordinator = make_runtime(events)
        router = RoleRouter(runtime, coordinator, {"role_router": True})
        await router.on_delegate_pre(
            {"tool_input": {"model_role": "coding"}, "tool_call_id": "1"}
        )
        self.assertNotIn("1", router._pending)
        proposals = [e for e in events if e["event"].endswith("role_proposed")]
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["data"]["reason_code"], "explicit_role_present")

    async def test_absent_resolver_disables_router(self):
        events = []
        runtime, coordinator = make_runtime(events)
        router = RoleRouter(runtime, coordinator, {"role_router": True})
        roles = await router.eligible_roles()
        self.assertEqual(roles, ())
        proposals = [e for e in events if e["event"].endswith("role_proposed")]
        self.assertEqual(
            sum(
                1
                for e in proposals
                if e["data"].get("reason_code") == "role_resolver_unavailable"
            ),
            1,
        )
        # No further probes: the cached () is returned without touching the
        # capability lookup a second time.
        coordinator.capabilities.pop(ROLE_RESOLVER_CAPABILITY, None)
        called = []
        original_get = coordinator.get_capability

        def spy(name):
            called.append(name)
            return original_get(name)

        coordinator.get_capability = spy
        roles_again = await router.eligible_roles()
        self.assertEqual(roles_again, ())
        self.assertEqual(called, [])

    async def test_known_roles_type_guarded(self):
        events = []
        runtime, coordinator = make_runtime(events)
        coordinator.register_capability(
            ROLE_RESOLVER_CAPABILITY, NS(known_roles="coding", resolve=None)
        )
        router = RoleRouter(runtime, coordinator, {"role_router": True})
        roles = await router.eligible_roles()
        self.assertEqual(roles, ())

    async def test_dead_roles_excluded(self):
        events = []
        runtime, coordinator = make_runtime(events)

        async def resolve(role):
            return [] if role == "dead" else [NS(provider="p", model="m", config={})]

        coordinator.register_capability(
            ROLE_RESOLVER_CAPABILITY, NS(known_roles=("dead", "fast"), resolve=resolve)
        )
        router = RoleRouter(runtime, coordinator, {"role_router": True})
        roles = await router.eligible_roles()
        self.assertEqual(roles, ("fast",))

    async def test_never_touches_provider_pin(self):
        events = []
        runtime, coordinator = make_runtime(events)

        async def resolve(role):
            return [NS(provider="p", model="m", config={})]

        coordinator.register_capability(
            ROLE_RESOLVER_CAPABILITY, NS(known_roles=("fast",), resolve=resolve)
        )
        original_get = coordinator.get_capability

        def guarded(name):
            if name == PROVIDER_PIN_CAPABILITY:
                raise AssertionError("must never read conversation.provider_pin")
            return original_get(name)

        coordinator.get_capability = guarded
        router = RoleRouter(runtime, coordinator, {"role_router": True})
        roles = await router.eligible_roles()
        self.assertEqual(roles, ("fast",))

    async def test_tool_pre_returns_immediately(self):
        events = []
        runtime, coordinator = make_runtime(events)
        hung = asyncio.Event()

        async def resolve(role):
            await hung.wait()
            return [NS(provider="p", model="m", config={})]

        coordinator.register_capability(
            ROLE_RESOLVER_CAPABILITY, NS(known_roles=("fast",), resolve=resolve)
        )
        router = RoleRouter(
            runtime, coordinator, {"role_router": True, "role_probe_timeout_ms": 50}
        )
        await asyncio.wait_for(
            router.on_delegate_pre({"tool_input": {}, "tool_call_id": "1"}),
            timeout=0.05,
        )
        # on_delegate_pre completed without waiting on resolve(); let the
        # background probe time out on its own so no task is left dangling.
        await asyncio.sleep(0.1)

    async def test_disabled_when_role_router_off(self):
        events = []
        runtime, coordinator = make_runtime(events)
        router = RoleRouter(runtime, coordinator, {"role_router": False})
        await router.on_delegate_pre({"tool_input": {}, "tool_call_id": "1"})
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
