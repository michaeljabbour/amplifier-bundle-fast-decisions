"""Scenario spec: loading, validation, stable hashes, gap schedule, pilot set hygiene, and graders."""
from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from paired_helpers import INLINE_SCENARIO, REPO_ROOT, paired, ps

PILOT_DIR = REPO_ROOT / "evals" / "paired" / "scenarios" / "pilot-v1"
# The S2 40-exercise slice (seed 20260919; python/rust/go/cpp), computed with polyglot_tasks.select_slice.
S2_SLICE = {
    "cpp": "allergies binary-search-tree circular-buffer diamond gigasecond grade-school kindergarten-garden perfect-numbers robot-name zebra-puzzle",
    "go": "beer-song book-store dnd-character error-handling kindergarten-garden ledger matrix transpose tree-building two-bucket",
    "python": "affine-cipher connect food-chain hangman proverb react robot-name transpose wordy zebra-puzzle",
    "rust": "acronym decimal doubly-linked-list macros nucleotide-codons parallel-letter-frequency pig-latin robot-name scale-generator simple-cipher",
}
POLYGLOT = "polyglot-benchmark"


class PilotSetTests(unittest.TestCase):
    def setUp(self):
        self.specs = ps.load_dir(PILOT_DIR)

    def test_five_scenarios_of_eight_turns(self):
        self.assertEqual(len(self.specs), 5)
        for s in self.specs:
            self.assertEqual(len(s.turns), 8, s.id)

    def test_exactly_one_scenario_has_two_seven_minute_gaps(self):
        gaps = {s.id: s.n_long_gaps for s in self.specs}
        self.assertEqual([k for k, v in gaps.items() if v], ["rust-wordcount"])
        self.assertEqual(gaps["rust-wordcount"], 2)
        rust = next(s for s in self.specs if s.id == "rust-wordcount")
        self.assertEqual([i + 1 for i, g in enumerate(rust.gap_schedule) if g == 420], [3, 6])

    def test_polyglot_exercises_are_outside_the_s2_slice(self):
        checked = 0
        for s in self.specs:
            sub = s.workspace.get("subdir", "")
            if "/exercises/practice/" not in sub:
                continue
            lang, slug = sub.split("/")[0], sub.split("/")[-1]
            self.assertNotIn(slug, S2_SLICE[lang].split(), f"{s.id} is in the S2 slice")
            checked += 1
        self.assertEqual(checked, 3)

    def test_ids_do_not_collide_with_s1_tasks(self):
        import battery_tasks
        for s in self.specs:
            self.assertNotIn(s.id, battery_tasks.TASKS)

    def test_every_workspace_is_pinned_to_a_full_sha(self):
        for s in self.specs:
            self.assertRegex(s.workspace["sha"], r"^[0-9a-f]{40}$")

    def test_hidden_files_never_appear_in_prompts(self):
        for s in self.specs:
            blob = "\n".join(ps.turn_prompts(s))
            for name in s.hidden_files:
                self.assertNotIn(Path(name).name, blob)

    def test_every_turn_has_a_deterministic_check(self):
        for s in self.specs:
            for i, t in enumerate(s.turns, start=1):
                self.assertTrue(t.checks, f"{s.id} turn {i} has no check")


