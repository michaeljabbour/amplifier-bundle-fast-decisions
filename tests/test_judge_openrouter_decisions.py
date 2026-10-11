"""Offline tests for the Microsoft Decision 1 arm (OpenRouter Decisions API). Mocked responses; no network."""
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
from evals.judge_bench import arms, scoring  # noqa: E402
from evals.judge_bench.scoring import validate_answer  # noqa: E402

CASE = {"id": "c1", "kind": "choice", "expected": "a", "screen": "dev",
        "payload": {"state": "{\"task\": \"read it\"}", "questions": {"decision": {
            "type": "choice", "instructions": "pick", "criteria": {"a": "A", "b": "B", "reason": "R"}}}}}
NOUL = {"state": "{}", "questions": {"decision": {"type": "noul", "instructions": "ok?"}}}
SCORE = {"state": "x", "questions": {"decision": {"type": "score", "instructions": "rate",
                                                  "criteria": ["bad", "good"]}}}


class Resp:
    def __init__(self, data, status=200, headers=None, text=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
        self.text = text if text is not None else json.dumps(data)

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self.data


class Client:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers, timeout))
        return self.response


def body(answer, usage=None):
    return {"model": "microsoft/microsoft-decision-1", "answers": {"decision": answer},
            "usage": usage or {"prompt_tokens": 120, "completion_tokens": 0}}


def make():
    return arms.OpenRouterDecisionsArm("microsoft-decision-1", "tok", "microsoft/microsoft-decision-1")


def ask(payload, response):
    client = Client(response)
    return client, asyncio.run(make().decide(client, payload))


