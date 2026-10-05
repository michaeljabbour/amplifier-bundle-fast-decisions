"""Offline tests for the Cloudflare Workers AI arms (clef, clef-flash) and the --posthoc-arms guard. No network."""
import asyncio
import contextlib
import io
import json
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
from evals.judge_bench import arms, cases as case_lib  # noqa: E402

CASE = {"id": "c1", "kind": "choice", "expected": "a", "screen": "dev",
        "payload": {"state": "{}", "questions": {"decision": {
            "type": "choice", "instructions": "pick", "criteria": {"a": "A", "b": "B", "reason": "R"}}}}}
NOUL_CASE = {"id": "c2", "kind": "search", "expected": True, "screen": "dev",
             "payload": {"state": "{}", "questions": {"decision": {"type": "noul", "instructions": "ok?"}}}}


class Resp:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
        self.text = json.dumps(data)

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self.data

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


class Client:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return self.response


def envelope(answer, usage=None, **extra):
    return {"result": {"model": "clef-flash", "answers": {"decision": answer},
                       "usage": usage or {"input_tokens": 219, "output_tokens": 0}},
            "success": True, "errors": [], "messages": [], **extra}


def arm():
    return arms.SystemOneArm("clef-flash", "https://cf.test/run/clef-flash", "clef-flash", "tok", envelope=True)


class EnvelopeTests(unittest.TestCase):
    def test_choice_is_unwrapped(self):
        probs = {"a": 0.9557, "b": 0.0117, "reason": 0.0326}
        client = Client(Resp(envelope({"type": "choice", "choice": "a", "probabilities": probs, "confidence": .87})))
        out = asyncio.run(arm().decide(client, CASE["payload"]))
        self.assertEqual(out["answer"]["probabilities"], probs)
        self.assertEqual((out["model"], out["input_tokens"], out["output_tokens"]), ("clef-flash", 219, 0))
        self.assertIsNone(out["timing"]["server_ms"])  # no timing header: the runner's client elapsed is used
        url, body, headers = client.calls[0]
        self.assertEqual(body["model"], "clef-flash")
        self.assertEqual(headers["Authorization"], "Bearer tok")

    def test_noul_carries_probability_in_noul(self):
        client = Client(Resp(envelope({"type": "noul", "noul": 0.83})))
        out = asyncio.run(arm().decide(client, NOUL_CASE["payload"]))
        self.assertEqual(out["answer"], {"type": "noul", "noul": 0.83})
        from evals.judge_bench.scoring import validate_answer
        validate_answer(NOUL_CASE, out["answer"])

    def test_success_false_is_invalid_with_error_text(self):
        body = {"result": {}, "success": False, "messages": [],
                "errors": [{"code": 5006, "message": "AiError: Bad input"}]}
        with self.assertRaisesRegex(arms.ArmParseError, r"envelope error: \[5006\] AiError: Bad input"):
            asyncio.run(arm().decide(Client(Resp(body)), CASE["payload"]))

    def test_http_error_carries_cloudflare_text(self):
        body = {"result": {}, "success": False, "errors": [{"code": 5006, "message": "required properties"}]}
        with self.assertRaisesRegex(arms.ArmParseError, r"HTTP 400: envelope error: \[5006\] required properties") as cm:
            asyncio.run(arm().decide(Client(Resp(body, status=400)), CASE["payload"]))
        self.assertEqual(cm.exception.http_status, 400)

    def test_errors_list_without_success_flag_is_invalid(self):
        body = envelope({"type": "choice", "probabilities": {"a": 1.0}})
        body["errors"] = [{"code": 1, "message": "boom"}]
        with self.assertRaisesRegex(arms.ArmParseError, "boom"):
            asyncio.run(arm().decide(Client(Resp(body)), CASE["payload"]))

    def test_error_keeps_reported_usage_out_of_a_missing_model(self):
        body = envelope({"type": "choice", "probabilities": {"a": 1.0}})
        body["result"]["model"] = ""
        with self.assertRaises(arms.ArmParseError) as cm:
            asyncio.run(arm().decide(Client(Resp(body)), CASE["payload"]))
        self.assertEqual(cm.exception.usage, (None, None))  # usage is read after the model check

    def test_server_timing_header_is_used_when_present(self):
        client = Client(Resp(envelope({"type": "noul", "noul": 0.5}), headers={"server-timing": "dur=41.5"}))
        out = asyncio.run(arm().decide(client, NOUL_CASE["payload"]))
        self.assertEqual(out["timing"]["server_ms"], 41.5)

    def test_plain_systemone_body_still_works_without_envelope(self):
        plain = {"model": "jev", "answers": {"decision": {"type": "noul", "noul": 0.2}}, "usage": {}}
        out = asyncio.run(arms.SystemOneArm("jev", "https://x", "jev", "t").decide(Client(Resp(plain)), NOUL_CASE["payload"]))
        self.assertEqual(out["answer"]["noul"], 0.2)

    def test_native_next_action_body_is_unwrapped(self):
        ids = ["r1", "r2", "reason"]
        native = {"decision_request": {"state": "{}", "candidates": []},
                  "systemone_body": {"state": "{}", "questions": {"next_action": {
                      "type": "choice", "instructions": "i", "criteria": {k: {"d": k} for k in ids}}}}}
        answer = {"type": "choice", "choice": "r1", "probabilities": {"r1": .95, "r2": .03, "reason": .02},
                  "confidence": .9}
        client = Client(Resp({"result": {"model": "clef", "answers": {"next_action": answer},
                                         "usage": {"input_tokens": 300, "output_tokens": 0}},
                              "success": True, "errors": []}))
        a = arms.SystemOneArm("clef", "https://cf.test/run/clef", "clef", "tok", "systemone_body", envelope=True)
        out = asyncio.run(a.decide_case(client, {"id": "t", "native": native, "payload": CASE["payload"]}, 0))
        self.assertEqual(out["form"], "native")
        self.assertEqual(out["answer"]["probabilities"]["r1"], .95)
        self.assertEqual(client.calls[0][1]["questions"]["next_action"]["criteria"]["r1"], {"d": "r1"})


