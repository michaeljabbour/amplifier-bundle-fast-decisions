"""Offline replay over recorded ``fast_decisions:*`` JSONL telemetry.

Zero network, zero LLM. Joins ``requested`` -> ``scored`` -> ``routed`` ->
``shadow_agreement`` / ``role_agreement`` by ``decision_id``. Harness-agnostic
core -- no Amplifier or network imports.

``requested`` and ``shadow_proposed`` events carry an explicit ``state_chars``
field (the length of the serialised state actually sent -- never the state
text itself), and ``requested``/``scored``/``routed``/``shadow_*``/``role_*``
events carry an explicit ``domain`` field, both decided once at the point
the candidate set is built (``contracts.classify_domain``). This replay
prefers those explicit fields. For legacy recordings made before this
bundle emitted them, ``state_chars_p50/p95``/``state_size_vs_latency``
report ``n=0``/``None`` rather than fabricating a size proxy, and
``domain`` falls back to a documented heuristic, labelled ``inferred`` in
the per-domain breakdown (``per_domain[domain]["n_inferred"]``). See
docs/BENCH.md.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import SLOW, Candidate, DecisionRequest
from . import metrics as m

EVENT_PREFIX = "fast_decisions:"


def _short(kind: str) -> str:
    return kind.removeprefix(EVENT_PREFIX)


def _iter_jsonl_paths(events_path: str | Path) -> list[Path]:
    path = Path(events_path).expanduser()
    if path.is_dir():
        return sorted(path.glob("*.jsonl"))
    if path.is_file():
        return [path]
    raise FileNotFoundError(f"No such events file or directory: {path}")


def load_events(
    events_path: str | Path, *, session_id: str | None = None
) -> list[dict[str, Any]]:
    """Read every valid, deduplicated ``fast_decisions:*`` event from a
    directory of JSONL files or a single JSONL file. Out-of-order files and
    duplicate ``event_id``s produce exactly one record each."""
    seen: set[str] = set()
    events: list[dict[str, Any]] = []
    for path in _iter_jsonl_paths(events_path):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                continue
            if not event["event"].startswith(EVENT_PREFIX):
                continue
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or event_id in seen:
                continue
            if session_id and event.get("session_id") != session_id:
                continue
            seen.add(event_id)
            events.append(event)
    return events


@dataclass
class DecisionJoin:
    decision_id: str
    requested: dict[str, Any] | None = None
    scored: dict[str, Any] | None = None
    routed: list[dict[str, Any]] = field(default_factory=list)
    fallback: list[dict[str, Any]] = field(default_factory=list)
    shadow_agreement: dict[str, Any] | None = None
    role_agreement: dict[str, Any] | None = None
    slow_end: dict[str, Any] | None = None


def join_by_decision_id(events: list[dict[str, Any]]) -> dict[str, DecisionJoin]:
    joins: dict[str, DecisionJoin] = {}

    def get(decision_id: str) -> DecisionJoin:
        return joins.setdefault(decision_id, DecisionJoin(decision_id=decision_id))

    # Stable ordering by (turn_id, seq) so "out of order" input still joins
    # deterministically; duplicates were already removed by event_id in
    # load_events.
    for event in sorted(
        events, key=lambda e: (e.get("turn_id") or "", e.get("seq") or 0)
    ):
        decision_id = event.get("decision_id")
        if not decision_id:
            continue
        kind = _short(event["event"])
        data = event.get("data", {}) or {}
        join = get(decision_id)
        if kind == "requested":
            join.requested = data
        elif kind == "scored":
            join.scored = data
        elif kind == "routed":
            join.routed.append(data)
        elif kind == "fallback":
            join.fallback.append(data)
        elif kind == "shadow_agreement":
            join.shadow_agreement = data
        elif kind == "role_agreement":
            join.role_agreement = data
        elif kind == "slow_end":
            join.slow_end = data
    return joins


def _domain_of(join: DecisionJoin) -> tuple[str, bool]:
    """Returns ``(domain, inferred)``. Prefers the explicit ``domain``
    field recorded at candidate-set-build time (service.py/shadow.py/
    router.py, via ``contracts.classify_domain``) on whichever joined event
    carries it. Falls back to a heuristic, ``inferred=True``, only for
    legacy recordings made before this bundle emitted that field."""
    for source in (
        join.requested,
        join.scored,
        join.shadow_agreement,
        join.role_agreement,
    ):
        if source and isinstance(source.get("domain"), str):
            return source["domain"], False
    return _infer_domain_legacy(join), True


def _infer_domain_legacy(join: DecisionJoin) -> str:
    """Best-effort classification for recordings that predate the explicit
    ``domain`` field. Retained only for legacy telemetry -- see
    docs/BENCH.md."""
    if join.role_agreement is not None:
        return "model-role"
    tools = set()
    if join.requested:
        for c in join.requested.get("candidates", []) or []:
            tool = c.get("tool")
            if tool:
                tools.add(tool)
    for r in join.routed:
        destination = r.get("destination")
        if destination and destination != "provider":
            tools.add(destination)
    if tools and tools <= {"fast_workspace"}:
        return "read-target"
    return "tool-choice"


def _reconstruct_candidates(join: DecisionJoin) -> tuple[Candidate, ...]:
    if not join.requested:
        return ()
    out = []
    for c in join.requested.get("candidates", []) or []:
        try:
            out.append(
                Candidate(
                    id=c["id"],
                    label=c.get("label", c["id"]),
                    tool=c.get("tool", "fast_workspace"),
                    arguments={},
                )
            )
        except (KeyError, ValueError):
            continue
    return tuple(out)


@dataclass
class ReplayResult:
    n_decisions: int
    decision_latency_ms_p50: float | None
    decision_latency_ms_p95: float | None
    decision_cost_usd: float | None
    avoided_llm_turn_rate: float | None
    projected_task_latency_delta_ms: float | None
    projected_task_cost_delta_usd: float | None
    agreement_rate: float | None
    agreement_with_deterministic: float | None
    agreement_ci95: tuple[float, float] | None
    calibration: dict[str, Any]
    mean_reported_confidence: float | None
    abstention_rate: float | None
    n_observed: int
    per_domain: dict[str, dict[str, Any]]
    unsafe_autonomous_actions: int
    state_chars_p50: float | None
    state_chars_p95: float | None
    state_size_vs_latency: list[dict[str, Any]]
    shadow_snapshot_budget_exceeded: int
    dropped_shadow_jobs: int


async def _agreement_with_deterministic(joins: list[DecisionJoin]) -> float | None:
    from .suite import DeterministicSuiteBackend

    backend = DeterministicSuiteBackend()
    matches = 0
    total = 0
    for join in joins:
        if not join.scored or not join.requested:
            continue
        candidates = _reconstruct_candidates(join)
        if not candidates:
            continue
        request = DecisionRequest(state={}, candidates=candidates)
        result = await backend.ask(request)
        total += 1
        if result.action.choice == join.scored.get("choice"):
            matches += 1
    return (matches / total) if total else None


async def replay_events(
    events_path: str | Path,
    *,
    session_id: str | None = None,
    default_allowed_tools: tuple[str, ...] = ("fast_workspace",),
) -> ReplayResult:
    events = load_events(events_path, session_id=session_id)
    joins = join_by_decision_id(events)
    decisions = [j for j in joins.values() if j.requested is not None]
    n_decisions = len(decisions)

    decision_latencies = [
        j.scored["duration_ms"]
        for j in decisions
        if j.scored
        and j.scored.get("latency_kind") == "decision_model_wall_time"
        and isinstance(j.scored.get("duration_ms"), (int, float))
    ]
    input_tokens = [j.scored.get("input_tokens") for j in decisions if j.scored]
    cost = m.decision_cost_usd(input_tokens)

    shadow_records = [j.shadow_agreement for j in decisions if j.shadow_agreement]
    avoided_count = sum(
        1 for s in shadow_records if s.get("would_have_avoided_llm_turn")
    )
    avoided_rate = m.rate(avoided_count, n_decisions) if n_decisions else None
    match_count = sum(1 for s in shadow_records if s.get("agreement") == "match")
    agreement_rate = (
        m.rate(match_count, len(shadow_records)) if shadow_records else None
    )
    agreement_ci95 = m.bootstrap_ci(
        [1.0 if s.get("agreement") == "match" else 0.0 for s in shadow_records]
    )

    mean_slow_ms = m.mean_or_none(
        [
            j.slow_end["duration_ms"]
            for j in decisions
            if j.slow_end and isinstance(j.slow_end.get("duration_ms"), (int, float))
        ]
    )
    mean_decision_ms = m.mean_or_none(decision_latencies)
    projected_latency = m.projected_task_latency_delta_ms(
        decisions=n_decisions,
        mean_slow_ms=mean_slow_ms,
        mean_decision_ms=mean_decision_ms,
        avoided_rate=avoided_rate,
    )
    # Illustrative: avoided provider spend modelled as the same per-decision
    # token cost applied to avoided turns; the decision cost itself is Jev's.
    avoided_provider_cost = None
    projected_cost = m.projected_task_cost_delta_usd(
        avoided_provider_cost_usd=avoided_provider_cost, decision_cost=cost
    )

    ece_pairs = [
        (
            j.scored["selected_probability"],
            j.shadow_agreement.get("agreement") == "match",
        )
        for j in decisions
        if j.scored
        and isinstance(j.scored.get("selected_probability"), (int, float))
        and j.shadow_agreement
    ]
    calibration = m.ece(ece_pairs)
    mean_conf = m.mean_or_none(
        [j.scored.get("reported_confidence") for j in decisions if j.scored]
    )
    abstain_count = sum(
        1 for j in decisions if j.scored and j.scored.get("choice") == SLOW
    )
    abstention_rate = m.rate(abstain_count, n_decisions) if n_decisions else None

    per_domain: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[DecisionJoin]] = defaultdict(list)
    inferred_counts: dict[str, int] = defaultdict(int)
    for j in decisions:
        domain, inferred = _domain_of(j)
        grouped[domain].append(j)
        if inferred:
            inferred_counts[domain] += 1
    for domain, group in grouped.items():
        group_pairs = [
            (
                j.scored["selected_probability"],
                j.shadow_agreement.get("agreement") == "match",
            )
            for j in group
            if j.scored
            and isinstance(j.scored.get("selected_probability"), (int, float))
            and j.shadow_agreement
        ]
        group_shadow = [j.shadow_agreement for j in group if j.shadow_agreement]
        group_matches = sum(1 for s in group_shadow if s.get("agreement") == "match")
        group_abstain = sum(
            1 for j in group if j.scored and j.scored.get("choice") == SLOW
        )
        per_domain[domain] = {
            "ece": m.ece(group_pairs)["ece"],
            "agreement_rate": m.rate(group_matches, len(group_shadow))
            if group_shadow
            else None,
            "abstention_rate": m.rate(group_abstain, len(group)) if group else None,
            "n": len(group),
            # 0 for every domain recorded with the explicit `domain` field;
            # >0 only when legacy telemetry forced the heuristic fallback.
            "n_inferred": inferred_counts.get(domain, 0),
        }

    unsafe = 0
    for j in decisions:
        for r in j.routed:
            if (
                r.get("route") == "fast"
                and r.get("destination") not in default_allowed_tools
            ):
                unsafe += 1

    state_chars: list[float] = [
        float(j.requested["state_chars"])
        for j in decisions
        if j.requested and isinstance(j.requested.get("state_chars"), (int, float))
    ]
    state_p50 = m.percentile(state_chars, 50) if state_chars else None
    state_p95 = m.percentile(state_chars, 95) if state_chars else None
    state_size_vs_latency: list[dict[str, Any]] = []
    if state_chars:
        paired: list[tuple[float, float]] = [
            (float(j.requested["state_chars"]), float(j.scored["duration_ms"]))
            for j in decisions
            if j.requested
            and j.scored
            and isinstance(j.requested.get("state_chars"), (int, float))
            and isinstance(j.scored.get("duration_ms"), (int, float))
        ]
        paired.sort(key=lambda pair: pair[0])
        deciles = 10
        chunk = max(1, len(paired) // deciles) if paired else 0
        for i in range(0, len(paired), chunk) if chunk else []:
            bucket = paired[i : i + chunk]
            if not bucket:
                continue
            state_size_vs_latency.append(
                {
                    "decile": min(deciles, i // chunk + 1),
                    "state_chars": sum(x for x, _ in bucket) / len(bucket),
                    "mean_ms": sum(y for _, y in bucket) / len(bucket),
                }
            )

    shadow_budget_exceeded = sum(
        1
        for j in joins.values()
        for fb in j.fallback
        if fb.get("reason_code") == "shadow_snapshot_budget_exceeded"
    )
    health_events = [
        e.get("data", {}) for e in events if _short(e["event"]) == "health"
    ]
    dropped_shadow_jobs = max(
        (h.get("dropped_shadow_jobs", 0) or 0 for h in health_events), default=0
    )

    agreement_with_deterministic = await _agreement_with_deterministic(decisions)

    return ReplayResult(
        n_decisions=n_decisions,
        decision_latency_ms_p50=m.percentile(decision_latencies, 50),
        decision_latency_ms_p95=m.percentile(decision_latencies, 95),
        decision_cost_usd=cost,
        avoided_llm_turn_rate=avoided_rate,
        projected_task_latency_delta_ms=projected_latency,
        projected_task_cost_delta_usd=projected_cost,
        agreement_rate=agreement_rate,
        agreement_with_deterministic=agreement_with_deterministic,
        agreement_ci95=agreement_ci95,
        calibration=calibration,
        mean_reported_confidence=mean_conf,
        abstention_rate=abstention_rate,
        n_observed=calibration["n_observed"],
        per_domain=per_domain,
        unsafe_autonomous_actions=unsafe,
        state_chars_p50=state_p50,
        state_chars_p95=state_p95,
        state_size_vs_latency=state_size_vs_latency,
        shadow_snapshot_budget_exceeded=shadow_budget_exceeded,
        dropped_shadow_jobs=dropped_shadow_jobs,
    )
