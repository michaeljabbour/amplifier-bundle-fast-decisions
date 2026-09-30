"""Transparency contract for RoutedProvider and ObservedTool (facade.py).

Each case is a pattern a real host applies to registry objects. The last class
runs the INSTALLED hooks-session-naming when present:

    $(python3 tests/_hostpy.py | head -1) -m unittest tests.test_facade_contract -v
"""
from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider
from amplifier_fast_decisions.orchestrator import ObservedTool, RoutedProvider
from amplifier_fast_decisions.runtime import get_runtime

HAS_NAMING = importlib.util.find_spec("amplifier_module_hooks_session_naming") is not None


class StatefulTool:
    """Like dot-runner's ReportOutcomeTool: per-branch instance state."""
    name = "report_outcome"

    def __init__(self):
        self.last_outcome = None

    async def execute(self, input, **kwargs):
        self.last_outcome = input
        return NS(success=True, output="ok", error=None)


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        coordinator = DemoCoordinator()
        self.runtime, _ = get_runtime(coordinator, {"backend": "unavailable", "events_dir": self._tmp.name})
        self.provider = DemoProvider(delay_ms=0)
        self.provider.coordinator = coordinator
        self.facade = RoutedProvider(self.provider, self.runtime, {})
        self.facade._registry_gate = True
        self.tool = StatefulTool()
        self.observed = ObservedTool(self.tool, self.runtime, "report_outcome")

    def tearDown(self):
        self.runtime.recorder.close()
        self._tmp.cleanup()


class CopyTests(Fixture):
    def test_copy_wraps_a_copy_of_the_provider(self):
        clone = copy.copy(self.facade)
        self.assertIsInstance(clone, RoutedProvider)
        self.assertIsNot(clone._provider, self.provider)
        self.assertTrue(clone._registry_gate)

    def test_naming_stamp_reaches_the_copy_only(self):
        # hooks-session-naming: stamped = copy.copy(provider); stamped.coordinator = view
        stamped = copy.copy(self.facade)
        view = object()
        stamped.coordinator = view
        self.assertIs(stamped.coordinator, view)
        self.assertIs(stamped._provider.coordinator, view)
        self.assertIsNot(self.provider.coordinator, view)

    def test_deepcopy(self):
        plain = RoutedProvider(DemoProvider(delay_ms=0), self.runtime, {})
        clone = copy.deepcopy(plain)
        self.assertIsInstance(clone, RoutedProvider)
        self.assertIsNot(clone._provider, plain._provider)
        self.assertIs(clone._runtime, self.runtime)

    def test_deepcopy_fails_exactly_when_the_raw_provider_would(self):
        # This provider holds a live coordinator (locks); the raw object
        # cannot be deep-copied either. The facade adds no failure of its own.
        with self.assertRaises(TypeError) as raw:
            copy.deepcopy(self.provider)
        with self.assertRaises(TypeError) as wrapped:
            copy.deepcopy(self.facade)
        self.assertEqual(str(raw.exception), str(wrapped.exception))

    def test_tool_copy_and_deepcopy(self):
        for clone in (copy.copy(self.observed), copy.deepcopy(self.observed)):
            self.assertIsInstance(clone, ObservedTool)
            self.assertIsNot(clone._tool, self.tool)


class AttributeTests(Fixture):
    def test_missing_private_name_never_recurses(self):
        half_built = object.__new__(RoutedProvider)
        with self.assertRaises(AttributeError):
            half_built._provider
        with self.assertRaises(AttributeError):
            self.facade._no_such_attribute

    def test_public_value_reaches_the_provider(self):
        # e.g. a host switching the model mid-session
        self.facade.default_model = "switched"
        self.assertEqual(self.provider.default_model, "switched")

    def test_method_patch_stays_on_the_facade_without_recursion(self):
        # hook-computer-use and Unified's telemetry: capture, then replace complete().
        original = self.facade.complete
        calls = []

        async def patched(request, **kwargs):
            calls.append(request)
            return await original(request, **kwargs)

        self.facade.complete = patched
        self.assertNotIn("complete", vars(self.provider))
        import asyncio
        request = NS(messages=[], tools=None, tool_choice="auto", model=None)
        asyncio.run(self.facade.complete(request))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_private_markers_stay_on_the_facade(self):
        self.facade._amplifier_web_observed = True
        self.assertNotIn("_amplifier_web_observed", vars(self.provider))
        self.assertTrue(self.facade._amplifier_web_observed)

    def test_stream_absence_is_mirrored(self):
        self.assertFalse(hasattr(self.facade, "stream"))


