"""Savings estimate from recorded routing and provider-completion events."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amplifier_fast_decisions import savings


def _event(kind, turn, data, ts="2026-09-24T10:00:00+00:00", **extra):
    return {"event": "fast_decisions:" + kind, "turn_id": turn, "timestamp": ts, "data": data, **extra}


def _write(directory, name, events):
    path = Path(directory) / name
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


class PriceTests(unittest.TestCase):
    def test_cached_reads_are_split_out_of_input(self):
        tokens = {"input": 1_000_000, "output": 0, "cache_read": 1_000_000, "cache_write": 0}
        self.assertAlmostEqual(savings.price("claude-sonnet-5", tokens, savings.DEFAULT_RATES), 0.30)
        self.assertAlmostEqual(savings.price("claude-fable-5-1", tokens, savings.DEFAULT_RATES), 0.25)

    def test_dated_ids_and_unknown_models(self):
        tokens = {"input": 1_000_000, "output": 1_000_000}
        self.assertAlmostEqual(savings.price("claude-sonnet-5-20260101", tokens, savings.DEFAULT_RATES), 18.0)
        self.assertIsNone(savings.price("gpt-x", tokens, savings.DEFAULT_RATES))


class SummarizeTests(unittest.TestCase):
    def test_cheap_turn_saved_and_strong_turn_counts_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s1.jsonl", [
                _event("difficulty_judged", "t1", {"choice": "cheap", "reason_code": "judge_cheap"}),
                _event("slow_end", "t1", {"status": "ok", "model": "claude-sonnet-5", "input_tokens": 1_000_000,
                                          "output_tokens": 100_000, "cache_read_tokens": 0, "duration_ms": 1000}),
                _event("difficulty_judged", "t2", {"choice": "strong", "reason_code": "scope_strong"}),
                _event("slow_end", "t2", {"status": "ok", "model": "provider-default", "input_tokens": 10,
                                          "output_tokens": 10, "duration_ms": 500}),
                _event("slow_end", "t1", {"status": "error", "model": "claude-sonnet-5", "input_tokens": 9_999_999}),
            ])
            r = savings.summarize(d)
        self.assertEqual(r["turns"]["cheap"], 1)
        self.assertEqual(r["turns"]["strong"], 1)
        self.assertEqual(r["turns"]["judge_calls"], 1)
        # sonnet: 3 + 1.5 = 4.5 ; fable: 10 + 5 = 15
        self.assertAlmostEqual(r["cost"]["cheap_turns_actual_usd"], 4.5)
        self.assertAlmostEqual(r["cost"]["cheap_turns_on_host_usd"], 15.0)
        self.assertAlmostEqual(r["cost"]["saved_usd"], 10.5)
        self.assertEqual(r["cost"]["requests_without_cache_data"], 0)
        self.assertFalse(r["time"]["available"])

    def test_provider_cost_is_preferred_and_missing_cache_data_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                _event("difficulty_judged", "t", {"choice": "cheap", "reason_code": "rules_cheap"}),
                _event("slow_end", "t", {"status": "ok", "model": "claude-sonnet-5", "input_tokens": 1_000_000,
                                         "output_tokens": 0, "cost_usd": 0.5}),
                _event("slow_end", "t", {"status": "ok", "model": "claude-sonnet-5", "input_tokens": 1_000_000,
                                         "output_tokens": 0}),
            ])
            r = savings.summarize(d)
        self.assertAlmostEqual(r["cost"]["cheap_turns_actual_usd"], 3.5)
        self.assertEqual(r["cost"]["provider_costed_requests"], 1)
        self.assertEqual(r["cost"]["requests_without_cache_data"], 1)

    def test_time_estimate_needs_samples_on_both_models(self):
        events = [_event("difficulty_judged", "c", {"choice": "cheap", "reason_code": "rules_cheap"}),
                  _event("difficulty_judged", "s", {"choice": "strong", "reason_code": "rules_strong"})]
        for _ in range(savings.MIN_RATE_SAMPLES):
            events.append(_event("slow_end", "c", {"status": "ok", "model": "claude-sonnet-5", "input_tokens": 1,
                                                   "output_tokens": 1000, "duration_ms": 10_000}))
            events.append(_event("slow_end", "s", {"status": "ok", "model": "provider-default", "input_tokens": 1,
                                                   "output_tokens": 1000, "duration_ms": 20_000}))
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", events)
            r = savings.summarize(d)
        t = r["time"]
        self.assertTrue(t["available"])
        self.assertEqual(r["cheap_model"], "claude-sonnet-5")
        self.assertAlmostEqual(t["cheap_turns_model_seconds"], 200.0)
        self.assertAlmostEqual(t["saved_seconds"], 200.0)

    def test_since_filter_synthetic_skip_and_cache_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.jsonl", [
                _event("difficulty_judged", "old", {"choice": "cheap", "reason_code": "rules_cheap"}, ts="2026-09-01T00:00:00Z"),
                _event("difficulty_judged", "new", {"choice": "cheap", "reason_code": "rules_cheap"}),
                _event("difficulty_judged", "fake", {"choice": "cheap", "reason_code": "rules_cheap"}, synthetic=True),
            ])
            cache = Path(d) / "cache" / "savings.json"
            first = savings.summarize(d, since="2026-09-20", cache_path=cache)
            self.assertEqual(first["turns"]["cheap"], 1)
            self.assertTrue(cache.exists())
            again = savings.summarize(d, cache_path=cache)
            self.assertEqual(again["turns"]["cheap"], 2)
            self.assertEqual([x["day"] for x in again["by_day"]], ["2026-09-01", "2026-09-24"])

    def test_empty_or_missing_directory(self):
        r = savings.summarize("/nonexistent/afast-events")
        self.assertEqual(r["turns"]["total"], 0)
        self.assertEqual(r["by_day"], [])


class CliTests(unittest.TestCase):
    def test_savings_cli_json(self):
        import contextlib
        import io

        from amplifier_fast_decisions.cli import main
        with tempfile.TemporaryDirectory() as d:
            events = Path(d) / "events"
            events.mkdir()
            _write(events, "s.jsonl", [_event("difficulty_judged", "t", {"choice": "cheap", "reason_code": "rules_cheap"})])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["savings", "--events", str(events), "--json"]), 0)
            self.assertEqual(json.loads(out.getvalue())["turns"]["cheap"], 1)
            self.assertTrue((Path(d) / "savings-cache.json").exists())


if __name__ == "__main__":
    unittest.main()
