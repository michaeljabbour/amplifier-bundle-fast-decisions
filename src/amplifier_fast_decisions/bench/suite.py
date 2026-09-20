"""Synthetic labelled decision suite: agreement/calibration against ground
truth, run offline (deterministic backend, hermetic, no network) or,
explicitly opted in, against the live Jev backend.

Harness-agnostic core -- no Amplifier or network imports here. The optional
live path imports ``.backends.JevBackend`` lazily, at call time, from the CLI
layer, never from this module (see cli.py).
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backends import BackendUnavailable
from ..contracts import SLOW, Candidate, Decision, DecisionRequest, DecisionResult


class ForbiddenLabelSource(ValueError):
    """A suite case declared ``label_source: "model"``.

    A model-derived label is never ground truth (P7 amendment (d)); the
    suite runner refuses to run at all rather than silently skip the case.
    """


@dataclass(frozen=True)
class SuiteCase:
    id: str
    domain: str
    state: dict[str, Any]
    candidates: tuple[Candidate, ...]
    expected_choice: str
    label_source: str
    tags: tuple[str, ...] = ()


def _candidate_from_json(entry: dict[str, Any]) -> Candidate:
    return Candidate(
        id=entry["id"],
        label=entry.get("label", entry["id"]),
        tool=entry.get("tool", "fast_workspace"),
        arguments=entry.get("arguments", {}),
        rationale=entry.get("rationale", "Suite candidate"),
        origin=entry.get("origin", "suite"),
    )


def load_suite(path: str | Path) -> list[SuiteCase]:
    """Parse a JSONL suite file. Raises ``ForbiddenLabelSource`` (before
    returning anything) if any case declares ``label_source: "model"``."""
    path = Path(path).expanduser()
    raw_lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    parsed = [json.loads(line) for line in raw_lines]
    for entry in parsed:
        if entry.get("label_source") == "model":
            raise ForbiddenLabelSource(
                f"Suite case {entry.get('id', '?')!r} declares label_source=model; "
                "a model-derived label is never ground truth."
            )
    cases = []
    for entry in parsed:
        cases.append(
            SuiteCase(
                id=entry["id"],
                domain=entry["domain"],
                state=entry.get("state", {}),
                candidates=tuple(_candidate_from_json(c) for c in entry["candidates"]),
                expected_choice=entry["expected_choice"],
                label_source=entry["label_source"],
                tags=tuple(entry.get("tags", ())),
            )
        )
    return cases


def _stable_unit(text: str) -> float:
    """Deterministic pseudo-random unit value in [0, 1) from a stable hash.
    Never uses Python's salted ``hash()``, which is not reproducible across
    processes/runs."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12)


class DeterministicSuiteBackend:
    """Fully offline, seeded, order-sensitive scorer.

    Not an accuracy claim about Jev -- a hermetic stand-in so the suite
    runner, permutation test, and metrics pipeline can be exercised in CI
    with no network. Order sensitivity is deliberate: independent research
    on the vendor found candidate order to be a real effect (P7 amendment
    (a)); this backend models that so the permutation test has something
    real to detect.
    """

    name = "deterministic"
    external = False

    async def ask(self, request: DecisionRequest) -> DecisionResult:
        candidates = list(request.candidates)
        n = len(candidates) or 1
        scores: dict[str, float] = {}
        for position, candidate in enumerate(candidates):
            base = _stable_unit(candidate.id)
            position_bias = (n - position) / n * 0.15
            scores[candidate.id] = base * 0.85 + position_bias
        # A small, deterministic abstention weight so suites can exercise
        # the "reason" alternative without it always winning or never
        # appearing.
        scores[SLOW] = 0.1 + 0.05 * _stable_unit(request.state.get("_case_id", ""))
        total = sum(scores.values()) or 1.0
        probabilities = {k: v / total for k, v in scores.items()}
        choice = max(probabilities, key=probabilities.get)  # type: ignore[arg-type]
        action = Decision(
            choice=choice,
            probabilities=probabilities,
            reported_confidence=probabilities[choice],
            model="deterministic-suite-backend",
            input_tokens=0,
            synthetic=True,
        )
        return DecisionResult(
            action=action,
            answers={},
            model="deterministic-suite-backend",
            input_tokens=0,
            output_tokens=0,
            synthetic=True,
        )

    async def close(self) -> None:
        return None


