"""Typed questions (choice / noul) on the local one-token backends. No network."""
from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from amplifier_fast_decisions.contracts import DecisionRequest, Question
from amplifier_fast_decisions.local_backend import (
    OllamaBackend, build_question_prompt, answer_from_top_logprobs, MIN_OPTION_MASS,
)
from amplifier_fast_decisions.backends import BackendUnavailable

CHOICE = Question(name="difficulty", type="choice", instructions="Simple or complex?",
                  criteria={"simple": "small fix", "complex": "large investigation"})
NOUL = Question(name="urgent", type="noul", instructions="Is it urgent?")


class FakeClient:
    """Answers letter A with p_first on the first (in-order) prompt and on the reversed prompt."""

    def __init__(self, model, p_a_forward, p_a_reverse):
        self.model, self.calls = model, []
        self.p = [p_a_forward, p_a_reverse]

    async def post(self, url, json):
        p_a = self.p[len(self.calls) % 2]
        self.calls.append(json)
        payload = {"model": self.model, "done": True, "eval_count": 1,
                   "logprobs": [{"top_logprobs": [{"token": "A", "logprob": math.log(p_a)},
                                                  {"token": "B", "logprob": math.log(1 - p_a)}]}]}
        return SimpleNamespace(status_code=200, content=b"{}", json=lambda: payload)

    async def aclose(self):
        pass


class PromptTests(unittest.TestCase):
    def test_letters_map_to_option_names_and_reverse(self):
        _, labels = build_question_prompt({"task": "x"}, CHOICE)
        self.assertEqual(labels, {"A": "simple", "B": "complex"})
        _, labels = build_question_prompt({"task": "x"}, CHOICE, reverse=True)
        self.assertEqual(labels, {"A": "complex", "B": "simple"})

    def test_score_questions_refused(self):
        with self.assertRaises(BackendUnavailable):
            build_question_prompt({}, Question(name="s", type="score", instructions="How?"))

    def test_non_letter_output_abstains(self):
        top = [{"token": "<think>", "logprob": math.log(0.95)}, {"token": "A", "logprob": math.log(0.05)}]
        self.assertLess(0.05, MIN_OPTION_MASS)
        with self.assertRaises(BackendUnavailable):
            answer_from_top_logprobs(CHOICE, top, {"A": "simple", "B": "complex"})


class OllamaQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_choice_is_permutation_debiased(self):
        # Always-"A" model: 0.9 on A in both orders -> perfectly position-biased -> 0.5/0.5 after debiasing.
        backend = OllamaBackend(model="m", client=FakeClient("m", 0.9, 0.9))
        result = await backend.ask(DecisionRequest(state={"task": "x"}, candidates=(), questions=(CHOICE,)))
        probs = result.answers["difficulty"].probabilities
        self.assertAlmostEqual(probs["simple"], 0.5)
        self.assertAlmostEqual(probs["complex"], 0.5)
        self.assertEqual(len(backend._client.calls), 2)  # forward + reversed option order

    async def test_choice_signal_survives_debiasing(self):
        # Forward: A(simple)=0.2 -> complex 0.8; reverse: A(complex)=0.8 -> complex 0.8.
        backend = OllamaBackend(model="m", client=FakeClient("m", 0.2, 0.8))
        result = await backend.ask(DecisionRequest(state={"task": "x"}, candidates=(), questions=(CHOICE,)))
        self.assertAlmostEqual(result.answers["difficulty"].probabilities["complex"], 0.8)

    async def test_noul(self):
        backend = OllamaBackend(model="m", client=FakeClient("m", 0.7, 0.3))
        result = await backend.ask(DecisionRequest(state={"t": 1}, candidates=(), questions=(NOUL,)))
        # forward A=true 0.7; reverse A=false 0.3 -> true 0.7
        self.assertAlmostEqual(result.answers["urgent"].noul, 0.7)


if __name__ == "__main__":
    unittest.main()
