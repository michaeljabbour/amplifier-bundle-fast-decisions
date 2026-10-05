"""The effective fast-decisions configuration, loaded once, from one place.

Layers, lowest to highest precedence:

1. the shipped behavior, ``behaviors/fast-decisions.yaml`` (``session.orchestrator.config``): the only copy
   of the research-backed defaults. A checkout reads it in place; an installed wheel reads the packaged copy
   (``amplifier_fast_decisions/shipped/fast-decisions.yaml``, built from the same file).
2. the user settings overlay, ``~/.amplifier/fast-decisions/settings.yaml`` (or the file named by
   ``AFAST_SETTINGS``): a mapping of orchestrator-config keys, deep-merged over the shipped config.
3. explicit overrides passed by the caller (``decide(config=...)``, CLI flags).

``Policy.from_config`` then validates the result, so a malformed overlay fails loudly. ``orchestrator``,
``decide``, ``afast doctor`` and the smart tool all call ``effective_config``; nothing else holds defaults.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import Policy

BEHAVIOR_NAME = "fast-decisions.yaml"
SETTINGS_ENV = "AFAST_SETTINGS"
BEHAVIOR_ENV = "AFAST_BEHAVIOR_FILE"
DEFAULT_SETTINGS = Path.home() / ".amplifier" / "fast-decisions" / "settings.yaml"


class ConfigError(ValueError):
    """The shipped behavior, a settings overlay or an override could not be loaded or validated."""


def _yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - PyYAML is a declared dependency
        raise ConfigError("PyYAML is required to load the fast-decisions configuration: pip install pyyaml") from exc
    return yaml


def shipped_behavior_path() -> Path:
    """The shipped behavior file: ``AFAST_BEHAVIOR_FILE``, else the checkout copy, else the packaged copy."""
    explicit = os.getenv(BEHAVIOR_ENV)
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"{BEHAVIOR_ENV} does not name a file: {path}")
        return path
    here = Path(__file__).resolve().parent
    for candidate in (here.parents[1] / "behaviors" / BEHAVIOR_NAME, here / "shipped" / BEHAVIOR_NAME):
        if candidate.is_file():
            return candidate
    raise ConfigError("shipped behaviors/fast-decisions.yaml not found (checkout or package data)")


def orchestrator_config(path: Path) -> dict[str, Any]:
    """``session.orchestrator.config`` of a behavior/bundle file."""
    try:
        data = _yaml().safe_load(path.read_text(encoding="utf-8"))
        return copy.deepcopy(data["session"]["orchestrator"]["config"])
    except (OSError, KeyError, TypeError) as exc:
        raise ConfigError(f"{path} has no session.orchestrator.config") from exc


@lru_cache(maxsize=4)
def _shipped(path: str) -> str:
    return json.dumps(orchestrator_config(Path(path)), sort_keys=True)


def shipped_config() -> dict[str, Any]:
    """A private copy of the shipped orchestrator config (parsed once per path per process)."""
    return json.loads(_shipped(str(shipped_behavior_path())))


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def settings_path() -> Path:
    return Path(os.getenv(SETTINGS_ENV) or DEFAULT_SETTINGS).expanduser()


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """The user overlay, or ``{}`` when the file is absent. A present but malformed file raises."""
    path = path or settings_path()
    if not path.is_file():
        return {}
    try:
        data = _yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # yaml.YAMLError and OSError
        raise ConfigError(f"cannot read settings {path}: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"settings {path} must be a mapping of orchestrator-config keys")
    return data


@dataclass
class EffectiveConfig:
    config: dict[str, Any]
    policy: Policy
    sources: list[str] = field(default_factory=list)

    @property
    def model_routing(self) -> dict[str, Any]:
        return self.policy.model_routing or {}

    @property
    def effort_routing(self) -> dict[str, Any]:
        return self.policy.effort_routing or {}

    @property
    def sha(self) -> str:
        return hashlib.sha256(json.dumps(self.config, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def effective_config(overrides: dict[str, Any] | None = None, *, use_settings: bool = True,
                     settings: Path | None = None) -> EffectiveConfig:
    """Shipped behavior + user overlay + explicit overrides, validated through ``Policy.from_config``."""
    config = shipped_config()
    sources = [str(shipped_behavior_path())]
    if use_settings:
        overlay = load_settings(settings)
        if overlay:
            config = deep_merge(config, overlay)
            sources.append(str(settings or settings_path()))
    if overrides:
        config = deep_merge(config, overrides)
        sources.append("overrides")
    try:
        policy = Policy.from_config(config)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"invalid effective configuration: {exc}") from exc
    return EffectiveConfig(config=config, policy=policy, sources=sources)


PHASE_KEYS = ("orient", "explore", "implement")
KNOWN_HOSTS = ("claude-opus-5-5", "claude-fable-5-1")


def config_report(host_model: str | None = None, *, overrides: dict[str, Any] | None = None,
                  use_settings: bool = True, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Load and validate the effective configuration and report what it will do. No network, no model call,
    no secret values (credential variables are reported present/absent only).

    Shared by ``afast doctor`` and the smart tool's ``diagnose`` so the two cannot disagree. ``host_model``
    defaults to ``AFAST_HOST_MODEL``; without either, the price gate is reported for the two priced hosts."""
    from . import judge_backends, price_gate

    env = os.environ if env is None else env
    try:
        eff = effective_config(overrides, use_settings=use_settings)
    except ConfigError as exc:
        return {"ok": False, "error": str(exc), "warnings": [str(exc)]}
    cfg, routing, effort = eff.config, eff.model_routing, eff.effort_routing
    warnings: list[str] = []
    backend_name = cfg.get("backend") or "jev"
    spec = judge_backends.spec(backend_name)
    if spec is None:
        warnings.append(f"unknown backend {backend_name!r}")
    consent_cfg = bool(cfg.get("allow_external_state", False))
    consent_env = env.get("FAST_DECISIONS_ALLOW_EXTERNAL_STATE")
    credentials = {name: bool(env.get(name)) for name in (spec.env if spec else ())
                   if name.endswith(("_KEY", "_TOKEN", "_ACCOUNT_ID"))}
    if spec and spec.external:
        if not consent_cfg:
            warnings.append(f"{backend_name} is an external judge and allow_external_state is false: the judge is never "
                            "asked and every decision falls back to the prompt-length rule")
        missing = [name for name, present in credentials.items() if not present]
        if missing:
            warnings.append("missing credential environment variable(s): " + ", ".join(missing))
        if spec.opt_in:
            warnings.append(f"{backend_name} is opt-in: no shipped default selects it")
    phase = [k for k in PHASE_KEYS if k in effort]
    if phase:
        warnings.append("effort_routing carries a per-phase effort map (" + ", ".join(phase) + "): an effort change "
                        "between requests rewrites the provider's prompt cache; use by_tier only")
    hosts = [host_model or env.get("AFAST_HOST_MODEL")] if (host_model or env.get("AFAST_HOST_MODEL")) else list(KNOWN_HOSTS)
    start_model = routing.get("start_model")
    gates = []
    for host in hosts:
        if routing.get("price_gate") is None or not start_model:
            gates.append({"host_model": host, "enabled": False})
            continue
        g = price_gate.evaluate(host, start_model, routing["price_gate"])
        gates.append({"host_model": host, "route": g.route, "reason": g.reason,
                      "predicted_cost_ratio": None if g.predicted_ratio is None else round(g.predicted_ratio, 4),
                      "request_multiplier": g.request_multiplier, "multiplier_source": g.multiplier_source})
    return {
        "ok": True, "config_sha": eff.sha, "sources": eff.sources,
        "backend": {"name": backend_name, "external": bool(spec and spec.external), "opt_in": bool(spec and spec.opt_in),
                    "credentials_present": credentials},
        "consent": {"allow_external_state": consent_cfg, "env_FAST_DECISIONS_ALLOW_EXTERNAL_STATE": consent_env,
                    "note": "decide/select take consent from their argument or the environment variable, never from this file"},
        "decision": {"start_policy": routing.get("start_policy", "cheap"), "decision_scope": routing.get("decision_scope", "turn"),
                     "start_model": start_model, "provider_match": routing.get("provider_match"),
                     "keep_on_host": (routing.get("keep_on_host") or {}).get("task_types")},
        "scope_gate": {"cheap_max_workspace_files": routing.get("cheap_max_workspace_files")},
        "effort": {"by_tier": effort.get("by_tier"), "phase_map": phase, "constant_within_session": not phase},
        "read_shortcut": eff.policy.read_shortcut, "timeout_ms": eff.policy.timeout_ms,
        "thresholds": {"min_probability": eff.policy.min_probability, "min_margin": eff.policy.min_margin},
        "price_gate": gates, "warnings": warnings,
    }
