"""Data-only operational evidence, diagnostics and matched-run comparisons.

No host imports and no inference. Diagnostics may probe explicit loopback health
endpoints; measurement and comparison only read caller-selected receipts.
"""
from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
from importlib import metadata
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
import urllib.request

from .bench.replay import _unwrap_kernel_envelope
from .contracts import EVENT_NAMES
from .local_backend import local_url
from .privacy import safe_data

DEFAULT_EVENTS = Path.home() / '.amplifier' / 'fast-decisions' / 'events'
DEFAULT_STATE = Path.home() / '.amplifier' / 'fast-decisions' / 'serve.json'


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _time(event):
    try:
        value = datetime.fromisoformat(event.get('timestamp', '').replace('Z', '+00:00'))
        return value.timestamp() if value.tzinfo else 0.0
    except (ValueError, TypeError, AttributeError):
        return 0.0


def read_receipts(path: str | Path, *, capacity: int = 100000) -> tuple[list[dict], dict]:
    """Read bounded JSONL records without creating directories or following links."""
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError('Receipt source must not be a symlink')
    if not path.exists():
        return [], {'source_exists': False, 'invalid_records': 0, 'truncated': False}
    files = sorted(path.glob('*.jsonl')) if path.is_dir() else [path]
    records = deque(maxlen=capacity)
    invalid, count = 0, 0
    for file in files:
        if file.is_symlink() or not file.is_file():
            continue
        with file.open('rb') as stream:
            while line := stream.readline(65537):
                if len(line) > 65536:
                    invalid += 1
                    while line and not line.endswith(b'\n'):
                        line = stream.readline(65537)
                    continue
                if not line.endswith(b'\n'):
                    # A currently writing producer may finish this line later.
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                    event = _unwrap_kernel_envelope(event)
                    if (not isinstance(event.get('event'), str) or event.get('event') not in EVENT_NAMES or not isinstance(event.get('data'), dict)
                        or not isinstance(event.get('session_id'), str) or not isinstance(event.get('event_id'), str)):
                        raise ValueError()
                    if any(event.get(key) is not None and not isinstance(event[key], str) for key in ('parent_session_id', 'turn_id', 'decision_id')):
                        raise ValueError()
                    event = {key: event.get(key) for key in ('event', 'event_id', 'session_id', 'parent_session_id', 'turn_id', 'decision_id', 'timestamp', 'seq', 'synthetic', 'data')}
                    event['data'] = safe_data(event['data'])
                    if any(event['data'].get(key) is not None and not isinstance(event['data'][key], str) for key in ('provider_call_id', 'tool_call_id', 'native_event', 'reason_code', 'backend', 'model', 'mode', 'phase', 'status')):
                        raise ValueError()
                    records.append(event)
                    count += 1
                except (ValueError, TypeError, UnicodeError):
                    invalid += 1
    return list(records), {'source_exists': True, 'invalid_records': invalid, 'truncated': count > capacity}


