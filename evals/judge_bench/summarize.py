"""Deterministic summary of a request log: pure function of rows, cases, tags, policies.

Scores are recomputed here from raw answers, never read from the log, so a replay
of requests.jsonl reproduces summary.json byte for byte.
"""
from __future__ import annotations

import statistics

from .failure import classify
from .scoring import score
from .stats import (SEED, bootstrap_ci, brier_decomposition, ece, holm, mcnemar_exact, nearest_rank,
                    wilson)

SCHEMA = "fast-decisions-evals/judge-summary/v1"
KINDS = ("select", "search", "cua")


def _chain(name, specs):
    """Adapters from an arm's spec down through its `base` wrappers."""
    out, spec = [], (specs or {}).get(name)
    while spec:
        out.append(spec.get("adapter"))
        spec = specs.get(spec.get("base"))
    return out


def _price(name, specs):
    spec = (specs or {}).get(name)
    while spec:
        if spec.get("price_in") is not None or spec.get("price_out") is not None:
            return spec
        spec = specs.get(spec.get("base"))
    return None


def _rate(k, n):
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": wilson(k, n)}


def _core(entries, detail):
    """entries: [(case, row, scored-or-None)] for primary-order rows of one slice."""
    n = len(entries)
    valid = [(c, r, s) for c, r, s in entries if s is not None]
    auto = [e for e in valid if e[2]["automatic"]]
    errors = [e for e in auto if e[2]["automatic_error"]]
    correct = sum(s["correct"] for _, _, s in valid)
    reasons: dict[str, int] = {}
    for _, _, s in valid:
        if s["fallback_reason"]:
            reasons[s["fallback_reason"]] = reasons.get(s["fallback_reason"], 0) + 1
    out = {
        "n": n, "valid": len(valid), "correct": correct,
        "accuracy": _rate(correct, n),
        "coverage": _rate(len(auto), n),
        "automatic": len(auto), "automatic_errors": len(errors),
        "wrong_automatic_rate": _rate(len(errors), n),
        "automatic_accuracy": _rate(len(auto) - len(errors), len(auto)),
        "mean_brier": statistics.mean(s["brier"] for _, _, s in valid) if valid else None,
        "fallback_reasons": reasons,
    }
    if detail is not None:
        conf = [s["certainty"] for _, _, s in valid]
        hit = [s["correct"] for _, _, s in valid]
        out["calibration"] = {"basis": "top_label_confidence", "bins": 10, "ece": ece(conf, hit),
                              "self_reported": detail["self_reported"],
                              "brier_decomposition": brier_decomposition(conf, hit)}
        classes: dict[str, int] = {}
        auto_classes: dict[str, int] = {}
        for case, _, s in valid:
            label = classify(case, detail["tags"].get(case["id"]), s["predicted"])
            if label:
                classes[label] = classes.get(label, 0) + 1
                if s["automatic"]:
                    auto_classes[label] = auto_classes.get(label, 0) + 1
        out["failure_classes"] = classes
        out["automatic_failure_classes"] = auto_classes
    return out


def _majority(flags):
    return 2 * sum(flags) > len(flags)


