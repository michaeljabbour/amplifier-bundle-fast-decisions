"""Two per-step efficiency levers inside the hybrid orchestrator (both off by default).

* **Cache keep-alive** (``Policy.cache_keepalive``): while a tool or helper
  agent runs past ``interval_s`` since the prompt cache was last used, re-send
  the last model request unchanged (byte-identical messages, same model,
  tools and thinking settings; output capped) so the provider's 5-minute
  prompt cache stays warm. Stops when the tool finishes or after
  ``max_refreshes``. One ``cache_keepalive`` receipt per episode, settled
  against the next real call's cache reads.
* **Loop stop** (``Policy.loop_stop``): detect an identical tool call repeated
  in a turn with no edit in between, consecutive tool failures, and ``sleep``
  used as a timer; queue a short note for the next model request (delivered as
  a ``tool:post`` context injection) instead of stopping anything. One
  ``loop_stop`` receipt per note at turn end, with the further pattern calls
  measured after the note.

Measured motivation: docs/evidence/2026-09-25/step-opportunity/summary.json.
Neither lever records prompts, arguments or results: receipts carry tool
names, token counts and prices only.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable

from . import efficiency
from .contracts import (EXPECTED_FURTHER_CALLS, EXPECTED_SOURCE, KEEPALIVE_DEFAULTS, LOOP_STOP_DEFAULTS, digest,
                        field_value)
from .savings import DEFAULT_RATES, _rates_for, price

EDIT_TOOLS = frozenset({"write_file", "edit_file", "apply_patch", "multi_edit"})
_SLEEP = re.compile(r"(?<![\w.-])sleep\s+(\d+(?:\.\d+)?)([smh]?)\b")
_LOOP_WORDS = re.compile(r"\b(while|until|for)\b")
_BASH_EDIT = re.compile(r"sed\s+-i|(?<![0-9&])>>?\s*(?!&|/dev/null)\S|\btee\b|\bgit\s+(apply|checkout|restore|commit|reset)\b")
# ~ tokens of one note; priced once at the cache-write rate.
NOTE_TOKENS = 90


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _enabled(cfg: dict | None) -> bool:
    return isinstance(cfg, dict) and cfg.get("enabled", True) is True


def sleep_seconds(command: str) -> float | None:
    """Largest ``sleep N`` in a shell command used as a timer, or None. A
    sleep inside a while/until/for loop is a blocking wait, not a timer."""
    if not isinstance(command, str) or _LOOP_WORDS.search(command):
        return None
    best = None
    for m in _SLEEP.finditer(command):
        n = float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]
        best = n if best is None else max(best, n)
    return best


def _command(input: Any) -> str:
    if isinstance(input, dict):
        cmd = input.get("command")
        if isinstance(cmd, str):
            return cmd
    return ""


class LoopWatch:
    """Per-turn loop detector. ``observe`` is called after every tool call."""

    def __init__(self, cfg: dict):
        self.cfg = {**LOOP_STOP_DEFAULTS, **cfg}
        self.expected = {**EXPECTED_FURTHER_CALLS, **(cfg.get("expected_further_calls") or {})}
        self.counts: dict[str, int] = {}
        self.fail_streak = 0
        self.fail_tools: list[str] = []
        self.sleep_calls = 0
        self.pending: list[str] = []
        self.interventions: list[dict] = []

    def _intervene(self, kind: str, tool: str, note: str, sig: str | None = None) -> None:
        self.pending.append(note)
        self.interventions.append({"kind": kind, "tool": tool, "sig": sig, "further": 0, "active": True,
                                   "delivered": False})

    def observe(self, tool: str, input: Any, success: bool | None) -> None:
        command = _command(input) if tool == "bash" else ""
        is_edit = tool in EDIT_TOOLS or bool(command and _BASH_EDIT.search(command))
        sig = tool + ":" + digest(input if isinstance(input, dict) else {"_": str(input)})
        failed = success is False
        timer = sleep_seconds(command) if command else None
        is_timer = timer is not None and timer >= float(self.cfg["min_sleep_s"])
        # Measure: pattern calls after an already-delivered (or queued) note.
        for iv in self.interventions:
            if not iv["active"]:
                continue
            if iv["kind"] == "repeat":
                if is_edit:
                    iv["active"] = False
                elif sig == iv["sig"]:
                    iv["further"] += 1
            elif iv["kind"] == "failures":
                if failed:
                    iv["further"] += 1
                else:
                    iv["active"] = False
            elif iv["kind"] == "sleep_timer" and is_timer:
                iv["further"] += 1
        # Detect.
        if is_edit:
            self.counts.clear()
        else:
            n = self.counts[sig] = self.counts.get(sig, 0) + 1
            if n == int(self.cfg["repeat_threshold"]):
                self._intervene("repeat", tool, (
                    f"The last {n} `{tool}` calls in this turn were identical, with no file edit in between. "
                    "Repeating it again is unlikely to change the result: change approach, or stop and report "
                    "what you found."), sig)
        if failed:
            self.fail_streak += 1
            self.fail_tools.append(tool)
            if self.fail_streak == int(self.cfg["failure_threshold"]):
                names = ", ".join(self.fail_tools[-self.fail_streak:])
                self._intervene("failures", tool, (
                    f"The last {self.fail_streak} tool calls failed ({names}). Diagnose the cause before retrying, "
                    "change approach, or stop and report the blocker."))
        else:
            self.fail_streak, self.fail_tools = 0, []
        if is_timer:
            self.sleep_calls += 1
            if self.sleep_calls == int(self.cfg["sleep_threshold"]):
                self._intervene("sleep_timer", tool, (
                    f"You have used `sleep` as a timer {self.sleep_calls} times this turn. Each check costs a full "
                    "model call. Prefer one blocking command that waits for the condition itself (for example "
                    "`timeout 900 sh -c 'until <check>; do sleep 10; done'`, or `wait` on the process), or stop "
                    "polling and report."))

    def take_note(self) -> str | None:
        if not self.pending:
            return None
        note = "[fast-decisions loop check]\n" + "\n".join(self.pending)
        self.pending = []
        for iv in self.interventions:
            iv["delivered"] = True
        return note


class Levers:
    """Per-execute state for both levers. Every public method never raises."""

    def __init__(self, policy: Any, service: Any, context: Callable[[], tuple[str, str]],
                 rates: dict | None = None, usage_fn: Callable[[Any], dict] | None = None):
        ka, ls = getattr(policy, "cache_keepalive", None), getattr(policy, "loop_stop", None)
        self.keepalive_cfg = {**KEEPALIVE_DEFAULTS, **ka} if _enabled(ka) else None
        self.loop = LoopWatch(ls) if _enabled(ls) else None
        self.service = service
        self.context = context
        self.usage_fn = usage_fn
        self.rates = rates or DEFAULT_RATES
        self.ttl_s = efficiency.CACHE_TTL_S
        # Last real model call (for keep-alive) and this turn's call averages.
        self.last: dict | None = None
        self.calls = 0
        self.sum_usd = 0.0
        self.sum_s = 0.0
        self.priced = 0
        self.host_model: str | None = None
        # Keep-alive runtime.
        self.running: dict[int, str] = {}
        self.episode: dict | None = None
        self._task: asyncio.Task | None = None
        self._refreshing = False

    @property
    def active(self) -> bool:
        return bool(self.keepalive_cfg or self.loop)

    # -- model calls ------------------------------------------------------
    async def after_call(self, provider: Any, request: Any, kwargs: dict, usage: dict, started: float,
                         seconds: float) -> None:
        try:
            model = kwargs.get("model") or getattr(provider, "default_model", None)
            model = model if isinstance(model, str) else None
            self.host_model = self.host_model or model
            self.calls += 1
            cost = _num(usage.get("cost_usd"))
            if cost is None:
                cost = price(model, {"input": usage.get("input_tokens") or 0, "output": usage.get("output_tokens") or 0,
                                     "cache_read": usage.get("cache_read_tokens") or 0,
                                     "cache_write": usage.get("cache_write_tokens") or 0}, self.rates)
            if cost is not None:
                self.sum_usd += cost
                self.sum_s += seconds
                self.priced += 1
            if self.episode is not None:
                await self._settle(next_usage=usage, next_model=model, next_started=started)
            if self.keepalive_cfg:
                prefix = int(usage.get("cache_read_tokens") or 0) + int(usage.get("cache_write_tokens") or 0)
                self.last = {"provider": provider, "request": request, "kwargs": dict(kwargs), "model": model,
                             "prefix": prefix, "anchor": started}
        except Exception:  # noqa: BLE001 -- levers never break the loop
            return

    def avg_call(self) -> tuple[float | None, float | None]:
        if not self.priced:
            return None, None
        return self.sum_usd / self.priced, self.sum_s / self.priced

    # -- tools ------------------------------------------------------------
    def tool_started(self, key: int, name: str) -> None:
        if not self.keepalive_cfg:
            return
        self.running[key] = name
        if self._task is None or self._task.done():
            try:
                self._task = asyncio.get_running_loop().create_task(self._keepalive_loop())
            except RuntimeError:
                self._task = None

    def tool_finished(self, key: int) -> None:
        self.running.pop(key, None)
        if not self.running and self._task is not None and not self._task.done() and not self._refreshing:
            self._task.cancel()

    async def tool_observed(self, tool: str, input: Any, success: bool | None) -> None:
        if self.loop is None:
            return
        try:
            before = len(self.loop.interventions)
            self.loop.observe(tool, input, success)
            for iv in self.loop.interventions[before:]:
                await self.service.emit("loop_note", {"reason_code": "loop_" + iv["kind"], "tool": iv["tool"]})
        except Exception:  # noqa: BLE001
            return

    def take_note(self) -> str | None:
        return self.loop.take_note() if self.loop else None

    # -- keep-alive -------------------------------------------------------
    async def _keepalive_loop(self) -> None:
        cfg = self.keepalive_cfg or {}
        interval = float(cfg["interval_s"])
        while self.running:
            last = self.last
            if last is None or last["prefix"] < int(cfg["min_prefix_tokens"]):
                return
            episode = self.episode
            if episode is not None and len(episode["refreshes"]) >= int(cfg["max_refreshes"]):
                return
            anchor = episode["anchor"] if episode is not None else last["anchor"]
            await asyncio.sleep(max(0.0, anchor + interval - time.monotonic()))
            if not self.running:
                return
            self._refreshing = True
            try:
                ok = await self._refresh()
            finally:
                self._refreshing = False
            if not ok:
                return
        return

    def _clone(self, request: Any) -> Any:
        cap = int((self.keepalive_cfg or {}).get("max_output_tokens", 1))
        messages = list(field_value(request, "messages", []) or [])
        copier = getattr(request, "model_copy", None)
        if callable(copier):
            return copier(update={"messages": messages, "max_output_tokens": cap})
        import copy
        clone = copy.copy(request)
        if isinstance(clone, dict):
            clone.update(messages=messages, max_output_tokens=cap)
        else:
            setattr(clone, "messages", messages)
            setattr(clone, "max_output_tokens", cap)
        return clone

    async def _refresh(self) -> bool:
        last = self.last
        if last is None:
            return False
        started = time.monotonic()
        if self.episode is None:
            self.episode = {"model": last["model"], "prefix": last["prefix"], "refreshes": [],
                            "tools": set(), "cache_used": last["anchor"], "anchor": started}
        episode = self.episode
        episode["tools"].update(self.running.values())
        call_id = "keepalive_" + digest({"t": started})[:16]
        try:
            response = await last["provider"].complete(self._clone(last["request"]), **last["kwargs"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self.service.emit("cache_refresh", {"provider_call_id": call_id, "model": last["model"],
                                                       "status": "error", "exception_type": type(exc).__name__,
                                                       "duration_ms": (time.monotonic() - started) * 1000})
            return False
        usage = self.usage_fn(response) if self.usage_fn else {}
        cost = _num(usage.get("cost_usd"))
        if cost is None:
            cost = price(last["model"], {"input": usage.get("input_tokens") or 0,
                                         "output": usage.get("output_tokens") or 0,
                                         "cache_read": usage.get("cache_read_tokens") or 0,
                                         "cache_write": usage.get("cache_write_tokens") or 0}, self.rates)
        episode["refreshes"].append(cost)
        episode["anchor"] = started
        await self.service.emit("cache_refresh", {
            "provider_call_id": call_id, "model": last["model"], "status": "ok",
            "duration_ms": (time.monotonic() - started) * 1000, "tools": sorted(episode["tools"])[:8],
            **{k: v for k, v in usage.items() if k != "served_model"}, "cost_usd": cost})
        return True

    async def _settle(self, *, next_usage: dict | None, next_model: str | None,
                      next_started: float | None) -> None:
        episode, self.episode = self.episode, None
        if episode is None or not episode["refreshes"]:
            return
        project, traffic = self.context()
        gap = None if next_started is None else next_started - episode["cache_used"]
        data = efficiency.cache_keepalive(
            model=episode["model"], prefix_tokens=episode["prefix"], refresh_costs=episode["refreshes"],
            tools=sorted(episode["tools"]), gap_s=gap,
            next_cache_read=None if next_usage is None else int(next_usage.get("cache_read_tokens") or 0),
            next_model=next_model if next_usage is not None else None,
            project=project, traffic=traffic, ttl_s=self.ttl_s, rates=self.rates)
        await self.service.emit("efficiency", data)

    # -- turn end ---------------------------------------------------------
    async def finish(self, status: str = "ok") -> None:
        """Turn end: stop refreshing, settle an open keep-alive episode (no
        later call reused it), and emit one receipt per delivered loop note.
        The continuation is measurable only when the turn ended normally."""
        try:
            self.running.clear()
            task = self._task
            if task is not None and not task.done():
                if self._refreshing:
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=30)
                    except Exception:  # noqa: BLE001
                        pass
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            if self.episode is not None:
                await self._settle(next_usage=None, next_model=None, next_started=None)
            if self.loop is not None:
                project, traffic = self.context()
                avg_usd, avg_s = self.avg_call()
                r = _rates_for(self.host_model, self.rates)
                note_usd = None if r is None else NOTE_TOKENS * r[3] / 1e6
                for iv in self.loop.interventions:
                    if not iv["delivered"]:
                        continue  # never reached the model: no decision acted on
                    data = efficiency.loop_stop(
                        kind=iv["kind"], tool=iv["tool"],
                        expected_further_calls=int(self.loop.expected.get(iv["kind"], 0)),
                        observed_further_calls=iv["further"] if status == "ok" else None,
                        avg_call_usd=avg_usd, avg_call_seconds=avg_s,
                        note_usd=note_usd, host_model=self.host_model,
                        source=EXPECTED_SOURCE, project=project, traffic=traffic)
                    await self.service.emit("efficiency", data)
        except Exception:  # noqa: BLE001
            return
