"""Optional browser integration checks: pip install playwright; playwright install chromium.

All records here are test fixtures in a temporary directory, never live user telemetry.
"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from datetime import datetime, timezone

from amplifier_fast_decisions.server import ViewerServer

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, 'Optional Playwright package is not installed')
class ViewerBrowserTests(unittest.TestCase):
    def test_parent_scope_live_tail_mechanics_pause_reconnect_and_import(self):
        with tempfile.TemporaryDirectory() as directory:
            server = ViewerServer(directory, 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            sequence = 0

            def emit(session, kind='health', data=None, parent=None, decision=None):
                nonlocal sequence
                sequence += 1
                event = dict(schema_version='1.0', event_id=str(sequence),
                             session_id=session, parent_session_id=parent,
                             event='fast_decisions:' + kind, decision_id=decision,
                             timestamp=datetime.now(timezone.utc).isoformat(),
                             seq=sequence, data=data or {})
                with (Path(directory) / (session + '.jsonl')).open('a') as stream:
                    stream.write(json.dumps(event) + '\n')
                return event

            emit('parent-one', data={'phase': 'configuration', 'mode': 'active', 'backend': 'ollama'})
            emit('parent-two', data={'phase': 'configuration'})
            emit('child-one', data={'phase': 'configuration'}, parent='parent-one')
            emit('parent-one', 'requested', {'candidate_count': 2}, decision='d1')
            score = emit('parent-one', 'scored', {'model': 'fixture-model', 'duration_ms': 25}, decision='d1')
            emit('parent-one', 'routed', {'route': 'fast', 'status': 'submitted_to_upstream'}, decision='d1')
            emit('parent-one', 'tool_end', {'status': 'ok'}, decision='d1')
            emit('child-one', 'tool_end', {'status': 'ok'}, parent='parent-one', decision='child')
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(server.url)
                    expect(page.locator('#connection')).to_have_text('Connected')
                    expect(page.locator('#sessionCount')).to_have_text('2')
                    expect(page.locator('.session-row')).to_have_count(2)
                    expect(page.locator('#toolCount')).to_have_text('2')
                    expect(page.locator('#includeChildren')).to_be_checked()
                    expect(page.locator('#liveFlows')).to_be_visible()
                    expect(page.locator('#bypassedCount')).to_have_text('1')
                    page.locator('[data-children-id="parent-one"]').click()
                    expect(page.locator('.session-row')).to_have_count(3)
                    page.locator('.session-row[data-session-id="parent-one"]').click()
                    expect(page.locator('[data-decision-key="parent-one:d1"] .flow-stage')).to_have_count(4)
                    page.locator('.flow-stage[data-stage-id="' + score['event_id'] + '"]').click()
                    expect(page.locator('#detailTitle')).to_have_text('Decision scored')
                    page.locator('#includeChildren').uncheck()
                    expect(page.locator('#toolCount')).to_have_text('1')
                    page.locator('#includeChildren').check()
                    expect(page.locator('#toolCount')).to_have_text('2')
                    # Child execution cannot appear in its parent's decision path.
                    expect(page.locator('[data-decision-key="parent-one:d1"] .flow-stage')).to_have_count(4)
                    page.locator('#allSessions').click()
                    page.locator('#includeChildren').uncheck()
                    emit('parent-two', data={'native_event': 'tool:pre', 'tool_call_id': 'native-one', 'tool': 'read_file'})
                    emit('parent-two', data={'native_event': 'tool:post', 'tool_call_id': 'native-one', 'tool': 'read_file'})
                    expect(page.locator('[data-decision-key="parent-two:native:native-one"] .flow-stage')).to_have_count(2)
                    expect(page.locator('#bypassedCount')).to_have_text('1')
                    arrived = emit('parent-two', 'requested', {'candidate_count': 3}, decision='live-new')
                    expect(page.locator('.flow-stage[data-stage-id="' + arrived['event_id'] + '"]')).to_be_visible()
                    expect(page.locator('.flow-stage[data-stage-id="' + arrived['event_id'] + '"]')).to_have_class(__import__('re').compile(r'.*arriving.*'))
                    emit('parent-two', data={'native_event': 'provider:retry', 'retry_attempt': 2})
                    expect(page.locator('#errorCount')).to_have_text('1')
                    page.locator('[data-filter="activity"]').click()
                    retry = page.locator('.event-row').filter(has_text='Provider retry')
                    retry.click()
                    expect(retry).to_be_focused()
                    page.wait_for_timeout(650)  # One poll must not steal keyboard focus.
                    expect(retry).to_be_focused()
                    page.locator('#followBtn').click()
                    emit('parent-two', data={'native_event': 'provider:error'})
                    page.wait_for_timeout(650)
                    expect(page.locator('#errorCount')).to_have_text('1')
                    page.locator('#followBtn').click()
                    expect(page.locator('#errorCount')).to_have_text('2')
                    fixture = json.dumps(score).encode()
                    page.locator('#fileInput').set_input_files({'name': 'fixture.jsonl', 'mimeType': 'application/x-ndjson', 'buffer': fixture})
                    expect(page.locator('#connection')).to_have_text('Saved trace')
                    expect(page.locator('#modelCount')).to_have_text('1')
                    page.locator('#followBtn').click()
                    expect(page.locator('#connection')).to_have_text('Connected')
                    expect(page.locator('#sessionCount')).to_have_text('2')
                    # A fresh tab with no bearer token has a recoverable connection state.
                    fresh = browser.new_page()
                    fresh.goto(server.url.split('#')[0])
                    expect(fresh.locator('#reconnectPanel')).to_be_visible()
                    fresh.locator('#viewerLink').fill(server.url)
                    fresh.locator('#connectForm button').click()
                    expect(fresh.locator('#connection')).to_have_text('Connected')
                    expect(fresh.locator('#viewerLink')).to_have_value('')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertTrue(page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'))
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
