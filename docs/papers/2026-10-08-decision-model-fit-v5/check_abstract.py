"""Abstract check (build-failing): the shared abstract (sections/abstract-body.tex) rendered as plain ASCII text must be
one paragraph of at most 250 words and 1,920 characters (arXiv metadata limit), contain no TeX or non-ASCII
characters, and appear unchanged on page 1 of both PDFs. `--write PATH` also writes the ASCII text for arXiv."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_WORDS, MAX_CHARS = 250, 1920
MACROS: dict[str, str] = {}
for f in ("generated/numbers.tex", "generated/jb/numbers.tex"):
    t = (HERE / f).read_text()
    for m in re.finditer(r"\\newcommand\{\\(\w+)\}\{", t):
        i, depth = m.end(), 1
        while depth:
            depth += {"{": 1, "}": -1}.get(t[i], 0)
            i += 1
        MACROS[m.group(1)] = t[m.end():i - 1]
HELPERS = {"TkTitle": "\\Tk{}Title", "TkHead": "\\Tk{}Head", "TkLabel": "{{[}}\\Tk{}Label{{]}}"}


def expand(s: str, depth: int = 0) -> str:
    if depth > 10:
        raise SystemExit("abstract: macro expansion too deep")
    for name, pat in HELPERS.items():
        s = re.sub(r"\\" + name + r"\{(\w+)\}", lambda m: pat.format(m.group(1)), s)
    return re.sub(r"\\(\w+)", lambda m: expand(MACROS[m.group(1)], depth + 1) if m.group(1) in MACROS else m.group(0), s)


def plain(tex: str, ascii_out: bool) -> str:
    s = expand(re.sub(r"(?m)%.*$", "", tex))
    reps = [(r"\X", "x" if ascii_out else "×"), (r"\,\%", "%"), (r"\%", "%"), (r"\$", "$"), ("{,}", ","),
            ("--", "-" if ascii_out else "–"), ("$-$", "-" if ascii_out else "−"), (r"\,", ""), ("\\ ", " "), ("~", " "),
            ("{[}", "["), ("{]}", "]")]
    for a, b in reps:
        s = s.replace(a, b)
    s = re.sub(r"\\[a-zA-Z]+\*?", "", s).replace("{", "").replace("}", "")
    return " ".join(s.split())


src = (HERE / "sections/abstract-body.tex").read_text()
text = plain(src, ascii_out=True)
fails = []
words, chars = len(text.split()), len(text)
if words > MAX_WORDS:
    fails.append(f"{words} words > {MAX_WORDS}")
if chars > MAX_CHARS:
    fails.append(f"{chars} characters > {MAX_CHARS}")
bad = sorted({c for c in text if ord(c) > 126 or c in "\\{}~"})
if bad:
    fails.append(f"non-ASCII or TeX characters in the plain abstract: {bad}")
if "\n\n" in src.strip():
    fails.append("abstract source has more than one paragraph")
if text.lower().startswith("abstract"):
    fails.append("plain abstract starts with the word 'Abstract'")
pdf_text = plain(src, ascii_out=False)
for pdf in ("decision-model-fit-v5.pdf", "decision-model-fit-v5-supplement.pdf"):
    p = HERE / pdf
    if not p.exists():
        continue
    page = subprocess.run(["pdftotext", "-f", "1", "-l", "1", str(p), "-"], capture_output=True, text=True).stdout
    page = " ".join(re.sub(r"-\n", "", page).split()).replace("\u2019", "'").replace("\u2018", "'")
    if re.sub(r"\s+", "", pdf_text) not in re.sub(r"\s+", "", page):  # thin spaces render as spaces
        fails.append(f"{pdf}: page 1 does not contain the shared abstract verbatim")
if len(sys.argv) > 2 and sys.argv[1] == "--write":
    Path(sys.argv[2]).write_text(text + "\n")
print(f"abstract: {words} words, {chars} characters (limits {MAX_WORDS} / {MAX_CHARS})")
for f in fails:
    print("FAIL:", f)
print("abstract OK" if not fails else f"abstract: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
