"""Loopback-only, token-protected, read-only telemetry viewer. Standard library only."""
from __future__ import annotations
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse
from typing import Any

from .privacy import safe_data
from .contracts import EVENT_NAMES

STATIC = Path(__file__).parent / "static"


class EventIndex:
    def __init__(self, directory: str | Path, capacity: int = 20000):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.capacity = capacity
        self.events: deque[dict] = deque(maxlen=capacity)
        self.ids: set[str] = set()
        self.positions: dict[str, tuple[int, int]] = {}
        self.cursor = 0
        self.epoch = secrets.token_hex(8)
        self.invalid_lines = 0
        self.lock = threading.Lock()

    def scan(self):
        with self.lock:
            for path in sorted(self.directory.glob("*.jsonl")):
                if path.is_symlink():
                    continue
                try:
                    st = path.stat()
                    offset, inode = self.positions.get(str(path), (0, st.st_ino))
                    if inode != st.st_ino or st.st_size < offset:
                        offset = 0
                    with path.open("rb") as file:
                        file.seek(offset)
                        # Bound work per scan; partial lines are retried next time.
                        for _ in range(10000):
                            position = file.tell()
                            line = file.readline(65537)
                            if not line:
                                break
                            if not line.endswith(b"\n"):
                                if len(line) > 65536:
                                    self.invalid_lines += 1
                                    # Skip oversized records as one record, bounded per call.
                                    while line and not line.endswith(b"\n"):
                                        line = file.readline(65537)
                                else:
                                    file.seek(position)
                                    break
                            else:
                                try:
                                    event = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                                    if not self._valid(event):
                                        raise ValueError("Not a fast-decisions event")
                                    # Do not publish arbitrary top-level fields from imported logs.
                                    event = {k: v for k, v in event.items() if k in {
                                        "schema_version", "event_id", "event", "session_id", "parent_session_id",
                                        "turn_id", "decision_id", "seq", "timestamp", "monotonic_ns", "synthetic", "data"}}
                                    if event["event_id"] not in self.ids:
                                        event["data"] = safe_data(event.get("data", {}))
                                        self.cursor += 1
                                        event["cursor"] = self.cursor
                                        if len(self.events) == self.capacity:
                                            self.ids.discard(self.events[0]["event_id"])
                                        self.events.append(event)
                                        self.ids.add(event["event_id"])
                                except (ValueError, TypeError, UnicodeError):
                                    self.invalid_lines += 1
                        self.positions[str(path)] = (file.tell(), st.st_ino)
                except OSError:
                    self.invalid_lines += 1

    @staticmethod
    def _valid(event):
        return (isinstance(event, dict) and event.get("schema_version") == "1.0"
                and isinstance(event.get("event_id"), str)
                and isinstance(event.get("session_id"), str)
                and isinstance(event.get("event"), str)
                and event["event"] in EVENT_NAMES
                and isinstance(event.get("data", {}), dict))

    def get(self, after: int = 0, limit: int = 1000):
        self.scan()
        with self.lock:
            events = [dict(e) for e in self.events if e["cursor"] > after][:limit]
            return {"events": events, "cursor": events[-1]["cursor"] if events else self.cursor,
                    "epoch": self.epoch, "retained": len(self.events),
                    "has_more": bool(events and events[-1]["cursor"] < self.cursor),
                    "first_cursor": self.events[0]["cursor"] if self.events else 0,
                    "invalid_lines": self.invalid_lines}


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, directory: str | Path, port: int = 8765, token: str | None = None):
        self.index = EventIndex(directory)
        self.token = token or secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}/#token={self.token}"


class Handler(BaseHTTPRequestHandler):
    server: ViewerServer
    def log_message(self, format, *args):
        # Never log auth-bearing URLs or request content.
        return

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                         "object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: Any):
        self._send(status, json.dumps(data, allow_nan=False).encode(), "application/json")

    def do_GET(self):
        parsed = urlparse(self.path)
        host = self.headers.get("Host", "")
        valid_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in valid_hosts:
            return self._json(403, {"error": "Invalid host"})
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in valid_hosts}:
            return self._json(403, {"error": "Invalid origin"})
        if parsed.path.startswith("/api/"):
            expected = "Bearer " + self.server.token
            if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                return self._json(401, {"error": "Open the token-bearing URL printed by afast"})
            if parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                try:
                    after = max(0, int(query.get("after", ["0"])[0]))
                    limit = max(1, min(2000, int(query.get("limit", ["1000"])[0])))
                except ValueError:
                    return self._json(400, {"error": "Invalid cursor"})
                return self._json(200, self.server.index.get(after, limit))
            if parsed.path == "/api/health":
                return self._json(200, {"read_only": True, "transport": "poll-500ms", "version": "0.1.0"})
            return self._json(404, {"error": "Not found"})
        name = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}.get(parsed.path)
        if not name:
            return self._json(404, {"error": "Not found"})
        path = STATIC / name
        self._send(200, path.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream")

    def do_POST(self):
        self._json(405, {"error": "Read-only viewer; runtime policy is not browser-editable"})
    do_PUT = do_DELETE = do_PATCH = do_POST