class BuildArmTests(unittest.TestCase):
    def setUp(self):
        self.cfg = judges.load_config()

    def test_arms_are_configured_as_post_hoc_cloud_arms(self):
        for name, price in (("clef", .24), ("clef-flash", .09)):
            spec = self.cfg["arms"][name]
            self.assertEqual((spec["adapter"], spec["native_form"], spec["local"], spec["price_in"], spec["price_out"]),
                             ("systemone", "systemone_body", False, price, 0.0))
            self.assertNotIn("key", json.dumps(spec).lower().replace("token_env", ""))

    def test_url_and_token_come_from_env_only(self):
        env = {"CLOUDFLARE_API_TOKEN": "tok-123", "CLOUDFLARE_ACCOUNT_ID": "acct-9"}
        built = judges.build_arm(self.cfg["arms"]["clef"], self.cfg["arms"], env)
        self.assertTrue(built.url.endswith("/accounts/acct-9/ai/run/@cf/cloudflare/clef"))
        self.assertEqual((built.token, built.model, built.envelope), ("tok-123", "clef", True))
        self.assertNotIn("acct-9", json.dumps(self.cfg))

    def test_missing_env_makes_the_arm_unavailable(self):
        for env in ({"CLOUDFLARE_ACCOUNT_ID": "a"}, {"CLOUDFLARE_API_TOKEN": "t"}):
            with self.assertRaises(arms.ArmUnavailable):
                judges.build_arm(self.cfg["arms"]["clef-flash"], self.cfg["arms"], env)

    def test_cost_accounting_charges_input_tokens_only(self):
        self.assertAlmostEqual(judges.request_cost("clef", self.cfg["arms"], 1_000_000, 500), 0.24)
        self.assertAlmostEqual(judges.request_cost("clef-flash", self.cfg["arms"], 1_000_000, 500), 0.09)

    def test_secrets_are_scrubbed_from_errors(self):
        import os
        old = dict(os.environ)
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acct-secret-1"
        try:
            self.assertNotIn("acct-secret-1", judges._scrub("for url https://x/accounts/acct-secret-1/ai"))
        finally:
            os.environ.clear()
            os.environ.update(old)


