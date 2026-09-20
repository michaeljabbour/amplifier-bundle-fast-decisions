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

# HC05 ("judge-driven phase classification", opt-in): the criteria a judge
# Choice question uses when asked to classify the phase itself, instead of
# (or alongside, for agreement comparison) the deterministic classify_phase()
# below. Reused verbatim by orchestrator.py so the wording lives in one
# place. Order matches PHASE_ORIENT/PHASE_EXPLORE/PHASE_IMPLEMENT above.
PHASE_CRITERIA = {
    PHASE_ORIENT: "This is the turn's first request; no exploration or implementation has happened yet.",
    PHASE_EXPLORE: "Only read-like tool calls have happened so far this turn; still investigating, nothing written yet.",
    PHASE_IMPLEMENT: "A write-like tool call has occurred, or verification/tests are running -- the turn is executing changes.",
}

REASON_PHASE_POLICY = "phase_policy"
REASON_DEFAULT_EFFORT = "default_effort"
REASON_HOST_PINNED = "host_pinned"
REASON_ESCALATED_MAX_EXPLORE = "escalated_max_explore"
REASON_ESCALATED_AFTER_ERROR = "escalated_after_error"


def _content_blocks(message: Any) -> list[Any]:
    content = field_value(message, "content")
    return list(content) if isinstance(content, list) else []


def _tool_call_names(message: Any) -> list[str]:
    """Names of the tool calls attached to one assistant message, else [].

    Reads both a ``tool_calls`` field and ``tool_call`` content blocks
    (``amplifier_core.message_models.ToolCallBlock``), which is how the
    installed loop represents calls at the provider seam.
    """
    calls = list(field_value(message, "tool_calls") or [])
    calls += [
        block
        for block in _content_blocks(message)
        if field_value(block, "type") == "tool_call"
    ]
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


def _carries_tool_results(message: Any) -> bool:
    blocks = _content_blocks(message)
    return bool(blocks) and all(
        field_value(block, "type") == "tool_result" for block in blocks
    )


def _turn_boundary(messages: list[Any]) -> int | None:
    """Index of the user message that starts the CURRENT turn, or None.

    The installed loop injects hook reminders and steering text as extra
    ``user`` messages in the middle of a turn (observed live: roles
    ``U U A T T U A T ...``), and some providers carry tool results in
    user-role messages. A user message therefore starts a new turn only
    when it follows nothing, another turn-opening/system-style message, or
    an assistant message that finished WITHOUT tool calls. A user message
    that follows a ``tool`` message, a tool-result carrier, an assistant
    message with tool calls, or another mid-turn user message is a
    continuation of the same turn.
    """
    boundary: int | None = None
    continuation = False
    for i, message in enumerate(messages):
        role = field_value(message, "role")
        if role == "assistant":
            continuation = bool(_tool_call_names(message))
            continue
        if role in ("tool", "function") or (
            role == "user" and _carries_tool_results(message)
        ):
            continuation = True
            continue
        if role == "user":
            if not continuation:
                boundary = i
            continue
        # system/developer messages neither open nor continue a turn
    return boundary


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
    messages = list(field_value(request, "messages") or [])
    last_user_index = _turn_boundary(messages)
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
    consulted when ``phase == explore``. Any phase (orient/explore/implement)
    may be mapped to an effort level in ``effort_routing``; phases without a
    mapping keep the provider default.
    """
    effort = effort_routing.get(phase)
    if not effort:
        return None, REASON_DEFAULT_EFFORT
    if host_pinned:
        return None, REASON_HOST_PINNED
    escalate_after = effort_routing.get("escalate_after_provider_errors")
    if escalate_after is not None and provider_errors_seen >= escalate_after:
        return None, REASON_ESCALATED_AFTER_ERROR
    if phase == PHASE_EXPLORE:
        max_explore = effort_routing.get("max_explore_requests")
        if max_explore is not None and explore_requests > max_explore:
            return None, REASON_ESCALATED_MAX_EXPLORE
    return effort, REASON_PHASE_POLICY
