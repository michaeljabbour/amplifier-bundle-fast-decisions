"""Build the arXiv edition: one LaTeX source with the main paper followed by the supplement as appendices A-I.

Copies the sources into arxiv/build, rewrites cross-document references into ordinary references, compiles once
with latexmk (pdflatex + bibtex), then flattens to arxiv/source/ (one comment-free main.tex, the matching main.bbl and
only the data files the build actually read), packs arxiv/arxiv-source.tar.gz, and writes arxiv/abstract.txt.
Run via `make arxiv`; test-compile the tarball with `make arxiv-test`."""
from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "arxiv"
BUILD, SRC = OUT / "build", OUT / "source"
SECTIONS = ["m1-intro", "m1b-claims", "m2-setting", "m3-choosing", "m4-routing", "m5-once", "m6-gate", "m7-telemetry",
            "m8-recommendations", "m9-limits", "m9b-statements", "m10-references"]
APPX = ["a-methods", "b-judges", "c-routing", "d-once", "e-risky", "f-telemetry", "g-s1", "h-reference", "i-index"]
MAIN_REWRITES = [(r"\ref{S-", r"\ref{"), (r"\cref{S-", r"\cref{"), (r"\Cref{S-", r"\Cref{"),
                 ("Supplement Sections~", "Appendices~"), ("Supplement Section~", "Appendix~"),
                 ("Supplement Table~", "Table~"), ("Supplement Figure~", "Figure~"), ("Supplement\nTable~", "Table~"),
                 ("Every supporting result is in the supplement.", "The appendices hold every supporting result."),
                 ("The supplement holds every supporting result.", "The appendices hold every supporting result."),
                 ("The supplement documents the correction.", "Appendix~\\ref{sec:f} documents the correction."),
                 ("the supplement gives\nready-to-use configurations", "Appendix~\\ref{sec:h} gives\nready-to-use configurations"),
                 ("The supplement gives\nready-to-use configurations", "Appendix~\\ref{sec:h} gives\nready-to-use configurations"),
                 ("Supplement figures and tables are numbered by supplement section (Figure~B.1, Table~G.1)",
                  "Appendix figures and tables are numbered by appendix (Figure~B.1, Table~G.1)")]
SUPP_REWRITES = [(r"\ref{M-", r"\ref{"), (r"\cref{M-", r"\cref{"), (r"\Cref{M-", r"\Cref{"),
                 (" of the main paper", " of the main text"), ("the main paper's ", "the main text's "),
                 ("this supplement", "these appendices"), ("This supplement", "These appendices")]
HEADER = r"""\documentclass[11pt,letterpaper]{article}
\input{preamble}
\hypersetup{
  pdftitle={Where a Decision Model Fits in an Agent Harness},
  pdfauthor={Michael J. Jabbour; David Koleczek},
  pdfsubject={Decision models in AI agent harnesses (arXiv edition of technical report v5.1, October 8, 2026)},
  pdfkeywords={decision models; model routing; prompt caching; reasoning effort; AI agents; preregistration; paired measurement},
  pdflang={en-US}, pdfdisplaydoctitle=true, pdfcreationdate={D:20261008000000}, pdfmoddate={D:20261008000000},
  colorlinks=true, linkcolor=okblue!65!black, urlcolor=okblue!65!black, citecolor=okblue!65!black,
  bookmarksnumbered=true, bookmarksopen=true,
}
\newcommand{\supp}[1]{Appendix~\ref{#1}}
\newcommand{\TkSupp}[1]{App.~\ref{#1}}
\newcommand{\suppfig}[1]{Figure~\ref{#1}}
\newcommand{\supptab}[1]{Table~\ref{#1}}
\newcommand{\StSec}[1]{Appendix~\ref{#1}}
\newcommand{\StSecs}[2]{Appendices~\ref{#1} and~\ref{#2}}
\newcommand{\thesupp}{the appendices}\newcommand{\Thesupp}{The appendices}\newcommand{\suppword}{appendices}
\newcommand{\mainpaper}{the main text}\newcommand{\thissupp}{these appendices}\newcommand{\Thissupp}{These appendices}
\newcommand{\StTab}[1]{Table~\ref{#1}}
\newcommand{\mainref}[1]{Section~\ref{#1}}
\input{figures/fig-fz.tex}
\begin{document}
\thispagestyle{plain}
\begin{center}
  {\LARGE\sffamily\bfseries Where a Decision Model Fits\\[3pt] in an Agent Harness\par}
  \vspace{10pt}
  {\large Michael J.\ Jabbour \qquad David Koleczek\par}
  \vspace{3pt}
  {\normalsize Microsoft, Office of the CTO\par}
  \vspace{3pt}
  {\normalsize October 8, 2026\par}
\end{center}
\vspace{4pt}
\input{sections/m0-abstract}
"""


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"{' '.join(cmd)} failed in {cwd}:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")
    return r


