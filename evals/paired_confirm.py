"""Confirmatory analysis for paired campaign main-v1.

The hypotheses, thresholds, train/test split and decision rule are those of evals/paired/PREREGISTRATION-main-v1.md.
The estimator itself (bootstrap resamples and seed, the pair-level quality filter, which cells count as savings
claims, and the verdict rule including "contradicted") is NOT in the preregistration: it was fixed in this script,
written after the campaign's data were collected (first committed in c3ea41a, about 55 minutes after the campaign
finished, when exploratory all-split summaries from evals/paired_model.py already existed).

Input : <campaign>/rows/{sessions,pairs}.jsonl and <campaign>/model/{model,predictions}.json (from evals/paired_model.py).
Output: <campaign>/confirm/{confirm.json,CONFIRM.md}. No API calls; seeded and deterministic.

Confirmatory (test split only)
  * Primary endpoint: geometric-mean cost ratio arm/anchor per host, scenario-cluster bootstrap 95% CI (resample
    scenarios, then reps inside each drawn scenario), "among pairs where quality is non-inferior (turn-pass fraction
    margin -0.05)". The text can be read two ways and both are computed:
      - reading "pair"  (matches the text: the restriction is on *pairs*): keep a pair only if its own
        delta_turn_pass > -0.05. Turn-pass fractions move in steps of 1/turns >= 1/16 = 0.0625, so in this design that
        is the same as delta_turn_pass >= 0 (the arm passed at least as many scripted turns as its anchor).
      - reading "arm"  (sensitivity): all cost-valid pairs; the arm x host cell counts only if its arm-level quality
        non-inferiority holds (the separate Quality hypothesis).
  * H1/H2/H3/Quality verdicts. One rule for every hypothesis, fixed in this script (after data collection, before
    this script's test-split numbers were looked at):
      confirmed      = the 95% CI lies entirely on the hypothesis side of its preregistered threshold
      contradicted   = the 95% CI lies entirely on the other side of that same threshold
      not confirmed  = otherwise.
    Thresholds: H1 upper < 1.0; H2 lower > 0.95; H3 upper <= 1.05; Quality lower > -0.05.
    A multi-part hypothesis is confirmed when every part is, contradicted when any part is, else not confirmed.
  * H3 "paired ratio sticky/shipped": per (scenario, rep, host) exp(y_sticky - y_shipped) (same anchor, so the anchor
    cancels). Pair reading: both the sticky and the shipped pair are pair-level non-inferior; arm reading: all triplets.
  * Prediction-model check: re-run paired_model.predict from model/model.json (must reproduce model/predictions.json),
    verdict on the preregistered bounds: 90% PI coverage in [0.80, 0.97] (log-ratio model and delta-$ model) and the
    observed test-total saving inside its 90% PI.
  * Decision rule per host.

Exploratory (labelled as such): final hidden-test pass + McNemar (all splits), A/A noise floor, interim vs final ratios,
raw cost basis, savings per 1,000 sessions (delta-$ model workload for a stated mix, and empirical mean delta x 1000).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paired_model as pm  # noqa: E402

SCHEMA = "fast-decisions-paired-confirm/v1"
SEED = 20261002
BOOT = 10_000                       # chosen here; the preregistration does not fix the number of resamples
NI = -0.05                          # turn-pass non-inferiority margin
ARMS = ("shipped", "sticky", "sonnet")
HOSTS = ("fable", "opus")
READINGS = ("pair", "arm")
PREREG_COVERAGE = (0.80, 0.97)
N_TEST_SCENARIOS = 23

# (threshold, side, inclusive): side "below" = the hypothesis says the value is below the threshold
RULES = {"H1": (1.0, "below", False), "H2": (0.95, "above", False), "H3": (1.05, "below", True), "Q": (NI, "above", False)}

INTERIM = {   # dashboard numbers seen during the run (train only, partial) and at the pilot (pilot-v1)
    "interim_train_partial": {"fable": {"shipped": 0.70, "sticky": 0.60, "sonnet": 0.58, "aa": 0.95},
                              "opus": {"shipped": 1.12, "sticky": 1.11, "sonnet": 1.36, "aa": 1.09}},
    "pilot": {"fable": {"sticky": 0.53, "shipped": 0.65, "sonnet": 0.62},
              "opus": {"sticky": 1.46, "shipped": 1.35, "sonnet": 1.66}},
}


# ----------------------------------------------------------------------------------------------- verdict logic

def verdict(lo, hi, rule: str) -> str:
    """confirmed / contradicted / not confirmed for one CI against the hypothesis' preregistered threshold."""
    if lo is None or hi is None:
        return "not confirmed"
    t, side, inclusive = RULES[rule]
    if side == "below":
        if hi < t or (inclusive and hi == t):
            return "confirmed"
        return "contradicted" if lo > t else "not confirmed"
    if lo > t or (inclusive and lo == t):
        return "confirmed"
    return "contradicted" if hi < t else "not confirmed"


def combine(parts) -> str:
    parts = list(parts)
    if parts and all(p == "confirmed" for p in parts):
        return "confirmed"
    return "contradicted" if "contradicted" in parts else "not confirmed"


def pair_noninferior(r: dict) -> bool:
    return r.get("dtp") is not None and r["dtp"] > NI


