"""Offline analysis of already-emitted ``fast_decisions:*`` telemetry.

Harness-agnostic: no Amplifier or network imports (see the "Smart-tool
packaging target" section of docs/design/redesign-2026-09-17.md). Bench reads
JSONL the system already writes, or a checked-in labelled suite, and computes
pure functions of that data. It is an analysis tool, not a second measurement
system, and it makes no network calls unless the caller explicitly opts a
live backend in (``--live`` plus both required environment gates).
"""

from __future__ import annotations

from .metrics import (
    bootstrap_ci,
    decision_cost_usd,
    ece,
    percentile,
)
from .replay import ReplayResult, replay_events
from .report import build_report, render_markdown, write_jsonl
from .suite import (
    DeterministicSuiteBackend,
    ForbiddenLabelSource,
    SuiteCase,
    SuiteResult,
    load_suite,
    run_suite,
)

__all__ = [
    "DeterministicSuiteBackend",
    "ForbiddenLabelSource",
    "ReplayResult",
    "SuiteCase",
    "SuiteResult",
    "bootstrap_ci",
    "build_report",
    "decision_cost_usd",
    "ece",
    "load_suite",
    "percentile",
    "render_markdown",
    "replay_events",
    "run_suite",
    "write_jsonl",
]
