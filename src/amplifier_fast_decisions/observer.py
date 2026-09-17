"""Optional native-event bridge; observes but never grants permission.

Also runs the shadow scorer (P3 in docs/design/redesign-2026-09-17.md):
watches provider:request / tool:pre / tool:post / provider:error /
execution:end to measure "what would we have chosen" without ever touching
the turn. The snapshot (context read, candidate collection, hashing) runs on
the caller's coroutine and is hard-bounded; only backend scoring is deferred
to Runtime's shadow worker. Every handler always returns "continue" and
never raises into the hook chain -- a bug in shadow measurement must never
affect a real turn.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from .candidates import collect_candidates
from .contracts import digest, field_value
from .router import RoleRouter
from .runtime import get_runtime
from .shadow import ShadowJob, ShadowOutcome
from .state import build_state

__amplifier_module_type__ = "hook"


def _continue_result() -> Any:
    """Duck-typed 'continue' result: the real amplifier_core HookResult when
    importable (real kernel), a plain stand-in otherwise (offline unit
    tests). Both expose `.action`, which is all any consumer in this
    codebase (or amplifier_core's own hook dispatch) checks."""
    try:
        from amplifier_core.models import HookResult

        return HookResult(action="continue")
    except ImportError:
        return SimpleNamespace(action="continue")


class ShadowScorer:
    """Off-critical-path 'what would we have chosen' measurement.

    Composes onto any orchestrator (including the untouched upstream loop):
    it reads state from the mounted context manager rather than from a
    request object, because provider:request carries no request
    (see docs/UPSTREAM_CONTRACT.md / design doc §0.3).
    """

    def __init__(self, runtime: Any, coordinator: Any, config: dict[str, Any]):
        self._runtime = runtime
        self._coordinator = coordinator
        policy = runtime.service.policy
        self._max_messages = config.get(
            "shadow_max_messages", policy.shadow_max_messages
        )
        self._budget_ms = config.get(
            "shadow_snapshot_budget_ms", policy.shadow_snapshot_budget_ms
        )
        self._state_source = config.get("shadow_state_source", "context_mount")
        self._turn_id: str | None = None

    async def on_provider_request(self, event: str, data: dict) -> Any:
        # No-op by design: upstream (loop-streaming) emits iteration 1's
        # provider:request BEFORE appending the turn's own user message to
        # the mounted context (amplifier_module_loop_streaming/__init__.py,
        # the "hoisted" provider:request block -- see
        # docs/UPSTREAM_CONTRACT.md and docs/design/redesign-2026-09-17.md
        # P3 postmortem). A snapshot taken here sees an empty/stale
        # ``context.get_messages()`` on that first iteration of every turn,
        # so no candidates are ever found and the real tool call that
        # follows is silently never scored. The snapshot instead happens in
        # ``on_tool_pre``, the earliest point at which the mounted context
        # is guaranteed (observed in a live DTU trace) to already include
        # this iteration's own user/assistant messages.
        return _continue_result()

    async def on_tool_pre(self, event: str, data: dict) -> Any:
        try:
            await self._propose_and_observe(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        return _continue_result()

    async def _propose_and_observe(self, data: dict) -> None:
        """Snapshot, propose, and immediately resolve against this same
        tool call -- all in one pass, now that ``on_tool_pre`` is the only
        point in the upstream loop where the mounted context is guaranteed
        to reflect this iteration's own messages (see ``on_provider_request``).
        The snapshot/candidate-collection step is bounded by the same
        ``shadow_snapshot_budget_ms`` as before; only backend scoring
        (``ShadowWorker._score``) remains deferred to the background task.
        """
        job = await self._snapshot()
        if job is None:
            return
        tool = data.get("tool_name") or data.get("tool")
        if not isinstance(tool, str):
            tool = field_value(tool, "name", None)
        arguments = data.get("tool_input")
        if arguments is None:
            arguments = data.get("arguments")
        arguments_hash = digest(arguments) if isinstance(arguments, dict) else None
        self._runtime.submit_shadow(job)
        await self._runtime.service.emit(
            "shadow_observed",
            {
                "tool": tool,
                "tool_call_id": data.get("tool_call_id"),
                "arguments_hash": arguments_hash,
            },
            job.decision_id,
        )
        self._runtime.resolve_shadow(
            ShadowOutcome(
                decision_id=job.decision_id,
                actual_tool=tool,
                actual_arguments_hash=arguments_hash,
            )
        )

    async def on_tool_post(self, event: str, data: dict) -> Any:
        return _continue_result()

    async def on_provider_error(self, event: str, data: dict) -> Any:
        return _continue_result()

    async def on_execution_end(self, event: str, data: dict) -> Any:
        self._turn_id = None
        try:
            self._runtime.shadow_worker.sweep_unobserved()
        except Exception:
            pass
        return _continue_result()

    async def _snapshot(self) -> ShadowJob | None:
        if self._state_source == "off":
            return None
        try:
            async with asyncio.timeout(self._budget_ms / 1000):
                return await self._build_job()
        except TimeoutError:
            await self._runtime.service.emit(
                "fallback", {"reason_code": "shadow_snapshot_budget_exceeded"}
            )
            return None

    async def _build_job(self) -> ShadowJob | None:
        getter = getattr(self._coordinator, "get", None)
        context = getter("context") if callable(getter) else None
        if context is None or not hasattr(context, "get_messages"):
            return None
        messages = list(await context.get_messages())
        messages = messages[-self._max_messages :] if self._max_messages > 0 else []
        tools = (getter("tools") if callable(getter) else None) or {}
        pseudo_request = SimpleNamespace(
            messages=messages, tools=None, tool_choice=None, model=None
        )
        service = self._runtime.service
        candidates, _reject_reasons = await collect_candidates(
            self._coordinator,
            pseudo_request,
            tools,
            service.configured_candidates,
            service.policy.max_candidates,
        )
        eligible = []
        for candidate in candidates:
            if await service._eligible(candidate, tools):
                eligible.append(candidate)
        eligible = eligible[: service.policy.max_candidates]
        if not eligible:
            return None
        state = build_state(pseudo_request, service.policy.max_state_chars)
        if self._turn_id is None:
            self._turn_id = uuid4().hex
        return ShadowJob(
            kind="turn",
            turn_id=self._turn_id,
            decision_id=uuid4().hex,
            state=state,
            candidates=tuple(eligible),
            questions=(),
            state_source="context_mount",
            state_hash=digest(state),
            state_revision=0,
        )


async def mount(coordinator, config: dict):
    from amplifier_core.models import HookResult

    # The hook has no execution authority: it can never own an "active"
    # policy. If its own config asks for one (only meaningful when no
    # orchestrator is mounted -- the normal shadow rung -- and this call is
    # therefore the one building the runtime), downgrade to shadow and
    # record why, rather than silently building an active Policy an
    # observer-only module has no business owning.
    effective_config = dict(config)
    hook_requested_active = effective_config.get("mode") == "active"
    if hook_requested_active:
        effective_config["mode"] = "shadow"
    runtime, owner = get_runtime(coordinator, effective_config)
    if hook_requested_active:
        await runtime.service.emit(
            "fallback", {"reason_code": "hook_cannot_own_active"}
        )
    registrations = []

    async def observe(event: str, data: dict):
        # Allowlisted structural fields only. Never copy native event bodies.
        tool = data.get("tool_name") or data.get("tool")
        if not isinstance(tool, str):
            tool = field_value(tool, "name", None)
        await runtime.service.emit(
            "health",
            {
                "native_event": event,
                "event_source": "native-hook-bridge",
                "tool": tool,
                "tool_call_id": data.get("tool_call_id"),
                "phase": data.get("phase"),
                "status": "observed",
            },
        )
        return HookResult(action="continue")

    for event in ("tool:pre", "tool:post", "provider:error"):
        registrations.append(coordinator.hooks.register(event, observe, priority=999))

    scorer = ShadowScorer(runtime, coordinator, config)
    for event, handler in (
        ("provider:request", scorer.on_provider_request),
        ("tool:pre", scorer.on_tool_pre),
        ("tool:post", scorer.on_tool_post),
        ("provider:error", scorer.on_provider_error),
        ("execution:end", scorer.on_execution_end),
    ):
        registrations.append(coordinator.hooks.register(event, handler, priority=999))

    # P4: the model-role router. Shadow-only -- never modifies the delegate
    # call. Cheap membership check per tool:pre/tool:post; the router itself
    # no-ops immediately when role_router is off (opt-out via config;
    # the shipped behaviors/fast-decisions.yaml default is on).
    router = RoleRouter(runtime, coordinator, config)

    async def on_role_pre(event: str, data: dict):
        tool = data.get("tool_name") or data.get("tool")
        if tool in router.tools:
            try:
                await router.on_delegate_pre(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        return _continue_result()

    async def on_role_post(event: str, data: dict):
        tool = data.get("tool_name") or data.get("tool")
        if tool in router.tools:
            try:
                router.on_delegate_post(data)
            except Exception:
                pass
        return _continue_result()

    registrations.append(
        coordinator.hooks.register("tool:pre", on_role_pre, priority=999)
    )
    registrations.append(
        coordinator.hooks.register("tool:post", on_role_post, priority=999)
    )

    async def cleanup():
        for unregister in registrations:
            if callable(unregister):
                unregister()
        if owner:
            await runtime.close()

    return cleanup
