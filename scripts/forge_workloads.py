"""Public coding workloads and independent acceptance checks for Forge E2E.

Checks run outside the agent workspace after the agent exits. They are not a
security sandbox or a statistical certification of general coding quality.
"""
from __future__ import annotations

import copy
from decimal import Decimal
import importlib.util
import random
import re
from pathlib import Path

SPECS = {
    'scheduler': '''# Dependency scheduler repair
Repair `solution.py` using only the Python standard library. Keep the public
function `plan(jobs, capacity)`. Run `python3 -m unittest -v test_public.py`.

`jobs` maps nonempty string job names to dictionaries with `deps` (a list of
job names) and `duration` (a positive integer, not bool). `capacity` is a positive
integer, not bool. Reject malformed inputs, unknown dependencies, self dependencies,
and all cycles with ValueError. Duplicate dependency names count only once.
Never mutate inputs. Empty jobs is valid.

Compute each job's downstream critical length: its duration plus the maximum
critical length among its immediate dependents, or its duration if none. At each
wave, ready jobs have all dependencies completed in PREVIOUS waves. Sort ready
jobs by descending downstream critical length, then ascending name. Choose up to
capacity jobs. Execute that whole wave, then release dependencies for the next
wave. A wave costs the maximum duration of its selected jobs (a barrier schedule).
Return {'waves': [[names...], ...], 'elapsed': sum of wave costs,
'critical_path': maximum downstream critical length, or 0 for an empty graph}.

Correctness matters more than guessing a fast order. Validate the whole graph
even when a disconnected component would otherwise be schedulable. Support at
least 250 jobs. Implement the repair and any additional tests you find useful.
''',
    'reconciler': '''# Idempotent financial event reconciliation
Repair `solution.py` using only Python's standard library. Keep `reconcile(events)`.
Run `python3 -m unittest -v test_public.py`. Never mutate the input.

Input is a list of dicts. Every event has exactly these shared fields: id (nonempty
string), account (nonempty string), currency ('USD' or 'EUR'), amount (positive
decimal STRING with exactly two fractional digits and no sign or exponent), kind
('charge' or 'refund'). A refund also has charge_id (nonempty string). Reject
missing/extra fields, malformed values, or invalid relationships with ValueError.
Identical duplicate events with the same id are ignored. A conflicting duplicate
id anywhere in the list is an error. Validate before producing a result.

A refund refers to a charge in the same batch, regardless of input order. It
must have the same account and currency. Sum of unique refunds against one charge
cannot exceed that charge. Refund references to refunds are invalid. Use exact
decimal arithmetic; do not use binary floating point for balances.

Return {'balances': [{'account': ..., 'currency': ..., 'net': '0.00'}, ...],
'unique_events': n, 'duplicates_ignored': n}. Include every account/currency
pair present even if net is zero; sort balances by account then currency.
Empty input returns empty balances and both counts zero. Amounts up to
999999999999.99 are valid. Implement the repair and useful additional tests.
''',
    'event_reducer': '''# Session-tree execution event reducer
Repair `solution.py` using only the Python standard library. Keep
`summarize(events, root)`. Run `python3 -m unittest -v test_public.py`.
Input is a list of dictionaries, root is a nonempty string, and inputs must not
be mutated. Each event has exactly id (nonempty string), session (nonempty string),
parent (nonempty string or None), call (nonempty string), kind ('start' or 'end'),
at (nonnegative int, not bool). End events also have ok (bool). Start events must
not have ok. Reject other missing/extra fields or invalid values with ValueError.

Deduplicate by (session,id), ignoring identical duplicates and rejecting conflicting
ones. All events for a session must agree on its parent; reject self-parenting and
cycles anywhere, even outside root's tree. A referenced but unobserved parent is
permitted. Include root plus every transitive descendant regardless of input order;
an unobserved root can still have observed descendants. Sort returned session IDs.

Within the selected tree, join by (session,call). A call has at most one unique
start and one unique end; two different event IDs of the same kind for that call
are invalid. End-before-start INPUT ORDER is allowed, but a matched end timestamp
before its start timestamp is invalid. Validate call rules in ALL sessions.
Only matched calls contribute completed, successful, failed, and duration totals.
Unmatched starts count as in_flight; unmatched ends count as orphan_ends. Equal
timestamps are valid zero-duration completions. Separate sessions may reuse IDs.

Return {'sessions': [observed session ids in scope], 'completed': n,
'successful': n, 'failed': n, 'in_flight': n, 'orphan_ends': n,
'total_duration': sum of matched durations}. Root absent without descendants gives
an empty sessions list and all zero counts. Implement repair and useful tests.
''',
}

