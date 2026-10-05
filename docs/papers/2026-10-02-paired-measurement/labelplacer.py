"""Deterministic label placer for labelled scatter plots (shared with the judge-benchmark report).

Label sizes come from the text font's TFM metrics (the same metrics pdflatex uses); positions from the
axis geometry fixed by `scale only axis`. A label that cannot satisfy every rule stops the build.
Call `configure(out_dir, data_dir, axis_w_cm, axis_h_cm)` before `place_labels`.
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = DATA = None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def configure(out_dir: Path, data_dir: Path, axis_w_cm: float, axis_h_cm: float) -> None:
    global OUT, DATA, AXIS_W_CM, AXIS_H_CM, AXIS_W, AXIS_H
    OUT, DATA = out_dir, data_dir
    AXIS_W_CM, AXIS_H_CM = axis_w_cm, axis_h_cm
    AXIS_W, AXIS_H = AXIS_W_CM * PT_PER_CM, AXIS_H_CM * PT_PER_CM


# Label placement for the labelled scatter plots (Figs. wacov-dev, wacov-holdout, acclat-holdout).
# A deterministic backtracking placer. Label sizes come from the font's TFM metrics (the same
# metrics pdflatex uses), positions from the axis geometry fixed by `scale only axis`. Every label
# must satisfy ALL of these, or the build fails:
#   (1) it keeps a clear gap to every marker, its own included;
#   (2) it does not overlap any other label or any other label's leader line;
#   (3) it stays inside the axis frame, clear of the axis lines;
#   (4) its own marker is strictly nearer to it than any other marker (by NEAREST_MARGIN);
#   (5) a displaced label gets a leader line that passes clear of other markers and labels.
# Placement never changes a plotted value; it only decides where text goes.
PT_PER_CM = 72.27 / 2.54
AXIS_W_CM, AXIS_H_CM = 14.5, 6.4
AXIS_W, AXIS_H = AXIS_W_CM * PT_PER_CM, AXIS_H_CM * PT_PER_CM
LABEL_PT = 8.0            # \scriptsize in an 11pt document
PAD = 2.0                 # TikZ inner sep of a label node
MARK_R = 3.2              # largest marker half-size used in the scatter plots
CLEAR = 1.5               # minimum gap between a label box and any marker
EDGE = 3.0                # minimum gap between a label box and the axis frame
LABEL_GAP = 1.0           # minimum gap between two label boxes
NEAREST_MARGIN = 3.5      # own marker must be nearer than any other by this much (pt)
DISTANCES = [0, 6, 12, 18, 24, 32, 40, 50]
DIRS = [("east", (1, 0), "west"), ("west", (-1, 0), "east"), ("north", (0, 1), "south"),
        ("south", (0, -1), "north"), ("north east", (1, 1), "south west"),
        ("north west", (-1, 1), "south east"), ("south east", (1, -1), "north west"),
        ("south west", (-1, -1), "north east")]


def _tfm_metrics():
    """Width/height/depth (in em) of each T1 glyph of the text font, read from its TFM."""
    import subprocess
    path = subprocess.run(["kpsewhich", "LibertinusSerif-Regular-tlf-t1.tfm"], capture_output=True,
                          text=True, check=True).stdout.strip()
    b = Path(path).read_bytes()
    lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, npar = (int.from_bytes(b[i:i + 2], "big") for i in range(0, 24, 2))

    def fix(off):
        return int.from_bytes(b[off:off + 4], "big", signed=True) / 2 ** 20

    ci = 4 * (6 + lh)
    wt = ci + 4 * (ec - bc + 1)
    ht, dt = wt + 4 * nw, wt + 4 * nw + 4 * nh
    pr = 4 * (6 + lh + (ec - bc + 1) + nw + nh + nd + ni + nl + nk + ne)
    glyph = {}
    for c in range(bc, ec + 1):
        info = b[ci + 4 * (c - bc): ci + 4 * (c - bc) + 4]
        if info[0]:
            glyph[c] = (fix(wt + 4 * info[0]), fix(ht + 4 * (info[1] >> 4)), fix(dt + 4 * (info[1] & 15)))
    return glyph, fix(pr + 4)  # param 2 = interword space


GLYPH, SPACE = _tfm_metrics()


BASELINE_SKIP = 9.5 * 1.15  # \scriptsize baseline skip (11pt document) x the \linespread of multi-line labels


def label_size(text):
    """(width, height) in pt of a TikZ label node holding `text` at LABEL_PT. A label may have several
    lines separated by newlines (typeset with align=left)."""
    lines = text.split("\n")

    def width(line):
        return sum(SPACE if ch == " " else GLYPH[ord(ch)][0] for ch in line) * LABEL_PT

    def hd(line, i):
        return max(GLYPH[ord(ch)][i] for ch in line if ch != " ") * LABEL_PT

    w = max(width(ln) for ln in lines)
    h = hd(lines[0], 1) + BASELINE_SKIP * (len(lines) - 1) + hd(lines[-1], 2)
    return w + 2 * PAD, h + 2 * PAD


def _anchor_box(qx, qy, w, h, anchor):
    x0 = {"west": qx, "east": qx - w}.get(anchor.split()[-1], qx - w / 2)
    y0 = qy if anchor.startswith("south") else (qy - h if anchor.startswith("north") else qy - h / 2)
    return (x0, y0, x0 + w, y0 + h)


def _dist_pt_box(px, py, b):
    dx = max(b[0] - px, 0.0, px - b[2])
    dy = max(b[1] - py, 0.0, py - b[3])
    return math.hypot(dx, dy)


def _boxes_touch(a, b, gap):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def _seg_hits_box(p, q, b, steps=40):
    return any(b[0] <= p[0] + (q[0] - p[0]) * i / steps <= b[2] and b[1] <= p[1] + (q[1] - p[1]) * i / steps <= b[3]
               for i in range(steps + 1))


def _seg_dist(p, q, c):
    vx, vy = q[0] - p[0], q[1] - p[1]
    t = max(0.0, min(1.0, ((c[0] - p[0]) * vx + (c[1] - p[1]) * vy) / ((vx * vx + vy * vy) or 1)))
    return math.hypot(p[0] + t * vx - c[0], p[1] + t * vy - c[1])


def place_labels(name, points, xr, yr, xlog=False, obstacles=(), extra=()):
    """points: [(key, text, x, y)] in data units; extra: unlabelled markers [(x, y)] that labels must also keep
    clear of and be farther from than from their own marker. Returns placements; exits non-zero if impossible."""
    def tx(x):
        if xlog:
            return AXIS_W * (math.log10(x) - math.log10(xr[0])) / (math.log10(xr[1]) - math.log10(xr[0]))
        return AXIS_W * (x - xr[0]) / (xr[1] - xr[0])

    def ty(y):
        return AXIS_H * (y - yr[0]) / (yr[1] - yr[0])

    pts = [(k, t, x, y, tx(x), ty(y)) for k, t, x, y in points]
    centers = {p[0]: (p[4], p[5]) for p in pts}
    for i, (ex, ey) in enumerate(extra):
        centers[f"_unlabelled{i}"] = (tx(ex), ty(ey))
    blocked = [(tx(a), ty(b), tx(c), ty(d)) for a, b, c, d in obstacles]  # e.g. a shaded zone

    def options(p):
        k, t, _, _, px, py = p
        w, h = label_size(t)
        for d in DISTANCES:
            for dname, (ux, uy), anchor in DIRS:
                n = math.hypot(ux, uy)
                r = MARK_R + CLEAR + d
                qx, qy = px + r * ux / n, py + r * uy / n
                box = _anchor_box(qx, qy, w, h, anchor)
                leader = None
                if d > 0:
                    leader = ((px + MARK_R * ux / n, py + MARK_R * uy / n), (qx, qy))
                yield {"key": k, "text": t, "anchor": anchor, "dir": dname, "d": d, "dx": qx - px, "dy": qy - py,
                       "box": box, "leader": leader}

    def ok(o, placed):
        b = o["box"]
        if b[0] < EDGE or b[1] < EDGE or b[2] > AXIS_W - EDGE or b[3] > AXIS_H - EDGE:
            return False
        if any(_boxes_touch(b, z, LABEL_GAP) for z in blocked):
            return False
        own = _dist_pt_box(*centers[o["key"]], b)
        for k, c in centers.items():
            dist = _dist_pt_box(*c, b)
            if dist < MARK_R + CLEAR - 1e-9:
                return False
            if k != o["key"] and dist < own + NEAREST_MARGIN:
                return False
            if o["leader"] and k != o["key"] and _seg_dist(*o["leader"], c) < MARK_R + 1.0:
                return False
        for q in placed:
            if _boxes_touch(b, q["box"], LABEL_GAP):
                return False
            if q["leader"] and _seg_hits_box(*q["leader"], b):
                return False
            if o["leader"] and _seg_hits_box(*o["leader"], q["box"]):
                return False
        return True

    crowd = {p[0]: sum(1 for q in pts if q is not p and math.hypot(q[4] - p[4], q[5] - p[5]) < 60) for p in pts}
    order = sorted(pts, key=lambda p: (-crowd[p[0]], p[4], p[0]))
    opts = {p[0]: list(options(p)) for p in pts}
    placed: list = []
    budget = [200000]

    def solve(i):
        if i == len(order):
            return True
        for o in opts[order[i][0]]:
            budget[0] -= 1
            if budget[0] < 0:
                return False
            if ok(o, placed):
                placed.append(o)
                if solve(i + 1):
                    return True
                placed.pop()
        return False

    if not solve(0):
        raise SystemExit(f"build_assets.py: cannot place scatter labels cleanly in panel {name!r}; "
                         f"placed {[o['key'] for o in placed]}")
    res = {o["key"]: o for o in placed}
    # Emit the TikZ code (read inside the axis) and a geometry record for checking.
    tex, rec = [f"% Generated by build_assets.py: labels for panel {name}. Do not edit."], \
        ["key\ttext\tx\ty\tpx\tpy\tx0\ty0\tx1\ty1\town_dist\tnearest_other\tnearest_other_dist\tleader"]
    for k, t, x, y, px, py in pts:
        o = res[k]
        at = f"($(axis cs:{x:.4f},{y:.4f})+({o['dx']:.3f}pt,{o['dy']:.3f}pt)$)"
        opts = ", scatterlabelmulti" if "\n" in t else ""
        tex.append(f"\\node[scatterlabel, anchor={o['anchor']}{opts}] at {at} {{{t.replace(chr(10), chr(92) * 2)}}};")
        if o["leader"]:
            (lx, ly), _ = o["leader"]
            tex.append(f"\\draw[leader] ($(axis cs:{x:.4f},{y:.4f})+({lx - px:.3f}pt,{ly - py:.3f}pt)$) -- {at};")
        b = o["box"]
        own = _dist_pt_box(px, py, b)
        other = min(((kk, _dist_pt_box(*c, b)) for kk, c in centers.items() if kk != k), key=lambda z: z[1])
        rec.append("\t".join([k, t.replace("\n", " "), f"{x:.4f}", f"{y:.4f}", f"{px:.2f}", f"{py:.2f}"] + [f"{v:.2f}" for v in b]
                             + [f"{own:.2f}", other[0], f"{other[1]:.2f}", "yes" if o["leader"] else "no"]))
    _write(OUT / "labels" / f"{name}.tex", "\n".join(tex) + "\n")
    _write(DATA / f"labels-{name}.tsv", "\n".join(rec) + "\n")
    return res


