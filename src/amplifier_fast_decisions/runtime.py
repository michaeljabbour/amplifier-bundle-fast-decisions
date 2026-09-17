"""One decision service per session; no global provider mutations."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from .backends import JevBackend, UnavailableBackend
from .contracts import SERVICE_CAPABILITY, RUNTIME_CAPABILITY, EVENT_NAMES, Policy
from .service import DecisionService
from .telemetry import Emitter, JsonlRecorder


def session_identity(coordinator: Any) -> tuple[str, str | None]:
    session = getattr(coordinator, "session", None)
    session_id = getattr(coordinator, "session_id", None) or getattr(session, "session_id", None)
    parent = getattr(coordinator, "parent_id", None) or getattr(session, "parent_id", None)
    return str(session_id or uuid4().hex), str(parent) if parent else None


class Runtime:
    def __init__(self, service: DecisionService, recorder: JsonlRecorder | None = None):
        self.service = service
        self.recorder = recorder
        self.lock = asyncio.Lock()
        self.closed = False

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.service.emit("health", self.recorder.health if self.recorder else {})
            await self.service.close()
        finally:
            if self.recorder:
                await asyncio.to_thread(self.recorder.close)


def get_runtime(coordinator: Any, config: dict[str, Any], *, owner: bool = False) -> tuple[Runtime, bool]:
    existing = coordinator.get_capability(RUNTIME_CAPABILITY)
    if existing is not None:
        if not isinstance(existing, Runtime):
            raise TypeError("fast_decisions.runtime has an incompatible implementation")
        if owner:
            # The orchestrator is the sole owner of decision policy (mode,
            # thresholds, allowed_tools). Mount order across module types is
            # a kernel implementation detail, not a contract -- if a
            # non-owning module (e.g. the observer hook, which mounts with
            # config: {}) built the runtime first, its Policy must not stick.
            # Re-apply the owner's Policy now. Backend/telemetry remain the
            # one-per-session singleton regardless of who built them first.
            existing.service.policy = Policy.from_config(config)
        return existing, False
    policy = Policy.from_config(config)
    session_id, parent = session_identity(coordinator)
    events_dir = config.get("events_dir") or os.getenv("AFAST_EVENTS_DIR") or str(
        Path.home() / ".amplifier" / "fast-decisions" / "events")
    recorder = JsonlRecorder(events_dir, session_id)
    emitter = Emitter(session_id, parent_session_id=parent, hooks=coordinator.hooks, recorder=recorder)
    backend_name = config.get("backend", "jev")
    if backend_name not in {"jev", "unavailable"}:
        recorder.close()
        raise ValueError("Production backend must be jev or unavailable; scripted is demo-only")
    backend = JevBackend(model=config.get("model"), timeout_ms=policy.timeout_ms) if backend_name == "jev" else UnavailableBackend()
    service = DecisionService(policy, backend, emitter, coordinator, config.get("candidates"))
    runtime = Runtime(service, recorder)
    coordinator.register_capability(RUNTIME_CAPABILITY, runtime)
    coordinator.register_capability(SERVICE_CAPABILITY, service)
    if hasattr(coordinator, "register_contributor"):
        coordinator.register_contributor("observability.events", "fast-decisions", lambda: list(EVENT_NAMES))
    return runtime, True
