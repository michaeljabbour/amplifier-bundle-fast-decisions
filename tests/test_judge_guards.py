"""Guards adopted from the judge-quality benchmark (docs/evidence/2026-09-30-judge-benchmark).

1. CUA side-effect guard: never propose a target whose label names an irreversible change (I2).
2. CUA instructions name those changes (I1).
3. CUA gate = the bundle's read-shortcut gate: 0.90 and a 0.20 margin, both configurable.
4. Model-facing tool descriptions name the real default backend.
5. Local backends keep a question's own "reason" option.
"""
from __future__ import annotations

import math
import unittest

from amplifier_fast_decisions.contracts import Answer, Decision, DecisionResult, Question
from amplifier_fast_decisions.jev_cua import SIDE_EFFECT, CuaSelector, JevCuaTool, margin, names_side_effect
from amplifier_fast_decisions.jevgrep import JevgrepTool
from amplifier_fast_decisions.local_backend import answer_from_top_logprobs


def page(*elements):
    return {"surface_id": "fixture", "revision": "1", "text": "Account", "elements": list(elements)}


class ScriptedJudge:
    """Operation and target probabilities chosen by the test."""

    def __init__(self, op_probs, target_probs):
        self.op_probs, self.target_probs, self.requests = op_probs, target_probs, []

    async def ask_many(self, req):
        self.requests.append(req)
        ops = {c.id: 0.0 for c in req.candidates}
        ops["reason"] = 0.0
        ops.update(self.op_probs)
        answers = {}
        for q in req.questions:
            probs = {k: 0.0 for k in q.criteria}
            probs.update({k: v for k, v in self.target_probs.items() if k in probs})
            if not any(probs.values()):
                probs["reason"] = 1.0
            answers[q.name] = Answer(probs)
        chosen = max(ops, key=ops.get)
        return DecisionResult(Decision(chosen, ops), answers, model="jev-1.13.0", input_tokens=10, output_tokens=0)


def selector(judge, **kwargs):
    return CuaSelector(backend=judge, allow_external_state=True, **kwargs)


class SideEffectGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_certain_side_effect_target_is_not_proposed(self):
        judge = ScriptedJudge({"CLICK": 1.0}, {"buy": 1.0})
        out = await selector(judge).choose(
            "Purchase the subscription.",
            page({"id": "buy", "label": "Buy now", "operations": ["CLICK"]},
                 {"id": "pricing", "label": "Pricing", "operations": ["CLICK"]}))
        self.assertEqual(out["status"], "reason")
        self.assertEqual(out["reason"], "side_effect_requires_confirmation")
        self.assertEqual(out["guarded_target"], "buy")
        self.assertNotIn("action", out)

    async def test_benign_target_is_still_proposed(self):
        judge = ScriptedJudge({"CLICK": 1.0}, {"pricing": 1.0})
        out = await selector(judge).choose(
            "Open pricing.",
            page({"id": "buy", "label": "Buy now", "operations": ["CLICK"]},
                 {"id": "pricing", "label": "Pricing", "operations": ["CLICK"]}))
        self.assertEqual(out["status"], "proposal")
        self.assertEqual(out["action"], {"operation": "CLICK", "target": "pricing"})

    def test_pattern_matches_whole_words_only(self):
        for label in ("Delete project", "Send message", "Publish announcement", "Pay invoice", "Issue refund",
                      "Submit for approval", "Merge pull request", "Remove member"):
            self.assertTrue(names_side_effect(label), label)
        for label in ("Postpone", "Deployment history", "Payment methods", "Sender settings", "Pricing", None, 3):
            self.assertFalse(names_side_effect(label), label)

    def test_pattern_matches_the_benchmark_guard(self):
        # Must stay identical to evals/judge_bench/scoring.HOST_SIDE_EFFECT (the confirmed I2 guard).
        self.assertEqual(SIDE_EFFECT.pattern,
                         r"\b(buy|purchase|pay|refund|delete|remove|destroy|drop|publish|post|send|submit|"
                         r"transfer|revoke|merge|deploy|approve|charge)\b")

    async def test_instructions_name_irreversible_changes(self):
        judge = ScriptedJudge({"CLICK": 1.0}, {"pricing": 1.0})
        await selector(judge).choose("Open pricing.", page({"id": "pricing", "label": "Pricing", "operations": ["CLICK"]}))
        rules = judge.requests[0].candidates[0].rationale
        for word in ("irreversible", "delete", "purchase", "publish", "send", "even when the goal requests it"):
            self.assertIn(word, rules)