class InspectionTests(Fixture):
    def test_vars_shows_the_wrapped_state(self):
        self.assertIn("last_outcome", vars(self.observed))
        self.assertIn("last_outcome", getattr(self.observed, "__dict__", {}))

    def test_loop_pipeline_clones_a_stateful_tool_per_branch(self):
        # amplifier_module_loop_pipeline.backend._clone_tool, verbatim logic.
        tool = self.observed
        is_stateful = ("last_outcome" in getattr(tool, "__dict__", {})
                       or any("last_outcome" in vars(cls) for cls in type(tool).__mro__))
        self.assertTrue(is_stateful)
        branch = copy.copy(tool)
        branch.last_outcome = None
        self.tool.last_outcome = "main"
        self.assertIsNone(branch._tool.last_outcome)


@unittest.skipUnless(HAS_NAMING, "amplifier_module_hooks_session_naming not installed (real-kernel lane only)")
class RealNamingTests(Fixture):
    def test_installed_naming_hook_stamps_a_routed_provider(self):
        import amplifier_module_hooks_session_naming as naming
        coordinator = self.provider.coordinator
        hook = naming.SessionNamingHook(coordinator, naming.SessionNamingConfig())
        stamped = hook._stamped_provider(self.facade)
        self.assertIsNotNone(stamped, "naming would skip the call and keep the fallback title")
        self.assertIsInstance(stamped._provider.coordinator, naming._NamingCoordinator)
        self.assertIs(self.provider.coordinator, coordinator)


if __name__ == "__main__":
    unittest.main()


class StalePackageTests(unittest.TestCase):
    """The failure that hid registry mode in the CLI: an older installed
    amplifier-fast-decisions without registry.py, same version string."""

    def _fake_env(self, root, with_registry):
        import os, stat, sys
        package = os.path.join(root, "site", "amplifier_fast_decisions")
        os.makedirs(package)
        open(os.path.join(package, "__init__.py"), "w").close()
        if with_registry:
            with open(os.path.join(package, "registry.py"), "w") as f:
                f.write("def mount(*a, **k):\n    return None\n")
        python = os.path.join(root, "python")
        with open(python, "w") as f:
            f.write(f"#!/bin/sh\nPYTHONPATH={root}/site exec {sys.executable} \"$@\"\n")
        os.chmod(python, os.stat(python).st_mode | stat.S_IEXEC)
        return python

    def test_doctor_flags_a_stale_host_environment(self):
        import os
        from unittest import mock
        from amplifier_fast_decisions import cli
        with tempfile.TemporaryDirectory() as root:
            stale = self._fake_env(os.path.join(root, "stale"), with_registry=False)
            current = self._fake_env(os.path.join(root, "current"), with_registry=True)
            settings = os.path.join(root, "settings.yaml")
            with open(settings, "w") as f:
                f.write("bundle:\n  app:\n  - x#subdirectory=behaviors/fast-decisions-registry.yaml\n")
            with mock.patch.object(cli, "_HOST_PYTHONS", (("stale", stale), ("current", current))):
                checks = {c["check"]: c for c in cli._host_environment_checks(Path(settings))}
        self.assertFalse(checks["registry_mode_package[stale]"]["ok"])
        self.assertIn("--reinstall-package", checks["registry_mode_package[stale]"]["note"])
        self.assertTrue(checks["registry_mode_package[current]"]["ok"])

    def test_doctor_probe_ignores_this_process_pythonpath(self):
        import os, sys
        from unittest import mock
        from amplifier_fast_decisions import cli
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        with tempfile.TemporaryDirectory() as root:
            settings = os.path.join(root, "settings.yaml")
            with open(settings, "w") as f:
                f.write("x fast-decisions-registry\n")
            bare = os.path.join(root, "bare")
            os.makedirs(bare)
            python = os.path.join(bare, "python")
            with open(python, "w") as f:
                f.write(f"#!/bin/sh\nexec {sys.executable} -S \"$@\"\n")
            os.chmod(python, 0o755)
            with mock.patch.dict(os.environ, {"PYTHONPATH": src}), \
                    mock.patch.object(cli, "_HOST_PYTHONS", (("bare", python),)):
                [check] = cli._host_environment_checks(Path(settings))
        self.assertEqual(check["value"], "absent")

    def test_doctor_skips_hosts_when_registry_mode_is_not_configured(self):
        from amplifier_fast_decisions import cli
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as f:
            f.write("bundle:\n  app: []\n")
            f.flush()
            self.assertEqual(cli._host_environment_checks(Path(f.name)), [])

    def test_router_entrypoint_names_the_repair_when_the_package_is_stale(self):
        import os, subprocess
        shim = os.path.join(os.path.dirname(__file__), "..", "modules", "hooks-fast-decisions-router")
        with tempfile.TemporaryDirectory() as root:
            python = self._fake_env(root, with_registry=False)
            result = subprocess.run(
                [python, "-c", f"import sys; sys.path.insert(0, {shim!r}); "
                               "import amplifier_module_hooks_fast_decisions_router"],
                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("predates registry mode", result.stderr)
        self.assertIn("--reinstall-package amplifier-fast-decisions", result.stderr)
