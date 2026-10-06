#!/usr/bin/env python3
"""holdout-v3 panel: constraint check, overlap check, frozen hashes, SPLIT.md. No model call, no scenario code is executed.

  python3 evals/paired/scenarios/holdout-v3/panel.py [--validation validation-combined.json] [--write]

Checks the PLAN S1 panel constraints on the 60 scenario files in this directory:
  10 per task type (bugfix, feature, mixed, review, explain, docs); families polyglot 12 / repos 20 / mixed 16 / knowledge 12;
  >= 12 scenarios with > 300 workspace files (counted two ways: every file of the snapshot, and the scope gate's own count
  = orchestrator.workspace_file_count + the 1 file the harness adds); >= 6 with >= 2 idle gaps of >= 300 s; 8-16 turns;
  no scenario shares an id, a (repo, sha, subdir) source, an inline file tree or a language+exercise slug with main-v1 or
  pilot-v1 (same upstream repo at another commit, the same exercise slug in another language, and a turn-1 prompt that
  resembles another scenario's are REPORTED, not failed).
With --write it (re)writes scenario-hashes.json (frozen sha256 of every scenario file, its scenario/prompt hashes, the
snapshot tree hash and the hidden-files hash) and SPLIT.md. The hash file is the contract the preregistration freezes.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
import paired_scenarios as ps  # noqa: E402
from amplifier_fast_decisions.orchestrator import workspace_file_count  # noqa: E402

if "holdout" not in ps.SPLITS:
    ps.SPLITS = tuple(ps.SPLITS) + ("holdout",)

FAMILIES = ("polyglot", "repos", "mixed", "knowledge")
WANT_FAMILY = {"polyglot": 12, "repos": 20, "mixed": 16, "knowledge": 12}
TYPES = ("bugfix", "feature", "mixed", "review", "explain", "docs")
SNAPSHOT_ROOT = Path("~/dev/afast-paired/snapshots").expanduser()
OLD_DIRS = {"main-v1": ["polyglot", "repos", "mixed", "knowledge"], "pilot-v1": [""]}
SCOPE_LIMIT = 300


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_key(spec) -> dict:
    ws = spec.workspace
    if ws["kind"] == "inline":
        files = json.dumps(ws["files"], sort_keys=True)
        return {"kind": "inline", "files_sha": hashlib.sha256(files.encode()).hexdigest()[:16]}
    sub = (ws.get("subdir") or "").strip("/")
    return {"kind": "git", "repo": str(ws["repo"]).removesuffix(".git").lower(), "sha": ws["sha"], "subdir": sub,
            "slug": sub.rsplit("/", 1)[-1] if "exercises" in sub else None,
            "lang": sub.split("/", 1)[0] if "exercises" in sub else None}


def load_old() -> list:
    out = []
    for name, subs in OLD_DIRS.items():
        base = REPO / "evals/paired/scenarios" / name
        for sub in subs:
            d = base / sub if sub else base
            for p in sorted(d.glob("*.yaml")):
                spec = ps.parse(yaml.safe_load(p.read_text(encoding="utf-8")), str(p))
                out.append((name, spec))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validation", default=str(HERE / "validation-combined.json"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-snapshots", action="store_true", help="skip snapshot materialization (no tree hashes)")
    a = ap.parse_args()
    validation = {r["id"]: r for r in json.loads(Path(a.validation).read_text(encoding="utf-8"))} if Path(a.validation).exists() else {}

    rows = []
    for fam in FAMILIES:
        for p in sorted((HERE / fam).glob("*.yaml")):
            spec = ps.parse(yaml.safe_load(p.read_text(encoding="utf-8")), str(p))
            row = {"id": spec.id, "family": fam, "task_type": spec.task_type, "language": spec.language, "split": spec.split,
                   "turns": len(spec.turns), "long_gaps": spec.n_long_gaps, "file": f"{fam}/{p.name}",
                   "file_sha256": sha256_file(p), "scenario_hash": ps.scenario_hash(spec), "prompt_sha256": ps.prompt_hash(spec),
                   "source": source_key(spec), "turn1": ps.turn_prompts(spec)[0]}
            if not a.no_snapshots:
                snap = ps.materialize(spec, SNAPSHOT_ROOT)
                meta = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
                row.update(tree_sha256=meta["tree_sha256"], hidden_sha256=ps.tree_hash(snap / "hidden"),
                           workspace_files=ps.workspace_stats(snap)["workspace_files"],
                           scope_gate_files=workspace_file_count(str(snap / "workspace"), 10 ** 9) + 1)
            else:
                row["workspace_files"] = (validation.get(spec.id) or {}).get("files")
            row["validated"] = (validation.get(spec.id) or {}).get("ok")
            rows.append(row)

    problems, notes = [], []
    # ------------------------------------------------------------------ constraints
    n = len(rows)
    if n != 60:
        problems.append(f"{n} scenarios, 60 required")
    by_type = {t: sum(1 for r in rows if r["task_type"] == t) for t in TYPES}
    by_fam = {f: sum(1 for r in rows if r["family"] == f) for f in FAMILIES}
    problems += [f"task type {t}: {c}, 10 required" for t, c in by_type.items() if c != 10]
    problems += [f"family {f}: {by_fam[f]}, {w} required" for f, w in WANT_FAMILY.items() if by_fam[f] != w]
    problems += [f"task types outside the six: {sorted({r['task_type'] for r in rows} - set(TYPES))}"] if set(r["task_type"] for r in rows) - set(TYPES) else []
    big_all = [r for r in rows if (r["workspace_files"] or 0) > SCOPE_LIMIT]
    big_gate = [r for r in rows if r.get("scope_gate_files", 0) > SCOPE_LIMIT]
    border = [r["id"] for r in rows if abs((r.get("scope_gate_files") or 0) - SCOPE_LIMIT) <= 5]
    if len(big_all) < 12 or (big_gate and len(big_gate) < 12):
        problems.append(f"scenarios with > {SCOPE_LIMIT} workspace files: {len(big_all)} (all files) / {len(big_gate)} (scope-gate count); 12 required")
    if border:
        notes.append(f"within 5 files of the scope-gate limit {SCOPE_LIMIT} (count differences could flip the gate): {border}")
    gaps = [r for r in rows if r["long_gaps"] >= 2]
    if len(gaps) < 6:
        problems.append(f"scenarios with >= 2 idle gaps: {len(gaps)}, 6 required")
    problems += [f"{r['id']}: {r['turns']} turns (8-16 required)" for r in rows if not 8 <= r["turns"] <= 16]
    problems += [f"{r['id']}: split {r['split']!r}, 'holdout' required" for r in rows if r["split"] != "holdout"]
    problems += [f"{r['id']}: not valid in the combined validator run" for r in rows if validation and not r["validated"]]
    if validation and set(validation) != {r["id"] for r in rows}:
        problems.append(f"validation covers {len(validation)} ids, panel has {len(rows)}")

    # ------------------------------------------------------------------ overlap
    old = load_old()
    old_ids = {s.id: nm for nm, s in old}
    old_src = [(nm, s, source_key(s)) for nm, s in old]
    overlap = {"identical": [], "same_upstream_other_commit": [], "same_slug_other_language": [], "same_slug_same_language": [],
               "similar_turn1": []}
    for r in rows:
        if r["id"] in old_ids:
            overlap["identical"].append(f"{r['id']}: same id as a {old_ids[r['id']]} scenario")
        k = r["source"]
        for nm, s, ok in old_src:
            if k["kind"] == "inline" and ok["kind"] == "inline" and k["files_sha"] == ok["files_sha"]:
                overlap["identical"].append(f"{r['id']}: inline workspace identical to {nm}/{s.id}")
            if k["kind"] == "git" and ok["kind"] == "git":
                if (k["repo"], k["sha"], k["subdir"]) == (ok["repo"], ok["sha"], ok["subdir"]):
                    overlap["identical"].append(f"{r['id']}: same repo@sha/subdir as {nm}/{s.id}")
                elif k["slug"] and k["slug"] == ok["slug"]:
                    key = "same_slug_same_language" if k["lang"] == ok["lang"] else "same_slug_other_language"
                    overlap[key].append(f"{r['id']} ({k['lang']}/{k['slug']}) vs {nm}/{s.id} ({ok['lang']}/{ok['slug']})")
                elif k["repo"] == ok["repo"] and not k["slug"]:
                    overlap["same_upstream_other_commit"].append(
                        f"{r['id']} ({k['repo'].rsplit('/', 2)[-2]}/{k['repo'].rsplit('/', 1)[-1]}@{k['sha'][:8]}) vs {nm}/{s.id} @{ok['sha'][:8]}")
        head = lambda t: t.split("\n\nRules:")[0].strip()          # the shared "Rules:" boilerplate is not content  # noqa: E731
        mine = head(r["turn1"])
        best = max(((difflib.SequenceMatcher(None, mine, head(ps.turn_prompts(s)[0])).ratio(), nm, s.id) for nm, s in old),
                   default=(0, "", ""))
        if best[0] > 0.8:
            overlap["similar_turn1"].append(f"{r['id']} turn 1 resembles {best[1]}/{best[2]} (ratio {best[0]:.2f})")
    # within the panel too
    seen = {}
    for r in rows:
        key = json.dumps(r["source"], sort_keys=True)
        if r["source"]["kind"] == "git" and r["source"]["subdir"] == "" and key in seen:
            overlap["identical"].append(f"{r['id']}: same repo@sha as {seen[key]} inside the panel")
        seen[key] = r["id"]
    problems += overlap["identical"] + [f"same language+exercise slug as an existing scenario: {x}" for x in overlap["same_slug_same_language"]]

    report = {"n": n, "by_type": by_type, "by_family": by_fam,
              "family_x_type": {f: {t: sum(1 for r in rows if r["family"] == f and r["task_type"] == t) for t in TYPES} for f in FAMILIES},
              "workspace_gt300_all_files": len(big_all), "workspace_gt300_scope_gate_count": len(big_gate),
              "with_ge2_idle_gaps": len(gaps), "turns": sorted(r["turns"] for r in rows),
              "overlap": overlap, "problems": problems, "notes": notes}
    print(json.dumps({k: v for k, v in report.items() if k != "overlap"}, indent=1))
    print("overlap:", json.dumps({k: v for k, v in overlap.items()}, indent=1))

    if a.write:
        if a.no_snapshots:
            raise SystemExit("--write needs snapshots (drop --no-snapshots)")
        entries = {r["id"]: {k: r[k] for k in ("file", "family", "task_type", "language", "turns", "long_gaps", "file_sha256",
                                               "scenario_hash", "prompt_sha256", "tree_sha256", "hidden_sha256",
                                               "workspace_files", "scope_gate_files")} for r in sorted(rows, key=lambda x: x["id"])}
        panel_sha = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
        (HERE / "scenario-hashes.json").write_text(json.dumps({
            "schema": "fast-decisions-v3-scenario-hashes/v1", "design": "holdout-v3", "n": n, "panel_sha256": panel_sha,
            "how": "file_sha256 = sha256 of the scenario YAML bytes; scenario_hash/prompt_sha256 = paired_scenarios.scenario_hash/"
                   "prompt_hash (what a plan freezes and every resume re-checks); tree_sha256 = paired_scenarios.tree_hash of the "
                   "frozen starting workspace (snapshot.json); hidden_sha256 = tree hash of the hidden grader files; "
                   "scope_gate_files = orchestrator.workspace_file_count(workspace) + 1 (the harness's settings.local.yaml)",
            "scenarios": entries}, indent=1) + "\n", encoding="utf-8")
        write_split_md(rows, report, panel_sha)
        print(f"wrote scenario-hashes.json (panel_sha256 {panel_sha}) and SPLIT.md")
    return 1 if problems else 0


def write_split_md(rows: list, report: dict, panel_sha: str) -> None:
    L = ["# holdout-v3: the S1 scenario panel (all `split: holdout`)", "",
         "No train/test division: all 60 scenarios are confirmatory for S1 (docs/design/v3/PLAN.md, S1). Dev-only data stays "
         "main-v1 (its test split already carried three confirmations). The frozen contract is `scenario-hashes.json` "
         f"(panel sha256 `{panel_sha}`); `panel.py` re-checks every constraint below from the files.", "",
         "## Constraints (PLAN S1) and the observed panel", "",
         "| constraint | required | observed |", "|---|---|---|",
         f"| scenarios | 60 | {report['n']} |",
         "| per task type | 10 each | " + ", ".join(f"{t} {c}" for t, c in report["by_type"].items()) + " |",
         "| families | polyglot 12, repos 20, mixed 16, knowledge 12 | " + ", ".join(f"{f} {c}" for f, c in report["by_family"].items()) + " |",
         f"| workspace files > 300 | >= 12 | {report['workspace_gt300_all_files']} (every file) / {report['workspace_gt300_scope_gate_count']} (scope-gate count) |",
         f"| >= 2 idle gaps (>= 300 s) | >= 6 | {report['with_ge2_idle_gaps']} |",
         f"| turns | 8-16 | {min(report['turns'])}-{max(report['turns'])} |",
         f"| overlap with main-v1 / pilot-v1 | none | {len(report['overlap']['identical'])} identical; see below |", "",
         "## Family x task type", "", "| family | " + " | ".join(TYPES) + " | total |", "|---|" + "---|" * (len(TYPES) + 1)]
    for f, d in report["family_x_type"].items():
        L.append(f"| {f} | " + " | ".join(str(d[t]) for t in TYPES) + f" | {sum(d.values())} |")
    L += ["", "## Overlap report (against main-v1: 70 scenarios, pilot-v1: 5)", ""]
    ov = report["overlap"]
    for key, title in (("identical", "Identical (id, repo@sha/subdir, inline tree): FAILS the check"),
                       ("same_slug_same_language", "Same exercise slug and language: FAILS the check"),
                       ("same_slug_other_language", "Same exercise slug, other language (reported, kept: a different task in a different language)"),
                       ("same_upstream_other_commit", "Same upstream repository, other commit/files (reported, kept: a different bug/feature and a different snapshot)"),
                       ("similar_turn1", "Turn-1 task text (the shared Rules boilerplate stripped) resembles an existing scenario's, ratio > 0.8 (reported)")):
        L += [f"- **{title}:** " + ("none" if not ov[key] else ""), *[f"  - {x}" for x in ov[key]]]
    L += ["", "## Scenarios", "",
          "| id | family | type | lang | turns | idle gaps | files | scope-gate files | source | scenario hash |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["family"], x["task_type"], x["id"])):
        s = r["source"]
        src = (f"{s['repo'].rsplit('github.com/', 1)[-1]}@{s['sha'][:8]}" + (f" `{s['subdir']}`" if s["subdir"] else "")) if s["kind"] == "git" else "inline (self-authored)"
        L.append(f"| {r['id']} | {r['family']} | {r['task_type']} | {r['language']} | {r['turns']} | {r['long_gaps']} | "
                 f"{r['workspace_files']} | {r.get('scope_gate_files')} | {src} | `{r['scenario_hash'][:12]}` |")
    (HERE / "SPLIT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
