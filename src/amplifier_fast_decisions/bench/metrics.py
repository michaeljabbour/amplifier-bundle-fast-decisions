"""Pure functions: latency percentiles, agreement, ECE, cost, projection.

No I/O, no Amplifier or network imports (harness-agnostic core, see
docs/design/redesign-2026-09-17.md, "Smart-tool packaging target"). Every
function here takes plain data in and returns plain data out.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

JEV_INPUT_PRICE_PER_MILLION = 0.042  # verified Jev pricing; output is $0.


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile. ``None`` for an empty sequence.

    For n=1 the single value is returned for any p. For n=2, p<=50 returns
    the lower value and p>50 the upper value (documented nearest-rank
    behaviour -- see docs/BENCH.md).
    """
    finite = sorted(
        v for v in values if isinstance(v, (int, float)) and math.isfinite(v)
    )
    if not finite:
        return None
    if len(finite) == 1:
        return float(finite[0])
    rank = max(0, min(len(finite) - 1, round((p / 100) * (len(finite) - 1))))
    return float(finite[rank])


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_boot: int = 500,
    seed: int = 0,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """A simple, deterministic (seeded) percentile bootstrap over a 0/1 or
    real-valued sample. Returns ``None`` for fewer than 2 observations."""
    sample = [
        float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)
    ]
    if len(sample) < 2:
        return None
    rng = random.Random(seed)
    n = len(sample)
    means = []
    for _ in range(n_boot):
        draw = [sample[rng.randrange(n)] for _ in range(n)]
        means.append(sum(draw) / n)
    means.sort()
    lo_p = (1 - confidence) / 2 * 100
    hi_p = (1 - (1 - confidence) / 2) * 100
    return (percentile(means, lo_p) or means[0], percentile(means, hi_p) or means[-1])


def decision_cost_usd(
    input_tokens: Sequence[int | float | None],
    *,
    price_per_million: float = JEV_INPUT_PRICE_PER_MILLION,
) -> float | None:
    """``sum(input_tokens) * price / 1e6``. ``None`` -- never ``0`` -- when
    no usage was reported at all."""
    known = [
        t
        for t in input_tokens
        if isinstance(t, (int, float)) and not isinstance(t, bool)
    ]
    if not known:
        return None
    return sum(known) * price_per_million / 1_000_000


def ece(
    pairs: Sequence[tuple[float, bool]],
    *,
    bins: int = 10,
    min_reliable_n: int = 30,
) -> dict[str, Any]:
    """Expected Calibration Error on the *chosen option's probability*,
    never on a separate ``confidence`` statistic (P7 amendment (c)).

    ``pairs`` is ``(selected_probability, was_correct)``. Equal-width bins
    over ``[0, 1]``. Each bin reports its own ``n``; bins with
    ``n < min_reliable_n`` are marked ``reliable: false`` and excluded from
    the headline (reliable-only, renormalised) ECE -- reported separately
    under ``low_n_bins``.
    """
    clean = [
        (float(p), bool(c))
        for p, c in pairs
        if isinstance(p, (int, float)) and math.isfinite(p) and 0.0 <= p <= 1.0
    ]
    width = 1.0 / bins
    bucket: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, c in clean:
        idx = min(bins - 1, int(p / width))
        bucket[idx].append((p, c))
    bin_records = []
    for i, items in enumerate(bucket):
        n = len(items)
        lo, hi = i * width, (i + 1) * width
        if n == 0:
            bin_records.append(
                {
                    "lo": lo,
                    "hi": hi,
                    "n": 0,
                    "mean_confidence": None,
                    "empirical_accuracy": None,
                    "reliable": False,
                }
            )
            continue
        mean_conf = sum(p for p, _ in items) / n
        acc = sum(1 for _, c in items if c) / n
        bin_records.append(
            {
                "lo": lo,
                "hi": hi,
                "n": n,
                "mean_confidence": mean_conf,
                "empirical_accuracy": acc,
                "reliable": n >= min_reliable_n,
            }
        )
    reliable_bins = [b for b in bin_records if b["reliable"]]
    low_n_bins = [b for b in bin_records if b["n"] > 0 and not b["reliable"]]
    n_reliable = sum(b["n"] for b in reliable_bins)
    headline = None
    if n_reliable:
        headline = sum(
            (b["n"] / n_reliable) * abs(b["empirical_accuracy"] - b["mean_confidence"])
            for b in reliable_bins
        )
    return {
        "ece": headline,
        "bins": bin_records,
        "low_n_bins": low_n_bins,
        "n_observed": len(clean),
    }


def mean_or_none(values: Sequence[float | None]) -> float | None:
    known = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if not known:
        return None
    return sum(known) / len(known)


def comparable_confidence_mean(records: Sequence[dict[str, Any]]) -> float | None:
    """Never pool different backends/models/statistics or an unknown formula.

    Raw values remain available in the trace. This is a distribution-statistic
    summary, not a calibration or correctness estimate.
    """
    values = []
    sources = set()
    for row in records:
        value = row.get('reported_confidence')
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            return None
        source = tuple(row.get(key) for key in ('backend', 'model', 'confidence_kind'))
        if any(not isinstance(item, str) or not item or item == 'unknown' for item in source):
            return None
        if source[2] in {'unspecified', 'not_reported'} or source[2].endswith('_unspecified'):
            return None
        sources.add(source)
        values.append(value)
    return mean_or_none(values) if len(sources) == 1 else None


def rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def projected_task_latency_delta_ms(
    *,
    decisions: int,
    mean_slow_ms: float | None,
    mean_decision_ms: float | None,
    avoided_rate: float | None,
) -> float | None:
    """``decisions x (mean(slow) - mean(decision)) x avoided_llm_turn_rate``.

    A *model*, not a measurement (P7): holds generation and tool time
    constant. ``None`` when any required input is unavailable.
    """
    if mean_slow_ms is None or mean_decision_ms is None or avoided_rate is None:
        return None
    return decisions * (mean_slow_ms - mean_decision_ms) * avoided_rate


def projected_task_cost_delta_usd(
    *, avoided_provider_cost_usd: float | None, decision_cost: float | None
) -> float | None:
    if avoided_provider_cost_usd is None or decision_cost is None:
        return None
    return avoided_provider_cost_usd - decision_cost


PROJECTION_ASSUMPTIONS = (
    "generation and tool time unchanged",
    "avoided turns are independent",
)
