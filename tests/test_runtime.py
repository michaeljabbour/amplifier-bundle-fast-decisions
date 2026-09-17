"""Unit tests for Runtime's shadow-worker lifecycle (P3).

test_owner_policy_defensive_reapply lives in test_build_contracts.py
(MountOrderTests) -- it needs the real amplifier_core/loop-streaming
production entrypoints and is real-kernel-only. This file covers the
offline half: Runtime.close() draining and cancelling its shadow worker.
"""
from __future__ import annotations
import asyncio
import tempfile
import unittest

from amplifier_fast_decisions.contracts import Policy
from amplifier_fast_decisions.demo import DemoCoordinator
from amplifier_fast_decisions.runtime import get_runtime
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


if __name__ == "__main__":
    unittest.main()
