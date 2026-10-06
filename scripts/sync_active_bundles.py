#!/usr/bin/env python3
"""Regenerate the orchestrator config of bundles/active*.yaml from behaviors/fast-decisions.yaml.

The behavior is the only hand-edited copy of the shipped defaults. ``tests/test_config_parity.py`` fails when
the bundles drift from it; run this script to fix them:

    python3 scripts/sync_active_bundles.py          # rewrite the config blocks in place
    python3 scripts/sync_active_bundles.py --check  # exit 1 if a bundle is out of sync (no writes)

Only the ``config:`` mapping under ``session.orchestrator`` is replaced; every other line is kept.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"bundles/active.yaml": {"upstream": {"max_iterations": 100, "extended_thinking": True}},
           "bundles/active-routing.yaml": {},
           # The local-judge rung: the shipped config with an Apple MLX judge and no external state.
           "bundles/active-mlx.yaml": {"backend": "mlx", "model": "mlx-community/Qwen3-0.6B-4bit",
                                       "mlx_url": "http://127.0.0.1:8080", "allow_external_state": False,
                                       # The shipped decider is the rule R*; this rung is the one that asks a (local) judge.
                                       "model_routing": {"start_policy": "judge"}}}


def render(extra: dict) -> str:
    cfg = yaml.safe_load((ROOT / "behaviors/fast-decisions.yaml").read_text(encoding="utf-8"))["session"]["orchestrator"]["config"]
    extra = dict(extra)
    routing = {**cfg["model_routing"], **extra.pop("model_routing", {})}
    cfg = {**cfg, **extra, "model_routing": routing}
    lines = yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False, width=100).splitlines()
    return "    config:\n" + "\n".join("      " + line for line in lines) + "\n"


def sync(path: str, extra: dict) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    head, sep, _ = text.partition("    config:\n")
    if not sep:
        raise SystemExit(f"{path}: no 'config:' block under session.orchestrator")
    return head + render(extra)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for path, extra in TARGETS.items():
        new = sync(path, extra)
        if new != (ROOT / path).read_text(encoding="utf-8"):
            stale.append(path)
            if not check:
                (ROOT / path).write_text(new, encoding="utf-8")
    if stale:
        print(("out of sync: " if check else "rewrote: ") + ", ".join(stale))
    return 1 if (check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
