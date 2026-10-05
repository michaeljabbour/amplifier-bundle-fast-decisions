"""evals/paired_confirm.py: verdict rules, the two non-inferiority readings, H3 pairing, the decision rule, and an
end-to-end run on synthetic campaigns with known truth. No model calls."""
from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # numpy is optional; CI installs only the package's own deps
    raise unittest.SkipTest("numpy not installed")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals"))

import paired_confirm as pc  # noqa: E402
import paired_model as pm  # noqa: E402

# true log cost ratio arm/anchor per host
TRUTH = {"fable": {"sticky": -0.50, "shipped": -0.40, "sonnet": -0.50, "aa": 0.0},
         "opus": {"sticky": 0.15, "shipped": 0.20, "sonnet": 0.35, "aa": 0.0}}
TURNS = 16


def make_campaign(root: Path, truth=TRUTH, bad_quality=None, seed=3, n_scen=40, n_test=23) -> None:
    """bad_quality=(host, arm, share): that share of the cell's pairs loses 4 scripted turns vs the anchor."""
    rng = np.random.default_rng(seed)
    sessions, pairs = [], []
    for s in range(n_scen):
        sid, split = f"s{s:02d}", ("test" if s < n_test else "train")
        task = ("bugfix", "feature", "mixed")[s % 3]
        n_long, t1 = s % 2 * 2, 400 + 10 * s
        u = rng.normal(0, 0.08)
        for rep in (1, 2):
            for host in ("fable", "opus"):
                a_cost = (4.0 if host == "fable" else 3.0) * math.exp(rng.normal(0, 0.2))
                base = {"scenario_id": sid, "rep": rep, "host": host, "split": split, "task_type": task, "scripted_turns": TURNS,
                        "n_long_gaps": n_long, "turn1_prompt_chars": t1, "wave_valid": True, "status": "ok", "cost_valid": True}
                sessions.append({**base, "arm": "anchor", "final_state_pass": True, "turn_pass_frac": 1.0,
                                 "cost_usd_tools_normalized": a_cost, "cost_usd_recomputed": a_cost})
                ur = rng.normal(0, 0.05)
                for arm, mu in truth[host].items():
                    y = mu + (u + ur if arm != "aa" else 0.0) + rng.normal(0, 0.05)
                    cost = a_cost * math.exp(y)
                    bad = bool(bad_quality and (host, arm) == bad_quality[:2] and rng.random() < bad_quality[2])
                    dtp = -4 / TURNS if bad else 0.0
                    sessions.append({**base, "arm": arm, "final_state_pass": not bad, "turn_pass_frac": 1.0 + dtp,
                                     "cost_usd_tools_normalized": cost, "cost_usd_recomputed": cost})
                    pairs.append({"scenario_id": sid, "rep": rep, "host": host, "arm": arm, "task_type": task, "n_long_gaps": n_long,
                                  "delta_usd": cost - a_cost, "log_cost_ratio": y, "delta_usd_raw": cost - a_cost, "log_cost_ratio_raw": y,
                                  "delta_turn_pass": dtp, "both_pass": not bad, "anchor_cost_usd": a_cost, "arm_cost_usd": cost,
                                  "anchor_cost_usd_raw": a_cost, "arm_cost_usd_raw": cost, "valid": True})
    (root / "rows").mkdir(parents=True)
    for name, data in (("sessions", sessions), ("pairs", pairs)):
        (root / "rows" / f"{name}.jsonl").write_text("\n".join(map(json.dumps, data)) + "\n", encoding="utf-8")
    ds = pm.load_dataset(root)
    model = pm.fit(ds, ("train",), engine="fallback", B=30, seed=0)
    (root / "model").mkdir()
    (root / "model" / "model.json").write_text(json.dumps(model), encoding="utf-8")
    (root / "model" / "predictions.json").write_text(json.dumps(pm.predict(model, ds, ("test",), D=500, seed=0)), encoding="utf-8")


