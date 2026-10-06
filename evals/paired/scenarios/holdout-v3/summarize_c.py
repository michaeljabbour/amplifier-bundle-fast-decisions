#!/usr/bin/env python3
"""Summarise validation-c.jsonl (output of run_all_c.sh) into validation-c.json, scenario-hashes-c.json and VALIDATION-C.md."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
import paired_scenarios as ps  # noqa: E402

src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "validation-c.jsonl"
rows = {}
for line in src.read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line); rows[r["id"]] = r
specs = {s.id: (s, fam) for fam in ("knowledge", "repos") for s in ps.load_dir(HERE / fam)}
out, hashes, md = [], {}, []
for sid in sorted(specs, key=lambda i: (specs[i][1], i)):
    s, fam = specs[sid]; r = rows.get(sid, {"errors": ["not validated"]})
    ws = s.workspace
    row = dict(id=sid, family=fam, task_type=s.task_type, language=s.language, split=s.split, repo=ws["repo"], sha=ws["sha"],
               files=r.get("files"), turns=len(s.turns), long_gaps=[i for i, g in enumerate(s.gap_schedule, 1) if g >= 300],
               kinds=r.get("kinds"), start_fails=r.get("start_fails"), wrong_fails=r.get("wrong_fails"), ref_passes=r.get("ref_passes"),
               kills=r.get("kills"), timeouts=r.get("timeouts"), peak_gb=r.get("peak_gb"), runtime_s=r.get("runtime_s"), errors=r.get("errors"),
               notes=r.get("notes"), valid=not r.get("errors"))
    out.append(row); hashes[sid] = ps.scenario_hash(s)
(HERE / "validation-c.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
(HERE / "scenario-hashes-c.json").write_text(json.dumps(hashes, indent=1, sort_keys=True) + "\n", encoding="utf-8")
n_ok = sum(r["valid"] for r in out)
md.append("# holdout-v3 batch C validation (20 scenarios: 12 knowledge + 8 repos; 10 review + 10 explain)\n")
md.append(f"- Result: **{n_ok}/{len(out)} valid** (loader parses with the stock loader, start state fails every turn, reference passes every turn, plausible-wrong variant fails every turn)")
md.append(f"- Guard: `run_all_c.sh`: one `validate_c.py` invocation per scenario, strictly serial, `--cap-gb 4 --grader-timeout 300`, `MEMGUARD_MAX_CONCURRENT=1`, free memory >= 50% checked before each; all grading through scripts/memguard.py")
md.append(f"- Kills: {sum(r['kills'] or 0 for r in out)} memory kills, {sum(r['timeouts'] or 0 for r in out)} timeouts; max sampled peak {max((r['peak_gb'] or 0) for r in out)} GB")
md.append(f"- Workspaces > 300 files: {sum(1 for r in out if (r['files'] or 0) > 300)}; scenarios with two 420 s gaps: {sum(1 for r in out if len(r['long_gaps']) == 2)}; turns min/max: {min(r['turns'] for r in out)}/{max(r['turns'] for r in out)}\n")
md.append("| family | id | type | repo@sha | files | turns | gaps | check kinds | start fails | wrong fails | ref passes | kills | peak GB | valid |")
md.append("|---|---|---|---|---:|---:|---|---|---|---|---|---:|---:|---|")
for r in out:
    repo = r["repo"].rstrip("/").removesuffix(".git").split("github.com/")[-1]
    md.append(f"| {r['family']} | {r['id']} | {r['task_type']} | {repo}@{r['sha'][:7]} | {r['files']} | {r['turns']} | {','.join(map(str, r['long_gaps'])) or '-'} | {','.join(r['kinds'] or [])} | {r['start_fails']} | {r['wrong_fails']} | {r['ref_passes']} | {r['kills']} | {r['peak_gb']} | {'yes' if r['valid'] else 'NO: ' + '; '.join(r['errors'] or [])} |")
notes = [(r["id"], n) for r in out for n in (r["notes"] or [])]
if notes:
    md.append("\n## Notes (non-blocking)\n"); md += [f"- {i}: {n}" for i, n in notes]
md.append("""
## Disclosures

- scripts/paired_scenarios.py: `SPLITS` gains `"holdout"` (one word; the stock loader rejected `split: holdout`). Sibling batches A/B will carry the same edit.
- One validator for both families (`validate_c.py`, adapted from validate_knowledge.py): stock loader, double materialize with identical tree hash, start state fails every turn, per-turn reference passes, per-turn plausible-wrong variant fails, keyed_facts not satisfied by the prompt or by `DONE: ok`, notes when a check already passes before its turn. All grading goes through scripts/memguard.py.
- Reference messages/files are hand-authored from the pinned source and from real runs of the pinned code; no model call was made, so the PLAN's per-scenario plain-Sonnet smoke session is still to be done.
- Authoring-time fact checks used a few ad-hoc `python3 -c` snippets and one direct pytest of a two-test file outside memguard (tiny, not the validator); every validator/grader run was guarded.
- Network check: every snapshot was rebuilt from git by sha with `local_hint` ignored and the tree hash equals the cached one (honcho needed `.git_archival.txt` removed: its export-subst content differs between a tagged clone and a shallow fetch).
- Same upstream repos as batch A (different tasks): jsonschema, pygments, rich.
- References and generators: ~/dev/afast-paired-refs/holdout-v3/<id>/turnN/ and ~/dev/afast-paired-refs/holdout-v3/_tools/{lib.py,sc/*.py}.
""")
(HERE / "VALIDATION-C.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"{n_ok}/{len(out)} valid")
