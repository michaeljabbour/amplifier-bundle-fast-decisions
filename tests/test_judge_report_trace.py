"""report.py trace mode: copy and drill-down for trace-derived splits; constructed pages stay byte-identical."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from evals.judge_bench import report  # noqa: E402

CONSTRUCTED = ROOT / "docs" / "evidence" / "2026-09-30-judge-benchmark"
TRACE = ROOT / "docs" / "evidence" / "2026-10-01-trace-judge-benchmark"


@unittest.skipUnless((CONSTRUCTED / "index.html").exists(), "constructed evidence not present")
class ConstructedPageUnchangedTests(unittest.TestCase):
    def test_constructed_page_is_byte_identical_to_the_committed_one(self):
        self.assertEqual(report.build(CONSTRUCTED), (CONSTRUCTED / "index.html").read_text(encoding="utf-8"))

    def test_constructed_page_keeps_its_original_copy(self):
        html = report.build(CONSTRUCTED)
        self.assertIn("90 or 63 cases", html)
        self.assertIn("<em>Buy now</em>", html)
        self.assertIn("deliberately adversarial", html)
        self.assertIn("Frozen label", html)


@unittest.skipUnless((TRACE / "dev" / "manifest.json").exists(), "trace evidence not present")
class TraceModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = report.build(TRACE)
        cls.holdout = report.load_split(TRACE / "holdout", "holdout")
        cls.dev = report.load_split(TRACE / "dev", "dev")

    def test_trace_splits_are_detected(self):
        self.assertTrue(self.holdout["trace"])
        self.assertTrue(self.dev["trace"])

    def test_copy_uses_actual_counts_and_real_read_examples(self):
        n_dev, n_hold = len(self.dev["cases"]), len(self.holdout["cases"])
        self.assertIn(f"given only {n_dev} (dev) and {n_hold} (holdout) cases", self.html)
        for gone in ("90 or 63", "Buy now", "adversarial", "stress test", "frozen label", "computer-use"):
            self.assertNotIn(gone, self.html, gone)
        self.assertIn("reading a file that was not the right next step", self.html)
        self.assertIn("real decisions the in-session judge sent to the host; reads have no side effects", self.html)

    def test_headline_cost_aggregation_is_named(self):
        self.assertIn("mean over repetitions of each repetition's mean billed-token cost", self.html)
        luna = next(j for j in self.holdout["judges"] if j["arm"] == "gpt-6-luna")
        summary = json.loads((TRACE / "holdout" / "summary.json").read_text(encoding="utf-8"))
        reps = [r["cost"]["usd_per_1m_decisions"] for r in summary["arms"]["gpt-6-luna"]["reps"].values()]
        self.assertAlmostEqual(luna["usd1m"], sum(reps) / len(reps))

    def test_drill_down_carries_observations_options_and_every_label(self):
        labels = json.loads(report.TRACE_LABELS.read_text(encoding="utf-8"))["labels"]
        for sp in (self.dev, self.holdout):
            for case in sp["cases"]:
                self.assertIsInstance(case["state"].get("observations"), list)
                self.assertIn("reason", case["options"])
                a, ref = case["audit"], labels[case["id"]]
                self.assertTrue(a["trace"])
                self.assertEqual((a["frozen"], a["outcome_label"], a["A"]["label"], a["B"]["label"], a["decision"]),
                                 (case["expected"], ref["outcome_label"], ref["reviewer_A"], ref["reviewer_B"],
                                  ref["decision"]))
                self.assertEqual(a["hard_to_answer"], bool(ref["hard_to_answer"]))
        self.assertIn("Observation ' + (n + 1)", self.html)
        self.assertIn("Outcome label (the host", self.html)
        self.assertIn("Reviewer ' + who", self.html)
        self.assertIn("Flags: ", self.html)

    def test_qwen_native_arms_stay_in_the_generic_local_family(self):
        fam = {j["arm"]: j["family"] for j in self.holdout["judges"]}
        for arm in ("qwen3-0.6b", "qwen3-4b", "qwen3-8b"):
            self.assertEqual(fam[arm], "generic", arm)
        self.assertEqual(fam["gpt-6-luna"], "hosted")
        self.assertEqual(fam["jev-1.13"], "hosted")
        self.assertEqual(fam["nimble-9b"], "system_one")

    def test_labels_note_replaces_the_missing_audit_note(self):
        self.assertNotIn("label quality is unaudited", self.html)
        self.assertIn("two blind reviewers' shared label", self.html)


if __name__ == "__main__":
    unittest.main()
