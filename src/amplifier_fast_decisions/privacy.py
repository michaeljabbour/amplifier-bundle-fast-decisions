"""Best-effort text scrubbing plus strict metadata-only telemetry projection.

Scrubbing is NOT a DLP guarantee. External state transmission is separately opt-in.
"""

from __future__ import annotations

import math
import re
from typing import Any

_SECRET = re.compile(
    r"(?i)(api[_-]?key|authorization|password|passwd|secret|access[_-]?token|refresh[_-]?token)"
    r"([\s\"':=]+)([^\s,;\"'}]{4,})"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_KEYS = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,}|AKIA[A-Z0-9]{16})\b"
)
_PEM = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL
)

# No prompt, arguments, outputs, arbitrary errors, or model thinking in event data.
SAFE_FIELDS = {
    "mode",
    "backend",
    "model",
    "provider",
    "destination",
    "route",
    "proposed_route",
    "reason_code",
    "policy_version",
    "state_hash",
    "candidate_count",
    "candidates",
    "choice",
    "probabilities",
    "probability_kind",
    "reported_confidence",
    "confidence_kind",
    "option_set_hash",
    "selected_probability",
    "margin",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tool",
    "tool_call_id",
    "status",
    "success",
    "exception_type",
    "retry_attempt",
    "status_code",
    "fast_total",
    "slow_total",
    "shadow",
    "synthetic",
    "dropped_events",
    "recording_error",
    "queue_depth",
    "step",
    "engine",
    "transport",
    "transport_measured",
    "event_source",
    "native_event",
    "latency_kind",
    "selected_candidate",
    "message_count",
    "result_bytes",
    "hook_ms",
    "event_count",
    "phase",
    "session_label",
    "warmup",
    "state_revision",
    "candidate_revision",
    "upstream_complete_calls",
    "output_path_redacted",
    # Shadow (P3): the proposal/observation join and worker health, never
    # arguments/outputs/raw state.
    "agreement",
    "proposed_candidate",
    "actual_tool",
    "would_have_avoided_llm_turn",
    "state_source",
    "arguments_hash",
    "dropped_shadow_jobs",
    "pending",
    "proposed_model_role",
    "actual_model_role",
    "eligible_roles",
    # Channels/router (P4/P5): canonical ordering, question volume, reason
    # codes for rejected contributions -- never the contributions themselves.
    "candidate_order_hash",
    "question_count",
    # Bench measurement fields (PR D amendment): small, privacy-safe
    # scalars only -- an integer length, a fixed label, a boolean -- never
    # the state text itself. See docs/BENCH.md and contracts.classify_domain.
    "state_chars",
    "domain",
    "allow_external_state",
    # Auto-observatory (session-start viewer bootstrap): a fixed action label,
    # a fixed reason code, and the local loopback port -- never the
    # token-bearing URL, which is never placed in event data.
    "action",
    "reason",
    "port",
}


def scrub(text: str, limit: int = 4000) -> str:
    text = _PEM.sub("[REDACTED PRIVATE KEY]", str(text))
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _KEYS.sub("[REDACTED KEY]", text)
    text = _SECRET.sub(lambda m: m[1] + m[2] + "[REDACTED]", text)
    return text[:limit]


def safe_data(data: dict[str, Any]) -> dict[str, Any]:
    def clean(v: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "[depth limit]"
        if isinstance(v, str):
            return scrub(v, 512)
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if v is None or isinstance(v, (bool, int, float)):
            return v
        if isinstance(v, dict):
            return {
                scrub(str(k), 80): clean(x, depth + 1) for k, x in list(v.items())[:64]
            }
        if isinstance(v, (list, tuple)):
            return [clean(x, depth + 1) for x in v[:64]]
        return None

    return {k: clean(v) for k, v in data.items() if k in SAFE_FIELDS}
