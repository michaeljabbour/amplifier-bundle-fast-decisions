"""Deterministic summary of a request log: pure function of rows, cases, tags, policies.

Scores are recomputed here from raw answers, never read from the log, so a replay
of requests.jsonl reproduces summary.json (byte for byte on one platform; floats can
differ in the last digit across platform math libraries).

The preregistered unit is the per-case outcome (`case_outcomes`): the denominator is EVERY case
in the manifest; for each case and repetition a missing, invalid or unscorable row counts as
"not correct, not automatic" (a fallback); the per-case outcome is the majority over
repetitions, ties broken toward the rep-1 outcome (then the lowest rep present). Majority-vote
metrics, pairwise contrasts, the decisions block and report.py all read this one function.
"""
from __future__ import annotations

import statistics

from .failure import classify
from .scoring import score
from .stats import (SEED, bootstrap_ci, brier_decomposition, ece, holm, mcnemar_exact, nearest_rank,
                    wilson)

SCHEMA = "fast-decisions-evals/judge-summary/v1"
KINDS = ("select", "search", "cua")
OUTCOME_KEYS = ("correct", "automatic", "automatic_error")


# ------------------------------------------------------------------ spec helpers

def spec_chain(name, specs):
    """The arm's spec followed by the specs of its `base` wrappers."""
    out, spec = [], (specs or {}).get(name)
    while spec:
        out.append(spec)
        spec = specs.get(spec.get("base"))
    return out


def _adapters(name, specs):
    return [s.get("adapter") for s in spec_chain(name, specs)]


def is_local(name, specs) -> bool:
    return any(s.get("local") or s.get("adapter") == "ollama_backend" for s in spec_chain(name, specs))


def is_intervention(name, specs) -> bool:
    return "instruction_clause" in _adapters(name, specs)


def _price(name, specs):
    for spec in spec_chain(name, specs):
        if spec.get("price_in") is not None or spec.get("price_out") is not None:
            return spec
    return None


def _tier_multiplier(name, specs) -> float:
    for spec in spec_chain(name, specs):
        if spec.get("adapter") == "chat":
            return float(spec.get("priority_multiplier") or 1.0) if spec.get("service_tier") == "priority" else 1.0
    return 1.0


def _rate(k, n):
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": wilson(k, n)}


# ------------------------------------------------------------------ scoring rows

def _row_score(row, case, policy):
    """(status, scored): status is missing | invalid | unscorable | ok."""
    if row is None:
        return "missing", None
    if not row.get("valid"):
        return "invalid", None
    try:
        return "ok", score(case, row["answer"], row["elapsed_ms"], policy)
    except (ValueError, KeyError, TypeError):
        return "unscorable", None


def _rep_outcome(s):
    if s is None:
        return {k: False for k in OUTCOME_KEYS}
    return {k: bool(s[k]) for k in OUTCOME_KEYS}


def _majority_outcome(per_rep):
    """per_rep: [(rep, outcome)] sorted by rep. Majority per key; a tie goes to the lowest rep's."""
    out = {}
    for key in OUTCOME_KEYS:
        flags = [o[key] for _, o in per_rep]
        yes = sum(flags)
        out[key] = flags[0] if 2 * yes == len(flags) else 2 * yes > len(flags)
    return out


