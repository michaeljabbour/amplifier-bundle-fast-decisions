"""Real-kernel lane: shadow-in-the-hook (P3) and the role router (P4)
against the ACTUAL loop-streaming payload shapes, not offline stand-ins.

Runs a real ``StreamingOrchestrator`` turn, with our hook mounted through
the real (Rust-backed) kernel coordinator, and a fake provider that issues
a ``fast_workspace`` tool call and a ``delegate``-named tool call. Exercises
the two telemetry gaps observed under the real Amplifier CLI in a Digital
Twin (docs/design/redesign-2026-09-17.md P3/P4):

1. ``shadow_observed``/``shadow_proposed``/``shadow_agreement`` must fire
   for a real tool call with a deterministic (in-process, un-gated)
   backend, and the ``jev`` backend must fall back exactly once per
   decision without ever constructing a Jev client.
2. The role router must record something -- a proposal/agreement pair, or
   an explicit abstain reason -- never silence, and must never mutate the
   delegate call's arguments.

Skipped (not failed) when amplifier_core or loop-streaming are not
importable. Run this file with the real Amplifier CLI's interpreter:

    python3 tests/_hostpy.py  # prints the resolved interpreter path, or why none was found
    $(python3 tests/_hostpy.py | head -1) \
        -m unittest tests.test_shadow_real_kernel -v
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HAS_CORE = importlib.util.find_spec("amplifier_core") is not None
HAS_LOOP = importlib.util.find_spec("amplifier_module_loop_streaming") is not None

SHADOW_EVENTS = (
    "fast_decisions:health",
    "fast_decisions:shadow_proposed",
    "fast_decisions:shadow_observed",
    "fast_decisions:shadow_agreement",
    "fast_decisions:role_proposed",
    "fast_decisions:role_agreement",
    "fast_decisions:fallback",
)


class ThreeIterationProvider:
    """iteration 1: fast_workspace call. iteration 2: delegate call.
    iteration 3: plain text -- three ``provider:request``/``complete()``
    calls, two real tool dispatches.
    """

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
                tool_calls=[
                    ToolCall(
                        id="call_fw",
                        name="fast_workspace",
                        arguments={"operation": "read", "path": "notes.md"},
                    )
                ],
                usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        if self.calls == 2:
            return ChatResponse(
                content=[],
                tool_calls=[
                    ToolCall(
                        id="call_delegate",
                        name="delegate",
                        arguments={"agent": "child", "prompt": "help"},
                    )
                ],
                usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        return ChatResponse(
            content=[{"type": "text", "text": "done"}],
            tool_calls=[],
            usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
        )


class FakeDelegateTool:
    """Mimics tool-delegate's real return shape: the routing summary is
    nested at output.provider_routing.model_role, never at a top-level
    hook field (amplifier_module_tool_delegate/__init__.py, "Build
    provider routing summary")."""

    name = "delegate"
    description = "Fake delegate"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, actual_model_role: str = "coding"):
        self.actual_model_role = actual_model_role
        self.calls: list[dict] = []

    async def execute(self, input: dict, **kwargs):
        from amplifier_core.models import ToolResult

        self.calls.append(dict(input))
        return ToolResult(
            success=True,
            output={
                "response": "ok",
                "session_id": "child-session",
                "agent": input.get("agent"),
                "provider_routing": {"model_role": self.actual_model_role},
            },
        )


class FakeRoleResolver:
    known_roles = ("coding",)

    async def resolve(self, role):
        return [SimpleNamespace(provider="p", model="m", config={})]


def _register_recorders(hooks, events: list[dict]):
    async def record(event, data):
        from amplifier_core.models import HookResult

        events.append({"event": event, "data": dict(data.get("data", data))})
        return HookResult(action="continue")

    for name in SHADOW_EVENTS:
        hooks.register(name, record)


