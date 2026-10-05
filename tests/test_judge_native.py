"""Offline tests for the trace-derived judge splits: native request forms, final labels, guard, runner."""
import asyncio
import contextlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from evals import judges  # noqa: E402
from evals.judge_bench import arms, cases as case_lib, native, scoring  # noqa: E402

POOL = ROOT / "evals" / "judge_bench" / "traces" / "pool.json"
HAVE_POOL = POOL.exists()
POOL_CASES = json.loads(POOL.read_text(encoding="utf-8"))["cases"] if HAVE_POOL else []
BUNDLE = scoring.POLICIES["bundle-read-shortcut"]


def pool_case(backend, split=None):
    for c in POOL_CASES:
        if c["native"]["sent"]["backend"] == backend and (split is None or c["split"] == split):
            return c
    raise unittest.SkipTest(f"no {backend} case in the pool")


def as_case(pool, label=None, screen="trace-dev"):
    """A runner-shaped case from a pool entry (what trace_cases builds)."""
    return {"id": pool["id"], "kind": pool["kind"], "expected": label or pool["proposed_label"],
            "payload": pool["payload"], "native": pool["native"], "screen": screen, "tags": {}}


class FakeResponse:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
        self.content = json.dumps(data).encode()
        self.text = self.content.decode()

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


def candidate_ids(pool):
    return [c["id"] for c in pool["native"]["decision_request"]["candidates"]]


def system_one_response(pool, top=0):
    ids = candidate_ids(pool) + ["reason"]
    probs = {k: (.91 if i == top else .09 / (len(ids) - 1)) for i, k in enumerate(ids)}
    return {"model": "jev-1.13.0", "answers": {"next_action": {"type": "choice", "choice": ids[top],
            "probabilities": probs, "confidence": .9}}, "usage": {"input_tokens": 321, "output_tokens": 12}}


