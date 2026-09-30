"""The `decisions` block of summary.json: the preregistered decision rules
(evals/judge_bench/holdout/PREREGISTRATION.md) applied to a run.

Every number comes from `summarize.Ctx.outcomes` (per-case majority over repetitions, all
manifest cases in the denominator). On the dev split the block is labeled `screen`; only the
holdout split, run under the guard, is `preregistered`.
"""
from __future__ import annotations

from .scoring import resolve_policy
from .stats import SEED, bootstrap_ci, holm, mcnemar_exact, wilson
from .summarize import is_intervention, is_local

BASELINE = "jev-1.13"
NI_ACCURACY = -0.05       # lower 95% bound of (candidate - jev) must exceed this
NI_WRONG_AUTO = 0.03      # upper 95% bound of (candidate - jev) must be below this
P95_MS = 500.0
COST_RATIO = 2.0
VALID_SHARE = 0.98
OFFLINE_POLICY = "bundle-read-shortcut+noul-gate+host-guard"
OFFLINE_MIN_COVERAGE = 0.30
OFFLINE_MAX_WRONG_AUTO_UPPER = 0.10
I1_CLASSES = ("acted_on_side_effect", "under_deferred")
HOST_CLASSES = ("acted_on_side_effect",)
NOUL_CLASSES = ("accepted_wrong_code", "rejected_correct_code")
POLICY_INTERVENTIONS = (("I2", "+host-guard", HOST_CLASSES),
                        ("I3", "+noul-gate", NOUL_CLASSES),
                        ("I2+I3", "+noul-gate+host-guard", HOST_CLASSES + NOUL_CLASSES))


def _paired(ctx, policy, arm_a, arm_b, metric, B):
    va, vb = ctx.outcomes(arm_a, policy), ctx.outcomes(arm_b, policy)
    ids = ctx.order_ids
    only_a = sum(va[c][metric] and not vb[c][metric] for c in ids)
    only_b = sum(vb[c][metric] and not va[c][metric] for c in ids)
    diffs = [int(va[c][metric]) - int(vb[c][metric]) for c in ids]
    n = len(ids)
    return {"n_pairs": n, "candidate_only": only_a, "baseline_only": only_b,
            "rate_candidate": sum(va[c][metric] for c in ids) / n if n else None,
            "rate_baseline": sum(vb[c][metric] for c in ids) / n if n else None,
            "diff": (sum(diffs) / n) if n else None, "diff_ci95": bootstrap_ci(diffs, B=B, seed=SEED),
            "p": mcnemar_exact(only_a, only_b)}


def _arm_cost(summary_arm):
    vals = [rep["cost"].get("usd_per_1m_decisions") for rep in summary_arm["reps"].values()]
    return None if not vals or any(v is None for v in vals) else sum(vals) / len(vals)


def _valid_shares(summary_arm, primary):
    blocks = summary_arm["policies"][primary]["reps"]
    return {rep: (b["valid"] / b["n"] if b["n"] else 0.0) for rep, b in blocks.items()}


def _totals(ctx, arm, policy):
    o = ctx.outcomes(arm, policy)
    n = len(ctx.order_ids)
    return {"n": n, "correct": sum(v["correct"] for v in o.values()),
            "automatic": sum(v["automatic"] for v in o.values()),
            "automatic_errors": sum(v["automatic_error"] for v in o.values())}


