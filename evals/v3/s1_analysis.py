#!/usr/bin/env python3
"""S1 (holdout-v3) preregistered analysis. Skeleton to be frozen with the preregistration; it computes nothing from data that
does not exist yet and is tested on synthetic data (tests/test_s1_analysis.py).

  python3 evals/v3/s1_analysis.py --sessions <paired.py rows out>/sessions.jsonl --out <dir> [--resamples 10000] [--seed 20261005]

Everything is stdlib. Inputs are the `sessions.jsonl` rows of `paired.py rows` (one row per session). Arm keys (design
evals/paired/holdout-v3.yaml): anchor = A0F|A0O, anchor_m = A0F-m|A0O-m, ph = PhF, ph_m = PhF-m, shipped = ShF|ShO,
shipped_m = ShO-m, pc = Pc (host `any`, used for both hosts), aa = the second anchor on a seeded 10% of scenario-reps.

Method (PLAN shared method + S1):
* cost basis `cost_usd_tools_normalized` plus the decider charge (judge_usage receipts x frozen Jev $/decision);
* a SCENARIO is the cluster: per scenario the within-scenario mean over its valid reps; cost ratio = geometric mean over
  scenarios of (policy cost / comparator cost); turn-pass difference = mean over scenarios; both with a scenario-cluster
  bootstrap (B resamples, one shared index draw so every contrast is resampled jointly);
* a session is VALID iff wave_valid, cost_valid, mechanism_engaged, cache_audit_clean and status != infra_fail. COST
  endpoints use a scenario-rep only when every session it needs is valid; QUALITY endpoints (turn-pass, final state) are
  unfiltered except for infrastructure failures, as in the effort-control studies;
* every decide-once policy (decider x strong effort x scope gate x keep_on_host) is the potential-outcome composition: per
  scenario-rep the cheap outcome (Pc) or the host outcome (PhF / PhF-m on Fable, ShO / ShO-m on Opus) the decider chose;
  the live Jev decision of a scenario-rep is read from its ShF session (served model Sonnet = cheap);
* hypotheses H1-H7 as preregistered, p-values from the same bootstrap (one-sided percentile; equivalence = TOST, the larger
  of the two one-sided p), Holm within family F1 = {H1, H3, H4, H6} and F2 = {H2, H5, H7} at alpha 0.05;
* the config-freeze rule, per host, deterministic (see `freeze`).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from evals.v3 import common  # noqa: E402

FROZEN = json.loads((REPO / "evals/v3/frozen_rule.json").read_text(encoding="utf-8"))
JEV_USD = FROZEN["constants"]["jev_usd_per_decision"]
SCOPE_LIMIT = FROZEN["R*"]["spec"]["scope_gate_max_workspace_files"]
CHEAP_PREFIX = "claude-sonnet-5"
KEEP_TYPES = ("review", "explain")
ALPHA = 0.05
FAMILIES = {"F1": ["H1", "H3", "H4", "H6"], "F2": ["H2", "H5", "H7"]}
OCCAM = {"plain-medium": 0, "bundle-unrouted": 1, "bundle+rule": 2, "bundle+jev": 3}      # simpler first
FREEZE = {"cost_upper_lt": 1.0, "turn_pass_lower_gt": -0.05, "final_state_point_ge": -0.03, "occam_tolerance": 0.03}


# ---------------------------------------------------------------------------------------------------- data
def valid(r: dict) -> bool:
    return bool(r.get("wave_valid", True) and r.get("cost_valid", True) and r.get("mechanism_engaged", True)
                and r.get("cache_audit_clean", True) and r.get("status") != "infra_fail")


def cost(r: dict) -> float:
    return float(r["cost_usd_tools_normalized"]) + JEV_USD * float((r.get("fd_receipt_counts") or {}).get("judge_usage", 0))


class Data:
    """Sessions by (scenario, rep, host, arm); Pc is host `any` and serves both hosts. Every session that did not fail for
    infrastructure reasons is kept: the QUALITY endpoints are unfiltered (as in the effort-control studies: a memory kill or a
    cache-audit flag must not hide a quality loss), while the COST endpoints use only fully valid sessions (`_cost_ok`)."""

    def __init__(self, rows: list):
        self.rows = rows
        self.by = {}
        for r in rows:
            if r.get("status") != "infra_fail":
                self.by[(r["scenario_id"], r["rep"], r["host"], r["arm"])] = {**r, "_cost_ok": valid(r)}
        self.meta = {}
        for r in rows:
            self.meta[r["scenario_id"]] = {"task_type": r["task_type"], "workspace_files": r["workspace_files"],
                                           "n_long_gaps": r["n_long_gaps"]}
        self.scenarios = sorted(self.meta)
        self.reps = sorted({r["rep"] for r in rows})

    def get(self, s, rep, host, arm):
        return self.by.get((s, rep, "any" if arm == "pc" else host, arm))

    def routed_live(self, s, rep) -> bool | None:
        """Did the live ShF session route to Sonnet (the Jev decision for this scenario-rep)? None if ShF is missing."""
        r = self.get(s, rep, "fable", "shipped")
        return None if r is None else any(str(m).startswith(CHEAP_PREFIX) for m in r.get("served_models") or [])


# ---------------------------------------------------------------------------------------------------- outcomes / policies
def arm_outcomes(d: Data, host: str, arm: str) -> dict:
    """{(scenario, rep): row} of one arm."""
    return {(s, rep): r for s in d.scenarios for rep in d.reps if (r := d.get(s, rep, host, arm)) is not None}


def decider_choice(d: Data, host: str, decider: str, s: str, rep: int) -> str | None:
    """'cheap' | 'host' | None (not computable) for a decider that does NOT yet include the scope gate or keep_on_host."""
    if decider == "always_route":
        return "cheap"
    if decider == "always_host":
        return "host"
    if decider == "rstar":                                  # R* without its scope gate = always route
        return "cheap"
    if decider == "jev":                                    # the live decision (scope gate and judge together)
        live = d.routed_live(s, rep)
        return None if live is None else ("cheap" if live else "host")
    raise ValueError(decider)


def policy(d: Data, host: str, *, decider: str, strong: str, scope: bool, keep: tuple = ()) -> dict:
    """Potential-outcome composition {(scenario, rep): row}. strong in {default, medium}; scope = the 300-file gate on;
    keep = task types kept on the host. `jev` with scope off is not computable (the judge was not asked where the gate fired)."""
    if decider == "jev" and not scope:
        return {}
    host_arm = {("fable", "default"): "ph", ("fable", "medium"): "ph_m",
                ("opus", "default"): "shipped", ("opus", "medium"): "shipped_m"}[(host, strong)]
    hostd, cheapd, out = arm_outcomes(d, host, host_arm), arm_outcomes(d, host, "pc"), {}
    for (s, rep), host_row in hostd.items():
        choice = decider_choice(d, host, decider, s, rep)
        if choice is None:
            continue
        m = d.meta[s]
        if scope and decider != "jev" and m["workspace_files"] > SCOPE_LIMIT:
            choice = "host"
        if keep and m["task_type"] in keep:
            choice = "host"
        row = host_row if choice == "host" else cheapd.get((s, rep))
        if row is not None:
            out[(s, rep)] = row
    return out


def oracle(d: Data, host: str, strong: str) -> dict:
    """Cross-fitted oracle: the choice for (s, rep) is made from the OTHER rep: the cheaper outcome unless its turn-pass is
    below the host outcome's. A scenario with one rep has no oracle."""
    host_arm = {("fable", "default"): "ph", ("fable", "medium"): "ph_m", ("opus", "default"): "shipped",
                ("opus", "medium"): "shipped_m"}[(host, strong)]
    hostd, cheapd, out = arm_outcomes(d, host, host_arm), arm_outcomes(d, host, "pc"), {}
    for (s, rep), host_row in hostd.items():
        others = [o for o in d.reps if o != rep and (s, o) in hostd and (s, o) in cheapd]
        if not others:
            continue
        o = others[0]
        cheap_better = cost(cheapd[(s, o)]) < cost(hostd[(s, o)]) and cheapd[(s, o)]["turn_pass_frac"] >= hostd[(s, o)]["turn_pass_frac"]
        row = cheapd.get((s, rep)) if cheap_better else host_row
        if row is not None:
            out[(s, rep)] = row
    return out


