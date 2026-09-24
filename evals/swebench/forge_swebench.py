#!/usr/bin/env python3
"""SWE-bench Verified through Forge: plain Amplifier vs the orchestrator-primary bundle.

A lighter path than the DTU scaffold in this directory (run.sh): every agent
run is an ordinary `amplifier run` in a real checkout of the instance's repo at
its base commit, driven in its own Forge PTY. The patch is `git diff` against
the base commit. Grading is the official `swebench.harness.run_evaluation`
(swebench 4.x, Docker), so "resolved" means exactly what it means on the SWE-bench
leaderboard.

Arms (profiles built by scripts/forge_e2e.py, same as the S1/S2 battery):
  plain          foundation + loop-streaming, --model claude-fable-5-1
  plain-sonnet   same, --model claude-sonnet-5   (model-confound control)
  orch-primary   the bundle root composed as shipped (orchestrator swap,
                 routing-only default), --model claude-fable-5-1

Usage:
  forge_swebench.py prepare --root R --instances ID[,ID...] --candidate-sha SHA \\
      --baseline-source DIR [--arms plain,plain-sonnet,orch-primary] [--reps 1] [--seed N]
  forge_swebench.py run    --root R [--parallel 3]
  forge_swebench.py grade  --root R [--swe-python PATH]
  forge_swebench.py report --root R

Explicit opt-in: `run` spends provider money, `grade` builds Docker images.
Run output (prompts, patches, traces) stays under --root; never commit it.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import shlex
import subprocess
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT/'scripts'))
import forge_e2e  # noqa: E402

DATASET = 'princeton-nlp/SWE-bench_Verified'
DEFAULT_SWE_PYTHON = Path.home()/'dev/afast-ev/swe-venv/bin/python'
MIRRORS = Path.home()/'dev/afast-ev/swe-mirrors'
ARMS = {
    'plain': {'model': 'claude-fable-5-1', 'composed': False},
    'plain-sonnet': {'model': 'claude-sonnet-5', 'composed': False},
    'orch-primary': {'model': 'claude-fable-5-1', 'composed': True},
}
PROMPT = """You are working in a git checkout of the {repo} repository (your current directory).
Resolve the GitHub issue below by editing the repository's source code.

The project's Python environment (dependencies installed, repo mounted at /testbed) runs in Docker.
Run any Python/test command through the helper, from this directory:  .swe/run <command>
  e.g.  .swe/run python -m pytest path/to/test_file.py -x -q
Do not install dependencies or search outside this directory for an environment.

Rules:
- Work directly in this checkout; do not delegate to sub-agents and do not use the network.
- Make the minimal, correct source change that resolves the issue. You may add or run tests to check your work,
  but the fix must be in the library source.
- Do not commit; leave your changes in the working tree.
- When done, reply with a short summary of the change.

<issue>
{problem_statement}
</issue>
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def _git(*args, cwd=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, check=check, capture_output=True, text=True)


def _load_instances(ids, swe_python):
    script = (
        "import json,sys\n"
        "from datasets import load_dataset\n"
        f"ds=load_dataset({DATASET!r}, split='test')\n"
        "want=set(sys.argv[1].split(','))\n"
        "keep=['instance_id','repo','base_commit','problem_statement','version','FAIL_TO_PASS','PASS_TO_PASS']\n"
        "print(json.dumps([{k:r[k] for k in keep} for r in ds if r['instance_id'] in want]))\n"
    )
    out = subprocess.run([str(swe_python), '-c', script, ','.join(ids)], check=True, capture_output=True, text=True)
    rows = {r['instance_id']: r for r in json.loads(out.stdout)}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise SystemExit(f'instances not in {DATASET}: {missing}')
    return [rows[i] for i in ids]


def _mirror(repo):
    MIRRORS.mkdir(parents=True, exist_ok=True)
    path = MIRRORS/(repo.replace('/', '__') + '.git')
    if not path.exists():
        _git('clone', '--mirror', '--quiet', f'https://github.com/{repo}.git', str(path))
    return path


