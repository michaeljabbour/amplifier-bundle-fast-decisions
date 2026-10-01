"""JevBackend criteria_format option and the HTTP 400 string-criteria fallback."""
from __future__ import annotations

import asyncio
import http.server
import json
import os
import threading
import unittest
from contextlib import contextmanager
from unittest import mock

from amplifier_fast_decisions import backends
from amplifier_fast_decisions.backends import JevBackend, _build_questions
from amplifier_fast_decisions.contracts import SLOW, Candidate, DecisionRequest

REJECT = {"error": {"message": "choice criteria must map option keys to descriptions or null"}}
OK = {"model": "m", "answers": {"next_action": {"probabilities": {"read_readme": 0.9, SLOW: 0.1}}}}


def _request():
    return DecisionRequest(
        state={"task": "read README"},
        candidates=(Candidate("read_readme", "Read README", "fast_workspace", {"path": "README.md"}),),
    )


def _server(reject_objects: bool, seen: list):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["questions"]["next_action"]["criteria"])
            bad = reject_objects and any(isinstance(v, dict) for v in seen[-1].values())
            raw = json.dumps(REJECT if bad else OK).encode()
            self.send_response(400 if bad else 200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    return http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)


@contextmanager
def running(reject_objects: bool):
    seen: list = []
    srv = _server(reject_objects, seen)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}", seen
    finally:
        srv.shutdown()
        srv.server_close()


class CriteriaFormatTests(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(backends, "_FORCE_URLLIB", True),
                  mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"})):
            p.start()
            self.addCleanup(p.stop)

    def test_build_questions_formats(self):
        obj, h1 = _build_questions(_request())
        strg, h2 = _build_questions(_request(), "string")
        self.assertIsInstance(obj["next_action"]["criteria"]["read_readme"], dict)
        self.assertEqual(strg["next_action"]["criteria"]["read_readme"].split(": ")[0], "Read README")
        self.assertIsInstance(strg["next_action"]["criteria"][SLOW], str)
        self.assertEqual(h1, h2)

    def test_invalid_format_rejected(self):
        with self.assertRaises(ValueError):
            JevBackend(criteria_format="xml")

    def test_default_object_sent_to_accepting_server(self):
        with running(False) as (url, seen):
            result = asyncio.run(JevBackend(base_url=url, timeout_ms=2000).ask(_request()))
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0]["read_readme"], dict)
        self.assertEqual(result.action.choice, "read_readme")

    def test_configured_string_format(self):
        with running(True) as (url, seen):
            backend = JevBackend(base_url=url, timeout_ms=2000, criteria_format="string")
            result = asyncio.run(backend.ask(_request()))
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0]["read_readme"], str)
        self.assertEqual(result.action.choice, "read_readme")

    def test_400_falls_back_once_and_remembers(self):
        with running(True) as (url, seen):
            backend = JevBackend(base_url=url, timeout_ms=2000)
            first = asyncio.run(backend.ask(_request()))
            self.assertEqual(len(seen), 2)  # object, then string retry
            self.assertIsInstance(seen[0]["read_readme"], dict)
            self.assertIsInstance(seen[1]["read_readme"], str)
            self.assertEqual(backend.criteria_format, "string")
            asyncio.run(backend.ask(_request()))
            self.assertEqual(len(seen), 3)  # remembered: string straight away
            self.assertIsInstance(seen[2]["read_readme"], str)
        self.assertEqual(first.action.choice, "read_readme")

    def test_unrelated_400_does_not_retry(self):
        class H(http.server.BaseHTTPRequestHandler):
            hits = 0

            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers["Content-Length"]))
                type(self).hits += 1
                self.send_response(400)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            backend = JevBackend(base_url=f"http://127.0.0.1:{srv.server_port}", timeout_ms=2000)
            with self.assertRaises(backends.BackendUnavailable):
                asyncio.run(backend.ask(_request()))
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(H.hits, 1)
        self.assertEqual(backend.criteria_format, "object")


if __name__ == "__main__":
    unittest.main()
