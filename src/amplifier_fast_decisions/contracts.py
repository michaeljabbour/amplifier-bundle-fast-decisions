"""Small vendor-neutral contracts; no Amplifier or network imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
import hashlib
import json
import math
import re

SERVICE_CAPABILITY = "fast_decisions.service"
RUNTIME_CAPABILITY = "fast_decisions.runtime"
CANDIDATES_CAPABILITY = "fast_decisions.candidates"
VALIDATOR_CAPABILITY = "fast_decisions.validate_candidate"
SLOW = "reason"
EVENT_PREFIX = "fast_decisions:"
EVENT_NAMES = tuple(EVENT_PREFIX + n for n in (
    "turn_start", "turn_end", "requested", "scored", "routed", "fallback",
    "slow_start", "slow_end", "tool_start", "tool_end", "cancelled", "health",
))


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def field_value(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


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
        return digest({"id": self.id, "tool": self.tool, "args": self.arguments, "revision": self.revision})


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
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               or not 0 <= v <= 1 for v in vals):
            raise ValueError("Invalid probability")
        if not math.isclose(sum(vals), 1.0, abs_tol=0.025):
            raise ValueError("Probabilities do not sum to one")
        if self.probabilities[self.choice] + 1e-9 < max(vals):
            raise ValueError("Selected choice is not the maximum-probability alternative")
        if self.reported_confidence is not None and (
            not math.isfinite(self.reported_confidence) or not 0 <= self.reported_confidence <= 1
        ):
            raise ValueError("Invalid reported confidence")


@dataclass(frozen=True)
class Policy:
    mode: Literal["off", "shadow", "active"] = "shadow"
    timeout_ms: int = 750
    min_probability: float = 0.90
    min_margin: float = 0.20
    max_fast_streak: int = 3
    max_fast_per_turn: int = 12
    max_candidates: int = 12
    max_state_chars: int = 12000
    allow_external_state: bool = False
    allow_synthetic_active: bool = False
    allowed_tools: tuple[str, ...] = ("fast_workspace",)
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
        if not 512 <= self.max_state_chars <= 100000:
            raise ValueError("max_state_chars must be between 512 and 100000")

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
    async def decide(self, state: dict[str, Any], candidates: list[Candidate]) -> Decision: ...
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
