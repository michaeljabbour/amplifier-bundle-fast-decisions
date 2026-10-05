"""The one judge-backend vocabulary.

``runtime.build_backend`` (the orchestrator, hooks and ``decide``), the portable smart tool
(``select``/``decide``) and ``afast configure`` all take their backend names from ``BACKENDS``. Adding a
backend means adding one row here and one branch where it is constructed; ``tests/test_backend_table.py``
fails if a surface drifts from this table.

Pure and stdlib-only (same layering as ``contracts.py``).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BackendSpec:
    name: str
    external: bool          # state leaves the machine: needs allow_external_state
    summary: str
    aliases: tuple[str, ...] = ()
    env: tuple[str, ...] = ()   # environment variables it reads (names only, never values)
    opt_in: bool = False        # never selected by a shipped default
    select: bool = True         # accepted by the portable ``select`` capability
    configure: bool = True      # accepted by ``afast configure --backend``
    price_in_per_m: float | None = None  # USD per million input tokens (output not billed); None = unpriced/local


BACKENDS: tuple[BackendSpec, ...] = (
    BackendSpec("jev", True, "Jev System One (TypeSafe). The shipped default judge.",
                env=("TYPESAFE_API_KEY", "TYPESAFE_DEFAULT_MODEL"), price_in_per_m=0.042),
    BackendSpec("clef", True, "Cloudflare Workers AI `clef` decision model (System One body in the Workers AI envelope).",
                env=("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"), opt_in=True, price_in_per_m=0.24),
    BackendSpec("clef-flash", True, "Cloudflare Workers AI `clef-flash` (smaller, cheaper than clef).",
                env=("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"), opt_in=True, price_in_per_m=0.09),
    BackendSpec("ollama", False, "Local Ollama token-probability scorer (default model qwen3:0.6b).",
                aliases=("local",), env=("FAST_DECISIONS_OLLAMA_URL", "FAST_DECISIONS_LOCAL_MODEL")),
    BackendSpec("mlx", False, "Local mlx_lm.server token-probability scorer.", env=("FAST_DECISIONS_LOCAL_MODEL",),
                select=False),
    BackendSpec("laya", False, "Laya decide server (loopback by default; experimental).",
                env=("FAST_DECISIONS_LAYA_URL",), opt_in=True),
    BackendSpec("hosted", True, "Your own OpenAI-compatible endpoint that returns top_logprobs.",
                aliases=("gateway",), env=("FAST_DECISIONS_HOSTED_URL", "FAST_DECISIONS_HOSTED_TOKEN"),
                opt_in=True, select=False),
    BackendSpec("anyjev", False, "AnyJev loopback server (opt-in, fixed choice questions).", opt_in=True,
                select=False, configure=False),
    BackendSpec("deterministic", False, "In-process offline scorer for shadow/tests; not a model.",
                select=False),
    BackendSpec("unavailable", False, "No judge: routing rules only.", aliases=("none",), select=False,
                configure=False),
)

_BY_NAME: dict[str, BackendSpec] = {}
for _spec in BACKENDS:
    _BY_NAME[_spec.name] = _spec
    for _alias in _spec.aliases:
        _BY_NAME[_alias] = _spec


def spec(name: str | None) -> BackendSpec | None:
    """The row for a backend name or alias, else None."""
    return _BY_NAME.get(name) if isinstance(name, str) else None


def canonical(name: str | None) -> str | None:
    found = spec(name)
    return found.name if found else None


def names(surface: str = "runtime", *, aliases: bool = False) -> list[str]:
    """Canonical names accepted on a surface: ``runtime`` (all), ``select`` or ``configure``."""
    if surface not in {"runtime", "select", "configure"}:
        raise ValueError(f"unknown surface {surface!r}")
    rows = [s for s in BACKENDS if surface == "runtime" or getattr(s, surface)]
    out = [s.name for s in rows]
    if aliases:
        out += [a for s in rows for a in s.aliases]
    return out


def describe(surface: str = "runtime") -> str:
    """One line per backend accepted on ``surface``, for ``--help`` text and docs."""
    rows = [s for s in BACKENDS if surface == "runtime" or getattr(s, surface)]
    return "; ".join(f"{s.name}{' (external)' if s.external else ''}" for s in rows)