class SpecValidationTests(unittest.TestCase):
    def base(self):
        return copy.deepcopy(INLINE_SCENARIO)

    def test_valid_inline_parses_and_default_gaps(self):
        s = ps.parse(self.base())
        self.assertEqual(s.gap_schedule, [0, 10, 420])
        self.assertEqual(s.n_long_gaps, 1)

    def test_rejections(self):
        cases = [("id", "Bad Id"), ("id", "x" * 40), ("task_type", "nope"), ("split", "dev"), ("turns", [{"prompt": "x"}])]
        for key, value in cases:
            d = self.base()
            d[key] = value
            with self.assertRaises(ps.ScenarioError, msg=key):
                ps.parse(d)

    def test_unpinned_git_workspace_rejected(self):
        d = self.base()
        d["workspace"] = {"kind": "git", "repo": "https://x/y.git", "sha": "main"}
        with self.assertRaises(ps.ScenarioError):
            ps.parse(d)

    def test_undeclared_hidden_file_rejected(self):
        d = self.base()
        d["turns"][0]["checks"] = [{"kind": "tests", "runner": "python", "hidden": ["missing.py"]}]
        with self.assertRaises(ps.ScenarioError):
            ps.parse(d)

    def test_bad_regex_rejected(self):
        d = self.base()
        d["turns"][1]["checks"] = [{"kind": "keyed_facts", "all": ["(unclosed"]}]
        with self.assertRaises(Exception):
            ps.parse(d)

    def test_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            import yaml
            for n in ("a", "b"):
                (Path(t) / f"{n}.yaml").write_text(yaml.safe_dump(self.base()))
            with self.assertRaises(ps.ScenarioError):
                ps.load_dir(t)


class HashTests(unittest.TestCase):
    def test_hash_stable_and_sensitive(self):
        a, b = ps.parse(copy.deepcopy(INLINE_SCENARIO)), ps.parse(copy.deepcopy(INLINE_SCENARIO))
        self.assertEqual(ps.scenario_hash(a), ps.scenario_hash(b))
        self.assertEqual(ps.prompt_hash(a), ps.prompt_hash(b))
        d = copy.deepcopy(INLINE_SCENARIO)
        d["turns"][1]["prompt"] = "Explain the change differently."
        c = ps.parse(d)
        self.assertNotEqual(ps.scenario_hash(a), ps.scenario_hash(c))
        self.assertNotEqual(ps.prompt_hash(a), ps.prompt_hash(c))
        d2 = copy.deepcopy(INLINE_SCENARIO)
        d2["turns"][0]["checks"] = []
        self.assertNotEqual(ps.scenario_hash(a), ps.scenario_hash(ps.parse(d2)))
        self.assertEqual(ps.prompt_hash(a), ps.prompt_hash(ps.parse(d2)))   # checks are not part of the prompt

    def test_prompts_carry_the_rules_suffix_exactly_once(self):
        s = ps.parse(copy.deepcopy(INLINE_SCENARIO))
        for p in ps.turn_prompts(s):
            self.assertEqual(p.count("Rules: work only inside this directory"), 1)


class GraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.spec = ps.parse(copy.deepcopy(INLINE_SCENARIO))
        self.snap = ps.materialize(self.spec, self.tmp / "snaps")
        self.ws = self.tmp / "ws"
        shutil.copytree(self.snap / "workspace", self.ws)

    def test_snapshot_is_idempotent_and_frozen(self):
        again = ps.materialize(self.spec, self.tmp / "snaps")
        self.assertEqual(again, self.snap)
        (self.snap / "workspace" / "solution.py").write_text("tampered")
        with self.assertRaises(ps.ScenarioError):
            ps.materialize(self.spec, self.tmp / "snaps")

    def test_tests_check_fails_then_passes(self):
        self.assertEqual(ps.grade_turn(self.spec, 1, self.ws, "", self.snap)["failed"], 1)
        (self.ws / "solution.py").write_text("def f():\n    return 1\n")
        self.assertEqual(ps.grade_turn(self.spec, 1, self.ws, "", self.snap)["failed"], 0)

    def test_protected_file_edit_fails_every_turn(self):
        (self.ws / "solution.py").write_text("def f():\n    return 1\n")
        (self.ws / "test_public.py").write_text("def test_f():\n    assert True\n")
        q = ps.grade_turn(self.spec, 1, self.ws, "", self.snap)
        self.assertGreaterEqual(q["failed"], 1)
        self.assertTrue(any(l.startswith("protected_modified") for l in q["failure_labels"]))

    def test_keyed_facts_use_the_final_message(self):
        self.assertEqual(ps.grade_turn(self.spec, 2, self.ws, "nothing", self.snap)["failed"], 2 - 1)  # protected ok, fact missing
        self.assertEqual(ps.grade_turn(self.spec, 2, self.ws, "It now will RETURN 1", self.snap)["failed"], 0)

    def test_doc_sections_and_file_regex(self):
        self.assertGreaterEqual(ps.grade_turn(self.spec, 3, self.ws, "", self.snap)["failed"], 2)
        (self.ws / "NOTES.md").write_text("# Notes\n## Usage\ntext\n")
        (self.ws / "solution.py").write_text("def f():\n    return 1\n")
        self.assertEqual(ps.grade_turn(self.spec, 3, self.ws, "", self.snap)["failed"], 0)

    def test_hidden_overlay_is_applied_only_in_the_private_copy(self):
        d = copy.deepcopy(INLINE_SCENARIO)
        d["id"] = "tiny-hidden"
        d["hidden_files"] = {"hidden_test.py": "from solution import f\n\ndef test_hidden():\n    assert f() == 7\n"}
        d["turns"][0]["checks"] = [{"kind": "tests", "runner": "python", "files": ["hidden_test.py"], "hidden": ["hidden_test.py"]}]
        spec = ps.parse(d)
        snap = ps.materialize(spec, self.tmp / "snaps")
        self.assertFalse((snap / "workspace" / "hidden_test.py").exists())
        ws = self.tmp / "ws2"
        shutil.copytree(snap / "workspace", ws)
        (ws / "solution.py").write_text("def f():\n    return 7\n")
        self.assertEqual(ps.grade_turn(spec, 1, ws, "", snap)["failed"], 0)
        self.assertFalse((ws / "hidden_test.py").exists())

    def test_a_crashing_check_is_a_failed_check_not_an_exception(self):
        d = copy.deepcopy(INLINE_SCENARIO)
        d["id"] = "tiny-crash"
        d["turns"][1]["checks"] = [{"kind": "doc_sections", "path": "x.md", "headings": ["A"]}]
        spec = ps.parse(d)
        snap = ps.materialize(spec, self.tmp / "snaps")
        q = ps.grade_turn(spec, 2, self.tmp / "does-not-exist", "", snap)
        self.assertGreaterEqual(q["failed"], 1)

    def test_grading_is_deterministic(self):
        (self.ws / "solution.py").write_text("def f():\n    return 1\n")
        a = [ps.grade_turn(self.spec, 1, self.ws, "", self.snap) for _ in range(3)]
        self.assertTrue(all(x == a[0] for x in a))


POLY = Path.home() / "dev/afast-campaign-corrected-polyglot-20260919/polyglot/polyglot-benchmark"


@unittest.skipUnless(POLY.exists(), "local polyglot checkout not present")
class BowlingReferenceTests(unittest.TestCase):
    """The pilot's hidden tests are satisfiable and detect the unsolved starter (end-to-end grader check)."""

    def test_reference_solution_passes_every_turn_and_starter_fails(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        spec = next(s for s in ps.load_dir(PILOT_DIR) if s.id == "py-bowling")
        snap = ps.materialize(spec, tmp / "snaps")
        ws = tmp / "ws"
        shutil.copytree(snap / "workspace", ws)
        self.assertGreater(ps.grade_turn(spec, 1, ws, "", snap)["failed"], 0)
        shutil.copy(REPO_ROOT / "tests/fixtures/paired/bowling_ref.py", ws / "bowling.py")
        (ws / "README_BOWLING.md").write_text("# B\n## Usage\n## API\n## Scoring rules\n## Examples\n")
        (ws / "test_extra.py").write_text("from bowling import BowlingGame\n" + "".join(
            f"def test_{i}():\n    g = BowlingGame(); g.roll(3); assert g.frames() == [[3]]\n" for i in range(6)))
        for i in range(1, 9):
            q = ps.grade_turn(spec, i, ws, "The 10th frame: strike, spare, bonus fill rolls", snap)
            self.assertEqual(q["failed"], 0, f"turn {i}: {q}")


if __name__ == "__main__":
    unittest.main()
