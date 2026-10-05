#!/usr/bin/env python3
"""Preregistered train/test split of the main-v1 scenarios (seed 20261002). Pure function of the scenario files.

Method (written into every file's `split:` line and into SPLIT.md / split.json):
  * stratum  = (family, gap pattern) where family is the directory (polyglot / repos / mixed / knowledge) and gap pattern is
               "long-gaps" (the scenario has any 7-minute gap) or "no-gaps";
  * unit     = one upstream project. repos/knowledge scenarios are grouped by upstream repository URL (so lark-discard and
               lark-template always share a split); a polyglot exercise and an inline (authored) fixture are each their own
               project, because the polyglot-benchmark repo is a corpus, not a project. A multi-scenario unit takes the
               stratum of its first member by id;
  * test share = 1/3 overall: floor(n/3) per stratum, the remaining test slots go to the strata with the largest
               fractional remainders (ties broken by the seeded RNG); inside a stratum units are shuffled with the seeded RNG
               (units sorted by key first) and filled into test while the stratum is under its quota.
Run: python3 evals/paired/scenarios/main-v1/assign_split.py [--check]   (--check exits 1 if files disagree; no writes)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
import paired_scenarios as ps  # noqa: E402

SEED = 20261002
FAMILIES = ("polyglot", "repos", "mixed", "knowledge")
SPLIT_LINE = re.compile(r"^split:\s*\S+\s*$", re.M)
ps.SPLITS = tuple(dict.fromkeys(ps.SPLITS + ("main",)))        # files still carrying `split: main` must parse


def unit_key(spec, family: str) -> str:
    ws = spec.workspace
    if family in ("repos", "knowledge") and ws.get("kind") == "git":
        return re.sub(r"\.git$", "", ws["repo"].lower())
    return f"{family}/{spec.id}"


def load() -> list:
    rows = []
    for fam in FAMILIES:
        for f in sorted((HERE / fam).glob("*.yaml")):
            spec = ps.parse(yaml.safe_load(f.read_text(encoding="utf-8")), str(f))
            rows.append({"family": fam, "id": spec.id, "path": f, "unit": unit_key(spec, fam), "long_gaps": spec.n_long_gaps > 0,
                         "turns": len(spec.turns), "task_type": spec.task_type, "language": spec.language})
    return rows


def assign(rows: list, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    units = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r["family"], r["id"])):
        units[r["unit"]].append(r)
    strata = defaultdict(list)                                   # (family, long_gaps) -> [unit key]
    for key, members in units.items():
        first = members[0]
        strata[(first["family"], first["long_gaps"])].append(key)
    total = sum(len(units[k]) for ks in strata.values() for k in ks)
    want_total = round(total / 3)
    sizes = {st: sum(len(units[k]) for k in ks) for st, ks in strata.items()}
    quota = {st: n // 3 for st, n in sizes.items()}
    extra = want_total - sum(quota.values())
    order = sorted(strata, key=lambda st: (-(sizes[st] / 3 - quota[st]), rng.random(), st))
    for st in order[:max(extra, 0)]:
        quota[st] += 1
    split = {}
    for st in sorted(strata):
        keys = sorted(strata[st])
        rng.shuffle(keys)
        n_test = 0
        for key in keys:
            to_test = n_test < quota[st]
            for m in units[key]:
                split[m["id"]] = "test" if to_test else "train"
            n_test += len(units[key]) if to_test else 0
    return {"split": split, "quota": {f"{f}/{'long-gaps' if g else 'no-gaps'}": q for (f, g), q in quota.items()},
            "sizes": {f"{f}/{'long-gaps' if g else 'no-gaps'}": n for (f, g), n in sizes.items()}}


def table(rows: list, split: dict) -> dict:
    out = defaultdict(lambda: {"train": 0, "test": 0})
    for r in rows:
        out[(r["family"], "long-gaps" if r["long_gaps"] else "no-gaps")][split[r["id"]]] += 1
        out[(r["family"], "ALL")][split[r["id"]]] += 1
        out[("ALL", "ALL")][split[r["id"]]] += 1
    return out


def render_md(rows: list, res: dict) -> str:
    split, t = res["split"], table(rows, res["split"])
    L = ["# main-v1 train/test split (preregistered)", "",
         f"- Seed: **{SEED}** (python `random.Random`); written into every scenario file's `split:` line and `split.json`.",
         "- Reproduce / verify: `python3 evals/paired/scenarios/main-v1/assign_split.py --check` (a pure function of the files).",
         "- Target: 2/3 train, 1/3 test (23 of 70 test).", "", "## Method", "",
         "1. **Stratum** = (family, gap pattern). Family is the directory (polyglot / repos / mixed / knowledge); gap pattern is "
         "*long-gaps* (any 7-minute gap in the script) vs *no-gaps*.",
         "2. **Unit** = one upstream project, so scenarios from the same upstream repository share a split: repos and knowledge "
         "scenarios are grouped by repository URL (only `lark-discard` + `lark-template` share one); each polyglot exercise "
         "and each authored (inline) fixture is its own unit (the polyglot-benchmark repo is a corpus, not a project). "
         "A unit takes the stratum of its first member by id.",
         "3. **Quota**: floor(n/3) test slots per stratum, the rest of the 23 go to the strata with the largest fractional "
         "remainders (ties by the seeded RNG). Within a stratum, units are sorted by key, shuffled with the seeded RNG and "
         "filled into *test* until the quota is met; the rest are *train*.", "",
         "## Counts", "", "| family | gap pattern | train | test |", "|---|---|---:|---:|"]
    for (fam, gp) in sorted(t, key=lambda k: (k[0] == "ALL", k[0], k[1] == "ALL", k[1])):
        L.append(f"| {fam} | {gp} | {t[(fam, gp)]['train']} | {t[(fam, gp)]['test']} |")
    L += ["", "pilot-v1 (5 scenarios) keeps `split: pilot` and is outside this split.", "", "## Assignment", ""]
    for part in ("test", "train"):
        L += [f"### {part} ({sum(1 for v in split.values() if v == part)})", ""]
        for fam in FAMILIES:
            ids = [r for r in rows if r["family"] == fam and split[r["id"]] == part]
            L.append(f"- **{fam}** ({len(ids)}): " + ", ".join(f"{r['id']}{' [gaps]' if r['long_gaps'] else ''}" for r in ids))
        L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    rows = load()
    res = assign(rows)
    if a.check:
        bad = []
        for r in rows:
            m = SPLIT_LINE.search(r["path"].read_text(encoding="utf-8"))
            if not m or m.group(0).split(":")[1].strip() != res["split"][r["id"]]:
                bad.append(r["id"])
        print("OK: files match the seeded assignment" if not bad else f"MISMATCH: {bad}")
        return 1 if bad else 0
    for r in rows:
        text = r["path"].read_text(encoding="utf-8")
        assert len(SPLIT_LINE.findall(text)) == 1, r["path"]
        r["path"].write_text(SPLIT_LINE.sub(f"split: {res['split'][r['id']]}", text), encoding="utf-8")
    (HERE / "SPLIT.md").write_text(render_md(rows, res), encoding="utf-8")
    (HERE / "split.json").write_text(json.dumps({"seed": SEED, "quota": res["quota"], "sizes": res["sizes"], "split": res["split"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_md(rows, res).split("## Assignment")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
