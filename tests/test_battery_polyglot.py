"""Tests for wiring the aider-polyglot task adapter (scripts/polyglot_tasks.py)
into the harness battery runner (scripts/battery.py) and the forge_e2e
worker/evaluate path.

No network, no real harness: external harnesses go through the same fake
`forge` module as tests/test_battery.py (imported from there), and
amplifier harnesses go through the same fake launcher/waiter/closer. The
polyglot corpus is a small fake tree (2 python exercises with pytest tests
and reference solutions) built on disk in a temp dir -- only the Python
evaluate() path is exercised against a real toolchain (pytest, already a
project dependency), matching tests/test_polyglot_tasks.py's own scope.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import battery  # noqa: E402
import forge_e2e  # noqa: E402
import forge_workloads  # noqa: E402
import battery_tasks as bt  # noqa: E402

from test_battery import (  # noqa: E402
    make_fake_forge, CLAUDE_STDOUT, _write_protocol,
    fake_amplifier_launcher, fake_amplifier_waiter, fake_amplifier_closer,
)

SCRIPTS_DIR = Path(__file__).resolve().parents[1]/'scripts'
FORGE_E2E_PY = SCRIPTS_DIR/'forge_e2e.py'


# --------------------------------------------------------------------------
# Fake polyglot-benchmark corpus: 2 python exercises, each with a stub
# (starter), a reference solution, and a pytest test file.
# --------------------------------------------------------------------------

_EXERCISES = {
    'add-numbers': {
        'instructions': 'Implement `add(a, b)` returning the sum of `a` and `b`.\n',
        'solution_file': 'add_numbers.py',
        'test_file': 'add_numbers_test.py',
        'stub': 'def add(a, b):\n    pass\n',
        'reference': 'def add(a, b):\n    return a + b\n',
        'test': (
            'from add_numbers import add\n\n\n'
            'def test_positive():\n    assert add(2, 3) == 5\n\n\n'
            'def test_negative():\n    assert add(-1, -1) == -2\n'
        ),
    },
    'double-numbers': {
        'instructions': 'Implement `double(a)` returning twice `a`.\n',
        'solution_file': 'double_numbers.py',
        'test_file': 'double_numbers_test.py',
        'stub': 'def double(a):\n    pass\n',
        'reference': 'def double(a):\n    return a * 2\n',
        'test': (
            'from double_numbers import double\n\n\n'
            'def test_positive():\n    assert double(3) == 6\n\n\n'
            'def test_zero():\n    assert double(0) == 0\n'
        ),
    },
}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _build_fake_polyglot_root(root: Path) -> None:
    for slug, spec in _EXERCISES.items():
        ex = root/'python'/'exercises'/'practice'/slug
        _write(ex/'.docs'/'instructions.md', spec['instructions'])
        _write(ex/'.meta'/'config.json', json.dumps({
            'files': {
                'solution': [spec['solution_file']],
                'test': [spec['test_file']],
                'example': [f".meta/{spec['solution_file']}"],
            }
        }))
        _write(ex/'.meta'/spec['solution_file'], spec['reference'])
        _write(ex/spec['solution_file'], spec['stub'])
        _write(ex/spec['test_file'], spec['test'])


def _prepare_args(root, experiment, **overrides):
    base = dict(
        root=str(root), experiment=experiment, harnesses='claude,amplifier-fd',
        tasks=None, seed=42, fd_override=None, deadline_seconds=None,
        claude_model='claude-x', codex_model='gpt-6-astra', opencode_model='opencode-x',
        claude_max_budget_usd=3.0, baseline_source=None, candidate_source=None,
        candidate_sha=None, fd_backend=None, allow_external_state=False,
        task_source='polyglot', polyglot_root=None, languages='python',
        slice=2, split='all',
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class PreparePolyglotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.corpus_root = self.tmp/'polyglot-benchmark'
        _build_fake_polyglot_root(self.corpus_root)
        self.baseline = self.tmp/'baseline'
        self.candidate = self.tmp/'candidate'
        self.baseline.mkdir()
        self.candidate.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_prepare_builds_identical_workspaces_and_records_slice(self):
        root = self.tmp/'campaign'
        args = _prepare_args(root, 'poly1', polyglot_root=str(self.corpus_root),
                              baseline_source=str(self.baseline), candidate_source=str(self.candidate))
        manifest = battery.cmd_prepare(args)
        self.assertTrue(manifest['run_order'])

        experiment_dir = root/'experiments'/'poly1'
        proposal = json.loads((experiment_dir/'proposal.json').read_text())
        self.assertEqual(proposal['task_source']['kind'], 'polyglot')
        self.assertEqual(proposal['task_source']['root'], str(self.corpus_root.resolve()))
        self.assertEqual(proposal['polyglot_slice'], 2)
        self.assertEqual(proposal['polyglot_split'], 'all')
        self.assertEqual(sorted(proposal['tasks']),
                          ['poly_python_add-numbers', 'poly_python_double-numbers'])

        amp_manifest = json.loads((experiment_dir/'runs'/'amplifier'/'manifest.json').read_text())
        self.assertEqual(amp_manifest['task_source']['kind'], 'polyglot')

        # Identical hashed workspace content per task, across BOTH harnesses
        # (claude external + amplifier-fd), same invariant as the battery tasks.
        by_task = {}
        for name, item in manifest['runs'].items():
            run_dir = battery._run_dir_for(experiment_dir, name, item['harness'])
            by_task.setdefault(item['task'], set()).add(forge_e2e.hash_files(run_dir/'workspace'))
        self.assertEqual(len(by_task), 2)
        for task, hashes in by_task.items():
            self.assertEqual(len(hashes), 1, f'workspace mismatch for {task}: {hashes}')

        # Amplifier sub-manifest run items carry the polyglot prompt (ends with
        # PROMPT_SUFFIX) with a matching prompt_sha256.
        for name, item in amp_manifest['runs'].items():
            self.assertTrue(item['prompt'].endswith(bt.PROMPT_SUFFIX), name)
            self.assertEqual(item['prompt_sha256'], hashlib.sha256(item['prompt'].encode()).hexdigest(), name)

    def test_split_dev_holdout_all_partition_the_slice(self):
        root = self.tmp/'campaign'
        args = _prepare_args(root, 'poly2', harnesses='amplifier-fd', split='dev',
                              polyglot_root=str(self.corpus_root),
                              baseline_source=str(self.baseline), candidate_source=str(self.candidate))
        manifest = battery.cmd_prepare(args)
        dev_tasks = {item['task'] for item in manifest['runs'].values()}
        self.assertTrue(dev_tasks)
        self.assertTrue(dev_tasks.issubset({'poly_python_add-numbers', 'poly_python_double-numbers'}))

    def test_missing_polyglot_root_fails_loud(self):
        root = self.tmp/'campaign'
        args = _prepare_args(root, 'poly3', polyglot_root=None,
                              baseline_source=str(self.baseline), candidate_source=str(self.candidate))
        with self.assertRaises(SystemExit) as ctx:
            battery.cmd_prepare(args)
        self.assertEqual(ctx.exception.code, 4)


class GetTaskAfterRegisterTests(unittest.TestCase):
    def test_get_task_resolves_from_manifest_task_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus_root = Path(tmp)/'polyglot-benchmark'
            _build_fake_polyglot_root(corpus_root)
            baseline = Path(tmp)/'baseline'; candidate = Path(tmp)/'candidate'
            baseline.mkdir(); candidate.mkdir()
            root = Path(tmp)/'campaign'
            args = _prepare_args(root, 'poly4', harnesses='amplifier-fd',
                                  polyglot_root=str(corpus_root),
                                  baseline_source=str(baseline), candidate_source=str(candidate))
            battery.cmd_prepare(args)
            amp_manifest = json.loads(
                (root/'experiments'/'poly4'/'runs'/'amplifier'/'manifest.json').read_text())

            # Simulate a fresh process: clear the in-memory registry, then
            # register only from what the manifest persisted.
            forge_workloads._extra_tasks.clear()
            with self.assertRaises(KeyError):
                forge_workloads.get_task('poly_python_add-numbers')
            forge_e2e._ensure_task_source_registered(amp_manifest)
            task = forge_workloads.get_task('poly_python_add-numbers')
            self.assertEqual(task.family, 'poly_python')
            self.assertEqual(task.kind, 'code')


class EvaluateSubprocessTests(unittest.TestCase):
    """Runs the real `forge_e2e.py evaluate <root> <name>` CLI in a fresh
    subprocess against a hand-built per-run root -- exercising the manifest's
    task_source registration path exactly as forge_e2e.worker() would."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.corpus_root = self.tmp/'polyglot-benchmark'
        _build_fake_polyglot_root(self.corpus_root)
        self.run_root = self.tmp/'runs'
        self.run_root.mkdir()
        self.name = 'r1'
        self.run_dir = self.run_root/self.name
        self.workspace = self.run_dir/'workspace'

    def tearDown(self):
        self._tmp.cleanup()

    def _write_manifest_and_workspace(self, solution_content, test_content=None):
        forge_workloads.register_source('polyglot', root=str(self.corpus_root), languages=['python'])
        task = forge_workloads.get_task('poly_python_add-numbers')
        for rel, content in task.files.items():
            target = self.workspace/rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        (self.workspace/'add_numbers.py').write_text(solution_content, encoding='utf-8')
        if test_content is not None:
            (self.workspace/'add_numbers_test.py').write_text(test_content, encoding='utf-8')
        manifest = {
            'runs': {self.name: {'task': 'poly_python_add-numbers'}},
            'task_source': {'kind': 'polyglot', 'root': str(self.corpus_root), 'languages': ['python']},
        }
        (self.run_root/'manifest.json').write_text(json.dumps(manifest))

    def _run_evaluate(self):
        proc = subprocess.run(
            [sys.executable, str(FORGE_E2E_PY), 'evaluate', str(self.run_root), self.name],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_reference_solution_passes(self):
        self._write_manifest_and_workspace(_EXERCISES['add-numbers']['reference'])
        result = self._run_evaluate()
        self.assertEqual(result['failed'], 0, result)

    def test_stub_fails(self):
        self._write_manifest_and_workspace(_EXERCISES['add-numbers']['stub'])
        result = self._run_evaluate()
        self.assertGreater(result['failed'], 0)

    def test_tampered_test_file_yields_protected_failure(self):
        tampered = _EXERCISES['add-numbers']['test'] + '\n# tampered\n'
        self._write_manifest_and_workspace(_EXERCISES['add-numbers']['reference'], test_content=tampered)
        result = self._run_evaluate()
        self.assertIn('protected_modified:add_numbers_test.py', result['failure_labels'])
        self.assertGreater(result['failed'], 0)


class RunAndEvaluatePolyglotTests(unittest.TestCase):
    def test_run_completes_and_evaluate_produces_per_family_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            corpus_root = tmp/'polyglot-benchmark'
            _build_fake_polyglot_root(corpus_root)
            baseline = tmp/'baseline'; candidate = tmp/'candidate'
            baseline.mkdir(); candidate.mkdir()
            root = tmp/'campaign'
            args = _prepare_args(root, 'poly5', harnesses='claude,amplifier-fd',
                                  polyglot_root=str(corpus_root),
                                  baseline_source=str(baseline), candidate_source=str(candidate))
            battery.cmd_prepare(args)
            _write_protocol(root, baseline=baseline, candidate=candidate)

            forge_module, _calls = make_fake_forge({'claude': {'output': CLAUDE_STDOUT, 'exitCode': 0}})
            battery.cmd_run(SimpleNamespace(root=str(root), experiment='poly5'),
                             launcher=fake_amplifier_launcher, waiter=fake_amplifier_waiter,
                             closer=fake_amplifier_closer, forge_module=forge_module)

            manifest = json.loads((root/'experiments'/'poly5'/'runs'/'manifest.json').read_text())
            for name, item in manifest['runs'].items():
                run_dir = battery._run_dir_for(root/'experiments'/'poly5', name, item['harness'])
                result = json.loads((run_dir/'result.json').read_text())
                self.assertFalse(result['infrastructure_failure'], name)

            comparison = battery.cmd_evaluate(SimpleNamespace(
                root=str(root), experiment='poly5', baseline_root=None, baseline_experiment=None))
            self.assertIn('poly_python', comparison['per_family'])


if __name__ == '__main__':
    unittest.main()