# ---------------------------------------------------------------------------------------------------- bootstrap contrasts
class Boot:
    """One shared set of scenario resamples for every contrast (B x n_scenarios indices, seeded)."""

    def __init__(self, scenarios: list, resamples: int, seed: int):
        rng = random.Random(seed)
        n = len(scenarios)
        self.idx = [[rng.randrange(n) for _ in range(n)] for _ in range(resamples)]
        self.pos = {s: i for i, s in enumerate(scenarios)}

    def draws(self, per_scenario: dict, stat) -> list:
        vals = [per_scenario.get(s) for s in self.pos]
        out = []
        for ix in self.idx:
            sample = [vals[i] for i in ix if vals[i] is not None]
            out.append(stat(sample) if sample else float("nan"))
        return out


def _gm(xs):
    return math.exp(common.mean(xs))


def contrast(a: dict, b: dict, boot: Boot, subset=None) -> dict:
    """a vs b ({(s, rep): row}): scenario-level log cost ratio, turn-pass and final-state differences."""
    log_ratio, dtp, dfs = {}, {}, {}
    for s in boot.pos:
        if subset is not None and s not in subset:
            continue
        reps = [k for k in a if k[0] == s and k in b]
        if not reps:
            continue
        dtp[s] = common.mean(a[k]["turn_pass_frac"] - b[k]["turn_pass_frac"] for k in reps)
        dfs[s] = common.mean(float(bool(a[k]["final_state_pass"])) - float(bool(b[k]["final_state_pass"])) for k in reps)
        ok = [k for k in reps if a[k]["_cost_ok"] and b[k]["_cost_ok"]]
        if not ok:
            continue
        ca, cb = common.mean(cost(a[k]) for k in ok), common.mean(cost(b[k]) for k in ok)
        if ca > 0 and cb > 0:
            log_ratio[s] = math.log(ca / cb)
    if not log_ratio:
        return {"n_scenarios": 0}
    r = {"n_scenarios": len(log_ratio), "n_pairs": sum(1 for k in a if k in b and a[k]["_cost_ok"] and b[k]["_cost_ok"]),
         "n_pairs_quality": sum(1 for k in a if k in b)}
    dr = boot.draws(log_ratio, lambda xs: math.exp(common.mean(xs)))
    dt = boot.draws(dtp, common.mean)
    df = boot.draws(dfs, common.mean)
    r["gm_ratio"] = _gm(log_ratio.values())
    r["d_turn_pass"], r["d_final_state"] = common.mean(dtp.values()), common.mean(dfs.values())
    for name, draws in (("gm_ratio", dr), ("d_turn_pass", dt), ("d_final_state", df)):
        clean = [x for x in draws if not math.isnan(x)]
        r[name + "_draws"] = clean
        r[name + "_ci95"] = [common.quantile(clean, 0.025), common.quantile(clean, 0.975)]
        r[name + "_ci90"] = [common.quantile(clean, 0.05), common.quantile(clean, 0.95)]
    return r


