"""One backend vocabulary (judge_backends.BACKENDS) shared by the runtime, the smart tool and `afast configure`;
plus the Workers AI (clef / clef-flash) backend against a local fake server. No network beyond loopback."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import backends, judge_backends, runtime, smart_tool  # noqa: E402
from amplifier_fast_decisions.contracts import DecisionRequest, Policy, Question, SLOW  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    server_version = "fake"
    log_message = lambda *a, **k: None  # noqa: E731

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        status, payload = self.server.reply
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeWorkersAI:
    def __enter__(self):
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.server.seen, self.server.reply = [], (200, {})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/client/v4"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def _request():
    question = Question(name="task_difficulty", type="choice", instructions="how hard",
                        criteria={"simple": "easy", "complex": "hard"})
    return DecisionRequest(state={"task": "fix the typo"}, candidates=(), questions=(question,))


def _ok(model="clef"):
    return {"success": True, "errors": [], "result": {
        "model": model, "usage": {"input_tokens": 321, "output_tokens": 0},
        "answers": {"next_action": {"probabilities": {SLOW: 1.0}},
                    "task_difficulty": {"probabilities": {"simple": 0.8, "complex": 0.2}}}}}


class BackendTableTests(unittest.TestCase):
    def test_table_is_well_formed(self):
        names = [s.name for s in judge_backends.BACKENDS]
        self.assertEqual(len(names), len(set(names)))
        for alias in (a for s in judge_backends.BACKENDS for a in s.aliases):
            self.assertNotIn(alias, names)
        self.assertEqual(judge_backends.canonical("local"), "ollama")
        self.assertEqual(judge_backends.canonical("gateway"), "hosted")
        self.assertEqual(judge_backends.canonical("none"), "unavailable")
        self.assertIsNone(judge_backends.spec("nope"))

    def test_clef_models_are_selectable_external_and_opt_in(self):
        for name in ("clef", "clef-flash"):
            spec = judge_backends.spec(name)
            self.assertTrue(spec.external and spec.opt_in and spec.select and spec.configure)
            self.assertEqual(set(spec.env), {"CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"})
        self.assertFalse(judge_backends.spec("jev").opt_in)

    def test_runtime_accepts_exactly_the_table(self):
        policy = Policy(mode="off")
        for name in judge_backends.names("runtime", aliases=True):
            if name in ("hosted", "gateway"):
                config = {"backend": name, "model": "m", "hosted_url": "https://llm.example.test/v1"}
            else:
                config = {"backend": name}
            try:
                runtime.build_backend(config, policy)
            except ValueError as exc:   # a backend may need more config, but never "unknown backend"
                self.assertNotIn("Backend must be", str(exc), name)
            except Exception:  # noqa: BLE001 - construction details are not this test's subject
                pass
        with self.assertRaisesRegex(ValueError, "Backend must be one of"):
            runtime.build_backend({"backend": "bogus"}, policy)

    def test_smart_tool_accepts_exactly_the_select_names(self):
        accepted = set()
        for name in [*judge_backends.names("runtime", aliases=True), "bogus"]:
            result = asyncio.run(smart_tool.select(
                {"task": "read README", "candidates": [{"id": "a", "operation": "read", "path": "README.md"}]},
                backend=name, allow_external_state=False))
            if result.reason_code != "unsupported_request":
                accepted.add(judge_backends.canonical(name))
        self.assertEqual(accepted, set(judge_backends.names("select")))

    def test_configure_accepts_exactly_the_configure_names(self):
        from amplifier_fast_decisions import cli
        parser_choices = None
        import argparse
        orig = argparse.ArgumentParser.add_argument

        def spy(self, *a, **k):
            nonlocal parser_choices
            if a and a[0] == "--backend" and k.get("choices") and "clef" in k["choices"]:
                parser_choices = list(k["choices"])
            return orig(self, *a, **k)
        with mock.patch.object(argparse.ArgumentParser, "add_argument", spy):
            with self.assertRaises(SystemExit):
                cli.main(["configure", "--help"])
        self.assertEqual(parser_choices, judge_backends.names("configure"))

    def test_select_skill_text_and_docs_name_every_selectable_backend(self):
        text = smart_tool.skill("select") + (ROOT / "src/amplifier_fast_decisions/SMART_TOOL.md").read_text(encoding="utf-8")
        for name in judge_backends.names("select"):
            self.assertIn(name, text)
        doc = (ROOT / "docs/CONFIGURATION.md").read_text(encoding="utf-8")
        self.assertIn("clef-flash", doc)


class ClefBackendTests(unittest.TestCase):
    ENV = {"CLOUDFLARE_API_TOKEN": "tok-SECRET-1", "CLOUDFLARE_ACCOUNT_ID": "acct-9"}

    def _backend(self, fake, model="clef"):
        return backends.ClefBackend(model=model, timeout_ms=3000, base_url=fake.url)

    def test_request_goes_to_the_account_model_path_with_the_bearer_token_and_the_envelope_is_unwrapped(self):
        with FakeWorkersAI() as fake, mock.patch.dict(os.environ, self.ENV):
            fake.server.reply = (200, _ok("clef-flash"))
            result = asyncio.run(self._backend(fake, "clef-flash").ask(_request()))
            seen = fake.server.seen[0]
        self.assertEqual(seen["path"], "/client/v4/accounts/acct-9/ai/run/@cf/cloudflare/clef-flash")
        self.assertEqual(seen["auth"], "Bearer tok-SECRET-1")
        self.assertEqual(seen["body"]["model"], "clef-flash")
        self.assertIn("task_difficulty", seen["body"]["questions"])
        self.assertEqual(result.model, "clef-flash")
        self.assertAlmostEqual(result.answers["task_difficulty"].probabilities["complex"], 0.2)
        self.assertEqual(result.input_tokens, 321)

    def test_error_envelope_is_unavailable_and_leaks_nothing(self):
        with FakeWorkersAI() as fake, mock.patch.dict(os.environ, self.ENV):
            fake.server.reply = (200, {"success": False, "result": None, "errors": [{"code": 7003, "message": "tok-SECRET-1 acct-9"}]})
            with self.assertRaises(backends.BackendUnavailable) as caught:
                asyncio.run(self._backend(fake).ask(_request()))
        self.assertIn("7003", str(caught.exception))
        for secret in ("tok-SECRET-1", "acct-9"):
            self.assertNotIn(secret, str(caught.exception))

    def test_http_error_is_unavailable(self):
        with FakeWorkersAI() as fake, mock.patch.dict(os.environ, self.ENV):
            fake.server.reply = (401, {"success": False, "errors": [{"code": 10000}]})
            with self.assertRaises(backends.BackendUnavailable):
                asyncio.run(self._backend(fake).ask(_request()))

    def test_missing_credentials_are_unavailable_and_name_the_variable(self):
        with FakeWorkersAI() as fake:
            for drop, expect in (("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID"), ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_TOKEN")):
                env = {k: v for k, v in self.ENV.items() if k != drop}
                with mock.patch.dict(os.environ, env, clear=False):
                    os.environ.pop(drop, None)
                    with self.assertRaisesRegex(backends.BackendUnavailable, expect):
                        asyncio.run(self._backend(fake).ask(_request()))
            self.assertEqual(fake.server.seen, [])

    def test_unknown_model_and_hostile_account_id_are_refused(self):
        with self.assertRaises(ValueError):
            backends.ClefBackend(model="jev")
        with FakeWorkersAI() as fake, mock.patch.dict(os.environ, {**self.ENV, "CLOUDFLARE_ACCOUNT_ID": "../../x"}):
            with self.assertRaises(backends.BackendUnavailable):
                asyncio.run(self._backend(fake).ask(_request()))

    def test_runtime_builds_clef_and_honours_the_consent_gate(self):
        backend = runtime.build_backend({"backend": "clef-flash"}, Policy(mode="off", timeout_ms=1500))
        self.assertIsInstance(backend, backends.ClefBackend)
        self.assertEqual((backend.name, backend.external, backend.timeout_ms), ("clef-flash", True, 1500))
        self.assertIsNone(asyncio.run(backend.warmup()))   # billed endpoint: no warmup call

    def test_smart_select_names_the_missing_clef_variables_and_checks_consent_first(self):
        payload = {"task": "read README", "candidates": [{"id": "a", "operation": "read", "path": "README.md"}]}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLOUDFLARE_API_TOKEN", None)
            os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
            no_consent = asyncio.run(smart_tool.select(payload, backend="clef"))
            no_key = asyncio.run(smart_tool.select(payload, backend="clef-flash", allow_external_state=True))
        self.assertEqual(no_consent.reason_code, "external_state_not_enabled")
        self.assertEqual(no_key.reason_code, "missing_api_key")
        self.assertIn("CLOUDFLARE_API_TOKEN", no_key.remediation)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", no_key.remediation)


if __name__ == "__main__":
    unittest.main()