def _build_workspace(run_dir, instance):
    workspace = run_dir/'workspace'
    _git('clone', '--quiet', '--shared', '--no-checkout', str(_mirror(instance['repo'])), str(workspace))
    _git('checkout', '--quiet', '--detach', instance['base_commit'], cwd=workspace)
    _git('config', 'user.email', 'bench@example.invalid', cwd=workspace)
    _git('config', 'user.name', 'bench', cwd=workspace)
    # Same isolation as forge_e2e._build_workspace: no user app bundles.
    (workspace/'.amplifier').mkdir(exist_ok=True)
    (workspace/'.amplifier/settings.local.yaml').write_text('bundle:\n  app: []\n')
    exclude = workspace/'.git/info/exclude'
    exclude.write_text(exclude.read_text() + '\n.amplifier/\n.swe/\n')
    helper = workspace/'.swe'/'run'
    helper.parent.mkdir()
    helper.write_text(
        '#!/bin/sh\n'
        '# Runs a command in the SWE-bench instance image (the grading environment), with this\n'
        '# checkout mounted at /testbed. Generated by evals/swebench/forge_swebench.py.\n'
        'cd "$(dirname "$0")/.." || exit 1\n'
        f'exec docker run --rm --platform linux/amd64 -v "$PWD":/testbed -w /testbed {instance_image(instance)} '
        'bash -lc \'source /opt/miniconda3/bin/activate testbed && '
        'if [ $# -eq 1 ]; then eval "$1"; else "$@"; fi\' _ "$@"\n')
    helper.chmod(0o755)
    return workspace


def instance_image(instance):
    """The official SWE-bench evaluation image for an instance (x86_64; runs emulated on arm64)."""
    iid = instance['instance_id'].replace('__', '_1776_').lower()
    return f'swebench/sweb.eval.x86_64.{iid}:latest'


def _pull_image(instance):
    subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', '-q', instance_image(instance)],
                   check=True, capture_output=True, text=True)


def cmd_prepare(args):
    root = Path(args.root).expanduser().resolve()
    if (root/'manifest.json').exists():
        raise SystemExit(f'{root} already prepared')
    root.mkdir(parents=True, exist_ok=True)
    ids = [i.strip() for i in args.instances.split(',') if i.strip()]
    arms = [a.strip() for a in args.arms.split(',') if a.strip()]
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f'unknown arm {arm!r}; choose from {sorted(ARMS)}')
    instances = _load_instances(ids, args.swe_python)
    _dump(root/'instances.json', instances)
    for inst in instances:
        _pull_image(inst)  # the agents' environment and the grader's; pulled before any timed run

    source = root/'source'
    if not source.exists():
        _git('-C', str(REPO_ROOT), 'worktree', 'add', '--detach', str(source), args.candidate_sha)
    baseline = Path(args.baseline_source).expanduser().resolve()

    rng = random.Random(args.seed)
    schedule = []
    for rep in range(1, args.reps + 1):
        block = list(instances)
        rng.shuffle(block)
        for inst in block:
            order = list(arms)
            rng.shuffle(order)
            schedule += [(inst, arm, rep) for arm in order]

    limits = {'max_iterations': args.max_iterations, 'extended_thinking': True}
    runs = {}
    for inst, arm, rep in schedule:
        name = forge_e2e._slug(f"{inst['instance_id']}__{arm}__r{rep}")
        run_dir = root/'runs'/name
        run_dir.mkdir(parents=True)
        workspace = _build_workspace(run_dir, inst)
        spec = ARMS[arm]
        if spec['composed']:
            side = {'source_root': str(source), 'mode': 'active', 'composition': 'composed', 'decision_overrides': {}}
        else:
            side = {'source_root': str(baseline), 'mode': 'off'}
        config = {'limits': limits, 'events_dir': str(run_dir/'events'),
                  'upstream_loop_source': forge_e2e.UPSTREAM_LOOP_SOURCE}
        profile = forge_e2e._side_profile(name, side, inst['instance_id'], workspace, config)
        forge_e2e._assert_bundle_uri_safe(run_dir/'profile.md')
        (run_dir/'profile.md').write_text('---\n' + json.dumps(profile, indent=2) + '\n---\n')
        if spec['composed']:
            effective = forge_e2e.composed_effective_config(source, profile['session']['orchestrator']['config'])
            if effective is not None:
                _dump(run_dir/'effective-loop-config.json', effective)
        (run_dir/'prompt.txt').write_text(PROMPT.format(repo=inst['repo'], problem_statement=inst['problem_statement']))
        runs[name] = {'instance_id': inst['instance_id'], 'repo': inst['repo'], 'base_commit': inst['base_commit'],
                      'arm': arm, 'rep': rep, 'model': spec['model']}
    manifest = {'schema': 'forge-swebench-v1', 'created_at': _now(), 'dataset': DATASET,
                'candidate_sha': _git('-C', str(source), 'rev-parse', 'HEAD').stdout.strip(),
                'baseline_source': str(baseline), 'baseline_sha': forge_e2e.git_sha(baseline),
                'upstream_loop_source': forge_e2e.UPSTREAM_LOOP_SOURCE, 'arms': {a: ARMS[a] for a in arms},
                'seed': args.seed, 'reps': args.reps, 'deadline_seconds': args.deadline_seconds,
                'limits': limits, 'settings_sha256': _settings_sha256(),
                'run_order': list(runs), 'runs': runs}
    _dump(root/'manifest.json', manifest)
    print(json.dumps({'prepared': str(root), 'runs': len(runs), 'instances': ids, 'arms': arms}))


