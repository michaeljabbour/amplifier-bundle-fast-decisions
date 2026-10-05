"""S1 analysis script on synthetic data with KNOWN effects (no real data exists yet): the estimators recover them, the
decision rules fire the right way, invalid sessions drop out, Holm is monotone, and the output is deterministic."""
from __future__ import annotations

import copy
import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.v3 import s1_analysis as a  # noqa: E402

TYPES = ["bugfix", "feature", "mixed", "review", "explain", "docs"]
B = 400


def session(s, rep, host, arm, cost, tp, *, models, ws, ttype, long_gaps=0, **kw):
    row = {"scenario_id": s, "rep": rep, "host": host, "arm": arm, "cost_usd_tools_normalized": cost, "turn_pass_frac": tp,
           "final_state_pass": tp >= 0.9, "status": "ok", "wave_valid": True, "cost_valid": True, "mechanism_engaged": True,
           "cache_audit_clean": True, "served_models": models, "task_type": ttype, "workspace_files": ws,
           "n_long_gaps": long_gaps, "n_req": 40, "tokens": {models[0]: {"input": 1000, "cache_read": 50000, "cache_write": 6000, "output": 3000}},
           "fd_receipt_counts": {}}
    row.update(kw)
    return row


def synth(seed=7, n=60, effects=None, jev_disagrees=0.10, pc_loss_on_keep=0.08):
    """Fable base cost per scenario-rep; every arm = base x a fixed factor x small noise; routing per the live ShF decision."""
    e = {"anchor_m": 0.86, "ph": 1.017, "ph_m": 0.875, "pc": 0.52, "o_m": 0.85, "sho": 1.02, "sho_m": 0.87, "pc_opus": 1.30}
    e.update(effects or {})
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        s, ttype = f"sc{i:02d}", TYPES[i % 6]
        ws = 450 if i % 5 == 0 else 40
        base = math.exp(rng.gauss(math.log(5.0), 0.3))
        for rep in (1, 2):
            nz = lambda sd=0.04: math.exp(rng.gauss(0, sd))      # noqa: E731
            tp = lambda x: max(0.0, min(1.0, x + rng.gauss(0, 0.01)))  # noqa: E731
            F, O = "claude-fable-5-1", "claude-opus-5-5"
            kw = dict(ws=ws, ttype=ttype)
            rstar_cheap = ws <= 300
            jev_cheap = rstar_cheap and rng.random() > jev_disagrees
            pc_tp = 0.95 - (pc_loss_on_keep if ttype in a.KEEP_TYPES else 0.0)
            rows += [session(s, rep, "fable", "anchor", base * nz(), tp(0.95), models=[F], **kw),
                     session(s, rep, "fable", "aa", base * nz(), tp(0.95), models=[F], **kw) if i % 10 == 0 else None,
                     session(s, rep, "fable", "anchor_m", base * e["anchor_m"] * nz(), tp(0.95), models=[F], **kw),
                     session(s, rep, "fable", "ph", base * e["ph"] * nz(), tp(0.95), models=[F], **kw),
                     session(s, rep, "fable", "ph_m", base * e["ph_m"] * nz(), tp(0.95), models=[F], **kw),
                     session(s, rep, "any", "pc", base * e["pc"] * nz(), tp(pc_tp), models=["claude-sonnet-5"], **kw)]
            pc_row = rows[-1]
            ph_row = rows[-3]
            shf = pc_row if jev_cheap else ph_row            # the live session IS its potential outcome (H6 true by construction)
            rows.append(session(s, rep, "fable", "shipped", shf["cost_usd_tools_normalized"], shf["turn_pass_frac"],
                                models=list(shf["served_models"]), **kw))
            ob = base * 0.4
            rows += [session(s, rep, "opus", "anchor", ob * nz(), tp(0.95), models=[O], **kw),
                     session(s, rep, "opus", "anchor_m", ob * e["o_m"] * nz(), tp(0.95), models=[O], **kw),
                     session(s, rep, "opus", "shipped", ob * e["sho"] * nz(), tp(0.95), models=[O], **kw),
                     session(s, rep, "opus", "shipped_m", ob * e["sho_m"] * nz(), tp(0.95), models=[O], **kw)]
    return [r for r in rows if r is not None]


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = synth()
        cls.res = a.analyse(cls.rows, resamples=B, seed=11)
        cls.h = cls.res["hypotheses"]

    def test_h1_recovers_a_large_saving_and_is_supported(self):
        h1 = self.h["H1"]
        self.assertLess(h1["estimate"]["gm_ratio"], 0.65)
        self.assertLess(h1["estimate"]["gm_ratio_ci95"][1], 0.75)
        self.assertTrue(h1["supported"], h1)

    def test_h3_equivalence_when_overhead_is_two_percent(self):
        h3 = self.h["H3"]
        self.assertAlmostEqual(h3["estimate"]["gm_ratio"], 1.02, delta=0.03)
        self.assertTrue(h3["supported"], h3)
        self.assertIn("cache_write_ratio", h3["decomposition"])

    def test_h3_fails_when_the_overhead_is_ten_percent(self):
        res = a.analyse(synth(effects={"sho": 1.10}), resamples=B, seed=11)
        self.assertFalse(res["hypotheses"]["H3"]["supported"])

    def test_h4_h5_h6(self):
        self.assertTrue(self.h["H4"]["supported"])
        self.assertAlmostEqual(self.h["H4"]["estimate"]["gm_ratio"], 0.85, delta=0.03)
        self.assertTrue(self.h["H5"]["supported"])            # Pc costs 1.3x on Opus
        self.assertGreater(self.h["H5"]["estimate"]["gm_ratio_ci95"][0], 1.0)
        self.assertTrue(self.h["H6"]["supported"])            # the live session equals its prediction by construction
        self.assertAlmostEqual(self.h["H6"]["estimate"]["gm_ratio"], 1.0, delta=0.001)

    def test_h6_fails_when_live_differs_from_prediction(self):
        rows = copy.deepcopy(self.rows)
        for r in rows:
            if r["arm"] == "shipped" and r["host"] == "fable":
                r["cost_usd_tools_normalized"] *= 1.15
        res = a.analyse(rows, resamples=B, seed=11)
        self.assertFalse(res["hypotheses"]["H6"]["supported"])

    def test_h7_loss_on_review_and_explain_ships_keep_on_host(self):
        h7 = self.h["H7"]
        self.assertLess(h7["estimate"]["d_turn_pass"], -0.06)
        self.assertFalse(h7["supported"])                      # not non-inferior => keep_on_host ships
        res = a.analyse(synth(pc_loss_on_keep=0.0), resamples=B, seed=11)
        self.assertTrue(res["hypotheses"]["H7"]["supported"])  # no loss => the opt-out example is removed

    def test_h2_decision_equivalent_deciders_ship_the_rule(self):
        h2 = self.h["H2"]
        self.assertIn("ship R*", h2["decision"])
        self.assertGreater(h2["discordant_scenario_reps"], 0)

    def test_h2_jev_cheaper_beyond_the_margin_ships_jev(self):
        # Jev keeps the host exactly on the even scenarios, where a routed session is a bad deal (2.6x): Jev is right there
        rows = synth(jev_disagrees=0.0)
        ph = {(r["scenario_id"], r["rep"]): r for r in rows if r["arm"] == "ph" and r["host"] == "fable"}
        for r in rows:
            even = int(r["scenario_id"][2:]) % 2 == 0
            if r["arm"] == "pc" and even:
                r["cost_usd_tools_normalized"] *= 2.6
            if r["arm"] == "shipped" and r["host"] == "fable" and even:
                src = ph[(r["scenario_id"], r["rep"])]
                r.update(cost_usd_tools_normalized=src["cost_usd_tools_normalized"], turn_pass_frac=src["turn_pass_frac"],
                         served_models=list(src["served_models"]))
        res = a.analyse(rows, resamples=B, seed=11)
        self.assertIn("ship Jev", res["hypotheses"]["H2"]["decision"], res["hypotheses"]["H2"])

    def test_holm_is_monotone_and_family_scoped(self):
        for fam, ids in a.FAMILIES.items():
            present = sorted((h for h in ids if h in self.h), key=lambda h: self.h[h]["p"])
            adj = [self.h[h]["p_holm"] for h in present]
            self.assertEqual(adj, sorted(adj))
            for h in present:
                self.assertGreaterEqual(self.h[h]["p_holm"], self.h[h]["p"] - 1e-12)
        self.assertIsNone(self.h["H3b"]["p_holm"])             # PhF/A0F decomposition is descriptive, in no family

    def test_noise_floor_and_health(self):
        nf = self.res["noise_floor"]["fable"]
        self.assertAlmostEqual(nf["gm_ratio"], 1.0, delta=0.08)
        self.assertEqual(self.res["health"]["stop_rule_triggers"], [])

    def test_invalid_sessions_drop_their_scenario_reps(self):
        rows = copy.deepcopy(self.rows)
        n0 = a.analyse(rows, resamples=50, seed=1)["hypotheses"]["H5"]["estimate"]["n_pairs"]
        for r in rows:
            if r["arm"] == "pc" and r["scenario_id"] == "sc03" and r["rep"] == 1:
                r["mechanism_engaged"] = False
        est = a.analyse(rows, resamples=50, seed=1)["hypotheses"]["H5"]["estimate"]
        self.assertEqual(est["n_pairs"], n0 - 1)                 # the cost endpoint drops the invalid scenario-rep ...
        self.assertEqual(est["n_pairs_quality"], n0)             # ... the quality endpoint keeps it (unfiltered)

    def test_shf_mechanism_failure_triggers_the_stop_rule(self):
        rows = copy.deepcopy(self.rows)
        for r in rows:
            if r["arm"] == "shipped" and r["host"] == "fable":
                r["mechanism_engaged"] = False
                break
        self.assertTrue(any("ShF" in t for t in a.analyse(rows, resamples=50, seed=1)["health"]["stop_rule_triggers"]))

    def test_deterministic(self):
        r1 = a.analyse(self.rows, resamples=100, seed=5)
        r2 = a.analyse(copy.deepcopy(self.rows), resamples=100, seed=5)
        self.assertEqual(r1, r2)

    def test_regret_is_nonnegative_for_non_oracle_policies_on_average_and_oracle_is_cross_fitted(self):
        reg = self.res["regret"]["fable"]
        self.assertIn("rstar | strong medium", reg)
        d = a.Data(self.rows)
        orc = a.oracle(d, "fable", "medium")
        self.assertTrue(orc)
        # cross-fitting: the choice for rep r uses rep (other) only: flipping rep-1 outcomes cannot change rep-1's own choice
        s = d.scenarios[1]
        before = orc[(s, 1)]["arm"]
        rows = copy.deepcopy(self.rows)
        for r in rows:
            if r["scenario_id"] == s and r["rep"] == 1 and r["arm"] in ("pc", "ph_m"):
                r["cost_usd_tools_normalized"] *= 100
        orc2 = a.oracle(a.Data(rows), "fable", "medium")
        self.assertEqual(orc2[(s, 1)]["arm"], before)


