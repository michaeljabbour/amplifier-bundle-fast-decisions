#!/usr/bin/env python3
"""Multi-harness benchmark runner: claude / codex / opencode / amplifier-plain / amplifier-fd.

Drives the same frozen task set through five external agent harnesses plus
the two Amplifier "sides" (fast-decisions off/active), on identical hashed
starting workspaces, with a shared reservation ledger (reusing the campaign
root created by `campaign.py init`) and a unified per-run result schema.

Stdlib only. Never invokes claude/codex/opencode/amplifier for real in tests
-- tests substitute fakes for `forge`, the amplifier launcher/waiter/closer,
and `battery_tasks`. Every subcommand prints one JSON line and exits 0 (ok),
3 (budget refused), or 4 (a precondition failed).
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
import math
from pathlib import Path
import random
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_e2e  # noqa: E402
import forge_workloads  # noqa: E402
import campaign  # noqa: E402 -- read-only reuse of its ledger/budget/checkpoint helpers

BATTERY_SCHEMA = 'fast-decisions-battery/v1'
HARNESSES = ('claude', 'codex', 'opencode', 'amplifier-plain', 'amplifier-fd')
AMPLIFIER_HARNESSES = ('amplifier-plain', 'amplifier-fd')

# Verified per-million USD rates, copied from
# amplifier-module-provider-openai/amplifier_module_provider_openai/_cost.py
# (standard short-context tier; source cites developers.openai.com/api/docs/pricing,
# verified 2026-09-03). Codex-specific models are not yet priced upstream (see the
# TODO list in that file) so they intentionally have no entry here -- cost stays
# 'unknown' rather than guessing $0.00.
CODEX_PRICES = {
    'gpt-6-astra': {'input_per_m': 10.00, 'output_per_m': 50.00,
                     'cache_read_per_m': 1.00, 'cache_write_per_m': 12.50},
}


# --------------------------------------------------------------------------
# Small shared helpers (mirrors campaign.py's style; deliberately duplicated
# rather than imported so battery.py never depends on campaign.py internals
# beyond its ledger/budget/checkpoint surface)
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


def _load_battery_tasks():
    import battery_tasks
    return battery_tasks


def _register_task_source_from_proposal(proposal):
    """Re-register a prepared experiment's task_source (if any) with
    forge_workloads, so get_task can resolve polyglot task names in this
    process too (prepare() already registered it once; run/evaluate/
    reevaluate are separate invocations, possibly separate processes)."""
    task_source = (proposal or {}).get('task_source')
    if task_source:
        forge_workloads.register_source(task_source['kind'],
                                         **{k: v for k, v in task_source.items() if k != 'kind'})


def _load_forge(forge_py):
    forge_py = Path(forge_py).expanduser()
    sys.path.insert(0, str(forge_py.parent))
    import forge
    return forge


def _amplifier_prompt_and_deadline(task, deadline_seconds):
    """Extra fields for an amplifier run spec: always `deadline_seconds`, plus an
    explicit `prompt` for any battery task with a fixed prompt (forge_workloads
    returns None only for the legacy SPECS trio, which keeps its no-prompt
    fallback). Passing the prompt explicitly is what makes forge_e2e._build_run
    store it on the sub-manifest item -- and worker() verify it -- instead of
    silently falling back to the generic legacy prompt.
    """
    fields = {'deadline_seconds': deadline_seconds}
    task_prompt = forge_workloads.task_prompt(task)
    if task_prompt:
        fields['prompt'] = task_prompt
    return fields


def _run_dir_for(experiment_dir, name, harness):
    runs_root = experiment_dir/'runs'
    if harness in AMPLIFIER_HARNESSES:
        return runs_root/'amplifier'/name
    return runs_root/name


def _freeze_candidate_source(candidate_source, experiment_dir, candidate_sha=None):
    '''Freeze a live git worktree candidate source for the lifetime of one
    experiment.

    A `--candidate-source` that is a live worktree can be edited mid-run
    (forge_e2e.py's tree_sha256 check then refuses the launch with "Source
    changed during the experiment"). Instead of racing the edit, snapshot
    the source into a detached git worktree at `experiment_dir/'source'`
    (or `candidate_sha` if given, else HEAD) and use that snapshot as the
    side's `source_root` -- the bits an experiment runs against can never
    change underneath it again.

    Non-git candidate sources (plain directories) are returned unchanged;
    only a real git worktree is snapshotted.

    Returns `(resolved_source_root, snapshot_info | None)`. Idempotent: a
    snapshot that already exists (re-prepare of the same experiment) is
    reused rather than recreated.
    '''
    candidate_source = Path(candidate_source).expanduser().resolve()
    if not (candidate_source/'.git').exists():
        return str(candidate_source), None
    snapshot = experiment_dir/'source'
    if not snapshot.exists():
        rev = candidate_sha or 'HEAD'
        subprocess.run(
            ['git', '-C', str(candidate_source), 'worktree', 'add', '--detach', str(snapshot), rev],
            check=True, capture_output=True, text=True,
        )
    snapshot_info = {
        'original_source_root': str(candidate_source),
        'snapshot_source_root': str(snapshot),
        'requested_sha': candidate_sha,
        'git_sha': forge_e2e.git_sha(snapshot),
        'tree_sha256': forge_e2e.tree_sha256(snapshot/'src'/'amplifier_fast_decisions'),
    }
    return str(snapshot), snapshot_info


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def _resolve_polyglot_tasks(args):
    """Register the polyglot task source from CLI args and return
    (task_names, dev_names, holdout_names, corpus_sha, polyglot_root, languages).

    `task_names` is the requested `--split` slice (dev/holdout/all) of a
    deterministic `--slice`-sized sample seeded by `--seed`. Fails loud (via
    `_fail`, never raises) when a required polyglot flag is missing.
    """
    if not args.polyglot_root:
        return _fail(4, '--task-source polyglot requires --polyglot-root')
    if not args.slice:
        return _fail(4, '--task-source polyglot requires --slice')
    if not args.split:
        return _fail(4, '--task-source polyglot requires --split')
    languages = [l.strip() for l in (args.languages or '').split(',') if l.strip()] or None
    polyglot_root = str(Path(args.polyglot_root).expanduser().resolve())
    corpus_sha = None
    manifest_path = Path(polyglot_root).parent/'polyglot-manifest.json'
    if manifest_path.exists():
        try:
            corpus_sha = _read_json(manifest_path).get('sha')
        except ValueError:
            corpus_sha = None
    tasks = forge_workloads.register_source('polyglot', root=polyglot_root, languages=languages)
    import polyglot_tasks
    dev_names, holdout_names = polyglot_tasks.select_slice(tasks, n=args.slice, seed=args.seed, languages=languages)
    if args.split == 'dev':
        task_names = dev_names
    elif args.split == 'holdout':
        task_names = holdout_names
    else:
        task_names = sorted(dev_names+holdout_names)
    return task_names, dev_names, holdout_names, corpus_sha, polyglot_root, languages


def cmd_prepare(args):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    if experiment_dir.exists():
        return _fail(4, f'Experiment {args.experiment} already exists')

    harnesses = [h.strip() for h in args.harnesses.split(',') if h.strip()]
    for h in harnesses:
        if h not in HARNESSES:
            return _fail(4, f'unknown harness: {h}')

    task_source_kind = getattr(args, 'task_source', None) or 'battery'
    # Claude Code refuses to run build/test commands under --permission-mode
    # acceptEdits ("build command was not approved"), while codex/opencode/
    # amplifier can always run them. acceptEdits stays the default for the
    # 20-task battery (unchanged behavior); polyglot tasks need real build/test
    # execution to be evaluated at all, so they default to bypassPermissions
    # unless the caller explicitly overrides --claude-permission-mode.
    claude_permission_mode = getattr(args, 'claude_permission_mode', None)
    if claude_permission_mode is None:
        claude_permission_mode = 'bypassPermissions' if task_source_kind == 'polyglot' else 'acceptEdits'
    polyglot_meta = None
    dev_names = holdout_names = None
    if task_source_kind == 'polyglot':
        task_names, dev_names, holdout_names, corpus_sha, polyglot_root, languages = _resolve_polyglot_tasks(args)
        if not task_names:
            return _fail(4, 'no tasks selected')
        polyglot_meta = {'kind': 'polyglot', 'root': polyglot_root, 'languages': languages, 'sha': corpus_sha}
        battery_tasks = None
    else:
        battery_tasks = _load_battery_tasks()
        if args.tasks in ('all', 'dev', 'holdout'):
            task_names = list(battery_tasks.split(args.tasks))
        elif args.tasks:
            task_names = [t.strip() for t in args.tasks.split(',') if t.strip()]
        else:
            return _fail(4, '--tasks is required for --task-source battery')
        if not task_names:
            return _fail(4, 'no tasks selected')

    fd_overrides = {}
    for kv in (args.fd_override or []):
        key, _, value = kv.partition('=')
        fd_overrides[key] = _coerce(value)

    # --amplifier-model/--amplifier-effort pin the generative harness model/effort (NOT
    # the fast-decisions backend's own decision model -- see fd_overrides above) identically
    # on both amplifier sides, so amplifier-plain can be run standalone as e.g. "Amplifier
    # plain on claude-sonnet-5 at medium" with no fast-decisions involved.
    amplifier_model = getattr(args, 'amplifier_model', None) or 'claude-fable-5-1'
    amplifier_effort = getattr(args, 'amplifier_effort', None)

    # --fd-backend/--allow-external-state translate into decision overrides
    # for the amplifier-fd side. External state is opt-in only (docs/PRIVACY.md):
    # jev is a real network call and always requires the explicit flag.
    fd_backend = getattr(args, 'fd_backend', None)
    allow_external_state = bool(getattr(args, 'allow_external_state', False))
    if fd_backend == 'jev' and not allow_external_state:
        return _fail(4, '--fd-backend jev requires --allow-external-state '
                         '(external state is opt-in, never default-on; see docs/PRIVACY.md)')
    if fd_backend:
        fd_overrides['backend'] = fd_backend
    if allow_external_state:
        fd_overrides['allow_external_state'] = True

    deadline_seconds = args.deadline_seconds or (900 if task_source_kind == 'polyglot' else 600)
    experiment_dir.mkdir(parents=True)
    runs_root = experiment_dir/'runs'
    runs_root.mkdir(parents=True)

    # Frozen randomized schedule: tasks in seeded random order; within each
    # task the harness order is independently shuffled (paired blocks).
    rng = random.Random(args.seed)
    shuffled_tasks = list(task_names)
    rng.shuffle(shuffled_tasks)
    schedule = []
    for task in shuffled_tasks:
        order = list(harnesses)
        rng.shuffle(order)
        for harness in order:
            schedule.append({'name': f'{args.experiment}-{task}-{harness}-a1', 'task': task,
                              'harness': harness, 'attempt': 1})

    models = {
        'claude': args.claude_model, 'codex': args.codex_model, 'opencode': args.opencode_model,
        'amplifier-plain': amplifier_model, 'amplifier-fd': amplifier_model,
    }

    amplifier_runs = [r for r in schedule if r['harness'] in AMPLIFIER_HARNESSES]
    candidate_source_snapshot = None
    if amplifier_runs:
        if not args.baseline_source or not args.candidate_source:
            return _fail(4, 'amplifier harnesses require --baseline-source and --candidate-source')
        baseline_source = str(Path(args.baseline_source).expanduser().resolve())
        candidate_source, candidate_source_snapshot = _freeze_candidate_source(
            args.candidate_source, experiment_dir, candidate_sha=getattr(args, 'candidate_sha', None))
        sides = {
            'amplifier-plain': {'source_root': baseline_source, 'mode': 'off'},
            'amplifier-fd': {'source_root': candidate_source, 'mode': 'active',
                              'decision_overrides': fd_overrides},
        }
        fe_config = {
            'runs': [{'name': r['name'], 'task': r['task'], 'side': r['harness'], 'rep': 1,
                      'attempt': 1, 'block': None, 'seed': args.seed,
                      **_amplifier_prompt_and_deadline(r['task'], deadline_seconds)} for r in amplifier_runs],
            'sides': sides,
            'provider': 'anthropic', 'model': amplifier_model, 'amplifier_effort': amplifier_effort,
            'limits': {'timeout_seconds': deadline_seconds, 'max_iterations': 30, 'extended_thinking': True},
            'events_dir': str(forge_e2e.EVENTS), 'host_python': str(forge_e2e.HOST_PYTHON),
            'forge_py': str(forge_e2e.FORGE), 'prompt': forge_e2e.PROMPT,
            'task_source': polyglot_meta,
        }
        forge_e2e.prepare(runs_root/'amplifier', fe_config)
    else:
        baseline_source = args.baseline_source
        candidate_source = args.candidate_source

    for r in schedule:
        if r['harness'] in AMPLIFIER_HARNESSES:
            continue
        forge_e2e._build_workspace(runs_root/r['name'], r['task'])

    # Every workspace for a task must have identical hashed content, no
    # matter which harness will edit it.
    by_task = {}
    for r in schedule:
        ws = _run_dir_for(experiment_dir, r['name'], r['harness'])/'workspace'
        by_task.setdefault(r['task'], []).append(forge_e2e.hash_files(ws))
    for task, hashes in by_task.items():
        assert len(set(hashes)) == 1, f'Workspace mismatch for task={task}: {hashes}'

    prompt = forge_e2e.PROMPT
    if task_source_kind == 'polyglot':
        dev_tasks_final = sorted(t for t in task_names if t in set(dev_names))
        holdout_tasks_final = sorted(t for t in task_names if t in set(holdout_names))
    else:
        dev_tasks = set(battery_tasks.split('dev'))
        holdout_tasks = set(battery_tasks.split('holdout'))
        dev_tasks_final = sorted(t for t in task_names if t in dev_tasks)
        holdout_tasks_final = sorted(t for t in task_names if t in holdout_tasks)
    commands = {h: _command_template(h, models.get(h), args, claude_permission_mode) for h in harnesses}

    proposal = {
        'schema_version': BATTERY_SCHEMA, 'experiment_id': args.experiment, 'seed': args.seed,
        'harnesses': harnesses, 'models': models, 'commands': commands,
        'deadline_seconds': deadline_seconds, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'claude_max_budget_usd': args.claude_max_budget_usd,
        'claude_permission_mode': claude_permission_mode,
        'amplifier_model': amplifier_model, 'amplifier_effort': amplifier_effort,
        'task_source': polyglot_meta,
        'requested_split': args.tasks if task_source_kind == 'battery' else args.split,
        'tasks': task_names,
        'dev_tasks': dev_tasks_final,
        'holdout_tasks': holdout_tasks_final,
        'frozen_run_schedule': schedule,
        'baseline_source': baseline_source, 'candidate_source': candidate_source,
        'candidate_source_snapshot': candidate_source_snapshot,
        'preregistered_at_utc': _now(), 'status': 'prepared',
    }
    if task_source_kind == 'polyglot':
        proposal['polyglot_slice'] = args.slice
        proposal['polyglot_split'] = args.split
    _dump(experiment_dir/'proposal.json', proposal)

    manifest = {
        'schema': BATTERY_SCHEMA, 'run_order': [r['name'] for r in schedule],
        'runs': {r['name']: {**r, 'model': models.get(r['harness'])} for r in schedule},
        'deadline_seconds': deadline_seconds, 'prompt': prompt,
    }
    _dump(runs_root/'manifest.json', manifest)
    _print({'prepared': str(experiment_dir), 'runs': manifest['run_order']})
    return manifest


def _command_template(harness, model, args, claude_permission_mode='acceptEdits'):
    """Command template recorded in proposal.json, prompt redacted to a placeholder."""
    if harness == 'claude':
        return _claude_argv('<PROMPT>', model, args.claude_max_budget_usd or 3.0, claude_permission_mode)
    if harness == 'codex':
        return _codex_argv('<WORKSPACE>', '<PROMPT>', model, '<RUN_DIR>/last-message.md')
    if harness == 'opencode':
        return _opencode_argv('<PROMPT>', model)
    return None


# --------------------------------------------------------------------------
# per-harness argv builders (shared by templates above and dispatch below)
# --------------------------------------------------------------------------

def _claude_argv(prompt, model, max_budget_usd, permission_mode='acceptEdits'):
    argv = ['claude', '-p', prompt, '--output-format', 'json', '--safe-mode',
            '--permission-mode', permission_mode, '--max-budget-usd', str(max_budget_usd)]
    if model:
        argv += ['--model', model]
    return argv


def _codex_argv(workspace, prompt, model, last_message_path):
    argv = ['codex', 'exec', '-C', str(workspace), '-s', 'workspace-write', '--skip-git-repo-check',
            '--json', '-o', str(last_message_path)]
    if model:
        argv += ['-m', model]
    argv.append(prompt)
    return argv


def _opencode_argv(prompt, model):
    return ['opencode', 'run', '--format', 'json', '--pure', '--auto', '-m', model, prompt]


# --------------------------------------------------------------------------
# per-harness output parsing (pure functions, unit-tested against fixtures)
# --------------------------------------------------------------------------

def _parse_claude(stdout):
    """Parse claude's --output-format json --safe-mode stdout: the LAST line that
    parses as a dict with type=="result" is the summary line."""
    best = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get('type') == 'result':
            best = obj
    if best is None:
        return None
    model_usage = best.get('modelUsage') or {}
    model = next(iter(model_usage), None)
    return {
        'cost_usd': best.get('total_cost_usd'), 'harness_duration_ms': best.get('duration_ms'),
        'num_turns': best.get('num_turns'), 'model': model, 'final_message': best.get('result'),
        'tokens': model_usage.get(model) if model else None, 'cost_source': 'harness_reported',
        'cost_billable': True,
    }


_CODEX_TOKEN_KEYS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
                     'output_tokens', 'reasoning_output_tokens')


def _codex_configured_model(config_path=None):
    """Model pinned in ~/.codex/config.toml (`model = "..."`), or None."""
    path = Path(config_path) if config_path else Path.home()/'.codex'/'config.toml'
    try:
        for line in path.read_text().splitlines():
            m = re.match(r'\s*model\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    except OSError:
        return None
    return None


def _parse_codex(stdout, last_message_path, model=None):
    model = model or _codex_configured_model()
    """Parse codex --json JSONL stdout: sum usage across all turn.completed events."""
    tokens = {k: 0 for k in _CODEX_TOKEN_KEYS}
    seen_usage = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        kind = obj.get('type') or (obj.get('msg') or {}).get('type')
        if kind != 'turn.completed':
            continue
        usage = obj.get('usage') or (obj.get('msg') or {}).get('usage')
        if not usage:
            continue
        seen_usage = True
        for k in _CODEX_TOKEN_KEYS:
            v = usage.get(k)
            if isinstance(v, (int, float)):
                tokens[k] += v
    final_message = None
    if last_message_path is not None and Path(last_message_path).exists():
        final_message = Path(last_message_path).read_text()
    cost_usd, cost_source = None, 'unknown'
    rates = CODEX_PRICES.get(model)
    if rates and seen_usage:
        cache_write_rate = rates.get('cache_write_per_m', rates['input_per_m'])
        cost = (tokens['input_tokens']*rates['input_per_m']
                + tokens['output_tokens']*rates['output_per_m']
                + tokens['cached_input_tokens']*rates['cache_read_per_m']
                + tokens['cache_write_input_tokens']*cache_write_rate) / 1_000_000
        cost_usd, cost_source = cost, 'computed_from_tokens_estimate'
    return {'tokens': tokens if seen_usage else None, 'final_message': final_message, 'model': model,
            'cost_usd': cost_usd, 'cost_source': cost_source, 'cost_billable': cost_usd is not None,
            'harness_duration_ms': None, 'num_turns': None}


_OPENCODE_TOKEN_KEYS = ('total', 'input', 'output', 'reasoning', 'cache')


def _parse_opencode(stdout, model=None):
    """Parse opencode --format json JSONL stdout: text events + step_finish token/cost sums."""
    texts = []
    tokens = {k: 0 for k in _OPENCODE_TOKEN_KEYS}
    seen_tokens = False
    cost = 0.0
    seen_cost = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        kind = obj.get('type')
        part = obj.get('part') or {}
        if kind == 'text' and part.get('text'):
            texts.append(part['text'])
        elif kind == 'step_finish':
            step_tokens = part.get('tokens') or {}
            for k in _OPENCODE_TOKEN_KEYS:
                v = step_tokens.get(k)
                if isinstance(v, (int, float)):
                    tokens[k] += v
                    seen_tokens = True
            if 'cost' in part and part.get('cost') is not None:
                cost += part['cost']
                seen_cost = True
    return {'final_message': texts[-1] if texts else None, 'tokens': tokens if seen_tokens else None,
            'cost_usd': cost if seen_cost else None, 'cost_source': 'gateway_internal_not_metered',
            'cost_billable': False, 'model': model, 'harness_duration_ms': None, 'num_turns': None}


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def _evaluate_quality(task_name, task_kind, workspace, final_message):
    if task_kind == 'answer':
        battery_tasks = _load_battery_tasks()
        try:
            return battery_tasks.check_answer(battery_tasks.TASKS[task_name], final_message)
        except Exception as exc:  # noqa: BLE001 -- evaluator must never crash the runner
            return {'checks': 0, 'passed': 0, 'failed': 1, 'failure_labels': [f'check_answer_error:{exc}']}
    try:
        task = forge_workloads.get_task(task_name)
        return task.evaluate(workspace)
    except Exception as exc:  # noqa: BLE001
        return {'checks': 0, 'passed': 0, 'failed': 1, 'failure_labels': [f'evaluate_error:{exc}']}


def _protected_unchanged(task_name, workspace):
    task = forge_workloads.get_task(task_name)
    files = task.files
    return {f: (Path(workspace)/f).exists() and (Path(workspace)/f).read_text() == files.get(f, '')
            for f in task.protected}


def _run_public_tests(workspace):
    if not (Path(workspace)/'test_public.py').exists():
        return None
    # test_public.py may be pytest-style; run_workspace_tests picks the best available
    # runner instead of assuming unittest (which silently collects nothing for plain
    # `def test_*` functions).
    passed, _runner, _summary = forge_e2e.run_workspace_tests(workspace, targets=['test_public.py'])
    return passed


def _run_external(harness, run_dir, workspace, prompt, deadline, model, forge_module, claude_max_budget_usd,
                   claude_permission_mode='acceptEdits'):
    if harness == 'claude':
        argv = _claude_argv(prompt, model, claude_max_budget_usd, claude_permission_mode)
    elif harness == 'codex':
        argv = _codex_argv(workspace, prompt, model, run_dir/'last-message.md')
    else:
        argv = _opencode_argv(prompt, model)
    command, argv_rest = argv[0], argv[1:]
    started_at = _now()
    started_perf = time.perf_counter()
    try:
        obs = forge_module.call('run_command', {'command': command, 'args': argv_rest,
                                                  'cwd': str(workspace), 'timeoutMs': (deadline+30)*1000})
        timed_out = False
    except SystemExit as exc:
        text = str(exc).removeprefix('forge: ')
        try:
            obs = json.loads(text)
        except ValueError:
            return {'infrastructure_failure': True, 'notes': [f'forge_error:{text[:300]}'],
                    'started_at': started_at, 'ended_at': _now(),
                    'wall_time_ms': (time.perf_counter()-started_perf)*1000,
                    'timed_out': False, 'exit_code': None, 'outcome_passed': False, 'stdout': ''}
        timed_out = bool(obs.get('timeout') is True)
    ended_at = _now()
    wall_time_ms = (time.perf_counter()-started_perf)*1000
    stdout = obs.pop('output', '') if isinstance(obs, dict) else ''
    exit_code = obs.get('exitCode') if isinstance(obs, dict) else None
    forge_session_id = obs.get('sessionId') if isinstance(obs, dict) else None
    if forge_session_id:
        try:
            forge_module.call('close_terminal', {'id': forge_session_id})
        except SystemExit:
            pass
    return {'stdout': stdout, 'exit_code': exit_code, 'timed_out': timed_out, 'started_at': started_at,
            'ended_at': ended_at, 'wall_time_ms': wall_time_ms, 'forge_session_id': forge_session_id,
            'infrastructure_failure': False}


def _normalize_worker_result(base, native):
    """Map a forge_e2e worker result.json onto the unified battery schema."""
    if native.get('harness') is None and native.get('side'):
        base = {**base, 'harness': 'amplifier-fd' if native['side'] in ('candidate', 'fast') else 'amplifier-plain'}
    if True:
        usage = (native.get('native') or {}).get('usage') or {}
        cost = usage.get('cost_usd')
        model = native.get('model') or next((e['model'] for e in native.get('effort_receipts', []) if e.get('model')), None)
        return {**base, 'model': model, 'started_at': native.get('started_at'), 'ended_at': native.get('ended_at'),
                'wall_time_ms': native.get('wall_time_ms'), 'harness_duration_ms': None,
                'exit_code': native.get('exit_code'), 'timed_out': native.get('timed_out'),
                'cost_usd': cost, 'cost_source': 'harness_reported' if cost is not None else 'unknown',
                'cost_billable': cost is not None, 'tokens': usage or None, 'num_turns': None,
                'final_message': native.get('final_message'), 'quality': native.get('quality'),
                'protected_files_unchanged': native.get('protected_files_unchanged'),
                'outcome_passed': bool(native.get('outcome_passed')),
                'infrastructure_failure': bool(native.get('infrastructure_failure')), 'notes': []}


# --------------------------------------------------------------------------
# exec_time_ms: harness-specific execution-time derivation (excludes startup
# where a native signal is available), used to annotate every result
# --------------------------------------------------------------------------

def _parse_iso(ts):
    """Parse an ISO-8601 string (or epoch number) into an aware datetime, or None."""
    if ts is None or ts == '':
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except ValueError:
        return None


def _resolve_session_id(result, run_dir):
    """Session id for an amplifier-harness run: result['session_id'], else
    worker-result.json in run_dir, else the first receipts.jsonl line's session_id."""
    sid = (result or {}).get('session_id')
    if sid:
        return sid
    run_dir = Path(run_dir)
    worker_result = run_dir/'worker-result.json'
    if worker_result.exists():
        try:
            data = json.loads(worker_result.read_text())
        except (OSError, ValueError):
            data = None
        if data and data.get('session_id'):
            return data['session_id']
    receipts = run_dir/'receipts.jsonl'
    if receipts.exists():
        try:
            lines = [line for line in receipts.read_text().splitlines() if line.strip()]
        except OSError:
            lines = []
        if lines:
            try:
                first = json.loads(lines[0])
            except ValueError:
                first = {}
            if first.get('session_id'):
                return first['session_id']
    return None


