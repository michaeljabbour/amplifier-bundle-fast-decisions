#!/usr/bin/env python3
"""Geometry check of the built PDF (run after `make`; needs poppler's pdftotext).

For each labelled scatter panel it maps data coordinates to page coordinates from the axis tick
labels, then checks, using the text boxes pdftotext reports, that every label sits inside the axis,
overlaps no marker and no other label, and is strictly nearer its own marker than any other.
For the latency-anatomy figure it checks that each legend lies wholly above its axis (so it cannot
touch a bar). Exits non-zero on any failure.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF = HERE / "judge-benchmark.pdf"
MARK_R = 3.2
PANELS = {  # panel -> (caption start, x ticks, y ticks, x range, y range, log x)
    "wacov-dev": ("Wrong automatic rate against coverage on the dev split", [20, 40, 60, 80, 100],
                  [0, 10, 20, 30, 40], (15, 100), (0, 40), False),
    "wacov-holdout": ("Wrong automatic rate against coverage on the holdout", [20, 40, 60, 80, 100],
                      [0, 10, 20, 30, 40], (15, 100), (0, 40), False),
    "acclat-holdout": ("Accuracy against p95 latency", [30, 100, 300, 1000, 3000],
                       [30, 40, 50, 60, 70, 80, 90, 100], (25, 9000), (25, 102), True),
    "reads-holdout": ("Real decisions: correct automatic reads",
                      [0, 2, 4, 6, 8, 10, 12], [0, 5, 10, 15, 20], (-1, 14), (-1.5, 22), False),
}


def pages():
    info = subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", info).group(1))


def words(page):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", str(PDF), "-"],
                         capture_output=True, text=True, check=True).stdout
    return [(float(a), float(b), float(c), float(d), t) for a, b, c, d, t in re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', out)]


def find_caption(prefix):
    head = prefix.split()
    for p in range(1, pages() + 1):
        w = words(p)
        for i, x in enumerate(w):
            if x[4] == "Figure" and i + len(head) + 1 < len(w) and \
                    [y[4] for y in w[i + 2:i + 2 + len(head)]] == head:
                return p, w, x[1], w[i + 1][4]
    raise SystemExit(f"caption not found: {prefix}")


def num(t):
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def fit(pairs, log):
    xs = [math.log10(v) if log else v for v, _ in pairs]
    ys = [c for _, c in pairs]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return lambda v: my + b * ((math.log10(v) if log else v) - mx)


def dist(px, py, b):
    return math.hypot(max(b[0] - px, 0, px - b[2]), max(b[1] - py, 0, py - b[3]))


def check_panel(name, spec):
    prefix, xt, yt, xr, yr, xlog = spec
    page, w, cap_y, fig = find_caption(prefix)
    region = [x for x in w if cap_y - 330 < x[1] < cap_y]
    # y ticks: numeric words forming the left-most column; x ticks: the lowest row of numeric words.
    ycand = [x for x in region if num(x[4]) in yt]
    col = min(round(x[2]) for x in ycand)
    yticks = {num(x[4]): (x[1] + x[3]) / 2 for x in ycand if abs(x[2] - col) < 2}
    xcand = [x for x in region if num(x[4]) in xt and abs(x[2] - col) >= 2]
    row = max(round(x[1]) for x in xcand)
    xticks = {num(x[4]): (x[0] + x[2]) / 2 for x in xcand if abs(x[1] - row) < 2}
    if len(xticks) < 3 or len(yticks) < 3:
        raise SystemExit(f"{name}: could not read ticks ({xticks}, {yticks})")
    fx, fy = fit(sorted(xticks.items()), xlog), fit(sorted(yticks.items()), False)
    ax = (fx(xr[0]), fy(yr[1]), fx(xr[1]), fy(yr[0]))
    rows = [ln.split("\t") for ln in (HERE / "generated/data" / f"labels-{name}.tsv").read_text().splitlines()[1:]]
    marks = {r[0]: (fx(float(r[2])), fy(float(r[3]))) for r in rows}
    inside = [x for x in w if ax[0] - 1 < x[0] and x[2] < ax[2] + 1 and ax[1] - 1 < x[1] and x[3] < ax[3] + 1
              ]
    boxes, fails = {}, []
    for key, text, *_ in rows:
        toks = text.split()
        for i in range(len(inside) - len(toks) + 1):
            seq = inside[i:i + len(toks)]
            if [s[4] for s in seq] == toks:
                boxes[key] = (min(s[0] for s in seq), min(s[1] for s in seq),
                              max(s[2] for s in seq), max(s[3] for s in seq))
                break
        else:
            fails.append(f"label {text!r} not found inside the axis")
    report = []
    for key, b in boxes.items():
        own = dist(*marks[key], b)
        others = sorted((dist(*c, b), k) for k, c in marks.items() if k != key)
        touching = [k for k, c in marks.items() if dist(*c, b) < MARK_R]
        if others[0][0] <= own:
            fails.append(f"{key}: nearer to {others[0][1]} ({others[0][0]:.1f}) than to own ({own:.1f})")
        if touching:
            fails.append(f"{key}: text box touches marker(s) {touching}")
        for k2, b2 in boxes.items():
            if k2 > key and b[0] < b2[2] and b2[0] < b[2] and b[1] < b2[3] and b2[1] < b[3]:
                fails.append(f"labels {key} and {k2} overlap")
        report.append((key, own, others[0][1], others[0][0]))
    print(f"{name} (Figure {fig.rstrip(':')}, page {page}): {len(boxes)} labels")
    for key, own, k, d in report:
        print(f"  {key:12s} own marker {own:5.1f} pt | nearest other {k:12s} {d:5.1f} pt")
    return fails


def check_legends():
    """Each Fig. 7 panel: locate the y-tick label column (bottom and top row labels share a right edge),
    map row index to page y, compute the axis top (ymax), and require every legend word to lie above it."""
    page, w, cap_y, fig = find_caption("Where the time goes in one call")
    fails = []
    panels = (("cloud", "Sol", "1.13", 3, 3.6, ["network", "provider", "server", "time", "client", "and", "rest"]),
              ("local", "9B", "0.6B", 4, 4.6, ["model", "load/check", "prompt", "prefill", "decode", "and", "rest"]))
    for name, bottom, top, top_idx, ymax, legend in panels:
        pair = None
        for lo in (x for x in w if x[4] == bottom and x[1] < cap_y):
            for hi in (x for x in w if x[4] == top and x[1] < cap_y):
                if abs(lo[2] - hi[2]) < 1.0 and 0 < lo[1] - hi[1] < 160:
                    pair = (lo, hi)
        if pair is None:
            fails.append(f"{name}: tick labels not found")
            continue
        lo, hi = pair
        y0, yn = (lo[1] + lo[3]) / 2, (hi[1] + hi[3]) / 2
        axis_top = y0 + (yn - y0) * ymax / top_idx
        axis_left = lo[2]
        near = [x for x in w if x[4] in legend and axis_top - 40 < x[1] < axis_top + 5 and x[0] > axis_left]
        if not near:
            fails.append(f"{name}: legend not found just above the axis")
            continue
        low = max(x[3] for x in near)
        inside = [x[4] for x in w if x[4] in legend and axis_top < x[1] < y0 and x[0] > axis_left]
        print(f"Figure {fig.rstrip(':')} {name} panel (page {page}): legend words {len(near)}, lowest legend "
              f"text bottom y={low:.1f}, axis top y={axis_top:.1f} (page y grows downward); "
              f"legend words inside axis: {inside or 'none'}")
        if low >= axis_top or inside:
            fails.append(f"{name}: legend reaches into the axis")
    return fails


if __name__ == "__main__":
    failures = []
    for name, spec in PANELS.items():
        failures += check_panel(name, spec)
    failures += check_legends()
    for f in failures:
        print("FAIL:", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)
