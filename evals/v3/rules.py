"""Deterministic session-start rule deciders (A0 / S1 preregistration).

A rule maps decision-time features of a session (turn-1 prompt, starting workspace) to a tier: `cheap` (route the whole
session to the cheap model) or `host` (keep the host model). It sees only what the product sees at session start:

* `turn1_prompt_chars`  length of the first user prompt in characters
* `workspace_files`     file count of the starting workspace (the scope gate's input)
* `intent`              a keyword class of the first prompt from `classify_intent` (implement / question / fix / other)

A rule spec is plain JSON: ``{"host_if_any": [<condition>, ...], "scope_gate_max_workspace_files": 300}``; a condition is
``{"feature": ..., "op": ">"|"<"|"in", "value": ...}``. The session stays on the host if ANY condition holds or the scope
gate fires; otherwise it routes to cheap. The empty list is "always route" (subject to the scope gate).
"""
from __future__ import annotations

import re

INTENT_CLASSIFIER = "intent-kw-v1"
INTENTS = ("implement", "question", "fix", "other")

_IMPLEMENT = re.compile(r"\bimplement\b", re.IGNORECASE)
_QUESTION_START = re.compile(
    r"^\W*(explain|how|what|which|why|where|when|who|describe|give me|summari[sz]e|compare|list|tell me|walk me|"
    r"from|in|using|compute|following|read)\b", re.IGNORECASE)
_FIX = re.compile(r"\b(fix|bug|crash(?:es|ed)?|fails?|failing|raises?|broken|wrong|no longer|silently|loses|blows up|"
                  r"regression|corrupts?|incorrect|error)\b", re.IGNORECASE)
_NO_CHANGE = re.compile(r"\b(do not|don't) (change|modify|edit)\b", re.IGNORECASE)


def classify_intent(prompt: str) -> str:
    """Keyword intent of a first prompt. Order matters: implement > question-shaped > fix > any question > other."""
    text = (prompt or "").strip()
    if _IMPLEMENT.search(text):
        return "implement"
    if _QUESTION_START.search(text) or _NO_CHANGE.search(text):
        return "question"
    if _FIX.search(text):
        return "fix"
    if "?" in text:
        return "question"
    return "other"


def features(prompt: str, workspace_files: int) -> dict:
    return {"turn1_prompt_chars": len(prompt or ""), "workspace_files": int(workspace_files),
            "intent": classify_intent(prompt)}


def condition_holds(cond: dict, feats: dict) -> bool:
    v = feats[cond["feature"]]
    op = cond["op"]
    if op == ">":
        return v > cond["value"]
    if op == "<":
        return v < cond["value"]
    if op == "in":
        return v in cond["value"]
    raise ValueError(f"unknown op {op!r}")


def decide(rule: dict, feats: dict) -> str:
    """`cheap` or `host` for one session under `rule`."""
    gate = rule.get("scope_gate_max_workspace_files")
    if gate is not None and feats["workspace_files"] > gate:
        return "host"
    return "host" if any(condition_holds(c, feats) for c in rule.get("host_if_any", [])) else "cheap"


def complexity(rule: dict) -> int:
    """Occam size: one per numeric condition, one per listed intent."""
    return sum(len(c["value"]) if c["op"] == "in" else 1 for c in rule.get("host_if_any", []))


def describe(rule: dict) -> str:
    parts = []
    for c in rule.get("host_if_any", []):
        val = "{" + ",".join(c["value"]) + "}" if c["op"] == "in" else str(c["value"])
        parts.append(f"{c['feature']} {c['op']} {val}")
    return "host if " + " or ".join(parts) if parts else "always route"