STARTERS = {
    'scheduler': "def plan(jobs, capacity):\n    names = sorted(jobs)\n    return {'waves': [names], 'elapsed': sum(j['duration'] for j in jobs.values()), 'critical_path': 0}\n",
    'reconciler': "def reconcile(events):\n    totals = {}\n    for e in events:\n        key = (e['account'], e['currency'])\n        totals[key] = totals.get(key, 0.0) + float(e['amount'])\n    return {'balances': [{'account': a, 'currency': c, 'net': str(v)} for (a,c),v in totals.items()], 'unique_events': len(events), 'duplicates_ignored': 0}\n",
    'event_reducer': "def summarize(events, root):\n    rows = [e for e in events if e['session'] == root]\n    return {'sessions': [root], 'completed': len(rows), 'successful': len(rows), 'failed': 0, 'in_flight': 0, 'orphan_ends': 0, 'total_duration': 0}\n",
}

PUBLIC = {
    'scheduler': """import unittest
from solution import plan
class Public(unittest.TestCase):
 def test_chain(self):
  self.assertEqual(plan({'a':{'deps':[],'duration':2},'b':{'deps':['a'],'duration':3}},2),{'waves':[['a'],['b']],'elapsed':5,'critical_path':5})
 def test_empty(self):
  self.assertEqual(plan({},3),{'waves':[],'elapsed':0,'critical_path':0})
 def test_cycle(self):
  with self.assertRaises(ValueError):plan({'a':{'deps':['b'],'duration':1},'b':{'deps':['a'],'duration':1}},2)
""",
    'reconciler': """import unittest
from solution import reconcile
class Public(unittest.TestCase):
 def test_refund_and_duplicate(self):
  a={'id':'c','account':'alice','currency':'USD','amount':'10.10','kind':'charge'}
  b={'id':'r','account':'alice','currency':'USD','amount':'0.10','kind':'refund','charge_id':'c'}
  self.assertEqual(reconcile([b,a,a]),{'balances':[{'account':'alice','currency':'USD','net':'10.00'}],'unique_events':2,'duplicates_ignored':1})
 def test_missing_charge(self):
  with self.assertRaises(ValueError):reconcile([{'id':'r','account':'a','currency':'USD','amount':'1.00','kind':'refund','charge_id':'missing'}])
 def test_empty(self):
  self.assertEqual(reconcile([]),{'balances':[],'unique_events':0,'duplicates_ignored':0})
""",
    'event_reducer': """import unittest
from solution import summarize
class Public(unittest.TestCase):
 def test_child(self):
  a={'id':'a','session':'child','parent':'root','call':'c','kind':'start','at':5}
  b={'id':'b','session':'child','parent':'root','call':'c','kind':'end','at':12,'ok':True}
  self.assertEqual(summarize([b,a,a],'root'),{'sessions':['child'],'completed':1,'successful':1,'failed':0,'in_flight':0,'orphan_ends':0,'total_duration':7})
 def test_empty(self):
  self.assertEqual(summarize([],'r'),{'sessions':[],'completed':0,'successful':0,'failed':0,'in_flight':0,'orphan_ends':0,'total_duration':0})
 def test_parent_cycle(self):
  with self.assertRaises(ValueError):summarize([{'id':'a','session':'r','parent':'r','call':'c','kind':'start','at':0}],'r')
""",
}


def scheduler_oracle(jobs, capacity):
    # Independent small-graph exhaustive relaxation and readiness calculation.
    scores = {k: v['duration'] for k, v in jobs.items()}
    for _ in jobs:
        scores = {k: v['duration'] + max([scores[n] for n, j in jobs.items() if k in j['deps']] or [0]) for k,v in jobs.items()}
    done, waves, elapsed = set(), [], 0
    while len(done) < len(jobs):
        ready = sorted((k for k,j in jobs.items() if k not in done and set(j['deps']) <= done), key=lambda k:(-scores[k],k))[:capacity]
        assert ready
        waves.append(ready); done.update(ready); elapsed += max(jobs[k]['duration'] for k in ready)
    return {'waves': waves, 'elapsed': elapsed, 'critical_path': max(scores.values(), default=0)}


# --------------------------------------------------------------------------
# Task source registry: makes tasks from an additional source (e.g. the
# aider-polyglot adapter in scripts/polyglot_tasks.py) resolvable by name
# alongside battery_tasks.TASKS, via a single `get_task`/`all_tasks` contract
# point. A registered source is process-local (module-level cache); a fresh
# process (e.g. a subprocess worker) must call `register_source` again --
# see forge_e2e.py's `_ensure_task_source_registered`, which does this from
# a manifest's persisted `task_source` field.
# --------------------------------------------------------------------------

_extra_tasks = {}


