"""Build the sanitized holdout-v3 (S1) evidence package from the RAW campaign directory (read-only).

    CAMPAIGNS=~/dev/afast-paired python3 package_evidence.py

Reads  <CAMPAIGNS>/holdout-v3 (schedule, plan, state, ledger, preflight, run.log, supervisor.log, rows/).
Writes data/, campaign/, prereg/, result/ (s1_result.json recomputed from the PUBLISHED data/sessions.jsonl with the preregistered
command, plus two exploratory robustness reruns) and SHA256SUMS next to this script's parent directory.
README.md, RESULT.md, FLAGS.md, FAILURES.md and data/DATA-DICTIONARY.md are hand-written.  Never touches the raw tree; no model calls.

Sanitization (the only transformations): home prefix -> ~, campaign root -> <campaign>, repo checkout -> <repo>; free-text failure reasons
(tails of agent terminal output captured by the harness) are cut at " -- " and replaced by a length + sha256 prefix; any key that could
hold prompt/response text aborts the build.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = str(Path.home())
RAW = Path(os.environ.get("CAMPAIGNS", Path.home() / "dev" / "afast-paired")).expanduser()
CAMP_RAW = RAW / "holdout-v3"
OUT = Path(__file__).resolve().parent.parent
REPO = OUT.parents[2]
REPLACEMENTS = [(str(CAMP_RAW), "<campaign>"), (str(RAW), "<campaigns>"), (str(Path.home() / "dev" / "fd-v3"), "<repo>"),
                (str(REPO), "<repo>"), (HOME, "~")]
FORBIDDEN_KEYS = {"prompt", "prompts", "response", "responses", "text", "content", "message", "messages", "stdout",
                  "stderr", "output_text", "tail", "transcript", "completion", "body"}
ITEM_SPLIT = re.compile(r"; (?=[A-Za-z0-9._-]+-r\d+-(?:fable|opus|any)-[a-z_]+: )")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PREREG = "evals/paired/PREREGISTRATION-holdout-v3.md"
PREREG_COMMIT = "6ea0fd3"
FROZEN_FILES = ["evals/paired/PREREGISTRATION-holdout-v3.md", "evals/paired/holdout-v3.yaml", "evals/cells.yaml", "evals/paired.py",
                "evals/v3/s1_analysis.py", "evals/v3/frozen_rule.json", "evals/v3/rules.py",
                "evals/paired/scenarios/holdout-v3/scenario-hashes.json"]
CMD_SEED, CMD_RESAMPLES = "20261005", "10000"


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
        return san_str(scrub_reason(v) if key in ("reason", "excluded_reason") else v)
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


def scrub_log_line(line: str) -> str:
    line = ANSI.sub("", line.rstrip("\n"))
    m = re.match(r"^(\[[^\]]+\] attempt \d+: transient infrastructure failure: )(.*)$", line)
    return ((m.group(1) + scrub_reason(m.group(2))) if m else line) + "\n"


def copy_log(src: Path, dst: Path) -> None:
    w(dst, "".join(san_str(scrub_log_line(l)) for l in src.read_text(encoding="utf-8", errors="replace").splitlines()))


def run_analysis(sessions: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["nice", "-n", "10", sys.executable, str(REPO / "evals" / "v3" / "s1_analysis.py"), "--sessions", str(sessions),
                    "--out", str(out), "--resamples", CMD_RESAMPLES, "--seed", CMD_SEED], check=True, capture_output=True, cwd=REPO)


def robustness(sessions: Path) -> None:
    rows = [json.loads(l) for l in sessions.read_text(encoding="utf-8").splitlines() if l.strip()]
    for name, drop in (("drop_bleach", {"bleach-sanitize-review"}),
                       ("drop_bleach_and_black_pipeline", {"bleach-sanitize-review", "black-pipeline-explain"})):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sessions.jsonl"
            p.write_text("".join(json.dumps(r) + "\n" for r in rows if r["scenario_id"] not in drop), encoding="utf-8")
            run_analysis(p, OUT / "result" / f"robustness-{name}")


def prereg_md(first_start: str, schedule_created: str, builds: list) -> str:
    h, ct, subj = git("log", "--format=%H|%cI|%s", "-1", PREREG_COMMIT, "--").split("|", 2)
    t0 = dt.datetime.fromisoformat(first_start.replace("Z", "+00:00"))
    tp = dt.datetime.fromisoformat(ct)
    tsch = dt.datetime.fromisoformat(schedule_created)
    ok = tp < tsch < t0
    if not ok:
        raise SystemExit("preregistration/schedule/first-session ordering check FAILED")
    rows = []
    for f in FROZEN_FILES:
        changed = git("diff", "--stat", h, "HEAD", "--", f)
        rows.append(f"| `{f}` | `{sha(REPO / f)[:16]}` | {'unchanged since the commit' if not changed else 'CHANGED: ' + changed.splitlines()[-1]} |")
    L = ["# Preregistration provenance", "", "| file | commit | commit time | subject | blob sha |", "|---|---|---|---|---|",
         f"| `{PREREG}` | `{h[:12]}` | {ct} | {subj} | `{git('rev-parse', f'{h}:{PREREG}')[:12]}` |", "",
         "## Preregistration precedes the schedule and the data", "",
         f"* preregistration commit time: {ct} ({tp.astimezone(dt.timezone.utc).isoformat()})",
         f"* schedule (`campaign/schedule.json`) created: {schedule_created}  ({tsch - tp} AFTER the preregistration commit)",
         f"* first session `actual_start` in `data/sessions.jsonl`: {first_start}",
         f"* the preregistration commit is {t0 - tp} before the first session started; **{'PASS' if ok else 'FAIL'}** (commit < schedule < first session)",
         f"* every session row carries `build_sha` = {', '.join('`' + b + '`' for b in builds)}: the campaign ran the code at the preregistration commit.",
         "", "## Frozen inputs, checked against the preregistration commit (`git diff 6ea0fd3 HEAD`)", "",
         "| file | sha256 (first 16) | status |", "|---|---|---|", *rows, "",
         "Stated plainly:",
         "* Commit `6ea0fd3` is the preregistration; the design, cells, analysis script, frozen rule and scenario hashes were committed before it (`a11c24e`, `180c7cf`) and are unchanged since.",
         "* Disclosed before the commit and never analysed: the 60-session smoke (`evals/paired/holdout-v3-smoke.yaml`), and a 10-cell preflight ($4.78; `evals/paired/holdout-v3-preflight.json`).",
         "  The campaign also ran its own 8-session preflight before wave 1 (`campaign/preflight.json`); preflights are in the ledger ($6.96 for the two preflight entries).",
         "* The run did NOT follow the preregistered stop rules in two ways, disclosed in `FAILURES.md` and `FLAGS.md`: the budget cap was raised 5000 -> 6300 on 2026-10-06 07:11 EDT, and mechanism-gate failures",
         "  were not detected live (the gate is evaluated when rows are extracted), so the preregistered \"stop\" did not occur.",
         "* Git commit times are author-controlled and the push time is not recorded in the repo, so ordering rests on commit timestamps.", ""]
    return "\n".join(L)


def main() -> None:
    data, camp = OUT / "data", OUT / "campaign"
    infos = {n: copy_rows(n, gz=(n == "requests")) for n in ("sessions", "turns", "pairs", "requests")}
    copy_json(CAMP_RAW / "rows" / "summary.json", data / "summary.json")
    for f in ("schedule.json", "state.json", "ledger.json", "preflight.json"):
        copy_json(CAMP_RAW / f, camp / f)
    copy_log(CAMP_RAW / "plan.txt", camp / "plan.txt")
    copy_log(CAMP_RAW / "run.log", camp / "run.log")
    copy_log(CAMP_RAW / "supervisor.log", camp / "supervisor.log")

    run_analysis(data / "sessions.jsonl", OUT / "result")
    shutil.copyfile(OUT / "result" / "s1_result.json", OUT / "s1_result.json")
    robustness(data / "sessions.jsonl")

    rows = [json.loads(l) for l in (data / "sessions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    first_start = min(r["actual_start"] for r in rows)
    builds = sorted({r["build_sha"] for r in rows})
    sched = json.loads((camp / "schedule.json").read_text(encoding="utf-8"))["created_at"]
    w(OUT / "prereg" / "PREREGISTRATION-holdout-v3.md", (REPO / PREREG).read_text(encoding="utf-8"))
    w(OUT / "prereg" / "FREEZE-CHECKLIST.md", (REPO / "evals/paired/prereg-holdout-v3/PROVENANCE.md").read_text(encoding="utf-8"))
    w(OUT / "prereg" / "PROVENANCE.md", prereg_md(first_start, sched, builds))

    w(data / "FILES.json", json.dumps(infos, indent=1) + "\n")
    lines = [f"{sha(p)}  {p.relative_to(OUT).as_posix()}" for p in sorted(OUT.rglob("*"))
             if p.is_file() and p.name not in ("SHA256SUMS", "README.md") and "__pycache__" not in p.parts]
    w(OUT / "SHA256SUMS", "\n".join(lines) + "\n")
    json.dump({"infos": infos, "first_start": first_start}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
