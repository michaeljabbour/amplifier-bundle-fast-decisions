"""Real-kernel lane: PR B / P3 acceptance criterion 1 -- shadow measurement
in hooks-fast-decisions changes nothing about the turn. Runs the same
fake-provider script through a real StreamingOrchestrator, once with the
shadow hook mounted and once bare, and asserts an identical tool-call
sequence, identical final string, and identical native event sequence.

Skipped (not failed) when amplifier_core or loop-streaming are not
importable. Run this file with the real Amplifier CLI's interpreter:

    /Users/michaeljabbour/.local/share/uv/tools/amplifier/bin/python3 \\
        -m unittest tests.test_shadow_no_behaviour_change -v
"""
from __future__ import annotations

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


def _register_recorder(hooks, events, names):
    async def record(event, data):
        from amplifier_core.models import HookResult
        events.append(event)
        return HookResult(action="continue")

    for name in names:
        hooks.register(name, record)
    return record


async def _run(*, mount_shadow_hook: bool, tmp_dir: str):
    from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
    from amplifier_module_loop_streaming import StreamingOrchestrator

    coordinator = MockCoordinator()
    context = MockContextManager()
    await coordinator.mount("context", context)
    hooks = coordinator.hooks
    events: list[str] = []
    _register_recorder(hooks, events, NATIVE_EVENTS)

    cleanup = None
    if mount_shadow_hook:
        from amplifier_fast_decisions import observer
        cleanup = await observer.mount(coordinator, {
            "mode": "shadow", "backend": "unavailable", "events_dir": tmp_dir,
        })

    tool = MockTool("echo", "ok")
    provider = OneToolProvider()
    orch = StreamingOrchestrator({})
    try:
        result = await orch.execute("hi", context, {"fake": provider}, {"echo": tool}, hooks, coordinator=coordinator)
    finally:
        if cleanup is not None:
            await cleanup()

    return result, provider.calls, tool.call_count, sorted(events)


@unittest.skipUnless(HAS_LOOP, "amplifier_module_loop_streaming not installed (real-kernel lane only)")
class ShadowNoBehaviourChangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_tool_sequence_final_string_and_native_events(self):
        with tempfile.TemporaryDirectory() as tmp_with, tempfile.TemporaryDirectory() as tmp_without:
            result_with, calls_with, tool_calls_with, events_with = await _run(
                mount_shadow_hook=True, tmp_dir=tmp_with)
            result_without, calls_without, tool_calls_without, events_without = await _run(
                mount_shadow_hook=False, tmp_dir=tmp_without)

        self.assertEqual(result_with, result_without)
        self.assertEqual(result_with, "done")
        self.assertEqual(calls_with, calls_without)
        self.assertEqual(tool_calls_with, tool_calls_without)
        self.assertEqual(events_with, events_without)


if __name__ == "__main__":
    unittest.main()