def register_source(kind, **opts):
    """Register an additional task source, making its tasks resolvable by
    name via `get_task`/`all_tasks` (and therefore via `task_files`,
    `task_prompt`, `task_protected`, and `evaluate` below).

    kind='polyglot': opts must include `root` (a polyglot-benchmark checkout
    directory) and may include `languages` (list[str]); any other keys
    (e.g. `sha`) are accepted and ignored -- they exist for manifest
    round-tripping, not for `load()`. Re-registering the same root simply
    reloads (idempotent in effect, not free -- call once per process).

    Returns the dict of tasks that were loaded.
    """
    if kind == 'polyglot':
        import polyglot_tasks
        tasks = polyglot_tasks.load(opts['root'], languages=opts.get('languages'))
        _extra_tasks.update(tasks)
        return tasks
    raise ValueError(f'unknown task source kind: {kind}')


def get_task(name):
    """Resolve `name` to its Task object: a registered extra source first
    (see `register_source`), then `battery_tasks.TASKS`. Raises KeyError for
    an unknown name. Legacy SPECS-trio tasks have no Task object -- callers
    that must also handle those check `name in SPECS` themselves (see
    `task_files`/`task_prompt`/`task_protected`/`evaluate` below)."""
    if name in _extra_tasks:
        return _extra_tasks[name]
    import battery_tasks
    if name in battery_tasks.TASKS:
        return battery_tasks.TASKS[name]
    raise KeyError(f'unknown task: {name}')


def all_tasks():
    """Every task known to this process: battery_tasks.TASKS plus any
    registered extra source, merged (extra sources win on name collision,
    though none is expected since polyglot names are namespaced)."""
    import battery_tasks
    merged = dict(battery_tasks.TASKS)
    merged.update(_extra_tasks)
    return merged


def task_files(task):
    """Starter workspace files for `task`: relative path -> text."""
    if task in SPECS:
        return {'README.md': SPECS[task], 'solution.py': STARTERS[task], 'test_public.py': PUBLIC[task]}
    return dict(get_task(task).files)


def task_prompt(task):
    """The exact user prompt for `task`, or None for legacy tasks with no
    fixed prompt (README.md + test_public.py stand alone)."""
    if task in SPECS:
        return None
    return get_task(task).prompt


def task_protected(task):
    """Files the agent must not modify for `task`."""
    if task in SPECS:
        return ('README.md', 'test_public.py')
    return tuple(get_task(task).protected)