def _amplifier_events_path(run_dir, session_id):
    """~/.amplifier/projects/<slug>/sessions/<sid>/events.jsonl, slug computed
    exactly as forge_e2e.worker computes it from the run's workspace path."""
    workspace = Path(run_dir)/'workspace'
    slug = str(workspace.resolve()).replace('\\', '-').replace('/', '-').replace(':', '')
    return Path.home()/'.amplifier/projects'/slug/'sessions'/session_id/'events.jsonl'


def _amplifier_exec_metrics(result, run_dir):
    """(exec_time_ms, provider_requests) from the session's native events.jsonl:
    first llm:request ts -> last llm:response ts. (None, None) when undeterminable."""
    session_id = _resolve_session_id(result, run_dir)
    if not session_id:
        return None, None
    events_path = _amplifier_events_path(run_dir, session_id)
    if not events_path.exists():
        return None, None
    try:
        lines = events_path.read_text().splitlines()
    except OSError:
        return None, None
    first_request, last_response, request_count = None, None, 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        etype = ev.get('type') or ev.get('event')
        ts = _parse_iso(ev.get('ts'))
        if etype == 'llm:request':
            request_count += 1
            if first_request is None and ts is not None:
                first_request = ts
        elif etype == 'llm:response' and ts is not None:
            last_response = ts
    requests = request_count or None
    if first_request is None or last_response is None:
        return None, requests
    ms = (last_response-first_request).total_seconds()*1000
    return (ms if ms >= 0 else None), requests