# ----------------------------------------------------------------------------------------------- endpoints

def boot_interval(values, clusters, seed: int, key, B: int, level: float = 0.95):
    """Scenario-cluster bootstrap (scenarios, then reps) via paired_model; 90% ranges use the same resampling."""
    if level == 0.95:
        return pm.cluster_boot_mean(values, clusters, pm.rng_for(seed, *key), B)
    return _boot_level(values, clusters, pm.rng_for(seed, *key), B, level)


def _boot_level(values, clusters, rng, B, level):
    """Same two-stage resampling as paired_model.cluster_boot_mean, any two-sided percentile level."""
    v = np.asarray(values, float)
    if len(v) == 0:
        return None, None, None, 0
    groups = defaultdict(list)
    for x, c in zip(v, clusters):
        groups[c].append(x)
    S = len(groups)
    if S < 2:
        return float(v.mean()), None, None, S
    kmax = max(len(x) for x in groups.values())
    M, k = np.zeros((S, kmax)), np.zeros(S, int)
    for i, x in enumerate(groups.values()):
        M[i, :len(x)], k[i] = x, len(x)
    sc = rng.integers(0, S, (B, S))
    ks = k[sc]
    pick = np.minimum((rng.random((B, S, kmax)) * ks[..., None]).astype(int), ks[..., None] - 1)
    mask = np.arange(kmax)[None, None, :] < ks[..., None]
    out = (M[sc[..., None], pick] * mask).sum((1, 2)) / mask.sum((1, 2))
    a = (1 - level) / 2 * 100
    lo, hi = np.percentile(out, [a, 100 - a])
    return float(v.mean()), float(lo), float(hi), S


def gm_endpoint(rows: list, seed: int, key, B: int) -> dict:
    """Geometric-mean ratio exp(mean log ratio) with its scenario-cluster bootstrap 95% CI."""
    if not rows:
        return {"n_pairs": 0, "n_scenarios": 0, "gm_ratio": None, "ci95": [None, None]}
    est, lo, hi, S = boot_interval([r["y"] for r in rows], [r["scenario"] for r in rows], seed, key, B)
    assert est is not None
    return {"n_pairs": len(rows), "n_scenarios": S, "mean_log_ratio": pm._f(est), "gm_ratio": pm._f(math.exp(est)),
            "ci95": [None if lo is None else pm._f(math.exp(lo)), None if hi is None else pm._f(math.exp(hi))]}


def primary_endpoints(test: list, seed: int, B: int, tag: str = "primary") -> dict:
    """{reading: {host: {arm: endpoint}}}; both readings use the cost-valid test pairs."""
    cost = pm._cost_rows(test)
    out = {rd: {h: {} for h in HOSTS} for rd in READINGS}
    for h in HOSTS:
        for a in ARMS:
            cell = [r for r in cost if r["host"] == h and r["arm"] == a]
            keep = [r for r in cell if pair_noninferior(r)]
            e = gm_endpoint(keep, seed, (tag, "pair", h, a), B)
            e.update({"n_cost_valid": len(cell), "n_excluded_quality": len(cell) - len(keep)})
            out["pair"][h][a] = e
            out["arm"][h][a] = gm_endpoint(cell, seed, (tag, "arm", h, a), B)
    return out


def h3_endpoints(test: list, seed: int, B: int) -> dict:
    by = defaultdict(dict)
    for r in pm._cost_rows(test):
        if r["arm"] in ("sticky", "shipped"):
            by[(r["scenario"], r["rep"], r["host"])][r["arm"]] = r
    out = {rd: {} for rd in READINGS}
    for h in HOSTS:
        trip = [v for k, v in sorted(by.items(), key=lambda kv: str(kv[0])) if k[2] == h and len(v) == 2]
        for rd in READINGS:
            keep = [v for v in trip if rd == "arm" or (pair_noninferior(v["sticky"]) and pair_noninferior(v["shipped"]))]
            rows = [{"y": v["sticky"]["y"] - v["shipped"]["y"], "scenario": v["sticky"]["scenario"]} for v in keep]
            e = gm_endpoint(rows, seed, ("h3", rd, h), B)
            e["n_triplets_available"] = len(trip)
            out[rd][h] = e
    return out


def quality_endpoints(test: list, seed: int, B: int) -> dict:
    """Arm-level turn-pass non-inferiority per arm x host: mean delta_turn_pass, 95% bootstrap CI, lower bound > -0.05."""
    q = [r for r in test if r["quality_ok"] and r["dtp"] is not None]
    out = {h: {} for h in HOSTS}
    for h in HOSTS:
        for a in ARMS:
            rs = [r for r in q if r["host"] == h and r["arm"] == a]
            est, lo, hi, S = boot_interval([r["dtp"] for r in rs], [r["scenario"] for r in rs], seed, ("quality", h, a), B)
            out[h][a] = {"n_pairs": len(rs), "n_scenarios": S, "mean_delta_turn_pass": pm._f(est, 4),
                         "ci95": [pm._f(lo, 4), pm._f(hi, 4)], "verdict": verdict(lo, hi, "Q")}
    return out


# ----------------------------------------------------------------------------------------------- hypotheses + decision

