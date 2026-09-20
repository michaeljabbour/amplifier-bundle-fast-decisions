"""Stdlib-only tests for MlxBackend, mlx_lm.server's local judge host.

A local ``http.server`` stands in for a running ``mlx_lm.server`` -- no real
model, no network, no installs. Mirrors the two-shape ``logprobs`` request
negotiation, timeout handling, and label-normalization parity with
``OllamaBackend`` described in docs/MODEL-SETUP.md.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import math
import threading
import time
import unittest
from contextlib import contextmanager

from amplifier_fast_decisions.backends import BackendUnavailable
from amplifier_fast_decisions.contracts import Candidate, DecisionRequest
from amplifier_fast_decisions.local_backend import (
    MlxBackend,
    mlx_base_url,
    score_tokens,
)


def _request() -> DecisionRequest:
    return DecisionRequest(
        state={"observations": [{"role": "user", "text": "Read README.md"}]},
        candidates=(
            Candidate(
                "read", "Read README.md", "fast_workspace",
                {"operation": "read", "path": "README.md"},
            ),
        ),
    )


def _completion_payload(*, model="mlx-test", top=None, completion_tokens=1):
    top = top if top is not None else [
        {"id": 32, "token": "A", "logprob": math.log(0.92)},
        {"id": 90, "token": "Z", "logprob": math.log(0.03)},
    ]
    return {
        "id": "cmpl-1", "object": "text_completion", "model": model,
        "choices": [{
            "text": "A", "index": 0, "finish_reason": "length",
            "logprobs": {
                "tokens": ["A"], "token_logprobs": [math.log(0.92)],
                "top_logprobs": [top],
            },
        }],
        "usage": {"prompt_tokens": 40, "completion_tokens": completion_tokens, "total_tokens": 41},
    }


class _Handler(http.server.BaseHTTPRequestHandler):
    """Per-test behaviour is configured via class attributes, rebound by
    ``_make_handler`` for each test rather than shared mutable state.

    ``accepts_form`` controls which ``logprobs`` request shape this fake
    server honours: "int" ({"logprobs": N}), "bool" ({"logprobs": true,
    "top_logprobs": N}), or "both". A request in the unaccepted shape gets
    a 400 with no body -- simulating a version that does not understand it.
    """

    accepts_form = "both"
    health_status = 200
    completion_status = 200
    completion_payload = None
    delay_s = 0.0
    raw_body: bytes | None = None
    request_paths: list[str] = []
    request_bodies: list[dict] = []

    def log_message(self, *_args, **_kwargs):
        return  # silence request logging in test output

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).request_paths.append(self.path)
        if self.path == "/health":
            body = b"{}"
            self.send_response(self.health_status)
        else:
            body = b"not found"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).request_paths.append(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {}
        type(self).request_bodies.append(parsed)
        if self.delay_s:
            time.sleep(self.delay_s)
        shape = "bool" if isinstance(parsed.get("logprobs"), bool) else "int"
        if self.accepts_form != "both" and shape != self.accepts_form:
            body = b""
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.raw_body is not None:
            body = self.raw_body
        else:
            payload = self.completion_payload or _completion_payload()
            body = json.dumps(payload).encode("utf-8")
        self.send_response(self.completion_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _make_handler(**attrs) -> type[_Handler]:
    attrs.setdefault("request_paths", [])
    attrs.setdefault("request_bodies", [])
    return type("_Handler", (_Handler,), dict(attrs))


@contextmanager
def _running_server(handler_cls):
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class MlxOriginValidationTests(unittest.TestCase):
    def test_nonlocal_origins_rejected(self):
        for url in ("https://example.com", "http://localhost", "http://127.0.0.1.evil",
                    "http://user:secret@127.0.0.1", "http://127.0.0.1/proxy", "http://127.0.0.1?x=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mlx_base_url(url)
        self.assertEqual(mlx_base_url("http://127.0.0.1:8080/"), "http://127.0.0.1:8080")


class MlxBackendScoringTests(unittest.TestCase):
    def test_scores_via_int_logprobs_shape_on_first_try(self):
        handler = _make_handler(accepts_form="int")
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            result = asyncio.run(backend.ask(_request()))
        self.assertEqual(result.action.choice, "read")
        self.assertAlmostEqual(result.action.probabilities["read"], 0.92, places=6)
        self.assertAlmostEqual(result.action.probabilities["reason"], 0.08, places=6)
        self.assertEqual(result.model, "mlx-test")
        self.assertEqual(result.input_tokens, 40)
        self.assertEqual(result.output_tokens, 1)
        self.assertEqual(backend._logprobs_form, "int")
        # Exactly one POST -- the server accepted the first shape tried.
        self.assertEqual(len(handler.request_bodies), 1)
        self.assertFalse(isinstance(handler.request_bodies[0]["logprobs"], bool))

    def test_falls_back_to_bool_shape_when_int_rejected_and_caches_it(self):
        handler = _make_handler(accepts_form="bool")
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            result = asyncio.run(backend.ask(_request()))
            self.assertEqual(result.action.choice, "read")
            self.assertEqual(backend._logprobs_form, "bool")
            # First call: int rejected (400), then bool succeeded -- 2 requests.
            self.assertEqual(len(handler.request_bodies), 2)
            self.assertFalse(isinstance(handler.request_bodies[0]["logprobs"], bool))
            self.assertTrue(isinstance(handler.request_bodies[1]["logprobs"], bool))
            # Second call: the working shape is cached, so exactly one more request.
            asyncio.run(backend.ask(_request()))
            self.assertEqual(len(handler.request_bodies), 3)
            self.assertTrue(isinstance(handler.request_bodies[2]["logprobs"], bool))

    def test_both_shapes_rejected_raises_backend_unavailable(self):
        handler = _make_handler(accepts_form="neither")
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))
        self.assertIsNone(backend._logprobs_form)

    def test_missing_top_logprobs_raises_backend_unavailable(self):
        handler = _make_handler(
            accepts_form="int",
            completion_payload=_completion_payload(top=[]),
        )
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))

    def test_more_than_one_completion_token_rejected(self):
        handler = _make_handler(
            accepts_form="int",
            completion_payload=_completion_payload(completion_tokens=2),
        )
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))

    def test_malformed_json_raises_backend_unavailable(self):
        handler = _make_handler(accepts_form="int", raw_body=b"not json at all")
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))

    def test_server_error_raises_backend_unavailable(self):
        handler = _make_handler(accepts_form="int", completion_status=500)
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))

    def test_timeout_raises_backend_unavailable_within_budget(self):
        handler = _make_handler(accepts_form="int", delay_s=2.0)
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=150)
            start = time.monotonic()
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.5)  # budget (150ms) + generous slack

    def test_label_normalization_matches_ollama_on_same_distribution(self):
        # Same top-token distribution, expressed in each backend's native
        # response shape -- both must arrive at the same probabilities.
        labels = {"A": "read"}
        ollama_style = {"logprobs": [{"top_logprobs": [
            {"token": "A", "logprob": math.log(0.92)},
            {"token": "Z", "logprob": math.log(0.03)},
        ]}]}
        mlx_choice = _completion_payload()
        mlx_style = {"logprobs": [{
            "top_logprobs": mlx_choice["choices"][0]["logprobs"]["top_logprobs"][0]
        }]}
        self.assertEqual(score_tokens(ollama_style, labels), score_tokens(mlx_style, labels))

    def test_request_body_folds_system_into_a_single_prompt(self):
        backend = MlxBackend(model="mlx-test", url="http://127.0.0.1:8080")
        body, labels = backend.request_body(_request())
        self.assertEqual(body["model"], "mlx-test")
        self.assertEqual(body["max_tokens"], 1)
        self.assertEqual(body["temperature"], 0)
        self.assertIn("routing classifier", body["prompt"])
        self.assertIn("README.md", body["prompt"])
        self.assertEqual(labels, {"A": "read"})
        self.assertNotIn("system", body)


class MlxWarmupTests(unittest.TestCase):
    def test_warmup_succeeds_when_server_healthy(self):
        handler = _make_handler(accepts_form="int")
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            asyncio.run(backend.warmup())
        self.assertIn("/health", handler.request_paths)
        self.assertIn("/v1/completions", handler.request_paths)

    def test_warmup_raises_backend_unavailable_when_health_fails(self):
        handler = _make_handler(accepts_form="int", health_status=503)
        with _running_server(handler) as base_url:
            backend = MlxBackend(model="mlx-test", url=base_url, timeout_ms=2000)
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.warmup())

    def test_warmup_raises_backend_unavailable_when_server_unreachable(self):
        # Port 0 without a listener: nothing is bound there in this process,
        # so the connection is refused immediately.
        backend = MlxBackend(model="mlx-test", url="http://127.0.0.1:1", timeout_ms=500)
        with self.assertRaises(BackendUnavailable):
            asyncio.run(backend.warmup())


class MlxDoctorCheckTests(unittest.TestCase):
    def test_doctor_reports_mlx_reachable(self):
        from amplifier_fast_decisions import cli

        handler = _make_handler(accepts_form="int")
        with _running_server(handler) as base_url:
            import os
            from unittest import mock

            with mock.patch.dict(os.environ, {"FAST_DECISIONS_MLX_URL": base_url}):
                check = cli._mlx_server_check()
        self.assertTrue(check["ok"])
        self.assertEqual(check["check"], "mlx_server")
        self.assertEqual(check["value"], base_url)

    def test_doctor_reports_mlx_unreachable(self):
        from amplifier_fast_decisions import cli
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"FAST_DECISIONS_MLX_URL": "http://127.0.0.1:1"}):
            check = cli._mlx_server_check()
        self.assertFalse(check["ok"])


if __name__ == "__main__":
    unittest.main()
