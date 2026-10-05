"""Build the sanitized effort-control-fable-v1 evidence package from the RAW campaign directory (read-only).

    CAMPAIGNS=~/dev/afast-paired python3 package_evidence.py

Reads  <CAMPAIGNS>/effort-control-fable-v1 (schedule, plan, state, ledger, preflight, run.log, rows/, effort-fable-result.json, the memory-kill marker).
Writes data/, campaign/, result/ (effort-fable-result.json + sensitivity.json recomputed from data/pairs.jsonl), prereg/, summary.json and SHA256SUMS next to this script's parent directory.
README.md, RESULT.md and data/DATA-DICTIONARY.md are hand-written.  Never touches the raw tree; no model calls.

Same sanitization as ../../2026-10-05-effort-control/reproduce/package_evidence.py (the only transformations applied):
  * the home directory prefix becomes ~ ; the campaign root becomes <campaign>; the repo checkout becomes <repo>
  * free-text failure reasons (tails of agent terminal output captured by the harness) are cut at " -- " and replaced by a
    length + sha256 prefix (this campaign had no failures; the scrub is applied anyway)
  * any key that could hold prompt/response text aborts the build instead of being silently kept
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = str(Path.home())
RAW = Path(os.environ.get("CAMPAIGNS", Path.home() / "dev" / "afast-paired")).expanduser()
CAMP_RAW = RAW / "effort-control-fable-v1"
OUT = Path(__file__).resolve().parent.parent
REPO = OUT.parents[2]
REPLACEMENTS = [(str(CAMP_RAW), "<campaign>"), (str(RAW), "<campaigns>"), (str(Path.home() / "dev" / "fd-effort"), "<repo>"),
                (str(REPO), "<repo>"), (HOME, "~")]
FORBIDDEN_KEYS = {"prompt", "prompts", "response", "responses", "text", "content", "message", "messages", "stdout",
                  "stderr", "output_text", "tail", "transcript", "completion", "body"}
ITEM_SPLIT = re.compile(r"; (?=[A-Za-z0-9._-]+-r\d+-[a-z0-9]+-(?:fable|fable_medium): )")
PREREG = "evals/paired/PREREGISTRATION-effort-control-fable-v1.md"
PREREG_COMMIT = "249941c"        # the preregistration commit (design yaml, cell and preregistration); the analysis script followed in fd6289e
MEMKILL_SESSION = ("w020-a1", "py-go-counting-r2-any-fable")


def san_str(s: str) -> str:
    for a, b in REPLACEMENTS:
        s = s.replace(a, b)
    return s


def scrub_reason(s: str) -> str:
    out = []
    for item in ITEM_SPLIT.split(s):
        head, sep, tail = item.partition(" -- ")
        out.append(f"{head} -- [terminal tail omitted: {len(tail)} chars, sha256:{hashlib.sha256(tail.encode()).hexdigest()[:8]}]"
                   if sep else item[:300])
    return "; ".join(out)


def walk(v, key=None):
    if isinstance(v, dict):
        bad = FORBIDDEN_KEYS & set(v)
        if bad:
            raise SystemExit(f"refusing to package: field(s) {sorted(bad)} may hold prompt/response text")
        return {san_str(k): walk(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [walk(x, key) for x in v]
    if isinstance(v, str):
        return san_str(scrub_reason(v) if key == "reason" else v)
    return v


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], check=True, capture_output=True, text=True).stdout.strip()


def copy_rows(name: str, gz: bool) -> dict:
    src, dst = CAMP_RAW / "rows" / f"{name}.jsonl", OUT / "data"
    dst.mkdir(parents=True, exist_ok=True)
    target = dst / (name + ".jsonl" + (".gz" if gz else ""))
    n, body = 0, hashlib.sha256()
    fh = open(target, "wb")
    out = gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) if gz else fh
    with src.open(encoding="utf-8") as f:
        for line in f:
            b = (json.dumps(walk(json.loads(line)), default=str) + "\n").encode("utf-8")
            body.update(b)
            out.write(b)
            n += 1
    if gz:
        out.close()
    fh.close()
    return {"rows": n, "bytes": target.stat().st_size, "sha256": sha(target), "content_sha256": body.hexdigest(),
            "raw_sha256": sha(src), "file": target.name}


def copy_json(src: Path, dst: Path) -> None:
    w(dst, json.dumps(walk(json.loads(src.read_text(encoding="utf-8"))), indent=2, default=str) + "\n")


def copy_text(src: Path, dst: Path, per_line=None) -> None:
    lines = []
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True):
        lines.append(san_str(per_line(line) if per_line else line))
    w(dst, "".join(lines))


def scrub_log_line(line: str) -> str:
    m = re.match(r"^(\[[^\]]+\] attempt \d+: transient infrastructure failure: )(.*)$", line.rstrip("\n"))
    return (m.group(1) + scrub_reason(m.group(2)) + "\n") if m else line


def summary_json(res: dict, sens: dict) -> dict:
    c, q = res["cost"], res["quality"]
    st, an, mc = res["secondary_vs_main_v1_sticky_fable_host"], res["secondary_vs_main_v1_anchor_fable_host"], res["exploratory_mcnemar_final_pass"]
    return {
        "description": ("effort-control-fable-v1 (preregistered, 2026-10-05): plain Fable 5.1 at reasoning effort medium vs the provider default; "
                        "cost = geometric-mean ratio of tools-normalized session cost per scenario, 95% percentile CI from "
                        f"{res['resamples']:,} scenario-cluster bootstrap resamples (seed {res['seed']}). Row 1 is the confirmatory test-split endpoint "
                        f"(23 scenarios x 2 reps = 46 pairs, {res['n_valid_cost_pairs']} cost-valid); rows 2-3 are exploratory and non-concurrent "
                        "(n_pairs counts scenarios). Ratios below 1.0 mean the first arm is cheaper. Strict sensitivity (flagged-anchor pair excluded): "
                        f"{sens['strict_44']['cost']['geo_mean_ratio']:.3f}; see FLAGS.md."),
        "rows": [
            {"label": "fable_medium / fable (HF, test split, confirmatory)", "n_pairs": res["n_pairs"],
             "gm_ratio": c["geo_mean_ratio"], "ci95": c["ci95"]},
            {"label": "fable_medium / main-v1 sticky, Fable host (exploratory, non-concurrent)", "n_pairs": st["n_scenarios"],
             "gm_ratio": st["geo_mean_ratio"], "ci95": st["ci95"]},
            {"label": "fable_medium / main-v1 anchor, Fable host (exploratory, non-concurrent)", "n_pairs": an["n_scenarios"],
             "gm_ratio": an["geo_mean_ratio"], "ci95": an["ci95"]},
        ],
        "quality": {"label": "turn-pass delta, fable_medium minus fable (HF quality endpoint, unfiltered)", "n_pairs": res["n_pairs"],
                    "mean_delta_turn_pass": q["mean_delta_turn_pass"], "ci95": q["ci95"], "non_inferiority_margin": q["margin"],
                    "non_inferior": q["non_inferior"],
                    "final_pass_mcnemar": {"both_pass": mc["both_pass"], "only_medium_passes": mc["only_medium_passes"],
                                           "only_default_passes": mc["only_default_passes"], "exact_p_two_sided": mc["exact_p_two_sided"]}},
        "HF_supported": res["HF_supported"],
    }


def sensitivity(pairs_path: Path) -> dict:
    """Recomputes HF from the PUBLISHED pairs with the pair whose anchor session was cache-audit flagged excluded (the pair row
    copied only the arm's flag when the campaign ran), and with the memory-killed pair also dropped from the quality endpoint."""
    sys.path.insert(0, str(REPO / "evals"))
    import paired_effort as pe
    pairs = [json.loads(l) for l in pairs_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    strict = [dict(p, cache_audit_clean=False) if (p["scenario_id"], p["rep"]) == ("go-linkedlist", 1) else dict(p) for p in pairs]
    no_kill = [p for p in strict if (p["scenario_id"], p["rep"]) != ("py-go-counting", 2)]
    return {"as_run": pe.analyse(pairs, design="fable"),
            "strict_44": pe.analyse(strict, design="fable"),
            "strict_44_and_killed_pair_dropped_from_quality": pe.analyse(no_kill, design="fable"),
            "note": "strict_44 excludes the go-linkedlist rep 1 pair (flagged ANCHOR session); the third variant also drops the py-go-counting rep 2 pair (memory-killed anchor) from the unfiltered quality endpoint"}


def prereg_md(first_start: str, schedule_created: str) -> str:
    h, ct, subj = git("log", "--format=%H|%cI|%s", "-1", PREREG_COMMIT, "--").split("|", 2)
    t0 = dt.datetime.fromisoformat(first_start.replace("Z", "+00:00"))
    tp = dt.datetime.fromisoformat(ct)
    tsch = dt.datetime.fromisoformat(schedule_created)
    ok = tp < tsch < t0
    unchanged = not git("diff", h, "HEAD", "--", PREREG)
    L = ["# Preregistration provenance", "", "| file | commit | commit time | subject | blob sha |", "|---|---|---|---|---|",
         f"| `{PREREG}` | `{h[:12]}` | {ct} | {subj} | `{git('rev-parse', f'{h}:{PREREG}')[:12]}` |", "",
         "## Preregistration precedes the schedule and the data", "",
         f"* preregistration commit time: {ct} ({tp.astimezone(dt.timezone.utc).isoformat()})",
         f"* schedule (`campaign/schedule.json`) created: {schedule_created}  ({tsch - tp} AFTER the preregistration commit)",
         f"* first session `actual_start` in `data/sessions.jsonl`: {first_start}",
         f"* the preregistration commit is {t0 - tp} before the first session started; **{'PASS' if ok else 'FAIL'}** (commit < schedule < first session)",
         f"* the file is unchanged since that commit: `git diff {h[:7]} HEAD -- {PREREG}` is empty ({'yes' if unchanged else 'NO'}).",
         "", "What was committed when, stated plainly:",
         "* Commit `249941c` contained the design (`evals/paired/effort-control-fable-v1.yaml`), the `plain-medium` cell (`evals/cells.yaml`) and the "
         "preregistration. The analysis script change (`evals/paired_effort.py`, Fable design, seed 20261006, McNemar and per-task-type blocks) and its tests "
         "were committed 7 s later in `fd6289e`, still before the schedule was created. The schedule was built from a clean working tree at `fd6289e`.",
         "* Disclosed scratch feasibility check, run BEFORE the preregistration commit: a throwaway schedule in `~/dev/afast-paired/"
         "effort-control-fable-v1-preflight-scratch` (not the campaign schedule; not published) and a 2-session preflight (`plain`, `plain-medium`, $1.73) that "
         "confirmed Fable accepts the `reasoning_effort` parameter (`output_config.effort` absent vs `medium` on the main request). It was mechanism-only and "
         "produced no analysed outcome. The campaign itself ran its own 2-session preflight (`campaign/preflight.json`) before wave 1.",
         "* The preregistration states the analysis rules (endpoints, bootstrap, seed 20261006, margins, exploratory items) before any analysed session; the "
         "run order inside the schedule is seeded and was fixed at schedule creation.",
         "* One post-hoc item, labelled as such: the pair rows copied only the arm's cache-audit flag, so the pair whose ANCHOR session was flagged was kept "
         "as cost-valid. `FLAGS.md` reports the preregistered (as-run) result AND the strict sensitivity; the harness bug is fixed in a later commit "
         "(`build_pairs` now requires both sessions to be audit-clean) and the campaign rows were not regenerated.",
         "* Git commit times are author-controlled and the push time is not recorded in the repo, so ordering rests on commit timestamps.", ""]
    if not ok:
        raise SystemExit("preregistration/schedule/first-session ordering check FAILED")
    return "\n".join(L)


def main() -> None:
    data, camp = OUT / "data", OUT / "campaign"
    infos = {n: copy_rows(n, gz=(n == "requests")) for n in ("sessions", "turns", "pairs", "requests")}
    copy_json(CAMP_RAW / "rows" / "summary.json", data / "summary.json")
    for f in ("schedule.json", "state.json", "ledger.json", "preflight.json"):
        copy_json(CAMP_RAW / f, camp / f)
    copy_text(CAMP_RAW / "plan.txt", camp / "plan.txt")
    copy_text(CAMP_RAW / "run.log", camp / "run.log", scrub_log_line)
    copy_json(CAMP_RAW / "effort-fable-result.json", OUT / "result" / "effort-fable-result.json")
    res = json.loads((CAMP_RAW / "effort-fable-result.json").read_text(encoding="utf-8"))
    sens = sensitivity(data / "pairs.jsonl")
    w(OUT / "result" / "sensitivity.json", json.dumps(sens, indent=2) + "\n")
    w(OUT / "summary.json", json.dumps(summary_json(res, sens), indent=2) + "\n")
    copy_json(CAMP_RAW / MEMKILL_SESSION[0] / MEMKILL_SESSION[1] / "killed_memory.json", camp / "killed_memory.py-go-counting-r2-any-fable.json")

    first_start = min(json.loads(l)["actual_start"] for l in (data / "sessions.jsonl").read_text(encoding="utf-8").splitlines())
    sched = json.loads((camp / "schedule.json").read_text(encoding="utf-8"))["created_at"]
    w(OUT / "prereg" / "PREREGISTRATION-effort-control-fable-v1.md", (REPO / PREREG).read_text(encoding="utf-8"))
    w(OUT / "prereg" / "PROVENANCE.md", prereg_md(first_start, sched))

    # row counts + checksums of the data files for the dictionary pointer
    w(data / "FILES.json", json.dumps({k: v for k, v in infos.items()}, indent=1) + "\n")
    lines = [f"{sha(p)}  {p.relative_to(OUT).as_posix()}" for p in sorted(OUT.rglob("*"))
             if p.is_file() and p.name not in ("SHA256SUMS", "README.md") and "__pycache__" not in p.parts]
    w(OUT / "SHA256SUMS", "\n".join(lines) + "\n")
    json.dump({"infos": infos, "first_start": first_start}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
