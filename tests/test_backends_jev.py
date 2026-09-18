"""Stdlib-only tests for JevBackend's urllib fallback transport.

No real typesafe_sdk installed or required: a local ``http.server`` stands
in for api.typesafe.ai, and ``backends._FORCE_URLLIB`` forces the fallback
path even if a real SDK happens to be importable in this environment. The
real API is never called.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import threading
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from amplifier_fast_decisions import backends
from amplifier_fast_decisions.backends import BackendUnavailable, JevBackend
from amplifier_fast_decisions.contracts import SLOW, Candidate, DecisionRequest

CANNED_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "next_action": {
            "type": "choice",
            "choice": "read_readme",
            "probabilities": {"read_readme": 0.93, SLOW: 0.07},
            "confidence": 0.9,
        }
    },
    "usage": {"input_tokens": 120, "output_tokens": 40},
}

DUMMY_KEY = "sk-test-dummy-not-a-real-key-000111222"


class _Handler(http.server.BaseHTTPRequestHandler):
    """Per-test behaviour is configured via class attributes, rebound by
    ``_make_handler`` for each test rather than shared mutable state."""

    status = 200
    raw_body: bytes | None = None
    response_body = CANNED_RESPONSE
    delay_s = 0.0
    last_auth = None
    last_path = None

    def log_message(self, *_args, **_kwargs):
        return  # silence request logging in test output

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).last_auth = self.headers.get("Authorization")
        type(self).last_path = self.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        if self.delay_s:
            time.sleep(self.delay_s)
        body = (
            self.raw_body
            if self.raw_body is not None
            else json.dumps(self.response_body).encode("utf-8")
        )
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _make_handler(**attrs) -> type[_Handler]:
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


def _request() -> DecisionRequest:
    return DecisionRequest(
        state={"task": "Read README.md before explaining the project."},
        candidates=(
            Candidate(
                "read_readme",
                "Read the project's README.md",
                "fast_workspace",
                {"operation": "read", "path": "README.md"},
            ),
        ),
    )


class JevUrllibFallbackTests(unittest.TestCase):
    def setUp(self):
        self._force_patch = mock.patch.object(backends, "_FORCE_URLLIB", True)
        self._force_patch.start()
        self.addCleanup(self._force_patch.stop)
        self._env_patch = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": DUMMY_KEY})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_forces_urllib_path_when_sdk_unavailable(self):
        self.assertFalse(backends._sdk_available())

    def test_normalizes_response_and_reports_transport(self):
        handler = _make_handler()
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                result = asyncio.run(backend.ask(_request()))
        result.action.validate({"read_readme", SLOW})
        self.assertEqual(result.action.choice, "read_readme")
        self.assertAlmostEqual(sum(result.action.probabilities.values()), 1.0, places=6)
        self.assertEqual(result.action.reported_confidence, 0.9)
        self.assertEqual(result.model, "jev-1.13.0")
        self.assertEqual(result.input_tokens, 120)
        self.assertEqual(result.output_tokens, 40)
        self.assertEqual(backend.last_transport, "urllib")
        self.assertEqual(handler.last_path, "/v1/systemone")
        self.assertEqual(handler.last_auth, f"Bearer {DUMMY_KEY}")

    def test_401_raises_backend_unavailable_without_leaking_key(self):
        handler = _make_handler(status=401)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                with self.assertRaises(BackendUnavailable) as ctx:
                    asyncio.run(backend.ask(_request()))
        self.assertNotIn(DUMMY_KEY, str(ctx.exception))

    def test_403_raises_backend_unavailable(self):
        handler = _make_handler(status=403)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                with self.assertRaises(BackendUnavailable):
                    asyncio.run(backend.ask(_request()))

    def test_server_error_raises_backend_unavailable(self):
        handler = _make_handler(status=500)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                with self.assertRaises(BackendUnavailable):
                    asyncio.run(backend.ask(_request()))

    def test_timeout_raises_within_budget(self):
        handler = _make_handler(delay_s=2.0)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=150)
                start = time.monotonic()
                with self.assertRaises(BackendUnavailable):
                    asyncio.run(backend.ask(_request()))
                elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.5)  # budget (150ms) + generous slack

    def test_malformed_json_raises_backend_unavailable(self):
        handler = _make_handler(raw_body=b"not json at all")
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                with self.assertRaises(BackendUnavailable):
                    asyncio.run(backend.ask(_request()))

    def test_missing_key_raises_before_any_network_call(self):
        handler = _make_handler()
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}, clear=True):
                # setUp's TYPESAFE_API_KEY patch is overridden by this
                # clear=True dict, so no key is present for this call.
                backend = JevBackend(timeout_ms=2000)
                with self.assertRaises(BackendUnavailable) as ctx:
                    asyncio.run(backend.ask(_request()))
        self.assertIn("TYPESAFE_API_KEY", str(ctx.exception))
        self.assertIsNone(handler.last_auth)  # no request ever left the process


if __name__ == "__main__":
    unittest.main()
