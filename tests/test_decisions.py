from __future__ import annotations
import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from uuid import uuid4

from amplifier_fast_decisions.backends import JevBackend, ScriptedBackend, BackendUnavailable
from amplifier_fast_decisions.contracts import Candidate, Decision, DecisionRequest, Policy, Question, TurnState, VALIDATOR_CAPABILITY, canonical
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, DemoTool, DemoContext, DemoLoop, demo_response
from amplifier_fast_decisions.orchestrator import RoutedProvider, HybridOrchestrator, ObservedTool
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter
from amplifier_fast_decisions.state import build_state, request_fingerprint
from amplifier_fast_decisions.privacy import scrub, safe_data
from amplifier_fast_decisions.workspace import WorkspaceTool
from amplifier_fast_decisions.candidates import collect_candidates


def make_candidate(i=0):
    return Candidate(f"read_{i}", f"Prepared {i}", "demo_inspect", {"target": str(i)})


def request(**overrides):
    return NS(**{"messages": [{"role": "user", "content": "Inspect the prepared artifact."}],
                 "tools": [{"name": "demo_inspect"}], "tool_choice": "auto", "model": "pinned-model", **overrides})


def setup_service(*, policy=None, backend=None, candidates=None):
    events=[]; coordinator=DemoCoordinator()
    policy=policy or Policy(mode="active", allowed_tools=("demo_inspect",), allow_synthetic_active=True)
    emitter=Emitter(coordinator.session_id, callback=events.append)
    service=DecisionService(policy,backend or ScriptedBackend(delay_ms=0),emitter,coordinator,
                            [c.__dict__ for c in (candidates if candidates is not None else [make_candidate()])])
    service.turn=TurnState("test-turn")
    runtime=Runtime(service)
    return service,runtime,events,coordinator