def _opencode_exec_time_ms(stdout_text):
    """First step_start timestamp (ms epoch) -> last step_finish timestamp, from
    opencode's --format json JSONL stdout. None when either marker is missing."""
    if not stdout_text:
        return None
    first_start, last_finish = None, None
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        ts = ev.get('timestamp')
        if not isinstance(ts, (int, float)):
            continue
        if ev.get('type') == 'step_start' and first_start is None:
            first_start = ts
        elif ev.get('type') == 'step_finish':
            last_finish = ts
    if first_start is None or last_finish is None:
        return None
    ms = last_finish-first_start
    return ms if ms >= 0 else None


def compute_exec_time(result, run_dir, stdout_text=None):
    """Pure(ish) helper: derive (exec_time_ms, exec_time_source) for one result.

    Amplifier harnesses: native events.jsonl (first llm:request -> last
    llm:response), source 'native_events_first_request_to_last_response'.
    claude: harness_duration_ms, source 'harness_duration_ms'.
    opencode: harness event timestamps (from stdout_text, or run_dir/'harness-
    stdout.txt' when stdout_text is not given), source 'harness_event_timestamps'.
    Everything else (including any harness lacking a usable native signal)
    falls back to wall_time_ms, source 'wall_includes_startup'.
    """
    result = result or {}
    run_dir = Path(run_dir)
    harness = result.get('harness')
    if harness in AMPLIFIER_HARNESSES:
        ms, _requests = _amplifier_exec_metrics(result, run_dir)
        if ms is not None:
            return ms, 'native_events_first_request_to_last_response'
    elif harness == 'claude':
        duration = result.get('harness_duration_ms')
        if duration is not None:
            return duration, 'harness_duration_ms'
    elif harness == 'opencode':
        text = stdout_text
        if text is None:
            stdout_path = run_dir/'harness-stdout.txt'
            if stdout_path.exists():
                try:
                    text = stdout_path.read_text()
                except OSError:
                    text = None
        ms = _opencode_exec_time_ms(text)
        if ms is not None:
            return ms, 'harness_event_timestamps'
    return result.get('wall_time_ms'), 'wall_includes_startup'


def _with_exec_time(result, run_dir, stdout_text=None):
    """Annotate a result dict with exec_time_ms/exec_time_source (and
    provider_requests, when derivable) without mutating the input."""
    ms, source = compute_exec_time(result, run_dir, stdout_text)
    out = {**result, 'exec_time_ms': ms, 'exec_time_source': source}
    if result.get('harness') in AMPLIFIER_HARNESSES:
        _ms, requests = _amplifier_exec_metrics(result, run_dir)
        if requests is not None:
            out['provider_requests'] = requests
    return out


