"""Small pure-stdlib statistics: intervals, exact tests, calibration."""
from __future__ import annotations

import math
import random

SEED = 20260930


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def bootstrap_ci(values, stat=None, B: int = 10000, seed: int = SEED, alpha: float = 0.05):
    """Percentile bootstrap over cases. For a paired difference pass the per-case
    differences (a_i - b_i); the default statistic is the mean."""
    values = list(values)
    if not values:
        return None
    stat = stat or (lambda xs: sum(xs) / len(xs))
    rng = random.Random(seed)
    n = len(values)
    stats = sorted(stat(rng.choices(values, k=n)) for _ in range(B))
    lo = stats[int(B * alpha / 2)]
    hi = stats[min(B - 1, int(math.ceil(B * (1 - alpha / 2))) - 1)]
    return [lo, hi]


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    cdf = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * cdf)


def holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adjusted[i] = running
    return adjusted


def _bin(c: float, bins: int) -> int:
    return min(int(c * bins), bins - 1)


def ece(conf, correct, bins: int = 10) -> float | None:
    """Expected calibration error, equal-width bins over top-label confidence."""
    conf, correct = list(conf), list(correct)
    n = len(conf)
    if not n:
        return None
    groups: dict[int, list[int]] = {}
    for i, c in enumerate(conf):
        groups.setdefault(_bin(c, bins), []).append(i)
    total = 0.0
    for idx in groups.values():
        acc = sum(bool(correct[i]) for i in idx) / len(idx)
        mean_conf = sum(conf[i] for i in idx) / len(idx)
        total += len(idx) / n * abs(acc - mean_conf)
    return total


def brier_decomposition(conf, outcome, bins: int = 10) -> dict | None:
    """Generalized Brier decomposition (Stephenson et al. 2008) of the binary Brier score of
    forecasts `conf` against 0/1 `outcome`, over `bins` equal-width forecast bins:

        BS = REL - RES + UNC + WBV - WBC

    REL reliability, RES resolution, UNC uncertainty (Murphy 1973), WBV the within-bin variance
    of the forecasts and WBC twice the within-bin covariance of forecast and outcome. When all
    forecasts in a bin are equal, WBV = WBC = 0 and Murphy's identity holds exactly. `residual`
    is BS - (REL - RES + UNC), which equals WBV - WBC. The score is for the top-label forecast
    (certainty of the chosen answer vs. whether it was right), so it is named `top_label_brier`
    to keep it apart from the multi-option `mean_brier`."""
    conf, outcome = list(conf), [float(bool(o)) for o in outcome]
    n = len(conf)
    if not n:
        return None
    base = sum(outcome) / n
    groups: dict[int, list[int]] = {}
    for i, c in enumerate(conf):
        groups.setdefault(_bin(c, bins), []).append(i)
    reliability = resolution = wbv = wbc = 0.0
    for idx in groups.values():
        f = sum(conf[i] for i in idx) / len(idx)
        o = sum(outcome[i] for i in idx) / len(idx)
        reliability += len(idx) / n * (f - o) ** 2
        resolution += len(idx) / n * (o - base) ** 2
        wbv += sum((conf[i] - f) ** 2 for i in idx) / n
        wbc += 2 * sum((conf[i] - f) * (outcome[i] - o) for i in idx) / n
    uncertainty = base * (1 - base)
    brier = sum((c - o) ** 2 for c, o in zip(conf, outcome)) / n
    return {"top_label_brier": brier, "reliability": reliability, "resolution": resolution,
            "uncertainty": uncertainty, "within_bin_variance": wbv, "within_bin_covariance": wbc,
            "residual": brier - (reliability - resolution + uncertainty)}


def nearest_rank(values, q: float):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(round(q * len(values), 9)) - 1)]