@unittest.skipUnless(HAVE_POOL, "traces/pool.json not present")
class NativeRequestBytesTests(unittest.TestCase):
    def test_system_one_body_equals_the_session_and_the_real_jev_backend(self):
        pool = pool_case("jev")
        arm = arms.SystemOneArm("jev-1.13", "https://example.test/v1/systemone", "jev-1.13.0", "tok",
                                native_form="systemone_body")
        client = FakeClient(lambda url, body: FakeResponse(system_one_response(pool)))
        result = asyncio.run(arm.decide_case(client, as_case(pool), 0))
        _, body, _ = client.calls[0]
        sent = pool["native"]["sent"]["body"]
        self.assertEqual(json.dumps({k: v for k, v in body.items() if k != "model"}), json.dumps(sent))
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertEqual(result["form"], "native")
        # ... and byte-identical to what JevBackend._ask_urllib puts on the wire
        captured = {}

        def fake_post(self_, base_url, path, headers, body_bytes, timeout_s):
            captured["bytes"], captured["path"] = body_bytes, path
            return system_one_response(pool)
        from amplifier_fast_decisions.backends import JevBackend
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "tok"}), \
                mock.patch.object(JevBackend, "_post_keepalive", fake_post):
            backend = JevBackend(base_url="http://x.test", api_key_env="TYPESAFE_API_KEY", model="jev-1.13.0")
            asyncio.run(backend.ask(native.decision_request(pool["native"])))
        self.assertEqual(captured["path"], "/v1/systemone")
        self.assertEqual(captured["bytes"], json.dumps(body).encode("utf-8"))

    def test_system_one_answer_is_read_from_next_action_and_normalized(self):
        pool = pool_case("jev")
        arm = arms.SystemOneArm("nimble-9b", "http://127.0.0.1:11434/v1/systemone", "nimble",
                                native_form="systemone_body")
        client = FakeClient(lambda url, body: FakeResponse(system_one_response(pool, top=1)))
        result = asyncio.run(arm.decide_case(client, as_case(pool), 0))
        answer = result["answer"]
        ids = candidate_ids(pool)
        self.assertEqual(list(answer["probabilities"]), ids + ["reason"])
        self.assertEqual(answer["choice"], ids[1] if len(ids) > 1 else "reason")
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (321, 12))
        scoring.validate_answer(as_case(pool), answer)  # scoring.py works unchanged
        self.assertEqual(scoring.score(as_case(pool, label=ids[0]), answer, 10, BUNDLE)["predicted"], answer["choice"])
        for broken in ({"model": "m", "answers": {"decision": {}}}, {"model": "m", "answers": {"next_action": {"type": "noul"}}}):
            bad = FakeClient(lambda url, body, broken=broken: FakeResponse(dict(broken, usage={"input_tokens": 5})))
            with self.assertRaises(arms.ArmParseError) as ctx:
                asyncio.run(arm.decide_case(bad, as_case(pool), 0))
            self.assertEqual(ctx.exception.usage[0], 5)

    def test_ollama_native_prompt_equals_the_session_and_answer_is_normalized(self):
        pool = pool_case("ollama")
        ids = candidate_ids(pool)
        sent = pool["native"]["sent"]["body"]
        letters = sent["labels"]
        top = [{"token": letter, "logprob": math.log(p)} for letter, p in zip(letters, [.6, .25, .1][:len(letters)])]

        def respond(url, body):
            return FakeResponse({"model": "qwen3:4b", "done": True, "eval_count": 1, "prompt_eval_count": 777,
                                 "logprobs": [{"top_logprobs": top}]})
        client = FakeClient(respond)
        arm = arms.OllamaBackendArm("qwen3-4b", "qwen3:4b", client=client, native_form="ollama_backend")
        result = asyncio.run(arm.decide_case(None, as_case(pool), 0))
        self.assertEqual(len(client.calls), 1)  # one candidate-mode call, not question mode's two
        url, body, _ = client.calls[0]
        self.assertTrue(url.endswith("/api/generate"))
        self.assertEqual(body["system"], sent["system"])
        self.assertEqual(body["prompt"], sent["prompt"])
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertIn("Z. None of the above", body["prompt"])
        answer = result["answer"]
        self.assertEqual(list(answer["probabilities"])[:len(ids)], ids)
        self.assertIn("reason", answer["probabilities"])  # Z -> reason, the SLOW residual
        self.assertAlmostEqual(sum(answer["probabilities"].values()), 1.0, places=6)
        self.assertEqual(answer["choice"], ids[0])
        self.assertEqual((result["form"], result["input_tokens"]), ("native", 777))
        scoring.validate_answer(as_case(pool), answer)

    def test_ollama_order_pass_reverses_the_candidate_letters(self):
        pool = pool_case("ollama")
        client = FakeClient(lambda url, body: FakeResponse({
            "model": "qwen3:4b", "done": True, "eval_count": 1,
            "logprobs": [{"top_logprobs": [{"token": "A", "logprob": math.log(.9)}]}]}))
        arm = arms.OllamaBackendArm("qwen3-4b", "qwen3:4b", client=client, native_form="ollama_backend")
        asyncio.run(arm.decide_case(None, as_case(pool), 0))
        result = asyncio.run(arm.decide_case(None, as_case(pool), 1))
        first, second = client.calls[0][1]["prompt"], client.calls[1][1]["prompt"]
        self.assertNotEqual(first, second)
        ids = candidate_ids(pool)
        self.assertEqual(result["answer"]["choice"], ids[-1])  # letter A is now the last candidate

    def test_laya_native_is_the_real_backend_request_and_validation(self):
        pool = pool_case("laya")
        ids = candidate_ids(pool)
        captured = {}

        def fake_call(req, timeout_s, *, expect_json=True):
            captured["url"], captured["body"] = req.full_url, json.loads(req.data)
            probs = {k: (.9 if i == 0 else .1 / len(ids)) for i, k in enumerate(ids + ["reason"])}
            return {"model": "laya-rl", "answers": {"next_action": {"type": "choice", "choice": ids[0],
                    "probabilities": probs, "confidence": .9}}}, 200
        arm = arms.SystemOneArm("laya-base", "http://127.0.0.1:8090/v1/decide", None, native_form="laya_backend")
        from amplifier_fast_decisions import local_backend
        with mock.patch.object(local_backend, "_mlx_urllib_call", fake_call):
            result = asyncio.run(arm.decide_case(None, as_case(pool), 0))
        self.assertEqual(captured["url"], "http://127.0.0.1:8090/v1/decide")
        self.assertEqual(captured["body"], pool["native"]["sent"]["body"])
        self.assertEqual((result["form"], result["model"]), ("native", "laya-rl"))
        self.assertEqual(list(result["answer"]["probabilities"]), ids + ["reason"])
        scoring.validate_answer(as_case(pool), result["answer"])

        def bad_call(req, timeout_s, *, expect_json=True):  # the real backend rejects mismatched alternatives
            return {"model": "laya", "answers": {"next_action": {"type": "choice", "choice": "a",
                    "probabilities": {"a": 1.0}}}}, 200
        with mock.patch.object(local_backend, "_mlx_urllib_call", bad_call), self.assertRaises(Exception):
            asyncio.run(arm.decide_case(None, as_case(pool), 0))

    def test_every_pool_backend_family_is_covered_by_the_tests_above(self):
        self.assertEqual({c["native"]["sent"]["backend"] for c in POOL_CASES} - {"jev", "laya", "ollama"}, set())


