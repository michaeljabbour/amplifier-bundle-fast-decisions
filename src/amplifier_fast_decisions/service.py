"""Fast decisions propose prepared actions; the upstream loop still executes them."""
from __future__ import annotations
import asyncio
import time
from typing import Any
from uuid import uuid4

from .contracts import Candidate, Policy, TurnState, VALIDATOR_CAPABILITY, SLOW
from .candidates import capability, maybe_await, collect_candidates
from .state import automatic_tools, build_state, request_fingerprint, tool_names
from .telemetry import Emitter


class DecisionService:
    def __init__(self, policy: Policy, backend: Any, emitter: Emitter,
                 coordinator: Any = None, configured_candidates: list[dict] | None = None):
        self.policy = policy
        self.backend = backend
        self.emitter = emitter
        self.coordinator = coordinator
        self.configured_candidates = configured_candidates or []
        self.turn: TurnState | None = None
        self.last_decision_id: str | None = None
        self.slow_total = 0
        self.unhealthy_until = 0.0

    async def emit(self, kind: str, data: dict, decision_id: str | None = None):
        return await self.emitter.emit(kind, data, turn_id=self.turn.id if self.turn else None,
                                       decision_id=decision_id or self.last_decision_id)

    async def _eligible(self, candidate: Candidate, tools: dict[str, Any]) -> bool:
        if candidate.tool not in self.policy.allowed_tools or candidate.tool not in tools:
            return False
        tool = tools[candidate.tool]
        # The bundled workspace validates containment, exclusions and revision.
        local = getattr(tool, "validate_candidate", None)
        if candidate.tool == "fast_workspace":
            return bool(local and await maybe_await(local(candidate)))
        # Other tools need a separately installed trusted validator in addition
        # to allowlisting. Candidate origins or risk labels are NOT approval.
        validator = capability(self.coordinator, VALIDATOR_CAPABILITY)
        return bool(validator and await maybe_await(validator(candidate)))

    async def choose(self, request: Any, tools: dict[str, Any]) -> Candidate | None:
        if self.turn is None:
            raise RuntimeError("No active turn")
        turn = self.turn
        turn.decision_count += 1
        self.last_decision_id = uuid4().hex
        decision_id = self.last_decision_id
        common = {"mode": self.policy.mode, "backend": self.backend.name,
                  "policy_version": self.policy.version, "step": turn.decision_count,
                  "state_revision": turn.revision}

        async def slow(reason: str, **extra):
            await self.emit("routed", {**common, "route": "slow", "destination": "provider",
                            "reason_code": reason, **extra}, decision_id)
            return None

        if self.policy.mode == "off":
            return await slow("mode_off")
        if not automatic_tools(request) or not tool_names(request):
            return await slow("no_automatic_tool_boundary")
        if turn.fast_streak >= self.policy.max_fast_streak or turn.fast_total >= self.policy.max_fast_per_turn:
            return await slow("fast_path_budget")
        if time.monotonic() < self.unhealthy_until:
            return await slow("backend_circuit_open")
        if self.backend.external and not self.policy.allow_external_state:
            return await slow("external_state_not_enabled")
        deadline = asyncio.get_running_loop().time() + self.policy.timeout_ms / 1000
        revision = turn.revision
        snapshot_hash = request_fingerprint(request)
        try:
            async with asyncio.timeout_at(deadline):
                candidates = await collect_candidates(self.coordinator, request, tools, self.configured_candidates)
                mounted = tool_names(request)
                candidates = [c for c in candidates if c.tool in mounted and c.fingerprint not in turn.used]
                eligible = []
                for c in candidates:
                    if await self._eligible(c, tools):
                        eligible.append(c)
                candidates = eligible[:self.policy.max_candidates]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.emit("fallback", {**common, "reason_code": "candidate_source_error",
                                         "exception_type": type(exc).__name__}, decision_id)
            return await slow("candidate_source_error")
        if not candidates:
            return await slow("no_eligible_candidates")
        state = build_state(request, self.policy.max_state_chars)
        await self.emit("requested", {**common, "state_hash": snapshot_hash,
            "candidate_count": len(candidates),
            "candidates": [{"id": c.id, "label": c.label, "tool": c.tool} for c in candidates]}, decision_id)
        start = time.perf_counter()
        try:
            async with asyncio.timeout_at(deadline):
                decision = await self.backend.decide(state, candidates)
            decision.validate({c.id for c in candidates} | {SLOW})
        except asyncio.CancelledError:
            await self.emit("cancelled", {**common, "reason_code": "decision_cancelled"}, decision_id)
            raise
        except Exception as exc:
            reason = "decision_timeout" if isinstance(exc, TimeoutError) else "backend_error"
            self.unhealthy_until = time.monotonic() + 5.0
            await self.emit("fallback", {**common, "reason_code": reason,
                "duration_ms": (time.perf_counter() - start) * 1000,
                "exception_type": type(exc).__name__}, decision_id)
            return await slow(reason)
        duration = (time.perf_counter() - start) * 1000
        p = decision.probabilities[decision.choice]
        others = [v for k, v in decision.probabilities.items() if k != decision.choice]
        margin = p - max(others, default=0)
        result = {**common, "choice": decision.choice, "probabilities": decision.probabilities,
                  "selected_probability": p, "reported_confidence": decision.reported_confidence,
                  "margin": margin, "duration_ms": duration, "model": decision.model,
                  "input_tokens": decision.input_tokens, "synthetic": decision.synthetic,
                  "latency_kind": "decision_model_wall_time"}
        await self.emit("scored", result, decision_id)
        proposed = "fast" if decision.choice != SLOW else "slow"
        if self.policy.mode == "shadow":
            return await slow("shadow_only", proposed_route=proposed, shadow=True,
                              selected_candidate=decision.choice)
        if decision.synthetic and not self.policy.allow_synthetic_active:
            return await slow("synthetic_backend_not_authorized")
        if decision.choice == SLOW:
            return await slow("model_abstained")
        if p < self.policy.min_probability or margin < self.policy.min_margin:
            return await slow("selection_threshold", proposed_route=proposed)
        candidate = next(c for c in candidates if c.id == decision.choice)
        # Revalidate both conversation and prepared action immediately before submission.
        if request_fingerprint(request) != snapshot_hash or turn.revision != revision:
            return await slow("stale_state")
        try:
            async with asyncio.timeout_at(deadline):
                still_valid = await self._eligible(candidate, tools)
        except asyncio.CancelledError:
            raise
        except Exception:
            still_valid = False
        if not still_valid:
            return await slow("candidate_no_longer_eligible")
        if request_fingerprint(request) != snapshot_hash or turn.revision != revision:
            return await slow("stale_state")
        if asyncio.get_running_loop().time() >= deadline:
            return await slow("decision_deadline_exceeded")
        # Submission is committed by the provider facade only after a valid
        # Amplifier response envelope has been constructed.
        return candidate

    async def close(self):
        await self.backend.close()
