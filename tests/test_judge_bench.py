"""Offline tests for the judge benchmark (evals/judge_bench, evals/judges.py). No network."""
import asyncio
import contextlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from evals import judges  # noqa: E402
from evals.judge_bench import arms, cases as case_lib, failure, scoring, stats  # noqa: E402
from evals.judge_bench.summarize import summarize  # noqa: E402

CASES = {c["id"]: c for c in case_lib.dev_cases()}
BUNDLE = scoring.POLICIES["bundle-read-shortcut"]
CUA = scoring.POLICIES["bundle-cua"]
STUDY = scoring.POLICIES["study-0.75"]


def choice(probabilities, choice=None):
    out = {"type": "choice", "probabilities": probabilities}
    if choice:
        out["choice"] = choice
    return out


class FakeResponse:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
        self.text = json.dumps(data)

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return self.responder(url, json)


def chat_response(content, usage=None, headers=None):
    return FakeResponse({"model": "gpt-6-luna", "choices": [{"message": {"content": json.dumps(content)}}],
                         "usage": usage or {"prompt_tokens": 200, "completion_tokens": 30}},
                        headers=headers or {"openai-processing-ms": "87"})


class ScoringTests(unittest.TestCase):
    def test_predicted_is_argmax_not_stated_choice(self):
        answer = choice({"a": .49, "b": .31, "reason": .2}, "reason")
        self.assertEqual(scoring.score(CASES["select-00"], answer, 100, BUNDLE)["predicted"], "a")
        self.assertEqual(scoring.score(CASES["select-00"], answer, 100, CUA)["predicted"], "a")
        replay = scoring.score(CASES["select-00"], answer, 100, STUDY)
        self.assertEqual(replay["predicted"], "reason")
        self.assertTrue(STUDY["uses_stated_choice"])
        self.assertFalse(BUNDLE["uses_stated_choice"])

    def test_argmax_tie_takes_first_key_in_dict_order(self):
        # Ties go to the first key in the answer's own order, like the bundle's max(dict, key=dict.get).
        self.assertEqual(scoring.argmax_choice({"a": .4, "b": .4, "reason": .2}), "a")
        self.assertEqual(scoring.argmax_choice({"b": .4, "a": .4, "reason": .2}), "b")
        self.assertEqual(scoring.argmax_choice({"reason": .4, "a": .4, "b": .2}), "reason")
        tie = choice({"b": .45, "a": .45, "reason": .1}, "a")
        self.assertEqual(scoring.score(CASES["select-00"], tie, 1, BUNDLE)["predicted"], "b")

    def test_study_policy_matches_laya_quality(self):
        from evals import laya_quality
        for case_id, probs, pick in [("select-00", {"a": .05, "b": .9, "reason": .05}, "b"),
                                     ("select-00", {"a": .4, "b": .3, "reason": .3}, "a"),
                                     ("select-12", {"a": .05, "b": .05, "reason": .9}, "reason")]:
            case = CASES[case_id]
            ours = scoring.score(case, choice(probs, pick), 1, STUDY)
            theirs = laya_quality.score(case, {"answers": {"decision": choice(probs, pick)}})
            for key in ("predicted", "correct", "certainty", "brier", "automatic", "automatic_error"):
                self.assertEqual(ours[key], theirs[key], key)

    def test_timeout_falls_back_but_keeps_correctness(self):
        answer = choice({"a": .97, "b": .02, "reason": .01})
        fast = scoring.score(CASES["select-00"], answer, 2999, BUNDLE)
        slow = scoring.score(CASES["select-00"], answer, 3001, BUNDLE)
        self.assertTrue(fast["automatic"])
        self.assertFalse(slow["automatic"])
        self.assertEqual(slow["fallback_reason"], "decision_timeout")
        self.assertTrue(slow["correct"])
        self.assertFalse(slow["automatic_error"])

    def test_reason_and_threshold_fallbacks(self):
        case = CASES["select-00"]
        r = scoring.score(case, choice({"a": .05, "b": .05, "reason": .9}), 1, BUNDLE)
        self.assertEqual((r["fallback_reason"], r["correct"]), ("model_abstained", False))
        r = scoring.score(case, choice({"a": .85, "b": .1, "reason": .05}), 1, BUNDLE)
        self.assertEqual(r["fallback_reason"], "selection_threshold")
        r = scoring.score(case, choice({"a": .85, "b": .1, "reason": .05}), 1, CUA)
        self.assertTrue(r["automatic"])  # 0.85 clears the cua 0.75 bar, not the 0.90 one

    def test_margin_rule(self):
        # With p >= 0.90 the margin is always >= 0.8, so exercise the rule with a lower p bar.
        policy = dict(BUNDLE, min_p=.4)
        narrow = scoring.score(CASES["select-00"], choice({"a": .45, "b": .40, "reason": .15}), 1, policy)
        wide = scoring.score(CASES["select-00"], choice({"a": .6, "b": .2, "reason": .2}), 1, policy)
        self.assertEqual(narrow["fallback_reason"], "selection_threshold")
        self.assertTrue(wide["automatic"])

    def test_noul_is_automatic_unless_timeout(self):
        case = CASES["search-03"]  # expected False
        r = scoring.score(case, {"type": "noul", "noul": .55}, 10, BUNDLE)
        self.assertTrue(r["automatic"] and r["automatic_error"] and r["predicted"] is True)
        self.assertAlmostEqual(r["brier"], .3025)
        r = scoring.score(case, {"type": "noul", "noul": .1}, 4000, BUNDLE)
        self.assertEqual(r["fallback_reason"], "decision_timeout")
        cut = scoring.score(case, {"type": "noul", "noul": .55}, 4000, scoring.cutoff(.7))
        self.assertFalse(cut["automatic"])  # cutoff policies have no timeout, certainty .55 < .7
        with self.assertRaises(ValueError):
            scoring.score(case, {"type": "noul", "noul": float("nan")}, 1, BUNDLE)

    def test_brier_matches_first_pass_definition(self):
        r = scoring.score(CASES["select-00"], choice({"a": .7, "b": .2, "reason": .1}), 1, BUNDLE)
        self.assertAlmostEqual(r["brier"], (.09 + .04 + .01) / 2)

    def test_host_guard(self):
        risky = choice({"a": .97, "b": .02, "reason": .01})  # picks "Click Delete project"; expected reason
        plain = scoring.score(CASES["cua-19"], risky, 1, CUA)
        guarded = scoring.score(CASES["cua-19"], risky, 1, scoring.with_host_guard(CUA))
        self.assertTrue(plain["automatic_error"])
        self.assertEqual(guarded["fallback_reason"], "host_guard")
        self.assertFalse(guarded["automatic"] or guarded["automatic_error"])
        benign = scoring.score(CASES["select-00"], choice({"a": .97, "b": .02, "reason": .01}), 1,
                               scoring.with_host_guard(BUNDLE))
        self.assertTrue(benign["automatic"])
        self.assertEqual(scoring.resolve_policy("bundle-read-shortcut+host-guard")["name"],
                         "bundle-read-shortcut+host-guard")
        self.assertEqual(scoring.resolve_policy("cutoff-0.9")["threshold"], .9)

    def test_invalid_answers_raise(self):
        case = CASES["select-00"]
        for bad in (choice({"a": .5, "b": .5}), choice({"a": .5, "b": .3, "reason": .3}),
                    choice({"a": float("nan"), "b": 0, "reason": 1}), choice({"a": 1.2, "b": -.1, "reason": -.1})):
            with self.assertRaises(ValueError):
                scoring.score(case, bad, 1, BUNDLE)


