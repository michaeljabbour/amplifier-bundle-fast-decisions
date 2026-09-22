"""Unit tests for amplifier_fast_decisions.bench.calibration -- offline,
no network, no LLM.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amplifier_fast_decisions.bench.calibration import (
    calibration_report,
    derived_confidence,
    gate_curve,
    joined_pairs,
)


def _event(event_id, decision_id, kind, data, seq=1, turn_id="t1"):
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event": f"fast_decisions:{kind}",
        "session_id": "s1",
        "parent_session_id": None,
        "turn_id": turn_id,
        "decision_id": decision_id,
        "seq": seq,
        "timestamp": "2026-09-17T00:00:00+00:00",
        "monotonic_ns": seq,
        "synthetic": True,
        "data": data,
    }


class DerivedConfidenceTests(unittest.TestCase):
    def test_two_options_even_split_is_zero(self):
        self.assertAlmostEqual(derived_confidence([0.5, 0.5]), 0.0)

    def test_two_options_certain_choice_is_one(self):
        self.assertAlmostEqual(derived_confidence([1.0, 0.0]), 1.0)

    def test_three_options_matches_formula(self):
        # n=3, p_max=0.6 -> (3*0.6 - 1) / (3 - 1) = 0.4
        self.assertAlmostEqual(derived_confidence([0.6, 0.3, 0.1]), 0.4)

    def test_single_option_is_undefined(self):
        self.assertIsNone(derived_confidence([1.0]))

    def test_empty_is_undefined(self):
        self.assertIsNone(derived_confidence([]))


class GateCurveTests(unittest.TestCase):
    def test_coverage_and_accuracy_split_at_threshold(self):
        pairs = [
            (0.95, True),
            (0.92, True),
            (0.60, False),
            (0.55, True),
        ]
        rows = gate_curve(pairs, thresholds=(0.9,))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["threshold"], 0.9)
        self.assertEqual(row["n_above"], 2)
        self.assertEqual(row["n_below"], 2)
        self.assertAlmostEqual(row["coverage"], 0.5)
        self.assertAlmostEqual(row["accuracy_above"], 1.0)
        self.assertAlmostEqual(row["accuracy_below"], 0.5)

    def test_empty_side_reports_none_accuracy_not_zero(self):
        pairs = [(0.99, True), (0.98, True)]
        rows = gate_curve(pairs, thresholds=(0.5,))
        row = rows[0]
        self.assertEqual(row["n_below"], 0)
        self.assertIsNone(row["accuracy_below"])
        self.assertEqual(row["accuracy_above"], 1.0)

    def test_no_pairs_reports_none_coverage(self):
        rows = gate_curve([], thresholds=(0.5,))
        self.assertIsNone(rows[0]["coverage"])
        self.assertIsNone(rows[0]["accuracy_above"])
        self.assertIsNone(rows[0]["accuracy_below"])

    def test_default_thresholds_match_the_spec(self):
        rows = gate_curve([(0.5, True)])
        thresholds = [r["threshold"] for r in rows]
        self.assertEqual(thresholds, [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99])


class CalibrationReportTests(unittest.TestCase):
    def test_shape_has_ece_bins_and_gate_curve(self):
        pairs = [(0.9, True), (0.9, True), (0.4, False), (0.4, True)]
        report = calibration_report(pairs, min_reliable_n=1)
        self.assertIn("ece", report)
        self.assertIn("bins", report)
        self.assertIn("low_n_bins", report)
        self.assertIn("n_observed", report)
        self.assertIn("gate_curve", report)
        self.assertEqual(report["n_observed"], 4)
        self.assertEqual(len(report["bins"]), 10)
        self.assertEqual(len(report["gate_curve"]), 7)

    def test_low_n_bins_excluded_from_headline_by_default(self):
        # Only 2 observations total: well under the default min_reliable_n
        # (30), so every populated bin is "low n" and the headline ECE
        # (computed only over reliable bins) is None.
        pairs = [(0.95, True), (0.95, True)]
        report = calibration_report(pairs)
        self.assertIsNone(report["ece"])
        self.assertTrue(any(b["n"] > 0 for b in report["low_n_bins"]))


class JoinedPairsTests(unittest.TestCase):
    def test_joins_receipts_and_labels_on_decision_id(self):
        events = [
            _event("e1", "d1", "requested", {"domain": "tool-choice"}),
            _event(
                "e2",
                "d1",
                "scored",
                {"domain": "tool-choice", "selected_probability": 0.9},
                seq=2,
            ),
            _event("e3", "d2", "requested", {"domain": "tool-choice"}, turn_id="t2"),
            _event(
                "e4",
                "d2",
                "scored",
                {"domain": "tool-choice", "selected_probability": 0.4},
                seq=2,
                turn_id="t2",
            ),
            # d3 has a scored event but no label -- must be dropped, not
            # scored against a fabricated label.
            _event(
                "e5",
                "d3",
                "scored",
                {"domain": "tool-choice", "selected_probability": 0.7},
                turn_id="t3",
            ),
        ]
        labels = [
            {"decision_id": "d1", "correct": True},
            {"decision_id": "d2", "correct": False},
            # d4 has a label but no receipt -- must also be dropped.
            {"decision_id": "d4", "correct": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            labels_path = Path(tmp) / "labels.jsonl"
            labels_path.write_text(
                "\n".join(json.dumps(row) for row in labels) + "\n", encoding="utf-8"
            )
            pairs = joined_pairs(events_path, labels_path)
        self.assertEqual(sorted(pairs), [(0.4, False), (0.9, True)])

    def test_malformed_label_row_is_skipped_not_coerced(self):
        events = [
            _event(
                "e1",
                "d1",
                "scored",
                {"domain": "tool-choice", "selected_probability": 0.8},
            ),
        ]
        labels = [
            {"decision_id": "d1", "correct": "yes"},  # not a bool -- skipped
        ]
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            labels_path = Path(tmp) / "labels.jsonl"
            labels_path.write_text(
                "\n".join(json.dumps(row) for row in labels) + "\n", encoding="utf-8"
            )
            pairs = joined_pairs(events_path, labels_path)
        self.assertEqual(pairs, [])


if __name__ == "__main__":
    unittest.main()