def hypotheses(primary: dict, h3: dict, quality: dict) -> dict:
    """Verdicts for one reading. primary = {host: {arm: ep}}, h3 = {host: ep}, quality = {host: {arm: q}}."""
    def part(h, a, rule):
        e = primary[h][a]
        return {"host": h, "arm": a, "gm_ratio": e["gm_ratio"], "ci95": e["ci95"], "n_pairs": e["n_pairs"],
                "verdict": verdict(e["ci95"][0], e["ci95"][1], rule)}
    h1 = [part("fable", a, "H1") for a in ("sticky", "shipped")]
    h2 = [part("opus", a, "H2") for a in ("sticky", "shipped", "sonnet")]
    h3p = [{"host": h, "gm_ratio": h3[h]["gm_ratio"], "ci95": h3[h]["ci95"], "n_pairs": h3[h]["n_pairs"],
            "verdict": verdict(h3[h]["ci95"][0], h3[h]["ci95"][1], "H3")} for h in HOSTS]
    claims = []   # every cell whose cost CI shows a saving is a savings claim and needs quality non-inferiority
    for h in HOSTS:
        for a in ARMS:
            ci = primary[h][a]["ci95"]
            if verdict(ci[0], ci[1], "H1") == "confirmed":
                claims.append({"host": h, "arm": a, **{k: quality[h][a][k] for k in ("mean_delta_turn_pass", "ci95", "verdict")}})
    return {"H1": {"verdict": combine(p["verdict"] for p in h1), "parts": h1},
            "H2": {"verdict": combine(p["verdict"] for p in h2), "parts": h2},
            "H3": {"verdict": combine(p["verdict"] for p in h3p), "parts": h3p},
            "Quality": {"verdict": combine(c["verdict"] for c in claims) if claims else "no savings claim to test",
                        "savings_claims": claims}}


def decision(hyp: dict, quality: dict) -> dict:
    """Preregistered rule: H1 (with non-inferior quality) -> route, sticky if H3 holds; H2 -> do not route to Sonnet."""
    out = {}
    h1_ok = hyp["H1"]["verdict"] == "confirmed"
    q_ok = all(quality["fable"][a]["verdict"] == "confirmed" for a in ("sticky", "shipped"))
    h3_ok = hyp["H3"]["verdict"] == "confirmed"
    if h1_ok and q_ok:
        arm = "sticky" if h3_ok else "shipped"
        why = f"H1 confirmed with non-inferior quality for sticky and shipped; H3 {'confirmed' if h3_ok else 'not confirmed'}"
        out["fable"] = {"recommendation": f"route ({arm})", "arm": arm, "rule_fired": "H1", "why": why}
    else:
        why = (f"H1 {hyp['H1']['verdict']}" + ("" if q_ok else "; quality non-inferiority not shown for both routed arms"))
        out["fable"] = {"recommendation": "plain host model (no preregistered routing rule fired)", "arm": "anchor",
                        "rule_fired": None, "why": why}
    if hyp["H2"]["verdict"] == "confirmed":
        out["opus"] = {"recommendation": "do not route to Sonnet: plain host model", "arm": "anchor", "rule_fired": "H2",
                       "why": "H2 confirmed: sticky, shipped and sonnet all show no saving (CI lower > 0.95)"}
    else:
        out["opus"] = {"recommendation": "plain host model (H2 not confirmed; no saving confirmed either)", "arm": "anchor",
                       "rule_fired": None, "why": f"H2 {hyp['H2']['verdict']}"}
    return out


# ----------------------------------------------------------------------------------------------- model check

def model_check(model: dict, ds: dict, on_disk: dict | None, draw_seed: int) -> dict:
    pred = pm.predict(model, ds, ("test",), D=(on_disk or {}).get("draws", 4000), seed=(on_disk or {}).get("seed", 0))
    o = pred["overall"]
    lo, hi = PREREG_COVERAGE
    checks = {"coverage_log_ratio_in_0.80_0.97": lo <= o["coverage_log_ratio"] <= hi,
              "coverage_saving_delta_model_in_0.80_0.97": lo <= o["coverage_saving_delta_model"] <= hi,
              "test_total_saving_inside_pi90": bool(o["observed_total_in_pi"])}
    reproduced = None
    if on_disk and "overall" in on_disk:
        keys = ("coverage_log_ratio", "coverage_saving_delta_model", "observed_total_saving_usd", "predicted_total_pi90")
        reproduced = all(on_disk["overall"][k] == o[k] for k in keys)
    alt = pm.predict(model, ds, ("test",), D=4000, seed=draw_seed)["overall"]
    keep = ("n_pairs", "coverage_log_ratio", "coverage_saving_delta_model", "coverage_saving_ratio_model",
            "observed_total_saving_usd", "predicted_total_saving_usd", "predicted_total_pi90", "observed_total_in_pi",
            "calibration_slope", "mean_error_saving_delta_model_usd", "mean_error_log_ratio")
    return {"n_test_pairs": pred["n_test_pairs"], "n_test_scenarios": pred["n_test_scenarios"], "draws": pred["draws"],
            "draw_seed": pred["seed"], "reproduces_predictions_json": reproduced,
            "overall": {k: o[k] for k in keep}, "preregistered_checks": checks,
            "verdict": "predictive" if all(checks.values()) else "not predictive (quote descriptive per-stratum ratios only)",
            "paired_model_own_checks_not_preregistered": o["preregistered_checks"],
            "by_arm_host": {k: {**{kk: v[kk] for kk in ("n_pairs", "coverage_log_ratio", "coverage_saving_delta_model",
                                                      "observed_total_saving_usd", "predicted_total_pi90", "observed_total_in_pi")},
                                "per_1000_test_mix_point": v["per_1000_sessions"]["saving_usd_point"],
                                "per_1000_test_mix_pi90": v["per_1000_sessions"]["saving_usd_pi90"],
                                "observed_test_per_1000": pm._f(1000 * v["observed_total_saving_usd"] / v["n_pairs"], 2)}
                            for k, v in pred["by_arm_host"].items()},
            "sensitivity_draw_seed": {"seed": draw_seed, **{k: alt[k] for k in keep}}}


