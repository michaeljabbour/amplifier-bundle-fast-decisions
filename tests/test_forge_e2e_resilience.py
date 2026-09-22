"""Tests for scripts/forge_e2e.py resilience fixes:

1. Run-directory names are slugged (percent-encoding-safe) so a cell/run id
   containing '+' never turns into a broken `file://` bundle URI.
2. A profile.md path that WOULD be percent-encoded is rejected loudly before
   ever invoking amplifier (defensive canary; should never fire in normal
   operation once (1) holds, but must fire immediately if it ever would).
3. Forge-launch resilience: a minimum spacing between launches, and
   exponential backoff with jitter (bounded retries) specifically for
   Forge-unreachable/empty-response errors -- verified with a fake clock,
   never real time.sleep.

Stdlib unittest only. Never invokes a real Forge daemon or amplifier.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import forge_e2e  # noqa: E402
import battery  # noqa: E402 -- only to cross-check the two modules' _slug agree


class SlugTests(unittest.TestCase):
    def test_slug_matches_battery_slug(self):
        """forge_e2e._slug is deliberately duplicated (not imported) from
        battery._slug -- battery.py imports forge_e2e, so the reverse import
        would be circular -- but the two must always agree on what's safe."""
        samples = ['judge-jev+effort-incumbent-s1-dev-r1-amplifier-fd-a2',
                   'plain-s1-dev-r1', 'a b/c:d+e', '']
        for s in samples:
            self.assertEqual(forge_e2e._slug(s), battery._slug(s))

    def test_slug_removes_plus_and_other_unsafe_chars(self):
        self.assertEqual(forge_e2e._slug('judge-jev+effort-incumbent'), 'judge-jev-effort-incumbent')
        self.assertNotIn('+', forge_e2e._slug('a+b+c'))


