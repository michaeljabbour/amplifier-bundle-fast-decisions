"""STEP 0: variance inputs for the cost-savings power plan. Makes no model calls.

Strata = lever (pair `kind`) x host model x suite (S1 single-turn, s1m 4-turn, S3).
y = ln(cost_treat / cost_anchor) per matched pair (pairs.csv, sessions_ok only).
One-way random effects, scenario (task) = group. Two versions per stratum:
  raw           - pooled over every cell (config) in the lever
  cell_adjusted - y re-centred on its cell mean first (removes between-config spread,
                  which a campaign testing ONE config would not see). Planning number.
Per-turn: s1m pairs; turn cost = sum of llm:response cost_usd with that turn index
(prompt:submit count), background calls included. sessions.csv shows $HOME as "~" everywhere,
including inside the encoded project-dir name, so every "~" is expanded.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
import pandas as pd

SRC = os.path.expanduser("~/dev/fd-judge-realistic/docs/evidence/2026-10-01-caching")
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from caching_survey import parse_session  # noqa: E402  (never returns message bodies)

Z = 1.959964
TARGETS = {"pm10": (math.log(1.10), math.log(1 / 0.90)), "pm20": (math.log(1.20), math.log(1 / 0.80))}
SUITE = {"S1-single": "S1", "S1-multi": "s1m", "S3-routing": "S3", "S3-v4-same-model": "S3-v4"}


def components(df, y="y", g="task"):
    grp = df.groupby(g)[y]
    n_i = grp.size().values.astype(float)
    a, N = len(n_i), n_i.sum()
    if a < 2 or N - a < 1:
        return None
    gm = df[y].mean()
    ssb = float((n_i * (grp.mean().values - gm) ** 2).sum())
    ssw = float(((df[y] - grp.transform("mean")) ** 2).sum())
    msb, msw = ssb / (a - 1), ssw / (N - a)
    k0 = (N - (n_i ** 2).sum() / N) / (a - 1)
    sb2 = max((msb - msw) / k0, 0.0)
    icc = sb2 / (sb2 + msw) if (sb2 + msw) > 0 else 0.0
    return dict(n_pairs=int(N), n_scenarios=int(a), pairs_per_scenario_k0=round(k0, 2),
                mean_ln_ratio=gm, gmean_ratio=math.exp(gm), sd_ln_ratio=float(df[y].std(ddof=1)),
                sd_between_scenario_means=float(grp.mean().std(ddof=1)),
                sigma_between=math.sqrt(sb2), sigma_within=math.sqrt(msw), icc=icc, msb=msb, msw=msw)


def plan(c):
    sb2, sw2 = c["sigma_between"] ** 2, c["sigma_within"] ** 2
    res = {}
    for name, (hi, lo) in TARGETS.items():
        h = min(hi, lo)
        rows = {}
        for m in (1, 2, 3, 5, 10):
            n = max(math.ceil((Z / h) ** 2 * (sb2 + sw2 / m)), 2)
            rows[f"m{m}"] = dict(scenarios=n, pairs=n * m, design_effect=1 + (m - 1) * c["icc"])
        rows["min_scenarios_m_inf"] = math.ceil((Z / h) ** 2 * sb2)
        res[name] = rows
    return res


def main():
    pairs = pd.read_csv(os.path.join(SRC, "pairs.csv"))
    sess = pd.read_csv(os.path.join(SRC, "sessions.csv"))
    p = pairs[(pairs.sessions_ok == True) & (pairs.cost_treat > 0) & (pairs.cost_anchor > 0)].copy()  # noqa: E712
    p["y"] = np.log(p.cost_treat / p.cost_anchor)
    p["suite"] = p.family.map(SUITE)
    p["y_cell"] = p.y - p.groupby(["family", "host", "cell", "anchor"]).y.transform("mean") \
        + p.groupby(["family", "host", "kind"]).y.transform("mean")

    strata = []
    for (kind, host, suite), d in p.groupby(["kind", "host", "suite"]):
        raw, adj = components(d, "y"), components(d, "y_cell")
        if raw is None:
            continue
        strata.append(dict(lever=kind, host=host, suite=suite, cells=sorted(d.cell.unique()),
                           campaigns=sorted(d.campaign.unique()), raw=raw, cell_adjusted=adj,
                           plan_cell_adjusted=plan(adj), plan_raw=plan(raw)))

    per_cell = []
    for (cell, anchor, host, suite), d in p.groupby(["cell", "anchor", "host", "suite"]):
        c = components(d, "y")
        if c and c["n_scenarios"] >= 6:
            per_cell.append(dict(cell=cell, anchor=anchor, host=host, suite=suite, **{k: c[k] for k in (
                "n_pairs", "n_scenarios", "gmean_ratio", "sd_ln_ratio", "sigma_between", "sigma_within", "icc")},
                plan=plan(c)))

    sidx = {(r.family, r.campaign, r.cell, r.task, int(r.rep)): os.path.expanduser(r.session_dir).replace("-~-", "-" + os.path.expanduser("~").strip("/").replace("/", "-") + "-")
            for r in sess.itertuples() if isinstance(r.session_dir, str)}
    cache = {}

    def turns(path):
        if path not in cache:
            t = defaultdict(float)
            for r in parse_session(path)["responses"]:
                t[r["turn"]] += r["cost"]
            cache[path] = dict(t)
        return cache[path]

    trows = []
    for r in p[p.suite == "s1m"].itertuples():
        ta = sidx.get((r.family, r.campaign, r.cell, r.task, int(r.rep)))
        an = sidx.get((r.family, r.campaign, r.anchor, r.task, int(r.rep)))
        if not ta or not an:
            continue
        ct, ca = turns(ta), turns(an)
        for t in sorted(set(ct) & set(ca)):
            if ct[t] > 0 and ca[t] > 0:
                trows.append(dict(kind=r.kind, host=r.host, cell=r.cell, task=r.task,
                                  pair=f"{r.campaign}|{r.cell}|{r.anchor}|{r.task}|{r.rep}", turn=t,
                                  y=math.log(ct[t] / ca[t]), y_pair=r.y))
    tdf = pd.DataFrame(trows)
    turn_strata = []
    for (kind, host), d in tdf.groupby(["kind", "host"]):
        c = components(d, "y", "pair")
        d = d.assign(y_res=d.y - d.groupby("turn").y.transform("mean"))
        cr = components(d, "y_res", "pair")
        turn_strata.append(dict(
            lever=kind, host=host, n_pairs=int(d.pair.nunique()), n_turn_obs=len(d),
            sd_turn_ln_ratio_all=float(d.y.std(ddof=1)),
            sd_turn_ln_ratio_within_session=c["sigma_within"], sigma_between_sessions=c["sigma_between"],
            icc_turns_within_session=c["icc"],
            # after removing the turn-index mean (turn 2 carries the post-switch rebuild): pure turn noise
            sd_turn_within_session_ex_turn_index=cr["sigma_within"], sigma_between_sessions_ex_turn_index=cr["sigma_between"],
            icc_ex_turn_index=cr["icc"],
            sd_session_ln_ratio=float(d.drop_duplicates("pair").y_pair.std(ddof=1)),
            by_turn={int(t): dict(n=len(g), gmean_ratio=math.exp(g.y.mean()), sd=float(g.y.std(ddof=1)))
                     for t, g in d.groupby("turn")}))

    out = dict(
        generated="2026-09-30", source=SRC, n_pairs_used=len(p),
        method=dict(
            y="ln(cost_treat/cost_anchor), cost = sum llm:response cost_usd (list-price table, incl. background calls)",
            icc="one-way random effects, ANOVA estimator, unbalanced k0; sigma_b^2 clipped at 0",
            plan="Var(mean y) = sb2/n + sw2/(n*m); n = ceil((1.96/h)^2 (sb2 + sw2/m)); h = ln(1.10) for +-10%, "
                 "ln(1.20) for +-20% (tighter, upper side of the asymmetric relative interval); normal approx "
                 "(with <15 scenarios inflate n by ~(t_{n-1}/1.96)^2); m = independent pairs (reps) per scenario",
            cell_adjusted="y re-centred on cell (config) means within the stratum; removes between-config spread",
            caveats=["anchor runs are reused across several treatment cells -> pairs sharing an anchor are correlated; "
                     "scenario clustering absorbs most of this, but sigma_within is slightly understated",
                     "s1m has only 6 scenarios per stratum (3 for routing_plus_shaping): sigma_between is very imprecise",
                     "sigma_b^2 clipped to 0 gives ICC=0 -> plan relies on within variance only; treat as optimistic"]),
        strata=strata, per_cell=per_cell, per_turn_s1m=turn_strata)
    with open(os.path.join(OUT, "step0_variance.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=float)

    L = ["| lever | host | suite | pairs | scen | gmean ratio | SD ln raw (adj) | SD between-scen means | sigma_b | sigma_w | ICC | "
         "+-10%: scen m=1/3/5 ; min scen | +-20%: scen m=1/3/5 ; min scen |", "|" + "---|" * 13]
    for s in strata:
        a, pl = s["cell_adjusted"], s["plan_cell_adjusted"]
        f = lambda k: f"{pl[k]['m1']['scenarios']}/{pl[k]['m3']['scenarios']}/{pl[k]['m5']['scenarios']} ; {pl[k]['min_scenarios_m_inf']}"
        L.append(f"| {s['lever']} | {s['host']} | {s['suite']} | {a['n_pairs']} | {a['n_scenarios']} | "
                 f"{a['gmean_ratio']:.3f} | {s['raw']['sd_ln_ratio']:.3f} ({a['sd_ln_ratio']:.3f}) | "
                 f"{a['sd_between_scenario_means']:.3f} | {a['sigma_between']:.3f} | {a['sigma_within']:.3f} | "
                 f"{a['icc']:.2f} | {f('pm10')} | {f('pm20')} |")
    L += ["", "Variance columns and plans are cell-adjusted. Pairs needed = scenarios x m.", "",
          "Per-turn ln-ratio, s1m (4-turn) pairs:", "",
          "| lever | host | pairs | turn obs | SD turn (all) | SD turn within session | sigma between sessions | ICC | within SD ex turn-index (ICC) | SD session ln | gmean ratio turn 1/2/3/4 |",
          "|" + "---|" * 11]
    for t in turn_strata:
        bt = "/".join(f"{t['by_turn'][k]['gmean_ratio']:.2f}" for k in sorted(t["by_turn"]))
        L.append(f"| {t['lever']} | {t['host']} | {t['n_pairs']} | {t['n_turn_obs']} | {t['sd_turn_ln_ratio_all']:.3f} | "
                 f"{t['sd_turn_ln_ratio_within_session']:.3f} | {t['sigma_between_sessions']:.3f} | "
                 f"{t['icc_turns_within_session']:.2f} | {t['sd_turn_within_session_ex_turn_index']:.3f} ({t['icc_ex_turn_index']:.2f}) | {t['sd_session_ln_ratio']:.3f} | {bt} |")
    with open(os.path.join(OUT, "step0_table.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
