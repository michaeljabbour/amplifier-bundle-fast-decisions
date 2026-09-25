#!/usr/bin/env python3
"""Explicit live Amplifier comparison on disposable public fixtures.

Uses the existing configured generative provider (may incur normal API charges).
Creates project-local profiles only. No global configuration or model parameters
are changed. Baseline uses the same instrumented orchestrator with decisions off.
These development fixtures are not a held-out quality certification.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import urllib.request

from amplifier_fast_decisions.cli import main as afast
from amplifier_fast_decisions.operations import compare, read_receipts


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def response_text(stdout):
    # Amplifier's JSON output may follow human-readable startup lines.
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != '{':
            continue
        try:
            result, _ = decoder.raw_decode(stdout[index:])
        except ValueError:
            continue
        if isinstance(result, dict) and isinstance(result.get('response'), str):
            return result['response']
    return None


def run(args):
    root = Path(__file__).resolve().parents[1]
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root/'src')
    env['AFAST_OBSERVATORY'] = 'off'
    # AMPLIFIER_MEMORY_CAPTURE=off: this launches the real `amplifier run`
    # CLI, which inherits os.environ (and with it whatever memory bundle is
    # installed) -- without this every paired-comparison run below writes a
    # memory capture per tool call. amplifier-bundle-memory's automation_gate
    # module honors this var; harmless no-op on older/no memory bundle.
    env['AMPLIFIER_MEMORY_CAPTURE'] = 'off'
    cases = [('extract-a', 'Juniper', 'amber'), ('extract-b', 'Zircon', 'indigo')]
    manifest = {'schema_version':'paired-runs-v1', 'pairs':[]}
    for i, (task, codename, channel) in enumerate(cases):
        text = f'The project codename is {codename}. The release channel is {channel}.\n'
        expected = f'{codename}|{channel}'
        prompt = "Read README.md, not LICENSE.md. Return exactly the project's codename and release channel in the format codename|channel, with no other text."
        pair = {'task_id':task, 'split':'development'}
        # Counterbalance order; this is still a tiny development sample.
        for side in (('baseline','enabled') if i == 0 else ('enabled','baseline')):
            run_dir = out/task/side
            workspace = run_dir/'workspace'
            (workspace/'.amplifier').mkdir(parents=True)
            (workspace/'README.md').write_text(text)
            (workspace/'LICENSE.md').write_text('This is the public license fixture, not project metadata.\n')
            (workspace/'.amplifier'/'settings.local.yaml').write_text('bundle:\n  app: []\n')
            events = run_dir/'events'
            profile = run_dir/'profile.md'
            with contextlib.redirect_stdout(io.StringIO()):
                code = afast(['configure','--bundle-root',str(root),'--workspace',str(workspace),
                    '--mode','active','--backend','ollama','--model',args.decision_model,
                    '--timeout-ms','500','--events',str(events),'--local-sources','--output',str(profile)])
            if code:
                raise RuntimeError('Could not generate local profile')
            data = json.loads(profile.read_text().split('---')[1])
            config = data['session']['orchestrator']['config']
            config.update(mode='off' if side == 'baseline' else 'active', max_fast_per_turn=1,
                          upstream={'max_iterations':4,'extended_thinking':False})
            data['bundle']['name'] = f'paired-{task}-{side}'
            profile.write_text('---\n'+json.dumps(data,indent=2)+'\n---\n')
            warm = urllib.request.Request('http://127.0.0.1:11434/api/generate',
                data=json.dumps({'model':args.decision_model,'stream':False,'keep_alive':'10m','options':{'num_ctx':4096}}).encode(),
                headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(warm,timeout=30) as result:
                json.load(result)
            started = time.perf_counter()
            command = [args.amplifier, 'run', '--bundle',profile.as_uri(),'--mode','single',
                       '--provider',args.provider,'--model',args.model,'--output-format','json',prompt]
            try:
                result = subprocess.run(command,cwd=workspace,env=env,capture_output=True,text=True,timeout=args.timeout)
                code = result.returncode
                answer = response_text(result.stdout)
            except subprocess.TimeoutExpired:
                code, answer = -1, None
            wall_ms = (time.perf_counter()-started)*1000
            receipts, _ = read_receipts(events)
            roots = {e['session_id'] for e in receipts if e['event']=='fast_decisions:turn_start' and not e.get('parent_session_id')}
            if len(roots) != 1:
                raise RuntimeError('Expected one instrumented root session; inspect the isolated receipt directory')
            pair[side] = {'events':str(events.relative_to(out)), 'session_id':roots.pop(), 'wall_time_ms':wall_ms,
                          'task_fingerprint':fingerprint(prompt), 'workspace_fingerprint':fingerprint(json.dumps({str(p.relative_to(workspace)):p.read_text() for p in sorted(workspace.rglob('*')) if p.is_file() and p.name in {'README.md','LICENSE.md','settings.local.yaml'}}, sort_keys=True)),
                          'provider_model':args.model, 'provider_revision':args.provider_revision,
                          'decision_model':args.decision_model, 'hardware':platform.platform(),
                          'outcome':{'passed':code==0 and answer is not None and answer.strip()==expected,
                                     'evaluator':'exact-public-fields-v1',
                                     'checks':{'process_succeeded':code==0, 'exact_answer':answer is not None and answer.strip()==expected}}}
            # Persist no provider output, prompts, credentials or private context in the report.
            print(json.dumps({'task':task,'side':side,'exit_code':code,'outcome':pair[side]['outcome']['passed'],'wall_time_ms':round(wall_ms,1)}),flush=True)
        manifest['pairs'].append(pair)
        (out/'runs.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (out/'comparison.json').write_text(json.dumps(compare(manifest,base_dir=out),indent=2)+'\n')
    print(str(out/'comparison.json'))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,help='New directory for public fixtures and receipts')
    parser.add_argument('--amplifier',default='amplifier')
    parser.add_argument('--provider',required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--provider-revision',default='unknown',help='Verified immutable revision if available; unknown prevents a comparability claim')
    parser.add_argument('--decision-model',default='qwen3:0.6b')
    parser.add_argument('--timeout',type=int,default=180)
    run(parser.parse_args())
