#!/usr/bin/env python3
"""Geometry checks on the built PDF (run after `make`; needs poppler's pdftotext/pdfinfo). Exits non-zero on failure.

1. No two words overlap anywhere in the document (text drawn over text).
2. The labelled scatter (savings-model check): every label lies inside the axis, touches no marker and no other
   label, and is strictly nearer its own marker than any other. Data are mapped to page coordinates from the
   axis tick labels; markers come from generated/data/labels-model-check.tsv.
3. Every figure legend sits wholly above its plot: the legend's text ends above the plot's topmost text (top tick
   label or panel title), within a short distance of it (so the text found really is that figure's legend).
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF = HERE / "decision-models-v3.pdf"
MARK_R = 3.2
LEGENDS = {  # caption start -> (first legend entry words, topmost words of the plot)
    "A decision call is two": (["median", "(p50)"], ["A", "decision", "is"]),
    "Most recorded events are": (["event", "kind"], ["Mostly", "bookkeeping,"]),
    "No accuracy difference between the": (["preregistered", "run"], ["Holdout", "accuracy,"]),
    "Jev is the cheapest judge": (["preregistered", "run", "(Jev,"], ["What", "a", "point"]),
    "On the main-v1 test split,": (["pair", "reading", "(co-primary)"], ["Fable", "sticky"]),
    "On Fable the rule R*": (["policy", "on", "main-v1,"], ["Who", "decides,"]),
    "Two hypotheses carry money": (["estimate,", "95"], ["Cost"]),
    "The direction is consistent across": (["one", "scenario"], ["Fable:", "frozen"]),
    "Every subgroup saves money;": (["estimate,", "95"], ["Cost"]),
    "On Fable many configurations qualify;": (["candidate"], ["Fable", "host"]),
    "Medium effort saved money on": (["cost,", "95"], ["Cost"]),
    "Plain Fable spends most of": (["uncached", "input"], ["Cost", "per", "session,"]),
    "The Decisions API was at": (["accuracy,", "95"], ["Decisions", "API", "vs"]),
    "Four independent sets of scenarios": (["geometric-mean", "cost"], ["The", "same", "answer,"]),
}
NUM = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", (HERE / "generated/numbers.tex").read_text()))
SC = (int(NUM["ScXMax"]), int(NUM["ScYMin"]), int(NUM["ScYMax"]))
SCATTERS = [  # caption start, x ticks, y ticks, x range, y range, label panel, data dir, log x, extra markers file
    ("On real read decisions, no", [0, 2, 4, 6, 8, 10, 12], [0, 5, 10, 15, 20], (-1, 14), (-1.5, 22),
     "reads-holdout-ph", "generated/data", False, None),
    ("Jev is the cheapest judge", [10, 30, 100, 300, 1000], [70, 80, 90, 100], (8, 2000), (70, 102),
     "costacc-holdout", "generated/data", True, None),
]


def npages():
    out = subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", out).group(1))


def words(page):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", str(PDF), "-"],
                         capture_output=True, text=True, check=True).stdout
    return [(float(a), float(b), float(c), float(d), t.replace("&amp;", "&")) for a, b, c, d, t in re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', out)]


PAGES = {p: words(p) for p in range(1, npages() + 1)}


def seqs(w, toks):
    """Every occurrence of the token sequence as a bounding box (x0, y0, x1, y1)."""
    out = []
    for i in range(len(w) - len(toks) + 1):
        if [x[4] for x in w[i:i + len(toks)]] == toks:
            s = w[i:i + len(toks)]
            out.append((min(x[0] for x in s), min(x[1] for x in s), max(x[2] for x in s), max(x[3] for x in s)))
    return out


def find_caption(prefix):
    head = prefix.split()
    for p, w in PAGES.items():
        for i, x in enumerate(w):
            if x[4] == "Figure" and [y[4] for y in w[i + 2:i + 2 + len(head)]] == head:
                return p, w, x[1], w[i + 1][4].rstrip(":")
    raise SystemExit(f"caption not found: {prefix}")


def check_overlaps():
    fails = []
    for p, w in PAGES.items():
        for i in range(len(w)):
            a = w[i]
            for b in w[i + 1:]:
                ox = min(a[2], b[2]) - max(a[0], b[0])
                oy = min(a[3], b[3]) - max(a[1], b[1])
                if ox > 1.5 and oy > 1.5 and abs(a[1] - b[1]) > 1.0:  # same-line neighbours share a baseline
                    fails.append(f"page {p}: '{a[4]}' overlaps '{b[4]}'")
    print(f"text overlap: {sum(len(w) for w in PAGES.values())} words on {len(PAGES)} pages checked, {len(fails)} overlaps")
    return fails


def fit(pairs, log=False):
    xs = [math.log10(v) if log else v for v, _ in pairs]
    ys = [c for _, c in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return lambda v: my + b * ((math.log10(v) if log else v) - mx)


def dist(px, py, b):
    return math.hypot(max(b[0] - px, 0, px - b[2]), max(b[1] - py, 0, py - b[3]))


def num(t):
    try:
        return float(t.replace("−", "-").replace("–", "-"))
    except ValueError:
        return None


def check_scatter(spec):
    prefix, xt, yt, xr, yr, name, ddir, xlog, extra = spec
    page, w, cap_y, fig = find_caption(prefix)
    region = [x for x in w if cap_y - 330 < x[1] < cap_y]
    ycand = [x for x in region if num(x[4]) in yt]
    from collections import Counter as _C
    col = _C(round(x[2]) for x in ycand).most_common(1)[0][0]  # the right-aligned tick column
    yticks = {num(x[4]): (x[1] + x[3]) / 2 for x in ycand if abs(x[2] - col) < 2}
    xcand = [x for x in region if num(x[4]) in xt and abs(x[2] - col) >= 2]
    row = _C(round(x[1]) for x in xcand).most_common(1)[0][0]  # the tick-label row
    xticks = {num(x[4]): (x[0] + x[2]) / 2 for x in xcand if abs(x[1] - row) < 2}
    if len(xticks) < 3 or len(yticks) < 3:
        return [f"{name}: could not read ticks ({xticks}, {yticks})"]
    fx, fy = fit(sorted(xticks.items()), xlog), fit(sorted(yticks.items()))
    ax = (fx(xr[0]), fy(yr[1]), fx(xr[1]), fy(yr[0]))
    rows = [ln.split("\t") for ln in (HERE / ddir / f"labels-{name}.tsv").read_text().splitlines()[1:]]
    marks = {r[0]: (fx(float(r[2])), fy(float(r[3]))) for r in rows}
    if extra:
        lab = {(round(float(r[2]), 3), round(float(r[3]), 3)) for r in rows}
        for i, ln in enumerate((HERE / ddir / extra).read_text().splitlines()[1:]):
            x_, y_ = map(float, ln.split("\t"))
            if (round(x_, 3), round(y_, 3)) not in lab:
                marks[f"_m{i}"] = (fx(x_), fy(y_))
    inside = [x for x in w if ax[0] - 1 < x[0] and x[2] < ax[2] + 1 and ax[1] - 1 < x[1] and x[3] < ax[3] + 1]
    fails, boxes = [], {}
    for key, text, *_ in rows:
        found = seqs(inside, text.split())
        if not found:
            fails.append(f"{name}: label {text!r} not found inside the axis")
            continue
        boxes[key] = found[0]
    for key, b in boxes.items():
        own = dist(*marks[key], b)
        other = min((dist(*c, b), k) for k, c in marks.items() if k != key)
        if other[0] <= own:
            fails.append(f"{name}: {key} nearer to {other[1]} ({other[0]:.1f}) than own ({own:.1f})")
        if any(dist(*c, b) < MARK_R for c in marks.values()):
            fails.append(f"{name}: {key} label touches a marker")
        for k2, b2 in boxes.items():
            if k2 > key and b[0] < b2[2] and b2[0] < b[2] and b[1] < b2[3] and b2[1] < b[3]:
                fails.append(f"{name}: labels {key} and {k2} overlap")
        print(f"  Figure {fig} (page {page}) {key:14s} own marker {own:5.1f} pt | nearest other {other[1]:14s} {other[0]:5.1f} pt")
    return fails


def check_legends():
    fails = []
    for prefix, (legend, top) in LEGENDS.items():
        page, w, cap_y, fig = find_caption(prefix)
        tops = [b for b in seqs(w, top) if cap_y - 520 < b[1] < cap_y]
        if not tops:
            fails.append(f"Figure {fig}: plot text {top} not found")
            continue
        anchor, legs = None, []
        for cand in sorted(tops, key=lambda b: b[1]):
            legs = [b for b in seqs(w, legend) if b[3] <= cand[1] + 40 and cand[1] - b[3] < 60]
            if legs:
                anchor = cand
                break
        if anchor is None:
            fails.append(f"Figure {fig}: legend {legend} not found just above the plot")
            continue
        leg = max(legs, key=lambda b: b[3])
        gap = anchor[1] - leg[3]
        print(f"legend Figure {fig} (page {page}): legend text bottom y={leg[3]:.1f}, topmost plot text top y={anchor[1]:.1f}, "
              f"gap {gap:.1f} pt")
        if gap <= 0:
            fails.append(f"Figure {fig}: legend reaches into the plot (gap {gap:.1f} pt)")
    return fails


ROWS = [  # caption start -> data files whose rows carry (label, v); every rendered row label must sit beside its own v
    ("A decision call is two", ["obs-latency.dat"]),
    ("Most recorded events are", ["obs-mix.dat"]),
    ("On the main-v1 test split,", ["forest.dat", "forest-h3.dat"]),
    ("On Fable the rule R*", ["a0-policies.dat"]),
    ("Two hypotheses carry money", ["s1-forest.dat"]),
    ("Every subgroup saves money;", ["s1-subgroups.dat"]),
    ("Medium effort saved money on", ["effort-hosts.dat"]),
    ("Plain Fable spends most of", ["s1-composition.dat"]),
    ("Four independent sets of scenarios", ["cumulative.dat"]),
    ("The Decisions API was at", ["openai-acc.dat"]),
]


def read_rows(path):
    lines = (HERE / "generated" / "data" / path).read_text().splitlines()
    head = lines[0].split()
    out = []
    for ln in lines[1:]:
        lab = re.search(r"\{([^}]*)\}", ln).group(1)
        rest = ln.replace("{" + lab + "}", "LABEL", 1).split()
        out.append((lab, rest[head.index("v")]))
    return out


def norm(t):
    return t.replace("\u2212", "-").replace("\u2013", "-")


def check_rows():
    fails, n = [], 0
    for prefix, files in ROWS:
        page, w, cap_y, fig = find_caption(prefix)
        area = [x for x in w if x[3] < cap_y]
        rows = []
        for f in files:
            for lab, v in read_rows(f):
                occ = [b for b in seqs(area, lab.split())]
                if not occ:
                    fails.append(f"Figure {fig}: row label '{lab}' not found")
                    continue
                b = max(occ, key=lambda b: b[1])  # the tick label is the occurrence closest above the caption
                rows.append((lab, v, b))
        if not rows:
            continue
        label_boxes = [r[2] for r in rows]
        nums = [x for x in area if num(x[4]) is not None and not any(
            lb[0] - 0.5 <= x[0] and x[2] <= lb[2] + 0.5 and lb[1] - 0.5 <= x[1] and x[3] <= lb[3] + 0.5 for lb in label_boxes)]
        assigned = {i: [] for i in range(len(rows))}
        for x in nums:
            yc = (x[1] + x[3]) / 2
            cands = [i for i, r in enumerate(rows) if x[0] > r[2][2]]
            if not cands:
                continue
            # value labels sit just above a marker (forest) or centred on a bar end: their bottom edge is nearest
            # their own row's centre
            i = min(cands, key=lambda i: abs((rows[i][2][1] + rows[i][2][3]) / 2 - x[3]))
            assigned[i].append(norm(x[4]))
        for i, (lab, v, _) in enumerate(rows):
            n += 1
            if norm(v) not in assigned[i]:
                fails.append(f"Figure {fig}: row '{lab}' expects value {v}, beside it: {assigned[i] or 'nothing'}")
    print(f"row identity: {n} rows in {len(ROWS)} figures checked, {len(fails)} mismatches")
    return fails


if __name__ == "__main__":
    failures = check_overlaps() + [f for sp in SCATTERS for f in check_scatter(sp)] + check_legends() + check_rows()
    for f in failures:
        print("FAIL:", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)
