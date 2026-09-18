#!/usr/bin/env python3
"""Resumable, budget-enforced hill-climbing campaign runner for Forge E2E.

Drives `forge_e2e` (the worker) across an arbitrary, resumable set of paired
baseline/candidate runs, with a frozen evaluation protocol, a preregistered
per-experiment proposal, an append-only spend ledger, and a checkpoint +
handoff pair a follow-on session can resume from cold.

Stdlib only. Every subcommand prints one JSON line and exits 0 (ok), 3
(budget refused), or 4 (a precondition failed).
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_e2e  # noqa: E402
from forge_workloads import SPECS  # noqa: E402

CAMPAIGN_SCHEMA = 'fast-decisions-campaign/v1'
PROTOCOL_SCHEMA = 'fast-decisions-protocol/v1'
EXPERIMENT_SCHEMA = 'fast-decisions-experiment/v1'


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).isoformat()


def _print(obj):
    print(json.dumps(obj))


def _fail(code, reason, **extra):
    _print({'error': reason, **extra})
    sys.exit(code)


def _read_json(path):
    return json.loads(Path(path).read_text())


def _dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n')


def _atomic_write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value, indent=2)+'\n')
    os.replace(tmp, path)


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _get(d, dotted, default=None):
    cur = d
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _coerce(value):
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    try:
        return json.loads(value)
    except ValueError:
        return value


def _pid_alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _try_run(cmd, timeout=20):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {'returncode': out.returncode, 'stdout': out.stdout.strip(), 'stderr': out.stderr.strip()}
    except Exception as exc:  # noqa: BLE001 - environment probing must never crash init
        return {'error': str(exc)}


# --------------------------------------------------------------------------
# Ledger (append-only JSONL at the campaign root)
# --------------------------------------------------------------------------

def _ledger_path(root):
    return Path(root)/'ledger.jsonl'


def _ledger_append(root, record):
    record = {**record}
    record.setdefault('ts', _now())
    with _ledger_path(root).open('a') as fh:
        fh.write(json.dumps(record)+'\n')
    return record


def _ledger_lines(root):
    path = _ledger_path(root)
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            lines.append(json.loads(raw))
        except ValueError:
            continue
    return lines


def _budget_totals(root):
    """Settled spend, unknown-cost spend, latest supervisor observation, and
    the sum of reservations that have not yet been settled."""
    entries = _ledger_lines(root)
    reservations = {}
    settled_ids = set()
    settled_benchmark = 0.0
    unknown_spend = 0.0
    supervisor_usd = 0.0
    for e in entries:
        kind = e.get('type')
        if kind == 'reservation':
            reservations[e['id']] = e.get('usd', 0.0)
        elif kind == 'settlement':
            rid = e.get('reservation')
            settled_ids.add(rid)
            if e.get('unknown'):
                unknown_spend += reservations.get(rid, 0.0)
            else:
                settled_benchmark += e.get('actual_usd') or 0.0
        elif kind == 'supervisor_observation':
            supervisor_usd = e.get('usd', supervisor_usd)
    active_reservations = sum(usd for rid, usd in reservations.items() if rid not in settled_ids)
    return {
        'settled_benchmark': settled_benchmark, 'unknown_spend': unknown_spend,
        'supervisor_usd': supervisor_usd, 'active_reservations': active_reservations,
    }


def _budget_status_dict(root):
    protocol = _read_json(Path(root)/'protocol.json')
    totals = _budget_totals(root)
    cap = protocol['limits']['estimated_total_usd']
    spent = totals['settled_benchmark']+totals['unknown_spend']+totals['supervisor_usd']+totals['active_reservations']
    entries = _ledger_lines(root)
    launches_used = sum(1 for e in entries if e.get('type') == 'run_launched')
    candidates_used = len(list((Path(root)/'experiments').glob('*/proposal.json')))
    return {
        'cap': cap, **totals, 'remaining': cap-spent,
        'launches_used': launches_used, 'launches_max': protocol['limits']['max_benchmark_worker_launches'],
        'candidates_used': candidates_used, 'candidates_max': protocol['limits']['max_candidates'],
    }


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def _provider_summaries(settings_path):
    """Parse `providers:` blocks from settings.yaml with a plain line scan
    (no yaml dependency). Only ever extracts id/module/default_model/
    reasoning_effort/priority -- never api_key, base_url, or anything whose
    field name contains key/token/secret."""
    settings_path = Path(settings_path).expanduser()
    if not settings_path.exists():
        return []
    text = settings_path.read_text(encoding='utf-8')
    import re
    blocks = re.split(r'\n\s*-\s*config:\s*\n', text)[1:]
    providers = []
    for block in blocks:
        entry = {}
        for key in ['id', 'module', 'default_model', 'reasoning_effort', 'priority']:
            m = re.search(rf'^\s*{key}:\s*(.+)$', block, re.MULTILINE)
            if m:
                entry[key] = m.group(1).strip().strip("'\"")
        if entry:
            providers.append(entry)
    return providers


def _ollama_tags():
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3) as response:
            models = json.load(response).get('models', [])
        return [{'name': m.get('name'), 'digest': m.get('digest')} for m in models]
    except Exception as exc:  # noqa: BLE001
        return {'error': str(exc)}


def _uv_pip_list(host_python):
    try:
        out = subprocess.run(['uv', 'pip', 'list', '--python', str(host_python)], capture_output=True, text=True, timeout=30)
        rows = []
        for line in out.stdout.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 2 and 'amplifier' in parts[0].lower():
                rows.append({'name': parts[0], 'version': parts[1], 'location': None})
        return rows
    except Exception as exc:  # noqa: BLE001
        return {'error': str(exc)}


def _source_record(path):
    path = Path(path).expanduser().resolve()
    return {'path': str(path), 'git_sha': forge_e2e.git_sha(path),
            'tree_sha256': forge_e2e.tree_sha256(path/'src'/'amplifier_fast_decisions')}


def _inventory(candidate_worktree, installed_cache, evidence_roots, history_index):
    worktrees = []
    try:
        out = subprocess.run(['git', '-C', str(candidate_worktree), 'worktree', 'list', '--porcelain'],
                              capture_output=True, text=True, check=True)
        for block in out.stdout.strip().split('\n\n'):
            info = {}
            wt_path = None
            for line in block.splitlines():
                if line.startswith('worktree '):
                    wt_path = line.split(' ', 1)[1]
                    info['path'] = wt_path
                elif line.startswith('HEAD '):
                    info['HEAD'] = line.split(' ', 1)[1]
                elif line.startswith('branch '):
                    info['branch'] = line.split(' ', 1)[1]
            if wt_path:
                status = subprocess.run(['git', '-C', wt_path, 'status', '--short'], capture_output=True, text=True)
                lines = status.stdout.splitlines()
                info['dirty_tracked'] = sum(1 for line in lines if not line.startswith('??'))
                info['untracked'] = sum(1 for line in lines if line.startswith('??'))
                diff = subprocess.run(['git', '-C', wt_path, 'diff'], capture_output=True, text=True)
                info['dirty_diff_sha256'] = hashlib.sha256((diff.stdout+status.stdout).encode()).hexdigest()
                worktrees.append(info)
    except Exception as exc:  # noqa: BLE001
        worktrees = [{'error': str(exc)}]
    evidence = []
    for e in (evidence_roots or []):
        p = Path(e).expanduser()
        evidence.append({'path': str(p), 'exists': p.exists(),
                          'file_count': sum(1 for f in p.rglob('*') if f.is_file()) if p.exists() else 0})
    return {
        'worktrees': worktrees,
        'installed_cache': {'path': str(installed_cache), 'HEAD': forge_e2e.git_sha(installed_cache)},
        'evidence_roots': evidence,
        'history_index': str(Path(history_index).expanduser()) if history_index else None,
    }


def cmd_init(args):
    root = Path(args.root).expanduser().resolve()
    if (root/'campaign.json').exists():
        return _fail(4, f'Campaign already exists at {root}')
    proposal = _read_json(args.proposal)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    for sub in ['experiments', 'tasks', 'history', 'reports', 'handoff']:
        (root/sub).mkdir(parents=True, exist_ok=True)

    baseline_source = Path(args.baseline_source).expanduser().resolve()
    candidate_worktree = Path(args.candidate_worktree).expanduser().resolve()
    installed_cache = Path(args.installed_cache).expanduser().resolve()
    sources = {
        'baseline_source': _source_record(baseline_source),
        'candidate_worktree': _source_record(candidate_worktree),
        'installed_cache': _source_record(installed_cache),
    }

    campaign_id = f"{proposal.get('campaign_name', 'campaign')}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    campaign = {
        'proposal': proposal, 'campaign_id': campaign_id, 'launched_at_utc': _now(),
        'campaign_root': str(root), 'status': 'active',
        'authorization_scope': {
            'merge': False, 'global_install': False, 'recorded_authorization': None,
            'note': 'no recorded merge/install authorization found; campaign stops at reviewable PRs',
        },
        'sources': sources,
        'host_python': str(Path(args.host_python).expanduser()),
        'events_dir': str(Path(args.events_dir).expanduser()),
        'forge_py': str(forge_e2e.FORGE),
    }
    _dump(root/'campaign.json', campaign)

    evaluator_path = candidate_worktree/'scripts'/'forge_workloads.py'
    evaluator_sha = _sha256_file(evaluator_path)
    protocol = {
        'schema_version': PROTOCOL_SCHEMA, 'frozen_at_utc': _now(),
        'deadline_seconds': _get(proposal, 'evaluation.deadline_seconds', 1200),
        'primary_metric': {
            'name': 'paired_penalized_task_time_ratio',
            'definition': ('per task: mean over reps of penalized_ms where penalized_ms = '
                           'wall_time_ms if outcome_passed else deadline_seconds*1000; '
                           'ratio_task = candidate/baseline; aggregate = geometric mean of ratio_task; '
                           'CI = cluster bootstrap over tasks (2000 resamples, seed 20260918), reported '
                           'only with >= 3 task clusters'),
            'target_point_at_most': _get(proposal, 'targets.primary.target_point_at_most', 0.8),
            'target_ci_upper_below': _get(proposal, 'targets.primary.target_ci_upper_below', 1.0),
        },
        'secondary_metric': {
            'name': 'total_cost_per_successful_task_ratio',
            'definition': ('sum of provider-reported cost_usd over ALL assigned runs of a side divided by '
                           'successful completions; None if any run cost unknown or zero successes'),
            'target_point_at_most': _get(proposal, 'targets.secondary.target_point_at_most', 1.1),
        },
        'quality': {
            'noninferiority_margin': _get(proposal, 'quality.noninferiority_margin', 0.02),
            'critical_new_failures_allowed': _get(proposal, 'quality.critical_new_failures_allowed', 0),
            'critical_failure_definition': ('protected file modified, evaluator crash, or candidate failing an '
                                            'independent check that baseline passed on the same task+rep'),
        },
        'warm_boundary': {
            'p95_ms_below': 500, 'min_observations': 200,
            'boundary': ('request receipt to route decision including state/candidate preparation, transport, '
                         'inference, decoding and policy'),
        },
        'no_eligible_overhead_p95_ms_below': 25,
        'tiers': {'screen': {'tasks': 2, 'reps': 1}, 'pilot': {'min_tasks': 8, 'min_families': 4, 'reps': 3}},
        'splits': {
            'development': ['scheduler', 'event_reducer', 'reconciler'], 'release_holdout': [],
            'note': 'no sealed release holdout authored yet; G3+ claims blocked',
        },
        'evaluator': {'path': 'scripts/forge_workloads.py', 'sha256': evaluator_sha},
        'prompt_sha256': hashlib.sha256(forge_e2e.PROMPT.encode()).hexdigest(),
        'baseline': {
            'orchestrator': forge_e2e.UPSTREAM_LOOP_SOURCE, 'hook_mode': 'off',
            'source_root': str(baseline_source), 'git_sha': sources['baseline_source']['git_sha'],
            'tree_sha256': sources['baseline_source']['tree_sha256'],
        },
        'decision_defaults': forge_e2e.DEFAULT_DECISION,
        'reservation_policy': {
            'per_launch_usd': _get(proposal, 'budgets.per_launch_usd', 12.0),
            'floor_usd': _get(proposal, 'budgets.floor_usd', 5.0),
            'derivation': ('1200 s deadline x ~100 output tok/s x $50/MTok = $6.0 output ceiling; '
                           '30 max iterations x 250k cached input tok x $0.25/MTok = $1.9; '
                           '30 x 10k cache-write tok x $12.5/MTok = $3.75; total $11.65 rounded up; '
                           'provider price table claude-fable-5-1 $10/$50/$0.25/$12.5 per MTok '
                           '(input/output/cache read/cache write)'),
        },
        'isolation': {
            'evaluator_separation': ('directory-only under the same account; evaluator sha frozen here and '
                                      'verified before every evaluation'),
            'contamination_risk': True, 'builder_may_edit_evaluator': False,
        },
        'limits': {
            'max_candidates': _get(proposal, 'budgets.max_candidates', 8),
            'max_benchmark_worker_launches': _get(proposal, 'budgets.max_benchmark_worker_launches', 60),
            'max_infrastructure_retries_per_run': _get(proposal, 'budgets.max_infrastructure_retries_per_run', 1),
            'max_parallel_timed_runs': _get(proposal, 'budgets.max_parallel_timed_runs', 1),
            'wall_hours': _get(proposal, 'budgets.wall_hours', 12),
            'estimated_total_usd': _get(proposal, 'budgets.estimated_total_usd', 150.0),
        },
    }
    _dump(root/'protocol.json', protocol)

    environment = {
        'amplifier_version': _try_run(['amplifier', '--version']),
        'host_python_version': _try_run([args.host_python, '--version']),
        'amplifier_packages': _uv_pip_list(args.host_python),
        'providers': _provider_summaries(Path.home()/'.amplifier/settings.yaml'),
        'ollama_models': _ollama_tags(),
        'platform': platform.platform(), 'cpu_count': os.cpu_count(),
        'forge_doctor': _try_run([args.host_python, str(forge_e2e.FORGE), 'doctor']),
    }
    _dump(root/'environment.json', environment)

    evidence_roots = args.evidence_root or []
    _dump(root/'inventory.json', _inventory(candidate_worktree, installed_cache, evidence_roots, args.history_index))

    _dump(root/'tasks'/'manifest.json', {
        'tasks': [{'id': t, 'family': 'python-repair', 'spec_sha256': hashlib.sha256(SPECS[t].encode()).hexdigest()}
                  for t in SPECS],
        'evaluator_sha256': evaluator_sha,
    })

    _dump(root/'history'/'index.json', {
        'created_at': _now(), 'native_history_index': str(Path(args.history_index).expanduser()),
        'evidence_roots': evidence_roots, 'runs': [],
    })

    _ledger_append(root, {'type': 'campaign_initialized', 'campaign_id': campaign_id})
    checkpoint = _write_checkpoint(root)
    _print({'initialized': str(root), 'campaign_id': campaign_id})
    return checkpoint


# --------------------------------------------------------------------------
# budget
# --------------------------------------------------------------------------

def cmd_budget_reserve(args):
    root = Path(args.root).expanduser().resolve()
    protocol = _read_json(root/'protocol.json')
    cap = protocol['limits']['estimated_total_usd']
    totals = _budget_totals(root)
    spent = totals['settled_benchmark']+totals['unknown_spend']+totals['supervisor_usd']+totals['active_reservations']
    if spent+args.usd > cap:
        return _fail(3, f'Reservation of ${args.usd} would exceed the campaign cap ${cap}', totals=totals, cap=cap)
    rid = str(uuid.uuid4())
    _ledger_append(root, {'type': 'reservation', 'id': rid, 'usd': args.usd, 'purpose': args.purpose})
    _print({'reservation_id': rid, 'usd': args.usd})


def cmd_budget_settle(args):
    root = Path(args.root).expanduser().resolve()
    record = {'type': 'settlement', 'reservation': args.reservation}
    if args.unknown:
        record['unknown'] = True
    else:
        record['actual_usd'] = args.actual_usd
    _ledger_append(root, record)
    _print({'settled': args.reservation})


def _descendant_sessions(session_dir):
    session_dir = Path(session_dir)
    meta_path = session_dir/'metadata.json'
    root_meta = _read_json(meta_path) if meta_path.exists() else {}
    root_id = root_meta.get('id', session_dir.name)
    siblings = {}
    for p in session_dir.parent.iterdir():
        mp = p/'metadata.json'
        if p.is_dir() and mp.exists():
            try:
                siblings[p] = _read_json(mp)
            except ValueError:
                continue
    included = {root_id}
    result = [session_dir]
    changed = True
    while changed:
        changed = False
        for p, meta in siblings.items():
            sid = meta.get('id', p.name)
            if sid in included:
                continue
            if meta.get('parent_id') in included:
                included.add(sid)
                result.append(p)
                changed = True
    return result


def cmd_budget_observe_supervisor(args):
    root = Path(args.root).expanduser().resolve()
    session_dir = Path(args.session_dir).expanduser().resolve()
    sessions = _descendant_sessions(session_dir)
    total = 0.0
    responses = 0
    without_cost = 0
    for sd in sessions:
        events = sd/'events.jsonl'
        if not events.exists():
            continue
        for line in events.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('event') != 'llm:response':
                continue
            responses += 1
            cost = e.get('data', {}).get('usage', {}).get('cost_usd')
            if cost is None:
                without_cost += 1
            else:
                try:
                    total += float(cost)
                except (TypeError, ValueError):
                    without_cost += 1
    _ledger_append(root, {'type': 'supervisor_observation', 'usd': total, 'sessions': len(sessions),
                          'responses': responses, 'responses_without_cost': without_cost})
    _print({'usd': total, 'sessions': len(sessions), 'responses': responses, 'responses_without_cost': without_cost})


def cmd_budget_status(args):
    root = Path(args.root).expanduser().resolve()
    _print(_budget_status_dict(root))


# --------------------------------------------------------------------------
# preregister
# --------------------------------------------------------------------------

def cmd_preregister(args):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    if experiment_dir.exists():
        return _fail(4, f'Experiment {args.experiment} already exists')
    protocol = _read_json(root/'protocol.json')
    campaign = _read_json(root/'campaign.json')
    candidates_used = len(list((root/'experiments').glob('*/proposal.json')))
    if candidates_used >= protocol['limits']['max_candidates']:
        return _fail(4, 'max_candidates reached for this campaign')

    experiment_dir.mkdir(parents=True)
    worktree = Path(args.candidate_worktree).expanduser().resolve()
    snapshot = experiment_dir/'source'
    snap = subprocess.run(['git', '-C', str(worktree), 'worktree', 'add', '--detach', str(snapshot), args.candidate_sha],
                          capture_output=True, text=True)
    if snap.returncode != 0:
        return _fail(4, f'Could not snapshot candidate source: {snap.stderr.strip()}')
    _ledger_append(root, {'type': 'source_snapshotted', 'experiment': args.experiment,
                          'path': str(snapshot), 'sha': args.candidate_sha})

    evaluator_path = snapshot/'scripts'/'forge_workloads.py'
    evaluator_sha = _sha256_file(evaluator_path) if evaluator_path.exists() else None
    protocol_sha256 = _sha256_file(root/'protocol.json')
    if evaluator_sha != protocol['evaluator']['sha256']:
        return _fail(4, 'evaluator drift: candidate snapshot evaluator does not match the frozen protocol evaluator')

    baseline_source = Path(args.baseline_source or protocol['baseline']['source_root']).expanduser().resolve()
    baseline_git_sha = forge_e2e.git_sha(baseline_source)
    candidate_git_sha = forge_e2e.git_sha(snapshot)
    candidate_tree_sha = forge_e2e.tree_sha256(snapshot/'src'/'amplifier_fast_decisions')

    diff = subprocess.run(['git', '-C', str(worktree), 'diff', baseline_git_sha or '', args.candidate_sha],
                          capture_output=True, text=True)
    (experiment_dir/'source.patch').write_text(diff.stdout)
    candidate_diff_sha256 = hashlib.sha256(diff.stdout.encode()).hexdigest()

    tasks = [t.strip() for t in args.tasks.split(',') if t.strip()]
    rng = random.Random(args.seed)
    shuffled_tasks = list(tasks)
    rng.shuffle(shuffled_tasks)
    schedule = []
    for block_idx, task in enumerate(shuffled_tasks):
        for rep in range(1, args.reps+1):
            sides = ['baseline', 'candidate']
            rng.shuffle(sides)
            for side in sides:
                schedule.append({'name': f'{args.experiment}-{task}-r{rep}-{side}-a1', 'task': task, 'side': side,
                                  'rep': rep, 'attempt': 1, 'block': block_idx, 'seed': args.seed})

    decision_overrides = {}
    for kv in (args.decision_override or []):
        key, _, value = kv.partition('=')
        decision_overrides[key] = _coerce(value)

    proposal = {
        'schema_version': EXPERIMENT_SCHEMA, 'status': 'preregistered', 'campaign_id': campaign['campaign_id'],
        'experiment_id': args.experiment, 'backlog_id': args.backlog, 'hypothesis': args.hypothesis,
        'expected_mechanism': args.mechanism, 'one_changed_variable': args.one_change,
        'baseline_source_sha': {'git': baseline_git_sha, 'tree': forge_e2e.tree_sha256(baseline_source/'src'/'amplifier_fast_decisions')},
        'candidate_source_sha': {'git': candidate_git_sha, 'tree': candidate_tree_sha},
        'candidate_diff_sha256': candidate_diff_sha256, 'protocol_sha256': protocol_sha256,
        'task_manifest_sha256': _sha256_file(root/'tasks'/'manifest.json'),
        'evaluator_sha256': evaluator_sha,
        'frozen_run_schedule': schedule,
        'controls': ['identical hashed starting workspaces per pair', 'frozen prompt', 'frozen evaluator',
                     'serial execution', 'same provider/model pin'],
        'mechanism_checks': list(args.mechanism_check or []),
        'primary_metric': protocol['primary_metric'], 'secondary_metric': protocol['secondary_metric'],
        'diagnostics': [], 'falsification': args.falsification,
        'reserved_usd': protocol['reservation_policy']['per_launch_usd']*len(schedule),
        'preregistered_at_utc': _now(),
        'gate_results': {f'G{i}': 'pending' for i in range(6)},
        'decision': 'pending', 'evidence_references': [],
        'note': None,
        'overrides': {k: v for k, v in {
            'provider': getattr(args, 'provider', None), 'model': getattr(args, 'model', None),
            'deadline_seconds': getattr(args, 'deadline_seconds', None),
            'per_launch_usd': getattr(args, 'per_launch_usd', None)}.items() if v is not None},
    }
    _dump(experiment_dir/'proposal.json', proposal)

    config = {
        'runs': schedule,
        'sides': {
            'baseline': {'source_root': str(baseline_source), 'mode': 'off'},
            'candidate': {'source_root': str(snapshot), 'mode': 'active', 'decision_overrides': decision_overrides},
        },
        'upstream_loop_source': protocol['baseline']['orchestrator'],
        'provider': proposal['overrides'].get('provider') or campaign['proposal'].get('provider', 'anthropic'),
        'model': proposal['overrides'].get('model') or campaign['proposal'].get('model', 'claude-fable-5-1'),
        'limits': {'timeout_seconds': proposal['overrides'].get('deadline_seconds') or protocol['deadline_seconds'],
                   'max_iterations': 30, 'extended_thinking': True},
        'events_dir': campaign['events_dir'], 'host_python': campaign['host_python'], 'forge_py': campaign['forge_py'],
        'prompt': forge_e2e.PROMPT,
    }
    forge_e2e.prepare(experiment_dir/'runs', config)
    _ledger_append(root, {'type': 'experiment_preregistered', 'experiment': args.experiment, 'runs': len(schedule)})
    _write_checkpoint(root, next_experiment=args.experiment)
    _print({'preregistered': args.experiment, 'runs': [r['name'] for r in schedule]})


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def cmd_run(args, launcher=None, waiter=None):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    runs_root = experiment_dir/'runs'
    protocol = _read_json(root/'protocol.json')
    per_launch = protocol['reservation_policy']['per_launch_usd']
    proposal_path = experiment_dir/'proposal.json'
    if proposal_path.exists():
        per_launch = (_read_json(proposal_path).get('overrides') or {}).get('per_launch_usd') or per_launch
    launcher = launcher or forge_e2e.launch_run
    waiter = waiter or forge_e2e.wait_for_result

    i = 0
    while True:
        manifest = _read_json(runs_root/'manifest.json')
        if i >= len(manifest['run_order']):
            break
        name = manifest['run_order'][i]
        i += 1
        run_dir = runs_root/name
        if (run_dir/'result.json').exists():
            continue
        item = manifest['runs'][name]
        wait_seconds = manifest['limits']['timeout_seconds']+180

        running = run_dir/'running.json'
        if running.exists():
            info = _read_json(running)
            if _pid_alive(info.get('controller_pid')):
                _ledger_append(root, {'type': 'adopted_live_worker', 'experiment': args.experiment, 'run': name})
                if waiter(runs_root, name, wait_seconds):
                    continue
                # falls through: treated as an infrastructure failure below

        launches_used = sum(1 for e in _ledger_lines(root) if e.get('type') == 'run_launched')
        if launches_used >= protocol['limits']['max_benchmark_worker_launches']:
            _ledger_append(root, {'type': 'paused', 'reason': 'launch_cap', 'experiment': args.experiment, 'run': name})
            _print({'paused': True, 'reason': 'launch_cap', 'run': name})
            sys.exit(3)

        totals = _budget_totals(root)
        cap = protocol['limits']['estimated_total_usd']
        spent = totals['settled_benchmark']+totals['unknown_spend']+totals['supervisor_usd']+totals['active_reservations']
        if spent+per_launch > cap:
            _ledger_append(root, {'type': 'paused', 'reason': 'budget', 'experiment': args.experiment, 'run': name})
            _print({'paused': True, 'reason': 'budget', 'run': name})
            sys.exit(3)

        rid = str(uuid.uuid4())
        _ledger_append(root, {'type': 'reservation', 'id': rid, 'usd': per_launch, 'purpose': f'run:{name}'})
        _ledger_append(root, {'type': 'run_launched', 'experiment': args.experiment, 'run': name,
                              'reservation': rid, 'attempt': item.get('attempt', 1)})
        launcher(runs_root, name)
        ok = waiter(runs_root, name, wait_seconds)

        outcome = _read_json(run_dir/'result.json') if ok and (run_dir/'result.json').exists() else None
        if outcome is not None:
            cost = (outcome.get('native') or {}).get('usage', {}).get('cost_usd')
            if cost is not None:
                _ledger_append(root, {'type': 'settlement', 'reservation': rid, 'actual_usd': cost})
            else:
                _ledger_append(root, {'type': 'settlement', 'reservation': rid, 'unknown': True})
            infra_failure = bool(outcome.get('infrastructure_failure'))
            _ledger_append(root, {'type': 'run_completed', 'experiment': args.experiment, 'run': name,
                                  'outcome_passed': outcome.get('outcome_passed'), 'timed_out': outcome.get('timed_out'),
                                  'wall_time_ms': outcome.get('wall_time_ms'), 'cost_usd': cost,
                                  'source_match': outcome.get('source_match'), 'infrastructure_failure': infra_failure})
        else:
            _ledger_append(root, {'type': 'settlement', 'reservation': rid, 'unknown': True})
            infra_failure = True
            _ledger_append(root, {'type': 'run_completed', 'experiment': args.experiment, 'run': name,
                                  'outcome_passed': False, 'timed_out': None, 'wall_time_ms': None, 'cost_usd': None,
                                  'source_match': None, 'infrastructure_failure': True})

        if infra_failure and item.get('attempt', 1) == 1:
            already_retried = any(
                v['task'] == item['task'] and v['rep'] == item['rep'] and v['side'] == item['side'] and v.get('attempt', 1) == 2
                for v in manifest['runs'].values()
            )
            if not already_retried:
                retry_name = f"{name[:-3]}-a2" if name.endswith('-a1') else f'{name}-a2'
                retry_spec = {'name': retry_name, 'task': item['task'], 'side': item['side'], 'rep': item['rep'],
                              'attempt': 2, 'block': item.get('block'), 'seed': item.get('seed')}
                forge_e2e.add_run(runs_root, retry_spec)
                _ledger_append(root, {'type': 'infrastructure_retry_scheduled', 'experiment': args.experiment, 'run': retry_name})
        _write_checkpoint(root)
    _print({'experiment': args.experiment, 'done': True})


# --------------------------------------------------------------------------
# evaluate
# --------------------------------------------------------------------------

def _bootstrap_ci(ratios, seed, resamples=2000):
    rng = random.Random(seed)
    n = len(ratios)
    means = []
    for _ in range(resamples):
        sample = [ratios[rng.randrange(n)] for _ in range(n)]
        means.append(math.exp(sum(math.log(x) for x in sample)/n))
    means.sort()
    lo = means[max(0, int(0.025*resamples)-1)]
    hi = means[min(resamples-1, int(0.975*resamples))]
    return [lo, hi]


def _assigned_runs(runs_root, manifest):
    groups = {}
    for name, item in manifest['runs'].items():
        groups.setdefault((item['task'], item['rep'], item['side']), []).append((name, item))
    assigned = {}
    attempts_by_key = {}
    for key, members in groups.items():
        members = sorted(members, key=lambda nm: nm[1].get('attempt', 1))
        attempts = [{'name': name, 'attempt': item.get('attempt', 1),
                     'result': _read_json(runs_root/name/'result.json') if (runs_root/name/'result.json').exists() else None}
                    for name, item in members]
        attempts_by_key[key] = attempts
        with_result = [a for a in attempts if a['result'] is not None]
        assigned[key] = with_result[-1] if with_result else attempts[-1]
    return assigned, attempts_by_key


def cmd_evaluate(args):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    proposal = _read_json(experiment_dir/'proposal.json')
    protocol = _read_json(root/'protocol.json')
    snapshot = experiment_dir/'source'
    evaluator_path = snapshot/'scripts'/'forge_workloads.py'
    current_sha = _sha256_file(evaluator_path) if evaluator_path.exists() else None
    if current_sha != protocol['evaluator']['sha256']:
        return _fail(4, 'evaluator drift detected at evaluation time; refusing to score')

    runs_root = experiment_dir/'runs'
    manifest = _read_json(runs_root/'manifest.json')
    assigned, attempts_by_key = _assigned_runs(runs_root, manifest)
    deadline_ms = protocol['deadline_seconds']*1000

    tasks = sorted({k[0] for k in assigned})
    per_task = {}
    missing_evidence = []
    launches = 0
    deadline_failures = 0
    retries = 0
    for task in tasks:
        row = {'task': task}
        for side in ('baseline', 'candidate'):
            keys = [k for k in assigned if k[0] == task and k[2] == side]
            penalized = []
            successes = 0
            costs = []
            names = []
            for key in keys:
                a = assigned[key]
                names.append(a['name'])
                launches += len(attempts_by_key[key])
                retries += sum(1 for x in attempts_by_key[key] if x['attempt'] > 1)
                r = a['result']
                if r is None:
                    missing_evidence.append(a['name'])
                    continue
                penalized.append(r['wall_time_ms'] if r.get('outcome_passed') else deadline_ms)
                if r.get('timed_out'):
                    deadline_failures += 1
                if r.get('outcome_passed'):
                    successes += 1
                native = r.get('native') or {}
                costs.append(native.get('usage', {}).get('cost_usd'))
            row[side] = names
            row[f'{side}_penalized_ms_mean'] = (sum(penalized)/len(penalized)) if penalized else None
            row[f'success_{side}'] = successes
            row[f'cost_{side}'] = sum(c for c in costs if c is not None) if costs and all(c is not None for c in costs) else None
        b, c = row.get('baseline_penalized_ms_mean'), row.get('candidate_penalized_ms_mean')
        row['ratio'] = (c/b) if (b is not None and c is not None and b) else None
        per_task[task] = row

    ratios = [row['ratio'] for row in per_task.values() if row['ratio'] is not None]
    point = math.exp(sum(math.log(r) for r in ratios)/len(ratios)) if ratios else None
    primary = {'point': point}
    if len(per_task) < 3:
        primary['ci95'] = None
        primary['ci95_reason'] = 'not_estimable_fewer_than_3_task_clusters'
    else:
        primary['ci95'] = _bootstrap_ci(ratios, seed=20260918)
    successful_ratios = [
        row['candidate_penalized_ms_mean']/row['baseline_penalized_ms_mean']
        for row in per_task.values()
        if row['success_baseline'] and row['success_candidate'] and row['baseline_penalized_ms_mean']
    ]
    primary['successful_only_ratio'] = (sum(successful_ratios)/len(successful_ratios)) if successful_ratios else None

    baseline_cost = candidate_cost = 0.0
    baseline_success = candidate_success = 0
    costs_known = True
    for row in per_task.values():
        baseline_success += row['success_baseline']
        candidate_success += row['success_candidate']
        if row['cost_baseline'] is None or row['cost_candidate'] is None:
            costs_known = False
        else:
            baseline_cost += row['cost_baseline']
            candidate_cost += row['cost_candidate']
    if costs_known and baseline_success and candidate_success:
        secondary = {'point': (candidate_cost/candidate_success)/(baseline_cost/baseline_success)}
    else:
        secondary = {'point': None, 'reason': 'cost_unknown_or_zero_successes'}

    success_rate_baseline = sum(row['success_baseline'] for row in per_task.values())
    success_rate_candidate = sum(row['success_candidate'] for row in per_task.values())
    critical_new_failures = []
    protected_files_intact = True
    for key, a in assigned.items():
        task, rep, side = key
        r = a['result']
        if side != 'candidate' or r is None:
            continue
        baseline_result = assigned.get((task, rep, 'baseline'), {}).get('result')
        if baseline_result and baseline_result.get('outcome_passed') and not r.get('outcome_passed'):
            critical_new_failures.append(a['name'])
        unchanged = r.get('protected_files_unchanged')
        if unchanged and not all(unchanged.values()):
            critical_new_failures.append(f"{a['name']}:protected_files_modified")
            protected_files_intact = False

    quality = {
        'success_rate_baseline': success_rate_baseline, 'success_rate_candidate': success_rate_candidate,
        'difference': success_rate_candidate-success_rate_baseline,
        'critical_new_failures': critical_new_failures, 'protected_files_intact': protected_files_intact,
        'one_sided_95_lower_bound_of_difference': None,
        'reason': 'not_estimable_at_this_sample_size' if len(per_task) < 8 else None,
    }

    requested = scored = routed = fast_routes = slow_routes = 0
    zero_observation_requests = requests_with_observation_stats = abstained = fast_tool_end_success = 0
    truncation_reasons = Counter()
    latencies = []
    source_matches = []
    mode_matches = []
    for key, a in assigned.items():
        mode_matches.append(a['result'].get('mode_match') if a['result'] else None)
        if key[2] != 'candidate':
            continue
        source_matches.append(a['result'].get('source_match') if a['result'] else None)
        receipts_path = runs_root/a['name']/'receipts.jsonl'
        if not receipts_path.exists():
            continue
        starts = {}
        for line in receipts_path.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            kind = e.get('event', '').split(':')[-1]
            data = e.get('data', {}) if isinstance(e.get('data'), dict) else {}
            if kind == 'requested':
                requested += 1
                starts[e.get('decision_id')] = e
                if 'observation_count' in data:
                    requests_with_observation_stats += 1
                    if data.get('observation_count') == 0:
                        zero_observation_requests += 1
                    truncation_reasons[str(data.get('truncation_reason'))] += 1
            elif kind == 'scored':
                scored += 1
            elif kind == 'routed':
                routed += 1
                if data.get('reason_code') == 'model_abstained':
                    abstained += 1
                if data.get('route') == 'fast':
                    fast_routes += 1
                else:
                    slow_routes += 1
                start = starts.get(e.get('decision_id'))
                if start and e.get('timestamp') and start.get('timestamp'):
                    try:
                        delta = (datetime.fromisoformat(e['timestamp'])-datetime.fromisoformat(start['timestamp'])).total_seconds()*1000
                        if delta >= 0:
                            latencies.append(delta)
                    except ValueError:
                        pass
            elif kind == 'tool_end':
                if data.get('success') is True:
                    fast_tool_end_success += 1
    latencies.sort()
    request_to_route_p95 = latencies[math.ceil(.95*len(latencies))-1] if latencies else None
    mechanism = {
        'source_match_all_candidate': bool(source_matches) and all(m is True for m in source_matches),
        'mode_match_all': bool(mode_matches) and all(m is True for m in mode_matches),
        'mode_match_per_run': mode_matches,
        'requested_count': requested, 'scored_count': scored,
        'zero_observation_requests': zero_observation_requests,
        'requests_with_observation_stats': requests_with_observation_stats,
        'truncation_reasons': dict(truncation_reasons),
        'scored_abstained': abstained, 'fast_tool_end_success': fast_tool_end_success,
        'fast_routes': fast_routes, 'slow_routes': slow_routes, 'request_to_route_p95_ms': request_to_route_p95,
    }

    comparison = {
        'per_task': per_task, 'primary': primary, 'secondary': secondary, 'quality': quality,
        'mechanism': mechanism, 'launches': launches, 'deadline_failures': deadline_failures,
        'retries': retries, 'missing_evidence': missing_evidence,
    }
    _dump(experiment_dir/'comparison.json', comparison)

    critical = len(critical_new_failures) > 0
    all_have_evidence = not missing_evidence
    gates = {
        'G0': 'pass' if (all_have_evidence and mechanism['source_match_all_candidate'] and mechanism['mode_match_all']) else 'fail',
        'G1': 'fail' if critical else 'pass',
        'G2': 'pass' if (point is not None and point < 1.0 and success_rate_candidate >= success_rate_baseline) else 'fail',
        'G3': 'not_evaluated_at_screen_tier', 'G4': 'not_evaluated', 'G5': 'not_evaluated',
    }
    if critical or success_rate_candidate < success_rate_baseline:
        decision = 'reject'
    elif success_rate_candidate >= success_rate_baseline and point is not None and point < 1.0:
        decision = 'keep_as_experimental_incumbent'
    else:
        decision = 'inconclusive'
    evidence_limits = [f'n_task_clusters={len(per_task)}']
    if len(per_task) < 3:
        evidence_limits.append('no statistical claim: fewer than 3 task clusters')
    decision_doc = {
        'decision': decision, 'tier': args.tier, 'gates': gates,
        'evidence_limits': evidence_limits, 'decided_at_utc': _now(),
    }
    _dump(experiment_dir/'decision.json', decision_doc)

    proposal['status'] = 'evaluated'
    proposal['gate_results'] = gates
    proposal['decision'] = decision
    _dump(experiment_dir/'proposal.json', proposal)
    _ledger_append(root, {'type': 'experiment_evaluated', 'experiment': args.experiment, 'decision': decision})
    _write_checkpoint(root)
    _print({'experiment': args.experiment, 'decision': decision, 'primary_point': point})


# --------------------------------------------------------------------------
# checkpoint / status
# --------------------------------------------------------------------------

def _write_latest_report(root, checkpoint):
    lines = ['# Campaign status', '', f"Updated: {checkpoint['updated_at_utc']}", '',
              '## Revisions', '', '```json', json.dumps(checkpoint['revisions'], indent=2), '```', '',
              '## Current bottleneck', '', str(checkpoint.get('bottleneck') or 'none recorded'), '',
              '## Experiments completed', '']
    for e in checkpoint['experiments']:
        lines.append(f"- {e['id']}: status={e['status']} decision={e['decision']} runs={e['runs_done']}/{e['runs_total']}")
    lines += ['', '## Measured gains and quality', '',
              'See each experiment\'s `comparison.json` and `decision.json` under `experiments/<id>/`.', '',
              '## Spend and reservations', '', '```json', json.dumps(checkpoint['budget'], indent=2), '```', '',
              '## Remaining budget', '', f"${checkpoint['budget'].get('remaining')}", '',
              '## Next experiment', '', str(checkpoint.get('next_experiment') or 'none recorded'), '',
              '## Evidence limits', '', '- See per-experiment `decision.json` for gate results and evidence limits.']
    (root/'reports'/'LATEST.md').write_text('\n'.join(lines)+'\n')


def _write_continue_handoff(root, checkpoint):
    lines = [
        '# Continue this campaign', '', f'Campaign root: `{root}`', '',
        '## Commands', '', '```bash',
        f'python3 scripts/campaign.py status --root {root}',
        f'python3 scripts/campaign.py run --root {root} --experiment {checkpoint.get("next_experiment") or "<experiment-id>"}',
        f'python3 scripts/campaign.py evaluate --root {root} --experiment {checkpoint.get("next_experiment") or "<experiment-id>"}',
        f'python3 scripts/campaign.py checkpoint --root {root}', '```', '',
        '## Rules', '',
        '- A Forge observation deadline is not completion. Never treat it as a finished run.',
        '- Always reserve budget before launching a paid run.',
        '- Timed benchmark runs execute strictly serially.',
        "- Do not touch other worktrees; this campaign only owns its own experiment source snapshots.",
        '', '## Current bottleneck', '', str(checkpoint.get('bottleneck') or 'none recorded'), '',
        '## Next experiment', '', str(checkpoint.get('next_experiment') or 'none recorded'),
    ]
    (root/'handoff'/'CONTINUE.md').write_text('\n'.join(lines)+'\n')


def _write_checkpoint(root, bottleneck=None, next_experiment=None):
    root = Path(root)
    campaign = _read_json(root/'campaign.json')
    experiments = []
    for exp_dir in sorted((root/'experiments').iterdir()) if (root/'experiments').exists() else []:
        proposal_path = exp_dir/'proposal.json'
        if not proposal_path.exists():
            continue
        proposal = _read_json(proposal_path)
        manifest_path = exp_dir/'runs'/'manifest.json'
        total = done = 0
        if manifest_path.exists():
            manifest = _read_json(manifest_path)
            total = len(manifest['run_order'])
            done = sum(1 for n in manifest['run_order'] if (exp_dir/'runs'/n/'result.json').exists())
        experiments.append({'id': exp_dir.name, 'status': proposal.get('status'),
                             'decision': proposal.get('decision'), 'runs_done': done, 'runs_total': total})

    live_workers = []
    for exp_dir in (root/'experiments').iterdir() if (root/'experiments').exists() else []:
        runs_root = exp_dir/'runs'
        if not runs_root.exists():
            continue
        for run_dir in runs_root.iterdir():
            running = run_dir/'running.json'
            if running.exists() and not (run_dir/'result.json').exists():
                info = _read_json(running)
                if _pid_alive(info.get('controller_pid')):
                    live_workers.append({'run': run_dir.name, 'pid': info.get('controller_pid')})

    candidate_path = campaign['sources']['candidate_worktree']['path']
    head = forge_e2e.git_sha(candidate_path)
    status = subprocess.run(['git', '-C', candidate_path, 'status', '--short'], capture_output=True, text=True)
    dirty = len([line for line in status.stdout.splitlines() if line.strip()])

    checkpoint = {
        'updated_at_utc': _now(), 'campaign_id': campaign['campaign_id'],
        'revisions': {
            'baseline': campaign['sources']['baseline_source'],
            'candidate_worktree': {**campaign['sources']['candidate_worktree'], 'HEAD': head, 'dirty_count': dirty},
            'installed_cache': campaign['sources']['installed_cache'],
            'experiments': [{'id': e['id']} for e in experiments],
        },
        'experiments': experiments, 'budget': _budget_status_dict(root),
        'live_workers': live_workers, 'bottleneck': bottleneck, 'next_experiment': next_experiment,
    }
    _atomic_write_json(root/'checkpoint.json', checkpoint)
    _write_latest_report(root, checkpoint)
    _write_continue_handoff(root, checkpoint)
    return checkpoint


def cmd_checkpoint(args):
    root = Path(args.root).expanduser().resolve()
    checkpoint = _write_checkpoint(root, bottleneck=args.bottleneck, next_experiment=args.next)
    _print({'checkpointed': True, 'bottleneck': checkpoint.get('bottleneck'), 'next_experiment': checkpoint.get('next_experiment')})


def cmd_status(args):
    root = Path(args.root).expanduser().resolve()
    path = root/'checkpoint.json'
    checkpoint = _read_json(path) if path.exists() else _write_checkpoint(root)
    _print(checkpoint)


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('init')
    p.add_argument('--root', required=True)
    p.add_argument('--proposal', required=True)
    p.add_argument('--baseline-source', required=True)
    p.add_argument('--candidate-worktree', required=True)
    p.add_argument('--installed-cache', required=True)
    p.add_argument('--evidence-root', action='append')
    p.add_argument('--history-index', required=True)
    p.add_argument('--host-python', required=True)
    p.add_argument('--events-dir', required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('budget')
    budget_sub = p.add_subparsers(dest='budget_command', required=True)

    br = budget_sub.add_parser('reserve')
    br.add_argument('--root', required=True)
    br.add_argument('--usd', type=float, required=True)
    br.add_argument('--purpose', required=True)
    br.set_defaults(func=cmd_budget_reserve)

    bs = budget_sub.add_parser('settle')
    bs.add_argument('--root', required=True)
    bs.add_argument('--reservation', required=True)
    bs.add_argument('--actual-usd', type=float)
    bs.add_argument('--unknown', action='store_true')
    bs.set_defaults(func=cmd_budget_settle)

    bo = budget_sub.add_parser('observe-supervisor')
    bo.add_argument('--root', required=True)
    bo.add_argument('--session-dir', required=True)
    bo.set_defaults(func=cmd_budget_observe_supervisor)

    bst = budget_sub.add_parser('status')
    bst.add_argument('--root', required=True)
    bst.set_defaults(func=cmd_budget_status)

    p = sub.add_parser('preregister')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.add_argument('--backlog', required=True)
    p.add_argument('--hypothesis', required=True)
    p.add_argument('--mechanism', required=True)
    p.add_argument('--one-change', required=True)
    p.add_argument('--candidate-worktree', required=True)
    p.add_argument('--candidate-sha', required=True)
    p.add_argument('--tasks', required=True)
    p.add_argument('--reps', type=int, required=True)
    p.add_argument('--tier', required=True)
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--decision-override', action='append')
    p.add_argument('--falsification')
    p.add_argument('--baseline-source')
    p.add_argument('--mechanism-check', action='append')
    p.add_argument('--provider', help='override the provider id for this experiment (configured providers only)')
    p.add_argument('--model', help='override the model pin for this experiment (configured providers only)')
    p.add_argument('--deadline-seconds', type=int, help='override the protocol deadline for this experiment')
    p.add_argument('--per-launch-usd', type=float, help='override the per-launch reservation (must stay conservative)')
    p.set_defaults(func=cmd_preregister)

    p = sub.add_parser('run')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser('evaluate')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.add_argument('--tier', default='screen')
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser('checkpoint')
    p.add_argument('--root', required=True)
    p.add_argument('--bottleneck')
    p.add_argument('--next')
    p.set_defaults(func=cmd_checkpoint)

    p = sub.add_parser('status')
    p.add_argument('--root', required=True)
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