# ----------------------------------------------------------------------------------------------- exploratory

def pass_rates(recs: list) -> dict:
    out = {}
    q = [r for r in recs if r["quality_ok"]]
    for h in HOSTS:
        anc = {}
        for r in q:
            if r["host"] == h:
                anc[(r["scenario"], r["rep"])] = r["anchor_pass"]
        out[h] = {"anchor": {"n": len(anc), "pass_rate": pm._f(np.mean(list(anc.values())), 4) if anc else None}}
        for a in ARMS + ("aa",):
            rs = [r for r in q if r["host"] == h and r["arm"] == a]
            b = sum(1 for r in rs if r["anchor_pass"] and not r["arm_pass"])
            c = sum(1 for r in rs if r["arm_pass"] and not r["anchor_pass"])
            out[h][a] = {"n_pairs": len(rs), "arm_pass_rate": pm._f(np.mean([r["arm_pass"] for r in rs]), 4) if rs else None,
                         "anchor_pass_rate_same_pairs": pm._f(np.mean([r["anchor_pass"] for r in rs]), 4) if rs else None,
                         "anchor_only_pass": b, "arm_only_pass": c, "mcnemar_p": pm._f(pm.mcnemar_exact(b, c), 4)}
    return out


def ratios_by_split(recs: list, seed: int, B: int) -> dict:
    cost = pm._cost_rows(recs)
    out = {}
    for sp in ("train", "test"):
        out[sp] = {h: {a: gm_endpoint([r for r in cost if r["split"] == sp and r["host"] == h and r["arm"] == a],
                                      seed, ("split", sp, h, a), B) for a in ARMS + ("aa",)} for h in HOSTS}
    return out


def scenario_attrs(recs: list) -> dict:
    sc = {}
    for r in recs:
        sc[r["scenario"]] = (r["task_type"], r["turns"], r["n_long_gaps"], r["t1"])
    return sc


def stated_mix(sc: dict, host: str, task_type: str | None) -> dict:
    """The campaign's own scenario mix (all 70 scenarios) for one task type, or over all task types."""
    v = [x for x in sc.values() if task_type is None or x[0] == task_type]
    mix = {"arm": list(ARMS), "host": {host: 1.0},
           "turns": {str(k): n / len(v) for k, n in sorted(Counter(x[1] for x in v).items())},
           "long_gap_share": round(sum(x[2] > 0 for x in v) / len(v), 4),
           "turn1_prompt_chars": float(statistics.median(x[3] for x in v))}
    mix["task_type"] = ({task_type: 1.0} if task_type else
                        {k: round(n / len(v), 4) for k, n in sorted(Counter(x[0] for x in v).items())})
    return mix


def per_1000_model(model: dict, recs: list, seed: int, D: int = 4000) -> list:
    sc = scenario_attrs(recs)
    rows = []
    for h in HOSTS:
        for t in sorted({x[0] for x in sc.values()}) + [None]:
            mix = stated_mix(sc, h, t)
            w = pm.workload(model, mix, 1000, D, seed)
            for a, v in w["by_arm"].items():
                rows.append({"host": h, "task_type": t or "campaign mix", "arm": a, "n_scenarios_in_mix":
                             sum(1 for x in sc.values() if t is None or x[0] == t), "mix": mix,
                             "saving_usd_point": v["saving_usd_point"], "saving_usd_pi90": v["saving_usd_pi90"],
                             "predicted_anchor_spend_usd": v["predicted_anchor_spend_usd"],
                             "saving_pct_of_anchor_spend": v["saving_pct_of_anchor_spend"]})
    return rows


def per_1000_empirical(recs: list, seed: int, B: int) -> list:
    cost = pm._cost_rows(recs)
    rows = []
    for h in HOSTS:
        for t in sorted({r["task_type"] for r in cost}) + [None]:
            for a in ARMS:
                rs = [r for r in cost if r["host"] == h and r["arm"] == a and (t is None or r["task_type"] == t)]
                est, lo, hi, S = boot_interval([r["delta"] for r in rs], [r["scenario"] for r in rs], seed,
                                               ("per1000", h, t, a), B, level=0.90)
                rows.append({"host": h, "task_type": t or "all", "arm": a, "n_pairs": len(rs), "n_scenarios": S,
                             "saving_per_1000_usd": None if est is None else pm._f(-1000 * est, 2),
                             "range90": [None if hi is None else pm._f(-1000 * hi, 2), None if lo is None else pm._f(-1000 * lo, 2)]})
    return rows