def _dispatch(item, name, experiment_dir, manifest, proposal, launcher=None, waiter=None, closer=None,
              forge_module=None):
    task = forge_workloads.get_task(item['task'])
    prompt = item.get('prompt') or getattr(task, 'prompt', None) or manifest.get('prompt') or forge_e2e.PROMPT
    deadline = item.get('deadline_seconds') or manifest.get('deadline_seconds') or 600
    harness = item['harness']
    base = {'name': name, 'task': item['task'], 'family': task.family, 'split': task.split, 'kind': task.kind,
            'harness': harness, 'attempt': item.get('attempt', 1)}

    if harness in AMPLIFIER_HARNESSES:
        launcher = launcher or forge_e2e.launch_run
        waiter = waiter or forge_e2e.wait_for_result
        closer = closer or forge_e2e.close_worker_terminal
        amp_root = experiment_dir/'runs'/'amplifier'
        amp_run_dir = amp_root/name
        wait_seconds = deadline+180
        try:
            if (amp_root/name/'result.json').exists():
                # The worker already finished (runner restarted after a crash): adopt, never relaunch.
                ok = True
                base['notes'] = ['adopted_existing_worker_result']
            elif (amp_root/name/'running.json').exists():
                # A worker launched by a previous runner is still going: wait for it, never duplicate it.
                base['notes'] = ['adopted_live_worker']
                ok = waiter(amp_root, name, wait_seconds)
            else:
                launcher(amp_root, name)
                ok = waiter(amp_root, name, wait_seconds)
                try:
                    closer(amp_root, name)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001 -- launch never started a worker
            return _with_exec_time({**base, 'model': None, 'started_at': _now(), 'ended_at': _now(),
                    'wall_time_ms': None, 'harness_duration_ms': None, 'exit_code': None,
                    'timed_out': None, 'cost_usd': None, 'cost_source': 'unknown', 'cost_billable': None,
                    'tokens': None, 'num_turns': None, 'final_message': None, 'quality': None,
                    'protected_files_unchanged': None, 'outcome_passed': False,
                    'infrastructure_failure': True, 'notes': [f'launch_failed:{str(exc)[:300]}']}, amp_run_dir)
        native = _read_json(amp_root/name/'result.json') if ok and (amp_root/name/'result.json').exists() else None
        if native is None:
            return _with_exec_time({**base, 'model': None, 'started_at': _now(), 'ended_at': _now(),
                    'wall_time_ms': None, 'harness_duration_ms': None, 'exit_code': None,
                    'timed_out': None, 'cost_usd': None, 'cost_source': 'unknown', 'cost_billable': None,
                    'tokens': None, 'num_turns': None, 'final_message': None, 'quality': None,
                    'protected_files_unchanged': None, 'outcome_passed': False,
                    'infrastructure_failure': True, 'notes': ['no_result_json']}, amp_run_dir)
        if 'cost_source' in native and 'native' not in native:
            # Already normalized by an earlier runner (adopted): return as-is, but still
            # (re)derive exec_time_ms so a pre-existing normalized result gets annotated too.
            merged = {**native, 'notes': list(native.get('notes') or []) + list(base.get('notes') or [])}
            return _with_exec_time(merged, amp_run_dir)
        raw_copy = amp_root/name/'worker-result.json'
        if not raw_copy.exists():
            raw_copy.write_text(json.dumps(native, indent=2)+'\n')  # keep the worker's native evidence
        return _with_exec_time(_normalize_worker_result(base, native), amp_run_dir)

    # External harnesses (claude/codex/opencode)
    run_dir = experiment_dir/'runs'/name
    workspace = run_dir/'workspace'
    forge_module = forge_module or _load_forge(manifest.get('forge_py', str(forge_e2e.FORGE)))
    model = (proposal.get('models') or {}).get(harness)
    outcome = _run_external(harness, run_dir, workspace, prompt, deadline, model, forge_module,
                             proposal.get('claude_max_budget_usd') or 3.0,
                             proposal.get('claude_permission_mode') or 'acceptEdits')
    if outcome.get('infrastructure_failure'):
        return _with_exec_time({**base, 'model': model, **{k: v for k, v in outcome.items() if k != 'stdout'}},
                                run_dir)
    stdout = outcome.pop('stdout', '')
    # Persist raw harness stdout so exec-time can be (re)derived later without a live run
    # (needed for opencode's step_start/step_finish timestamps; harmless for the others).
    try:
        (run_dir/'harness-stdout.txt').write_text(stdout)
    except OSError:
        pass
    if harness == 'claude':
        parsed = _parse_claude(stdout) or {}
    elif harness == 'codex':
        parsed = _parse_codex(stdout, run_dir/'last-message.md', model)
    else:
        parsed = _parse_opencode(stdout, model)

    final_message = parsed.get('final_message')
    quality = _evaluate_quality(item['task'], task.kind, workspace, final_message)
    unchanged = _protected_unchanged(item['task'], workspace)
    public_ok = None
    if task.kind == 'code':
        public_ok = _run_public_tests(workspace)
    outcome_passed = (outcome.get('exit_code') == 0 and not outcome.get('timed_out')
                      and quality.get('failed', 1) == 0 and all(unchanged.values()))
    if public_ok is not None:
        outcome_passed = outcome_passed and public_ok

    result = {**base, 'model': parsed.get('model') or model, 'started_at': outcome.get('started_at'),
            'ended_at': outcome.get('ended_at'), 'wall_time_ms': outcome.get('wall_time_ms'),
            'harness_duration_ms': parsed.get('harness_duration_ms'), 'exit_code': outcome.get('exit_code'),
            'timed_out': outcome.get('timed_out'), 'cost_usd': parsed.get('cost_usd'),
            'cost_source': parsed.get('cost_source', 'unknown'), 'cost_billable': parsed.get('cost_billable'),
            'tokens': parsed.get('tokens'), 'num_turns': parsed.get('num_turns'),
            'final_message': (final_message[:4000] if isinstance(final_message, str) else final_message),
            'quality': quality, 'protected_files_unchanged': unchanged, 'public_tests_passed': public_ok,
            'outcome_passed': outcome_passed, 'infrastructure_failure': False,
            'forge_session_id': outcome.get('forge_session_id'), 'notes': []}
    return _with_exec_time(result, run_dir, stdout)


def cmd_run(args, launcher=None, waiter=None, closer=None, forge_module=None):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    runs_root = experiment_dir/'runs'
    protocol = campaign._read_json(root/'protocol.json')
    proposal = _read_json(experiment_dir/'proposal.json')
    _register_task_source_from_proposal(proposal)
    per_launch = proposal.get('per_launch_usd') or protocol['reservation_policy']['per_launch_usd']

    i = 0
    while True:
        manifest = _read_json(runs_root/'manifest.json')
        if i >= len(manifest['run_order']):
            break
        name = manifest['run_order'][i]
        i += 1
        item = manifest['runs'][name]
        run_dir = _run_dir_for(experiment_dir, name, item['harness'])
        if (run_dir/'result.json').exists():
            continue

        launches_used = sum(1 for e in campaign._ledger_lines(root) if e.get('type') == 'run_launched')
        if launches_used >= protocol['limits']['max_benchmark_worker_launches']:
            campaign._ledger_append(root, {'type': 'paused', 'reason': 'launch_cap',
                                            'experiment': args.experiment, 'run': name})
            _print({'paused': True, 'reason': 'launch_cap', 'run': name})
            sys.exit(3)

        totals = campaign._budget_totals(root)
        cap = protocol['limits']['estimated_total_usd']
        spent = totals['settled_benchmark']+totals['unknown_spend']+totals['supervisor_usd']+totals['active_reservations']
        if spent+per_launch > cap:
            campaign._ledger_append(root, {'type': 'paused', 'reason': 'budget',
                                            'experiment': args.experiment, 'run': name})
            _print({'paused': True, 'reason': 'budget', 'run': name})
            sys.exit(3)

        rid = str(uuid.uuid4())
        campaign._ledger_append(root, {'type': 'reservation', 'id': rid, 'usd': per_launch, 'purpose': f'run:{name}'})
        campaign._ledger_append(root, {'type': 'run_launched', 'experiment': args.experiment, 'run': name,
                                        'reservation': rid, 'attempt': item.get('attempt', 1)})

        try:
            result = _dispatch(item, name, experiment_dir, manifest, proposal,
                                launcher=launcher, waiter=waiter, closer=closer, forge_module=forge_module)
        except Exception as exc:  # noqa: BLE001 -- any unexpected dispatch failure is an infra failure, not a crash
            result = {'name': name, 'task': item['task'], 'harness': item['harness'],
                      'attempt': item.get('attempt', 1), 'model': None, 'wall_time_ms': None,
                      'cost_usd': None, 'cost_billable': None, 'timed_out': None,
                      'infrastructure_failure': True, 'outcome_passed': False,
                      'notes': [f'dispatch_error:{str(exc)[:300]}']}
        run_dir.mkdir(parents=True, exist_ok=True)
        _dump(run_dir/'result.json', result)

        cost = result.get('cost_usd') if result.get('cost_billable') else None
        if cost is not None:
            campaign._ledger_append(root, {'type': 'settlement', 'reservation': rid, 'actual_usd': cost})
        elif result.get('cost_billable') is False:
            campaign._ledger_append(root, {'type': 'settlement', 'reservation': rid, 'actual_usd': 0.0,
                                            'note': 'not_billable_here'})
        else:
            if result.get('infrastructure_failure') and result.get('session_id') is None and not result.get('provider_requests'):
                # No session ever started: zero provider usage, not an unknown cost.
                campaign._ledger_append(root, {'type': 'settlement', 'reservation': rid, 'actual_usd': 0.0,
                                               'note': 'infrastructure failure before any provider call'})
            else:
                campaign._ledger_append(root, {'type': 'settlement', 'reservation': rid, 'unknown': True})

        infra_failure = bool(result.get('infrastructure_failure'))
        campaign._ledger_append(root, {'type': 'run_completed', 'experiment': args.experiment, 'run': name,
                                        'outcome_passed': result.get('outcome_passed'),
                                        'timed_out': result.get('timed_out'), 'wall_time_ms': result.get('wall_time_ms'),
                                        'cost_usd': result.get('cost_usd'), 'infrastructure_failure': infra_failure})

        if infra_failure and item.get('attempt', 1) == 1:
            already_retried = any(
                v['task'] == item['task'] and v['harness'] == item['harness'] and v.get('attempt', 1) == 2
                for v in manifest['runs'].values())
            if not already_retried:
                retry_name = f"{name[:-3]}-a2" if name.endswith('-a1') else f'{name}-a2'
                retry_item = {**item, 'name': retry_name, 'attempt': 2}
                if item['harness'] in AMPLIFIER_HARNESSES:
                    retry_deadline = item.get('deadline_seconds') or proposal.get('deadline_seconds')
                    forge_e2e.add_run(runs_root/'amplifier', {'name': retry_name, 'task': item['task'],
                                                                'side': item['harness'], 'rep': 1, 'attempt': 2,
                                                                'block': item.get('block'), 'seed': item.get('seed'),
                                                                **_amplifier_prompt_and_deadline(item['task'], retry_deadline)})
                else:
                    forge_e2e._build_workspace(runs_root/retry_name, item['task'])
                manifest['runs'][retry_name] = retry_item
                manifest['run_order'].append(retry_name)
                _dump(runs_root/'manifest.json', manifest)
                campaign._ledger_append(root, {'type': 'infrastructure_retry_scheduled',
                                                'experiment': args.experiment, 'run': retry_name})

        campaign._write_checkpoint(root)
    _print({'experiment': args.experiment, 'done': True})


# --------------------------------------------------------------------------
# evaluate (pure math helpers first, unit-tested independently)
# --------------------------------------------------------------------------

def _penalized_ms(result, deadline_ms):
    """Penalized time for one result: exec_time_ms when present (deadline
    otherwise/when not passed), falling back to wall_time_ms for results that
    predate exec_time_ms."""
    if result is None:
        return deadline_ms
    if not result.get('outcome_passed'):
        return deadline_ms
    ms = result.get('exec_time_ms')
    if ms is None:
        ms = result.get('wall_time_ms')
    return ms if ms is not None else deadline_ms


