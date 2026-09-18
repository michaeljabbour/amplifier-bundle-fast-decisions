"""Tests for scripts/battery.py -- the multi-harness benchmark runner.

Stdlib unittest only. Never invokes claude/codex/opencode/amplifier for real:
external harnesses are driven through a fake `forge` module (patched into
sys.modules) whose `call('run_command', ...)` returns canned per-harness
stdout, and the two amplifier harnesses are driven through fake
launcher/waiter/closer callables that write worker-shaped result.json files
directly. Task data comes from a small fake `battery_tasks` module (2 code
tasks + 1 answer task) injected via sys.modules, never the real one (which
another builder is writing concurrently).
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import battery  # noqa: E402
import forge_e2e  # noqa: E402


# --------------------------------------------------------------------------
# Fake battery_tasks module (2 code tasks + 1 answer task)
# --------------------------------------------------------------------------

class _Task:
    def __init__(self, name, family, split, kind, prompt, files, protected,
                 expected_answer=None, evaluate_fn=None):
        self.name = name
        self.family = family
        self.split = split
        self.kind = kind
        self.prompt = prompt
        self.files = files
        self.protected = protected
        self.expected_answer = expected_answer
        self._evaluate_fn = evaluate_fn

    def evaluate(self, workspace):
        return self._evaluate_fn(workspace)


def _eval_module(workspace, attr):
    import importlib.util
    spec = importlib.util.spec_from_file_location('candidate_solution', Path(workspace)/'solution.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, attr)


def _eval_add_one(workspace):
    fn = _eval_module(workspace, 'add_one')
    checks, failures = 0, []
    for x, expected in [(1, 2), (5, 6), (-1, 0)]:
        checks += 1
        try:
            ok = fn(x) == expected
        except Exception:
            ok = False
        if not ok:
            failures.append(f'add_one({x})!={expected}')
    return {'checks': checks, 'passed': checks-len(failures), 'failed': len(failures), 'failure_labels': failures}


def _eval_double(workspace):
    fn = _eval_module(workspace, 'double')
    checks, failures = 0, []
    for x, expected in [(1, 2), (3, 6), (0, 0)]:
        checks += 1
        try:
            ok = fn(x) == expected
        except Exception:
            ok = False
        if not ok:
            failures.append(f'double({x})!={expected}')
    return {'checks': checks, 'passed': checks-len(failures), 'failed': len(failures), 'failure_labels': failures}


def make_fake_battery_tasks():
    mod = ModuleType('battery_tasks')

    tasks = {
        'add_one': _Task(
            'add_one', 'arith', 'dev', 'code',
            'Fix solution.py so add_one(x) returns x+1. Run python3 -m unittest -v test_public.py.',
            {'README.md': 'Fix add_one.\n', 'solution.py': 'def add_one(x):\n    return x\n',
             'test_public.py': ('import unittest\nfrom solution import add_one\n'
                                 'class T(unittest.TestCase):\n def test(self):\n  self.assertEqual(add_one(1), 2)\n')},
            ('README.md', 'test_public.py'), evaluate_fn=_eval_add_one),
        'double': _Task(
            'double', 'arith', 'holdout', 'code',
            'Fix solution.py so double(x) returns x*2. Run python3 -m unittest -v test_public.py.',
            {'README.md': 'Fix double.\n', 'solution.py': 'def double(x):\n    return x\n',
             'test_public.py': ('import unittest\nfrom solution import double\n'
                                 'class T(unittest.TestCase):\n def test(self):\n  self.assertEqual(double(3), 6)\n')},
            ('README.md', 'test_public.py'), evaluate_fn=_eval_double),
        'capital': _Task(
            'capital', 'geography', 'dev', 'answer',
            'What is the capital of France? Answer in one word.',
            {'README.md': 'Answer the question in the prompt with one word.\n'},
            ('README.md',), expected_answer=r'(?i)paris'),
    }

    def check_answer(task, final_message):
        checks = 1
        if task.expected_answer and final_message and re.search(task.expected_answer, final_message):
            return {'checks': checks, 'passed': 1, 'failed': 0, 'failure_labels': []}
        return {'checks': checks, 'passed': 0, 'failed': 1, 'failure_labels': ['answer_mismatch']}

    def split(name):
        if name == 'all':
            return list(tasks)
        return [n for n, t in tasks.items() if t.split == name]

    mod.TASKS = tasks
    mod.check_answer = check_answer
    mod.split = split
    mod.REFERENCE_SOLUTIONS = {}
    return mod


def _patched_battery_tasks():
    return patch.dict(sys.modules, {'battery_tasks': make_fake_battery_tasks()})


# --------------------------------------------------------------------------
# Canned harness stdout fixtures
# --------------------------------------------------------------------------

CLAUDE_STDOUT = '\n'.join([
    json.dumps({'type': 'system', 'subtype': 'init'}),
    json.dumps({'type': 'assistant', 'text': 'working...'}),
    json.dumps({'type': 'result', 'total_cost_usd': 0.42, 'duration_ms': 12345, 'num_turns': 3,
                'modelUsage': {'claude-opus-5[1m]': {'input_tokens': 100, 'output_tokens': 50}},
                'result': 'All good, tests updated and passing.'}),
]) + '\n'

CODEX_STDOUT = '\n'.join([
    json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 1000, 'cached_input_tokens': 200,
                                                       'cache_write_input_tokens': 50, 'output_tokens': 300,
                                                       'reasoning_output_tokens': 20}}),
    json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 500, 'cached_input_tokens': 0,
                                                       'cache_write_input_tokens': 0, 'output_tokens': 100,
                                                       'reasoning_output_tokens': 0}}),
]) + '\n'

OPENCODE_STDOUT = '\n'.join([
    json.dumps({'type': 'text', 'part': {'text': 'Working on it...'}}),
    json.dumps({'type': 'step_finish', 'part': {'tokens': {'total': 300, 'input': 200, 'output': 100,
                                                              'reasoning': 0, 'cache': 0}, 'cost': 0.05}}),
    json.dumps({'type': 'text', 'part': {'text': 'Done, solution updated.'}}),
]) + '\n'


def make_fake_forge(behaviors):
    """behaviors: {command: value|callable(args)->dict|Exception}."""
    calls = []

    def call(tool, args):
        calls.append((tool, dict(args)))
        if tool == 'close_terminal':
            return {}
        behavior = behaviors.get(args['command'])
        if isinstance(behavior, BaseException):
            raise behavior
        if callable(behavior):
            return behavior(args)
        return behavior
    return SimpleNamespace(call=call), calls


def codex_ok(args):
    argv = args['args']
    out_path = argv[argv.index('-o')+1]
    Path(out_path).write_text('Fixed the bug and validated with tests.\n')
    return {'output': CODEX_STDOUT, 'exitCode': 0}


# --------------------------------------------------------------------------
# Pure-function tests: harness output parsing
# --------------------------------------------------------------------------

class ParseClaudeTests(unittest.TestCase):
    def test_parses_last_result_line(self):
        parsed = battery._parse_claude(CLAUDE_STDOUT)
        self.assertEqual(parsed['cost_usd'], 0.42)
        self.assertEqual(parsed['harness_duration_ms'], 12345)
        self.assertEqual(parsed['num_turns'], 3)
        self.assertEqual(parsed['model'], 'claude-opus-5[1m]')
        self.assertEqual(parsed['tokens'], {'input_tokens': 100, 'output_tokens': 50})
        self.assertEqual(parsed['final_message'], 'All good, tests updated and passing.')
        self.assertEqual(parsed['cost_source'], 'harness_reported')
        self.assertTrue(parsed['cost_billable'])

    def test_no_result_line_returns_none(self):
        self.assertIsNone(battery._parse_claude('{"type":"system"}\n'))


class ParseCodexTests(unittest.TestCase):
    def test_sums_usage_across_turns_and_reads_last_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            msg_path = Path(tmp)/'last-message.md'
            msg_path.write_text('Fixed it.\n')
            parsed = battery._parse_codex(CODEX_STDOUT, msg_path, model='gpt-6-astra')
        self.assertEqual(parsed['tokens'], {'input_tokens': 1500, 'cached_input_tokens': 200,
                                             'cache_write_input_tokens': 50, 'output_tokens': 400,
                                             'reasoning_output_tokens': 20})
        self.assertEqual(parsed['final_message'], 'Fixed it.\n')
        self.assertEqual(parsed['cost_source'], 'computed_from_tokens_estimate')
        self.assertIsNotNone(parsed['cost_usd'])
        self.assertTrue(parsed['cost_billable'])

    def test_unknown_model_leaves_cost_unknown(self):
        parsed = battery._parse_codex(CODEX_STDOUT, None, model='some-unpriced-model')
        self.assertIsNone(parsed['cost_usd'])
        self.assertEqual(parsed['cost_source'], 'unknown')
        self.assertFalse(parsed['cost_billable'])

    def test_no_usage_events_returns_none_tokens(self):
        parsed = battery._parse_codex('{"type":"other"}\n', None, model='gpt-6-astra')
        self.assertIsNone(parsed['tokens'])


class ParseOpencodeTests(unittest.TestCase):
    def test_concatenates_last_text_and_sums_cost(self):
        parsed = battery._parse_opencode(OPENCODE_STDOUT, model='runpod/zai-org/GLM-5.3-Flash')
        self.assertEqual(parsed['final_message'], 'Done, solution updated.')
        self.assertEqual(parsed['tokens']['total'], 300)
        self.assertAlmostEqual(parsed['cost_usd'], 0.05)
        self.assertEqual(parsed['cost_source'], 'gateway_internal_not_metered')
        self.assertFalse(parsed['cost_billable'])


# --------------------------------------------------------------------------
# Pure-function tests: evaluate math
# --------------------------------------------------------------------------

class EvaluateMathTests(unittest.TestCase):
    def test_penalized_ms_uses_wall_time_only_when_passed(self):
        self.assertEqual(battery._penalized_ms({'outcome_passed': True, 'wall_time_ms': 111}, 60000), 111)
        self.assertEqual(battery._penalized_ms({'outcome_passed': False, 'wall_time_ms': 111}, 60000), 60000)
        self.assertEqual(battery._penalized_ms(None, 60000), 60000)

    def test_geomean(self):
        self.assertAlmostEqual(battery._geomean([1.0, 4.0]), 2.0)
        self.assertIsNone(battery._geomean([]))

    def test_sign_test_hand_computed(self):
        # 4 wins (candidate faster), 1 loss, 0 ties -> n=5, k=min(4,1)=1
        # exact two-sided binomial: 2 * sum_{i=0}^{1} C(5,i)/2^5 = 2*(1+5)/32 = 12/32 = 0.375
        diffs = [-10, -10, -10, -10, 5]
        result = battery._sign_test(diffs)
        self.assertEqual(result['wins'], 4)
        self.assertEqual(result['losses'], 1)
        self.assertEqual(result['ties'], 0)
        self.assertAlmostEqual(result['p_value'], 0.375)

    def test_sign_test_all_ties(self):
        result = battery._sign_test([0, 0, 0])
        self.assertIsNone(result['p_value'])


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def _prepare_args(root, experiment, tasks='all', harnesses='claude,codex,opencode,amplifier-plain,amplifier-fd',
                   seed=7, baseline_source=None, candidate_source=None, deadline_seconds=60):
    return SimpleNamespace(
        root=str(root), experiment=experiment, harnesses=harnesses, tasks=tasks, seed=seed,
        fd_override=None, deadline_seconds=deadline_seconds, claude_model='claude-x', codex_model='gpt-6-astra',
        opencode_model='runpod/zai-org/GLM-5.3-Flash', claude_max_budget_usd=3.0,
        baseline_source=baseline_source, candidate_source=candidate_source)


class PrepareTests(unittest.TestCase):
    def test_frozen_order_deterministic_and_workspaces_identical_per_task(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            base = Path(tmp)
            baseline = base/'baseline'; candidate = base/'candidate'
            baseline.mkdir(); candidate.mkdir()
            root_a = base/'campaign_a'; root_b = base/'campaign_b'
            args_a = _prepare_args(root_a, 'e1', baseline_source=str(baseline), candidate_source=str(candidate))
            args_b = _prepare_args(root_b, 'e1', baseline_source=str(baseline), candidate_source=str(candidate))
            manifest_a = battery.cmd_prepare(args_a)
            manifest_b = battery.cmd_prepare(args_b)
            self.assertEqual(manifest_a['run_order'], manifest_b['run_order'])

            proposal = json.loads((root_a/'experiments'/'e1'/'proposal.json').read_text())
            self.assertEqual(proposal['schema_version'], battery.BATTERY_SCHEMA)
            self.assertEqual(sorted(proposal['harnesses']), sorted(['claude', 'codex', 'opencode',
                                                                      'amplifier-plain', 'amplifier-fd']))
            self.assertIn('add_one', proposal['dev_tasks'])
            self.assertIn('capital', proposal['dev_tasks'])
            self.assertIn('double', proposal['holdout_tasks'])
            self.assertIn('prompt_sha256', proposal)
            self.assertIn('preregistered_at_utc', proposal)
            self.assertEqual(proposal['models']['codex'], 'gpt-6-astra')

            experiment_dir = root_a/'experiments'/'e1'
            by_task = {}
            for name, item in manifest_a['runs'].items():
                run_dir = battery._run_dir_for(experiment_dir, name, item['harness'])
                by_task.setdefault(item['task'], set()).add(forge_e2e.hash_files(run_dir/'workspace'))
            for task, hashes in by_task.items():
                self.assertEqual(len(hashes), 1, f'workspace mismatch for {task}: {hashes}')

    def test_only_dev_split_selected(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            base = Path(tmp)
            baseline = base/'baseline'; candidate = base/'candidate'
            baseline.mkdir(); candidate.mkdir()
            root = base/'campaign'
            args = _prepare_args(root, 'dev1', tasks='dev', harnesses='claude',
                                  baseline_source=str(baseline), candidate_source=str(candidate))
            manifest = battery.cmd_prepare(args)
            tasks_seen = {item['task'] for item in manifest['runs'].values()}
            self.assertEqual(tasks_seen, {'add_one', 'capital'})

    def test_amplifier_harnesses_require_sources(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = Path(tmp)/'campaign'
            args = _prepare_args(root, 'e2', harnesses='amplifier-plain', tasks='dev')
            with self.assertRaises(SystemExit) as ctx:
                battery.cmd_prepare(args)
            self.assertEqual(ctx.exception.code, 4)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def _write_protocol(root, per_launch=1.0, cap=1000.0, max_launches=100, baseline=None, candidate=None):
    root.mkdir(parents=True, exist_ok=True)
    for sub in ('experiments', 'reports', 'handoff'):
        (root/sub).mkdir(parents=True, exist_ok=True)
    (root/'protocol.json').write_text(json.dumps({
        'reservation_policy': {'per_launch_usd': per_launch},
        'limits': {'max_benchmark_worker_launches': max_launches, 'estimated_total_usd': cap, 'max_candidates': 100},
    }))
    # campaign._write_checkpoint() (called by battery.cmd_run) needs campaign.json's
    # sources block; a minimal stub is enough since we bypass campaign.py's full init.
    (root/'campaign.json').write_text(json.dumps({
        'campaign_id': 'battery-test',
        'sources': {
            'baseline_source': {'path': str(baseline or root), 'git_sha': None, 'tree_sha256': None},
            'candidate_worktree': {'path': str(candidate or root), 'git_sha': None, 'tree_sha256': None},
            'installed_cache': {'path': str(root), 'git_sha': None, 'tree_sha256': None},
        },
    }))


def fake_amplifier_launcher(amp_root, name):
    active = 'amplifier-fd' in name
    (amp_root/name).mkdir(parents=True, exist_ok=True)
    result = {
        'outcome_passed': True, 'wall_time_ms': 5000.0 if active else 9000.0, 'exit_code': 0,
        'timed_out': False, 'native': {'usage': {'cost_usd': None}},
        'effort_receipts': [{'model': 'claude-fable-5-1', 'count': 3}], 'model': 'claude-fable-5-1',
        'final_message': None, 'quality': {'checks': 3, 'passed': 3, 'failed': 0, 'failure_labels': []},
        'protected_files_unchanged': {'README.md': True, 'test_public.py': True},
        'started_at': 't0', 'ended_at': 't1', 'infrastructure_failure': False,
    }
    (amp_root/name/'result.json').write_text(json.dumps(result))


def fake_amplifier_waiter(amp_root, name, timeout):
    return (amp_root/name/'result.json').exists()


def fake_amplifier_closer(amp_root, name):
    pass


class RunTests(unittest.TestCase):
    def _prepared(self, tmp, harnesses, tasks='dev', per_launch=1.0, cap=1000.0, max_launches=100):
        base = Path(tmp)
        baseline = base/'baseline'; candidate = base/'candidate'
        baseline.mkdir(); candidate.mkdir()
        root = base/'campaign'
        args = _prepare_args(root, 'e1', harnesses=harnesses, tasks=tasks,
                              baseline_source=str(baseline), candidate_source=str(candidate))
        battery.cmd_prepare(args)
        _write_protocol(root, per_launch=per_launch, cap=cap, max_launches=max_launches,
                         baseline=baseline, candidate=candidate)
        return root

    def test_external_harnesses_dispatch_parse_and_settle(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'claude,codex,opencode', tasks='dev')
            forge_module, calls = make_fake_forge({'claude': {'output': CLAUDE_STDOUT, 'exitCode': 0},
                                                     'codex': codex_ok,
                                                     'opencode': {'output': OPENCODE_STDOUT, 'exitCode': 0}})
            battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'), forge_module=forge_module)

            manifest = json.loads((root/'experiments'/'e1'/'runs'/'manifest.json').read_text())
            results = {}
            for name, item in manifest['runs'].items():
                run_dir = battery._run_dir_for(root/'experiments'/'e1', name, item['harness'])
                results[name] = json.loads((run_dir/'result.json').read_text())

            claude_result = next(r for r in results.values() if r['harness'] == 'claude' and r['task'] == 'add_one')
            self.assertEqual(claude_result['cost_usd'], 0.42)
            self.assertTrue(claude_result['cost_billable'])
            self.assertEqual(claude_result['model'], 'claude-opus-5[1m]')

            codex_result = next(r for r in results.values() if r['harness'] == 'codex' and r['task'] == 'add_one')
            self.assertIsNotNone(codex_result['cost_usd'])
            self.assertEqual(codex_result['cost_source'], 'computed_from_tokens_estimate')

            opencode_result = next(r for r in results.values() if r['harness'] == 'opencode' and r['task'] == 'add_one')
            self.assertFalse(opencode_result['cost_billable'])
            self.assertEqual(opencode_result['cost_source'], 'gateway_internal_not_metered')

            ledger = [json.loads(line) for line in (root/'ledger.jsonl').read_text().splitlines()]
            settlements = {e['reservation']: e for e in ledger if e.get('type') == 'settlement'}
            reservations = {e['id']: e for e in ledger if e.get('type') == 'reservation'}
            # every reservation was settled
            self.assertEqual(set(reservations), set(settlements))
            # opencode settles at 0.0 (not billable here), never "unknown"
            opencode_reservation = next(rid for rid, e in reservations.items()
                                         if e['purpose'].endswith(f"{opencode_result['name']}"))
            self.assertNotIn('unknown', settlements[opencode_reservation])
            self.assertEqual(settlements[opencode_reservation]['actual_usd'], 0.0)

    def test_amplifier_harnesses_use_launcher_waiter_closer(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'amplifier-plain,amplifier-fd', tasks='dev')
            battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'),
                             launcher=fake_amplifier_launcher, waiter=fake_amplifier_waiter,
                             closer=fake_amplifier_closer)
            manifest = json.loads((root/'experiments'/'e1'/'runs'/'manifest.json').read_text())
            for name, item in manifest['runs'].items():
                run_dir = battery._run_dir_for(root/'experiments'/'e1', name, item['harness'])
                result = json.loads((run_dir/'result.json').read_text())
                self.assertTrue(result['outcome_passed'])
                self.assertEqual(result['cost_source'], 'unknown')  # native cost_usd was None
                self.assertFalse(result['infrastructure_failure'])

    def test_timeout_observation_marks_timed_out_not_completion(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'claude', tasks='dev')
            timeout_exc = SystemExit('forge: '+json.dumps({'timeout': True, 'exitCode': None, 'output': ''}))
            forge_module, _calls = make_fake_forge({'claude': timeout_exc})
            battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'), forge_module=forge_module)
            manifest = json.loads((root/'experiments'/'e1'/'runs'/'manifest.json').read_text())
            for name, item in manifest['runs'].items():
                run_dir = battery._run_dir_for(root/'experiments'/'e1', name, item['harness'])
                result = json.loads((run_dir/'result.json').read_text())
                self.assertTrue(result['timed_out'])
                self.assertFalse(result['outcome_passed'])
                self.assertFalse(result['infrastructure_failure'])

    def test_skips_completed_runs(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'claude', tasks='dev')
            experiment_dir = root/'experiments'/'e1'
            manifest = json.loads((experiment_dir/'runs'/'manifest.json').read_text())
            first_name = manifest['run_order'][0]
            run_dir = battery._run_dir_for(experiment_dir, first_name, manifest['runs'][first_name]['harness'])
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir/'result.json').write_text(json.dumps({'outcome_passed': True, 'name': first_name,
                                                             'harness': 'claude', 'task': manifest['runs'][first_name]['task']}))
            forge_module, calls = make_fake_forge({'claude': {'output': CLAUDE_STDOUT, 'exitCode': 0}})
            battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'), forge_module=forge_module)
            invoked_cwds = [c[1]['cwd'] for c in calls if c[0] == 'run_command']
            self.assertFalse(any(first_name in cwd for cwd in invoked_cwds))
            ledger = [json.loads(line) for line in (root/'ledger.jsonl').read_text().splitlines()]
            launched = [e['run'] for e in ledger if e.get('type') == 'run_launched']
            self.assertNotIn(first_name, launched)

    def test_infrastructure_failure_retries_once_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'claude', tasks='dev')
            attempts = {'n': 0}

            def flaky(args):
                attempts['n'] += 1
                if attempts['n'] == 1:
                    raise RuntimeError('simulated launch crash')
                return {'output': CLAUDE_STDOUT, 'exitCode': 0}
            forge_module, _calls = make_fake_forge({'claude': flaky})
            battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'), forge_module=forge_module)
            manifest = json.loads((root/'experiments'/'e1'/'runs'/'manifest.json').read_text())
            retried = [n for n in manifest['run_order'] if n.endswith('-a2')]
            self.assertEqual(len(retried), 1)
            retry_run_dir = battery._run_dir_for(root/'experiments'/'e1', retried[0],
                                                  manifest['runs'][retried[0]]['harness'])
            retry_result = json.loads((retry_run_dir/'result.json').read_text())
            # The retry attempt reached the (fake) harness successfully -- outcome_passed depends
            # on the fake claude call actually editing solution.py, which it deliberately does not.
            self.assertFalse(retry_result['infrastructure_failure'])
            self.assertEqual(retry_result['exit_code'], 0)
            self.assertEqual(retry_result['attempt'], 2)
            ledger = [json.loads(line) for line in (root/'ledger.jsonl').read_text().splitlines()]
            self.assertTrue(any(e.get('type') == 'infrastructure_retry_scheduled' for e in ledger))

    def test_budget_refusal_pauses(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'claude', tasks='dev', per_launch=50.0, cap=10.0)
            forge_module, _calls = make_fake_forge({'claude': {'output': CLAUDE_STDOUT, 'exitCode': 0}})
            with self.assertRaises(SystemExit) as ctx:
                battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'), forge_module=forge_module)
            self.assertEqual(ctx.exception.code, 3)
            ledger = [json.loads(line) for line in (root/'ledger.jsonl').read_text().splitlines()]
            self.assertTrue(any(e.get('type') == 'paused' and e.get('reason') == 'budget' for e in ledger))

    def test_launch_cap_pauses(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = self._prepared(tmp, 'claude', tasks='dev', max_launches=0)
            forge_module, _calls = make_fake_forge({'claude': {'output': CLAUDE_STDOUT, 'exitCode': 0}})
            with self.assertRaises(SystemExit) as ctx:
                battery.cmd_run(SimpleNamespace(root=str(root), experiment='e1'), forge_module=forge_module)
            self.assertEqual(ctx.exception.code, 3)
            ledger = [json.loads(line) for line in (root/'ledger.jsonl').read_text().splitlines()]
            self.assertTrue(any(e.get('type') == 'paused' and e.get('reason') == 'launch_cap' for e in ledger))


# --------------------------------------------------------------------------
# evaluate (hand-built experiment tree; bypasses cmd_prepare/cmd_run entirely)
# --------------------------------------------------------------------------

class EvaluateTests(unittest.TestCase):
    def test_per_harness_and_paired_math(self):
        with tempfile.TemporaryDirectory() as tmp, _patched_battery_tasks():
            root = Path(tmp)/'campaign'
            experiment_dir = root/'experiments'/'e1'
            runs_root = experiment_dir/'runs'
            runs_root.mkdir(parents=True)
            (runs_root/'amplifier').mkdir(parents=True)

            # Two tasks (add_one=dev, double=holdout), two harnesses (amplifier-fd, amplifier-plain).
            # fd wins on add_one (2000 < 4000), fd loses on double (5000 > 3000).
            fixtures = [
                ('e1-add_one-amplifier-fd-a1', 'add_one', 'amplifier-fd', True, 2000.0, 0.10),
                ('e1-add_one-amplifier-plain-a1', 'add_one', 'amplifier-plain', True, 4000.0, 0.20),
                ('e1-double-amplifier-fd-a1', 'double', 'amplifier-fd', True, 5000.0, 0.10),
                ('e1-double-amplifier-plain-a1', 'double', 'amplifier-plain', True, 3000.0, 0.20),
            ]
            run_order, runs = [], {}
            for name, task, harness, passed, ms, cost in fixtures:
                run_dir = runs_root/'amplifier'/name if harness.startswith('amplifier') else runs_root/name
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir/'result.json').write_text(json.dumps({
                    'name': name, 'task': task, 'harness': harness, 'family': 'arith', 'split': 'dev',
                    'outcome_passed': passed, 'wall_time_ms': ms, 'cost_usd': cost, 'timed_out': False,
                }))
                run_order.append(name)
                runs[name] = {'name': name, 'task': task, 'harness': harness, 'attempt': 1}
            (runs_root/'manifest.json').write_text(json.dumps({'run_order': run_order, 'runs': runs,
                                                                 'deadline_seconds': 600}))
            (experiment_dir/'proposal.json').write_text(json.dumps({
                'experiment_id': 'e1', 'dev_tasks': ['add_one'], 'holdout_tasks': ['double']}))

            comparison = battery.cmd_evaluate(SimpleNamespace(root=str(root), experiment='e1'))
            self.assertEqual(comparison['per_harness']['amplifier-fd']['n'], 2)
            self.assertEqual(comparison['per_harness']['amplifier-fd']['success_rate'], 1.0)
            paired = comparison['amplifier_fd_vs_plain']
            self.assertEqual(paired['wins'], 1)
            self.assertEqual(paired['losses'], 1)
            self.assertAlmostEqual(paired['geomean_ratio'], (2000/4000*5000/3000)**0.5)
            self.assertIn('add_one', comparison['dev'])
            self.assertIn('double', comparison['holdout'])
            self.assertEqual(comparison['per_task']['add_one']['fastest_passing_harness'], 'amplifier-fd')
            self.assertEqual(comparison['per_task']['double']['fastest_passing_harness'], 'amplifier-plain')
            self.assertAlmostEqual(paired['cost_ratio'], (0.10+0.10)/(0.20+0.20))


# --------------------------------------------------------------------------
# forge_e2e legacy behavior must survive the generalization
# --------------------------------------------------------------------------

class ForgeE2ELegacyStillWorksTests(unittest.TestCase):
    def test_build_workspace_still_writes_legacy_trio(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)/'run'
            workspace = forge_e2e._build_workspace(run_dir, 'scheduler')
            self.assertEqual((workspace/'README.md').read_text(), forge_e2e.SPECS['scheduler'])
            self.assertEqual((workspace/'solution.py').read_text(), forge_e2e.STARTERS['scheduler'])
            self.assertEqual((workspace/'test_public.py').read_text(), forge_e2e.PUBLIC['scheduler'])

    def test_task_kind_defaults_to_code_without_battery_tasks(self):
        self.assertEqual(forge_e2e._task_kind('scheduler'), 'code')

    def test_task_protected_and_files_fallback(self):
        self.assertEqual(forge_e2e._task_protected('scheduler'), ('README.md', 'test_public.py'))
        files = forge_e2e._task_files('scheduler')
        self.assertEqual(set(files), {'README.md', 'solution.py', 'test_public.py'})


if __name__ == '__main__':
    unittest.main()