class OpenRouterDecisionsTests(unittest.TestCase):
    def test_choice_request_and_dict_probabilities(self):
        answer = {"type": "choice", "choice": "a", "probabilities": {"reason": 0.04, "b": 0.01, "a": 0.95}}
        client, out = ask(CASE["payload"], Resp(body(answer), headers={"x-processing-ms": "310", "x-other": "1",
                                                                        "openrouter-request-id": "r1"}))
        url, req, headers, timeout = client.calls[0]
        self.assertEqual(url, arms.OPENROUTER_DECISIONS_URL)
        self.assertEqual(req, {"model": "microsoft/microsoft-decision-1", "state": "{\"task\": \"read it\"}",
                               "questions": {"decision": {"type": "choice", "instructions": "pick",
                                                          "criteria": {"a": "A", "b": "B", "reason": "R"}}}})
        self.assertEqual((headers["Authorization"], headers["Content-Type"], headers["X-Title"], timeout),
                         ("Bearer tok", "application/json", "fast-decisions-benchmark", 30.0))
        self.assertEqual(list(out["answer"]["probabilities"]), ["a", "b", "reason"])  # request order
        self.assertEqual((out["input_tokens"], out["output_tokens"]), (120, 0))
        self.assertEqual(out["timing"]["server_ms"], 310.0)
        self.assertEqual(out["timing"]["headers"], {"x-processing-ms": "310", "openrouter-request-id": "r1"})
        validate_answer(CASE, out["answer"])

    def test_choice_list_probabilities_of_objects_and_bare_numbers(self):
        listed = {"type": "choice", "choice": "a", "probabilities": [
            {"value": "reason", "probability": 0.04}, {"value": "b", "probability": 0.01},
            {"value": "a", "probability": 0.95}]}
        self.assertEqual(ask(CASE["payload"], Resp(body(listed)))[1]["answer"]["probabilities"],
                         {"a": 0.95, "b": 0.01, "reason": 0.04})
        bare = {"type": "choice", "choice": "a", "probabilities": [0.95, 0.01, 0.04]}  # criteria order
        self.assertEqual(ask(CASE["payload"], Resp(body(bare)))[1]["answer"]["probabilities"],
                         {"a": 0.95, "b": 0.01, "reason": 0.04})

    def test_noul(self):
        client, out = ask(NOUL, Resp(body({"type": "noul", "noul": 0.83})))
        self.assertEqual(client.calls[0][1]["questions"], {"decision": {"type": "noul", "instructions": "ok?"}})
        self.assertEqual(out["answer"], {"type": "noul", "noul": 0.83})
        validate_answer({"kind": "search", "expected": True, "payload": NOUL}, out["answer"])

    def test_noul_criteria_pass_through_when_configured(self):
        arm = arms.OpenRouterDecisionsArm("m", "t", "m", noul_criteria={"true": "yes", "false": "no"})
        self.assertEqual(arm.request_body(NOUL)["questions"]["decision"]["criteria"], {"true": "yes", "false": "no"})

    def test_score_with_dict_and_list_probabilities(self):
        client, out = ask(SCORE, Resp(body({"type": "score", "score": 0.8, "probabilities": [0.2, 0.8]})))
        self.assertEqual(client.calls[0][1]["questions"]["decision"]["criteria"], ["bad", "good"])
        self.assertEqual((out["answer"]["score"], out["answer"]["probabilities"]), (0.8, {"0": 0.2, "1": 0.8}))
        out = ask(SCORE, Resp(body({"type": "score", "score": 1, "probabilities": {"0": 0.1, "1": 0.9}})))[1]
        self.assertEqual(out["answer"]["probabilities"], {"0": 0.1, "1": 0.9})

    def test_object_valued_choice_criteria_are_text(self):
        payload = {"state": "{}", "questions": {"decision": {"type": "choice", "instructions": "i", "criteria": {
            "r1": {"tool": "read", "path": "x"}, "reason": "R"}}}}
        crit = make().request_body(payload)["questions"]["decision"]["criteria"]
        self.assertEqual(crit["r1"], json.dumps({"tool": "read", "path": "x"}))

    def test_usage_and_reported_cost_are_recorded(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 0, "cost": 0.000042}
        out = ask(NOUL, Resp(body({"type": "noul", "noul": 0.5}, usage)))[1]
        self.assertEqual((out["input_tokens"], out["reported_cost_usd"]), (1000, 0.000042))
        self.assertAlmostEqual(judges.request_cost("microsoft-decision-1", judges.load_config()["arms"], 1_000_000, 0),
                               0.042)
        self.assertIsNone(ask(NOUL, Resp(body({"type": "noul", "noul": 0.5})))[1]["reported_cost_usd"])

    def test_http_error_is_invalid_with_message(self):
        resp = Resp({"error": {"message": "bad model"}}, status=400)
        with self.assertRaisesRegex(arms.ArmParseError, "HTTP 400: bad model") as cm:
            ask(CASE["payload"], resp)
        self.assertEqual(cm.exception.http_status, 400)

    def test_404_all_providers_ignored_is_an_account_routing_block(self):
        resp = Resp({"error": {"message": "All providers have been ignored for this request", "code": 404}}, status=404)
        with self.assertRaises(arms.ArmParseError) as cm:
            ask(CASE["payload"], resp)
        self.assertTrue(str(cm.exception).startswith("ACCOUNT_ROUTING_BLOCK: HTTP 404"))
        self.assertIn("not a model failure", str(cm.exception))
        other = Resp({"error": {"message": "no such model"}}, status=404)
        with self.assertRaisesRegex(arms.ArmParseError, "^HTTP 404: no such model"):
            ask(CASE["payload"], other)

    def test_unusable_bodies_are_invalid_and_usage_is_kept(self):
        wrong = body({"type": "noul", "noul": 0.5}, {"prompt_tokens": 77, "completion_tokens": 0})
        with self.assertRaisesRegex(arms.ArmParseError, "expected a choice") as cm:
            ask(CASE["payload"], Resp(wrong))
        self.assertEqual(cm.exception.usage, (77, 0))
        mismatch = body({"type": "choice", "choice": "a", "probabilities": {"a": 1.0}})
        with self.assertRaisesRegex(arms.ArmParseError, "do not match"):
            ask(CASE["payload"], Resp(mismatch))
        with self.assertRaisesRegex(arms.ArmParseError, "unrecognized shape"):
            ask(CASE["payload"], Resp(body({"type": "choice", "choice": "a", "probabilities": "x"})))
        with self.assertRaises(arms.ArmUnavailable):
            asyncio.run(arms.OpenRouterDecisionsArm("x", None, "m").decide(Client(Resp({})), CASE["payload"]))

    def test_build_arm_from_judges_yaml(self):
        cfg = judges.load_config()
        spec = cfg["arms"]["microsoft-decision-1"]
        arm = arms.build_arm(spec, cfg["arms"], env={"OPENROUTER_MS_DECISIONS_API_KEY": "k"})
        self.assertIsInstance(arm, arms.OpenRouterDecisionsArm)
        self.assertEqual((arm.model, arm.url, arm.timeout_s), ("microsoft/microsoft-decision-1",
                                                               "https://openrouter.ai/api/alpha/decisions", 30.0))
        self.assertIs(spec["local"], False)
        self.assertIn(["jev-1.13", "microsoft-decision-1"], cfg["contrasts"])
        with self.assertRaises(arms.ArmUnavailable):
            arms.build_arm(spec, cfg["arms"], env={})

    def test_late_answer_is_scored_as_decision_timeout(self):
        answer = {"type": "choice", "probabilities": {"a": .97, "b": .02, "reason": .01}}
        policy = scoring.resolve_policy("bundle-read-shortcut")
        self.assertIsNone(scoring.score(CASE, answer, 2900, policy)["fallback_reason"])
        self.assertEqual(scoring.score(CASE, answer, 5200, policy)["fallback_reason"], "decision_timeout")


if __name__ == "__main__":
    unittest.main()