@unittest.skipUnless(HAVE_POOL, "traces/pool.json not present")
class ReorderAndAdaptedTests(unittest.TestCase):
    def test_reorder_native_reverses_candidates_and_system_one_criteria(self):
        pool = pool_case("jev")
        zero, one = native.reorder_native(pool["native"], 0), native.reorder_native(pool["native"], 1)
        self.assertEqual(zero, pool["native"])
        self.assertEqual([c["id"] for c in one["decision_request"]["candidates"]], candidate_ids(pool)[::-1])
        crit = list(pool["native"]["systemone_body"]["questions"]["next_action"]["criteria"])
        self.assertEqual(list(one["systemone_body"]["questions"]["next_action"]["criteria"]), crit[::-1])
        self.assertEqual(pool["native"], native.reorder_native(pool["native"], 0))  # input untouched

    def test_chat_arms_run_adapted_on_the_bench_payload(self):
        pool = pool_case("jev")
        arm = arms.ChatJudgeArm("gpt-6-luna", "gpt-6-luna", "test-token")
        keys = candidate_ids(pool) + ["reason"]
        client = FakeClient(lambda url, body: FakeResponse({
            "model": "gpt-6-luna", "usage": {"prompt_tokens": 9, "completion_tokens": 3},
            "choices": [{"message": {"content": json.dumps({"choice": keys[0], "probabilities": {
                k: (1.0 if k == keys[0] else 0.0) for k in keys}})}}]}))
        result = asyncio.run(arms.decide_case(arm, client, as_case(pool), 0))
        self.assertEqual(result["form"], "adapted")
        sent = json.loads(client.calls[0][1]["messages"][1]["content"])
        self.assertEqual(sent["state"], pool["payload"]["state"])
        self.assertEqual(sent["options"], pool["payload"]["questions"]["decision"]["criteria"])
        self.assertIsNone(arms.native_form_of(arm))

    def test_clause_arms_native_only_where_the_prompt_has_an_instruction_slot(self):
        pool = pool_case("jev")
        clause = "CLAUSE-TEXT."
        base = arms.SystemOneArm("jev-1.13", "https://example.test/v1/systemone", "jev-1.13.0", "tok",
                                 native_form="systemone_body")
        client = FakeClient(lambda url, body: FakeResponse(system_one_response(pool)))
        wrapped = arms.InstructionClauseArm(base, clause, "jev-1.13+sideeffect-clause")
        result = asyncio.run(wrapped.decide_case(client, as_case(pool), 0))
        instructions = client.calls[0][1]["questions"]["next_action"]["instructions"]
        self.assertTrue(instructions.endswith(" " + clause))
        self.assertEqual(result["form"], "native")
        self.assertEqual(arms.native_form_of(wrapped), "systemone_body")
        ollama = arms.InstructionClauseArm(
            arms.OllamaBackendArm("qwen3-8b", "qwen3:8b", native_form="ollama_backend"), clause, "q+clause")
        self.assertIsNone(arms.native_form_of(ollama))  # fixed production prompt: clause only fits adapted
        self.assertEqual(pool["native"]["systemone_body"]["questions"]["next_action"]["instructions"] + " " + clause,
                         native.patch_clause(as_case(pool), clause)["native"]["systemone_body"]["questions"]["next_action"]["instructions"])

    def test_yaml_declares_which_arms_run_native(self):
        cfg = judges.load_config()
        env = {"TYPESAFE_API_KEY": "x", "OPENAI_API_KEY": "x", "CLOUDFLARE_API_TOKEN": "x",
               "CLOUDFLARE_ACCOUNT_ID": "x"}
        got = {n: arms.native_form_of(arms.build_arm(s, cfg["arms"], env)) for n, s in cfg["arms"].items()}
        self.assertEqual(got["jev-1.13"], "systemone_body")
        self.assertEqual(got["jev-1.13+sideeffect-clause"], "systemone_body")
        # Ollama /v1/systemone rejects the bundle's object-valued criteria (HTTP 400): these run adapted.
        for n in ("nimble-9b", "tev1-4b", "tev1-0.8b", "tev1-0.8b+sideeffect-clause"):
            self.assertIsNone(got[n], n)
        for n in ("clef", "clef-flash"):  # Workers AI accepts the bundle's next_action body
            self.assertEqual(got[n], "systemone_body", n)
        self.assertEqual(got["laya-base"], "laya_backend")
        for n in ("qwen3-0.6b", "qwen3-4b", "qwen3-8b"):
            self.assertEqual(got[n], "ollama_backend", n)
        for n in ("gpt-6-luna", "gpt-6.1-sol", "openai-decisions", "gpt-6-luna+sideeffect-clause",
                  "qwen3-8b+sideeffect-clause"):
            self.assertIsNone(got[n], n)


