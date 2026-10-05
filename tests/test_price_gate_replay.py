"""Replay of the recorded main-v1 campaign through the real decision code (offline, no model calls)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import price_gate_replay as replay  # noqa: E402


class PriceGateReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = replay.load(replay.DEFAULT_EVIDENCE)

    def test_derived_constants_agree_with_code(self):
        result = replay.derive(self.data)
        self.assertTrue(result["ok"], result)

    def test_opus_host_never_routes_and_fable_matches_recorded_decisions(self):
        result = replay.replay(self.data, replay.DEFAULT_BEHAVIOR)
        opus, fable = result["by_host"]["opus"], result["by_host"]["fable"]
        self.assertEqual((opus["no_routing"], opus["waves"]), (140, 140))
        self.assertEqual((fable["decision_matches_recorded"], fable["waves"]), (140, 140))
        self.assertEqual((fable["recorded_cheap"], fable["recorded_host"]), (124, 16))
        self.assertEqual(fable["judged_once"], 140)
        self.assertEqual(fable["turns_2_3_reuse_session"], 140)
        self.assertTrue(result["pass"], result)

    def test_gate_never_routes_where_recorded_data_says_it_costs_more(self):
        result = replay.sweep(self.data)
        self.assertTrue(result["pass"], result)
        by_price = {r["opus_cache_read_usd_per_m"]: r for r in result["rows"]}
        self.assertEqual(by_price[0.20]["gate"], "host")
        self.assertEqual(by_price[0.50]["gate"], "route")
        self.assertAlmostEqual(by_price[0.35]["measured_sticky_over_anchor"], 0.989, delta=0.002)


if __name__ == "__main__":
    unittest.main()
