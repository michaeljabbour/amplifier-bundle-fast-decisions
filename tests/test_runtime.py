"""Unit tests for Runtime's shadow-worker lifecycle (P3).

test_owner_policy_defensive_reapply lives in test_build_contracts.py
(MountOrderTests) -- it needs the real amplifier_core/loop-streaming
production entrypoints and is real-kernel-only. This file covers the
offline half: Runtime.close() draining and cancelling its shadow worker.
"""
from __future__ import annotations
import asyncio
import tempfile
import threading
import unittest
from unittest import mock

from amplifier_fast_decisions.backends import JevBackend, ScriptedBackend, UnavailableBackend
from amplifier_fast_decisions.contracts import Policy
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions.runtime import _schedule_backend_warmup, get_runtime
from amplifier_fast_decisions.shadow import ShadowJob


def make_job(decision_id="d1"):
    return ShadowJob(kind="turn", turn_id="t", decision_id=decision_id, state={},
                      candidates=(), questions=(), state_source="context_mount",
                      state_hash="h", state_revision=0)


class RuntimeCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_drains_and_cancels_worker(self):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            runtime, owner = get_runtime(coordinator, {
                "backend": "unavailable", "events_dir": tmp, "shadow_drain_ms": 200,
            })
            self.assertTrue(owner)

            # A never-resolving job: the backend is "unavailable" so _score
            # returns quickly (an exception is swallowed), but this still
            # exercises the ordinary submit -> worker -> queue.task_done path.
            self.assertTrue(runtime.submit_shadow(make_job("d1")))

            task_before = runtime._shadow_task
            self.assertIsNotNone(task_before)
            self.assertFalse(task_before.done())

            await runtime.close()

            self.assertTrue(runtime.closed)
            self.assertTrue(task_before.done())
            self.assertFalse(task_before.cancelled() and not task_before.done())
            # No pending asyncio task is left behind.
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
            self.assertEqual(pending, [])

            # Idempotent: a second close() must not raise or hang.
            await runtime.close()

    async def test_close_cancels_a_worker_stuck_past_the_drain_budget(self):
        coordinator = DemoCoordinator()

        class HangingBackend:
            name = "hanging"
            external = False

            async def ask(self, request):
                await asyncio.sleep(10)

            async def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = get_runtime(coordinator, {
                "backend": "unavailable", "events_dir": tmp, "shadow_drain_ms": 50,
            })
            runtime.service.backend = HangingBackend()
            runtime.service.policy = Policy(mode="shadow", allow_external_state=True)

            self.assertTrue(runtime.submit_shadow(make_job("stuck")))
            await asyncio.sleep(0.01)  # let the worker pick the job up and start hanging

            task = runtime._shadow_task
            await runtime.close()

            self.assertTrue(runtime.closed)
            self.assertTrue(task.done())
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
            self.assertEqual(pending, [])


class BackendSelectionTests(unittest.IsolatedAsyncioTestCase):
    """get_runtime's backend config -> instance mapping.

    Confirms the deterministic backend is wireable (GAP1's root cause: it
    previously wasn't, so the shipped shadow rung could only ever hit the
    external_state_not_enabled fallback) and that jev/unavailable still
    behave as before.
    """

    async def test_backend_deterministic_selects_scripted_backend(self):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = get_runtime(
                coordinator, {"backend": "deterministic", "events_dir": tmp}
            )
            try:
                self.assertIsInstance(runtime.service.backend, ScriptedBackend)
                self.assertFalse(runtime.service.backend.external)
            finally:
                await runtime.close()

    async def test_backend_jev_selects_jev_backend(self):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = get_runtime(
                coordinator, {"backend": "jev", "events_dir": tmp}
            )
            try:
                self.assertIsInstance(runtime.service.backend, JevBackend)
                self.assertTrue(runtime.service.backend.external)
            finally:
                await runtime.close()

    async def test_backend_unavailable_selects_unavailable_backend(self):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = get_runtime(
                coordinator, {"backend": "unavailable", "events_dir": tmp}
            )
            try:
                self.assertIsInstance(runtime.service.backend, UnavailableBackend)
            finally:
                await runtime.close()

    async def test_unknown_backend_name_still_rejected(self):
        coordinator = DemoCoordinator()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                get_runtime(coordinator, {"backend": "scripted", "events_dir": tmp})