def write_labels(path, entries):
    path.write_text(json.dumps({"labels": entries}), encoding="utf-8")


@unittest.skipUnless(HAVE_POOL, "traces/pool.json not present")
class FinalLabelTests(unittest.TestCase):
    def labels_for(self, split, drop=(), override=None):
        want = "holdout" if split == "trace-holdout" else "dev"
        out = {}
        for c in POOL_CASES:
            if c["split"] == want:
                out[c["id"]] = {"label": c["proposed_label"],
                                "decision": "dropped" if c["id"] in drop else "agreed"}
        for cid, entry in (override or {}).items():
            out[cid] = entry
        return out

    def test_missing_labels_file_refuses_clearly(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            case_lib.trace_cases("trace-dev", POOL, Path("/nonexistent/labels_final.json"))
        self.assertIn("blind review", str(ctx.exception))
        self.assertIn("labels_final.json", str(ctx.exception))

    def test_final_label_is_expected_and_dropped_cases_are_excluded(self):
        dev = [c for c in POOL_CASES if c["split"] == "dev"]
        dropped, adjudicated = dev[0]["id"], dev[1]
        relabel = "reason" if adjudicated["proposed_label"] != "reason" else candidate_ids(adjudicated)[0]
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels_final.json"
            write_labels(labels, self.labels_for("trace-dev", drop={dropped}, override={
                adjudicated["id"]: {"label": relabel, "decision": "adjudicated"}}))
            cases = case_lib.trace_cases("trace-dev", POOL, labels)
            by_id = {c["id"]: c for c in cases}
            self.assertEqual(len(cases), len(dev) - 1)
            self.assertNotIn(dropped, by_id)
            self.assertEqual(by_id[adjudicated["id"]]["expected"], relabel)  # FINAL label, not the proposal
            self.assertEqual(by_id[adjudicated["id"]]["label_decision"], "adjudicated")
            self.assertTrue(all(c["screen"] == "trace-dev" and c["kind"] == "read_shortcut" for c in cases))
            self.assertEqual(set(case_lib.load_tags("trace-dev", cases)), set(by_id))
            hold = {c["id"] for c in POOL_CASES if c["split"] == "holdout"}
            self.assertFalse(hold & set(by_id))  # splits never mix
            self.assertEqual(case_lib.cases_sha256(cases), case_lib.cases_sha256(case_lib.trace_cases("trace-dev", POOL, labels)))

    def test_incomplete_or_invalid_labels_are_rejected(self):
        dev = [c["id"] for c in POOL_CASES if c["split"] == "dev"]
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels_final.json"
            partial = self.labels_for("trace-dev")
            del partial[dev[0]]
            write_labels(labels, partial)
            with self.assertRaisesRegex(ValueError, "no decision"):
                case_lib.trace_cases("trace-dev", POOL, labels)
            write_labels(labels, self.labels_for("trace-dev", override={dev[0]: {"label": "not_an_option", "decision": "agreed"}}))
            with self.assertRaisesRegex(ValueError, "not one of"):
                case_lib.trace_cases("trace-dev", POOL, labels)
            write_labels(labels, self.labels_for("trace-dev", override={dev[0]: {"label": "reason", "decision": "maybe"}}))
            with self.assertRaisesRegex(ValueError, "decision must be"):
                case_lib.trace_cases("trace-dev", POOL, labels)
            with self.assertRaises(ValueError):
                case_lib.trace_cases("holdout", POOL, labels)

    def test_flat_label_mapping_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels_final.json"
            labels.write_text(json.dumps(self.labels_for("trace-dev")), encoding="utf-8")
            self.assertEqual(len(case_lib.trace_cases("trace-dev", POOL, labels)),
                             sum(c["split"] == "dev" for c in POOL_CASES))

    def test_cli_refuses_trace_splits_until_labels_exist(self):
        for split in ("trace-dev",):
            err = io.StringIO()
            with mock.patch.object(case_lib, "TRACE_LABELS", Path("/nonexistent/labels_final.json")), \
                    contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judges.main(["--split", split, "--dry-run"]), 2)
            self.assertIn("Final trace labels not found", err.getvalue())


