"""Native-form replay of real read-shortcut decisions (the trace-derived splits).

A trace case carries the exact request the bundle's DecisionService built
(`native.decision_request`: state + candidates) and the bench choice-question rendering
(`payload`). Each judge family is asked in the form the bundle itself uses for it:

* System One servers (Jev, Ollama /v1/systemone: nimble, tev1): POST `native.systemone_body`
  (`backends._build_questions`, with `model`) and read `answers["next_action"]`.
* OllamaBackend (qwen3): the real `OllamaBackend.ask(DecisionRequest)` candidate path
  (letter-coded prompt, "Z. None of the above" option, SLOW residual).
* Laya: the real `LayaBackend.ask(DecisionRequest)`.
* Chat models (GPT-6 Luna / Sol): no native form exists; the bench `payload` is used and the row
  is marked `form: adapted`.

Every native answer is normalized to {"type": "choice", "probabilities": {candidate ids +
"reason"}} (the bundle's abstain key `reason` is SLOW), so scoring.py works unchanged. Option order
pass 1 reverses the candidate order (and, for System One, the whole criteria mapping as the bench
does); the abstain option stays where each backend puts it.
"""
from __future__ import annotations

import json

NATIVE = "native"
ADAPTED = "adapted"
SLOW = "reason"  # amplifier_fast_decisions.contracts.SLOW


def reorder_native(native: dict, order: int) -> dict:
    """A deep copy of `native` with the option order of pass `order` (0 = as built, 1 = reversed)."""
    native = json.loads(json.dumps(native))
    if order:
        native["decision_request"]["candidates"] = list(reversed(native["decision_request"]["candidates"]))
        question = native["systemone_body"]["questions"]["next_action"]
        question["criteria"] = dict(reversed(list(question["criteria"].items())))
    return native


def decision_request(native: dict):
    """The bundle's DecisionRequest for this case (real contracts, no questions)."""
    from amplifier_fast_decisions.contracts import Candidate, DecisionRequest
    dr = native["decision_request"]
    return DecisionRequest(state=dr["state"], candidates=tuple(Candidate(**c) for c in dr["candidates"]),
                           questions=())


def systemone_request_body(native: dict, model: str | None) -> dict:
    """Key order state, model, questions: the body JevBackend._ask_urllib serializes."""
    body = native["systemone_body"]
    out = {"state": body["state"]}
    if model:
        out["model"] = model
    out["questions"] = body["questions"]
    return out


def systemone_answer(data: dict) -> dict:
    """Normalized decision from a System One response: answers['next_action'] -> choice answer."""
    answer = (data.get("answers") or {})["next_action"]
    if answer.get("type") != "choice":
        raise ValueError("next_action answer is not a choice")
    probabilities = dict(answer["probabilities"])
    decision = {"type": "choice", "probabilities": probabilities,
                "choice": max(probabilities, key=probabilities.get)}
    if answer.get("confidence") is not None:
        decision["vendor_confidence"] = answer["confidence"]  # recorded only; the bundle never gates on it
    return decision


def decision_answer(result) -> dict:
    """Normalized decision from a bundle DecisionResult (OllamaBackend / LayaBackend)."""
    probabilities = dict(result.action.probabilities)
    return {"type": "choice", "probabilities": probabilities, "choice": result.action.choice}


def patch_clause(case: dict, clause: str) -> dict:
    """A copy of `case` whose choice instructions (bench payload and System One next_action) carry `clause`."""
    case = json.loads(json.dumps(case))
    question = case["payload"]["questions"]["decision"]
    question["instructions"] = question["instructions"] + " " + clause
    next_action = case["native"]["systemone_body"]["questions"]["next_action"]
    next_action["instructions"] = next_action["instructions"] + " " + clause
    return case
