"""Tests for scripts/battery_tasks.py -- the 20-task coding-agent battery."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import battery_tasks as bt  # noqa: E402


def _materialize(files: dict, extra: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    merged = dict(files)
    if extra:
        merged.update(extra)
    for name, content in merged.items():
        path = d / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return d


class TestRegistryShape(unittest.TestCase):
    def test_exactly_twenty_tasks_five_per_family(self):
        self.assertEqual(len(bt.TASKS), 20)
        counts = {}
        for t in bt.TASKS.values():
            counts[t.family] = counts.get(t.family, 0) + 1
        self.assertEqual(counts, {"repair": 5, "edit": 5, "bugfix": 5, "answer": 5})

    def test_three_dev_two_holdout_per_family(self):
        by_family_split = {}
        for t in bt.TASKS.values():
            by_family_split.setdefault(t.family, {"dev": 0, "holdout": 0})
            self.assertIn(t.split, ("dev", "holdout"), t.name)
            by_family_split[t.family][t.split] += 1
        for family, counts in by_family_split.items():
            self.assertEqual(counts["dev"], 3, family)
            self.assertEqual(counts["holdout"], 2, family)

    def test_unique_names(self):
        names = [t.name for t in bt.TASKS.values()]
        self.assertEqual(len(names), len(set(names)))
        for name, t in bt.TASKS.items():
            self.assertEqual(name, t.name)

    def test_every_prompt_ends_with_suffix(self):
        for name, t in bt.TASKS.items():
            self.assertTrue(t.prompt.endswith(bt.PROMPT_SUFFIX), name)

    def test_every_files_dict_has_readme(self):
        for name, t in bt.TASKS.items():
            self.assertIn("README.md", t.files, name)

    def test_protected_includes_readme_and_public_test_when_present(self):
        for name, t in bt.TASKS.items():
            self.assertIn("README.md", t.protected, name)
            if "test_public.py" in t.files:
                self.assertIn("test_public.py", t.protected, name)

    def test_families_and_split_helpers(self):
        self.assertEqual(set(bt.families()), {"repair", "edit", "bugfix", "answer"})
        dev = bt.split("dev")
        holdout = bt.split("holdout")
        allnames = bt.split("all")
        self.assertEqual(len(dev), 12)
        self.assertEqual(len(holdout), 8)
        self.assertEqual(set(dev) | set(holdout), set(allnames))
        self.assertEqual(len(allnames), 20)
        with self.assertRaises(ValueError):
            bt.split("nonsense")


class TestCodeTasks(unittest.TestCase):
    """For every 'code' task: unmodified starter fails, reference solution
    passes with failed == 0, and (when shipped) test_public.py passes via
    `python -m unittest` in a subprocess for the reference solution, and
    fails for the unmodified starter (bugfix family)."""

    def test_all_code_tasks(self):
        code_tasks = [t for t in bt.TASKS.values() if t.kind == "code"]
        self.assertEqual(len(code_tasks), 15)
        for task in code_tasks:
            with self.subTest(task=task.name):
                ws = _materialize(task.files)
                try:
                    result = task.evaluate(ws)
                    self.assertGreater(result["failed"], 0, f"{task.name}: starter should fail evaluate")
                finally:
                    shutil.rmtree(ws, ignore_errors=True)

                overrides = bt.REFERENCE_SOLUTIONS.get(task.name)
                self.assertIsNotNone(overrides, f"{task.name}: missing REFERENCE_SOLUTIONS entry")
                ws2 = _materialize(task.files, overrides)
                try:
                    result2 = task.evaluate(ws2)
                    self.assertEqual(
                        result2["failed"], 0,
                        f"{task.name}: reference solution should pass, got {result2['failure_labels']}",
                    )
                    self.assertGreater(result2["checks"], 0, task.name)

                    if "test_public.py" in task.files:
                        proc = subprocess.run(
                            [sys.executable, "-m", "unittest", "test_public.py"],
                            cwd=str(ws2),
                            capture_output=True,
                            text=True,
                            timeout=20,
                        )
                        self.assertEqual(
                            proc.returncode, 0,
                            f"{task.name}: reference solution should pass test_public.py\n{proc.stdout}\n{proc.stderr}",
                        )
                finally:
                    shutil.rmtree(ws2, ignore_errors=True)

    def test_bugfix_starters_fail_public_test(self):
        for task in bt.TASKS.values():
            if task.family != "bugfix":
                continue
            with self.subTest(task=task.name):
                ws = _materialize(task.files)
                try:
                    proc = subprocess.run(
                        [sys.executable, "-m", "unittest", "test_public.py"],
                        cwd=str(ws),
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    self.assertNotEqual(proc.returncode, 0, f"{task.name}: buggy starter should fail public test")
                finally:
                    shutil.rmtree(ws, ignore_errors=True)


class TestAnswerTasks(unittest.TestCase):
    _CORRECT = {
        "answer_audit_log_key": ["AUD-ORDER-7781", "`AUD-ORDER-7781`", "aud-order-7781."],
        "answer_compute_fee": ["480", "`480`", "The fee is 480."],
        "answer_sqlite_import_module": ["storage", "`storage`", "STORAGE"],
        "answer_default_port": ["8765"],
        "answer_exception_count": ["4", "four", "There are 4 distinct exceptions."],
    }
    _DECOYS = {
        "answer_audit_log_key": ["MET-ORDER-7781", "AUD-ORDER-7782", "AUD-order-778"],
        "answer_compute_fee": ["600", "500", "120"],
        "answer_sqlite_import_module": ["decoy_db_helpers", "cache", "network", "utils"],
        "answer_default_port": ["9999", "80", "443"],
        "answer_exception_count": ["3", "5", "2"],
    }

    def test_answer_tasks_are_answer_kind_with_zero_check_evaluate(self):
        for name in self._CORRECT:
            task = bt.TASKS[name]
            self.assertEqual(task.kind, "answer", name)
            self.assertEqual(task.family, "answer", name)
            result = task.evaluate(Path("/nonexistent"))
            self.assertEqual(result, {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []})

    def test_correct_answers_pass(self):
        for name, answers in self._CORRECT.items():
            task = bt.TASKS[name]
            for ans in answers:
                with self.subTest(task=name, answer=ans):
                    result = bt.check_answer(task, f"ANSWER: {ans}")
                    self.assertEqual(result["failed"], 0, result)
                    self.assertEqual(result["passed"], 1)

    def test_decoys_and_missing_answer_fail(self):
        for name, decoys in self._DECOYS.items():
            task = bt.TASKS[name]
            for decoy in decoys:
                with self.subTest(task=name, decoy=decoy):
                    result = bt.check_answer(task, f"ANSWER: {decoy}")
                    self.assertEqual(result["failed"], 1, result)
            with self.subTest(task=name, case="no_answer_line"):
                result = bt.check_answer(task, "DONE: finished looking around")
                self.assertEqual(result["failed"], 1)
            with self.subTest(task=name, case="none"):
                result = bt.check_answer(task, None)
                self.assertEqual(result["failed"], 1)


if __name__ == "__main__":
    unittest.main()
