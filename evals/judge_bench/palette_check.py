"""Palette validator for the judge-benchmark report.

No external dataviz skill or validator is available in this environment, so this is a
small self-contained check of the two properties the report's charts rely on:

1. every mark color has WCAG contrast >= MIN_CONTRAST (3:1, the non-text graphics bar)
   against BOTH the light and the dark theme backgrounds, so one palette serves both themes;
2. colors that appear together in one chart stay distinguishable under simulated
   deuteranopia and protanopia (Machado et al. 2009, severity 1.0, applied in linear RGB),
   measured with CIEDE2000 >= MIN_DELTA_E_CVD, and are also distinct for normal vision.

Run: python3 evals/judge_bench/palette_check.py   (exit 0 = pass, 1 = fail)
report.py imports the constants below, so the report cannot drift from what was validated.
"""
from __future__ import annotations

import math
import sys

# Okabe-Ito derived. Luminance sits in the band that clears 3:1 on both a near-white and
# a near-black surface, so the same hex works in either theme.
FAMILY_HOSTED = "#0072B2"      # hosted API
FAMILY_SYSTEM_ONE = "#D55E00"  # local System One
FAMILY_GENERIC = "#009E73"     # local generic OllamaBackend
NEUTRAL = "#8A8A85"            # fallback / no-data / reference lines

FAMILIES = {"hosted": FAMILY_HOSTED, "system_one": FAMILY_SYSTEM_ONE, "generic": FAMILY_GENERIC}
# Case-matrix states reuse two family hues plus the neutral; glyphs carry the meaning too.
STATES = {"correct": FAMILY_HOSTED, "wrong": FAMILY_SYSTEM_ONE, "fallback": NEUTRAL}

LIGHT_BG = ("#FCFCFB", "#F4F3F0")   # card, page
DARK_BG = ("#1A1A19", "#121211")

GROUPS = {"families": FAMILIES, "states": STATES}

MIN_CONTRAST = 3.0
MIN_DELTA_E_CVD = 10.0
MIN_DELTA_E_NORMAL = 15.0

_PROTAN = ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
           (-0.003882, -0.048116, 1.051998))
_DEUTAN = ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413),
           (-0.011820, 0.042940, 0.968881))


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def luminance(hex_color: str) -> float:
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def simulate(hex_color: str, matrix) -> tuple[float, float, float]:
    lin = [_lin(c) for c in _rgb(hex_color)]
    return tuple(_unlin(sum(m * v for m, v in zip(row, lin))) for row in matrix)  # type: ignore[return-value]


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_lin(c) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e2000(lab1, lab2) -> float:
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar7 = ((c1 + c2) / 2) ** 7
    g = 0.5 * (1 - math.sqrt(cbar7 / (cbar7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dLp, dCp = L2 - L1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        dhp += -360 if dhp > 180 else 360 if dhp < -180 else 0
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    Lbp, Cbp = (L1 + L2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + (360 if h1p + h2p < 360 else -360)) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    sc, sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dLp / sl) ** 2 + (dCp / sc) ** 2 + (dHp / sh) ** 2
                     + rt * (dCp / sc) * (dHp / sh))


def color_distance(a: str, b: str, matrix=None) -> float:
    ra, rb = (simulate(a, matrix), simulate(b, matrix)) if matrix else (_rgb(a), _rgb(b))
    return delta_e2000(_lab(ra), _lab(rb))


def _all_colors() -> dict[str, str]:
    every: dict[str, str] = {}
    for group in GROUPS.values():
        every.update(group)
    return every


def check() -> list[str]:
    """Return a list of failure messages (empty = pass)."""
    errors: list[str] = []
    for name, color in sorted(_all_colors().items()):
        for bg in LIGHT_BG + DARK_BG:
            ratio = contrast(color, bg)
            if ratio < MIN_CONTRAST:
                errors.append(f"contrast {name} {color} on {bg}: {ratio:.2f} < {MIN_CONTRAST}")
    for gname, group in sorted(GROUPS.items()):
        names = sorted(group)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                for label, matrix, floor in (("normal", None, MIN_DELTA_E_NORMAL),
                                             ("deuteranopia", _DEUTAN, MIN_DELTA_E_CVD),
                                             ("protanopia", _PROTAN, MIN_DELTA_E_CVD)):
                    d = color_distance(group[a], group[b], matrix)
                    if d < floor:
                        errors.append(f"{gname}: {a} vs {b} under {label}: dE00 {d:.1f} < {floor}")
    return errors


def report() -> str:
    return "\n".join(
        f"{name:11s} {color}  contrast (light card/page, dark card/page) "
        + "  ".join(f"{contrast(color, bg):.2f}" for bg in LIGHT_BG + DARK_BG)
        for name, color in sorted(_all_colors().items()))


if __name__ == "__main__":
    problems = check()
    print(report())
    for p in problems:
        print("FAIL", p, file=sys.stderr)
    print("palette OK" if not problems else f"palette FAILED ({len(problems)})")
    sys.exit(1 if problems else 0)