def p_below(draws: list, bound: float) -> float:
    """One-sided bootstrap p for H0: theta >= bound (evidence that theta < bound)."""
    return (1 + sum(1 for x in draws if x >= bound)) / (len(draws) + 1)


def p_above(draws: list, bound: float) -> float:
    """One-sided bootstrap p for H0: theta <= bound (evidence that theta > bound)."""
    return (1 + sum(1 for x in draws if x <= bound)) / (len(draws) + 1)


def p_equiv(draws: list, lo: float, hi: float) -> float:
    return max(p_above(draws, lo), p_below(draws, hi))


def public(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.endswith("_draws")}


# ---------------------------------------------------------------------------------------------------- hypotheses
def hypotheses(d: Data, boot: Boot) -> dict:
    out = {}
    anchor_f, anchor_o = arm_outcomes(d, "fable", "anchor"), arm_outcomes(d, "opus", "anchor")
    cstar_f = policy(d, "fable", decider="rstar", strong="medium", scope=True)
    # H1: C*_F vs A0F
    c = contrast(cstar_f, anchor_f, boot)
    if c["n_scenarios"]:
        out["H1"] = {"family": "F1", "statement": "C*_F vs A0F: cost-ratio upper bound < 0.75 and turn-pass lower bound > -0.05",
                     "estimate": public(c), "p": max(p_below(c["gm_ratio_draws"], 0.75), p_above(c["d_turn_pass_draws"], -0.05)),
                     "rule": "gm_ratio_ci95[1] < 0.75 and d_turn_pass_ci95[0] > -0.05"}
    # H2: decider value, policy(Jev) vs policy(R*) on Fable, both with strong medium and the scope gate
    jev = policy(d, "fable", decider="jev", strong="medium", scope=True)
    c = contrast(jev, cstar_f, boot)
    if c["n_scenarios"]:
        disc = sum(1 for k in jev if k in cstar_f and jev[k]["arm"] != cstar_f[k]["arm"])
        decision = h2_decision(c)
        out["H2"] = {"family": "F2", "statement": "policy(Jev) vs policy(R*) on Fable: equivalence on cost (+-5%) and turn-pass (+-0.02)",
                     "estimate": public(c), "discordant_scenario_reps": disc, "n_scenario_reps": len(jev), "decision": decision,
                     "p": max(p_equiv(c["gm_ratio_draws"], 0.95, 1.05), p_equiv(c["d_turn_pass_draws"], -0.02, 0.02)),
                     "rule": "equivalence: gm_ratio_ci90 within [0.95, 1.05] and d_turn_pass_ci90 within [-0.02, +0.02] => ship R*; "
                             "Jev ships only if gm_ratio_ci90[1] < 0.95 and d_turn_pass_ci90[0] >= -0.02; otherwise R* (simpler)"}
    # H3: overhead of the unrouted bundle on Opus (ShO/A0O) and on Fable (PhF/A0F), equivalence [0.95, 1.05]
    for key, host, arm in (("H3", "opus", "shipped"), ("H3b", "fable", "ph")):
        c = contrast(arm_outcomes(d, host, arm), arm_outcomes(d, host, "anchor"), boot)
        if c["n_scenarios"]:
            ent = {"family": "F1" if key == "H3" else None, "statement": f"{arm}/anchor on {host}: 90% CI inside [0.95, 1.05]",
                   "estimate": public(c), "p": p_equiv(c["gm_ratio_draws"], 0.95, 1.05), "rule": "gm_ratio_ci90 within [0.95, 1.05]"}
            if key == "H3b":
                ent["decomposition"] = decomposition(d, "fable", "ph", "anchor")
                ent["note"] = "descriptive (PLAN S1: H3 'also PhF/A0F, decomposed'); not in a Holm family"
            else:
                ent["decomposition"] = decomposition(d, "opus", "shipped", "anchor")
            out[key] = ent
    # H4: Opus medium
    c = contrast(arm_outcomes(d, "opus", "anchor_m"), anchor_o, boot)
    if c["n_scenarios"]:
        out["H4"] = {"family": "F1", "statement": "A0O-m vs A0O: cost upper bound < 1.0 and turn-pass lower bound > -0.05",
                     "estimate": public(c), "p": max(p_below(c["gm_ratio_draws"], 1.0), p_above(c["d_turn_pass_draws"], -0.05)),
                     "rule": "gm_ratio_ci95[1] < 1.0 and d_turn_pass_ci95[0] > -0.05"}
        c2 = contrast(arm_outcomes(d, "opus", "shipped_m"), arm_outcomes(d, "opus", "shipped"), boot)
        if c2["n_scenarios"]:
            out["H4"]["shipped_default"] = {"statement": "ShO-m vs ShO (the shipped default question)", "estimate": public(c2)}
    # H5: routing to Sonnet still loses on Opus
    c = contrast(arm_outcomes(d, "opus", "pc"), anchor_o, boot)
    if c["n_scenarios"]:
        out["H5"] = {"family": "F2", "statement": "Pc/A0O lower bound > 1.0", "estimate": public(c),
                     "p": p_above(c["gm_ratio_draws"], 1.0), "rule": "gm_ratio_ci95[0] > 1.0"}
    # H6: live ShF equals its decomposition-predicted outcome
    live, pred = {}, {}
    for (s, rep), r in arm_outcomes(d, "fable", "shipped").items():
        routed = d.routed_live(s, rep)
        p = d.get(s, rep, "fable", "pc" if routed else "ph")
        if p is not None:
            live[(s, rep)], pred[(s, rep)] = r, p
    c = contrast(live, pred, boot)
    if c["n_scenarios"]:
        out["H6"] = {"family": "F1", "statement": "ShF observed / decomposition-predicted inside [0.95, 1.05] (90% CI)",
                     "estimate": public(c), "p": p_equiv(c["gm_ratio_draws"], 0.95, 1.05), "rule": "gm_ratio_ci90 within [0.95, 1.05]",
                     "route_share_live": common.mean(1.0 if d.routed_live(*k) else 0.0 for k in live)}
    # H7: task types; Pc - PhF-m turn-pass on review U explain (and feature, exploratory)
    keep = {s for s in d.scenarios if d.meta[s]["task_type"] in KEEP_TYPES}
    c = contrast(arm_outcomes(d, "fable", "pc"), arm_outcomes(d, "fable", "ph_m"), boot, subset=keep)
    if c["n_scenarios"]:
        out["H7"] = {"family": "F2", "statement": "Pc - PhF-m turn-pass on review U explain is non-inferior (> -0.05); "
                                                  "not supported => ship keep_on_host: [review, explain]",
                     "estimate": public(c), "p": p_above(c["d_turn_pass_draws"], -0.05),
                     "rule": "d_turn_pass_ci95[0] < -0.05 (cannot exclude a 5-point loss) => keep_on_host [review, explain] ships; "
                             "otherwise the opt-out example is removed. Supported = non-inferior = opt-out removed",
                     "feature_exploratory": public(contrast(arm_outcomes(d, "fable", "pc"), arm_outcomes(d, "fable", "ph_m"), boot,
                                                            subset={s for s in d.scenarios if d.meta[s]["task_type"] == "feature"}))}
    holm(out)
    return out


