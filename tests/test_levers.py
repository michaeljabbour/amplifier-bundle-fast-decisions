"""Cache keep-alive and loop-stop levers: receipt math, detection, and the loop wiring."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions import efficiency, levers
from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import Policy, TurnState
from amplifier_fast_decisions.demo import DemoCoordinator, demo_response
from amplifier_fast_decisions.orchestrator import HybridOrchestrator, ObservedTool, RoutedProvider, usage_fields
from amplifier_fast_decisions.runtime import Runtime, get_runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter

K = 1000
OPUS = "claude-opus-5-5"  # (4.0, 20.0, 0.20, 5.0) per MTok


class KeepaliveReceiptTests(unittest.TestCase):
    def _r(self, **kw):
        args = dict(model=OPUS, prefix_tokens=200 * K, refresh_costs=[0.05], tools=["bash"], gap_s=400.0,
                    next_cache_read=200 * K, next_model=OPUS, project="p", traffic="test")
        args.update(kw)
        return efficiency.cache_keepalive(**args)

    def test_confirmed_keepalive_saves_the_rewrite_minus_the_refresh(self):
        r = self._r()
        # Baseline: 200k written at $5/M = $1.00. Actual: $0.05 refresh + 200k read at $0.20/M = $0.04.
        self.assertEqual(r["decision"], "kept_cache_warm")
        self.assertAlmostEqual(r["baseline"]["cost_usd"], 1.0)
        self.assertAlmostEqual(r["actual"]["cost_usd"], 0.09)
        self.assertAlmostEqual(r["usd_saved"], 0.91)
        self.assertEqual(r["calls_saved"], -1)
        self.assertIsNone(r["seconds_saved"])
        self.assertIn("confirmed", r["method"])

    def test_shared_warm_prefix_is_not_claimed(self):
        # Measured live: 31,857 of 68,170 prefix tokens stayed warm without keep-alive (tools + static system).
        r = self._r(prefix_tokens=68_170, next_cache_read=68_170, refresh_costs=[0.01367], shared_warm_tokens=31_857)
        self.assertAlmostEqual(r["baseline"]["cost_usd"], (36_313 * 5.0 + 31_857 * 0.2) / 1e6, places=6)
        self.assertAlmostEqual(r["usd_saved"], 0.160634, places=5)
        self.assertEqual(r["baseline"]["shared_warm_tokens"], 31_857)

    def test_missed_keepalive_is_a_loss(self):
        r = self._r(next_cache_read=10 * K)
        self.assertEqual(r["decision"], "keepalive_missed")
        self.assertLess(r["usd_saved"], 0)

    def test_not_needed_when_the_wait_was_within_ttl(self):
        r = self._r(gap_s=200.0)
        self.assertEqual(r["decision"], "keepalive_not_needed")
        self.assertAlmostEqual(r["usd_saved"], -0.05)   # the refresh was wasted

    def test_unused_when_no_later_call_or_other_model(self):
        for kw in ({"next_cache_read": None, "next_model": None}, {"next_model": "claude-sonnet-5"}):
            r = self._r(refresh_costs=[0.05, 0.04], **kw)
            self.assertEqual(r["decision"], "keepalive_unused")
            self.assertAlmostEqual(r["usd_saved"], -0.09)
            self.assertEqual(r["calls_saved"], -2)

    def test_unknown_refresh_cost_makes_usd_unknown(self):
        self.assertIsNone(self._r(refresh_costs=[None])["usd_saved"])


class LoopReceiptTests(unittest.TestCase):
    def test_measured_and_unmeasured(self):
        r = efficiency.loop_stop(kinds=["sleep_timer", "repeat"], tools=["bash"], expected_further_calls=6,
                                 observed_calls=2, observed_usd=0.05, observed_seconds=8.0, marginal_call_usd=0.03,
                                 marginal_call_seconds=4.0, note_usd=0.001, host_model=OPUS, source="s",
                                 project="p", traffic="test")
        self.assertEqual((r["mechanism"], r["decision"]), ("rule:sleep_timer", "nudged_sleep_timer+repeat"))
        self.assertEqual(r["calls_saved"], 4)
        self.assertAlmostEqual(r["usd_saved"], 6 * 0.03 - (0.05 + 0.001))
        self.assertAlmostEqual(r["seconds_saved"], 24.0 - 8.0)
        u = efficiency.loop_stop(kinds=["failures"], tools=["bash"], expected_further_calls=1, observed_calls=None,
                                 observed_usd=None, observed_seconds=None, marginal_call_usd=None,
                                 marginal_call_seconds=None, note_usd=None, host_model=None, source="s",
                                 project="p", traffic="test")
        self.assertEqual(u["calls_saved"], 1)
        self.assertIsNone(u["usd_saved"])
        self.assertIn("unobservable", u["method"])


class DetectionTests(unittest.TestCase):
    def test_sleep_seconds(self):
        s = levers.sleep_seconds
        self.assertEqual(s("sleep 30 && tail -5 log"), 30)
        self.assertEqual(s("cd x && sleep 2m; cat y"), 120)
        self.assertIsNone(s("until grep -q done log; do sleep 5; done"))
        self.assertIsNone(s("echo nosleep 5"))
        self.assertIsNone(s("ls"))

    def test_repeat_needs_three_identical_calls_without_edit(self):
        w = levers.LoopWatch({})
        call = {"command": "git status"}
        w.observe("bash", call, True)
        w.observe("bash", call, True)
        w.observe("edit_file", {"path": "a"}, True)
        w.observe("bash", call, True)
        w.observe("bash", call, True)
        self.assertEqual(w.interventions, [])
        w.observe("bash", call, True)
        self.assertEqual([iv["kind"] for iv in w.interventions], ["repeat"])
        note = w.take_note()
        self.assertIn("identical", note)
        self.assertIsNone(w.take_note())
        w.observe("bash", call, True)
        self.assertEqual(w.interventions[0]["further"], 1)

    def test_failure_streak_and_measured_continuation(self):
        w = levers.LoopWatch({})
        for i in range(3):
            w.observe("bash", {"command": f"make t{i}"}, False)
        self.assertEqual(w.interventions[0]["kind"], "failures")
        w.take_note()
        w.observe("bash", {"command": "make -j2"}, False)
        w.observe("bash", {"command": "make clean"}, True)
        w.observe("bash", {"command": "make x"}, False)
        self.assertEqual(w.interventions[0]["further"], 1)

    def test_sleep_timer_on_second_call(self):
        w = levers.LoopWatch({})
        w.observe("bash", {"command": "sleep 20 && tail log"}, True)
        self.assertEqual(w.interventions, [])
        w.observe("bash", {"command": "sleep 25; tail log"}, True)
        self.assertEqual(w.interventions[0]["kind"], "sleep_timer")
        self.assertIn("timer", w.take_note())
        w.observe("bash", {"command": "sleep 3"}, True)   # under min_sleep_s
        w.observe("bash", {"command": "sleep 30"}, True)
        self.assertEqual(w.interventions[0]["further"], 1)

    def test_policy_validation(self):
        Policy(cache_keepalive={"interval_s": 200}, loop_stop={"repeat_threshold": 4})
        for bad in ({"cache_keepalive": {"interval_s": 400}}, {"cache_keepalive": {"nope": 1}},
                    {"loop_stop": {"repeat_threshold": 1}}, {"loop_stop": {"expected_further_calls": {"x": 1}}}):
            with self.assertRaises(ValueError):
                Policy(**bad)


class CacheProvider:
    """Anthropic-like double: a call reads what an earlier call cached if the
    last use was within ``ttl`` seconds, else writes it."""
    name = "anthropic-primary"
    default_model = OPUS

    def __init__(self, prefix, ttl):
        self.prefix, self.ttl, self.last_use, self.requests = prefix, ttl, None, []

    async def complete(self, request, **kwargs):
        import time
        now = time.monotonic()
        warm = self.last_use is not None and now - self.last_use < self.ttl
        self.last_use = now
        self.requests.append((request, kwargs))
        usage = {"input_tokens": self.prefix, "output_tokens": 1,
                 "cache_read_tokens": self.prefix if warm else 0,
                 "cache_write_tokens": 0 if warm else self.prefix}
        return NS(content=[], tool_calls=None, finish_reason="end_turn", usage=NS(**usage), model=None)


class SlowTool:
    def __init__(self, seconds, success=True):
        self.seconds, self.success = seconds, success

    async def execute(self, input, **kwargs):
        await asyncio.sleep(self.seconds)
        return NS(success=self.success, output="done")


def _service(policy):
    events = []
    coordinator = DemoCoordinator()
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(policy, ScriptedBackend(delay_ms=0), emitter, coordinator, [])
    return service, Runtime(service), events, coordinator


class KeepaliveLoopTests(unittest.IsolatedAsyncioTestCase):
    async def _turn(self, tool_seconds, ttl=0.5, interval=0.3, **cfg):
        policy = Policy(mode="off", read_shortcut=False,
                        cache_keepalive={"interval_s": interval, "min_prefix_tokens": 1000, **cfg})
        service, runtime, events, coordinator = _service(policy)
        provider = CacheProvider(100 * K, ttl)
        lv = levers.Levers(policy, service, lambda: ("proj", "test"), usage_fn=usage_fields)
        lv.ttl_s = ttl
        service.turn = TurnState("t")
        facade = RoutedProvider(provider, runtime, {}, demo_response, "anthropic-primary", levers=lv)
        tool = ObservedTool(SlowTool(tool_seconds), runtime, "bash", levers=lv)
        request = NS(messages=[{"role": "user", "content": "go"}], tools=[], max_output_tokens=None)
        await facade.complete(request)             # writes the cache
        await tool.execute({"command": "sleep"})   # long wait
        await facade.complete(NS(messages=request.messages + [{"role": "tool", "content": "done"}], tools=[]))
        await lv.finish("ok")
        return provider, events

    async def test_refreshes_during_long_tool_and_next_call_reads_cache(self):
        provider, events = await self._turn(tool_seconds=1.0)
        refreshes = [e for e in events if e["event"] == "fast_decisions:cache_refresh"]
        self.assertGreaterEqual(len(refreshes), 2)
        # Refresh re-sent the same messages with output capped at 1 token.
        refresh_request = provider.requests[1][0]
        self.assertEqual(refresh_request.messages, provider.requests[0][0].messages)
        self.assertEqual(refresh_request.max_output_tokens, 1)
        receipts = [e["data"] for e in events if e["event"] == efficiency.EVENT]
        self.assertEqual(len(receipts), 1)
        r = receipts[0]
        self.assertEqual((r["lever"], r["decision"]), ("cache_keepalive", "kept_cache_warm"))
        self.assertEqual(r["actual"]["calls"], len(refreshes))
        self.assertGreater(r["usd_saved"], 0)
        self.assertEqual(r["traffic"], "test")

    async def test_short_tool_sends_nothing(self):
        provider, events = await self._turn(tool_seconds=0.05)
        self.assertEqual(len(provider.requests), 2)
        self.assertFalse([e for e in events if e["event"] == efficiency.EVENT])

    async def test_cap_stops_refreshing(self):
        provider, events = await self._turn(tool_seconds=1.6, max_refreshes=1)
        self.assertEqual(len([e for e in events if e["event"] == "fast_decisions:cache_refresh"]), 1)
        r = next(e["data"] for e in events if e["event"] == efficiency.EVENT)
        self.assertEqual(r["decision"], "keepalive_missed")   # cache expired after the cap
        self.assertLess(r["usd_saved"], 0)


class LoopStopWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_note_injected_via_tool_post_and_receipt_at_turn_end(self):
        coordinator = DemoCoordinator()
        hooks = coordinator.hooks
        seen_notes = []

        class Upstream:
            async def execute(self, prompt, context, providers, tools, hooks, **kwargs):
                provider = providers["anthropic-primary"]
                for i in range(4):
                    await provider.complete(NS(messages=[{"role": "user", "content": "x"}], tools=[]))
                    await tools["bash"].execute({"command": "sleep 20 && tail log"})
                    for _, handler in hooks.handlers.get("tool:post", []):
                        result = await handler("tool:post", {"tool_name": "bash"})
                        if getattr(result, "action", None) == "inject_context":
                            seen_notes.append(result.context_injection)
                await provider.complete(NS(messages=[{"role": "user", "content": "x"}], tools=[]))
                return "done"

        with tempfile.TemporaryDirectory() as tmp:
            config = {"backend": "none", "events_dir": tmp, "mode": "off", "read_shortcut": False,
                      "loop_stop": {"enabled": True, "expected_further_calls": {"sleep_timer": 6}}}
            runtime, _ = get_runtime(coordinator, config, owner=True)
            events = []
            runtime.service.emitter.callback = events.append
            orch = HybridOrchestrator(config, coordinator, runtime, upstream=Upstream())
            orch.register_lifecycle_hooks(hooks)
            provider = CacheProvider(50 * K, 300)
            try:
                await orch.execute("hi", NS(), {"anthropic-primary": provider}, {"bash": SlowTool(0)}, hooks)
            finally:
                await runtime.close()
        self.assertEqual(len(seen_notes), 2)
        self.assertIn("sleep", seen_notes[0])
        self.assertIn("identical", seen_notes[1])
        receipts = [e["data"] for e in events if e["event"] == efficiency.EVENT and e["data"]["lever"] == "loop_stop"]
        # One receipt per turn: sleep_timer fired first (2nd call), repeat joined at the 3rd;
        # calls 3 and 4 continued the pattern after the note (the 5th call ended the turn).
        self.assertEqual(len(receipts), 1)
        r = receipts[0]
        self.assertEqual((r["mechanism"], r["decision"]), ("rule:sleep_timer", "nudged_sleep_timer+repeat"))
        self.assertEqual((r["baseline"]["calls"], r["actual"]["calls"], r["calls_saved"]), (6, 2, 4))
        self.assertTrue(r["actual"]["measured"])

    async def test_off_by_default_is_inert(self):
        policy = Policy(mode="off")
        service, runtime, events, _ = _service(policy)
        self.assertFalse(levers.Levers(policy, service, lambda: ("p", "test")).active)


class ReviewProvider:
    """Anthropic-style double for the review fixes: configurable name, latency,
    reported output tokens and thinking capabilities; tracks overlap."""

    def __init__(self, name="anthropic-primary", delay=0.0, output_tokens=1, caps=None, config=None):
        self.name, self.delay, self.output_tokens = name, delay, output_tokens
        self.default_model = OPUS
        self.config = config or {}
        self.requests, self.in_flight, self.max_in_flight = [], 0, 0
        if caps is not None:
            async def _caps(model):
                return caps
            self._get_request_capabilities = _caps

    async def complete(self, request, **kwargs):
        self.requests.append((request, kwargs))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        usage = {"input_tokens": 100 * K, "output_tokens": self.output_tokens, "cache_read_tokens": 100 * K,
                 "cache_write_tokens": 0}
        return NS(content=[], tool_calls=None, finish_reason="end_turn", usage=NS(**usage), model=None)


class Svc:
    def __init__(self):
        self.events = []

    async def emit(self, kind, data, *args):
        self.events.append((kind, data))


COLD = {"input_tokens": 100 * K, "output_tokens": 5, "cache_read_tokens": 0, "cache_write_tokens": 100 * K}


class ReviewFixTests(unittest.IsolatedAsyncioTestCase):
    """Fixes M1-M6, O1-O3 from the keep-alive review; each has a must-not-fire case."""

    def _levers(self, shared_warm=None, **cfg):
        policy = Policy(mode="off", cache_keepalive={"interval_s": 0.1, "min_prefix_tokens": 1000, **cfg})
        svc = Svc()
        lv = levers.Levers(policy, svc, lambda: ("p", "test"), usage_fn=usage_fields, shared_warm=shared_warm)
        return lv, svc

    async def _capture(self, lv, provider, request=None, kwargs=None, usage=None, key="anthropic-primary"):
        import time
        request = request or NS(messages=[{"role": "user", "content": "go"}], max_output_tokens=None, metadata=None)
        await lv.after_call(provider, request, kwargs or {}, usage or COLD, time.monotonic(), 1.0, provider_key=key)
        return request

    async def _wait(self, lv, seconds):
        lv.tool_started(1, "bash")
        await asyncio.sleep(seconds)
        lv.tool_finished(1)

    def _refreshes(self, svc):
        return [d for k, d in svc.events if k == "cache_refresh"]

    # M1
    async def test_clone_never_streams_and_is_marked(self):
        lv, _ = self._levers()
        p = ReviewProvider()
        req = NS(messages=[{"role": "user", "content": "go"}], max_output_tokens=None, metadata={"trace": "x"})
        await self._capture(lv, p, request=req)
        clone = lv._clone(lv.last)
        self.assertIs(clone.metadata["stream"], False)
        self.assertEqual(clone.metadata["fast_decisions"], "cache_keepalive")
        self.assertEqual(clone.metadata["trace"], "x")
        self.assertEqual(req.metadata, {"trace": "x"})   # original untouched

    # M2a
    async def test_manual_thinking_is_skipped_adaptive_only_is_not(self):
        manual = NS(supports_thinking=True, requires_adaptive_thinking=False, thinking_always_on=False)
        adaptive = NS(supports_thinking=True, requires_adaptive_thinking=True, thinking_always_on=False)
        for caps, kwargs, expect in ((manual, {"extended_thinking": True}, 0),
                                     (None, {"extended_thinking": True}, 0),      # capabilities unknown
                                     (adaptive, {"extended_thinking": True}, 1),
                                     (manual, {}, 1)):                            # thinking off: cap honored
            lv, svc = self._levers(max_refreshes=1)
            p = ReviewProvider(caps=caps)
            await self._capture(lv, p, kwargs=kwargs)
            await self._wait(lv, 0.25)
            await lv.finish("ok")
            self.assertEqual(len(p.requests), expect, (caps, kwargs))
        lv, _ = self._levers()
        await self._capture(lv, ReviewProvider(caps=manual, config={"reasoning_effort": "low"}))
        self.assertEqual(lv.last["skip"], "manual_thinking")

    # M2b
    async def test_cap_exceeded_stops_the_episode(self):
        lv, svc = self._levers()
        p = ReviewProvider(output_tokens=900)
        await self._capture(lv, p)
        await self._wait(lv, 0.45)
        await lv.finish("ok")
        self.assertEqual([d["status"] for d in self._refreshes(svc)], ["cap_exceeded"])
        self.assertEqual(len(p.requests), 1)

    # M3
    async def test_real_call_waits_for_in_flight_refresh_one_receipt(self):
        policy = Policy(mode="off", read_shortcut=False,
                        cache_keepalive={"interval_s": 0.1, "min_prefix_tokens": 1000})
        service, runtime, events, _ = _service(policy)
        lv = levers.Levers(policy, service, lambda: ("p", "test"), usage_fn=usage_fields, shared_warm=0)
        service.turn = TurnState("t")
        p = ReviewProvider(delay=0.3)
        facade = RoutedProvider(p, runtime, {}, demo_response, "anthropic-primary", levers=lv)
        req = NS(messages=[{"role": "user", "content": "go"}], tools=[], max_output_tokens=None)
        p.delay = 0.0
        await facade.complete(req)
        p.delay = 0.3
        lv.tool_started(1, "bash")
        await asyncio.sleep(0.15)          # refresh in flight
        self.assertTrue(lv._refreshing)
        lv.tool_finished(1)                # tool ends mid-refresh
        await facade.complete(NS(messages=req.messages + [{"role": "tool", "content": "ok"}], tools=[]))
        await lv.finish("ok")
        self.assertEqual(p.max_in_flight, 1)   # never concurrent
        receipts = [e["data"] for e in events if e["event"] == efficiency.EVENT]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["actual"]["refresh_calls"], 1)

    # M4
    async def test_floor_applies_to_the_unshared_prefix(self):
        for shared, expect in ((95 * K, 0), (50 * K, 1)):   # 100k prefix: 5k vs 50k unshared, floor 20k
            lv, svc = self._levers(shared_warm=shared, min_prefix_tokens=20_000, max_refreshes=1)
            p = ReviewProvider()
            await self._capture(lv, p)
            await self._wait(lv, 0.25)
            await lv.finish("ok")
            self.assertEqual(len(p.requests), expect, shared)

    # M5
    async def test_no_refresh_after_finish(self):
        lv, svc = self._levers()
        p = ReviewProvider()
        await self._capture(lv, p)
        await lv.finish("ok")
        await self._wait(lv, 0.35)
        await self._capture(lv, p)
        self.assertEqual(p.requests, [])
        self.assertIsNone(lv._task)

    # M6
    async def test_anthropic_only(self):
        for name, key, model, expect in (("openai", "openai-primary", OPUS, 0),
                                         ("anthropic", "anthropic-primary", "some-unpriced-model", 0),
                                         ("anthropic", "anthropic-primary", OPUS, 1)):
            lv, svc = self._levers(max_refreshes=1)
            p = ReviewProvider(name=name)
            p.default_model = model
            await self._capture(lv, p, key=key)
            await self._wait(lv, 0.25)
            await lv.finish("ok")
            self.assertEqual(len(p.requests), expect, (name, model))

    # O1
    async def test_finish_does_not_wait_long_and_survives_cancel(self):
        import time
        lv, svc = self._levers()
        p = ReviewProvider(delay=10.0)
        await self._capture(lv, p)
        lv.tool_started(1, "bash")
        await asyncio.sleep(0.2)
        self.assertTrue(lv._refreshing)
        t = time.monotonic()
        await lv.finish("cancelled")
        self.assertLess(time.monotonic() - t, 3.0)
        # A cancel arriving during finish's bounded wait must not skip cleanup.
        lv2, svc2 = self._levers()
        p2 = ReviewProvider(delay=10.0)
        await self._capture(lv2, p2)
        lv2.tool_started(1, "bash")
        await asyncio.sleep(0.2)
        task = asyncio.ensure_future(lv2.finish("cancelled"))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        self.assertTrue(lv2._closed)
        self.assertTrue(lv2._task.cancelled() or lv2._task.done())

    # O2
    async def test_messages_copied_at_capture(self):
        lv, _ = self._levers()
        msgs = [{"role": "user", "content": "go"}]
        await self._capture(lv, ReviewProvider(), request=NS(messages=msgs, max_output_tokens=None, metadata=None))
        msgs.append({"role": "assistant", "content": "MUTATED"})
        self.assertEqual([m["content"] for m in lv._clone(lv.last).messages], ["go"])

    # O3
    async def test_side_calls_neither_capture_nor_settle(self):
        lv, _ = self._levers()
        p = ReviewProvider()
        real = await self._capture(lv, p)
        side = NS(messages=[{"role": "user", "content": "goal?"}], max_output_tokens=10, metadata={"stream": False})
        lv.episode = {"model": OPUS, "prefix": 100 * K, "refreshes": [0.01], "tools": {"bash"}, "cache_used": 0.0,
                      "anchor": 0.0}
        await self._capture(lv, p, request=side)
        self.assertIs(lv.last["request"], real)
        self.assertIsNotNone(lv.episode)      # still open for the next real call
        self.assertEqual(lv.calls, 1)


if __name__ == "__main__":
    unittest.main()
