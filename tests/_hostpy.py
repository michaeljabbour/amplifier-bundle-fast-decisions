"""Resolve the Amplifier host interpreter for tests in the "real-kernel"
lane (test_upstream_contract.py, test_shadow_real_kernel.py,
test_shadow_no_behaviour_change.py, test_lifecycle_events.py,
test_kernel_validation.py).

These tests exercise the ACTUAL installed ``amplifier_core`` /
``amplifier_module_loop_streaming`` packages, which live in the Amplifier
CLI's own venv, not this project's. They already skip cleanly (not fail)
via ``importlib.util.find_spec`` checks when those packages aren't
importable in whatever interpreter runs them -- this helper exists only to
locate that interpreter for a human (or CI) that wants to actually exercise
the real-kernel lane, without hardcoding any one person's home directory.

Resolution order:
1. ``AFAST_HOST_PYTHON`` env var, if set.
2. The venv ``python3`` sitting next to an ``amplifier`` executable found on
   PATH (``uv tool install`` lays out ``<venv>/bin/amplifier`` and
   ``<venv>/bin/python3`` side by side).
3. ``uv tool dir`` (if ``uv`` is on PATH) -> ``<tool dir>/amplifier/bin/python3``.

Never raises: returns ``(None, reason)`` when nothing is found.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def resolve_host_python() -> tuple[str | None, str]:
    """Return ``(interpreter_path_or_None, human_readable_reason)``."""
    env_path = os.getenv("AFAST_HOST_PYTHON")
    if env_path:
        if Path(env_path).exists():
            return env_path, f"AFAST_HOST_PYTHON={env_path}"
        return None, f"AFAST_HOST_PYTHON={env_path} does not exist"

    amplifier_cli = shutil.which("amplifier")
    if amplifier_cli:
        candidate = Path(amplifier_cli).resolve().parent / "python3"
        if candidate.exists():
            return str(candidate), f"resolved via `amplifier` on PATH: {candidate}"

    uv = shutil.which("uv")
    if uv:
        try:
            result = subprocess.run(
                [uv, "tool", "dir"], capture_output=True, text=True, timeout=5, check=True
            )
            tool_dir = result.stdout.strip()
        except Exception:  # noqa: BLE001 -- resolution must never raise
            tool_dir = None
        if tool_dir:
            candidate = Path(tool_dir) / "amplifier" / "bin" / "python3"
            if candidate.exists():
                return str(candidate), f"resolved via `uv tool dir`: {candidate}"

    return None, (
        "no Amplifier host interpreter found (set AFAST_HOST_PYTHON, or "
        "install Amplifier via `uv tool install amplifier`)"
    )


if __name__ == "__main__":
    path, reason = resolve_host_python()
    print(path or "(not found)")
    print(reason)
