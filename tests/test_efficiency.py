"""Efficiency receipts: math, traffic classification, exact aggregation, and emission from the loop."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from amplifier_fast_decisions import efficiency
from amplifier_fast_decisions.contracts import Answer, Decision, DecisionResult, Policy, SLOW, TurnState
from amplifier_fast_decisions.demo import DemoCoordinator, demo_response
from amplifier_fast_decisions.orchestrator import RoutedProvider
from amplifier_fast_decisions.runtime import Runtime
from amplifier_fast_decisions.service import DecisionService
from amplifier_fast_decisions.telemetry import Emitter

M = 1_000_000


class ReceiptMathTests(unittest.TestCase):
    def test_cheaper_model_step_cold_and_warm_host_cache(self):
        usage = {"input_tokens": M, "cache_read_tokens": 0, "cache_write_tokens": M, "output_tokens": 0}
        cold = efficiency.cheaper_model_step(usage=usage, seconds=10.0, served_model="claude-sonnet-5",
                                             host_model="claude-opus-5-5", host_cache_warm=False,
                                             mechanism="jev:task_difficulty", judge_seconds=0.2,
                                             project="p", traffic="production")
        # Sonnet: 1M fresh input $3 + 1M cache write $3.75; Opus: $4 + $5.
        self.assertAlmostEqual(cold["actual"]["cost_usd"], 6.75)
        self.assertAlmostEqual(cold["baseline"]["cost_usd"], 9.0)
        self.assertAlmostEqual(cold["usd_saved"], 2.25)
        # Seconds: 10 s on Sonnet (113 tok/s) -> 10*113/88 on Opus; judge adds 0.2 s.
        self.assertAlmostEqual(cold["seconds_saved"], round(10 * 113 / 88 - 10.2, 4))
        self.assertEqual(cold["calls_saved"], 0)
        warm = efficiency.cheaper_model_step(usage=usage, seconds=10.0, served_model="claude-sonnet-5",
                                             host_model="claude-opus-5-5", host_cache_warm=True,
                                             mechanism="jev:task_difficulty", project="p", traffic="production")
        # Warm host would have READ those tokens: $4 input (fresh stays 1M? no: input includes reads) -> see price().
        self.assertLess(warm["baseline"]["cost_usd"], cold["baseline"]["cost_usd"])
        self.assertLess(warm["usd_saved"], 0)   # routing cost money against a warm Opus cache

    def test_provider_cost_is_the_actual(self):
        r = efficiency.cheaper_model_step(usage={"input_tokens": M, "output_tokens": 0, "cost_usd": 1.23},
                                          seconds=None, served_model="claude-sonnet-5", host_model="claude-opus-5-5",
                                          host_cache_warm=False, mechanism="m", project="p", traffic="production")
        self.assertEqual(r["actual"]["cost_usd"], 1.23)
        self.assertIsNone(r["seconds_saved"])

    def test_rebuild_and_judge_overhead_are_losses(self):
        rb = efficiency.host_rebuild_after_cheap(usage={"input_tokens": 0, "cache_write_tokens": M, "output_tokens": 0},
                                                 seconds=3.0, host_model="claude-opus-5-5", mechanism="m",
                                                 project="p", traffic="production")
        self.assertAlmostEqual(rb["usd_saved"], -(5.0 - 0.20))
        jo = efficiency.judge_overhead(mechanism="jev:task_difficulty", judge_seconds=0.15, host_model="claude-opus-5-5",
                                       project="p", traffic="production")
        self.assertEqual((jo["usd_saved"], jo["seconds_saved"], jo["calls_saved"]), (0.0, -0.15, 0))

    def test_prepared_action_saves_a_call(self):
        r = efficiency.prepared_action(tool="read_file", decision_seconds=0.3, host_model="claude-opus-5-5",
                                       avg_host_call_usd=0.12, avg_host_call_seconds=4.0, mechanism="jev:next_action",
                                       project="p", traffic="production")
        self.assertEqual((r["calls_saved"], r["usd_saved"], r["seconds_saved"]), (1, 0.12, 3.7))
        unknown = efficiency.prepared_action(tool="read_file", decision_seconds=0.3, host_model=None,
                                             avg_host_call_usd=None, avg_host_call_seconds=None, mechanism="m",
                                             project="p", traffic="production")
        self.assertIsNone(unknown["usd_saved"])

    def test_unknown_lever_rejected(self):
        with self.assertRaises(ValueError):
            efficiency.receipt(lever="magic", mechanism="m", decision="d", baseline={}, actual={}, method="",
                               project=None, traffic="production")


class TrafficTests(unittest.TestCase):
    def test_classification(self):
        c = efficiency.classify_traffic
        self.assertEqual(c("/Users/x/dev/teaserkit", env={}), "production")
        self.assertEqual(c("/tmp/ampup/proj", env={}), "test")
        self.assertEqual(c("/private/var/folders/ab/T/x", env={}), "test")
        self.assertEqual(c("/Users/x/dev/afast-ev/reval/experiments/r1/workspace", env={}), "test")
        self.assertEqual(c("/Users/x/repo/.claude/worktrees/agent-1", env={}), "test")
        self.assertEqual(c("/Users/x/dev/teaserkit", session_label="Forge repair_x", env={}), "test")
        self.assertEqual(c("/Users/x/dev/teaserkit", env={"AFAST_TRAFFIC": "benchmark"}), "test")
        self.assertEqual(c("/tmp/demo", env={"AFAST_TRAFFIC": "production"}), "production")


def _event(data, event_id, ts="2026-09-25T12:00:00Z"):
    return {"event": efficiency.EVENT, "event_id": event_id, "timestamp": ts, "data": data}


class AggregationTests(unittest.TestCase):
    def _receipts(self):
        mk = lambda lever, project, traffic, calls, usd, secs: efficiency.receipt(
            lever=lever, mechanism="m", decision="d", method="x", project=project, traffic=traffic,
            baseline={"calls": calls, "cost_usd": usd, "seconds": secs}, actual={"calls": 0, "cost_usd": 0.0, "seconds": 0.0})
        return [
            _event(mk("cheaper_model", "teaserkit", "production", 0, 0.5, 2.0), "a"),
            _event(mk("cheaper_model", "teaserkit", "production", 0, -0.2, -1.5), "b"),
            _event(mk("prepared_action", "repo", "production", 1, 0.12, 4.0), "c"),
            _event(mk("prepared_action", "repo", "production", 1, None, None), "d"),
            _event(mk("cheaper_model", "proj", "test", 0, 9.0, 9.0), "e"),
        ]

    def test_totals_are_exact_sums_and_test_traffic_is_excluded(self):
        report = efficiency.aggregate(self._receipts())
        self.assertEqual(report["excluded_test_receipts"], 1)
        self.assertEqual(report["totals"]["receipts"], 4)
        self.assertEqual(report["totals"]["calls_saved"], 2)
        self.assertAlmostEqual(report["totals"]["usd_saved"], 0.42)
        self.assertAlmostEqual(report["totals"]["seconds_saved"], 4.5)
        self.assertEqual(report["totals"]["usd_unknown"], 1)
        self.assertEqual(report["by_lever"]["prepared_action"]["receipts"], 2)
        self.assertEqual(report["by_project"]["teaserkit"]["cheaper_model"]["receipts"], 2)
        self.assertNotIn("proj", report["by_project"])
        for lever in efficiency.LEVERS:          # every lever is always reported
            self.assertIn(lever, report["by_lever"])
        with_test = efficiency.aggregate(self._receipts(), include_test=True)
        self.assertEqual(with_test["totals"]["receipts"], 5)

    def test_dashboard_numbers_match_an_independent_resum_of_stored_records(self):
        with tempfile.TemporaryDirectory() as d:
            lines = [json.dumps(e) for e in self._receipts()]
            Path(d, "s1.jsonl").write_text("\n".join(lines[:3]) + "\n")
            Path(d, "s2.jsonl").write_text("\n".join(lines[2:]) + "\n")        # "c" duplicated across files
            report = efficiency.summarize(d)
            # Independent recomputation: read raw lines, dedupe by event_id, sum production receipts.
            seen, usd, secs, calls, n = set(), 0.0, 0.0, 0, 0
            for f in sorted(Path(d).glob("*.jsonl")):
                for line in f.read_text().splitlines():
                    e = json.loads(line)
                    if e["event_id"] in seen or e["data"]["traffic"] != "production":
                        seen.add(e["event_id"]); continue
                    seen.add(e["event_id"]); n += 1; calls += e["data"]["calls_saved"]
                    usd += e["data"]["usd_saved"] or 0.0; secs += e["data"]["seconds_saved"] or 0.0
        self.assertEqual(report["totals"]["receipts"], n)
        self.assertEqual(report["totals"]["calls_saved"], calls)
        self.assertEqual(report["totals"]["usd_saved"], round(usd, 6))
        self.assertEqual(report["totals"]["seconds_saved"], round(secs, 3))


class UsageProvider:
    """A provider double that reports realistic Anthropic-style usage."""
    name = "anthropic-primary"

    def __init__(self, default_model, usage_seq):
        self.default_model, self.usage_seq, self.calls = default_model, list(usage_seq), 0

    async def complete(self, request, **kwargs):
        usage = self.usage_seq[min(self.calls, len(self.usage_seq) - 1)]
        self.calls += 1
        return NS(content=[{"type": "text", "text": "ok"}], tool_calls=None, finish_reason="end_turn",
                  usage=NS(**usage), model=None)

    def get_info(self):
        return {"name": self.name}


class FakeJudge:
    name = "fake-judge"
    external = False

    def __init__(self, p_complex):
        self.p_complex = p_complex

    async def ask(self, request):
        probs = {"simple": 1 - self.p_complex, "complex": self.p_complex}
        return DecisionResult(action=Decision(choice=SLOW, probabilities={SLOW: 1.0}),
                              answers={"task_difficulty": Answer(probabilities=probs)})

    async def close(self):
        pass


class LoopEmissionTests(unittest.IsolatedAsyncioTestCase):
    ROUTING = {"start_model": "claude-sonnet-5", "provider_match": "anthropic", "start_policy": "judge",
               "max_requests_before_escalation": None}

    def _setup(self, judge):
        events = []
        coordinator = DemoCoordinator()
        emitter = Emitter(coordinator.session_id, callback=events.append)
        policy = Policy(mode="off", model_routing=self.ROUTING, read_shortcut=False)
        service = DecisionService(policy, judge, emitter, coordinator, [])
        return service, Runtime(service), events

    async def test_cheap_turn_emits_cheaper_model_receipts_with_judge_attribution(self):
        judge = FakeJudge(0.1)
        service, runtime, events = self._setup(judge)
        usage = {"input_tokens": 100_000, "output_tokens": 200, "cache_read_tokens": 0, "cache_write_tokens": 100_000,
                 "cost_usd": 0.40}
        provider = UsageProvider("claude-opus-5-5", [usage])
        facade = RoutedProvider(provider, runtime, {}, demo_response, "anthropic-primary")
        service.turn = TurnState("t1")
        for _ in range(2):
            await facade.complete(NS(messages=[{"role": "user", "content": "fix typo"}], tools=[], tool_choice="auto"))
        receipts = [e["data"] for e in events if e["event"] == efficiency.EVENT]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(r["lever"] == "cheaper_model" and r["mechanism"] == "fake-judge:task_difficulty"
                            for r in receipts))
        self.assertEqual(receipts[0]["actual"]["model"], "claude-sonnet-5")
        self.assertEqual(receipts[0]["baseline"]["model"], "claude-opus-5-5")
        self.assertEqual(receipts[0]["actual"]["cost_usd"], 0.40)
        self.assertIn("traffic", receipts[0]); self.assertIn("project", receipts[0])

    async def test_host_turn_after_cheap_turn_charges_the_cache_rebuild(self):
        service, runtime, events = self._setup(FakeJudge(0.1))
        usage = {"input_tokens": 50_000, "output_tokens": 100, "cache_read_tokens": 0, "cache_write_tokens": 50_000}
        provider = UsageProvider("claude-opus-5-5", [usage])
        facade = RoutedProvider(provider, runtime, {}, demo_response, "anthropic-primary")
        service.turn = TurnState("t1")
        await facade.complete(NS(messages=[{"role": "user", "content": "typo"}], tools=[], tool_choice="auto"))
        service.backend = FakeJudge(0.95)
        service.turn = TurnState("t2")
        await facade.complete(NS(messages=[{"role": "user", "content": "hard"}], tools=[], tool_choice="auto"))
        decisions = [e["data"]["decision"] for e in events if e["event"] == efficiency.EVENT]
        self.assertIn("host_cache_rebuild_after_cheap_turn", decisions)
        self.assertIn("kept_on_host", decisions)
        rebuild = next(e["data"] for e in events if e["event"] == efficiency.EVENT
                       and e["data"]["decision"] == "host_cache_rebuild_after_cheap_turn")
        self.assertLess(rebuild["usd_saved"], 0)


if __name__ == "__main__":
    unittest.main()
