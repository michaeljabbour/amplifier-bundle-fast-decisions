"""Unit tests for the shadow scorer (P3, docs/design/redesign-2026-09-17.md).

Covers observer.py's ShadowScorer (the critical-path snapshot) and
shadow.py's ShadowWorker (the off-critical-path scoring/join). All offline;
no real kernel, no network.
"""
from __future__ import annotations
import asyncio
import tempfile
import time
import unittest

from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.contracts import Candidate, Policy, digest
from amplifier_fast_decisions.demo import DemoCoordinator, DemoContext, DemoTool
from amplifier_fast_decisions.observer import ShadowScorer
from amplifier_fast_decisions.runtime import get_runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.shadow import ShadowJob, ShadowOutcome, ShadowWorker
from amplifier_fast_decisions.telemetry import Emitter


def make_service(events, *, backend=None, allow_external_state=False):
    coordinator = DemoCoordinator()
    policy = Policy(mode="shadow", allowed_tools=("demo_inspect",), allow_external_state=allow_external_state)
    emitter = Emitter(coordinator.session_id, callback=events.append)
    service = DecisionService(policy, backend or ScriptedBackend(delay_ms=0), emitter, coordinator, [])
    return service, coordinator


def make_job(decision_id="d1", candidates=()):
    return ShadowJob(kind="turn", turn_id="t", decision_id=decision_id, state={},
                      candidates=candidates, questions=(), state_source="context_mount",
                      state_hash="h", state_revision=0)


class ShadowWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_overflow_is_counted_not_blocking(self):
        events = []
        service, _ = make_service(events)
        worker = ShadowWorker(service, capacity=64)
        results = [worker.submit(make_job(f"d{i}")) for i in range(65)]
        self.assertEqual(results.count(False), 1)
        self.assertEqual(worker.dropped_shadow_jobs, 1)
        self.assertEqual(worker.health, {"dropped_shadow_jobs": 1, "pending": 64})

    async def test_agreement_match_and_mismatch(self):
        candidate = Candidate("read_x", "Read x", "demo_inspect", {"target": "x"})

        events = []
        service, _ = make_service(events, backend=ScriptedBackend([{"choice": "read_x"}], delay_ms=0))
        worker = ShadowWorker(service, capacity=8)
        await worker._score(make_job("d1", candidates=(candidate,)))
        await worker._handle_outcome(ShadowOutcome(
            decision_id="d1", actual_tool="demo_inspect", actual_arguments_hash=digest({"target": "x"})))
        agreements = [e for e in events if e["event"].endswith("shadow_agreement")]
        self.assertEqual(len(agreements), 1)
        self.assertEqual(agreements[0]["data"]["agreement"], "match")
        self.assertTrue(agreements[0]["data"]["would_have_avoided_llm_turn"])
        self.assertEqual(agreements[0]["data"]["domain"], "tool-choice")

    async def test_shadow_proposed_carries_domain_and_state_chars(self):
        candidate = Candidate("read_x", "Read x", "demo_inspect", {"target": "x"})
        events = []
        service, _ = make_service(events, backend=ScriptedBackend([{"choice": "read_x"}], delay_ms=0))
        worker = ShadowWorker(service, capacity=8)
        await worker._score(make_job("d1", candidates=(candidate,)))
        proposed = [e for e in events if e["event"].endswith("shadow_proposed")]
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["data"]["domain"], "tool-choice")
        self.assertIsInstance(proposed[0]["data"]["state_chars"], int)

    async def test_shadow_proposed_workspace_candidates_are_read_target(self):
        candidate = Candidate("read_ws", "Read ws", "fast_workspace", {"operation": "read", "path": "x"})
        events = []
        service, _ = make_service(events, backend=ScriptedBackend([{"choice": "read_ws"}], delay_ms=0))
        worker = ShadowWorker(service, capacity=8)
        await worker._score(make_job("d1", candidates=(candidate,)))
        proposed = [e for e in events if e["event"].endswith("shadow_proposed")]
        self.assertEqual(proposed[0]["data"]["domain"], "read-target")

    async def test_allow_external_state_only_on_first_shadow_proposed_per_turn(self):
        candidate = Candidate("read_x", "Read x", "demo_inspect", {"target": "x"})
        events = []
        service, _ = make_service(events, backend=ScriptedBackend([{"choice": "read_x"}], delay_ms=0))
        worker = ShadowWorker(service, capacity=8)
        job1 = ShadowJob(kind="turn", turn_id="t1", decision_id="d1", state={},
                          candidates=(candidate,), questions=(), state_source="context_mount",
                          state_hash="h", state_revision=0)
        job2 = ShadowJob(kind="turn", turn_id="t1", decision_id="d2", state={},
                          candidates=(candidate,), questions=(), state_source="context_mount",
                          state_hash="h", state_revision=0)
        await worker._score(job1)
        await worker._score(job2)
        proposed = [e for e in events if e["event"].endswith("shadow_proposed")]
        self.assertEqual(len(proposed), 2)
        self.assertIn("allow_external_state", proposed[0]["data"])
        self.assertNotIn("allow_external_state", proposed[1]["data"])

        # A new turn_id gets its own first-shadow_proposed field.
        job3 = ShadowJob(kind="turn", turn_id="t2", decision_id="d3", state={},
                          candidates=(candidate,), questions=(), state_source="context_mount",
                          state_hash="h", state_revision=0)
        await worker._score(job3)
        proposed3 = [e for e in events if e["event"].endswith("shadow_proposed")][-1]
        self.assertIn("allow_external_state", proposed3["data"])

        events2 = []
        service2, _ = make_service(events2, backend=ScriptedBackend([{"choice": "read_x"}], delay_ms=0))
        worker2 = ShadowWorker(service2, capacity=8)
        await worker2._score(make_job("d2", candidates=(candidate,)))
        await worker2._handle_outcome(ShadowOutcome(
            decision_id="d2", actual_tool="demo_inspect", actual_arguments_hash=digest({"target": "other"})))
        mismatches = [e for e in events2 if e["event"].endswith("shadow_agreement")]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["data"]["agreement"], "mismatch")
        self.assertFalse(mismatches[0]["data"]["would_have_avoided_llm_turn"])

    async def test_external_state_gate_still_applies(self):
        constructed: list[bool] = []

        class ExternalBackend:
            name = "external-demo"
            external = True

            async def ask(self, request):
                constructed.append(True)
                raise AssertionError("must never be called while allow_external_state is False")

        events = []
        service, _ = make_service(events, backend=ExternalBackend(), allow_external_state=False)
        worker = ShadowWorker(service, capacity=8)
        candidate = Candidate("read_x", "Read x", "demo_inspect", {"target": "x"})
        await worker._score(make_job("d1", candidates=(candidate,)))

        self.assertEqual(constructed, [])
        fallbacks = [e for e in events if e["event"].endswith("fallback")]
        self.assertTrue(any(e["data"].get("reason_code") == "external_state_not_enabled" for e in fallbacks))


