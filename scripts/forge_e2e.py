#!/usr/bin/env python3
"""Run real Amplifier coding sessions through Forge, with independent checks.

Explicit opt-in: this invokes the configured paid generative provider and lets
agents edit only disposable workspaces. It never changes global host settings.

This module is used two ways:

- Directly, via its legacy CLI (`prepare|worker|evaluate|batch root [name]`),
  which reproduces the original three-task, two-side (baseline/fast)
  comparison against the installed bundle cache.
- As a library, via `prepare(root, config=...)`, `add_run(...)`,
  `launch_run(...)` and `wait_for_result(...)`, by `scripts/campaign.py`,
  which drives an arbitrary, resumable set of paired runs against a frozen
  candidate source tree instead of the installed cache.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

import forge_workloads
from forge_workloads import SPECS, STARTERS, PUBLIC, evaluate

FORGE = Path.home()/'.agents/skills/amplifier-skill-forge/tools/forge.py'
CACHE = Path.home()/'.amplifier/cache/amplifier-bundle-fast-decisions-703c3edc7c970204'
EVENTS = Path.home()/'.amplifier/fast-decisions/events'
HOST_PYTHON = Path.home()/'.local/share/uv/tools/amplifier/bin/python'
BENCHMARK_BUNDLE_NAME = 'afast-benchmark-run'

PROMPT = ('Read README.md first, then repair the implementation to satisfy its full contract. '
          'Work directly in this workspace without delegating or using the network. '
          'Modify solution.py and add tests if useful, but do not change README.md or existing test_public.py. '
          'Run the tests and explain your fix and validation. Do not inspect files outside this workspace.')

# The upstream orchestrator the "off" (no fast-decisions routing) side runs.
UPSTREAM_LOOP_SOURCE = 'git+https://github.com/microsoft/amplifier-module-loop-streaming@20aac7a9eb26034d230357f6aa6805f27c86df52'

# The decision policy the "active" side runs with, absent overrides.
DEFAULT_DECISION = {
    'backend': 'ollama', 'model': 'qwen3:0.6b', 'timeout_ms': 500,
    'min_probability': .90, 'min_margin': .20, 'max_fast_streak': 3,
    'max_fast_per_turn': 12, 'max_candidates': 12, 'max_state_chars': 2048,
    'allowed_tools': ['fast_workspace'],
}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def hash_files(workspace):
    files={str(p.relative_to(workspace)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(workspace.rglob('*')) if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def tree_sha256(package_dir):
    """Deterministic content hash of a Python source tree.

    MUST match `amplifier_fast_decisions.provenance.tree_sha256` byte for
    byte -- both this script (comparing a side's frozen source before/after
    a run) and the running module (emitting the `fast_decisions:source`
    event this script reads back) hash the same tree, and `source_match`
    only means anything if they agree. Algorithm: walk every `*.py` file
    under `package_dir` (skipping any `__pycache__` directory), sort by
    POSIX-style relative path, and feed sha256, per file in that order: the
    relative path (utf-8), a NUL byte, the raw file bytes, then a trailing
    NUL byte. An unreadable file is skipped, not fatal. Returns None if
    `package_dir` does not exist.
    """
    package_dir = Path(package_dir)
    if not package_dir.exists():
        return None
    candidates = [p for p in package_dir.rglob('*.py') if '__pycache__' not in p.parts]
    candidates.sort(key=lambda p: p.relative_to(package_dir).as_posix())
    digest = hashlib.sha256()
    for p in candidates:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        rel = p.relative_to(package_dir).as_posix()
        digest.update(rel.encode('utf-8'))
        digest.update(b'\0')
        digest.update(data)
        digest.update(b'\0')
    return digest.hexdigest()


def git_sha(path):
    try:
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def available(name):
    try:metadata.version(name);return True
    except metadata.PackageNotFoundError:return False


def _battery_task(task):
    """Look up ``task`` in battery_tasks.TASKS, if that module is importable
    and knows about it. Returns None otherwise (never raises)."""
    try:
        import battery_tasks
    except ImportError:
        return None
    return getattr(battery_tasks, 'TASKS', {}).get(task)


def _task_files(task):
    """Initial workspace files for ``task``: {relpath: text}.

    Delegates to ``forge_workloads.task_files`` (the contract point where a
    task-generalizing sibling module registers new task shapes). Falls back,
    in order, to: the legacy README/solution/test_public trio (for this
    module's own SPECS/STARTERS/PUBLIC tasks), then battery_tasks.TASKS
    directly -- so this module works standalone whether or not
    forge_workloads has been generalized yet.
    """
    fn = getattr(forge_workloads, 'task_files', None)
    if fn is not None:
        return fn(task)
    if task in SPECS:
        return {'README.md': SPECS[task], 'solution.py': STARTERS[task], 'test_public.py': PUBLIC[task]}
    entry = _battery_task(task)
    if entry is not None:
        return entry.files
    raise KeyError(task)


def _task_prompt(task):
    """Per-task prompt override, or None to use the run/manifest default."""
    fn = getattr(forge_workloads, 'task_prompt', None)
    if fn is not None:
        return fn(task)
    if task in SPECS:
        return None
    entry = _battery_task(task)
    return getattr(entry, 'prompt', None) if entry is not None else None


def _task_protected(task):
    """Files the agent must not modify for ``task``."""
    fn = getattr(forge_workloads, 'task_protected', None)
    if fn is not None:
        return fn(task)
    if task in SPECS:
        return ('README.md', 'test_public.py')
    entry = _battery_task(task)
    return tuple(entry.protected) if entry is not None else ('README.md', 'test_public.py')


def _task_kind(task):
    """'code' (evaluator-checked) or 'answer' (message-checked). Legacy SPECS-only
    tasks and any task battery_tasks does not know about are 'code'."""
    try:
        import battery_tasks
    except ImportError:
        return 'code'
    entry = getattr(battery_tasks, 'TASKS', {}).get(task)
    return getattr(entry, 'kind', 'code') if entry is not None else 'code'


def _extract_final_message(session_dir, workspace):
    """Best-effort extraction of the assistant's final response text.

    Primary source: the last ``llm:response`` event's ``data.raw.content``
    ``text``-type blocks (verified against real session events.jsonl files).
    Falls back to the last line of ``.amplifier-final-answer.txt`` in the
    workspace, if present. Returns None when neither source is usable.
    """
    if session_dir is not None:
        events_path = Path(session_dir)/'events.jsonl'
        if events_path.exists():
            last_text = None
            for line in events_path.read_text().splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get('event') != 'llm:response':
                    continue
                raw = (e.get('data') or {}).get('raw') or {}
                content = raw.get('content')
                if not isinstance(content, list):
                    continue
                texts = [b.get('text') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text' and b.get('text')]
                if texts:
                    last_text = '\n'.join(texts)
            if last_text is not None:
                return last_text
    marker = Path(workspace)/'.amplifier-final-answer.txt'
    if marker.exists():
        lines = marker.read_text().splitlines()
        if lines:
            return lines[-1]
    return None


def _default_config():
    tasks = list(SPECS)
    runs = []
    for i, task in enumerate(tasks):
        order = ['baseline', 'fast'] if i % 2 == 0 else ['fast', 'baseline']
        for side in order:
            runs.append({'name': f'{task}-{side}', 'task': task, 'side': side, 'rep': 1, 'attempt': 1, 'block': i, 'seed': None})
    return {
        'runs': runs,
        'sides': {
            'baseline': {'source_root': str(CACHE), 'mode': 'off'},
            'fast': {'source_root': str(CACHE), 'mode': 'active'},
        },
        'upstream_loop_source': UPSTREAM_LOOP_SOURCE,
        'provider': 'anthropic', 'model': 'claude-fable-5-1',
        'limits': {'timeout_seconds': 480, 'max_iterations': 30, 'extended_thinking': True},
        'events_dir': str(EVENTS), 'host_python': str(HOST_PYTHON), 'forge_py': str(FORGE),
        'prompt': PROMPT,
    }


def _side_profile(name, side, task, workspace, config):
    upstream = {'max_iterations': config['limits']['max_iterations'], 'extended_thinking': config['limits']['extended_thinking']}
    source_root = Path(side['source_root'])
    decision = {**DEFAULT_DECISION, **side.get('decision_overrides', {})}
    if side['mode'] == 'active':
        loop_config = {**decision, 'mode': 'active', 'allow_external_state': False, 'events_dir': config['events_dir'], 'upstream': upstream}
        loop = {'module': 'loop-fast-decisions', 'source': (source_root/'modules/loop-fast-decisions').as_uri(), 'config': loop_config}
        hook_config = {**loop_config, 'session_label': f'Forge {task} / active', 'observatory': {'enabled': False}}
        hooks = [{'module': 'hooks-fast-decisions', 'source': (source_root/'modules/hooks-fast-decisions').as_uri(), 'config': hook_config}]
    else:
        loop = {'module': 'loop-streaming', 'source': config.get('upstream_loop_source', UPSTREAM_LOOP_SOURCE), 'config': upstream}
        off_config = {**decision, 'events_dir': config['events_dir'], 'upstream': upstream, 'session_label': f'Forge {task}', 'observatory': {'enabled': False}}
        hooks = [{'module': 'hooks-fast-decisions', 'source': (source_root/'modules/hooks-fast-decisions').as_uri(), 'config': {**off_config, 'mode': 'off'}}]
    # One fixed bundle name for every benchmark profile: Amplifier records each `--bundle` it loads in
    # ~/.amplifier/registry.json keyed by name, so unique per-run names left 80+ stale 'Local' entries.
    # The worker also removes the entry after the run (see _unregister_benchmark_bundle).
    return {'bundle': {'name': BENCHMARK_BUNDLE_NAME, 'version': '0.1.0'}, 'includes': [{'bundle': source_root.as_uri()}],
            'session': {'orchestrator': loop},
            'tools': [{'module': 'tool-fast-workspace', 'source': (source_root/'modules/tool-fast-workspace').as_uri(), 'config': {'root': str(workspace)}}],
            'hooks': hooks}


def _build_workspace(run_dir, task):
    workspace = run_dir/'workspace'
    (workspace/'.amplifier').mkdir(parents=True, exist_ok=True)
    for relpath, content in _task_files(task).items():
        target = workspace/relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (workspace/'.amplifier/settings.local.yaml').write_text('bundle:\n  app: []\n')
    subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
    return workspace


def _build_run(root, run_spec, config, sides):
    name = run_spec['name']
    run = root/name
    run.mkdir(parents=True, exist_ok=True)
    task = run_spec['task']
    workspace = _build_workspace(run, task)
    side = sides[run_spec['side']]
    profile = _side_profile(name, side, task, workspace, config)
    (run/'profile.md').write_text('---\n'+json.dumps(profile, indent=2)+'\n---\n')
    prompt = run_spec.get('prompt') or _task_prompt(task) or config.get('prompt', PROMPT)
    item = {
        'task': task, 'side': run_spec['side'], 'rep': run_spec.get('rep', 1),
        'attempt': run_spec.get('attempt', 1), 'block': run_spec.get('block'), 'seed': run_spec.get('seed'),
        'workspace_hash': hash_files(workspace), 'profile_sha256': hashlib.sha256((run/'profile.md').read_bytes()).hexdigest(),
        'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
    }
    if 'prompt' in run_spec:
        item['prompt'] = run_spec['prompt']
    if 'deadline_seconds' in run_spec:
        item['deadline_seconds'] = run_spec['deadline_seconds']
    return item


def prepare(root, config=None):
    root.mkdir(parents=True, exist_ok=False)
    legacy = config is None
    if legacy:
        config = _default_config()
    sides = {}
    for side_name, side in config['sides'].items():
        source_root = Path(side['source_root'])
        sides[side_name] = {**side, 'source_root': str(source_root),
                             'source_git_sha': git_sha(source_root),
                             'source_tree_sha256': tree_sha256(source_root/'src'/'amplifier_fast_decisions')}
    installed_commit = git_sha(CACHE)
    versions={name:metadata.version(name) for name in ['amplifier-app-cli','amplifier-core','amplifier-foundation','amplifier-module-loop-streaming','amplifier-provider-anthropic'] if available(name)}
    local_digest = None
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            models=json.load(response)['models']
        wanted = config.get('sides', {}).get('fast', {}).get('decision_overrides', {}).get('model', 'qwen3:0.6b')
        match = next((m for m in models if m['name']==wanted), None)
        local_digest = match.get('digest') if match else None
    except Exception:
        local_digest = None
    prompt = config.get('prompt', PROMPT)
    manifest={'schema':'forge-e2e-v1','created_at':datetime.now(timezone.utc).isoformat(),
              'installed_commit':installed_commit,'python':platform.python_version(),
              'hardware':platform.platform(),'packages':versions,'provider':config.get('provider', 'anthropic'),
              'model':config.get('model', 'claude-fable-5-1'),'provider_revision':'unknown',
              'decision_model':DEFAULT_DECISION['model'],'decision_model_digest':local_digest,
              'prompt':prompt,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
              'evaluator_sha256':hashlib.sha256(Path(__file__).with_name('forge_workloads.py').read_bytes()).hexdigest(),
              'sides': sides, 'upstream_loop_source': config.get('upstream_loop_source', UPSTREAM_LOOP_SOURCE),
              'events_dir': config.get('events_dir', str(EVENTS)), 'host_python': config.get('host_python', str(HOST_PYTHON)),
              'forge_py': config.get('forge_py', str(FORGE)), 'task_source': config.get('task_source'),
              'run_order':[],'runs':{},'limits':config.get('limits', {'max_iterations':30,'extended_thinking':True,'timeout_seconds':480})}
    for run_spec in config['runs']:
        manifest['runs'][run_spec['name']] = _build_run(root, run_spec, config, sides)
        manifest['run_order'].append(run_spec['name'])
    # Pairs sharing (task, rep) must start from identical workspace content.
    groups = {}
    for name, item in manifest['runs'].items():
        groups.setdefault((item['task'], item['rep']), []).append((name, item['workspace_hash']))
    for (task, rep), members in groups.items():
        hashes = {h for _, h in members}
        assert len(hashes) == 1, f'Workspace mismatch within task={task} rep={rep}: {members}'
    dump(root/'manifest.json',manifest)
    print(json.dumps({'prepared':str(root),'runs':manifest['run_order'],'installed_commit':installed_commit}))
    return manifest


def add_run(root, run_spec):
    """Append one more run to an already-prepared root (used for retries)."""
    manifest = json.loads((root/'manifest.json').read_text())
    config = {'events_dir': manifest['events_dir'], 'upstream_loop_source': manifest['upstream_loop_source'],
              'limits': manifest['limits'], 'prompt': manifest.get('prompt', PROMPT)}
    manifest['runs'][run_spec['name']] = _build_run(root, run_spec, config, manifest['sides'])
    manifest['run_order'].append(run_spec['name'])
    task, rep = run_spec['task'], run_spec.get('rep', 1)
    hashes = {item['workspace_hash'] for name, item in manifest['runs'].items() if item['task']==task and item['rep']==rep}
    assert len(hashes) == 1, f'Workspace mismatch within task={task} rep={rep}'
    dump(root/'manifest.json', manifest)
    return manifest


def native_summary(session_dir):
    counts=Counter(); usage=Counter(); usage_known=Counter(); durations=[]; tools=[]; complete=False
    path=session_dir/'events.jsonl'
    for line in path.open():
        try:e=json.loads(line)
        except ValueError:continue
        name=e.get('event');d=e.get('data',{});counts[name]+=1
        if name=='llm:response':
            if isinstance(e.get('duration_ms'),(int,float)):durations.append(e['duration_ms'])
            for key in ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','cost_usd']:
                v=d.get('usage',{}).get(key)
                if v is not None:
                    try:usage[key]+=float(v);usage_known[key]+=1
                    except (TypeError,ValueError):pass
        if name=='tool:post':
            result=d.get('result',{})
            tools.append({'tool':d.get('tool_name'),'call_id':d.get('tool_call_id'),
                          'success':result.get('success') if isinstance(result,dict) else None})
        if name=='execution:end':complete=True
    return {'provider_requests':counts['llm:request'],'provider_responses':counts['llm:response'],
            'provider_retries':counts['provider:retry'],'provider_errors':counts['provider:error'],
            'tool_results':len(tools),'tool_names':dict(Counter(t['tool'] for t in tools)),
            'tool_failures_reported':sum(t['success'] is False for t in tools),'execution_completed':complete,
            'provider_response_duration_ms':sum(durations),
            'usage':{k:usage[k] if usage_known[k]==counts['llm:response'] and counts['llm:response'] else None for k in ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','cost_usd']},
            'usage_known_calls':dict(usage_known),'cost_evidence':'provider_reported_estimate_not_billing'}


def effort_summary(session_dir):
    """Counter of (model, thinking_enabled, thinking_budget) over llm:request events."""
    counts = Counter()
    path = session_dir/'events.jsonl'
    for line in path.open():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('event') != 'llm:request':continue
        d = e.get('data', {})
        key = (d.get('model'), d.get('thinking_enabled'), d.get('thinking_budget'))
        counts[key] += 1
    return [{'model': m, 'thinking_enabled': t, 'thinking_budget': b, 'count': n} for (m, t, b), n in counts.items()]


def _source_observed(run):
    receipts = run/'receipts.jsonl'
    if not receipts.exists():
        return None
    for line in receipts.read_text().splitlines():
        try:e = json.loads(line)
        except ValueError:continue
        if e.get('event') == 'fast_decisions:source':
            d = e.get('data', {})
            return {k: d.get(k) for k in ['source_git_sha', 'source_tree_sha256', 'source_kind', 'module']}
    return None


RECEIPT_EXTRACTOR = """
import json, sys
from pathlib import Path
from amplifier_fast_decisions.operations import measure, read_receipts
events_dir, sid, run = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
measured = measure(events_dir, session_id=sid)
rows, _ = read_receipts(events_dir)
ids = {s['session_id'] for s in measured['sessions']}
(run/'receipts.jsonl').write_text(''.join(json.dumps(e)+'\\n' for e in rows if e['session_id'] in ids))
(run/'measurements.json').write_text(json.dumps(measured))
"""


def extract_receipts(source_root, events_dir, sid, run, python=None, timeout=120):
    """Write ``run/receipts.jsonl`` + ``run/measurements.json`` using the SIDE's source and return the measurements.

    Runs in a subprocess with ``PYTHONPATH=<source_root>/src`` so the side under test decides which event
    names and fields survive (its own allowlist), and so the calling process keeps its imported modules.
    Returns None (and writes ``receipts-error.txt``) when extraction fails; the run is still reported.
    """
    env = dict(os.environ, PYTHONPATH=str(Path(source_root)/'src'))
    try:
        proc = subprocess.run([python or sys.executable, '-c', RECEIPT_EXTRACTOR, str(events_dir), sid, str(run)],
                              env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        (run/'receipts-error.txt').write_text('receipt extraction timed out\n')
        return None
    if proc.returncode != 0 or not (run/'measurements.json').exists():
        (run/'receipts-error.txt').write_text(proc.stderr[-4000:])
        return None
    return json.loads((run/'measurements.json').read_text())


def _unregister_benchmark_bundle(name=None):
    """Remove the benchmark profile's registry entry that `amplifier run --bundle` just created (best effort)."""
    try:
        subprocess.run(['amplifier','bundle','remove',name or BENCHMARK_BUNDLE_NAME],capture_output=True,text=True,timeout=120)
    except (OSError,subprocess.TimeoutExpired):
        pass


def _mode_observed(run):
    """Distinct decision modes reported by the run's own receipts (turn_start/requested/routed/source events)."""
    receipts = run/'receipts.jsonl'
    if not receipts.exists():
        return None
    modes = set()
    for line in receipts.read_text().splitlines():
        try:e = json.loads(line)
        except ValueError:continue
        if e.get('event') in {'fast_decisions:turn_start', 'fast_decisions:requested', 'fast_decisions:routed', 'fast_decisions:source'}:
            m = (e.get('data') or {}).get('mode')
            if m is not None:
                modes.add(m)
    return modes


def _interpreter_with_pytest():
    """First of (sys.executable, python3 on PATH) that can `import pytest`, or None.

    Never imports pytest into this process -- each candidate is probed in its
    own subprocess.
    """
    candidates = []
    if sys.executable:
        candidates.append(sys.executable)
    py3 = shutil.which('python3')
    if py3 and py3 not in candidates:
        candidates.append(py3)
    for interp in candidates:
        try:
            proc = subprocess.run([interp, '-c', 'import pytest'], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return interp
    return None


def run_workspace_tests(workspace, timeout=45, targets=None):
    """Run whatever tests exist in `workspace` with the best available runner,
    always in a fresh subprocess (never imports candidate code in-process).

    Prefers pytest (handles both pytest-style and unittest-style test files);
    falls back to `unittest discover` only when no interpreter on this host can
    import pytest. `targets`, if given, restricts the run to those paths/files
    (e.g. ['test_public.py']); otherwise the whole workspace is discovered.

    Returns (passed, runner, summary):
      passed: True (all pass), False (a failure/timeout/error), or None (no
              tests were collected -- not applicable, not a failure).
      runner: 'pytest' or 'unittest'.
      summary: tail of combined stdout+stderr, for diagnostics.
    """
    workspace = Path(workspace)
    interp = _interpreter_with_pytest()
    if interp is not None:
        argv = [interp, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *(targets or [])]
        # Auto-loaded third-party pytest plugins from this host's environment (installed
        # via setuptools entrypoints, e.g. framework-specific pytest plugins) can crash on
        # import when the candidate workspace's PYTHONPATH doesn't include their deps --
        # that is not a test failure, so run pytest in its bare, plugin-autoload-free mode.
        env = {**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
        try:
            proc = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return False, 'pytest', 'pytest timed out'
        summary = ((getattr(proc, 'stdout', None) or '') + (getattr(proc, 'stderr', None) or ''))[-4000:]
        if proc.returncode == 0:
            return True, 'pytest', summary
        if proc.returncode == 5:  # no tests collected
            return None, 'pytest', summary
        return False, 'pytest', summary
    unittest_argv = [sys.executable, '-m', 'unittest'] + (['-v', *targets] if targets else ['discover', '-v'])
    try:
        proc = subprocess.run(unittest_argv, cwd=workspace, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, 'unittest', 'unittest timed out'
    summary = ((getattr(proc, 'stdout', None) or '') + (getattr(proc, 'stderr', None) or ''))[-4000:]
    if proc.returncode == 5:  # NO TESTS RAN (Python 3.12+)
        return None, 'unittest', summary
    return proc.returncode == 0, 'unittest', summary


def _ensure_task_source_registered(manifest):
    """Register a manifest's `task_source` (if any) with forge_workloads so
    task_files/task_prompt/task_protected/evaluate can resolve tasks from it
    in THIS process. Every entry point that resolves a task from a bare
    manifest read (worker(), and the `evaluate` CLI subcommand) is a fresh
    process and must call this before touching forge_workloads' task
    accessors -- see forge_workloads.register_source."""
    task_source = manifest.get('task_source')
    if task_source:
        forge_workloads.register_source(task_source['kind'],
                                         **{k: v for k, v in task_source.items() if k != 'kind'})


def worker(root,name):
    manifest=json.loads((root/'manifest.json').read_text());_ensure_task_source_registered(manifest);run=root/name;workspace=run/'workspace';item=manifest['runs'][name]
    if hash_files(workspace)!=item['workspace_hash']:raise RuntimeError('Starting workspace changed')
    side = manifest['sides'][item['side']]
    source_root = Path(side['source_root'])
    if tree_sha256(source_root/'src'/'amplifier_fast_decisions') != side['source_tree_sha256']:
        raise RuntimeError('Source changed during the experiment')
    task = item['task']
    prompt = item.get('prompt')
    if prompt is None:
        if task not in SPECS:
            # A battery task (anything not in the legacy SPECS trio) must never silently
            # fall back to the generic legacy prompt -- that silently sends the wrong
            # instructions to the agent (see: amplifier runs getting the README-repair
            # boilerplate instead of their task-specific prompt).
            raise SystemExit(f'worker: run {name!r} (task={task!r}) has no prompt recorded; '
                              'refusing to fall back to the generic legacy prompt for a battery task')
        prompt = manifest['prompt']
    expected_prompt_sha256 = item.get('prompt_sha256')
    if expected_prompt_sha256 is not None:
        actual_prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
        if actual_prompt_sha256 != expected_prompt_sha256:
            raise SystemExit(f'worker: run {name!r} prompt does not match the preregistered '
                              f'prompt_sha256 (expected {expected_prompt_sha256}, got '
                              f'{actual_prompt_sha256}); refusing to launch amplifier')
    deadline_seconds = item.get('deadline_seconds') or manifest['limits']['timeout_seconds']
    warm=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps({'model':'qwen3:0.6b','stream':False,'keep_alive':'20m','options':{'num_ctx':4096}}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(warm,timeout=60) as response:json.load(response)
    slug=str(workspace.resolve()).replace('/','-').replace('\\','-').replace(':','')
    sessions=Path.home()/'.amplifier/projects'/slug/'sessions'
    before=set(sessions.iterdir()) if sessions.exists() else set()
    env=dict(os.environ,AFAST_OBSERVATORY='off')
    env['PYTHONPATH'] = str(source_root/'src')
    command=['amplifier','run','--bundle',(run/'profile.md').as_uri(),'--mode','single','--provider',manifest['provider'],'--model',manifest['model'],'--output-format','json',prompt]
    started_at=datetime.now(timezone.utc).isoformat();started=time.perf_counter()
    process=subprocess.Popen(command,cwd=workspace,env=env)
    dump(run/'running.json',{'started_at':started_at,'name':name,'controller_pid':os.getpid(),'pid':process.pid,
                              'attempt':item.get('attempt',1),'deadline_seconds':deadline_seconds,
                              'tty':sys.stdout.isatty()})
    print('FORGE_E2E_STARTED '+name,flush=True)
    timed_out=False
    try:code=process.wait(timeout=deadline_seconds)
    except subprocess.TimeoutExpired:
        timed_out=True;process.terminate()
        try:code=process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();code=process.wait()
    elapsed=(time.perf_counter()-started)*1000
    ended_at=datetime.now(timezone.utc).isoformat()
    # events.jsonl exists during execution; metadata.json may only be written on
    # orderly shutdown. Preserve native evidence even for deadline failures.
    found=[p for p in sessions.iterdir() if p not in before and (p/'events.jsonl').exists()] if sessions.exists() else []
    sid=found[0].name if len(found)==1 else None
    native=native_summary(found[0]) if len(found)==1 else None
    effort=effort_summary(found[0]) if len(found)==1 else []
    # Extract receipts with the side's own source: the installed package's allowlist would silently drop
    # event names/fields that only the side under test emits (observed in HC00: no source event, no observation stats).
    # Done in a subprocess with PYTHONPATH=<side>/src so this process never swaps already-imported modules
    # (purging sys.modules here broke unrelated tests that patch amplifier_fast_decisions.operations).
    events_dir = Path(manifest.get('events_dir', str(EVENTS)))
    measured = extract_receipts(source_root, events_dir, sid, run) if sid else None
    kind = _task_kind(item['task'])
    if kind == 'answer':
        final_message = _extract_final_message(found[0] if len(found)==1 else None, workspace)
        try:
            import battery_tasks
            quality = battery_tasks.check_answer(battery_tasks.TASKS[item['task']], final_message)
        except Exception:
            quality = {'checks':0,'passed':0,'failed':1,'failure_labels':['check_answer_failed']}
        public_ok = None
        suite_ok = None
        workspace_tests_runner = None
    else:
        final_message = None
        # Execute the independent evaluator in its own process with a deadline.
        try:
            test=subprocess.run([sys.executable,str(Path(__file__).resolve()),'evaluate',str(root),name],capture_output=True,text=True,timeout=45)
            quality=json.loads(test.stdout)
        except (ValueError,subprocess.TimeoutExpired):
            quality={'checks':0,'passed':0,'failed':1,'failure_labels':['evaluator_failed_or_timed_out']}
        if (workspace/'test_public.py').exists():
            public_ok, _public_runner, _public_summary = run_workspace_tests(workspace, targets=['test_public.py'])
        else:
            public_ok=None
        suite_ok, workspace_tests_runner, _suite_summary = run_workspace_tests(workspace)
    protected = _task_protected(item['task'])
    files = _task_files(item['task'])
    unchanged={f:(workspace/f).exists() and (workspace/f).read_text()==files.get(f,'') for f in protected}
    source_observed = _source_observed(run)
    source_expected = {'git_sha': side['source_git_sha'], 'tree_sha256': side['source_tree_sha256']}
    if source_observed is None:
        source_match = None
    else:
        source_match = (source_observed.get('source_git_sha') == source_expected['git_sha']
                         and source_observed.get('source_tree_sha256') == source_expected['tree_sha256'])
    mode_observed = _mode_observed(run)
    mode_match = None if mode_observed is None else (
        (mode_observed == {'active'}) if side['mode'] == 'active' else mode_observed <= {'off'})
    infrastructure_failure = sid is None or code is None
    harness = 'amplifier-fd' if side['mode'] == 'active' else 'amplifier-plain'
    model = next((e['model'] for e in effort if e.get('model')), None)
    result={'name':name,'task':item['task'],'side':item['side'],'session_id':sid,'exit_code':code,'timed_out':timed_out,
            'wall_time_ms':elapsed,'native':native,'measurements':measured,'quality':quality,'public_tests_passed':public_ok,
            'workspace_tests_passed':suite_ok,'workspace_tests_runner':workspace_tests_runner,'protected_files_unchanged':unchanged,
            'final_solution_sha256':hashlib.sha256((workspace/'solution.py').read_bytes()).hexdigest() if (workspace/'solution.py').exists() else None,
            'attempt': item.get('attempt', 1), 'deadline_seconds': deadline_seconds,
            'started_at': started_at, 'ended_at': ended_at,
            'source_expected': source_expected, 'source_observed': source_observed, 'source_match': source_match,
            'mode_expected': side['mode'], 'mode_observed': sorted(mode_observed) if mode_observed is not None else None, 'mode_match': mode_match,
            'retry_count': native['provider_retries'] if native else None, 'effort_receipts': effort,
            'new_session_dirs': len(found), 'infrastructure_failure': infrastructure_failure,
            'harness': harness, 'model': model, 'final_message': final_message[:4000] if isinstance(final_message, str) else final_message}
    outcome_passed = code==0 and not timed_out and quality['failed']==0 and all(unchanged.values())
    if public_ok is not None:
        outcome_passed = outcome_passed and public_ok
    if suite_ok is not None:
        outcome_passed = outcome_passed and suite_ok
    result['outcome_passed']=outcome_passed
    dump(run/'result.json',result)
    _unregister_benchmark_bundle()
    print('FORGE_E2E_FINISHED '+json.dumps({'name':name,'outcome':result['outcome_passed'],'wall_ms':round(elapsed),'checks':quality,'session_id':sid}),flush=True)
    return 0 if result['outcome_passed'] else 1


def launch_run(root, name, forge_module=None):
    """Hand one run's worker command to Forge; return its observation dict.

    A Forge observation deadline is reported as an MCP error (SystemExit) but
    the launched process is explicitly kept alive -- that is not completion.
    """
    manifest=json.loads((root/'manifest.json').read_text())
    run=root/name
    if forge_module is None:
        forge_py = Path(manifest.get('forge_py', str(FORGE))).expanduser()
        sys.path.insert(0, str(forge_py.parent))
        import forge as forge_module
    host_python = manifest.get('host_python', str(HOST_PYTHON))
    cmd=shlex.join([str(host_python),str(Path(__file__).resolve()),'worker',str(root),name])
    # The Forge daemon's shell does not carry the user's API keys; source ~/.amplifier/keys.env (0600) into the
    # worker's environment so external decision backends (e.g. TYPESAFE_API_KEY) work. Values never appear in logs.
    cmd='set -a; . ~/.amplifier/keys.env 2>/dev/null; set +a; '+cmd
    for attempt in (1, 2):
        try:
            result=forge_module.call('run_command',{'command':'/bin/zsh','args':['-lc',cmd],
                'cwd':str(run/'workspace'),'timeoutMs':60000})
            break
        except SystemExit as exc:
            text=str(exc).removeprefix('forge: ')
            try:result=json.loads(text)
            except ValueError:
                # Forge refuses new terminals once exited ones pile up. Reap only OUR exited worker
                # terminals (never live or unowned sessions) and retry once; otherwise fail loud.
                if 'Maximum sessions' in text and attempt == 1 and reap_exited_worker_terminals(forge_module, root):
                    continue
                raise RuntimeError('forge launch failed: '+text) from None
            if result.get('timeout') is not True:
                raise RuntimeError('forge launch failed: '+text) from None
            break
    (run/'forge-output.txt').write_text(result.pop('output',''))
    dump(run/'forge-observation.json',result)
    return result


def reap_exited_worker_terminals(forge_module, root):
    """Close Forge terminals that have EXITED and were launched by this runner for ``root``.

    Live sessions and sessions that do not reference this campaign root are never touched.
    Returns True when at least one terminal was closed.
    """
    try:
        sessions=forge_module.call('list_terminals',{})
    except SystemExit:
        return False
    if isinstance(sessions,dict):
        sessions=sessions.get('sessions') or sessions.get('terminals') or []
    closed=0
    for s in sessions:
        if not isinstance(s,dict) or s.get('status')!='exited':
            continue
        if str(root) not in (s.get('name') or '')+' '+(s.get('cwd') or ''):
            continue
        try:forge_module.call('close_terminal',{'id':s['id']});closed+=1
        except SystemExit:pass
    return closed>0


def close_worker_terminal(root, name, forge_module=None):
    """Close the terminal this runner opened for ``name`` (recorded in forge-observation.json), if any."""
    obs=root/name/'forge-observation.json'
    if not obs.exists():
        return False
    try:sid=json.loads(obs.read_text()).get('sessionId')
    except ValueError:return False
    if not sid:
        return False
    if forge_module is None:
        manifest=json.loads((root/'manifest.json').read_text())
        forge_py=Path(manifest.get('forge_py', str(FORGE))).expanduser()
        sys.path.insert(0,str(forge_py.parent))
        import forge as forge_module
    try:forge_module.call('close_terminal',{'id':sid});return True
    except SystemExit:return False


def wait_for_result(root, name, timeout_seconds):
    """Poll for result.json; bail out early if the launching controller died."""
    run = root/name
    deadline = time.monotonic()+timeout_seconds
    dead_since = None
    while True:
        if (run/'result.json').exists():
            return True
        if time.monotonic() >= deadline:
            return (run/'result.json').exists()
        running = run/'running.json'
        if running.exists():
            try:
                pid = json.loads(running.read_text()).get('controller_pid')
            except ValueError:
                pid = None
            if pid is not None:
                try:
                    os.kill(pid, 0)
                    dead_since = None
                except ProcessLookupError:
                    if dead_since is None:
                        dead_since = time.monotonic()
                    elif time.monotonic()-dead_since >= 10:
                        return (run/'result.json').exists()
                except OSError:
                    pass
        time.sleep(2)


def batch(root):
    manifest=json.loads((root/'manifest.json').read_text())
    wait_seconds = manifest['limits']['timeout_seconds'] + 180
    for name in manifest['run_order']:
        run = root/name
        if (run/'result.json').exists():continue
        print('LAUNCH '+name,flush=True)
        observation = launch_run(root, name)
        ok = wait_for_result(root, name, wait_seconds)
        if not ok:
            raise RuntimeError('Worker did not produce a result; inspect the owned Forge session before proceeding')
        # Only close our own completed terminal. Keep failed experiments in the report.
        if observation.get('sessionId'):
            forge_py = Path(manifest.get('forge_py', str(FORGE))).expanduser()
            sys.path.insert(0, str(forge_py.parent))
            import forge
            try:forge.call('close_terminal',{'id':observation['sessionId']})
            except SystemExit:pass
        outcome=json.loads((run/'result.json').read_text())
        print('COLLECT '+name+' '+str(outcome['outcome_passed']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','worker','evaluate','batch']);parser.add_argument('root',type=Path);parser.add_argument('name',nargs='?');args=parser.parse_args();root=args.root.expanduser().resolve()
    if args.command=='prepare':prepare(root)
    elif args.command=='worker':sys.exit(worker(root,args.name))
    elif args.command=='evaluate':
        _manifest=json.loads((root/'manifest.json').read_text());_ensure_task_source_registered(_manifest)
        print(json.dumps(evaluate(_manifest['runs'][args.name]['task'],root/args.name/'workspace')))
    else:batch(root)
