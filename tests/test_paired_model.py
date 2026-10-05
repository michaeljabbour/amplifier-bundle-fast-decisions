"""evals/paired_model.py on a synthetic campaign with known effects: recovery within CI, prediction-interval coverage,
loader semantics, determinism, CLI end to end, and a smoke run on a real (tiny) pilot if one is on disk. No model calls."""
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

import paired_model as pm  # noqa: E402

PILOT = Path("~/dev/afast-paired/pilot-1").expanduser()

# ------------------------------------------------------------------------------------------------ synthetic truth
ARM_EFF = {"aa": 0.0, "shipped": -0.20, "sticky": -0.10}
HOST_EFF = {"opus": 0.0, "fable": 0.05}
TASK_EFF = {"bugfix": 0.0, "feature": -0.08, "refactor": 0.06}
SD_SCEN, SD_REP, SD_EPS = 0.12, 0.05, 0.08          # log-ratio random effects
SD_ANCHOR_SCEN = 0.25                               # anchor cost between-scenario SD (log)
HOSTS, TASKS = ("opus", "fable"), tuple(TASK_EFF)


def true_y(arm, host, task, turns, long_gap, t1):
    return ARM_EFF[arm] + HOST_EFF[host] + TASK_EFF[task] + 0.02 * (turns - 12) - 0.05 * long_gap + 0.03 * (math.log1p(t1) - 6.8) \
        if arm != "aa" else 0.0


def anchor_median(host, task, turns, long_gap, t1):
    return 0.35 * turns * (1.3 if host == "fable" else 1.0) * math.exp(0.1 * TASKS.index(task)) * (1 + 0.1 * long_gap)


