"""Price gate: pure-function tests. No network, no keys."""
from __future__ import annotations

import gzip
import json
import unittest
from collections import defaultdict
from pathlib import Path

from amplifier_fast_decisions import price_gate as pg

CHEAP = "claude-sonnet-5"
EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "2026-10-02-paired-campaign"


class PriceGateTests(unittest.TestCase):
    def test_opus_5_5_host_does_not_route(self):
        r = pg.evaluate("claude-opus-5-5", CHEAP, {})
        self.assertFalse(r.route)
        self.assertEqual(r.reason, "price_gate_host")
        self.assertAlmostEqual(r.predicted_ratio, 1.366, delta=0.005)
        self.assertEqual((r.request_multiplier, r.multiplier_source), (1.38, "table"))

    def test_fable_5_1_host_routes(self):
        r = pg.evaluate("claude-fable-5-1", CHEAP, {})
        self.assertTrue(r.route)
        self.assertAlmostEqual(r.predicted_ratio, 0.523, delta=0.005)
        self.assertEqual(r.request_multiplier, 1.11)

    def test_sonnet_host_same_model(self):
        for host in ("claude-sonnet-5", "claude-sonnet-5-20260101"):
            r = pg.evaluate(host, CHEAP, {})
            self.assertEqual((r.route, r.reason), (False, "same_model"))

    def test_haiku_host_does_not_route(self):
        r = pg.evaluate("claude-haiku-4-5", CHEAP, {})
        self.assertFalse(r.route)
        self.assertAlmostEqual(r.predicted_ratio, 4.14, delta=0.01)

    def test_dated_host_id_uses_table(self):
        r = pg.evaluate("claude-opus-5-5-20260901", CHEAP, {})
        self.assertEqual(r.multiplier_source, "table")
        self.assertFalse(r.route)

    def test_unlisted_priced_host_uses_default_multiplier(self):
        r = pg.evaluate("claude-opus-5", CHEAP, {})
        self.assertEqual((r.multiplier_source, r.request_multiplier), ("default", 1.38))
        self.assertAlmostEqual(r.predicted_ratio, 0.828, delta=0.005)
        self.assertTrue(r.route)

    def test_unknown_and_unpriced(self):
        self.assertEqual(pg.evaluate(None, CHEAP, {}).reason, "host_unknown")
        self.assertEqual(pg.evaluate("gpt-5", CHEAP, {}).reason, "host_unpriced")
        self.assertEqual(pg.evaluate("claude-opus-5-5", "foo", {}).reason, "cheap_unpriced")
        for host, cheap in ((None, CHEAP), ("gpt-5", CHEAP), ("claude-opus-5-5", "foo")):
            self.assertFalse(pg.evaluate(host, cheap, {}).route)

    def test_break_even(self):
        self.assertAlmostEqual(pg.break_even_cache_read("claude-opus-5-5", CHEAP), 0.429, delta=0.005)
        opus = list(pg.DEFAULT_RATES["claude-opus-5-5"])
        for read, route in ((0.45, True), (0.40, False)):
            cfg = {"rates": {"claude-opus-5-5": [opus[0], opus[1], read, opus[3]]}}
            self.assertEqual(pg.evaluate("claude-opus-5-5", CHEAP, cfg).route, route)

    def test_multiplier_override_flips_decision(self):
        r = pg.evaluate("claude-opus-5-5", CHEAP, {"request_multipliers": {"claude-opus-5-5": 1.0}})
        self.assertTrue(r.route)
        self.assertAlmostEqual(r.predicted_ratio, 0.990, delta=0.005)
        self.assertEqual(r.multiplier_source, "config")

    def test_disabled(self):
        r = pg.evaluate("claude-opus-5-5", CHEAP, {"enabled": False})
        self.assertEqual((r.route, r.reason), (True, "gate_disabled"))
        self.assertFalse(r.receipt()["enabled"])

    def test_receipt_carries_inputs(self):
        receipt = pg.evaluate("claude-opus-5-5", CHEAP, {}).receipt()
        self.assertEqual(receipt["predicted_cost_ratio"], 1.3656)
        self.assertEqual(receipt["host_rates"], [4.0, 20.0, 0.2, 5.0])
        self.assertEqual(receipt["reference_mix"], pg.REFERENCE_MIX)
        self.assertEqual(receipt["rates_source"], "default")
        json.dumps(receipt)

    def test_validation(self):
        pg.validate({})
        pg.validate({"enabled": True, "request_multipliers": {"m": 1.2}, "default_request_multiplier": 1.5,
                     "rates": {"m": [1, 2, 0.1, 1.25]}})
        for bad in ({"nope": 1}, {"enabled": "yes"}, {"request_multipliers": {"m": 0}},
                    {"request_multipliers": {"m": 11}}, {"request_multipliers": {"m": True}},
                    {"default_request_multiplier": 0}, {"rates": {"m": [1, 2, 3]}},
                    {"rates": {"m": [1, 2, -1, 4]}}, [], "on"):
            with self.assertRaises(ValueError, msg=str(bad)):
                pg.validate(bad)

    def test_constants_match_published_evidence(self):
        sessions = [json.loads(l) for l in (EVIDENCE / "data" / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
        index = {(s["scenario_id"], s["rep"], s["host"], s["arm"]): s for s in sessions}
        multipliers = {}
        for host, model in (("opus", "claude-opus-5-5"), ("fable", "claude-fable-5-1")):
            pairs = [(s, index[(s["scenario_id"], s["rep"], host, "anchor")]) for s in sessions
                     if s["host"] == host and s["arm"] == "sticky" and s["sticky_decision"] == "cheap" and s["cost_valid"]]
            pairs = [(s, a) for s, a in pairs if a["cost_valid"]]
            multipliers[model] = sum(s["n_req"] for s, _ in pairs) / sum(a["n_req"] for _, a in pairs)
            self.assertEqual(round(multipliers[model], 2), pg.REQUEST_MULTIPLIERS[model])
        self.assertEqual(pg.DEFAULT_REQUEST_MULTIPLIER, max(round(m, 2) for m in multipliers.values()))
        anchors = [s for s in sessions if s["arm"] == "anchor" and s["cost_valid"]]
        n, totals = sum(s["n_req"] for s in anchors), defaultdict(float)
        for s in anchors:
            for tokens in s["tokens"].values():
                for k, v in tokens.items():
                    totals[k] += v
        for k, v in pg.REFERENCE_MIX.items():
            self.assertLessEqual(abs(totals[k] / n - v), 1.0, k)
        with gzip.open(EVIDENCE / "data" / "requests.jsonl.gz", "rt", encoding="utf-8") as handle:
            self.assertGreater(sum(1 for _ in handle), 50000)


if __name__ == "__main__":
    unittest.main()