class DistributionTests(unittest.TestCase):
    def test_valid(self):
        Decision("a",{"a":.9,"reason":.1}).validate({"a","reason"})
    def test_unknown_label(self):
        with self.assertRaises(ValueError): Decision("x",{"a":.9,"reason":.1}).validate({"a","reason"})
    def test_missing_probability(self):
        with self.assertRaises(ValueError): Decision("a",{"a":1.}).validate({"a","reason"})
    def test_nan(self):
        with self.assertRaises(ValueError): Decision("a",{"a":float('nan'),"reason":.1}).validate({"a","reason"})
    def test_sum(self):
        with self.assertRaises(ValueError): Decision("a",{"a":.8,"reason":.8}).validate({"a","reason"})
    def test_not_argmax(self):
        with self.assertRaises(ValueError): Decision("a",{"a":.2,"reason":.8}).validate({"a","reason"})
    def test_reserved_candidate(self):
        with self.assertRaises(ValueError): Candidate("reason","x","x",{})
    def test_invalid_policy(self):
        with self.assertRaises(ValueError): Policy(timeout_ms=0)
    def test_boolean_probability(self):
        with self.assertRaises(ValueError): Decision("a",{"a":True,"reason":0}).validate({"a","reason"})
    def test_invalid_reported_confidence(self):
        for value in (True, '0.9', float('nan'), float('inf'), -.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Decision('a', {'a':.9, 'reason':.1}, reported_confidence=value).validate({'a','reason'})


class PrivacyTests(unittest.TestCase):
    def test_secrets_scrubbed(self):
        text='api_key=abcdefghijklmnop Bearer abcdefghijk sk-abcdefghijklmnop'
        clean=scrub(text)
        self.assertNotIn('abcdefghijklmnop',clean)
        self.assertNotIn('abcdefghijk ',clean)
    def test_raw_fields_excluded(self):
        output=safe_data({'prompt':'SECRET','arguments':{'token':'SECRET'},'output':'SECRET',
                          'thinking':'SECRET','route':'fast','reason_code':'prepared_action'})
        self.assertEqual(output,{'route':'fast','reason_code':'prepared_action'})
    def test_allowed_string_values_are_still_scrubbed(self):
        # An allow-listed field is kept, but a secret inside its value is not.
        output=safe_data({'reason_code':'api_key=abcdefghijklmnop','exception_type':'Bearer abcdefghijklmnop',
                          'probabilities':{'sk-abcdefghijklmnopqrst':0.5}})
        self.assertNotIn('abcdefghijklmnop',json.dumps(output))
        self.assertEqual(set(output),{'reason_code','exception_type','probabilities'})
    def test_savings_usage_fields_survive_the_allow_list(self):
        # The savings estimate reads these from recorded slow_end events; a
        # field dropped here silently disappears from every event on disk.
        usage={'cost_usd':0.0123,'host_model':'claude-opus-5-5','served_model':'claude-sonnet-5',
               'cache_read_tokens':1000,'cache_write_tokens':50,'input_tokens':1200,'output_tokens':300}
        self.assertEqual(safe_data(usage),usage)
    def test_state_excludes_system_and_private_thinking(self):
        req=request(messages=[{'role':'system','content':'SYSTEM_SECRET'},
            {'role':'assistant','content':[{'type':'thinking','thinking':'PRIVATE'},{'type':'text','text':'Public summary'}]},
            {'role':'tool','content':'api_key=abcdefghijklmnop'}])
        state=str(build_state(req))
        self.assertNotIn('SYSTEM_SECRET',state);self.assertNotIn('PRIVATE',state)
        self.assertNotIn('abcdefghijklmnop',state);self.assertIn('Public summary',state)
    def test_state_bounded(self):
        req=request(messages=[{'role':'user','content':'x'*4000} for _ in range(15)])
        import json
        self.assertLessEqual(len(json.dumps(build_state(req,1000))),1100)
    def test_long_tool_result_keeps_task_and_recent_evidence(self):
        req=request(messages=[{'role':'user','content':'Repair solution.py from README.md'},
                              {'role':'tool','content':'FAILED test_cycle\n'+'x'*5000}])
        state=build_state(req,2048)
        self.assertLessEqual(len(canonical(state)),2048)
        self.assertEqual([x['role'] for x in state['observations']],['user','tool'])
        self.assertIn('Repair solution.py',state['observations'][0]['text'])
        self.assertIn('FAILED test_cycle',state['observations'][1]['text'])
    def test_task_survives_more_than_twelve_messages(self):
        req=request(messages=[{'role':'user','content':'Original task: inspect README.md'}]+
                    [{'role':'tool','content':f'Observation {i}'} for i in range(20)])
        state=build_state(req,512)
        self.assertLessEqual(len(canonical(state)),512)
        text=str(state['observations'])
        self.assertIn('Original task',text)
        self.assertIn('Observation 19',text)
    def test_escaped_and_unicode_observations_stay_bounded_and_scrubbed(self):
        req=request(messages=[{'role':'user','content':'Task '+'"\\\n😀'*1000},
                    {'role':'tool','content':'api_key=abcdefghijklmnop '+'"\\\n😀'*1000}])
        for budget in (512,1000,2048):
            state=build_state(req,budget)
            self.assertLessEqual(len(canonical(state)),budget)
            self.assertEqual(len(state['observations']),2)
            self.assertNotIn('abcdefghijklmnop',canonical(state))
    def test_latest_user_task_supersedes_old_task_anchor(self):
        req=request(messages=[{'role':'user','content':'Old task'},
                    {'role':'user','content':'Current task'}]+
                    [{'role':'tool','content':'recent evidence '*300} for _ in range(15)])
        state=build_state(req,512)
        self.assertIn('Current task',str(state))
        self.assertNotIn('Old task',str(state))
    def test_fingerprint_changes(self):
        a=request(); before=request_fingerprint(a);a.messages.append({'role':'tool','content':'new'})
        self.assertNotEqual(before,request_fingerprint(a))
    def test_stats_no_messages(self):
        stats={}
        state=build_state(request(messages=[]),12000,stats)
        self.assertEqual(state['observations'],[])
        self.assertEqual(stats['observation_count'],0)
        self.assertEqual(stats['observations_available'],0)
        self.assertEqual(stats['observations_dropped'],0)
        self.assertEqual(stats['observations_clipped'],0)
        self.assertFalse(stats['task_anchored'])
        self.assertEqual(stats['truncation_reason'],'no_messages')
    def test_stats_long_tool_result_small_budget(self):
        stats={}
        req=request(messages=[{'role':'user','content':'Repair solution.py from README.md'},
                              {'role':'tool','content':'FAILED test_cycle\n'+'x'*5000}])
        build_state(req,600,stats)
        self.assertGreaterEqual(stats['observations_clipped'],1)
        self.assertTrue(stats['task_anchored'])
        self.assertEqual(stats['truncation_reason'],'budget')
    def test_stats_normal_short_conversation(self):
        stats={}
        req=request(messages=[{'role':'user','content':'Inspect the prepared artifact.'},
                              {'role':'tool','content':'ok'}])
        build_state(req,12000,stats)
        self.assertEqual(stats['observations_dropped'],0)
        self.assertEqual(stats['observations_clipped'],0)
        self.assertEqual(stats['truncation_reason'],'none')
        self.assertTrue(stats['task_anchored'])


class DecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_selects(self):
        service,_,events,_=setup_service()
        result=await service.choose(request(),{'demo_inspect':DemoTool()})
        self.assertEqual(result.id,'read_0')
        self.assertTrue(any(e['event'].endswith('scored') for e in events))
    async def test_requested_carries_domain_and_state_chars(self):
        service,_,events,_=setup_service()
        await service.choose(request(),{'demo_inspect':DemoTool()})
        requested=[e for e in events if e['event'].endswith('requested')]
        self.assertEqual(len(requested),1)
        # demo_inspect is not fast_workspace, so the classifier's
        # tool-choice/read-target distinction lands on tool-choice here.
        self.assertEqual(requested[0]['data']['domain'],'tool-choice')
        self.assertIsInstance(requested[0]['data']['state_chars'],int)
        self.assertGreater(requested[0]['data']['state_chars'],0)
        scored=[e for e in events if e['event'].endswith('scored')]
        self.assertEqual(scored[0]['data']['domain'],'tool-choice')
    async def test_requested_domain_is_read_target_for_workspace_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hello')
            workspace=WorkspaceTool(root)
            candidate=workspace.candidate_for_path('README.md',0)
            policy=Policy(mode='active',allowed_tools=('fast_workspace',),allow_synthetic_active=True)
            service,_,events,_=setup_service(policy=policy,candidates=[candidate])
            await service.choose(request(tools=[{'name':'fast_workspace'}]),{'fast_workspace':workspace})
        requested=[e for e in events if e['event'].endswith('requested')]
        self.assertEqual(len(requested),1)
        self.assertEqual(requested[0]['data']['domain'],'read-target')
    async def test_shadow_does_not_execute(self):
        p=Policy(mode='shadow',allowed_tools=('demo_inspect',))
        service,_,events,_=setup_service(policy=p)
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(events[-1]['data']['reason_code'],'shadow_only')
        self.assertEqual(events[-1]['data']['proposed_route'],'fast')
    async def test_off_skips_backend(self):
        service,_,events,_=setup_service(policy=Policy(mode='off'))
        self.assertIsNone(await service.choose(request(),{}))
        self.assertEqual(service.backend.calls,0)
    async def test_empty_skips_backend(self):
        service,_,events,_=setup_service(candidates=[])
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(service.backend.calls,0)
    async def test_unmounted_tool(self):
        service,_,_,_=setup_service()
        self.assertIsNone(await service.choose(request(),{}))
        self.assertEqual(service.backend.calls,0)
    async def test_force_no_tool(self):
        service,_,_,_=setup_service()
        self.assertIsNone(await service.choose(request(tool_choice='none'),{'demo_inspect':DemoTool()}))
        self.assertEqual(service.backend.calls,0)
    async def test_force_specific_tool_not_overridden(self):
        service,_,_,_=setup_service()
        self.assertIsNone(await service.choose(request(tool_choice={'type':'function','name':'demo_inspect'}),{'demo_inspect':DemoTool()}))
        self.assertEqual(service.backend.calls,0)
    async def test_external_state_requires_consent(self):
        backend=ScriptedBackend(delay_ms=0);backend.external=True
        service,_,events,_=setup_service(backend=backend)
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(backend.calls,0)
        self.assertEqual(events[-1]['data']['reason_code'],'external_state_not_enabled')
    async def test_synthetic_never_silent_production(self):
        p=Policy(mode='active',allowed_tools=('demo_inspect',))
        service,_,events,_=setup_service(policy=p)
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(events[-1]['data']['reason_code'],'synthetic_backend_not_authorized')
    async def test_ambiguous_falls_back(self):
        service,_,events,_=setup_service(backend=ScriptedBackend([{'probability':.55}],delay_ms=0))
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(events[-1]['data']['reason_code'],'selection_threshold')
    async def test_abstain_calls_slow(self):
        service,runtime,events,_=setup_service(backend=ScriptedBackend([{'choice':'reason'}],delay_ms=0))
        provider=DemoProvider(delay_ms=0)
        await RoutedProvider(provider,runtime,{'demo_inspect':DemoTool()},demo_response).complete(request())
        self.assertEqual(provider.calls,1)
        self.assertTrue(any(e['data'].get('reason_code')=='model_abstained' for e in events))
    async def test_timeout_and_circuit(self):
        # timeout_ms>=100 with a >=5x backend delay keeps this deterministic under
        # CI scheduling jitter (see test_build_contracts.py's shared-deadline test
        # for the failure mode a too-tight margin produces).
        p=Policy(mode='active',timeout_ms=100,allowed_tools=('demo_inspect',),allow_synthetic_active=True)
        backend=ScriptedBackend([{'delay_ms':500}],delay_ms=0)
        service,_,events,_=setup_service(policy=p,backend=backend)
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertTrue(any(e['data'].get('reason_code')=='decision_timeout' for e in events))
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(backend.calls,1)
        self.assertEqual(events[-1]['data']['reason_code'],'backend_circuit_open')
    async def test_backend_error_falls_back(self):
        service,_,events,_=setup_service(backend=ScriptedBackend([{'error':True}],delay_ms=0))
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertTrue(any(e['data'].get('reason_code')=='backend_error' for e in events))
    async def test_cancel_propagates(self):
        backend=ScriptedBackend([{'delay_ms':2000}])
        service,_,events,_=setup_service(backend=backend)
        task=asyncio.create_task(service.choose(request(),{'demo_inspect':DemoTool()}))
        await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(any(e['event'].endswith('cancelled') for e in events))
    async def test_stale_request_rejected(self):
        req=request()
        class Mutating(ScriptedBackend):
            async def ask(self,decision_request):
                answer=await super().ask(decision_request)
                req.messages.append({'role':'user','content':'Cancel the old objective'})
                return answer
        service,_,events,_=setup_service(backend=Mutating(delay_ms=0))
        self.assertIsNone(await service.choose(req,{'demo_inspect':DemoTool()}))
        self.assertEqual(events[-1]['data']['reason_code'],'stale_state')
    async def test_revalidation_can_deny(self):
        service,_,events,coord=setup_service()
        count=0
        def validator(c):
            nonlocal count
            count+=1
            return count==1
        coord.capabilities[VALIDATOR_CAPABILITY]=validator
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(events[-1]['data']['reason_code'],'candidate_no_longer_eligible')
    async def test_untrusted_other_tool_requires_validator(self):
        service,_,events,coord=setup_service();coord.capabilities.pop(VALIDATOR_CAPABILITY)
        self.assertIsNone(await service.choose(request(),{'demo_inspect':DemoTool()}))
        self.assertEqual(service.backend.calls,0)
    async def test_duplicate_candidate_not_repeated(self):
        service,runtime,events,_=setup_service()
        provider=DemoProvider(delay_ms=0)
        facade=RoutedProvider(provider,runtime,{'demo_inspect':DemoTool()},demo_response)
        first=await facade.complete(request());second=await facade.complete(request())
        self.assertTrue(first.tool_calls);self.assertFalse(second.tool_calls)
        self.assertEqual(provider.calls,1)
    async def test_fast_streak_budget(self):
        p=Policy(mode='active',allowed_tools=('demo_inspect',),allow_synthetic_active=True,max_fast_streak=1)
        service,runtime,events,_=setup_service(policy=p,candidates=[make_candidate(0),make_candidate(1)])
        provider=DemoProvider(delay_ms=0);facade=RoutedProvider(provider,runtime,{'demo_inspect':DemoTool()},demo_response)
        await facade.complete(request());await facade.complete(request())
        self.assertEqual(provider.calls,1)
        self.assertTrue(any(e['data'].get('reason_code')=='fast_path_budget' for e in events))


class FacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_kwargs_response_identity(self):
        service,runtime,events,_=setup_service(policy=Policy(mode='off'))
        sentinel=object();req=request()
        class Provider(DemoProvider):
            async def complete(self, incoming, **kwargs):
                self.asserted=(incoming is req and kwargs=={'flag':'preserved'})
                return sentinel
        provider=Provider(delay_ms=0)
        response=await RoutedProvider(provider,runtime,{},demo_response).complete(req,flag='preserved')
        self.assertIs(response,sentinel);self.assertTrue(provider.asserted)
    async def test_facade_mirrors_absent_stream(self):
        _,runtime,_,_=setup_service();provider=DemoProvider();provider.extra='preserved'
        facade=RoutedProvider(provider,runtime,{},demo_response)
        self.assertFalse(hasattr(facade,'stream'));self.assertEqual(facade.extra,'preserved')
    async def test_facade_mirrors_present_stream(self):
        _,runtime,_,_=setup_service();provider=DemoProvider()
        async def fake_stream(request,**kwargs):
            for chunk in ('a','b','c'): yield chunk
        provider.stream=fake_stream
        facade=RoutedProvider(provider,runtime,{},demo_response)
        self.assertTrue(callable(getattr(facade,'stream',None)))
        chunks=[c async for c in facade.stream(request())]
        self.assertEqual(chunks,['a','b','c'])
    async def test_stream_transport_never_calls_service(self):
        service,runtime,events,_=setup_service()
        provider=DemoProvider()
        async def fake_stream(request,**kwargs):
            yield 'chunk'
        provider.stream=fake_stream
        facade=RoutedProvider(provider,runtime,{'demo_inspect':DemoTool()},demo_response)
        chunks=[c async for c in facade.stream(request())]
        self.assertEqual(chunks,['chunk'])
        self.assertEqual(service.backend.calls,0)
        routed=[e for e in events if e['event'].endswith('routed')]
        self.assertEqual(len(routed),1)
        self.assertEqual(routed[0]['data']['reason_code'],'fast_path_unavailable_on_transport')
        self.assertEqual(routed[0]['data']['transport_measured'],'provider-stream')
        self.assertTrue(any(e['event'].endswith('slow_start') and e['data'].get('transport_measured')=='provider-stream' for e in events))
        self.assertTrue(any(e['event'].endswith('slow_end') and e['data'].get('transport_measured')=='provider-stream' for e in events))
    async def test_transport_measured_is_recorded(self):
        _,runtime,events,_=setup_service(policy=Policy(mode='off'))
        provider=DemoProvider(delay_ms=0)
        facade=RoutedProvider(provider,runtime,{},demo_response)
        await facade.complete(request())
        ends=[e for e in events if e['event'].endswith('slow_end')]
        self.assertEqual(ends[-1]['data']['transport_measured'],'provider-complete')
    async def test_turn_start_does_not_claim_transport(self):
        _,runtime,events,coord=setup_service()
        loop=HybridOrchestrator({},coord,runtime,upstream=DemoLoop(),response_factory=demo_response)
        await loop.execute('Inspect',DemoContext(),{'p':DemoProvider(delay_ms=0)},{'demo_inspect':DemoTool()},coord.hooks)
        starts=[e for e in events if e['event'].endswith('turn_start')]
        self.assertEqual(len(starts),1)
        self.assertNotIn('transport',starts[0]['data'])
    async def test_synthetic_parse_does_not_call_provider_parser(self):
        _,runtime,_,_=setup_service()
        class Provider(DemoProvider):
            def parse_tool_calls(self,response): raise RuntimeError('Should not parse synthetic')
        facade=RoutedProvider(Provider(),runtime,{'demo_inspect':DemoTool()},demo_response)
        response=await facade.complete(request())
        self.assertEqual(facade.parse_tool_calls(response)[0].name,'demo_inspect')
    async def test_denied_tool_never_executes(self):
        service,runtime,events,coord=setup_service();tool=DemoTool()
        async def deny(event,data): return NS(action='deny')
        coord.hooks.register('tool:pre',deny,priority=0)
        loop=HybridOrchestrator({},coord,runtime,upstream=DemoLoop(),response_factory=demo_response)
        await loop.execute('Inspect',DemoContext(),{'pinned':DemoProvider(delay_ms=0)}, {'demo_inspect':tool},coord.hooks)
        self.assertEqual(tool.executions,[])
        self.assertFalse(any(e['event'].endswith('tool_start') for e in events))
        self.assertFalse(any(e['event'].endswith('tool_end') for e in events))
    async def test_actual_execution_measured(self):
        service,runtime,events,coord=setup_service();tool=DemoTool()
        loop=HybridOrchestrator({},coord,runtime,upstream=DemoLoop(),response_factory=demo_response)
        await loop.execute('Inspect',DemoContext(),{'pinned':DemoProvider(delay_ms=0)}, {'demo_inspect':tool},coord.hooks)
        self.assertEqual(len(tool.executions),1)
        starts=[e for e in events if e['event'].endswith('tool_start')]
        ends=[e for e in events if e['event'].endswith('tool_end')]
        self.assertEqual(starts[0]['data']['tool_call_id'],ends[0]['data']['tool_call_id'])
        self.assertEqual(starts[0]['decision_id'],ends[0]['decision_id'])
        self.assertTrue(any(e['data'].get('provider')=='pinned' for e in events))
    async def test_original_provider_mapping_not_mutated(self):
        _,runtime,_,coord=setup_service();provider=DemoProvider(delay_ms=0);providers={'original':provider}
        loop=HybridOrchestrator({},coord,runtime,upstream=DemoLoop(),response_factory=demo_response)
        await loop.execute('Test',DemoContext(),providers,{'demo_inspect':DemoTool()},coord.hooks)
        self.assertIs(providers['original'],provider)
    async def test_tool_error_propagates(self):
        _,runtime,events,_=setup_service()
        class Failing:
            async def execute(self,input): raise ValueError('SECRET INPUT')
        with self.assertRaises(ValueError): await ObservedTool(Failing(),runtime,'fail').execute({})
        self.assertEqual(events[-1]['data']['status'],'error')
        self.assertNotIn('SECRET INPUT',str(events))
    async def test_slow_cancel_propagates(self):
        _,runtime,events,_=setup_service(policy=Policy(mode='off'))
        facade=RoutedProvider(DemoProvider(delay_ms=5000),runtime,{},demo_response)
        task=asyncio.create_task(facade.complete(request()));await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(events[-1]['data']['status'],'cancelled')
    async def test_per_turn_once_resets(self):
        _,runtime,_,coord=setup_service();tool=DemoTool()
        loop=HybridOrchestrator({},coord,runtime,upstream=DemoLoop(),response_factory=demo_response)
        for _ in range(2):
            await loop.execute('Inspect',DemoContext(),{'p':DemoProvider(delay_ms=0)},{'demo_inspect':tool},coord.hooks)
        self.assertEqual(len(tool.executions),2)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'README.md').write_text('Hello');self.tool=WorkspaceTool(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_read(self):self.assertEqual(self.tool._read({'operation':'read','path':'README.md'})['text'],'Hello')
    def test_traversal(self):
        with self.assertRaises(ValueError):self.tool._read({'operation':'read','path':'../README.md'})
    def test_hidden(self):
        (self.root/'.env').write_text('secret')
        with self.assertRaises(ValueError):self.tool._read({'operation':'read','path':'.env'})
    def test_symlink(self):
        (self.root/'link.md').symlink_to(self.root/'README.md')
        with self.assertRaises(ValueError):self.tool._read({'operation':'read','path':'link.md'})
    def test_secret_filename(self):
        (self.root/'secrets.json').write_text('{}')
        with self.assertRaises(ValueError):self.tool._read({'operation':'read','path':'secrets.json'})
    def test_binary(self):
        (self.root/'binary.txt').write_bytes(b'a\x00b')
        with self.assertRaises(ValueError):self.tool._read({'operation':'read','path':'binary.txt'})
    def test_no_writes(self):
        with self.assertRaises(ValueError):self.tool._read({'operation':'write','path':'README.md'})
    def test_revision_invalidated(self):
        candidate=self.tool.candidate_for_path('README.md',0)
        self.assertTrue(self.tool.validate_candidate(candidate))
        (self.root/'README.md').write_text('Changed long content')
        self.assertFalse(self.tool.validate_candidate(candidate))
    def test_truncation(self):
        (self.root/'large.md').write_text('x'*5000)
        tool=WorkspaceTool(self.root,max_bytes=1024)
        result=tool._read({'operation':'read','path':'large.md'})
        self.assertTrue(result['truncated']);self.assertEqual(len(result['text']),1024)


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_documented_sdk_shape(self):
        class Client:
            async def system_one(self,**kwargs):
                self.kwargs=kwargs
                return NS(answers={'next_action':NS(probabilities={'read_0':.95,'reason':.05}, confidence=.9)},
                          model='actual-returned-model',usage=NS(input_tokens=17,output_tokens=0))
            async def aclose(self):self.closed=True
        client=Client();backend=JevBackend(client=client,model='test-model')
        req=DecisionRequest(state={'task':'inspect'},candidates=(make_candidate(),))
        result=await backend.ask(req)
        self.assertEqual(result.action.choice,'read_0')
        self.assertEqual(result.model,'actual-returned-model');self.assertEqual(result.input_tokens,17)
        self.assertEqual(client.kwargs['questions']['next_action']['type'],'choice')
        self.assertIn('reason',client.kwargs['questions']['next_action']['criteria'])
        self.assertFalse(result.synthetic)
        await backend.close();self.assertTrue(client.closed)
    async def test_batches_contributed_questions_in_one_call(self):
        class Client:
            calls=0
            async def system_one(self,**kwargs):
                self.calls+=1;self.kwargs=kwargs
                return NS(answers={
                    'next_action':NS(probabilities={'read_0':.95,'reason':.05}, confidence=.9),
                    'risk':NS(probabilities={'x':1.0},confidence=.4),
                    'stale':NS(noul=.7),
                },model='m',usage=NS(input_tokens=5,output_tokens=0))
            async def aclose(self):pass
        client=Client();backend=JevBackend(client=client,model='m')
        questions=(Question('risk','score','How risky?'),Question('stale','noul','Stale?'))
        req=DecisionRequest(state={},candidates=(make_candidate(),),questions=questions)
        result=await backend.ask(req)
        self.assertEqual(client.calls,1)
        self.assertEqual(set(client.kwargs['questions']),{'next_action','risk','stale'})
        self.assertEqual(result.answers['risk'].confidence,.4)
        self.assertEqual(result.answers['stale'].noul,.7)
    async def test_key_not_assumed(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(BackendUnavailable):JevBackend()._get_client()



class RaisingBackend:
    """HC02a: proves the suppressed-to-empty route never reaches the backend."""
    name = "raising"
    external = False

    def __init__(self):
        self.calls = 0

    async def ask(self, request):
        self.calls += 1
        raise AssertionError("backend must not be called when every candidate is suppressed")

    async def close(self):
        pass


class CompletedReadLedgerTests(unittest.IsolatedAsyncioTestCase):
    """HC02a: revision-aware completed-read suppression."""

    async def test_already_read_candidate_suppressed_no_backend_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hello')
            workspace=WorkspaceTool(root)
            candidate=workspace.candidate_for_path('README.md',0)
            identity=workspace.read_identity('README.md','read')
            policy=Policy(mode='active',allowed_tools=('fast_workspace',),allow_synthetic_active=True)
            backend=RaisingBackend()
            service,_,events,_=setup_service(policy=policy,backend=backend,candidates=[candidate])
            # Simulate a native read_file already having read this exact revision.
            service.turn.completed_reads[identity[0]]=identity[1]
            result=await service.choose(request(tools=[{'name':'fast_workspace'}]),{'fast_workspace':workspace})
        self.assertIsNone(result)
        self.assertEqual(backend.calls,0)
        routed=[e for e in events if e['event'].endswith('routed')]
        self.assertEqual(routed[-1]['data']['reason_code'],'already_read_unchanged')
        self.assertEqual(routed[-1]['data']['candidates_suppressed_already_read'],1)
        self.assertFalse(any(e['event'].endswith('requested') for e in events))

    async def test_changed_revision_is_eligible_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hello')
            workspace=WorkspaceTool(root)
            stale_identity=workspace.read_identity('README.md','read')
            # File changes after the recorded read: a fresh candidate carries
            # the new revision, so it no longer matches the stale ledger entry.
            (root/'README.md').write_text('Changed content, different revision now')
            candidate=workspace.candidate_for_path('README.md',0)
            self.assertNotEqual(candidate.revision,stale_identity[1])
            policy=Policy(mode='active',allowed_tools=('fast_workspace',),allow_synthetic_active=True)
            backend=ScriptedBackend(delay_ms=0)
            service,_,events,_=setup_service(policy=policy,backend=backend,candidates=[candidate])
            service.turn.completed_reads[stale_identity[0]]=stale_identity[1]
            result=await service.choose(request(tools=[{'name':'fast_workspace'}]),{'fast_workspace':workspace})
        self.assertEqual(result.id,candidate.id)
        self.assertEqual(backend.calls,1)
        requested=[e for e in events if e['event'].endswith('requested')]
        self.assertEqual(requested[0]['data']['candidates_suppressed_already_read'],0)

    async def test_fast_submission_records_ledger_and_suppresses_next_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hello')
            workspace=WorkspaceTool(root)
            revision=workspace.read_identity('README.md','read')[1]
            # Two distinct candidate ids pointing at the identical (path, revision):
            # proves suppression is driven by the ledger, not the existing
            # per-fingerprint `turn.used` dedup (candidate_b has a different id
            # and therefore a different fingerprint than candidate_a).
            candidate_a=Candidate('read_a','Read A','fast_workspace',{'operation':'read','path':'README.md'},revision=revision)
            candidate_b=Candidate('read_b','Read B','fast_workspace',{'operation':'read','path':'README.md'},revision=revision)
            policy=Policy(mode='active',allowed_tools=('fast_workspace',),allow_synthetic_active=True)
            backend=ScriptedBackend([{'choice':'read_a'}],delay_ms=0)
            service,runtime,events,_=setup_service(policy=policy,backend=backend,candidates=[candidate_a,candidate_b])
            facade=RoutedProvider(DemoProvider(delay_ms=0),runtime,{'fast_workspace':workspace},demo_response)
            first=await facade.complete(request(tools=[{'name':'fast_workspace'}]))
            self.assertTrue(first.tool_calls)
            self.assertIn(str((root/'README.md').resolve()),service.turn.completed_reads)
            second=await facade.complete(request(tools=[{'name':'fast_workspace'}]))
        self.assertFalse(second.tool_calls)
        self.assertEqual(backend.calls,1)
        routed=[e for e in events if e['event'].endswith('routed')]
        self.assertEqual(routed[-1]['data']['reason_code'],'already_read_unchanged')
        self.assertEqual(routed[-1]['data']['candidates_suppressed_already_read'],1)

    async def test_denied_or_failed_read_not_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hello')
            workspace=WorkspaceTool(root)
            class FailingReadFile:
                async def execute(self,input,**kwargs):
                    return NS(success=False,error={'message':'denied'})
            service,runtime,_,_=setup_service()
            observed=ObservedTool(FailingReadFile(),runtime,'read_file',workspace=workspace)
            await observed.execute({'file_path':str(root/'README.md')})
        self.assertEqual(service.turn.completed_reads,{})

    async def test_ledger_resets_on_new_turn(self):
        service,_,_,_=setup_service()
        service.turn.completed_reads['/some/path']='rev1'
        self.assertTrue(service.turn.completed_reads)
        # Mirrors HybridOrchestrator.execute's per-turn TurnState replacement.
        service.turn=TurnState(uuid4().hex)
        self.assertEqual(service.turn.completed_reads,{})

    async def test_flag_disabled_behaves_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hello')
            workspace=WorkspaceTool(root)
            candidate=workspace.candidate_for_path('README.md',0)
            identity=workspace.read_identity('README.md','read')
            policy=Policy(mode='active',allowed_tools=('fast_workspace',),allow_synthetic_active=True,suppress_completed_reads=False)
            backend=ScriptedBackend(delay_ms=0)
            service,_,events,_=setup_service(policy=policy,backend=backend,candidates=[candidate])
            service.turn.completed_reads[identity[0]]=identity[1]
            result=await service.choose(request(tools=[{'name':'fast_workspace'}]),{'fast_workspace':workspace})
        self.assertEqual(result.id,candidate.id)
        self.assertEqual(backend.calls,1)
        requested=[e for e in events if e['event'].endswith('requested')]
        self.assertEqual(requested[0]['data']['candidates_suppressed_already_read'],0)

if __name__=='__main__':unittest.main()
