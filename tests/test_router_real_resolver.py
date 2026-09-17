"""Real-kernel-adjacent check: RoleRouter against the actual routing-matrix
MatrixModelRoleResolver, when that bundle is installed alongside this one.
Skipped otherwise -- this repo does not vendor or depend on routing-matrix.
"""

from __future__ import annotations

import importlib.util
import unittest

from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import Policy
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions.router import ROLE_RESOLVER_CAPABILITY, RoleRouter
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter

HAS_ROUTING_MATRIX = (
    importlib.util.find_spec("amplifier_module_hooks_routing") is not None
)


@unittest.skipUnless(HAS_ROUTING_MATRIX, "routing-matrix is not installed")
class RealResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_roles_and_resolve_shape(self):
        from amplifier_module_hooks_routing.resolver_class import (
            MatrixModelRoleResolver,
        )

        resolver = MatrixModelRoleResolver(
            matrix_roles={"fast": {}, "reasoning": {}},
            providers={},
            matrix_name="test-matrix",
        )
        self.assertIsInstance(resolver.known_roles, tuple)
        self.assertTrue(all(isinstance(r, str) for r in resolver.known_roles))

        coordinator = DemoCoordinator()
        coordinator.register_capability(ROLE_RESOLVER_CAPABILITY, resolver)
        events = []
        policy = Policy(mode="shadow")
        emitter = Emitter(coordinator.session_id, callback=events.append)
        service = DecisionService(
            policy, ScriptedBackend(delay_ms=0), emitter, coordinator, []
        )
        runtime = Runtime(service)
        router = RoleRouter(runtime, coordinator, {"role_router": True})
        # No installed provider matches an empty matrix -- resolve() returns
        # a list (possibly empty), never raises, matching the documented shape.
        roles = await router.eligible_roles()
        self.assertIsInstance(roles, tuple)


if __name__ == "__main__":
    unittest.main()
