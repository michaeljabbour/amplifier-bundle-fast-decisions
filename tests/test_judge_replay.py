"""Replay tests: recompute committed judge results offline. No network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from evals import judges  # noqa: E402
from evals.judge_bench import scoring  # noqa: E402

FIRST_PASS = ROOT / "docs" / "evidence" / "2026-09-30-judge-comparison"


class FirstPassReplayTests(unittest.TestCase):
    def setUp(self):
        self.summary = json.loads((FIRST_PASS / "summary.json").read_text(encoding="utf-8"))
        self.cases = {c["id"]: c for c in json.loads((FIRST_PASS / "manifest.json").read_text(encoding="utf-8"))["cases"]}
        self.rows = [json.loads(line) for line in (FIRST_PASS / "requests.jsonl").read_text(encoding="utf-8").splitlines()
                     if line.strip()]

    def test_study_policy_reproduces_committed_counts(self):
        policy = scoring.POLICIES["study-0.75"]
        arms = sorted({r["arm"] for r in self.rows})
        self.assertEqual(sorted(self.summary), arms)
        for arm in arms:
            valid = auto = errors = correct = 0
            for row in self.rows:
                if row["arm"] != arm or row["order"] != 0 or not row["valid"]:
                    continue
                s = scoring.score(self.cases[row["id"]], row["answer"], row["elapsed_ms"], policy)
                valid += 1
                correct += s["correct"]
                auto += s["automatic"]
                errors += s["automatic_error"]
            want = self.summary[arm]["all/all"]
            with self.subTest(arm=arm):
                self.assertEqual((valid, correct, auto, errors),
                                 (want["valid"], want["correct"], want["automatic"], want["automatic_errors"]))

    def test_full_summary_pipeline_agrees(self):
        cfg = judges.load_config()
        meta = judges._meta_from_cfg(cfg)
        meta["policies"] = ["study-0.75", "bundle-read-shortcut"]
        meta["primary_policy"] = "bundle-read-shortcut"
        summary = judges.build_summary(self.rows, list(self.cases.values()), judges.case_lib.load_tags("dev"), meta)
        for arm, want in self.summary.items():
            block = summary["arms"][arm]["policies"]["study-0.75"]["reps"]["1"]
            with self.subTest(arm=arm):
                self.assertEqual((block["correct"], block["automatic"], block["automatic_errors"]),
                                 (want["all/all"]["correct"], want["all/all"]["automatic"],
                                  want["all/all"]["automatic_errors"]))


class CommittedBenchmarkReplayTests(unittest.TestCase):
    def test_committed_benchmarks_replay_byte_identical(self):
        found = sorted((ROOT / "docs" / "evidence").glob("*-judge-benchmark/**/requests.jsonl"))
        if not found:
            self.skipTest("no committed judge-benchmark evidence yet")
        for requests in found:
            with self.subTest(evidence=requests.parent.name), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(judges.main(["--replay", str(requests), "--out", tmp]), 0)
                self.assertEqual((Path(tmp) / "summary.json").read_bytes(),
                                 (requests.parent / "summary.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