class BundleUriSafetyTests(unittest.TestCase):
    def test_safe_path_passes(self):
        forge_e2e._assert_bundle_uri_safe(Path('/tmp/campaign/runs/judge-jev-effort-a1/profile.md'))  # must not raise

    def test_unsafe_path_raises_before_launch(self):
        """A '+' (or any character outside the safe set) in a profile.md path
        would be percent-encoded by Path.as_uri() into a URI Amplifier's
        bundle loader cannot resolve back to the real file. This must fail
        loudly, with a clear message, BEFORE any amplifier invocation --
        never silently proceed to a broken launch."""
        unsafe = Path('/tmp/campaign/runs/judge-jev+effort-a1/profile.md')
        with self.assertRaises(SystemExit) as ctx:
            forge_e2e._assert_bundle_uri_safe(unsafe)
        self.assertIn('not bundle-URI-safe', str(ctx.exception))

    def test_build_run_produces_a_bundle_uri_safe_profile_path_for_a_plus_bearing_name(self):
        """End-to-end: _build_run's on-disk profile.md path for a '+'-bearing
        run name must already pass _assert_bundle_uri_safe (the slugged
        directory is the actual fix; this check is the canary)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_spec = {'name': 'judge-jev+effort-incumbent-s1-dev-r1-amplifier-fd-a1', 'task': 'scheduler',
                        'side': 'candidate', 'rep': 1, 'attempt': 1, 'block': None, 'seed': 1}
            sides = {'candidate': {'mode': 'active', 'source_root': str(root), 'decision_overrides': {}}}
            config = {'events_dir': str(root/'events'), 'upstream_loop_source': forge_e2e.UPSTREAM_LOOP_SOURCE,
                      'limits': {'timeout_seconds': 60, 'max_iterations': 5, 'extended_thinking': False},
                      'amplifier_bundle': 'foundation'}
            forge_e2e._build_run(root, run_spec, config, sides)
            run_dir = root/forge_e2e._slug(run_spec['name'])
            self.assertTrue((run_dir/'profile.md').exists())
            forge_e2e._assert_bundle_uri_safe(run_dir/'profile.md')  # must not raise
            self.assertNotIn('+', str(run_dir))


class LaunchSpacingTests(unittest.TestCase):
    def test_second_launch_within_window_sleeps_the_remainder(self):
        clock = {'t': 100.0}
        sleeps = []

        def now_fn():
            return clock['t']

        def sleep_fn(seconds):
            sleeps.append(seconds)
            clock['t'] += seconds

        forge_e2e._last_launch_at[0] = clock['t']  # simulate a launch that just happened
        clock['t'] += 0.5  # only 0.5s elapsed since that launch
        forge_e2e._wait_for_launch_spacing(sleep_fn, now_fn)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], forge_e2e.MIN_LAUNCH_SPACING_SECONDS - 0.5, places=6)

    def test_launch_after_window_elapsed_does_not_sleep(self):
        clock = {'t': 200.0}

        def now_fn():
            return clock['t']

        def sleep_fn(seconds):
            raise AssertionError(f'should not sleep, requested {seconds}s')

        forge_e2e._last_launch_at[0] = clock['t'] - forge_e2e.MIN_LAUNCH_SPACING_SECONDS - 1.0
        forge_e2e._wait_for_launch_spacing(sleep_fn, now_fn)  # must not raise -- no sleep needed


def _manifest_root(tmp, name='r1'):
    root = Path(tmp)
    (root/name/'workspace').mkdir(parents=True)
    root_manifest = {'run_order': [name], 'runs': {name: {'task': 't', 'side': 'candidate'}},
                      'sides': {'candidate': {'source_root': str(root)}},
                      'limits': {'timeout_seconds': 60}, 'events_dir': str(root/'events'),
                      'host_python': 'python3', 'forge_py': str(root/'forge.py')}
    (root/'manifest.json').write_text(json.dumps(root_manifest))
    return root


class LaunchRunBackoffTests(unittest.TestCase):
    """Every test here pins MIN_LAUNCH_SPACING_SECONDS to 0 for its duration,
    isolating the backoff-specific sleeps from the (separately tested, see
    LaunchSpacingTests) launch-spacing wait that also runs on every attempt."""

    def _fake_clock(self):
        clock = {'t': 0.0}
        # _last_launch_at is process-global (shared across threads/tests by design);
        # pin it to this test's own clock epoch so a previous test's leftover value
        # can never leak in as a spurious spacing wait here.
        forge_e2e._last_launch_at[0] = 0.0

        def now_fn():
            return clock['t']

        def sleep_fn(seconds):
            clock['t'] += seconds
        return sleep_fn, now_fn

    def test_forge_unreachable_retries_with_backoff_then_succeeds(self):
        """Defect: 18 runs failed with 'cannot reach http://127.0.0.1:3141/mcp'
        and 4 with 'empty response' -- a bursty scheduler hammered a Forge
        daemon that was unreachable/restarting. launch_run must retry those
        SPECIFIC errors with exponential backoff + jitter, bounded, and
        eventually succeed once Forge comes back -- never raising for a
        transient outage within the retry budget."""
        with tempfile.TemporaryDirectory() as tmp, \
             unittest.mock.patch.object(forge_e2e, 'MIN_LAUNCH_SPACING_SECONDS', 0.0):
            root = _manifest_root(tmp)
            calls = {'n': 0}
            sleeps = []
            base_sleep_fn, now_fn = self._fake_clock()

            def sleep_fn(seconds):
                sleeps.append(seconds)
                base_sleep_fn(seconds)

            def call(tool, args):
                calls['n'] += 1
                if calls['n'] <= 2:
                    raise SystemExit('forge: cannot reach http://127.0.0.1:3141/mcp')
                return {'exitCode': 0, 'output': ''}
            forge_module = SimpleNamespace(call=call)

            result = forge_e2e.launch_run(root, 'r1', forge_module=forge_module,
                                           sleep_fn=sleep_fn, now_fn=now_fn)
            self.assertEqual(result['exitCode'], 0)
            self.assertEqual(calls['n'], 3)  # 2 unreachable + 1 success
            # Exactly one backoff sleep per unreachable failure (spacing is pinned to 0 above).
            self.assertEqual(len(sleeps), 2)
            # First backoff: [0.5, 1.0). Second (doubled): [1.0, 2.0). Deterministic
            # bounds regardless of the random jitter component.
            self.assertGreaterEqual(sleeps[0], forge_e2e.BACKOFF_INITIAL_SECONDS)
            self.assertLess(sleeps[0], forge_e2e.BACKOFF_INITIAL_SECONDS * 2)
            self.assertGreaterEqual(sleeps[1], forge_e2e.BACKOFF_INITIAL_SECONDS * 2)
            self.assertLess(sleeps[1], forge_e2e.BACKOFF_INITIAL_SECONDS * 4)
            # Never sleeps longer than the cap plus its own jitter budget.
            for s in sleeps:
                self.assertLessEqual(s, forge_e2e.BACKOFF_CAP_SECONDS * 2)

    def test_persistent_unreachable_error_gives_up_after_retry_budget(self):
        """Once max_unreachable_retries is exhausted, launch_run must still
        fail loud (RuntimeError) rather than retry forever."""
        with tempfile.TemporaryDirectory() as tmp, \
             unittest.mock.patch.object(forge_e2e, 'MIN_LAUNCH_SPACING_SECONDS', 0.0):
            root = _manifest_root(tmp)
            sleeps = []
            base_sleep_fn, now_fn = self._fake_clock()

            def sleep_fn(seconds):
                sleeps.append(seconds)
                base_sleep_fn(seconds)

            def call(tool, args):
                raise SystemExit('forge: empty response')
            forge_module = SimpleNamespace(call=call)

            with self.assertRaises(RuntimeError) as ctx:
                forge_e2e.launch_run(root, 'r1', forge_module=forge_module,
                                      sleep_fn=sleep_fn, now_fn=now_fn,
                                      max_unreachable_retries=3)
            self.assertIn('forge launch failed', str(ctx.exception))
            # Retried exactly the configured budget, not indefinitely.
            self.assertEqual(len(sleeps), 3)

    def test_non_unreachable_error_is_not_retried_with_backoff(self):
        """A launch failure that is NOT a Forge-unreachable error (e.g. a
        plain configuration error) must fail immediately -- backoff is
        specific to the unreachable/empty-response class of failure."""
        with tempfile.TemporaryDirectory() as tmp, \
             unittest.mock.patch.object(forge_e2e, 'MIN_LAUNCH_SPACING_SECONDS', 0.0):
            root = _manifest_root(tmp)
            sleeps = []
            base_sleep_fn, now_fn = self._fake_clock()

            def sleep_fn(seconds):
                sleeps.append(seconds)
                base_sleep_fn(seconds)

            def call(tool, args):
                raise SystemExit('forge: some unrelated configuration error')
            forge_module = SimpleNamespace(call=call)

            with self.assertRaises(RuntimeError):
                forge_e2e.launch_run(root, 'r1', forge_module=forge_module,
                                      sleep_fn=sleep_fn, now_fn=now_fn)
            # No backoff (or spacing, pinned to 0 above) sleeps at all.
            self.assertEqual(sleeps, [])


if __name__ == '__main__':
    unittest.main()