def _project_sessions_dir(workspace):
    slug = str(Path(workspace).resolve()).replace('\\', '-').replace('/', '-').replace(':', '')
    return Path.home()/'.amplifier/projects'/slug/'sessions'


_launch_lock = threading.Lock()
SETTINGS = Path.home()/'.amplifier'/'settings.yaml'


def _settings_sha256():
    import hashlib
    return hashlib.sha256(SETTINGS.read_bytes()).hexdigest() if SETTINGS.exists() else None


def _capture_patch(workspace, base_commit, index_path):
    """`git diff` of the working tree (tracked + untracked, minus excludes) against the
    base commit, through a private index file: never touches the workspace's own index,
    so a stale .git/index.lock left by the agent cannot silently yield an empty patch."""
    env = dict(os.environ, GIT_INDEX_FILE=str(index_path))
    for cmd in (['read-tree', base_commit], ['add', '-A']):
        proc = subprocess.run(['git', *cmd], cwd=workspace, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f'git {cmd[0]} failed: {proc.stderr.strip()[:300]}')
    return subprocess.run(['git', 'diff', '--cached', base_commit], cwd=workspace, env=env,
                          check=True, capture_output=True, text=True).stdout


def cmd_agent(args):
    """Worker: runs ONE agent session to completion inside a Forge PTY, then writes result.json.

    Forge's run_command observation returns after ~60 s while keeping the process alive
    (forge_e2e.launch_run relies on the same behavior), so completion is signalled by
    result.json, never by the observation."""
    root = Path(args.root).resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    name = args.name
    item = manifest['runs'][name]
    run_dir = root/'runs'/name
    workspace = run_dir/'workspace'
    sessions = _project_sessions_dir(workspace)
    before = set(sessions.iterdir()) if sessions.exists() else set()
    deadline = manifest['deadline_seconds']
    argv = ['amplifier', 'run', '--bundle', (run_dir/'profile.md').as_uri(), '--mode', 'single',
            '--provider', 'anthropic', '--model', item['model'], '--output-format', 'json',
            (run_dir/'prompt.txt').read_text()]
    started_at, t0 = _now(), time.perf_counter()
    timed_out, exit_code, notes = False, None, []
    with open(run_dir/'amplifier-output.json', 'w') as out, open(run_dir/'amplifier-stderr.txt', 'w') as err:
        proc = subprocess.Popen(argv, cwd=workspace, stdout=out, stderr=err, start_new_session=True)
        try:
            exit_code = proc.wait(timeout=deadline)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()
            try:
                exit_code = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait()
    wall_ms = (time.perf_counter() - t0) * 1000
    try:
        patch = _capture_patch(workspace, item['base_commit'], run_dir/'patch.index')
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        patch = ''
        notes.append(f'patch_capture_failed:{exc}'[:300])
    (run_dir/'patch.diff').write_text(patch)
    found = [p for p in sessions.iterdir() if p not in before and (p/'events.jsonl').exists()] if sessions.exists() else []
    native = forge_e2e.native_summary(found[0]) if len(found) == 1 else None
    effort = forge_e2e.effort_summary(found[0]) if len(found) == 1 else []
    exec_ms = _exec_time_ms(found[0]/'events.jsonl') if len(found) == 1 else None
    if len(found) != 1:
        notes.append(f'session_dirs_found:{len(found)}')
    result = {'name': name, **item, 'started_at': started_at, 'ended_at': _now(), 'wall_time_ms': wall_ms,
              'exec_time_ms': exec_ms, 'exit_code': exit_code, 'timed_out': timed_out,
              'session_id': found[0].name if len(found) == 1 else None, 'native': native,
              'models_served': effort, 'cost_usd': ((native or {}).get('usage') or {}).get('cost_usd'),
              'patch_bytes': len(patch.encode()), 'empty_patch': not patch.strip(),
              'infrastructure_failure': any(n.startswith(('patch_capture_failed', 'session_dirs_found')) for n in notes),
              'notes': notes}
    _dump(run_dir/'result.json', result)


