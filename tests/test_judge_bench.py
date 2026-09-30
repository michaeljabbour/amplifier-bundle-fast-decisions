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

    def test_argmax_tie_prefers_stated_choice_else_sorted(self):
        tie = {"a": .4, "b": .4, "reason": .2}
        self.assertEqual(scoring.argmax_choice(tie, "b"), "b")
        self.assertEqual(scoring.argmax_choice(tie), "a")
        self.assertEqual(scoring.argmax_choice(tie, "reason"), "a")

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
        self.assertAlmostEqual(d["reliability"] - d["resolution"] + d["uncertainty"], d["brier"])
        self.assertAlmostEqual(d["residual"], 0)
        conf = [.75] * 4 + [.25] * 4
        hit = [1, 1, 1, 0, 1, 0, 0, 0]
        d = stats.brier_decomposition(conf, hit)
        self.assertAlmostEqual(d["reliability"] - d["resolution"] + d["uncertainty"], d["brier"])
        self.assertAlmostEqual(stats.ece(conf, hit), 0)


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


if __name__ == "__main__":
    unittest.main()
