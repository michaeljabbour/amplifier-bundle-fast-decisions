"""Price gate: route to the cheap start model only when it is predicted to cost less for the session.

Evidence: docs/evidence/2026-10-02-paired-campaign (data/sessions.jsonl), derived by
evals/price_gate_replay.py ``derive``. Pure and stdlib-only (same layering as contracts.py).

predicted_ratio = request_multiplier(host) * per_request_usd(cheap) / per_request_usd(host)
route           = predicted_ratio < 1.0
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .savings import DEFAULT_RATES, _rates_for

RATES_VERIFIED = "2026-06-10"  # same date as savings.DEFAULT_RATES
EVIDENCE = "docs/evidence/2026-10-02-paired-campaign"
# Per main request, pooled plain-host anchors of main-v1 (280 sessions, 11,537 requests).
REFERENCE_MIX: dict[str, int] = {"input": 3, "cache_read": 88516, "cache_write": 5376, "output": 541}
# Cheap-model (Sonnet 5, medium effort) main requests / host main requests, paired, main-v1.
REQUEST_MULTIPLIERS: dict[str, float] = {"claude-opus-5-5": 1.38, "claude-fable-5-1": 1.11}
DEFAULT_REQUEST_MULTIPLIER = 1.38
PRICE_GATE_KEYS = frozenset({"enabled", "request_multipliers", "default_request_multiplier", "rates"})


@dataclass(frozen=True)
class GateResult:
    route: bool
    reason: str  # price_gate_route | price_gate_host | same_model | host_unknown | host_unpriced | cheap_unpriced | gate_disabled
    host_model: str | None
    cheap_model: str
    predicted_ratio: float | None
    request_multiplier: float | None
    multiplier_source: str | None  # "config" | "table" | "default"
    host_rates: tuple[float, ...] | None
    cheap_rates: tuple[float, ...] | None
    rates_source: str  # "default" | "config"

    def receipt(self) -> dict[str, Any]:
        data = asdict(self)
        ratio = data.pop("predicted_ratio")
        data["predicted_cost_ratio"] = None if ratio is None else round(ratio, 4)
        for key in ("host_rates", "cheap_rates"):
            if data[key] is not None:
                data[key] = list(data[key])
        data["enabled"] = self.reason != "gate_disabled"
        data["reference_mix"] = dict(REFERENCE_MIX)
        data["rates_verified"] = RATES_VERIFIED
        data["evidence"] = EVIDENCE
        return data


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(cfg: Any) -> None:
    """Raise ValueError on a malformed ``model_routing.price_gate`` block."""
    if not isinstance(cfg, dict):
        raise ValueError("model_routing.price_gate must be a dict")
    unknown = set(cfg) - PRICE_GATE_KEYS
    if unknown:
        raise ValueError(f"model_routing.price_gate has unknown keys: {sorted(unknown)}")
    if "enabled" in cfg and not isinstance(cfg["enabled"], bool):
        raise ValueError("model_routing.price_gate.enabled must be a bool")
    multipliers = cfg.get("request_multipliers")
    if multipliers is not None:
        if not isinstance(multipliers, dict):
            raise ValueError("model_routing.price_gate.request_multipliers must be a dict")
        for model, value in multipliers.items():
            if not isinstance(model, str) or not model or not _number(value) or not 0 < value <= 10:
                raise ValueError("model_routing.price_gate.request_multipliers must map model ids to numbers in (0, 10]")
    default = cfg.get("default_request_multiplier")
    if default is not None and (not _number(default) or not 0 < default <= 10):
        raise ValueError("model_routing.price_gate.default_request_multiplier must be a number in (0, 10]")
    rates = cfg.get("rates")
    if rates is not None:
        if not isinstance(rates, dict):
            raise ValueError("model_routing.price_gate.rates must be a dict")
        for model, value in rates.items():
            if (not isinstance(model, str) or not model or not isinstance(value, (list, tuple)) or len(value) != 4
                    or not all(_number(v) and v >= 0 for v in value)):
                raise ValueError(
                    "model_routing.price_gate.rates must map model ids to [input, output, cache_read, cache_write] USD/M, each >= 0")


def enabled(cfg: Any) -> bool:
    return isinstance(cfg, dict) and cfg.get("enabled", True) is True


def per_request_usd(rates: tuple | list, mix: dict | None = None) -> float:
    mix = REFERENCE_MIX if mix is None else mix
    r_in, r_out, r_read, r_write = rates
    return (mix["input"] * r_in + mix["output"] * r_out + mix["cache_read"] * r_read
            + mix["cache_write"] * r_write) / 1e6


def _lookup(model: str, table: dict) -> Any:
    """Exact id, else the longest family prefix (so dated ids match)."""
    if model in table:
        return table[model]
    for name in sorted(table, key=len, reverse=True):
        if model.startswith(name):
            return table[name]
    return None


def multiplier_for(host: str, cfg: dict | None) -> tuple[float, str]:
    """config (prefix match) > table (prefix match) > default."""
    cfg = cfg or {}
    value = _lookup(host, cfg.get("request_multipliers") or {})
    if value is not None:
        return float(value), "config"
    value = _lookup(host, REQUEST_MULTIPLIERS)
    if value is not None:
        return float(value), "table"
    return float(cfg.get("default_request_multiplier", DEFAULT_REQUEST_MULTIPLIER)), "default"


def _rates(model: str, cfg: dict) -> tuple[tuple | None, bool]:
    override = cfg.get("rates") or {}
    value = _lookup(model, override)
    if value is not None:
        return tuple(float(v) for v in value), True
    return _rates_for(model, DEFAULT_RATES), False


def evaluate(host_model: str | None, cheap_model: str, cfg: dict | None) -> GateResult:
    """Decide whether routing to ``cheap_model`` is predicted to be cheaper than staying on the host."""
    def result(route: bool, reason: str, **kw: Any) -> GateResult:
        fields: dict[str, Any] = dict(predicted_ratio=None, request_multiplier=None, multiplier_source=None,
                                      host_rates=None, cheap_rates=None, rates_source="default")
        fields.update(kw)
        return GateResult(route=route, reason=reason, host_model=host_model if isinstance(host_model, str) else None,
                          cheap_model=cheap_model, **fields)

    if not enabled(cfg):
        return result(True, "gate_disabled")
    cfg = cfg or {}
    if not isinstance(host_model, str) or not host_model:
        return result(False, "host_unknown")
    if host_model == cheap_model or host_model.startswith(cheap_model) or cheap_model.startswith(host_model):
        return result(False, "same_model")
    host_rates, host_cfg = _rates(host_model, cfg)
    cheap_rates, cheap_cfg = _rates(cheap_model, cfg)
    source = "config" if host_cfg or cheap_cfg else "default"
    if not host_rates:
        return result(False, "host_unpriced", rates_source=source)
    if not cheap_rates:
        return result(False, "cheap_unpriced", host_rates=host_rates, rates_source=source)
    multiplier, multiplier_source = multiplier_for(host_model, cfg)
    ratio = multiplier * per_request_usd(cheap_rates) / per_request_usd(host_rates)
    return result(ratio < 1.0, "price_gate_route" if ratio < 1.0 else "price_gate_host",
                  predicted_ratio=ratio, request_multiplier=multiplier, multiplier_source=multiplier_source,
                  host_rates=host_rates, cheap_rates=cheap_rates, rates_source=source)


def break_even_cache_read(host_model: str, cheap_model: str, cfg: dict | None = None) -> float | None:
    """Host cache-read price (USD/M) at which the gate starts routing, other prices held fixed."""
    cfg = cfg or {}
    host_rates, _ = _rates(host_model, cfg)
    cheap_rates, _ = _rates(cheap_model, cfg)
    if not host_rates or not cheap_rates or not REFERENCE_MIX["cache_read"]:
        return None
    multiplier, _ = multiplier_for(host_model, cfg)
    target = multiplier * per_request_usd(cheap_rates)
    without_reads = per_request_usd((host_rates[0], host_rates[1], 0.0, host_rates[3]))
    return (target - without_reads) * 1e6 / REFERENCE_MIX["cache_read"]