def _run_one(root, manifest, name, forge):
    run_dir = root/'runs'/name
    # STUDY-DESIGN.md 18.5: a mid-campaign change to the user's Amplifier settings
    # (providers, overrides, modules) invalidates every later run; stop, don't continue.
    if manifest.get('settings_sha256') and _settings_sha256() != manifest['settings_sha256']:
        raise SystemExit(f'{SETTINGS} changed since prepare; refusing to launch {name} (STUDY-DESIGN.md 18.5)')
    cmd = shlex.join([sys.executable, str(Path(__file__).resolve()), 'agent', '--root', str(root), '--name', name])
    cmd = 'set -a; . ~/.amplifier/keys.env 2>/dev/null; set +a; ' + cmd
    with _launch_lock:  # same spacing discipline as forge_e2e launches
        forge_e2e._wait_for_launch_spacing(time.sleep, time.monotonic)
    try:
        obs = forge.call('run_command', {'command': '/bin/zsh', 'args': ['-lc', cmd],
                                         'cwd': str(run_dir/'workspace'), 'timeoutMs': 60000})
    except SystemExit as exc:  # the ~60 s observation deadline: the worker keeps running
        text = str(exc).removeprefix('forge: ')
        try:
            obs = json.loads(text)
        except ValueError:
            obs = {'launch_error': text[:500]}
    _dump(run_dir/'forge-observation.json', {k: v for k, v in (obs or {}).items() if k != 'output'})
    deadline = time.monotonic() + manifest['deadline_seconds'] + 180
    while not (run_dir/'result.json').exists() and time.monotonic() < deadline:
        if (obs or {}).get('launch_error'):
            break
        time.sleep(5)
    if not (run_dir/'result.json').exists():
        _dump(run_dir/'result.json', {'name': name, **manifest['runs'][name], 'infrastructure_failure': True,
                                      'timed_out': True, 'exec_time_ms': None, 'wall_time_ms': None,
                                      'cost_usd': None, 'patch_bytes': 0, 'empty_patch': True,
                                      'notes': ['worker_never_reported', str((obs or {}).get('launch_error', ''))[:300]]})
    if (obs or {}).get('sessionId'):
        try:
            forge.call('close_terminal', {'id': obs['sessionId']})
        except SystemExit:
            pass
    return json.loads((run_dir/'result.json').read_text())