@dataclass
class SuiteItemResult:
    case: SuiteCase
    canonical_choice: str
    canonical_probability: float
    reported_confidence: float | None
    input_tokens: int | None
    correct: bool
    permutation_choices: list[str] = field(default_factory=list)
    permutation_probabilities: list[float] = field(default_factory=list)


@dataclass
class SuiteResult:
    items: list[SuiteItemResult]
    order_agreement_stability: float | None
    max_probability_swing: float | None
    permutations: int
    # Per-case ``TimeoutError``/``BackendUnavailable`` outcomes (canonical or
    # permutation calls) counted as abstentions rather than aborting the
    # whole suite -- e.g. a backend cold-reloading mid-run. Never includes
    # cases that scored normally.
    errors: int = 0


def _permuted_candidates(
    candidates: Sequence[Candidate], case_id: str, k: int
) -> tuple[Candidate, ...]:
    if k == 0:
        return tuple(candidates)
    ordered = list(candidates)
    random.Random(f"{case_id}:{k}").shuffle(ordered)
    return tuple(ordered)


async def run_suite(
    cases: Sequence[SuiteCase],
    backend: Any,
    *,
    permutations: int = 4,
) -> SuiteResult:
    """Score every case under ``permutations`` candidate orderings (k=1
    disables the permutation test). Canonical (k=0, as-declared order)
    results feed accuracy/calibration; k>=1 orderings feed only the
    stability/swing diagnostic.

    A per-case ``TimeoutError`` or ``BackendUnavailable`` (e.g. a backend
    cold-reloading mid-run) is counted in ``SuiteResult.errors`` and treated
    as an abstention for that call -- it never aborts the rest of the
    suite. A canonical-call error drops the case entirely (no ground truth
    to score against); a permutation-call error only drops that one
    ordering from the stability/swing diagnostic.
    """
    k = max(1, permutations)
    items: list[SuiteItemResult] = []
    stable_count = 0
    swings: list[float] = []
    errors = 0
    for case in cases:
        state = dict(case.state)
        state["_case_id"] = case.id
        canonical_request = DecisionRequest(state=state, candidates=case.candidates)
        try:
            canonical_result = await backend.ask(canonical_request)
        except (TimeoutError, BackendUnavailable):
            errors += 1
            continue
        canonical_action = canonical_result.action
        canonical_p = canonical_action.probabilities[canonical_action.choice]
        item = SuiteItemResult(
            case=case,
            canonical_choice=canonical_action.choice,
            canonical_probability=canonical_p,
            reported_confidence=canonical_action.reported_confidence,
            input_tokens=canonical_result.input_tokens,
            correct=canonical_action.choice == case.expected_choice,
        )
        choices = [canonical_action.choice]
        chosen_probs = [canonical_p]
        for perm_index in range(1, k):
            ordered = _permuted_candidates(case.candidates, case.id, perm_index)
            try:
                result = await backend.ask(DecisionRequest(state=state, candidates=ordered))
            except (TimeoutError, BackendUnavailable):
                errors += 1
                continue
            choices.append(result.action.choice)
            # Probability of *this run's own* chosen option, for the swing
            # metric ("max - min probability of the chosen option across k").
            chosen_probs.append(result.action.probabilities[result.action.choice])
        item.permutation_choices = choices
        item.permutation_probabilities = chosen_probs
        items.append(item)
        if len(set(choices)) == 1:
            stable_count += 1
        if len(chosen_probs) > 1:
            swings.append(max(chosen_probs) - min(chosen_probs))
    n = len(items) or 1
    order_agreement_stability = stable_count / n if k > 1 else 1.0
    max_probability_swing = max(swings) if swings else 0.0
    return SuiteResult(
        items=items,
        order_agreement_stability=order_agreement_stability,
        max_probability_swing=max_probability_swing,
        permutations=k,
        errors=errors,
    )
