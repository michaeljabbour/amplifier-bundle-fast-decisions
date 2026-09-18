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
            (root/'manifest.json').write_text(json.dumps({'run_order':['one','two']}))
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


if __name__=='__main__':unittest.main()