class Ctx:
    """Indexed rows plus cached scoring; shared by summarize() and decisions."""

    def __init__(self, rows, cases, tags, specs):
        self.cases, self.tags, self.specs = cases, tags, specs or {}
        self.by_case = {c["id"]: c for c in cases}
        self.order_ids = [c["id"] for c in cases]
        self.index: dict = {}
        for row in rows:
            if row.get("id") not in self.by_case:
                continue
            self.index.setdefault((row["arm"], int(row.get("rep", 1)), int(row["order"])), {})[row["id"]] = row
        self.arms = sorted({k[0] for k in self.index})
        self._reps = {a: sorted({k[1] for k in self.index if k[0] == a}) for a in self.arms}
        self._scores: dict = {}
        self._outcomes: dict = {}

    def reps(self, arm):
        return self._reps[arm]

    def rows(self, arm, rep, order=0):
        return self.index.get((arm, rep, order), {})

    def scored(self, arm, rep, cid, policy, order=0):
        key = (arm, rep, order, cid, policy["name"])
        if key not in self._scores:
            self._scores[key] = _row_score(self.rows(arm, rep, order).get(cid), self.by_case[cid], policy)
        return self._scores[key]

    def entries(self, arm, rep, policy):
        return [(self.by_case[cid], self.rows(arm, rep).get(cid), *self.scored(arm, rep, cid, policy))
                for cid in self.order_ids]

    def outcomes(self, arm, policy):
        key = (arm, policy["name"])
        if key not in self._outcomes:
            reps = self.reps(arm)
            self._outcomes[key] = {
                cid: _majority_outcome([(r, _rep_outcome(self.scored(arm, r, cid, policy)[1])) for r in reps])
                for cid in self.order_ids}
        return self._outcomes[key]

    def class_count(self, arm, policy, classes) -> int:
        """Automatic errors of the given failure classes, pooled over repetitions (order 0)."""
        total = 0
        for rep in self.reps(arm):
            for cid in self.order_ids:
                s = self.scored(arm, rep, cid, policy)[1]
                if s is not None and s["automatic_error"] and classify(
                        self.by_case[cid], self.tags.get(cid), s["predicted"]) in classes:
                    total += 1
        return total

    def pooled_latency(self, arm, q=.95):
        vals = [r["elapsed_ms"] for (a, _, _), d in self.index.items() if a == arm
                for r in d.values() if r.get("valid")]
        return nearest_rank(vals, q)


def case_outcomes(rows, cases, policy, arm):
    """cid -> {correct, automatic, automatic_error} for EVERY case in `cases`; see module docstring."""
    ctx = Ctx([r for r in rows if r.get("arm") == arm], cases, {}, {})
    if arm not in ctx.arms:
        return {c["id"]: {k: False for k in OUTCOME_KEYS} for c in cases}
    return ctx.outcomes(arm, policy)


# ------------------------------------------------------------------------ blocks

def _core(entries, detail):
    """entries: [(case, row-or-None, status, scored-or-None)] for one slice; n counts every case."""
    n = len(entries)
    scored = [(c, r, s) for c, r, st, s in entries if s is not None]
    auto = [e for e in scored if e[2]["automatic"]]
    errors = [e for e in auto if e[2]["automatic_error"]]
    correct = sum(s["correct"] for _, _, s in scored)
    reasons: dict[str, int] = {}
    for _, _, s in scored:
        if s["fallback_reason"]:
            reasons[s["fallback_reason"]] = reasons.get(s["fallback_reason"], 0) + 1
    statuses = [st for _, _, st, _ in entries]
    out = {
        "n": n, "valid": len(scored), "correct": correct,
        "missing": statuses.count("missing"), "invalid": statuses.count("invalid"),
        "unscorable": statuses.count("unscorable"),
        "repaired": sum(bool((r["answer"] or {}).get("repaired")) for _, r, _ in scored),
        "accuracy": _rate(correct, n),
        "coverage": _rate(len(auto), n),
        "automatic": len(auto), "automatic_errors": len(errors),
        "wrong_automatic_rate": _rate(len(errors), n),
        "automatic_accuracy": _rate(len(auto) - len(errors), len(auto)),
        "mean_brier": statistics.mean(s["brier"] for _, _, s in scored) if scored else None,
        "fallback_reasons": reasons,
    }
    if detail is not None:
        conf = [s["certainty"] for _, _, s in scored]
        hit = [s["correct"] for _, _, s in scored]
        out["calibration"] = {"basis": "top_label_confidence", "bins": 10, "ece": ece(conf, hit),
                              "self_reported": detail["self_reported"],
                              "brier_decomposition": brier_decomposition(conf, hit)}
        classes: dict[str, int] = {}
        auto_classes: dict[str, int] = {}
        for case, _, s in scored:
            label = classify(case, detail["tags"].get(case["id"]), s["predicted"])
            if label:
                classes[label] = classes.get(label, 0) + 1
                if s["automatic"]:
                    auto_classes[label] = auto_classes.get(label, 0) + 1
        out["failure_classes"] = classes
        out["automatic_failure_classes"] = auto_classes
    return out


