"""S1's shipped defaults: the rule decider R*, Fable C*_F, keep_on_host [review, explain], per-host strong effort.

Offline: no network, no model. The judge is a local fake. Evidence: docs/evidence/2026-10-06-holdout-v3/ (on the
v3/program branch), evals/v3/frozen_rule.json + FROZEN.md. The replay tests run when the recorded rows are present.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amplifier_fast_decisions import config as fd_config, effort, orchestrator, rules  # noqa: E402
from amplifier_fast_decisions.contracts import Policy  # noqa: E402
from test_decide import FABLE, OPUS, FakeJudge, decide_sync  # noqa: E402
from test_effort_constant import session_efforts  # noqa: E402

EVIDENCE_V3 = ROOT / "docs" / "evidence" / "2026-10-06-holdout-v3"
EVIDENCE_V1 = ROOT / "docs" / "evidence" / "2026-10-02-paired-campaign"
FROZEN_RULES = ROOT / "evals" / "v3" / "rules.py"
EXPLAIN = "Explain how the retry module works. Do not change any files."
REVIEW_MAP = "Give me a one-line role for each module under src/click/. Do not change any files."
FIX = "Fix the failing test in parser.py: the tokenizer drops the last character."
IMPLEMENT = "Implement a function slugify(text) in util.py that lowercases and joins words with dashes."


class ShippedDefaultsTests(unittest.TestCase):
    def test_the_shipped_decider_is_the_frozen_rule(self):
        cfg = fd_config.shipped_config()
        routing = cfg["model_routing"]
        # R*: always route, subject to the scope gate (frozen_rule.json: host_if_any [], scope gate 300).
        self.assertEqual(routing["start_policy"], "rules")
        self.assertIsNone(routing["complex_min_prompt_chars"])
        self.assertEqual(routing["cheap_max_workspace_files"], 300)
        self.assertEqual(routing["price_gate"], {"enabled": True})
        self.assertEqual(routing["start_model"], "claude-sonnet-5")
        self.assertEqual(routing["decision_scope"], "session")
        self.assertIs(cfg["allow_external_state"], False)  # no consent needed: nothing leaves the machine
        self.assertEqual(cfg["backend"], "jev")  # still the judge named for the start_policy: judge opt-in

    def test_c_star_f_efforts_and_the_keep_on_host_default(self):
        cfg = fd_config.shipped_config()
        self.assertEqual(cfg["effort_routing"]["by_tier"], {"cheap": "medium", "strong": None})
        self.assertEqual(cfg["effort_routing"]["by_host"], {"claude-fable-5-1": {"strong": "medium"}})
        self.assertEqual(cfg["model_routing"]["keep_on_host"], {"task_types": ["review", "explain"]})


class RuleDeciderTests(unittest.TestCase):
    def test_a_short_task_on_fable_routes_to_sonnet_medium_without_a_judge(self):
        d = decide_sync(FIX, FABLE)
        self.assertEqual((d.route, d.tier, d.model, d.effort, d.reason), (True, "cheap", "claude-sonnet-5", "medium", "rules_cheap"))
        self.assertEqual((d.decider, d.judge["status"], d.judge["backend"], d.usd), ("rules", "not_used", None, None))

    def test_there_is_no_prompt_length_rule(self):
        d = decide_sync(IMPLEMENT + " " + "detail " * 1000, FABLE)
        self.assertEqual((d.route, d.reason), (True, "rules_cheap"))

    def test_the_scope_gate_keeps_a_big_workspace_on_the_host_at_strong_medium(self):
        d = decide_sync(FIX, FABLE, files=301)
        self.assertEqual((d.route, d.model, d.effort, d.reason, d.workspace_files), (False, FABLE, "medium", "scope_strong", 301))
        self.assertTrue(decide_sync(FIX, FABLE, files=300).route)

    def test_opus_never_routes_and_keeps_the_default_effort(self):
        d = decide_sync(FIX, OPUS)
        self.assertEqual((d.route, d.model, d.effort, d.reason), (False, OPUS, None, "price_gate_strong"))

    def test_keep_on_host_keeps_question_shaped_sessions_on_the_host(self):
        for prompt in (EXPLAIN, REVIEW_MAP):
            d = decide_sync(prompt, FABLE)
            self.assertEqual((d.route, d.model, d.reason, d.judge["task_type"]), (False, FABLE, "task_type_strong", "explain"), prompt)
            self.assertEqual(d.effort, "medium")  # a host-kept Fable session runs at strong medium
        for prompt in (FIX, IMPLEMENT):
            self.assertTrue(decide_sync(prompt, FABLE).route, prompt)

    def test_keep_on_host_can_be_removed(self):
        d = decide_sync(EXPLAIN, FABLE, config={"model_routing": {"keep_on_host": None}})
        self.assertEqual((d.route, d.reason), (True, "rules_cheap"))

    def test_naming_a_judge_decider_is_the_opt_in(self):
        judge = FakeJudge(0.1, task_type="bugfix", external=False)
        d = decide_sync(FIX, FABLE, judge=judge)
        self.assertEqual((judge.calls, d.reason, d.judge["status"]), (1, "judge_cheap", "answered"))
        # `decider=` alone also switches the policy to the judge; without consent an external judge is not asked
        # and the answer falls back to the 2000-character rule (never to "always route").
        ext = FakeJudge(0.1, external=True)
        d = decide_sync("x" * 2500, FABLE, decider="jev", judge=ext, config={"model_routing": {"keep_on_host": None}})
        self.assertEqual((ext.calls, d.judge["status"], d.tier, d.reason), (0, "no_consent", "strong", "rules_strong"))

    def test_the_orchestrator_and_decide_agree_on_every_prompt_shape(self):
        from test_decide import orchestrator_decision
        for host in (FABLE, OPUS):
            for files in (10, 301):
                for prompt in (EXPLAIN, REVIEW_MAP, FIX, IMPLEMENT, "x"):
                    ref = asyncio.run(orchestrator_decision(host, prompt, FakeJudge(0.9), files))
                    mine = decide_sync(prompt, host, files=files)
                    got = {"tier": mine.tier, "reason": mine.reason, "model": mine.model, "effort": mine.effort}
                    self.assertEqual(got, ref, (host, files, prompt))

    def test_the_orchestrator_applies_one_model_and_one_effort_per_session(self):
        cfg = fd_config.shipped_config()
        routed = asyncio.run(session_efforts(cfg, 0.9, host=FABLE))  # the harness prompt "task" is not question-shaped
        self.assertEqual(set(routed), {("claude-sonnet-5", "medium")})
        opus = asyncio.run(session_efforts(cfg, 0.9, host=OPUS))
        self.assertEqual(set(opus), {(None, None)})  # gate closed: plain Opus, default effort


class ByHostEffortTests(unittest.TestCase):
    R = {"by_tier": {"cheap": "medium", "strong": None},
         "by_host": {"claude-fable": {"strong": "low"}, "claude-fable-5-1": {"strong": "medium"}}}

    def test_longest_prefix_wins_and_overrides_only_the_named_tiers(self):
        self.assertEqual(effort.effort_by_tier(self.R, "claude-fable-5-1"), {"cheap": "medium", "strong": "medium"})
        self.assertEqual(effort.effort_by_tier(self.R, "claude-fable-5-1-20261001"), {"cheap": "medium", "strong": "medium"})
        self.assertEqual(effort.effort_by_tier(self.R, "claude-fable-6"), {"cheap": "medium", "strong": "low"})

    def test_other_hosts_and_missing_hosts_keep_by_tier(self):
        for host in ("claude-opus-5-5", None, ""):
            self.assertEqual(effort.effort_by_tier(self.R, host), {"cheap": "medium", "strong": None})
        self.assertIsNone(effort.effort_by_tier({}, FABLE))
        self.assertEqual(effort.effort_by_tier({"by_tier": {"cheap": "low"}}, FABLE), {"cheap": "low"})

    def test_tier_effort_decision_uses_the_host(self):
        kw = dict(start_tier="strong", escalated=False, tier_effort=None, tier_label=None, user_model_pick=False, host_pinned=False)
        self.assertEqual(orchestrator.tier_effort_decision(self.R, host_model=FABLE, **kw)[:2], (True, "medium"))
        self.assertEqual(orchestrator.tier_effort_decision(self.R, host_model=OPUS, **kw)[:2], (True, None))
        # back-compat: callers that do not pass a host get by_tier
        self.assertEqual(orchestrator.tier_effort_decision(self.R, **kw)[:2], (True, None))

    def test_validation(self):
        base = {"start_model": "m", "start_policy": "rules"}
        ok = Policy.from_config({"model_routing": base, "effort_routing": {"by_host": {"h": {"strong": "medium"}}}})
        self.assertIsNotNone(ok)
        for bad in ({"h": {"fast": "low"}}, {"h": {}}, {"h": {"strong": "turbo"}}, {"h": "medium"}, {"": {"strong": "low"}}, ["h"]):
            with self.assertRaises(ValueError, msg=str(bad)):
                Policy.from_config({"model_routing": base, "effort_routing": {"by_host": bad}})

    def test_keep_on_host_validation(self):
        keep = {"task_types": ["review"]}
        for policy in ("rules", "judge"):
            Policy.from_config({"model_routing": {"start_model": "m", "start_policy": policy, "keep_on_host": keep}})
        with self.assertRaises(ValueError):
            Policy.from_config({"model_routing": {"start_model": "m", "start_policy": "cheap", "keep_on_host": keep}})


class IntentClassifierTests(unittest.TestCase):
    def test_task_type_mapping(self):
        self.assertEqual(rules.rule_task_type(EXPLAIN), "explain")
        self.assertEqual(rules.rule_task_type(FIX), "bugfix")
        self.assertEqual(rules.rule_task_type(IMPLEMENT), "feature")
        self.assertEqual(rules.rule_task_type("Rename the module."), "other")
        self.assertEqual(rules.rule_task_type(""), "other")

    @unittest.skipUnless(FROZEN_RULES.exists(), "evals/v3/rules.py (v3/program) not present")
    def test_identical_to_the_frozen_classifier(self):
        spec = importlib.util.spec_from_file_location("frozen_rules", FROZEN_RULES)
        frozen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frozen)
        for prompt in (EXPLAIN, REVIEW_MAP, FIX, IMPLEMENT, "Rename the module.", "Is this safe?", "from the log, count 5xx"):
            self.assertEqual(rules.classify_intent(prompt), frozen.classify_intent(prompt), prompt)


@unittest.skipUnless((EVIDENCE_V1 / "campaign" / "decisions.jsonl").exists(), "main-v1 evidence not present")
class MainV1ReplayTests(unittest.TestCase):
    def test_r_star_on_the_140_fable_waves(self):
        """R* routes exactly the waves under the scope gate; it disagrees with the recorded Jev decision on 14/140 (0.10)."""
        sessions = [json.loads(x) for x in (EVIDENCE_V1 / "data" / "sessions.jsonl").read_text(encoding="utf-8").splitlines() if x]
        files = {(s["scenario_id"], s["rep"], s["host"]): s["workspace_files"] for s in sessions if s["arm"] == "sticky"}
        decisions = [json.loads(x) for x in (EVIDENCE_V1 / "campaign" / "decisions.jsonl").read_text(encoding="utf-8").splitlines() if x]
        agree = disagree = 0
        for d in (d for d in decisions if d["host"] == "fable"):
            n = files[(d["scenario"], d["rep"], d["host"])]
            r = decide_sync("scripted turn", FABLE, files=n)  # the harness prompt is not question-shaped
            self.assertEqual(r.route, n <= 300)
            same = (d["decision"] == "cheap") == r.route
            agree, disagree = agree + same, disagree + (not same)
        self.assertEqual((agree, disagree), (126, 14))


@unittest.skipUnless((EVIDENCE_V3 / "data" / "sessions.jsonl").exists(), "holdout-v3 evidence not present (v3/program)")
class HoldoutV3ReplayTests(unittest.TestCase):
    def test_c_star_f_cost_and_turn_pass_replay(self):
        """R* (scope 300, strong medium on the host) over the holdout rows reproduces S1's H1 point estimates."""
        import math
        rows = [json.loads(x) for x in (EVIDENCE_V3 / "data" / "sessions.jsonl").read_text(encoding="utf-8").splitlines() if x]
        idx = {(r["scenario_id"], r["rep"], r["arm"], r["host"]): r for r in rows if r["arm"] != "aa"}
        logs, dq = [], []
        for (sid, rep, arm, host), a in idx.items():
            if arm != "anchor" or host != "fable":
                continue
            pc, ph = idx.get((sid, rep, "pc", "any")), idx.get((sid, rep, "ph_m", "fable"))
            if not (pc and ph and a["cost_valid"] and pc["cost_valid"] and ph["cost_valid"]):
                continue
            kept = decide_sync("scripted turn", FABLE, files=a["workspace_files"], config={"model_routing": {"keep_on_host": None}})
            chosen = pc if kept.route else ph
            logs.append(math.log(chosen["cost_usd_tools_normalized"] / a["cost_usd_tools_normalized"]))
            dq.append(chosen["turn_pass_frac"] - a["turn_pass_frac"])
        self.assertEqual(len(logs), 120)
        self.assertAlmostEqual(math.exp(sum(logs) / len(logs)), 0.581, delta=0.0015)
        self.assertAlmostEqual(sum(dq) / len(dq), -0.013, delta=0.0015)


if __name__ == "__main__":
    unittest.main()
