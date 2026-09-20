"""Real-kernel lane: P6 -- we emit none of the native lifecycle events, and
that is a test, not a claim. Runs a real StreamingOrchestrator, once wrapped
by HybridOrchestrator and once bare, and compares the native event-name
multiset.

Skipped (not failed) when amplifier_core or loop-streaming are not importable.
Run this file with the real Amplifier CLI's interpreter:

    python3 tests/_hostpy.py  # prints the resolved interpreter path, or why none was found
    $(python3 tests/_hostpy.py | head -1) \
        -m unittest tests.test_lifecycle_events -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import unittest
from types import SimpleNamespace

HAS_CORE = importlib.util.find_spec("amplifier_core") is not None
HAS_LOOP = importlib.util.find_spec("amplifier_module_loop_streaming") is not None

NATIVE_EVENTS = (
    "execution:start", "execution:end", "orchestrator:complete",
    "provider:request", "tool:pre", "tool:post",
)


class OneToolProvider:
    """Returns a single tool call, then plain text -- two iterations."""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def get_info(self):
        return SimpleNamespace(id=self.name, display_name=self.name, context_window=32000)

    async def list_models(self):
        return []

    def parse_tool_calls(self, response):
        return response.tool_calls or []

    async def complete(self, request, **kwargs):
        from amplifier_core.message_models import ChatResponse, ToolCall, Usage
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content=[],
                tool_calls=[ToolCall(id="call1", name="echo", arguments={"x": 1})],
                usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        return ChatResponse(
            content=[{"type": "text", "text": "done"}],
            tool_calls=[],
            usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
        )


class HangingProvider:
    """Never returns from complete() -- used to exercise mid-turn cancellation."""

    name = "fake"

    def get_info(self):
        return SimpleNamespace(id=self.name, display_name=self.name, context_window=32000)

    async def list_models(self):
        return []

    def parse_tool_calls(self, response):
        return []

    async def complete(self, request, **kwargs):
        await asyncio.sleep(10)


def _register_recorder(hooks, events, names):
    async def record(event, data):
        from amplifier_core.models import HookResult
        events.append(event)
        return HookResult(action="continue")

    for name in names:
        hooks.register(name, record)
    return record


@unittest.skipUnless(HAS_LOOP, "amplifier_module_loop_streaming not installed (real-kernel lane only)")
class LifecycleEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_events_fire_exactly_once(self):
        from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
        from amplifier_fast_decisions.orchestrator import HybridOrchestrator
        from amplifier_fast_decisions.runtime import get_runtime

        coordinator = MockCoordinator()
        context = MockContextManager()
        hooks = coordinator.hooks
        events: list[str] = []
        _register_recorder(hooks, events, NATIVE_EVENTS)

        with tempfile.TemporaryDirectory() as tmp:
            config = {"backend": "unavailable", "events_dir": tmp}
            runtime, _ = get_runtime(coordinator, config, owner=True)
            tool = MockTool("echo", "ok")
            provider = OneToolProvider()
            orch = HybridOrchestrator(config, coordinator, runtime, upstream=None)
            try:
                result = await orch.execute("hi", context, {"fake": provider}, {"echo": tool}, hooks)
            finally:
                await runtime.close()

        self.assertEqual(result, "done")
        self.assertEqual(events.count("execution:start"), 1)
        self.assertEqual(events.count("execution:end"), 1)
        self.assertEqual(events.count("orchestrator:complete"), 1)
        self.assertEqual(events.count("provider:request"), 2)
        self.assertEqual(events.count("tool:pre"), 1)
        self.assertEqual(events.count("tool:post"), 1)

    async def test_counts_match_bare_upstream(self):
        from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
        from amplifier_fast_decisions.orchestrator import HybridOrchestrator
        from amplifier_fast_decisions.runtime import get_runtime
        from amplifier_module_loop_streaming import StreamingOrchestrator

        # Hybrid run.
        hybrid_coordinator = MockCoordinator()
        hybrid_context = MockContextManager()
        hybrid_hooks = hybrid_coordinator.hooks
        hybrid_events: list[str] = []
        _register_recorder(hybrid_hooks, hybrid_events, NATIVE_EVENTS)
        with tempfile.TemporaryDirectory() as tmp:
            config = {"backend": "unavailable", "events_dir": tmp}
            runtime, _ = get_runtime(hybrid_coordinator, config, owner=True)
            hybrid_tool = MockTool("echo", "ok")
            hybrid_provider = OneToolProvider()
            orch = HybridOrchestrator(config, hybrid_coordinator, runtime, upstream=None)
            try:
                await orch.execute("hi", hybrid_context, {"fake": hybrid_provider}, {"echo": hybrid_tool}, hybrid_hooks)
            finally:
                await runtime.close()

        # Bare run: same script, no HybridOrchestrator in the middle.
        bare_coordinator = MockCoordinator()
        bare_context = MockContextManager()
        bare_hooks = bare_coordinator.hooks
        bare_events: list[str] = []
        _register_recorder(bare_hooks, bare_events, NATIVE_EVENTS)
        bare_tool = MockTool("echo", "ok")
        bare_provider = OneToolProvider()
        bare_orch = StreamingOrchestrator({})
        await bare_orch.execute("hi", bare_context, {"fake": bare_provider}, {"echo": bare_tool}, bare_hooks,
                                 coordinator=bare_coordinator)

        self.assertEqual(sorted(hybrid_events), sorted(bare_events))

    async def test_event_ordering_note(self):
        """fast_decisions:turn_start precedes execution:start; turn_end follows execution:end."""
        from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
        from amplifier_fast_decisions.orchestrator import HybridOrchestrator
        from amplifier_fast_decisions.runtime import get_runtime

        coordinator = MockCoordinator()
        context = MockContextManager()
        hooks = coordinator.hooks
        events: list[str] = []
        _register_recorder(hooks, events, NATIVE_EVENTS + (
            "fast_decisions:turn_start", "fast_decisions:turn_end",
        ))

        with tempfile.TemporaryDirectory() as tmp:
            config = {"backend": "unavailable", "events_dir": tmp}
            runtime, _ = get_runtime(coordinator, config, owner=True)
            tool = MockTool("echo", "ok")
            provider = OneToolProvider()
            orch = HybridOrchestrator(config, coordinator, runtime, upstream=None)
            try:
                await orch.execute("hi", context, {"fake": provider}, {"echo": tool}, hooks)
            finally:
                await runtime.close()

        self.assertLess(events.index("fast_decisions:turn_start"), events.index("execution:start"))
        self.assertGreater(events.index("fast_decisions:turn_end"), events.index("execution:end"))
        self.assertGreater(events.index("fast_decisions:turn_end"), events.index("orchestrator:complete"))

    async def test_cancellation_still_propagates(self):
        from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
        from amplifier_fast_decisions.orchestrator import HybridOrchestrator
        from amplifier_fast_decisions.runtime import get_runtime

        coordinator = MockCoordinator()
        context = MockContextManager()
        hooks = coordinator.hooks
        events: list[str] = []
        _register_recorder(hooks, events, (
            "execution:start", "fast_decisions:cancelled", "fast_decisions:turn_end",
        ))

        with tempfile.TemporaryDirectory() as tmp:
            config = {"backend": "unavailable", "events_dir": tmp}
            runtime, _ = get_runtime(coordinator, config, owner=True)
            tool = MockTool("echo", "ok")
            provider = HangingProvider()
            orch = HybridOrchestrator(config, coordinator, runtime, upstream=None)
            task = asyncio.create_task(orch.execute("hi", context, {"fake": provider}, {"echo": tool}, hooks))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                await runtime.close()

        self.assertEqual(events.count("fast_decisions:cancelled"), 1)
        self.assertEqual(events.count("fast_decisions:turn_end"), 1)


if __name__ == "__main__":
    unittest.main()
