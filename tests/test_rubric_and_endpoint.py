"""Rubric scoring over Jev noul questions, and JevBackend pointed at another
Jev System One-compatible server. A local http.server stands in for the
endpoint; no real API is called."""

from __future__ import annotations

import asyncio
import http.server
import json
import math
import os
import threading
import unittest
from typing import ClassVar
from unittest import mock

from amplifier_fast_decisions import backends, rubric
from amplifier_fast_decisions.backends import BackendUnavailable, JevBackend
from amplifier_fast_decisions.contracts import SLOW, Answer, DecisionRequest, DecisionResult


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        answers = {"next_action": {"type": "choice", "probabilities": {SLOW: 1.0}}}
        for name, q in body["questions"].items():
            if q["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 0.25 if "fail" in q["instructions"] else 0.9}
        payload = json.dumps({"model": body.get("model"), "answers": answers, "usage": {}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class JevCompatibleEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.seen.clear()

    def _ask(self, backend):
        request = DecisionRequest(state={"task": "x"}, candidates=())

        async def run():
            try:
                return await backend.ask(request)
            finally:
                await backend.close()

        return asyncio.run(run())

    def test_url_and_key_env_route_to_the_configured_server(self):
        env = {"MY_URL": self.url, "MY_KEY": "k-123"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("TYPESAFE_API_KEY", None)
            backend = JevBackend(model="other-model", base_url_env="MY_URL", api_key_env="MY_KEY",
                                 label="Other scorer", timeout_ms=5000)
            result = self._ask(backend)
        self.assertEqual(result.model, "other-model")
        self.assertEqual(_Handler.seen[0]["path"], "/v1/systemone")
        self.assertEqual(_Handler.seen[0]["auth"], "Bearer k-123")
        self.assertEqual(backend.last_transport, "urllib")
        self.assertEqual(backend.label, "Other scorer")

    def test_configured_endpoint_skips_the_sdk_even_when_installed(self):
        with mock.patch.dict(os.environ, {"MY_KEY": "k"}), mock.patch.object(backends, "_sdk_available", return_value=True):
            backend = JevBackend(base_url=self.url, api_key_env="MY_KEY", timeout_ms=5000)
            self._ask(backend)
        self.assertEqual(backend.last_transport, "urllib")

    def test_missing_url_env_is_unavailable_not_a_crash(self):
        with mock.patch.dict(os.environ, {"MY_KEY": "k"}):
            os.environ.pop("MISSING_URL", None)
            backend = JevBackend(base_url_env="MISSING_URL", api_key_env="MY_KEY")
            with self.assertRaises(BackendUnavailable):
                self._ask(backend)

    def test_missing_custom_key_is_unavailable(self):
        os.environ.pop("NO_SUCH_KEY", None)
        backend = JevBackend(base_url=self.url, api_key_env="NO_SUCH_KEY")
        with self.assertRaisesRegex(BackendUnavailable, "NO_SUCH_KEY"):
            self._ask(backend)

    def test_default_backend_keeps_typesafe_env(self):
        backend = JevBackend()
        self.assertEqual(backend.api_key_env, "TYPESAFE_API_KEY")
        self.assertFalse(backend._endpoint_override)
        self.assertIsNone(backend.label)

    def test_rubric_end_to_end_over_http(self):
        with mock.patch.dict(os.environ, {"MY_KEY": "k"}):
            backend = JevBackend(base_url=self.url, api_key_env="MY_KEY", timeout_ms=5000)

            async def run():
                try:
                    return await rubric.score(backend, {
                        "scoring_spec": [{"question": "Is it good?", "label": "good"},
                                         {"question": "Does it fail?", "label": "fails", "weight": 3}],
                        "llm_input": "in", "llm_output": "out"})
                finally:
                    await backend.close()

            out = asyncio.run(run())
        self.assertEqual(out["question_scores"], {"good": 0.9, "fails": 0.25})
        expected = math.exp((math.log(0.9) + 3 * math.log(0.25)) / 4)
        self.assertAlmostEqual(out["total_score"], round(expected, 4))
        sent = _Handler.seen[0]["body"]
        self.assertEqual(sent["state"], {"llm_input": "in", "llm_output": "out"})
        self.assertEqual(sorted(q["type"] for q in sent["questions"].values()), ["choice", "noul", "noul"])


class _FakeBackend:
    def __init__(self, values):
        self.values = values

    async def ask(self, request):
        answers = {q.name: Answer(probabilities={}, confidence=None, noul=v)
                   for q, v in zip(request.questions, self.values)}
        return DecisionResult(action=None, answers=answers, model="fake", input_tokens=None,
                              output_tokens=None, synthetic=False)


class RubricTests(unittest.TestCase):
    def test_aggregations(self):
        self.assertAlmostEqual(rubric.aggregate([1.0, 0.25], [1, 1], "arithmetic_mean"), 0.625)
        self.assertAlmostEqual(rubric.aggregate([1.0, 0.25], [1, 1], "geometric_mean"), 0.5)
        self.assertAlmostEqual(rubric.aggregate([1.0, 0.25], [1, 1], "harmonic_mean"), 0.4)
        self.assertGreater(rubric.aggregate([0.0, 1.0], [1, 1], "geometric_mean"), 0.0)
        with self.assertRaises(ValueError):
            rubric.aggregate([1.0], [1], "median")

    def test_weight_makes_one_failure_dominate(self):
        # One clearly failed criterion weighted 3 against three passes.
        total = rubric.aggregate([0.95, 0.95, 0.95, 0.09], [1, 1, 1, 3], "geometric_mean")
        self.assertLess(total, 0.35)

    def test_spec_validation(self):
        for bad in ([], None, [{"question": ""}], [{"question": "a", "weight": 0}],
                    [{"question": "a", "label": "x"}, {"question": "b", "label": "x"}]):
            with self.assertRaises(ValueError):
                rubric.parse_spec(bad)
        items = rubric.parse_spec([{"question": "Is it polite?"}])
        self.assertEqual(items[0].label, "Is it polite?")

    def test_question_names_are_valid_and_unique(self):
        spec = [{"question": "q", "label": "9 Same label!"}, {"question": "q", "label": "9 same label"}]
        out = asyncio.run(rubric.score(_FakeBackend([0.5, 0.7]), {"scoring_spec": spec, "llm_input": "", "llm_output": ""}))
        self.assertEqual(out["question_scores"], {"9 Same label!": 0.5, "9 same label": 0.7})

    def test_missing_score_is_an_error_and_batch_continues(self):
        good = {"scoring_spec": [{"question": "q"}], "llm_input": "", "llm_output": ""}
        out = asyncio.run(rubric.score_many(_FakeBackend([None]), [good]))
        self.assertIn("error", out[0])
        out = asyncio.run(rubric.score_many(_FakeBackend([0.8]), [good, {"scoring_spec": []}]))
        self.assertEqual(out[0]["total_score"], 0.8)
        self.assertIn("error", out[1])


class ObserverLabelTests(unittest.TestCase):
    def test_backend_label_is_bounded_and_optional(self):
        from amplifier_fast_decisions.observer import _backend_label

        class B:
            label = "  Other scorer  "
        self.assertEqual(_backend_label(B()), "Other scorer")
        B.label = "x" * 100
        self.assertEqual(len(_backend_label(B())), 64)
        B.label = "   "
        self.assertIsNone(_backend_label(B()))
        self.assertIsNone(_backend_label(object()))


if __name__ == "__main__":
    unittest.main()


class SessionContextTests(unittest.TestCase):
    def test_harness_from_executable_name(self):
        from amplifier_fast_decisions import observer
        with mock.patch.object(observer.sys, "argv", ["/Users/x/.local/bin/amplifier-tui"]):
            self.assertEqual(observer.harness_name(), "Amplifier TUI")
        with mock.patch.object(observer.sys, "argv", ["/opt/bin/python3", "-m", "x"]):
            self.assertEqual(observer.harness_name(), "Amplifier")
        self.assertEqual(observer.harness_name({"harness": "Studio"}), "Studio")

    def test_repo_context_reads_git_without_paths(self):
        import tempfile
        from pathlib import Path
        from amplifier_fast_decisions.observer import repo_context
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "my-repo"
            (root / ".git").mkdir(parents=True)
            (root / ".git" / "HEAD").write_text("ref: refs/heads/feature/x\n")
            deep = root / "src" / "pkg" / "inner"
            deep.mkdir(parents=True)
            info = repo_context(deep)
            self.assertEqual(info, {"repo": "my-repo", "subdir": "src/pkg", "branch": "feature/x"})
            self.assertNotIn(d, str(info))
            self.assertEqual(repo_context(Path(d)), {} if not (Path(d) / ".git").exists() else repo_context(Path(d)))


class SessionWorkingDirTests(unittest.TestCase):
    def test_scope_gate_reads_the_session_working_dir(self):
        from types import SimpleNamespace
        from amplifier_fast_decisions.orchestrator import session_working_dir
        coord = SimpleNamespace(get_capability=lambda name: "/work/big-repo" if name == "session.working_dir" else None)
        self.assertEqual(session_working_dir(SimpleNamespace(coordinator=coord)), "/work/big-repo")
        none = SimpleNamespace(get_capability=lambda name: None)
        self.assertEqual(session_working_dir(SimpleNamespace(coordinator=none)), os.getcwd())
        broken = SimpleNamespace(get_capability=lambda name: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(session_working_dir(SimpleNamespace(coordinator=broken)), os.getcwd())
