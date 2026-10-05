from common import *
import pickle
# the original read a local pickle of the request rows; rebuilt here from the committed file
REQ=collections.defaultdict(list)
for _l in gzip.open(E+'/requests.jsonl.gz','rt'):
    _r=json.loads(_l); REQ[_r['session_key']].append(_r)
idx={(s['scenario_id'],s['rep'],s['host'],s['arm']):s for s in S}
def C(s): return s['cost_usd_tools_normalized']
def tok(s):
    t=collections.Counter()
    for m,v in s['tokens'].items(): t.update(v)
    return t
def boot2(vals, cl, key, B=10000): return boot(vals, cl, ('c11',)+key, B)
out=[]
for h in ('fable','opus'):
  for sp in ('all','test'):
    rows=[]
    for s in S:
        if s['arm']!='sticky' or s['host']!=h or s['sticky_decision']!='cheap' or not s['cost_valid']: continue
        if sp=='test' and s['split']!='test': continue
        c=idx[(s['scenario_id'],s['rep'],'any','sonnet')]
        if not c['cost_valid']: continue
        a=idx[(s['scenario_id'],s['rep'],h,'anchor')]
        ts_,tc=tok(s),tok(c)
        bg_s=sum(r['cost_usd_tools_normalized'] for r in REQ[s['session_key']] if not r['main'])
        bg_c=sum(r['cost_usd_tools_normalized'] for r in REQ[c['session_key']] if not r['main'])
        rows.append(dict(sc=s['scenario_id'], y=math.log(C(s)/C(c)), ymain=math.log((C(s)-bg_s)/(C(c)-bg_c)),
            nreq=math.log(s['n_req']/c['n_req']), ns=s['n_req'], nc=c['n_req'], cs=C(s), cc=C(c), bgs=bg_s, bgc=bg_c,
            dtp=s['turn_pass_frac']-c['turn_pass_frac'], fps=s['final_state_pass'], fpc=c['final_state_pass'],
            outs=ts_['output'], outc=tc['output'], rds=ts_['cache_read'], rdc=tc['cache_read'], wrs=ts_['cache_write'], wrc=tc['cache_write'],
            ya=math.log(C(s)/C(a)), yca=math.log(C(c)/C(a)), wall=math.log(s['wall_ms']/c['wall_ms']), ex=math.log(s['exec_ms']/c['exec_ms'])))
    cl=[r['sc'] for r in rows]
    def B(field,k): 
        e,lo,hi,n=boot2([r[field] for r in rows],cl,(h,sp,k)); return e,lo,hi,n
    e,lo,hi,n=B('y','y'); em,lom,him,_=B('ymain','ym'); en,lon,hin,_=B('nreq','n'); ed,lod,hid,_=B('dtp','d')
    ew,low,hiw,_=B('ex','ex')
    print(f"\n== {h} host, {sp}: {len(rows)} sticky-chose-Sonnet sessions, {n} scenarios")
    print(f"  cost ratio sticky/sonnet-control GM {math.exp(e):.3f} [{math.exp(lo):.3f}, {math.exp(hi):.3f}]  (main-loop only {math.exp(em):.3f} [{math.exp(lom):.3f}, {math.exp(him):.3f}])")
    print(f"  ratio of mean cost {sum(r['cs'] for r in rows)/sum(r['cc'] for r in rows):.3f}; mean $ sticky {st.mean(r['cs'] for r in rows):.3f} control {st.mean(r['cc'] for r in rows):.3f}; bg $/session sticky {st.mean(r['bgs'] for r in rows):.4f} control {st.mean(r['bgc'] for r in rows):.4f}")
    print(f"  requests/session sticky {st.mean(r['ns'] for r in rows):.1f} control {st.mean(r['nc'] for r in rows):.1f}; GM ratio {math.exp(en):.3f} [{math.exp(lon):.3f}, {math.exp(hin):.3f}]; sticky fewer in {sum(r['ns']<r['nc'] for r in rows)}/{len(rows)}")
    print(f"  tokens/session sticky vs control: output {st.mean(r['outs'] for r in rows):,.0f} vs {st.mean(r['outc'] for r in rows):,.0f}; cache_read {st.mean(r['rds'] for r in rows)/1e6:.2f}M vs {st.mean(r['rdc'] for r in rows)/1e6:.2f}M; cache_write {st.mean(r['wrs'] for r in rows):,.0f} vs {st.mean(r['wrc'] for r in rows):,.0f}")
    print(f"  exec time GM ratio {math.exp(ew):.3f} [{math.exp(low):.3f},{math.exp(hiw):.3f}]")
    print(f"  turn-pass diff sticky-control {ed:+.4f} [{lod:+.4f}, {hid:+.4f}]; final pass sticky {np.mean([r['fps'] for r in rows]):.3f} control {np.mean([r['fpc'] for r in rows]):.3f}")
    print(f"  vs anchor on same subset: sticky GM {math.exp(st.mean(r['ya'] for r in rows)):.3f}, sonnet-control GM {math.exp(st.mean(r['yca'] for r in rows)):.3f}")
# claim 7 composition
print('\n== claim 7: naive composition weighting (Table 20 means)')
def m(f,h,a): return st.mean(f(s) for s in S if s['host']==h and s['arm']==a and s['cost_valid'])
for h in ('fable','opus'):
    p=124/140
    son_n=m(lambda s:s['n_req'],'any','sonnet'); an_n=m(lambda s:s['n_req'],h,'anchor'); stn=m(lambda s:s['n_req'],h,'sticky')
    son_c=m(C,'any','sonnet'); an_c=m(C,h,'anchor'); stc=m(C,h,'sticky')
    pn=p*son_n+(1-p)*an_n; pc=p*son_c+(1-p)*an_c
    print(f"{h}: requests predicted {pn:.2f} actual {stn:.2f} -> {100*(1-stn/pn):.1f}% fewer; cost predicted {pc:.3f} actual {stc:.3f} -> {100*(1-stc/pc):.1f}% less")
    # matched composition: same scenario-rep partner (control if cheap, anchor if host)
    pr=[];pc_=[]
    for s in S:
        if s['arm']!='sticky' or s['host']!=h: continue
        c=idx[(s['scenario_id'],s['rep'],'any','sonnet')] if s['sticky_decision']=='cheap' else idx[(s['scenario_id'],s['rep'],h,'anchor')]
        pr.append((s['n_req'],c['n_req'])); pc_.append((C(s),C(c)))
    print(f"   matched partner: requests {sum(a for a,b in pr)/sum(b for a,b in pr):.3f}x, cost {sum(a for a,b in pc_)/sum(b for a,b in pc_):.3f}x")