def _penalized_wall_ms(result, deadline_ms):
    """The original (pre-exec_time_ms) penalized-time definition: wall_time_ms
    only. Kept alongside _penalized_ms so evaluate can report both."""
    if result is None:
        return deadline_ms
    return result.get('wall_time_ms') if result.get('outcome_passed') and result.get('wall_time_ms') is not None else deadline_ms


def _geomean(values):
    if not values:
        return None
    return math.exp(sum(math.log(v) for v in values)/len(values))


def _binom_pmf(k, n):
    return math.comb(n, k) / (2**n)


def _sign_test(diffs):
    """Exact two-sided binomial sign test at p=0.5.

    diffs: candidate-minus-reference style values; negative means the
    candidate won (was faster/lower), positive means it lost, zero is a tie
    (excluded from n)."""
    wins = sum(1 for d in diffs if d < 0)
    losses = sum(1 for d in diffs if d > 0)
    ties = sum(1 for d in diffs if d == 0)
    n = wins+losses
    if n == 0:
        return {'wins': wins, 'losses': losses, 'ties': ties, 'p_value': None}
    k = min(wins, losses)
    p = min(1.0, sum(_binom_pmf(i, n) for i in range(0, k+1))*2)
    return {'wins': wins, 'losses': losses, 'ties': ties, 'p_value': p}


def _latest_result(experiment_dir, manifest, name):
    item = manifest['runs'][name]
    run_dir = _run_dir_for(experiment_dir, name, item['harness'])
    path = run_dir/'result.json'
    if not path.exists():
        return None
    result = _read_json(path)
    if 'cost_source' not in result and 'native' in result:
        # A worker result adopted by a restarted runner without normalization: map it on the fly.
        try:
            task = forge_workloads.get_task(item['task'])
        except KeyError:
            task = None
        base = {'name': name, 'task': item['task'], 'family': getattr(task, 'family', None),
                'split': getattr(task, 'split', None), 'kind': getattr(task, 'kind', None),
                'harness': item['harness'], 'attempt': item.get('attempt', 1), 'notes': ['normalized_at_evaluate']}
        result = _normalize_worker_result(base, result)
    return result


def _load_experiment_assigned(experiment_dir):
    """(manifest, assigned) for one experiment: assigned maps (task, harness)
    to its latest-attempt {'name', 'result'}, same rule cmd_evaluate uses."""
    manifest = _read_json(experiment_dir/'runs'/'manifest.json')
    groups = {}
    for name, item in manifest['runs'].items():
        groups.setdefault((item['task'], item['harness']), []).append((name, item.get('attempt', 1)))
    assigned = {}
    for key, members in groups.items():
        members.sort(key=lambda m: m[1])
        name = members[-1][0]
        assigned[key] = {'name': name, 'result': _latest_result(experiment_dir, manifest, name)}
    return manifest, assigned


# --------------------------------------------------------------------------
# mechanism gate: did fast-decisions actually run, from its own receipts
# (see docs/EVENTS.md), or did every request silently fall back to the slow
# path? A paired win/loss comparison is meaningless if the "engaged" side
# never actually engaged (e.g. --fd-backend jev requested but every request
# fell back -- the historical defect this gate exists to catch).
# --------------------------------------------------------------------------

def _receipt_events(run_dir):
    """Parsed `fast_decisions:*` events from run_dir/'receipts.jsonl' (see
    docs/EVENTS.md), skipping any line that isn't valid JSON. [] when the
    file is missing (no receipts -- e.g. an infrastructure failure, or a
    harness that never wrote a receipts.jsonl)."""
    path = Path(run_dir)/'receipts.jsonl'
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def _profile_loop_config(run_dir):
    """The loop-fast-decisions orchestrator config recorded in run_dir/'profile.md'
    (written by forge_e2e._build_run as '---\n<json>\n---\n'): backend,
    model_routing, effort_routing, etc. {} when profile.md is missing, malformed,
    or has no orchestrator config (e.g. the amplifier-plain side runs loop-streaming,
    which carries no decision config at all)."""
    path = Path(run_dir)/'profile.md'
    if not path.exists():
        return {}
    parts = path.read_text().split('---')
    if len(parts) < 3:
        return {}
    try:
        profile = json.loads(parts[1])
    except ValueError:
        return {}
    orchestrator = (profile.get('session') or {}).get('orchestrator') or {}
    return orchestrator.get('config') or {}


def _percentile(values_sorted, pct):
    """Nearest-rank percentile over an already-sorted ascending list of numbers.
    `pct` in [0, 100]. None on an empty list. Stdlib-only (no numpy/statistics
    dependency); nearest-rank is adequate for the receipt-count sample sizes a
    single battery experiment produces."""
    if not values_sorted:
        return None
    n = len(values_sorted)
    idx = min(n - 1, max(0, math.ceil(pct / 100 * n) - 1))
    return values_sorted[idx]


# Receipt event kinds that can carry a judge decision-latency figure. As of
# this writing only `fast_decisions:scored` receipts carry `duration_ms`
# (`latency_kind: "decision_model_wall_time"`) -- confirmed against real
# receipts.jsonl files from a completed campaign run. `fallback` receipts are
# checked too (per docs/EVENTS.md a fallback can in principle report how long
# the judge was given before giving up) but carried no latency field in the
# receipts inspected; if a future fallback receipt adds one, it's picked up
# automatically since the check is generic (any event of these kinds with a
# numeric `duration_ms`), not hardcoded to 'scored' alone.
# HC05 ("judge-driven escalation and phase classification"): both
# `escalation_judged` and `phase_judged` receipts carry a `duration_ms` and
# `backend` field from the same `_ask_judge_choice` call site, so they are
# picked up by the generic per-kind loop below exactly like `scored`.
_LATENCY_EVENT_KINDS = ('scored', 'fallback', 'escalation_judged', 'phase_judged')


def _run_mechanism_counts(run_dir):
    """Raw fast_decisions:* receipt counts for one amplifier-fd run: scored by
    backend, fallback count, routed by route (fast/slow), effort_routed by
    (phase, requested_effort), model_routed requested models and escalations by
    reason, judge decision-latency (ms) observed per backend -- plus the run's
    own configured backend/model_routing (from profile.md). None when the run
    has no receipts.jsonl (nothing to report)."""
    events = _receipt_events(run_dir)
    if not events:
        return None
    scored_by_backend = Counter()
    fallback_count = 0
    routed_by_route = Counter()
    effort_routed_by_phase_effort = Counter()
    model_routed_requested = Counter()
    model_routed_escalations = Counter()
    latencies_ms_by_backend = {}
    # HC05: which backend actually answered each judge ask, and (for
    # escalation) what it decided / (for phase) whether it agreed with the
    # deterministic classifier -- see docs/ARCHITECTURE.md's HC05 section.
    escalation_judged_by_backend = Counter()
    escalation_judged_by_decided = Counter()
    phase_judged_by_backend = Counter()
    phase_judged_agreement = Counter()
    for e in events:
        kind = (e.get('event') or '').removeprefix('fast_decisions:')
        d = e.get('data') or {}
        if kind in _LATENCY_EVENT_KINDS:
            latency = d.get('duration_ms')
            if isinstance(latency, (int, float)) and not isinstance(latency, bool):
                backend = d.get('backend') or 'unknown'
                latencies_ms_by_backend.setdefault(backend, []).append(float(latency))
        if kind == 'scored':
            scored_by_backend[d.get('backend')] += 1
        elif kind == 'fallback':
            fallback_count += 1
        elif kind == 'routed':
            routed_by_route[d.get('route')] += 1
        elif kind == 'effort_routed':
            effort_routed_by_phase_effort[(d.get('phase'), d.get('requested_effort'))] += 1
        elif kind == 'model_routed':
            model_routed_requested[d.get('requested_model')] += 1
            if d.get('escalated'):
                model_routed_escalations[d.get('escalation_reason')] += 1
        elif kind == 'escalation_judged':
            escalation_judged_by_backend[d.get('backend')] += 1
            escalation_judged_by_decided[d.get('decided')] += 1
        elif kind == 'phase_judged':
            phase_judged_by_backend[d.get('backend')] += 1
            agreed = d.get('agreed_with_rules')
            phase_judged_agreement['agreed' if agreed is True else 'disagreed' if agreed is False else 'abstained'] += 1
    loop_config = _profile_loop_config(run_dir)
    return {
        'scored_by_backend': dict(scored_by_backend), 'fallback_count': fallback_count,
        'routed_by_route': dict(routed_by_route),
        'effort_routed_by_phase_effort': {f'{p}:{eff}': n for (p, eff), n in effort_routed_by_phase_effort.items()},
        'model_routed_requested_models': dict(model_routed_requested),
        'model_routed_escalations_by_reason': dict(model_routed_escalations),
        'escalation_judged_by_backend': dict(escalation_judged_by_backend),
        'escalation_judged_by_decided': dict(escalation_judged_by_decided),
        'phase_judged_by_backend': dict(phase_judged_by_backend),
        'phase_judged_agreement': dict(phase_judged_agreement),
        'configured_backend': loop_config.get('backend'),
        'model_routing': loop_config.get('model_routing'),
        'effort_routing': loop_config.get('effort_routing'),
        'latencies_ms_by_backend': latencies_ms_by_backend,
    }


