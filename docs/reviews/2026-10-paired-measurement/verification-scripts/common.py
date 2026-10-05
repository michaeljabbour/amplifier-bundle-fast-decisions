import json, math, sys, gzip, collections, statistics as st
import os
REPO=os.environ.get('FD_PAIRED_REPO', '.')  # run from the repository root, or set FD_PAIRED_REPO
sys.path.insert(0, REPO+'/evals')
import numpy as np
import paired_model as pm
E=REPO+'/docs/evidence/2026-10-02-paired-campaign/data'
S=[json.loads(l) for l in open(E+'/sessions.jsonl')]
T=[json.loads(l) for l in open(E+'/turns.jsonl')]
P=[json.loads(l) for l in open(E+'/pairs.jsonl')]
DS=pm.load_dataset(E)
R=DS['pairs']
SK={s['session_key']:s for s in S}
def boot(vals, cl, key, B=10000, seed=20261002):
    return pm.cluster_boot_mean(vals, cl, pm.rng_for(seed,*key), B)
import re
FAM={}
for line in open(REPO+'/docs/evidence/2026-10-02-paired-campaign/prereg/SPLIT.md'):
    m=re.match(r'- \*\*(\w+)\*\* \(\d+\): (.*)',line)
    if m:
        for x in m.group(2).split(', '): FAM[x.split(' ')[0]]=m.group(1)