def write_metadata(clean: Path) -> None:
    """ASCII metadata for the arXiv submission form; every count comes from the clean compile of the tarball."""
    info = run(["pdfinfo", str(clean / "main.pdf")], HERE).stdout
    pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    text = run(["pdftotext", str(clean / "main.pdf"), "-"], HERE).stdout
    first_appx = next(i for i in range(1, pages + 1)
                      if re.search(r"^A\s*$", run(["pdftotext", "-f", str(i), "-l", str(i), str(clean / "main.pdf"), "-"], HERE).stdout, re.M))
    main_pages = first_appx - 1
    figs = (clean / "main.lof").read_text().count(r"\contentsline {figure}")
    tabs = (clean / "main.lot").read_text().count(r"\contentsline {table}")
    repo = "https://github.com/michaeljabbour/amplifier-bundle-fast-decisions"
    (OUT / "metadata.txt").write_text(f"""Title: Where a Decision Model Fits in an Agent Harness

Authors: Michael J. Jabbour (1), David Koleczek (1) ((1) Microsoft, Office of the CTO)

Abstract: see abstract.txt (ASCII, {len((OUT / 'abstract.txt').read_text().strip())} characters; paste without the word "Abstract")

Comments: {main_pages} pages main text + {pages - main_pages}-page appendix; {figs} figures, {tabs} tables. Code and data: {repo}

Primary category: cs.SE (Software Engineering)
Cross-lists: cs.AI, cs.LG
ACM-class: D.2.8; I.2.11

License: CC BY 4.0 (recommended; pending Microsoft legal review)

Report-no: none (no institutional report number has been issued)
Journal-ref: none
DOI: none
""")
    (OUT / "README.txt").write_text(f"""arXiv edition of "Where a Decision Model Fits in an Agent Harness" (technical report v5.1, October 8, 2026)

Contents of this directory
  arxiv-source.tar.gz              upload this file (flat TeX source: main.tex, main.bbl, plotted data and label files)
  decision-model-fit-v5-arxiv.pdf  the PDF this source compiles to ({pages} pages: main text, then appendices A-I)
  abstract.txt                     ASCII abstract for the metadata form (no "Abstract" prefix)
  metadata.txt                     title, authors, comments, categories, license
  source/                          the unpacked tarball, for inspection

Upload steps
  1. Rebuild from the paper directory: `make arxiv` (regenerates the source, then test-compiles the tarball alone
     with pdflatex three times, as arXiv does, and fails on any error or undefined reference).
  2. Log in to arxiv.org with an account endorsed for cs.SE (request endorsement first if needed).
  3. Start a new submission; choose the license in metadata.txt only after Microsoft legal has confirmed it
     (the choice is irrevocable).
  4. Upload arxiv-source.tar.gz and select PDFLaTeX as the processor. arXiv compiles main.tex using main.bbl
     (no .bib is needed); the shipped PDF here is exactly that clean compile.
  5. Paste the metadata from metadata.txt and abstract.txt. Authors: Michael J. Jabbour and David Koleczek only;
     arXiv does not allow AI tools as authors. The paper's Statements section carries the AI-use disclosure.
  6. Check the compiled preview: page count, figures, references, appendix cross-references.
  7. Submit before 14:00 US Eastern for same-day announcement; check the HTML rendering after announcement.

Before submitting (decisions for the lead; not changed by the build)
  - License: CC BY 4.0 is recommended but pending Microsoft legal review; the arXiv choice is irrevocable.
  - ORCID iDs: link each author's ORCID to their arXiv profile (no source change needed).
  - Author consent: both authors must confirm the author list, affiliation and the competing-interests statement.
  - Endorsement: the submitting account needs cs.SE endorsement (institutional email or an endorser).
  - Authorship: the two review PDFs list Amplifier as an author; arXiv forbids AI authors, so this edition lists
    only Michael J. Jabbour and David Koleczek and discloses Amplifier's role in the AI-use statement.
  - Data and code: the statement cites git tag report-v5.1; create and push that tag before submitting.

Notes
  - Figures are pgfplots drawn at compile time from the shipped data files; there are no image files.
  - All fonts are Type 1 (Libertinus, Bera Mono) from TeX Live 2025; no Type 3 fonts.
  - The review editions (main paper + separate supplement PDF) are built by `make FINAL=1`; arXiv does not
    accept a separate supplement, so this edition appends it as appendices.
""")


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(SRC, ignore_errors=True)
    BUILD.mkdir(parents=True)
    for d in ("sections", "supp", "figures", "generated"):
        shutil.copytree(HERE / d, BUILD / d, ignore=shutil.ignore_patterns("src", "*.json", "__pycache__"))
    for f in ("preamble.tex", "refs.bib"):
        shutil.copy(HERE / f, BUILD / f)
    pre = BUILD / "preamble.tex"   # keep TeX Live's glyphtounicode as an \input, do not let the flattener inline it
    pre.write_text(pre.read_text().replace(r"\input{glyphtounicode}", r"\csname input\endcsname{glyphtounicode}"))
    for p in (BUILD / "sections").glob("*.tex"):
        t = p.read_text()
        for a, b in MAIN_REWRITES:
            t = t.replace(a, b)
        p.write_text(t)
    for p in list((BUILD / "supp").rglob("*.tex")) + list((BUILD / "generated").rglob("*.tex")):
        t = p.read_text()
        for a, b in SUPP_REWRITES:
            t = t.replace(a, b)
        p.write_text(t)
    h = BUILD / "supp/h-reference.tex"   # the statements already close the main text
    t = h.read_text()
    h.write_text(t[:t.index(r"\subsection{Statements}")])
    body = "\n".join(rf"\input{{sections/{s}}}" for s in SECTIONS)
    appx = "\n".join(rf"\input{{supp/{s}}}" for s in APPX)
    (BUILD / "main.tex").write_text(HEADER + body + "\n\\clearpage\n\\appendix\n"
                                    + r"\counterwithin*{figure}{section}\counterwithin*{table}{section}" + "\n"
                                    + r"\renewcommand{\thefigure}{\thesection.\arabic{figure}}" + "\n"
                                    + r"\renewcommand{\thetable}{\thesection.\arabic{table}}" + "\n"
                                    + appx + "\n\\end{document}\n")
    run(["latexmk", "-pdf", "-recorder", "-interaction=nonstopmode", "-halt-on-error", "main.tex"], BUILD)
    SRC.mkdir(parents=True)
    flat = run(["latexpand", "--empty-comments", "main.tex"], BUILD).stdout
    flat = re.sub(r"(?m)^[ \t]*%[^\n]*\n", "", flat)               # comment-only lines
    flat = re.sub(r"(?<!\\)%[^\n]*$", "%", flat, flags=re.M)       # trailing comments, keep the line-joining %
    (SRC / "main.tex").write_text(flat)
    shutil.copy(BUILD / "main.bbl", SRC / "main.bbl")
    # .tex files read from inside macros (figure label files) are not inlined by latexpand; ship exactly those
    todo, seen = [flat], set()
    while todo:
        for name in re.findall(r"\\input\{([^}#\\]+)\}", todo.pop()):
            f = name if name.endswith(".tex") else name + ".tex"
            if f in seen or not (BUILD / f).is_file():
                continue
            seen.add(f)
            (SRC / f).parent.mkdir(parents=True, exist_ok=True)
            body = re.sub(r"(?m)^[ \t]*%[^\n]*\n", "", (BUILD / f).read_text())
            (SRC / f).write_text(body)
            todo.append(body)
    param_inputs = []  # \input{...#1...} patterns that latexpand cannot inline
    for name in re.findall(r"\\input\{([^}]*#[^}]*)\}", flat):
        pat = re.escape(name if name.endswith(".tex") else name + ".tex")
        param_inputs.append(re.sub(r"\\#[0-9]", ".+", pat))
    for line in (BUILD / "main.fls").read_text().splitlines():
        if not line.startswith("INPUT ") or line[6:].startswith("/"):
            continue
        rel = Path(line[6:].removeprefix("./"))
        if rel.suffix == ".tex" and any(re.fullmatch(pat, str(rel)) for pat in param_inputs) and (BUILD / rel).is_file():
            pass  # read through a parameterised \input inside a macro (label and plot files); ship it
        elif rel.suffix in {".tex", ".aux", ".bbl", ".toc", ".lof", ".lot", ".out", ".bib", ".bst"} or not (BUILD / rel).is_file():
            continue
        (SRC / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(BUILD / rel, SRC / rel)
    bad = [str(p.relative_to(SRC)) for p in SRC.rglob("*") if p.is_file() and not re.fullmatch(r"[A-Za-z0-9_+\-.,=/]+", str(p.relative_to(SRC)))]
    if bad:
        raise SystemExit(f"filenames arXiv will reject: {bad}")
    def owner0(ti):
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti
    with tarfile.open(OUT / "arxiv-source.tar.gz", "w:gz") as tar:
        for p in sorted(SRC.rglob("*")):
            if p.is_file():
                tar.add(p, arcname=str(p.relative_to(SRC)), filter=owner0)
    clean = OUT / "clean-compile"            # compile the tarball alone, three pdflatex passes, as arXiv does
    shutil.rmtree(clean, ignore_errors=True)
    clean.mkdir()
    with tarfile.open(OUT / "arxiv-source.tar.gz") as tar:
        tar.extractall(clean, filter="data")
    for _ in range(3):
        run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"], clean)
    log = (clean / "main.log").read_text(errors="ignore")
    if re.search(r"undefined|Overfull|Underfull|LaTeX Error", log):
        raise SystemExit("clean compile of the tarball has warnings; see arxiv/clean-compile/main.log")
    def pages_text(pdf):
        txt = run(["pdftotext", str(pdf), "-"], HERE).stdout
        return txt.count("\f"), " ".join(txt.split())
    n_build, t_build = pages_text(BUILD / "main.pdf")
    n_clean, t_clean = pages_text(clean / "main.pdf")
    if n_build != n_clean or t_build != t_clean:
        print(f"arxiv: note: working build ({n_build} pp) and clean compile ({n_clean} pp) differ; shipping the clean compile")
    shutil.copy(clean / "main.pdf", OUT / "decision-model-fit-v5-arxiv.pdf")
    run(["python3", str(HERE / "check_abstract.py"), "--write", str(OUT / "abstract.txt")], HERE)
    write_metadata(clean)
    shutil.rmtree(clean)
    shutil.rmtree(BUILD)
    print("arxiv: wrote", OUT / "decision-model-fit-v5-arxiv.pdf", "and", OUT / "arxiv-source.tar.gz")


if __name__ == "__main__":
    main()
