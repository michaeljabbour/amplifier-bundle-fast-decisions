from common import *
from datetime import datetime
ts=lambda x: datetime.fromisoformat(x).timestamp()
W=collections.defaultdict(list)
for s in S: W[s['wave_id']].append(s)
off={}
for w,v in W.items():
    t0=min(ts(s['actual_start']) for s in v)
    for s in v: off[s['session_key']]=ts(s['actual_start'])-t0
rk=collections.Counter()
for w,v in W.items():
    o=sorted(v,key=lambda s: s['actual_start']); rk[tuple(s['arm'] for s in o)]+=1
print('observed start orders (top):'); [print(' ',k,c) for k,c in rk.most_common(8)]
idx={(s['scenario_id'],s['rep'],s['host'],s['arm']):s for s in S}
def key(r):
    a=idx[(r['scenario'],r['rep'],r['host'],'anchor')]
    s=idx.get((r['scenario'],r['rep'],r['host'],r['arm'])) or idx[(r['scenario'],r['rep'],'any',r['arm'])]
    return a,s
rows=[]
for r in pm._cost_rows(R):
    a,s=key(r)
    same_wave = a['wave_id']==s['wave_id']
    dx = (off[s['session_key']]-off[a['session_key']]) if same_wave else None
    rows.append(dict(r, dx=dx, same_wave=same_wave, offa=off[a['session_key']], offs=off[s['session_key']], gap_h=(ts(s['actual_start'])-ts(a['actual_start']))/3600))
def ols(X,y):
    b,*_=np.linalg.lstsq(X,y,rcond=None); return b
def fit(rs, arms_fe):
    y=np.array([r['y'] for r in rs]); x=np.array([r['dx'] for r in rs])
    cols=[x]
    if arms_fe:
        for a in sorted({r['arm'] for r in rs}): cols.append(np.array([1.0 if r['arm']==a else 0.0 for r in rs]))
    else: cols.append(np.ones(len(rs)))
    return ols(np.column_stack(cols),y)
def cboot(rs, arms_fe, B=4000, seed=7):
    rng=np.random.default_rng(seed); g=collections.defaultdict(list)
    for r in rs: g[r['scenario']].append(r)
    keys=list(g); out=[]
    for _ in range(B):
        pick=rng.integers(0,len(keys),len(keys)); rr=[x for i in pick for x in g[keys[i]]]
        try: out.append(fit(rr,arms_fe)[0])
        except Exception: pass
    return np.percentile(out,[2.5,97.5])
res={}
for h in ('fable','opus'):
    aa=[r for r in rows if r['host']==h and r['arm']=='aa']
    b=fit(aa,False); lo,hi=cboot(aa,False)
    print(f'{h} A/A n={len(aa)} dx mean {np.mean([r["dx"] for r in aa]):.2f}s sd {np.std([r["dx"] for r in aa]):.2f} slope/s {b[0]:+.4f} [{lo:+.4f},{hi:+.4f}] intercept {b[1]:+.4f} (exp {math.exp(b[1]):.3f}) mean y {np.mean([r["y"] for r in aa]):+.4f}')
    print('   frac aa started before anchor', np.mean([r['dx']<0 for r in aa]))
    sw=[r for r in rows if r['host']==h and r['same_wave']]
    b=fit(sw,True); lo,hi=cboot(sw,True,B=2000)
    print(f'{h} all same-wave arms n={len(sw)} arms={sorted({r["arm"] for r in sw})} slope/s {b[0]:+.4f} [{lo:+.4f},{hi:+.4f}]')
    for a in ('shipped','sticky','sonnet'):
        rs=[r for r in rows if r['host']==h and r['arm']==a and r['same_wave']]
        if len(rs)<10: print(f'   {a}: only {len(rs)} same-wave pairs'); continue
        b=fit(rs,False); lo,hi=cboot(rs,False,B=2000)
        print(f'   {a} n={len(rs)} slope/s {b[0]:+.4f} [{lo:+.4f},{hi:+.4f}]')
# anchor offset only (anchor started late => ?) : regress y_aa on offset of anchor and of aa separately
for h in ('fable','opus'):
    aa=[r for r in rows if r['host']==h and r['arm']=='aa']
    X=np.column_stack([[r['offs'] for r in aa],[r['offa'] for r in aa],np.ones(len(aa))]); print(h,'aa: coef offset_aa, offset_anchor, icpt',ols(X,np.array([r['y'] for r in aa])))
fs=[r for r in rows if r['host']=='fable' and r['arm']=='sonnet']
print('fable-sonnet pairs same wave:',sum(r['same_wave'] for r in fs),'of',len(fs),'median |gap| h %.2f'%np.median([abs(r['gap_h']) for r in fs]), 'max %.1f'%max(abs(r['gap_h']) for r in fs))
print('--- A/A by start order and composition')
for h in ('fable','opus'):
    aa=[r for r in rows if r['host']==h and r['arm']=='aa']
    b=[r['y'] for r in aa if r['dx']<0]; a_=[r['y'] for r in aa if r['dx']>=0]
    print(h,'aa first: n=%d mean y %+.4f | anchor first: n=%d mean y %+.4f'%(len(b),np.mean(b),len(a_),np.mean(a_)))
    nr=[math.log(idx[(r['scenario'],r['rep'],h,'aa')]['n_req']/idx[(r['scenario'],r['rep'],h,'anchor')]['n_req']) for r in aa]
    print('   GM n_req ratio aa/anchor %.3f'%math.exp(np.mean(nr)), ' corr(y, log nreq ratio) %.2f'%np.corrcoef([r['y'] for r in aa],nr)[0,1])
