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
from typing import ClassVar
from unittest import mock

from amplifier_fast_decisions import backends
from amplifier_fast_decisions.backends import BackendUnavailable, JevBackend
from amplifier_fast_decisions.contracts import SLOW, Candidate, DecisionRequest

KEEPALIVE_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "next_action": {
            "type": "choice",
            "choice": "read_readme",
            "probabilities": {"read_readme": 0.91, SLOW: 0.09},
            "confidence": 0.85,
        }
    },
    "usage": {"input_tokens": 10, "output_tokens": 2},
}

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

MISLEADING_CONFIDENCE_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "next_action": {
            "type": "choice",
            "choice": "read_readme",
            # A vendor "confidence" of 0.99 alongside a near-toss-up
            # probability split -- exactly the shape independent Jev
            # audits found: confidence flat/uninformative except at the
            # extreme. Gating must use the 0.51 probability, never 0.99.
            "probabilities": {"read_readme": 0.51, SLOW: 0.49},
            "confidence": 0.99,
        }
    },
    "usage": {"input_tokens": 15, "output_tokens": 3},
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
    # HTTP/1.0 (BaseHTTPRequestHandler's default) closes the connection
    # after every response, which defeats keep-alive reuse tests. Tests
    # exercising connection reuse rebind this to "HTTP/1.1" via
    # ``_make_handler``.
    protocol_version = "HTTP/1.0"
    # Populated (class-level, across every request handled by any instance
    # bound to this connection) with the client source port of each
    # request -- an unchanged port across requests proves the same TCP
    # connection served both; a new port proves the client reconnected.
    client_ports: ClassVar[list[int]] = []
    # When set, the response to the request AT THIS 1-based count closes
    # the connection server-side right after responding, simulating a
    # keep-alive connection the peer silently dropped between decisions.
    close_after_request: int | None = None

    def log_message(self, *_args, **_kwargs):
        return  # silence request logging in test output

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).last_auth = self.headers.get("Authorization")
        type(self).last_path = self.path
        type(self).client_ports.append(self.client_address[1])
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
        if type(self).close_after_request == len(type(self).client_ports):
            self.close_connection = True


def _make_handler(**attrs) -> type[_Handler]:
    # Each handler subclass gets its OWN fresh ``client_ports`` list unless
    # a test overrides it -- otherwise every subclass would share (and
    # accumulate into) the base ``_Handler.client_ports`` class attribute.
    attrs.setdefault("client_ports", [])
    return type("_Handler", (_Handler,), dict(attrs))


class _QuietServer(http.server.HTTPServer):
    """Suppresses the default traceback-to-stderr noise from a connection
    a test deliberately abandons (e.g. after a client-side timeout) --
    harmless, but otherwise clutters every test run's output."""

    def handle_error(self, request, client_address):
        return


@contextmanager
def _running_server(handler_cls):
    server = _QuietServer(("127.0.0.1", 0), handler_cls)
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
        # reported_confidence is the chosen option's own probability
        # (0.93), never the vendor's separate confidence field (0.9).
        self.assertEqual(result.action.reported_confidence, 0.93)
        self.assertEqual(backend.last_vendor_confidence, 0.9)
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

    def test_misleading_vendor_confidence_never_feeds_the_decision(self):
        """A vendor confidence of 0.99 next to a near-even probability
        split must not leak into Decision.reported_confidence or the
        chosen action -- only the chosen option's own probability (0.51)
        may. The raw vendor value is still captured, verbatim, as
        last_vendor_confidence for receipts/observability."""
        handler = _make_handler(response_body=MISLEADING_CONFIDENCE_RESPONSE)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                result = asyncio.run(backend.ask(_request()))
        self.assertEqual(result.action.choice, "read_readme")
        self.assertEqual(result.action.reported_confidence, 0.51)
        self.assertEqual(backend.last_vendor_confidence, 0.99)

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