class VerdictRules(unittest.TestCase):
    def test_h1_strict_below_one(self):
        self.assertEqual(pc.verdict(0.6, 0.99, "H1"), "confirmed")
        self.assertEqual(pc.verdict(0.6, 1.0, "H1"), "not confirmed")       # upper must be strictly < 1.0
        self.assertEqual(pc.verdict(1.01, 1.2, "H1"), "contradicted")

    def test_h2_lower_above_095(self):
        self.assertEqual(pc.verdict(0.951, 1.3, "H2"), "confirmed")
        self.assertEqual(pc.verdict(0.96, 0.99, "H2"), "confirmed")        # prereg: lower > 0.95 counts as no saving
        self.assertEqual(pc.verdict(0.95, 1.3, "H2"), "not confirmed")
        self.assertEqual(pc.verdict(0.80, 0.94, "H2"), "contradicted")

    def test_h3_upper_inclusive_105(self):
        self.assertEqual(pc.verdict(0.9, 1.05, "H3"), "confirmed")
        self.assertEqual(pc.verdict(0.9, 1.06, "H3"), "not confirmed")
        self.assertEqual(pc.verdict(1.06, 1.2, "H3"), "contradicted")

    def test_quality_margin(self):
        self.assertEqual(pc.verdict(-0.049, 0.02, "Q"), "confirmed")
        self.assertEqual(pc.verdict(-0.05, 0.02, "Q"), "not confirmed")      # prereg says > -0.05
        self.assertEqual(pc.verdict(-0.2, -0.06, "Q"), "contradicted")
        self.assertEqual(pc.verdict(None, None, "Q"), "not confirmed")

    def test_combine(self):
        self.assertEqual(pc.combine(["confirmed", "confirmed"]), "confirmed")
        self.assertEqual(pc.combine(["confirmed", "not confirmed"]), "not confirmed")
        self.assertEqual(pc.combine(["confirmed", "contradicted"]), "contradicted")

    def test_pair_noninferior_boundary(self):
        self.assertTrue(pc.pair_noninferior({"dtp": 0.0}))
        self.assertTrue(pc.pair_noninferior({"dtp": -0.049}))
        self.assertFalse(pc.pair_noninferior({"dtp": -0.05}))
        self.assertFalse(pc.pair_noninferior({"dtp": -1 / 16}))
        self.assertFalse(pc.pair_noninferior({"dtp": None}))

    def test_boot_level_matches_paired_model_at_95(self):
        rng = np.random.default_rng(0)
        vals = list(rng.normal(0, 1, 60))
        cl = [i // 2 for i in range(60)]
        a = pm.cluster_boot_mean(vals, cl, np.random.default_rng(5), 500)
        b = pc._boot_level(vals, cl, np.random.default_rng(5), 500, 0.95)
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=12)
        c = pc._boot_level(vals, cl, np.random.default_rng(5), 500, 0.90)
        self.assertTrue(b[1] < c[1] < c[2] < b[2])                            # 90% range sits inside the 95% one


