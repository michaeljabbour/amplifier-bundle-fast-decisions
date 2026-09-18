"""Phase-specific effort routing (HC03, opt-in).

Classifies the CURRENT turn's phase from ``request.messages`` and, when
enabled by the host's ``Policy.effort_routing``, lowers
``request.reasoning_effort`` for requests classified as ``explore`` --
deterministic, request-local, and never touching ``request.model`` or any
approval/permission decision. See docs/ARCHITECTURE.md and docs/EVENTS.md.

No amplifier-core or network imports; pure request-shape classification.
"""

from __future__ import annotations

from typing import Any

from .contracts import field_value

# Read-like tools never modify state; everything else -- including any tool
# name this module does not recognize -- is treated as write-like. This is
# deliberately conservative: an unknown tool must not be assumed safe to
# explore against.
READ_LIKE_TOOLS = frozenset(
    {
        "read_file",
        "fast_workspace",
        "glob",
        "grep",
        "list_dir",
        "ls",
        "search",
        "todo",
    }
)

ALLOWED_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

PHASE_ORIENT = "orient"
PHASE_EXPLORE = "explore"
PHASE_IMPLEMENT = "implement"

REASON_PHASE_POLICY = "phase_policy"
REASON_DEFAULT_EFFORT = "default_effort"
REASON_HOST_PINNED = "host_pinned"
REASON_ESCALATED_MAX_EXPLORE = "escalated_max_explore"
REASON_ESCALATED_AFTER_ERROR = "escalated_after_error"


def _tool_call_names(message: Any) -> list[str]:
    """Names of the tool calls attached to one assistant message, else []."""
    calls = field_value(message, "tool_calls")
    if not calls:
        return []
    names: list[str] = []
    for call in calls:
        name = field_value(call, "name")
        if not name:
            function = field_value(call, "function")
            name = field_value(function, "name") if function is not None else None
        if name:
            names.append(str(name))
    return names


def _is_write_like(tool_name: str) -> bool:
    return tool_name not in READ_LIKE_TOOLS


def classify_phase(request: Any) -> str:
    """Classify the CURRENT turn's phase from ``request.messages``.

    Only messages after the last ``user`` message belong to the current
    turn; anything at or before it (prior turns) is ignored. Never raises:
    a malformed message shape is simply skipped when reading its role or
    tool calls, which naturally biases the result toward the more
    conservative (write-like / implement) classification.

    - ``orient``: no assistant message yet in the current turn (this is
      the turn's first request).
    - ``explore``: at least one assistant message in the turn, no
      write-like tool call has occurred so far in the turn, and the most
      recent assistant message's tool calls (if any) are all read-like.
    - ``implement``: a write-like tool call has occurred anywhere in the
      turn (this also covers "verify" requests -- e.g. running tests via
      ``bash`` -- which are write-like and therefore fold into
      ``implement``, matching HC03's default-effort treatment for verify).
    """
    messages = field_value(request, "messages") or []
    last_user_index: int | None = None
    for i, message in enumerate(messages):
        if field_value(message, "role") == "user":
            last_user_index = i
    turn_messages = (
        messages[last_user_index + 1 :]
        if last_user_index is not None
        else list(messages)
    )

    assistant_messages = [
        m for m in turn_messages if field_value(m, "role") == "assistant"
    ]
    if not assistant_messages:
        return PHASE_ORIENT

    write_seen = False
    most_recent_tool_names: list[str] = []
    for message in assistant_messages:
        names = _tool_call_names(message)
        if names:
            most_recent_tool_names = names
        for name in names:
            if _is_write_like(name):
                write_seen = True

    if write_seen:
        return PHASE_IMPLEMENT
    if most_recent_tool_names and all(
        not _is_write_like(name) for name in most_recent_tool_names
    ):
        return PHASE_EXPLORE
    # Assistant activity exists but produced no tool calls at all (e.g. plain
    # text without acting yet) -- not a positive "read-like" signal, so this
    # does not qualify as explore. Conservative default: implement.
    return PHASE_IMPLEMENT


def decide_effort(
    phase: str,
    effort_routing: dict[str, Any],
    *,
    explore_requests: int,
    provider_errors_seen: int,
    host_pinned: bool,
) -> tuple[str | None, str]:
    """Decide whether to lower effort for this request.

    Returns ``(effort_or_None, reason_code)``. ``effort_or_None`` is the
    string to set on ``request.reasoning_effort``, or ``None`` when the
    request must be left untouched (provider-default / host-controlled
    effort stands). Callers must not invoke this when
    ``Policy.effort_routing`` is falsy -- routing-disabled is a distinct,
    event-free path handled by the caller, not represented here as a
    reason code.

    ``explore_requests`` is the 1-indexed count of explore-phase requests
    in this turn INCLUDING the current one (the caller increments before
    calling, for a ``phase == explore`` request only). It is only
    consulted when ``phase == explore``.
    """
    if phase != PHASE_EXPLORE:
        return None, REASON_DEFAULT_EFFORT
    if host_pinned:
        return None, REASON_HOST_PINNED
    escalate_after = effort_routing.get("escalate_after_provider_errors")
    if escalate_after is not None and provider_errors_seen >= escalate_after:
        return None, REASON_ESCALATED_AFTER_ERROR
    max_explore = effort_routing.get("max_explore_requests")
    if max_explore is not None and explore_requests > max_explore:
        return None, REASON_ESCALATED_MAX_EXPLORE
    effort = effort_routing.get("explore")
    if not effort:
        return None, REASON_DEFAULT_EFFORT
    return effort, REASON_PHASE_POLICY