def summarize(events: list[dict], *, session_id: str | None = None, now: float | None = None) -> dict:
    """Aggregate each receipt once, including descendants by default.

    Native hooks and instrumented executions are separate counters. No cost or
    eliminated-tool-call figure is inferred from a proposal or model score.
    """
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    dedup = {(e['session_id'], e['event_id']): e for e in events}
    events = sorted(dedup.values(), key=lambda e: (_time(e), e.get('seq') if isinstance(e.get('seq'), int) else 0))
    parents = {}
    synthetic_decisions = set()
    for e in events:
        parent = e.get('parent_session_id')
        if isinstance(parent, str) and parent and parent != e['session_id']:
            parents[e['session_id']] = parent
        d = e['data']
        if e.get('decision_id') and (e.get('synthetic') or d.get('synthetic') or str(d.get('backend', '')).startswith('scripted') or str(d.get('model', '')).startswith('scripted')):
            synthetic_decisions.add((e['session_id'], e['decision_id']))
    def descends(sid, ancestor):
        seen = set()
        while sid not in seen:
            if sid == ancestor:
                return True
            seen.add(sid)
            sid = parents.get(sid)
            if sid is None:
                break
        return False
    selected = [e for e in events if session_id is None or descends(e['session_id'], session_id)]
    def genuine(e):
        return not (e.get('synthetic') or e['data'].get('synthetic') or
                    (e.get('decision_id') and (e['session_id'], e['decision_id']) in synthetic_decisions and e['event'] != 'fast_decisions:health'))
    selected = [e for e in selected if genuine(e)]
    def counts(rows):
        kind = lambda e: e['event'].removeprefix('fast_decisions:')
        starts, ends, tools, tool_ends, bypass, scores = {}, {}, {}, {}, set(), {}
        native = Counter()
        fallback = set()
        for e in rows:
            d, k, sid = e['data'], kind(e), e['session_id']
            if k == 'health' and d.get('native_event'):
                native[d['native_event']] += 1
            if k == 'slow_start':
                starts[(sid, d.get('provider_call_id') or e['event_id'])] = e
            if k == 'slow_end':
                ends[(sid, d.get('provider_call_id') or e['event_id'])] = e
            if k == 'tool_start':
                tools[(sid, d.get('tool_call_id') or e['event_id'])] = e
            if k == 'tool_end':
                tool_ends[(sid, d.get('tool_call_id') or e['event_id'])] = e
            if k == 'routed' and d.get('route') == 'fast' and d.get('status') == 'submitted_to_upstream':
                bypass.add((sid, e.get('decision_id') or e['event_id']))
            if k in {'scored', 'shadow_proposed'}:
                scores[(sid, e.get('decision_id') or e['event_id'])] = e
            if k == 'fallback' or k == 'routed' and d.get('route') == 'slow':
                fallback.add((sid, e.get('decision_id') or e['event_id'], d.get('reason_code') or 'unknown'))
        successful = [e for e in ends.values() if e['data'].get('status') == 'ok']
        usage = {}
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            known = [e['data'][key] for e in successful if _number(e['data'].get(key))]
            usage[key] = sum(known) if len(known) == len(ends) == len(starts) and starts and set(starts) == set(ends) else None
            usage[key + '_known_calls'] = len(known)
        latencies = [e['data']['duration_ms'] for e in scores.values() if _number(e['data'].get('duration_ms'))]
        turn_starts = {(e['session_id'], e.get('turn_id')) for e in rows if kind(e) == 'turn_start'}
        turn_ends = {(e['session_id'], e.get('turn_id')): e for e in rows if kind(e) == 'turn_end'}
        complete = [e for e in turn_ends.values() if e['data'].get('status') == 'ok']
        coverage = (bool(turn_starts) and turn_starts == set(turn_ends) and set(starts) == set(ends)
                    and set(tools) == set(tool_ends)
                    and all(e['data'].get('provider_call_id') for e in starts.values())
                    and all(e['data'].get('tool_call_id') for e in tools.values())
                    and {e['session_id'] for e in rows} <= {sid for sid, _ in turn_starts}
                    and not any(e['data'].get('dropped_events') or e['data'].get('recording_error') for e in rows))
        return {'provider_calls_started': len(starts), 'provider_calls_finished': len(ends),
                'provider_calls_failed': sum(e['data'].get('status') in {'error', 'cancelled'} for e in ends.values()),
                'provider_requests_observed': native['provider:request'], 'retries_observed': native['provider:retry'],
                'tool_executions_started': len(tools), 'tool_executions_finished': len(tool_ends),
                'tool_executions_successful': sum(e['data'].get('success') is True for e in tool_ends.values()),
                'tool_executions_failed': sum(e['data'].get('success') is False for e in tool_ends.values()),
                'tool_pre_observed': native['tool:pre'], 'tool_post_observed': native['tool:post'],
                'provider_calls_bypassed': len(bypass), 'decisions_scored': len(scores),
                'decision_scoring_ms': sum(latencies) if latencies else None,
                'decision_scoring_p95_ms': sorted(latencies)[math.ceil(len(latencies)*.95)-1] if latencies else None,
                'decision_budget_overruns': sum(v >= 500 for v in latencies),
                'turns_started': len(turn_starts), 'turns_completed': len(complete),
                'instrumented_coverage_complete': coverage, 'fallback_reasons': dict(Counter(row[2] for row in fallback)),
                'provider_usage': usage, 'tool_calls_eliminated': None, 'net_cost_saved_usd': None,
                'task_quality_parity': None}
    sessions = []
    for sid in sorted({e['session_id'] for e in selected}):
        rows = [e for e in selected if e['session_id'] == sid]
        config = next((e for e in reversed(rows) if e['data'].get('phase') == 'configuration'), None)
        presence = [e for e in rows if e['data'].get('phase') in {'configuration', 'session_heartbeat', 'session_closed'}]
        last = presence[-1] if presence else None
        live = bool(last and 0 <= now-_time(last) < 45 and last['data'].get('phase') != 'session_closed')
        lifecycle = [e['data'].get('native_event') for e in rows if e['data'].get('native_event') in {'execution:start', 'execution:end'}]
        mode, backend = (config['data'].get('mode'), config['data'].get('backend')) if config else (None, None)
        status = 'not_observed' if config is None else ('scripted_shadow' if str(backend).startswith('scripted') else 'active_routing' if mode == 'active' else 'real_model_shadow' if mode == 'shadow' and backend not in {None, 'unavailable'} else mode or 'unknown')
        sessions.append({'session_id': sid, 'parent_session_id': parents.get(sid), 'mode': mode, 'backend': backend,
                         'integration': status, 'presence': 'closed' if last and last['data'].get('phase') == 'session_closed' else 'present' if live else 'unknown',
                         'activity': ('working' if lifecycle and lifecycle[-1] == 'execution:start' else 'idle') if live else 'unknown',
                         'last_event_at': rows[-1].get('timestamp'), 'counts': counts(rows)})
    return {'schema_version': 'operations-v1', 'scope': {'session_id': session_id, 'include_children': True, 'sessions': len(sessions)},
            'totals': counts(selected), 'sessions': sessions,
            'evidence_limits': ['Counts cover retained receipts only; missing instrumentation is not zero activity.',
                                'Native hook observations are separate from instrumented execution; do not add them.',
                                'Successful execution does not establish task correctness. Savings need a matched comparison.']}