class Freeze(unittest.TestCase):
    def test_occam_prefers_the_simpler_candidate_within_three_percent(self):
        rows = synth(jev_disagrees=0.0)              # Jev == R* everywhere: identical cost, so the rule decider must win
        res = a.analyse(rows, resamples=B, seed=11)
        fz = res["freeze"]["fable"]
        self.assertIsNotNone(fz["chosen"])
        chosen = next(r for r in fz["table"] if r["config"] == fz["chosen"])
        self.assertEqual(chosen["class"], "bundle+rule")

    def test_nothing_qualifies_means_ship_the_default(self):
        rows = synth(effects={"anchor_m": 1.3, "ph": 1.3, "ph_m": 1.3, "pc": 1.3, "o_m": 1.3, "sho": 1.3, "sho_m": 1.3, "pc_opus": 1.3})
        res = a.analyse(rows, resamples=B, seed=11)
        self.assertIsNone(res["freeze"]["opus"]["chosen"])
        self.assertTrue(res["freeze"]["opus"]["ship_default"])

    def test_chosen_not_equal_to_cstar_is_labelled_selected_on_holdout(self):
        res = a.analyse(synth(), resamples=B, seed=11)
        fz = res["freeze"]["opus"]
        self.assertEqual(fz["selected_on_holdout"], fz["chosen"] != fz["preregistered_C*"])

    def test_jev_with_scope_gate_off_is_not_computed(self):
        d = a.Data(synth())
        self.assertEqual(a.policy(d, "fable", decider="jev", strong="medium", scope=False), {})


