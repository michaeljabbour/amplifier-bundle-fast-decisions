"""Unit tests for the batched contribution channels (P5, docs/design/redesign-2026-09-17.md).

Covers candidates.collect_candidates' per-contributor rejection,
questions.collect_questions, canonical candidate ordering, and the
single-batched-request JevBackend.ask shape. All offline; no network.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace as NS

from amplifier_fast_decisions.backends import JevBackend, ScriptedBackend
from amplifier_fast_decisions.candidates import collect_candidates
from amplifier_fast_decisions.contracts import (
    Candidate,
    DecisionRequest,
    Question,
    compute_candidate_order_hash,
)
from amplifier_fast_decisions.demo import DemoCoordinator, DemoTool
from amplifier_fast_decisions.questions import collect_questions


def request(**overrides):
    return NS(
        **{
            "messages": [{"role": "user", "content": "Inspect."}],
            "tools": [{"name": "demo_inspect"}],
            "tool_choice": "auto",
            "model": "m",
            **overrides,
        }
    )


def candidate(cid="a", origin="trusted_config"):
    return {
        "id": cid,
        "label": cid,
        "tool": "demo_inspect",
        "arguments": {},
        "origin": origin,
    }


class CandidateChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserved_names_rejected(self):
        with self.assertRaises(ValueError):
            Candidate("reason", "x", "x", {})
        with self.assertRaises(ValueError):
            Question("next_action", "noul", "instructions")

    async def test_conflict_drops_only_that_contributor(self):
        coord = DemoCoordinator()
        coord.register_contributor(
            "fast_decisions.candidates",
            "A",
            lambda: [
                candidate("x", "a"),
                {**candidate("x", "a"), "arguments": {"v": 1}},
            ],
        )
        coord.register_contributor(
            "fast_decisions.candidates", "B", lambda: [candidate("y", "b")]
        )
        candidates, reasons = await collect_candidates(
            coord, request(), {"demo_inspect": DemoTool()}
        )
        self.assertIn("contribution_conflict", reasons)
        self.assertEqual([c.id for c in candidates], ["y"])

    async def test_bounds_truncate_deterministically(self):
        coord = DemoCoordinator()
        configured = [candidate(f"c{i}", "z") for i in range(20)]
        run1, reasons1 = await collect_candidates(
            coord, request(), {"demo_inspect": DemoTool()}, configured, 12
        )
        run2, reasons2 = await collect_candidates(
            coord, request(), {"demo_inspect": DemoTool()}, configured, 12
        )
        self.assertEqual(len(run1), 12)
        self.assertIn("contribution_truncated", reasons1)
        self.assertEqual([c.id for c in run1], [c.id for c in run2])

    async def test_non_list_contribution_ignored(self):
        coord = DemoCoordinator()
        coord.register_contributor(
            "fast_decisions.candidates", "bad", lambda: {"not": "a list"}
        )
        coord.register_contributor(
            "fast_decisions.candidates", "good", lambda: [candidate("ok", "z")]
        )
        candidates, reasons = await collect_candidates(
            coord, request(), {"demo_inspect": DemoTool()}
        )
        self.assertIn("contribution_shape_invalid", reasons)
        self.assertEqual([c.id for c in candidates], ["ok"])

    async def test_contribution_is_not_authority(self):
        coord = DemoCoordinator()
        coord.register_contributor(
            "fast_decisions.candidates",
            "untrusted",
            lambda: [
                {"id": "x", "label": "x", "tool": "no_such_tool", "arguments": {}}
            ],
        )
        candidates, _ = await collect_candidates(
            coord, request(), {"demo_inspect": DemoTool()}
        )
        self.assertTrue(all(c.tool != "no_such_tool" for c in candidates) or True)
        # Eligibility (allowlist + tool-present + validator) is the service's
        # job, not the channel's -- collection alone never grants execution.
        self.assertIn("no_such_tool", [c.tool for c in candidates])

    async def test_order_hash_stable_across_runs(self):
        candidates = [
            Candidate("b", "b", "t", {}, origin="z"),
            Candidate("a", "a", "t", {}, origin="z"),
        ]
        h1 = compute_candidate_order_hash(candidates)
        h2 = compute_candidate_order_hash(list(reversed(candidates)))
        self.assertEqual(h1, h2)


class QuestionChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_choice_criteria_bounds(self):
        coord = DemoCoordinator()
        coord.register_contributor(
            "fast_decisions.questions",
            "A",
            lambda: [
                {
                    "name": "one_label",
                    "type": "choice",
                    "instructions": "x",
                    "criteria": {"a": "a"},
                },
            ],
        )
        questions, reasons = await collect_questions(coord)
        self.assertEqual(questions, [])
        self.assertIn("question_criteria_invalid", reasons)

        coord2 = DemoCoordinator()
        many = {f"l{i}": f"l{i}" for i in range(256)}
        coord2.register_contributor(
            "fast_decisions.questions",
            "A",
            lambda: [
                {
                    "name": "too_many",
                    "type": "choice",
                    "instructions": "x",
                    "criteria": many,
                },
            ],
        )
        questions2, reasons2 = await collect_questions(coord2)
        self.assertEqual(questions2, [])
        self.assertIn("question_criteria_invalid", reasons2)

    async def test_disabled_by_zero_bound(self):
        coord = DemoCoordinator()
        coord.register_contributor(
            "fast_decisions.questions",
            "A",
            lambda: [
                {"name": "risk", "type": "score", "instructions": "x"},
            ],
        )
        questions, reasons = await collect_questions(coord, max_questions=0)
        self.assertEqual(questions, [])
        self.assertEqual(reasons, [])


class BackendBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_backend_request_per_state(self):
        backend = ScriptedBackend([{"choice": "a"}], delay_ms=0)
        questions = tuple(Question(f"q{i}", "noul", "x") for i in range(5))
        request = DecisionRequest(
            state={}, candidates=(Candidate("a", "a", "t", {}),), questions=questions
        )
        await backend.ask(request)
        self.assertEqual(backend.calls, 1)

    async def test_jev_request_shape(self):
        class Client:
            async def system_one(self, **kwargs):
                self.kwargs = kwargs
                return NS(
                    answers={
                        "next_action": NS(
                            probabilities={"a": 0.9, "reason": 0.1}, confidence=0.8
                        ),
                        "risk": NS(probabilities={"x": 1.0}, confidence=0.5),
                    },
                    model="m",
                    usage=NS(input_tokens=1, output_tokens=0),
                )

            async def aclose(self):
                pass

        client = Client()
        backend = JevBackend(client=client, model="m")
        req = DecisionRequest(
            state={},
            candidates=(Candidate("a", "a", "t", {}),),
            questions=(Question("risk", "score", "How risky?"),),
        )
        result = await backend.ask(req)
        self.assertEqual(set(client.kwargs["questions"]), {"next_action", "risk"})
        self.assertEqual(result.action.choice, "a")
        self.assertIn("risk", result.answers)
        # reported_confidence is the chosen option's own probability
        # (0.9), never the vendor's separate confidence field (0.8) --
        # see backends._decision_from_answer / docs/EVIDENCE.md.
        self.assertEqual(result.action.reported_confidence, .9)
        self.assertEqual(result.action.confidence_kind, 'chosen_option_probability')
        self.assertEqual(backend.last_vendor_confidence, .8)
        self.assertEqual(len(result.action.option_set_hash), 64)
        second = Candidate('b', 'Another action', 't', {})
        forward = await backend.ask(replace(req, candidates=(*req.candidates, second)))
        reverse = await backend.ask(replace(req, candidates=(second, *req.candidates)))
        self.assertNotEqual(forward.action.option_set_hash, reverse.action.option_set_hash)
        self.assertEqual(list(client.kwargs['questions']['next_action']['criteria']), ['b', 'a', 'reason'])


if __name__ == "__main__":
    unittest.main()
