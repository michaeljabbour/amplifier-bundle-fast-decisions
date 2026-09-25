"""Turn planner: cache- and price-aware model choice for one easy turn.

See docs/proposals/TURN-PLANNER.md for the full specification. This module
is a PURE function (no Amplifier, network, or clock side effects beyond the
``now`` parameter the caller supplies): the orchestrator gathers the inputs
(host, candidates, per-session cache state, ``ctx``), calls ``plan_turn``,
records the returned per-model cache state after the real provider call,
and applies the returned ``choice``. No amplifier_core import.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .savings import _rates_for


def _prior_for(model: str, priors: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Prefix-matched prior lookup for ``model``, mirroring
    ``savings._rates_for``'s dated-id matching: an exact key wins, else the
    longest prior name that is a prefix of ``model`` (a dated id like
    ``claude-sonnet-5-20260101`` matches the family entry
    ``claude-sonnet-5``). ``None`` when no prior matches.
    """
    if model in priors:
        return priors[model]
    for name in sorted(priors, key=len, reverse=True):
        if model.startswith(name):
            return priors[name]
    return None


def _option(
    model: str,
    *,
    ctx: int,
    state: dict[str, dict[str, Any]],
    now: float,
    cache_ttl_seconds: float,
    expected_calls: float,
    output_tokens_per_call: float,
    priors: dict[str, dict[str, float]],
    rates: dict[str, tuple[float, float, float, float]],
) -> dict[str, Any] | None:
    """One option's ``{model, warm, cold, cost, time}``, or ``None`` when
    ``model`` has no price (``rates``, ``savings.DEFAULT_RATES``-shaped) or
    no prior -- per spec, such a model "is not a candidate".
    """
    rate = _rates_for(model, rates)
    prior = _prior_for(model, priors)
    if rate is None or prior is None:
        return None
    entry = state.get(model)
    warm = bool(
        entry is not None
        and (now - entry.get("last_used_at", float("-inf"))) < cache_ttl_seconds
    )
    cached_tokens = entry.get("cached_tokens", 0) if (warm and entry) else 0
    cold = max(0, ctx - cached_tokens) if warm else ctx
    calls_factor = prior.get("calls_factor", 1.0)
    n = expected_calls * calls_factor
    read_rate, write_rate = rate[2], rate[3]
    output_rate = rate[1]
    cost = (
        cold * write_rate
        + (ctx - cold) * read_rate
        + (n - 1) * ctx * read_rate
        + n * output_tokens_per_call * output_rate
    ) / 1_000_000
    latency_s = prior.get("latency_s", 0.0)
    cold_s_per_100k = prior.get("cold_s_per_100k", 0.0)
    time_s = n * latency_s + cold / 100_000 * cold_s_per_100k
    return {"model": model, "warm": warm, "cold": cold, "cost": cost, "time": time_s}


def plan_turn(
    host: str,
    candidates: Sequence[str],
    state: dict[str, dict[str, Any]],
    ctx: int,
    now: float,
    config: dict[str, Any],
    rates: dict[str, tuple[float, float, float, float]],
) -> dict[str, Any]:
    """Decide the model for one easy turn (spec:
    docs/proposals/TURN-PLANNER.md).

    ``state`` maps a model id to ``{"last_used_at": float, "cached_tokens": int}``,
    updated by the caller after every real provider response -- this
    function only reads it. ``config`` is the merged
    ``model_routing.planner`` dict (``objective``, ``cost_tolerance``,
    ``cache_ttl_seconds``, ``expected_calls``, ``output_tokens_per_call``,
    ``priors``); ``candidates`` are the cheap models to consider alongside
    the host.

    Returns::

        {
            "ctx": ctx,
            "objective": objective,
            "host": host,
            "options": [{"model", "warm", "cold", "cost", "time"}, ...],
            "choice": <model id> | None,
            "abstained": bool,
        }

    ``abstained`` is ``True`` only when the host itself has no price or no
    prior -- per spec, "the planner abstains and today's behaviour
    applies" (the caller must fall back to its pre-planner logic; ``choice``
    is ``None`` and ``options`` is empty in that case). Otherwise ``choice``
    is always a model id present in ``options`` -- ``host`` when the host is
    chosen, a candidate id otherwise. Ties go to the host.
    """
    objective = config.get("objective", "balanced")
    cache_ttl_seconds = config.get("cache_ttl_seconds", 300)
    expected_calls = config.get("expected_calls", 3.5)
    output_tokens_per_call = config.get("output_tokens_per_call", 170)
    priors = config.get("priors") or {}
    cost_tolerance = config.get("cost_tolerance", 0.05)

    def option_for(model: str) -> dict[str, Any] | None:
        return _option(
            model,
            ctx=ctx,
            state=state,
            now=now,
            cache_ttl_seconds=cache_ttl_seconds,
            expected_calls=expected_calls,
            output_tokens_per_call=output_tokens_per_call,
            priors=priors,
            rates=rates,
        )

    host_option = option_for(host)
    if host_option is None:
        return {
            "ctx": ctx,
            "objective": objective,
            "host": host,
            "options": [],
            "choice": None,
            "abstained": True,
        }

    options = [host_option]
    seen = {host}
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        option = option_for(candidate)
        if option is not None:
            options.append(option)

    host_cost = host_option["cost"]

    if objective == "speed":
        best = min(opt["time"] for opt in options)
        winners = [opt["model"] for opt in options if opt["time"] == best]
    elif objective == "cost":
        best = min(opt["cost"] for opt in options)
        winners = [opt["model"] for opt in options if opt["cost"] == best]
    else:  # balanced
        budget = host_cost * (1 + cost_tolerance)
        eligible = [opt for opt in options if opt["model"] == host or opt["cost"] <= budget]
        best = min(opt["time"] for opt in eligible)
        winners = [opt["model"] for opt in eligible if opt["time"] == best]

    choice = host if host in winners else winners[0]

    return {
        "ctx": ctx,
        "objective": objective,
        "host": host,
        "options": options,
        "choice": choice,
        "abstained": False,
    }
