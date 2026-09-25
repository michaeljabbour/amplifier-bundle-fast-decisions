"""Estimated time and cost saved by turn-start routing, from recorded events.

The orchestrator routes each turn once: ``strong`` turns run exactly the host
setup (nothing saved, nothing lost), ``cheap`` turns run on the start model.
For every cheap turn this module prices the same recorded work as if the host
model had done it:

* **Cost.** Actual cost is the provider's own ``cost_usd`` when recorded, else
  the tokens priced at the start model's rates. The counterfactual prices the
  same tokens (fresh input, cached reads, cache writes, output) at the host
  model's rates.
* **Time.** Each model's generation rate (seconds per output token, requests
  with at least ``MIN_RATE_OUTPUT`` output tokens) is measured from this same
  event history. The counterfactual scales the cheap turns' model time by the
  host/start rate ratio. Until both models have ``MIN_RATE_SAMPLES`` samples
  the time estimate is reported as unavailable instead of guessed.

Both are estimates: the host model would not have produced exactly the same
tokens or taken exactly the same number of steps. Tool time, start-up, and
the judge's own calls are not counted as savings (judge calls are reported).
Only numbers already in the privacy-safe event records are read.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# USD per million tokens: (input, output, cache_read, cache_write_5m).
# Source: Amplifier's Anthropic provider price table (_cost.py, verified
# 2026-06-10 against anthropic.com/pricing). Override with ``rates=``.
DEFAULT_RATES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-fable-5": (10.0, 50.0, 1.0, 12.5),
    "claude-sonnet-5": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30, 3.75),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-7": (5.0, 25.0, 0.50, 6.25),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}
DEFAULT_HOST_MODEL = "claude-fable-5-1"
MIN_RATE_OUTPUT = 200
MIN_RATE_SAMPLES = 20
CACHE_VERSION = 2
_JUDGED = '"fast_decisions:difficulty_judged"'
_SLOW_END = '"fast_decisions:slow_end"'


def _rates_for(model: str | None, rates: dict) -> tuple | None:
    if not model:
        return None
    if model in rates:
        return rates[model]
    # Dated ids ("claude-sonnet-5-20260101") match their family entry.
    for name in sorted(rates, key=len, reverse=True):
        if model.startswith(name):
            return rates[name]
    return None


def price(model: str | None, tokens: dict, rates: dict) -> float | None:
    """USD for one request's tokens at ``model``'s rates. Amplifier's
    ``input_tokens`` already includes cached reads; cache writes are separate."""
    r = _rates_for(model, rates)
    if r is None:
        return None
    cached = tokens.get("cache_read", 0)
    fresh = max(0, tokens.get("input", 0) - cached)
    return (fresh * r[0] + tokens.get("output", 0) * r[1] + cached * r[2]
            + tokens.get("cache_write", 0) * r[3]) / 1_000_000


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _empty_day() -> dict:
    return {"cheap_turns": 0, "strong_turns": 0, "judge_calls": 0, "by_reason": {},
            "cheap_requests": 0, "cheap_seconds": 0.0, "actual_usd": 0.0,
            "counterfactual_usd": 0.0, "unpriced_requests": 0, "no_cache_data_requests": 0,
            "provider_costed_requests": 0,
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def scan_file(path: Path, *, host_model: str | None = None, rates: dict | None = None) -> dict:
    """Per-day partial aggregates for one session's event file (additive
    across files). Only routing and provider-completion records are parsed."""
    rates = rates or DEFAULT_RATES
    turns: dict[str, dict] = {}
    requests: list[dict] = []
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return {"days": {}, "rate": {}}
    with handle:
        for line in handle:
            if _JUDGED not in line and _SLOW_END not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = event.get("data") or {}
            if event.get("synthetic") or data.get("synthetic"):
                continue
            turn = event.get("turn_id")
            day = str(event.get("timestamp", ""))[:10]
            if event.get("event") == "fast_decisions:difficulty_judged" and turn:
                turns[turn] = {"tier": data.get("choice"), "reason": str(data.get("reason_code") or "unknown"),
                               "day": day}
            elif event.get("event") == "fast_decisions:slow_end" and data.get("status") == "ok":
                requests.append({"turn": turn, "day": day, "data": data})
    days: dict[str, dict] = defaultdict(_empty_day)
    rate: dict[str, list] = defaultdict(lambda: [0.0, 0, 0])  # model -> [seconds, output tokens, samples]
    hosts: dict[str, int] = defaultdict(int)  # recorded host models, for auto-detection
    for req in requests:
        recorded = req["data"].get("host_model")
        if isinstance(recorded, str) and recorded:
            hosts[recorded] += 1
    file_host = max(hosts, key=hosts.get) if hosts else None
    host_model = host_model or file_host or DEFAULT_HOST_MODEL
    for info in turns.values():
        bucket = days[info["day"]]
        bucket["cheap_turns" if info["tier"] == "cheap" else "strong_turns"] += 1
        bucket["by_reason"][info["reason"]] = bucket["by_reason"].get(info["reason"], 0) + 1
        if info["reason"].startswith("judge_"):
            bucket["judge_calls"] += 1
    for req in requests:
        data = req["data"]
        info = turns.get(req["turn"])
        model = data.get("served_model") or data.get("model")
        if model in (None, "", "provider-default"):
            recorded = data.get("host_model")
            model = (recorded or host_model) if not info or info["tier"] != "cheap" else None
        seconds = float(data.get("duration_ms") or 0) / 1000
        tokens = {"input": _int(data.get("input_tokens")), "output": _int(data.get("output_tokens")),
                  "cache_read": _int(data.get("cache_read_tokens")), "cache_write": _int(data.get("cache_write_tokens"))}
        if model and tokens["output"] >= MIN_RATE_OUTPUT and seconds > 0:
            entry = rate[model]
            entry[0] += seconds
            entry[1] += tokens["output"]
            entry[2] += 1
        if not info or info["tier"] != "cheap":
            continue
        bucket = days[req["day"] or info["day"]]
        bucket["cheap_requests"] += 1
        bucket["cheap_seconds"] += seconds
        for key, value in tokens.items():
            bucket[key] += value
        if "cache_read_tokens" not in data and "cost_usd" not in data:
            bucket["no_cache_data_requests"] += 1
        cost = data.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            bucket["provider_costed_requests"] += 1
        actual = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else price(model, tokens, rates)
        counterfactual = price(data.get("host_model") or host_model, tokens, rates)
        if actual is None or counterfactual is None:
            bucket["unpriced_requests"] += 1
            continue
        bucket["actual_usd"] += actual
        bucket["counterfactual_usd"] += counterfactual
    return {"days": dict(days), "rate": {m: list(v) for m, v in rate.items()}, "hosts": dict(hosts)}


def _merge(total: dict, part: dict) -> None:
    for day, bucket in part["days"].items():
        into = total["days"].setdefault(day, _empty_day())
        for key, value in bucket.items():
            if key == "by_reason":
                for reason, n in value.items():
                    into["by_reason"][reason] = into["by_reason"].get(reason, 0) + n
            else:
                into[key] += value
    for model, n in part.get("hosts", {}).items():
        total.setdefault("hosts", {})
        total["hosts"][model] = total["hosts"].get(model, 0) + n
    for model, (seconds, output, samples) in part["rate"].items():
        entry = total["rate"].setdefault(model, [0.0, 0, 0])
        entry[0] += seconds
        entry[1] += output
        entry[2] += samples


def _load_cache(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        return cache.get("files", {}) if cache.get("version") == CACHE_VERSION else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _save_cache(path: Path | None, files: dict) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": CACHE_VERSION, "files": files}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def summarize(events_dir: str | Path, *, host_model: str | None = None, cheap_model: str | None = None,
              since: str | None = None, rates: dict | None = None, cache_path: str | Path | None = None) -> dict:
    """Aggregate savings across every ``*.jsonl`` session file in ``events_dir``.

    ``since`` (``YYYY-MM-DD``) limits the day buckets. ``cache_path`` keeps
    per-file partials keyed by (size, mtime) so repeated calls only rescan
    changed files. ``cheap_model`` names the start model for the time rate
    (default: the fastest-measured non-host model seen in cheap turns)."""
    rates = {**DEFAULT_RATES, **(rates or {})}
    root = Path(events_dir).expanduser()
    cache_file = Path(cache_path).expanduser() if cache_path else None
    cached = _load_cache(cache_file)
    fresh: dict[str, Any] = {}
    total: dict = {"days": {}, "rate": {}}
    files = sorted(root.glob("*.jsonl")) if root.is_dir() else []
    key_suffix = f"|{host_model or 'auto'}"
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        key = str(path) + key_suffix
        signature = [stat.st_size, stat.st_mtime_ns]
        hit = cached.get(key)
        if hit and hit.get("sig") == signature:
            part = hit["part"]
        else:
            part = scan_file(path, host_model=host_model, rates=rates)
        fresh[key] = {"sig": signature, "part": part}
        _merge(total, part)
    _save_cache(cache_file, fresh)

    days = {d: b for d, b in total["days"].items() if d and (since is None or d >= since)}
    agg = _empty_day()
    for bucket in days.values():
        for key, value in bucket.items():
            if key == "by_reason":
                for reason, n in value.items():
                    agg["by_reason"][reason] = agg["by_reason"].get(reason, 0) + n
            else:
                agg[key] += value

    def rate_of(model):
        seconds, output, samples = total["rate"].get(model, (0.0, 0, 0))
        return (seconds / output if output else None), samples

    # Recorded host models (requests carry the provider's default model);
    # older records without one fall back to DEFAULT_HOST_MODEL.
    recorded_hosts = total.get("hosts", {})
    host_model = host_model or (max(recorded_hosts, key=recorded_hosts.get) if recorded_hosts else DEFAULT_HOST_MODEL)
    host_rate, host_samples = rate_of(host_model)
    if cheap_model is None:
        candidates = [m for m in total["rate"] if m != host_model and _rates_for(m, rates)]
        cheap_model = max(candidates, key=lambda m: total["rate"][m][2]) if candidates else None
    cheap_rate, cheap_samples = rate_of(cheap_model) if cheap_model else (None, 0)
    time_ok = bool(host_rate and cheap_rate and host_samples >= MIN_RATE_SAMPLES and cheap_samples >= MIN_RATE_SAMPLES)
    ratio = (host_rate / cheap_rate) if (time_ok and host_rate and cheap_rate) else None

    saved_usd = agg["counterfactual_usd"] - agg["actual_usd"]
    turns_total = agg["cheap_turns"] + agg["strong_turns"]
    by_day = []
    for day in sorted(days):
        b = days[day]
        by_day.append({
            "day": day, "cheap_turns": b["cheap_turns"], "strong_turns": b["strong_turns"],
            "saved_usd": round(b["counterfactual_usd"] - b["actual_usd"], 4),
            "saved_seconds": round(b["cheap_seconds"] * (ratio - 1), 1) if ratio else None,
        })
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "events_dir": str(root),
        "files": len(files),
        "since": since,
        "host_model": host_model,
        "host_model_source": "recorded" if recorded_hosts else "default",
        "cheap_model": cheap_model,
        "turns": {"total": turns_total, "cheap": agg["cheap_turns"], "strong": agg["strong_turns"],
                  "cheap_share": round(agg["cheap_turns"] / turns_total, 3) if turns_total else None,
                  "by_reason": dict(sorted(agg["by_reason"].items())), "judge_calls": agg["judge_calls"]},
        "cost": {"cheap_turns_actual_usd": round(agg["actual_usd"], 4),
                 "cheap_turns_on_host_usd": round(agg["counterfactual_usd"], 4),
                 "saved_usd": round(saved_usd, 4),
                 "saved_pct_of_cheap_turns": round(saved_usd / agg["counterfactual_usd"], 3) if agg["counterfactual_usd"] else None,
                 "unpriced_requests": agg["unpriced_requests"],
                 "provider_costed_requests": agg["provider_costed_requests"],
                 # Older records lack cached-token counts and the provider's
                 # cost, so their tokens are all priced as fresh input, which
                 # overstates both actual and host-model dollars.
                 "requests_without_cache_data": agg["no_cache_data_requests"]},
        "time": {
            "available": time_ok,
            "cheap_turns_model_seconds": round(agg["cheap_seconds"], 1),
            "cheap_turns_on_host_seconds": round(agg["cheap_seconds"] * ratio, 1) if ratio else None,
            "saved_seconds": round(agg["cheap_seconds"] * (ratio - 1), 1) if ratio else None,
            "host_s_per_output_token": round(host_rate, 5) if host_rate else None,
            "cheap_s_per_output_token": round(cheap_rate, 5) if cheap_rate else None,
            "rate_samples": {"host": host_samples, "cheap": cheap_samples},
            "reason": None if time_ok else f"needs {MIN_RATE_SAMPLES}+ requests with {MIN_RATE_OUTPUT}+ output tokens on both models",
        },
        "tokens": {k: agg[k] for k in ("input", "output", "cache_read", "cache_write")},
        "by_day": by_day,
        "method": ("Cheap turns only; strong turns run the host setup unchanged. Cost: the same recorded tokens "
                   "priced at host-model rates vs actual. Time: cheap-turn model time scaled by the measured "
                   "host/start generation-rate ratio. Estimates: the host model would not produce identical "
                   "tokens or steps. Tool time, start-up and judge calls are not counted."),
    }