class PosthocGuardTests(unittest.TestCase):
    YAML = ("schema: s\ndefaults: {reps: 3}\nbudget: {default_usd: 5.0}\n"
            "arms:\n  jev-1.13: {adapter: systemone, price_in: 0.042}\ncontrasts:\n  - [jev-1.13, jev-1.13]\n")

    def repo(self, tmp):
        root = Path(tmp)
        holdout = root / "evals" / "judge_bench" / "holdout"
        holdout.mkdir(parents=True)
        cases = [{"id": "h-0", "kind": "search", "expected": True,
                  "payload": {"state": "{}", "questions": {}}, "tags": {}}]
        (holdout / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        digest = case_lib.cases_sha256([dict(c, screen="holdout") for c in cases])
        (holdout / "PREREGISTRATION.md").write_text(f"# prereg\ncases_sha256: {digest}\n", encoding="utf-8")
        for rel, text in (("evals/judges.yaml", self.YAML), ("evals/judges.py", "x = 1\n"),
                          ("evals/judge_bench/arms.py", "a = 1\n"), ("evals/judge_bench/scoring.py", "s = 1\n")):
            (root / rel).write_text(text, encoding="utf-8")
        self.git(tmp, "init", "-q")
        self.git(tmp, "add", "-A")
        self.git(tmp, "commit", "-q", "-m", "x")
        return root, holdout

    @staticmethod
    def git(tmp, *a):
        subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       check=True, capture_output=True)

    def test_new_arms_in_arms_py_judges_py_and_yaml_are_allowed_but_the_default_guard_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            (root / "evals" / "judge_bench" / "arms.py").write_text("a = 2\n", encoding="utf-8")
            (root / "evals" / "judges.py").write_text("x = 2\n", encoding="utf-8")
            (root / "evals" / "judges.yaml").write_text(self.YAML + "  - [jev-1.13, clef]\n", encoding="utf-8")
            with self.assertRaisesRegex(judges.GuardError, "uncommitted changes in the benchmark code"):
                judges.check_holdout_guard(root, holdout)
            self.assertEqual(len(judges.check_holdout_guard(root, holdout, posthoc=True)), 64)

    def test_scoring_code_changes_are_still_refused_posthoc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            (root / "evals" / "judge_bench" / "scoring.py").write_text("s = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(judges.GuardError, r"uncommitted changes in the benchmark code \(.*scoring"):
                judges.check_holdout_guard(root, holdout, posthoc=True)

    def test_untracked_judge_bench_module_is_refused_posthoc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            (root / "evals" / "judge_bench" / "extra.py").write_text("y = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(judges.GuardError, "uncommitted changes"):
                judges.check_holdout_guard(root, holdout, posthoc=True)

    def test_cases_and_prereg_are_still_pinned_posthoc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, holdout = self.repo(tmp)
            (holdout / "cases.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(judges.GuardError, "differs from HEAD"):
                judges.check_holdout_guard(root, holdout, posthoc=True)

    def test_config_check_lists_only_added_arms(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self.repo(tmp)
            cfg = yaml.safe_load(self.YAML)
            self.assertEqual(judges.check_posthoc_config(root, cfg), [])
            cfg["arms"]["clef"] = {"adapter": "systemone"}
            cfg["contrasts"].append(["jev-1.13", "clef"])
            self.assertEqual(judges.check_posthoc_config(root, cfg), ["clef"])

    def test_config_check_refuses_any_other_change(self):
        import copy
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self.repo(tmp)
            base = yaml.safe_load(self.YAML)
            for mutate, pattern in (
                    (lambda c: c["defaults"].update(reps=1), "defaults"),
                    (lambda c: c["budget"].update(default_usd=9), "budget"),
                    (lambda c: c["arms"]["jev-1.13"].update(price_in=1.0), "jev-1.13"),
                    (lambda c: c["arms"].pop("jev-1.13"), "jev-1.13"),
                    (lambda c: c["contrasts"].clear(), "contrast")):
                cfg = copy.deepcopy(base)
                mutate(cfg)
                with self.assertRaisesRegex(judges.GuardError, pattern):
                    judges.check_posthoc_config(root, cfg)

    def test_cli_refusals(self):
        for argv, msg in ((["--split", "dev", "--posthoc-arms", "--arms", "clef"], "applies to holdout"),
                          (["--split", "holdout", "--posthoc-arms"], "needs --arms")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judges.main(argv), 2)
            self.assertIn(msg, err.getvalue())

    def test_summary_is_relabeled_but_numbers_are_not(self):
        cases = [dict(CASE, screen="holdout")]
        rows = [{"arm": "clef", "rep": 1, "id": "c1", "screen": "holdout", "kind": "choice", "expected": "a",
                 "order": o, "valid": True, "elapsed_ms": 10.0, "model": "clef", "http_status": 200,
                 "input_tokens": 10, "output_tokens": 0, "timing": {"server_ms": None},
                 "answer": {"type": "choice", "probabilities": {"a": .95, "b": .03, "reason": .02}}}
                for o in (0, 1)]
        cfg = judges.load_config()
        meta = judges._meta_from_cfg(cfg) | {"split": "holdout"}
        plain = judges.build_summary(rows, cases, {"c1": {}}, meta)
        post = judges.build_summary(rows, cases, {"c1": {}}, dict(meta, posthoc=True))
        self.assertEqual(plain["label"], "preregistered")
        self.assertEqual(post["label"], post["decisions"]["label"], judges.POSTHOC_LABEL)
        post["label"] = plain["label"]
        post["decisions"]["label"] = plain["decisions"]["label"]
        self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(post, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
