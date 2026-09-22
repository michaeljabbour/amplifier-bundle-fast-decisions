"""Calibration report: ECE, gate curve, and a reference-only derived
confidence -- pure, offline analysis over ``(chosen-option probability,
correct)`` pairs. No network, no LLM calls.

Wired into two entry points that must never drift from each other, so both
route through ``calibration_report`` below:

- ``afast bench suite --json`` adds a top-level ``calibration`` key, built
  from each case's chosen-option probability vs. agreement with the
  suite's ``expected_choice`` (see ``cli.py``).
- ``afast bench calibrate --receipts <events-dir-or-jsonl> --labels
  <jsonl>`` joins judged-decision receipts (the same ``fast_decisions:*``
  telemetry ``bench replay`` reads, keyed by ``decision_id`` ->
  ``scored.selected_probability``) with an external label file
  (``decision_id`` -> ``correct: bool``), so the gate curve below can be
  fit from real judged data rather than assumed.

Independent Jev audits found accuracy flat across roughly 0.50-0.95
reported confidence and discriminative only at >=0.99 confidence on some
workloads (see docs/EVIDENCE.md) -- the gate curve here is what lets that
claim be re-derived from any receipts/labels pair, not just taken on faith.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import metrics as m

DEFAULT_THRESHOLDS: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99)


def derived_confidence(probabilities: Sequence[float]) -> float | None:
    """``(n * p_max - 1) / (n - 1)`` over a single decision's full
    probability vector -- a normalized-margin statistic, reference only.
    Never a substitute for a backend's own reported confidence, and never
    fed into a gate. ``None`` for fewer than two alternatives (undefined)."""
    values = [float(p) for p in probabilities]
    n = len(values)
    if n < 2:
        return None
    p_max = max(values)
    return (n * p_max - 1) / (n - 1)


def gate_curve(
    pairs: Sequence[tuple[float, bool]],
    *,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
) -> list[dict[str, Any]]:
    """For each threshold ``t``: ``coverage`` (fraction of decisions with
    probability >= t), ``accuracy_above`` (accuracy restricted to those
    decisions), ``accuracy_below`` (accuracy of everything else). Accuracy
    is ``None`` -- never a fabricated 0/1 -- when a side is empty at that
    threshold."""
    clean = [
        (float(p), bool(c))
        for p, c in pairs
        if isinstance(p, (int, float)) and 0.0 <= float(p) <= 1.0
    ]
    n = len(clean)
    rows: list[dict[str, Any]] = []
    for t in thresholds:
        above = [c for p, c in clean if p >= t]
        below = [c for p, c in clean if p < t]
        rows.append(
            {
                "threshold": t,
                "n_above": len(above),
                "n_below": len(below),
                "coverage": (len(above) / n) if n else None,
                "accuracy_above": (sum(above) / len(above)) if above else None,
                "accuracy_below": (sum(below) / len(below)) if below else None,
            }
        )
    return rows


def calibration_report(
    pairs: Sequence[tuple[float, bool]],
    *,
    bins: int = 10,
    min_reliable_n: int = 30,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """The single calibration report shape both entry points print: ECE
    with per-bin accuracy/confidence/count (reusing ``metrics.ece``'s
    reliable-bin renormalisation, unchanged) plus ``gate_curve`` above,
    over the same ``(chosen_probability, correct)`` pairs."""
    report = m.ece(pairs, bins=bins, min_reliable_n=min_reliable_n)
    report["gate_curve"] = gate_curve(pairs, thresholds=thresholds)
    return report


def _load_labels(path: str | Path) -> dict[str, bool]:
    """``decision_id`` -> ``correct``, from a JSONL file of
    ``{"decision_id": ..., "correct": bool}`` rows. A row with a missing or
    non-bool ``correct`` is skipped, never coerced to ``False``."""
    labels: dict[str, bool] = {}
    text = Path(path).expanduser().read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        decision_id = row.get("decision_id")
        correct = row.get("correct")
        if isinstance(decision_id, str) and isinstance(correct, bool):
            labels[decision_id] = correct
    return labels


def _load_receipt_probabilities(events_path: str | Path) -> dict[str, float]:
    """``decision_id`` -> chosen-option probability, from the same
    ``fast_decisions:*`` telemetry ``bench replay`` reads (an events
    directory or a single JSONL file). Uses each join's
    ``scored.selected_probability`` -- the same field ``replay.py``'s own
    calibration path uses -- so receipts and replay can never silently
    disagree on what "the probability" means."""
    from .replay import join_by_decision_id, load_events

    events = load_events(events_path)
    joins = join_by_decision_id(events)
    out: dict[str, float] = {}
    for decision_id, join in joins.items():
        scored = join.scored or {}
        probability = scored.get("selected_probability")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            out[decision_id] = float(probability)
    return out


def joined_pairs(
    events_path: str | Path, labels_path: str | Path
) -> list[tuple[float, bool]]:
    """Inner-join receipts and labels on ``decision_id``. A ``decision_id``
    present on only one side is silently dropped -- there is no ground
    truth (or no probability) to score it against."""
    probabilities = _load_receipt_probabilities(events_path)
    labels = _load_labels(labels_path)
    shared = sorted(set(probabilities) & set(labels))
    return [(probabilities[d], labels[d]) for d in shared]