@unittest.skipUnless(HAVE_POOL, "traces/pool.json not present")
class TraceGuardTests(unittest.TestCase):
    def repo(self, tmp, *, prereg=True, labels=True, commit=True, sha=None, labels_decisions=None):
        root = Path(tmp)
        traces = root / "evals" / "judge_bench" / "traces"
        traces.mkdir(parents=True)
        pool = [c for c in POOL_CASES if c["split"] == "holdout"][:4]
        (traces / "pool.json").write_text(json.dumps({"meta": {}, "cases": pool}), encoding="utf-8")
        entries = {c["id"]: {"label": c["proposed_label"], "decision": (labels_decisions or {}).get(c["id"], "agreed")}
                   for c in pool}
        if labels:
            write_labels(traces / "labels_final.json", entries)
        digest = sha
        if digest is None:
            digest = case_lib.cases_sha256(case_lib.trace_cases("trace-holdout", traces / "pool.json",
                                                                traces / "labels_final.json")) if labels else "0" * 64
        if prereg:
            (traces / "PREREGISTRATION.md").write_text(f"# prereg\ncases_sha256: {digest}\n", encoding="utf-8")

        def git(*a):
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", *a],
                           check=True, capture_output=True)
        git("init", "-q")
        git("add", "-A")
        if commit:
            git("commit", "-q", "-m", "x")
        return root, traces

    def test_accepts_committed_preregistration_pool_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp)
            sha = judges.check_holdout_guard(root, traces, "trace-holdout")
            self.assertEqual(len(sha), 64)

    def test_refuses_without_prereg_labels_commit_or_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp, prereg=False)
            with self.assertRaisesRegex(judges.GuardError, "PREREGISTRATION.md does not exist"):
                judges.check_holdout_guard(root, traces, "trace-holdout")
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp, labels=False)
            with self.assertRaisesRegex(judges.GuardError, "labels_final.json does not exist.*final labels"):
                judges.check_holdout_guard(root, traces, "trace-holdout")
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp, commit=False)
            with self.assertRaises(judges.GuardError):
                judges.check_holdout_guard(root, traces, "trace-holdout")
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp)
            first = json.loads((traces / "labels_final.json").read_text(encoding="utf-8"))["labels"]
            cid = next(iter(first))
            first[cid]["decision"] = "dropped"  # a label edit after preregistration changes the case set
            write_labels(traces / "labels_final.json", first)
            with self.assertRaisesRegex(judges.GuardError, "differs from HEAD"):
                judges.check_holdout_guard(root, traces, "trace-holdout")
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp, sha="1" * 64)
            with self.assertRaisesRegex(judges.GuardError, "does not match"):
                judges.check_holdout_guard(root, traces, "trace-holdout")
        with tempfile.TemporaryDirectory() as tmp:
            root, traces = self.repo(tmp, labels_decisions={})
            (traces / "labels_final.json").unlink()
            subprocess.run(["git", "-C", tmp, "rm", "-q", "--cached", "evals/judge_bench/traces/labels_final.json"],
                           check=True, capture_output=True)
            with self.assertRaises(judges.GuardError):
                judges.check_holdout_guard(root, traces, "trace-holdout")

    def test_cli_trace_holdout_is_guarded_and_refuses_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with mock.patch.object(judges, "TRACES_DIR", Path(tmp)), contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judges.main(["--split", "trace-holdout", "--dry-run"]), 2)
            self.assertIn("holdout guard", err.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(judges.main(["--split", "trace-holdout", "--limit", "5"]), 2)
        self.assertIn("--limit is not allowed with --split trace-holdout", err.getvalue())


class NativeOracle:
    determinism = {"temperature_sent": None, "seed_sent": None}
    model = "oracle"

    def __init__(self, name):
        self.name = name
        self.native_form = "systemone_body"

    async def decide_case(self, client, case, order):
        keys = list(case["payload"]["questions"]["decision"]["criteria"])
        probs = {k: (.96 if k == case["expected"] else .04 / (len(keys) - 1)) for k in keys}
        return {"answer": {"type": "choice", "probabilities": probs, "choice": case["expected"]},
                "model": "oracle", "input_tokens": 100, "output_tokens": 5, "timing": {"server_ms": None},
                "http_status": 200, "form": "native"}


class AdaptedOracle(NativeOracle):
    """Only has decide(): the runner must route it through the adapted bench payload."""

    def __init__(self, name):
        self.name = name

    decide_case = None

    async def decide(self, client, payload):
        keys = list(payload["questions"]["decision"]["criteria"])
        probs = {k: (.96 if k == keys[0] else .04 / (len(keys) - 1)) for k in keys}
        return {"answer": {"type": "choice", "probabilities": probs}, "model": "adapted-oracle",
                "input_tokens": 50, "output_tokens": 4, "timing": {"server_ms": None}, "http_status": 200}


@unittest.skipUnless(HAVE_POOL, "traces/pool.json not present")
class TraceRunnerTests(unittest.TestCase):
    def test_rows_log_form_and_run_json_records_arm_forms(self):
        dev = [c for c in POOL_CASES if c["split"] == "dev"]
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels_final.json"
            write_labels(labels, {c["id"]: {"label": c["proposed_label"], "decision": "agreed"} for c in dev})
            built = {}

            def fake_build(spec, specs):
                built[spec["name"]] = (NativeOracle if spec["name"] == "jev-1.13" else AdaptedOracle)(spec["name"])
                return built[spec["name"]]
            out = Path(tmp) / "run"
            with mock.patch.object(case_lib, "TRACE_LABELS", labels), mock.patch.object(judges, "build_arm", fake_build), \
                    mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x", "TYPESAFE_API_KEY": "tk-x"}), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = judges.main(["--split", "trace-dev", "--arms", "jev-1.13", "gpt-6-luna", "--reps", "1",
                                    "--limit", "6", "--out", str(out)])
            self.assertEqual(code, 0)
            rows = [json.loads(l) for l in (out / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({r["form"] for r in rows if r["arm"] == "jev-1.13"}, {"native"})
            self.assertEqual({r["form"] for r in rows if r["arm"] == "gpt-6-luna"}, {"adapted"})
            self.assertTrue(all(r["valid"] for r in rows))
            self.assertEqual({r["kind"] for r in rows}, {"read_shortcut"})
            run = json.loads((out / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["invocations"][0]["arm_forms"], {"jev-1.13": "native", "gpt-6-luna": "adapted"})
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual((summary["split"], summary["label"]), ("trace-dev", "screen"))
            self.assertEqual(summary["arms"]["jev-1.13"]["flags"]["forms"], ["native"])
            self.assertEqual(summary["arms"]["gpt-6-luna"]["flags"]["forms"], ["adapted"])
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["split"], "trace-dev")
            self.assertEqual(len(manifest["cases"]), 6)
            self.assertIn("native", manifest["cases"][0])  # the exact requests are frozen with the cases
            for r in rows:  # oracle answers score without any scoring.py change
                self.assertIn(r["expected"], r["answer"]["probabilities"])


@unittest.skipUnless(HAVE_POOL, "traces/pool.json not present")
class OrderFlipFlagTests(unittest.TestCase):
    def test_native_ollama_flips_are_comparable_question_mode_flips_are_not(self):
        from evals.judge_bench.summarize import summarize
        pool = pool_case("jev")
        case = as_case(pool)
        ids = candidate_ids(pool) + ["reason"]
        answer = {"type": "choice", "probabilities": {k: (.9 if k == case["expected"] else .1 / (len(ids) - 1))
                                                       for k in ids}}

        def rows(form):
            return [{"arm": "q", "rep": 1, "id": case["id"], "screen": "trace-dev", "kind": "read_shortcut",
                     "expected": case["expected"], "order": o, "valid": True, "elapsed_ms": 10.0, "answer": answer,
                     "form": form, "model": "m", "input_tokens": None, "output_tokens": None} for o in (0, 1)]
        specs = {"q": {"adapter": "ollama_backend", "name": "q", "local": True}}
        for form, comparable in (("native", True), ("adapted", False)):
            summary = summarize(rows(form), [case], {}, [BUNDLE], specs=specs, bootstrap_b=10)
            self.assertEqual(summary["arms"]["q"]["flags"]["order_flip_comparable"], comparable, form)


if __name__ == "__main__":
    unittest.main()