def _rule1(ctx, summary, primary_policy, B):
    if BASELINE not in ctx.arms:
        return {"available": False, "note": f"{BASELINE} has no rows in this run"}
    primary = primary_policy["name"]
    candidates = [a for a in ctx.arms if a != BASELINE]
    acc = {a: _paired(ctx, primary_policy, a, BASELINE, "correct", B) for a in candidates}
    wa = {a: _paired(ctx, primary_policy, a, BASELINE, "automatic_error", B) for a in candidates}
    for family in (acc, wa):
        for a, adj in zip(candidates, holm([family[a]["p"] for a in candidates])):
            family[a]["p_holm"] = adj
    jev_cost = _arm_cost(summary["arms"][BASELINE])
    out = {}
    for a in candidates:
        d_acc, d_wa = acc[a], wa[a]
        ni_acc = d_acc["diff_ci95"] is not None and d_acc["diff_ci95"][0] > NI_ACCURACY
        ni_wa = d_wa["diff_ci95"] is not None and d_wa["diff_ci95"][1] < NI_WRONG_AUTO
        superior = []
        if d_acc["diff"] is not None and d_acc["diff"] > 0 and d_acc["p_holm"] <= .05:
            superior.append("accuracy")
        if d_wa["diff"] is not None and d_wa["diff"] < 0 and d_wa["p_holm"] <= .05:
            superior.append("wrong_automatic")
        p95 = ctx.pooled_latency(a)
        cost = _arm_cost(summary["arms"][a])
        cost_ok = cost is not None and jev_cost is not None and cost <= COST_RATIO * jev_cost
        shares = _valid_shares(summary["arms"][a], primary)
        valid_ok = bool(shares) and all(v >= VALID_SHARE for v in shares.values())
        p95_ok = p95 is not None and p95 <= P95_MS
        out[a] = {
            "accuracy": d_acc, "wrong_automatic": d_wa,
            "rep_counts": {a: len(ctx.reps(a)), BASELINE: len(ctx.reps(BASELINE))},
            "non_inferior_accuracy": ni_acc, "non_inferior_wrong_auto": ni_wa, "superior_on": superior,
            "p95_ms": p95, "p95_ok": p95_ok,
            "cost_usd_per_1m": cost, "cost_usd_per_1m_jev": jev_cost, "cost_ok": cost_ok,
            "valid_share_by_rep": shares, "valid_ok": valid_ok,
            "replaces_default": bool(ni_acc and ni_wa and superior and p95_ok and cost_ok and valid_ok),
        }
    return {"available": True, "baseline": BASELINE, "policy": primary,
            "sign_convention": "diff = candidate - jev-1.13 for both endpoints: accuracy diff > 0 is better; "
                               "wrong-automatic diff < 0 is better",
            "margins": {"accuracy_lower_bound_above": NI_ACCURACY, "wrong_automatic_upper_bound_below": NI_WRONG_AUTO,
                        "p95_ms_at_most": P95_MS, "cost_at_most_x_jev": COST_RATIO, "valid_share_at_least": VALID_SHARE},
            "holm_family": "all candidates, per endpoint", "candidates": out}


def _rule2(ctx):
    policy = resolve_policy(OFFLINE_POLICY)
    rows = []
    for a in ctx.arms:
        if not is_local(a, ctx.specs) or is_intervention(a, ctx.specs):
            continue
        t = _totals(ctx, a, policy)
        n = t["n"]
        rows.append({"arm": a, "coverage": t["automatic"] / n if n else 0.0,
                     "wrong_automatic": {"k": t["automatic_errors"], "n": n,
                                         "rate": t["automatic_errors"] / n if n else None,
                                         "ci95": wilson(t["automatic_errors"], n)},
                     "accuracy": t["correct"] / n if n else 0.0})
    eligible = [r for r in rows if r["coverage"] >= OFFLINE_MIN_COVERAGE]
    eligible.sort(key=lambda r: (r["wrong_automatic"]["rate"], -r["accuracy"], r["arm"]))
    best = eligible[0] if eligible else None
    recommended = bool(best and best["wrong_automatic"]["ci95"][1] < OFFLINE_MAX_WRONG_AUTO_UPPER)
    return {"policy": OFFLINE_POLICY, "min_coverage": OFFLINE_MIN_COVERAGE,
            "max_wrong_automatic_upper_95": OFFLINE_MAX_WRONG_AUTO_UPPER,
            "scope": "local arms without a prompt intervention", "ranking": eligible,
            "below_coverage_floor": [r["arm"] for r in rows if r not in eligible],
            "best": best["arm"] if best else None, "recommended": best["arm"] if recommended else None}