class JevKeepAliveTests(unittest.TestCase):
    """Stdlib transport connection reuse: same TCP connection across
    decisions, one-shot reconnect when the peer silently drops a stale
    keep-alive connection, and best-effort warmup. All offline, against a
    local HTTP/1.1 loopback server -- the real API is never called."""

    def setUp(self):
        self._force_patch = mock.patch.object(backends, "_FORCE_URLLIB", True)
        self._force_patch.start()
        self.addCleanup(self._force_patch.stop)
        self._env_patch = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": DUMMY_KEY})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_second_ask_reuses_the_same_connection(self):
        handler = _make_handler(protocol_version="HTTP/1.1", response_body=KEEPALIVE_RESPONSE)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                first = asyncio.run(backend.ask(_request()))
                first_reused = backend.last_reused_connection
                first_connect_ms = backend.last_connect_ms
                second = asyncio.run(backend.ask(_request()))
                second_reused = backend.last_reused_connection
                second_connect_ms = backend.last_connect_ms
                # Tear down the persistent connection before the loopback
                # server's ``with`` block exits -- otherwise the server's
                # blocking read for a next request that never comes
                # prevents ``HTTPServer.shutdown()`` from ever returning.
                asyncio.run(backend.close())
        self.assertEqual(first.action.choice, "read_readme")
        self.assertEqual(second.action.choice, "read_readme")
        self.assertFalse(first_reused)  # first call: nothing to reuse yet
        self.assertGreaterEqual(first_connect_ms, 0.0)
        # Second call must have reused the connection: zero connect cost,
        # and the server must have seen exactly one client source port
        # across both requests (proof it was the SAME TCP connection).
        self.assertTrue(second_reused)
        self.assertEqual(second_connect_ms, 0.0)
        self.assertEqual(len(handler.client_ports), 2)
        self.assertEqual(handler.client_ports[0], handler.client_ports[1])

    def test_reconnects_once_after_server_drops_stale_connection(self):
        handler = _make_handler(
            protocol_version="HTTP/1.1",
            response_body=KEEPALIVE_RESPONSE,
            close_after_request=1,
        )
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                first = asyncio.run(backend.ask(_request()))
                # The server closed its side of the socket right after
                # request 1. The backend still believes the connection is
                # open; this second call must detect the stale connection,
                # reconnect exactly once, and still succeed.
                second = asyncio.run(backend.ask(_request()))
                asyncio.run(backend.close())
        self.assertEqual(first.action.choice, "read_readme")
        self.assertEqual(second.action.choice, "read_readme")
        self.assertFalse(backend.last_reused_connection)  # had to reconnect
        self.assertGreater(backend.last_connect_ms, 0.0)
        # Two distinct TCP connections reached the server: the original,
        # and the one reconnect opened after the stale-connection failure.
        self.assertEqual(len(handler.client_ports), 2)
        self.assertNotEqual(handler.client_ports[0], handler.client_ports[1])

    def test_timeout_on_fresh_connection_still_raises_within_budget(self):
        """A timeout on a connection that was never proven stale (nothing
        to reuse yet) must not retry -- retrying would silently double the
        wait against the decision budget with no evidence it would help."""
        handler = _make_handler(protocol_version="HTTP/1.1", delay_s=2.0)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=150)
                start = time.monotonic()
                with self.assertRaises(BackendUnavailable):
                    asyncio.run(backend.ask(_request()))
                elapsed = time.monotonic() - start
        # One 150ms attempt, not a doubled retry: well under a single
        # retry's worth of slack.
        self.assertLess(elapsed, 1.0)

    def test_warmup_opens_the_connection(self):
        handler = _make_handler(protocol_version="HTTP/1.1", response_body=KEEPALIVE_RESPONSE)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                asyncio.run(backend.warmup())
                self.assertEqual(len(handler.client_ports), 1)
                self.assertIsNotNone(backend._conn)  # verifying the warm connection is cached
                # The real decision right after warmup reuses that connection.
                result = asyncio.run(backend.ask(_request()))
                asyncio.run(backend.close())
        self.assertEqual(result.action.choice, "read_readme")
        self.assertTrue(backend.last_reused_connection)
        self.assertEqual(len(handler.client_ports), 2)
        self.assertEqual(handler.client_ports[0], handler.client_ports[1])

    def test_warmup_failure_is_swallowed(self):
        backend = JevBackend(timeout_ms=100)
        with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": "http://127.0.0.1:1"}):
            # Nothing listens on port 1: connection refused. warmup() must
            # not raise -- the first real ask() still pays the handshake
            # itself, exactly as it did before warmup existed.
            asyncio.run(backend.warmup())
        self.assertIsNone(backend._conn)  # verifying no connection was left half-open

    def test_close_tears_down_the_persistent_connection(self):
        handler = _make_handler(protocol_version="HTTP/1.1", response_body=KEEPALIVE_RESPONSE)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"TYPESAFE_BASE_URL": base_url}):
                backend = JevBackend(timeout_ms=2000)
                asyncio.run(backend.ask(_request()))
                self.assertIsNotNone(backend._conn)
                asyncio.run(backend.close())
        self.assertIsNone(backend._conn)


if __name__ == "__main__":
    unittest.main()