def _cost_block(arm, specs, billed):
    """Cost of the requests that were billed (tokens reported), valid or not."""
    cost = {"requests": len(billed),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in billed) if billed else None,
            "mean_output_tokens": statistics.mean((r.get("output_tokens") or 0) for r in billed) if billed else None}
    price = _price(arm, specs)
    if billed and price:
        p_in, p_out = price.get("price_in") or 0.0, price.get("price_out") or 0.0
        listed = [((r["input_tokens"] or 0) * p_in + (r.get("output_tokens") or 0) * p_out) / 1e6 for r in billed]
        mult = _tier_multiplier(arm, specs)
        usd = [x * mult for x in listed]
        cost.update(usd_total=sum(usd), usd_per_request=statistics.mean(usd),
                    usd_per_1m_decisions=1e6 * statistics.mean(usd))
        if mult != 1.0:
            cost.update(service_tier="priority", usd_per_1m_decisions_list=1e6 * statistics.mean(listed))
        if price.get("priority_multiplier"):
            cost["usd_per_1m_decisions_priority"] = 1e6 * statistics.mean(listed) * price["priority_multiplier"]
    elif is_local(arm, specs):
        cost.update(usd_per_1m_decisions=0.0, note="local: no API charge")
    else:
        cost.update(usd_per_1m_decisions=None, note="unpriced")
    reasoning = [r["reasoning_tokens"] for r in billed if r.get("reasoning_tokens") is not None]
    if reasoning:
        cost["mean_reasoning_tokens"] = statistics.mean(reasoning)
    return cost


