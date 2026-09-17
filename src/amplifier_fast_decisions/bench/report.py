"""CLASSic-compatible JSONL record + Markdown summary emission.

Verified against ``michaeljabbour/amplifier-eval-taxonomies``,
``modules/hooks-eval-metrics/.../models.py`` (docs/design/redesign-2026-09-17.md,
P7 (iii)): the taxonomy writes JSONL records of ``CLASSicMetrics.to_dict()``
-- top-level ``session_id, model, provider, start_time, end_time`` plus
nested ``cost``, ``latency``, ``security``, ``stability``, and
``accuracy_proxy``. Bench emits a record in that exact shape, adding one
``decision`` sub-block and populating ``accuracy_proxy``. No mapping layer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import metrics as m
from .replay import ReplayResult
from .suite import SuiteResult

PROJECTION_BASIS = "model"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def build_report_from_replay(
    result: ReplayResult,
    *,
    session_id: str,
    model: str = "unknown",
    provider: str = "unknown",
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    accuracy_proxy: dict[str, Any] = {
        "agreement_rate": result.agreement_rate,
        "agreement_with_deterministic": result.agreement_with_deterministic,
        "calibration_ece": result.calibration["ece"],
        "calibration_bins": result.calibration["bins"],
        "ece_low_n_bins": result.calibration["low_n_bins"],
        "mean_reported_confidence": result.mean_reported_confidence,
        "abstention_rate": result.abstention_rate,
        "n_observed": result.n_observed,
        "agreement_ci95": list(result.agreement_ci95)
        if result.agreement_ci95
        else None,
        "per_domain": result.per_domain,
        "order_agreement_stability": None,
        "max_probability_swing": None,
        "permutations": 1,
    }
    decision = {
        "decision_latency_ms_p50": result.decision_latency_ms_p50,
        "decision_latency_ms_p95": result.decision_latency_ms_p95,
        "decision_cost_usd": result.decision_cost_usd,
        "avoided_llm_turn_rate": result.avoided_llm_turn_rate,
        "projected_task_latency_delta_ms": result.projected_task_latency_delta_ms,
        "projected_task_cost_delta_usd": result.projected_task_cost_delta_usd,
        "projection_basis": PROJECTION_BASIS,
        "projection_assumptions": list(m.PROJECTION_ASSUMPTIONS),
        "unsafe_autonomous_actions": result.unsafe_autonomous_actions,
        "state_chars_p50": result.state_chars_p50,
        "state_chars_p95": result.state_chars_p95,
        "state_size_vs_latency": result.state_size_vs_latency,
        "shadow_snapshot_budget_exceeded": result.shadow_snapshot_budget_exceeded,
        "dropped_shadow_jobs": result.dropped_shadow_jobs,
        "n_decisions": result.n_decisions,
    }
    now = _now()
    return {
        "session_id": session_id,
        "model": model,
        "provider": provider,
        "start_time": start_time or now,
        "end_time": end_time or now,
        "cost": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "estimated_cost_usd": result.decision_cost_usd,
            "tool_calls": result.n_decisions,
        },
        "latency": {
            "total_duration_ms": None,
            "avg_provider_duration_ms": None,
            "provider_durations_ms": [],
        },
        "security": {},
        "stability": {
            "total_errors": result.shadow_snapshot_budget_exceeded,
            "task_completed": None,
            "completion_confidence": None,
        },
        "accuracy_proxy": accuracy_proxy,
        "decision": decision,
    }


def build_report_from_suite(
    result: SuiteResult,
    *,
    session_id: str,
    model: str,
    provider: str,
    backend_external: bool,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    ece_pairs = [(item.canonical_probability, item.correct) for item in result.items]
    calibration = m.ece(ece_pairs)
    mean_conf = m.mean_or_none([item.reported_confidence for item in result.items])
    from ..contracts import SLOW

    abstain_count = sum(1 for item in result.items if item.canonical_choice == SLOW)
    abstention_rate = m.rate(abstain_count, len(result.items)) if result.items else None
    correct_count = sum(1 for item in result.items if item.correct)
    agreement_rate = m.rate(correct_count, len(result.items)) if result.items else None

    per_domain: dict[str, dict[str, Any]] = {}
    domains = {item.case.domain for item in result.items}
    for domain in domains:
        group = [item for item in result.items if item.case.domain == domain]
        group_ece = m.ece([(i.canonical_probability, i.correct) for i in group])
        group_correct = sum(1 for i in group if i.correct)
        group_abstain = sum(1 for i in group if i.canonical_choice == SLOW)
        per_domain[domain] = {
            "ece": group_ece["ece"],
            "agreement_rate": m.rate(group_correct, len(group)) if group else None,
            "abstention_rate": m.rate(group_abstain, len(group)) if group else None,
            "n": len(group),
        }

    input_tokens = [item.input_tokens for item in result.items]
    # An offline/deterministic backend genuinely used zero tokens (not
    # "missing"); only an external backend's absent usage is reported null.
    cost = m.decision_cost_usd(input_tokens) if backend_external else 0.0

    accuracy_proxy = {
        "agreement_rate": agreement_rate,
        "agreement_with_deterministic": None,
        "calibration_ece": calibration["ece"],
        "calibration_bins": calibration["bins"],
        "ece_low_n_bins": calibration["low_n_bins"],
        "mean_reported_confidence": mean_conf,
        "abstention_rate": abstention_rate,
        "n_observed": calibration["n_observed"],
        "agreement_ci95": list(
            m.bootstrap_ci([1.0 if i.correct else 0.0 for i in result.items]) or ()
        )
        or None,
        "per_domain": per_domain,
        "order_agreement_stability": result.order_agreement_stability,
        "max_probability_swing": result.max_probability_swing,
        "permutations": result.permutations,
    }
    decision = {
        "decision_latency_ms_p50": None,
        "decision_latency_ms_p95": None,
        "decision_cost_usd": cost,
        "avoided_llm_turn_rate": None,
        "projected_task_latency_delta_ms": None,
        "projected_task_cost_delta_usd": None,
        "projection_basis": PROJECTION_BASIS,
        "projection_assumptions": list(m.PROJECTION_ASSUMPTIONS),
        "unsafe_autonomous_actions": 0,
        "state_chars_p50": None,
        "state_chars_p95": None,
        "state_size_vs_latency": [],
        "shadow_snapshot_budget_exceeded": 0,
        "dropped_shadow_jobs": 0,
        "n_cases": len(result.items),
    }
    now = _now()
    return {
        "session_id": session_id,
        "model": model,
        "provider": provider,
        "start_time": start_time or now,
        "end_time": end_time or now,
        "cost": {
            "input_tokens": sum(t for t in input_tokens if isinstance(t, (int, float)))
            or (0 if not backend_external else None),
            "output_tokens": 0,
            "total_tokens": None,
            "estimated_cost_usd": cost,
            "tool_calls": 0,
        },
        "latency": {
            "total_duration_ms": None,
            "avg_provider_duration_ms": None,
            "provider_durations_ms": [],
        },
        "security": {},
        "stability": {
            "total_errors": 0,
            "task_completed": None,
            "completion_confidence": None,
        },
        "accuracy_proxy": accuracy_proxy,
        "decision": decision,
    }


def build_report(kind: str, *args, **kwargs) -> dict[str, Any]:
    """Dispatch to ``build_report_from_replay``/``build_report_from_suite``."""
    if kind == "replay":
        return build_report_from_replay(*args, **kwargs)
    if kind == "suite":
        return build_report_from_suite(*args, **kwargs)
    raise ValueError(f"Unknown report kind: {kind!r}")


def render_markdown(
    report: dict[str, Any], *, title: str = "Fast Decisions Bench Report"
) -> str:
    accuracy = report.get("accuracy_proxy", {})
    decision = report.get("decision", {})
    lines = [
        f"# {title}",
        "",
        f"- session: `{report.get('session_id')}`",
        f"- model / provider: `{report.get('model')}` / `{report.get('provider')}`",
        f"- window: {report.get('start_time')} .. {report.get('end_time')}",
        "",
        "## Decision",
        "",
        f"- decision latency p50/p95 (ms): {decision.get('decision_latency_ms_p50')} / {decision.get('decision_latency_ms_p95')}",
        f"- decision cost (usd): {decision.get('decision_cost_usd')}",
        f"- avoided LLM turn rate: {decision.get('avoided_llm_turn_rate')}",
        (
            f"- projected task latency delta (ms): {decision.get('projected_task_latency_delta_ms')} "
            f"(basis: {decision.get('projection_basis')}; "
            f"assumptions: {', '.join(decision.get('projection_assumptions', []))})"
        ),
        f"- projected task cost delta (usd): {decision.get('projected_task_cost_delta_usd')}",
        f"- unsafe autonomous actions: {decision.get('unsafe_autonomous_actions')} (must be 0 by construction)",
        f"- state chars p50/p95: {decision.get('state_chars_p50')} / {decision.get('state_chars_p95')}",
        f"- shadow_snapshot_budget_exceeded: {decision.get('shadow_snapshot_budget_exceeded')}, dropped_shadow_jobs: {decision.get('dropped_shadow_jobs')}",
        "",
        "## Accuracy proxy (never ground truth)",
        "",
        f"- agreement_rate: {accuracy.get('agreement_rate')} (n_observed={accuracy.get('n_observed')})",
        f"- agreement_with_deterministic: {accuracy.get('agreement_with_deterministic')}",
        f"- calibration_ece (chosen-option probability, >=10 bins, n>=30 only): {accuracy.get('calibration_ece')}",
        f"- mean_reported_confidence: {accuracy.get('mean_reported_confidence')}",
        f"- abstention_rate: {accuracy.get('abstention_rate')}",
        (
            f"- order_agreement_stability: {accuracy.get('order_agreement_stability')}, "
            f"max_probability_swing: {accuracy.get('max_probability_swing')} "
            f"(permutations={accuracy.get('permutations')})"
        ),
        "",
        "### Per-domain",
        "",
        "| domain | n | agreement_rate | abstention_rate | ece |",
        "|---|---|---|---|---|",
    ]
    for domain, stats in sorted((accuracy.get("per_domain") or {}).items()):
        lines.append(
            f"| {domain} | {stats.get('n')} | {stats.get('agreement_rate')} | "
            f"{stats.get('abstention_rate')} | {stats.get('ece')} |"
        )
    swing = accuracy.get("max_probability_swing")
    if isinstance(swing, (int, float)) and swing > 0.15:
        lines += [
            "",
            (
                "> **Warning:** max_probability_swing exceeds 0.15 -- at this magnitude "
                "the thresholds are measuring candidate serialisation, not the task."
            ),
        ]
    lines.append("")
    return "\n".join(lines)


def write_jsonl(report: dict[str, Any], path: str | Path) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True, allow_nan=False) + "\n")
