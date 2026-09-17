"""Small vendor-neutral contracts; no Amplifier or network imports."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

SERVICE_CAPABILITY = "fast_decisions.service"
RUNTIME_CAPABILITY = "fast_decisions.runtime"
CANDIDATES_CAPABILITY = "fast_decisions.candidates"
CANDIDATES_CHANNEL = "fast_decisions.candidates"
QUESTIONS_CHANNEL = "fast_decisions.questions"
VALIDATOR_CAPABILITY = "fast_decisions.validate_candidate"
SLOW = "reason"
NEXT_ACTION = "next_action"
QUESTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
EVENT_PREFIX = "fast_decisions:"
EVENT_NAMES = tuple(
    EVENT_PREFIX + n
    for n in (
        "turn_start",
        "turn_end",
        "requested",
        "scored",
        "routed",
        "fallback",
        "slow_start",
        "slow_end",
        "tool_start",
        "tool_end",
        "cancelled",
        "health",
        "shadow_proposed",
        "shadow_observed",
        "shadow_agreement",
        "role_proposed",
        "role_agreement",
        "observatory",
    )
)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def field_value(value: Any, name: str, fallback: Any = None) -> Any:
    return (
        value.get(name, fallback)
        if isinstance(value, dict)
        else getattr(value, name, fallback)
    )


def indexed(container: Any, name: str, fallback: Any = None) -> Any:
    """Subscript access (``container[name]``), falling back to attribute access.

    The verified Jev SDK shape is ``response.answers["next_action"]`` --
    subscriptable, not necessarily a plain dict. Falls back to attribute
    access so a dict-like *or* an attribute-bearing object both work.
    """
    if container is None:
        return fallback
    try:
        return container[name]
    except (TypeError, KeyError, IndexError):
        return getattr(container, name, fallback)


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Do not stringify arbitrary runtime objects (could expose secrets).
    return None


@dataclass(frozen=True)
class Candidate:
    """Prepared action, never a permission grant. Args are copied at the boundary."""

    id: str
    label: str
    tool: str
    arguments: dict[str, Any]
    rationale: str = "Prepared read-only action"
    origin: str = "trusted_config"
    revision: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", self.id) or self.id == SLOW:
            raise ValueError("Invalid or reserved candidate id")
        if not self.tool or not isinstance(self.arguments, dict):
            raise ValueError("Candidate requires a tool and an argument object")
        canonical(self.arguments)
        if len(canonical(self.arguments)) > 16384:
            raise ValueError("Candidate arguments exceed the 16 KiB limit")

    @property
    def fingerprint(self) -> str:
        return digest(
            {
                "id": self.id,
                "tool": self.tool,
                "args": self.arguments,
                "revision": self.revision,
            }
        )


def candidate_order_key(candidate: Candidate) -> tuple[str, str]:
    """Canonical stable sort key for serialisation: ``(origin, id)``."""
    return (candidate.origin, candidate.id)


DOMAIN_TOOL_CHOICE = "tool-choice"
DOMAIN_READ_TARGET = "read-target"
DOMAIN_MODEL_ROLE = "model-role"
DOMAINS = (DOMAIN_TOOL_CHOICE, DOMAIN_READ_TARGET, DOMAIN_MODEL_ROLE)


def classify_domain(candidates: Sequence[Candidate], *, kind: str = "action") -> str:
    """One pure classifier, reused everywhere a domain label is recorded
    (service.py's main decision path, shadow.py's off-critical-path
    scoring, router.py's model-role proposals, and bench's offline
    replay/suite reporting) so there is exactly one place this decision is
    made, at the point the candidate set is built:

    - ``kind="role"`` (a model-role router decision, which has no
      candidate set of its own) always classifies as ``"model-role"``.
    - Every candidate targeting ``fast_workspace`` (and at least one
      candidate present) classifies as ``"read-target"``.
    - Anything else -- mixed tools, non-workspace tools, or an empty
      candidate set -- classifies as ``"tool-choice"``.
    """
    if kind == "role":
        return DOMAIN_MODEL_ROLE
    if candidates and all(c.tool == "fast_workspace" for c in candidates):
        return DOMAIN_READ_TARGET
    return DOMAIN_TOOL_CHOICE


def compute_candidate_order_hash(
    candidates: list[Candidate] | tuple[Candidate, ...],
) -> str:
    """Deterministic hash of the canonical ``(origin, id)`` ordering.

    Computed once per request. Two runs over the same candidate set
    (regardless of collection/iteration order) produce the same hash.
    """
    ordered = sorted(candidates, key=candidate_order_key)
    return digest([[c.origin, c.id] for c in ordered])


QuestionType = Literal["choice", "score", "noul"]


class InvalidCriteria(ValueError):
    """A choice question's criteria count is outside the vendor's 2..255 bound."""


@dataclass(frozen=True)
class Question:
    """A bounded judgment question, evaluated in the same backend request as
    the action choice. ``type`` uses the vendor's own primitive names
    (``choice`` / ``score`` / ``noul``) so no translation table is needed.
    """

    name: str
    type: QuestionType
    instructions: str
    criteria: dict[str, str] = field(default_factory=dict)
    origin: str = "contributed"

    def __post_init__(self) -> None:
        if not QUESTION_NAME_RE.fullmatch(self.name) or self.name == NEXT_ACTION:
            raise ValueError("Invalid or reserved question name")
        if self.type not in ("choice", "score", "noul"):
            raise ValueError("Invalid question type")
        if not self.instructions or len(self.instructions) > 512:
            raise ValueError("instructions must be 1..512 chars")
        if self.type == "choice":
            if not 2 <= len(self.criteria) <= 255:
                raise InvalidCriteria("choice question needs 2..255 criteria")
        elif self.criteria:
            raise ValueError("criteria only valid for choice questions")


@dataclass(frozen=True)
class DecisionRequest:
    """One batched request per state: the action choice plus every
    contributed question, scored independently by the backend in a single
    call. ``questions`` never includes ``next_action`` -- the backend
    assembles that from ``candidates`` itself."""

    state: dict[str, Any]
    candidates: tuple[Candidate, ...]
    questions: tuple[Question, ...] = ()
    candidate_order_hash: str = ""


@dataclass(frozen=True)
class Answer:
    """One question's result. ``probabilities`` for choice/score,
    ``noul`` for noul questions."""

    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None
    noul: float | None = None


@dataclass(frozen=True)
class Decision:
    choice: str
    probabilities: dict[str, float]
    reported_confidence: float | None = None
    model: str = "unknown"
    input_tokens: int | None = None
    synthetic: bool = False

    def validate(self, choices: set[str]) -> None:
        if self.choice not in choices or set(self.probabilities) != choices:
            raise ValueError("Decision alternatives do not match the request")
        vals = list(self.probabilities.values())
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not 0 <= v <= 1
            for v in vals
        ):
            raise ValueError("Invalid probability")
        if not math.isclose(sum(vals), 1.0, abs_tol=0.025):
            raise ValueError("Probabilities do not sum to one")
        if self.probabilities[self.choice] + 1e-9 < max(vals):
            raise ValueError(
                "Selected choice is not the maximum-probability alternative"
            )
        if self.reported_confidence is not None and (
            not math.isfinite(self.reported_confidence)
            or not 0 <= self.reported_confidence <= 1
        ):
            raise ValueError("Invalid reported confidence")


@dataclass(frozen=True)
class DecisionResult:
    """The full batched response: the ``next_action`` choice plus every
    contributed question's answer, keyed by name."""

    action: Decision
    answers: dict[str, Answer] = field(default_factory=dict)
    model: str = "unknown"
    input_tokens: int | None = None
    output_tokens: int | None = None
    synthetic: bool = False