class ShadowScorerTests(unittest.IsolatedAsyncioTestCase):
    async def _make_scorer(self, config=None):
        coordinator = DemoCoordinator()
        context = DemoContext()
        await coordinator.mount("context", context)
        await coordinator.mount("tools", {"demo_inspect": DemoTool()})
        cfg = {"backend": "unavailable", "events_dir": tempfile.mkdtemp(),
               "allowed_tools": ["demo_inspect"],
               "candidates": [{"id": "read_x", "label": "Read x", "tool": "demo_inspect",
                                "arguments": {"target": "x"}}],
               **(config or {})}
        runtime, _ = get_runtime(coordinator, cfg)
        scorer = ShadowScorer(runtime, coordinator, cfg)
        return scorer, runtime, coordinator, context

    async def test_handlers_always_continue(self):
        scorer, runtime, _coordinator, context = await self._make_scorer()

        async def boom():
            raise RuntimeError("simulated snapshot failure")
        context.get_messages = boom

        try:
            result = await scorer.on_provider_request("provider:request", {})
            self.assertEqual(result.action, "continue")

            result = await scorer.on_tool_pre("tool:pre", {"tool_name": "demo_inspect", "tool_input": {}})
            self.assertEqual(result.action, "continue")

            result = await scorer.on_tool_post("tool:post", {})
            self.assertEqual(result.action, "continue")

            result = await scorer.on_provider_error("provider:error", {})
            self.assertEqual(result.action, "continue")

            result = await scorer.on_execution_end("execution:end", {})
            self.assertEqual(result.action, "continue")
        finally:
            await runtime.close()

    async def test_snapshot_budget_abandons_not_raises(self):
        scorer, runtime, _coordinator, context = await self._make_scorer({"shadow_snapshot_budget_ms": 25})
        events = []
        runtime.service.emitter.callback = events.append

        async def slow_get_messages():
            await asyncio.sleep(0.2)
            return []
        context.get_messages = slow_get_messages

        try:
            start = time.perf_counter()
            result = await scorer.on_provider_request("provider:request", {})
            elapsed = time.perf_counter() - start
            self.assertEqual(result.action, "continue")
            self.assertLess(elapsed, 0.15, "snapshot must abandon well before the 200ms sleep completes")
            fallbacks = [e for e in events if e["event"].endswith("fallback")]
            self.assertEqual(
                sum(1 for e in fallbacks if e["data"].get("reason_code") == "shadow_snapshot_budget_exceeded"), 1)
        finally:
            await runtime.close()

    async def test_snapshot_reads_at_most_max_messages(self):
        scorer, runtime, _coordinator, context = await self._make_scorer({"shadow_max_messages": 12})
        context.messages = [{"role": "user", "content": f"msg-{i}"} for i in range(500)]

        try:
            job = await scorer._build_job()
        finally:
            await runtime.close()

        self.assertIsNotNone(job)
        texts = [o["text"] for o in job.state["observations"]]
        self.assertEqual(len(texts), 12)
        self.assertEqual(texts, [f"msg-{i}" for i in range(488, 500)])


if __name__ == "__main__":
    unittest.main()
