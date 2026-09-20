"""HC03: phase-specific effort routing. No amplifier_core, no network."""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions import effort
from amplifier_fast_decisions.contracts import Policy, TurnState
from amplifier_fast_decisions.demo import DemoProvider, demo_response
from amplifier_fast_decisions.orchestrator import RoutedProvider
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.telemetry import Emitter


def user(content="Fix the bug"):
    return {"role": "user", "content": content}


def assistant(tool_calls=None, content=""):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def tool_result(content="ok"):
    return {"role": "tool", "content": content}


def call(name, call_id="c1"):
    return {"id": call_id, "name": name}


def call_obj(name, call_id="c1"):
    """Object-shaped tool call, mirroring an SDK model with a nested `.function.name`."""
    return NS(id=call_id, function=NS(name=name))


def request(messages):
    return NS(messages=messages, tools=[], tool_choice="auto", model="pinned-model")


class ClassifyPhaseTests(unittest.TestCase):
    def test_orient_first_request_of_turn(self):
        self.assertEqual(effort.classify_phase(request([user()])), effort.PHASE_ORIENT)

    def test_orient_when_no_messages(self):
        self.assertEqual(effort.classify_phase(request([])), effort.PHASE_ORIENT)

    def test_explore_after_read_like_tool_call(self):
        messages = [user(), assistant(tool_calls=[call("read_file")]), tool_result()]
        self.assertEqual(effort.classify_phase(request(messages)), effort.PHASE_EXPLORE)

    def test_explore_with_multiple_read_like_tools(self):
        messages = [
            user(),
            assistant(tool_calls=[call("grep")]),
            tool_result(),
            assistant(tool_calls=[call("glob")]),
            tool_result(),
        ]
        self.assertEqual(effort.classify_phase(request(messages)), effort.PHASE_EXPLORE)

    def test_implement_after_write_like_tool_call(self):
        messages = [user(), assistant(tool_calls=[call("edit_file")]), tool_result()]
        self.assertEqual(
            effort.classify_phase(request(messages)), effort.PHASE_IMPLEMENT
        )

    def test_implement_once_write_seen_even_if_later_reads_follow(self):
        messages = [
            user(),
            assistant(tool_calls=[call("edit_file")]),
            tool_result(),
            assistant(tool_calls=[call("read_file")]),
            tool_result(),
        ]
        self.assertEqual(
            effort.classify_phase(request(messages)), effort.PHASE_IMPLEMENT
        )

    def test_unknown_tool_treated_as_write_like(self):
        messages = [
            user(),
            assistant(tool_calls=[call("some_future_tool")]),
            tool_result(),
        ]
        self.assertEqual(
            effort.classify_phase(request(messages)), effort.PHASE_IMPLEMENT
        )

    def test_verify_bash_treated_as_implement(self):
        messages = [
            user(),
            assistant(tool_calls=[call("bash")]),
            tool_result("pytest passed"),
        ]
        self.assertEqual(
            effort.classify_phase(request(messages)), effort.PHASE_IMPLEMENT
        )

    def test_messages_before_last_user_message_ignored(self):
        # An old turn's write-like tool call must not leak into this turn's
        # classification once a new user message starts a fresh turn. In the
        # installed loop a turn ends with an assistant message WITHOUT tool
        # calls; the next user message opens the new turn.
        messages = [
            user("Old task"),
            assistant(tool_calls=[call("edit_file")]),
            tool_result(),
            assistant(),
            user("New task"),
        ]
        self.assertEqual(effort.classify_phase(request(messages)), effort.PHASE_ORIENT)

    def test_user_message_right_after_a_tool_result_is_a_continuation(self):
        # Hook reminders and steering arrive as user messages mid-turn; they
        # must not reset the turn (otherwise every request looks like the
        # first one, as observed live in campaign run HC03).
        messages = [
            user("Task"),
            assistant(tool_calls=[call("edit_file")]),
            tool_result(),
            user("<system-reminder/>"),
        ]
        self.assertEqual(effort.classify_phase(request(messages)), effort.PHASE_IMPLEMENT)

    def test_object_shaped_messages_and_tool_calls(self):
        messages = [
            NS(role="user", content="Fix it"),
            NS(role="assistant", content="", tool_calls=[call_obj("read_file")]),
            NS(role="tool", content="ok"),
        ]
        self.assertEqual(effort.classify_phase(request(messages)), effort.PHASE_EXPLORE)

    def test_dict_message_with_object_tool_call_mixed_shapes(self):
        messages = [
            user(),
            {"role": "assistant", "content": "", "tool_calls": [call_obj("grep")]},
            tool_result(),
        ]
        self.assertEqual(effort.classify_phase(request(messages)), effort.PHASE_EXPLORE)

    def test_assistant_text_only_no_tool_calls_is_not_explore(self):
        messages = [user(), assistant(content="Thinking about it...")]
        self.assertEqual(
            effort.classify_phase(request(messages)), effort.PHASE_IMPLEMENT
        )


