"""A Forge observation deadline must not cause overlapping benchmark runs."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import forge_e2e
import forge_report
import hashlib


class ForgeControllerTests(unittest.TestCase):
    def test_empty_forge_session_list_preserves_recorded_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'forge-sessions.json'
            path.write_text(json.dumps({'completed':{'id':'completed'}}))
            with patch.dict(sys.modules,{'forge':SimpleNamespace(call=lambda *_:'No active sessions')}):
                forge_report.monitor(root)
            self.assertEqual(json.loads(path.read_text()),{'completed':{'id':'completed'}})

    def test_observation_timeout_waits_for_worker_before_next_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('one','two'):(root/name/'workspace').mkdir(parents=True)
            (root/'manifest.json').write_text(json.dumps({'run_order':['one','two'],'limits':{'timeout_seconds':480}}))
            launched=[];closed=[]
            def call(tool,args):
                if tool=='close_terminal':closed.append(args['id']);return {}
                name=Path(args['cwd']).parent.name
                if launched:self.assertTrue((root/launched[-1]/'result.json').exists())
                launched.append(name)
                raise SystemExit('forge: '+json.dumps({'timeout':True,'exitCode':None,'sessionId':name,'output':''}))
            def sleep(_):
                (root/launched[-1]/'result.json').write_text(json.dumps({'outcome_passed':True}))
            with patch.dict(sys.modules,{'forge':SimpleNamespace(call=call)}), patch.object(forge_e2e.time,'sleep',sleep):
                forge_e2e.batch(root)
            self.assertEqual(launched,['one','two'])
            self.assertEqual(closed,['one','two'])

    def test_wait_for_result_returns_false_when_controller_pid_is_dead(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'one';run.mkdir()
            # A pid that is (barring astronomical bad luck) not alive right now.
            dead_pid = 999999
            (run/'running.json').write_text(json.dumps({'controller_pid': dead_pid}))
            clock = {'t': 0.0}
            def fake_sleep(_):
                clock['t'] += 2
            with patch.object(forge_e2e.time, 'sleep', fake_sleep), \
                 patch.object(forge_e2e.time, 'monotonic', lambda: clock['t']):
                ok = forge_e2e.wait_for_result(root, 'one', timeout_seconds=120)
            self.assertFalse(ok)
            self.assertFalse((run/'result.json').exists())

    def test_wait_for_result_true_once_result_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'one';run.mkdir()
            (run/'result.json').write_text(json.dumps({'outcome_passed':True}))
            self.assertTrue(forge_e2e.wait_for_result(root,'one',timeout_seconds=5))

    def test_worker_sets_pythonpath_to_side_source_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            side_source = root/'side-source'
            (side_source/'src'/'amplifier_fast_decisions').mkdir(parents=True)
            (side_source/'src'/'amplifier_fast_decisions'/'mod.py').write_text('x = 1\n')
            tree_sha = forge_e2e.tree_sha256(side_source/'src'/'amplifier_fast_decisions')
            run = root/'one'
            workspace = run/'workspace'
            (workspace/'.amplifier').mkdir(parents=True)
            (workspace/'README.md').write_text(forge_e2e.SPECS['scheduler'])
            (workspace/'solution.py').write_text(forge_e2e.STARTERS['scheduler'])
            (workspace/'test_public.py').write_text(forge_e2e.PUBLIC['scheduler'])
            (run/'profile.md').write_text('---\n{}\n---\n')
            workspace_hash = forge_e2e.hash_files(workspace)
            manifest = {
                'runs': {'one': {'task': 'scheduler', 'side': 'fast', 'workspace_hash': workspace_hash, 'attempt': 1}},
                'sides': {'fast': {'source_root': str(side_source), 'mode': 'active',
                                    'source_git_sha': None, 'source_tree_sha256': tree_sha}},
                'provider': 'anthropic', 'model': 'claude-fable-5-1', 'prompt': 'do it',
                'events_dir': str(root/'events'),
                'limits': {'timeout_seconds': 5},
            }
            (root/'manifest.json').write_text(json.dumps(manifest))

            captured = {}

            class FakeProcess:
                pid = 4242
                def wait(self, timeout=None):
                    return 0

            def fake_popen(command, cwd=None, env=None):
                captured['env'] = env
                captured['cwd'] = cwd
                return FakeProcess()

            with patch.object(forge_e2e.subprocess, 'Popen', fake_popen), \
                 patch.object(forge_e2e.urllib.request, 'urlopen') as fake_urlopen, \
                 patch.object(forge_e2e.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"checks":0,"passed":0,"failed":0,"failure_labels":[]}')):
                fake_urlopen.return_value.__enter__.return_value = SimpleNamespace()
                with patch('json.load', return_value={}):
                    forge_e2e.worker(root, 'one')

            self.assertEqual(captured['env']['PYTHONPATH'], str(side_source/'src'))


if __name__=='__main__':unittest.main()


class SideProfileModeTests(unittest.TestCase):
    def test_active_side_profile_pins_mode_active(self):
        import forge_e2e
        cfg = {'limits': {'max_iterations': 30, 'extended_thinking': True}, 'events_dir': '/tmp/e', 'upstream_loop_source': 'git+x'}
        active = forge_e2e._side_profile('n', {'source_root': '/tmp/s', 'mode': 'active'}, 'scheduler', '/tmp/w', cfg)
        self.assertEqual(active['session']['orchestrator']['config']['mode'], 'active')
        self.assertEqual(active['hooks'][0]['config']['mode'], 'active')
        off = forge_e2e._side_profile('n', {'source_root': '/tmp/s', 'mode': 'off'}, 'scheduler', '/tmp/w', cfg)
        self.assertEqual(off['session']['orchestrator']['module'], 'loop-streaming')
        self.assertEqual(off['hooks'][0]['config']['mode'], 'off')


class WorkerPromptVerificationTests(unittest.TestCase):
    """Defect 1: worker() must never silently fall back to the generic legacy
    prompt for a battery task, and must refuse to launch amplifier at all when
    the prompt it is about to send does not match the preregistered
    prompt_sha256."""

    def _base_manifest(self, side_source, tree_sha, **item_overrides):
        item = {'task': 'battery_task_x', 'side': 'fast', 'attempt': 1}
        item.update(item_overrides)
        return {
            'runs': {'one': item},
            'sides': {'fast': {'source_root': str(side_source), 'mode': 'active',
                                'source_git_sha': None, 'source_tree_sha256': tree_sha}},
            'provider': 'anthropic', 'model': 'claude-fable-5-1', 'prompt': 'generic legacy prompt',
            'events_dir': '/tmp/events',
            'limits': {'timeout_seconds': 5},
        }

    def _set_up_workspace(self, root, workspace_hash_task='scheduler'):
        side_source = root/'side-source'
        (side_source/'src'/'amplifier_fast_decisions').mkdir(parents=True)
        (side_source/'src'/'amplifier_fast_decisions'/'mod.py').write_text('x = 1\n')
        tree_sha = forge_e2e.tree_sha256(side_source/'src'/'amplifier_fast_decisions')
        run = root/'one'
        workspace = run/'workspace'
        (workspace/'.amplifier').mkdir(parents=True)
        (run/'profile.md').write_text('---\n{}\n---\n')
        return side_source, tree_sha, workspace

    def test_missing_prompt_for_battery_task_refuses_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            side_source, tree_sha, workspace = self._set_up_workspace(root)
            workspace_hash = forge_e2e.hash_files(workspace)
            manifest = self._base_manifest(side_source, tree_sha, workspace_hash=workspace_hash)
            (root/'manifest.json').write_text(json.dumps(manifest))

            with patch.object(forge_e2e.subprocess, 'Popen') as fake_popen, \
                 patch.object(forge_e2e.urllib.request, 'urlopen') as fake_urlopen:
                with self.assertRaises(SystemExit):
                    forge_e2e.worker(root, 'one')
            fake_popen.assert_not_called()
            fake_urlopen.assert_not_called()

    def test_prompt_sha256_mismatch_refuses_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            side_source, tree_sha, workspace = self._set_up_workspace(root)
            workspace_hash = forge_e2e.hash_files(workspace)
            manifest = self._base_manifest(
                side_source, tree_sha, workspace_hash=workspace_hash,
                prompt='the real task prompt', prompt_sha256='0'*64)
            (root/'manifest.json').write_text(json.dumps(manifest))

            with patch.object(forge_e2e.subprocess, 'Popen') as fake_popen, \
                 patch.object(forge_e2e.urllib.request, 'urlopen') as fake_urlopen:
                with self.assertRaises(SystemExit):
                    forge_e2e.worker(root, 'one')
            fake_popen.assert_not_called()
            fake_urlopen.assert_not_called()

    def test_matching_prompt_and_sha256_launches_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            side_source, tree_sha, workspace = self._set_up_workspace(root)
            (workspace/'README.md').write_text('readme\n')
            (workspace/'solution.py').write_text('x = 1\n')
            workspace_hash = forge_e2e.hash_files(workspace)
            prompt = 'the real task prompt'
            manifest = self._base_manifest(
                side_source, tree_sha, workspace_hash=workspace_hash,
                prompt=prompt, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
            (root/'manifest.json').write_text(json.dumps(manifest))

            fake_tasks = SimpleNamespace(TASKS={}, check_answer=lambda *a: None)

            class FakeProcess:
                pid = 4242
                def wait(self, timeout=None):
                    return 0

            with patch.dict(sys.modules, {'battery_tasks': fake_tasks}), \
                 patch.object(forge_e2e.forge_workloads, 'task_files', lambda t: {'README.md': 'readme\n', 'solution.py': 'x = 1\n'}), \
                 patch.object(forge_e2e.forge_workloads, 'task_protected', lambda t: ('README.md',)), \
                 patch.object(forge_e2e, '_task_kind', lambda t: 'code'), \
                 patch.object(forge_e2e.subprocess, 'Popen', lambda *a, **k: FakeProcess()), \
                 patch.object(forge_e2e.urllib.request, 'urlopen') as fake_urlopen, \
                 patch.object(forge_e2e.subprocess, 'run',
                               lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"checks":0,"passed":0,"failed":0,"failure_labels":[]}', stderr='')):
                fake_urlopen.return_value.__enter__.return_value = SimpleNamespace()
                with patch('json.load', return_value={}):
                    forge_e2e.worker(root, 'one')
            result = json.loads((root/'one'/'result.json').read_text())
            self.assertEqual(result['exit_code'], 0)


class RunWorkspaceTestsTests(unittest.TestCase):
    """Defect 2: run_workspace_tests must run pytest-style tests correctly
    (unittest discover silently collects nothing for plain `def test_*`
    functions), and must distinguish 'no tests collected' (None) from an
    actual failure (False)."""

    def _pytest_available(self):
        return forge_e2e._interpreter_with_pytest() is not None

    def test_passing_pytest_style_test(self):
        if not self._pytest_available():
            self.skipTest('no interpreter on this host can import pytest')
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace/'test_thing.py').write_text('def test_ok():\n    assert True\n')
            passed, runner, _summary = forge_e2e.run_workspace_tests(workspace)
            self.assertTrue(passed)
            self.assertEqual(runner, 'pytest')

    def test_failing_pytest_style_test(self):
        if not self._pytest_available():
            self.skipTest('no interpreter on this host can import pytest')
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace/'test_thing.py').write_text('def test_bad():\n    assert False\n')
            passed, runner, _summary = forge_e2e.run_workspace_tests(workspace)
            self.assertFalse(passed)
            self.assertEqual(runner, 'pytest')

    def test_no_tests_collected_returns_none(self):
        if not self._pytest_available():
            self.skipTest('no interpreter on this host can import pytest')
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace/'test_empty.py').write_text('x = 1\n')
            passed, runner, _summary = forge_e2e.run_workspace_tests(workspace)
            self.assertIsNone(passed)
            self.assertEqual(runner, 'pytest')

    def test_falls_back_to_unittest_when_pytest_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace/'test_thing.py').write_text(
                'import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n')
            with patch.object(forge_e2e, '_interpreter_with_pytest', lambda: None):
                passed, runner, _summary = forge_e2e.run_workspace_tests(workspace)
            self.assertTrue(passed)
            self.assertEqual(runner, 'unittest')