def seed_robustness(test: list, B: int, seed: int, n: int = 20) -> dict:
    """Re-derive every verdict under n other bootstrap seeds; report whether any verdict changes."""
    def verdicts(sd):
        pr, h3, q = primary_endpoints(test, sd, B), h3_endpoints(test, sd, B), quality_endpoints(test, sd, B)
        out = {}
        for rd in READINGS:
            hy = hypotheses(pr[rd], h3[rd], q)
            out.update({f"{rd}:{k}": hy[k]["verdict"] for k in ("H1", "H2", "H3", "Quality")})
            out.update({f"{rd}:{k}:{p.get('arm', p['host'])}@{p['host']}": p["verdict"]
                        for k in ("H1", "H2", "H3") for p in hy[k]["parts"]})
        out.update({f"quality:{a}@{h}": q[h][a]["verdict"] for h in HOSTS for a in ARMS})
        return out
    base = verdicts(seed)
    changed = defaultdict(int)
    for sd in range(seed + 1, seed + 1 + n):
        for k, v in verdicts(sd).items():
            changed[k] += v != base[k]
    return {"seeds": [seed + 1, seed + n], "bootstrap": B, "verdicts_that_changed": {k: c for k, c in changed.items() if c},
            "all_stable": not any(changed.values())}


# ----------------------------------------------------------------------------------------------- run

def run(root: Path, B: int = BOOT, seed: int = SEED, emp_B: int = 4000, robust_n: int = 20) -> dict:
    ds = pm.load_dataset(root)
    test = [r for r in ds["pairs"] if r["split"] == "test"]
    n_test_scen = len({r["scenario"] for r in test})
    model = json.loads((root / "model" / "model.json").read_text(encoding="utf-8"))
    p_path = root / "model" / "predictions.json"
    on_disk = json.loads(p_path.read_text(encoding="utf-8")) if p_path.exists() else None

    primary = primary_endpoints(test, seed, B)
    h3 = h3_endpoints(test, seed, B)
    quality = quality_endpoints(test, seed, B)
    hyp = {rd: hypotheses(primary[rd], h3[rd], quality) for rd in READINGS}
    dec = {rd: decision(hyp[rd], quality) for rd in READINGS}

    ds_raw = pm.load_dataset(root, "raw")
    raw_primary = primary_endpoints([r for r in ds_raw["pairs"] if r["split"] == "test"], seed, B, tag="raw")

    return {
        "schema": SCHEMA, "campaign": str(root), "seed": seed, "bootstrap": B, "ni_margin": NI,
        "prereg": "evals/paired/PREREGISTRATION-main-v1.md", "primary_reading": "pair",
        "counts": {"sessions": ds["n_sessions"], "pairs": ds["n_pairs_raw"], "unjoined": ds["skipped_unjoined_pairs"],
                   "test_pairs": len(test), "test_scenarios": n_test_scen,
                   "test_scenarios_expected": N_TEST_SCENARIOS},
        "confirmatory": {"primary_endpoint": primary, "h3_paired_ratio": h3, "quality": quality,
                         "hypotheses": hyp, "decision": dec,
                         "model_check": model_check(model, ds, on_disk, seed)},
        "exploratory": {"pass_rates_all_splits": pass_rates(ds["pairs"]),
                        "aa_noise_all_splits": pm.aa_noise(ds["pairs"], seed, B),
                        "aa_noise_test": pm.aa_noise(test, seed, B),
                        "interim_vs_final": {"interim": INTERIM, "final": ratios_by_split(ds["pairs"], seed, B)},
                        "raw_basis_primary": raw_primary,
                        "per_1000_model": per_1000_model(model, ds["pairs"], seed),
                        "per_1000_empirical": per_1000_empirical(ds["pairs"], seed, emp_B),
                        "seed_robustness": seed_robustness(test, B, seed, robust_n)},
        "deviations": deviations(),
    }


