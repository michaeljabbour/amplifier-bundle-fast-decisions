"""Rubric scoring over the Jev System One API.

Scores an ``(llm_input, llm_output)`` pair against a rubric of yes/no
questions, each answered by one Jev ``noul`` question in a single batched
request. The request and response shapes follow the widely used rubric-scorer
format, so existing rubric specs work unchanged::

    request:  {"scoring_spec": [{"question": str, "label"?: str, "weight"?: float}],
               "llm_input": str, "llm_output": str,
               "aggregation_method"?: "geometric_mean" | "arithmetic_mean" | "harmonic_mean"}
    response: {"total_score": float, "question_scores": {label: float}}

Any backend that answers ``noul`` questions works (hosted Jev, or a
Jev-compatible server configured on ``JevBackend``). Scores are the
backend's own values in [0, 1]; they are not calibrated probabilities of
correctness -- choose pass thresholds on your own labeled data.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any

from .contracts import DecisionRequest, Question

AGGREGATIONS = ("geometric_mean", "arithmetic_mean", "harmonic_mean")
DEFAULT_AGGREGATION = "geometric_mean"
# Jev's per-field limits; long inputs/outputs are truncated, never rejected.
MAX_FIELD_CHARS = 20000
MAX_QUESTIONS = 32
# Floor for geometric/harmonic means so a 0.0 score stays finite.
_EPS = 1e-6


@dataclass(frozen=True)
class RubricItem:
    question: str
    label: str
    weight: float = 1.0


def parse_spec(scoring_spec: Any) -> list[RubricItem]:
    """Validate a ``scoring_spec`` list into rubric items with unique labels."""
    if not isinstance(scoring_spec, list) or not 1 <= len(scoring_spec) <= MAX_QUESTIONS:
        raise ValueError(f"scoring_spec must be a list of 1..{MAX_QUESTIONS} questions")
    items: list[RubricItem] = []
    labels: set[str] = set()
    for index, raw in enumerate(scoring_spec):
        if not isinstance(raw, dict) or not isinstance(raw.get("question"), str) or not raw["question"].strip():
            raise ValueError(f"scoring_spec[{index}] needs a non-empty 'question'")
        label = raw.get("label") or raw["question"]
        if not isinstance(label, str):
            raise ValueError(f"scoring_spec[{index}].label must be a string")
        if label in labels:
            raise ValueError(f"duplicate rubric label: {label!r}")
        weight = raw.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not weight > 0:
            raise ValueError(f"scoring_spec[{index}].weight must be a positive number")
        labels.add(label)
        items.append(RubricItem(question=raw["question"].strip(), label=label, weight=float(weight)))
    return items


def aggregate(scores: list[float], weights: list[float], method: str = DEFAULT_AGGREGATION) -> float:
    """Weighted mean of per-question scores. Geometric (default) and harmonic
    means are increasingly sensitive to a single low score."""
    if method not in AGGREGATIONS:
        raise ValueError(f"aggregation_method must be one of {', '.join(AGGREGATIONS)}")
    total = sum(weights)
    if method == "arithmetic_mean":
        return sum(w * s for s, w in zip(scores, weights)) / total
    clamped = [min(1.0, max(_EPS, s)) for s in scores]
    if method == "geometric_mean":
        return math.exp(sum(w * math.log(s) for s, w in zip(clamped, weights)) / total)
    return total / sum(w / s for s, w in zip(clamped, weights))


def _question_name(index: int, label: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", label.lower()).strip("_")[:24] or "q"
    if not slug[0].isalpha():
        slug = "q_" + slug
    return f"{slug[:26]}_{index}"


async def score(backend: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Score one rubric request with ``backend`` (one batched call)."""
    items = parse_spec(request.get("scoring_spec"))
    method = request.get("aggregation_method") or DEFAULT_AGGREGATION
    if method not in AGGREGATIONS:
        raise ValueError(f"aggregation_method must be one of {', '.join(AGGREGATIONS)}")
    llm_input = str(request.get("llm_input") or "")[:MAX_FIELD_CHARS]
    llm_output = str(request.get("llm_output") or "")[:MAX_FIELD_CHARS]
    names = [_question_name(i, item.label) for i, item in enumerate(items)]
    questions = tuple(
        Question(name=name, type="noul", instructions=item.question[:512], origin="rubric")
        for name, item in zip(names, items)
    )
    started = time.perf_counter()
    result = await backend.ask(DecisionRequest(
        state={"llm_input": llm_input, "llm_output": llm_output},
        candidates=(),
        questions=questions,
    ))
    elapsed_ms = (time.perf_counter() - started) * 1000
    scores: dict[str, float] = {}
    for name, item in zip(names, items):
        answer = result.answers.get(name)
        value = getattr(answer, "noul", None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"backend returned no score for rubric question {item.label!r}")
        scores[item.label] = min(1.0, max(0.0, float(value)))
    total = aggregate([scores[i.label] for i in items], [i.weight for i in items], method)
    return {
        "total_score": round(total, 4),
        "question_scores": {label: round(value, 4) for label, value in scores.items()},
        "aggregation_method": method,
        "model": getattr(result, "model", None),
        "latency_ms": round(elapsed_ms, 1),
    }


async def score_many(backend: Any, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score a list of rubric requests in order; a failed item reports
    ``{"error": ...}`` instead of aborting the batch."""
    results = []
    for request in requests:
        try:
            results.append(await score(backend, request))
        except Exception as exc:  # noqa: BLE001 -- per-item, reported
            results.append({"error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    return results
