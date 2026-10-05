#!/usr/bin/env python3
"""Offline validation of holdout-v3 batch B (mixed/ + polyglot/): no model calls, no network (polyglot snapshots use the
pinned local clone via local_hint). Every grader / hidden test / `go test` runs through scripts/memguard.py (4 GB, 300 s)
via paired_scenarios.grade_turn. Run strictly serially, one scenario per invocation (see run_all_b.sh).

Per scenario: (1) loader parses (split `holdout` is added to ps.SPLITS in-process, and the file is also parsed with
split=test to prove that is the only deviation); (2) 8-16 turns, gaps none or exactly two 420 s gaps (never before turn 2);
(3) snapshot materializes twice into fresh roots with identical tree hash; (4) no hidden-file name in any prompt, no
keyed_facts satisfied by the prompt; (5) per turn, with the reference workspace evolving like a real session: checks FAIL
on the state at the start of the turn (workspace after turn N-1 + empty answer) and PASS on the reference output;
(6) discrimination: explicit wrong variants (turnN/wrong/), the `empty` mutation (reference files and answer blanked) and,
for turns flagged bump in turnN/meta.json, the `bump` mutation (every number in reference files + answer incremented)
must each FAIL; (7) guard: tampering with the first protected file makes the final turn fail; (8) warning-only half-truncation probe.

Reference layout: <ref-root>/<id>/turnN/{message.txt,files/**,delete.txt,meta.json,wrong/{message.txt,files/**}}.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "scripts"))
import memguard  # noqa: E402
import paired_scenarios as ps  # noqa: E402

ps.SPLITS = tuple(dict.fromkeys(ps.SPLITS + ("holdout",)))
STATS = {"runs": 0, "peak": 0.0, "kills": 0}
_orig_guarded = memguard.run_guarded


def _guarded(*a, **k):
    r = _orig_guarded(*a, **k)
    STATS["runs"] += 1
    STATS["peak"] = max(STATS["peak"], float(getattr(r, "peak_rss_gb", 0) or 0))
    if getattr(r, "killed", None):
        STATS["kills"] += 1
    return r


memguard.run_guarded = _guarded


def overlay(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def bump(text):
    return re.sub(r"\d+", lambda m: str(int(m.group(0)) + 1), text)


def mutate(ws, td, fn):
    """Apply fn(text) to every reference file of the turn (on top of the pre-turn workspace ws)."""
    for f in (td / "files").rglob("*"):
        if f.is_file():
            tgt = ws / f.relative_to(td / "files")
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(fn(f.read_text(encoding="utf-8")), encoding="utf-8")


def fresh(src, name, root):
    d = Path(root) / name
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(src, d)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--dirs", default=f"{HERE / 'mixed'},{HERE / 'polyglot'}")
    ap.add_argument("--ref-root", default=str(Path.home() / "dev/afast-paired-refs/holdout-v3"))
    ap.add_argument("--cap-gb", type=float, default=None)
    ap.add_argument("--grader-timeout", type=float, default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if a.cap_gb is not None:
        os.environ["PAIRED_GRADER_CAP_GB"] = str(a.cap_gb)
    if a.grader_timeout is not None:
        os.environ["PAIRED_GRADER_TIMEOUT_S"] = str(a.grader_timeout)
    dirs = [Path(d) for d in a.dirs.split(",") if d]
    specs = []
    for d in dirs:
        for p in sorted(d.glob("*.yaml")):
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            specs.append((p, ps.parse(doc, str(p))))
            doc["split"] = "test"
            saved = ps.SPLITS
            ps.SPLITS = ("train", "test", "pilot")
            try:
                ps.parse(doc, str(p))
            finally:
                ps.SPLITS = saved
    if a.ids:
        want = set(a.ids.split(","))
        specs = [(p, s) for p, s in specs if s.id in want]
    results, warns, bad = [], [], 0
    for path, spec in specs:
        t0, errs = time.time(), []
        STATS.update(runs=0, peak=0.0, kills=0)
        n = len(spec.turns)
        if not 8 <= n <= 16:
            errs.append(f"turns={n} outside 8-16")
        longs = [i for i, g in enumerate(spec.gap_schedule, 1) if g >= 300]
        if len(longs) not in (0, 2) or any(spec.gap_schedule[i - 1] != 420 for i in longs) or 1 in longs:
            errs.append(f"gaps {longs}")
        blob = "\n".join(ps.turn_prompts(spec))
        for h in spec.hidden_files:
            if Path(h).name in blob:
                errs.append(f"hidden file name {h} appears in a prompt")
        with tempfile.TemporaryDirectory(prefix="vb-") as ra, tempfile.TemporaryDirectory(prefix="vb-") as rb:
            snap, snap2 = ps.materialize(spec, ra), ps.materialize(spec, rb)
            h1 = json.loads((snap / "snapshot.json").read_text())["tree_sha256"]
            if h1 != json.loads((snap2 / "snapshot.json").read_text())["tree_sha256"]:
                errs.append("unstable tree hash")
            nfiles = json.loads((snap / "snapshot.json").read_text())["files"]
            ws = Path(ra) / "ws"
            shutil.copytree(snap / "workspace", ws)
            refdir = Path(a.ref_root).expanduser() / spec.id
            kinds, start_fail, wrong_n, mut_n = set(), 0, 0, 0
            if not refdir.is_dir():
                errs.append(f"no reference dir {refdir}")
            for i, t in enumerate(spec.turns, 1):
                kinds |= {c.kind for c in t.checks}
                td = refdir / f"turn{i}"
                if not t.checks:
                    errs.append(f"turn{i}: no checks")
                if not td.is_dir():
                    errs.append(f"turn{i}: missing reference")
                    continue
                msg = (td / "message.txt").read_text(encoding="utf-8")
                meta = json.loads((td / "meta.json").read_text()) if (td / "meta.json").exists() else {}
                for c in t.checks:
                    if c.kind == "keyed_facts" and ps._check_keyed_facts(c.args, t.prompt)["failed"] == 0:
                        errs.append(f"turn{i}: keyed_facts satisfied by the prompt itself")
                r0 = ps.grade_turn(spec, i, ws, "", snap)
                if r0["failed"] == 0:
                    errs.append(f"turn{i}: checks already PASS on the starting state")
                else:
                    start_fail += 1
                if (td / "wrong").is_dir():
                    w = fresh(ws, "wrongws", ra)
                    overlay(td / "wrong" / "files", w)
                    wm = td / "wrong" / "message.txt"
                    wr = ps.grade_turn(spec, i, w, wm.read_text(encoding="utf-8") if wm.exists() else "", snap)
                    wrong_n += 1
                    if wr["failed"] == 0:
                        errs.append(f"turn{i}: WRONG variant passed")
                if (td / "files").is_dir() or msg:
                    w = fresh(ws, "emptyws", ra)
                    mutate(w, td, lambda _t: "")
                    er = ps.grade_turn(spec, i, w, "", snap)
                    mut_n += 1
                    if er["failed"] == 0:
                        errs.append(f"turn{i}: EMPTY mutation passed")
                    if meta.get("bump"):
                        w = fresh(ws, "bumpws", ra)
                        mutate(w, td, bump)
                        br = ps.grade_turn(spec, i, w, bump(msg), snap)
                        mut_n += 1
                        if br["failed"] == 0:
                            errs.append(f"turn{i}: BUMP mutation passed (numbers not enforced)")
                if (td / "files").is_dir():
                    w = fresh(ws, "halfws", ra)
                    mutate(w, td, lambda t_: "".join(t_.splitlines(True)[: len(t_.splitlines(True)) // 2]))
                    hr = ps.grade_turn(spec, i, w, msg, snap)
                    if hr["failed"] == 0:
                        warns.append(f"{spec.id} turn{i}: still passes with half-truncated reference files")
                overlay(td / "files", ws)
                if (td / "delete.txt").exists():
                    for rel in (td / "delete.txt").read_text(encoding="utf-8").split():
                        shutil.rmtree(ws / rel) if (ws / rel).is_dir() else (ws / rel).unlink(missing_ok=True)
                rr = ps.grade_turn(spec, i, ws, msg, snap)
                if rr["failed"] != 0 or rr["checks"] == 0:
                    errs.append(f"turn{i}: reference failed {rr['failure_labels']}")
            if spec.protected:
                victim = ws / spec.protected[0]
                orig = victim.read_bytes()
                victim.write_bytes(orig + b"\n#tamper\n")
                last = refdir / f"turn{n}" / "message.txt"
                rt = ps.grade_turn(spec, n, ws, last.read_text(encoding="utf-8") if last.exists() else "", snap)
                victim.write_bytes(orig)
                if rt["failed"] == 0:
                    errs.append("protected-file tamper not detected")
            else:
                errs.append("no protected files declared")
        row = dict(id=spec.id, family=path.parent.name, task_type=spec.task_type, language=spec.language, turns=n,
                   long_gaps=longs, files=nfiles, tree=h1[:10], start_fail=f"{start_fail}/{n}", wrong_variants=wrong_n,
                   mutations=mut_n, kinds=sorted(kinds), guarded_runs=STATS["runs"], kills=STATS["kills"],
                   peak_gb=round(STATS["peak"], 3), seconds=round(time.time() - t0, 1), errors=errs,
                   result="OK" if not errs else "FAIL")
        results.append(row)
        for e in errs:
            print(f"  {spec.id}: {e}")
        bad += bool(errs)
        print(f"{row['result']:4} {spec.id:24} {spec.task_type:6} turns={n:<2} gaps={longs} files={nfiles:<4} start-fail={row['start_fail']:6} "
              f"wrong={wrong_n} mut={mut_n} kills={row['kills']} peak={row['peak_gb']}GB {row['seconds']}s", flush=True)
    for w in warns:
        print("  warn:", w)
    print(f"\n{len(specs) - bad}/{len(specs)} scenarios valid")
    if a.json:
        Path(a.json).write_text(json.dumps({"results": results, "warnings": warns}, indent=2), encoding="utf-8")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
