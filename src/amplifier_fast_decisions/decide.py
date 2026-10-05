"""``decide``: the session-start routing decision, usable from any harness.

One typed question, asked once at the start of a session: should it run on the cheaper start model (and at
which effort), or stay on the host model unchanged? The answer is computed by the SAME code the Amplifier
orchestrator runs at turn 1 -- ``orchestrator.decide_start_tier`` (price gate, scope gate, judge, task-type
opt-out), ``price_gate.evaluate``, ``orchestrator.tier_effort_decision`` and ``orchestrator.start_model_is_cheaper``
-- over the defaults in ``behaviors/fast-decisions.yaml`` (see ``config``). Nothing here has its own thresholds.

    >>> from amplifier_fast_decisions.decide import decide
    >>> d = decide("fix the typo in README", "claude-fable-5-1", workspace=".")
    >>> d.route, d.model, d.effort, d.reason

``decide`` is advisory: it never executes anything. The caller (``amplifier-fast-decisions launch``, an agent
skill, a study harness) applies ``model``/``effort``. Decide once per session and keep it: switching model or
effort between requests rewrites the provider's prompt cache.

Consent: outside Amplifier, composing a bundle is not consent to send the task text to an external judge. An
external decider therefore needs ``allow_external_state=True`` (argument) or
``FAST_DECISIONS_ALLOW_EXTERNAL_STATE=true``; the shipped bundle's ``allow_external_state: true`` is NOT inherited.
Without consent the decision falls back to the prompt-length rule and says so (``judge.status``).
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from . import judge_backends, price_gate
from .config import EffectiveConfig, effective_config
from .contracts import TurnState
from .orchestrator import decide_start_tier, start_model_is_cheaper, tier_effort_decision
from .runtime import build_backend
from .service import DecisionService
from .telemetry import Emitter

SCHEMA = "fd-decision/1"
NON_MODEL_DECIDERS = ("rules", "always-host", "always-cheap")
# ``provider_match`` in model_routing names a provider family; the harness only tells us the host model id.
_PROVIDER_MODEL_PREFIXES = {"anthropic": ("claude",)}


def deciders() -> list[str]:
    """Names accepted by ``--decider``: every judge backend plus the three study deciders."""
    return [*judge_backends.names("runtime", aliases=True), *NON_MODEL_DECIDERS]


@dataclass(frozen=True)
class Decision:
    """The typed session-start decision. ``route`` False means: run the host model unchanged."""
    route: bool
    tier: str                       # "cheap" | "strong" (the judged tier; ``route`` also needs the host to be pricier)
    model: str | None               # the model to start the session on (the host model when route is False)
    effort: str | None              # reasoning effort to set for the whole session; None = leave the harness default
    reason: str                     # machine-readable: judge_cheap, price_gate_strong, scope_strong, ...
    host_model: str | None
    start_model: str                # the cheap model considered
    decider: str
    gate: dict[str, Any]            # price-gate receipt: rates, request multiplier, predicted cost ratio, reason
    judge: dict[str, Any]           # {backend, status, p_complex, task_type, duration_ms}
    scope: str = "session"
    workspace_files: int | None = None
    scope_limit: int | None = None
    latency_ms: float = 0.0
    usd: float | None = None        # estimated billed cost of the judge call(s); None = unpriced or none made
    config_sha: str = ""
    config_sources: tuple[str, ...] = ()
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["config_sources"] = list(self.config_sources)
        return out


class _Coordinator:
    """The one capability ``orchestrator.session_working_dir`` reads."""

    def __init__(self, workspace: str):
        self.session_id = "decide"
        self.hooks = None
        self._workspace = workspace

    def get_capability(self, key: str) -> Any:
        return self._workspace if key == "session.working_dir" else None


class _FixedBackend:
    """Stand-in judge for ``rules`` / ``always-*`` deciders: never asked (start_policy rules or short-circuit)."""
    name = "none"
    external = False

    async def ask(self, request):  # pragma: no cover - never reached
        raise RuntimeError("no judge")

    ask_many = ask

    async def close(self) -> None:
        return None


def _consent(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.getenv("FAST_DECISIONS_ALLOW_EXTERNAL_STATE", "").strip().lower() in ("1", "true", "yes", "on")


def _provider_matches(model_routing: dict[str, Any], host: str | None) -> bool:
    needle = model_routing.get("provider_match")
    prefixes = _PROVIDER_MODEL_PREFIXES.get(needle.lower()) if isinstance(needle, str) else None
    if prefixes is None:
        return True
    return isinstance(host, str) and host.lower().startswith(prefixes)


async def adecide(task: str, host_model: str | None, workspace: str | os.PathLike[str] | None = None, *,
                  config: dict[str, Any] | None = None, decider: str | None = None,
                  allow_external_state: bool | None = None, cheap_model: str | None = None,
                  user_model: str | None = None, use_settings: bool = True,
                  _backend: Any = None, _effective: EffectiveConfig | None = None) -> Decision:
    """Async ``decide``. ``config`` overrides orchestrator-config keys (deep-merged over the shipped behavior and
    the user settings overlay); ``decider`` overrides the judge (see ``deciders()``); ``cheap_model`` replaces
    ``model_routing.start_model`` (the price gate is re-evaluated for it, and the provider match is skipped);
    ``user_model`` is a model the user already picked: it always wins. ``_backend`` is a test seam."""
    started = time.perf_counter()
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if decider is not None and decider not in deciders():
        raise ValueError(f"decider must be one of {', '.join(deciders())}")
    eff = _effective or effective_config(config, use_settings=use_settings)
    routing = dict(eff.model_routing)
    if not routing.get("start_model"):
        raise ValueError("effective configuration has no model_routing.start_model")
    if cheap_model:
        routing["start_model"] = cheap_model
        routing["provider_match"] = None
    start_model = routing["start_model"]
    consent = _consent(allow_external_state)
    policy = dataclasses.replace(eff.policy, allow_external_state=consent)
    workspace_dir = os.fspath(workspace) if workspace is not None else os.getcwd()

    name = decider or eff.config.get("backend") or "jev"
    always: str | None = None
    if name in ("always-host", "always-cheap"):
        always, backend = name, _FixedBackend()
    elif name == "rules":
        routing["start_policy"] = "rules"
        backend = _FixedBackend()
    else:
        backend = _backend or build_backend({**eff.config, "backend": name, "model": eff.config.get("model")}, policy)
    spec = judge_backends.spec(getattr(backend, "name", name)) or judge_backends.spec(name)

    events: list[dict[str, Any]] = []
    service = DecisionService(policy, backend, Emitter("decide", callback=events.append), _Coordinator(workspace_dir), [])
    service.turn = TurnState("decide")
    request = SimpleNamespace(messages=[{"role": "user", "content": task}])
    gate = None
    if routing.get("price_gate") is not None and not user_model:
        gate = price_gate.evaluate(host_model, start_model, routing["price_gate"])
    try:
        if always == "always-host":
            tier, reason = "strong", "decider_always_host"
        elif always == "always-cheap":
            tier, reason = "cheap", "decider_always_cheap"
        else:
            tier = await decide_start_tier(service, request, routing, None, user_model=user_model, gate=gate)
            judged = [e["data"] for e in events if e["event"].endswith("difficulty_judged")]
            reason = (service.turn.start_reason or (judged[-1].get("reason_code") if judged else None)
                      or ("start_policy_cheap" if routing.get("start_policy", "cheap") == "cheap" else f"rules_{tier}"))
    finally:
        if _backend is None:
            await backend.close()

    turn = service.turn
    judged = [e["data"] for e in events if e["event"].endswith("difficulty_judged")]
    last = judged[-1] if judged else {}
    p_complex = (turn.start_probabilities or {}).get("complex")
    scope_limit = routing.get("cheap_max_workspace_files")
    if turn.start_scope_files is not None:
        files: int | None = turn.start_scope_files
    elif last.get("candidate_count") is not None:
        files = last["candidate_count"]
    else:
        files = None
    usage = [e["data"] for e in events if e["event"].endswith("judge_usage")]

    # Judge status: why the decision came from the judge, or why it did not.
    if user_model:
        status = "skipped_user_model"
    elif always or routing.get("start_policy") != "judge":
        status = "not_used"
    elif reason.startswith("price_gate"):
        status = "skipped_price_gate"
    elif reason.startswith("scope_strong"):
        status = "skipped_scope_gate"
    elif p_complex is not None:
        status = "answered"
    elif spec is not None and spec.external and not consent:
        status = "no_consent"
    else:
        status = "unanswered"
    tokens = [u.get("input_tokens") for u in usage if isinstance(u.get("input_tokens"), (int, float))]
    usd = (sum(tokens) * spec.price_in_per_m / 1e6) if (tokens and spec is not None and spec.price_in_per_m) else None
    judge = {"backend": None if status in ("not_used", "skipped_user_model") else getattr(backend, "name", name),
             "status": status, "p_complex": p_complex, "task_type": turn.task_type,
             "duration_ms": round(float(turn.judge_seconds or 0.0) * 1000, 1)}

    # Model and effort: the same rules RoutedProvider.complete applies after the tier is known.
    route, model = False, host_model
    effective_reason = reason
    if user_model:
        model = user_model
    elif tier == "cheap":
        chosen = turn.tier_model or start_model
        if not _provider_matches(routing, host_model):
            effective_reason = "provider_not_matched"
        elif not start_model_is_cheaper(host_model, chosen):
            effective_reason = "host_already_cheaper"
        else:
            route, model = True, chosen
    pick = bool(user_model)
    decided, effort, _ = tier_effort_decision(
        eff.effort_routing, start_tier=tier, escalated=False, tier_effort=turn.tier_effort,
        tier_label=turn.tier_label, user_model_pick=pick, host_pinned=False)
    if not decided:
        effort = None
    if route and effort is None and routing.get("start_effort"):
        effort = routing["start_effort"]
    return Decision(
        route=route, tier=tier, model=model, effort=effort, reason=effective_reason, host_model=host_model,
        start_model=start_model, decider=name, gate=gate.receipt() if gate is not None else {"enabled": False},
        judge=judge, scope=routing.get("decision_scope", "turn"), workspace_files=files, scope_limit=scope_limit,
        latency_ms=round((time.perf_counter() - started) * 1000, 2), usd=usd, config_sha=eff.sha,
        config_sources=tuple(eff.sources))


def decide(task: str, host_model: str | None, workspace: str | os.PathLike[str] | None = None, **kwargs: Any) -> Decision:
    """Synchronous ``adecide`` for scripts and CLIs. Inside a running event loop, ``await adecide(...)``."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(adecide(task, host_model, workspace, **kwargs))
    raise RuntimeError("decide() cannot run inside a running event loop; use `await adecide(...)`")
