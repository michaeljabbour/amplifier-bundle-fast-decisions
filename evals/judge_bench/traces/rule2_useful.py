"""Preregistered trace rule 2 (traces/PREREGISTRATION.md): is the read shortcut useful with this judge?

A judge is "useful here" if, on per-case majorities under bundle-read-shortcut, it makes at least 4 correct
automatic reads (cases whose final label is a read) and its wrong-automatic rate has a Wilson upper 95% bound
below 0.10. Also reports, descriptively, how many wrong automatic decisions match the host's actual next read.

    PYTHONPATH=src:. python3 evals/judge_bench/traces/rule2_useful.py docs/evidence/<dir>/holdout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.judge_bench import scoring, stats
from evals.judge_bench.summarize import case_outcomes

LABELS = Path(__file__).resolve().parent / "labels_final.json"


def main(run_dir: str) -> dict:
    run = Path(run_dir)
    cases = json.loads((run / "manifest.json").read_text())["cases"]
    rows = [json.loads(line) for line in (run / "requests.jsonl").read_text().splitlines() if line.strip()]
    labels = json.loads(LABELS.read_text())["labels"]
    policy = scoring.resolve_policy("bundle-read-shortcut")
    out = {}
    for arm in sorted({r["arm"] for r in rows if r["arm"] != "openai-decisions"}):
        oc = case_outcomes(rows, cases, policy, arm)
        reads = [c for c in cases if c["expected"] != "reason"]
        correct_reads = sum(oc[c["id"]]["correct"] and oc[c["id"]]["automatic"] for c in reads)
        wrong = sum(oc[c["id"]]["automatic_error"] for c in cases)
        lo, hi = stats.wilson(wrong, len(cases))
        out[arm] = {"correct_automatic_reads": correct_reads, "read_cases": len(reads),
                    "wrong_automatic": wrong, "n": len(cases), "wrong_automatic_upper95": hi,
                    "useful": correct_reads >= 4 and hi < 0.10}
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1, sort_keys=True))
