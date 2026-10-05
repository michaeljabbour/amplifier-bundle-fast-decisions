#!/usr/bin/env python3
"""Offline validator for the holdout-v3 scenarios (batch A: repos + polyglot). No model, no network beyond snapshot building.

Per scenario it checks that
  1. the loader parses it (``split: holdout`` is appended to the loader's SPLITS at runtime until the checked-in loader lists it);
  2. the snapshot materializes, and two independent builds have the same tree hash (frozen, reproducible);
  3. turn 1's checks FAIL on the pristine workspace (start state);
  4. every turn's checks PASS on the reference state (cumulative overlays under <ref-root>/<id>/turnN/, MESSAGE.txt = the
     reference final message, _DELETE = paths to remove);
  5. every turn DISCRIMINATES: its checks FAIL on the state before the turn's overlay with a content-free final message
     ("DONE: ok"); checks that already pass there are listed as `weak` (informational: sibling checks still discriminate);
  6. all scenario code ran under memguard (4 GB cap, 300 s): peak RSS and kills are recorded (a kill is a defect).
Usage (memory discipline of the campaign):  python3 validate_holdout.py --ids a --jobs 1 --cap-gb 4 --grader-timeout 300
Exit 0 only if every selected scenario is valid.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
import memguard  # noqa: E402
import paired_scenarios as ps  # noqa: E402

if "holdout" not in ps.SPLITS:
    ps.SPLITS = tuple(ps.SPLITS) + ("holdout",)

REF_ROOT = Path("~/dev/afast-paired-refs/holdout-v3").expanduser()
_PEAKS: list = []
_orig = memguard.run_guarded


def _recording(*a, **k):
    g = _orig(*a, **k)
    _PEAKS.append((g.peak_rss_gb, g.killed, g.wall_s))
    return g


memguard.run_guarded = _recording


def free_pct() -> int:
    m = re.search(r"free percentage:\s*(\d+)%", subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout)
    return int(m.group(1)) if m else 100


def overlay(ws: Path, tdir: Path):
    for p in sorted(tdir.rglob("*")):
        rel = p.relative_to(tdir)
        if p.is_file() and rel.name not in ("MESSAGE.txt", "_DELETE"):
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, ws / rel)
    d = tdir / "_DELETE"
    if d.exists():
        for rel in d.read_text(encoding="utf-8").split():
            t = ws / rel
            shutil.rmtree(t) if t.is_dir() else t.unlink(missing_ok=True)


def validate(path: Path) -> dict:
    t0 = time.time()
    out = {"id": path.stem, "problems": [], "notes": [], "weak": [], "turns": []}
    prob = out["problems"].append
    try:
        spec = ps.parse(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except Exception as e:  # noqa: BLE001
        prob(f"parse: {e}")
        return out
    out.update(family=path.parent.name, language=spec.language, task_type=spec.task_type, n_turns=len(spec.turns),
               gaps=spec.gap_schedule, long_gaps=spec.n_long_gaps, split=spec.split)
    tmp = Path(tempfile.mkdtemp(prefix=f"vh-{spec.id[:10]}-"))
    n0 = len(_PEAKS)
    try:
        a, b = ps.materialize(spec, tmp / "a"), ps.materialize(spec, tmp / "b")
        ha, hb = ps.tree_hash(a / "workspace"), ps.tree_hash(b / "workspace")
        out["tree"], out["files"] = ha[:12], ps.workspace_stats(a)["workspace_files"]
        out["scenario_hash"] = ps.scenario_hash(spec)[:12]
        if ha != hb:
            prob(f"snapshot not stable across builds: {ha[:10]} vs {hb[:10]}")
        ps.materialize(spec, tmp / "a")
        start = ps.grade_turn(spec, 1, a / "workspace", "", a)
        out["start_turn1"] = start["failure_labels"]
        if start["failed"] == 0:
            prob(f"turn1 checks pass on the pristine workspace: {start}")
        ref = REF_ROOT / spec.id
        if not ref.is_dir():
            prob(f"no reference dir {ref}")
            return out
        ws = tmp / "ref"
        shutil.copytree(a / "workspace", ws, symlinks=True)
        for i, turn in enumerate(spec.turns, start=1):
            tdir = ref / f"turn{i}"
            if not tdir.is_dir():
                prob(f"turn{i}: missing reference dir")
                continue
            msg = (tdir / "MESSAGE.txt").read_text(encoding="utf-8") if (tdir / "MESSAGE.txt").exists() else ""
            prev = tmp / f"prev{i}"
            shutil.copytree(ws, prev, symlinks=True)
            overlay(ws, tdir)
            res = ps.grade_turn(spec, i, ws, msg, a)
            pre = ps.grade_turn(spec, i, prev, "DONE: ok", a)
            row = {"turn": i, "checks": res["checks"], "ref_pass": res["failed"] == 0, "pre_fail": pre["failed"] > 0}
            out["turns"].append(row)
            if res["failed"]:
                prob(f"turn{i}: reference FAILS {res['failure_labels']}")
            if pre["failed"] == 0:
                prob(f"turn{i}: NOT discriminating (checks already pass before the turn)")
            if not turn.checks:
                prob(f"turn{i}: no checks")
            if len(turn.checks) > 1 and pre["failed"] and pre["failed"] < pre["checks"]:
                for c in turn.checks:
                    if c.kind == "tests":
                        continue
                    sp = ps.ScenarioSpec(**{**spec.__dict__, "turns": tuple(
                        ps.TurnSpec(prompt=t.prompt, checks=(c,) if j == i - 1 else t.checks, gap_before_s=t.gap_before_s)
                        for j, t in enumerate(spec.turns))})
                    if ps.grade_turn(sp, i, prev, "DONE: ok", a)["failed"] == 0 and not c.args.get("absent"):
                        out["weak"].append(f"turn{i}:{c.kind}:{c.args.get('path') or ''}")
            if pre["failed"] and pre["failed"] == pre["checks"] and len(turn.checks) > 1 and False:
                pass
    except Exception as exc:  # noqa: BLE001
        prob(f"exception: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    runs = _PEAKS[n0:]
    out["guarded_runs"] = len(runs)
    out["kills"] = sum(1 for r in runs if r[1])
    out["peak_gb"] = round(max([r[0] for r in runs] or [0.0]), 3)
    out["runtime_s"] = round(time.time() - t0, 1)
    if out["kills"]:
        prob(f"{out['kills']} guarded runs killed by memguard")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--cap-gb", type=float, default=None)
    ap.add_argument("--grader-timeout", type=float, default=None)
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.cap_gb is not None:
        os.environ["PAIRED_GRADER_CAP_GB"] = str(a.cap_gb)
    if a.grader_timeout is not None:
        os.environ["PAIRED_GRADER_TIMEOUT_S"] = str(a.grader_timeout)
    os.environ.setdefault("MEMGUARD_MAX_CONCURRENT", "1")
    paths = sorted(HERE.glob("*/*.yaml"))
    if a.ids:
        want = set(a.ids.split(","))
        paths = [p for p in paths if p.stem in want]
    results = []
    for p in paths:       # strictly serial; memory floor checked before each scenario
        fp = free_pct()
        if fp < 50:
            print(f"memory_pressure free {fp}% < 50%: refusing to run {p.stem}")
            return 2
        r = validate(p)
        r["mem_free_before_pct"] = fp
        results.append(r)
        print(f"{'OK  ' if not r['problems'] else 'FAIL'} {r['id']:<26} {r.get('family','?'):<8} turns={r.get('n_turns')} "
              f"long_gaps={r.get('long_gaps')} files={r.get('files')} runs={r.get('guarded_runs')} kills={r.get('kills')} "
              f"peak={r.get('peak_gb')}GB t={r.get('runtime_s')}s free={fp}%", flush=True)
        for x in r["problems"]:
            print("      !", x)
        if r["weak"]:
            print("      weak:", ", ".join(r["weak"]))
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    bad = sum(1 for r in results if r["problems"])
    print(f"\n{len(results) - bad}/{len(results)} scenarios valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
