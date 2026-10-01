#!/usr/bin/env python3
"""Offline validation of the knowledge/ scenarios (no model calls).

For every scenario: (1) loader parses; (2) snapshot materializes twice into fresh roots with an identical
tree hash; (3) per turn, a reference answer/artifact passes all checks and a plausible-but-wrong one fails
(proves checks discriminate); (4) keyed_facts are not satisfied by the prompt text itself (no give-away);
(5) the STARTING workspace (pristine snapshot, empty answer) FAILS every turn's checks, so no turn is satisfied by doing nothing.

Reference layout (outside the repo): <ref-root>/<id>/turnN/{message.txt,files/**} and turnN/wrong/{message.txt,files/**}.
Reference files accumulate across turns (the workspace evolves like a real session); the wrong variant of
turn N is graded on the reference workspace of turns < N plus its own wrong files.

  validate_knowledge.py [--ids a,b] [--ref-root DIR] [--network]   (--network: ignore local_hint, fetch by sha)
"""
import argparse, copy, json, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "scripts"))
import paired_scenarios as ps  # noqa: E402

# The stock loader lists task types docs/explain and the files carry a real train/test split; no in-process patching.


def overlay(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--dir", default=str(HERE / "knowledge"))
    ap.add_argument("--ref-root", default=str(Path.home() / "dev/afast-paired-refs/knowledge"))
    ap.add_argument("--network", action="store_true")
    ap.add_argument("--cap-gb", type=float, default=None, help="memory cap per grader run (default 4 GB; memguard)")
    ap.add_argument("--grader-timeout", type=float, default=None, help="seconds per grader run (default 300; memguard)")
    a = ap.parse_args()
    import os as _os  # memguard defaults (scripts/paired_scenarios.py sets 4 GB / 300 s); explicit flags win
    if a.cap_gb is not None:
        _os.environ["PAIRED_GRADER_CAP_GB"] = str(a.cap_gb)
    if a.grader_timeout is not None:
        _os.environ["PAIRED_GRADER_TIMEOUT_S"] = str(a.grader_timeout)
    specs = ps.load_dir(a.dir)
    if a.ids:
        want = set(a.ids.split(","))
        specs = [s for s in specs if s.id in want]
    bad = 0
    summary = []
    for spec in specs:
        errs = []
        if a.network:
            spec = copy.deepcopy(spec)
            object.__setattr__(spec, "workspace", {k: v for k, v in spec.workspace.items() if k != "local_hint"})
        n = len(spec.turns)
        if not 8 <= n <= 16: errs.append(f"turns={n} outside 8-16")
        longs = [i for i, g in enumerate(spec.gap_schedule, 1) if g >= 300]
        if len(longs) not in (0, 2) or any(spec.gap_schedule[i - 1] != 420 for i in longs):
            errs.append(f"gaps {longs}")
        with tempfile.TemporaryDirectory(prefix="vk-") as ra, tempfile.TemporaryDirectory(prefix="vk-") as rb:
            snap = ps.materialize(spec, ra)
            snap2 = ps.materialize(spec, rb)
            h1 = json.loads((snap / "snapshot.json").read_text())["tree_sha256"]
            h2 = json.loads((snap2 / "snapshot.json").read_text())["tree_sha256"]
            if h1 != h2: errs.append("unstable tree hash")
            ws = Path(ra) / "ws"
            shutil.copytree(snap / "workspace", ws)
            start_ok = 0
            for i, t in enumerate(spec.turns, 1):      # (5) the untouched start state must fail every turn
                st = Path(ra) / "startws"
                if st.exists(): shutil.rmtree(st)
                shutil.copytree(snap / "workspace", st)
                sr = ps.grade_turn(spec, i, st, "", snap)
                if sr["failed"] == 0: errs.append(f"turn{i}: START state passes all checks (nothing to do)")
                else: start_ok += 1
            refdir = Path(a.ref_root).expanduser() / spec.id
            kinds = set()
            for i, t in enumerate(spec.turns, 1):
                kinds |= {c.kind for c in t.checks}
                if not t.checks: errs.append(f"turn{i}: no checks")
                td = refdir / f"turn{i}"
                if not td.is_dir(): errs.append(f"turn{i}: missing reference"); continue
                for c in t.checks:  # prompt-echo guard
                    if c.kind == "keyed_facts" and ps._check_keyed_facts(c.args, t.prompt)["failed"] == 0:
                        errs.append(f"turn{i}: keyed_facts satisfied by the prompt itself")
                wtmp = Path(ra) / "wrongws"
                if wtmp.exists(): shutil.rmtree(wtmp)
                shutil.copytree(ws, wtmp)
                overlay(td / "wrong" / "files", wtmp)
                wm = td / "wrong" / "message.txt"
                wr = ps.grade_turn(spec, i, wtmp, wm.read_text(encoding="utf-8") if wm.exists() else "", snap)
                if wr["failed"] == 0: errs.append(f"turn{i}: WRONG answer passed all checks")
                overlay(td / "files", ws)
                rr = ps.grade_turn(spec, i, ws, (td / "message.txt").read_text(encoding="utf-8"), snap)
                if rr["failed"] != 0 or rr["checks"] == 0:
                    errs.append(f"turn{i}: reference failed {rr['failure_labels']}")
            summary.append((spec.id, n, longs, sorted(kinds), h1[:10], f"start-fails {start_ok}/{n} " + ("OK" if not errs else "FAIL")))
        for e in errs: print(f"  {spec.id}: {e}")
        bad += bool(errs)
    print(f"\n{'id':26} turns gaps        kinds{'':52} tree        result")
    for sid, n, longs, kinds, h, r in summary:
        print(f"{sid:26} {n:<5} {str(longs):11} {','.join(kinds):57} {h}  {r}")
    print(f"\n{len(specs) - bad}/{len(specs)} scenarios valid")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