async def _run_turn(
    *,
    backend: str,
    allow_external_state: bool,
    tmp_workspace: str,
    tmp_events: str,
    prompt: str = "Please read notes.md, then delegate the rest to a helper.",
):
    from amplifier_core.testing import MockCoordinator, MockContextManager
    from amplifier_module_loop_streaming import StreamingOrchestrator

    from amplifier_fast_decisions import observer
    from amplifier_fast_decisions.workspace import WorkspaceTool

    coordinator = MockCoordinator()
    # Empty starting context, matching a fresh session's very first turn --
    # the exact real-CLI condition that exposed the bug (see the P3
    # postmortem in docs/design/redesign-2026-09-17.md): upstream
    # (loop-streaming) appends `prompt` as the turn's own user message via
    # `context.add_message` only *after* emitting iteration 1's
    # `provider:request` (the "hoisted" provider:request block). Seeding the
    # filename into the context's pre-existing history instead of the
    # `prompt` argument (as an earlier version of this fixture did) hid the
    # bug: the candidate was already visible in `get_messages()` regardless
    # of when the snapshot ran. With no pre-existing history, the
    # "notes.md" candidate exists *only* once the prompt has been appended,
    # so a snapshot taken at `provider:request` (before that append) sees
    # zero candidates -- this fixture would have failed
    # `test_deterministic_backend_produces_shadow_and_role_telemetry`'s
    # `shadow_observed`/`shadow_agreement` assertions under that bug.
    context = MockContextManager(messages=[])
    await coordinator.mount("context", context)

    workspace_tool = WorkspaceTool(root=tmp_workspace)
    delegate_tool = FakeDelegateTool()
    await coordinator.mount("tools", workspace_tool, name="fast_workspace")
    await coordinator.mount("tools", delegate_tool, name="delegate")
    coordinator.register_capability("model_role_resolver", FakeRoleResolver())

    hooks = coordinator.hooks
    events: list[dict] = []
    _register_recorders(hooks, events)

    cleanup = await observer.mount(
        coordinator,
        {
            "mode": "shadow",
            "backend": backend,
            "allow_external_state": allow_external_state,
            "events_dir": tmp_events,
            "role_router": True,
            "role_router_tools": ["delegate"],
            "shadow_drain_ms": 500,
        },
    )

    provider = ThreeIterationProvider()
    tools = {"fast_workspace": workspace_tool, "delegate": delegate_tool}
    orch = StreamingOrchestrator({})
    try:
        result = await orch.execute(
            prompt, context, {"fake": provider}, tools, hooks, coordinator=coordinator
        )
        # Let fire-and-forget router probes/joins (asyncio.ensure_future,
        # never awaited by the hook chain) finish before we inspect events.
        await asyncio.sleep(0.15)
    finally:
        await cleanup()

    return result, events, delegate_tool