def _mechanism_report(experiment_dir, manifest):
    """Aggregate fast_decisions:* mechanism receipts across every amplifier-fd
    run in the experiment, and a mechanism_engaged verdict:

    - If the profile's backend is external (anything but the shipped default
      'ollama', e.g. 'jev') and either it was never actually scored on that
      backend, or nothing was ever scored and at least one fallback fired,
      the mechanism is not engaged (external backend refused/never scored).
    - If model_routing was configured (a start_model set) but zero
      model_routed receipts were ever emitted, the mechanism is not engaged
      (model routing configured but never applied).

    None when the experiment has no amplifier-fd runs.
    """
    run_dirs = [_run_dir_for(experiment_dir, name, item['harness'])
                for name, item in manifest['runs'].items() if item['harness'] == 'amplifier-fd']
    if not run_dirs:
        return None
    per_run = [c for c in (_run_mechanism_counts(rd) for rd in run_dirs) if c is not None]
    scored_by_backend = Counter()
    fallback_count = 0
    routed_by_route = Counter()
    effort_routed = Counter()
    model_routed_requested = Counter()
    model_routed_escalations = Counter()
    escalation_judged_by_backend = Counter()
    escalation_judged_by_decided = Counter()
    phase_judged_by_backend = Counter()
    phase_judged_agreement = Counter()
    configured_backend = None
    model_routing = None
    effort_routing = None
    latencies_ms_by_backend = {}
    for c in per_run:
        scored_by_backend.update(c['scored_by_backend'])
        fallback_count += c['fallback_count']
        routed_by_route.update(c['routed_by_route'])
        effort_routed.update(c['effort_routed_by_phase_effort'])
        model_routed_requested.update(c['model_routed_requested_models'])
        model_routed_escalations.update(c['model_routed_escalations_by_reason'])
        escalation_judged_by_backend.update(c['escalation_judged_by_backend'])
        escalation_judged_by_decided.update(c['escalation_judged_by_decided'])
        phase_judged_by_backend.update(c['phase_judged_by_backend'])
        phase_judged_agreement.update(c['phase_judged_agreement'])
        configured_backend = configured_backend or c['configured_backend']
        model_routing = model_routing or c['model_routing']
        effort_routing = effort_routing or c['effort_routing']
        for backend, values in c['latencies_ms_by_backend'].items():
            latencies_ms_by_backend.setdefault(backend, []).extend(values)

    # Judge decision latency (ms), per backend and overall, from whichever
    # scored/fallback receipts carried a `duration_ms` figure (see
    # `_LATENCY_EVENT_KINDS`). DESIGN-BRIDGE.md rule (b) gates promoting an
    # external judge backend on p95 < decision_latency_budget_ms -- this is
    # the receipts-derived figure that closes that evidence gap. None (with a
    # reason) when nothing in this experiment's receipts carried a latency
    # figure at all -- never a fabricated number.
    decision_latency_ms_by_backend = {}
    all_latencies_ms = []
    for backend, values in latencies_ms_by_backend.items():
        values_sorted = sorted(values)
        decision_latency_ms_by_backend[backend] = {
            'n': len(values_sorted),
            'p50': _percentile(values_sorted, 50),
            'p95': _percentile(values_sorted, 95),
        }
        all_latencies_ms.extend(values)
    all_latencies_ms.sort()
    decision_latency_ms_p50 = _percentile(all_latencies_ms, 50)
    decision_latency_ms_p95 = _percentile(all_latencies_ms, 95)
    decision_latency_budget_ms = 500
    if decision_latency_ms_p95 is None:
        latency_within_budget = None
        decision_latency_reason = ('no scored or fallback receipt in this experiment carried a '
                                    'latency field (duration_ms) -- cannot compute p95')
    else:
        latency_within_budget = decision_latency_ms_p95 <= decision_latency_budget_ms
        decision_latency_reason = None

    engaged = True
    reasons = []
    scored_total = sum(scored_by_backend.values())
    if configured_backend == 'unavailable':
        if scored_total > 0:
            engaged = False
            reasons.append(f"judge configured 'unavailable' (off) but scored={scored_total} "
                            "(the judge was supposed to be off and was not)")
    elif configured_backend and configured_backend not in ('ollama', 'unavailable'):
        scored_on_backend = scored_by_backend.get(configured_backend, 0)
        if scored_on_backend == 0 or (scored_total == 0 and fallback_count > 0):
            engaged = False
            reasons.append(f"external backend {configured_backend!r} refused/never scored "
                            f"(scored={scored_on_backend} fallback={fallback_count})")
    if model_routing and model_routing.get('start_model') and sum(model_routed_requested.values()) == 0:
        engaged = False
        reasons.append(f"model routing configured (start_model={model_routing.get('start_model')!r}) "
                        "but 0 model_routed receipts")

    # HC05 ("judge-driven escalation and phase classification", opt-in):
    # `judged_engaged` is `None` (not applicable) unless the run's own
    # config actually turned on `escalation_judge: "judge"` and/or
    # `effort_routing.phase_judge`. When one is configured, engagement
    # requires at least one matching receipt, AND every one of those
    # receipts to have been answered by the CONFIGURED backend -- catching
    # both "the judge mechanism never fired" and "it fired against the
    # wrong backend" (the exact class of defect R4 already guards for the
    # base scored/model_routed mechanisms). Feeds a future
    # `mechanism_gate: {require_judged: true}` check.
    escalation_judge_configured = bool(model_routing and model_routing.get('escalation_judge') == 'judge')
    phase_judge_configured = bool(effort_routing and effort_routing.get('phase_judge'))
    judged_reasons = []
    if escalation_judge_configured or phase_judge_configured:
        judged_engaged = True
        if escalation_judge_configured:
            total = sum(escalation_judged_by_backend.values())
            on_configured = escalation_judged_by_backend.get(configured_backend, 0)
            if total == 0:
                judged_engaged = False
                judged_reasons.append('escalation_judge configured but 0 escalation_judged receipts')
            elif on_configured != total:
                judged_engaged = False
                judged_reasons.append(
                    f'escalation_judged receipts came from a different backend than configured '
                    f'{configured_backend!r}: {dict(escalation_judged_by_backend)}')
        if phase_judge_configured:
            total = sum(phase_judged_by_backend.values())
            on_configured = phase_judged_by_backend.get(configured_backend, 0)
            if total == 0:
                judged_engaged = False
                judged_reasons.append('phase_judge configured but 0 phase_judged receipts')
            elif on_configured != total:
                judged_engaged = False
                judged_reasons.append(
                    f'phase_judged receipts came from a different backend than configured '
                    f'{configured_backend!r}: {dict(phase_judged_by_backend)}')
    else:
        judged_engaged = None

    return {
        'runs_evaluated': len(per_run), 'configured_backend': configured_backend,
        'model_routing_configured': bool(model_routing), 'model_routing_start_model': (model_routing or {}).get('start_model'),
        'scored_by_backend': dict(scored_by_backend), 'fallback_count': fallback_count,
        'routed_by_route': dict(routed_by_route),
        'effort_routed_by_phase_effort': dict(effort_routed),
        'model_routed_requested_models': dict(model_routed_requested),
        'model_routed_escalations_by_reason': dict(model_routed_escalations),
        'decision_latency_ms_by_backend': decision_latency_ms_by_backend,
        'decision_latency_ms_p50': decision_latency_ms_p50,
        'decision_latency_ms_p95': decision_latency_ms_p95,
        'decision_latency_budget_ms': decision_latency_budget_ms,
        'latency_within_budget': latency_within_budget,
        'decision_latency_reason': decision_latency_reason,
        'mechanism_engaged': engaged, 'mechanism_reason': '; '.join(reasons) if reasons else None,
        'escalation_judged_by_backend': dict(escalation_judged_by_backend),
        'escalation_judged_by_decided': dict(escalation_judged_by_decided),
        'phase_judged_by_backend': dict(phase_judged_by_backend),
        'phase_judged_agreement': dict(phase_judged_agreement),
        'judged_engaged': judged_engaged,
        'judged_reason': '; '.join(judged_reasons) if judged_reasons else None,
    }


def _amplifier_fd_series_label(experiment_dir, manifest):
    """'amplifier-fd [judge=<backend> <model>; effort <phase>-><effort>, ...; model routing: on/off]'
    derived from an amplifier-fd run's own recorded profile (see _profile_loop_config) --
    never a bare 'amplifier-fd'. None when the experiment has no amplifier-fd runs."""
    run_dirs = [_run_dir_for(experiment_dir, name, item['harness'])
                for name, item in manifest['runs'].items() if item['harness'] == 'amplifier-fd']
    if not run_dirs:
        return None
    loop_config = {}
    for rd in run_dirs:
        loop_config = _profile_loop_config(rd)
        if loop_config:
            break
    backend = loop_config.get('backend') or 'unknown'
    model = loop_config.get('model')
    judge = f'{backend} {model}' if model else backend
    effort_routing = loop_config.get('effort_routing') or {}
    effort_phases = [f'{phase}->{effort}' for phase, effort in effort_routing.items()
                      if phase in ('orient', 'explore', 'implement') and effort]
    effort_label = ', '.join(effort_phases) if effort_phases else 'off'
    model_routing = loop_config.get('model_routing')
    routing_label = 'on' if model_routing and model_routing.get('start_model') else 'off'
    return f'amplifier-fd [judge={judge}; effort {effort_label}; model routing: {routing_label}]'


_CROSS_CAMPAIGN_HARNESSES = ('claude', 'codex', 'opencode', 'amplifier-plain', 'amplifier-fd')


def _cross_campaign_comparison(candidate_tasks, candidate_assigned, deadline_ms, baseline_root, baseline_experiment):
    """Compare the candidate experiment's amplifier-fd exec time against every
    harness present in ANOTHER campaign's experiment (baseline_root/baseline_experiment),
    restricted to the tasks the two experiments have in common. Returns a dict with a
    per-baseline-harness geomean ratio/wins/sign-test, a per-task table, and a per-task
    speed rank of the candidate among all passing harnesses (candidate's own + baseline's).
    """
    baseline_experiment_dir = Path(baseline_root)/'experiments'/baseline_experiment
    baseline_manifest, baseline_assigned = _load_experiment_assigned(baseline_experiment_dir)
    baseline_deadline_ms = baseline_manifest.get('deadline_seconds', 600)*1000
    baseline_tasks = sorted({k[0] for k in baseline_assigned})
    common_tasks = sorted(set(candidate_tasks) & set(baseline_tasks))
    baseline_harnesses = sorted({k[1] for k in baseline_assigned} & set(_CROSS_CAMPAIGN_HARNESSES))

    def candidate_result(task):
        return candidate_assigned.get((task, 'amplifier-fd'), {}).get('result')

    per_task_rank = {}
    for task in common_tasks:
        entries = []
        cr = candidate_result(task)
        if cr and cr.get('outcome_passed'):
            entries.append(('amplifier-fd(candidate)', _penalized_ms(cr, deadline_ms)))
        for h in baseline_harnesses:
            br = baseline_assigned.get((task, h), {}).get('result')
            if br and br.get('outcome_passed'):
                entries.append((h, _penalized_ms(br, baseline_deadline_ms)))
        entries.sort(key=lambda pair: pair[1])
        rank = next((i+1 for i, (label, _ms) in enumerate(entries) if label == 'amplifier-fd(candidate)'), None)
        per_task_rank[task] = {'rank': rank, 'field_size': len(entries)}

    baselines = {}
    for h in baseline_harnesses:
        ratios, diffs = [], []
        wins = losses = 0
        candidate_successes = baseline_successes = 0
        per_task_table = {}
        for task in common_tasks:
            cr = candidate_result(task)
            br = baseline_assigned.get((task, h), {}).get('result')
            c_ms = _penalized_ms(cr, deadline_ms)
            b_ms = _penalized_ms(br, baseline_deadline_ms)
            c_passed = bool(cr and cr.get('outcome_passed'))
            b_passed = bool(br and br.get('outcome_passed'))
            if c_passed:
                candidate_successes += 1
            if b_passed:
                baseline_successes += 1
            per_task_table[task] = {
                'task': task, 'family': ((cr or {}).get('family') or (br or {}).get('family')),
                'candidate_exec_s': (c_ms/1000.0) if (c_ms is not None and c_passed) else None,
                'candidate_passed': c_passed,
                f'{h}_exec_s': (b_ms/1000.0) if (b_ms is not None and b_passed) else None,
                f'{h}_passed': b_passed,
            }
            if c_passed and b_passed and b_ms:
                ratios.append(c_ms/b_ms)
                diffs.append(c_ms-b_ms)
                if c_ms < b_ms:
                    wins += 1
                elif c_ms > b_ms:
                    losses += 1
        sign = _sign_test(diffs)
        baselines[h] = {
            'geomean_ratio': _geomean(ratios), 'wins': wins, 'losses': losses,
            'sign_test_p_value': sign['p_value'], 'n_common_pass_pairs': len(ratios),
            'candidate_successes': candidate_successes, 'baseline_successes': baseline_successes,
            'n_common_tasks': len(common_tasks), 'per_task': per_task_table,
        }

    return {
        'baseline_root': str(baseline_root), 'baseline_experiment': baseline_experiment,
        'common_tasks': common_tasks, 'baselines': baselines, 'rank': per_task_rank,
        'evidence_limits': [
            'single_repetition_per_task_per_harness', 'non_contemporaneous_runs_across_campaigns',
            'external_harness_exec_time_may_still_include_its_own_startup',
            'models_not_necessarily_matched_across_campaigns_or_harnesses',
        ],
    }


