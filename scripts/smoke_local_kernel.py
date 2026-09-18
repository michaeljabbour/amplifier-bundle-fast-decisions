#!/usr/bin/env python3
"""Opt-in live Ollama smoke with installed core/loop and a fixture finalizer.

Run with PYTHONPATH=src in the Amplifier Python environment, after pulling
qwen3:0.6b. This is not a complete Foundation CLI host certification.
Uses only temporary public files; writes allowlisted evidence under docs/evidence.
"""
import asyncio,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from amplifier_core.testing import MockCoordinator,MockContextManager
from amplifier_core.models import HookResult
from amplifier_core.message_models import ChatResponse,Usage
from amplifier_fast_decisions.runtime import get_runtime
from amplifier_fast_decisions.orchestrator import HybridOrchestrator
from amplifier_fast_decisions.workspace import WorkspaceTool
from amplifier_fast_decisions.local_backend import OllamaBackend
from amplifier_fast_decisions.contracts import DecisionRequest

class TrackingWorkspace(WorkspaceTool):
    def __init__(self, root):
        super().__init__(root)
        self.calls = []
    async def execute(self, input, **kwargs):
        self.calls.append(dict(input))
        return await super().execute(input, **kwargs)

class Provider:
    name='fixture-finalizer'
    def get_info(self):return SimpleNamespace(id=self.name,display_name=self.name,context_window=32000)
    async def list_models(self):return []
    def parse_tool_calls(self,response):return response.tool_calls or []
    async def complete(self,request,**kw):
        return ChatResponse(content=[{'type':'text','text':'fixture complete'}],tool_calls=[],usage=Usage(input_tokens=1,output_tokens=1,total_tokens=2))

async def main():
    records=[]
    for deny in (False,True):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'docs').mkdir();(root/'README.md').write_text('Public event schema fixture.\n');(root/'LICENSE.md').write_text('Public license fixture.\n')
            tool=TrackingWorkspace(root);candidate=tool.candidate_for_path('README.md',0)
            warm=OllamaBackend(model='qwen3:0.6b',timeout_ms=30000)
            await warm.ask(DecisionRequest(state={'observations':[{'role':'user','text':'Read README.md, not LICENSE.md.'}]},candidates=(candidate,)))
            await warm.close()
            coordinator=MockCoordinator();context=MockContextManager();native=[]
            async def pre(event,data):
                native.append(event)
                return HookResult(action='deny' if deny else 'continue')
            coordinator.hooks.register('tool:pre',pre,priority=0)
            config={'backend':'ollama','model':'qwen3:0.6b','mode':'active','timeout_ms':500,'max_state_chars':2048,'events_dir':str(root/'events'),'max_fast_per_turn':1,'upstream':{'max_iterations':3}}
            runtime,_=get_runtime(coordinator,config,owner=True)
            try:
                result=await HybridOrchestrator(config,coordinator,runtime).execute('Read README.md, not LICENSE.md.',context,{'fixture':Provider()},{'fast_workspace':tool},coordinator.hooks)
            finally:await runtime.close()
            events=[json.loads(line) for p in (root/'events').glob('*.jsonl') for line in p.read_text().splitlines()]
            assert tool.calls == ([] if deny else [{'operation':'read','path':'README.md'}]), tool.calls
            assert len(native) == 1, native
            assert sum(e['event']=='fast_decisions:tool_start' for e in events) == (0 if deny else 1)
            records.append({'deny':deny,'native_tool_pre':len(native),'fixture_finished':result=='fixture complete','events':events})
    out={'evidence_kind':'real Ollama and installed Amplifier loop/core with mock coordinator/context and fixture generative finalizer; not Foundation CLI host validation','runs':records}
    Path('docs/evidence/local-kernel-two-targets-smoke.json').write_text(json.dumps(out,indent=2)+'\n')
    for r in records:
        print(json.dumps({'deny':r['deny'],'native_tool_pre':r['native_tool_pre'],'events':[(e['event'],{k:v for k,v in e['data'].items() if k in ('route','reason_code','selected_probability','duration_ms','model')}) for e in r['events']]}))
asyncio.run(main())