def h2_decision(c: dict) -> str:
    lo, hi = c["gm_ratio_ci90"]
    tlo, thi = c["d_turn_pass_ci90"]
    if 0.95 <= lo and hi <= 1.05 and -0.02 <= tlo and thi <= 0.02:
        return "equivalent: ship R* (no external call, no consent)"
    if hi < 0.95 and tlo >= -0.02:
        return "Jev better beyond the margin: ship Jev"
    return "inconclusive or R* better: ship R* (simpler); Jev stays opt-in"


def holm(hyps: dict) -> None:
    for fam, ids in FAMILIES.items():
        present = sorted((h for h in ids if h in hyps), key=lambda h: hyps[h]["p"])
        m, running = len(present), 0.0
        for i, h in enumerate(present):
            running = max(running, min(1.0, hyps[h]["p"] * (m - i)))
            hyps[h]["p_holm"], hyps[h]["supported"] = running, running < ALPHA
        # a family member that could not be computed is reported as missing, never as supported
    for h, v in hyps.items():
        v.setdefault("p_holm", None)
        v.setdefault("supported", None)


def decomposition(d: Data, host: str, arm: str, base: str) -> dict:
    """Token and receipt components of the overhead: sum over valid pairs of arm vs base."""
    a, b = arm_outcomes(d, host, arm), arm_outcomes(d, host, base)
    keys = [k for k in a if k in b]

    def tok(rows, field):
        return sum(sum(float(t.get(field, 0)) for t in (r.get("tokens") or {}).values()) for r in rows)
    out = {"pairs": len(keys)}
    for field in ("input", "cache_read", "cache_write", "output"):
        den = tok([b[k] for k in keys], field)
        out[field + "_ratio"] = tok([a[k] for k in keys], field) / den if den else None
    nb = sum(b[k]["n_req"] for k in keys)
    out["n_req_ratio"] = sum(a[k]["n_req"] for k in keys) / nb if nb else None
    out["judge_usd_total"] = sum(JEV_USD * float((a[k].get("fd_receipt_counts") or {}).get("judge_usage", 0)) for k in keys)
    out["keepalive_receipts"] = sum(int((a[k].get("fd_receipt_counts") or {}).get("cache_keepalive", 0)) for k in keys)
    out["waste_guard_receipts"] = sum(int((a[k].get("fd_receipt_counts") or {}).get("waste_guard", 0)) for k in keys)
    return out