def evaluate(task, workspace):
    if task not in SPECS:
        return get_task(task).evaluate(Path(workspace))
    spec = importlib.util.spec_from_file_location('candidate_solution', Path(workspace)/'solution.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failures, total = [], 0
    rng = random.Random(987041)
    def check(label, fn, args, expected=None, invalid=False):
        nonlocal total
        total += 1
        before = copy.deepcopy(args)
        try:
            got = fn(*args)
            ok = not invalid and got == expected
        except ValueError:
            ok = invalid
        except Exception:
            ok = False
        if args != before: ok = False
        if not ok: failures.append(label)
    if task == 'scheduler':
        fn = module.plan
        for case in range(80):
            n = rng.randrange(0,35)
            jobs = {f'j{i:02}':{'deps':[f'j{k:02}' for k in range(i) if rng.random()<.12], 'duration':rng.randrange(1,30)} for i in range(n)}
            if n and jobs[f'j{n-1:02}']['deps']:jobs[f'j{n-1:02}']['deps'] *= 2
            cap = rng.randrange(1,7)
            check(f'dag-{case}',fn,(jobs,cap),scheduler_oracle(jobs,cap))
        chain = {str(i): {'deps':[str(i-1)] if i else [],'duration':1} for i in range(250)}
        check('long-chain',fn,(chain,3),{'waves':[[str(i)] for i in range(250)],'elapsed':250,'critical_path':250})
        for cap in [0,-1,True,1.5,'2',None]:check('capacity-'+repr(cap),fn,({},cap),invalid=True)
        for jobs in [[], {'a':{'deps':['x'],'duration':1}}, {'a':{'deps':['a'],'duration':1}}, {'a':{'deps':[],'duration':True}}, {'a':{'deps':[],'duration':0}}, {'a':{'deps':'x','duration':1}}, {'a':{'duration':1}}, {'':{'deps':[],'duration':1}}, {'a':{'deps':['b'],'duration':1},'b':{'deps':['a'],'duration':1},'c':{'deps':[],'duration':1}}]:
            check('invalid-graph-'+str(total),fn,(jobs,2),invalid=True)
    elif task == 'reconciler':
        fn = module.reconcile
        for case in range(80):
            rows, cents, unique = [], {}, 0
            for i in range(rng.randrange(1,20)):
                account = rng.choice(['alpha','beta','gamma']); currency=rng.choice(['USD','EUR']); amount=rng.randrange(1,10000000)
                charge={'id':f'c{i}','account':account,'currency':currency,'amount':f'{amount//100}.{amount%100:02}','kind':'charge'}
                refund=rng.randrange(amount+1); rows.append(charge);unique+=1
                if refund:
                    rows.append({'id':f'r{i}','account':account,'currency':currency,'amount':f'{refund//100}.{refund%100:02}','kind':'refund','charge_id':f'c{i}'});unique+=1
                cents[(account,currency)]=cents.get((account,currency),0)+amount-refund
            for _ in range(5):rows.append(copy.deepcopy(rng.choice(rows)))
            rng.shuffle(rows)
            expected={'balances':[{'account':a,'currency':c,'net':f'{v//100}.{v%100:02}'} for (a,c),v in sorted(cents.items())], 'unique_events':unique,'duplicates_ignored':len(rows)-unique}
            check(f'batch-{case}',fn,(rows,),expected)
        base={'id':'c','account':'a','currency':'USD','amount':'10.00','kind':'charge'}
        refund={'id':'r','account':'a','currency':'USD','amount':'10.00','kind':'refund','charge_id':'c'}
        check('zero-balance',fn,([base,refund],),{'balances':[{'account':'a','currency':'USD','net':'0.00'}],'unique_events':2,'duplicates_ignored':0})
        for key, values in {'amount':['NaN','Infinity','1e2','-1.00','0.00','1.001',1.25,True,'1.0'], 'currency':['GBP',None], 'id':['',3], 'account':['',None], 'kind':['unknown']}.items():
            for value in values:check('invalid-'+key+'-'+repr(value),fn,([{**base,key:value}],),invalid=True)
        for rows in [[base,{**base,'amount':'9.00'}],[refund],[base,{**refund,'amount':'10.01'}],[base,{**refund,'currency':'EUR'}],[base,{**refund,'account':'b'}],[base,refund,{**refund,'id':'r2','amount':'0.01'}],[{**base,'extra':1}],[{k:v for k,v in base.items() if k!='account'}]]:
            check('invalid-batch-'+str(total),fn,(rows,),invalid=True)
        huge={**base,'amount':'999999999999.99'}
        check('large-exact',fn,([huge],),{'balances':[{'account':'a','currency':'USD','net':'999999999999.99'}],'unique_events':1,'duplicates_ignored':0})
        check('empty',fn,([],),{'balances':[],'unique_events':0,'duplicates_ignored':0})
    else:
        fn=module.summarize
        for case in range(80):
            rows=[]; expected={'sessions':['a','b','root'],'completed':0,'successful':0,'failed':0,'in_flight':0,'orphan_ends':0,'total_duration':0}
            for sid,parent in [('root',None),('a','root'),('b','a'),('other',None)]:
                for i in range(8):
                    mode=rng.choice(['pair','pair','start','end']); start=rng.randrange(50);delta=rng.randrange(20);ok=bool(rng.randrange(2))
                    if mode!='end':rows.append({'id':f's{i}','session':sid,'parent':parent,'call':str(i),'kind':'start','at':start})
                    if mode!='start':rows.append({'id':f'e{i}','session':sid,'parent':parent,'call':str(i),'kind':'end','at':start+delta,'ok':ok})
                    if sid!='other':
                        if mode=='pair':expected['completed']+=1;expected['successful' if ok else 'failed']+=1;expected['total_duration']+=delta
                        else:expected['in_flight' if mode=='start' else 'orphan_ends']+=1
            rows+=copy.deepcopy(rows[:5]);rng.shuffle(rows)
            check(f'tree-{case}',fn,(rows,'root'),expected)
        start={'id':'x','session':'a','parent':'root','call':'c','kind':'start','at':3}
        end={**start,'id':'y','kind':'end','at':8,'ok':True}
        for rows in [[start,{**start,'at':4}],[start,{**start,'id':'z'}],[start,{**end,'at':2}],[start,{**end,'parent':None}],[{**start,'parent':'a'}],[start,{**start,'session':'root','parent':'a'}],[{**start,'at':True}],[{**start,'ok':True}],[{**end,'ok':1}],[{**start,'extra':1}],[{**start,'id':''}]]:
            check('invalid-events-'+str(total),fn,(rows,'root'),invalid=True)
        zero={'sessions':[],'completed':0,'successful':0,'failed':0,'in_flight':0,'orphan_ends':0,'total_duration':0}
        check('absent-root',fn,([start,end],'missing'),zero)
        check('unobserved-parent',fn,([end,start],'root'),{**zero,'sessions':['a'],'completed':1,'successful':1,'total_duration':5})
        check('empty',fn,([],'root'),zero)
    return {'checks':total,'passed':total-len(failures),'failed':len(failures),'failure_labels':failures,'input_immutability_checked':True}