def summarize(rows, cases, tags, policies, specs=None, contrasts=None, primary=None,
              timeout_ms=3000, bootstrap_b=10000, split=None):
    specs = specs or {}
    ctx = Ctx(rows, cases, tags, specs)
    order_ids = ctx.order_ids
    primary = primary or policies[0]["name"]
    primary_policy = next(p for p in policies if p["name"] == primary)
    screens = sorted({c.get("screen") for c in cases if c.get("screen")})
    if split is None:
        split = "holdout" if screens == ["holdout"] else "dev"
    label = "preregistered" if split == "holdout" else "screen"

    summary = {"schema": SCHEMA, "split": split, "label": label, "primary_policy": primary,
               "n_cases": len(cases), "policies": [p["name"] for p in policies], "arms": {}}
    for arm in ctx.arms:
        adapters = _adapters(arm, specs)
        flags = {"self_reported_probabilities": "chat" in adapters,
                 "order_flip_comparable": "ollama_backend" not in adapters}
        detail = {"self_reported": flags["self_reported_probabilities"], "tags": tags}
        reps = ctx.reps(arm)
        arm_out = {"flags": flags, "reps": {}, "policies": {}}
        for rep in reps:
            first, second = ctx.rows(arm, rep, 0), ctx.rows(arm, rep, 1)
            every = list(first.values()) + list(second.values())
            valid_rows = [r for r in every if r.get("valid")]
            lat = [r["elapsed_ms"] for r in valid_rows]
            lat_all = [r["elapsed_ms"] for r in every if r.get("elapsed_ms") is not None]
            flips = pairs = 0
            for cid in order_ids:
                if cid in first and cid in second:
                    a = ctx.scored(arm, rep, cid, primary_policy, 0)[1]
                    b = ctx.scored(arm, rep, cid, primary_policy, 1)[1]
                    if a is not None and b is not None:
                        pairs += 1
                        flips += a["predicted"] != b["predicted"]
            billed = [r for r in every if r.get("input_tokens") is not None]
            arm_out["reps"][str(rep)] = {
                "requests": len(every), "invalid_requests": len(every) - len(valid_rows),
                "latency": {"basis": "valid_requests", "n": len(lat), "n_all": len(lat_all),
                            "errors": len(every) - len(valid_rows),
                            "p50_ms": nearest_rank(lat, .50), "p95_ms": nearest_rank(lat, .95),
                            "p95_ms_all_requests": nearest_rank(lat_all, .95),
                            "max_ms": max(lat) if lat else None,
                            f"over_{timeout_ms}ms": sum(x > timeout_ms for x in lat_all),
                            f"over_{timeout_ms}ms_valid": sum(x > timeout_ms for x in lat)},
                "order_flips": {"comparable": flags["order_flip_comparable"], "pairs": pairs, "flips": flips},
                "cost": _cost_block(arm, specs, billed),
            }
        for policy in policies:
            name = policy["name"]
            pol_out = {"reps": {}}
            per_case: dict = {}
            for rep in reps:
                entries = ctx.entries(arm, rep, policy)
                for case, _, _, s in entries:
                    if s is not None:
                        per_case.setdefault(case["id"], []).append(s)
                block = _core(entries, detail)
                if not policy.get("sweep"):
                    slices = {}
                    for screen in ["all"] + screens:
                        for kind in ["all"] + list(KINDS):
                            subset = [e for e in entries if (screen == "all" or e[0].get("screen") == screen)
                                      and (kind == "all" or e[0]["kind"] == kind)]
                            if subset and (screen, kind) != ("all", "all"):
                                slices[f"{screen}/{kind}"] = _core(subset, None)
                    block["slices"] = slices
                pol_out["reps"][str(rep)] = block
            accs = [pol_out["reps"][str(r)]["accuracy"]["rate"] for r in reps]
            waers = [pol_out["reps"][str(r)]["wrong_automatic_rate"]["rate"] for r in reps]
            eligible = [v for v in per_case.values() if len(v) >= 2]
            agree = sum(len({s["predicted"] for s in v}) == 1 for v in eligible)
            voted = ctx.outcomes(arm, policy)
            n = len(order_ids)
            k_correct = sum(o["correct"] for o in voted.values())
            k_auto = sum(o["automatic"] for o in voted.values())
            k_err = sum(o["automatic_error"] for o in voted.values())
            pol_out["across_reps"] = {
                "reps": len(reps),
                "accuracy": {"mean": statistics.mean(accs), "min": min(accs), "max": max(accs)},
                "wrong_automatic_rate": {"mean": statistics.mean(waers), "min": min(waers), "max": max(waers)},
                "per_case_agreement": {"cases": len(eligible), "agree": agree,
                                       "rate": (agree / len(eligible)) if eligible else None},
                "majority_vote": {"n": n, "correct": k_correct,
                                  "accuracy": (k_correct / n) if n else None, "ci95": wilson(k_correct, n),
                                  "automatic": k_auto, "coverage": _rate(k_auto, n),
                                  "automatic_errors": k_err, "wrong_automatic_rate": _rate(k_err, n),
                                  "tie_rule": "toward the lowest repetition present"},
            }
            arm_out["policies"][name] = pol_out
        summary["arms"][arm] = arm_out

    pairwise = {"policy": primary, "basis": "all manifest cases, per-case majority over reps "
                "(missing/invalid rows count as fallbacks; ties toward rep 1)", "contrasts": {}}
    for metric in ("correct", "automatic_error"):
        results = []
        for a, b in contrasts or []:
            if a not in ctx.arms or b not in ctx.arms:
                continue
            va, vb = ctx.outcomes(a, primary_policy), ctx.outcomes(b, primary_policy)
            only_a = sum(va[c][metric] and not vb[c][metric] for c in order_ids)
            only_b = sum(vb[c][metric] and not va[c][metric] for c in order_ids)
            diffs = [int(va[c][metric]) - int(vb[c][metric]) for c in order_ids]
            n = len(order_ids)
            counts = {a: len(ctx.reps(a)), b: len(ctx.reps(b))}
            results.append({"a": a, "b": b, "n_pairs": n, "a_only": only_a, "b_only": only_b,
                            "rep_counts": counts, "rep_counts_equal": counts[a] == counts[b],
                            "rate_a": sum(va[c][metric] for c in order_ids) / n if n else None,
                            "rate_b": sum(vb[c][metric] for c in order_ids) / n if n else None,
                            "diff": (sum(diffs) / n) if n else None,
                            "diff_ci95": bootstrap_ci(diffs, B=bootstrap_b, seed=SEED),
                            "p": mcnemar_exact(only_a, only_b)})
        for r, adj in zip(results, holm([r["p"] for r in results])):
            r["p_holm"] = adj
        pairwise["contrasts"][metric] = results
    summary["pairwise"] = pairwise

    from .decisions import build_decisions
    summary["decisions"] = build_decisions(ctx, summary, primary_policy, split, label, bootstrap_b)
    return summary
