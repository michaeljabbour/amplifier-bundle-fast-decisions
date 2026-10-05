#!/usr/bin/env python3
"""Offline validator for the holdout-v3 knowledge/ and repos/ scenarios (batch C). No model calls.

Per scenario (one invocation per scenario, serial; every grader run goes through scripts/memguard.py):
  1. the stock loader parses it (task_type review|explain, split holdout, 8-16 turns, 0 or two 420 s gaps);
  2. the snapshot materializes twice into fresh roots with an identical tree hash (file count reported);
  3. the STARTING workspace with an empty answer FAILS every turn's checks (nothing is satisfied by doing nothing);
  4. per turn: the reference (cumulative overlays) PASSES; a plausible-wrong variant FAILS; keyed_facts are not
     satisfied by the prompt text itself nor by a content-free `DONE: ok` message; tests/regex/doc checks are
     reported (note) when they already pass on the previous turn's reference state (non-discriminating).
Reference layout (outside the repo): <ref-root>/<id>/turnN/{message.txt,files/**,_DELETE,wrong/{message.txt,files/**}}.

  validate_c.py --ids a [--ref-root DIR] [--cap-gb 4 --grader-timeout 300] [--json out.json]
"""
import argparse, copy, json, os, shutil, sys, tempfile, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
import memguard  # noqa: E402
import paired_scenarios as ps  # noqa: E402

PEAK = {"peak": 0.0, "kills": 0, "timeouts": 0, "runs": 0}
_orig = memguard.run_guarded


def _spy(*a, **k):
    g = _orig(*a, **k)
    PEAK["runs"] += 1
    PEAK["peak"] = max(PEAK["peak"], g.peak_rss_gb)
    if g.killed in ("memory", "system_floor"): PEAK["kills"] += 1
    if g.killed == "timeout": PEAK["timeouts"] += 1
    return g


memguard.run_guarded = _spy