# ---------------------------------------------------------------------------------------------------- config freeze
def configs(d: Data, host: str) -> dict:
    """The preregistered candidate set per host: {name: (simplicity class, outcomes)}. Everything is a composition of
    Pc / host outcomes or a measured plain/bundle arm; nothing outside this enumeration can be shipped."""
    out = {}
    out["plain-medium"] = ("plain-medium", arm_outcomes(d, host, "anchor_m"))
    if host == "fable":
        out["bundle-unrouted default"] = ("bundle-unrouted", arm_outcomes(d, host, "ph"))
        out["bundle-unrouted medium"] = ("bundle-unrouted", arm_outcomes(d, host, "ph_m"))
    else:
        out["bundle-unrouted default"] = ("bundle-unrouted", arm_outcomes(d, host, "shipped"))
        out["bundle-unrouted medium"] = ("bundle-unrouted", arm_outcomes(d, host, "shipped_m"))
    for decider, klass in (("rstar", "bundle+rule"), ("jev", "bundle+jev"), ("always_route", "bundle+rule")):
        for strong in ("default", "medium"):
            for scope in (True, False):
                for keep in ((), KEEP_TYPES):
                    pol = policy(d, host, decider=decider, strong=strong, scope=scope, keep=keep)
                    if pol:
                        name = f"{decider} | strong {strong} | scope {'300' if scope else 'off'} | keep {'+'.join(keep) or 'none'}"
                        out[name] = (klass, pol)
    return out