@unittest.skipUnless(HAS_LOOP, "amplifier_module_loop_streaming not installed (real-kernel lane only)")
class ShadowRealKernelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._workspace = tempfile.TemporaryDirectory()
        (Path(self._workspace.name) / "notes.md").write_text("hello", encoding="utf-8")
        self._events_a = tempfile.TemporaryDirectory()
        self._events_b = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        self._workspace.cleanup()
        self._events_a.cleanup()
        self._events_b.cleanup()

    async def test_observer_reports_native_activity_and_effective_configuration(self):
        result, events, _ = await _run_turn(
            backend="deterministic", allow_external_state=False,
            tmp_workspace=self._workspace.name, tmp_events=self._events_a.name,
            prompt="Use the tools, then answer.",
        )
        self.assertEqual(result, "done")
        health = [e["data"] for e in events if e["event"].endswith(":health")]
        config = next(d for d in health if d.get("phase") == "configuration")
        self.assertEqual(config["mode"], "shadow")
        self.assertEqual(config["backend"], "scripted-demo")
        self.assertFalse(config["allow_external_state"])
        self.assertEqual(sum(d.get("native_event") == "provider:request" for d in health), 3)
        self.assertEqual(sum(d.get("native_event") == "tool:post" for d in health), 2)
        self.assertTrue(any(d.get("reason_code") == "no_eligible_candidates" for d in health))
        self.assertFalse(any("prompt" in d or "result" in d or "tool_input" in d for d in health))

    async def test_deterministic_backend_produces_shadow_and_role_telemetry(self):
        result, events, delegate_tool = await _run_turn(
            backend="deterministic",
            allow_external_state=False,
            tmp_workspace=self._workspace.name,
            tmp_events=self._events_a.name,
        )
        self.assertEqual(result, "done")

        def of(suffix):
            return [e for e in events if e["event"].endswith(suffix)]

        # shadow_observed: emitted per matched tool call, with the
        # documented fields.
        observed = of("shadow_observed")
        self.assertGreaterEqual(len(observed), 1)
        for e in observed:
            self.assertIn("tool", e["data"])
            self.assertIn("tool_call_id", e["data"])
            self.assertIn("arguments_hash", e["data"])

        # deterministic backend is un-gated (external=False): real
        # shadow_proposed/shadow_agreement telemetry, not just a fallback.
        self.assertGreaterEqual(len(of("shadow_proposed")), 1)
        self.assertGreaterEqual(len(of("shadow_agreement")), 1)

        # role router: enabled, resolver present -> a real proposal/
        # agreement pair for the delegate call, matching the real
        # tool-delegate payload shape (result.output.provider_routing).
        role_proposed = of("role_proposed")
        role_agreement = of("role_agreement")
        self.assertTrue(
            any(e["data"].get("proposed_model_role") == "coding" for e in role_proposed)
        )
        self.assertEqual(len(role_agreement), 1)
        self.assertEqual(role_agreement[0]["data"]["actual_model_role"], "coding")
        self.assertEqual(role_agreement[0]["data"]["agreement"], "match")

        # Never mutates the call: the delegate tool saw its original,
        # unmodified arguments.
        self.assertEqual(delegate_tool.calls, [{"agent": "child", "prompt": "help"}])

    async def test_first_iteration_tool_call_is_scored_not_just_the_trailing_one(self):
        """Regression test for the P3 postmortem (docs/design/redesign-2026-09-17.md):
        a snapshot taken on `provider:request` never scored iteration 1's own
        tool call, because upstream appends the turn's user message to the
        mounted context *after* emitting iteration 1's `provider:request`
        (see `_run_turn`'s docstring-comment above and
        `docs/UPSTREAM_CONTRACT.md`). Under that bug this fixture -- an empty
        starting context, the candidate filename living only in the turn's
        own prompt -- produced a `shadow_proposed` for the *second*
        `provider:request` (after the tool already ran, with no further tool
        call to match against) and zero `shadow_observed`/`shadow_agreement`
        for the `fast_workspace` call that actually happened. Snapshotting
        in `on_tool_pre` instead fixes this: the proposal for the
        `fast_workspace` decision must resolve to a real `match`.
        """
        result, events, _delegate_tool = await _run_turn(
            backend="deterministic",
            allow_external_state=False,
            tmp_workspace=self._workspace.name,
            tmp_events=self._events_a.name,
        )
        self.assertEqual(result, "done")

        def of(suffix):
            return [e for e in events if e["event"].endswith(suffix)]

        workspace_agreements = [
            e
            for e in of("shadow_agreement")
            if e["data"].get("actual_tool") == "fast_workspace"
        ]
        self.assertEqual(
            len(workspace_agreements),
            1,
            "the fast_workspace tool call must have a matching shadow_agreement "
            "record, not just an unmatched trailing shadow_proposed",
        )
        self.assertEqual(workspace_agreements[0]["data"]["agreement"], "match")

    async def test_jev_backend_falls_back_once_per_decision_no_client_built(self):
        os.environ.pop("TYPESAFE_API_KEY", None)
        result, events, _delegate_tool = await _run_turn(
            backend="jev",
            allow_external_state=False,
            tmp_workspace=self._workspace.name,
            tmp_events=self._events_b.name,
        )
        self.assertEqual(result, "done")

        fallbacks = [
            e
            for e in events
            if e["event"].endswith("fallback")
            and e["data"].get("reason_code") == "external_state_not_enabled"
        ]
        self.assertGreaterEqual(len(fallbacks), 1)
        # "one per decision": grouping by decision_id, no decision is ever
        # double-counted.
        by_decision: dict[str, int] = {}
        for i, e in enumerate(fallbacks):
            key = str(e["data"].get("decision_id") or e.get("decision_id") or i)
            by_decision[key] = by_decision.get(key, 0) + 1
        for count in by_decision.values():
            self.assertEqual(count, 1)

        # No shadow_proposed/shadow_agreement -- the external gate closed
        # before any backend call.
        self.assertEqual(
            [e for e in events if e["event"].endswith("shadow_proposed")], []
        )


if __name__ == "__main__":
    unittest.main()
