from __future__ import annotations
import asyncio
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from amplifier_fast_decisions.backends import BackendUnavailable
from amplifier_fast_decisions.contracts import Candidate, DecisionRequest
from amplifier_fast_decisions.local_backend import OllamaBackend, local_url, score_tokens


def request(**kw):
    return DecisionRequest(state={'observations':[{'role':'user','text':'Read README.md'}]},
                           candidates=(Candidate('read','Read README.md','fast_workspace',{'operation':'read','path':'README.md'}),),**kw)


def payload():
    return {'model':'test-local','done':True,'eval_count':1,'prompt_eval_count':40,
            'response':'A','logprobs':[{'token':'A','logprob':math.log(.92),
              'top_logprobs':[{'token':'A','logprob':math.log(.92)},
                              {'token':'Z','logprob':math.log(.03)}]}]}


class Client:
    def __init__(self,body=None,delay=0,status=200):
        self.body=body or payload();self.delay=delay;self.status=status
        self.calls=[];self.closed=False;self.cancelled=False
    async def post(self,url,**kw):
        self.calls.append((url,kw))
        try: await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled=True
            raise
        return SimpleNamespace(status_code=self.status,content=json.dumps(self.body).encode(),json=lambda:self.body)
    async def aclose(self): self.closed=True


class LocalBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_scores_are_real_token_mass_with_conservative_abstention(self):
        client=Client();backend=OllamaBackend(model='test-local',client=client)
        result=await backend.ask(request())
        self.assertEqual(result.action.choice,'read')
        self.assertAlmostEqual(result.action.probabilities['read'],.92)
        self.assertAlmostEqual(result.action.probabilities['reason'],.08)
        self.assertIsNone(result.action.reported_confidence)
        self.assertEqual(result.action.confidence_kind, 'not_reported')
        self.assertEqual(len(result.action.option_set_hash), 64)
        self.assertFalse(result.synthetic)
        self.assertEqual(result.action.probability_kind,'token_mass_with_abstention_residual')
        body=client.calls[0][1]['json']
        self.assertEqual(body['options']['num_predict'],1)
        self.assertFalse(body['think'])
        await backend.close();self.assertTrue(client.closed)

    async def test_option_hash_tracks_order_and_rendered_targets_not_unseen_arguments(self):
        first = request().candidates[0]
        other = replace(first, id='other', arguments={'operation':'read','path':'LICENSE.md'})
        req = replace(request(), candidates=(first, other))
        backend = OllamaBackend(model='test-local', client=Client())
        async def fingerprint(value):
            return (await backend.ask(value)).action.option_set_hash
        baseline = await fingerprint(req)
        self.assertNotEqual(baseline, await fingerprint(replace(req, candidates=(other, first))))
        changed = replace(first, arguments={'operation':'read','path':'CHANGED.md'})
        self.assertNotEqual(baseline, await fingerprint(replace(req, candidates=(changed, other))))
        # Changing state or non-model-facing metadata must not change the option fingerprint.
        hidden = replace(first, label='hidden label', arguments={**first.arguments, 'private':'not sent'})
        self.assertEqual(baseline, await fingerprint(replace(req, candidates=(hidden, other), state={})))

    async def test_missing_scores_and_bad_models_fail_closed(self):
        for change in ({'logprobs':[]},{'model':'different'},{'thinking':'hidden'},
                       {'eval_count':2},{'done':False}):
            with self.subTest(change=change):
                with self.assertRaises(BackendUnavailable):
                    await OllamaBackend(model='test-local',client=Client({**payload(),**change})).ask(request())

    async def test_timeout_and_cancellation_cancel_http_exchange(self):
        client=Client(delay=1)
        with self.assertRaises(TimeoutError):
            await OllamaBackend(model='test-local',client=client,timeout_ms=10).ask(request())
        self.assertTrue(client.cancelled)
        client=Client(delay=1)
        task=asyncio.create_task(OllamaBackend(model='test-local',client=client).ask(request()))
        await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(client.cancelled)

    async def test_redirect_is_not_a_success(self):
        with self.assertRaises(BackendUnavailable):
            await OllamaBackend(model='test-local',client=Client(status=302)).ask(request())

    async def test_unsupported_questions_and_oversize_state_never_call_model(self):
        client=Client();backend=OllamaBackend(client=client)
        with self.assertRaises(BackendUnavailable):await backend.ask(request(questions=('unsupported',)))
        big=DecisionRequest(state={'observations':[{'role':'user','text':'x'*10000}]},candidates=request().candidates)
        with self.assertRaises(BackendUnavailable):await backend.ask(big)
        self.assertEqual(client.calls,[])

    async def test_prompt_excludes_instruction_hints_and_arguments(self):
        req=DecisionRequest(state={'observations':[{'role':'user','text':'Read README.md'}],
                                   'instruction':'ANSWER_HINT'},
            candidates=(Candidate('read','Read README.md','fast_workspace',{'operation':'read','path':'README.md','private':'PRIVATE_ARGUMENT'}),))
        body,_=OllamaBackend().request_body(req)
        self.assertNotIn('ANSWER_HINT',json.dumps(body))
        self.assertNotIn('PRIVATE_ARGUMENT',json.dumps(body))

    def test_nonlocal_origins_rejected(self):
        for url in ('https://example.com','http://localhost','http://127.0.0.1.evil',
                    'http://user:secret@127.0.0.1','http://127.0.0.1/proxy','http://127.0.0.1?x=1'):
            with self.subTest(url=url),self.assertRaises(ValueError):local_url(url)
        self.assertEqual(local_url('http://127.0.0.1:11434'),'http://127.0.0.1:11434/api/generate')

    def test_runtime_candidate_description_identifies_the_prepared_target(self):
        from amplifier_fast_decisions.workspace import WorkspaceTool
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'README.md').write_text('public fixture')
            candidate=WorkspaceTool(tmp).candidate_for_path('README.md',0)
            body,_=OllamaBackend().request_body(DecisionRequest(
                state={'observations':[]},candidates=(candidate,)))
            self.assertIn('README.md',body['prompt'])
            self.assertNotIn(tmp,body['prompt'])

    def test_unrecognized_tokens_abstain_without_renormalization(self):
        p=payload();p['logprobs'][0]['top_logprobs']=[{'token':'The','logprob':math.log(.99)}]
        self.assertEqual(score_tokens(p,{'A':'read'}),{'read':0,'reason':1})

    def test_invalid_probability_rejected(self):
        for lp in (float('nan'),float('inf'),1,True):
            p=payload();p['logprobs'][0]['top_logprobs'][0]['logprob']=lp
            with self.assertRaises(BackendUnavailable):score_tokens(p,{'A':'read'})

    def test_local_active_profile_needs_no_external_opt_in(self):
        from amplifier_fast_decisions.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'profile.md'
            self.assertEqual(main(['configure','--bundle-root',str(Path(__file__).resolve().parents[1]),
                '--workspace',tmp,'--mode','active','--backend','ollama','--model','test-local',
                '--timeout-ms','500','--local-sources','--output',str(out)]),0)
            data=json.loads(out.read_text().split('---')[1]);config=data['session']['orchestrator']['config']
            self.assertEqual(config['backend'],'ollama')
            self.assertEqual(config['model'],'test-local')
            self.assertFalse(config['allow_external_state'])
            self.assertTrue(data['session']['orchestrator']['source'].startswith('file://'))
