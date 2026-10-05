"""effort-control-v1: plain-sonnet-medium differs from plain-sonnet ONLY in the provider reasoning effort."""
from __future__ import annotations

import difflib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from paired_helpers import REPO_ROOT, paired, ps, write_inline_scenario

import forge_e2e
import forge_workloads
import run as evals_run


class ProfileDiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scn = write_inline_scenario(self.tmp / "scn")
        self.spec = ps.load_dir(scn)[0]
        ps.materialize(self.spec, self.tmp / "snaps")
        self.source = {"kind": "paired", "scenario_dir": str(scn), "snapshot_root": str(self.tmp / "snaps"), "ids": [self.spec.id]}
        forge_workloads.register_source(**self.source)
        self.addCleanup(forge_workloads._extra_tasks.clear)
        self.cells = evals_run.load_cells(REPO_ROOT / "evals" / "cells.yaml")
        self.suites = evals_run.load_suites()
        self.provider = paired.load_design(REPO_ROOT / "evals" / "paired" / "effort-control-v1.yaml")["campaign_provider"]

    def render(self):
        sides, models = {}, {}
        for arm, cell in (("sonnet", "plain-sonnet"), ("sonnet_medium", "plain-sonnet-medium")):
            side, model, _ = paired.cell_to_side(cell, self.cells, self.suites, baseline_source=REPO_ROOT, candidate_source=REPO_ROOT, candidate_sha=None)
            sides[arm], models[arm] = {**side, "model": model}, model
        prompt = ps.TURN_SEPARATOR.join(ps.turn_prompts(self.spec))
        runs = [{"name": f"t-{a}", "task": self.spec.id, "side": a, "rep": 1, "attempt": 1, "block": None, "seed": 1, "prompt": prompt} for a in sides]
        config = {"runs": runs, "sides": sides, "provider": "anthropic", "model": models["sonnet"], "task_source": self.source,
                  "limits": {"timeout_seconds": 60, "max_iterations": 30, "extended_thinking": True}, "events_dir": str(self.tmp / "ev"),
                  "campaign_provider": self.provider}
        root = self.tmp / "r0"
        forge_e2e.prepare(root, config)
        return {a: (root / f"t-{a}" / "profile.md").read_text(encoding="utf-8") for a in sides}, sides

    def test_only_the_reasoning_effort_differs(self):
        texts, sides = self.render()
        self.assertNotIn("amplifier_effort", sides["sonnet"])
        self.assertEqual(sides["sonnet_medium"]["amplifier_effort"], "medium")
        norm = lambda s, n: [l.rstrip().rstrip(",") for l in s.replace(f"t-{n}", "t-RUN").splitlines()]       # per-run paths / JSON commas
        diff = [l for l in difflib.unified_diff(norm(texts["sonnet"], "sonnet"), norm(texts["sonnet_medium"], "sonnet_medium"), lineterm="", n=0)
                if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        # only the provider's reasoning_effort line is added; everything else (system prompt, tools, provider config) is identical
        self.assertEqual(len(diff), 1, diff)
        self.assertRegex(diff[0], r'^\+\s*"reasoning_effort": "medium"\s*$')
        a = json.loads(texts["sonnet"].split("---\n")[1].replace("t-sonnet", "t-RUN"))
        b = json.loads(texts["sonnet_medium"].split("---\n")[1].replace("t-sonnet_medium", "t-RUN"))
        pa, pb = a.pop("providers"), b.pop("providers")
        self.assertEqual(a, b)                                      # every non-provider key identical
        self.assertEqual(pb[0]["config"].pop("reasoning_effort"), "medium")
        self.assertEqual(pa, pb)                                    # providers identical once the effort is removed
        self.assertEqual(texts["sonnet"].split("\n---\n", 1)[1], texts["sonnet_medium"].split("\n---\n", 1)[1])      # identical prompt body

    def test_cells_are_identical_except_effort_and_labels(self):
        a, b = dict(self.cells["cells"]["plain-sonnet"]), dict(self.cells["cells"]["plain-sonnet-medium"])
        self.assertEqual(b.pop("amplifier_effort"), "medium")
        for k in ("label_suffix", "role", "purpose"):
            a.pop(k, None)
            b.pop(k, None)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()


class GateTests(unittest.TestCase):
    def gate(self, effort_expect, efforts, models=("claude-sonnet-5",) * 3):
        s = {"kind": "control", "gate": {"served_model_prefix": "claude-sonnet-5", "effort": effort_expect}}
        return paired.mechanism_gate(s, {}, 0, list(models), list(efforts))

    def test_default_arm_must_show_no_effort(self):
        self.assertTrue(self.gate("absent", [None, None, None])["mechanism_engaged"])
        g = self.gate("absent", [None, "medium", None])
        self.assertFalse(g["mechanism_engaged"])
        self.assertIn("medium", g["mechanism_reasons"][0])

    def test_medium_arm_must_show_medium_on_every_main_request(self):
        self.assertTrue(self.gate("medium", ["medium"] * 3)["mechanism_engaged"])
        self.assertFalse(self.gate("medium", ["medium", None, "medium"])["mechanism_engaged"])
        self.assertFalse(self.gate("medium", ["high"] * 3)["mechanism_engaged"])

    def test_served_model_must_be_sonnet_5(self):
        self.assertFalse(self.gate("medium", ["medium"] * 3, models=("claude-sonnet-5", "claude-opus-5-5", "claude-sonnet-5"))["mechanism_engaged"])

    def test_design_arms_carry_the_gates_into_sessions(self):
        d = paired.load_design(REPO_ROOT / "evals" / "paired" / "effort-control-v1.yaml")
        specs = paired.load_specs(d)
        self.assertEqual(len(specs), 23)
        self.assertEqual({s.split for s in specs}, {"test"})
        sess = paired.expand_sessions(d, specs, reps=2, hosts=list(d["hosts"]), arms=list(d["arms"]))
        self.assertEqual(len(sess), 92)
        by = {s.arm: s.gate for s in sess}
        self.assertEqual(by["sonnet"]["effort"], "absent")
        self.assertEqual(by["sonnet_medium"]["effort"], "medium")
        self.assertEqual({s.wave_id for s in sess if s.arm == "sonnet"}, {s.wave_id for s in sess if s.arm == "sonnet_medium"})   # same waves

    def test_plan_has_a_budget_below_400_and_two_session_waves(self):
        d = paired.load_design(REPO_ROOT / "evals" / "paired" / "effort-control-v1.yaml")
        plan = paired.build_plan(d, paired.load_specs(d), reps=2, hosts=list(d["hosts"]), arms=list(d["arms"]), seed=1, budget_usd=d["budget_usd"], parallel=8)
        self.assertEqual((plan["n_sessions"], plan["n_waves"], plan["anchor_arm"]), (92, 46, "sonnet"))
        self.assertLess(plan["est_with_reserve_usd"], 400)
        self.assertEqual({len(v) for v in plan["waves"].values()}, {2})
        with self.assertRaises(paired.BudgetExceeded):
            paired.build_plan(d, paired.load_specs(d), reps=2, hosts=list(d["hosts"]), arms=list(d["arms"]), seed=1, budget_usd=100, parallel=8)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("paired_effort", REPO_ROOT / "evals" / "paired_effort.py")
        self.pe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pe)

    def pairs(self, ratio, dpass=0.0, n=23, **over):
        import math
        return [{"scenario_id": f"s{i}", "rep": r, "arm": "sonnet_medium", "log_cost_ratio": math.log(ratio) + (0.02 if (i + r) % 2 else -0.02),
                 "delta_turn_pass": dpass, "valid": True, "mechanism_engaged": True, "cache_audit_clean": True, "cost_valid": True, **over}
                for i in range(n) for r in (1, 2)]

    def test_cheaper_arm_with_equal_quality_supports_HE(self):
        res = self.pe.analyse(self.pairs(0.85), resamples=2000)
        self.assertTrue(res["HE_supported"])
        self.assertLess(res["cost"]["ci95"][1], 1.0)
        self.assertAlmostEqual(res["cost"]["geo_mean_ratio"], 0.85, places=2)
        self.assertEqual((res["n_pairs"], res["n_valid_cost_pairs"], res["cost"]["n_scenarios"]), (46, 46, 23))

    def test_no_cost_saving_or_a_quality_loss_does_not_support_HE(self):
        self.assertFalse(self.pe.analyse(self.pairs(1.00), resamples=2000)["HE_supported"])
        worse = self.pe.analyse(self.pairs(0.80, dpass=-0.10), resamples=2000)
        self.assertTrue(worse["cost"]["supported"])
        self.assertFalse(worse["quality"]["non_inferior"])
        self.assertFalse(worse["HE_supported"])

    def test_cost_filters_apply_but_quality_is_unfiltered(self):
        pairs = self.pairs(0.85, dpass=-0.30, mechanism_engaged=False)          # every pair fails the mechanism gate
        res = self.pe.analyse(pairs, resamples=500)
        self.assertEqual(res["n_valid_cost_pairs"], 0)
        self.assertEqual(res["cost"], {})
        self.assertAlmostEqual(res["quality"]["mean_delta_turn_pass"], -0.30)      # quality still counted
        self.assertFalse(res["HE_supported"])

    def test_bootstrap_is_seeded_and_clusters_by_scenario(self):
        means = {f"s{i}": 0.1 * i for i in range(10)}
        a, b = self.pe.cluster_bootstrap(means, resamples=500), self.pe.cluster_bootstrap(means, resamples=500)
        self.assertEqual(a, b)
        self.assertNotEqual(a, self.pe.cluster_bootstrap(means, seed=1, resamples=500))
        self.assertAlmostEqual(a["mean"], 0.45)
        self.assertLess(a["lo"], a["mean"] < a["hi"] and a["mean"])
        self.assertEqual((self.pe.SEED, self.pe.RESAMPLES), (20261005, 10000))

    def test_secondary_compares_to_sticky_cheap_sessions_only(self):
        new = [{"scenario_id": f"s{i}", "arm": "sonnet_medium", "cost_usd_tools_normalized": 2.0} for i in range(5)]
        main = [{"scenario_id": f"s{i}", "arm": "sticky", "sticky_decision": "cheap", "cost_usd_tools_normalized": 4.0} for i in range(5)]
        main += [{"scenario_id": f"s{i}", "arm": "sticky", "sticky_decision": "host", "cost_usd_tools_normalized": 100.0} for i in range(5)]
        r = self.pe.vs_sticky(new, main, resamples=200)
        self.assertTrue(r["exploratory"])
        self.assertAlmostEqual(r["geo_mean_ratio_medium_over_sticky_cheap"], 0.5)

    def test_cli_reads_rows_dir(self):
        import contextlib, io
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "pairs.jsonl").write_text("\n".join(json.dumps(p) for p in self.pairs(0.9, n=8)), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(self.pe.main(["--rows", str(tmp), "--json", str(tmp / "out.json")]), 0)
        self.assertEqual(json.loads(buf.getvalue())["hypothesis"], "HE")
        self.assertTrue((tmp / "out.json").exists())
