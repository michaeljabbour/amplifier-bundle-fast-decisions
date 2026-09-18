#!/usr/bin/env python3
"""Live loopback-only benchmark on public development fixtures; no tool execution.

Run with the local extra installed. Never a held-out accuracy/calibration claim.
Reports cold/warm timing separately, policy coverage, wrong accepted choices,
and reversed-order consistency. Does not send per-case instruction/answer hints.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time

from amplifier_fast_decisions.bench.suite import load_suite
from amplifier_fast_decisions.contracts import DecisionRequest
from amplifier_fast_decisions.local_backend import OllamaBackend


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)] if values else None


async def main(args):
    cases = [c for c in load_suite(args.suite) if c.domain != 'model-role']
    backend = OllamaBackend(model=args.model, timeout_ms=30000)
    rows=[]
    try:
        t=time.perf_counter()
        await backend.ask(DecisionRequest(state=cases[0].state, candidates=cases[0].candidates))
        warmup_ms=(time.perf_counter()-t)*1000
        backend.timeout_ms=args.timeout_ms
        for repeat in range(args.repeats):
            for case in cases:
                for reverse in (False,True):
                    candidates=tuple(reversed(case.candidates)) if reverse else case.candidates
                    t=time.perf_counter()
                    row={'case':case.id,'repeat':repeat,'reversed':reverse,'expected':case.expected_choice}
                    try:
                        result=await backend.ask(DecisionRequest(state=case.state,candidates=candidates))
                        d=result.action
                        p=d.probabilities[d.choice]
                        margin=p-max((v for k,v in d.probabilities.items() if k!=d.choice),default=0)
                        accepted=d.choice!='reason' and p>=.90 and margin>=.20
                        row.update(choice=d.choice,probability=p,margin=margin,
                                   policy_choice=d.choice if accepted else 'reason',accepted=accepted,
                                   correct=d.choice==case.expected_choice,
                                   wrong_accepted=accepted and d.choice!=case.expected_choice,
                                   input_tokens=result.input_tokens,probability_kind=d.probability_kind)
                    except Exception as exc:
                        row.update(error=type(exc).__name__,accepted=False,wrong_accepted=False)
                    row['duration_ms']=(time.perf_counter()-t)*1000;rows.append(row)
    finally:
        await backend.close()
    durations=[r['duration_ms'] for r in rows]
    pairs=[(rows[i],rows[i+1]) for i in range(0,len(rows),2)]
    report={'created_at':datetime.now(timezone.utc).isoformat(),'model':args.model,
            'backend':'ollama-token','external_state':False,'target_ms':args.timeout_ms,
            'suite':str(args.suite),'suite_kind':'public development fixtures, not held-out evaluation',
            'warmup_ms':warmup_ms,'requests':len(rows),'errors':sum('error' in r for r in rows),
            'warm_p50_ms':statistics.median(durations),'warm_p95_ms':percentile(durations,.95),
            'warm_max_ms':max(durations),'under_target':sum(v<args.timeout_ms for v in durations),
            'argmax_agreement':sum(r.get('correct',False) for r in rows)/len(rows),
            'policy_agreement':sum(r.get('policy_choice')==r['expected'] for r in rows)/len(rows),
            'accepted':sum(r['accepted'] for r in rows),'wrong_accepted':sum(r['wrong_accepted'] for r in rows),
            'order_stable_pairs':sum(a.get('choice')==b.get('choice') and 'error' not in a and 'error' not in b for a,b in pairs),
            'pairs':len(pairs),'rows':rows}
    if args.output:
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',default='qwen3:0.6b')
    p.add_argument('--suite',default='suites/v1.jsonl')
    p.add_argument('--timeout-ms',type=int,default=500)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--output')
    args=p.parse_args()
    if args.repeats<1:p.error('--repeats must be positive')
    asyncio.run(main(args))
