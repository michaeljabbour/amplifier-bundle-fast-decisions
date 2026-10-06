#!/usr/bin/env python3
"""Prove, offline and without a model call, that every S1 cell differs from its comparator only in the intended setting.

For each cell the design uses, this builds the session profile exactly as the paired harness does (``paired.cell_to_side`` +
``forge_e2e._side_profile``), loads it through the REAL bundle composition (``amplifier_foundation.load_bundle`` in the
Amplifier host interpreter: the same deep merge a live session gets, including the shipped behaviors/fast-decisions.yaml),
flattens the effective ``session`` / ``providers`` / ``hooks`` / ``tools`` config, and then checks each ``render_contrasts``
entry of the design: the set of differing paths must be non-empty and contained in the contrast's ``allowed`` list
(dotted-path prefixes; ``model`` is the host model the design assigns the session).

  python3 evals/v3/s1_render_cells.py [--design evals/paired/holdout-v3.yaml] [--out evals/paired/holdout-v3-render.json]

Exit 0 only when every contrast holds. Writes the flattened effective configs and the contrast table to ``--out``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "evals"), str(REPO / "scripts"), str(REPO)]
import forge_e2e  # noqa: E402
import paired  # noqa: E402
import run as evals_run  # noqa: E402
from evals.v3 import common  # noqa: E402

_LOAD = """
import asyncio, json, sys
from amplifier_foundation import load_bundle
async def main():
    b = await load_bundle(sys.argv[1])
    print(json.dumps({"session": b.session, "providers": b.providers, "hooks": b.hooks, "tools": b.tools}, default=str))
asyncio.run(main())
"""


def flatten(obj, prefix="") -> dict:
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def effective_config(cell: str, design: dict, cells_doc: dict, suites_doc: dict, scratch: Path, source: Path) -> dict:
    side, _, bundle = paired.cell_to_side(cell, cells_doc, suites_doc, baseline_source=source, candidate_source=source,
                                          candidate_sha="render")
    cfg = {"limits": {"max_iterations": 30, "extended_thinking": True}, "events_dir": "/render/events",
           "campaign_provider": design.get("campaign_provider"), "amplifier_bundle": bundle}
    profile = forge_e2e._side_profile("render", side, "render", Path("/render/workspace"), cfg)
    d = scratch / cell
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.md").write_text("---\n" + json.dumps(profile, indent=2) + "\n---\n", encoding="utf-8")
    proc = subprocess.run([str(forge_e2e.HOST_PYTHON), "-c", _LOAD, (d / "profile.md").as_uri()],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit(f"load_bundle failed for {cell}: {proc.stderr[-500:]}")
    flat = flatten(json.loads(proc.stdout.splitlines()[-1]))
    flat.pop("providers[0].config.api_key", None)             # an env reference, never a value, but not needed here
    return flat


def contrast(a_flat: dict, b_flat: dict, a_model: str, b_model: str, allowed: list) -> dict:
    a_flat, b_flat = {**a_flat, "model": a_model}, {**b_flat, "model": b_model}
    diffs = sorted(k for k in set(a_flat) | set(b_flat) if a_flat.get(k) != b_flat.get(k))
    ok_prefix = lambda k: any(k == p or k.startswith(p + ".") or k.startswith(p + "[") for p in allowed)  # noqa: E731
    stray = [k for k in diffs if not ok_prefix(k)]
    return {"differs": [{"path": k, "a": a_flat.get(k), "b": b_flat.get(k)} for k in diffs],
            "unexpected": [{"path": k, "a": a_flat.get(k), "b": b_flat.get(k)} for k in stray],
            "ok": bool(diffs) and not stray}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", default=str(REPO / "evals/paired/holdout-v3.yaml"))
    ap.add_argument("--out", default=str(REPO / "evals/paired/holdout-v3-render.json"))
    ap.add_argument("--source", default=str(REPO), help="candidate source tree (the bundle root that is composed)")
    a = ap.parse_args()
    design = paired.load_design(a.design)
    cells_doc = evals_run.load_cells(paired._abs(paired.REPO_ROOT, design["cells_file"]))
    suites_doc = evals_run.load_suites()
    source = Path(a.source).resolve()

    def cell_of(arm: str, host: str) -> str:
        arm_cells = design["arms"][arm]["cells"]
        return arm_cells["any"] if design["arms"][arm].get("host_independent") else arm_cells[host]

    def model_of(arm: str, host: str) -> str:
        return design["hosts"][host if not design["arms"][arm].get("host_independent") else next(iter(design["hosts"]))]

    needed = sorted({cell_of(arm, h) for arm, d in design["arms"].items() for h in ((["any"] if d.get("host_independent") else list(d["cells"])))})
    with tempfile.TemporaryDirectory(prefix="s1-render-") as td:
        flats = {c: effective_config(c, design, cells_doc, suites_doc, Path(td), source) for c in needed}
    report = {"design": design["id"], "source": str(source), "cells": {}, "contrasts": [], "ok": True}
    for c, flat in flats.items():
        report["cells"][c] = {"sha256": hashlib.sha256(json.dumps(flat, sort_keys=True, default=str).encode()).hexdigest()[:16],
                              "n_keys": len(flat), "effective": flat}
    for spec in design["render_contrasts"]:
        host_a, host_b = spec["host"], spec.get("vs_host", spec["host"])
        ca, cb = cell_of(spec["a"], host_a), cell_of(spec["b"], host_b)
        res = contrast(flats[ca], flats[cb], model_of(spec["a"], host_a), model_of(spec["b"], host_b), spec["allowed"])
        entry = {"a": f"{spec['a']}@{host_a} ({ca})", "b": f"{spec['b']}@{host_b} ({cb})", "allowed": spec["allowed"], **res}
        report["contrasts"].append(entry)
        report["ok"] &= res["ok"]
        print(f"{'OK  ' if res['ok'] else 'FAIL'} {entry['a']:46} vs {entry['b']:46} differs in: "
              + (", ".join(f"{d['path']} ({d['b']!r} -> {d['a']!r})" for d in res["differs"]) or "NOTHING"))
        for d in res["unexpected"]:
            print(f"       UNEXPECTED {d['path']}: {d['b']!r} vs {d['a']!r}")
    common.write_json(Path(a.out), report)           # sanitized: the home directory becomes ~, key-like strings are refused
    print(f"\n{'ALL CONTRASTS HOLD' if report['ok'] else 'CONTRAST FAILURES'}; wrote {a.out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
