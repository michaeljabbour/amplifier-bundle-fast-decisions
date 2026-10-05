"""Shared helpers for the v3 offline analyses (A0, A1, A3): stdlib only, deterministic.

Nothing here calls a model or the network. Outputs are written through `write_json` / `write_csv`, which replace the home
directory with `~` and refuse values that look like keys, so evidence stays sanitized by construction.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from pathlib import Path
from typing import Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
HOME = str(Path.home())
_KEYLIKE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]|Bearer [A-Za-z0-9]|api[_-]key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{6,}",
                      re.IGNORECASE)


def sanitize(value):
    """Recursively replace the home path with `~`; round floats to 6 places; raise on key-like strings."""
    if isinstance(value, str):
        if _KEYLIKE.search(value):
            raise ValueError("refusing to write a key-like string")
        return value.replace(HOME, "~")
    if isinstance(value, dict):
        return {sanitize(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else round(value, 6)
    return value


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize(obj), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict], fields: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [sanitize(r) for r in rows]
    fields = list(fields or (rows[0].keys() if rows else []))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def quantile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile (numpy's default 'linear' method)."""
    s = sorted(xs)
    if not s:
        return float("nan")
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def cluster_bootstrap(clusters: dict, stat: Callable[[list], float], n: int = 10_000, seed: int = 20261005,
                      alpha: float = 0.05) -> tuple[float, float, float]:
    """Point estimate and percentile CI of `stat` over a cluster bootstrap (resample clusters with replacement).

    `clusters` maps a cluster key (scenario) to its per-rep values; `stat` receives a list of clusters."""
    data = [clusters[k] for k in sorted(clusters)]
    point = stat(data)
    if not data:
        return point, float("nan"), float("nan")
    rng = random.Random(seed)
    m = len(data)
    draws = [stat([data[rng.randrange(m)] for _ in range(m)]) for _ in range(n)]
    return point, quantile(draws, alpha / 2), quantile(draws, 1 - alpha / 2)


def cluster_mean(data: list) -> float:
    """Equal weight per cluster: mean over clusters of the within-cluster mean."""
    return mean(mean(c) for c in data)


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    """Proportion with its Wilson score interval (95% by default)."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)