class DecisionRule(unittest.TestCase):
    def _hyp(self, h1, h2, h3):
        return {"H1": {"verdict": h1}, "H2": {"verdict": h2}, "H3": {"verdict": h3}}

    def _q(self, fable_ok=True):
        v = "confirmed" if fable_ok else "not confirmed"
        return {"fable": {"sticky": {"verdict": v}, "shipped": {"verdict": "confirmed"}, "sonnet": {"verdict": v}},
                "opus": {a: {"verdict": "confirmed"} for a in pc.ARMS}}

    def test_route_sticky_when_h1_h3_and_quality(self):
        d = pc.decision(self._hyp("confirmed", "confirmed", "confirmed"), self._q())
        self.assertEqual(d["fable"]["arm"], "sticky")
        self.assertEqual(d["opus"]["rule_fired"], "H2")

    def test_route_shipped_when_h3_fails(self):
        self.assertEqual(pc.decision(self._hyp("confirmed", "confirmed", "not confirmed"), self._q())["fable"]["arm"], "shipped")

    def test_no_route_without_quality_or_h1(self):
        self.assertEqual(pc.decision(self._hyp("confirmed", "confirmed", "confirmed"), self._q(False))["fable"]["arm"], "anchor")
        d = pc.decision(self._hyp("not confirmed", "not confirmed", "confirmed"), self._q())
        self.assertEqual(d["fable"]["arm"], "anchor")
        self.assertIsNone(d["opus"]["rule_fired"])


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        make_campaign(cls.tmp / "good")
        make_campaign(cls.tmp / "badq", bad_quality=("fable", "shipped", 0.6))
        worse = {"fable": dict(TRUTH["fable"], shipped=0.30), "opus": dict(TRUTH["opus"], sonnet=-0.40)}
        make_campaign(cls.tmp / "worse", truth=worse)
        cls.good = pc.run(cls.tmp / "good", B=4000, emp_B=500, robust_n=2)
        cls.badq = pc.run(cls.tmp / "badq", B=4000, emp_B=500, robust_n=2)
        cls.worse = pc.run(cls.tmp / "worse", B=4000, emp_B=500, robust_n=2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_test_split_only(self):
        self.assertEqual(self.good["counts"]["test_scenarios"], 23)
        ep = self.good["confirmatory"]["primary_endpoint"]["arm"]["fable"]["sticky"]
        self.assertEqual(ep["n_pairs"], 46)

    def test_recovers_truth(self):
        for h, arms in TRUTH.items():
            for a in pc.ARMS:
                lo, hi = self.good["confirmatory"]["primary_endpoint"]["pair"][h][a]["ci95"]
                self.assertTrue(lo < math.exp(arms[a]) < hi, (h, a, lo, hi))
        h3 = self.good["confirmatory"]["h3_paired_ratio"]["pair"]["fable"]
        self.assertTrue(h3["ci95"][0] < math.exp(-0.10) < h3["ci95"][1])      # anchor cancels: sticky - shipped

    def test_all_hypotheses_confirmed_and_decision(self):
        for rd in pc.READINGS:
            h = self.good["confirmatory"]["hypotheses"][rd]
            self.assertEqual([h[k]["verdict"] for k in ("H1", "H2", "H3", "Quality")], ["confirmed"] * 4, rd)
            d = self.good["confirmatory"]["decision"][rd]
            self.assertEqual((d["fable"]["arm"], d["opus"]["rule_fired"]), ("sticky", "H2"))

    def test_quality_failure_blocks_claim_and_readings_diverge(self):
        c = self.badq["confirmatory"]
        self.assertNotEqual(c["quality"]["fable"]["shipped"]["verdict"], "confirmed")
        self.assertEqual(c["quality"]["fable"]["sticky"]["verdict"], "confirmed")
        pair = c["primary_endpoint"]["pair"]["fable"]["shipped"]
        self.assertGreater(pair["n_excluded_quality"], 10)
        self.assertEqual(pair["n_pairs"] + pair["n_excluded_quality"], 46)
        for rd in pc.READINGS:
            self.assertNotEqual(c["hypotheses"][rd]["Quality"]["verdict"], "confirmed")
            self.assertEqual(c["decision"][rd]["fable"]["arm"], "anchor")
        self.assertLess(c["h3_paired_ratio"]["pair"]["fable"]["n_pairs"], c["h3_paired_ratio"]["arm"]["fable"]["n_pairs"])

    def test_contradictions(self):
        h = self.worse["confirmatory"]["hypotheses"]["pair"]
        self.assertEqual(h["H1"]["verdict"], "contradicted")                  # shipped costs more on Fable
        self.assertEqual({p["arm"]: p["verdict"] for p in h["H1"]["parts"]}, {"sticky": "confirmed", "shipped": "contradicted"})
        self.assertEqual(h["H2"]["verdict"], "contradicted")                  # sonnet saves on Opus
        self.assertEqual(h["H3"]["verdict"], "confirmed")                     # sticky far cheaper than shipped on Fable
        self.assertEqual(self.worse["confirmatory"]["decision"]["pair"]["fable"]["arm"], "anchor")

    def test_model_check_and_report(self):
        mc = self.good["confirmatory"]["model_check"]
        self.assertTrue(mc["reproduces_predictions_json"])
        self.assertEqual(set(mc["preregistered_checks"]), {"coverage_log_ratio_in_0.80_0.97",
                                                           "coverage_saving_delta_model_in_0.80_0.97", "test_total_saving_inside_pi90"})
        self.assertTrue(self.good["exploratory"]["seed_robustness"]["all_stable"])
        md = pc.render(self.good)
        for s in ("## Verdicts", "EXPLORATORY", "Deviations from the preregistration", "per 1,000 sessions"):
            self.assertIn(s, md)

    def test_deterministic(self):
        again = pc.primary_endpoints([r for r in pm.load_dataset(self.tmp / "good")["pairs"] if r["split"] == "test"], pc.SEED, 4000)
        self.assertEqual(again, self.good["confirmatory"]["primary_endpoint"])

    def test_cli_rejects_too_few_resamples(self):
        with self.assertRaises(SystemExit):
            pc.main([str(self.tmp / "good"), "--boot", "100"])


if __name__ == "__main__":
    unittest.main()
