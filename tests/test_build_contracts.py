"""Packaging/config checks plus opt-in checks against actual installed envelopes.

Skipped upstream checks are reported as skipped, never counted as proven runtime tests.
"""
import asyncio
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from amplifier_fast_decisions.cli import configure, export_html
from amplifier_fast_decisions.contracts import Candidate, EVENT_NAMES, Policy
from amplifier_fast_decisions.candidates import parse_candidate
from amplifier_fast_decisions.privacy import safe_data
from amplifier_fast_decisions.runtime import get_runtime
from amplifier_fast_decisions.demo import DemoCoordinator, DemoTool, DemoProvider, demo_response
from amplifier_fast_decisions.orchestrator import RoutedProvider
from test_decisions import setup_service, request

ROOT = Path(__file__).resolve().parents[1]
HAS_CORE = importlib.util.find_spec("amplifier_core") is not None
HAS_LOOP = importlib.util.find_spec("amplifier_module_loop_streaming") is not None

class BuildTests(unittest.TestCase):
    def test_module_entrypoints(self):
        for name in ('loop-fast-decisions','hooks-fast-decisions','tool-fast-workspace'):
            data=tomllib.loads((ROOT/'modules'/name/'pyproject.toml').read_text())
            self.assertIn(name,data['project']['entry-points']['amplifier.modules'])
    def test_root_package_assets(self):
        data=tomllib.loads((ROOT/'pyproject.toml').read_text())
        self.assertEqual(data['project']['requires-python'], '>=3.11')
        self.assertTrue((ROOT/'README.md').is_file())
        self.assertIn('static/*',data['tool']['setuptools']['package-data']['amplifier_fast_decisions'])
    def test_profile_is_valid_frontmatter_and_not_global(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'profile.md'
            args=SimpleNamespace(bundle_root=str(ROOT),workspace=temp,mode='shadow',
                allow_external_state=True,events=str(Path(temp)/'events'),timeout_ms=750,output=str(output))
            configure(args)
            data=json.loads(output.read_text().split('---')[1])
            self.assertEqual(data['bundle']['name'],'fast-decisions-shadow')
            self.assertTrue(data['includes'][0]['bundle'].startswith('file:///'))
            self.assertEqual(data['tools'][0]['config']['root'],temp)
    def test_active_requires_external_opt_in(self):
        with self.assertRaises(ValueError):
            configure(SimpleNamespace(bundle_root=str(ROOT),mode='active',allow_external_state=False))
    def test_dict_candidate_is_copied(self):
        data={'id':'x','label':'label','tool':'tool','arguments':{'nested':{'a':1}}}
        candidate=parse_candidate(data);data['arguments']['nested']['a']=2
        self.assertEqual(candidate.arguments['nested']['a'],1)
    def test_nonfinite_metadata_removed(self):
        self.assertIsNone(safe_data({'duration_ms':float('nan')})['duration_ms'])
    def test_bounded_candidate_count(self):
        with self.assertRaises(ValueError):Policy(max_candidates=100)
    def test_workspace_truncated_unicode(self):
        from amplifier_fast_decisions.workspace import WorkspaceTool
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"unicode.txt").write_text("a"*1023+"é"*20)
            result=WorkspaceTool(temp,max_bytes=1024)._read({"operation":"read","path":"unicode.txt"})
            self.assertTrue(result["truncated"])
            self.assertEqual(result["text"],"a"*1023)
    def test_event_schema_names(self):
        schema=json.loads((ROOT/'schemas/event.schema.json').read_text())
        self.assertEqual(set(schema['properties']['event']['enum']),set(EVENT_NAMES))

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_service_capability_and_idempotent_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            coordinator=DemoCoordinator()
            runtime,owner=get_runtime(coordinator,{'backend':'unavailable','events_dir':temp})
            again,second_owner=get_runtime(coordinator,{})
            self.assertIs(again,runtime);self.assertTrue(owner);self.assertFalse(second_owner)
            self.assertIs(coordinator.get_capability('fast_decisions.service'),runtime.service)
            await runtime.close();await runtime.close()
            self.assertTrue(runtime.closed)
    async def test_invalid_envelope_does_not_claim_fast_submission(self):
        service,runtime,events,_=setup_service()
        def invalid(candidate,call_id):raise ValueError('schema drift')
        await RoutedProvider(DemoProvider(delay_ms=0),runtime,{'demo_inspect':DemoTool()},invalid).complete(request())
        self.assertEqual(service.turn.fast_total,0)
        self.assertFalse(any(e['event'].endswith('routed') and e['data'].get('route')=='fast' for e in events))
    async def test_deadline_shared_across_candidate_and_model(self):
        service,_,events,coord=setup_service(policy=Policy(mode='active',timeout_ms=25,
            allowed_tools=('demo_inspect',),allow_synthetic_active=True))
        service.backend.delay_ms=20
        async def slow_candidates(req):await asyncio.sleep(.018);return []
        coord.capabilities['fast_decisions.candidates']=slow_candidates
        result=await service.choose(request(),{'demo_inspect':DemoTool()})
        self.assertIsNone(result)
        self.assertTrue(any(e['data'].get('reason_code')=='decision_timeout' for e in events))

class InstalledUpstreamTests(unittest.TestCase):
    @unittest.skipUnless(HAS_CORE,'Actual amplifier_core is not installed')
    def test_actual_core_envelope(self):
        from amplifier_fast_decisions.orchestrator import action_response
        from amplifier_core.message_models import ChatResponse
        response=action_response(Candidate('read','Read','fast_workspace',{'operation':'read','path':'README.md'}),'call')
        self.assertIsInstance(response,ChatResponse)
        self.assertEqual(response.tool_calls[0].arguments['path'],'README.md')
        self.assertEqual(response.usage.total_tokens,0)
    @unittest.skipUnless(HAS_CORE,'Actual amplifier_core is not installed')
    def test_actual_hook_result(self):
        from amplifier_core.models import HookResult
        self.assertEqual(HookResult(action='continue').action,'continue')
    @unittest.skipUnless(HAS_LOOP,'Actual loop-streaming is not installed')
    def test_actual_loop_signature(self):
        from amplifier_module_loop_streaming import StreamingOrchestrator
        signature=inspect.signature(StreamingOrchestrator({}).execute)
        self.assertTrue({'prompt','context','providers','tools','hooks'}<=set(signature.parameters))