def overlay(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def only(spec, i, c):
    turns = [ps.TurnSpec(prompt=t.prompt, checks=(c,) if j == i - 1 else t.checks, gap_before_s=t.gap_before_s)
             for j, t in enumerate(spec.turns)]
    return ps.ScenarioSpec(**{**spec.__dict__, "turns": tuple(turns)})


def validate(spec, ref_root, network):
    errs, notes = [], []
    if network:
        spec = copy.deepcopy(spec)
        object.__setattr__(spec, "workspace", {k: v for k, v in spec.workspace.items() if k != "local_hint"})
    n = len(spec.turns)
    if not 8 <= n <= 16: errs.append(f"turns={n} outside 8-16")
    longs = [i for i, g in enumerate(spec.gap_schedule, 1) if g >= 300]
    if len(longs) not in (0, 2) or any(spec.gap_schedule[i - 1] != 420 for i in longs): errs.append(f"gaps {longs}")
    if spec.split != "holdout": errs.append("split != holdout")
    if spec.task_type not in ("review", "explain"): errs.append(f"task_type {spec.task_type}")
    kinds, start_ok, wrong_ok, ref_ok = set(), 0, 0, 0
    with tempfile.TemporaryDirectory(prefix="vh-") as ra, tempfile.TemporaryDirectory(prefix="vh-") as rb:
        snap, snap2 = ps.materialize(spec, ra), ps.materialize(spec, rb)
        h1 = json.loads((snap / "snapshot.json").read_text())["tree_sha256"]
        h2 = json.loads((snap2 / "snapshot.json").read_text())["tree_sha256"]
        if h1 != h2: errs.append("unstable tree hash")
        files = ps.workspace_stats(snap)["workspace_files"]
        ws = Path(ra) / "ws"
        shutil.copytree(snap / "workspace", ws)
        refdir = Path(ref_root).expanduser() / spec.id
        for i, t in enumerate(spec.turns, 1):
            kinds |= {c.kind for c in t.checks}
            if not t.checks: errs.append(f"turn{i}: no checks"); continue
            st = Path(ra) / "startws"
            if st.exists(): shutil.rmtree(st)
            shutil.copytree(snap / "workspace", st)
            if ps.grade_turn(spec, i, st, "", snap)["failed"] == 0: errs.append(f"turn{i}: START state passes all checks")
            else: start_ok += 1
            td = refdir / f"turn{i}"
            if not td.is_dir(): errs.append(f"turn{i}: missing reference"); continue
            for c in t.checks:
                if c.kind == "keyed_facts":
                    if ps._check_keyed_facts(c.args, t.prompt)["failed"] == 0: errs.append(f"turn{i}: keyed_facts satisfied by the prompt itself")
                    if ps._check_keyed_facts(c.args, "DONE: ok")["failed"] == 0: errs.append(f"turn{i}: keyed_facts pass on a content-free message")
            wt = Path(ra) / "wrongws"
            if wt.exists(): shutil.rmtree(wt)
            shutil.copytree(ws, wt)
            overlay(td / "wrong" / "files", wt)
            wm = td / "wrong" / "message.txt"
            if ps.grade_turn(spec, i, wt, wm.read_text(encoding="utf-8") if wm.exists() else "", snap)["failed"] == 0:
                errs.append(f"turn{i}: WRONG answer passed all checks")
            else: wrong_ok += 1
            prev = Path(ra) / "prevws"
            if prev.exists(): shutil.rmtree(prev)
            shutil.copytree(ws, prev)
            overlay(td / "files", ws)
            if (td / "_DELETE").exists():
                for line in (td / "_DELETE").read_text().split():
                    if (ws / line).exists(): (ws / line).unlink()
            rr = ps.grade_turn(spec, i, ws, (td / "message.txt").read_text(encoding="utf-8"), snap)
            if rr["failed"] != 0 or rr["checks"] == 0: errs.append(f"turn{i}: reference failed {rr['failure_labels']}")
            else: ref_ok += 1
            for c in t.checks:
                if c.kind in ("tests", "file_regex", "doc_sections", "file_exists") and not c.args.get("absent"):
                    if ps.grade_turn(only(spec, i, c), i, prev, "", snap)["failed"] == 0:
                        notes.append(f"turn{i}: {c.kind} {c.args.get('path') or c.args.get('files')} already passes before the turn")
    return {"id": spec.id, "task_type": spec.task_type, "turns": n, "long_gaps": longs, "files": files, "tree": h1[:12],
            "kinds": sorted(kinds), "start_fails": f"{start_ok}/{n}", "wrong_fails": f"{wrong_ok}/{n}",
            "ref_passes": f"{ref_ok}/{n}", "errors": errs, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--dir", default=str(HERE))
    ap.add_argument("--ref-root", default=str(Path.home() / "dev/afast-paired-refs/holdout-v3"))
    ap.add_argument("--network", action="store_true")
    ap.add_argument("--cap-gb", type=float, default=None)
    ap.add_argument("--grader-timeout", type=float, default=None)
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.cap_gb is not None: os.environ["PAIRED_GRADER_CAP_GB"] = str(a.cap_gb)
    if a.grader_timeout is not None: os.environ["PAIRED_GRADER_TIMEOUT_S"] = str(a.grader_timeout)
    specs = ps.load_dir([Path(a.dir) / "knowledge", Path(a.dir) / "repos"])    # stock loader, both families
    want = set(a.ids.split(","))
    t0 = time.time()
    bad = 0
    for spec in [s for s in specs if s.id in want]:
        r = validate(spec, a.ref_root, a.network)
        r.update(runtime_s=round(time.time() - t0, 1), peak_gb=round(PEAK["peak"], 3), runs=PEAK["runs"],
                 kills=PEAK["kills"], timeouts=PEAK["timeouts"], hash=ps.scenario_hash(spec)[:12])
        print(json.dumps(r))
        for e in r["errors"]: print("  !", e, file=sys.stderr)
        for e in r["notes"]: print("  note:", e, file=sys.stderr)
        bad += bool(r["errors"])
        if a.json:
            with open(a.json, "a", encoding="utf-8") as f: f.write(json.dumps(r) + "\n")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