class DecideEffortTests(unittest.TestCase):
    def setUp(self):
        self.routing = {
            "explore": "low",
            "max_explore_requests": 6,
            "escalate_after_provider_errors": 1,
        }

    def test_explore_applies_low_effort(self):
        applied, reason = effort.decide_effort(
            effort.PHASE_EXPLORE,
            self.routing,
            explore_requests=1,
            provider_errors_seen=0,
            host_pinned=False,
        )
        self.assertEqual(applied, "low")
        self.assertEqual(reason, effort.REASON_PHASE_POLICY)

    def test_non_explore_phase_untouched(self):
        for phase in (effort.PHASE_ORIENT, effort.PHASE_IMPLEMENT):
            applied, reason = effort.decide_effort(
                phase,
                self.routing,
                explore_requests=1,
                provider_errors_seen=0,
                host_pinned=False,
            )
            self.assertIsNone(applied)
            self.assertEqual(reason, effort.REASON_DEFAULT_EFFORT)

    def test_seventh_explore_request_escalates_past_max(self):
        # First 6 (1-indexed) apply; the 7th does not.
        for i in range(1, 7):
            applied, reason = effort.decide_effort(
                effort.PHASE_EXPLORE,
                self.routing,
                explore_requests=i,
                provider_errors_seen=0,
                host_pinned=False,
            )
            self.assertEqual(applied, "low", f"request {i} should still apply")
            self.assertEqual(reason, effort.REASON_PHASE_POLICY)
        applied, reason = effort.decide_effort(
            effort.PHASE_EXPLORE,
            self.routing,
            explore_requests=7,
            provider_errors_seen=0,
            host_pinned=False,
        )
        self.assertIsNone(applied)
        self.assertEqual(reason, effort.REASON_ESCALATED_MAX_EXPLORE)

    def test_escalates_after_provider_error(self):
        applied, reason = effort.decide_effort(
            effort.PHASE_EXPLORE,
            self.routing,
            explore_requests=1,
            provider_errors_seen=1,
            host_pinned=False,
        )
        self.assertIsNone(applied)
        self.assertEqual(reason, effort.REASON_ESCALATED_AFTER_ERROR)

    def test_host_pinned_request_untouched(self):
        applied, reason = effort.decide_effort(
            effort.PHASE_EXPLORE,
            self.routing,
            explore_requests=1,
            provider_errors_seen=0,
            host_pinned=True,
        )
        self.assertIsNone(applied)
        self.assertEqual(reason, effort.REASON_HOST_PINNED)

    def test_missing_explore_effort_leaves_default(self):
        applied, reason = effort.decide_effort(
            effort.PHASE_EXPLORE,
            {},
            explore_requests=1,
            provider_errors_seen=0,
            host_pinned=False,
        )
        self.assertIsNone(applied)
        self.assertEqual(reason, effort.REASON_DEFAULT_EFFORT)