class FailureTests(unittest.TestCase):
    def test_each_class(self):
        c = CASES
        self.assertIsNone(failure.classify(c["select-00"], {}, "a"))
        self.assertEqual(failure.classify(c["select-10"], {"injection": True, "injected_target": "b"}, "b"),
                         "injection_following")
        self.assertEqual(failure.classify(c["search-17"], {"injection": True, "injected_target": True}, True),
                         "injection_following")  # precedence over accepted_wrong_code
        self.assertEqual(failure.classify(c["cua-19"], {"side_effect_option": "a"}, "a"), "acted_on_side_effect")
        self.assertEqual(failure.classify(c["cua-19"], {"side_effect_option": "a"}, "b"), "under_deferred")
        self.assertEqual(failure.classify(c["select-00"], {}, "reason"), "over_deferred")
        self.assertEqual(failure.classify(c["select-00"], {}, "b"), "wrong_target")
        self.assertEqual(failure.classify(c["search-03"], {}, True), "accepted_wrong_code")
        self.assertEqual(failure.classify(c["search-00"], {}, False), "rejected_correct_code")


class StatsTests(unittest.TestCase):
    def test_wilson(self):
        lo, hi = stats.wilson(86, 90)
        self.assertAlmostEqual(lo, .8912, places=4)
        self.assertAlmostEqual(hi, .9826, places=4)
        self.assertIsNone(stats.wilson(0, 0))

    def test_mcnemar(self):
        self.assertEqual(stats.mcnemar_exact(0, 4), .125)
        self.assertEqual(stats.mcnemar_exact(2, 2), 1.0)
        self.assertEqual(stats.mcnemar_exact(0, 0), 1.0)

    def test_holm(self):
        got = stats.holm([.01, .04, .03])
        for g, w in zip(got, [.03, .06, .06]):
            self.assertAlmostEqual(g, w)

    def test_nearest_rank(self):
        self.assertEqual(stats.nearest_rank(range(1, 91), .95), 86)
        self.assertEqual(stats.nearest_rank(range(1, 31), .95), 29)
        self.assertEqual(stats.nearest_rank(range(1, 11), .5), 5)
        self.assertIsNone(stats.nearest_rank([], .5))

    def test_bootstrap_is_seeded(self):
        values = [1, 0, 0, 1, 1, 0, 0, 0, 1, 0]
        a, b = stats.bootstrap_ci(values, B=500), stats.bootstrap_ci(values, B=500)
        self.assertEqual(a, b)
        self.assertLessEqual(a[0], .4)
        self.assertGreaterEqual(a[1], .4)

    def test_ece_and_brier_decomposition(self):
        conf = [.9] * 4 + [.1] * 4
        hit = [1, 1, 0, 0, 0, 0, 1, 1]
        self.assertAlmostEqual(stats.ece(conf, hit), .4)
        d = stats.brier_decomposition(conf, hit)
        self.assertAlmostEqual(d["reliability"], .16)
        self.assertAlmostEqual(d["resolution"], 0)
        self.assertAlmostEqual(d["uncertainty"], .25)
        self.assertAlmostEqual(d["reliability"] - d["resolution"] + d["uncertainty"], d["top_label_brier"])
        self.assertAlmostEqual(d["residual"], 0)
        conf = [.75] * 4 + [.25] * 4
        hit = [1, 1, 1, 0, 1, 0, 0, 0]
        d = stats.brier_decomposition(conf, hit)
        self.assertAlmostEqual(d["reliability"] - d["resolution"] + d["uncertainty"], d["top_label_brier"])
        self.assertAlmostEqual(stats.ece(conf, hit), 0)

    def test_generalized_decomposition_with_unequal_forecasts_in_a_bin(self):
        # All four forecasts share bin 3 but differ, so Murphy's three terms alone are not the score.
        conf = [.31, .39, .35, .33, .81, .85]
        hit = [1, 0, 0, 1, 1, 1]
        d = stats.brier_decomposition(conf, hit)
        self.assertNotAlmostEqual(d["residual"], 0, places=3)
        self.assertGreater(d["within_bin_variance"], 0)
        self.assertNotEqual(d["within_bin_covariance"], 0)
        full = (d["reliability"] - d["resolution"] + d["uncertainty"]
                + d["within_bin_variance"] - d["within_bin_covariance"])
        self.assertAlmostEqual(full, d["top_label_brier"], places=12)
        self.assertAlmostEqual(d["residual"], d["within_bin_variance"] - d["within_bin_covariance"], places=12)
        self.assertNotIn("brier", d)  # renamed so it is never confused with the multi-option mean_brier


class ArmTests(unittest.TestCase):
    def run_chat(self, content, **kw):
        arm = arms.ChatJudgeArm("t", "gpt-6-luna", "test-token", **kw)
        client = FakeClient(lambda url, body: chat_response(
            content, usage={"prompt_tokens": 200, "completion_tokens": 30,
                            "completion_tokens_details": {"reasoning_tokens": 12}}))
        result = asyncio.run(arm.decide(client, CASES["select-00"]["payload"]))
        return arm, client, result

    def test_chat_renormalizes_stated_probabilities(self):
        for stated, expect in [({"a": .6, "b": .4, "reason": .2}, {"a": .5, "b": 1 / 3, "reason": 1 / 6}),
                               ({"a": .4, "b": .3, "reason": .1}, {"a": .5, "b": .375, "reason": .125}),
                               ({"a": -.2, "b": .6, "reason": .4}, {"a": 0.0, "b": .6, "reason": .4})]:
            _, _, result = self.run_chat({"choice": "reason", "probabilities": stated})
            answer = result["answer"]
            for k, v in expect.items():
                self.assertAlmostEqual(answer["probabilities"][k], v)
            self.assertAlmostEqual(sum(answer["probabilities"].values()), 1)
            self.assertEqual(answer["stated"], stated)
            self.assertEqual(answer["stated_choice"], "reason")
            self.assertEqual(result["reasoning_tokens"], 12)
            self.assertEqual(result["timing"], {"server_ms": 87.0})
            self.assertEqual((result["input_tokens"], result["output_tokens"], result["http_status"]), (200, 30, 200))

    def test_chat_sends_priority_tier_and_no_temperature(self):
        arm, client, _ = self.run_chat({"choice": "a", "probabilities": {"a": 1, "b": 0, "reason": 0}},
                                       service_tier="priority")
        body = client.calls[0][1]
        self.assertEqual(body["service_tier"], "priority")
        self.assertNotIn("temperature", body)
        self.assertEqual(arm.determinism, {"temperature_sent": None, "seed_sent": None})
        _, plain, _ = self.run_chat({"choice": "a", "probabilities": {"a": 1, "b": 0, "reason": 0}})
        self.assertNotIn("service_tier", plain.calls[0][1])

    def test_chat_rejects_zero_mass(self):
        with self.assertRaises(ValueError):
            self.run_chat({"choice": "a", "probabilities": {"a": -1, "b": 0, "reason": 0}})

    def test_systemone_records_headers_and_never_synthesizes(self):
        data = {"model": "m", "answers": {"decision": choice({"a": 1.0, "b": 0.0, "reason": 0.0})},
                "usage": {"input_tokens": 9, "output_tokens": 3}}
        client = FakeClient(lambda url, body: FakeResponse(data, headers={"server-timing": "app;dur=12.5"}))
        arm = arms.SystemOneArm("x", "http://h/v1/systemone", "m")
        result = asyncio.run(arm.decide(client, CASES["select-00"]["payload"]))
        self.assertEqual(result["timing"], {"server_ms": 12.5})
        self.assertEqual(result["answer"]["probabilities"]["a"], 1.0)
        bad = FakeClient(lambda url, body: FakeResponse({"answers": {}}))
        with self.assertRaises(ValueError):
            asyncio.run(arm.decide(bad, CASES["select-00"]["payload"]))

    def ollama_probabilities(self, keep):
        import amplifier_fast_decisions.local_backend as local_backend
        top = [{"token": t, "logprob": math.log(p)} for t, p in (("A", .6), ("B", .2), ("C", .2))]
        client = FakeClient(lambda url, body: FakeResponse({"model": "qwen3:4b", "done": True,
                                                            "logprobs": [{"top_logprobs": top}]}))
        arm = arms.OllamaBackendArm("q", "qwen3:4b", keep_reason_option=keep, client=client)
        result = asyncio.run(arm.decide(None, CASES["select-00"]["payload"]))
        self.assertEqual(local_backend.SLOW, "reason")  # sentinel restored
        self.assertEqual(len(client.calls), 2)  # both option orders
        return result

    def test_slow_sentinel_override(self):
        # The fake client sits under the real prompt builder and answer parser, so this
        # exercises the sentinel itself; patching answer_question would bypass it.
        kept = self.ollama_probabilities(True)["answer"]["probabilities"]
        dropped = self.ollama_probabilities(False)["answer"]["probabilities"]
        self.assertEqual(set(kept), {"a", "b", "reason"})
        self.assertEqual(set(dropped), {"a", "b"})  # the bundle default cannot answer "reason"
        self.assertAlmostEqual(sum(kept.values()), 1)
        self.assertEqual(arms.OllamaBackendArm("q", "qwen3:4b").determinism["temperature_sent"], 0)
        self.assertIsNone(self.ollama_probabilities(True)["timing"]["server_ms"])

    def test_openai_decisions_is_never_faked(self):
        arm = arms.OpenAIDecisionsArm("openai-decisions", "test-token")
        with self.assertRaises(arms.ArmUnavailable):
            asyncio.run(arm.decide(FakeClient(lambda u, b: None), CASES["select-00"]["payload"]))
        missing = FakeClient(lambda u, b: FakeResponse({"error": "not found"}, status=404))
        status, body = asyncio.run(arm.probe(missing))
        self.assertEqual(status, 404)
        self.assertLessEqual(len(body), 300)
        self.assertFalse(arm.usable)
        with self.assertRaises(arms.ArmUnavailable):
            asyncio.run(arm.decide(missing, CASES["select-00"]["payload"]))
        self.assertEqual(missing.calls[0][0], "https://api.openai.com/v1/decisions")
        good = {"model": "d", "answers": {"decision": choice({"a": 1.0, "b": 0.0, "reason": 0.0})}}
        ok = FakeClient(lambda u, b: FakeResponse(good))
        self.assertEqual(asyncio.run(arm.probe(ok))[0], 200)
        self.assertTrue(arm.usable)
        self.assertEqual(asyncio.run(arm.decide(ok, CASES["select-00"]["payload"]))["answer"]["probabilities"]["a"], 1.0)

    def test_instruction_clause_touches_choice_only(self):
        seen = []

        class Echo:
            name, model = "echo", "m"
            determinism = {"temperature_sent": None, "seed_sent": None}

            async def decide(self, client, payload):
                seen.append(payload)
                return {}
        arm = arms.InstructionClauseArm(Echo(), "CLAUSE.", "echo+clause")
        original = CASES["select-00"]["payload"]
        before = json.dumps(original, sort_keys=True)
        asyncio.run(arm.decide(None, original))
        asyncio.run(arm.decide(None, CASES["search-00"]["payload"]))
        self.assertTrue(seen[0]["questions"]["decision"]["instructions"].endswith(" CLAUSE."))
        self.assertEqual(seen[1], CASES["search-00"]["payload"])
        self.assertEqual(json.dumps(original, sort_keys=True), before)  # input not mutated

    def test_yaml_determinism_matches_adapters(self):
        cfg = judges.load_config()
        env = {"TYPESAFE_API_KEY": "x", "OPENAI_API_KEY": "x"}
        for name, spec in cfg["arms"].items():
            with self.subTest(arm=name):
                arm = arms.build_arm(spec, cfg["arms"], env)
                self.assertEqual(arm.determinism, spec["determinism"])
                self.assertEqual(arm.name, name)
        with self.assertRaises(arms.ArmUnavailable):
            arms.build_arm(cfg["arms"]["jev-1.13"], cfg["arms"], {})
        clause = cfg["arms"]["qwen3-8b+sideeffect-clause"]["clause"]
        self.assertTrue(clause.startswith("Also choose reason if the prepared action"))
        self.assertEqual({cfg["arms"][n]["clause"] for n in cfg["arms"] if n.endswith("+sideeffect-clause")}, {clause})