def freeze(d: Data, boot: Boot, host: str) -> dict:
    """Deterministic: candidates = cost upper < 1.0, turn-pass lower > -0.05, final-state point >= -0.03 vs the host's plain
    default; ship the cheapest; any candidate within 3% of the cheapest that is simpler wins (Occam order: plain-medium <
    bundle-unrouted < bundle + rule decider < bundle + Jev decider); not C*_h => 'selected on holdout' (must replicate in S2)."""
    base = arm_outcomes(d, host, "anchor")
    rows = []
    for name, (klass, out) in configs(d, host).items():
        c = contrast(out, base, boot)
        if not c["n_scenarios"]:
            continue
        ok = (c["gm_ratio_ci95"][1] < FREEZE["cost_upper_lt"] and c["d_turn_pass_ci95"][0] > FREEZE["turn_pass_lower_gt"]
              and c["d_final_state"] >= FREEZE["final_state_point_ge"])
        rows.append({"config": name, "class": klass, "candidate": ok, **public(c)})
    cands = [r for r in rows if r["candidate"]]
    chosen = None
    if cands:
        cheapest = min(cands, key=lambda r: r["gm_ratio"])
        near = [r for r in cands if r["gm_ratio"] <= cheapest["gm_ratio"] * (1 + FREEZE["occam_tolerance"])]
        chosen = min(near, key=lambda r: (OCCAM[r["class"]], r["gm_ratio"], r["config"]))
    preregistered = "rstar | strong medium | scope 300 | keep none" if host == "fable" else "bundle-unrouted medium"
    return {"host": host, "preregistered_C*": preregistered, "chosen": chosen["config"] if chosen else None,
            "selected_on_holdout": bool(chosen) and chosen["config"] != preregistered,
            "ship_default": chosen is None, "table": rows}


# ---------------------------------------------------------------------------------------------------- policy value, noise, health
def regret(d: Data, boot: Boot, host: str) -> dict:
    """$ per 1,000 sessions of the decide-once policies vs the cross-fitted oracle (same strong effort)."""
    out = {}
    for strong in ("default", "medium"):
        orc = oracle(d, host, strong)
        for decider in ("rstar", "jev", "always_host"):
            pol = policy(d, host, decider=decider, strong=strong, scope=True)
            keys = [k for k in pol if k in orc and pol[k]["_cost_ok"] and orc[k]["_cost_ok"]]
            if keys:
                out[f"{decider} | strong {strong}"] = {
                    "n_scenario_reps": len(keys),
                    "regret_usd_per_1000": 1000 * (common.mean(cost(pol[k]) for k in keys) - common.mean(cost(orc[k]) for k in keys)),
                    "route_share": common.mean(1.0 if pol[k]["arm"] == "pc" else 0.0 for k in keys)}
    return out


