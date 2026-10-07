"""Import the judge-benchmark assets (Part I) from committed sources on another branch.

`git archive` extracts the judge-benchmark, trace-benchmark and caching-survey evidence, the judge-bench eval
files and the judge-benchmark paper's own build code from REF into generated/src/judge-realistic/, runs that
paper's build_assets.py there (its numbers come only from that extracted evidence), and copies its generated
numbers, tables, data, labels and (path-rewritten) figure sources into generated/jb/.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REF = "94bb7b58ab75b71ce095a4eda9c19822765e7b55"  # pinned commit (origin/main when the v3 review revision was made)
PATHS = ["docs/evidence/2026-09-30-judge-benchmark", "docs/evidence/2026-09-30-judge-comparison",
         "docs/evidence/2026-10-01-trace-judge-benchmark", "docs/evidence/2026-10-01-caching",
         "evals/judge_bench", "evals/STUDY-DESIGN.md", "docs/papers/2026-09-30-judge-benchmark"]


def run(repo: Path, out: Path) -> Path:
    src = out / "src" / "judge-realistic"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)
    try:
        blob = subprocess.run(["git", "-C", str(repo), "archive", REF, *PATHS], capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"jb_import: cannot archive {REF} (fetch it first): {exc.stderr.decode()}")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(src, filter="data")
    paper = src / "docs" / "papers" / "2026-09-30-judge-benchmark"
    r = subprocess.run([sys.executable, "build_assets.py"], cwd=paper, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"jb_import: judge-benchmark build_assets.py failed:\n{r.stderr[-2000:]}")
    jb = out / "jb"
    if jb.exists():
        shutil.rmtree(jb)
    shutil.copytree(paper / "generated", jb)
    (jb / "figures").mkdir()
    for f in (paper / "figures").glob("*.tex"):
        (jb / "figures" / f.name).write_text(f.read_text().replace("generated/", "generated/jb/"))
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", REF], capture_output=True, text=True,
                         check=True).stdout.strip()
    return src, sha