def measure(events_dir: str | Path = DEFAULT_EVENTS, *, session_id: str | None = None) -> dict:
    events, source = read_receipts(events_dir)
    return {**summarize(events, session_id=session_id), 'source': source}


def _get_json(url, headers=None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=2) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('Health response too large')
    return json.loads(raw)


def diagnose(*, events_dir: str | Path = DEFAULT_EVENTS, session_id: str | None = None,
             state_file: str | Path = DEFAULT_STATE, ollama_url: str = 'http://127.0.0.1:11434',
             model: str = 'qwen3:0.6b', probe: bool = True) -> dict:
    """Inspect local installation, session receipts and authenticated viewer health.

    No model inference, writes, viewer startup, credentials or URLs in output.
    Session composition is observed from receipts, never inferred from installation.
    """
    report = measure(events_dir, session_id=session_id)
    try:
        dist = metadata.distribution('amplifier-fast-decisions')
        direct = json.loads(dist.read_text('direct_url.json') or '{}')
        installed = {'scope': 'invoking_python_environment', 'present': True, 'version': dist.version, 'commit': direct.get('vcs_info', {}).get('commit_id')}
    except (metadata.PackageNotFoundError, ValueError):
        installed = {'scope': 'invoking_python_environment', 'present': False, 'version': None, 'commit': None}
    local = {'status': 'not_probed', 'model': model, 'model_revision': None}
    viewer = {'status': 'not_probed', 'events_directory_matches': None}
    if probe:
        try:
            origin = local_url(ollama_url).removesuffix('/api/generate')
            tags = _get_json(origin + '/api/tags')
            match = next((m for m in tags['models'] if m.get('name') == model), None)
            local.update(status='model_installed' if match else 'model_missing', model_revision=match.get('digest') if match else None)
            local['warm'] = any(m.get('name') == model for m in _get_json(origin + '/api/ps')['models'])
        except Exception:
            local['status'] = 'unavailable_or_invalid'
        try:
            state = json.loads(Path(state_file).expanduser().read_text())
            url = urlsplit(state['url'])
            # Never send a viewer token to an arbitrary origin or redirect.
            if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or not url.port:
                raise ValueError('Invalid viewer origin')
            token = parse_qs(url.fragment).get('token', [None])[0]
            if not token:
                raise ValueError('Missing viewer token')
            health = _get_json(f'http://127.0.0.1:{url.port}/api/health', {'Authorization': 'Bearer ' + token})
            viewer['status'] = 'connected' if health.get('read_only') is True else 'invalid_health'
            viewer['events_directory_matches'] = Path(state['events_dir']).expanduser().resolve() == Path(events_dir).expanduser().resolve()
        except FileNotFoundError:
            viewer['status'] = 'not_started'
        except Exception:
            viewer['status'] = 'disconnected_or_invalid'
    actions = []
    if not report['sessions']:
        actions.append('Start a fresh Amplifier session with the bundle, then pass its session ID; installation alone does not prove composition.')
    if any(s['integration'] == 'scripted_shadow' for s in report['sessions']):
        actions.append('Use an explicit Ollama profile from docs/MODEL-SETUP.md for real scoring; scripted shadow does not bypass provider calls.')
    if local['status'] == 'model_missing':
        actions.append('Run ollama pull for the configured model, then warm it before latency-sensitive work.')
    if local['status'] == 'unavailable_or_invalid':
        actions.append('Start Ollama on the configured literal loopback origin and check its health.')
    if viewer['status'] in {'not_started', 'disconnected_or_invalid'}:
        actions.append('Use afast serve --open with the same events directory; open its complete authenticated URL.')
    if viewer['events_directory_matches'] is False:
        actions.append('The viewer is reading a different events directory. Point diagnostics and the viewer at the same receipts.')
    if report['totals']['decisions_scored'] == 0:
        actions.append('No real score was observed in this scope. Check fallback reasons and use an explicit eligible read/list target.')
    if report['totals']['provider_calls_failed']:
        actions.append('The generative provider failed; decision-model readiness does not establish provider availability.')
    return {'installation': installed, 'local_backend': local, 'viewer': viewer, 'activity': report, 'next_actions': actions}