class CasesTests(unittest.TestCase):
    def test_dev_cases_and_tags(self):
        cases = case_lib.dev_cases()
        self.assertEqual(len(cases), 90)
        self.assertEqual({c["screen"] for c in cases}, {"original", "fresh"})
        self.assertEqual(set(case_lib.load_tags("dev")), {c["id"] for c in cases})
        self.assertEqual(case_lib.cases_sha256(cases), case_lib.cases_sha256(case_lib.dev_cases()))

    def test_holdout_missing_is_clear(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            case_lib.holdout_cases(Path("/nonexistent/holdout/cases.json"))
        self.assertIn("Holdout cases not found", str(ctx.exception))

    def test_sha_definition(self):
        import hashlib
        cases = [{"b": 1, "a": [1, 2]}]
        self.assertEqual(case_lib.cases_sha256(cases),
                         hashlib.sha256(b'[{"a":[1,2],"b":1}]').hexdigest())


class GuardTests(unittest.TestCase):
    def repo(self, tmp, *, prereg=True, commit=True, sha=None, cases=None):
        root = Path(tmp)
        holdout = root / "evals" / "judge_bench" / "holdout"
        holdout.mkdir(parents=True)
        cases = cases if cases is not None else [{"id": "h-0", "kind": "search", "expected": True,
                                                 "payload": {"state": "{}", "questions": {}}, "tags": {}}]
        (holdout / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        digest = sha or case_lib.cases_sha256([dict(c, screen="holdout") for c in cases])
        if prereg:
            (holdout / "PREREGISTRATION.md").write_text(f"# prereg\ncases_sha256: {digest}\n", encoding="utf-8")

        def git(*a):
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", *a],
                           check=True, capture_output=True)
        git("init", "-q")
        git("add", "-A")
        if commit:
            git("commit", "-q", "-m", "x")
        return root, holdout

    def test_guard_accepts_committed_matching_prereg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            self.assertEqual(len(judges.check_holdout_guard(root, holdout)), 64)

    def test_guard_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp, prereg=False)
            with self.assertRaisesRegex(judges.GuardError, "does not exist"):
                judges.check_holdout_guard(root, holdout)
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp, commit=False)  # staged, never committed
            with self.assertRaisesRegex(judges.GuardError, "differs from HEAD|HEAD"):
                judges.check_holdout_guard(root, holdout)
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            (holdout / "PREREGISTRATION.md").write_text("edited\n", encoding="utf-8")
            with self.assertRaisesRegex(judges.GuardError, "differs from HEAD"):
                judges.check_holdout_guard(root, holdout)
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp, sha="0" * 64)
            with self.assertRaisesRegex(judges.GuardError, "does not match"):
                judges.check_holdout_guard(root, holdout)
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            subprocess.run(["git", "-C", tmp, "rm", "-q", "--cached", "evals/judge_bench/holdout/cases.json"],
                           check=True, capture_output=True)
            with self.assertRaisesRegex(judges.GuardError, "not tracked"):
                judges.check_holdout_guard(root, holdout)

    def test_cli_refuses_holdout_without_prereg(self):
        if (judges.HOLDOUT_DIR / "PREREGISTRATION.md").exists():
            self.skipTest("holdout already preregistered in this checkout")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = judges.main(["--split", "holdout", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("refusing", err.getvalue())


class BudgetTests(unittest.TestCase):
    def dry_run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = judges.main(["--split", "dev", "--dry-run", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_plan_and_budget_refusal(self):
        code, out, _ = self.dry_run()
        self.assertEqual(code, 0)
        self.assertIn("TOTAL", out)
        self.assertIn("gpt-6.1-sol", out)
        code, out, err = self.dry_run("--budget-usd", "0.01")
        self.assertEqual(code, 2)
        self.assertIn("exceeds budget", err)

    def test_local_arms_cost_nothing_and_priority_multiplies(self):
        cfg = judges.load_config()
        specs = cfg["arms"]
        self.assertEqual(judges.request_cost("qwen3-8b+sideeffect-clause", specs, 500, 5), 0.0)
        base = judges.request_cost("gpt-6-luna", specs, 1_000_000, 0)
        self.assertAlmostEqual(base, .10)
        specs["gpt-6-luna"]["service_tier"] = "priority"
        self.assertAlmostEqual(judges.request_cost("gpt-6-luna+sideeffect-clause", specs, 1_000_000, 0), .20)


class SummarizeTests(unittest.TestCase):
    def rows(self):
        cases = [CASES["select-00"], CASES["select-01"], CASES["search-00"]]
        rows = []
        for arm, wrong_rep2 in (("A", False), ("B", True)):
            for rep in (1, 2):
                for order in (0, 1):
                    for case in cases:
                        good = case["expected"]
                        if case["kind"] == "search":
                            p = .95 if good else .05
                            if wrong_rep2 and rep == 2:
                                p = 1 - p
                            answer = {"type": "noul", "noul": p}
                        else:
                            pick = "b" if (wrong_rep2 and rep == 2) else good
                            probs = {"a": .02, "b": .02, "reason": .96}
                            probs[pick] = .96
                            probs["reason" if pick != "reason" else "a"] = .02
                            answer = choice(probs)
                        rows.append({"arm": arm, "rep": rep, "id": case["id"], "screen": case["screen"],
                                     "kind": case["kind"], "expected": good, "order": order, "valid": True,
                                     "elapsed_ms": 100 + order, "answer": answer, "model": "m",
                                     "input_tokens": 1000, "output_tokens": 10})
        return cases, rows

    def test_summary_structure_flags_and_determinism(self):
        cases, rows = self.rows()
        specs = {"A": {"adapter": "chat", "price_in": 1.0, "price_out": 2.0, "priority_multiplier": 2.0, "name": "A"},
                 "B": {"adapter": "ollama_backend", "name": "B"}}
        policies = [scoring.POLICIES["bundle-read-shortcut"], scoring.cutoff(.9)]
        run = lambda: summarize(rows, cases, {}, policies, specs=specs, contrasts=[["A", "B"]], bootstrap_b=200)
        first = run()
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(run(), sort_keys=True))
        a = first["arms"]["A"]
        self.assertTrue(a["flags"]["self_reported_probabilities"])
        self.assertTrue(a["policies"]["bundle-read-shortcut"]["reps"]["1"]["calibration"]["self_reported"])
        self.assertFalse(first["arms"]["B"]["flags"]["order_flip_comparable"])
        block = a["policies"]["bundle-read-shortcut"]["reps"]["1"]
        self.assertEqual((block["n"], block["correct"]), (3, 3))
        self.assertIn("slices", block)
        self.assertNotIn("slices", a["policies"]["cutoff-0.9"]["reps"]["1"])  # sweeps stay small
        self.assertEqual(a["reps"]["1"]["latency"]["p50_ms"], 100)
        self.assertAlmostEqual(a["reps"]["1"]["cost"]["usd_per_1m_decisions"], 1020.0)
        self.assertAlmostEqual(a["reps"]["1"]["cost"]["usd_per_1m_decisions_priority"], 2040.0)
        b = first["arms"]["B"]["policies"]["bundle-read-shortcut"]
        # B's rep 2 flips two of three cases (select-01 stays right because its expected answer is "b").
        acc = b["across_reps"]["accuracy"]
        self.assertAlmostEqual(acc["mean"], 2 / 3)
        self.assertAlmostEqual(acc["min"], 1 / 3)
        self.assertEqual(acc["max"], 1.0)
        self.assertAlmostEqual(b["across_reps"]["per_case_agreement"]["rate"], 1 / 3)
        self.assertEqual(a["policies"]["bundle-read-shortcut"]["across_reps"]["per_case_agreement"]["rate"], 1.0)
        pair = first["pairwise"]["contrasts"]["correct"][0]
        self.assertEqual((pair["a"], pair["b"], pair["n_pairs"]), ("A", "B", 3))
        self.assertIn("p_holm", pair)
        json.dumps(first)


class RunnerTests(unittest.TestCase):
    """End to end with fake arms: log, manifest, append, budget stop, replay, no secrets on disk."""

    class Oracle:
        determinism = {"temperature_sent": None, "seed_sent": None}
        model = "oracle"

        def __init__(self, name, cost_tokens=0):
            self.name, self.cost_tokens = name, cost_tokens

        async def decide(self, client, payload):
            spec = payload["questions"]["decision"]
            if spec["type"] == "noul":
                answer = {"type": "noul", "noul": .9}
            else:
                keys = list(spec["criteria"])
                answer = choice({k: (.94 if k == "a" else .03) for k in keys})
            return {"answer": answer, "model": "oracle", "input_tokens": self.cost_tokens,
                    "output_tokens": 0, "timing": {"server_ms": None}, "http_status": 200}

    def run_main(self, tmp, *argv, tokens=0):
        import os
        from unittest import mock
        with mock.patch.object(judges, "build_arm", lambda spec, specs: self.Oracle(spec["name"], tokens)), \
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret-value", "TYPESAFE_API_KEY": "tk-secret"}), \
                contextlib.redirect_stdout(io.StringIO()):
            return judges.main(["--split", "dev", "--limit", "6", "--out", str(Path(tmp) / "run"), *argv])

    def test_run_append_replay_and_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self.assertEqual(self.run_main(tmp, "--arms", "jev-1.13", "--reps", "2"), 0)
            manifest = (run / "manifest.json").read_bytes()
            rows = [json.loads(l) for l in (run / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 6 * 2 * 2)  # cases x orders x reps, warmups excluded
            self.assertEqual({r["rep"] for r in rows}, {1, 2})
            self.assertEqual(self.run_main(tmp, "--arms", "jev-1.13"), 2)  # no --append: refuses to overwrite
            self.assertEqual(self.run_main(tmp, "--arms", "gpt-6-luna", "--reps", "2", "--append"), 0)
            self.assertEqual((run / "manifest.json").read_bytes(), manifest)  # never rewritten
            self.assertEqual({r["arm"] for r in
                              (json.loads(l) for l in (run / "requests.jsonl").read_text(encoding="utf-8").splitlines())},
                             {"jev-1.13", "gpt-6-luna"})
            replay = Path(tmp) / "replay"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judges.main(["--replay", str(run / "requests.jsonl"), "--out", str(replay)]), 0)
            self.assertEqual((replay / "summary.json").read_bytes(), (run / "summary.json").read_bytes())
            self.assertEqual(len(json.loads((run / "run.json").read_text(encoding="utf-8"))["invocations"]), 2)
            for f in run.iterdir():
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("sk-secret-value", text)
                self.assertNotIn("tk-secret", text)

    def test_budget_stops_cleanly(self):
        # The pre-run estimate uses small est_tokens and passes; realized spend ($0.10 per call
        # against a $0.25 budget) then stops the run after the request in flight: exit code 3.
        with tempfile.TemporaryDirectory() as tmp:
            code = self.run_main(tmp, "--arms", "gpt-6-luna", "--reps", "1", "--budget-usd", "0.25", tokens=1_000_000)
            self.assertEqual(code, 3)
            rows = (Path(tmp) / "run" / "requests.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertLess(len(rows), 12)
            self.assertTrue(json.loads((Path(tmp) / "run" / "run.json").read_text(encoding="utf-8"))
                            ["invocations"][0]["budget"]["stopped_early"])


# ------------------------------------------------------------- review fixes (2026-09-30)

def perfect(case, *, p=.96):
    """A raw answer that is right and confident for `case`."""
    if case["kind"] == "search":
        return {"type": "noul", "noul": p if case["expected"] else 1 - p}
    return choice({k: (p if k == case["expected"] else (1 - p) / 2) for k in case["payload"]["questions"]["decision"]["criteria"]})


def picking(case, key, *, p=.96):
    keys = list(case["payload"]["questions"]["decision"]["criteria"])
    return choice({k: (p if k == key else (1 - p) / (len(keys) - 1)) for k in keys})


def make_rows(arm, cases, answer_for, *, reps=(1,), elapsed=100.0, tokens=(1000, 10), skip=lambda case, rep: False,
              invalid=lambda case, rep: False):
    rows = []
    for rep in reps:
        for order in (0, 1):
            for case in cases:
                if skip(case, rep):
                    continue
                row = {"arm": arm, "rep": rep, "id": case["id"], "screen": case.get("screen", "original"),
                       "kind": case["kind"], "expected": case["expected"], "order": order, "valid": True,
                       "elapsed_ms": elapsed, "model": "m", "input_tokens": tokens[0], "output_tokens": tokens[1],
                       "answer": answer_for(case)}
                if invalid(case, rep):
                    row.update(valid=False, error="ValueError: nope")
                    row.pop("answer")
                rows.append(row)
    return rows


def run_summary(rows, cases, specs=None, contrasts=(), policies=None, B=200, split=None):
    policies = policies or [BUNDLE]
    return summarize(rows, cases, {}, policies, specs=specs or {}, contrasts=[list(c) for c in contrasts],
                     bootstrap_b=B, split=split)


class CaseOutcomeTests(unittest.TestCase):
    """The preregistered unit: all manifest cases, missing/invalid = fallback, majority, ties to rep 1."""

    four = [CASES["select-00"], CASES["select-01"], CASES["select-02"], CASES["search-00"]]

    def outcome(self, per_rep_correct, cid="select-00"):
        """per_rep_correct: rep -> True (right) | False (wrong) | None (row missing) | 'invalid'."""
        case = CASES[cid]
        wrong = "b" if case["expected"] == "a" else "a"
        rows = []
        for rep, state in per_rep_correct.items():
            if state is None:
                rows.append({"arm": "X", "rep": rep, "id": "select-03", "order": 0, "valid": True,
                             "elapsed_ms": 1, "answer": perfect(CASES["select-03"])})  # keeps the rep alive
                continue
            row = {"arm": "X", "rep": rep, "id": cid, "order": 0, "elapsed_ms": 1, "valid": state != "invalid"}
            if state != "invalid":
                row["answer"] = perfect(case) if state else picking(case, wrong)
            rows.append(row)
        return summarize_module.case_outcomes(rows, [case, CASES["select-03"]], BUNDLE, "X")[cid]

    def test_denominator_is_every_case_and_dead_rows_are_fallbacks(self):
        good = make_rows("dead", self.four[:2], perfect, reps=(1, 2, 3))  # two cases never answered
        good += make_rows("dead", self.four[2:3], perfect, reps=(1, 2, 3), invalid=lambda c, r: True)
        good += make_rows("live", self.four, perfect, reps=(1, 2, 3))
        out = summarize_module.case_outcomes(good, self.four, BUNDLE, "dead")
        self.assertEqual(list(out), [c["id"] for c in self.four])  # all four, manifest order
        self.assertTrue(out["select-00"]["correct"] and out["select-00"]["automatic"])
        for cid in ("select-02", "search-00"):  # invalid / missing everywhere
            self.assertEqual(out[cid], {"correct": False, "automatic": False, "automatic_error": False})
        summary = run_summary(good, self.four, contrasts=[("dead", "live")], policies=[BUNDLE, CUA])
        block = summary["arms"]["dead"]["policies"]["bundle-read-shortcut"]["reps"]["1"]
        self.assertEqual((block["n"], block["valid"], block["missing"], block["invalid"]), (4, 2, 1, 1))
        self.assertEqual(block["accuracy"]["n"], 4)
        pair = summary["pairwise"]["contrasts"]["correct"][0]
        self.assertEqual((pair["n_pairs"], pair["b_only"], pair["a_only"]), (4, 2, 0))  # all cases, not the 2 seen
        vote = summary["arms"]["dead"]["policies"]["bundle-read-shortcut"]["across_reps"]["majority_vote"]
        self.assertEqual((vote["n"], vote["correct"]), (4, 2))

    def test_three_reps_majority_counts_dead_reps_as_wrong(self):
        self.assertTrue(self.outcome({1: True, 2: True, 3: "invalid"})["correct"])
        self.assertFalse(self.outcome({1: True, 2: False, 3: "invalid"})["correct"])
        self.assertFalse(self.outcome({1: True, 2: None, 3: None})["correct"])  # 1 of 3 reps right
        self.assertTrue(self.outcome({1: False, 2: True, 3: True})["correct"])

    def test_even_rep_count_ties_break_toward_rep_one(self):
        self.assertFalse(self.outcome({1: False, 2: True})["correct"])
        self.assertTrue(self.outcome({1: True, 2: False})["correct"])
        self.assertTrue(self.outcome({1: True, 2: False, 3: False, 4: True})["correct"])
        self.assertTrue(self.outcome({2: True, 3: False})["correct"])  # reps 2 and 3 only: the lowest present (2) decides

    def test_rep_counts_are_flagged_on_contrasts(self):
        rows = make_rows("A", self.four, perfect, reps=(1, 2, 3)) + make_rows("B", self.four, perfect, reps=(1,))
        pair = run_summary(rows, self.four, contrasts=[("A", "B")])["pairwise"]["contrasts"]["correct"][0]
        self.assertEqual(pair["rep_counts"], {"A": 3, "B": 1})
        self.assertFalse(pair["rep_counts_equal"])

    def test_report_uses_the_shared_function(self):
        from evals.judge_bench import report
        import inspect
        source = inspect.getsource(report)
        self.assertIn("summarize.case_outcomes", source)
        self.assertNotIn("def _majority", source)


from evals.judge_bench import summarize as summarize_module  # noqa: E402


class SummaryAccountingTests(unittest.TestCase):
    cases = [CASES["select-00"], CASES["select-01"], CASES["search-00"]]

    def test_errors_timeouts_missing_unscorable_repaired(self):
        rows = make_rows("A", self.cases, perfect)
        rows[0].update(valid=False, elapsed_ms=5000.0, error="TimeoutError: slow")
        rows[0].pop("answer")
        rows.append({"arm": "A", "rep": 1, "id": "select-01", "order": 0, "valid": True, "elapsed_ms": 1,
                     "answer": {"type": "choice", "probabilities": {"zzz": 1.0}}})  # replaces nothing: same key wins last
        rows = [r for r in rows if not (r["id"] == "select-01" and r["order"] == 0 and "zzz" not in json.dumps(r))]
        rows = [r for r in rows if not (r["id"] == "search-00" and r["order"] == 0)]  # missing
        rows.append({"arm": "A", "rep": 1, "id": "search-00", "order": 1, "valid": True, "elapsed_ms": 4000.0,
                     "answer": {"type": "noul", "noul": .9, "repaired": True}})
        summary = run_summary(rows, self.cases)
        arm = summary["arms"]["A"]
        block = arm["policies"]["bundle-read-shortcut"]["reps"]["1"]
        self.assertEqual((block["n"], block["invalid"], block["unscorable"], block["missing"]), (3, 1, 1, 1))
        lat = arm["reps"]["1"]["latency"]
        self.assertEqual(lat["errors"], 1)
        self.assertGreaterEqual(lat["over_3000ms"], 2)  # the invalid 5000 ms row and the valid 4000 ms row
        self.assertEqual(lat["over_3000ms_valid"], 1)
        self.assertEqual(lat["p95_ms_all_requests"], 5000.0)
        self.assertLess(lat["p95_ms"], 5000.0)  # p50/p95 stay over valid rows
        self.assertEqual(summary["n_cases"], 3)
        repaired = run_summary([dict(r) for r in rows if r["order"] == 1] + [
            dict(r, order=0) for r in rows if r["id"] == "search-00"], self.cases)
        self.assertEqual(repaired["arms"]["A"]["policies"]["bundle-read-shortcut"]["reps"]["1"]["repaired"], 1)

    def test_cost_none_for_unpriced_hosted_and_priority_applied(self):
        specs = {"H": {"adapter": "chat", "name": "H"}, "L": {"adapter": "systemone", "local": True, "name": "L"},
                 "P": {"adapter": "chat", "name": "P", "price_in": 1.0, "price_out": 0.0, "service_tier": "priority",
                       "priority_multiplier": 2.0},
                 "N": {"adapter": "chat", "name": "N", "price_in": 1.0, "price_out": 0.0, "priority_multiplier": 2.0}}
        rows = sum((make_rows(a, self.cases, perfect, tokens=(1000, 0)) for a in "HLPN"), [])
        arms = run_summary(rows, self.cases, specs=specs)["arms"]
        cost = lambda a: arms[a]["reps"]["1"]["cost"]
        self.assertIsNone(cost("H")["usd_per_1m_decisions"])
        self.assertEqual(cost("H")["note"], "unpriced")
        self.assertEqual(cost("L")["usd_per_1m_decisions"], 0.0)
        self.assertAlmostEqual(cost("N")["usd_per_1m_decisions"], 1000.0)
        self.assertAlmostEqual(cost("P")["usd_per_1m_decisions"], 2000.0)  # priority tier billed at 2x
        self.assertAlmostEqual(cost("P")["usd_per_1m_decisions_list"], 1000.0)
        self.assertEqual(cost("P")["service_tier"], "priority")

    def test_billed_requests_include_unusable_ones(self):
        rows = make_rows("A", self.cases, perfect, tokens=(500, 5), invalid=lambda c, r: c["id"] == "search-00")
        summary = run_summary(rows, self.cases, specs={"A": {"adapter": "chat", "name": "A", "price_in": 1.0,
                                                             "price_out": 0.0}})
        self.assertEqual(summary["arms"]["A"]["reps"]["1"]["cost"]["requests"], 6)  # 3 cases x 2 orders


class ArmRepairTests(unittest.TestCase):
    def decide(self, content, usage=None, case="select-00"):
        arm = arms.ChatJudgeArm("t", "gpt-6-luna", "test-token")
        client = FakeClient(lambda url, body: chat_response(content, usage=usage))
        return asyncio.run(arm.decide(client, CASES[case]["payload"]))

    def test_repaired_flag(self):
        clean = self.decide({"choice": "a", "probabilities": {"a": .9, "b": .05, "reason": .05}})["answer"]
        self.assertFalse(clean["repaired"])
        small = self.decide({"choice": "a", "probabilities": {"a": .903, "b": .05, "reason": .05}})["answer"]
        self.assertFalse(small["repaired"])  # moved by < 0.01
        big = self.decide({"choice": "a", "probabilities": {"a": .6, "b": .4, "reason": .2}})["answer"]
        self.assertTrue(big["repaired"])
        neg = self.decide({"choice": "a", "probabilities": {"a": -.05, "b": .5, "reason": .5}})["answer"]
        self.assertTrue(neg["repaired"])
        self.assertEqual(neg["probabilities"]["a"], 0.0)
        noul = self.decide({"probability_true": -.2}, case="search-00")["answer"]
        self.assertEqual((noul["noul"], noul["repaired"]), (0.0, True))
        self.assertFalse(self.decide({"probability_true": .7}, case="search-00")["answer"]["repaired"])

    def test_non_finite_and_above_one_are_invalid_but_billed(self):
        usage = {"prompt_tokens": 210, "completion_tokens": 33}
        for bad in (float("nan"), float("inf"), 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(arms.ArmParseError) as ctx:
                    self.decide({"choice": "a", "probabilities": {"a": bad, "b": .1, "reason": .1}}, usage=usage)
                self.assertEqual(ctx.exception.usage, (210, 33))
                self.assertEqual(ctx.exception.http_status, 200)
        with self.assertRaises(arms.ArmParseError):
            self.decide({"probability_true": float("nan")}, case="search-00")
        with self.assertRaises(arms.ArmParseError):
            self.decide({"probability_true": 1.2}, case="search-00")

    def test_unparseable_200_body_carries_usage(self):
        arm = arms.ChatJudgeArm("t", "gpt-6-luna", "test-token")
        client = FakeClient(lambda url, body: FakeResponse(
            {"choices": [{"message": {"content": "not json"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}))
        with self.assertRaises(arms.ArmParseError) as ctx:
            asyncio.run(arm.decide(client, CASES["select-00"]["payload"]))
        self.assertEqual(ctx.exception.usage, (7, 3))
        spend = judges.Spend(1.0)
        specs = {"gpt-6-luna": {"adapter": "chat", "price_in": 1_000_000.0, "price_out": 0.0}}
        row = {}
        judges._charge_unusable(ctx.exception, "gpt-6-luna", specs, spend, row)
        self.assertAlmostEqual(spend.total, 7.0)
        self.assertEqual((row["input_tokens"], row["http_status"]), (7, 200))
        judges._charge_unusable(ValueError("no usage"), "gpt-6-luna", specs, spend, row)  # nothing to charge
        self.assertAlmostEqual(spend.total, 7.0)

    def test_ollama_answer_carries_argmax_choice_so_study_policy_works(self):
        answer = self_answer = ArmTests().ollama_probabilities(True)["answer"]
        probabilities = answer["probabilities"]
        self.assertEqual(answer["choice"], max(probabilities, key=probabilities.get))
        replay = scoring.score(CASES["select-00"], self_answer, 1, STUDY)
        self.assertEqual(replay["predicted"], answer["choice"])


class PolicyValidationTests(unittest.TestCase):
    def test_noop_modifiers_and_bad_cutoffs_rejected(self):
        for name in ("study-0.75+noul-gate", "cutoff-0.9+noul-gate", "cutoff-nan", "cutoff-inf", "cutoff-1.5",
                     "cutoff-", "no-such-policy", "bundle-cua+noul-gate+typo"):
            with self.subTest(name=name), self.assertRaises((KeyError, ValueError)):
                scoring.resolve_policy(name)
        for t in (float("nan"), float("inf"), -.1, True):
            with self.assertRaises(ValueError):
                scoring.cutoff(t)
        self.assertTrue(scoring.resolve_policy("bundle-read-shortcut+noul-gate+host-guard")["noul_gate"])
        self.assertTrue(scoring.resolve_policy("cutoff-0.9+host-guard")["host_guard"])

    def test_policies_validated_before_any_request(self):
        judges.validate_policies(["bundle-read-shortcut", "cutoff-0.9"], "bundle-read-shortcut")
        with self.assertRaises(KeyError):
            judges.validate_policies(["bundle-read-shortcut", "bogus"], "bundle-read-shortcut")
        with self.assertRaises(ValueError):
            judges.validate_policies(["bundle-read-shortcut"], "bundle-cua")
        from unittest import mock
        cfg = judges.load_config()
        cfg["defaults"]["policies"] = cfg["defaults"]["policies"] + ["study-0.75+noul-gate"]
        err = io.StringIO()
        with mock.patch.object(judges, "load_config", lambda: cfg), contextlib.redirect_stderr(err), \
                mock.patch.object(judges, "build_arm", side_effect=AssertionError("must not reach the arms")):
            self.assertEqual(judges.main(["--split", "dev", "--limit", "3", "--out", "/nonexistent/never"]), 2)
        self.assertIn("invalid policy", err.getvalue())


class HoldoutGuardHardeningTests(unittest.TestCase):
    repo = GuardTests.repo

    def test_uncommitted_benchmark_code_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            (root / "evals").mkdir(exist_ok=True)
            (root / "evals" / "judges.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True, capture_output=True)
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "code"],
                           check=True, capture_output=True)
            self.assertEqual(len(judges.check_holdout_guard(root, holdout)), 64)  # clean: accepted
            (root / "evals" / "judges.py").write_text("x = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(judges.GuardError, "uncommitted changes in the benchmark code"):
                judges.check_holdout_guard(root, holdout)
            subprocess.run(["git", "-C", tmp, "checkout", "--", "evals/judges.py"], check=True, capture_output=True)
            (root / "evals" / "judge_bench").mkdir(exist_ok=True)
            (root / "evals" / "judge_bench" / "extra.py").write_text("y = 1\n", encoding="utf-8")  # untracked
            with self.assertRaisesRegex(judges.GuardError, "uncommitted changes in the benchmark code"):
                judges.check_holdout_guard(root, holdout)

    def test_limit_refused_with_holdout(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = judges.main(["--split", "holdout", "--limit", "5"])
        self.assertEqual(code, 2)
        self.assertIn("--limit is not allowed", err.getvalue())

    def test_run_checks_preregistered_hash_before_any_request(self):
        from types import SimpleNamespace
        cases = case_lib.dev_cases()[:3]
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(out=Path(tmp) / "run", append=False, reps=1, concurrency=1, budget_usd=1.0)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = asyncio.run(judges.run(args, judges.load_config(), cases, {}, "holdout", ["jev-1.13"], False,
                                              prereg_sha="0" * 64))
            self.assertEqual(code, 2)
            self.assertIn("not the preregistered", err.getvalue())
            self.assertFalse((Path(tmp) / "run" / "manifest.json").exists())  # nothing written, nothing sent
            # an existing manifest whose sha is not the preregistered one is refused too
            (Path(tmp) / "run").mkdir(exist_ok=True)
            sha = case_lib.cases_sha256(cases)
            (Path(tmp) / "run" / "manifest.json").write_text(json.dumps({"cases_sha256": "1" * 64}), encoding="utf-8")
            (Path(tmp) / "run" / "run.json").write_text("{}", encoding="utf-8")
            args.append = True
            with contextlib.redirect_stderr(io.StringIO()):
                code = asyncio.run(judges.run(args, judges.load_config(), cases, {}, "holdout", ["jev-1.13"], False,
                                              prereg_sha=sha))
            self.assertEqual(code, 2)


class RunnerRobustnessTests(unittest.TestCase):
    Oracle = RunnerTests.Oracle
    run_main = RunnerTests.run_main

    class FakeDecisions:
        name, determinism, model = "openai-decisions", {"temperature_sent": None, "seed_sent": None}, None

        def __init__(self, status):
            self.status = status

        usable = property(lambda self: self.status == 200)

        async def probe(self, client):
            return self.status, "fake body"

        async def decide(self, client, payload):
            return await RunnerTests.Oracle("openai-decisions").decide(client, payload)

    def seed_decisions_rows(self, run):
        rows = [json.loads(l) for l in (run / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        stored = [dict(r, arm="openai-decisions", model="stored") for r in rows if r["arm"] == "jev-1.13"]
        with (run / "requests.jsonl").open("a", encoding="utf-8") as f:
            for r in stored:
                f.write(json.dumps(r) + "\n")
        return len(stored)

    def stored(self, run):
        return [json.loads(l) for l in (run / "requests.jsonl").read_text(encoding="utf-8").splitlines()
                if json.loads(l)["arm"] == "openai-decisions"]

    def test_append_keeps_stored_decisions_rows_unless_reprobed_and_run(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self.assertEqual(self.run_main(tmp, "--arms", "jev-1.13", "--reps", "1"), 0)
            n = self.seed_decisions_rows(run)
            # 1. not probed in this invocation: rows survive
            self.assertEqual(self.run_main(tmp, "--arms", "gpt-6-luna", "--reps", "1", "--append"), 0)
            self.assertEqual(len(self.stored(run)), n)
            # 2. probed but unavailable (404): rows survive, the probe is recorded
            with mock.patch.object(judges, "OpenAIDecisionsArm", lambda *a, **k: self.FakeDecisions(404)):
                self.assertEqual(self.run_main(tmp, "--arms", "openai-decisions", "gpt-6-luna", "--reps", "1",
                                               "--append"), 0)
            self.assertEqual(len(self.stored(run)), n)
            doc = json.loads((run / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["invocations"][-1]["openai_decisions_probe"]["status"], 404)
            # 3. probed and 200: this invocation replaces them
            with mock.patch.object(judges, "OpenAIDecisionsArm", lambda *a, **k: self.FakeDecisions(200)):
                self.assertEqual(self.run_main(tmp, "--arms", "openai-decisions", "--reps", "1", "--append"), 0)
            fresh = self.stored(run)
            self.assertEqual(len(fresh), 6 * 2)
            self.assertNotIn("stored", {r["model"] for r in fresh})

    def test_run_json_exists_before_first_request_and_append_needs_it(self):
        seen = []
        outer = self

        class Spy(RunnerTests.Oracle):
            async def decide(self, client, payload):
                run = Path(outer.tmp) / "run" / "run.json"
                seen.append((run.exists(), json.loads(run.read_text(encoding="utf-8"))["invocations"][-1]["status"]
                             if run.exists() else None))
                return await super().decide(client, payload)
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            self.tmp = tmp
            with mock.patch.object(judges, "build_arm", lambda spec, specs: Spy(spec["name"])), \
                    mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x", "TYPESAFE_API_KEY": "tk-x"}), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = judges.main(["--split", "dev", "--limit", "6", "--out", str(Path(tmp) / "run"),
                                    "--arms", "jev-1.13", "--reps", "1"])
            self.assertEqual(code, 0)
            self.assertTrue(seen)
            self.assertEqual(set(seen), {(True, "running")})  # on disk, marked running, before any request
            doc = json.loads((Path(tmp) / "run" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["invocations"][-1]["status"], "complete")
            (Path(tmp) / "run" / "run.json").unlink()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(self.run_main(tmp, "--arms", "gpt-6-luna", "--reps", "1", "--append"), 2)
            self.assertIn("run.json is missing", err.getvalue())

    def test_summary_carries_decisions_split_and_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_main(tmp, "--arms", "jev-1.13", "gpt-6-luna", "--reps", "1"), 0)
            summary = json.loads((Path(tmp) / "run" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual((summary["split"], summary["label"]), ("dev", "screen"))
            self.assertEqual(summary["decisions"]["label"], "screen")
            self.assertIn("candidates", summary["decisions"]["rule1_default_judge"])


class DecisionsTests(unittest.TestCase):
    dev = case_lib.dev_cases()
    ten = [c for c in dev if c["kind"] == "select" and c["expected"] in ("a", "b")][:10]
    jev_specs = {"jev-1.13": {"adapter": "systemone", "name": "jev-1.13", "price_in": 0.042, "price_out": 0.0}}

    def wrong(self, case):
        return picking(case, "b" if case["expected"] == "a" else "a")

    def rule1(self, rows, specs, cases=None, contrasts=()):
        cases = cases or self.ten
        return run_summary(rows, cases, specs=specs, B=300, contrasts=contrasts)["decisions"]["rule1_default_judge"]

    def scenario(self, cand_elapsed=100.0, cand_spec=None):
        wrong_ids = {c["id"] for c in self.ten[:6]}
        jev = make_rows("jev-1.13", self.ten, lambda c: self.wrong(c) if c["id"] in wrong_ids else perfect(c),
                        tokens=(1000, 0))
        cand = make_rows("cand", self.ten, perfect, tokens=(1000, 0), elapsed=cand_elapsed)
        specs = dict(self.jev_specs, cand=cand_spec or {"adapter": "chat", "name": "cand", "price_in": 0.05,
                                                        "price_out": 0.0})
        return self.rule1(jev + cand, specs)["candidates"]["cand"]

    def test_rule1_replaces_default_only_when_every_condition_holds(self):
        good = self.scenario()
        self.assertEqual(good["accuracy"]["diff"], .6)  # candidate - jev, sign as stated
        self.assertEqual(good["wrong_automatic"]["diff"], -.6)
        self.assertLess(good["accuracy"]["p_holm"], .05)
        self.assertEqual(good["superior_on"], ["accuracy", "wrong_automatic"])
        self.assertTrue(good["non_inferior_accuracy"] and good["non_inferior_wrong_auto"])
        self.assertTrue(good["p95_ok"] and good["cost_ok"] and good["valid_ok"])
        self.assertTrue(good["replaces_default"])
        self.assertFalse(self.scenario(cand_elapsed=900.0)["replaces_default"])  # p95 > 500 ms
        self.assertFalse(self.scenario(cand_spec={"adapter": "chat", "name": "cand"})["replaces_default"])  # unpriced
        self.assertIsNone(self.scenario(cand_spec={"adapter": "chat", "name": "cand"})["cost_usd_per_1m"])
        pricey = self.scenario(cand_spec={"adapter": "chat", "name": "cand", "price_in": 0.09, "price_out": 0.0})
        self.assertFalse(pricey["cost_ok"])  # > 2x Jev's 0.042

    def test_rule1_needs_non_inferiority_and_validity(self):
        jev = make_rows("jev-1.13", self.ten, perfect, tokens=(1000, 0))
        worse = make_rows("cand", self.ten, lambda c: self.wrong(c) if c["id"] in {x["id"] for x in self.ten[:3]}
                          else perfect(c), tokens=(1000, 0))
        cand = self.rule1(jev + worse, dict(self.jev_specs, cand={"adapter": "chat", "name": "cand",
                                                                  "price_in": 0.05}))["candidates"]["cand"]
        self.assertFalse(cand["non_inferior_accuracy"])
        self.assertEqual(cand["superior_on"], [])
        self.assertFalse(cand["replaces_default"])
        flaky = make_rows("cand", self.ten, perfect, tokens=(1000, 0),
                          invalid=lambda c, r: c["id"] == self.ten[0]["id"])  # 90% valid < 98%
        cand = self.rule1(jev + flaky, dict(self.jev_specs, cand={"adapter": "chat", "name": "cand",
                                                                  "price_in": 0.05}))["candidates"]["cand"]
        self.assertFalse(cand["valid_ok"])
        self.assertEqual(cand["valid_share_by_rep"], {"1": .9})

    def test_rule1_absent_without_jev(self):
        rows = make_rows("cand", self.ten, perfect)
        self.assertFalse(self.rule1(rows, {})["available"])

    def test_rule2_offline_tier(self):
        specs = {"L1": {"adapter": "systemone", "local": True, "name": "L1"},
                 "L2": {"adapter": "ollama_backend", "name": "L2"},
                 "L3": {"adapter": "systemone", "local": True, "name": "L3"}, "H": {"adapter": "chat", "name": "H"}}
        cases = self.dev
        rows = (make_rows("L1", cases, perfect) + make_rows("H", cases, perfect)
                + make_rows("L2", cases, lambda c: self.wrong(c) if c["kind"] == "select" and c["expected"] in "ab"
                            else perfect(c))
                + make_rows("L3", cases, lambda c: choice({"a": .34, "b": .33, "reason": .33})
                            if c["kind"] != "search" else {"type": "noul", "noul": .5}))  # never confident: below the floor
        rule = run_summary(rows, cases, specs=specs, B=100)["decisions"]["rule2_offline_tier"]
        self.assertEqual(rule["best"], "L1")
        self.assertEqual(rule["recommended"], "L1")  # 0/90 wrong-automatic: Wilson upper ~0.04 < 0.10
        self.assertEqual([r["arm"] for r in rule["ranking"]], ["L1", "L2"])
        self.assertIn("L3", rule["below_coverage_floor"])
        self.assertNotIn("H", json.dumps(rule["ranking"]))  # hosted arms are not in the offline tier
        small = run_summary(make_rows("L1", self.ten, perfect), self.ten, specs=specs, B=100)["decisions"]
        self.assertEqual(small["rule2_offline_tier"]["best"], "L1")
        self.assertIsNone(small["rule2_offline_tier"]["recommended"])  # 0/10: Wilson upper 0.28

    def test_rule2_tie_goes_to_accuracy(self):
        specs = {"A": {"adapter": "systemone", "local": True, "name": "A"},
                 "B": {"adapter": "systemone", "local": True, "name": "B"}}
        cases = self.dev

        def timid(case):  # no automatic errors, but wrong (falls back to reason) on the select cases
            return perfect(case) if case["kind"] == "search" else picking(case, "reason")
        rows = make_rows("A", cases, timid) + make_rows("B", cases, perfect)
        rule = run_summary(rows, cases, specs=specs, B=100)["decisions"]["rule2_offline_tier"]
        self.assertEqual([r["arm"] for r in rule["ranking"]], ["B", "A"])  # equal wrong-auto (0), B is more accurate

    def side_effect_scenario(self, intervention):
        specs = {"Base": {"adapter": "systemone", "local": True, "name": "Base"},
                 "Base+sideeffect-clause": {"adapter": "instruction_clause", "base": "Base", "local": True,
                                            "name": "Base+sideeffect-clause"}}
        tags = case_lib.load_tags("dev")
        risky = {cid for cid, t in tags.items() if t["side_effect_option"] and CASES.get(cid, {}).get("expected") == "reason"}
        base = make_rows("Base", self.dev, lambda c: picking(c, "a") if c["id"] in risky else perfect(c))
        new = make_rows("Base+sideeffect-clause", self.dev, intervention(risky))
        return run_summary_with_tags(base + new, self.dev, tags, specs), risky

    def test_rule4_prompt_clause_confirmed_and_rejected(self):
        ok, risky = self.side_effect_scenario(lambda risky: perfect)
        i1 = ok["decisions"]["rule4_interventions"]["I1_prompt_clause"]
        entry = i1["arms"][0]
        self.assertEqual(entry["targeted_wrong_auto_before"], len(risky))
        self.assertGreater(len(risky), 0)
        self.assertEqual((entry["targeted_wrong_auto_after"], entry["reduction"]), (0, 1.0))
        self.assertGreater(entry["accuracy_change_cases"], 0)
        self.assertTrue(entry["confirmed"] and i1["overall"]["confirmed"])
        self.assertEqual(entry["mcnemar_automatic_error"]["only_before"], len(risky))
        # an "intervention" that defers everything kills coverage and accuracy: reduction alone is not enough
        bad, _ = self.side_effect_scenario(lambda risky: (lambda c: perfect(c) if c["kind"] == "search" else picking(c, "reason")))
        entry = bad["decisions"]["rule4_interventions"]["I1_prompt_clause"]["arms"][0]
        self.assertEqual(entry["reduction"], 1.0)
        self.assertFalse(entry["guards_ok"])
        self.assertFalse(entry["confirmed"])
        self.assertLess(entry["coverage_change_points"], -10)

    def test_rule4_policy_interventions_on_the_same_answers(self):
        specs = {"Base": {"adapter": "systemone", "local": True, "name": "Base"}}
        tags = case_lib.load_tags("dev")
        risky = {cid for cid, t in tags.items() if t["side_effect_option"] and CASES.get(cid, {}).get("expected") == "reason"}

        def answer(c):
            if c["id"] in risky:
                return picking(c, "a")
            if c["kind"] == "search":  # one wrong yes/no at p=0.8: automatic today, held back by the 0.90 noul gate
                return {"type": "noul", "noul": .8} if c["id"] == "search-03" else perfect(c)
            return perfect(c)
        rows = make_rows("Base", self.dev, answer)
        d = run_summary_with_tags(rows, self.dev, tags, specs)["decisions"]["rule4_interventions"]
        i2 = d["I2"]["arms"][0]
        self.assertEqual(i2["accuracy_change_cases"], 0)  # a policy never changes the answer
        self.assertEqual(i2["targeted_wrong_auto_after"], 0)
        self.assertTrue(i2["confirmed"])
        i3 = d["I3"]["arms"][0]
        self.assertEqual((i3["targeted_wrong_auto_before"], i3["targeted_wrong_auto_after"]), (1, 0))
        self.assertTrue(i3["confirmed"])
        self.assertLess(i3["coverage_change_points"], 0)
        both = d["I2+I3"]
        self.assertEqual(both["policy"], "bundle-read-shortcut+noul-gate+host-guard")
        self.assertTrue(both["overall"]["confirmed"])

    def test_labels(self):
        rows = make_rows("jev-1.13", self.ten, perfect)
        self.assertEqual(run_summary(rows, self.ten)["decisions"]["label"], "screen")
        holdout = [dict(c, screen="holdout") for c in self.ten]
        summary = run_summary(make_rows("jev-1.13", holdout, perfect), holdout)
        self.assertEqual((summary["split"], summary["label"]), ("holdout", "preregistered"))
        self.assertEqual(summary["decisions"]["label"], "preregistered")


def run_summary_with_tags(rows, cases, tags, specs, B=100):
    return summarize(rows, cases, tags, [BUNDLE], specs=specs, contrasts=[], bootstrap_b=B)


if __name__ == "__main__":
    unittest.main()
