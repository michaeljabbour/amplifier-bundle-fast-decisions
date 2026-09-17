"""Versioned events and a bounded, nonblocking, metadata-only JSONL recorder."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import queue
import re
import stat
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from .contracts import EVENT_PREFIX, canonical
from .privacy import safe_data


class JsonlRecorder:
    def __init__(self, directory: str | Path, session_id: str, capacity: int = 4096):
        directory = Path(directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)[:70]
        self.path = directory / f"{safe_id}-{uuid4().hex[:8]}.jsonl"
        self._queue: queue.Queue[str] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._closed = False
        self.dropped = 0
        self.error: str | None = None
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("Telemetry destination is not a regular file")
        self._file = os.fdopen(fd, "a", encoding="utf-8", buffering=1)
        self._thread = threading.Thread(target=self._run, name="afast-jsonl", daemon=True)
        self._thread.start()

    def submit(self, event: dict[str, Any]) -> None:
        if self._closed or self.error:
            self.dropped += 1
            return
        try:
            self._queue.put_nowait(canonical(event) + "\n")
        except queue.Full:
            self.dropped += 1

    def _run(self):
        try:
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    line = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    self._file.write(line)
                except OSError as exc:
                    self.error = type(exc).__name__
                    self.dropped += 1
                finally:
                    self._queue.task_done()
        finally:
            self._file.close()

    def close(self):
        self._closed = True
        self._stop.set()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            self.error = "RecorderShutdownTimeout"

    @property
    def health(self):
        return {"dropped_events": self.dropped, "recording_error": self.error,
                "queue_depth": self._queue.qsize()}


class Emitter:
    def __init__(self, session_id: str, *, parent_session_id: str | None = None,
                 hooks: Any = None, recorder: JsonlRecorder | None = None,
                 callback: Callable[[dict], Any] | None = None, synthetic: bool = False):
        self.session_id = session_id
        self.parent_session_id = parent_session_id
        self.hooks = hooks
        self.recorder = recorder
        self.callback = callback
        self.synthetic = synthetic
        self.sequence = 0
        self.hook_errors = 0

    async def emit(self, kind: str, data: dict[str, Any] | None = None, *,
                   turn_id: str | None = None, decision_id: str | None = None) -> dict[str, Any]:
        self.sequence += 1
        event = {
            "schema_version": "1.0", "event_id": uuid4().hex,
            "event": kind if kind.startswith(EVENT_PREFIX) else EVENT_PREFIX + kind,
            "session_id": self.session_id, "parent_session_id": self.parent_session_id,
            "turn_id": turn_id, "decision_id": decision_id, "seq": self.sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "synthetic": self.synthetic, "data": safe_data(data or {}),
        }
        if self.recorder:
            self.recorder.submit(event)
        if self.callback:
            value = self.callback(event)
            if inspect.isawaitable(value):
                await value
        if self.hooks:
            try:
                # Observability events carry no execution authority. Native tool/provider
                # events remain owned and processed by the upstream orchestrator.
                await self.hooks.emit(event["event"], event)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.hook_errors += 1
        return event
