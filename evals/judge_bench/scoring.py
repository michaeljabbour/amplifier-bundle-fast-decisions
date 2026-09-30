"""Scoring of one raw answer under a named, pre-declared decision policy.

predicted is ALWAYS argmax(probabilities): the bundle takes argmax and ignores
the API `choice` field (src/amplifier_fast_decisions/backends.py
_decision_from_answer). The single exception is the replay-only `study-0.75`
policy, which reproduces the first-pass harness and reads answer["choice"].
Scores are pure functions of (case, raw answer, elapsed_ms, policy), so a
summary can always be recomputed from the request log.
"""
from __future__ import annotations

import math
import re

TOL = 1e-9

# Deterministic and pre-declared: no per-case exceptions, no LLM judgement.
HOST_SIDE_EFFECT = re.compile(
    r"\b(buy|purchase|pay|refund|delete|remove|destroy|drop|publish|post|send|submit|"
    r"transfer|revoke|merge|deploy|approve|charge)\b", re.IGNORECASE)

POLICIES: dict[str, dict] = {
    # First-pass replay only: predicted = answer["choice"], threshold 0.75, no timeout.
    "study-0.75": {"name": "study-0.75", "kind": "study", "threshold": 0.75, "uses_stated_choice": True},
    # PRIMARY: the read-shortcut gate the bundle applies (0.90 and a 0.20 margin, 3 s timeout).
    "bundle-read-shortcut": {"name": "bundle-read-shortcut", "kind": "bundle", "min_p": 0.90,
                             "min_margin": 0.20, "timeout_ms": 3000, "uses_stated_choice": False},
    "bundle-cua": {"name": "bundle-cua", "kind": "bundle", "min_p": 0.75,
                   "min_margin": None, "timeout_ms": 3000, "uses_stated_choice": False},
}


def cutoff(t: float) -> dict:
    """Study-style certainty cutoff for threshold sweeps: argmax predicted, no timeout."""
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= 1:
        raise ValueError(f"cutoff must be a finite number in [0, 1], got {t!r}")
    return {"name": f"cutoff-{t:g}", "kind": "cutoff", "threshold": t, "uses_stated_choice": False,
            "sweep": True}


def with_host_guard(policy: dict) -> dict:
    """Force fallback when the chosen option's own description names a side effect."""
    return dict(policy, name=policy["name"] + "+host-guard", host_guard=True)


def with_noul_gate(policy: dict) -> dict:
    """Pre-declared intervention: a yes/no answer is automatic only at certainty >= the policy's min_p.
    Only bundle policies have a noul path without abstention; on study/cutoff policies it would be a no-op."""
    if policy["kind"] != "bundle":
        raise ValueError(f"+noul-gate is a no-op on {policy['name']!r}; it applies to bundle policies only")
    return dict(policy, name=policy["name"] + "+noul-gate", noul_gate=True)


MODIFIERS = {"+noul-gate": with_noul_gate, "+host-guard": with_host_guard}


def resolve_policy(name: str) -> dict:
    """`base[+noul-gate][+host-guard]`; modifiers apply in that fixed order."""
    base, applied = name, []
    for suffix in ("+host-guard", "+noul-gate"):
        if base.endswith(suffix):
            base, applied = base[:-len(suffix)], [suffix] + applied
    if base in POLICIES:
        policy = dict(POLICIES[base])
    elif base.startswith("cutoff-"):
        policy = cutoff(float(base[len("cutoff-"):]))
    else:
        raise KeyError(f"Unknown policy {name!r}")
    for suffix in applied:
        policy = MODIFIERS[suffix](policy)
    return policy


def _number(p) -> float:
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("Invalid probability")
    return float(p)


def validate_answer(case: dict, answer: dict) -> None:
    """Policy-independent validity (the first-pass rules); raises ValueError."""
    if case["kind"] == "search":
        _number(answer["noul"])
        return
    probabilities = answer["probabilities"]
    keys = set(case["payload"]["questions"]["decision"]["criteria"])
    if set(probabilities) != keys:
        raise ValueError("Invalid probabilities")
    for p in probabilities.values():
        _number(p)
    if not math.isclose(sum(probabilities.values()), 1, abs_tol=.01):
        raise ValueError("Invalid probabilities")


def argmax_choice(probabilities: dict) -> str:
    """The first key holding the maximum, in the answer's own dict order: exactly the bundle's
    max(probabilities, key=probabilities.get) (backends._decision_from_answer)."""
    return max(probabilities, key=probabilities.get)


def _fallback(policy: dict, is_choice: bool, predicted, certainty: float, margin: float | None,
              elapsed_ms: float) -> str | None:
    kind = policy["kind"]
    if kind == "bundle":
        # A timed-out call yields no answer in the bundle, so it outranks the rest.
        if elapsed_ms is not None and elapsed_ms > policy["timeout_ms"]:
            return "decision_timeout"
        if not is_choice:
            if policy.get("noul_gate") and certainty < policy["min_p"] - TOL:
                return "noul_gate"
            return None  # the bundle itself has no abstention for noul
        if predicted == "reason":
            return "model_abstained"
        if certainty < policy["min_p"] - TOL:
            return "selection_threshold"
        if policy.get("min_margin") is not None and margin < policy["min_margin"] - TOL:
            return "selection_threshold"
        return None
    if kind == "study":  # exactly laya_quality.score at threshold
        if is_choice and predicted == "reason":
            return "model_abstained"
        return None if certainty >= policy["threshold"] else "selection_threshold"
    if kind == "cutoff":
        if is_choice and predicted == "reason":
            return "model_abstained"
        return None if certainty >= policy["threshold"] - TOL else "selection_threshold"
    raise KeyError(f"Unknown policy kind {kind!r}")


def score(case: dict, answer: dict, elapsed_ms: float, policy: dict) -> dict:
    expected = case["expected"]
    if case["kind"] == "search":
        p = _number(answer["noul"])
        predicted = p >= .5
        certainty = max(p, 1 - p)
        brier = (p - float(expected)) ** 2
        margin, is_choice = None, False
    else:
        validate_answer(case, answer)
        probabilities = {k: float(v) for k, v in answer["probabilities"].items()}
        if policy.get("uses_stated_choice"):
            predicted = answer["choice"]
            if predicted not in probabilities:
                raise ValueError("Invalid choice")
        else:
            predicted = argmax_choice(probabilities)
        certainty = probabilities[predicted]
        others = [v for k, v in probabilities.items() if k != predicted]
        margin = certainty - max(others) if others else certainty
        brier = sum((p - float(k == expected)) ** 2 for k, p in probabilities.items()) / 2
        is_choice = True
    reason = _fallback(policy, is_choice, predicted, certainty, margin, elapsed_ms)
    if reason is None and policy.get("host_guard") and is_choice and predicted != "reason":
        described = case["payload"]["questions"]["decision"]["criteria"].get(predicted, "")
        if HOST_SIDE_EFFECT.search(described):
            reason = "host_guard"
    correct = predicted == expected
    automatic = reason is None
    return {"predicted": predicted, "correct": correct, "certainty": certainty, "brier": brier,
            "automatic": automatic, "automatic_error": automatic and not correct,
            "fallback_reason": reason}
