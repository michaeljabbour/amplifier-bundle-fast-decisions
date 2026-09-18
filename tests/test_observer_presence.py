"""Presence and retry observations must remain metadata-only and owned by mount."""
import asyncio
import importlib.util
import tempfile
import unittest
from unittest.mock import patch
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions import observer

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