def noise_floor(d: Data) -> dict:
    out = {}
    for host in ("fable", "opus"):
        aa, an = arm_outcomes(d, host, "aa"), arm_outcomes(d, host, "anchor")
        keys = [k for k in aa if k in an and aa[k]["_cost_ok"] and an[k]["_cost_ok"]]
        lr = [math.log(cost(aa[k]) / cost(an[k])) for k in keys if cost(aa[k]) > 0 and cost(an[k]) > 0]
        if lr:
            out[host] = {"n": len(lr), "gm_ratio": math.exp(common.mean(lr)),
                         "sd_log_ratio": math.sqrt(sum((x - common.mean(lr)) ** 2 for x in lr) / max(len(lr) - 1, 1)),
                         "d_turn_pass": common.mean(aa[k]["turn_pass_frac"] - an[k]["turn_pass_frac"] for k in keys)}
    return out


def health(rows: list) -> dict:
    by_arm = {}
    for r in rows:
        k = f"{r['arm']}@{r['host']}"
        e = by_arm.setdefault(k, {"sessions": 0, "valid": 0, "mechanism_failed": 0, "cache_audit_flagged": 0, "infra_fail": 0,
                                  "killed_memory": 0})
        e["sessions"] += 1
        e["valid"] += valid(r)
        e["mechanism_failed"] += not r.get("mechanism_engaged", True)
        e["cache_audit_flagged"] += not r.get("cache_audit_clean", True)
        e["infra_fail"] += r.get("status") == "infra_fail"
        e["killed_memory"] += bool(r.get("killed_memory"))
    n = len(rows)
    stop = []
    shf_bad = sum(1 for r in rows if r["arm"] == "shipped" and r["host"] == "fable" and not r.get("mechanism_engaged", True))
    if shf_bad:
        stop.append(f"{shf_bad} ShF sessions failed the mechanism gate (decided once but switched or wrong effort): product bug, STOP")
    if n and sum(e["mechanism_failed"] for e in by_arm.values()) / n > 0:
        stop.append("mechanism-gate failures present: stop rule applies (see the preregistration)")
    if n and sum(e["cache_audit_flagged"] for e in by_arm.values()) / n > 0.02:
        stop.append("cache-audit flags above 2% of sessions")
    return {"n_sessions": n, "by_arm": by_arm, "stop_rule_triggers": stop}


# ---------------------------------------------------------------------------------------------------- main
def analyse(rows: list, resamples: int = 10_000, seed: int = 20261005) -> dict:
    d = Data(rows)
    boot = Boot(d.scenarios, resamples, seed)
    result = {"schema": "fast-decisions-v3-s1-result/v1", "resamples": resamples, "seed": seed,
              "n_scenarios": len(d.scenarios), "health": health(rows), "noise_floor": noise_floor(d),
              "hypotheses": hypotheses(d, boot)}
    result["regret"] = {h: regret(d, boot, h) for h in ("fable", "opus")}
    result["freeze"] = {h: freeze(d, boot, h) for h in ("fable", "opus")}
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resamples", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=20261005)
    a = ap.parse_args()
    rows = [json.loads(line) for line in Path(a.sessions).read_text(encoding="utf-8").splitlines() if line.strip()]
    res = analyse(rows, a.resamples, a.seed)
    common.write_json(Path(a.out) / "s1_result.json", res)
    for h, v in sorted(res["hypotheses"].items()):
        e = v["estimate"]
        print(f"{h}: gm_ratio {e.get('gm_ratio'):.3f} {e.get('gm_ratio_ci95')}  d_turn_pass {e.get('d_turn_pass'):+.3f}  "
              f"p_holm {v['p_holm']}  supported {v['supported']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
