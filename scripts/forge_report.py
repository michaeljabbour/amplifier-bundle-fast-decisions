#!/usr/bin/env python3
"""Read-only progress and final report for a frozen Forge experiment."""
from __future__ import annotations
from datetime import datetime
import json
import math
from pathlib import Path
import sys

from forge_workloads import SPECS


def native_detail(workspace, sid):
    slug=str(workspace.resolve()).replace('/','-').replace('\\','-').replace(':','')
    path=Path.home()/'.amplifier/projects'/slug/'sessions'/sid/'events.jsonl'
    start=end=None;orchestrator=None;model_names=set()
    for line in path.open():
        try:e=json.loads(line)
        except ValueError:continue
        data=e.get('data',{})
        if e.get('event')=='execution:start':start=e.get('ts')
        if e.get('event')=='execution:end':end=e.get('ts')
        if e.get('event')=='llm:request' and data.get('model'):model_names.add(data['model'])
        if e.get('event')=='session:config':
            raw=data.get('raw',{})
            if isinstance(raw,dict):
                orchestrator=raw.get('session',{}).get('orchestrator',{}).get('module')
    duration=(datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()*1000 if start and end else None
    return {'execution_wall_ms':duration,'orchestrator_recorded':orchestrator,'models_observed':sorted(model_names)}


def report(root):
    manifest=json.loads((root/'manifest.json').read_text());runs={}
    for name in manifest['run_order']:
        path=root/name/'result.json'
        if not path.exists():continue
        r=json.loads(path.read_text())
        if r.get('session_id'):r['native_detail']=native_detail(root/name/'workspace',r['session_id'])
        r['usage_receipts_complete']=r['native']['provider_requests']==r['native']['provider_responses'] and r['native']['execution_completed']
        starts={};latencies=[];routes=[];fast_ids=set();tool_ends={};active_scores=shadow_scores=0
        for line in (root/name/'receipts.jsonl').read_text().splitlines():
            e=json.loads(line);key=(e['session_id'],e.get('decision_id'));kind=e['event'].split(':')[-1]
            if kind=='scored':active_scores+=1
            if kind=='shadow_proposed':shadow_scores+=1
            if kind=='tool_end':tool_ends[key]=e['data']
            if kind=='requested':starts[key]=e
            if kind=='routed':
                routes.append({k:e['data'].get(k) for k in ['route','status','reason_code','destination']})
                if e['data'].get('route')=='fast' and e['data'].get('status')=='submitted_to_upstream':fast_ids.add(key)
                if key in starts:
                    delta=(datetime.fromisoformat(e['timestamp'])-datetime.fromisoformat(starts[key]['timestamp'])).total_seconds()*1000
                    if delta>=0:latencies.append(delta)
        latencies.sort()
        r['routing_evidence']={'routes':routes,'request_to_route_count':len(latencies),
            'active_scores':active_scores,'shadow_scores':shadow_scores,
            'fast_execution_successes':sum(key in tool_ends and (tool_ends[key].get('success') is True or tool_ends[key].get('status')=='ok') and tool_ends[key].get('success') is not False and tool_ends[key].get('status') not in ['error','cancelled'] for key in fast_ids),
            'fast_execution_receipts':sum(key in tool_ends for key in fast_ids),
            'request_to_route_p95_ms':latencies[math.ceil(.95*len(latencies))-1] if latencies else None,
            'request_to_route_max_ms':max(latencies,default=None),
            'request_to_route_over_500ms':sum(x>=500 for x in latencies),
            'boundary':'Recorded request to route; excludes candidate preparation before request receipt'}
        runs[name]=r
    pairs=[]
    for task in SPECS:
        a,b=runs.get(task+'-baseline'),runs.get(task+'-fast')
        if not a or not b:continue
        fields={}
        for key in ['provider_requests','provider_responses','tool_results','provider_retries','tool_failures_reported']:
            fields[key]=a['native'][key]-b['native'][key]
        for key in ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','cost_usd']:
            x,y=a['native']['usage'][key],b['native']['usage'][key]
            fields[key]=x-y if x is not None and y is not None and a['usage_receipts_complete'] and b['usage_receipts_complete'] else None
        fields['wall_time_ms']=a['wall_time_ms']-b['wall_time_ms']
        x,y=a['native_detail']['execution_wall_ms'],b['native_detail']['execution_wall_ms']
        fields['execution_wall_ms']=x-y if x is not None and y is not None else None
        pairs.append({'task':task,'both_outcomes_passed':a['outcome_passed'] and b['outcome_passed'],
                      'timing_censored':a['timed_out'] or b['timed_out'],
                      'baseline_minus_fast':fields,'fast_bypasses':b['measurements']['totals']['provider_calls_bypassed'],
                      'fast_fallbacks':b['measurements']['totals']['fallback_reasons']})
    aggregate={}
    for side in ['baseline','fast']:
        selected=[r for r in runs.values() if r['side']==side]
        costs=[r['native']['usage']['cost_usd'] if r['usage_receipts_complete'] else None for r in selected]
        aggregate[side]={'completed_runs':len(selected),'passed_runs':sum(r['outcome_passed'] for r in selected),
            'wall_time_ms':sum(r['wall_time_ms'] for r in selected),
            'provider_requests':sum(r['native']['provider_requests'] for r in selected),
            'tool_results':sum(r['native']['tool_results'] for r in selected),
            'bypasses':sum(r['measurements']['totals']['provider_calls_bypassed'] for r in selected),
            'fast_execution_successes':sum(r['routing_evidence']['fast_execution_successes'] for r in selected),
            'independent_checks_passed':sum(r['quality']['passed'] for r in selected),
            'independent_checks_total':sum(r['quality']['checks'] for r in selected),
            'provider_estimated_cost_usd':sum(costs) if selected and all(c is not None for c in costs) else None}
    intervals=[]
    for name,r in runs.items():
        started=json.loads((root/name/'running.json').read_text())['started_at']
        t=datetime.fromisoformat(started).timestamp()
        intervals.append({'name':name,'start':t,'end':t+r['wall_time_ms']/1000})
    intervals.sort(key=lambda item:item['start'])
    serial=all(a['end']<=b['start'] for a,b in zip(intervals,intervals[1:]))
    output={'manifest':manifest,'runs':runs,'pairs':pairs,'aggregate':aggregate,'serial_execution_verified':serial,'complete':len(runs)==6,
            'limitations':['Three task pairs, one run per variant; no statistical speedup claim.',
                'Native upstream baseline retains passive telemetry and the same read-only tool; it performs no fast or shadow inference.',
                'Immutable provider serving revision is unknown. Requested model is fixed and observed model names are recorded.',
                'Provider-reported cost is an estimate, not independently reconciled billing. Cache warmth and run order can affect results.',
                'The local decision model is warmed outside timing. Full CLI time includes startup; execution time is shown separately.',
                'Withheld checks are outside the workspace, not enforced by an OS sandbox. Agents receive the same public specification.',
                'The benchmark freezes one prompt per task; a changed decision strategy can cause different downstream tool trajectories.',
                'Successful tool execution alone does not establish task quality; independent functional checks are evaluated separately.',
                'Each run has a fixed 480-second agent deadline. Deadline failures remain in the results.']}
    (root/'report.json').write_text(json.dumps(output,indent=2)+'\n')
    passed=sum(r['outcome_passed'] for r in runs.values());timeouts=sum(r['timed_out'] for r in runs.values())
    lines=['# Forge end-to-end comparison','',f"Source: `{manifest['installed_commit']}`. {len(runs)} of six planned real Amplifier runs collected through Forge: {passed} finished and passed the run gate; {timeouts} hit the fixed eight-minute deadline.",
           '', '| Task | Variant | CLI seconds | Execution seconds | Provider calls | Tool results | Bypasses | Independent checks | Outcome |',
           '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for name in manifest['run_order']:
        if name not in runs:continue
        r=runs[name];q=r['quality'];n=r['native'];d=r['native_detail'];m=r['measurements']['totals']
        sec=lambda ms:f'{ms/1000:.2f}' if ms is not None else 'unknown'
        wall=sec(r['wall_time_ms'])+(' (timeout)' if r['timed_out'] else '')
        lines.append(f"| {r['task']} | {r['side']} | {wall} | {sec(d['execution_wall_ms'])} | {n['provider_requests']} | {n['tool_results']} | {m['provider_calls_bypassed']} | {q['passed']}/{q['checks']} | {'pass' if r['outcome_passed'] else 'FAIL'} |")
    lines+=['','## Interpretation','']
    for pair in pairs:
        d=pair['baseline_minus_fast'];time=d['wall_time_ms']/1000
        timing='A deadline censored at least one run; a completed-task speed comparison is unavailable' if pair['timing_censored'] else f"fast was {abs(time):.2f} seconds {'faster' if time>0 else 'slower'} overall"
        lines.append(f"- **{pair['task']}**: {timing}; {pair['fast_bypasses']} confirmed bypass(es); observed provider-call difference {d['provider_requests']:+d}; tool-result difference {d['tool_results']:+d}. Both checked outcomes passed: {pair['both_outcomes_passed']}.")
    if output['complete']:
        lines+=['', 'Observed totals across the three tasks (one run per task and variant):', '',
            '| Variant | Observed seconds (censored at deadline) | Provider calls | Tool results | Completed and passed | Provider estimated USD |',
            '|---|---:|---:|---:|---:|---:|']
        for side,a in aggregate.items():
            cost=f"${a['provider_estimated_cost_usd']:.4f}" if a['provider_estimated_cost_usd'] is not None else 'unknown'
            lines.append(f"| {side} | {a['wall_time_ms']/1000:.2f} | {a['provider_requests']} | {a['tool_results']} | {a['passed_runs']}/{a['completed_runs']} | {cost} |")
        lines+=['', 'These sums describe this sample; they do not isolate a causal effect of routing or establish expected production savings. A timeout is a censored interval, not a completed-task latency. Counts from incomplete runs do not establish savings at equivalent completed work.']
    lines+=['','## Routing latency','',
        'Request-to-route latency includes scoring and policy after the request receipt. It excludes candidate preparation before that receipt. These are local warm-model observations, not hosted network benchmarks. The 500 ms target applies to this decision boundary, not whole coding-task completion.', '',
        '| Task | Active / shadow scores | Scoring p95 ms | Request-to-route p95 ms | Max ms | Routes ≥500 ms | Bypasses / successful fast executions |',
        '|---|---:|---:|---:|---:|---:|---:|']
    number=lambda value:f'{value:.2f}' if isinstance(value,(int,float)) else 'unknown'
    for name,r in runs.items():
        if r['side']!='fast':continue
        m=r['measurements']['totals'];e=r['routing_evidence']
        lines.append(f"| {r['task']} | {e['active_scores']} / {e['shadow_scores']} | {number(m['decision_scoring_p95_ms'])} | {number(e['request_to_route_p95_ms'])} | {number(e['request_to_route_max_ms'])} | {e['request_to_route_over_500ms']}/{e['request_to_route_count']} | {m['provider_calls_bypassed']} / {e['fast_execution_successes']} |")
    lines+=['', 'Scoring p95 includes active and shadow scoring. Shadow evaluations measure alternative proposals; they do not bypass generation.']
    lines+=['','## Provider usage and estimates','',
        'Cost is the sum reported by the provider adapter, not verified billing. Cache read/write tokens are shown separately; do not add them to reported input tokens. The baseline runs the upstream orchestrator, so provider calls are counted from native SDK receipts in both variants, not from the fast wrapper alone.', '',
        '| Run | Input tokens | Output tokens | Cache read | Cache write | Estimated USD | Retries | Deadline hit |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    integer=lambda value:f'{value:,.0f}' if isinstance(value,(int,float)) else 'unknown'
    for name,r in runs.items():
        n=r['native'];u=n['usage']
        cost=f"${u['cost_usd']:.4f}" if u['cost_usd'] is not None else 'unknown'
        if not r['usage_receipts_complete']:cost+=' (partial receipts)'
        lines.append(f"| {name} | {integer(u['input_tokens'])} | {integer(u['output_tokens'])} | {integer(u['cache_read_tokens'])} | {integer(u['cache_write_tokens'])} | {cost} | {n['provider_retries']} | {r['timed_out']} |")
    lines+=['','## Quality and controls','',
        'All pairs start with identical hashed workspace contents and the same prompt. The evaluator and specs were frozen before execution. Independent checks cover randomized valid inputs, invalid inputs, boundary cases and input immutability. Public tests and all agent-authored unittest tests also run after the session exits.', '',
        '| Run | Orchestrator observed | Independent checks | Public tests | Workspace tests | Protected files intact | Execution ended |',
        '|---|---|---:|---|---|---|---|']
    for name,r in runs.items():
        q=r['quality'];d=r['native_detail']
        lines.append(f"| {name} | {d['orchestrator_recorded']} | {q['passed']}/{q['checks']} | {r['public_tests_passed']} | {r.get('workspace_tests_passed','not collected')} | {all(r['protected_files_unchanged'].values())} | {r['native']['execution_completed']} |")
    lines+=['',f'No overlap among recorded primary agent execution intervals: **{serial}**.']
    lines+=['','## Fast fallback reasons','']
    for name,r in runs.items():
        if r['side']=='fast':lines.append(f"- {name}: `"+json.dumps(r['measurements']['totals']['fallback_reasons'],sort_keys=True)+'`.')
    if (root/'pilot-exclusion.json').exists():
        lines+=['','## Excluded pilot runs','',
            'Two initial scheduler pilots overlapped because the Forge controller treated its observation timeout as process completion. Both results are retained in the adjacent `afast-forge-evidence-20260918-01` directory; neither is included in the primary comparison. The controller was corrected and regression-tested before these six serial runs. See [pilot exclusion record](pilot-exclusion.json).']
    proof=root/'scheduler-fast/viewer-receipt-check.json'
    if proof.exists():
        v=json.loads(proof.read_text())
        lines+=['','## Live Observatory verification','',
            f"The browser captured {v['new_stages_in_20_seconds']} new stages in 20 seconds. All {v['rendered_stage_ids']} rendered stage IDs matched actual session receipts: **{v['all_rendered_ids_match']}**. Child activity was included by default: **{v['children_included']}**. Browser errors: **{len(v['browser_errors'])}**.", '',
            '[Browser-to-receipt check](scheduler-fast/viewer-receipt-check.json) · [Live screenshot](scheduler-fast/live-viewer.png) · [Product observations and follow-up hypotheses](OBSERVATIONS.md)']
    lines+=['','## Evidence limits','']+['- '+x for x in output['limitations']]
    lines+=['','## Session receipts','']
    for name,r in runs.items():
        lines.append(f"- {name}: `{r['session_id']}`; [result]({name}/result.json), [metadata receipts]({name}/receipts.jsonl), [finished implementation]({name}/workspace/solution.py).")
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'complete':output['complete'],'finished':len(runs),'runs':[{k:r[k] for k in ['name','outcome_passed','wall_time_ms']} for r in runs.values()]}))


def monitor(root):
    sys.path.insert(0,str(Path.home()/'.agents/skills/amplifier-skill-forge/tools'))
    import forge
    path=root/'forge-sessions.json'
    known=json.loads(path.read_text()) if path.exists() else {}
    terminals=forge.call('list_terminals',{})
    if terminals=='No active sessions':terminals=[]
    if not isinstance(terminals,list):raise RuntimeError('Unexpected Forge terminal-list response')
    for s in terminals:
        cwd=Path(s.get('cwd','/'))
        if root in cwd.parents:
            known[s['id']]={k:s[k] for k in ['id','pid','cwd','createdAt','status']}
            print(json.dumps({'forge_id':s['id'],'run':cwd.parent.name,'status':s['status']}))
    path.write_text(json.dumps(known,indent=2)+'\n')


if __name__=='__main__':
    root=Path(sys.argv[1]).expanduser().resolve()
    if '--monitor' in sys.argv:monitor(root)
    report(root)
