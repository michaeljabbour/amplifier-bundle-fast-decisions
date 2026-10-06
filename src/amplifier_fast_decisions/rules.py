"""Deterministic session-start rule helpers: the keyword intent classifier ``intent-kw-v1``.

``intent-kw-v1`` is the classifier frozen for the S1 preregistration (``evals/v3/rules.py`` on ``v3/program``, file
sha256 ``9ff0e82c58d11c94d64997330b883ca42ac3758563fb228bee4b95d9c5997c5a``). The regexes below are copied
unchanged; ``tests/test_rules.py`` compares them with that file when it is present.

It serves one purpose here: the task-type opt-out (``model_routing.keep_on_host``) when the session-start decider is
the rule R* and no judge model is asked. A first prompt only shows intent, so the mapping to a task type is a proxy:

    question  -> explain      (a read-only question; review and explain prompts look alike on turn 1)
    implement -> feature
    fix       -> bugfix
    other     -> other

``review`` is never produced (indistinguishable from ``explain`` at turn 1), so ``keep_on_host: [review, explain]``
keeps the question-shaped sessions on the host. Replayed on 135 scenario prompts (holdout-v3 + main-v1 + pilot-v1):
26 of 28 review/explain sessions are caught; 43 other read-only questions are caught too. A judge decider
(``start_policy: judge``) answers the task-type question itself and does not use this proxy.
"""
from __future__ import annotations

import re

INTENT_CLASSIFIER = "intent-kw-v1"
INTENTS = ("implement", "question", "fix", "other")
INTENT_TO_TASK_TYPE = {"question": "explain", "implement": "feature", "fix": "bugfix", "other": "other"}

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


def rule_task_type(prompt: str) -> str:
    """The task type ``keep_on_host`` sees when no judge is asked (one of ``contracts.TASK_TYPES``)."""
    return INTENT_TO_TASK_TYPE[classify_intent(prompt)]