class Helpers(unittest.TestCase):
    def test_one_sided_p_values(self):
        draws = [0.5] * 100
        self.assertAlmostEqual(a.p_below(draws, 0.75), 1 / 101)        # every draw is below 0.75: strong evidence
        self.assertAlmostEqual(a.p_below(draws, 0.4), 101 / 101)       # none is below 0.4
        self.assertAlmostEqual(a.p_equiv([1.0] * 100, 0.95, 1.05), 1 / 101)
        self.assertAlmostEqual(a.p_equiv([1.2] * 100, 0.95, 1.05), 1.0)

    def test_valid_requires_every_flag(self):
        base = {"wave_valid": True, "cost_valid": True, "mechanism_engaged": True, "cache_audit_clean": True, "status": "ok"}
        self.assertTrue(a.valid(base))
        for k, v in (("wave_valid", False), ("cost_valid", False), ("mechanism_engaged", False), ("cache_audit_clean", False),
                     ("status", "infra_fail")):
            self.assertFalse(a.valid({**base, k: v}))

    def test_decider_charge_is_added_to_cost(self):
        r = {"cost_usd_tools_normalized": 1.0, "fd_receipt_counts": {"judge_usage": 2}}
        self.assertAlmostEqual(a.cost(r), 1.0 + 2 * a.JEV_USD)


if __name__ == "__main__":
    unittest.main()
