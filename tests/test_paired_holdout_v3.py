"""holdout-v3 (S1) design: sessions, waves, adjacency, host-specific arms, gates, cost, cells, smoke design.

Runs on the real design files and the 60 real scenario files (no network, no snapshot build, no model call)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from paired_helpers import paired, ps  # noqa: F401  (paired_helpers puts evals/ and scripts/ on sys.path)

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "evals/paired/holdout-v3.yaml"
SMOKE = ROOT / "evals/paired/holdout-v3-smoke.yaml"
FROZEN = json.loads((ROOT / "evals/v3/frozen_rule.json").read_text(encoding="utf-8"))


def plan_for(path, **kw):
    design = paired.load_design(path)
    specs = paired.load_specs(design)
    args = dict(reps=design["default_reps"], hosts=list(design["hosts"]), arms=list(design["arms"]), seed=20261005,
                budget_usd=design["budget_usd"], parallel=12)
    args.update(kw)
    return design, specs, paired.build_plan(design, specs, **args)


class S1Plan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design, cls.specs, cls.plan = plan_for(DESIGN)

    def test_session_and_wave_counts(self):
        self.assertEqual(len(self.specs), 60)
        self.assertEqual(self.plan["n_sessions"], 1224)         # 120 scenario-reps x 10 arms + 24 A/A
        self.assertEqual(self.plan["n_waves"], 240)
        self.assertFalse(self.plan["control_waves_split"])      # Pc rides in the Fable wave

    def test_wave_composition(self):
        aa_keys = set()
        for wid, sess in self.plan["waves"].items():
            arms = sorted(s["arm"] for s in sess)
            host = wid.rsplit("-", 1)[1]
            base_fable = ["anchor", "anchor_m", "pc", "ph", "ph_m", "shipped"]
            base_opus = ["anchor", "anchor_m", "shipped", "shipped_m"]
            base = base_fable if host == "fable" else base_opus
            self.assertIn(arms, (sorted(base), sorted(base + ["aa"])), wid)
            if "aa" in arms:
                aa_keys.add(wid.rsplit("-", 1)[0])
            self.assertEqual(sum(1 for s in sess if s["host"] == "any"), 1 if host == "fable" else 0)
        self.assertEqual(len(aa_keys), 12)                      # the A/A scenario-reps are the same on both hosts
        for k in aa_keys:
            self.assertIn(f"{k}-fable", self.plan["waves"])
            self.assertIn(f"{k}-opus", self.plan["waves"])

    def test_host_specific_arms(self):
        hosts = {}
        for sess in self.plan["waves"].values():
            for s in sess:
                hosts.setdefault(s["arm"], set()).add(s["host"])
        self.assertEqual(hosts["ph"], {"fable"})
        self.assertEqual(hosts["ph_m"], {"fable"})
        self.assertEqual(hosts["shipped_m"], {"opus"})
        self.assertEqual(hosts["pc"], {"any"})
        self.assertEqual(hosts["anchor"], {"fable", "opus"})

    def test_scenario_rep_waves_are_adjacent(self):
        order = self.plan["wave_order"]
        for i in range(0, len(order), 2):
            f, o = order[i], order[i + 1]
            self.assertTrue(f.endswith("-fable") and o.endswith("-opus"), (f, o))
            self.assertEqual(f.rsplit("-", 1)[0], o.rsplit("-", 1)[0])

    def test_cells_and_models(self):
        sessions = [s for w in self.plan["waves"].values() for s in w]
        cells = {(s["arm"], s["host"]): s["cell"] for s in sessions}
        self.assertEqual(cells[("ph", "fable")], "v3-pin-host")
        self.assertEqual(cells[("ph_m", "fable")], "v3-pin-host-medium")
        self.assertEqual(cells[("shipped", "fable")], "v3-shipped")
        self.assertEqual(cells[("shipped", "opus")], "v3-shipped-opus")
        self.assertEqual(cells[("shipped_m", "opus")], "v3-shipped-opus-medium")
        self.assertEqual(cells[("pc", "any")], "v3-pin-cheap")
        self.assertEqual(cells[("anchor_m", "opus")], "plain-opus-medium")
        self.assertEqual({s["model"] for s in sessions if s["host"] == "opus"}, {"claude-opus-5-5"})
        self.assertEqual({s["model"] for s in sessions if s["host"] == "fable"}, {"claude-fable-5-1"})

    def test_budget_and_estimate(self):
        self.assertEqual(self.design["budget_usd"], 5000)
        self.assertLess(self.plan["est_with_reserve_usd"], 5000)
        self.assertGreater(self.plan["est_with_reserve_usd"], 3500)     # PLAN S1: ~$4.4k planned

    def test_cost_model_covers_every_cell(self):
        cells = {c for a in self.design["arms"].values() for c in a["cells"].values()}
        self.assertLessEqual(cells, set(self.design["cost_model"]["unit_usd_4turn"]))

    def test_frozen_candidates_match_the_design(self):
        f = FROZEN["candidate_configs"]
        self.assertEqual(f["C*_F"]["effort_by_tier"], {"cheap": "medium", "strong": "medium"})
        self.assertEqual(f["C*_O"]["host"], "claude-opus-5-5")
        self.assertEqual(self.design["hosts"]["fable"], f["C*_F"]["host"])

    def test_wall_time_falls_with_parallel(self):
        _, _, p8 = plan_for(DESIGN, parallel=8)
        _, _, p12 = plan_for(DESIGN, parallel=12)
        self.assertGreater(p8["est_wall_hours"], p12["est_wall_hours"])

    def test_parallel_below_the_largest_wave_is_refused(self):
        with self.assertRaises(paired.PairedError):
            plan_for(DESIGN, parallel=6)                         # an A/A Fable wave has 7 sessions


class S1Cells(unittest.TestCase):
    def test_fd_cells_are_composed_and_declare_no_phase_map(self):
        import run as evals_run
        cells = evals_run.load_cells(ROOT / "evals/cells.yaml")["cells"]
        for name in ("v3-shipped", "v3-pin-host", "v3-pin-host-medium", "v3-pin-cheap", "v3-shipped-opus",
                     "v3-shipped-opus-medium"):
            fd = cells[name]["fd"]
            self.assertEqual(fd["composition"], "composed", name)
            self.assertNotIn("effort_profile", fd, name)
            self.assertNotIn("model_routing_profile", fd, name)
        self.assertEqual(cells["plain-opus-medium"]["amplifier_effort"], "medium")
        self.assertEqual(cells["v3-shipped-opus"]["amplifier_model"], "claude-opus-5-5")

    def test_overrides_differ_only_as_documented(self):
        import run as evals_run
        cells = evals_run.load_cells(ROOT / "evals/cells.yaml")["cells"]
        self.assertEqual(cells["v3-shipped"]["fd"], {"composition": "composed"})
        self.assertEqual(cells["v3-shipped-opus"]["fd"], {"composition": "composed"})
        self.assertEqual(cells["v3-shipped-opus-medium"]["fd"]["overrides"], {"effort_routing": {"by_tier": {"strong": "medium"}}})
        ph, phm = cells["v3-pin-host"]["fd"]["overrides"], cells["v3-pin-host-medium"]["fd"]["overrides"]
        self.assertEqual({k: v for k, v in phm.items() if k != "effort_routing"}, ph)
        self.assertEqual(phm["effort_routing"], {"by_tier": {"strong": "medium"}})


class S1Gates(unittest.TestCase):
    def arm_gate(self, arm, host):
        design = paired.load_design(DESIGN)
        a = design["arms"][arm]
        return {**(a.get("gate") or {}), **((a.get("gate_by_host") or {}).get(host) or {})}

    def gate(self, arm, host, *, models, efforts, routed, counts=None, switches=0):
        counts = {"difficulty_judged": 1, **(counts or {})}
        reqs = [{"model": m, "effort": e} for m, e in zip(models, efforts)]
        session = {"kind": "fd", "gate": self.arm_gate(arm, host)}
        return paired.mechanism_gate(session, counts, switches, models, efforts, routed, reqs)

    def decided(self, **kw):
        return {"source": "decided", "decision": "strong", "reason_code": "judge_strong", **kw}

    def test_shf_routed_session_passes(self):
        g = self.gate("shipped", "fable", models=["claude-sonnet-5"] * 3, efforts=["medium"] * 3,
                      routed=[self.decided(decision="cheap", reason_code="judge_cheap"), {"source": "restored"}],
                      counts={"model_routed": 3})
        self.assertTrue(g["mechanism_engaged"], g)

    def test_shf_kept_host_session_passes(self):
        g = self.gate("shipped", "fable", models=["claude-fable-5-1"] * 3, efforts=[None] * 3, routed=[self.decided()])
        self.assertTrue(g["mechanism_engaged"], g)

    def test_shf_wrong_effort_for_the_model_fails(self):
        g = self.gate("shipped", "fable", models=["claude-sonnet-5"] * 2, efforts=["medium", "high"], routed=[self.decided()])
        self.assertFalse(g["mechanism_engaged"])

    def test_shf_switch_or_double_decision_fails(self):
        g = self.gate("shipped", "fable", models=["claude-fable-5-1", "claude-sonnet-5"], efforts=[None, "medium"],
                      routed=[self.decided()], switches=1)
        self.assertFalse(g["mechanism_engaged"])
        g = self.gate("shipped", "fable", models=["claude-sonnet-5"], efforts=["medium"], routed=[self.decided(), self.decided()])
        self.assertFalse(g["mechanism_engaged"])
        g = self.gate("shipped", "fable", models=["claude-sonnet-5"], efforts=["medium"], routed=[])
        self.assertFalse(g["mechanism_engaged"])

    def test_sho_gate_closed_and_never_routes(self):
        ok = self.gate("shipped", "opus", models=["claude-opus-5-5"] * 3, efforts=[None] * 3,
                       routed=[self.decided(reason_code="price_gate_strong")])
        self.assertTrue(ok["mechanism_engaged"], ok)
        self.assertFalse(self.gate("shipped", "opus", models=["claude-opus-5-5"], efforts=[None],
                                   routed=[self.decided(reason_code="judge_strong")])["mechanism_engaged"])      # gate did not close
        self.assertFalse(self.gate("shipped", "opus", models=["claude-sonnet-5"], efforts=["medium"],
                                   routed=[self.decided(reason_code="price_gate_strong")],
                                   counts={"model_routed": 1})["mechanism_engaged"])                             # it routed
        self.assertFalse(self.gate("shipped", "opus", models=["claude-opus-5-5"], efforts=["medium"],
                                   routed=[self.decided(reason_code="price_gate_strong")])["mechanism_engaged"])  # effort set on ShO

    def test_sho_m_needs_medium_on_every_request(self):
        routed = [self.decided(reason_code="price_gate_strong")]
        self.assertTrue(self.gate("shipped_m", "opus", models=["claude-opus-5-5"] * 2, efforts=["medium"] * 2, routed=routed)["mechanism_engaged"])
        self.assertFalse(self.gate("shipped_m", "opus", models=["claude-opus-5-5"] * 2, efforts=["medium", None], routed=routed)["mechanism_engaged"])

    def test_pc_must_route_to_sonnet_at_medium(self):
        routed = [self.decided(decision="cheap", reason_code="rules_cheap")]
        self.assertTrue(self.gate("pc", "any", models=["claude-sonnet-5"] * 3, efforts=["medium"] * 3, routed=routed,
                                  counts={"model_routed": 3})["mechanism_engaged"])
        self.assertFalse(self.gate("pc", "any", models=["claude-sonnet-5"] * 3, efforts=["medium"] * 3, routed=routed)["mechanism_engaged"])
        self.assertFalse(self.gate("pc", "any", models=["claude-fable-5-1"] * 3, efforts=["medium"] * 3, routed=routed,
                                   counts={"model_routed": 3})["mechanism_engaged"])

    def test_phf_effort_is_constant(self):
        routed = [self.decided(reason_code="rules_strong")]
        self.assertTrue(self.gate("ph", "fable", models=["claude-fable-5-1"] * 3, efforts=[None] * 3, routed=routed)["mechanism_engaged"])
        self.assertFalse(self.gate("ph", "fable", models=["claude-fable-5-1"] * 3, efforts=[None, "low", None], routed=routed)["mechanism_engaged"])
        self.assertTrue(self.gate("ph_m", "fable", models=["claude-fable-5-1"] * 3, efforts=["medium"] * 3, routed=routed)["mechanism_engaged"])

    def test_plain_arms_have_effort_gates(self):
        s = {"kind": "plain", "gate": self.arm_gate("anchor_m", "opus")}
        ok = paired.mechanism_gate(s, {}, 0, ["claude-opus-5-5"], ["medium"])
        self.assertTrue(ok["mechanism_engaged"])
        self.assertFalse(paired.mechanism_gate(s, {}, 0, ["claude-opus-5-5"], [None])["mechanism_engaged"])

    def test_session_routed_is_parsed_from_events(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ev = [{"event": "fast_decisions:session_routed", "event_id": "1",
                   "data": {"source": "decided", "decision": "cheap", "reason_code": "judge_cheap", "scope": "session",
                            "gate": {"route": True, "reason": "cheaper"}}},
                  {"event": "fast_decisions:session_routed", "event_id": "2", "data": {"source": "restored", "decision": "cheap"}}]
            (Path(td) / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev), encoding="utf-8")
            parsed = paired.parse_events(td)
        self.assertEqual([r["source"] for r in parsed["session_routed"]], ["decided", "restored"])
        self.assertEqual(parsed["session_routed"][0]["gate_route"], True)
        self.assertEqual(parsed["fd_counts"]["session_routed"], 2)


class S1Smoke(unittest.TestCase):
    def test_smoke_is_one_plain_sonnet_session_per_scenario(self):
        design, specs, plan = plan_for(SMOKE, parallel=8)
        self.assertEqual(plan["n_sessions"], 60)
        self.assertEqual({s["cell"] for w in plan["waves"].values() for s in w}, {"plain-sonnet"})
        self.assertEqual(design["budget_usd"], 250)
        self.assertLess(plan["est_with_reserve_usd"], 250)

    def test_smoke_uses_the_same_scenarios_as_s1(self):
        a, b = paired.load_specs(paired.load_design(DESIGN)), paired.load_specs(paired.load_design(SMOKE))
        self.assertEqual({s.id: ps.scenario_hash(s) for s in a}, {s.id: ps.scenario_hash(s) for s in b})


class S1Render(unittest.TestCase):
    def test_every_contrast_differs_only_where_intended(self):
        import subprocess
        import sys
        import forge_e2e
        if not Path(forge_e2e.HOST_PYTHON).exists():
            self.skipTest("Amplifier host interpreter not installed")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run([sys.executable, str(ROOT / "evals/v3/s1_render_cells.py"), "--out", str(Path(td) / "r.json")],
                                  capture_output=True, text=True, timeout=900)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