def deviations() -> list:
    return [
        "Coverage bounds: paired_model.py (PREREG constant) and MODEL.md use 0.83-0.97 plus a calibration-slope check "
        "0.7-1.3; the preregistration says [0.80, 0.97] and has no slope check. The verdict here uses [0.80, 0.97]; "
        "the slope and paired_model's own checks are reported, not used.",
        "Coverage outcome: the prereg does not say which outcome's PI coverage is checked; both the log-ratio and the "
        "delta-$ model coverage must be in bounds here (stricter of the two readings).",
        "Primary-endpoint restriction is ambiguous (pair-level vs arm-level non-inferiority). Pair-level matches the text "
        "('among pairs where ...') and is primary; arm-level is reported alongside. Pair-level filtering conditions on a "
        "post-treatment outcome and in this design keeps only pairs with delta_turn_pass >= 0 (steps are >= 1/16).",
        "Non-inferiority comparison: paired_model uses lower bound >= -0.05; the prereg says > -0.05, used here.",
        "'Lower bound' for Quality is the 2.5th percentile (two-sided 95% bootstrap CI), consistent with the 95% CIs of "
        "the primary endpoint; the prereg does not state the level for this bound.",
        "'Contradicted' is not defined in the prereg; defined here, before looking at test numbers, as the 95% CI lying "
        "entirely on the other side of the same preregistered threshold.",
        "H3 restriction: the prereg does not say which pairs enter the sticky/shipped ratio; pair reading keeps triplets "
        "where both sticky and shipped are pair-level non-inferior to the shared anchor; arm reading keeps all.",
        "Decision rule: 'H3 holds' is read as H3 as a whole (both hosts), and 'H1 holds' as both sticky and shipped.",
        "Model engine: statsmodels is not installed, so the fit used paired_model's numpy fallback (method-of-moments "
        "variance components + feasible GLS), not REML MixedLM. The model is the existing model.json (train only, "
        "fit-boot 400, seed 0); the PI check re-runs predict with its on-disk seed/draws and with seed 20261002 as a "
        "sensitivity check.",
        "Bootstrap: 10,000 resamples, seed 20261002 (per analysis instructions; the prereg names 20261002 as the split seed).",
    ]


# ----------------------------------------------------------------------------------------------- report

_md, _ci, _usd = pm._md, pm._ci, pm._usd


