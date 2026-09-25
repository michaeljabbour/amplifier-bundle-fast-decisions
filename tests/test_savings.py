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

    def test_cache_writes_use_the_cache_write_rate(self):
        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 1_000_000}
        self.assertAlmostEqual(savings.price("claude-sonnet-5", tokens, savings.DEFAULT_RATES), 3.75)


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

    def test_recorded_host_model_prices_the_counterfactual(self):
        # Opus 5.5 reads cache cheaper than Sonnet 5: a cache-heavy cheap turn
        # can cost MORE than the host would have -- the estimate must show it.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                _event("difficulty_judged", "t", {"choice": "cheap", "reason_code": "judge_cheap"}),
                _event("slow_end", "t", {"status": "ok", "model": "claude-sonnet-5", "host_model": "claude-opus-5-5",
                                         "input_tokens": 1_000_000, "cache_read_tokens": 1_000_000,
                                         "output_tokens": 0}),
            ])
            r = savings.summarize(d)
        self.assertEqual(r["host_model"], "claude-opus-5-5")
        self.assertEqual(r["host_model_source"], "recorded")
        self.assertAlmostEqual(r["cost"]["cheap_turns_actual_usd"], 0.30)
        self.assertAlmostEqual(r["cost"]["cheap_turns_on_host_usd"], 0.20)
        self.assertAlmostEqual(r["cost"]["saved_usd"], -0.10)

    def test_alternating_turns_do_not_overstate_savings(self):
        # Turn 1 host (warms the host cache), turn 2 cheap (writes 1M tokens to
        # the cheap model's cache), turn 3 host (rebuilds its cache: 1M writes).
        ev = [
            _event("difficulty_judged", "t1", {"choice": "strong", "reason_code": "judge_strong"}, ts="2026-09-24T10:00:00Z"),
            _event("slow_end", "t1", {"status": "ok", "model": "provider-default", "host_model": "claude-opus-5-5",
                                      "input_tokens": 0, "cache_write_tokens": 1_000_000, "output_tokens": 0}, ts="2026-09-24T10:00:01Z"),
            _event("difficulty_judged", "t2", {"choice": "cheap", "reason_code": "judge_cheap"}, ts="2026-09-24T10:01:00Z"),
            _event("slow_end", "t2", {"status": "ok", "model": "claude-sonnet-5", "host_model": "claude-opus-5-5",
                                      "input_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 1_000_000,
                                      "output_tokens": 0}, ts="2026-09-24T10:01:01Z"),
            _event("difficulty_judged", "t3", {"choice": "strong", "reason_code": "judge_strong"}, ts="2026-09-24T10:02:00Z"),
            _event("slow_end", "t3", {"status": "ok", "model": "provider-default", "host_model": "claude-opus-5-5",
                                      "input_tokens": 0, "cache_write_tokens": 1_000_000, "output_tokens": 0}, ts="2026-09-24T10:02:01Z"),
        ]
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", ev)
            r = savings.summarize(d)
        c = r["cost"]
        self.assertAlmostEqual(c["cheap_turns_actual_usd"], 3.75)     # Sonnet cache write
        self.assertAlmostEqual(c["cheap_turns_on_host_usd"], 0.20)    # host would have READ it
        self.assertAlmostEqual(c["switch_penalty_usd"], 4.80)         # Opus rebuild: 5.00 - 0.20
        self.assertAlmostEqual(c["saved_usd"], 0.20 - 3.75 - 4.80)    # routing cost money here

    def test_each_request_is_priced_at_its_own_recorded_host(self):
        # Two host models in one file: each request's counterfactual uses the
        # host it recorded, not the file's majority host.
        req = {"status": "ok", "model": "claude-sonnet-5", "input_tokens": 1_000_000, "output_tokens": 0,
               "cache_read_tokens": 0}
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                _event("difficulty_judged", "t", {"choice": "cheap", "reason_code": "judge_cheap"}),
                _event("slow_end", "t", dict(req, host_model="claude-opus-5-5")),
                _event("slow_end", "t", dict(req, host_model="claude-opus-5-5")),
                _event("slow_end", "t", dict(req, host_model="claude-fable-5-1")),
            ])
            r = savings.summarize(d)
        # opus-5-5 input $4/M twice + fable-5-1 input $10/M once
        self.assertAlmostEqual(r["cost"]["cheap_turns_on_host_usd"], 18.0)

    def test_request_without_host_uses_the_file_host(self):
        # An older cheap-turn record lacks host_model; the file's recorded host
        # (from another request) prices it, not the global default.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                _event("difficulty_judged", "c", {"choice": "cheap", "reason_code": "judge_cheap"}),
                _event("slow_end", "c", {"status": "ok", "model": "claude-sonnet-5", "input_tokens": 1_000_000,
                                         "output_tokens": 0, "cache_read_tokens": 0}),
                _event("difficulty_judged", "s", {"choice": "strong", "reason_code": "judge_strong"}),
                _event("slow_end", "s", {"status": "ok", "model": "provider-default", "host_model": "claude-opus-5-5",
                                         "input_tokens": 10, "output_tokens": 10}),
            ])
            r = savings.summarize(d)
        self.assertAlmostEqual(r["cost"]["cheap_turns_on_host_usd"], 4.0)

    def test_served_model_is_what_gets_priced(self):
        # The provider served haiku although sonnet was requested: actual cost
        # is haiku's rate.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                _event("difficulty_judged", "t", {"choice": "cheap", "reason_code": "judge_cheap"}),
                _event("slow_end", "t", {"status": "ok", "model": "claude-sonnet-5", "served_model": "claude-haiku-4-5",
                                         "input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0}),
            ])
            r = savings.summarize(d)
        self.assertAlmostEqual(r["cost"]["cheap_turns_actual_usd"], 1.0)

    def test_cache_is_invalidated_when_a_session_file_grows(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "a.jsonl", [_event("difficulty_judged", "t1", {"choice": "cheap", "reason_code": "rules_cheap"})])
            cache = Path(d) / "cache" / "savings.json"
            self.assertEqual(savings.summarize(d, cache_path=cache)["turns"]["cheap"], 1)
            with path.open("a") as handle:
                handle.write(json.dumps(_event("difficulty_judged", "t2", {"choice": "cheap", "reason_code": "rules_cheap"})) + "\n")
            self.assertEqual(savings.summarize(d, cache_path=cache)["turns"]["cheap"], 2)

    def test_recent_reports_turns_since_last_cheap_turn(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", [
                _event("difficulty_judged", "a", {"choice": "cheap", "reason_code": "judge_cheap"}, ts="2026-09-25T01:00:00Z"),
                _event("difficulty_judged", "b", {"choice": "strong", "reason_code": "scope_strong"}, ts="2026-09-25T02:00:00Z"),
                _event("difficulty_judged", "c", {"choice": "strong", "reason_code": "scope_strong"}, ts="2026-09-25T03:00:00Z"),
            ])
            r = savings.summarize(d)
        self.assertEqual(r["recent"]["last_cheap_turn_at"], "2026-09-25T01:00:00Z")
        self.assertEqual(r["recent"]["turns_since_by_reason"], {"scope_strong": 2})

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
