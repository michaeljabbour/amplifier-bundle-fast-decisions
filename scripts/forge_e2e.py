#!/usr/bin/env python3
"""Run six real Amplifier coding sessions through Forge, with independent checks.

Explicit opt-in: this invokes the configured paid generative provider and lets
agents edit only disposable workspaces. It never changes global host settings.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import time
import urllib.request

from forge_workloads import SPECS, STARTERS, PUBLIC, evaluate

FORGE = Path.home()/'.agents/skills/amplifier-skill-forge/tools/forge.py'
CACHE = Path.home()/'.amplifier/cache/amplifier-bundle-fast-decisions-703c3edc7c970204'
EVENTS = Path.home()/'.amplifier/fast-decisions/events'
HOST_PYTHON = Path.home()/'.local/share/uv/tools/amplifier/bin/python'
PROMPT = ('Read README.md first, then repair the implementation to satisfy its full contract. '
          'Work directly in this workspace without delegating or using the network. '
          'Modify solution.py and add tests if useful, but do not change README.md or existing test_public.py. '
          'Run the tests and explain your fix and validation. Do not inspect files outside this workspace.')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def hash_files(workspace):
    files={str(p.relative_to(workspace)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(workspace.rglob('*')) if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    installed_commit=subprocess.check_output(['git','-C',str(CACHE),'rev-parse','HEAD'],text=True).strip()
    versions={name:metadata.version(name) for name in ['amplifier-app-cli','amplifier-core','amplifier-foundation','amplifier-module-loop-streaming','amplifier-provider-anthropic'] if available(name)}
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as response:
        models=json.load(response)['models']
    local=next(m for m in models if m['name']=='qwen3:0.6b')
    manifest={'schema':'forge-e2e-v1','created_at':datetime.now(timezone.utc).isoformat(),
              'installed_commit':installed_commit,'python':platform.python_version(),
              'hardware':platform.platform(),'packages':versions,'provider':'anthropic',
              'model':'claude-fable-5-1','provider_revision':'unknown',
              'decision_model':'qwen3:0.6b','decision_model_digest':local.get('digest'),
              'prompt':PROMPT,'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
              'evaluator_sha256':hashlib.sha256(Path(__file__).with_name('forge_workloads.py').read_bytes()).hexdigest(),
              'run_order':[],'runs':{},'limits':{'max_iterations':30,'extended_thinking':True,'timeout_seconds':480}}
    upstream={'max_iterations':30,'extended_thinking':True}
    for i,task in enumerate(SPECS):
        for side in ['baseline','fast']:
            name=f'{task}-{side}';run=root/name;workspace=run/'workspace';(workspace/'.amplifier').mkdir(parents=True)
            (workspace/'README.md').write_text(SPECS[task]);(workspace/'solution.py').write_text(STARTERS[task])
            (workspace/'test_public.py').write_text(PUBLIC[task]);(workspace/'.amplifier/settings.local.yaml').write_text('bundle:\n  app: []\n')
            subprocess.run(['git','init','-q',str(workspace)],check=True)
            config={'mode':'active' if side=='fast' else 'off','backend':'ollama','model':'qwen3:0.6b',
                    'allow_external_state':False,'timeout_ms':500,'min_probability':.90,'min_margin':.20,
                    'max_fast_streak':3,'max_fast_per_turn':12,'max_candidates':12,'max_state_chars':2048,
                    'allowed_tools':['fast_workspace'],'events_dir':str(EVENTS),'upstream':upstream}
            observer={**config,'session_label':f'Forge {task} / {side}','observatory':{'enabled':False}}
            loop=({'module':'loop-fast-decisions','source':(CACHE/'modules/loop-fast-decisions').as_uri(),'config':config}
                  if side=='fast' else {'module':'loop-streaming','source':'git+https://github.com/microsoft/amplifier-module-loop-streaming@20aac7a9eb26034d230357f6aa6805f27c86df52','config':upstream})
            profile={'bundle':{'name':f'forge-{name}','version':'0.1.0'},'includes':[{'bundle':CACHE.as_uri()}],
                     'session':{'orchestrator':loop},
                     'tools':[{'module':'tool-fast-workspace','source':(CACHE/'modules/tool-fast-workspace').as_uri(),'config':{'root':str(workspace)}}],
                     'hooks':[{'module':'hooks-fast-decisions','source':(CACHE/'modules/hooks-fast-decisions').as_uri(),'config':observer}]}
            (run/'profile.md').write_text('---\n'+json.dumps(profile,indent=2)+'\n---\n')
            manifest['runs'][name]={'task':task,'side':side,'workspace_hash':hash_files(workspace),
                                    'profile_sha256':hashlib.sha256((run/'profile.md').read_bytes()).hexdigest()}
        manifest['run_order'] += [f'{task}-{side}' for side in (['baseline','fast'] if i%2==0 else ['fast','baseline'])]
        assert manifest['runs'][f'{task}-baseline']['workspace_hash']==manifest['runs'][f'{task}-fast']['workspace_hash']
    dump(root/'manifest.json',manifest)
    print(json.dumps({'prepared':str(root),'runs':manifest['run_order'],'installed_commit':installed_commit}))


def available(name):
    try:metadata.version(name);return True
    except metadata.PackageNotFoundError:return False


def native_summary(session_dir):
    counts=Counter(); usage=Counter(); usage_known=Counter(); durations=[]; tools=[]; complete=False
    path=session_dir/'events.jsonl'
    for line in path.open():
        try:e=json.loads(line)
        except ValueError:continue
        name=e.get('event');d=e.get('data',{});counts[name]+=1
        if name=='llm:response':
            if isinstance(e.get('duration_ms'),(int,float)):durations.append(e['duration_ms'])
            for key in ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','cost_usd']:
                v=d.get('usage',{}).get(key)
                if v is not None:
                    try:usage[key]+=float(v);usage_known[key]+=1
                    except (TypeError,ValueError):pass
        if name=='tool:post':
            result=d.get('result',{})
            tools.append({'tool':d.get('tool_name'),'call_id':d.get('tool_call_id'),
                          'success':result.get('success') if isinstance(result,dict) else None})
        if name=='execution:end':complete=True
    return {'provider_requests':counts['llm:request'],'provider_responses':counts['llm:response'],
            'provider_retries':counts['provider:retry'],'provider_errors':counts['provider:error'],
            'tool_results':len(tools),'tool_names':dict(Counter(t['tool'] for t in tools)),
            'tool_failures_reported':sum(t['success'] is False for t in tools),'execution_completed':complete,
            'provider_response_duration_ms':sum(durations),
            'usage':{k:usage[k] if usage_known[k]==counts['llm:response'] and counts['llm:response'] else None for k in ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','cost_usd']},
            'usage_known_calls':dict(usage_known),'cost_evidence':'provider_reported_estimate_not_billing'}


def worker(root,name):
    manifest=json.loads((root/'manifest.json').read_text());run=root/name;workspace=run/'workspace';item=manifest['runs'][name]
    if hash_files(workspace)!=item['workspace_hash']:raise RuntimeError('Starting workspace changed')
    if subprocess.check_output(['git','-C',str(CACHE),'rev-parse','HEAD'],text=True).strip()!=manifest['installed_commit']:
        raise RuntimeError('Installed bundle changed during the experiment')
    warm=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps({'model':'qwen3:0.6b','stream':False,'keep_alive':'20m','options':{'num_ctx':4096}}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(warm,timeout=60) as response:json.load(response)
    slug=str(workspace.resolve()).replace('/','-').replace('\\','-').replace(':','')
    sessions=Path.home()/'.amplifier/projects'/slug/'sessions'
    before=set(sessions.iterdir()) if sessions.exists() else set()
    env=dict(os.environ,AFAST_OBSERVATORY='off');env.pop('PYTHONPATH',None)
    command=['amplifier','run','--bundle',(run/'profile.md').as_uri(),'--mode','single','--provider',manifest['provider'],'--model',manifest['model'],'--output-format','json',PROMPT]
    started=time.perf_counter();dump(run/'running.json',{'started_at':datetime.now(timezone.utc).isoformat(),'name':name,'controller_pid':os.getpid(),'tty':sys.stdout.isatty()})
    print('FORGE_E2E_STARTED '+name,flush=True)
    # Inherit the Forge PTY, including native approvals and actual terminal output.
    process=subprocess.Popen(command,cwd=workspace,env=env)
    timed_out=False
    try:code=process.wait(timeout=manifest['limits']['timeout_seconds'])
    except subprocess.TimeoutExpired:
        timed_out=True;process.terminate()
        try:code=process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();code=process.wait()
    elapsed=(time.perf_counter()-started)*1000
    # events.jsonl exists during execution; metadata.json may only be written on
    # orderly shutdown. Preserve native evidence even for deadline failures.
    found=[p for p in sessions.iterdir() if p not in before and (p/'events.jsonl').exists()] if sessions.exists() else []
    sid=found[0].name if len(found)==1 else None
    native=native_summary(found[0]) if len(found)==1 else None
    from amplifier_fast_decisions.operations import measure,read_receipts
    measured=measure(EVENTS,session_id=sid) if sid else None
    if sid:
        rows,_=read_receipts(EVENTS);ids={s['session_id'] for s in measured['sessions']}
        (run/'receipts.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in rows if e['session_id'] in ids))
    # Execute the independent evaluator in its own process with a deadline.
    try:
        test=subprocess.run([sys.executable,str(Path(__file__).resolve()),'evaluate',str(root),name],capture_output=True,text=True,timeout=45)
        quality=json.loads(test.stdout)
    except (ValueError,subprocess.TimeoutExpired):
        quality={'checks':0,'passed':0,'failed':1,'failure_labels':['evaluator_failed_or_timed_out']}
    try:
        public=subprocess.run([sys.executable,'-m','unittest','-v','test_public.py'],cwd=workspace,capture_output=True,text=True,timeout=45)
        public_ok=public.returncode==0
    except subprocess.TimeoutExpired:public_ok=False
    try:
        suite=subprocess.run([sys.executable,'-m','unittest','discover','-v'],cwd=workspace,capture_output=True,text=True,timeout=45)
        suite_ok=suite.returncode==0
    except subprocess.TimeoutExpired:suite_ok=False
    unchanged={f:(workspace/f).read_text()==text for f,text in {'README.md':SPECS[item['task']],'test_public.py':PUBLIC[item['task']]}.items()}
    result={'name':name,'task':item['task'],'side':item['side'],'session_id':sid,'exit_code':code,'timed_out':timed_out,
            'wall_time_ms':elapsed,'native':native,'measurements':measured,'quality':quality,'public_tests_passed':public_ok,
            'workspace_tests_passed':suite_ok,'protected_files_unchanged':unchanged,
            'final_solution_sha256':hashlib.sha256((workspace/'solution.py').read_bytes()).hexdigest()}
    result['outcome_passed']=code==0 and not timed_out and quality['failed']==0 and public_ok and suite_ok and all(unchanged.values())
    dump(run/'result.json',result)
    print('FORGE_E2E_FINISHED '+json.dumps({'name':name,'outcome':result['outcome_passed'],'wall_ms':round(elapsed),'checks':quality,'session_id':sid}),flush=True)
    return 0 if result['outcome_passed'] else 1


def batch(root):
    sys.path.insert(0,str(FORGE.parent))
    import forge
    manifest=json.loads((root/'manifest.json').read_text())
    for name in manifest['run_order']:
        run=root/name
        if (run/'result.json').exists():continue
        cmd=shlex.join([str(HOST_PYTHON),str(Path(__file__).resolve()),'worker',str(root),name])
        print('LAUNCH '+name,flush=True)
        try:
            result=forge.call('run_command',{'command':'/bin/zsh','args':['-lc',cmd],
                'cwd':str(run/'workspace'),'timeoutMs':60000})
        except SystemExit as exc:
            # Forge reports its observation deadline as an MCP error, but the
            # process is explicitly kept alive. A deadline is not completion.
            try:result=json.loads(str(exc).removeprefix('forge: '))
            except ValueError:raise
            if result.get('timeout') is not True:raise
        (run/'forge-output.txt').write_text(result.pop('output',''))
        dump(run/'forge-observation.json',result)
        deadline=time.monotonic()+550
        while not (run/'result.json').exists() and time.monotonic()<deadline:
            time.sleep(2)
        if not (run/'result.json').exists():
            raise RuntimeError('Worker did not produce a result; inspect the owned Forge session before proceeding')
        # Only close our own completed terminal. Keep failed experiments in the report.
        if result.get('sessionId'):
            try:forge.call('close_terminal',{'id':result['sessionId']})
            except SystemExit:pass
        outcome=json.loads((run/'result.json').read_text())
        print('COLLECT '+name+' '+str(outcome['outcome_passed']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','worker','evaluate','batch']);parser.add_argument('root',type=Path);parser.add_argument('name',nargs='?');args=parser.parse_args();root=args.root.expanduser().resolve()
    if args.command=='prepare':prepare(root)
    elif args.command=='worker':sys.exit(worker(root,args.name))
    elif args.command=='evaluate':print(json.dumps(evaluate(json.loads((root/'manifest.json').read_text())['runs'][args.name]['task'],root/args.name/'workspace')))
    else:batch(root)