def cmd_backfill_exec(args):
    """Fill exec_time_ms/exec_time_source (and provider_requests, when derivable)
    for every existing result.json in an experiment, in place. Idempotent: a
    second run over already-backfilled results reports zero updates. Never
    invokes a harness; reads only what's already on disk (result.json,
    worker-result.json, receipts.jsonl, harness-stdout.txt, native events.jsonl)."""
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    manifest = _read_json(experiment_dir/'runs'/'manifest.json')
    updated = []
    for name, item in manifest['runs'].items():
        run_dir = _run_dir_for(experiment_dir, name, item['harness'])
        path = run_dir/'result.json'
        if not path.exists():
            continue
        result = _read_json(path)
        stdout_text = None
        stdout_path = run_dir/'harness-stdout.txt'
        if stdout_path.exists():
            try:
                stdout_text = stdout_path.read_text()
            except OSError:
                stdout_text = None
        ms, source = compute_exec_time(result, run_dir, stdout_text)
        changed = result.get('exec_time_ms') != ms or result.get('exec_time_source') != source
        new_result = {**result, 'exec_time_ms': ms, 'exec_time_source': source}
        if new_result.get('harness') in AMPLIFIER_HARNESSES:
            _ms, requests = _amplifier_exec_metrics(new_result, run_dir)
            if requests is not None and result.get('provider_requests') != requests:
                new_result['provider_requests'] = requests
                changed = True
        if changed:
            _dump(path, new_result)
            updated.append(name)
    campaign._ledger_append(root, {'type': 'exec_time_backfilled', 'experiment': args.experiment,
                                    'updated': len(updated)})
    _print({'experiment': args.experiment, 'updated': updated})
    return {'experiment': args.experiment, 'updated': updated}


def _prompt_match_info(name, item, amp_manifest):
    """(prompt_matches: bool|None, note: str|None) for one run's preregistered prompt,
    checked without re-running anything.

    Only amplifier sub-manifests (runs/amplifier/manifest.json) record a per-run
    prompt_sha256 today; external harnesses' battery-level manifest never persisted
    one, so this honestly reports None rather than reconstructing a value it cannot
    actually attest to.
    """
    if item.get('harness') not in AMPLIFIER_HARNESSES:
        return None, 'prompt_sha256 not tracked for external harnesses'
    amp_item = ((amp_manifest or {}).get('runs') or {}).get(name) or {}
    recorded_prompt = amp_item.get('prompt')
    if recorded_prompt is None:
        return None, 'prompt not recorded; generic prompt suspected'
    expected_sha256 = amp_item.get('prompt_sha256')
    if expected_sha256 is None:
        return None, 'no prompt_sha256 recorded for this run'
    actual_sha256 = hashlib.sha256(recorded_prompt.encode()).hexdigest()
    return actual_sha256 == expected_sha256, None


def cmd_reevaluate(args):
    """Recompute quality/outcome for every finished run from its workspace (deterministic, no model calls).

    Used after an evaluator/outcome-rule fix; the previous result is kept as result-before-reevaluate.json.
    Also reports (without re-running) whether each run's actual prompt matches its
    preregistered prompt_sha256 -- see _prompt_match_info.
    """
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    manifest = _read_json(experiment_dir/'runs'/'manifest.json')
    proposal = _read_json(experiment_dir/'proposal.json')
    _register_task_source_from_proposal(proposal)
    amp_manifest_path = experiment_dir/'runs'/'amplifier'/'manifest.json'
    amp_manifest = _read_json(amp_manifest_path) if amp_manifest_path.exists() else None
    changed = []
    prompt_checks = []
    for name, item in manifest['runs'].items():
        run_dir = _run_dir_for(experiment_dir, name, item['harness'])
        path = run_dir/'result.json'
        if not path.exists():
            continue
        result = _latest_result(experiment_dir, manifest, name)
        workspace = run_dir/'workspace'
        task = forge_workloads.get_task(item['task'])
        quality = _evaluate_quality(item['task'], task.kind, workspace, result.get('final_message'))
        files = forge_workloads.task_files(item['task'])
        protected = {f: (workspace/f).exists() and (workspace/f).read_text() == files.get(f, '')
                     for f in forge_workloads.task_protected(item['task'])}
        suite_ok = None
        workspace_tests_runner = None
        if any(workspace.glob('test*.py')):
            suite_ok, workspace_tests_runner, _summary = forge_e2e.run_workspace_tests(workspace)
        prompt_matches, prompt_note = _prompt_match_info(name, item, amp_manifest)
        prompt_checks.append({'run': name, 'prompt_matches': prompt_matches, 'note': prompt_note})
        outcome = bool(result.get('exit_code') == 0 and not result.get('timed_out') and quality.get('failed') == 0
                       and suite_ok is not False and all(protected.values()) and not result.get('infrastructure_failure'))
        if outcome != bool(result.get('outcome_passed')) or quality != result.get('quality'):
            (run_dir/'result-before-reevaluate.json').write_text(json.dumps(result, indent=2)+'\n')
            notes = list(result.get('notes') or []) + [f'reevaluated: outcome {result.get("outcome_passed")} -> {outcome}']
            result = {**result, 'quality': quality, 'protected_files_unchanged': protected, 'workspace_tests_passed': suite_ok,
                      'workspace_tests_runner': workspace_tests_runner, 'prompt_matches': prompt_matches,
                      'outcome_passed': outcome, 'notes': notes}
            path.write_text(json.dumps(result, indent=2)+'\n')
            changed.append({'run': name, 'outcome_passed': outcome, 'failed_checks': quality.get('failed')})
    campaign._ledger_append(root, {'type': 'reevaluated', 'experiment': args.experiment, 'changed': len(changed),
                                   'reason': getattr(args, 'reason', None)})
    _print({'experiment': args.experiment, 'changed': changed, 'prompt_checks': prompt_checks})
    return {'experiment': args.experiment, 'changed': changed, 'prompt_checks': prompt_checks}


