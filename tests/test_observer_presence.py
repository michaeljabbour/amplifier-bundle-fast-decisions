"""Presence and retry observations must remain metadata-only and owned by mount."""
import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions import observer, provenance
from amplifier_fast_decisions.privacy import safe_data

@unittest.skipUnless(importlib.util.find_spec('amplifier_core'), 'Requires real Amplifier hook contract')
class PresenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_stops_at_cleanup_and_retry_excludes_error_body(self):
        coordinator=DemoCoordinator()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(observer,'_HEARTBEAT_INTERVAL_SECONDS',.01):
                cleanup=await observer.mount(coordinator,{'backend':'unavailable','events_dir':directory,'observatory':{'enabled':False}})
                try:
                    await coordinator.hooks.emit('provider:retry',{'provider':'test','attempt':2,'status_code':503,'error_type':'ConnectError','error_message':'PRIVATE_BODY','api_key':'PRIVATE_KEY'})
                    await asyncio.sleep(.035)
                finally:await cleanup()
                records=[data['data'] for name,data in coordinator.hooks.events if name=='fast_decisions:health']
                self.assertTrue(any(d.get('phase')=='session_heartbeat' for d in records))
                self.assertTrue(any(d.get('phase')=='session_closed' for d in records))
                retry=next(d for d in records if d.get('native_event')=='provider:retry')
                self.assertEqual(retry['retry_attempt'],2)
                self.assertEqual(retry['status_code'],503)
                self.assertNotIn('PRIVATE',str(records))
                count=len(coordinator.hooks.events)
                await asyncio.sleep(.025)
                self.assertEqual(len(coordinator.hooks.events),count)


@unittest.skipUnless(importlib.util.find_spec('amplifier_core'), 'Requires real Amplifier hook contract')
class SourceEventTests(unittest.IsolatedAsyncioTestCase):
    """HC00 (\"freeze source\"): mount must emit fast_decisions:source in every
    mode, including \"off\" -- a baseline profile still needs a receipt proving
    which source produced it."""

    async def _source_records(self, mode):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as directory:
            cleanup = await observer.mount(coordinator, {
                'mode': mode, 'backend': 'unavailable', 'events_dir': directory,
                'observatory': {'enabled': False},
            })
            try:
                pass
            finally:
                await cleanup()
        return [data['data'] for name, data in coordinator.hooks.events
                if name == 'fast_decisions:source']

    def _assert_valid_record(self, data):
        self.assertEqual(safe_data(data), data)
        expected_tree_sha = provenance.tree_sha256(Path('src/amplifier_fast_decisions'))
        self.assertEqual(data['source_tree_sha256'], expected_tree_sha)
        self.assertEqual(data['module'], 'hooks-fast-decisions')
        self.assertIn('source_kind', data)
        self.assertIn('python', data)

    async def test_emits_source_event_in_off_mode(self):
        records = await self._source_records('off')
        self.assertEqual(len(records), 1)
        self._assert_valid_record(records[0])
        self.assertEqual(records[0]['mode'], 'off')

    async def test_emits_source_event_in_shadow_mode(self):
        records = await self._source_records('shadow')
        self.assertEqual(len(records), 1)
        self._assert_valid_record(records[0])
        self.assertEqual(records[0]['mode'], 'shadow')


class WorkspaceNameTests(unittest.TestCase):
    """The viewer names sessions by directory basename; the hook must never record a path."""
    def test_basename_only_never_a_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = __import__('pathlib').Path(directory) / 'my-project'
            target.mkdir()
            previous = __import__('os').getcwd()
            __import__('os').chdir(target)
            try:
                name = observer.workspace_name({})
            finally:
                __import__('os').chdir(previous)
            self.assertEqual(name, 'my-project')
            self.assertNotIn('/', name)
            self.assertNotIn(directory, name)
    def test_config_override_and_allowlist(self):
        from amplifier_fast_decisions.privacy import safe_data
        self.assertEqual(observer.workspace_name({'workspace_name': ' Custom name '}), 'Custom name')
        self.assertEqual(observer.workspace_name({'workspace_name': ''}), observer.workspace_name({}))
        self.assertEqual(safe_data({'workspace_name': 'repo', 'cwd': '/Users/private/repo'}), {'workspace_name': 'repo'})


    def test_override_strips_windows_and_posix_parent_paths(self):
        for value in ('/Users/private/repo/', r'C:\Users\private\repo'):
            self.assertEqual(observer.workspace_name({'workspace_name': value}), 'repo')
