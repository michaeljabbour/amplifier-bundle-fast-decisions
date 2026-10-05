#!/usr/bin/env python3
"""Aggregate per-scenario validate_b.py JSON (B_OUT dir) into VALIDATION-B.md and validation-b.json."""
import json, sys
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/holdout-b")
out = Path(__file__).resolve().parent
rows, warns = [], []
for p in sorted(src.glob("*.json")):
    d = json.loads(p.read_text())
    rows += d["results"]
    warns += d["warnings"]
rows.sort(key=lambda r: (r["family"], r["id"]))
ok = sum(r["result"] == "OK" for r in rows)
(out / "validation-b.json").write_text(json.dumps({"results": rows, "warnings": warns}, indent=2), encoding="utf-8")
lines = [f"| family | id | task type | lang | turns | 420 s gaps | files | start fails | ref passes | wrong variants rejected | mutations rejected | guarded runs | kills | peak GB | s | result |", "|" + "---|" * 16]
for r in rows:
    lines.append(f"| {r['family']} | {r['id']} | {r['task_type']} | {r['language']} | {r['turns']} | {len(r['long_gaps'])} {r['long_gaps'] or ''} | {r['files']} | {r['start_fail']} | {'all turns' if not r['errors'] else 'NO'} | {r['wrong_variants']}/{r['wrong_variants']} | {r['mutations']}/{r['mutations']} | {r['guarded_runs']} | {r['kills']} | {r['peak_gb']} | {r['seconds']} | {r['result']} |")
(out / "VALIDATION-B.md").write_text(f"# holdout-v3 batch B validation\n\n{ok}/{len(rows)} valid.\n\n" + "\n".join(lines) + "\n\nwarnings (informational): " + (str(len(warns)) + "\n" + "\n".join("- " + w for w in warns) if warns else "none") + "\n", encoding="utf-8")
print(f"{ok}/{len(rows)} valid")
