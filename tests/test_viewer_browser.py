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
    def test_unified_dashboard_live_selection_collapse_and_legacy_links(self):
        with tempfile.TemporaryDirectory() as directory:
            server = ViewerServer(directory, 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            sequence = 0

            def emit(kind, data, decision='first'):
                nonlocal sequence
                sequence += 1
                event = dict(schema_version='1.0', event_id=str(sequence),
                             session_id='live-fixture', decision_id=decision,
                             event='fast_decisions:' + kind, seq=sequence,
                             timestamp=datetime.now(timezone.utc).isoformat(), data=data)
                with (Path(directory) / 'live.jsonl').open('a') as stream:
                    stream.write(json.dumps(event) + '\n')
                return event

            emit('health', {'phase': 'configuration', 'mode': 'active', 'backend': 'ollama'}, None)
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    ledger, circuit = context.new_page(), context.new_page()
                    errors = []
                    for page in (ledger, circuit):
                        page.on('pageerror', lambda error: errors.append(str(error)))
                    # An already-open loopback tab is ready without a separate
                    # browser credential or manual reconnect.
                    waiting = context.new_page()
                    waiting.goto(server.url.split('#')[0])
                    expect(waiting.locator('#reconnectPanel')).to_be_hidden()
                    ledger.goto(server.url)
                    circuit.goto(server.url.replace('/#', '/?view=circuit#'))
                    for page in (ledger, circuit):
                        expect(page.locator('#connection')).to_have_text('Connected')
                    expect(waiting.locator('#connection')).to_have_text('Connected')
                    waiting.close()
                    # A fresh tab has no sessionStorage token; the first launch
                    # establishes an HttpOnly cookie for subsequent root visits.
                    reopened = context.new_page()
                    reopened.goto(f'http://127.0.0.1:{server.server_port}/')
                    expect(reopened.locator('#connection')).to_have_text('Connected')
                    self.assertIsNone(reopened.evaluate('sessionStorage.getItem("afast-token:" + location.host)'))
                    self.assertNotIn('afast_viewer_', reopened.evaluate('document.cookie'))
                    # A stale per-tab bearer must not override a valid cookie.
                    reopened.goto(server.url.split('#')[0] + '#token=expired-fixture-token')
                    expect(reopened.locator('#connection')).to_have_text('Connected')
                    reopened.reload()
                    expect(reopened.locator('#connection')).to_have_text('Connected')
                    reopened.close()
                    # Both old entry points now show the same diagram and ledger.
                    for page in (ledger, circuit):
                        expect(page.locator('#decisionCircuit')).to_be_visible()
                        expect(page.locator('#liveFlows')).to_be_visible()
                        expect(page.locator('.view-switch')).to_have_count(0)

                    emit('requested', {'candidate_count': 2})
                    expect(circuit.locator('#circuitStateNote')).to_have_text('2 prepared candidates')
                    expect(ledger.locator('.flow-stage')).to_have_count(1)
                    score = emit('scored', {'choice': 'read', 'model': 'fixture-model', 'duration_ms': 20})
                    for page in (ledger, circuit):
                        expect(page.locator('#modelCount')).to_have_text('1')
                    expect(circuit.locator('#circuitMap')).to_have_attribute('data-branch', 'unknown')
                    expect(circuit.locator('#circuitMap')).to_have_class(__import__('re').compile(r'.*fresh-score.*'))
                    # Ledger inspection pins the diagram and inspector together.
                    ledger.locator('.session-row[data-session-id="live-fixture"]').click()
                    ledger.locator('#timeWindow').select_option('all')
                    inspect = ledger.locator('.flow-inspect[data-inspect-id="' + score['event_id'] + '"]')
                    inspect.focus()
                    inspect.press('Enter')
                    expect(inspect).to_be_focused()
                    expect(ledger.locator('#circuitJudge')).to_have_attribute('aria-pressed', 'true')
                    ledger.locator('#decisionCircuit > summary').click()
                    expect(ledger.locator('#circuitMap')).to_be_hidden()
                    expect(ledger.locator('#timeWindow')).to_have_value('all')
                    ledger.locator('#decisionCircuit > summary').click()
                    expect(ledger.locator('#circuitJudge')).to_have_attribute('aria-pressed', 'true')
                    expect(ledger.locator('#detailTitle')).to_have_text('Decision scored')
                    expect(ledger.locator('#viewTitle')).to_have_text('live-fix')

                    emit('routed', {'route': 'fast', 'status': 'submitted_to_upstream'})
                    for page in (ledger, circuit):
                        expect(page.locator('#bypassedCount')).to_have_text('1')
                        expect(page.locator('#fastExecuted')).to_have_text('0')
                    expect(circuit.locator('#circuitReceipt')).to_have_text('Fast · submitted')
                    emit('tool_end', {'status': 'ok', 'tool': 'read_file'})
                    for page in (ledger, circuit):
                        expect(page.locator('#fastExecuted')).to_have_text('1')
                    expect(circuit.locator('#circuitReceipt')).to_have_text('Fast · executed')
                    expect(circuit.locator('#circuitMap')).to_have_class(__import__('re').compile(r'.*fresh-fast.*'))
                    # Completed rows stay compact until inspected; selected rows
                    # retain their stages even as fresh events arrive.
                    expect(circuit.locator('.flow-stages')).to_be_hidden()
                    expect(ledger.locator('.selected-card .flow-stages')).to_be_visible()

                    ledger.locator('#followBtn').click()
                    emit('requested', {'candidate_count': 1}, 'second')
                    emit('scored', {'choice': 'reason', 'model': 'fixture-model'}, 'second')
                    emit('routed', {'route': 'slow', 'reason_code': 'ambiguous'}, 'second')
                    expect(circuit.locator('#modelCount')).to_have_text('2')
                    expect(circuit.locator('#circuitMap')).to_have_attribute('data-branch', 'slow')
                    ledger.locator('#decisionCircuit > summary').click()
                    expect(ledger.locator('#modelCount')).to_have_text('1')
                    expect(ledger.locator('#followBtn')).to_have_text('Resume live')
                    ledger.locator('#followBtn').click()
                    expect(ledger.locator('#modelCount')).to_have_text('2')
                    ledger.locator('#decisionCircuit > summary').click()
                    expect(ledger.locator('#circuitContext')).to_contain_text('Selected decision')
                    ledger.locator('#circuitLatest').click()
                    expect(ledger.locator('#circuitMap')).to_have_attribute('data-branch', 'slow')
                    # Refresh keeps authentication and live data.
                    ledger.reload()
                    expect(ledger.locator('#connection')).to_have_text('Connected')
                    expect(ledger.locator('#modelCount')).to_have_text('2')
                    ledger.locator('#decisionCircuit > summary').click()
                    circuit.emulate_media(reduced_motion='reduce')
                    self.assertEqual(circuit.locator('.slow-wire').evaluate('(el) => getComputedStyle(el).animationName'), 'none')
                    for width in (390, 1000, 1280, 1440, 1920):
                        ledger.set_viewport_size({'width': width, 'height': 1000})
                        self.assertTrue(ledger.evaluate('() => document.documentElement.scrollWidth <= innerWidth'))
                        self.assertTrue(ledger.locator('.activity-panel').evaluate('(el) => el.scrollWidth <= el.clientWidth'))
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()

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
            child_result = emit('child-one', 'tool_end', {'status': 'ok'}, parent='parent-one', decision='child')
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
                    expect(page.locator('#decisionCircuit')).to_be_visible()
                    # The latest child has only a tool result; it must not
                    # inherit its parent's routing evidence in the circuit.
                    page.locator('[data-decision-key="child-one:child"] .flow-inspect').click()
                    page.locator('.flow-stage[data-stage-id="' + child_result['event_id'] + '"]').click()
                    expect(page.locator('#circuitMap')).to_have_attribute('data-branch', 'unknown')
                    page.locator('[data-decision-key="parent-one:d1"] .flow-inspect').click()
                    page.locator('.flow-stage[data-stage-id="' + score['event_id'] + '"]').click()
                    expect(page.locator('#circuitMap')).to_have_attribute('data-branch', 'fast')
                    page.locator('#circuitJudge').click()
                    expect(page.locator('#detailTitle')).to_have_text('Decision scored')
                    expect(page.locator('#circuitContext')).to_contain_text('Selected decision')
                    page.locator('#circuitLatest').click()
                    expect(page.locator('#circuitContext')).to_contain_text('Latest decision')
                    page.locator('[data-children-id="parent-one"]').click()
                    expect(page.locator('.session-row')).to_have_count(3)
                    page.locator('.session-row[data-session-id="parent-one"]').click()
                    expect(page.locator('[data-decision-key="parent-one:d1"] .flow-stage')).to_have_count(4)
                    page.locator('[data-decision-key="parent-one:d1"] .flow-inspect').click()
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
                    expect(page.locator('#decisionCircuit')).to_be_visible()
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
                    page.locator('[data-filter="live"]').click()
                    expect(page.locator('#decisionCircuit')).to_be_visible()
                    # Loopback-only viewer: a fresh tab connects without a
                    # browser credential, including an Incognito-like context.
                    fresh = browser.new_page()
                    fresh.goto(server.url.split('#')[0])
                    expect(fresh.locator('#connection')).to_have_text('Connected')
                    expect(fresh.locator('#reconnectPanel')).to_be_hidden()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertTrue(page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'))
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
