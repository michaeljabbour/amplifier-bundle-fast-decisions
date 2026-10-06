#!/usr/bin/env python3
"""Re-grade a smoke session's per-turn workspace snapshots against a scenario file (no model calls).

  python3 regrade_smoke.py <scenario-id> [--spec path.yaml] [--turns 4,5] [--smoke-root ...]

Each turn's snapshot (turn-snapshots/tN.tar.gz) is unpacked and graded with paired_scenarios.grade_turn using the turn's
final message (turnN-stdout.txt, json "response"). Every grader runs through scripts/memguard.py. Prints one line per turn.
"""
import argparse, json, os, re, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path
import yaml
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
import paired_scenarios as ps  # noqa: E402
ps.SPLITS = tuple(dict.fromkeys(ps.SPLITS + ("holdout",)))


def find_spec(sid):
    for p in HERE.glob("*/*.yaml"):
        if yaml.safe_load(p.read_text(encoding="utf-8")).get("id") == sid:
            return p
    raise SystemExit(f"no scenario {sid}")


def session_dir(root, sid):
    c = list(Path(root).expanduser().glob(f"w*-a1/{sid}-r1-any-sonnet"))
    if not c:
        raise SystemExit(f"no smoke session for {sid}")
    return c[0]


def message(sd, i):
    p = sd / f"turn{i}-stdout.txt"
    if not p.exists():
        return ""
    t = p.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(t).get("response", "")
    except ValueError:
        m = re.search(r'"response":\s*"(.*?)",\n', t, re.S)
        return m.group(1) if m else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--spec")
    ap.add_argument("--turns")
    ap.add_argument("--smoke-root", default="~/dev/afast-paired/holdout-v3-smoke")
    a = ap.parse_args()
    path = Path(a.spec) if a.spec else find_spec(a.id)
    spec = ps.parse(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    sd = session_dir(a.smoke_root, a.id)
    want = {int(x) for x in a.turns.split(",")} if a.turns else None
    out = {}
    with tempfile.TemporaryDirectory(prefix="rg-") as root:
        snap = ps.materialize(spec, root)
        for i in range(1, len(spec.turns) + 1):
            if want and i not in want:
                continue
            tgz = sd / "turn-snapshots" / f"t{i}.tar.gz"
            if not tgz.exists():
                continue
            ws = Path(root) / f"t{i}"
            ws.mkdir()
            with tarfile.open(tgz) as t:
                t.extractall(ws)
            r = ps.grade_turn(spec, i, ws / "ws", message(sd, i), snap)
            out[i] = r
            print(f"{a.id} turn{i}: {'PASS' if r['failed'] == 0 else 'FAIL'} {r['passed']}/{r['checks']} {r['failure_labels']}", flush=True)
            shutil.rmtree(ws)
    print("TURN_PASS", sum(1 for r in out.values() if r["failed"] == 0), "/", len(out))


main()
