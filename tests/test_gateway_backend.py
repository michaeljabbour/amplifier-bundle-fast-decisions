"""Stdlib-only tests for GatewayBackend, the hosted OpenAI-compatible judge.

A local ``http.server`` stands in for a hosted gateway (e.g. the team's
RunPod-backed endpoint) -- no real model, no network, no installs. Mirrors
the request/response contract shared with ``MlxBackend`` via
``OpenAICompatBackend``, plus the gateway-specific concerns: HTTPS
enforcement, the Authorization header sourced from an env-named key
(never logged or echoed), the ``external = True`` consent gate, and
abstention on a leaked think-token first position.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import math
import os
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from amplifier_fast_decisions.backends import BackendUnavailable
from amplifier_fast_decisions.contracts import Candidate, DecisionRequest
from amplifier_fast_decisions.local_backend import (
    GATEWAY_DEFAULT_KEY_ENV,
    GatewayBackend,
    gateway_base_url,
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


def _completion_payload(*, model="gateway-test", top=None, completion_tokens=1):
    top = top if top is not None else [
        {"token": "A", "logprob": math.log(0.92)},
        {"token": "Z", "logprob": math.log(0.03)},
    ]
    return {
        "id": "cmpl-1", "object": "chat.completion", "model": model,
        "choices": [{
            "index": 0, "finish_reason": "length",
            "logprobs": {"top_logprobs": [top]},
        }],
        "usage": {"prompt_tokens": 40, "completion_tokens": completion_tokens, "total_tokens": 41},
    }


class _Handler(http.server.BaseHTTPRequestHandler):
    """Configured per-test via class attributes, rebound by ``_make_handler``.

    Records every request's path, headers and (for POST) parsed body, so
    tests can assert on the Authorization header without ever needing the
    real key to leave this process.
    """

    completion_status = 200
    completion_payload = None
    models_status = 200
    delay_s = 0.0
    request_paths: list[str] = []
    request_bodies: list[dict] = []
    request_headers: list[dict] = []

    def log_message(self, *_args, **_kwargs):
        return  # silence request logging in test output

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).request_paths.append(self.path)
        type(self).request_headers.append(dict(self.headers))
        if self.path == "/models":
            body = b"{}"
            self.send_response(self.models_status)
        else:
            body = b"not found"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).request_paths.append(self.path)
        type(self).request_headers.append(dict(self.headers))
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {}
        type(self).request_bodies.append(parsed)
        if self.delay_s:
            time.sleep(self.delay_s)
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
    attrs.setdefault("request_headers", [])
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


class GatewayUrlValidationTests(unittest.TestCase):
    def test_https_required_for_nonloopback(self):
        for url in (
            "http://example.com", "http://llm.amplifier.run/v1",
            "https://user:secret@llm.amplifier.run/v1",
            "https://llm.amplifier.run/v1?x=1",
            "https://llm.amplifier.run/v1#frag",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                gateway_base_url(url)

    def test_https_nonloopback_with_path_accepted(self):
        self.assertEqual(
            gateway_base_url("https://llm.amplifier.run/v1"),
            "https://llm.amplifier.run/v1",
        )
        self.assertEqual(
            gateway_base_url("https://llm.amplifier.run/v1/"),
            "https://llm.amplifier.run/v1",
        )

    def test_loopback_may_use_http(self):
        self.assertEqual(gateway_base_url("http://127.0.0.1:9000/v1"), "http://127.0.0.1:9000/v1")

    def test_loopback_https_also_accepted(self):
        self.assertEqual(gateway_base_url("https://127.0.0.1:9000/v1"), "https://127.0.0.1:9000/v1")


class GatewayConstructionTests(unittest.TestCase):
    def test_requires_a_model(self):
        with self.assertRaises(BackendUnavailable):
            GatewayBackend(model="")
        with self.assertRaises(BackendUnavailable):
            GatewayBackend(model=None)  # type: ignore[arg-type]

    def test_missing_url_raises_backend_unavailable(self):
        # No public default: a public repo must not hardcode any private
        # team hostname. Without a gateway_url config or
        # FAST_DECISIONS_GATEWAY_URL env var, construction must fail loud.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAST_DECISIONS_GATEWAY_URL", None)
            with self.assertRaises(BackendUnavailable):
                GatewayBackend(model="some-model")

    def test_env_url_overrides_default(self):
        with mock.patch.dict(os.environ, {"FAST_DECISIONS_GATEWAY_URL": "https://custom.example/v1"}):
            backend = GatewayBackend(model="some-model")
        self.assertEqual(backend.base_url, "https://custom.example/v1")

    def test_external_flag_is_true(self):
        backend = GatewayBackend(model="some-model", url="http://127.0.0.1:9000")
        self.assertTrue(backend.external)
        self.assertEqual(backend.name, "gateway")


class GatewayAuthHeaderTests(unittest.TestCase):
    def test_authorization_header_sent_from_api_key(self):
        handler = _make_handler()
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url, timeout_ms=2000, api_key="sk-test-opaque-000111")
            result = asyncio.run(backend.ask(_request()))
        self.assertEqual(result.action.choice, "read")
        self.assertEqual(len(handler.request_headers), 1)
        self.assertEqual(handler.request_headers[0]["Authorization"], "Bearer sk-test-opaque-000111")

    def test_no_authorization_header_when_api_key_absent(self):
        handler = _make_handler()
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url, timeout_ms=2000, api_key=None)
            asyncio.run(backend.ask(_request()))
        self.assertNotIn("Authorization", handler.request_headers[0])

    def test_api_key_never_appears_in_repr_or_str(self):
        # The default object repr/str never enumerate instance attributes
        # (no __repr__/__str__ override adds one) -- this guards against a
        # future change accidentally introducing one that would leak it.
        backend = GatewayBackend(model="gw-test", url="http://127.0.0.1:9000", api_key="sk-test-opaque-000111")
        self.assertNotIn("sk-test-opaque-000111", repr(backend))
        self.assertNotIn("sk-test-opaque-000111", str(backend))


class GatewayScoringTests(unittest.TestCase):
    def test_scores_via_shared_logprobs_negotiation(self):
        handler = _make_handler(completion_payload=_completion_payload(model="gw-test"))
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url, timeout_ms=2000, api_key="k")
            result = asyncio.run(backend.ask(_request()))
        self.assertEqual(result.action.choice, "read")
        self.assertAlmostEqual(result.action.probabilities["read"], 0.92, places=6)
        self.assertAlmostEqual(result.action.probabilities["reason"], 0.08, places=6)
        self.assertEqual(result.model, "gw-test")
        self.assertEqual(result.input_tokens, 40)
        self.assertEqual(result.output_tokens, 1)

    def test_completions_url_appends_chat_completions_to_base(self):
        handler = _make_handler()
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url + "/v1", timeout_ms=2000, api_key="k")
            asyncio.run(backend.ask(_request()))
        self.assertIn("/v1/chat/completions", handler.request_paths[-1])

    def test_abstains_when_first_token_is_a_think_style_token(self):
        # The system prompt forbids a <think> preamble, but a hosted server
        # cannot be assumed to enforce it -- if the model emits one anyway,
        # it simply fails to match any label and its mass becomes
        # abstention, exactly like any other unrecognized token.
        handler = _make_handler(
            completion_payload=_completion_payload(top=[
                {"token": "<think>", "logprob": math.log(0.95)},
                {"token": "A", "logprob": math.log(0.04)},
            ])
        )
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url, timeout_ms=2000, api_key="k")
            result = asyncio.run(backend.ask(_request()))
        self.assertEqual(result.action.choice, "reason")  # SLOW/abstain
        self.assertGreater(result.action.probabilities["reason"], 0.9)

    def test_label_normalization_shared_with_mlx_scoring(self):
        labels = {"A": "read"}
        gateway_style = {"logprobs": [{"top_logprobs": [
            {"token": "A", "logprob": math.log(0.92)},
            {"token": "Z", "logprob": math.log(0.03)},
        ]}]}
        self.assertEqual(score_tokens(gateway_style, labels)["read"], 0.92)

    def test_request_body_uses_system_instruction_forbidding_thinking(self):
        backend = GatewayBackend(model="gw-test", url="http://127.0.0.1:9000", api_key="k")
        body, labels = backend.request_body(_request())
        self.assertEqual(body["model"], "gw-test")
        self.assertEqual(body["max_tokens"], 1)
        self.assertEqual(body["temperature"], 0)
        self.assertIn("no <think>", body["messages"][0]["content"])
        self.assertEqual(labels, {"A": "read"})

    def test_server_error_raises_backend_unavailable(self):
        handler = _make_handler(completion_status=500)
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url, timeout_ms=2000, api_key="k")
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))

    def test_timeout_raises_backend_unavailable_within_budget(self):
        handler = _make_handler(delay_s=2.0)
        with _running_server(handler) as base_url:
            backend = GatewayBackend(model="gw-test", url=base_url, timeout_ms=150, api_key="k")
            start = time.monotonic()
            with self.assertRaises(BackendUnavailable):
                asyncio.run(backend.ask(_request()))
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.5)


class GatewayRuntimeFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_builds_gateway_backend_from_config(self):
        from amplifier_fast_decisions.demo import DemoCoordinator
        from amplifier_fast_decisions.runtime import get_runtime

        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {GATEWAY_DEFAULT_KEY_ENV: "test-key"}):
                runtime, _ = get_runtime(coordinator, {
                    "backend": "gateway", "model": "gw-model",
                    "gateway_url": "https://gw.example/v1",
                    "events_dir": tmp,
                })
            try:
                self.assertIsInstance(runtime.service.backend, GatewayBackend)
                self.assertTrue(runtime.service.backend.external)
                self.assertEqual(runtime.service.backend.model, "gw-model")
                self.assertEqual(runtime.service.backend.base_url, "https://gw.example/v1")
                self.assertEqual(runtime.service.backend.api_key, "test-key")
            finally:
                await runtime.close()

    async def test_runtime_rejects_gateway_backend_missing_model(self):
        from amplifier_fast_decisions.demo import DemoCoordinator
        from amplifier_fast_decisions.runtime import get_runtime

        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                get_runtime(coordinator, {"backend": "gateway", "events_dir": tmp})

    async def test_runtime_rejects_unrelated_unknown_backend_name(self):
        # A regression guard for the backend-name allowlist itself: an
        # unrelated unknown name must still be rejected.
        from amplifier_fast_decisions.demo import DemoCoordinator
        from amplifier_fast_decisions.runtime import get_runtime

        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                get_runtime(coordinator, {"backend": "not-a-real-backend", "events_dir": tmp})


class GatewayDoctorCheckTests(unittest.TestCase):
    def test_doctor_reports_gateway_reachable(self):
        from amplifier_fast_decisions import cli

        handler = _make_handler()
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {
                "FAST_DECISIONS_GATEWAY_URL": base_url,
                GATEWAY_DEFAULT_KEY_ENV: "test-key",
            }):
                check = cli._gateway_server_check()
        self.assertEqual(check["check"], "gateway_server")
        self.assertTrue(check["ok"])
        self.assertEqual(check["state"], "reachable")
        self.assertEqual(check["value"], base_url)
        self.assertNotIn("test-key", json.dumps(check))

    def test_doctor_reports_gateway_auth_failed(self):
        from amplifier_fast_decisions import cli

        handler = _make_handler(models_status=401)
        with _running_server(handler) as base_url:
            with mock.patch.dict(os.environ, {"FAST_DECISIONS_GATEWAY_URL": base_url}):
                os.environ.pop(GATEWAY_DEFAULT_KEY_ENV, None)
                check = cli._gateway_server_check()
        self.assertFalse(check["ok"])
        self.assertEqual(check["state"], "auth_failed")

    def test_doctor_reports_gateway_unreachable(self):
        from amplifier_fast_decisions import cli

        with mock.patch.dict(os.environ, {"FAST_DECISIONS_GATEWAY_URL": "http://127.0.0.1:1"}):
            check = cli._gateway_server_check()
        self.assertFalse(check["ok"])
        self.assertEqual(check["state"], "unreachable")

    def test_doctor_reports_gateway_not_configured(self):
        # No public default: without gateway_url configured, the check
        # must report not_configured rather than crashing or hardcoding
        # any team-specific host.
        from amplifier_fast_decisions import cli

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAST_DECISIONS_GATEWAY_URL", None)
            check = cli._gateway_server_check()
        self.assertFalse(check["ok"])
        self.assertEqual(check["state"], "not_configured")
        self.assertIsNone(check["value"])


class CellsYamlGatewayCellTests(unittest.TestCase):
    def _cells_data(self):
        import yaml
        from pathlib import Path

        cells_path = Path(__file__).resolve().parents[1] / "evals" / "cells.yaml"
        with open(cells_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_cells_yaml_loads_and_has_the_gateway_cell(self):
        data = self._cells_data()
        cell = data["cells"]["judge-gateway+effort-incumbent"]
        self.assertEqual(cell["fd"]["backend"], "gateway")
        self.assertTrue(cell["fd"]["allow_external_state"])
        self.assertEqual(cell["mechanism_gate"]["scored_backend"], "gateway")

    def test_gateway_cell_requires_external_state(self):
        cell = self._cells_data()["cells"]["judge-gateway+effort-incumbent"]
        self.assertIn("allow_external_state", cell["fd"])
        self.assertTrue(cell["fd"]["allow_external_state"])

    def test_gateway_cell_wires_through_evals_run_argv(self):
        # evals/run.py's cell_to_argv must recognize the "gateway" backend
        # (mirrors the "jev" branch: requires allow_external_state, emits
        # --fd-backend gateway --allow-external-state).
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        evals_dir = str(repo_root / "evals")
        if evals_dir not in sys.path:
            sys.path.insert(0, evals_dir)
        import run as evals_run

        cells = evals_run.load_cells(repo_root / "evals" / "cells.yaml")
        suites = evals_run.load_suites(repo_root / "evals" / "suites.yaml")
        argv = evals_run.cell_to_argv(
            "judge-gateway+effort-incumbent", cells, suites, "s1", "dev", 1,
            out_root="/out", base_seed=20260919, baseline_source="/baseline",
            candidate_source="/candidate", candidate_sha="deadbeef", polyglot_root="/poly",
        )
        self.assertIn("--fd-backend", argv)
        self.assertIn("gateway", argv)
        self.assertIn("--allow-external-state", argv)


if __name__ == "__main__":
    unittest.main()


class ExtraBodyTests(unittest.TestCase):
    def test_gateway_disables_thinking_by_default_and_mlx_sends_no_extras(self):
        import os
        from amplifier_fast_decisions.local_backend import GatewayBackend, MlxBackend
        os.environ.setdefault("LITELLM_INFERENCE_KEY", "test-key")
        gw = GatewayBackend(model="m", url="https://example.invalid/v1", api_key="k")
        body, _ = gw.request_body(_request()) if hasattr(gw, "request_body") else (gw._prepare_request(_request())[0], None)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        mlx = MlxBackend(model="m", url="http://127.0.0.1:8080")
        mbody, _ = mlx.request_body(_request()) if hasattr(mlx, "request_body") else (mlx._prepare_request(_request())[0], None)
        self.assertNotIn("chat_template_kwargs", mbody)
        custom = GatewayBackend(model="m", url="https://example.invalid/v1", api_key="k", extra_body={})
        cbody = custom._prepare_request(_request())[0]
        self.assertNotIn("chat_template_kwargs", cbody)
