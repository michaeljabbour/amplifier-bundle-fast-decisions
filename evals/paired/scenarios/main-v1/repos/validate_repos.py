#!/usr/bin/env python3
"""Offline validator for the main-v1 real-repo scenarios in this directory.

Per scenario it checks that:
  1. the loader parses it (``split: main`` is appended to the loader's SPLITS at runtime when the checked-in
     loader does not list it yet);
  2. the snapshot materializes and its tree hash is identical across two independent builds;
  3. turn-1 hidden tests FAIL on the pristine parent workspace;
  4. every turn's deterministic checks PASS against the reference solution (cumulative per-turn overlays under
     ``~/dev/afast-paired-refs/repos/<id>/turnN/``; ``MESSAGE.txt`` is the reference final message);
  5. every hidden test file first used by a later turn (scenario-authored edge-case tests) FAILS on the
     previous turn's reference state and passes on its own turn;
  6. keyed-fact checks fail on a content-free message; file/doc checks are reported (note) when they already
     pass before their turn.

Usage: python3 validate_repos.py [--ids a,b] [--jobs 4] [--keep]
Network is touched only by snapshot building (git fetch fallback / pip download for vendored deps).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "scripts"))
import paired_scenarios as ps  # noqa: E402

if "main" not in ps.SPLITS:
    ps.SPLITS = tuple(ps.SPLITS) + ("main",)

REF_ROOTS = [Path.home() / "dev/afast-paired-refs/repos"]       # the single consolidated reference root
REF_ROOT = REF_ROOTS[0]


def _ref_root(sid):
    """First reference root that has this scenario (new campaign refs, then the earlier drafts' location)."""
    for r in REF_ROOTS:
        if (r / sid).is_dir():
            return r
    return REF_ROOTS[0]


def _apply(ws: Path, turn_dir: Path):
    for p in sorted(turn_dir.rglob("*")):
        if p.is_file() and p.name != "MESSAGE.txt":
            dst = ws / p.relative_to(turn_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)


def _hidden_of(turn):
    return {h for c in turn.checks if c.kind == "tests" for h in (c.args.get("hidden") or [])}


def _with_checks(spec, idx, checks):
    turns = [ps.TurnSpec(prompt=t.prompt, checks=checks if j == idx - 1 else t.checks, gap_before_s=t.gap_before_s)
             for j, t in enumerate(spec.turns)]
    return ps.ScenarioSpec(**{**spec.__dict__, "turns": tuple(turns)})


def validate(spec, keep=False):
    out = {"id": spec.id, "turns": len(spec.turns), "gaps_long": spec.n_long_gaps, "problems": [], "notes": []}
    tmp = Path(tempfile.mkdtemp(prefix=f"val-{spec.id[:10]}-"))
    prob = out["problems"].append
    try:
        snap_a = ps.materialize(spec, tmp / "a")
        snap_b = ps.materialize(spec, tmp / "b")
        ha, hb = ps.tree_hash(snap_a / "workspace"), ps.tree_hash(snap_b / "workspace")
        out["tree"] = ha[:12]
        out["files"] = ps.workspace_stats(snap_a)["workspace_files"]
        if ha != hb or snap_a.name != snap_b.name:
            prob(f"snapshot not stable across builds: {ha[:10]} vs {hb[:10]}")
        ps.materialize(spec, tmp / "a")  # idempotent re-materialize verifies the recorded hash
        r = ps.grade_turn(spec, 1, snap_a / "workspace", "", snap_a)
        test_checks = [c for c in spec.turns[0].checks if c.kind == "tests"]
        if not test_checks or r["failed"] == 0:
            prob(f"turn1 hidden tests do not fail on the parent workspace: {r}")
        elif "pytest_failures" not in r["failure_labels"]:
            prob(f"turn1 fails on the parent for the wrong reason: {r['failure_labels']}")
        ws = tmp / "ws"
        shutil.copytree(snap_a / "workspace", ws)
        seen_hidden: set = set()
        for i, turn in enumerate(spec.turns, start=1):
            tdir = _ref_root(spec.id) / spec.id / f"turn{i}"
            if not tdir.is_dir():
                prob(f"turn{i}: missing reference dir {tdir}")
                continue
            msg = (tdir / "MESSAGE.txt").read_text(encoding="utf-8") if (tdir / "MESSAGE.txt").exists() else ""
            prev = tmp / f"prev{i}"
            shutil.copytree(ws, prev)
            _apply(ws, tdir)
            res = ps.grade_turn(spec, i, ws, msg, snap_a)
            if res["failed"]:
                prob(f"turn{i}: reference FAILS {res['failure_labels']}")
            new_h = _hidden_of(turn) - seen_hidden
            if new_h and i > 1:
                probe = tuple(ps.Check("tests", {"runner": "python", "files": sorted(new_h), "hidden": sorted(new_h)}) for _ in (0,))
                sp = _with_checks(spec, i, probe)
                if ps.grade_turn(sp, i, prev, msg, snap_a)["failed"] == 0:
                    prob(f"turn{i}: new hidden tests {sorted(new_h)} already pass BEFORE the turn (vacuous)")
                if ps.grade_turn(sp, i, ws, msg, snap_a)["failed"] != 0:
                    prob(f"turn{i}: new hidden tests {sorted(new_h)} fail AFTER the reference")
            seen_hidden |= _hidden_of(turn)
            for c in turn.checks:
                if c.kind in ("file_regex", "doc_sections"):
                    if ps.grade_turn(_with_checks(spec, i, (c,)), i, prev, "", snap_a)["failed"] == 0 and not c.args.get("absent"):
                        out["notes"].append(f"turn{i}: {c.kind} {c.args.get('path')} already passes before the turn")
                if c.kind == "keyed_facts" and ps.grade_turn(_with_checks(spec, i, (c,)), i, ws, "DONE: ok", snap_a)["failed"] == 0:
                    prob(f"turn{i}: keyed_facts passes on a content-free message")
        out["gaps"] = spec.gap_schedule
    except Exception as exc:  # noqa: BLE001
        prob(f"exception: {type(exc).__name__}: {exc}")
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--cap-gb", type=float, default=None, help="memory cap per grader run (default 4 GB; memguard)")
    ap.add_argument("--grader-timeout", type=float, default=None, help="seconds per grader run (default 300; memguard)")
    a = ap.parse_args()
    import os as _os  # memguard defaults (scripts/paired_scenarios.py sets 4 GB / 300 s); explicit flags win
    if a.cap_gb is not None:
        _os.environ["PAIRED_GRADER_CAP_GB"] = str(a.cap_gb)
    if a.grader_timeout is not None:
        _os.environ["PAIRED_GRADER_TIMEOUT_S"] = str(a.grader_timeout)
    specs = ps.load_dir(HERE)  # also proves the loader parses every YAML in this directory
    if a.ids:
        want = set(a.ids.split(","))
        specs = [s for s in specs if s.id in want]
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda s: validate(s, a.keep), specs))
    bad = 0
    for r in results:
        bad += bool(r["problems"])
        print(f"{'OK  ' if not r['problems'] else 'FAIL'} {r['id']:<28} turns={r['turns']:<2} long_gaps={r['gaps_long']} "
              f"files={r.get('files')} tree={r.get('tree')}")
        for p in r["problems"]:
            print("      !", p)
        for n in r["notes"]:
            print("      note:", n)
    print(f"\n{len(results) - bad}/{len(results)} scenarios valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