@dataclass(frozen=True)
class Policy:
    mode: Literal["off", "shadow", "active"] = "shadow"
    timeout_ms: int = 750
    min_probability: float = 0.90
    min_margin: float = 0.20
    max_fast_streak: int = 3
    max_fast_per_turn: int = 12
    max_candidates: int = 12
    max_questions: int = 8
    max_state_chars: int = 12000
    allow_external_state: bool = False
    allow_synthetic_active: bool = False
    allowed_tools: tuple[str, ...] = ("fast_workspace",)
    # Hard bounds for the shadow snapshot, which runs on the hook's critical
    # path (only backend scoring is deferred to the shadow worker). Exceeding
    # either is a normal, counted outcome (reason_code shadow_snapshot_budget_exceeded),
    # never an exception into the hook chain. See docs/design/redesign-2026-09-17.md P3.
    shadow_max_messages: int = 12
    shadow_snapshot_budget_ms: int = 25
    version: str = "policy-v1"

    def __post_init__(self) -> None:
        if self.mode not in {"off", "shadow", "active"}:
            raise ValueError("mode must be off, shadow, or active")
        if not 10 <= self.timeout_ms <= 60000:
            raise ValueError("timeout_ms must be between 10 and 60000")
        if not (0 <= self.min_probability <= 1 and 0 <= self.min_margin <= 1):
            raise ValueError("Invalid selection thresholds")
        if not 1 <= self.max_candidates <= 63:
            raise ValueError("max_candidates must be between 1 and 63")
        if min(self.max_fast_streak, self.max_fast_per_turn, self.max_candidates) < 1:
            raise ValueError("Decision limits must be positive")
        if not 0 <= self.max_questions <= 64:
            raise ValueError("max_questions must be between 0 and 64")
        if not 512 <= self.max_state_chars <= 100000:
            raise ValueError("max_state_chars must be between 512 and 100000")
        if not 1 <= self.shadow_max_messages <= 200:
            raise ValueError("shadow_max_messages must be between 1 and 200")
        if not 1 <= self.shadow_snapshot_budget_ms <= 5000:
            raise ValueError("shadow_snapshot_budget_ms must be between 1 and 5000")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Policy:
        names = cls.__dataclass_fields__
        values = {k: v for k, v in config.items() if k in names}
        if "allowed_tools" in values:
            values["allowed_tools"] = tuple(values["allowed_tools"])
        return cls(**values)


class DecisionBackend(Protocol):
    name: str
    external: bool

    async def ask(self, request: DecisionRequest) -> DecisionResult: ...
    async def close(self) -> None: ...


@dataclass
class TurnState:
    id: str
    used: set[str] = field(default_factory=set)
    fast_streak: int = 0
    fast_total: int = 0
    decision_count: int = 0
    revision: int = 0
    tool_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