class BackendWarmupSchedulingTests(unittest.IsolatedAsyncioTestCase):
    """_schedule_backend_warmup (called from get_runtime right after a
    backend is constructed): mount-time warmup that never blocks the mount
    and never lets a failing warmup escape. Ollama's warmup absorbs the
    model reload, Jev's opens the TLS connection, Mlx/Laya/Hosted hit their
    health endpoints -- all of that is paid here instead of on the first
    real decision.
    """

    async def test_warmup_runs_via_create_task_when_loop_is_running(self):
        ran = asyncio.Event()

        class FakeBackend:
            name = "fake"

            async def warmup(self):
                ran.set()

        _schedule_backend_warmup(FakeBackend())
        await asyncio.wait_for(ran.wait(), timeout=1)

    async def test_raising_warmup_is_swallowed_not_propagated(self):
        failed = asyncio.Event()

        class FakeBackend:
            name = "fake"

            async def warmup(self):
                failed.set()
                raise RuntimeError("boom")

        loop = asyncio.get_running_loop()
        real_create_task, scheduled = loop.create_task, []

        def spy(coro, *args, **kwargs):
            task = real_create_task(coro, *args, **kwargs)
            scheduled.append(task)
            return task

        # Must not raise synchronously from the scheduling call itself.
        with mock.patch.object(loop, "create_task", spy):
            _schedule_backend_warmup(FakeBackend())
        # ...and the background task's failure must not surface anywhere
        # that would crash the event loop or this test.
        await asyncio.wait_for(failed.wait(), timeout=1)
        self.assertEqual(len(scheduled), 1)
        await asyncio.wait(scheduled, timeout=1)
        # The task completed without an exception: the failure was swallowed
        # inside it (an unswallowed one would only be logged, never raised).
        self.assertIsNone(scheduled[0].exception())

    async def test_backend_without_warmup_is_skipped(self):
        class FakeBackend:
            name = "fake"

        # No `warmup` attribute at all -- must be a no-op, not an error.
        _schedule_backend_warmup(FakeBackend())

    async def test_non_coroutine_warmup_attribute_is_skipped(self):
        class FakeBackend:
            name = "fake"
            warmup = "not-a-callable-coroutine-fn"

        _schedule_backend_warmup(FakeBackend())


class BackendWarmupNoRunningLoopTests(unittest.TestCase):
    """Outside a running loop (e.g. constructed synchronously), warmup must
    still run -- in a daemon thread via asyncio.run -- rather than being
    silently dropped."""

    def test_warmup_runs_in_daemon_thread_when_no_loop_is_running(self):
        ran = threading.Event()

        class FakeBackend:
            name = "fake"

            async def warmup(self):
                ran.set()

        _schedule_backend_warmup(FakeBackend())
        self.assertTrue(ran.wait(timeout=2))

    def test_raising_warmup_in_thread_path_does_not_raise_here(self):
        class FakeBackend:
            name = "fake"

            async def warmup(self):
                raise RuntimeError("boom")

        # Must return immediately without raising; the failure happens on
        # the background daemon thread and is swallowed there. A thread's
        # uncaught exception never reaches this test on its own, so capture
        # it through threading.excepthook and join the thread.
        uncaught = []
        before = set(threading.enumerate())
        with mock.patch.object(threading, "excepthook", side_effect=uncaught.append):
            _schedule_backend_warmup(FakeBackend())
            for thread in set(threading.enumerate()) - before:
                thread.join(timeout=2)
        self.assertEqual(uncaught, [])


if __name__ == "__main__":
    unittest.main()