def _r(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def render(doc: dict) -> str:
    c = doc["confirmatory"]
    L = ["# Confirmatory analysis: paired campaign main-v1", "",
         f"Preregistration: `{doc['prereg']}`. Test split only for everything under 'Confirmatory'. "
         f"{doc['counts']['test_pairs']} test pairs, {doc['counts']['test_scenarios']} test scenarios "
         f"(expected {doc['counts']['test_scenarios_expected']}). Ratios are arm / anchor (0.80 = 20% cheaper); "
         f"95% CIs from a scenario-cluster bootstrap (scenarios, then reps), {doc['bootstrap']:,} resamples, seed {doc['seed']}. "
         "Cost basis: tools-normalized.", "",
         "Verdict rule (all hypotheses): confirmed = the 95% CI lies entirely on the hypothesis side of its preregistered "
         "threshold; contradicted = entirely on the other side; otherwise not confirmed.", "",
         "## Verdicts", ""]
    rows = []
    for rd in READINGS:
        h = c["hypotheses"][rd]
        for name in ("H1", "H2", "H3", "Quality"):
            rows.append([name, rd + (" (primary)" if rd == doc["primary_reading"] else " (sensitivity)"), h[name]["verdict"]])
    L += [_md(["hypothesis", "non-inferiority reading", "verdict"], rows), ""]
    mc = c["model_check"]
    L += [f"Prediction model: **{mc['verdict']}**.", ""]
    for rd in READINGS:
        L += [f"Decision ({rd} reading): " + "; ".join(f"{h}: **{v['recommendation']}** ({v['why']})"
                                                       for h, v in c["decision"][rd].items()), ""]

    L += ["## Primary endpoint: cost ratio vs anchor (test split)", "",
          "Pair reading keeps a pair only if its own delta turn-pass > -0.05 (in practice >= 0). Arm reading uses every "
          "cost-valid pair.", ""]
    rows = []
    for h in HOSTS:
        for a in ARMS:
            p, ar = c["primary_endpoint"]["pair"][h][a], c["primary_endpoint"]["arm"][h][a]
            rows.append([h, a, f"{p['n_pairs']}/{p['n_cost_valid']}", p["n_scenarios"], _r(p["gm_ratio"]), _ci(p["ci95"]),
                         ar["n_pairs"], _r(ar["gm_ratio"]), _ci(ar["ci95"])])
    L += [_md(["host", "arm", "pairs kept (pair)", "scen.", "ratio (pair)", "95% CI (pair)", "pairs (arm)", "ratio (arm)",
               "95% CI (arm)"], rows), ""]

    for rd in READINGS:
        h = c["hypotheses"][rd]
        L += [f"## Hypotheses, {rd} reading", ""]
        rows = [["H1 (<1.0)", p["host"], p["arm"], _r(p["gm_ratio"]), _ci(p["ci95"]), p["verdict"]] for p in h["H1"]["parts"]]
        rows += [["H2 (lower >0.95)", p["host"], p["arm"], _r(p["gm_ratio"]), _ci(p["ci95"]), p["verdict"]] for p in h["H2"]["parts"]]
        rows += [["H3 sticky/shipped (<=1.05)", p["host"], f"{p['n_pairs']} triplets", _r(p["gm_ratio"]), _ci(p["ci95"]),
                  p["verdict"]] for p in h["H3"]["parts"]]
        L += [_md(["hypothesis", "host", "arm", "ratio", "95% CI", "verdict"], rows), "",
              f"H1 **{h['H1']['verdict']}**, H2 **{h['H2']['verdict']}**, H3 **{h['H3']['verdict']}**, "
              f"Quality **{h['Quality']['verdict']}** (savings claims tested: "
              + (", ".join(f"{x['arm']}@{x['host']}" for x in h["Quality"]["savings_claims"]) or "none") + ").", ""]

    L += ["## Quality: turn-pass non-inferiority (test split, all quality-valid pairs)", "",
          "Mean of arm minus anchor turn-pass fraction; non-inferior when the 95% lower bound > -0.05.", "",
          _md(["host", "arm", "pairs", "mean delta", "95% CI", "verdict"],
              [[h, a, q["n_pairs"], q["mean_delta_turn_pass"], _ci(q["ci95"], "{:.4f}"), q["verdict"]]
               for h in HOSTS for a, q in c["quality"][h].items()]), ""]

    o, pc = mc["overall"], mc["preregistered_checks"]
    L += ["## Prediction model check (preregistered bounds)", "",
          f"{mc['n_test_pairs']} test pairs, {mc['n_test_scenarios']} scenarios, {mc['draws']} draws (seed {mc['draw_seed']}); "
          f"re-run reproduces model/predictions.json: {mc['reproduces_predictions_json']}.", "",
          _md(["check", "value", "pass"], [
              ["90% PI coverage, log ratio, in [0.80, 0.97]", o["coverage_log_ratio"], pc["coverage_log_ratio_in_0.80_0.97"]],
              ["90% PI coverage, saving $ (delta model), in [0.80, 0.97]", o["coverage_saving_delta_model"],
               pc["coverage_saving_delta_model_in_0.80_0.97"]],
              ["test-total saving inside its 90% PI", f"{_usd(o['observed_total_saving_usd'])} in {_ci(o['predicted_total_pi90'], '{:.2f}')}",
               pc["test_total_saving_inside_pi90"]],
              ["(not preregistered) calibration slope", o["calibration_slope"], ""],
              ["(not preregistered) coverage, saving $ via ratio model", o["coverage_saving_ratio_model"], ""]]), "",
          f"Verdict: **{mc['verdict']}**. Sensitivity with draw seed {mc['sensitivity_draw_seed']['seed']}: coverage log "
          f"{mc['sensitivity_draw_seed']['coverage_log_ratio']}, $ {mc['sensitivity_draw_seed']['coverage_saving_delta_model']}, "
          f"total PI {_ci(mc['sensitivity_draw_seed']['predicted_total_pi90'], '{:.2f}')}.", "",
          _md(["arm / host", "pairs", "coverage (log)", "coverage ($)", "observed total", "PI90 total", "inside"],
              [[k.replace("|", " / "), v["n_pairs"], v["coverage_log_ratio"], v["coverage_saving_delta_model"],
                _usd(v["observed_total_saving_usd"]), _ci(v["predicted_total_pi90"], "{:.2f}"), v["observed_total_in_pi"]]
               for k, v in mc["by_arm_host"].items()]), ""]

    L += ["## Deviations from the preregistration", ""] + [f"- {d}" for d in doc["deviations"]] + [""]

    e = doc["exploratory"]
    sr = e["seed_robustness"]
    L += ["## Bootstrap-seed robustness", "",
          f"Every verdict re-derived under bootstrap seeds {sr['seeds'][0]}-{sr['seeds'][1]} ({sr['bootstrap']:,} resamples each): "
          + ("no verdict changed." if sr["all_stable"] else f"changed: {sr['verdicts_that_changed']}"), ""]
    L += ["# EXPLORATORY (not confirmatory)", "",
          "## Final hidden-test pass rate and McNemar vs anchor (all splits)", "",
          _md(["host", "arm", "pairs", "arm pass", "anchor pass (same pairs)", "anchor-only / arm-only", "McNemar p"],
              [[h, a, v["n_pairs"], v["arm_pass_rate"], v["anchor_pass_rate_same_pairs"],
                f"{v['anchor_only_pass']} / {v['arm_only_pass']}", v["mcnemar_p"]]
               for h in HOSTS for a, v in e["pass_rates_all_splits"][h].items() if a != "anchor"]), "",
          "## A/A noise floor (anchor vs second anchor)", "",
          _md(["split", "host", "pairs", "ratio", "mean log ratio 95% CI", "SD log ratio", "SD per session", "centred on 0"],
              [[sp, h, v["n_pairs"], _r(math.exp(v["mean_log_ratio"])) if v["mean_log_ratio"] is not None else "n/a",
                _ci(v["mean_log_ratio_ci95"]), v["sd_log_ratio"], v["implied_sd_single_session"], v["centred_on_zero"]]
               for sp, k in (("all", "aa_noise_all_splits"), ("test", "aa_noise_test")) for h, v in e[k].items()]), ""]
    iv = e["interim_vs_final"]
    rows = []
    for h in HOSTS:
        for a in ("sticky", "shipped", "sonnet", "aa"):
            tr, te = iv["final"]["train"][h][a], iv["final"]["test"][h][a]
            rows.append([h, a, iv["interim"]["pilot"][h].get(a, ""), iv["interim"]["interim_train_partial"][h].get(a, ""),
                         f"{_r(tr['gm_ratio'])} ({_ci(tr['ci95'], '{:.2f}')})", f"{_r(te['gm_ratio'])} ({_ci(te['ci95'], '{:.2f}')})",
                         _r(c["primary_endpoint"]["pair"][h][a]["gm_ratio"]) if a in ARMS else ""])
    L += ["## Interim vs final cost ratios", "",
          "Pilot and interim are dashboard numbers seen during the run (interim = train only, partial). Final train/test are "
          "all cost-valid pairs (no quality restriction); the last column is the confirmatory pair-reading ratio.", "",
          _md(["host", "arm", "pilot", "interim (train, partial)", "final train (95% CI)", "final test (95% CI)",
               "confirmatory test (pair)"], rows), ""]
    L += ["## Raw cost basis (test split, sensitivity)", "",
          _md(["host", "arm", "ratio (pair)", "95% CI", "ratio (arm)", "95% CI"],
              [[h, a, _r(e["raw_basis_primary"]["pair"][h][a]["gm_ratio"]), _ci(e["raw_basis_primary"]["pair"][h][a]["ci95"]),
                _r(e["raw_basis_primary"]["arm"][h][a]["gm_ratio"]), _ci(e["raw_basis_primary"]["arm"][h][a]["ci95"])]
               for h in HOSTS for a in ARMS]), ""]
    m0 = next(x for x in e["per_1000_model"] if x["task_type"] == "campaign mix")["mix"]
    emp = {(x["host"], "campaign mix" if x["task_type"] == "all" else x["task_type"], x["arm"]): x for x in e["per_1000_empirical"]}

    def inside(x):
        r = emp.get((x["host"], x["task_type"], x["arm"]), {}).get("range90")
        return "" if not r or r[0] is None else ("yes" if r[0] <= x["saving_usd_point"] <= r[1] else "NO")
    n_out = sum(inside(x) == "NO" for x in e["per_1000_model"])
    mix_out = [f"{x['arm']}@{x['host']}" for x in e["per_1000_model"] if x["task_type"] == "campaign mix" and inside(x) == "NO"]
    L += ["## Savings per 1,000 sessions: delta-$ model (paired_model workload)", "",
          "Saving = anchor cost - arm cost (positive = saved), 90% prediction ranges. Stated mix: for each task type, that "
          "type's own scenario mix across all 70 campaign scenarios (scripted-turn distribution, long-gap share, median "
          "turn-1 prompt chars); 'campaign mix' row uses the campaign's task-type shares "
          f"`{json.dumps(m0['task_type'])}`, long-gap share {m0['long_gap_share']}, median turn-1 chars "
          f"{m0['turn1_prompt_chars']:.0f}.", "",
          f"Caution: the preregistered model has additive arm, host and task-type effects (no arm x host or host x task "
          f"interaction), so an arm or task-type effect is shared by both hosts. The model point lies outside the empirical "
          f"90% range (next table) in {n_out} of {len(e['per_1000_model'])} cells (campaign-mix rows outside: "
          f"{', '.join(mix_out) or 'none'}). "
          "The preregistered check validates pooled pair-level coverage and the pooled test total, not per-arm-per-host "
          "levels; on the test mix itself:", "",
          _md(["arm / host", "model per 1,000 (test mix)", "90% PI", "observed test per 1,000", "inside"],
              [[k.replace("|", " / "), _usd(v["per_1000_test_mix_point"]), _ci(v["per_1000_test_mix_pi90"], "{:,.0f}"),
                _usd(v["observed_test_per_1000"]),
                v["per_1000_test_mix_pi90"][0] <= v["observed_test_per_1000"] <= v["per_1000_test_mix_pi90"][1]]
               for k, v in c["model_check"]["by_arm_host"].items()]), "",
          "Use the empirical table for per-host x task-type x arm figures; the model rows are shown as preregistered output.", "",
          _md(["host", "task type", "scenarios", "arm", "saving / 1,000", "90% PI", "share of anchor spend",
               "empirical / 1,000", "model inside empirical 90%"],
              [[x["host"], x["task_type"], x["n_scenarios_in_mix"], x["arm"], _usd(x["saving_usd_point"]),
                _ci(x["saving_usd_pi90"], "{:,.0f}"), f"{x['saving_pct_of_anchor_spend']}%",
                _usd(emp.get((x["host"], x["task_type"], x["arm"]), {}).get("saving_per_1000_usd")), inside(x)]
               for x in e["per_1000_model"]]), "",
          "## Savings per 1,000 sessions: empirical (all splits, EXPLORATORY)", "",
          "-(mean delta $) x 1000 per host x task type x arm; 90% range from the scenario-cluster bootstrap.", "",
          _md(["host", "task type", "arm", "pairs", "scenarios", "saving / 1,000", "90% range"],
              [[x["host"], x["task_type"], x["arm"], x["n_pairs"], x["n_scenarios"], _usd(x["saving_per_1000_usd"]),
                _ci(x["range90"], "{:,.0f}")] for x in e["per_1000_empirical"]]), ""]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Preregistered confirmatory analysis for paired campaign main-v1")
    ap.add_argument("root", nargs="?", default="~/dev/afast-paired/main-v1")
    ap.add_argument("--out")
    ap.add_argument("--boot", type=int, default=BOOT)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    if a.boot < 4000:
        ap.error("use at least 4000 bootstrap resamples (this script's floor; the preregistration does not set one)")
    root = Path(a.root).expanduser()
    out = Path(a.out).expanduser() if a.out else root / "confirm"
    doc = run(root, a.boot, a.seed)
    out.mkdir(parents=True, exist_ok=True)
    (out / "confirm.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "CONFIRM.md").write_text(render(doc), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