def cmd_evaluate(args):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    proposal = _read_json(experiment_dir/'proposal.json')
    _register_task_source_from_proposal(proposal)
    manifest, assigned = _load_experiment_assigned(experiment_dir)
    deadline_ms = manifest.get('deadline_seconds', 600)*1000

    tasks = sorted({k[0] for k in assigned})
    harnesses = sorted({k[1] for k in assigned})

    per_harness = {}
    for harness in harnesses:
        results = [assigned[(t, harness)]['result'] for t in tasks if (t, harness) in assigned]
        n = len(results)
        successes = sum(1 for r in results if r and r.get('outcome_passed'))
        deadline_failures = sum(1 for r in results if r and r.get('timed_out'))
        penalized = [_penalized_ms(r, deadline_ms) for r in results]
        penalized_wall = [_penalized_wall_ms(r, deadline_ms) for r in results]
        costs_known = [r.get('cost_usd') for r in results if r and r.get('cost_usd') is not None]
        unknown_cost_count = sum(1 for r in results if r is None or r.get('cost_usd') is None)
        sorted_pen = sorted(penalized)
        median_pen = sorted_pen[len(sorted_pen)//2] if sorted_pen else None
        sorted_wall = sorted(penalized_wall)
        median_wall = sorted_wall[len(sorted_wall)//2] if sorted_wall else None
        tokens_total = None
        token_sums = {}
        for r in results:
            t = (r or {}).get('tokens') or {}
            for k, v in t.items():
                if isinstance(v, (int, float)):
                    token_sums[k] = token_sums.get(k, 0)+v
        per_harness[harness] = {
            'n': n, 'success_rate': (successes/n) if n else None, 'deadline_failures': deadline_failures,
            'mean_penalized_ms': (sum(penalized)/n) if n else None, 'median_penalized_ms': median_pen,
            # exec_time_ms-aware (same values as mean/median_penalized_ms above; named
            # explicitly so consumers don't have to know the penalized default changed).
            'mean_exec_ms': (sum(penalized)/n) if n else None, 'median_exec_ms': median_pen,
            # Pre-exec_time_ms behavior (wall_time_ms only), kept for comparability.
            'mean_wall_ms': (sum(penalized_wall)/n) if n else None, 'median_wall_ms': median_wall,
            'mean_cost_known_usd': (sum(costs_known)/len(costs_known)) if costs_known else None,
            'unknown_cost_count': unknown_cost_count,
            'cost_per_success_usd': (sum(costs_known)/successes) if costs_known and successes else None,
            'tokens': token_sums or None,
        }

    per_task = {}
    for task in tasks:
        row = {'task': task}
        best_harness, best_ms = None, None
        for harness in harnesses:
            r = assigned.get((task, harness), {}).get('result')
            ms = _penalized_ms(r, deadline_ms)
            row[harness] = {'penalized_ms': ms, 'outcome_passed': bool(r and r.get('outcome_passed')),
                            'cost_usd': r.get('cost_usd') if r else None}
            if r and r.get('outcome_passed') and (best_ms is None or ms < best_ms):
                best_ms, best_harness = ms, harness
        row['fastest_passing_harness'] = best_harness
        per_task[task] = row

    family_table = {}
    for task in tasks:
        family = None
        for harness in harnesses:
            r = assigned.get((task, harness), {}).get('result')
            if r and r.get('family'):
                family = r['family']
                break
        family = family or 'unknown'
        family_table.setdefault(family, {})
        for harness in harnesses:
            r = assigned.get((task, harness), {}).get('result')
            bucket = family_table[family].setdefault(harness, {'n': 0, 'successes': 0, 'penalized_ms': []})
            bucket['n'] += 1
            bucket['successes'] += 1 if (r and r.get('outcome_passed')) else 0
            bucket['penalized_ms'].append(_penalized_ms(r, deadline_ms))

    paired = None
    if 'amplifier-fd' in harnesses and 'amplifier-plain' in harnesses:
        ratios, diffs = [], []
        wins = losses = ties = 0
        cost_fd = cost_plain = 0.0
        costs_known = True
        for task in tasks:
            fd = assigned.get((task, 'amplifier-fd'), {}).get('result')
            plain = assigned.get((task, 'amplifier-plain'), {}).get('result')
            fd_ms = _penalized_ms(fd, deadline_ms)
            plain_ms = _penalized_ms(plain, deadline_ms)
            ratios.append(fd_ms/plain_ms if plain_ms else None)
            diffs.append(fd_ms-plain_ms)
            if fd_ms < plain_ms:
                wins += 1
            elif fd_ms > plain_ms:
                losses += 1
            else:
                ties += 1
            fc, pc = (fd or {}).get('cost_usd'), (plain or {}).get('cost_usd')
            if fc is None or pc is None:
                costs_known = False
            else:
                cost_fd += fc
                cost_plain += pc
        ratios = [r for r in ratios if r is not None]
        sign = _sign_test(diffs)
        paired = {'geomean_ratio': _geomean(ratios), 'wins': wins, 'losses': losses, 'ties': ties,
                  'sign_test_p_value': sign['p_value'],
                  'cost_ratio': (cost_fd/cost_plain) if (costs_known and cost_plain) else None}

    dev_tasks = set(proposal.get('dev_tasks', []))
    holdout_tasks = set(proposal.get('holdout_tasks', []))

    def _slice(names):
        return {t: per_task[t] for t in names if t in per_task}

    baseline_root = getattr(args, 'baseline_root', None)
    baseline_experiment = getattr(args, 'baseline_experiment', None)
    cross = None
    if baseline_root and baseline_experiment:
        cross = _cross_campaign_comparison(tasks, assigned, deadline_ms,
                                            Path(baseline_root).expanduser().resolve(), baseline_experiment)

    comparison = {
        'per_harness': per_harness, 'per_task': per_task, 'per_family': family_table,
        'amplifier_fd_vs_plain': paired, 'cross': cross,
        'dev': _slice(dev_tasks), 'holdout': _slice(holdout_tasks),
        'mechanism': _mechanism_report(experiment_dir, manifest),
        'amplifier_fd_series_label': _amplifier_fd_series_label(experiment_dir, manifest),
        'evidence_limits': [f'n_tasks={len(tasks)}', 'single_repetition_per_task_per_harness',
                            'models_not_necessarily_matched_across_harnesses'],
    }
    _dump(experiment_dir/'comparison.json', comparison)
    _write_report(experiment_dir, comparison, proposal)
    _print({'experiment': args.experiment, 'per_harness': {h: v['success_rate'] for h, v in per_harness.items()}})
    return comparison


def _write_report(experiment_dir, comparison, proposal):
    fd_label = comparison.get('amplifier_fd_series_label') or 'amplifier-fd'
    lines = ['# Battery report', '', f"Experiment: {proposal.get('experiment_id')}", '', '## Per-harness summary', '']
    for harness, row in comparison['per_harness'].items():
        label = fd_label if harness == 'amplifier-fd' else harness
        lines.append(f"- {label}: n={row['n']} success_rate={row['success_rate']} "
                     f"mean_exec_ms={row['mean_exec_ms']} mean_wall_ms={row['mean_wall_ms']} "
                     f"unknown_cost_count={row['unknown_cost_count']}")
    lines += ['', f'## {fd_label} vs amplifier-plain', '']
    if comparison['amplifier_fd_vs_plain']:
        p = comparison['amplifier_fd_vs_plain']
        lines.append(f"geomean_ratio={p['geomean_ratio']} wins={p['wins']} losses={p['losses']} "
                     f"ties={p['ties']} sign_test_p_value={p['sign_test_p_value']} cost_ratio={p['cost_ratio']}")
    else:
        lines.append('not evaluated (both amplifier harnesses required)')
    mechanism = comparison.get('mechanism')
    lines += ['', '## Mechanism gate', '']
    if mechanism:
        if not mechanism['mechanism_engaged']:
            lines.append(f"WARNING: mechanism_engaged=false -- {mechanism['mechanism_reason']}")
        lines.append(f"runs_evaluated={mechanism['runs_evaluated']} configured_backend={mechanism['configured_backend']} "
                     f"scored_by_backend={mechanism['scored_by_backend']} fallback_count={mechanism['fallback_count']} "
                     f"routed_by_route={mechanism['routed_by_route']}")
        lines.append(f"effort_routed_by_phase_effort={mechanism['effort_routed_by_phase_effort']} "
                     f"model_routing_configured={mechanism['model_routing_configured']} "
                     f"model_routed_requested_models={mechanism['model_routed_requested_models']} "
                     f"model_routed_escalations_by_reason={mechanism['model_routed_escalations_by_reason']}")
        lines.append(f"decision_latency_ms_p50={mechanism['decision_latency_ms_p50']} "
                     f"decision_latency_ms_p95={mechanism['decision_latency_ms_p95']} "
                     f"decision_latency_budget_ms={mechanism['decision_latency_budget_ms']} "
                     f"latency_within_budget={mechanism['latency_within_budget']} "
                     f"decision_latency_ms_by_backend={mechanism['decision_latency_ms_by_backend']}")
        if mechanism['decision_latency_ms_p95'] is None:
            lines.append(f"decision_latency: {mechanism['decision_latency_reason']}")
    else:
        lines.append('not evaluated (no amplifier-fd runs)')
    lines += ['', '## Per-task', '', '```json', json.dumps(comparison['per_task'], indent=2), '```', '']
    cross = comparison.get('cross')
    if cross:
        lines += ['## Cross-campaign comparison', '',
                  f"Baseline: {cross['baseline_root']} experiment={cross['baseline_experiment']}",
                  f"Common tasks: {len(cross['common_tasks'])}", '']
        for h, row in cross['baselines'].items():
            lines.append(f"- amplifier-fd vs {h}: geomean_ratio={row['geomean_ratio']} wins={row['wins']} "
                         f"losses={row['losses']} sign_test_p_value={row['sign_test_p_value']} "
                         f"n_common_pass_pairs={row['n_common_pass_pairs']} "
                         f"candidate_successes={row['candidate_successes']}/{row['n_common_tasks']} "
                         f"baseline_successes={row['baseline_successes']}/{row['n_common_tasks']}")
        lines += ['', '### Per-task rank (candidate speed rank among passing harnesses)', '',
                  '```json', json.dumps(cross['rank'], indent=2), '```', '',
                  '### Per-task exec times', '',
                  '```json', json.dumps({h: row['per_task'] for h, row in cross['baselines'].items()}, indent=2),
                  '```', '', '### Cross-campaign evidence limits', ''] + [f'- {e}' for e in cross['evidence_limits']]
    lines += ['', '## Evidence limits', ''] + [f'- {e}' for e in comparison['evidence_limits']]
    (experiment_dir/'REPORT.md').write_text('\n'.join(lines)+'\n')


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(args):
    root = Path(args.root).expanduser().resolve()
    experiment_dir = root/'experiments'/args.experiment
    manifest = _read_json(experiment_dir/'runs'/'manifest.json')
    done = running = 0
    for name, item in manifest['runs'].items():
        run_dir = _run_dir_for(experiment_dir, name, item['harness'])
        if (run_dir/'result.json').exists():
            done += 1
        elif (run_dir/'running.json').exists():
            running += 1
    spent = None
    if (root/'protocol.json').exists():
        spent = campaign._budget_totals(root)
    _print({'experiment': args.experiment, 'done': done, 'total': len(manifest['run_order']),
            'running': running, 'spent': spent})


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('prepare')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.add_argument('--harnesses', required=True)
    p.add_argument('--tasks', required=False, default=None,
                    help='all|dev|holdout|comma-list. Required for --task-source battery (the default); '
                         'ignored for --task-source polyglot (use --split instead).')
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--fd-override', action='append')
    p.add_argument('--deadline-seconds', type=int)
    p.add_argument('--claude-model')
    p.add_argument('--codex-model')
    p.add_argument('--opencode-model')
    p.add_argument('--claude-max-budget-usd', type=float)
    p.add_argument('--claude-permission-mode', choices=['acceptEdits', 'bypassPermissions'], default=None,
                    help='Claude Code --permission-mode. Default: acceptEdits for --task-source battery '
                         '(unchanged), bypassPermissions for --task-source polyglot (build/test commands '
                         'are denied under acceptEdits). Explicit value always wins.')
    p.add_argument('--baseline-source')
    p.add_argument('--candidate-source')
    p.add_argument('--candidate-sha', help='Freeze the candidate snapshot at this git rev instead of HEAD')
    p.add_argument('--fd-backend', choices=['ollama', 'jev'],
                    help='Decision backend override for the amplifier-fd side')
    p.add_argument('--allow-external-state', action='store_true',
                    help='Required alongside --fd-backend jev (opt-in external state; see docs/PRIVACY.md)')
    p.add_argument('--amplifier-model', default=None,
                    help="Generative model for BOTH amplifier sides (plain and fd), so a paired "
                         "comparison never silently compares two different models. "
                         "Default: today's value, claude-fable-5-1.")
    p.add_argument('--amplifier-effort', default=None,
                    help='Reasoning effort for BOTH amplifier sides (provider-anthropic '
                         'reasoning_effort). Default: unset (provider default).')
    p.add_argument('--task-source', choices=['battery', 'polyglot'], default='battery',
                    help='Task set to prepare from: the 20-task battery (default) or the aider-polyglot corpus.')
    p.add_argument('--polyglot-root', help='Path to a polyglot-benchmark checkout (--task-source polyglot).')
    p.add_argument('--languages', help='Comma-separated language filter for --task-source polyglot.')
    p.add_argument('--slice', type=int, help='Deterministic sample size for --task-source polyglot.')
    p.add_argument('--split', choices=['dev', 'holdout', 'all'],
                    help='Which half of the --slice sample to prepare (--task-source polyglot).')
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser('run')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser('reevaluate')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.add_argument('--reason')
    p.set_defaults(func=cmd_reevaluate)

    p = sub.add_parser('evaluate')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.add_argument('--baseline-root')
    p.add_argument('--baseline-experiment')
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser('backfill-exec')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.set_defaults(func=cmd_backfill_exec)

    p = sub.add_parser('status')
    p.add_argument('--root', required=True)
    p.add_argument('--experiment', required=True)
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
