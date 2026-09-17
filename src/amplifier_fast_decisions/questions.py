"""Trusted collection of the batched judgment-question channel.

Mirrors candidates.py's shape and bounds (P5, docs/design/redesign-2026-09-17.md):
a contribution is extensibility, never authority, and one misbehaving
contributor must not disable the fast path for others. No Amplifier or
network imports -- the coordinator is used only through the two duck-typed
calls it actually needs (``collect_contributions``).
"""

from __future__ import annotations

from typing import Any

from .contracts import QUESTIONS_CHANNEL, InvalidCriteria, Question


async def maybe_await(value: Any) -> Any:
    import inspect

    return await value if inspect.isawaitable(value) else value


def parse_question(value: Any) -> Question:
    if isinstance(value, Question):
        return Question(**{**value.__dict__, "criteria": dict(value.criteria)})
    if not isinstance(value, dict):
        raise ValueError("Question must be a Question or dictionary")
    data = dict(value)
    data.setdefault("criteria", {})
    data["criteria"] = dict(data["criteria"])
    return Question(**data)


async def collect_questions(
    coordinator: Any, max_questions: int = 8
) -> tuple[list[Question], list[str]]:
    """Returns ``(questions, reject_reasons)``.

    ``reject_reasons`` is a flat list of reason codes (one per rejected item
    or dropped contributor group), counted -- never raised -- by the caller.
    """
    reasons: list[str] = []
    if max_questions <= 0:
        return [], reasons

    groups: list[list[Any] | None] = []
    collect = getattr(coordinator, "collect_contributions", None)
    if collect:
        contributions = await maybe_await(collect(QUESTIONS_CHANNEL)) or []
        if isinstance(contributions, dict):
            contributions = list(contributions.values())
        for contribution in contributions:
            if isinstance(contribution, list):
                groups.append(contribution)
            elif isinstance(contribution, (Question, dict)):
                groups.append([contribution])
            else:
                groups.append(None)

    by_name: dict[str, Question] = {}
    for group in groups:
        if group is None:
            reasons.append("contribution_shape_invalid")
            continue
        parsed: list[Question] = []
        for item in group:
            try:
                parsed.append(parse_question(item))
            except InvalidCriteria:
                reasons.append("question_criteria_invalid")
            except Exception:
                reasons.append("contribution_shape_invalid")
        local: dict[str, Question] = {}
        conflict = False
        for q in parsed:
            if q.name in local and local[q.name] != q:
                conflict = True
                break
            local[q.name] = q
        if conflict:
            reasons.append("contribution_conflict")
            continue
        if any(name in by_name and by_name[name] != q for name, q in local.items()):
            reasons.append("contribution_conflict")
            continue
        by_name.update(local)

    ordered = sorted(by_name.values(), key=lambda q: q.name)
    if len(ordered) > max_questions:
        reasons.append("contribution_truncated")
        ordered = ordered[:max_questions]
    return ordered, reasons
