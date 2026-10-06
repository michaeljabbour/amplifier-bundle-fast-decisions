"""Unit tests for the v3 offline analyses (evals/v3: A0 counterfactual, A1 observatory, A3 projection inputs) and a
sanitization guard on their committed evidence (docs/evidence/2026-10-v3-offline). Synthetic data only: no model
calls, no network, nothing read from the home directory."""
from __future__ import annotations

import gzip
import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.v3 import a0_counterfactual as A0  # noqa: E402
from evals.v3 import a1_observatory as A1  # noqa: E402
from evals.v3 import a3_projection as A3  # noqa: E402
from evals.v3 import rules as R  # noqa: E402
from evals.v3.common import cluster_bootstrap, cluster_mean, quantile, sanitize, wilson  # noqa: E402

EVIDENCE = REPO_ROOT / "docs" / "evidence" / "2026-10-v3-offline"
FROZEN = REPO_ROOT / "evals" / "v3" / "frozen_rule.json"


class CommonTests(unittest.TestCase):
    def test_wilson_matches_reference(self):
        p, lo, hi = wilson(117, 1642)
        self.assertAlmostEqual(p, 0.071255, places=5)
        self.assertAlmostEqual(lo, 0.059787, places=5)
        self.assertAlmostEqual(hi, 0.084724, places=5)
        self.assertEqual(wilson(0, 10)[1], 0.0)

    def test_quantile_linear(self):
        self.assertEqual(quantile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(quantile([5], 0.95), 5)

    def test_cluster_bootstrap_deterministic_and_bounds(self):
        data = {"a": [1.0, 1.0], "b": [3.0], "c": [2.0, 2.0]}
        p1 = cluster_bootstrap(data, cluster_mean, n=500, seed=1)
        p2 = cluster_bootstrap(data, cluster_mean, n=500, seed=1)
        self.assertEqual(p1, p2)
        self.assertAlmostEqual(p1[0], 2.0)
        self.assertLessEqual(p1[1], p1[0])
        self.assertGreaterEqual(p1[2], p1[0])

    def test_sanitize_home_and_keys(self):
        self.assertEqual(sanitize(str(Path.home()) + "/x"), "~/x")
        with self.assertRaises(ValueError):
            sanitize({"k": "sk-abc123456"})
        self.assertIsNone(sanitize(float("nan")))


class RulesTests(unittest.TestCase):
    def test_intent_classifier(self):
        self.assertEqual(R.classify_intent("Read .docs/instructions.md and implement `x`"), "implement")
        self.assertEqual(R.classify_intent("Explain how the parser works"), "question")
        self.assertEqual(R.classify_intent("`foo()` crashes on empty input"), "fix")
        self.assertEqual(R.classify_intent("Tidy the module layout"), "other")
        self.assertEqual(R.classify_intent("The cache keys drift sometimes?"), "question")

    def test_decide_and_scope_gate(self):
        rule = {"host_if_any": [{"feature": "turn1_prompt_chars", "op": ">", "value": 100}],
                "scope_gate_max_workspace_files": 300}
        self.assertEqual(R.decide(rule, R.features("x" * 50, 10)), "cheap")
        self.assertEqual(R.decide(rule, R.features("x" * 150, 10)), "host")
        self.assertEqual(R.decide(rule, R.features("x" * 50, 301)), "host")
        always = {"host_if_any": [], "scope_gate_max_workspace_files": 300}
        self.assertEqual(R.decide(always, R.features("y", 300)), "cheap")
        self.assertEqual(R.complexity(always), 0)
        self.assertEqual(R.describe(always), "always route")
        self.assertEqual(R.complexity({"host_if_any": [{"feature": "intent", "op": "in", "value": ["fix", "other"]}]}), 2)


def unit(scen, rep, host="fable", split="train", ch=10.0, cc=5.0, th=1.0, tc=1.0, jev="cheap", chars=100, ws=10,
         intent="fix"):
    return {"host": host, "scenario": scen, "rep": rep, "split": split, "task_type": "bugfix", "cost_host": ch,
            "tp_host": th, "final_host": th == 1.0, "wall_host_min": 5.0, "cost_cheap": cc, "tp_cheap": tc,
            "final_cheap": tc == 1.0, "wall_cheap_min": 4.0, "cheap_source": "sticky_cheap", "jev": jev,
            "turn1_prompt_chars": chars, "workspace_files": ws, "intent": intent}


class A0Tests(unittest.TestCase):
    def test_build_units_potential_outcomes(self):
        base = {"cost_valid": True, "split": "train", "task_type": "bugfix", "workspace_files": 5, "wall_ms": 60000,
                "final_state_pass": True}
        sessions = []
        for scen, sticky in (("s1", "cheap"), ("s2", "host")):
            sessions += [
                {**base, "host": "fable", "arm": "anchor", "scenario_id": scen, "rep": 1, "cost_usd_tools_normalized": 10.0,
                 "turn_pass_frac": 1.0},
                {**base, "host": "fable", "arm": "sticky", "scenario_id": scen, "rep": 1, "sticky_decision": sticky,
                 "cost_usd_tools_normalized": 4.0, "turn_pass_frac": 0.9},
                {**base, "host": "any", "arm": "sonnet", "scenario_id": scen, "rep": 1, "cost_usd_tools_normalized": 6.0,
                 "turn_pass_frac": 0.8}]
        decisions = [{"host": "fable", "scenario": "s1", "rep": 1, "decision": "cheap"},
                     {"host": "fable", "scenario": "s2", "rep": 1, "decision": "host"}]
        prompts = {"s1": "fix the bug", "s2": "implement it"}
        us = {u["scenario"]: u for u in A0.build_units(sessions, decisions, prompts)}
        self.assertEqual(us["s1"]["cost_cheap"], 4.0)             # the sticky-cheap session
        self.assertEqual(us["s1"]["tp_cheap"], 0.9)
        self.assertAlmostEqual(us["s2"]["cost_cheap"], 6.0 * A0.SONNET_MEDIUM_FACTOR)   # fallback: Sonnet x 0.821
        self.assertEqual(us["s2"]["tp_cheap"], 0.8)
        self.assertEqual(us["s2"]["cheap_source"], f"sonnet_x{A0.SONNET_MEDIUM_FACTOR}")
        self.assertEqual(us["s2"]["cost_host"], 10.0)              # host = plain anchor, never the sticky-host session
        self.assertEqual(us["s1"]["intent"], "fix")
        son = {u["scenario"]: u for u in A0.build_units(sessions, decisions, prompts, cheap_source="sonnet")}
        self.assertAlmostEqual(son["s1"]["cost_cheap"], 6.0 * A0.SONNET_MEDIUM_FACTOR)

    def test_oracle_and_cross_fit(self):
        u1 = unit("a", 1, cc=5, tc=0.9)        # cheaper but worse: equal-quality oracle keeps host
        u2 = unit("a", 2, cc=5, tc=1.0)        # cheaper and as good: route
        self.assertEqual(A0.oracle_choice(u1), "host")
        self.assertEqual(A0.oracle_choice(u1, cost_only=True), "cheap")
        self.assertEqual(A0.oracle_choice(u2), "cheap")
        xf = A0.cross_fit([u1, u2], A0.oracle_choice)
        self.assertEqual(xf[("fable", "a", 1)], "cheap")          # chosen on rep 2
        self.assertEqual(xf[("fable", "a", 2)], "host")           # chosen on rep 1

    def test_evaluate_and_disagreement_identity(self):
        units = [unit("a", 1, ch=10, cc=5), unit("b", 1, ch=8, cc=2, jev="host")]
        pols = A0.policy_decisions(units)
        ev = A0.evaluate(units, pols["always_host"], resamples=50)
        self.assertAlmostEqual(ev["gm_cost_ratio"], 1.0)
        ev = A0.evaluate(units, pols["always_route"], resamples=50)
        self.assertAlmostEqual(ev["gm_cost_ratio"], math.exp((math.log(.5) + math.log(.25)) / 2))
        self.assertEqual(ev["route_share"], 1.0)
        d = A0.disagreement(units, pols["jev_recorded"], pols["always_route"])
        self.assertEqual(d["n_discordant"], 1)
        self.assertAlmostEqual(d["d"], 0.5)
        self.assertAlmostEqual(d["implied_mean_cost_diff_usd"], 0.5 * (8 - 2))
        self.assertEqual(pols["shipped_jev_price_gate"][("fable", "a", 1)], "cheap")
        opus = [unit("a", 1, host="opus")]
        self.assertEqual(A0.policy_decisions(opus)["shipped_jev_price_gate"][("opus", "a", 1)], "host")

    def test_fit_rule_prefers_always_route_unless_floor_binds(self):
        good = [unit(f"s{i}", r, chars=100 + i) for i in range(10) for r in (1, 2)]
        rule, table = A0.fit_rule(good, quality_floor=-0.025)
        self.assertEqual(rule["host_if_any"], [])
        self.assertEqual(sum(t["chosen"] for t in table), 1)
        # long prompts lose quality when routed: the floor forces a length rule
        bad = [unit(f"s{i}", r, chars=100 if i < 5 else 900, tc=1.0 if i < 5 else 0.5) for i in range(10) for r in (1, 2)]
        rule, _ = A0.fit_rule(bad, quality_floor=-0.025)
        self.assertTrue(rule["host_if_any"])
        self.assertEqual(R.decide(rule, R.features("x" * 900, 10)), "host")
        self.assertEqual(R.decide(rule, R.features("x" * 100, 10)), "cheap")
        floor, rows = A0.select_floor(bad, k=2)
        self.assertEqual(len(rows), len(A0.CV_FLOORS))
        self.assertIn(floor, A0.CV_FLOORS)

    def test_effort_cache_positions(self):
        sessions = [
            {"session_key": "s-st", "arm": "sticky", "sticky_decision": "host", "host": "fable", "scenario_id": "x",
             "rep": 1, "cost_usd_tools_normalized": 12.0},
            {"session_key": "s-an", "arm": "anchor", "sticky_decision": None, "host": "fable", "scenario_id": "x",
             "rep": 1, "cost_usd_tools_normalized": 10.0}]

        def req(sk, i, turn, effort, write):
            return {"session_key": sk, "main": True, "request_index": i, "turn_index": turn, "effort": effort,
                    "model": "claude-fable-5-1", "tokens": {"cache_write": write, "cache_read": 0}}
        reqs = [req("s-st", 1, 1, "high", 30000), req("s-st", 2, 1, "high", 1000), req("s-st", 3, 1, "low", 20000),
                req("s-st", 4, 2, "low", 900), req("s-st", 5, 3, "high", 60000),
                req("s-an", 1, 1, None, 30000), req("s-an", 2, 1, None, 1100), req("s-an", 3, 2, None, 12000)]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "requests.jsonl.gz"
            with gzip.open(p, "wt") as fh:
                for r in reqs:
                    fh.write(json.dumps(r) + "\n")
            gaps = {("s-st", 3): 420, ("s-st", 2): 10, ("s-an", 2): 10}
            summ, agg, srows = A0.effort_cache(p, sessions, gaps)
        self.assertEqual(summ["requests_after_effort_change"]["n"], 2)
        self.assertEqual(summ["requests_after_effort_change"]["mean_cache_write"], 40000)
        self.assertEqual(summ["requests_effort_unchanged"]["n"], 2)
        self.assertEqual(summ["by_position"]["sticky_host|changed|turn_first_long_gap"]["n"], 1)
        self.assertEqual(summ["within_turn_ratio_changed_over_unchanged"], 20.0)
        self.assertEqual(srows[0]["effort_changes"], 2)
        self.assertAlmostEqual(srows[0]["cost_ratio"], 1.2)
        # premium only on the within-turn change (the long-gap change is excluded): (20000 - 1000) x (12.5 - 0.25)/1e6
        self.assertAlmostEqual(srows[0]["est_rewrite_premium_usd"], 19000 * 12.25 / 1e6)


def ev(event, sid, ts, data=None, decision=None, parent=None):
    return {"event": f"fast_decisions:{event}", "session_id": sid, "timestamp": ts, "data": data or {},
            "decision_id": decision, "parent_session_id": parent}


class A1Tests(unittest.TestCase):
    def build(self):
        c = A1.Census(cutoff="2026-10-01T00:00:00+00:00")
        t = "2026-09-18T10:00:00+00:00"
        c.add(ev("health", "p1", t, {"phase": "configuration", "workspace_name": "secret-project", "mode": "shadow"}))
        c.add(ev("health", "p1", t, {"phase": "session_heartbeat"}))
        c.add(ev("health", "f1", t, {"phase": "configuration", "workspace_name": "workspace", "session_label": "Forge x"}))
        c.add(ev("health", "k1", t, {"phase": "turn_start"}, parent="f1"))
        c.add(ev("health", "u1", t, {"phase": "session_heartbeat"}))
        # shadow: scripted demo mismatch (other tool), local match (candidate tool), local abstain
        c.add(ev("shadow_proposed", "p1", t, {"backend": "scripted-demo", "model": "m", "synthetic": True,
                                              "duration_ms": 35}, "d1"))
        c.add(ev("shadow_agreement", "p1", t, {"agreement": "mismatch", "actual_tool": "bash"}, "d1"))
        c.add(ev("shadow_proposed", "f1", t, {"backend": "ollama-token", "model": "q", "duration_ms": 50}, "d2"))
        c.add(ev("shadow_agreement", "f1", t, {"agreement": "match", "actual_tool": "fast_workspace"}, "d2"))
        c.add(ev("shadow_proposed", "f1", t, {"backend": "ollama-token", "model": "q", "duration_ms": 70}, "d3"))
        c.add(ev("shadow_agreement", "f1", t, {"agreement": "abstained", "actual_tool": "read_file"}, "d3"))
        c.add(ev("difficulty_judged", "p1", "2026-09-26T00:00:00+00:00",
                 {"backend": "jev", "reason_code": "judge_cheap", "choice": "cheap", "duration_ms": 150}))
        c.add(ev("difficulty_judged", "p1", "2026-09-26T00:00:01+00:00",
                 {"backend": "jev", "reason_code": "scope_strong", "choice": "strong", "duration_ms": 0}))
        c.add(ev("efficiency", "e1", "2026-09-26T00:00:00+00:00",
                 {"lever": "cache_keepalive", "decision": "kept_cache_warm", "traffic": "test", "usd_saved": 1.5,
                  "seconds_saved": 0}))
        c.add(ev("health", "e1", "2026-09-26T00:00:00+00:00", {"phase": "configuration", "workspace_name": "real-repo"}))
        c.add(ev("slow_end", "p1", "2026-09-26T00:00:02+00:00", {"duration_ms": 1000, "host_model": "claude-opus-5-5",
                                                                  "cost_usd": 0.5, "cache_read_tokens": 10}))
        for eff in ("high", "high", "low"):
            c.add(ev("effort_routed", "p1", "2026-09-26T00:00:03+00:00", {"requested_effort": eff}))
        c.add(ev("health", "p1", "2026-10-02T00:00:00+00:00", {"phase": "session_heartbeat"}))   # after cutoff
        return c

    def test_classification(self):
        c = self.build()
        cls = c.classify()
        self.assertEqual(cls[("events", "p1")], ("production", "workspace_default"))
        self.assertEqual(cls[("events", "f1")], ("test", "forge_label"))
        self.assertEqual(cls[("events", "k1")], ("test", "inherited_from_parent"))
        self.assertEqual(cls[("events", "u1")], ("unclassified", "no_config"))
        self.assertEqual(cls[("events", "e1")], ("test", "afast_traffic_tag"))    # the receipt tag beats the name
        self.assertEqual(A1.classify_name("ampcfg.UYO5", None), ("test", "workspace_marker"))
        self.assertEqual(A1.classify_name("teamproject", None), ("production", "workspace_default"))

    def test_finish_shadow_latency_receipts(self):
        c = self.build()
        res = c.finish()
        self.assertEqual(c.excluded_after_cutoff, 1)
        r = res["shadow_rates"]
        self.assertEqual((r["all (the 7.1% headline)"]["match"], r["all (the 7.1% headline)"]["n"]), (1, 3))
        self.assertEqual(r["scripted-demo backend (synthetic: always the first candidate)"]["n"], 1)
        self.assertEqual(r["real scorer, host used the candidate tool"]["n"], 1)
        self.assertEqual(r["real scorer, not abstained"]["n"], 1)
        self.assertEqual(r["any scorer, host used another tool (unmatchable by construction)"]["n"], 2)
        kinds = {(x["kind"], x["backend"]): x for x in res["latency"]}
        self.assertEqual(kinds[("difficulty_judged:judge_call", "jev")]["n"], 1)
        self.assertEqual(kinds[("difficulty_judged:no_judge_call", "jev")]["p50_ms"], 0.0)
        self.assertEqual(kinds[("shadow_proposed", "ollama-token")]["p50_ms"], 60.0)
        self.assertEqual(res["receipts"][0]["usd_saved_sum"], 1.5)
        self.assertEqual(res["start_tier_first_per_session"][0]["reason_code"], "judge_cheap")
        self.assertEqual(res["workload"][0]["host_model"], "claude-opus-5-5")
        es = {e["traffic"]: e for e in res["effort_switching"]}
        self.assertEqual((es["production"]["requests"], es["production"]["effort_changes"]), (3, 1))
        hb = {h["health_kind"]: h["n"] for h in res["health_mix"]}
        self.assertEqual(hb["session_heartbeat"], 2)

    def test_run_writes_no_names(self):
        with tempfile.TemporaryDirectory() as d:
            ev_dir, out = Path(d) / "events", Path(d) / "out"
            ev_dir.mkdir()
            with open(ev_dir / "p1.jsonl", "w") as fh:
                for e in self.build_events():
                    fh.write(json.dumps(e) + "\n")
                fh.write("not json\n")
            s = A1.run(ev_dir, Path(d) / "missing", "2026-10-01T00:00:00+00:00", out)
            self.assertEqual(s["store"]["bad_lines"], 1)
            blob = "".join(p.read_text() for p in out.iterdir())
            self.assertNotIn("secret-project", blob)
            self.assertNotIn("Forge x", blob)

    def build_events(self):
        t = "2026-09-18T10:00:00+00:00"
        return [ev("health", "p1", t, {"phase": "configuration", "workspace_name": "secret-project",
                                       "session_label": "Forge x"}),
                ev("shadow_proposed", "p1", t, {"backend": "ollama-token", "duration_ms": 40}, "d1"),
                ev("shadow_agreement", "p1", t, {"agreement": "mismatch", "actual_tool": "bash"}, "d1")]


class A3Tests(unittest.TestCase):
    def test_projection(self):
        workload = [{"traffic": "production", "host_model": "claude-opus-5-5", "recorded_cost_usd": 60.0},
                    {"traffic": "production", "host_model": "claude-sonnet-5", "recorded_cost_usd": 40.0},
                    {"traffic": "test", "host_model": "claude-opus-5-5", "recorded_cost_usd": 999.0}]
        start = [{"traffic": "production", "reason_code": "scope_strong", "sessions": 5},
                 {"traffic": "production", "reason_code": "judge_cheap", "sessions": 5}]
        a0 = {"s1_predictions": {"C*_F": {"gm_cost_ratio": 0.5, "gm_cost_ratio_ci95": [0.45, 0.55]}},
              "headline": {"fable": {"always_route": {"all": {"gm_cost_ratio": 0.5}},
                                     "jev_recorded": {"all": {"route_share": 0.9}}}}}
        r = A3.project(workload, start, a0)
        self.assertAlmostEqual(r["spend_share_by_host"]["opus"], 0.6)
        self.assertEqual(r["projection_on_recorded_mix"]["shipped"]["ratio"], 1.0)
        self.assertAlmostEqual(r["projection_on_recorded_mix"]["C*"]["ratio"], 0.6 * 0.84 + 0.4 * 0.821)
        self.assertAlmostEqual(r["fable_host_what_if"]["ratio_R*_strong_default"], 0.5 * 1.0 + 0.5 * 0.5)
        self.assertFalse(r["projection_on_recorded_mix"]["C*"]["meets_goal_cost"])


class FrozenAndEvidenceTests(unittest.TestCase):
    def test_frozen_rule_is_applicable(self):
        if not FROZEN.exists():
            self.skipTest("frozen_rule.json not generated")
        f = json.loads(FROZEN.read_text())
        rule = f["R*"]["spec"]
        self.assertIn(R.decide(rule, R.features("Explain the module", 12)), ("cheap", "host"))
        self.assertEqual(R.decide(rule, R.features("anything", 10_000)), "host")      # scope gate is part of R*
        self.assertEqual(f["R*"]["intent_classifier"], R.INTENT_CLASSIFIER)
        self.assertIn("C*_F", f["candidate_configs"])
        self.assertIn("C*_O", f["candidate_configs"])

    def test_evidence_sanitized(self):
        if not EVIDENCE.exists():
            self.skipTest("no v3 offline evidence yet")
        home = re.compile(re.escape(str(Path.home())) + r"|/Users/[^/\s\"']+|/home/[a-z_][a-z0-9_-]*/")
        keyish = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]|Bearer [A-Za-z0-9]|[A-Z_]*API_KEY\s*=\s*\S")
        forbidden_keys = {"prompt", "prompts", "response", "responses", "content", "messages", "transcript",
                          "workspace_name", "session_label", "stdout", "stderr"}
        for p in EVIDENCE.rglob("*"):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
            self.assertIsNone(home.search(text), f"home path in {p}")
            self.assertIsNone(keyish.search(text), f"key-like string in {p}")
            if p.suffix == ".json":
                def walk(v):
                    if isinstance(v, dict):
                        for k, x in v.items():
                            self.assertNotIn(k, forbidden_keys, f"{k} in {p}")
                            walk(x)
                    elif isinstance(v, list):
                        for x in v:
                            walk(x)
                walk(json.loads(text))
            if p.suffix == ".csv":
                header = text.splitlines()[0].split(",") if text else []
                self.assertFalse(forbidden_keys & set(header), f"forbidden column in {p}")


if __name__ == "__main__":
    unittest.main()
