"""Offline tests for the OpenAI Decisions API arm (luna-decisions). Mocked responses; no network."""
import asyncio
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from evals import judges  # noqa: E402
from evals.judge_bench import arms  # noqa: E402
from evals.judge_bench.scoring import validate_answer  # noqa: E402

CASE = {"id": "c1", "kind": "choice", "expected": "a", "screen": "dev",
        "payload": {"state": "{\"task\": \"read it\"}", "questions": {"decision": {
            "type": "choice", "instructions": "pick", "criteria": {"a": "A", "b": "B", "reason": "R"}}}}}
NOUL_CASE = {"id": "c2", "kind": "search", "expected": True, "screen": "dev",
             "payload": {"state": "{}", "questions": {"decision": {"type": "noul", "instructions": "ok?"}}}}
SCORE_PAYLOAD = {"state": "x", "questions": {"decision": {"type": "score", "instructions": "rate", "criteria": {
    "low": "bad", "high": "good"}}}}


class Resp:
    def __init__(self, data, status=200, headers=None, text=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
        self.text = text if text is not None else json.dumps(data)

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Client:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers, timeout))
        return self.response


def body(answer, tokens=120):
    return {"model": "gpt-6-luna", "answers": [answer],
            "usage": {"input_tokens": tokens, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                      "output_tokens": 0}}


def make():
    return arms.DecisionsApiArm("luna-decisions", "tok", "gpt-6-luna")


class DecisionsApiTests(unittest.TestCase):
    def test_choice_request_and_response(self):
        answer = {"type": "choice", "name": "decision", "choice": "a", "confidence": 0.9,
                  "probabilities": [{"value": "reason", "probability": 0.04}, {"value": "b", "probability": 0.01},
                                    {"value": "a", "probability": 0.95}]}
        client = Client(Resp(body(answer), headers={"openai-processing-ms": "412"}))
        out = asyncio.run(make().decide(client, CASE["payload"]))
        url, req, headers, timeout = client.calls[0]
        self.assertEqual(url, arms.OPENAI_DECISIONS_URL)
        self.assertEqual(req, {"model": "gpt-6-luna", "input": "{\"task\": \"read it\"}", "questions": [
            {"type": "choice", "name": "decision", "instructions": "pick", "choices": [
                {"value": "a", "description": "A"}, {"value": "b", "description": "B"},
                {"value": "reason", "description": "R"}]}]})
        self.assertEqual((headers["Authorization"], timeout), ("Bearer tok", 30.0))
        self.assertEqual(list(out["answer"]["probabilities"]), ["a", "b", "reason"])  # request order
        self.assertEqual(out["answer"]["probabilities"]["a"], 0.95)
        self.assertEqual((out["model"], out["input_tokens"], out["output_tokens"]), ("gpt-6-luna", 120, 0))
        self.assertEqual(out["timing"]["server_ms"], 412.0)
        validate_answer(CASE, out["answer"])

    def test_predicate_maps_to_noul(self):
        client = Client(Resp(body({"type": "predicate", "name": "decision", "probability": 0.83})))
        out = asyncio.run(make().decide(client, NOUL_CASE["payload"]))
        self.assertEqual(client.calls[0][1]["questions"], [{"type": "predicate", "name": "decision",
                                                           "instructions": "ok?"}])
        self.assertEqual(out["answer"], {"type": "noul", "noul": 0.83})
        validate_answer(NOUL_CASE, out["answer"])

    def test_score_levels_and_response(self):
        answer = {"type": "score", "name": "decision", "score": 0.8, "confidence": 0.7,
                  "probabilities": [{"value": 0, "label": "low", "probability": 0.2},
                                    {"value": 1, "label": "high", "probability": 0.8}]}
        client = Client(Resp(body(answer)))
        out = asyncio.run(make().decide(client, SCORE_PAYLOAD))
        self.assertEqual(client.calls[0][1]["questions"][0]["levels"],
                         [{"label": "low", "description": "bad"}, {"label": "high", "description": "good"}])
        self.assertEqual(out["answer"]["score"], 0.8)
        self.assertEqual(out["answer"]["probabilities"], {"low": 0.2, "high": 0.8})

    def test_object_valued_criteria_are_serialized_as_text(self):
        payload = {"state": "{}", "questions": {"decision": {"type": "choice", "instructions": "i", "criteria": {
            "r1": {"tool": "read", "path": "x"}, "reason": "R"}}}}
        req = make().request_body(payload)
        self.assertEqual(req["questions"][0]["choices"][0],
                         {"value": "r1", "description": json.dumps({"tool": "read", "path": "x"})})

    def test_http_error_is_invalid_with_message(self):
        resp = Resp({"error": {"message": "Invalid model", "type": "invalid_request_error"}}, status=400)
        with self.assertRaisesRegex(arms.ArmParseError, "HTTP 400: Invalid model") as cm:
            asyncio.run(make().decide(Client(resp), CASE["payload"]))
        self.assertEqual(cm.exception.http_status, 400)

    def test_mismatched_choices_are_invalid_and_usage_is_kept(self):
        answer = {"type": "choice", "name": "decision", "choice": "a",
                  "probabilities": [{"value": "a", "probability": 1.0}]}
        with self.assertRaisesRegex(arms.ArmParseError, "do not match") as cm:
            asyncio.run(make().decide(Client(Resp(body(answer, tokens=77))), CASE["payload"]))
        self.assertEqual(cm.exception.usage, (77, 0))  # billed even though unusable

    def test_wrong_answer_type_and_missing_key(self):
        wrong = body({"type": "predicate", "name": "decision", "probability": 0.5})
        with self.assertRaisesRegex(arms.ArmParseError, "expected a choice"):
            asyncio.run(make().decide(Client(Resp(wrong)), CASE["payload"]))
        with self.assertRaises(arms.ArmUnavailable):
            asyncio.run(arms.DecisionsApiArm("x", None, "m").decide(Client(Resp({})), CASE["payload"]))

    def test_build_arm_and_pricing_from_judges_yaml(self):
        cfg = judges.load_config()
        spec = cfg["arms"]["luna-decisions"]
        arm = arms.build_arm(spec, cfg["arms"], env={"OPENAI_API_KEY": "k"})
        self.assertIsInstance(arm, arms.DecisionsApiArm)
        self.assertEqual((arm.model, arm.timeout_s), ("gpt-6-luna", 30.0))
        self.assertAlmostEqual(judges.request_cost("luna-decisions", cfg["arms"], 1_000_000, 0), 0.10)
        with self.assertRaises(arms.ArmUnavailable):
            arms.build_arm(spec, cfg["arms"], env={})

    def test_late_answer_is_scored_as_decision_timeout(self):
        from evals.judge_bench import scoring
        answer = {"type": "choice", "probabilities": {"a": .97, "b": .02, "reason": .01}}
        policy = scoring.resolve_policy("bundle-read-shortcut")
        self.assertIsNone(scoring.score(CASE, answer, 2900, policy)["fallback_reason"])
        self.assertEqual(scoring.score(CASE, answer, 5200, policy)["fallback_reason"], "decision_timeout")


if __name__ == "__main__":
    unittest.main()
