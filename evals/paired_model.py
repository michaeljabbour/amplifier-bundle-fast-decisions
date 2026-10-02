"""Savings model for the paired cost-measurement campaign (docs/design/parallel-measurement-mode.md, section 2).

Input : <campaign>/rows/{sessions,pairs}.jsonl written by ``evals/paired.py rows`` (turns/requests are not needed).
Output: <campaign>/model/{summary,model,predictions,workload}.json and MODEL.md. Fully seeded and deterministic.

Subcommands
  summarize   per arm x host (and x task_type, x gap pattern, x turn band): valid pairs, mean/median saving $, geometric
              mean cost ratio with a scenario-cluster bootstrap 95% CI, quality vs the anchor (non-inferiority, McNemar),
              A/A noise, share of cost from cache rebuilds, model switches
  fit         mixed models fitted on split=train only, anchor-free covariates only, scenario (+ scenario:rep) random effects
  predict     test split: per-session and per-1,000-session savings with 90% prediction intervals + calibration
  workload    savings per N sessions for a user-supplied mix of task types / turn counts / hosts
  all         summarize + fit + predict (+ workload when --mix is given) + MODEL.md
  report      re-render MODEL.md from the JSON files already in the output directory

Sign convention: ``saving = anchor cost - arm cost`` (positive = money saved). The data's ``delta_usd`` is arm - anchor.

Methods
  * Cost basis: tools-normalized (primary, as written by paired.py) or ``--basis raw``.
  * Bootstrap: resample scenarios with replacement, then resample the rows (reps) inside each drawn scenario.
  * Mixed models: y = X b + u_scenario + u_(scenario,rep,host) + e. The rep block includes the host because arms of the
    same scenario/rep/host share one anchor session, which is where their residuals correlate (the design doc writes
    scenario:rep; the host-strata of the paired design make that the same thing within a stratum). Engine ``statsmodels`` (MixedLM, REML) when importable,
    otherwise the numpy fallback: covariance-based method-of-moments variance components from OLS residuals, then
    feasible GLS. CIs and prediction draws come from the scenario-cluster bootstrap of the whole fit either way.
  * Outcomes: (a) log cost ratio; (b) delta $ divided by the predicted anchor cost c_hat (equivalent to the
    1/anchor_cost^2 weighting; c_hat comes from an anchor-cost submodel fitted on anchor+aa sessions with
    pre-session features only, so no post-treatment quantity enters any covariate).
  * Covariates (all known before the session): arm, host, task_type, scripted turns, long-gap indicator,
    log(turn-1 prompt chars). ``anchor_*`` proxies are deliberately not used (no anchor numbers are needed to predict).
  * Prediction interval draws: bootstrap coefficient/variance-component sets, then new-scenario, new-rep and residual
    effects. 1,000-session totals treat every session as its own scenario (spec), with multinomial mix sampling.

Workload mix JSON (marginals are multiplied; omitted ones use the training mode):
  {"arm": "shipped" | ["shipped", "sticky"], "host": {"opus": 0.6, "fable": 0.4}, "task_type": {"bugfix": 0.5, "feature": 0.5},
   "turns": {"8": 0.5, "12": 0.5}, "long_gap_share": 0.1, "turn1_prompt_chars": 900}
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import zlib
from collections import defaultdict
from pathlib import Path

try:  # hard requirement: the bootstrap and the models need it (statsmodels is the optional part)
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise SystemExit("paired_model needs numpy (python3 -m pip install numpy)") from exc

SCHEMA = "fast-decisions-paired-model/v1"
NI_MARGIN = -0.05                 # lower 95% bound of mean delta turn_pass_frac must be >= this
PI_LEVEL = 0.90
PREREG = {"coverage": (0.83, 0.97), "slope": (0.7, 1.3)}      # design doc section 2, validation on the test scenarios
ANCHOR_ARMS = ("anchor", "aa")
BANDS = (("<=8", 8), ("9-12", 12), (">=13", 10 ** 9))
GROUP_PRIORITY = ("host", "task_type", "turns", "long_gap", "log_turn1")


# ----------------------------------------------------------------------------------------------- small helpers

def _f(x, nd=6):
    """JSON-safe float: None for nan/inf/None."""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def rng_for(seed: int, *key):
    return np.random.default_rng([int(seed), zlib.crc32("|".join(map(str, key)).encode())])


def _read_jsonl(path: Path) -> list:
    out = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    return out


def _num(x, default=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def band_of(turns: int) -> str:
    for label, hi in BANDS:
        if turns <= hi:
            return label
    return BANDS[-1][0]


def gap_pattern_of(n_long: int) -> str:
    return "no long gap" if n_long <= 0 else ("1 long gap" if n_long == 1 else "2+ long gaps")


def _count(it) -> dict:
    d = defaultdict(int)
    for x in it:
        d[x] += 1
    return d


# ----------------------------------------------------------------------------------------------- dataset

def load_dataset(root, basis: str = "normalized") -> dict:
    """Join pairs with their arm / anchor session rows. One record per pair; one per anchor-type session."""
    root = Path(root).expanduser()
    rows_dir = root / "rows" if (root / "rows").is_dir() else root
    sessions = _read_jsonl(rows_dir / "sessions.jsonl")
    pairs = _read_jsonl(rows_dir / "pairs.jsonl")
    if basis not in ("normalized", "raw"):
        raise ValueError("basis must be normalized or raw")
    y_key, d_key = (("log_cost_ratio", "delta_usd") if basis == "normalized" else ("log_cost_ratio_raw", "delta_usd_raw"))
    c_key = "cost_usd_tools_normalized" if basis == "normalized" else "cost_usd_recomputed"
    a_key, r_key = (("anchor_cost_usd", "arm_cost_usd") if basis == "normalized" else ("anchor_cost_usd_raw", "arm_cost_usd_raw"))
    idx = {(s["scenario_id"], s["rep"], s["host"], s["arm"]): s for s in sessions}
    recs, skipped = [], 0
    for p in pairs:
        a = idx.get((p["scenario_id"], p["rep"], p["host"], "anchor"))
        r = idx.get((p["scenario_id"], p["rep"], p["host"], p["arm"])) or idx.get((p["scenario_id"], p["rep"], "any", p["arm"]))
        if a is None or r is None:
            skipped += 1
            continue
        turns = int(r.get("scripted_turns") or 0)
        n_long = int(p.get("n_long_gaps") or r.get("n_long_gaps") or 0)
        recs.append({
            "scenario": p["scenario_id"], "rep": p["rep"], "host": p["host"], "arm": p["arm"],
            "split": r.get("split"), "task_type": p.get("task_type") or r.get("task_type"), "language": r.get("language"),
            "turns": turns, "n_long_gaps": n_long, "long_gap": int(n_long > 0), "gap_pattern": gap_pattern_of(n_long),
            "band": band_of(turns), "t1": _num(r.get("turn1_prompt_chars"), 0.0),
            "y": _num(p.get(y_key)), "delta": _num(p.get(d_key)),
            "a_cost": _num(p.get(a_key)), "r_cost": _num(p.get(r_key)),
            # cost validity: the pair's own `valid` (wave valid, no infra failure, cost_valid / killed_memory excluded)
            "cost_ok": bool(p.get("valid", True)),
            # quality still counts a memory-killed session (a task outcome); only infra failures / invalid waves drop out
            "quality_ok": bool(r.get("wave_valid", True) and a.get("wave_valid", True)
                               and r.get("status") != "infra_fail" and a.get("status") != "infra_fail"),
            "dtp": _num(p.get("delta_turn_pass")), "arm_pass": bool(r.get("final_state_pass")),
            "anchor_pass": bool(a.get("final_state_pass")), "both_pass": bool(p.get("both_pass")),
            "rebuild_usd": _num(r.get("rebuild_usd"), 0.0), "switches": _num(r.get("model_switches"), 0.0),
            "receipt_saved": _num(r.get("receipt_usd_saved_sum")),
        })
    anchors = []
    for s in sessions:
        if s["arm"] not in ANCHOR_ARMS or s["host"] == "any":
            continue
        n_long = int(s.get("n_long_gaps") or 0)
        anchors.append({
            "scenario": s["scenario_id"], "rep": s["rep"], "host": s["host"], "arm": s["arm"], "split": s.get("split"),
            "task_type": s.get("task_type"), "turns": int(s.get("scripted_turns") or 0), "long_gap": int(n_long > 0),
            "t1": _num(s.get("turn1_prompt_chars"), 0.0), "cost": _num(s.get(c_key)),
            "ok": bool(s.get("wave_valid", True) and s.get("status") != "infra_fail" and s.get("cost_valid", True) is not False)})
    return {"pairs": recs, "anchors": anchors, "basis": basis, "skipped_unjoined_pairs": skipped,
            "n_sessions": len(sessions), "n_pairs_raw": len(pairs)}


def _cost_rows(recs):
    return [r for r in recs if r["cost_ok"] and r["y"] is not None and r["delta"] is not None]


# ----------------------------------------------------------------------------------------------- bootstrap + tests

def cluster_boot_mean(values, clusters, rng, B: int = 2000):
    """(estimate, lo95, hi95, S) for the mean of `values`: resample clusters (scenarios), then rows inside each draw."""
    v = np.asarray(values, float)
    if len(v) == 0:
        return None, None, None, 0
    est = float(v.mean())
    groups = defaultdict(list)
    for x, c in zip(v, clusters):
        groups[c].append(x)
    S = len(groups)
    if S < 2:
        return est, None, None, S
    kmax = max(len(g) for g in groups.values())
    M = np.zeros((S, kmax))
    k = np.zeros(S, int)
    for i, g in enumerate(groups.values()):
        M[i, :len(g)] = g
        k[i] = len(g)
    means = []
    chunk = max(1, int(2_000_000 // max(1, S * kmax)))
    done = 0
    while done < B:
        b = min(chunk, B - done)
        sc = rng.integers(0, S, (b, S))
        ks = k[sc]
        pick = np.minimum((rng.random((b, S, kmax)) * ks[..., None]).astype(int), ks[..., None] - 1)
        vals = M[sc[..., None], pick]
        mask = np.arange(kmax)[None, None, :] < ks[..., None]
        means.append((vals * mask).sum((1, 2)) / mask.sum((1, 2)))
        done += b
    lo, hi = np.percentile(np.concatenate(means), [2.5, 97.5])
    return est, float(lo), float(hi), S


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


# ----------------------------------------------------------------------------------------------- summarize

def _group_summary(rs: list, rng_key: tuple, seed: int, B: int) -> dict:
    cost = _cost_rows(rs)
    qual = [r for r in rs if r["quality_ok"] and r["dtp"] is not None]
    out: dict = {"n_pairs_total": len(rs), "n_valid_pairs": len(cost), "n_scenarios": len({r["scenario"] for r in cost})}
    if cost:
        scen = [r["scenario"] for r in cost]
        deltas = np.array([r["delta"] for r in cost])
        out["mean_saving_usd"] = _f(-deltas.mean())
        out["median_saving_usd"] = _f(-np.median(deltas))
        _, dlo, dhi, _ = cluster_boot_mean(deltas, scen, rng_for(seed, *rng_key, "delta"), B)
        out["mean_saving_usd_ci95"] = [None if dhi is None else _f(-dhi), None if dlo is None else _f(-dlo)]
        est, lo, hi, _ = cluster_boot_mean([r["y"] for r in cost], scen, rng_for(seed, *rng_key, "y"), B)
        out["gm_cost_ratio"] = _f(math.exp(est))
        out["gm_cost_ratio_ci95"] = [None if lo is None else _f(math.exp(lo)), None if hi is None else _f(math.exp(hi))]
        out["saving_pct"] = _f(100 * (1 - math.exp(est)), 3)
        both = [r for r in cost if r["both_pass"]]
        out["n_both_pass"] = len(both)
        if both:
            e2, l2, h2, _ = cluster_boot_mean([r["y"] for r in both], [r["scenario"] for r in both], rng_for(seed, *rng_key, "yb"), B)
            out["gm_cost_ratio_both_pass"] = _f(math.exp(e2))
            out["gm_cost_ratio_both_pass_ci95"] = [None if l2 is None else _f(math.exp(l2)), None if h2 is None else _f(math.exp(h2))]
        spend = sum(r["r_cost"] for r in cost if r["r_cost"] is not None)
        out["rebuild_cost_share"] = _f(sum(r["rebuild_usd"] for r in cost) / spend) if spend > 0 else None
        out["mean_model_switches"] = _f(np.mean([r["switches"] for r in cost]), 3)
        out["share_sessions_with_switch"] = _f(np.mean([r["switches"] > 0 for r in cost]), 3)
        rec = [r["receipt_saved"] for r in cost if r["receipt_saved"] is not None]
        out["mean_receipt_saving_usd"] = _f(np.mean(rec)) if rec else None
    if qual:
        est, lo, hi, _ = cluster_boot_mean([r["dtp"] for r in qual], [r["scenario"] for r in qual], rng_for(seed, *rng_key, "q"), B)
        b = sum(1 for r in qual if r["anchor_pass"] and not r["arm_pass"])
        c = sum(1 for r in qual if not r["anchor_pass"] and r["arm_pass"])
        out["quality"] = {
            "n_pairs": len(qual), "mean_delta_turn_pass": _f(est, 4), "delta_turn_pass_ci95": [_f(lo, 4), _f(hi, 4)],
            "non_inferior": None if lo is None else bool(lo >= NI_MARGIN),
            "arm_final_pass_rate": _f(np.mean([r["arm_pass"] for r in qual]), 4),
            "anchor_final_pass_rate": _f(np.mean([r["anchor_pass"] for r in qual]), 4),
            "mcnemar_anchor_only_pass": b, "mcnemar_arm_only_pass": c, "mcnemar_p": _f(mcnemar_exact(b, c), 4)}
        out["savings_claim_allowed"] = out["quality"]["non_inferior"]
    return out


def aa_noise(recs: list, seed: int, B: int) -> dict:
    """Anchor vs the independent second anchor (arm 'aa'): the log ratio should be centred on 0; its SD is the noise floor."""
    out = {}
    aa = _cost_rows([r for r in recs if r["arm"] == "aa"])
    for host in sorted({r["host"] for r in aa}) + ["all"]:
        rs = [r for r in aa if host == "all" or r["host"] == host]
        y = np.array([r["y"] for r in rs])
        est, lo, hi, S = cluster_boot_mean(y, [r["scenario"] for r in rs], rng_for(seed, "aa", host), B)
        sd = float(y.std(ddof=1)) if len(y) > 1 else None
        out[host] = {"n_pairs": len(rs), "n_scenarios": S, "mean_log_ratio": _f(est), "mean_log_ratio_ci95": [_f(lo), _f(hi)],
                     "sd_log_ratio": _f(sd), "implied_sd_single_session": _f(sd / math.sqrt(2)) if sd else None,
                     "centred_on_zero": None if lo is None else bool(lo <= 0 <= hi)}
    return out


def summarize(ds: dict, seed: int = 0, B: int = 2000) -> dict:
    recs = ds["pairs"]
    dims = {"overall": lambda r: "all", "task_type": lambda r: r["task_type"], "gap_pattern": lambda r: r["gap_pattern"],
            "turn_band": lambda r: r["band"]}
    groups = []
    multi_host = len({r["host"] for r in recs}) > 1
    for dim, fn in dims.items():
        buckets = defaultdict(list)
        for r in recs:
            for host in ({r["host"], "all"} if multi_host else {r["host"]}):
                buckets[(r["arm"], host, str(fn(r)))].append(r)
        for (arm, host, val), rs in sorted(buckets.items()):
            g = {"arm": arm, "host": host, "dim": dim, "value": val}
            g.update(_group_summary(rs, (arm, host, dim, val), seed, B))
            groups.append(g)
    return {"schema": SCHEMA, "basis": ds["basis"], "seed": seed, "bootstrap": B, "ni_margin": NI_MARGIN,
            "counts": {"pairs": len(recs), "valid_cost_pairs": len(_cost_rows(recs)), "unjoined_pairs": ds["skipped_unjoined_pairs"],
                       "by_split": {str(k): v for k, v in sorted(_count(r["split"] for r in recs).items(), key=lambda kv: str(kv[0]))}},
            "aa_noise": aa_noise(recs, seed, B), "groups": groups}


# ----------------------------------------------------------------------------------------------- design matrices

class Design:
    """Column definitions fixed at fit time (levels, centring, scaling) so test / workload rows get identical columns."""

    def __init__(self, spec: dict):
        self.spec = spec

    @classmethod
    def fit(cls, recs: list, include_arm: bool = True, interactions: bool = False, rows_per_param: int = 3) -> Design:
        n = len(recs)
        arms = sorted({r["arm"] for r in recs})
        hosts, tts = _count(r["host"] for r in recs), _count(r["task_type"] for r in recs)
        ref_host = max(sorted(hosts), key=lambda k: hosts[k])
        ref_tt = max(sorted(tts, key=str), key=lambda k: tts[k])
        turns = np.array([r["turns"] for r in recs], float)
        lt1 = np.log1p(np.array([r["t1"] for r in recs], float))
        num = {"turns": [float(turns.mean()), float(turns.std())], "log_turn1": [float(lt1.mean()), float(lt1.std())]}
        if include_arm:   # cell-means coding: one column per arm, so each arm term is that arm's effect at the reference point
            cols = [{"group": "arm", "kind": "arm", "level": a, "name": f"arm={a}", "ax": None} for a in arms]
        else:
            cols = [{"group": "const", "kind": "const", "name": "intercept", "ax": None}]
        n_base = len(cols)
        group_defs = {
            "host": [("cat", "host", h) for h in sorted(hosts) if h != ref_host],
            "task_type": [("cat", "task_type", t) for t in sorted(tts, key=str) if t != ref_tt],
            "turns": [("num", "turns", None)] if num["turns"][1] > 0 else [],
            "long_gap": [("flag", "long_gap", None)] if len({r["long_gap"] for r in recs}) > 1 else [],
            "log_turn1": [("num", "log_turn1", None)] if num["log_turn1"][1] > 0 else []}
        budget = max(n_base, n // rows_per_param)
        dropped = []
        for g in GROUP_PRIORITY:
            if not group_defs[g]:
                continue
            new = []
            for ax in (arms if (interactions and include_arm) else [None]):
                for kind, var, level in group_defs[g]:
                    nm = f"{var}={level}" if kind == "cat" else var
                    new.append({"group": g, "kind": kind, "var": var, "level": level, "ax": ax,
                                "name": nm if ax is None else f"{nm}:arm={ax}"})
            if len(cols) + len(new) <= budget:
                cols.extend(new)
            else:
                dropped.append(g)
        return cls({"include_arm": include_arm, "arms": arms, "ref_host": ref_host, "ref_task_type": ref_tt, "num": num,
                    "columns": cols, "dropped_groups": dropped, "interactions": bool(interactions and include_arm),
                    "rows_per_param": rows_per_param})

    @classmethod
    def from_dict(cls, d: dict) -> Design:
        return cls(d)

    @property
    def names(self) -> list:
        return [c["name"] for c in self.spec["columns"]]

    def transform(self, recs: list):
        """(X, unseen). Raises ValueError on an arm the model never saw; unseen host / task_type levels use the reference."""
        s = self.spec
        X = np.zeros((len(recs), len(s["columns"])))
        m_t, s_t = s["num"]["turns"]
        m_l, s_l = s["num"]["log_turn1"]
        known = {"host": {s["ref_host"]}, "task_type": {s["ref_task_type"]}}
        for c in s["columns"]:
            if c["kind"] == "cat":
                known[c["var"]].add(c["level"])
        unseen = defaultdict(set)
        for i, r in enumerate(recs):
            if s["include_arm"] and r["arm"] not in s["arms"]:
                raise ValueError(f"arm {r['arm']!r} was not in the training data (arms: {s['arms']})")
            for j, c in enumerate(s["columns"]):
                if c["ax"] is not None and r["arm"] != c["ax"]:
                    continue
                k = c["kind"]
                if k == "const":
                    v = 1.0
                elif k == "arm":
                    v = float(r["arm"] == c["level"])
                elif k == "cat":
                    v = float(r[c["var"]] == c["level"])
                elif k == "flag":
                    v = float(r["long_gap"])
                elif c["var"] == "turns":
                    v = (r["turns"] - m_t) / s_t
                else:
                    v = (math.log1p(r["t1"]) - m_l) / s_l
                X[i, j] = v
            for var in ("host", "task_type"):
                if r[var] not in known[var]:
                    unseen[var].add(str(r[var]))
        return X, {k: sorted(v) for k, v in unseen.items()}


# ----------------------------------------------------------------------------------------------- mixed model (engine)

def _statsmodels_available() -> bool:
    try:
        import pandas  # noqa: F401
        import statsmodels  # noqa: F401
        return True
    except ImportError:
        return False


def _fit_statsmodels(X, y, scen, blk):
    import warnings

    import pandas as pd
    import statsmodels.formula.api as smf
    p = X.shape[1]
    cols = [f"c{i}" for i in range(p)]
    df = pd.DataFrame(X, columns=cols)
    df["y"], df["g"], df["r"] = y, scen, blk
    # a scenario:rep component is identifiable only when some scenario holds more than one rep block
    multi = len(set(blk)) > len(set(scen)) and len(set(blk)) < len(blk)
    kw = {"vc_formula": {"rep": "0 + C(r)"}} if multi else {}
    md = smf.mixedlm("y ~ 0 + " + " + ".join(cols), df, groups="g", re_formula="1", **kw)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = md.fit(reml=True, method=["lbfgs"])
    sr2 = float(res.vcomp[0]) if multi and len(res.vcomp) else 0.0
    return (np.asarray(res.fe_params, float), np.asarray(res.cov_params(), float)[:p, :p],
            [float(res.cov_re.iloc[0, 0]), sr2, float(res.scale)])


def _vc_mom(e, scen, blk, p):
    """Covariance-based method of moments for (scenario, scenario:rep, residual) from OLS residuals.
    Same-block residual products estimate sb2+sr2, same-scenario/other-block products estimate sb2, squares estimate the total."""
    n = len(e)
    tot = float((e ** 2).sum() / (n - p if n - p > 0 else n))
    nb, ns = blk.max() + 1, scen.max() + 1
    sb, mb, qb = np.bincount(blk, e, nb), np.bincount(blk, None, nb), np.bincount(blk, e ** 2, nb)
    ss, ms = np.bincount(scen, e, ns), np.bincount(scen, None, ns)
    den_rep = float((mb * (mb - 1)).sum())
    cov_rep = float((sb ** 2 - qb).sum() / den_rep) if den_rep > 0 else None
    den_scn = float((ms ** 2).sum() - (mb ** 2).sum())
    cov_scn = float((ss ** 2).sum() - (sb ** 2).sum()) / den_scn if den_scn > 0 else None
    if cov_rep is None and cov_scn is None:
        sb2 = sr2 = 0.0
    elif cov_scn is None:        # every scenario has one rep block: scenario and rep effects are inseparable
        sb2, sr2 = max(cov_rep, 0.0), 0.0
    else:
        sb2 = max(cov_scn, 0.0)
        sr2 = max((cov_rep if cov_rep is not None else sb2) - sb2, 0.0)
    return sb2, sr2, max(tot - sb2 - sr2, 1e-3 * max(tot, 1e-12))


def fit_re(X, y, scen, blk, engine: str = "fallback"):
    """y = X b + u_scen + u_blk + e. `scen` sorted/contiguous 0..S-1, `blk` global block ids 0..K-1.
    Returns (beta, model-based covariance of beta, [sb2, sr2, se2])."""
    if engine == "statsmodels":
        try:
            return _fit_statsmodels(X, y, scen, blk)
        except Exception as exc:  # noqa: BLE001 - degrade to the numpy path rather than abort a campaign analysis
            print(f"paired_model: statsmodels fit failed ({type(exc).__name__}); using the numpy fallback", file=sys.stderr)
    n, p = X.shape
    beta0 = np.linalg.lstsq(X, y, rcond=None)[0]
    sb2, sr2, se2 = _vc_mom(y - X @ beta0, scen, blk, p)
    starts = np.r_[0, np.flatnonzero(np.diff(scen)) + 1, n]
    XtWX, XtWy = np.zeros((p, p)), np.zeros(p)
    for a, b in zip(starts[:-1], starts[1:]):
        bs = blk[a:b]
        S = se2 * np.eye(b - a) + sb2 + sr2 * (bs[:, None] == bs[None, :])
        sol = np.linalg.solve(S, np.column_stack([X[a:b], y[a:b]]))
        XtWX += X[a:b].T @ sol[:, :p]
        XtWy += X[a:b].T @ sol[:, p]
    cov = np.linalg.pinv(XtWX)
    return cov @ XtWy, cov, [sb2, sr2, se2]


class Panel:
    """Rows sorted by scenario with block ids, so a scenario bootstrap is an index shuffle."""

    def __init__(self, X, y, scenarios, reps):
        labels = sorted(set(scenarios), key=str)
        sid = {s: i for i, s in enumerate(labels)}
        order = sorted(range(len(y)), key=lambda i: (sid[scenarios[i]], str(reps[i])))
        self.X, self.y = np.asarray(X)[order], np.asarray(y, float)[order]
        s_arr = np.array([sid[scenarios[i]] for i in order])
        seen, per_scen = {}, defaultdict(int)
        loc = np.zeros(len(order), int)
        for k, i in enumerate(order):
            key = (sid[scenarios[i]], reps[i])
            if key not in seen:
                seen[key] = per_scen[key[0]]
                per_scen[key[0]] += 1
            loc[k] = seen[key]
        self.S, self.loc = len(labels), loc
        self.rows_of = [np.flatnonzero(s_arr == s) for s in range(self.S)]
        self.nblk = [int(loc[r].max()) + 1 for r in self.rows_of]

    def arrays(self, choice=None):
        rows, scen, blk, off = [], [], [], 0
        for new, s in enumerate(range(self.S) if choice is None else choice):
            r = self.rows_of[s]
            rows.append(r)
            scen.append(np.full(len(r), new))
            blk.append(self.loc[r] + off)
            off += self.nblk[s]
        rows = np.concatenate(rows)
        return self.X[rows], self.y[rows], np.concatenate(scen), np.concatenate(blk)


def fit_model(name: str, recs: list, y, include_arm: bool, interactions: bool, B: int, seed: int, engine: str) -> dict:
    """Fit one outcome: point fit + scenario-cluster bootstrap of the entire procedure (design fixed)."""
    design = Design.fit(recs, include_arm=include_arm, interactions=interactions)
    X, _ = design.transform(recs)
    panel = Panel(X, y, [r["scenario"] for r in recs], [(r["rep"], r["host"]) for r in recs])
    beta, cov, vc = fit_re(*panel.arrays(), engine=engine)
    boots, vcs = [], []
    rng = rng_for(seed, "fit", name)
    for _ in range(B if panel.S >= 2 else 0):
        b, _, v = fit_re(*panel.arrays(rng.integers(0, panel.S, panel.S)), engine=engine)
        boots.append(b)
        vcs.append(v)
    bb = np.array(boots) if boots else beta[None, :]
    vv = np.array(vcs) if vcs else np.array([vc])
    lo, hi = np.percentile(bb, [2.5, 97.5], axis=0) if boots else (np.full_like(beta, np.nan), np.full_like(beta, np.nan))
    se_model = np.sqrt(np.clip(np.diag(cov), 0, None))
    return {
        "name": name, "engine": engine, "design": design.spec, "n_rows": int(len(y)), "n_scenarios": panel.S,
        "coef": [{"term": t, "estimate": _f(b, 6), "se_model": _f(s, 6), "ci95_boot": [_f(l, 6), _f(h, 6)]}
                 for t, b, s, l, h in zip(design.names, beta, se_model, lo, hi)],
        "beta": [_f(v, 10) for v in beta],
        "variance": {"scenario": _f(vc[0], 8), "scenario_rep": _f(vc[1], 8), "residual": _f(vc[2], 8)},
        "boot": {"B": len(boots), "beta": [[_f(v, 8) for v in row] for row in bb], "vc": [[_f(v, 10) for v in row] for row in vv]}}


def anchor_cost_hat(model: dict, recs: list):
    """Predicted anchor cost per record from anchor-free features; a per-turn mean when no anchor model exists."""
    am = model["models"].get("anchor_cost")
    if am is None:
        return np.array([r["turns"] for r in recs], float) * model["anchor_fallback_per_turn"]
    X, _ = Design.from_dict(am["design"]).transform(recs)
    return np.exp(X @ np.array(am["beta"], float))


def _fit_engine(engine: str) -> str:
    if engine == "auto":
        return "statsmodels" if _statsmodels_available() else "fallback"
    if engine == "statsmodels" and not _statsmodels_available():
        raise SystemExit("--engine statsmodels requested but statsmodels/pandas are not importable")
    return engine


def fit(ds: dict, train_splits=("train",), engine: str = "auto", B: int = 400, seed: int = 0,
        include_aa: bool = False, interactions: bool = False) -> dict:
    engine = _fit_engine(engine)
    train = [r for r in _cost_rows(ds["pairs"]) if r["split"] in train_splits and (include_aa or r["arm"] != "aa")]
    anchors = [a for a in ds["anchors"] if a["split"] in train_splits and a["ok"] and a["cost"] and a["cost"] > 0]
    model = {"schema": SCHEMA, "basis": ds["basis"], "seed": seed, "engine": engine, "train_splits": list(train_splits),
             "interactions": interactions, "n_train_pairs": len(train), "models": {}, "notes": [], "anchor_fallback_per_turn": 1.0}
    if len(train) < 2 or len({r["scenario"] for r in train}) < 2:
        model["notes"].append(f"fit skipped: {len(train)} train pairs across {len({r['scenario'] for r in train})} scenarios "
                              f"(splits {list(train_splits)})")
        return model
    if len(anchors) >= 2 and len({a["scenario"] for a in anchors}) >= 2:
        model["models"]["anchor_cost"] = fit_model("anchor_cost", anchors, np.log([a["cost"] for a in anchors]),
                                                   False, False, B, seed, engine)
    else:
        per_turn = [r["a_cost"] / r["turns"] for r in train if r["a_cost"] and r["turns"]]
        model["anchor_fallback_per_turn"] = _f(np.mean(per_turn) if per_turn else 1.0, 6)
        model["notes"].append("no anchor sessions in the train split: delta-$ model scaled by a mean anchor cost per turn")
    chat = anchor_cost_hat(model, train)
    model["models"]["log_ratio"] = fit_model("log_ratio", train, [r["y"] for r in train], True, interactions, B, seed, engine)
    model["models"]["delta_rel"] = fit_model("delta_rel", train, [r["delta"] / c for r, c in zip(train, chat)], True,
                                             interactions, B, seed, engine)
    for nm, m in model["models"].items():
        if m["design"]["dropped_groups"]:
            model["notes"].append(f"{nm}: covariate groups {m['design']['dropped_groups']} left out (fewer than "
                                  f"{m['design']['rows_per_param']} rows per parameter)")
    return model


# ----------------------------------------------------------------------------------------------- predict

def _draws(m: dict, X, scen_idx, blk_idx, n_scen, n_blk, D: int, rng):
    """(mu, total), shape (D, n): bootstrap coefficient/variance draws plus new scenario, rep and residual effects."""
    beta, vc = np.array(m["boot"]["beta"], float), np.array(m["boot"]["vc"], float)
    b = rng.integers(0, len(beta), D)
    mu = beta[b] @ X.T
    sd = np.sqrt(np.clip(vc[b], 0, None))
    us = rng.standard_normal((D, n_scen)) * sd[:, [0]]
    ur = rng.standard_normal((D, n_blk)) * sd[:, [1]]
    eps = rng.standard_normal((D, X.shape[0])) * sd[:, [2]]
    return mu, mu + us[:, scen_idx] + ur[:, blk_idx] + eps


def _pi(arr, level=PI_LEVEL, axis=0):
    a = (1 - level) / 2 * 100
    return np.percentile(arr, [a, 100 - a], axis=axis)


def workload_total(model: dict, cells: list, weights, N: int = 1000, D: int = 4000, seed: int = 0, rng=None) -> dict:
    """Total saving over N sessions drawn from the weighted cell mix (delta-$ model). Every session is its own scenario."""
    m = model["models"]["delta_rel"]
    X, unseen = Design.from_dict(m["design"]).transform(cells)
    chat = anchor_cost_hat(model, cells)
    w = np.asarray(weights, float)
    w = w / w.sum()
    rng = rng or rng_for(seed, "workload", N, len(cells))
    beta, vc = np.array(m["boot"]["beta"], float), np.array(m["boot"]["vc"], float)
    b = rng.integers(0, len(beta), D)
    mu = (beta[b] @ X.T) * chat                                   # (D, C) delta $ per session
    counts = rng.multinomial(N, w, size=D)
    shock = rng.standard_normal(D) * np.sqrt(vc[b].sum(1) * (counts * chat ** 2).sum(1))
    sav = -((counts * mu).sum(1) + shock)
    point = float(-N * (w * ((X @ np.array(m["beta"], float)) * chat)).sum())
    lo, hi = _pi(sav)
    base = float(N * (w * chat).sum())
    return {"n_sessions": N, "saving_usd_point": _f(point, 2), "saving_usd_pi90": [_f(lo, 2), _f(hi, 2)],
            "saving_usd_per_session": _f(point / N, 4), "predicted_anchor_spend_usd": _f(base, 2),
            "saving_pct_of_anchor_spend": _f(100 * point / base, 2) if base > 0 else None, "unseen_levels": unseen}


def predict(model: dict, ds: dict, test_splits=("test",), D: int = 4000, seed: int = 0) -> dict:
    out = {"schema": SCHEMA, "seed": seed, "pi_level": PI_LEVEL, "test_splits": list(test_splits), "draws": D}
    lr, dr = model["models"].get("log_ratio"), model["models"].get("delta_rel")
    test = [r for r in _cost_rows(ds["pairs"]) if r["split"] in test_splits and (not lr or r["arm"] in lr["design"]["arms"])]
    if lr is None or dr is None or not test:
        out["note"] = "no fitted model or no valid test pairs: nothing to predict"
        out["n_test_pairs"] = len(test)
        return out
    scen_ids = {s: i for i, s in enumerate(sorted({r["scenario"] for r in test}, key=str))}
    blk_ids = {k: i for i, k in enumerate(sorted({(r["scenario"], r["rep"], r["host"]) for r in test}, key=str))}
    si = np.array([scen_ids[r["scenario"]] for r in test])
    bi = np.array([blk_ids[(r["scenario"], r["rep"], r["host"])] for r in test])
    rng = rng_for(seed, "predict")
    chat = anchor_cost_hat(model, test)
    Xl, unseen = Design.from_dict(lr["design"]).transform(test)
    Xd, _ = Design.from_dict(dr["design"]).transform(test)
    _, ylog = _draws(lr, Xl, si, bi, len(scen_ids), len(blk_ids), D, rng)
    _, yrel = _draws(dr, Xd, si, bi, len(scen_ids), len(blk_ids), D, rng)
    sav_delta = -(yrel * chat)                                    # saving $ per session, delta-$ route
    sav_ratio = chat * (1 - np.exp(ylog))                         # saving $ per session, ratio route (c_hat held fixed)
    obs_sav = -np.array([r["delta"] for r in test])
    obs_y = np.array([r["y"] for r in test])
    mean_delta, mean_ratio, med_y = sav_delta.mean(0), sav_ratio.mean(0), np.median(ylog, 0)
    (lo_d, hi_d), (lo_r, hi_r), (lo_y, hi_y) = _pi(sav_delta), _pi(sav_ratio), _pi(ylog)

    def agg(mask):
        tlo, thi = _pi(sav_delta[:, mask].sum(1))
        ob = float(obs_sav[mask].sum())
        slope = float(np.polyfit(mean_delta[mask], obs_sav[mask], 1)[0]) if mask.sum() > 2 and mean_delta[mask].std() > 0 else None
        cover = lambda v, lo, hi: _f(np.mean((v[mask] >= lo[mask]) & (v[mask] <= hi[mask])), 4)
        return {"n_pairs": int(mask.sum()),
                "coverage_log_ratio": cover(obs_y, lo_y, hi_y),
                "coverage_saving_delta_model": cover(obs_sav, lo_d, hi_d),
                "coverage_saving_ratio_model": cover(obs_sav, lo_r, hi_r),
                "mean_error_log_ratio": _f(np.mean(med_y[mask] - obs_y[mask])),
                "mean_error_saving_delta_model_usd": _f(np.mean(mean_delta[mask] - obs_sav[mask]), 4),
                "mean_error_saving_ratio_model_usd": _f(np.mean(mean_ratio[mask] - obs_sav[mask]), 4),
                "observed_total_saving_usd": _f(ob, 2), "predicted_total_saving_usd": _f(mean_delta[mask].sum(), 2),
                "predicted_total_pi90": [_f(tlo, 2), _f(thi, 2)], "observed_total_in_pi": bool(tlo <= ob <= thi),
                "calibration_slope": _f(slope, 3)}

    overall = agg(np.ones(len(test), bool))
    sl = overall["calibration_slope"]
    overall["preregistered_checks"] = {
        "coverage_log_ratio_in_0.83_0.97": PREREG["coverage"][0] <= overall["coverage_log_ratio"] <= PREREG["coverage"][1],
        "coverage_saving_in_0.83_0.97": PREREG["coverage"][0] <= overall["coverage_saving_delta_model"] <= PREREG["coverage"][1],
        "total_in_pi90": overall["observed_total_in_pi"],
        "calibration_slope_in_0.7_1.3": None if sl is None else PREREG["slope"][0] <= sl <= PREREG["slope"][1]}
    by_arm = {}
    for key in sorted({(r["arm"], r["host"]) for r in test}):
        mask = np.array([(r["arm"], r["host"]) == key for r in test])
        g = agg(mask)
        cells = [r for r, k in zip(test, mask) if k]
        g["per_1000_sessions"] = workload_total(model, cells, np.ones(len(cells)), 1000, D, seed, rng=rng_for(seed, "per1000", *key))
        by_arm["|".join(key)] = g
    out.update({"n_test_pairs": len(test), "n_test_scenarios": len(scen_ids), "unseen_levels": unseen,
                "overall": overall, "by_arm_host": by_arm,
                "per_pair": [{"scenario": r["scenario"], "rep": r["rep"], "host": r["host"], "arm": r["arm"],
                              "observed_saving_usd": _f(o, 4), "predicted_saving_usd": _f(m_, 4),
                              "pi90_saving_usd": [_f(l, 4), _f(h, 4)], "observed_log_ratio": _f(y, 5),
                              "pi90_log_ratio": [_f(a, 5), _f(b, 5)]}
                             for r, o, m_, l, h, y, a, b in zip(test, obs_sav, mean_delta, lo_d, hi_d, obs_y, lo_y, hi_y)]})
    return out


def cells_from_mix(mix: dict, model: dict) -> list:
    """Product of the marginal shares in `mix` -> [(weight, record-like dict)]. Missing marginals use the training mode."""
    dm = model["models"]["delta_rel"]["design"]

    def shares(key, default):
        v = mix.get(key, default)
        return {str(k): float(w) for k, w in (v.items() if isinstance(v, dict) else [(v, 1.0)])}

    hosts = shares("host", {dm["ref_host"]: 1.0})
    tts = shares("task_type", {dm["ref_task_type"]: 1.0})
    turns = shares("turns", {str(round(dm["num"]["turns"][0])): 1.0})
    lg = float(mix.get("long_gap_share", 0.0))
    t1 = float(mix.get("turn1_prompt_chars", math.expm1(dm["num"]["log_turn1"][0])))
    cells = []
    for arm in (mix["arm"] if isinstance(mix["arm"], list) else [mix["arm"]]):
        for h, wh in hosts.items():
            for t, wt in tts.items():
                for n, wn in turns.items():
                    for g, wg in ((1, lg), (0, 1 - lg)):
                        if wh * wt * wn * wg > 0:
                            cells.append((wh * wt * wn * wg, {"arm": arm, "host": h, "task_type": t, "turns": int(n),
                                                              "long_gap": g, "n_long_gaps": g, "t1": t1}))
    return cells


def workload(model: dict, mix: dict, N: int = 1000, D: int = 4000, seed: int = 0) -> dict:
    if "delta_rel" not in model["models"]:
        return {"note": "no fitted model"}
    cells = cells_from_mix(mix, model)
    out = {"mix": mix, "by_arm": {}}
    for arm in sorted({c[1]["arm"] for c in cells}):
        sub = [c for c in cells if c[1]["arm"] == arm]
        out["by_arm"][arm] = workload_total(model, [c[1] for c in sub], [c[0] for c in sub], N, D, seed,
                                            rng=rng_for(seed, "mix", arm, json.dumps(mix, sort_keys=True)))
    return out


# ----------------------------------------------------------------------------------------------- report

def _md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _ci(ci, fmt="{:.3f}"):
    if not ci or ci[0] is None or ci[1] is None:
        return "n/a"
    return f"{fmt.format(ci[0])} to {fmt.format(ci[1])}"


def _usd(x):
    return "n/a" if x is None else (f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}")


def render_report(summary=None, model=None, preds=None, work=None) -> str:
    L = ["# Savings model", "",
         "Saving = anchor cost - arm cost (positive = money saved). Ratios are arm / anchor, so 0.80 is a 20% saving. "
         "Intervals are 95% for estimates and 90% for predictions. Confidence intervals resample scenarios first, then reps.", ""]
    if summary:
        c = summary["counts"]
        L += [f"Cost basis: {summary['basis']}. {c['pairs']} pairs, {c['valid_cost_pairs']} valid for cost; by split {c['by_split']}; "
              f"{c['unjoined_pairs']} pairs could not be joined to their sessions.", "",
              "## A/A noise (anchor vs a second, identical anchor)", "",
              "The mean log ratio should be about 0. Its SD is the run-to-run noise floor for one session.", "",
              _md(["host", "pairs", "mean log ratio", "95% CI", "SD log ratio", "SD per session", "centred on 0"],
                  [[h, v["n_pairs"], v["mean_log_ratio"], _ci(v["mean_log_ratio_ci95"]), v["sd_log_ratio"],
                    v["implied_sd_single_session"], v["centred_on_zero"]] for h, v in summary["aa_noise"].items()]), ""]
        titles = {"overall": "Savings by arm and host", "task_type": "By task type", "gap_pattern": "By gap pattern",
                  "turn_band": "By scripted turn count"}
        for dim, title in titles.items():
            gs = [g for g in summary["groups"] if g["dim"] == dim and g["arm"] != "anchor"]
            if not gs:
                continue
            rows = []
            for g in gs:
                q = g.get("quality") or {}
                rows.append([g["arm"], g["host"], g["value"], g["n_valid_pairs"], g["n_scenarios"],
                             _usd(g.get("mean_saving_usd")), _usd(g.get("median_saving_usd")),
                             g.get("gm_cost_ratio"), _ci(g.get("gm_cost_ratio_ci95")),
                             "" if g.get("saving_pct") is None else f"{g['saving_pct']:.1f}%", g.get("gm_cost_ratio_both_pass"),
                             q.get("mean_delta_turn_pass"), q.get("non_inferior"), g.get("savings_claim_allowed")])
            L += [f"## {title}", "", _md(["arm", "host", "slice", "valid pairs", "scenarios", "mean saving/session", "median",
                                          "cost ratio", "95% CI", "saving", "ratio (both pass)", "d turn-pass", "non-inferior",
                                          "claim allowed"], rows), ""]
        rows = []
        for g in [g for g in summary["groups"] if g["dim"] == "overall" and g["arm"] != "anchor"]:
            q = g.get("quality") or {}
            rows.append([g["arm"], g["host"], q.get("arm_final_pass_rate"), q.get("anchor_final_pass_rate"),
                         f"{q.get('mcnemar_anchor_only_pass')} / {q.get('mcnemar_arm_only_pass')}", q.get("mcnemar_p"),
                         _ci(q.get("delta_turn_pass_ci95")), g.get("rebuild_cost_share"), g.get("mean_model_switches"),
                         g.get("share_sessions_with_switch"), _usd(g.get("mean_receipt_saving_usd"))])
        L += ["## Quality against the anchor, and where the cost comes from", "",
              f"Non-inferior means the 95% lower bound of the mean turn-pass difference is at least {NI_MARGIN}. "
              "McNemar compares the final hidden-test result: anchor-only passes vs arm-only passes.", "",
              _md(["arm", "host", "arm pass", "anchor pass", "anchor-only / arm-only", "McNemar p", "d turn-pass 95% CI",
                   "cache-rebuild share of cost", "switches/session", "sessions with a switch", "receipt saving/session"], rows), ""]
    if model:
        L += ["## Fitted model", ""]
        if not model["models"]:
            L += ["; ".join(model["notes"]) or "not fitted", ""]
        else:
            how = "statsmodels MixedLM, REML" if model["engine"] == "statsmodels" else "numpy method-of-moments variance components + feasible GLS"
            L += [f"Engine: **{model['engine']}** ({how}); {model['n_train_pairs']} train pairs (splits {model['train_splits']}); "
                  f"interactions with arm: {model['interactions']}. Fixed effects use only information known before the session. "
                  "Coefficient CIs are scenario-cluster bootstrap percentiles.", ""]
            for nm, title in (("log_ratio", "Log cost ratio (arm term = log ratio at the reference host and task type, average size)"),
                              ("delta_rel", "Delta $ as a share of predicted anchor cost (arm term negative = saves)"),
                              ("anchor_cost", "Anchor cost submodel (log $ per session, anchor + aa sessions)")):
                m = model["models"].get(nm)
                if m:
                    v = m["variance"]
                    L += [f"### {title}", "", f"{m['n_rows']} rows, {m['n_scenarios']} scenarios. Variance: scenario {v['scenario']}, "
                          f"scenario:rep {v['scenario_rep']}, residual {v['residual']}.", "",
                          _md(["term", "estimate", "model SE", "bootstrap 95% CI"],
                              [[c["term"], c["estimate"], c["se_model"], _ci(c["ci95_boot"], "{:.4f}")] for c in m["coef"]]), ""]
            if model["notes"]:
                L += ["Notes: " + "; ".join(model["notes"]), ""]
    if preds:
        L += ["## Prediction on the test split", ""]
        if "overall" not in preds:
            L += [preds.get("note", "no predictions"), ""]
        else:
            o = preds["overall"]
            pc = o["preregistered_checks"]
            L += [f"{preds['n_test_pairs']} test pairs from {preds['n_test_scenarios']} scenarios; 90% prediction intervals from "
                  f"{preds['draws']} draws. Checks follow the design doc (coverage 0.83-0.97, total inside the interval, slope 0.7-1.3).", "",
                  _md(["check", "value", "pass"], [
                      ["90% PI coverage, log ratio", o["coverage_log_ratio"], pc["coverage_log_ratio_in_0.83_0.97"]],
                      ["90% PI coverage, saving $ (delta model)", o["coverage_saving_delta_model"], pc["coverage_saving_in_0.83_0.97"]],
                      ["90% PI coverage, saving $ (ratio model, c_hat fixed)", o["coverage_saving_ratio_model"], ""],
                      ["measured total inside predicted total PI",
                       f"{_usd(o['observed_total_saving_usd'])} in {_ci(o['predicted_total_pi90'], '{:.0f}')}", pc["total_in_pi90"]],
                      ["calibration slope (measured on predicted saving)", o["calibration_slope"], pc["calibration_slope_in_0.7_1.3"]],
                      ["mean error, saving $/session (pred - measured)", o["mean_error_saving_delta_model_usd"], ""],
                      ["mean error, log ratio (pred - measured)", o["mean_error_log_ratio"], ""]]), "",
                  "### Per arm and host, and per 1,000 sessions with this test mix", "",
                  _md(["arm / host", "pairs", "PI coverage (log)", "PI coverage ($)", "measured total", "predicted total", "total PI90",
                       "inside", "per 1,000 sessions", "PI90 (1,000 sessions)"],
                      [[k.replace("|", " / "), v["n_pairs"], v["coverage_log_ratio"], v["coverage_saving_delta_model"], _usd(v["observed_total_saving_usd"]),
                        _usd(v["predicted_total_saving_usd"]), _ci(v["predicted_total_pi90"], "{:.0f}"), v["observed_total_in_pi"],
                        _usd(v["per_1000_sessions"]["saving_usd_point"]), _ci(v["per_1000_sessions"]["saving_usd_pi90"], "{:,.0f}")]
                       for k, v in preds["by_arm_host"].items()]), ""]
    if work and work.get("by_arm"):
        L += ["## Workload calculator", "", f"Mix: `{json.dumps(work['mix'], sort_keys=True)}`", "",
              _md(["arm", "sessions", "saving", "90% PI", "per session", "share of anchor spend"],
                  [[a, v["n_sessions"], _usd(v["saving_usd_point"]), _ci(v["saving_usd_pi90"], "{:,.0f}"),
                    _usd(v["saving_usd_per_session"]), f"{v['saving_pct_of_anchor_spend']}%"] for a, v in work["by_arm"].items()]), ""]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- CLI

def _write(out: Path, name: str, doc) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / name, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")


def _read(out: Path, name: str):
    p = out / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _report(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "MODEL.md").write_text(render_report(_read(out, "summary.json"), _read(out, "model.json"),
                                                _read(out, "predictions.json"), _read(out, "workload.json")), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Savings model for the paired campaign (see module docstring)")
    ap.add_argument("cmd", choices=["summarize", "fit", "predict", "workload", "all", "report"])
    ap.add_argument("root", help="campaign root (contains rows/)")
    ap.add_argument("--out", help="output directory (default <root>/model)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--basis", default="normalized", choices=["normalized", "raw"])
    ap.add_argument("--boot", type=int, default=2000, help="bootstrap draws for summaries")
    ap.add_argument("--fit-boot", type=int, default=400, help="bootstrap refits for the mixed models")
    ap.add_argument("--draws", type=int, default=4000, help="prediction-interval draws")
    ap.add_argument("--engine", default="auto", choices=["auto", "statsmodels", "fallback"])
    ap.add_argument("--train-splits", default="train")
    ap.add_argument("--test-splits", default="test")
    ap.add_argument("--include-aa", action="store_true", help="fit the A/A arm as an arm too")
    ap.add_argument("--arm-interactions", action="store_true", help="cross every covariate with arm (needs more scenarios)")
    ap.add_argument("--mix", help="workload mix JSON file")
    ap.add_argument("--sessions", type=int, default=1000, help="workload size")
    a = ap.parse_args(argv)
    out = Path(a.out).expanduser() if a.out else Path(a.root).expanduser() / "model"
    if a.cmd == "report":
        _report(out)
        return 0
    ds = load_dataset(a.root, a.basis)
    train, test = tuple(a.train_splits.split(",")), tuple(a.test_splits.split(","))
    if a.cmd in ("summarize", "all"):
        _write(out, "summary.json", summarize(ds, a.seed, a.boot))
    model: dict | None = None
    if a.cmd in ("fit", "all"):
        model = fit(ds, train, a.engine, a.fit_boot, a.seed, a.include_aa, a.arm_interactions)
        _write(out, "model.json", model)
    if a.cmd in ("predict", "workload", "all") and model is None:
        model = _read(out, "model.json")
    if model is None and a.cmd in ("predict", "workload", "all"):
        print("no model.json: run `fit` first", file=sys.stderr)
        return 4
    assert model is not None or a.cmd in ("summarize",)
    if a.cmd in ("predict", "all"):
        _write(out, "predictions.json", predict(model, ds, test, a.draws, a.seed))
    if a.cmd == "workload" or (a.cmd == "all" and a.mix):
        if not a.mix:
            print("workload needs --mix", file=sys.stderr)
            return 4
        mix = json.loads(Path(a.mix).expanduser().read_text(encoding="utf-8"))
        _write(out, "workload.json", workload(model, mix, a.sessions, a.draws, a.seed))
    _report(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
