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
TRACES_DIR = HERE / "traces"
TRACE_POOL = TRACES_DIR / "pool.json"
TRACE_LABELS = TRACES_DIR / "labels_final.json"
TRACE_SPLITS = {"trace-dev": "dev", "trace-holdout": "holdout"}  # split name -> pool.json `split`
LABEL_DECISIONS = ("agreed", "adjudicated", "dropped")


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


def load_trace_labels(path: Path | None = None) -> dict[str, dict]:
    """labels_final.json: {"labels": {case id: {"label": <candidate id | "reason" | null>,
    "decision": "agreed" | "adjudicated" | "dropped"}}} (a flat id -> {...} mapping is accepted too).
    Written once the blind review is adjudicated; nothing trace-derived runs without it."""
    path = Path(path) if path else TRACE_LABELS
    if not path.exists():
        raise FileNotFoundError(
            f"Final trace labels not found: {path}. The blind review has to finish first; write "
            'labels_final.json as {"labels": {"<id>": {"label": "<candidate id or reason>", '
            '"decision": "agreed|adjudicated|dropped"}}}.')
    doc = json.loads(path.read_text(encoding="utf-8"))
    labels = doc["labels"] if isinstance(doc, dict) and isinstance(doc.get("labels"), dict) else doc
    for cid, entry in labels.items():
        if not isinstance(entry, dict) or entry.get("decision") not in LABEL_DECISIONS:
            raise ValueError(f"{path}: {cid}: decision must be one of {LABEL_DECISIONS}")
        if entry["decision"] != "dropped" and not isinstance(entry.get("label"), str):
            raise ValueError(f"{path}: {cid}: a kept case needs a string label")
    return labels


def trace_cases(split: str, pool_path: Path | None = None, labels_path: Path | None = None) -> list[dict]:
    """Trace-derived read-shortcut cases for `trace-dev` / `trace-holdout`: pool.json entries of that
    split, `expected` = the FINAL label, dropped cases excluded. Every pool case of the split must have a
    decision, and every label must name a candidate or `reason`; otherwise this raises."""
    if split not in TRACE_SPLITS:
        raise ValueError(f"Unknown trace split {split!r}")
    pool_path = Path(pool_path) if pool_path else TRACE_POOL
    if not pool_path.exists():
        raise FileNotFoundError(f"Trace pool not found: {pool_path}")
    labels = load_trace_labels(labels_path)
    pool = json.loads(pool_path.read_text(encoding="utf-8"))["cases"]
    mine = [c for c in pool if c["split"] == TRACE_SPLITS[split]]
    missing = [c["id"] for c in mine if c["id"] not in labels]
    if missing:
        raise ValueError(f"labels_final.json has no decision for {len(missing)} {split} case(s): {missing[:5]}")
    out = []
    for c in mine:
        entry = labels[c["id"]]
        if entry["decision"] == "dropped":
            continue
        options = set(c["payload"]["questions"]["decision"]["criteria"])
        if entry["label"] not in options:
            raise ValueError(f"{c['id']}: final label {entry['label']!r} is not one of {sorted(options)}")
        out.append({"id": c["id"], "kind": c["kind"], "expected": entry["label"], "payload": c["payload"],
                    "native": c["native"], "screen": split, "label_decision": entry["decision"],
                    "tags": {"stratum": c.get("stratum"), "era": c.get("era"), "group": c.get("group")}})
    return out


def load_tags(split: str, cases: list[dict] | None = None) -> dict[str, dict]:
    if split == "dev":
        return json.loads(DEV_TAGS.read_text(encoding="utf-8"))
    if split == "holdout":
        return {c["id"]: c.get("tags") or {} for c in (cases if cases is not None else holdout_cases())}
    if split in TRACE_SPLITS:
        return {c["id"]: c.get("tags") or {} for c in (cases if cases is not None else trace_cases(split))}
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
