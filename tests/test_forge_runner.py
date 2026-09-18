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