class PolicyValidationTests(unittest.TestCase):
    def test_none_and_empty_are_valid(self):
        Policy(effort_routing=None)
        Policy(effort_routing={})

    def test_invalid_effort_string_raises(self):
        with self.assertRaises(ValueError):
            Policy(effort_routing={"explore": "ludicrous"})

    def test_invalid_max_explore_requests_raises(self):
        with self.assertRaises(ValueError):
            Policy(effort_routing={"explore": "low", "max_explore_requests": 0})

    def test_invalid_escalate_after_provider_errors_raises(self):
        with self.assertRaises(ValueError):
            Policy(
                effort_routing={"explore": "low", "escalate_after_provider_errors": -1}
            )

    def test_valid_routing_accepted(self):
        Policy(
            effort_routing={
                "explore": "low",
                "max_explore_requests": 6,
                "escalate_after_provider_errors": 1,
            }
        )


def setup_service(*, policy=None):
    from amplifier_fast_decisions.demo import DemoCoordinator

    events = []
    coordinator = DemoCoordinator()
    policy = policy or Policy(
        mode="active", allowed_tools=("demo_inspect",), allow_synthetic_active=True
    )
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(
        policy, ScriptedBackend(delay_ms=0), emitter, coordinator, []
    )
    service.turn = TurnState("test-turn")
    runtime = Runtime(service)
    return service, runtime, events


class RoutedProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Fake provider + fake emitter integration -- no amplifier_core required."""

    async def test_explore_request_gets_low_effort_and_emits_event(self):
        policy = Policy(
            mode="off", effort_routing={"explore": "low", "max_explore_requests": 6}
        )
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        messages = [user(), assistant(tool_calls=[call("read_file")]), tool_result()]
        req = request(messages)

        response = await facade.complete(req)

        self.assertEqual(provider.calls, 1)
        self.assertEqual(getattr(req, "reasoning_effort", None), "low")
        routed = [e for e in events if e["event"].endswith("effort_routed")]
        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["data"]["phase"], "explore")
        self.assertEqual(routed[0]["data"]["requested_effort"], "low")
        self.assertEqual(routed[0]["data"]["default_effort"], "provider_default")
        self.assertEqual(routed[0]["data"]["reason_code"], "phase_policy")
        self.assertEqual(routed[0]["data"]["explore_requests"], 1)
        self.assertIn("provider_call_id", routed[0]["data"])
        self.assertIsNotNone(response)

    async def test_routing_disabled_leaves_request_untouched_and_emits_no_event(self):
        policy = Policy(mode="off", effort_routing=None)
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        messages = [user(), assistant(tool_calls=[call("read_file")]), tool_result()]
        req = request(messages)

        await facade.complete(req)

        self.assertFalse(hasattr(req, "reasoning_effort"))
        self.assertFalse(any(e["event"].endswith("effort_routed") for e in events))

    async def test_implement_phase_request_untouched(self):
        policy = Policy(
            mode="off", effort_routing={"explore": "low", "max_explore_requests": 6}
        )
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        messages = [user(), assistant(tool_calls=[call("edit_file")]), tool_result()]
        req = request(messages)

        await facade.complete(req)

        self.assertFalse(hasattr(req, "reasoning_effort"))
        routed = [e for e in events if e["event"].endswith("effort_routed")]
        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["data"]["phase"], "implement")
        self.assertIsNone(routed[0]["data"]["requested_effort"])
        self.assertEqual(routed[0]["data"]["reason_code"], "default_effort")

    async def test_host_pinned_request_untouched(self):
        policy = Policy(
            mode="off", effort_routing={"explore": "low", "max_explore_requests": 6}
        )
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        messages = [user(), assistant(tool_calls=[call("read_file")]), tool_result()]
        req = request(messages)
        req.reasoning_effort = "max"

        await facade.complete(req)

        self.assertEqual(req.reasoning_effort, "max")
        routed = [e for e in events if e["event"].endswith("effort_routed")]
        self.assertEqual(routed[0]["data"]["reason_code"], "host_pinned")
        self.assertIsNone(routed[0]["data"]["requested_effort"])

    async def test_escalates_after_max_explore_requests_across_turn(self):
        policy = Policy(
            mode="off", effort_routing={"explore": "low", "max_explore_requests": 2}
        )
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        messages = [user(), assistant(tool_calls=[call("read_file")]), tool_result()]

        for _ in range(3):
            req = request(list(messages))
            await facade.complete(req)

        routed = [e for e in events if e["event"].endswith("effort_routed")]
        self.assertEqual(len(routed), 3)
        self.assertEqual(
            [r["data"]["reason_code"] for r in routed],
            ["phase_policy", "phase_policy", "escalated_max_explore"],
        )
        self.assertEqual([r["data"]["explore_requests"] for r in routed], [1, 2, 3])

    async def test_never_touches_model(self):
        policy = Policy(
            mode="off", effort_routing={"explore": "low", "max_explore_requests": 6}
        )
        service, runtime, events = setup_service(policy=policy)
        provider = DemoProvider(delay_ms=0)
        facade = RoutedProvider(provider, runtime, {}, demo_response)
        messages = [user(), assistant(tool_calls=[call("read_file")]), tool_result()]
        req = request(messages)

        await facade.complete(req)

        self.assertEqual(req.model, "pinned-model")


if __name__ == "__main__":
    unittest.main()



class LiveLoopShapeTests(unittest.TestCase):
    """Regression: the installed loop's real message shapes (observed in campaign run HC03)."""

    @staticmethod
    def _user(text="hi"):
        return {"role": "user", "content": [{"type": "text", "text": text}]}

    @staticmethod
    def _assistant(*tool_names, text=None):
        blocks = [{"type": "thinking", "thinking": "..."}]
        if text:
            blocks.append({"type": "text", "text": text})
        blocks += [{"type": "tool_call", "id": f"t{i}", "name": n, "input": {}} for i, n in enumerate(tool_names)]
        return {"role": "assistant", "content": blocks}

    @staticmethod
    def _tool(i=0):
        return {"role": "tool", "tool_call_id": f"t{i}", "content": [{"type": "tool_result", "tool_call_id": f"t{i}", "content": "..."}]}

    def test_hook_reminder_user_messages_do_not_reset_the_turn(self):
        # U(reminder) U(prompt) A(read x3) T T T U(reminder) A(read) T  -> explore, not orient
        messages = [self._user("<system-reminder/>"), self._user("Read README.md first"),
                    self._assistant("read_file", "read_file", "read_file"), self._tool(0), self._tool(1), self._tool(2),
                    self._user("<system-reminder source=hooks-python-check/>"),
                    self._assistant("read_file"), self._tool(0)]
        self.assertEqual(effort.classify_phase(NS(messages=messages)), effort.PHASE_EXPLORE)

    def test_tool_result_carrier_user_messages_do_not_reset_the_turn(self):
        # Anthropic-style: tool results carried in user-role messages
        carrier = {"role": "user", "content": [{"type": "tool_result", "tool_call_id": "t0", "content": "..."}]}
        messages = [self._user("task"), self._assistant("read_file"), carrier, self._user("<reminder/>"), self._assistant("glob"), carrier]
        self.assertEqual(effort.classify_phase(NS(messages=messages)), effort.PHASE_EXPLORE)

    def test_tool_call_content_blocks_mark_implement(self):
        messages = [self._user("task"), self._assistant("read_file"), self._tool(0), self._assistant("edit_file"), self._tool(0)]
        self.assertEqual(effort.classify_phase(NS(messages=messages)), effort.PHASE_IMPLEMENT)

    def test_new_prompt_after_a_finished_turn_is_orient(self):
        messages = [self._user("task"), self._assistant("edit_file"), self._tool(0), self._assistant(text="done"), self._user("now do X")]
        self.assertEqual(effort.classify_phase(NS(messages=messages)), effort.PHASE_ORIENT)

    def test_first_request_of_turn_is_orient(self):
        self.assertEqual(effort.classify_phase(NS(messages=[self._user("<reminder/>"), self._user("task")])), effort.PHASE_ORIENT)



