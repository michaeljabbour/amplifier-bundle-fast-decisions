"""Case sets and tags for the judge benchmark.

dev: the 90 first-pass cases, imported (never copied) from
evals/judge_comparison.py. holdout: evals/judge_bench/holdout/cases.json, which
the runner refuses to touch until it is pre-registered (see judges.py).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV_TAGS = HERE / "dev_tags.json"
HOLDOUT_CASES = HERE / "holdout" / "cases.json"


def dev_cases() -> list[dict]:
    from evals.judge_comparison import all_cases
    return all_cases()


def holdout_cases(path: Path | None = None) -> list[dict]:
    path = Path(path) if path else HOLDOUT_CASES
    if not path.exists():
        raise FileNotFoundError(f"Holdout cases not found: {path}. Author them and pre-register first.")
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("holdout cases.json must be a list")
    return [dict(c, screen="holdout") for c in cases]


def load_tags(split: str, cases: list[dict] | None = None) -> dict[str, dict]:
    if split == "dev":
        return json.loads(DEV_TAGS.read_text(encoding="utf-8"))
    if split == "holdout":
        return {c["id"]: c.get("tags") or {} for c in (cases if cases is not None else holdout_cases())}
    raise ValueError(f"Unknown split {split!r}")


def cases_sha256(cases: list[dict]) -> str:
    blob = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def reorder(payload: dict, order: int) -> dict:
    """Order pass 1 reverses Choice options; identical to judge_comparison.reorder."""
    from evals.judge_comparison import reorder as first_pass_reorder
    return first_pass_reorder(payload, order)


if __name__ == "__main__":  # print the sha to paste into PREREGISTRATION.md
    print("cases_sha256:", cases_sha256(holdout_cases()))