def _exec_time_ms(events_path):
    first = last = None
    for line in events_path.open():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind, ts = ev.get('event'), ev.get('ts') or ev.get('timestamp')
        if not isinstance(ts, str):
            continue
        try:
            t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            continue
        if kind == 'llm:request' and first is None:
            first = t
        elif kind == 'llm:response':
            last = t
    if first is None or last is None:
        return None
    return max(0.0, (last - first).total_seconds() * 1000)


def cmd_run(args):
    root = Path(args.root).expanduser().resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    sys.path.insert(0, str(forge_e2e.FORGE.parent))
    import forge  # type: ignore  # the Forge skill's stdlib helper (same one battery.py loads)
    forge_e2e.forge_self_heal({'forge_py': str(forge_e2e.FORGE)})
    pending = [n for n in manifest['run_order'] if not (root/'runs'/n/'result.json').exists()]
    print(json.dumps({'pending': len(pending), 'parallel': args.parallel}), flush=True)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for result in pool.map(lambda n: _run_one(root, manifest, n, forge), pending):
            print(json.dumps({k: result.get(k) for k in ('name', 'exit_code', 'timed_out', 'wall_time_ms',
                                                           'exec_time_ms', 'cost_usd', 'patch_bytes',
                                                           'infrastructure_failure')}), flush=True)


def cmd_grade(args):
    root = Path(args.root).expanduser().resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    grading = root/'grading'
    grading.mkdir(exist_ok=True)
    by_run_id = defaultdict(list)
    for name, item in manifest['runs'].items():
        result_path = root/'runs'/name/'result.json'
        if not result_path.exists():
            continue
        patch = (root/'runs'/name/'patch.diff').read_text()
        by_run_id[f"{item['arm']}-r{item['rep']}"].append(
            {'instance_id': item['instance_id'], 'model_name_or_path': item['arm'], 'model_patch': patch})
    for run_id, preds in sorted(by_run_id.items()):
        report = grading/f"{preds[0]['model_name_or_path']}.{run_id}.json"
        if report.exists():
            continue
        preds_path = grading/f'{run_id}.jsonl'
        preds_path.write_text(''.join(json.dumps(p) + '\n' for p in preds))
        cmd = [str(args.swe_python), '-m', 'swebench.harness.run_evaluation', '--dataset_name', DATASET,
               '--split', 'test', '--predictions_path', str(preds_path), '--run_id', run_id,
               '--max_workers', str(args.max_workers), '--timeout', str(args.timeout),
               '--cache_level', 'instance',  # keep the instance images: they are also the agents' environment
               '--instance_ids', *[p['instance_id'] for p in preds]]
        print('+', ' '.join(cmd), flush=True)
        subprocess.run(cmd, cwd=grading, check=False)


def _report_rows(root, manifest):
    grading = root/'grading'
    resolved = {}
    for report in grading.glob('*.json'):
        try:
            data = json.loads(report.read_text())
        except ValueError:
            continue
        if 'resolved_ids' not in data:
            continue
        arm, run_id = report.name.split('.', 1)[0], report.name.split('.', 1)[1].rsplit('.json', 1)[0]
        rep = int(run_id.rsplit('-r', 1)[1])
        for iid in data.get('submitted_ids', []):
            resolved[(iid, arm, rep)] = iid in set(data['resolved_ids'])
    rows = []
    for name, item in manifest['runs'].items():
        path = root/'runs'/name/'result.json'
        if not path.exists():
            continue
        r = json.loads(path.read_text())
        r['resolved'] = resolved.get((item['instance_id'], item['arm'], item['rep']))
        rows.append(r)
    return rows


def _geomean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else None


