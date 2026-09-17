"""The fast router: model-role proposals, shadow-only (P4).

A second consumer of the same shadow measurement path, living in the same
hook, that at delegation time proposes a ``model_role`` and records it next
to what actually happened. It never mutates anything: ``modify`` is not
honored at ``tool:pre`` in the upstream loop today (see
docs/UPSTREAM_CONTRACT.md), so an "active" router through this seam is
structurally impossible -- shadow-only is not a staging choice, it is the
only honest option.

This module is an Amplifier-specific adapter (imports the coordinator's
duck-typed capability surface), not part of the harness-agnostic core.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from .contracts import classify_domain

# Owned by routing-matrix (or any other resolver bundle); read-only here.
ROLE_RESOLVER_CAPABILITY = "model_role_resolver"
# Named ONLY to document, and test, that this module never touches it.
PROVIDER_PIN_CAPABILITY = "conversation.provider_pin"
# Every event this module emits is a model-role decision, by construction --
# one call to the shared classifier, reused verbatim (contracts.classify_domain).
_ROLE_DOMAIN = classify_domain((), kind="role")


class RoleRouter:
    """Shadow-only proposer for ``model_role``. Composes onto the same
    ``Runtime`` the shadow scorer uses; never calls ``resolver.resolve`` on
    the ``tool:pre`` critical path.
    """

    def __init__(self, runtime: Any, coordinator: Any, config: dict[str, Any]):
        self._runtime = runtime
        self._coordinator = coordinator
        self._enabled = bool(config.get("role_router", False))
        self._probe_timeout_ms = config.get("role_probe_timeout_ms", 2000)
        self.tools: set[str] = set(config.get("role_router_tools", ("delegate",)))
        self._roles: tuple[str, ...] | None = None
        self._probe_lock = asyncio.Lock()
        self._pending: dict[str, str] = {}  # tool_call_id -> decision_id
        self._proposed: dict[str, str] = {}  # decision_id -> proposed role

    async def eligible_roles(self) -> tuple[str, ...]:
        """Live roles, probed once per session. Empty disables the router."""
        if self._roles is not None:
            return self._roles
        async with self._probe_lock:
            if self._roles is not None:
                return self._roles
            self._roles = await self._probe()
            return self._roles

    async def _probe(self) -> tuple[str, ...]:
        get_capability = getattr(self._coordinator, "get_capability", None)
        resolver = (
            get_capability(ROLE_RESOLVER_CAPABILITY)
            if callable(get_capability)
            else None
        )
        if resolver is None:
            await self._runtime.service.emit(
                "role_proposed",
                {"reason_code": "role_resolver_unavailable", "domain": _ROLE_DOMAIN},
            )
            return ()
        known_roles = getattr(resolver, "known_roles", None)
        # Optional metadata: absent means "cannot enumerate", NOT "no
        # resolver registered". Type-guard rather than trust it blindly --
        # a plain string is iterable-of-characters, not a sequence of roles.
        if not isinstance(known_roles, (list, tuple)) or not all(
            isinstance(r, str) for r in known_roles
        ):
            await self._runtime.service.emit(
                "role_proposed",
                {"reason_code": "role_resolver_unavailable", "domain": _ROLE_DOMAIN},
            )
            return ()
        live: list[str] = []
        try:
            async with asyncio.timeout(self._probe_timeout_ms / 1000):
                for role in known_roles:
                    try:
                        preferences = await resolver.resolve(role)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        continue
                    if preferences:
                        live.append(role)
        except TimeoutError:
            await self._runtime.service.emit(
                "role_proposed",
                {"reason_code": "role_resolver_unavailable", "domain": _ROLE_DOMAIN},
            )
            return ()
        if not live:
            await self._runtime.service.emit(
                "role_proposed",
                {"reason_code": "role_resolver_unavailable", "domain": _ROLE_DOMAIN},
            )
        return tuple(live)

    async def on_delegate_pre(self, data: dict) -> None:
        """Enqueue only; never awaits the resolver on this call."""
        if not self._enabled:
            return
        tool_input = data.get("tool_input")
        explicit_role = (
            tool_input.get("model_role") if isinstance(tool_input, dict) else None
        )
        if explicit_role:
            await self._runtime.service.emit(
                "role_proposed",
                {
                    "reason_code": "explicit_role_present",
                    "proposed_model_role": None,
                    "domain": _ROLE_DOMAIN,
                },
            )
            return
        tool_call_id = data.get("tool_call_id")
        decision_id = uuid4().hex
        if tool_call_id is not None:
            self._pending[tool_call_id] = decision_id
        # The probe/proposal runs off this call's critical path -- it is
        # never awaited here, matching the shadow worker's off-path scoring.
        asyncio.ensure_future(self._propose(decision_id))

    async def _propose(self, decision_id: str) -> None:
        try:
            roles = await self.eligible_roles()
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        if not roles:
            return
        proposed = roles[0]
        self._proposed[decision_id] = proposed
        await self._runtime.service.emit(
            "role_proposed",
            {
                "proposed_model_role": proposed,
                "eligible_roles": list(roles),
                "domain": _ROLE_DOMAIN,
            },
            decision_id,
        )

    def on_delegate_post(self, data: dict) -> None:
        """Resolve into a role_agreement record."""
        tool_call_id = data.get("tool_call_id")
        decision_id = (
            self._pending.pop(tool_call_id, None) if tool_call_id is not None else None
        )
        if decision_id is None:
            return
        proposed = self._proposed.pop(decision_id, None)
        routing = data.get("provider_routing")
        actual = routing.get("model_role") if isinstance(routing, dict) else None
        if proposed is None:
            agreement = "unobserved"
        else:
            agreement = "match" if proposed == actual else "mismatch"
        asyncio.ensure_future(
            self._runtime.service.emit(
                "role_agreement",
                {
                    "proposed_model_role": proposed,
                    "actual_model_role": actual,
                    "agreement": agreement,
                    "tool_call_id": tool_call_id,
                    "domain": _ROLE_DOMAIN,
                },
                decision_id,
            )
        )