def _delta(ctx, arm_base, policy_base, arm_new, policy_new, classes, B):
    ob, on = ctx.outcomes(arm_base, policy_base), ctx.outcomes(arm_new, policy_new)
    ids, n = ctx.order_ids, len(ctx.order_ids)
    before = ctx.class_count(arm_base, policy_base, classes)
    after = ctx.class_count(arm_new, policy_new, classes)
    only_new = sum(on[c]["automatic_error"] and not ob[c]["automatic_error"] for c in ids)
    only_base = sum(ob[c]["automatic_error"] and not on[c]["automatic_error"] for c in ids)
    acc_change = sum(on[c]["correct"] for c in ids) - sum(ob[c]["correct"] for c in ids)
    cov_change = 100.0 * (sum(on[c]["automatic"] for c in ids) - sum(ob[c]["automatic"] for c in ids)) / n if n else None
    reduction = (before - after) / before if before else None
    guards = acc_change >= -2 and cov_change is not None and cov_change >= -10
    return {"arm": arm_new, "base": arm_base, "targeted_wrong_auto_before": before,
            "targeted_wrong_auto_after": after, "reduction": reduction,
            "accuracy_change_cases": acc_change, "coverage_change_points": cov_change,
            "mcnemar_automatic_error": {"only_after": only_new, "only_before": only_base,
                                        "p": mcnemar_exact(only_new, only_base)},
            "applicable": before > 0, "guards_ok": guards,
            "confirmed": bool(before > 0 and reduction >= .5 and guards)}


def _pool(entries):
    """Overall verdict across arms: pooled reduction, every applicable arm inside the guards."""
    applicable = [e for e in entries if e["applicable"]]
    before = sum(e["targeted_wrong_auto_before"] for e in applicable)
    after = sum(e["targeted_wrong_auto_after"] for e in applicable)
    reduction = (before - after) / before if before else None
    return {"arms": [e["arm"] for e in applicable], "targeted_wrong_auto_before": before,
            "targeted_wrong_auto_after": after, "reduction": reduction,
            "all_guards_ok": all(e["guards_ok"] for e in applicable),
            "confirmed": bool(applicable and reduction >= .5 and all(e["guards_ok"] for e in applicable))}


def _rule4(ctx, primary_policy, B):
    primary = primary_policy["name"]
    i1 = []
    for a in ctx.arms:
        specs = ctx.specs.get(a) or {}
        if specs.get("adapter") == "instruction_clause" and specs.get("base") in ctx.arms:
            i1.append(_delta(ctx, specs["base"], primary_policy, a, primary_policy, I1_CLASSES, B))
    out = {"confirmation_rule": "targeted wrong-automatic pooled over repetitions reduced by >= 50%, accuracy down "
                                "<= 2 cases, coverage down <= 10 points (per-case majority unit)",
           "I1_prompt_clause": {"targeted_classes": list(I1_CLASSES), "policy": primary, "arms": i1, "overall": _pool(i1)}}
    arms = [a for a in ctx.arms if not is_intervention(a, ctx.specs)]
    for tag, suffix, classes in POLICY_INTERVENTIONS:
        try:
            policy = resolve_policy(primary + suffix)
        except (KeyError, ValueError) as exc:
            out[tag] = {"error": str(exc)}
            continue
        entries = [_delta(ctx, a, primary_policy, a, policy, classes, B) for a in arms]
        out[tag] = {"policy": policy["name"], "versus": primary, "targeted_classes": list(classes),
                    "arms": entries, "overall": _pool(entries)}
    return out


def build_decisions(ctx, summary, primary_policy, split, label, B):
    non_local = [a for a in ctx.arms if not is_local(a, ctx.specs) and a != BASELINE
                 and not is_intervention(a, ctx.specs)]
    rule3 = {}
    for a in non_local:
        t = _totals(ctx, a, primary_policy)
        rule3[a] = {"accuracy": t["correct"] / t["n"] if t["n"] else None,
                    "wrong_automatic": t["automatic_errors"] / t["n"] if t["n"] else None,
                    "p95_ms": ctx.pooled_latency(a), "cost_usd_per_1m": _arm_cost(summary["arms"][a])}
    return {"split": split, "label": label, "primary_policy": primary_policy["name"],
            "unit": "per-case majority over repetitions, all manifest cases, missing/invalid rows count as fallbacks",
            "rule1_default_judge": _rule1(ctx, summary, primary_policy, B),
            "rule2_offline_tier": _rule2(ctx),
            "rule3_cloud_fallback_descriptive": rule3,
            "rule4_interventions": _rule4(ctx, primary_policy, B)}
