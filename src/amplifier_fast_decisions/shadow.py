"""Off-critical-path shadow scoring: "what would we have chosen".

The snapshot (candidate/question collection, hashing) runs on the caller's
coroutine and is hard-bounded by the hook (see observer.py); only the
backend call that scores a snapshot happens here, on a single background
task owned by Runtime. Nothing here can change the turn: a scoring failure
is swallowed, never raised, and no result from this module denies, modifies
or injects anything into the hook chain.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from .contracts import (
    SLOW,
    Candidate,
    DecisionRequest,
    Question,
    canonical,
    classify_domain,
    digest,
)


@dataclass(frozen=True)
class ShadowJob:
    """One decision opportunity to score in the background.

    ``questions`` is reserved for the batched-judgment-question channel
    (contributed candidates today; typed ``Question`` objects land with the
    router in a later PR) -- always empty in this PR's ``kind="turn"`` jobs.
    """

    kind: Literal["turn", "role"]
    turn_id: str
    decision_id: str
    state: dict[str, Any]
    candidates: tuple[Candidate, ...]
    questions: tuple[Question, ...]
    state_source: Literal["context_mount", "provider_complete"]
    state_hash: str
    state_revision: int


@dataclass(frozen=True)
class ShadowOutcome:
    """What the LLM actually did, matched against what we proposed."""

    decision_id: str
    actual_tool: str | None
    actual_arguments_hash: str | None
    actual_model_role: str | None = None


@dataclass
class _Proposal:
    job: ShadowJob
    choice: str
    probabilities: dict[str, float]
    selected_probability: float
    margin: float
    duration_ms: float


class ShadowWorker:
    """Single background task: score jobs, join outcomes, emit results.

    ``submit`` and ``resolve`` are both non-blocking (bounded queue, drop and
    count on overflow) so neither the snapshot phase nor tool dispatch ever
    waits on this worker.
    """

    def __init__(self, service: Any, capacity: int = 64):
        self._service = service
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(
            maxsize=max(1, capacity)
        )
        self._proposals: dict[str, _Proposal] = {}
        self._pending_outcomes: dict[str, ShadowOutcome] = {}
        self.dropped_shadow_jobs = 0
        # Turn ids whose first shadow_proposed event has already carried
        # allow_external_state -- a per-turn context field, not repeated on
        # every decision within the same turn. Bounded defensively; turn
        # ids are never reused, so an extremely long-lived session is the
        # only way this grows without bound.
        self._turn_context_emitted: set[str] = set()

    def submit(self, job: ShadowJob) -> bool:
        """Non-blocking enqueue. False when the queue is full (counted)."""
        try:
            self._queue.put_nowait(("job", job))
            return True
        except asyncio.QueueFull:
            self.dropped_shadow_jobs += 1
            return False

    def resolve(self, outcome: ShadowOutcome) -> None:
        """Non-blocking enqueue of an observed outcome. Never raises."""
        try:
            self._queue.put_nowait(("outcome", outcome))
        except asyncio.QueueFull:
            self.dropped_shadow_jobs += 1

    @property
    def health(self) -> dict[str, int]:
        return {
            "dropped_shadow_jobs": self.dropped_shadow_jobs,
            "pending": self._queue.qsize(),
        }

    async def join(self) -> None:
        """Wait for the queue to drain. Used by Runtime.close's bounded drain."""
        await self._queue.join()

    async def run(self) -> None:
        while True:
            kind, item = await self._queue.get()
            try:
                if kind == "job":
                    await self._score(item)
                else:
                    await self._handle_outcome(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A scoring or joining failure is an observability defect,
                # never a reason to affect the turn or crash the worker.
                pass
            finally:
                self._queue.task_done()

    async def _score(self, job: ShadowJob) -> None:
        # Same privacy gate DecisionService.choose applies on the active path:
        # an external backend is never called for shadow scoring without the
        # explicit opt-in. This runs before any backend method is touched, so
        # an external backend's client (e.g. JevBackend's lazy AsyncTypeSafeClient)
        # is never constructed while the gate is closed.
        if (
            self._service.backend.external
            and not self._service.policy.allow_external_state
        ):
            await self._service.emit(
                "fallback",
                {"reason_code": "external_state_not_enabled"},
                job.decision_id,
            )
            return
        start = time.perf_counter()
        try:
            request = DecisionRequest(
                state=job.state, candidates=job.candidates, questions=job.questions
            )
            result = await self._service.backend.ask(request)
            result.action.validate({c.id for c in job.candidates} | {SLOW})
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        decision = result.action
        duration = (time.perf_counter() - start) * 1000
        p = decision.probabilities[decision.choice]
        others = [v for k, v in decision.probabilities.items() if k != decision.choice]
        margin = p - max(others, default=0)
        domain = classify_domain(
            job.candidates, kind="role" if job.kind == "role" else "action"
        )
        proposed_data = {
            "mode": "shadow",
            "backend": self._service.backend.name,
            "model": decision.model,
            "synthetic": result.synthetic,
            "choice": decision.choice,
            "probabilities": decision.probabilities,
            "probability_kind": decision.probability_kind,
            "reported_confidence": decision.reported_confidence,
            "confidence_kind": decision.confidence_kind,
            "option_set_hash": decision.option_set_hash,
            "selected_probability": p,
            "margin": margin,
            "duration_ms": duration,
            "state_source": job.state_source,
            "candidate_count": len(job.candidates),
            "domain": domain,
            "state_chars": len(canonical(job.state)),
        }
        if job.turn_id not in self._turn_context_emitted:
            if len(self._turn_context_emitted) >= 4096:
                self._turn_context_emitted.clear()
            self._turn_context_emitted.add(job.turn_id)
            proposed_data["allow_external_state"] = (
                self._service.policy.allow_external_state
            )
        await self._service.emit("shadow_proposed", proposed_data, job.decision_id)
        proposal = _Proposal(
            job, decision.choice, decision.probabilities, p, margin, duration
        )
        outcome = self._pending_outcomes.pop(job.decision_id, None)
        if outcome is not None:
            await self._emit_agreement(proposal, outcome)
        else:
            self._proposals[job.decision_id] = proposal

    async def _handle_outcome(self, outcome: ShadowOutcome) -> None:
        proposal = self._proposals.pop(outcome.decision_id, None)
        if proposal is None:
            self._pending_outcomes[outcome.decision_id] = outcome
            return
        await self._emit_agreement(proposal, outcome)

    async def _emit_agreement(
        self, proposal: _Proposal, outcome: ShadowOutcome
    ) -> None:
        if proposal.choice == SLOW:
            agreement = "abstained"
        elif outcome.actual_tool is None:
            agreement = "unobserved"
        else:
            candidate = next(
                (c for c in proposal.job.candidates if c.id == proposal.choice), None
            )
            matched = (
                candidate is not None
                and candidate.tool == outcome.actual_tool
                and digest(candidate.arguments) == outcome.actual_arguments_hash
            )
            agreement = "match" if matched else "mismatch"
        domain = classify_domain(
            proposal.job.candidates,
            kind="role" if proposal.job.kind == "role" else "action",
        )
        await self._service.emit(
            "shadow_agreement",
            {
                "agreement": agreement,
                "proposed_candidate": proposal.choice,
                "actual_tool": outcome.actual_tool,
                "would_have_avoided_llm_turn": agreement == "match",
                "domain": domain,
            },
            proposal.job.decision_id,
        )

    def sweep_unobserved(self) -> None:
        """Drop any proposals that never saw a matching outcome this turn.

        Called at execution:end -- a proposal with no tool call ever means
        the LLM did not act on anything comparable this turn, and holding it
        forever would leak memory across turns.
        """
        self._proposals.clear()
        self._pending_outcomes.clear()
