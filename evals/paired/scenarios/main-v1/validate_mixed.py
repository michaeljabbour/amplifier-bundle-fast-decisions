#!/usr/bin/env python3
"""Offline validation of the mixed/ scenarios (no model calls, no network).

Per scenario: (1) loader parses (the stock loader does not list split "main"; like validate_knowledge.py the tuple is
extended in-process, and every scenario is additionally parsed with split overridden to "train" to prove that is the
only deviation); (2) turns in {8,12,16}, gaps = none or exactly two 420 s gaps (never before turn 1); (3) snapshot
materializes twice into fresh roots with an identical tree hash; (4) per turn, with the reference workspace evolving
like a real session: the checks FAIL on the state at the start of the turn (workspace after turn N-1, empty answer)
and PASS on the reference output; keyed_facts are not satisfied by the prompt text itself; (5) protected files:
tampering with the first protected file makes the final turn fail; (6) warning-only truncation probe (half of each reference file + correct answer should not pass); (7) optional turnN/wrong/{message.txt,files/**}
must fail.

Reference layout (outside the repo): <ref-root>/<id>/turnN/{message.txt,files/**,delete.txt (paths to remove)}.

  validate_mixed.py [--ids a,b] [--ref-root DIR]
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "scripts"))
import paired_scenarios as ps  # noqa: E402

ps.SPLITS = tuple(dict.fromkeys(ps.SPLITS + ("main",)))


def overlay(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--dir", default=str(HERE / "mixed"))
    ap.add_argument("--ref-root", default=str(Path.home() / "dev/afast-paired-refs/mixed"))
    ap.add_argument("--cap-gb", type=float, default=None, help="memory cap per grader run (default 4 GB; memguard)")
    ap.add_argument("--grader-timeout", type=float, default=None, help="seconds per grader run (default 300; memguard)")
    a = ap.parse_args()
    import os as _os  # memguard defaults (scripts/paired_scenarios.py sets 4 GB / 300 s); explicit flags win
    if a.cap_gb is not None:
        _os.environ["PAIRED_GRADER_CAP_GB"] = str(a.cap_gb)
    if a.grader_timeout is not None:
        _os.environ["PAIRED_GRADER_TIMEOUT_S"] = str(a.grader_timeout)
    specs = ps.load_dir(a.dir)
    for p in sorted(Path(a.dir).glob("*.yaml")):  # stock-loader parity: only the split value may differ
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        doc["split"] = "train"
        saved = ps.SPLITS
        ps.SPLITS = ("train", "test", "pilot")
        try:
            ps.parse(doc, str(p))
        finally:
            ps.SPLITS = saved
    if a.ids:
        want = set(a.ids.split(","))
        specs = [s for s in specs if s.id in want]
    bad, summary, warns = 0, [], []
    for spec in specs:
        errs = []
        n = len(spec.turns)
        if n not in (8, 12, 16):
            errs.append(f"turns={n} not in 8/12/16")
        longs = [i for i, g in enumerate(spec.gap_schedule, 1) if g >= 300]
        if len(longs) not in (0, 2) or any(spec.gap_schedule[i - 1] != 420 for i in longs) or 1 in longs:
            errs.append(f"gaps {longs}")
        with tempfile.TemporaryDirectory(prefix="vm-") as ra, tempfile.TemporaryDirectory(prefix="vm-") as rb:
            snap, snap2 = ps.materialize(spec, ra), ps.materialize(spec, rb)
            h1 = json.loads((snap / "snapshot.json").read_text())["tree_sha256"]
            h2 = json.loads((snap2 / "snapshot.json").read_text())["tree_sha256"]
            if h1 != h2:
                errs.append("unstable tree hash")
            ws = Path(ra) / "ws"
            shutil.copytree(snap / "workspace", ws)
            refdir = Path(a.ref_root).expanduser() / spec.id
            kinds, start_fail = set(), 0
            for i, t in enumerate(spec.turns, 1):
                kinds |= {c.kind for c in t.checks}
                if not t.checks:
                    errs.append(f"turn{i}: no checks")
                td = refdir / f"turn{i}"
                if not td.is_dir():
                    errs.append(f"turn{i}: missing reference")
                    continue
                for c in t.checks:  # prompt-echo guard
                    if c.kind == "keyed_facts" and ps._check_keyed_facts(c.args, t.prompt)["failed"] == 0:
                        errs.append(f"turn{i}: keyed_facts satisfied by the prompt itself")
                r0 = ps.grade_turn(spec, i, ws, "", snap)  # starting state must fail
                if r0["failed"] == 0:
                    errs.append(f"turn{i}: checks already PASS on the starting state")
                else:
                    start_fail += 1
                if (td / "wrong").is_dir():  # optional wrong variant must fail
                    wtmp = Path(ra) / "wrongws"
                    if wtmp.exists():
                        shutil.rmtree(wtmp)
                    shutil.copytree(ws, wtmp)
                    overlay(td / "wrong" / "files", wtmp)
                    wm = td / "wrong" / "message.txt"
                    wr = ps.grade_turn(spec, i, wtmp, wm.read_text(encoding="utf-8") if wm.exists() else "", snap)
                    if wr["failed"] == 0:
                        errs.append(f"turn{i}: WRONG variant passed")
                if (td / "files").is_dir():  # truncation probe: first half of every reference file + correct answer must NOT pass (warning only)
                    wtmp = Path(ra) / "halfws"
                    if wtmp.exists():
                        shutil.rmtree(wtmp)
                    shutil.copytree(ws, wtmp)
                    for f in (td / "files").rglob("*"):
                        if f.is_file():
                            tgt = wtmp / f.relative_to(td / "files")
                            tgt.parent.mkdir(parents=True, exist_ok=True)
                            lines = f.read_text(encoding="utf-8").splitlines(True)
                            tgt.write_text("".join(lines[: len(lines) // 2]), encoding="utf-8")
                    hr = ps.grade_turn(spec, i, wtmp, (td / "message.txt").read_text(encoding="utf-8"), snap)
                    if hr["failed"] == 0:
                        warns.append(f"{spec.id} turn{i}: still passes with half-truncated reference files")
                overlay(td / "files", ws)  # reference must pass
                if (td / "delete.txt").exists():  # reference deletions (file moves)
                    for rel in (td / "delete.txt").read_text(encoding="utf-8").split():
                        (ws / rel).unlink()
                rr = ps.grade_turn(spec, i, ws, (td / "message.txt").read_text(encoding="utf-8"), snap)
                if rr["failed"] != 0 or rr["checks"] == 0:
                    errs.append(f"turn{i}: reference failed {rr['failure_labels']}")
            if spec.protected:  # tamper test on the final state
                victim = ws / spec.protected[0]
                orig = victim.read_bytes()
                victim.write_bytes(orig + b"\n#tamper\n")
                rt = ps.grade_turn(spec, n, ws, (refdir / f"turn{n}" / "message.txt").read_text(encoding="utf-8"), snap)
                victim.write_bytes(orig)
                if rt["failed"] == 0:
                    errs.append("protected-file tamper not detected")
            else:
                errs.append("no protected files declared")
            summary.append((spec.id, n, longs, sorted(kinds), h1[:10], start_fail, "OK" if not errs else "FAIL"))
        for e in errs:
            print(f"  {spec.id}: {e}")
        bad += bool(errs)
    print(f"\n{'id':24} turns gaps      start-fail kinds{'':44} tree        result")
    for sid, n, longs, kinds, h, sf, r in summary:
        print(f"{sid:24} {n:<5} {str(longs):9} {sf:>2}/{n:<7} {','.join(kinds):50} {h}  {r}")
    for w in warns:
        print("  warn:", w)
    print(f"\n{len(specs) - bad}/{len(specs)} scenarios valid")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
