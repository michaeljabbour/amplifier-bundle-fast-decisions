"""OllamaBackend candidate path: prose first token -> chat prefill retry -> unavailable."""
from __future__ import annotations

import asyncio
import json
import math
import unittest
from types import SimpleNamespace

from amplifier_fast_decisions.contracts import Candidate, DecisionRequest
from amplifier_fast_decisions.local_backend import BackendUnavailable, OllamaBackend


def request():
    return DecisionRequest(
        state={"observations": [{"role": "user", "text": "Read README.md"}]},
        candidates=(Candidate("read", "Read README.md", "fast_workspace",
                              {"operation": "read", "path": "README.md"}),))


def reply(tokens, **extra):
    top = [{"token": t, "logprob": math.log(p)} for t, p in tokens]
    return {"model": "m", "done": True, "eval_count": 1, "prompt_eval_count": 7,
            "logprobs": [{"top_logprobs": top}], **extra}


class Client:
    """Scripted: first response for /api/generate, second for /api/chat."""

    def __init__(self, generate, chat=None):
        self.generate, self.chat, self.calls = generate, chat, []

    async def post(self, url, **kw):
        self.calls.append((url, kw["json"]))
        body = self.chat if url.endswith("/api/chat") else self.generate
        return SimpleNamespace(status_code=200, content=json.dumps(body).encode(), json=lambda: body)

    async def aclose(self):
        pass


def ask(client):
    return asyncio.run(OllamaBackend(model="m", client=client).ask(request()))


class CandidatePrefillTests(unittest.TestCase):
    def test_letter_first_token_needs_no_retry(self):
        client = Client(reply([("A", .9), ("Z", .05)]))
        result = ask(client)
        self.assertEqual(result.action.choice, "read")
        self.assertEqual(len(client.calls), 1)

    def test_abstain_letter_mass_is_not_mistaken_for_prose(self):
        client = Client(reply([("Z", .9), ("A", .05)]))
        result = ask(client)
        self.assertEqual(result.action.choice, "reason")
        self.assertEqual(len(client.calls), 1)

    def test_prose_first_token_retries_via_chat_prefill(self):
        client = Client(reply([("We", .95), ("A", .01)]),
                        reply([(" A", .8), (" Z", .15)]))
        result = ask(client)
        self.assertEqual(len(client.calls), 2)
        url, body = client.calls[1]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertEqual(body["messages"][-1], {"role": "assistant", "content": "Answer:"})
        self.assertEqual(body["options"]["num_predict"], 1)
        self.assertEqual(result.action.choice, "read")
        self.assertAlmostEqual(result.action.probabilities["read"], .8)
        self.assertAlmostEqual(result.action.probabilities["reason"], .2)

    def test_still_prose_after_prefill_is_unavailable_not_a_confident_abstain(self):
        client = Client(reply([("We", .95)]), reply([(" The", .9), (" A", .01)]))
        with self.assertRaises(BackendUnavailable):
            ask(client)
        self.assertEqual(len(client.calls), 2)

    def test_chat_failure_is_unavailable(self):
        client = Client(reply([("We", .95)]), {"model": "other", "done": True})
        with self.assertRaises(BackendUnavailable):
            ask(client)

    def test_malformed_prefill_tokens_raise_backend_unavailable(self):
        bad_tops = [
            [{"token": 5, "logprob": -1.0}],
            [{"token": "A"}],
            [{"token": "A", "logprob": "x"}],
            [{"token": "A", "logprob": True}],
            [{"token": "A", "logprob": float("nan")}],
            [{"token": "A", "logprob": 0.5}],
            ["A"],
        ]
        for top in bad_tops:
            with self.subTest(top=top):
                chat = {"model": "m", "done": True, "logprobs": [{"top_logprobs": top}]}
                with self.assertRaises(BackendUnavailable):
                    ask(Client(reply([("We", .95)]), chat))
        for logprobs in ([], ["x"], [{"top_logprobs": []}], [{"top_logprobs": "A"}], None):
            with self.subTest(logprobs=logprobs):
                chat = {"model": "m", "done": True, "logprobs": logprobs}
                with self.assertRaises(BackendUnavailable):
                    ask(Client(reply([("We", .95)]), chat))

    def test_warmup_posts_to_chat_endpoint(self):
        seen = []

        class Resp:
            def read(self):
                return b"{}"

        def fake_urlopen(req, timeout=None):
            seen.append(req.full_url)
            return Resp()

        from unittest import mock
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            asyncio.run(OllamaBackend(model="m", url="http://127.0.0.1:11434").warmup())
        self.assertEqual(seen, ["http://127.0.0.1:11434/api/chat"])


if __name__ == "__main__":
    unittest.main()
