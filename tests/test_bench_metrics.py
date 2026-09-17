"""Unit tests for amplifier_fast_decisions.bench.metrics -- pure functions,
no I/O, offline and deterministic."""

from __future__ import annotations

import unittest

from amplifier_fast_decisions.bench.metrics import (
    decision_cost_usd,
    ece,
    percentile,
)


class PercentileTests(unittest.TestCase):
    def test_percentiles_small_n(self):
        self.assertIsNone(percentile([], 50))
        self.assertEqual(percentile([7.0], 50), 7.0)
        self.assertEqual(percentile([7.0], 95), 7.0)
        # n=2: documented nearest-rank behaviour (docs/BENCH.md).
        self.assertEqual(percentile([1.0, 3.0], 50), 1.0)
        self.assertEqual(percentile([1.0, 3.0], 95), 3.0)

    def test_percentile_ignores_non_finite(self):
        self.assertEqual(percentile([1.0, float("nan"), 3.0], 100), 3.0)


class MissingUsageTests(unittest.TestCase):
    def test_missing_usage_is_null_not_zero(self):
        self.assertIsNone(decision_cost_usd([None, None]))
        self.assertIsNone(decision_cost_usd([]))

    def test_known_usage_computes_cost(self):
        cost = decision_cost_usd([1_000_000])
        assert cost is not None
        self.assertAlmostEqual(cost, 0.042)

    def test_mixed_known_and_missing_usage_sums_known(self):
        cost = decision_cost_usd([1_000_000, None])
        assert cost is not None
        self.assertAlmostEqual(cost, 0.042)


class EceTests(unittest.TestCase):
    def test_ece_known_input(self):
        # Four points, two bins of width 0.5: [0, 0.5) and [0.5, 1].
        # Bin A: probabilities 0.2, 0.3 -- both wrong -> acc=0, conf=0.25.
        # Bin B: probabilities 0.7, 0.9 -- both right -> acc=1, conf=0.8.
        pairs = [(0.2, False), (0.3, False), (0.7, True), (0.9, True)]
        result = ece(pairs, bins=2, min_reliable_n=1)
        expected = 0.5 * abs(0 - 0.25) + 0.5 * abs(1 - 0.8)
        self.assertAlmostEqual(result["ece"], expected)
        self.assertEqual(result["n_observed"], 4)
        self.assertEqual([b["n"] for b in result["bins"]], [2, 2])

    def test_ece_uses_probability_not_confidence(self):
        # ece() takes (selected_probability, correct) pairs directly -- it
        # never receives or reads a separate "confidence" statistic. This
        # locks that contract: passing the same probability values under
        # any other name would still be scored identically. Perfectly
        # calibrated input (probability == empirical accuracy) gives ece=0.
        pairs = [(1.0, True), (1.0, True), (0.0, False), (0.0, False)]
        result = ece(pairs, bins=10, min_reliable_n=1)
        self.assertAlmostEqual(result["ece"], 0.0, places=6)

    def test_low_n_bins_flagged_and_excluded(self):
        # 40 points in the top bin (reliable, n>=30), 5 points in a low
        # bin (n<30, excluded from the headline and reported separately).
        pairs = [(0.95, True) for _ in range(40)] + [(0.15, False) for _ in range(5)]
        result = ece(pairs, bins=10, min_reliable_n=30)
        reliable = [b for b in result["bins"] if b["reliable"]]
        self.assertEqual(len(reliable), 1)
        self.assertEqual(reliable[0]["n"], 40)
        self.assertEqual(len(result["low_n_bins"]), 1)
        self.assertEqual(result["low_n_bins"][0]["n"], 5)
        self.assertFalse(result["low_n_bins"][0]["reliable"])
        # Headline ECE reflects only the reliable bin: acc=1, conf=0.95.
        self.assertAlmostEqual(result["ece"], abs(1 - 0.95), places=6)

    def test_ece_empty_input(self):
        result = ece([], bins=10)
        self.assertIsNone(result["ece"])
        self.assertEqual(result["n_observed"], 0)


if __name__ == "__main__":
    unittest.main()
