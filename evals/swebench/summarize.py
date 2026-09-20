#!/usr/bin/env python3
"""Convert one amplifier-evaluation harness run (`<output_dir>/summary.json`
+ `<output_dir>/trials/<trial-id>/`) into rows matching this repo's own
battery result-row vocabulary (`scripts/battery.py` / `scripts/battery_report.py`
-- see `task`, `harness`, `outcome_passed`, `wall_time_ms`, `exec_time_ms`,
`exec_time_source`, `cost_usd`, `cost_source` in those modules), so a human
reading a S3 result row recognizes the same field names as every other S1/S2
row. `scripts/battery_report.py` itself is out of scope for this change (it
reads its own campaign/manifest.json layout, not this harness's summary.json)
-- this module produces a compatible row shape for a future bridge, not a
drop-in replacement for that report.

Every function here is pure (no subprocess, no network): given a parsed
`summary.json` dict and the trial directory Path, produce plain dicts. See
tests/test_swebench_stage.py for fixtures built from a fake harness summary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# The single grader evaluation every S3 grader.yaml declares (see
# evals/swebench/sample_swebench.py::_grader_yaml). A trial's grader summary
# (harness `state.json`/`summary.json` "grader" field -- see
# amplifier_evaluation.harness.trial::run_trial, which writes
# `{"status": ..., "overall_score": ..., "evaluations": [{"name", "score",
# "weight"}, ...]}`) is read against this name.
SWEBENCH_EVAL_NAME = "swebench-resolved"

# A cost figure embedded in ai_user.json's free-form text, if the AI User's
# provider surfaced one (best-effort only -- most AI User backends do not
# report cost in transcript text; this is why cost defaults to null/"unknown"
# rather than ever being guessed).
_COST_RE = re.compile(r'"cost_usd"\s*:\s*([0-9]+(?:\.[0-9]+)?)')


def _outcome_passed(trial: dict[str, Any]) -> bool:
    """True iff the grader ran successfully and the swebench-resolved
    evaluation scored a full point. Any other shape (grader failed/skipped,
    evaluation missing, partial score) is NOT passed -- SWE-bench resolution
    is binary, never partial credit.
    """
    grader = trial.get("grader") or {}
    if grader.get("status") != "ok":
        return False
    for ev in grader.get("evaluations") or []:
        if ev.get("name") == SWEBENCH_EVAL_NAME:
            return float(ev.get("score", 0.0)) >= 1.0
    return False


def _extract_cost_from_trial_dir(trial_dir: Path) -> tuple[float | None, str]:
    """Best-effort cost extraction from the trial's full `ai_user.json`
    artifact on disk (harness on-disk layout: "ai_user.json  AI User result
    (conclude verdict, session id, full text)" -- see
    context/harness/harness_modules.md). Returns (cost_usd, source):
    `("harness_ai_user_json", <value>)` when a `"cost_usd": <number>` is
    found in that file's raw text, else `(None, "unknown")`. Never raises --
    a missing/malformed file is exactly the common case, not an error.
    """
    ai_user_path = trial_dir / "ai_user.json"
    if not ai_user_path.is_file():
        return None, "unknown"
    try:
        text = ai_user_path.read_text(encoding="utf-8")
    except OSError:
        return None, "unknown"
    match = _COST_RE.search(text)
    if not match:
        return None, "unknown"
    try:
        return float(match.group(1)), "ai_user_json"
    except ValueError:
        return None, "unknown"


def summarize_trial(trial: dict[str, Any], trial_dir: Path) -> dict[str, Any]:
    """Map one `TrialResult`-shaped dict (an entry of summary.json's
    `"trials"` list) plus its on-disk trial directory into one battery-style
    result row. Pure given `trial`; the only filesystem read is the
    best-effort cost extraction above.
    """
    wall_time_ms = None
    elapsed_s = trial.get("elapsed_s")
    if elapsed_s is not None:
        wall_time_ms = float(elapsed_s) * 1000.0

    cost_usd, cost_source = _extract_cost_from_trial_dir(trial_dir)

    grader = trial.get("grader") or {}
    notes: list[str] = []
    if grader.get("status") == "failed":
        notes.append(f"grader_failed:{grader.get('error', '')[:200]}")
    if trial.get("state") not in ("completed",):
        notes.append(f"trial_state:{trial.get('state')}")
    if trial.get("error"):
        notes.append(f"trial_error:{str(trial['error'])[:200]}")

    return {
        "task": trial.get("task_id"),
        "harness": trial.get("agent_id"),
        "trial_number": trial.get("trial_number"),
        "outcome_passed": _outcome_passed(trial),
        # exec_time_ms == wall_time_ms here: the harness's TrialResult.elapsed_s
        # spans the whole trial (launch..cleanup), and none of launching /
        # installing / seeding / running_agent / extracting / grading /
        # cleaning_up is separately timestamped in summary.json today (only
        # `state.json`'s `history` list carries per-stage `at` timestamps --
        # see context/harness/harness_modules.md's TrialState list). A future
        # bridge that wants agent-only exec time should read `history` from
        # each trial's `state.json` (RUNNING_AGENT -> EXTRACTING) instead of
        # this summary-only path.
        "exec_time_ms": wall_time_ms,
        "exec_time_source": "harness_elapsed_s"
        if wall_time_ms is not None
        else "unknown",
        "wall_time_ms": wall_time_ms,
        "cost_usd": cost_usd,
        "cost_source": cost_source,
        "cost_billable": cost_usd is not None,
        "dtu_id": trial.get("dtu_id"),
        "state": trial.get("state"),
        "notes": notes,
    }


def summarize_run(
    harness_summary: dict[str, Any], trials_dir: Path
) -> list[dict[str, Any]]:
    """Convert a full harness `summary.json` dict into one row per trial.

    `trials_dir` is `<output_dir>/trials`; each trial's on-disk directory is
    looked up by its `trial_id` for the (best-effort) cost extraction. A
    trial whose directory does not exist on disk still produces a row (cost
    falls back to null/"unknown"; nothing else in the row depends on the
    directory existing).
    """
    rows = []
    for trial in harness_summary.get("trials", []):
        trial_dir = trials_dir / str(trial.get("trial_id", ""))
        rows.append(summarize_trial(trial, trial_dir))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert an amplifier-evaluation S3 run's summary.json into battery-style result rows"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="the harness run's --output-dir (contains summary.json, trials/)",
    )
    parser.add_argument(
        "--out", required=True, help="where to write the JSON list of result rows"
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file():
        print(f"ERROR: {summary_path} not found", file=sys.stderr)
        return 1

    harness_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = summarize_run(harness_summary, output_dir / "trials")

    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} row(s) to {args.out}", file=sys.stderr)
    passed = sum(1 for r in rows if r["outcome_passed"])
    print(f"outcome_passed: {passed}/{len(rows)}", file=sys.stderr)
    cost_unknown = sum(1 for r in rows if r["cost_usd"] is None)
    if cost_unknown:
        print(
            f"cost unknown for {cost_unknown}/{len(rows)} row(s) (source=unknown)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
