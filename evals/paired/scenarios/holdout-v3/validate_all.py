#!/usr/bin/env python3
"""One combined, serial, memory-guarded validation run over all 60 holdout-v3 scenarios.

The three authoring batches each shipped their own validator (reference layouts differ), so this driver dispatches each
scenario to the validator that matches how its reference was authored, ONE scenario per invocation, strictly serial:

  validate_holdout.py  repos bugfix/feature + polyglot feature          (batch A)
  validate_b.py        mixed family + polyglot docs/mixed               (batch B)
  validate_c.py        knowledge family + repos review/explain          (batch C)

Every grader / hidden test / validator run goes through scripts/memguard.py (4 GB cap, 300 s, system floor) inside the
validators; this driver only schedules them (`nice -n 10`, `MEMGUARD_MAX_CONCURRENT=1`) and refuses to start one unless
`memory_pressure` reports >= 50% free. It writes a unified row per scenario to validation-combined.json.

  python3 evals/paired/scenarios/holdout-v3/validate_all.py [--ids a,b] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "scripts"))
import paired_scenarios as ps  # noqa: E402

if "holdout" not in ps.SPLITS:
    ps.SPLITS = tuple(ps.SPLITS) + ("holdout",)


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    m = re.search(r"free percentage:\s*(\d+)%", out)
    return int(m.group(1)) if m else 0


def validator_for(family: str, task_type: str) -> str:
    if family == "knowledge" or (family == "repos" and task_type in ("review", "explain")):
        return "validate_c.py"
    if family == "mixed" or (family == "polyglot" and task_type in ("docs", "mixed")):
        return "validate_b.py"
    return "validate_holdout.py"


def unify(validator: str, out_json: Path) -> dict:
    """Normalise the three validators' JSON shapes into one row."""
    raw = out_json.read_text(encoding="utf-8").strip() if out_json.exists() else ""
    if not raw:
        return {}
    if validator == "validate_c.py":
        r = json.loads(raw.splitlines()[-1])
        return dict(files=r.get("files"), tree=r.get("tree"), turns=r.get("turns"), long_gaps=r.get("long_gaps"),
                    kills=r.get("kills", 0) + r.get("timeouts", 0), peak_gb=r.get("peak_gb"),
                    errors=r.get("errors", []), runtime_s=r.get("runtime_s"))
    doc = json.loads(raw)
    if validator == "validate_b.py":
        r = doc["results"][0]
        return dict(files=r.get("files"), tree=r.get("tree"), turns=r.get("turns"), long_gaps=r.get("long_gaps"),
                    kills=r.get("kills"), peak_gb=r.get("peak_gb"), errors=r.get("errors", []),
                    runtime_s=r.get("seconds"))
    r = doc[0]
    return dict(files=r.get("files"), tree=r.get("tree"), turns=r.get("n_turns"), long_gaps=r.get("long_gaps"),
                kills=r.get("kills"), peak_gb=r.get("peak_gb"), errors=r.get("problems", []),
                runtime_s=r.get("runtime_s"), weak=r.get("weak", []))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--json", default=str(HERE / "validation-combined.json"))
    ap.add_argument("--cap-gb", type=float, default=4.0)
    ap.add_argument("--grader-timeout", type=float, default=300.0)
    a = ap.parse_args()
    want = set(a.ids.split(",")) if a.ids else None
    env = dict(os.environ, MEMGUARD_MAX_CONCURRENT="1", PYTHONPATH=f"{REPO / 'src'}:{REPO}")
    rows = []
    for path in sorted(HERE.glob("*/*.yaml")):
        if path.parent.name == "gen_b" or (want and path.stem not in want):
            continue
        spec = ps.parse(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
        validator = validator_for(path.parent.name, spec.task_type)
        fp = free_pct()
        row = dict(id=spec.id, family=path.parent.name, task_type=spec.task_type, validator=validator,
                   scenario_hash=ps.scenario_hash(spec), mem_free_before_pct=fp)
        if fp < 50:
            row.update(ok=False, errors=[f"memory_pressure {fp}% free < 50%: not run"])
            rows.append(row)
            print(f"SKIP {spec.id}: {fp}% free", flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix="vall-") as td:
            oj = Path(td) / "out.json"
            cmd = ["nice", "-n", "10", sys.executable, str(HERE / validator), "--ids", spec.id,
                   "--cap-gb", str(a.cap_gb), "--grader-timeout", str(a.grader_timeout), "--json", str(oj)]
            t0 = time.time()
            p = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
            row.update(unify(validator, oj))
            row.setdefault("errors", [])
            if p.returncode != 0 and not row["errors"]:
                row["errors"] = [f"validator exit {p.returncode}: {(p.stdout + p.stderr)[-300:]}"]
            row.update(ok=p.returncode == 0 and not row["errors"], wall_s=round(time.time() - t0, 1))
        rows.append(row)
        print(f"{'OK  ' if row['ok'] else 'FAIL'} {spec.id:<26} {validator:<20} turns={row.get('turns')} "
              f"files={row.get('files')} kills={row.get('kills')} peak={row.get('peak_gb')}GB "
              f"t={row['wall_s']}s free={fp}%", flush=True)
        for e in row["errors"]:
            print("      !", e, flush=True)
    Path(a.json).write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    bad = [r["id"] for r in rows if not r["ok"]]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} valid; kills={sum(r.get('kills') or 0 for r in rows)}; failed={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