def cmd_report(args):
    root = Path(args.root).expanduser().resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    rows = _report_rows(root, manifest)
    arms = list(manifest['arms'])
    by = defaultdict(dict)
    for r in rows:
        by[(r['instance_id'], r['rep'])][r['arm']] = r
    summary = {}
    for arm in arms:
        mine = [r for r in rows if r['arm'] == arm]
        summary[arm] = {
            'runs': len(mine),
            'resolved': sum(1 for r in mine if r['resolved']),
            'graded': sum(1 for r in mine if r['resolved'] is not None),
            'empty_patches': sum(1 for r in mine if r['empty_patch']),
            'infra_failures': sum(1 for r in mine if r['infrastructure_failure']),
            'timeouts': sum(1 for r in mine if r['timed_out']),
            'median_exec_s': _median([r['exec_time_ms'] / 1000 for r in mine if r.get('exec_time_ms')]),
            'median_wall_s': _median([r['wall_time_ms'] / 1000 for r in mine if r.get('wall_time_ms')]),
            'total_cost_usd': round(sum(r['cost_usd'] or 0 for r in mine), 2),
        }
    paired = {}
    for arm in arms:
        if arm == 'plain':
            continue
        time_ratios, cost_ratios = [], []
        for pair in by.values():
            if 'plain' in pair and arm in pair:
                a, b = pair['plain'], pair[arm]
                if a.get('exec_time_ms') and b.get('exec_time_ms'):
                    time_ratios.append(b['exec_time_ms'] / a['exec_time_ms'])
                if a.get('cost_usd') and b.get('cost_usd'):
                    cost_ratios.append(b['cost_usd'] / a['cost_usd'])
        paired[f'{arm}_vs_plain'] = {'pairs': len(time_ratios), 'geomean_exec_time_ratio': _round(_geomean(time_ratios)),
                                     'geomean_cost_ratio': _round(_geomean(cost_ratios))}
    per_instance = {f'{iid} r{rep}': {arm: {'resolved': r['resolved'], 'exec_s': _round((r.get('exec_time_ms') or 0) / 1000),
                                             'cost': _round(r.get('cost_usd')), 'models': [m.get('model') for m in r.get('models_served') or []]}
                                       for arm, r in pair.items()} for (iid, rep), pair in sorted(by.items())}
    out = {'summary': summary, 'paired': paired, 'per_instance': per_instance,
           'label': 'screen' if manifest['reps'] < 3 else 'dev-reps>=3',
           'evidence_limits': ['Provider-reported cost is an estimate, not billing.',
                               'Fewer than 3 reps is a screen, never a finding (STUDY-DESIGN.md section 8).',
                               'exec time = first llm:request to last llm:response in the parent session.']}
    _dump(root/'report.json', out)
    print(json.dumps(out, indent=2))


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    return round(xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2, 1)


def _round(x, n=3):
    return None if x is None else round(x, n)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--root', required=True)
    p.add_argument('--instances', required=True)
    p.add_argument('--candidate-sha', required=True)
    p.add_argument('--baseline-source', required=True)
    p.add_argument('--arms', default='plain,plain-sonnet,orch-primary')
    p.add_argument('--reps', type=int, default=1)
    p.add_argument('--seed', type=int, default=20260924)
    p.add_argument('--deadline-seconds', type=int, default=1800)
    p.add_argument('--max-iterations', type=int, default=100)
    p.add_argument('--swe-python', default=str(DEFAULT_SWE_PYTHON))
    p.set_defaults(func=cmd_prepare)
    p = sub.add_parser('run')
    p.add_argument('--root', required=True)
    p.add_argument('--parallel', type=int, default=3)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser('agent', help='internal: one agent run (launched inside Forge by `run`)')
    p.add_argument('--root', required=True)
    p.add_argument('--name', required=True)
    p.set_defaults(func=cmd_agent)
    p = sub.add_parser('grade')
    p.add_argument('--root', required=True)
    p.add_argument('--swe-python', default=str(DEFAULT_SWE_PYTHON))
    p.add_argument('--max-workers', type=int, default=1)
    p.add_argument('--timeout', type=int, default=1800)
    p.set_defaults(func=cmd_grade)
    p = sub.add_parser('report')
    p.add_argument('--root', required=True)
    p.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
