"""Actual installed core/loop, controlled scorer/provider; not performance evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HAS_HOST = all(importlib.util.find_spec(name) is not None for name in (
    "amplifier_core", "amplifier_module_loop_streaming"))


@unittest.skipUnless(HAS_HOST, "requires installed Amplifier core and loop")
class NativeActivePermissionsTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, action="continue", delay=0, stale=False):
        from amplifier_core.testing import MockCoordinator, MockContextManager
        from amplifier_core.models import HookResult
        from amplifier_core.message_models import ChatResponse, Usage
        from amplifier_fast_decisions.backends import ScriptedBackend
        from amplifier_fast_decisions.orchestrator import HybridOrchestrator
        from amplifier_fast_decisions.runtime import get_runtime
        from amplifier_fast_decisions.workspace import WorkspaceTool

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("original\n")
            coordinator = MockCoordinator()
            context = MockContextManager(messages=[])
            await coordinator.mount("context", context)
            tool = WorkspaceTool(root)
            await coordinator.mount("tools", tool, name="fast_workspace")
            executions, events = [], []
            original = tool.execute

            async def execute(arguments):
                executions.append(dict(arguments))
                return await original(arguments)

            tool.execute = execute

            async def approval(event, data):
                return HookResult(action=action, data={"tool_input": {
                    "operation": "read", "path": "OTHER.md"}} if action == "modify" else None)

            coordinator.hooks.register("tool:pre", approval, priority=0)
            config = {"mode": "active", "backend": "deterministic",
                      "allow_synthetic_active": True, "timeout_ms": 10,
                      "max_fast_per_turn": 1, "events_dir": str(root / "events")}
            runtime, _ = get_runtime(coordinator, config, owner=True)
            runtime.service.emitter.callback = events.append

            class Scorer(ScriptedBackend):
                async def ask(self, request):
                    result = await super().ask(request)
                    if stale:
                        (root / "README.md").write_text("changed during scoring\n")
                    return result

            runtime.service.backend = Scorer(delay_ms=delay)

            class Provider:
                name = "controlled-provider"

                def get_info(self):
                    from types import SimpleNamespace
                    return SimpleNamespace(id=self.name, display_name=self.name, context_window=32000)

                def parse_tool_calls(self, response):
                    return response.tool_calls or []

                async def complete(self, request, **kwargs):
                    return ChatResponse(content=[{"type": "text", "text": "done"}],
                                        usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2))

            try:
                loop = HybridOrchestrator(config, coordinator, runtime)
                result = await loop.execute("Read README.md", context, {"fixed": Provider()},
                                            {"fast_workspace": tool}, coordinator.hooks)
                self.assertEqual(result, "done")
            finally:
                await runtime.close()
            return executions, events

    async def test_native_allow_executes_once(self):
        executions, events = await self.run_case()
        self.assertEqual(executions, [{"operation": "read", "path": "README.md"}])
        self.assertEqual(sum(e["event"].endswith(":tool_start") for e in events), 1)

    async def test_native_deny_never_reaches_tool(self):
        executions, events = await self.run_case("deny")
        self.assertEqual(executions, [])
        self.assertFalse(any(e["event"].endswith(":tool_start") for e in events))

    async def test_modify_preserves_installed_upstream_semantics(self):
        # This upstream version does not apply tool:pre modify data. FD must
        # not independently execute the hook's replacement arguments.
        executions, _ = await self.run_case("modify")
        self.assertEqual(executions, [{"operation": "read", "path": "README.md"}])

    async def test_scoring_timeout_falls_back_without_tool_execution(self):
        executions, events = await self.run_case(delay=100)
        self.assertEqual(executions, [])
        self.assertTrue(any(e["data"].get("reason_code") == "decision_timeout" for e in events))

    async def test_changed_candidate_falls_back_without_tool_execution(self):
        executions, events = await self.run_case(stale=True)
        self.assertEqual(executions, [])
        self.assertTrue(any(e["data"].get("reason_code") == "candidate_no_longer_eligible" for e in events))
