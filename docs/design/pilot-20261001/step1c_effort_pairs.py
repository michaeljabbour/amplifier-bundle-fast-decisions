"""Pairwise Sonnet 5 effort partition check: fresh nonce per (first, second) pair, 2 replicates.
Second request R>0 => same cache partition. Appends to step1_cache_probe.json."""
import json, os, step1_cache_probe as p
LV = [None, "low", "medium", "high"]
pairs = [(a, b) for a in LV for b in LV if a != b and LV.index(a) < LV.index(b)] + [(None, None), ("medium", "medium")]
for rep in (1, 2):
    for a, b in pairs:
        n = f"e4-{a}-{b}-r{rep}"
        msgs = [p.u1(p.txt(p.X, True), p.txt(p.Q))]
        p.call("e4", f"r{rep} first effort={a}", p.SON, p.sysblk(n), msgs, thinking=p.ADAPT, effort=a)
        p.call("e4", f"r{rep} then effort={b}", p.SON, p.sysblk(n), msgs, thinking=p.ADAPT, effort=b)
f = os.path.join(p.OUT, "step1_cache_probe.json")
d = json.load(open(f)); d["requests"] += p.LOG; d["pairs_run"] = p.RUN
d["total_cost_usd"] = round(d["total_cost_usd"] + p.SPEND[0], 4)
json.dump(d, open(f, "w"), indent=1); print("added", round(p.SPEND[0], 4), "total", d["total_cost_usd"])