def make_campaign(root: Path, seed: int = 1, n_scen: int = 100, n_train: int = 70, reps: int = 2) -> None:
    rng = np.random.default_rng(seed)
    sessions, pairs = [], []
    for s in range(n_scen):
        sid = f"s{s:03d}"
        split = "train" if s < n_train else "test"
        task = TASKS[s % 3]
        turns = int(rng.choice([8, 10, 12, 14, 16]))
        n_long = int(rng.choice([0, 0, 1, 2]))
        t1 = float(np.exp(rng.normal(6.8, 0.4)))
        u_s, v_s = rng.normal(0, SD_SCEN), rng.normal(0, SD_ANCHOR_SCEN)
        for rep in range(1, reps + 1):
            for host in HOSTS:
                u_sr = rng.normal(0, SD_REP)
                a_cost = anchor_median(host, task, turns, min(n_long, 1), t1) * math.exp(v_s + rng.normal(0, 0.06))
                base = {"scenario_id": sid, "rep": rep, "host": host, "split": split, "task_type": task, "language": "python",
                        "scripted_turns": turns, "n_long_gaps": n_long, "turn1_prompt_chars": int(t1), "wave_valid": True,
                        "status": "ok", "final_state_pass": True, "turn_pass_frac": 1.0, "rebuild_usd": 0.0, "model_switches": 0}
                sessions.append({**base, "arm": "anchor", "cost_usd_tools_normalized": a_cost, "cost_usd_recomputed": a_cost})
                for arm in ARM_EFF:
                    y = true_y(arm, host, task, turns, min(n_long, 1), t1) + u_s * (arm != "aa") + u_sr + rng.normal(0, SD_EPS)
                    cost = a_cost * math.exp(y)
                    sessions.append({**base, "arm": arm, "cost_usd_tools_normalized": cost, "cost_usd_recomputed": cost,
                                     "model_switches": 2 if arm == "shipped" else 0, "rebuild_usd": 0.1 * cost if arm == "shipped" else 0.0})
                    pairs.append({"scenario_id": sid, "rep": rep, "host": host, "arm": arm, "task_type": task, "n_long_gaps": n_long,
                                  "delta_usd": cost - a_cost, "log_cost_ratio": y, "delta_usd_raw": cost - a_cost,
                                  "log_cost_ratio_raw": y, "delta_turn_pass": 0.0, "both_pass": True,
                                  "anchor_cost_usd": a_cost, "arm_cost_usd": cost, "anchor_cost_usd_raw": a_cost,
                                  "arm_cost_usd_raw": cost, "valid": True})
    rows = root / "rows"
    rows.mkdir(parents=True)
    for name, data in (("sessions", sessions), ("pairs", pairs)):
        (rows / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in data) + "\n", encoding="utf-8")


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        make_campaign(cls.tmp / "c")
        cls.ds = pm.load_dataset(cls.tmp / "c")
        cls.model = pm.fit(cls.ds, ("train",), engine="fallback", B=200, seed=3)
        cls.preds = pm.predict(cls.model, cls.ds, ("test",), D=2000, seed=3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- recovery -----------------------------------------------------------------------------------------
    def test_arm_effects_recovered_within_bootstrap_ci(self):
        m = self.model["models"]["log_ratio"]
        design = pm.Design.from_dict(m["design"])
        boot = np.array(m["boot"]["beta"])
        self.assertEqual(m["design"]["arms"], ["shipped", "sticky"], "aa is excluded from the fit by default")
        cells = [dict(arm=a, host=h, task_type=t, turns=n, long_gap=g, n_long_gaps=g, t1=900.0)
                 for a in ("shipped", "sticky") for h, t, n, g in (("opus", "bugfix", 12, 0), ("fable", "feature", 8, 1),
                                                                    ("opus", "refactor", 16, 0))]
        X, _ = design.transform(cells)
        draws = boot @ X.T
        lo, hi = np.percentile(draws, [2.5, 97.5], axis=0)
        for c, a, b in zip(cells, lo, hi):
            truth = true_y(c["arm"], c["host"], c["task_type"], c["turns"], c["long_gap"], c["t1"])
            self.assertTrue(a <= truth <= b, f"{c}: truth {truth:.3f} outside [{a:.3f}, {b:.3f}]")
            self.assertLess(b - a, 0.2, "interval should be reasonably tight with 70 scenarios")

    def test_covariate_and_variance_components(self):
        m = self.model["models"]["log_ratio"]
        coef = {c["term"]: c for c in m["coef"]}
        rh, rt = m["design"]["ref_host"], m["design"]["ref_task_type"]
        for term, truth in [(f"host={h}", HOST_EFF[h] - HOST_EFF[rh]) for h in HOSTS if h != rh] + \
                           [(f"task_type={t}", TASK_EFF[t] - TASK_EFF[rt]) for t in TASKS if t != rt]:
            lo, hi = coef[term]["ci95_boot"]
            self.assertTrue(lo <= truth <= hi, f"{term}: truth {truth} outside [{lo}, {hi}]")
        v = m["variance"]
        self.assertTrue(SD_SCEN ** 2 / 2 < v["scenario"] < SD_SCEN ** 2 * 2, v)
        self.assertTrue(SD_EPS ** 2 / 2 < v["residual"] < SD_EPS ** 2 * 2, v)
        # the rep block is shared across arms of one scenario/rep/host: estimated clearly above zero
        self.assertGreater(v["scenario_rep"], SD_REP ** 2 / 3)

    def test_only_pre_session_covariates(self):
        allowed = {"arm", "host", "task_type", "turns", "long_gap", "log_turn1", "const"}
        for m in self.model["models"].values():
            for c in m["design"]["columns"]:
                self.assertIn(c.get("var") or c["group"], allowed)
                self.assertFalse(c["name"].startswith("anchor_"))

    # --- prediction -----------------------------------------------------------------------------------------
    def test_prediction_intervals_calibrated_on_test_split(self):
        o = self.preds["overall"]
        self.assertEqual(self.preds["n_test_scenarios"], 30)
        self.assertTrue(0.82 <= o["coverage_log_ratio"] <= 0.98, o["coverage_log_ratio"])
        self.assertTrue(0.78 <= o["coverage_saving_delta_model"] <= 0.98, o["coverage_saving_delta_model"])
        self.assertAlmostEqual(o["mean_error_log_ratio"], 0.0, delta=0.03)
        self.assertTrue(o["observed_total_in_pi"], o)
        self.assertTrue(0.7 <= o["calibration_slope"] <= 1.3, o["calibration_slope"])

    def test_coverage_across_seeds_is_near_nominal(self):
        cov = []
        for seed in range(10, 15):
            d = Path(tempfile.mkdtemp())
            try:
                make_campaign(d / "c", seed=seed, n_scen=160, n_train=70)
                ds = pm.load_dataset(d / "c")
                mdl = pm.fit(ds, ("train",), engine="fallback", B=60, seed=seed)
                cov.append(pm.predict(mdl, ds, ("test",), D=800, seed=seed)["overall"]["coverage_log_ratio"])
            finally:
                shutil.rmtree(d, ignore_errors=True)
        # nominal 0.90; a percentile bootstrap with few refits runs a little narrow, so the floor is 0.84
        self.assertTrue(0.84 <= float(np.mean(cov)) <= 0.95, cov)

    def test_workload_calculator_matches_truth(self):
        mix = {"arm": "shipped", "host": {"opus": 0.6, "fable": 0.4}, "task_type": {"bugfix": 0.5, "feature": 0.5},
               "turns": {"8": 0.5, "12": 0.5}, "long_gap_share": 0.0, "turn1_prompt_chars": 900}
        w = pm.workload(self.model, mix, N=1000, D=2000, seed=5)["by_arm"]["shipped"]
        truth = 0.0
        e_noise = math.exp((SD_SCEN ** 2 + SD_REP ** 2 + SD_EPS ** 2) / 2)
        a_noise = math.exp((SD_ANCHOR_SCEN ** 2 + 0.06 ** 2) / 2)
        for h, wh in mix["host"].items():
            for t, wt in mix["task_type"].items():
                for n, wn in mix["turns"].items():
                    y = true_y("shipped", h, t, int(n), 0, 900.0)
                    truth += wh * wt * wn * anchor_median(h, t, int(n), 0, 900.0) * a_noise * (1 - math.exp(y) * e_noise)
        self.assertAlmostEqual(w["saving_usd_per_session"] / truth, 1.0, delta=0.12, msg=(w, truth))
        lo, hi = w["saving_usd_pi90"]
        self.assertTrue(lo < w["saving_usd_point"] < hi)
        self.assertTrue(lo < 1000 * truth < hi)

    # --- semantics ------------------------------------------------------------------------------------------
    def test_summary_aa_noise_and_savings(self):
        s = pm.summarize(self.ds, seed=1, B=300)
        aa = s["aa_noise"]["all"]
        self.assertTrue(aa["centred_on_zero"], aa)
        self.assertAlmostEqual(aa["sd_log_ratio"], math.sqrt(SD_REP ** 2 + SD_EPS ** 2), delta=0.03)
        g = next(x for x in s["groups"] if (x["arm"], x["host"], x["dim"]) == ("shipped", "all", "overall"))
        lo, hi = g["gm_cost_ratio_ci95"]
        self.assertTrue(lo < g["gm_cost_ratio"] < hi)
        self.assertTrue(lo <= math.exp(-0.20 + 0.025) * 1.03 and hi >= math.exp(-0.20 - 0.03) * 0.97)
        self.assertTrue(g["savings_claim_allowed"])
        self.assertAlmostEqual(g["rebuild_cost_share"], 0.1, delta=0.005)     # every shipped session spends 10% on rebuilds
        self.assertGreater(g["mean_model_switches"], 1.9)
        dims = {x["dim"] for x in s["groups"]}
        self.assertEqual(dims, {"overall", "task_type", "gap_pattern", "turn_band"})

    def test_deterministic_cli_and_report(self):
        outs = []
        for i in range(2):
            out = self.tmp / f"out{i}"
            self.assertEqual(pm.main(["all", str(self.tmp / "c"), "--out", str(out), "--seed", "7", "--boot", "200",
                                      "--fit-boot", "30", "--draws", "300", "--engine", "fallback"]), 0)
            outs.append(out)
        for name in ("summary.json", "model.json", "predictions.json", "MODEL.md"):
            self.assertEqual((outs[0] / name).read_bytes(), (outs[1] / name).read_bytes(), name)
        md = (outs[0] / "MODEL.md").read_text(encoding="utf-8")
        for needle in ("A/A noise", "Savings by arm and host", "Fitted model", "Prediction on the test split", "numpy method-of-moments"):
            self.assertIn(needle, md)
        mix = self.tmp / "mix.json"
        mix.write_text(json.dumps({"arm": ["shipped", "sticky"], "task_type": {"bugfix": 1}, "turns": {"12": 1}}), encoding="utf-8")
        self.assertEqual(pm.main(["workload", str(self.tmp / "c"), "--out", str(outs[0]), "--mix", str(mix), "--draws", "300"]), 0)
        self.assertIn("Workload calculator", (outs[0] / "MODEL.md").read_text(encoding="utf-8"))

    def test_statsmodels_engine_agrees_when_available(self):
        if not pm._statsmodels_available():
            self.skipTest("statsmodels not installed; fallback engine covered above")
        a = pm.fit(self.ds, ("train",), engine="statsmodels", B=5, seed=1)["models"]["log_ratio"]
        b = pm.fit(self.ds, ("train",), engine="fallback", B=5, seed=1)["models"]["log_ratio"]
        for x, y in zip(a["beta"], b["beta"]):
            self.assertAlmostEqual(x, y, delta=0.03)


class Units(unittest.TestCase):
    def test_mcnemar_exact(self):
        self.assertAlmostEqual(pm.mcnemar_exact(0, 5), 0.0625)
        self.assertEqual(pm.mcnemar_exact(0, 0), 1.0)
        self.assertEqual(pm.mcnemar_exact(3, 3), 1.0)

    def test_cluster_bootstrap_ci_contains_truth_and_is_seeded(self):
        rng = np.random.default_rng(0)
        vals, cl = [], []
        for s in range(40):
            u = rng.normal(0, 1)
            for _ in range(2):
                vals.append(2.0 + u + rng.normal(0, 0.5))
                cl.append(s)
        a = pm.cluster_boot_mean(vals, cl, np.random.default_rng(1), 1000)
        b = pm.cluster_boot_mean(vals, cl, np.random.default_rng(1), 1000)
        self.assertEqual(a, b)
        self.assertTrue(a[1] < 2.0 < a[2])
        self.assertIsNone(pm.cluster_boot_mean([1.0, 2.0], ["x", "x"], np.random.default_rng(1), 50)[1])

    def test_loader_excludes_invalid_cost_but_keeps_quality_and_joins_host_any(self):
        d = Path(tempfile.mkdtemp())
        try:
            base = {"scenario_id": "a", "rep": 1, "split": "train", "task_type": "bugfix", "scripted_turns": 8, "n_long_gaps": 0,
                    "turn1_prompt_chars": 500, "wave_valid": True, "status": "ok", "final_state_pass": True, "turn_pass_frac": 1.0}
            sessions = [{**base, "host": "opus", "arm": "anchor", "cost_usd_tools_normalized": 2.0, "cost_usd_recomputed": 2.0},
                        {**base, "host": "any", "arm": "sonnet", "cost_usd_tools_normalized": 1.0, "cost_usd_recomputed": 1.0,
                         "final_state_pass": False}]
            pair = {"scenario_id": "a", "rep": 1, "host": "opus", "arm": "sonnet", "task_type": "bugfix", "n_long_gaps": 0,
                    "delta_usd": -1.0, "log_cost_ratio": -0.69, "delta_turn_pass": -0.2, "both_pass": False,
                    "anchor_cost_usd": 2.0, "arm_cost_usd": 1.0, "valid": False}
            (d / "rows").mkdir()
            (d / "rows" / "sessions.jsonl").write_text("\n".join(map(json.dumps, sessions)), encoding="utf-8")
            (d / "rows" / "pairs.jsonl").write_text(json.dumps(pair), encoding="utf-8")
            ds = pm.load_dataset(d)
            self.assertEqual(len(ds["pairs"]), 1)
            self.assertEqual(pm._cost_rows(ds["pairs"]), [])
            self.assertTrue(ds["pairs"][0]["quality_ok"])
            g = pm.summarize(ds, B=50)["groups"][0]
            self.assertEqual(g["n_valid_pairs"], 0)
            self.assertEqual(g["quality"]["mcnemar_anchor_only_pass"], 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_design_degrades_when_data_is_tiny(self):
        recs = [dict(arm=a, host="opus", task_type="bugfix", turns=8, long_gap=0, t1=500.0, scenario=s, rep=1)
                for s in "ab" for a in ("x", "y")]
        d = pm.Design.fit(recs)
        self.assertEqual(d.names, ["arm=x", "arm=y"])
        with self.assertRaises(ValueError):
            d.transform([dict(recs[0], arm="new")])


@unittest.skipUnless((PILOT / "rows").is_dir(), "pilot-1 rows not on this machine")
class PilotSmoke(unittest.TestCase):
    def test_does_not_crash_on_pilot_rows(self):
        out = Path(tempfile.mkdtemp())
        try:
            for extra in ([], ["--train-splits", "pilot", "--test-splits", "pilot"]):
                self.assertEqual(pm.main(["all", str(PILOT), "--out", str(out), "--boot", "100", "--fit-boot", "20",
                                          "--draws", "200", *extra]), 0)
            self.assertTrue((out / "MODEL.md").read_text(encoding="utf-8").startswith("# Savings model"))
            self.assertEqual(json.loads((out / "summary.json").read_text(encoding="utf-8"))["counts"]["pairs"], 3)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
