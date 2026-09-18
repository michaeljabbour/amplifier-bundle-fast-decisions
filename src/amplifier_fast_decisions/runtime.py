"""One decision service per session; no global provider mutations."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from .backends import JevBackend, ScriptedBackend, UnavailableBackend
from .contracts import SERVICE_CAPABILITY, RUNTIME_CAPABILITY, EVENT_NAMES, Policy
from .service import DecisionService
from .shadow import ShadowJob, ShadowOutcome, ShadowWorker
from .telemetry import Emitter, JsonlRecorder


def session_identity(coordinator: Any) -> tuple[str, str | None]:
    session = getattr(coordinator, "session", None)
    session_id = getattr(coordinator, "session_id", None) or getattr(session, "session_id", None)
    parent = getattr(coordinator, "parent_id", None) or getattr(session, "parent_id", None)
    return str(session_id or uuid4().hex), str(parent) if parent else None


class Runtime:
    def __init__(self, service: DecisionService, recorder: JsonlRecorder | None = None, *,
                 shadow_capacity: int = 64, shadow_drain_ms: int = 2000):
        self.service = service
        self.recorder = recorder
        self.lock = asyncio.Lock()
        self.closed = False
        self.shadow_worker = ShadowWorker(service, shadow_capacity)
        self.shadow_drain_ms = shadow_drain_ms
        self._shadow_task: asyncio.Task | None = None

    def start_shadow_worker(self) -> None:
        """Idempotent. The runtime's creator owns this task (mirrors runtime
        lifecycle ownership: whichever module builds the Runtime also closes
        it -- see get_runtime's owner semantics below).

        Runtime/get_runtime can be constructed outside a running event loop
        (e.g. a synchronous test wiring a fake runtime via get_runtime), so
        this silently no-ops rather than raising when there is no loop to
        schedule onto; submit_shadow/resolve_shadow call this again lazily,
        and by the time either fires on the real hook path a loop is always
        running."""
        if self._shadow_task is not None and not self._shadow_task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._shadow_task = None
            return
        self._shadow_task = asyncio.create_task(self.shadow_worker.run())

    def submit_shadow(self, job: ShadowJob) -> bool:
        """Non-blocking enqueue. False when the queue is full (counted as dropped_shadow_jobs)."""
        self.start_shadow_worker()
        return self.shadow_worker.submit(job)

    def resolve_shadow(self, outcome: ShadowOutcome) -> None:
        """Non-blocking. Records what the LLM actually did against a pending proposal."""
        self.start_shadow_worker()
        self.shadow_worker.resolve(outcome)

    async def close(self):
        """Idempotent. Drains the shadow worker with a bounded budget, then
        cancels the task and awaits it, so no shadow work outlives the
        session and no task is left pending at interpreter exit."""
        if self.closed:
            return
        self.closed = True
        try:
            await self.service.emit("health", {
                **(self.recorder.health if self.recorder else {}),
                **self.shadow_worker.health,
            })
            if self._shadow_task is not None:
                try:
                    await asyncio.wait_for(self.shadow_worker.join(), timeout=self.shadow_drain_ms / 1000)
                except TimeoutError:
                    pass
                self._shadow_task.cancel()
                try:
                    await self._shadow_task
                except asyncio.CancelledError:
                    pass
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
            # thresholds, allowed_tools). Mount order across module types IS
            # a documented, guaranteed kernel contract (@core:CONTRACTS.md
            # Module Lifecycle; amplifier_core's _session_init.py loads
            # orchestrator (:74) before context (:104), providers (:154),
            # tools (:222) and hooks (:248)) -- within a session the
            # orchestrator always builds the runtime before the hook mounts,
            # so no race exists to solve here. This re-apply is defensive,
            # not a race resolution: it protects out-of-session construction
            # paths (unit tests, `afast demo`, a future non-kernel host)
            # where a non-owning module (e.g. the observer hook, which
            # mounts with config: {}) might build the runtime first. Backend/
            # telemetry remain the one-per-session singleton regardless of
            # who built them first.
            existing.service.policy = Policy.from_config(config)
        return existing, False
    policy = Policy.from_config(config)
    session_id, parent = session_identity(coordinator)
    events_dir = config.get("events_dir") or os.getenv("AFAST_EVENTS_DIR") or str(
        Path.home() / ".amplifier" / "fast-decisions" / "events")
    recorder = JsonlRecorder(events_dir, session_id)
    emitter = Emitter(session_id, parent_session_id=parent, hooks=coordinator.hooks, recorder=recorder)
    backend_name = config.get("backend", "jev")
    if backend_name not in {"jev", "unavailable", "deterministic", "ollama"}:
        recorder.close()
        raise ValueError(
            "Backend must be jev, deterministic, ollama, or unavailable"
        )
    if backend_name == "jev":
        backend = JevBackend(model=config.get("model"), timeout_ms=policy.timeout_ms)
    elif backend_name == "ollama":
        from .local_backend import OllamaBackend

        try:
            backend = OllamaBackend(
                model=config.get("model", "qwen3:0.6b"),
                url=config.get("ollama_url", "http://127.0.0.1:11434"),
                timeout_ms=policy.timeout_ms,
            )
        except Exception:
            recorder.close()
            raise
    elif backend_name == "deterministic":
        # In-process, offline scorer (external=False, never gated by
        # allow_external_state): the "shadow, external=false" rung on the
        # design's rung ladder (docs/design/redesign-2026-09-17.md P3
        # decision 5). Explicitly opted into via config -- not a silent
        # substitution for jev.
        backend = ScriptedBackend()
    else:
        backend = UnavailableBackend()
    service = DecisionService(policy, backend, emitter, coordinator, config.get("candidates"))
    runtime = Runtime(service, recorder, shadow_capacity=config.get("shadow_capacity", 64),
                       shadow_drain_ms=config.get("shadow_drain_ms", 2000))
    # The runtime's creator (whichever module calls get_runtime first this
    # session) owns the shadow worker's lifecycle: it starts the task here
    # and drains/cancels it in Runtime.close, which the same module's
    # cleanup calls (observer.py/orchestrator.py both do this today).
    runtime.start_shadow_worker()
    coordinator.register_capability(RUNTIME_CAPABILITY, runtime)
    coordinator.register_capability(SERVICE_CAPABILITY, service)
    if hasattr(coordinator, "register_contributor"):
        coordinator.register_contributor("observability.events", "fast-decisions", lambda: list(EVENT_NAMES))
    return runtime, True
