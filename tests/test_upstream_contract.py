"""Real-kernel lane: assert docs/UPSTREAM_CONTRACT.md against the INSTALLED
amplifier_module_loop_streaming, not against a description of it.

Skipped (not failed) when amplifier_core or loop-streaming are not importable.
Run this file with the real Amplifier CLI's interpreter:

    python3 tests/_hostpy.py  # prints the resolved interpreter path, or why none was found
    $(python3 tests/_hostpy.py | head -1) \
        -m unittest tests.test_upstream_contract -v
"""
from __future__ import annotations

import importlib.util
import inspect
import unittest
from types import SimpleNamespace

HAS_CORE = importlib.util.find_spec("amplifier_core") is not None
HAS_LOOP = importlib.util.find_spec("amplifier_module_loop_streaming") is not None


class FakeCompleteProvider:
    """No `.stream`; the complete() branch is the one that dispatches tools."""

    name = "fake-complete"

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


class FakeStreamProvider:
    """Has `.stream`; text-only chunks, never a tool call the loop could act on."""

    name = "fake-stream"

    def __init__(self):
        self.calls = 0

    def get_info(self):
        return SimpleNamespace(id=self.name, display_name=self.name, context_window=32000)

    async def list_models(self):
        return []

    def parse_tool_calls(self, response):
        return []

    async def stream(self, request, tools=None, **kwargs):
        self.calls += 1
        for chunk in ("Hello ", "world"):
            yield {"block_type": "text", "content": chunk}


@unittest.skipUnless(HAS_LOOP, "amplifier_module_loop_streaming not installed (real-kernel lane only)")
class UpstreamContractTests(unittest.IsolatedAsyncioTestCase):
    """Item 1 & 2: constructor and execute() signature (docs/UPSTREAM_CONTRACT.md)."""

    def test_constructor_accepts_plain_dict(self):
        from amplifier_module_loop_streaming import StreamingOrchestrator
        StreamingOrchestrator({"max_iterations": 3})

    def test_execute_signature(self):
        from amplifier_module_loop_streaming import StreamingOrchestrator
        signature = inspect.signature(StreamingOrchestrator({}).execute)
        self.assertTrue({"prompt", "context", "providers", "tools", "hooks"} <= set(signature.parameters))

    async def test_complete_branch_dispatches_tools(self):
        """Item 3 & 4: no .stream -> complete() branch runs; tool.execute gets
        the exact arguments dict, tool:pre/tool:post each fire once."""
        from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
        from amplifier_module_loop_streaming import StreamingOrchestrator

        coordinator = MockCoordinator()
        context = MockContextManager()
        hooks = coordinator.hooks
        recorded: list[str] = []

        async def record(event, data):
            from amplifier_core.models import HookResult
            recorded.append(event)
            return HookResult(action="continue")

        for name in ("tool:pre", "tool:post"):
            hooks.register(name, record)

        tool = MockTool("echo", "ok")
        provider = FakeCompleteProvider()
        orch = StreamingOrchestrator({})
        result = await orch.execute("hi", context, {"fake": provider}, {"echo": tool}, hooks, coordinator=coordinator)

        self.assertEqual(result, "done")
        self.assertEqual(tool.call_count, 1)
        tool.execute.assert_called_once_with({"x": 1})
        self.assertEqual(recorded.count("tool:pre"), 1)
        self.assertEqual(recorded.count("tool:post"), 1)

    async def test_stream_branch_drops_tool_calls(self):
        """Executable record of docs/UPSTREAM_CONTRACT.md item 3: a provider
        WITH `.stream` yielding text never reaches tool dispatch."""
        from amplifier_core.testing import MockCoordinator, MockContextManager, MockTool
        from amplifier_module_loop_streaming import StreamingOrchestrator

        coordinator = MockCoordinator()
        context = MockContextManager()
        hooks = coordinator.hooks
        tool = MockTool("echo", "ok")
        provider = FakeStreamProvider()
        orch = StreamingOrchestrator({})
        result = await orch.execute("hi", context, {"fake": provider}, {"echo": tool}, hooks, coordinator=coordinator)

        self.assertEqual(result, "Hello world")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(tool.call_count, 0)

    def test_transport_selection_matches_bare_provider(self):
        """The facade must not change what
        `callable(getattr(provider, "stream", None))` returns, for a
        provider with `.stream` and for one without."""
        import tempfile

        from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response
        from amplifier_fast_decisions.orchestrator import RoutedProvider
        from amplifier_fast_decisions.runtime import get_runtime

        with tempfile.TemporaryDirectory() as tmp:
            coordinator = DemoCoordinator()
            runtime, _ = get_runtime(coordinator, {"backend": "unavailable", "events_dir": tmp})

            bare_without = DemoProvider()
            facade_without = RoutedProvider(bare_without, runtime, {}, demo_response)
            self.assertEqual(
                callable(getattr(bare_without, "stream", None)),
                callable(getattr(facade_without, "stream", None)),
            )
            self.assertFalse(callable(getattr(facade_without, "stream", None)))

            bare_with = DemoProvider()

            async def fake_stream(request, **kwargs):
                yield "chunk"

            bare_with.stream = fake_stream
            facade_with = RoutedProvider(bare_with, runtime, {}, demo_response)
            self.assertEqual(
                callable(getattr(bare_with, "stream", None)),
                callable(getattr(facade_with, "stream", None)),
            )
            self.assertTrue(callable(getattr(facade_with, "stream", None)))


if __name__ == "__main__":
    unittest.main()