def compare(payload: dict, *, base_dir: str | Path = '.') -> dict:
    """Compare caller-recorded matched runs; never infer a counterfactual from a trace."""
    if not isinstance(payload, dict) or payload.get('schema_version') != 'paired-runs-v1' or not isinstance(payload.get('pairs'), list) or not 1 <= len(payload['pairs']) <= 1000:
        raise ValueError('Expected paired-runs-v1 with 1..1000 pairs')
    rows = []
    identities = set()
    for pair in payload['pairs']:
        if not isinstance(pair, dict) or not isinstance(pair.get('task_id'), str) or pair.get('split') not in {'development', 'held_out'}:
            raise ValueError('Each pair requires task_id and split')
        task_id = pair['task_id']
        if task_id in identities:
            raise ValueError('Task IDs must be unique; aggregate repeats under distinct task/run identities')
        identities.add(task_id)
        runs = {}
        for side in ('baseline', 'enabled'):
            run = pair.get(side)
            if not isinstance(run, dict) or not isinstance(run.get('events'), str) or not isinstance(run.get('session_id'), str):
                raise ValueError('Each run requires events and session_id')
            if not _number(run.get('wall_time_ms')):
                raise ValueError('Each run requires finite nonnegative wall_time_ms')
            path = Path(run['events']).expanduser()
            if not path.is_absolute():
                path = Path(base_dir) / path
            runs[side] = measure(path, session_id=run['session_id'])
        a, b = pair['baseline'], pair['enabled']
        mismatches = [key for key in ('task_fingerprint', 'workspace_fingerprint', 'provider_model', 'provider_revision', 'hardware') if not isinstance(a.get(key), str) or not a[key] or a[key] in {'unknown', 'server-default', 'unverified'} or a.get(key) != b.get(key)]
        if a['session_id'] == b['session_id']:
            mismatches.append('distinct_sessions')
        def checked(run):
            outcome = run.get('outcome', {})
            if not isinstance(outcome, dict):
                return False
            checks = outcome.get('checks', {})
            return (outcome.get('passed') is True and isinstance(outcome.get('evaluator'), str) and bool(outcome['evaluator'])
                    and isinstance(checks, dict) and bool(checks) and all(v is True for v in checks.values()))
        quality = checked(a) and checked(b)
        if quality and (a['outcome']['evaluator'] != b['outcome']['evaluator'] or set(a['outcome']['checks']) != set(b['outcome']['checks'])):
            mismatches.append('outcome_evaluator')
            quality = False
        complete = all(r['scope']['sessions'] > 0 and not r['source']['truncated'] and not r['source']['invalid_records']
                       and r['totals']['turns_started'] == r['totals']['turns_completed']
                       and r['totals']['instrumented_coverage_complete'] for r in runs.values())
        ac, bc = runs['baseline']['totals'], runs['enabled']['totals']
        deltas = {'wall_time_ms': a['wall_time_ms'] - b['wall_time_ms']}
        for key in ('provider_calls_started', 'tool_executions_started', 'retries_observed', 'provider_calls_failed', 'tool_executions_failed'):
            deltas[key] = ac[key] - bc[key]
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            x, y = ac['provider_usage'][key], bc['provider_usage'][key]
            deltas[key] = x-y if x is not None and y is not None else None
        deltas['cost_usd'] = None
        rows.append({'task_id': task_id, 'split': pair['split'], 'comparable': not mismatches,
                     'mismatches': mismatches, 'outcome_checks_passed': quality, 'complete_receipts': complete,
                     'eligible_for_efficiency_claim': not mismatches and quality and complete,
                     'baseline': runs['baseline'], 'enabled': runs['enabled'], 'baseline_minus_enabled': deltas})
    return {'schema_version': 'paired-comparison-v1', 'pairs': rows,
            'all_pairs_eligible': all(r['eligible_for_efficiency_claim'] for r in rows),
            'all_held_out': all(r['split'] == 'held_out' for r in rows),
            'evidence_limits': ['Outcomes and elapsed times are caller-supplied checks, not independently verified by the comparator.',
                                'Positive deltas mean fewer resources or less time in the enabled run. Regressions remain negative.',
                                'No general quality parity, causal savings or cost estimate is inferred from a small paired sample.']}
