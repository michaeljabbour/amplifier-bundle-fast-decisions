"""`decide`: the session-start decision, and its parity with the Amplifier orchestrator.

No network, no model: every judge is a local fake. The parity tests drive the REAL orchestrator
(`RoutedProvider` over a `DemoProvider`) and `decide()` with the same shipped config, judge answer, host model and
workspace size, and require the same tier, model, effort and reason on (a) the 280 recorded main-v1 waves and
(b) the turn-1 prompt of every main-v1 scenario on both priced hosts.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import config as fd_config, decide as decide_lib, orchestrator  # noqa: E402
from amplifier_fast_decisions.contracts import Answer, Decision, DecisionResult, Policy, SLOW, TurnState  # noqa: E402
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response  # noqa: E402
from amplifier_fast_decisions.runtime import Runtime  # noqa: E402
from amplifier_fast_decisions.service import DecisionService  # noqa: E402
from amplifier_fast_decisions.telemetry import Emitter  # noqa: E402

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-1"
EVIDENCE = ROOT / "docs" / "evidence" / "2026-10-02-paired-campaign"
SCENARIOS = ROOT / "evals" / "paired" / "scenarios" / "main-v1"


class FakeJudge:
    """Answers task_difficulty with a fixed p(complex). `external` mirrors a remote judge (consent gate)."""

    def __init__(self, p_complex: float, *, external: bool = False, task_type: str | None = None,
                 name: str = "fake-judge", input_tokens: int | None = None):
        self.p_complex, self.external, self.name, self.calls = p_complex, external, name, 0
        self.task_type, self.input_tokens = task_type, input_tokens

    async def ask(self, request):
        self.calls += 1
        answers = {"task_difficulty": Answer(probabilities={"simple": 1 - self.p_complex, "complex": self.p_complex})}
        if self.task_type and any(q.name == "task_type" for q in request.questions):
            answers["task_type"] = Answer(probabilities={self.task_type: 0.95})
        return DecisionResult(action=Decision(choice=SLOW, probabilities={SLOW: 1.0}), answers=answers,
                              model="fake", input_tokens=self.input_tokens, output_tokens=2)

    async def ask_many(self, request):
        return await self.ask(request)

    async def close(self):
        pass


def shipped() -> dict:
    return fd_config.shipped_config()


JUDGE_OPT_IN = {"model_routing": {"start_policy": "judge", "keep_on_host": None}}


def decide_sync(task, host, *, judge=None, files=10, **kw):
    """`judge=` is the opt-in to the judge path (Jev by default); without it the shipped rule decider R* decides."""
    if judge is not None:
        kw["config"] = fd_config.deep_merge(JUDGE_OPT_IN, kw.get("config") or {})
    with mock.patch.object(orchestrator, "workspace_file_count", lambda root, limit: files):
        return asyncio.run(decide_lib.adecide(task, host, "/ws", _backend=judge, use_settings=False, **kw))


async def orchestrator_decision(host: str, prompt: str, judge: FakeJudge, files: int, config: dict | None = None) -> dict:
    """What the real orchestrator does at turn 1 under the shipped policy (the reference `decide` must match)."""
    events: list[dict] = []
    coordinator = DemoCoordinator()
    emitter = Emitter(coordinator.session_id, callback=events.append)
    policy = Policy.from_config({**fd_config.deep_merge(shipped(), config or {}), "mode": "off", "read_shortcut": False})
    service = DecisionService(policy, judge, emitter, coordinator, [])
    service.turn = TurnState("t1")
    provider = DemoProvider(delay_ms=0)
    provider.default_model = host
    facade = orchestrator.RoutedProvider(provider, Runtime(service), {}, demo_response, "anthropic-primary")
    req = NS(messages=[{"role": "user", "content": prompt}], tools=[], tool_choice="auto")
    with mock.patch.object(orchestrator, "workspace_file_count", lambda root, limit: files):
        await facade.complete(req)
    judged = [e["data"] for e in events if e["event"].endswith("difficulty_judged")][0]
    return {"tier": judged["choice"], "reason": judged["reason_code"],
            "model": getattr(req, "model", None) or host, "effort": getattr(req, "reasoning_effort", None)}


class DecideBehaviorTests(unittest.TestCase):
    def test_easy_task_on_a_pricey_host_routes_to_the_cheap_model_at_medium_effort(self):
        d = decide_sync("fix the typo in README", FABLE, judge=FakeJudge(0.1))
        self.assertEqual((d.route, d.tier, d.model, d.effort, d.reason), (True, "cheap", "claude-sonnet-5", "medium", "judge_cheap"))
        self.assertEqual(d.judge["status"], "answered")
        self.assertEqual(d.gate["reason"], "price_gate_route")
        self.assertEqual(d.scope, "session")

    def test_hard_task_stays_on_the_host_with_the_default_effort(self):
        d = decide_sync("redesign the storage layer", FABLE, judge=FakeJudge(0.9))
        self.assertEqual((d.route, d.tier, d.model, d.effort, d.reason), (False, "strong", FABLE, "medium", "judge_strong"))  # Fable: by_host strong medium
        d = decide_sync("redesign the storage layer", OPUS, judge=FakeJudge(0.9), config={"model_routing": {"price_gate": {"enabled": False}}})
        self.assertEqual((d.route, d.model, d.effort), (False, OPUS, None))  # Opus: provider default effort

    def test_price_gate_keeps_opus_on_the_host_without_asking_the_judge(self):
        judge = FakeJudge(0.1)
        d = decide_sync("fix the typo", OPUS, judge=judge)
        self.assertEqual((d.route, d.model, d.reason), (False, OPUS, "price_gate_strong"))
        self.assertEqual(judge.calls, 0)
        self.assertEqual(d.judge["status"], "skipped_price_gate")
        self.assertGreater(d.gate["predicted_cost_ratio"], 1.0)

    def test_scope_gate_keeps_a_large_workspace_on_the_host(self):
        limit = shipped()["model_routing"]["cheap_max_workspace_files"]
        judge = FakeJudge(0.1)
        d = decide_sync("fix the typo", FABLE, judge=judge, files=limit + 1)
        self.assertEqual((d.route, d.reason, d.judge["status"]), (False, "scope_strong", "skipped_scope_gate"))
        self.assertEqual((d.workspace_files, d.scope_limit, judge.calls), (limit + 1, limit, 0))

    def test_a_user_picked_model_always_wins(self):
        d = decide_sync("fix the typo", FABLE, judge=FakeJudge(0.1), user_model="claude-opus-5-5")
        self.assertEqual((d.route, d.model, d.reason, d.judge["status"]), (False, "claude-opus-5-5", "user_model_strong", "skipped_user_model"))

    def test_external_judge_without_consent_falls_back_to_the_rule_and_says_so(self):
        judge = FakeJudge(0.1, external=True)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAST_DECISIONS_ALLOW_EXTERNAL_STATE", None)
            d = decide_sync("fix the typo", FABLE, judge=judge, allow_external_state=None)
        self.assertEqual(judge.calls, 0)
        self.assertEqual(d.judge["status"], "no_consent")
        self.assertEqual(d.reason, "rules_cheap")

    def test_consent_from_the_environment_or_the_argument_lets_the_judge_run(self):
        judge = FakeJudge(0.9, external=True)
        d = decide_sync("fix the typo", FABLE, judge=judge, allow_external_state=True)
        self.assertEqual((judge.calls, d.reason), (1, "judge_strong"))
        judge2 = FakeJudge(0.9, external=True)
        with mock.patch.dict(os.environ, {"FAST_DECISIONS_ALLOW_EXTERNAL_STATE": "true"}):
            d2 = decide_sync("fix the typo", FABLE, judge=judge2)
        self.assertEqual((judge2.calls, d2.reason), (1, "judge_strong"))

    def test_the_shipped_bundle_consent_is_not_inherited_outside_amplifier(self):
        # The shipped decider needs no consent (allow_external_state: false); a judge opt-in still has to ask for it.
        self.assertIs(shipped()["allow_external_state"], False)
        judge = FakeJudge(0.1, external=True)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAST_DECISIONS_ALLOW_EXTERNAL_STATE", None)
            decide_sync("fix the typo", FABLE, judge=judge)
        self.assertEqual(judge.calls, 0)

    def test_study_deciders(self):
        self.assertEqual(decide_sync("x", FABLE, decider="always-host").route, False)
        cheap = decide_sync("x", OPUS, decider="always-cheap")
        self.assertEqual((cheap.route, cheap.model, cheap.effort), (True, "claude-sonnet-5", "medium"))
        # Shipped `rules` is R*: no prompt-length rule, so a long prompt routes too.
        always = decide_sync("x" * 2500, FABLE, decider="rules")
        self.assertEqual((always.tier, always.route, always.reason), ("cheap", True, "rules_cheap"))
        # The older length rule is still there for a config that sets the key.
        length = {"model_routing": {"complex_min_prompt_chars": 2000}}
        long_task = decide_sync("x" * 2500, FABLE, decider="rules", config=length)
        self.assertEqual((long_task.tier, long_task.reason), ("strong", "rules_strong"))
        short = decide_sync("x" * 20, FABLE, decider="rules")
        self.assertEqual((short.tier, short.route, short.reason), ("cheap", True, "rules_cheap"))

    def test_a_non_anthropic_host_is_not_routed_to_an_anthropic_start_model(self):
        d = decide_sync("fix the typo", "gpt-6-astra", judge=FakeJudge(0.1), config={"model_routing": {"price_gate": {"enabled": False}}})
        self.assertEqual((d.route, d.model, d.reason), (False, "gpt-6-astra", "provider_not_matched"))

    def test_cheap_model_override_routes_another_family(self):
        d = decide_sync("fix the typo", "gpt-6-astra", judge=FakeJudge(0.1), cheap_model="gpt-6-mini",
                        config={"model_routing": {"price_gate": {"enabled": False}}})
        self.assertEqual((d.route, d.model, d.start_model), (True, "gpt-6-mini", "gpt-6-mini"))

    def test_config_override_disables_the_price_gate(self):
        d = decide_sync("fix the typo", OPUS, judge=FakeJudge(0.1), config={"model_routing": {"price_gate": {"enabled": False}}})
        self.assertEqual((d.route, d.reason), (True, "judge_cheap"))

    def test_judge_cost_is_estimated_from_reported_tokens_and_the_backend_price(self):
        judge = FakeJudge(0.1, external=True, name="clef", input_tokens=400)
        d = decide_sync("fix the typo", FABLE, judge=judge, allow_external_state=True)
        self.assertAlmostEqual(d.usd, 400 * 0.24 / 1e6, places=9)

    def test_decision_is_json_serializable_and_typed(self):
        d = decide_sync("fix the typo", FABLE, judge=FakeJudge(0.1))
        data = json.loads(json.dumps(d.to_dict()))
        for key in ("route", "tier", "model", "effort", "reason", "gate", "judge", "host_model", "start_model", "decider",
                    "latency_ms", "usd", "config_sha", "schema"):
            self.assertIn(key, data)
        self.assertEqual(data["schema"], "fd-decision/1")

    def test_inputs_are_validated(self):
        with self.assertRaises(ValueError):
            decide_sync("  ", FABLE)
        with self.assertRaises(ValueError):
            decide_sync("x", FABLE, decider="nope")

    def test_sync_decide_refuses_to_run_inside_a_loop(self):
        async def inside():
            decide_lib.decide("x", FABLE, decider="always-host")
        with self.assertRaises(RuntimeError):
            asyncio.run(inside())

    def test_sync_decide_works_from_plain_code(self):
        d = decide_lib.decide("x", FABLE, tempfile.gettempdir(), decider="always-host", use_settings=False)
        self.assertFalse(d.route)

    def test_defaults_are_not_duplicated_in_the_decide_module(self):
        """No threshold, model id or price lives in decide.py: they all come from the shipped behavior."""
        text = (ROOT / "src/amplifier_fast_decisions/decide.py").read_text(encoding="utf-8")
        for needle in ("claude-sonnet-5", "300", "1.38", "1.11", "3000", "medium"):
            self.assertNotIn(needle, text.replace("Policy", ""), needle)


class ParityWithOrchestratorTests(unittest.TestCase):
    """decide == the orchestrator's turn-1 decision, on the recorded campaign and on the real scenario prompts."""

    # The shipped rule decider R* (no judge is asked) and the Jev opt-in (a fake judge answers).
    VARIANTS = (None, JUDGE_OPT_IN)

    def _assert_same(self, host, prompt, p_complex, files):
        reference = None
        for variant in self.VARIANTS:
            ref = asyncio.run(orchestrator_decision(host, prompt, FakeJudge(p_complex), files, variant))
            if variant is None:
                mine = decide_sync(prompt, host, files=files)
            else:
                mine = decide_sync(prompt, host, judge=FakeJudge(p_complex), files=files)
            got = {"tier": mine.tier, "reason": mine.reason, "model": mine.model, "effort": mine.effort}
            self.assertEqual(got, ref, f"{variant} {host} p={p_complex} files={files} prompt={prompt[:40]!r}")
            reference = reference or ref
        return reference

    @unittest.skipUnless((EVIDENCE / "campaign" / "decisions.jsonl").exists(), "main-v1 evidence not present")
    def test_all_280_recorded_waves(self):
        sessions = [json.loads(line) for line in (EVIDENCE / "data" / "sessions.jsonl").read_text(encoding="utf-8").splitlines() if line]
        stickies = {(s["scenario_id"], s["rep"], s["host"]): s for s in sessions if s["arm"] == "sticky"}
        decisions = [json.loads(line) for line in (EVIDENCE / "campaign" / "decisions.jsonl").read_text(encoding="utf-8").splitlines() if line]
        hosts = {"opus": OPUS, "fable": FABLE}
        seen = {"cheap": 0, "strong": 0}
        for d in decisions:
            files = stickies[(d["scenario"], d["rep"], d["host"])]["workspace_files"]
            ref = self._assert_same(hosts[d["host"]], "scripted turn", 0.1 if d["decision"] == "cheap" else 0.9, files)
            seen[ref["tier"]] += 1
        self.assertEqual(len(decisions), 280)
        self.assertGreater(seen["cheap"], 100)
        self.assertGreater(seen["strong"], 100)

    def test_turn_one_prompt_of_every_main_v1_scenario_on_both_hosts_and_both_workspace_sizes(self):
        prompts = []
        for path in sorted(SCENARIOS.rglob("*.yaml")):
            spec = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(spec, dict) and spec.get("turns"):
                prompts.append(spec["turns"][0]["prompt"])
        self.assertEqual(len(prompts), 70)
        limit = shipped()["model_routing"]["cheap_max_workspace_files"]
        routed = 0
        for prompt in prompts:
            p = 0.9 if hashlib.sha256(prompt.encode()).digest()[0] % 3 == 0 else 0.1
            for host in (OPUS, FABLE):
                for files in (limit - 1, limit + 1):
                    routed += self._assert_same(host, prompt, p, files)["tier"] == "cheap"
        self.assertGreater(routed, 20)   # the corpus exercises both outcomes, not only "host"


if __name__ == "__main__":
    unittest.main()