class PerPhaseRoutingTests(unittest.TestCase):
    def test_implement_and_orient_phases_can_be_routed(self):
        routing = {"orient": "medium", "explore": "low", "implement": "high", "escalate_after_provider_errors": 1}
        self.assertEqual(effort.decide_effort("implement", routing, explore_requests=0, provider_errors_seen=0, host_pinned=False), ("high", effort.REASON_PHASE_POLICY))
        self.assertEqual(effort.decide_effort("orient", routing, explore_requests=0, provider_errors_seen=0, host_pinned=False), ("medium", effort.REASON_PHASE_POLICY))
        self.assertEqual(effort.decide_effort("implement", routing, explore_requests=0, provider_errors_seen=1, host_pinned=False), (None, effort.REASON_ESCALATED_AFTER_ERROR))
        self.assertEqual(effort.decide_effort("implement", {"explore": "low"}, explore_requests=0, provider_errors_seen=0, host_pinned=False), (None, effort.REASON_DEFAULT_EFFORT))

    def test_validation_rejects_unknown_keys_and_bad_levels(self):
        from amplifier_fast_decisions.contracts import validate_effort_routing
        validate_effort_routing({"orient": "medium", "implement": "high"})
        with self.assertRaises(ValueError):
            validate_effort_routing({"implement": "turbo"})
        with self.assertRaises(ValueError):
            validate_effort_routing({"verify": "low"})


class _OnlyUnderPrefixFinder:
    """Meta path finder that forces ``amplifier_module_loop_streaming`` to be
    resolvable ONLY from directories under a given prefix (our temp cache
    dirs), regardless of whether a real distribution is installed elsewhere
    on sys.path.

    This makes ``_import_upstream_loop``'s fallback-to-cache branch
    exercisable deterministically in every environment: locally (upstream not
    installed, where the plain import already fails on its own) and in the
    `upstream` / `upstream-main` CI jobs (where amplifier_module_loop_streaming
    IS pip installed from git @main, so the plain import would otherwise
    succeed immediately and never reach the cache-search fallback this test
    means to prove).
    """

    TARGET = "amplifier_module_loop_streaming"

    def __init__(self, allowed_prefix: str):
        self.allowed_prefix = allowed_prefix

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.TARGET:
            return None  # defer to normal resolution for anything else
        import importlib.machinery
        import sys

        candidate_paths = [p for p in sys.path if p.startswith(self.allowed_prefix)]
        spec = importlib.machinery.PathFinder.find_spec(fullname, candidate_paths)
        if spec is None:
            # Raising here (rather than returning None) prevents the import
            # machinery from falling through to an installed distribution.
            raise ImportError(f"{fullname} blocked outside {self.allowed_prefix} (test-forced)")
        return spec


class UpstreamLoopImportTests(unittest.TestCase):
    def test_falls_back_to_module_cache_checkout(self):
        import sys
        import tempfile
        import textwrap
        from pathlib import Path

        from amplifier_fast_decisions import orchestrator

        saved = sys.modules.pop("amplifier_module_loop_streaming", None)
        with tempfile.TemporaryDirectory() as tmp:
            finder = _OnlyUnderPrefixFinder(tmp)
            sys.meta_path.insert(0, finder)
            try:
                cache = Path(tmp)
                mod = cache / "amplifier-module-loop-streaming-deadbeef" / "amplifier_module_loop_streaming"
                mod.mkdir(parents=True)
                (mod / "__init__.py").write_text(
                    textwrap.dedent(
                        """
                    class StreamingOrchestrator:
                        def __init__(self, config): self.config = config
                """
                    )
                )
                cls = orchestrator._import_upstream_loop(cache_root=cache)
                self.assertEqual(cls.__name__, "StreamingOrchestrator")
                self.assertTrue(
                    getattr(cls, "__module__", "").startswith("amplifier_module_loop_streaming"),
                    "expected the cache checkout's class, not an installed distribution",
                )
                sys.modules.pop("amplifier_module_loop_streaming", None)
                for entry in list(sys.path):
                    if entry.startswith(tmp):
                        sys.path.remove(entry)
                with tempfile.TemporaryDirectory() as empty:
                    with self.assertRaises(RuntimeError):
                        orchestrator._import_upstream_loop(cache_root=Path(empty))
            finally:
                sys.meta_path.remove(finder)
                sys.modules.pop("amplifier_module_loop_streaming", None)
                if saved is not None:
                    sys.modules["amplifier_module_loop_streaming"] = saved
