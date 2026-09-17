"""Trusted candidate collection. Never extract executable actions from model text."""
from __future__ import annotations
import inspect
import re
from typing import Any
from .contracts import Candidate, CANDIDATES_CAPABILITY, field_value
from .state import message_text


def capability(coordinator: Any, name: str) -> Any:
    if coordinator is None:
        return None
    return coordinator.get_capability(name)


async def maybe_await(value):
    return await value if inspect.isawaitable(value) else value


def parse_candidate(value: Any) -> Candidate:
    if isinstance(value, Candidate):
        # Deep-copy the mutable args at the trusted boundary.
        from .contracts import canonical
        import json
        return Candidate(**{**value.__dict__, "arguments": json.loads(canonical(value.arguments))})
    if not isinstance(value, dict):
        raise ValueError("Candidate must be a Candidate or dictionary")
    from .contracts import canonical
    import json
    return Candidate(**{**value, "arguments": json.loads(canonical(value.get("arguments", {})))})


async def collect_candidates(coordinator: Any, request: Any, tools: dict[str, Any],
                             configured: list[dict] | None = None) -> list[Candidate]:
    values: list[Any] = list(configured or [])
    supplier = capability(coordinator, CANDIDATES_CAPABILITY)
    if supplier is not None:
        values.extend(await maybe_await(supplier(request)) or [])
    # Optional native contribution channel. The channel is extensibility, NOT authority.
    collect = getattr(coordinator, "collect_contributions", None)
    if collect:
        contributions = await maybe_await(collect("fast_decisions.candidates"))
        if isinstance(contributions, dict):
            for contribution in contributions.values():
                if isinstance(contribution, list):
                    values.extend(contribution)
        elif isinstance(contributions, list):
            for contribution in contributions:
                if isinstance(contribution, list):
                    values.extend(contribution)
                elif isinstance(contribution, (Candidate, dict)):
                    values.append(contribution)

    workspace = tools.get("fast_workspace")
    if workspace and hasattr(workspace, "candidate_for_path"):
        messages = field_value(request, "messages", []) or []
        user = next((m for m in reversed(messages) if field_value(m, "role") == "user"), None)
        # Only explicitly named files; no guessed paths, shell commands, or recursive scan.
        pattern = r"(?<![\w/])(?:\./)?[\w./-]+\.(?:md|txt|py|js|ts|tsx|jsx|json|yaml|yml|toml|rs|html|css)\b"
        paths = list(dict.fromkeys(re.findall(pattern, message_text(user)))) if user else []
        for index, path in enumerate(paths[:12]):
            candidate = workspace.candidate_for_path(path, index)
            if candidate:
                values.append(candidate)
    parsed = [parse_candidate(x) for x in values]
    by_id: dict[str, Candidate] = {}
    for candidate in parsed:
        if candidate.id in by_id and by_id[candidate.id].fingerprint != candidate.fingerprint:
            raise ValueError("Conflicting candidate identifiers")
        by_id[candidate.id] = candidate
    return list(by_id.values())
