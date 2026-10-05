"""Replication of (e) in a different order, fresh nonces. Appends to step1_cache_probe.json."""
import json, os, step1_cache_probe as p
V = [("effort medium FIRST (write)", p.ADAPT, "medium"), ("base adaptive (no effort)", p.ADAPT, None),
     ("effort medium again", p.ADAPT, "medium"), ("effort high", p.ADAPT, "high"),
     ("no thinking + effort medium", None, "medium"), ("no thinking, no effort", None, None)]
for model in (p.SON, p.OPUS):
    for lab, th, ef in V:
        p.call("e2", lab, model, p.sysblk(f"e2-{model}"), [p.u1(p.txt(p.X, True), p.txt(p.Q))], thinking=th, effort=ef)
# does a Sonnet effort change also miss with NO message bp (system-only bp)?
for lab, th, ef in [("sys-bp only: base", p.ADAPT, None), ("sys-bp only: effort medium", p.ADAPT, "medium")]:
    p.call("e3", lab, p.SON, p.sysblk("e3"), [p.u1(p.txt(p.Q))], thinking=th, effort=ef)
f = os.path.join(p.OUT, "step1_cache_probe.json")
d = json.load(open(f))
d["requests"] += p.LOG
d["replication_run"] = p.RUN
d["total_cost_usd"] = round(d["total_cost_usd"] + p.SPEND[0], 4)
json.dump(d, open(f, "w"), indent=1)
print("added", round(p.SPEND[0], 4), "total", d["total_cost_usd"])
