#!/usr/bin/env python3
"""Offline validation of the main-v1 polyglot scenarios (no model, no network beyond a local clone).

For every scenario YAML in ./polyglot (or --only ids):
  * the loader (scripts/paired_scenarios.parse) accepts it, its snapshot materializes;
  * (a) STARTER: turn 1's checks run against the untouched snapshot and must FAIL;
  * (b) REFERENCE: turn-by-turn overlays from <ref-root>/<id>/turnN/ are applied cumulatively to a private
        copy of the starter and every check of turn N must PASS (keyed_facts use turnN/MESSAGE.txt);
  * (c) DISCRIMINATION (informational): checks of turn N are also run on the state BEFORE turn N's
        overlay; a code/doc turn whose checks already pass there is reported as `weak` (not an error).
Reference solutions live OUTSIDE the repo (default ~/dev/afast-paired-src/reference/polyglot/<id>/turnN/,
optional turnN/_DELETE lists paths to remove). Re-run:

    python3 evals/paired/scenarios/main-v1/validate_polyglot.py [--only id,id] [--jobs 4] [--json out.json]
Exit 0 only if every scenario parses, starter fails turn 1 and the reference passes every turn.
"""
from __future__ import annotations
import argparse, json, shutil, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "scripts"))
import paired_scenarios as ps  # noqa: E402

# The loader's SPLITS is (train, test, pilot); main-v1 scenarios carry `split: main` until the seeded train/test
# assignment step rewrites it. Accept it here (in-process only) so the rest of the loader contract is still enforced.
if "main" not in ps.SPLITS:
    ps.SPLITS = tuple(ps.SPLITS) + ("main",)

DEFAULT_REF = Path("~/dev/afast-paired-src/reference/polyglot").expanduser()


def overlay(ws: Path, tdir: Path):
    if not tdir.is_dir():
        return
    for p in sorted(tdir.rglob("*")):
        rel = p.relative_to(tdir)
        if p.is_file() and rel.name not in ("MESSAGE.txt", "_DELETE") and not rel.parts[0].startswith("_"):
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, ws / rel)
    d = tdir / "_DELETE"
    if d.exists():
        for rel in d.read_text(encoding="utf-8").split():
            t = ws / rel
            shutil.rmtree(t) if t.is_dir() else t.unlink(missing_ok=True)


def message(tdir: Path):
    m = tdir / "MESSAGE.txt"
    return m.read_text(encoding="utf-8") if m.exists() else ""


def validate(path: Path, ref_root: Path, snap_root: Path) -> dict:
    t0 = time.time()
    out = {"id": path.stem, "errors": [], "turns": []}
    try:
        spec = ps.parse(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"parse: {e}")
        return out
    out.update(language=spec.language, n_turns=len(spec.turns), gaps=spec.gap_schedule, task_type=spec.task_type)
    n_checks = [len(t.checks) for t in spec.turns]
    snap = ps.materialize(spec, snap_root)
    ref = ref_root / spec.id
    if not ref.is_dir():
        out["errors"].append(f"no reference dir {ref}")
        return out
    with tempfile.TemporaryDirectory(prefix="val-") as tmp:
        starter = Path(tmp) / "starter"
        shutil.copytree(snap / "workspace", starter)
        s = ps.grade_turn(spec, 1, starter, "", snap)
        out["starter_turn1"] = {"failed": s["failed"], "labels": s["failure_labels"]}
        if s["failed"] == 0:
            out["errors"].append("starter passes turn 1 checks (must fail)")
        ws = Path(tmp) / "ref"
        shutil.copytree(snap / "workspace", ws)
        for i in range(1, len(spec.turns) + 1):
            tdir = ref / f"turn{i}"
            row = {"turn": i, "checks": n_checks[i - 1]}
            if i > 1:   # discrimination: previous state vs this turn's checks
                prev = ps.grade_turn(spec, i, ws, "", snap)
                row["passes_before_overlay"] = prev["failed"] == 0
            overlay(ws, tdir)
            g = ps.grade_turn(spec, i, ws, message(tdir), snap)
            row.update(failed=g["failed"], labels=g["failure_labels"])
            if g["failed"]:
                out["errors"].append(f"turn {i}: reference fails {g['failure_labels']}")
            out["turns"].append(row)
    out["weak_turns"] = [r["turn"] for r in out["turns"] if r.get("passes_before_overlay") and r["checks"] and
                         any(c.kind in ("tests", "doc_sections", "file_regex", "file_exists") for c in spec.turns[r["turn"] - 1].checks)]
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(HERE / "polyglot"))
    ap.add_argument("--ref-root", default=str(DEFAULT_REF))
    ap.add_argument("--snapshots", default=None, help="snapshot root (default: temp dir, discarded)")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    only = {x for x in a.only.split(",") if x}
    files = [p for p in sorted(Path(a.dir).glob("*.yaml")) if not only or p.stem in only]
    tmp_ctx = tempfile.TemporaryDirectory(prefix="val-snap-") if not a.snapshots else None
    snap_root = Path(a.snapshots).expanduser() if a.snapshots else Path(tmp_ctx.name)
    ref_root = Path(a.ref_root).expanduser()
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda p: validate(p, ref_root, snap_root), files))
    bad = 0
    for r in results:
        ok = not r["errors"]
        bad += 0 if ok else 1
        marks = "".join("." if t["failed"] == 0 else "F" for t in r["turns"])
        print(f"{'PASS' if ok else 'FAIL'} {r['id']:28s} {r.get('language','?'):10s} turns={r.get('n_turns','?'):>2} "
              f"starter_fail={r.get('starter_turn1',{}).get('failed','?')} ref[{marks}] weak={r.get('weak_turns')} {r.get('seconds','')}s")
        for e in r["errors"]:
            print("     !", e)
    print(f"\n{len(results) - bad}/{len(results)} scenarios valid")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
