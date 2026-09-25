"""bench_compare_host.run() launches the real `amplifier run` CLI (paired
baseline/enabled comparison runs), which inherits os.environ. This pins
that AMPLIFIER_MEMORY_CAPTURE=off is set on that subprocess's env, the same
way AFAST_OBSERVATORY=off already is.

bench_compare_host.run() itself requires a live provider/ollama endpoint to
execute end-to-end (explicit live-comparison tooling, not CI-safe), so this
is a structural check on the env-construction source rather than a full
subprocess-capturing integration test -- mirrors the existing structural-
guard pattern used elsewhere in this repo (e.g. hooks-memory-interject's
test_privacy_defaults.py).
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import bench_compare_host  # noqa: E402


class RunEnvTests(unittest.TestCase):
    def test_run_sets_amplifier_memory_capture_off_before_launching(self) -> None:
        source = inspect.getsource(bench_compare_host.run)
        # Must be set on `env` (the dict passed to subprocess.run) BEFORE the
        # env dict is used, mirroring AFAST_OBSERVATORY's existing placement.
        assert "env['AMPLIFIER_MEMORY_CAPTURE'] = 'off'" in source
        capture_idx = source.index("env['AMPLIFIER_MEMORY_CAPTURE'] = 'off'")
        popen_idx = source.index("subprocess.run(command")
        assert capture_idx < popen_idx, (
            "AMPLIFIER_MEMORY_CAPTURE must be set on env before the amplifier "
            "subprocess is launched"
        )


if __name__ == "__main__":
    unittest.main()
