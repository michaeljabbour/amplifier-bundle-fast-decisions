"""Operational counts and comparison gates, independent of model correctness."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from amplifier_fast_decisions.operations import compare, diagnose, measure, read_receipts, summarize


def event(sid, kind, data=None, *, parent=None, decision='d', idx=1, synthetic=False):
    return {'event_id': f'{sid}-{kind}-{idx}', 'session_id': sid, 'parent_session_id': parent,
            'event': 'fast_decisions:' + kind, 'decision_id': decision, 'turn_id': 'turn',
            'timestamp': datetime.now(timezone.utc).isoformat(), 'seq': idx,
            'synthetic': synthetic, 'data': data or {}}


def complete(sid, *, parent=None, calls=1):
    rows = [event(sid, 'turn_start', parent=parent)]
    for i in range(calls):
        rows += [event(sid, 'slow_start', {'provider_call_id': str(i)}, idx=i, parent=parent),
                 event(sid, 'slow_end', {'provider_call_id': str(i), 'status':'ok', 'input_tokens':10, 'output_tokens':2, 'total_tokens':12}, idx=i, parent=parent)]
    rows += [event(sid, 'turn_end', {'status':'ok'}, parent=parent)]
    return rows


class OperationsTests(unittest.TestCase):
    def test_parent_child_grandchild_and_duplicate_receipts_count_once(self):
        rows = complete('root', calls=2) + complete('child', parent='root') + complete('grandchild', parent='child') + complete('elsewhere')
        result = summarize(rows + rows, session_id='root')
        self.assertEqual(result['scope']['sessions'], 3)
        self.assertEqual(result['totals']['provider_calls_started'], 4)
        self.assertEqual(result['totals']['provider_usage']['total_tokens'], 48)
        self.assertTrue(result['totals']['instrumented_coverage_complete'])
        self.assertEqual(sum(s['counts']['provider_calls_started'] for s in result['sessions']), 4)

    def test_advisory_scripted_and_native_hooks_never_claim_execution(self):
        rows = [event('s', 'requested', {'mode':'advisory'}), event('s', 'scored', {'duration_ms':20}),
                event('s', 'health', {'native_event':'tool:post', 'tool_call_id':'x'}, decision=None),
                event('fixture', 'scored', {'synthetic':True}),
                event('fixture', 'routed', {'route':'fast','status':'submitted_to_upstream'})]
        counts = summarize(rows)['totals']
        self.assertEqual(counts['decisions_scored'], 1)
        self.assertEqual(counts['provider_calls_bypassed'], 0)
        self.assertEqual(counts['tool_executions_started'], 0)
        self.assertEqual(counts['tool_post_observed'], 1)
        self.assertIsNone(counts['tool_calls_eliminated'])
        self.assertIsNone(counts['net_cost_saved_usd'])
        self.assertFalse(counts['instrumented_coverage_complete'])

    def test_denied_submission_is_bypass_without_tool_execution(self):
        counts = summarize([event('s', 'routed', {'route':'fast','status':'submitted_to_upstream'})])['totals']
        self.assertEqual(counts['provider_calls_bypassed'], 1)
        self.assertEqual(counts['tool_executions_successful'], 0)

    def test_incomplete_mismatched_and_missing_usage_remain_unknown(self):
        rows = complete('s')
        rows[2]['data']['provider_call_id'] = 'unmatched'
        rows[2]['data'].pop('input_tokens')
        counts = summarize(rows)['totals']
        self.assertFalse(counts['instrumented_coverage_complete'])
        self.assertIsNone(counts['provider_usage']['input_tokens'])
        self.assertIsNone(counts['provider_usage']['output_tokens'])
        partial = complete('root') + [event('child', 'health', {'native_event':'provider:request'}, parent='root')]
        self.assertFalse(summarize(partial)['totals']['instrumented_coverage_complete'])

    def test_diagnostics_do_not_infer_composition_from_installation_or_leak_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); events=root/'events'; events.mkdir()
            (events/'s.jsonl').write_text(json.dumps(event('s','health',{'phase':'configuration','backend':'scripted-demo','mode':'shadow'}))+'\n')
            state=root/'state.json'
            state.write_text(json.dumps({'url':'http://127.0.0.1:7777/#token=DO_NOT_PRINT','events_dir':str(events)}))
            def get(url,headers=None):
                if url.endswith('/api/tags'): return {'models':[{'name':'qwen3:0.6b','digest':'revision'}]}
                if url.endswith('/api/ps'): return {'models':[]}
                self.assertEqual(headers, {'Authorization':'Bearer DO_NOT_PRINT'})
                return {'read_only':True}
            with patch('amplifier_fast_decisions.operations._get_json', get):
                report=diagnose(events_dir=events,state_file=state)
            self.assertEqual(report['viewer']['status'],'connected')
            self.assertTrue(report['viewer']['events_directory_matches'])
            self.assertEqual(report['activity']['sessions'][0]['integration'],'scripted_shadow')
            self.assertNotIn('DO_NOT_PRINT',json.dumps(report))
            absent=diagnose(events_dir=root/'missing',probe=False)
            self.assertEqual(absent['activity']['scope']['sessions'],0)
            self.assertFalse((root/'missing').exists())

    def test_remote_viewer_url_never_receives_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state.json'
            state.write_text(json.dumps({'url':'http://remote.example/#token=SECRET','events_dir':tmp}))
            with patch('amplifier_fast_decisions.operations._get_json', return_value={'models':[]}) as get:
                result=diagnose(events_dir=tmp,state_file=state)
            self.assertEqual(result['viewer']['status'],'disconnected_or_invalid')
            self.assertTrue(all('remote.example' not in c.args[0] for c in get.call_args_list))

    def test_partial_invalid_and_truncated_sources_report_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.jsonl'
            path.write_text('bad\n'+json.dumps(event('s','health',{'native_event':[]}))+'\n'+''.join(json.dumps(e)+'\n' for e in complete('s'))+'{"partial"')
            rows, source=read_receipts(path,capacity=2)
            self.assertEqual(source['invalid_records'],2)
            self.assertTrue(source['truncated'])
            self.assertEqual(len(rows),2)

    def test_comparison_rejects_quality_regressions_and_unmatched_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.jsonl'
            path.write_text(''.join(json.dumps(e)+'\n' for e in complete('baseline',calls=2)+complete('enabled')))
            common={'events':'trace.jsonl','task_fingerprint':'taskhash','workspace_fingerprint':'workhash',
                    'provider_model':'model','provider_revision':'version','hardware':'host',
                    'outcome':{'passed':True,'evaluator':'exact-match-v1','checks':{'output':True}}}
            payload={'schema_version':'paired-runs-v1','pairs':[{'task_id':'t','split':'held_out',
                'baseline':{**common,'session_id':'baseline','wall_time_ms':100},
                'enabled':{**common,'session_id':'enabled','wall_time_ms':150}}]}
            report=compare(payload,base_dir=tmp)
            self.assertTrue(report['all_pairs_eligible'])
            delta=report['pairs'][0]['baseline_minus_enabled']
            self.assertEqual(delta['provider_calls_started'],1)
            self.assertEqual(delta['wall_time_ms'],-50)  # Slower overall despite fewer calls.
            self.assertIsNone(delta['cost_usd'])
            changed=copy.deepcopy(payload)
            changed['pairs'][0]['enabled']['outcome']['checks']['output']=False
            self.assertFalse(compare(changed,base_dir=tmp)['all_pairs_eligible'])
            changed=copy.deepcopy(payload)
            changed['pairs'][0]['enabled']['outcome']={'passed':True,'evaluator':'another-check','checks':{'output':True}}
            self.assertFalse(compare(changed,base_dir=tmp)['all_pairs_eligible'])
            changed=copy.deepcopy(payload)
            changed['pairs'][0]['enabled']['provider_revision']='changed'
            self.assertFalse(compare(changed,base_dir=tmp)['all_pairs_eligible'])
            changed=copy.deepcopy(payload)
            for side in ('baseline','enabled'):changed['pairs'][0][side]['provider_revision']='unknown'
            self.assertFalse(compare(changed,base_dir=tmp)['all_pairs_eligible'])


if __name__=='__main__':unittest.main()