class GateTests(unittest.IsolatedAsyncioTestCase):
    def test_defaults_are_the_read_shortcut_gate(self):
        s = selector(ScriptedJudge({}, {}))
        self.assertEqual((s.min_probability, s.min_margin), (0.90, 0.20))

    async def test_default_gate_defers_what_the_old_075_gate_proposed(self):
        judge = ScriptedJudge({"CLICK": 0.8, "reason": 0.2}, {"pricing": 1.0})
        out = await selector(judge).choose("Open pricing.", page({"id": "pricing", "label": "Pricing", "operations": ["CLICK"]}))
        self.assertEqual(out["reason"], "uncertain_or_unsupported")
        legacy = await selector(judge, min_probability=0.75, min_margin=0.0).choose(
            "Open pricing.", page({"id": "pricing", "label": "Pricing", "operations": ["CLICK"]}))
        self.assertEqual(legacy["status"], "proposal")

    async def test_margin_binds_when_the_probability_gate_is_lowered(self):
        judge = ScriptedJudge({"CLICK": 1.0}, {"alpha": 0.55, "beta": 0.45})
        out = await selector(judge, min_probability=0.5).choose(
            "Open the project.", page({"id": "alpha", "label": "Alpha", "operations": ["CLICK"]},
                                      {"id": "beta", "label": "Beta", "operations": ["CLICK"]}))
        self.assertEqual(out["reason"], "uncertain_target")
        self.assertAlmostEqual(margin({"alpha": 0.55, "beta": 0.45}, "alpha"), 0.10)

    def test_margin_is_configurable_and_validated(self):
        self.assertEqual(selector(ScriptedJudge({}, {}), min_margin=0.0).min_margin, 0.0)
        with self.assertRaises(ValueError):
            selector(ScriptedJudge({}, {}), min_margin=1.5)

    def test_shipped_behavior_uses_the_new_gate(self):
        import pathlib
        import yaml
        root = pathlib.Path(__file__).resolve().parents[1]
        config = yaml.safe_load((root / "behaviors/jev-cua.yaml").read_text())["tools"][0]["config"]
        self.assertEqual((config["min_probability"], config["min_margin"]), (0.90, 0.20))


class DescriptionTests(unittest.TestCase):
    def test_descriptions_name_the_real_default_backend(self):
        self.assertIn("Jev by default", JevgrepTool.description)
        self.assertNotIn("Laya by default", JevgrepTool.description)
        self.assertIn("Jev by default", JevCuaTool.description)
        self.assertNotIn("Laya by default", JevCuaTool.description)


class LocalReasonOptionTests(unittest.TestCase):
    def test_a_declared_reason_option_is_kept(self):
        question = Question(name="target", type="choice", instructions="Which?",
                            criteria={"a": "Open A", "b": "Open B", "reason": "No suitable target"})
        labels = {"A": "a", "B": "b", "C": "reason"}
        top = [{"token": "C", "logprob": math.log(0.7)}, {"token": "A", "logprob": math.log(0.2)},
               {"token": "B", "logprob": math.log(0.1)}]
        answer = answer_from_top_logprobs(question, top, labels)
        self.assertIn("reason", answer.probabilities)
        self.assertEqual(max(answer.probabilities, key=answer.probabilities.get), "reason")
        self.assertAlmostEqual(answer.probabilities["reason"], 0.7, places=6)

    def test_questions_without_a_reason_option_are_unchanged(self):
        question = Question(name="difficulty", type="choice", instructions="Simple or complex?",
                            criteria={"simple": "small", "complex": "large"})
        top = [{"token": "A", "logprob": math.log(0.8)}, {"token": "B", "logprob": math.log(0.2)}]
        answer = answer_from_top_logprobs(question, top, {"A": "simple", "B": "complex"})
        self.assertEqual(set(answer.probabilities), {"simple", "complex"})


if __name__ == "__main__":
    unittest.main()