def summarize(rows, cases, tags, policies, specs=None, contrasts=None, primary=None,
              timeout_ms=3000, bootstrap_b=10000):
    specs = specs or {}
    by_case = {c["id"]: c for c in cases}
    order_ids = [c["id"] for c in cases]
    primary = primary or policies[0]["name"]
    primary_policy = next(p for p in policies if p["name"] == primary)
    screens = sorted({c.get("screen") for c in cases if c.get("screen")})

    index: dict = {}
    for row in rows:
        if row["id"] not in by_case:
            continue
        key = (row["arm"], int(row.get("rep", 1)), int(row["order"]))
        index.setdefault(key, {})[row["id"]] = row
    arms = sorted({k[0] for k in index})

    def scored(policy, row):
        if not row.get("valid"):
            return None
        try:
            return score(by_case[row["id"]], row["answer"], row["elapsed_ms"], policy)
        except (ValueError, KeyError, TypeError):
            return None

    summary = {"schema": SCHEMA, "primary_policy": primary, "n_cases": len(cases),
               "policies": [p["name"] for p in policies], "arms": {}}
    majority_by_arm: dict = {}
    for arm in arms:
        chain = _chain(arm, specs)
        flags = {"self_reported_probabilities": "chat" in chain,
                 "order_flip_comparable": "ollama_backend" not in chain}
        detail = {"self_reported": flags["self_reported_probabilities"], "tags": tags}
        reps = sorted({k[1] for k in index if k[0] == arm})
        arm_out = {"flags": flags, "reps": {}, "policies": {}}
        price = _price(arm, specs)
        for rep in reps:
            first = index.get((arm, rep, 0), {})
            second = index.get((arm, rep, 1), {})
            every = list(first.values()) + list(second.values())
            valid_rows = [r for r in every if r.get("valid")]
            lat = [r["elapsed_ms"] for r in valid_rows]
            flips = pairs = 0
            for cid in order_ids:
                if cid in first and cid in second:
                    a, b = scored(primary_policy, first[cid]), scored(primary_policy, second[cid])
                    if a is not None and b is not None:
                        pairs += 1
                        flips += a["predicted"] != b["predicted"]
            billed = [r for r in valid_rows if r.get("input_tokens") is not None]
            cost = {"requests": len(billed),
                    "mean_input_tokens": statistics.mean(r["input_tokens"] for r in billed) if billed else None,
                    "mean_output_tokens": statistics.mean((r.get("output_tokens") or 0) for r in billed) if billed else None}
            if billed and price:
                p_in, p_out = price.get("price_in") or 0.0, price.get("price_out") or 0.0
                usd = [((r["input_tokens"] or 0) * p_in + (r.get("output_tokens") or 0) * p_out) / 1e6 for r in billed]
                cost.update(usd_total=sum(usd), usd_per_request=statistics.mean(usd),
                            usd_per_1m_decisions=1e6 * statistics.mean(usd))
                if price.get("priority_multiplier"):
                    cost["usd_per_1m_decisions_priority"] = cost["usd_per_1m_decisions"] * price["priority_multiplier"]
            else:
                cost.update(usd_per_1m_decisions=0.0, note="no API price (local or unpriced)")
            reasoning = [r["reasoning_tokens"] for r in billed if r.get("reasoning_tokens") is not None]
            if reasoning:
                cost["mean_reasoning_tokens"] = statistics.mean(reasoning)
            arm_out["reps"][str(rep)] = {
                "requests": len(every), "invalid_requests": len(every) - len(valid_rows),
                "latency": {"basis": "all_valid_requests", "n": len(lat), "p50_ms": nearest_rank(lat, .50),
                            "p95_ms": nearest_rank(lat, .95), "max_ms": max(lat) if lat else None,
                            f"over_{timeout_ms}ms": sum(x > timeout_ms for x in lat)},
                "order_flips": {"comparable": flags["order_flip_comparable"], "pairs": pairs, "flips": flips},
                "cost": cost,
            }
        per_case: dict = {}  # policy -> cid -> list of scored, over reps
        for policy in policies:
            name = policy["name"]
            pol_out = {"reps": {}}
            per_case[name] = {}
            for rep in reps:
                first = index.get((arm, rep, 0), {})
                entries = []
                for cid in order_ids:
                    if cid in first:
                        s = scored(policy, first[cid])
                        entries.append((by_case[cid], first[cid], s))
                        if s is not None:
                            per_case[name].setdefault(cid, []).append(s)
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
            seen = {cid for rep in reps for cid in index.get((arm, rep, 0), {})}
            accs = [pol_out["reps"][str(r)]["accuracy"]["rate"] for r in reps]
            waers = [pol_out["reps"][str(r)]["wrong_automatic_rate"]["rate"] for r in reps]
            eligible = [v for v in per_case[name].values() if len(v) >= 2]
            agree = sum(len({s["predicted"] for s in v}) == 1 for v in eligible)
            voted = {cid: _majority([s["correct"] for s in v]) for cid, v in per_case[name].items()}
            pol_out["across_reps"] = {
                "reps": len(reps),
                "accuracy": {"mean": statistics.mean(accs), "min": min(accs), "max": max(accs)},
                "wrong_automatic_rate": {"mean": statistics.mean(waers), "min": min(waers), "max": max(waers)},
                "per_case_agreement": {"cases": len(eligible), "agree": agree,
                                       "rate": (agree / len(eligible)) if eligible else None},
                "majority_vote": {"n": len(seen), "correct": sum(voted.values()),
                                  "accuracy": (sum(voted.values()) / len(seen)) if seen else None,
                                  "ci95": wilson(sum(voted.values()), len(seen))},
            }
            arm_out["policies"][name] = pol_out
        majority_by_arm[arm] = {
            "correct": {cid: _majority([s["correct"] for s in v]) for cid, v in per_case[primary].items()},
            "automatic_error": {cid: _majority([s["automatic_error"] for s in v]) for cid, v in per_case[primary].items()},
        }
        summary["arms"][arm] = arm_out

    pairwise = {"policy": primary, "basis": "order 0, per-case majority over reps", "contrasts": {}}
    for metric in ("correct", "automatic_error"):
        results = []
        for a, b in contrasts or []:
            if a not in majority_by_arm or b not in majority_by_arm:
                continue
            va, vb = majority_by_arm[a][metric], majority_by_arm[b][metric]
            ids = [cid for cid in order_ids if cid in va and cid in vb]
            only_a = sum(va[c] and not vb[c] for c in ids)
            only_b = sum(vb[c] and not va[c] for c in ids)
            diffs = [int(va[c]) - int(vb[c]) for c in ids]
            results.append({"a": a, "b": b, "n_pairs": len(ids), "a_only": only_a, "b_only": only_b,
                            "rate_a": (sum(va[c] for c in ids) / len(ids)) if ids else None,
                            "rate_b": (sum(vb[c] for c in ids) / len(ids)) if ids else None,
                            "diff": (sum(diffs) / len(diffs)) if diffs else None,
                            "diff_ci95": bootstrap_ci(diffs, B=bootstrap_b, seed=SEED),
                            "p": mcnemar_exact(only_a, only_b)})
        for r, adj in zip(results, holm([r["p"] for r in results])):
            r["p_holm"] = adj
        pairwise["contrasts"][metric] = results
    summary["pairwise"] = pairwise
    return summary
