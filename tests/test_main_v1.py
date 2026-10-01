"""main-v1 finalization: the stock loader accepts all 75 files, the preregistered split is a reproducible pure function of
the files, the main design plans, the A/A subsample and the long-block TODO behave. No scenario code is executed."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path

from paired_helpers import REPO_ROOT, paired, ps

BASE = REPO_ROOT / "evals" / "paired" / "scenarios"
FAMILIES = ("polyglot", "repos", "mixed", "knowledge")
spec_ = importlib.util.spec_from_file_location("assign_split", BASE / "main-v1" / "assign_split.py")
assign_split = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(assign_split)


class LoaderTests(unittest.TestCase):
    def test_stock_loader_accepts_all_75_files(self):
        n = len(ps.load_dir(BASE / "pilot-v1")) + sum(len(ps.load_dir(BASE / "main-v1" / f)) for f in FAMILIES)
        self.assertEqual(n, 75)

    def test_docs_and_explain_are_task_types_and_main_is_not_a_split(self):
        self.assertIn("docs", ps.TASK_TYPES)
        self.assertIn("explain", ps.TASK_TYPES)
        self.assertIn("knowledge", ps.TASK_TYPES)
        src = (REPO_ROOT / "scripts" / "paired_scenarios.py").read_text(encoding="utf-8")   # assign_split patches SPLITS in-process
        self.assertIn('SPLITS = ("train", "test", "pilot")', src)
        types = {s.task_type for s in ps.load_dir(BASE / "main-v1" / "knowledge")}
        self.assertTrue({"docs", "explain"} <= types)

    def test_load_dir_takes_a_list_and_rejects_duplicates(self):
        both = ps.load_dir([BASE / "main-v1" / "repos", BASE / "main-v1" / "knowledge"])
        self.assertEqual(len(both), 16 + 14)
        with self.assertRaises(ps.ScenarioError):
            ps.load_dir([BASE / "main-v1" / "repos", BASE / "main-v1" / "repos"])

    def test_pilot_keeps_its_split(self):
        self.assertEqual({s.split for s in ps.load_dir(BASE / "pilot-v1")}, {"pilot"})


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.rows = assign_split.load()
        self.res = assign_split.assign(self.rows)

    def test_files_match_the_seeded_assignment(self):
        for r in self.rows:
            text = r["path"].read_text(encoding="utf-8")
            self.assertIn(f"\nsplit: {self.res['split'][r['id']]}\n", text, r["id"])

    def test_assignment_is_deterministic_and_seed_dependent(self):
        self.assertEqual(self.res["split"], assign_split.assign(self.rows)["split"])
        self.assertNotEqual(self.res["split"], assign_split.assign(self.rows, seed=1)["split"])
        self.assertEqual(assign_split.SEED, 20261002)

    def test_a_third_is_test_and_every_stratum_has_both_halves(self):
        c = Counter(self.res["split"].values())
        self.assertEqual((c["train"], c["test"]), (47, 23))
        t = assign_split.table(self.rows, self.res["split"])
        for fam in FAMILIES:
            for gp in ("long-gaps", "no-gaps"):
                self.assertGreater(t[(fam, gp)]["train"], 0, (fam, gp))
                self.assertGreater(t[(fam, gp)]["test"], 0, (fam, gp))

    def test_same_upstream_repo_same_split(self):
        by_unit = {}
        for r in self.rows:
            by_unit.setdefault(r["unit"], set()).add(self.res["split"][r["id"]])
        self.assertTrue(all(len(v) == 1 for v in by_unit.values()))
        self.assertEqual(self.res["split"]["lark-discard"], self.res["split"]["lark-template"])

    def test_split_md_lists_every_scenario(self):
        md = (BASE / "main-v1" / "SPLIT.md").read_text(encoding="utf-8")
        self.assertIn("20261002", md)
        for r in self.rows:
            self.assertIn(r["id"], md)


class CheckFixTests(unittest.TestCase):
    """The 8 VALIDATION.md check fixes are in the files (the guarded validators confirmed them against references)."""

    def text(self, sid):
        return (BASE / "main-v1" / "repos" / f"{sid}.yaml").read_text(encoding="utf-8")

    def test_bounded_changelog_patterns_replaced_the_unbounded_ones(self):
        self.assertIn(r"^Next Release\s*\n=+\n(?:(?!\d+\.\d+\.\d+\s*\n=).*\n)*?.*(?i:string)", self.text("jmespath-strcmp"))
        self.assertIn(r"(?:(?!\d+\.\d+\.\d+ \().*\n)*?.*match_file", self.text("pathspec-matchfile"))
        self.assertIn(r"def partition\([^)]*\)", self.text("pathspec-matchfile"))
        self.assertIn(r"^## Unreleased\n(?:(?!## v).*\n)*?.*Optional", self.text("schema-wrongkey"))
        self.assertIn("pattern: wrong_keys, min_count: 8", self.text("schema-wrongkey"))
        self.assertEqual(self.text("sortedc-update").count(r"^2\.2\.3 \(unreleased\)\n-{10,}\n(?:"), 2)
        self.assertEqual(self.text("sqlparse-realname").count(r"Development Version\n-+\n(?:(?!Release ).*\n)*?"), 2)

    def test_patterns_compile_and_do_not_match_a_pristine_changelog_stub(self):
        import re
        pat = r"^## Unreleased\n(?:(?!## v).*\n)*?.*Optional"
        self.assertIsNone(re.search(pat, "## Unreleased\n\n## v1.0\n- Optional thing\n", re.M))
        self.assertTrue(re.search(pat, "## Unreleased\n### Fixes\n* Optional keys\n## v1.0\n", re.M))


class MainDesignTests(unittest.TestCase):
    def setUp(self):
        self.design = paired.load_design(REPO_ROOT / "evals" / "paired" / "main-v1.yaml")
        self.specs = paired.load_specs(self.design)

    def test_design_shape(self):
        d = self.design
        self.assertEqual((d["default_reps"], d["default_parallel"], list(d["hosts"])), (2, 4, ["opus", "fable"]))
        self.assertEqual(list(d["arms"]), ["anchor", "aa", "shipped", "sticky", "sonnet"])
        self.assertEqual(len(self.specs), 70)
        self.assertEqual(d["long_block"]["status"], "TODO")
        self.assertEqual({s.split for s in self.specs}, {"train", "test"})
        for t in {s.task_type for s in self.specs}:
            self.assertIn(t, d["cost_model"]["type_factor"])

    def test_long_block_candidates_are_train_scenarios_and_never_scheduled(self):
        by_id = {s.id: s for s in self.specs}
        cands = self.design["long_block"]["candidates"]
        self.assertEqual(len(cands), 6)
        self.assertTrue(all(by_id[c].split == "train" for c in cands))
        plan = paired.build_plan(self.design, self.specs, reps=1, hosts=["opus"], arms=["anchor"], seed=1, budget_usd=None, parallel=4)
        self.assertFalse(plan["long_block"]["scheduled"])
        self.assertGreater(plan["long_block"]["est_usd_if_authored"], 0)
        self.assertIn("NOT scheduled", paired.render_plan(plan))

    def test_aa_runs_in_a_stratified_20_percent_subsample_on_both_hosts(self):
        keys = paired.subsample_keys(self.specs, 2, self.design["arms"]["aa"]["subsample"])
        self.assertEqual(keys, paired.subsample_keys(self.specs, 2, self.design["arms"]["aa"]["subsample"]))      # seeded
        self.assertTrue(abs(len(keys) - 0.2 * 140) <= 4, len(keys))
        plan = paired.build_plan(self.design, self.specs, reps=2, hosts=["opus", "fable"], arms=["anchor", "aa"], seed=1, budget_usd=None, parallel=4)
        aa = [s for w in plan["waves"].values() for s in w if s["arm"] == "aa"]
        self.assertEqual(len(aa), 2 * len(keys))
        self.assertEqual({(s["scenario"], s["rep"]) for s in aa}, keys)
        anchors = [s for w in plan["waves"].values() for s in w if s["arm"] == "anchor"]
        self.assertEqual(len(anchors), 280)
        by_id = {s.id: s for s in self.specs}
        for split in ("train", "test"):
            self.assertTrue(any(by_id[sid].split == split for sid, _ in keys))

    def test_full_plan_counts_and_wave_sizes_fit_parallel_4(self):
        plan = paired.build_plan(self.design, self.specs, reps=2, hosts=["opus", "fable"], arms=list(self.design["arms"]), seed=20261002,
                                 budget_usd=self.design["budget_usd"], parallel=4)
        self.assertEqual(plan["n_sessions"], 1036)
        self.assertLessEqual(max(len(v) for v in plan["waves"].values()), 4)
        self.assertTrue(plan["control_waves_split"])
        self.assertLess(plan["est_with_reserve_usd"], self.design["budget_usd"])
        self.assertGreater(plan["est_wall_hours"], 10)

    def test_wall_simulation_respects_fifo_admission(self):
        class S:                        # minimal session/spec stand-ins
            def __init__(self, sid): self.scenario = sid
        class Sp:
            turns = [0] * 4
            gap_schedule = [0, 0, 0, 0]
        waves = {"a": [S("x")] * 4, "b": [S("x")] * 4, "c": [S("x")] * 2, "d": [S("x")] * 2}
        d = {"wall_model": {"minutes_per_turn": 1.0, "wave_slowest_factor": 1.0}}
        h4 = paired.simulate_wall_hours(d, waves, ["a", "b", "c", "d"], {"x": Sp()}, 4)
        h8 = paired.simulate_wall_hours(d, waves, ["a", "b", "c", "d"], {"x": Sp()}, 8)
        self.assertAlmostEqual(h4, 0.2, places=1)                      # a, b, then c+d together: 3 waves of 4 min = 12 min
        self.assertLess(h8, h4)


if __name__ == "__main__":
    unittest.main()
