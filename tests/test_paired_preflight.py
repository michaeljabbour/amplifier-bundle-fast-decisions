"""Credential/config failures (before any model call) are not retried and stop the run (exit 4); transient infra
failures still retry; preflight starts one minimal session per distinct (cell, model, key) and aborts the run on
failure; reset-wave makes an excluded wave runnable without losing the ledger; the campaign-owned provider is the only
provider in a generated profile. No model, network or Forge."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from paired_helpers import REPO_ROOT, FakeBackend, FakeProbe, make_design, paired, ps, write_events, write_inline_scenario

import forge_e2e
import forge_workloads
import run as evals_run

CRED_TAIL = ("Traceback (most recent call last):\r\n  File runtime/config.py, line 1324, in _validate_provider_credentials\r\n"
             "ValueError: Credential environment variable GOOGLE_API_KEY for provider 'provider-gemini' is not set.\r\n"
             "FORGE_E2E_FINISHED {\"name\": \"x\"}\r\n")


class ClassifyTests(unittest.TestCase):
    def test_pre_model_non_transient_failure_is_a_config_error(self):
        diag = {"error_tail": paired.clean_tail(CRED_TAIL), "model_calls": 0}
        self.assertEqual(paired.classify_failure({"session_id": None, "infrastructure_failure": True}, diag), "config_error")

    def test_transient_markers_win_even_before_any_model_call(self):
        for text in ("anthropic.APIStatusError: 529 overloaded", "Error 429 rate limit exceeded", "Connection reset by peer",
                     "forge launch failed: Maximum sessions reached", "request timed out"):
            self.assertEqual(paired.classify_failure(None, {"error_tail": text, "model_calls": 0}), "transient", text)

    def test_failure_after_a_model_call_is_transient(self):
        self.assertEqual(paired.classify_failure({"session_id": "s"}, {"error_tail": "ValueError: x", "model_calls": 3}), "transient")

    def test_nothing_to_go_on_is_transient_not_config(self):
        self.assertEqual(paired.classify_failure(None, {"error_tail": "", "model_calls": 0}), "transient")
        self.assertEqual(paired.classify_failure(None, {"error_tail": "Traceback ... ValueError", "model_calls": 0}), "transient")  # no marker

    def test_clean_tail_drops_forge_markers_ansi_and_keeps_the_last_lines(self):
        t = paired.clean_tail("\x1b[2mok\x1b[0m\r\n" + "\n".join(f"line{i}" for i in range(30)) + "\nFORGE_E2E_FINISHED {}\n", lines=5)
        self.assertEqual(t.splitlines(), [f"line{i}" for i in range(25, 30)])
        self.assertNotIn("FORGE_E2E", t)
        self.assertIn("GOOGLE_API_KEY", paired.clean_tail(CRED_TAIL))


# What the real go-wordsearch-r1-fable run.log excerpt looked like: healthy turn-1 output, no config marker anywhere.
HEALTHY_TAIL = ("Amplifier:\nCoordinates are {col, row} for first and last letter. Implementing now.\n"
                "\U0001f527 Building tool call: write_file\u2026\n\u2514\u2500 Input: 77,439 (88% cached) | Output: 1,198 | Cost: $0.19\n"
                "\u2705 Tool result: write_file\nAll tests pass.\nDONE: Implemented Solve in word_search.go\n")


class FalseConfigErrorRegression(unittest.TestCase):
    """2026-10-01 go-wordsearch-r1-fable: the Forge daemon shut down mid-turn-2 and killed every worker. All four
    sessions had made model calls and printed healthy output, but result.json was missing, so the old classifier saw
    `model_calls == 0` and no transient marker and declared a CONFIGURATION error, halting the campaign."""

    def test_missing_result_with_healthy_output_is_not_a_config_error(self):
        self.assertEqual(paired.classify_failure(None, {"error_tail": paired.clean_tail(HEALTHY_TAIL), "model_calls": 0}), "transient")
        self.assertEqual(paired.classify_failure(None, {"error_tail": paired.clean_tail(HEALTHY_TAIL), "model_calls": 0, "worker_died": True}), "transient")

    def test_config_error_needs_both_zero_model_calls_and_a_known_marker(self):
        cred = paired.clean_tail(CRED_TAIL)
        self.assertEqual(paired.classify_failure(None, {"error_tail": cred, "model_calls": 0}), "config_error")
        self.assertEqual(paired.classify_failure(None, {"error_tail": cred, "model_calls": 1}), "transient")           # a call happened
        self.assertEqual(paired.classify_failure(None, {"error_tail": cred, "model_calls": 0, "worker_died": True}), "transient")
        for marker in ("Provider 'anthropic' not configured", "Could not load configured provider source for 'x'",
                       "Error: Bundle 'file:///x/profile.md' not found", "RuntimeError: cannot determine base instruction for p"):
            self.assertEqual(paired.classify_failure(None, {"error_tail": marker, "model_calls": 0}), "config_error", marker)

    def test_backend_diagnose_counts_model_calls_from_disk_when_result_json_is_missing(self):
        import os
        import subprocess
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root, name = tmp / "w003-a1", "go-wordsearch-r1-fable-aa"
        run = root / name
        (run / "workspace").mkdir(parents=True)
        (run / "forge-output.txt").write_text(HEALTHY_TAIL)
        dead = subprocess.Popen(["true"])
        dead.wait()
        (run / "running.json").write_text(json.dumps({"controller_pid": dead.pid, "turn": 2}))
        sessions = tmp / "sessions"
        write_events(sessions / "d6382653" / "events.jsonl", [{"t": 1_800_000_000.0, "model": "claude-fable-5-1", "uncached": 10, "read": 0, "write": 100, "output": 5}])
        (sessions / ".d6382653.metadata.lock").mkdir()                                  # real sessions dirs hold such lock dirs
        be = paired.ForgeBackend()
        with patch.object(paired, "sessions_dir_for_workspace", lambda ws: sessions):
            d = be.diagnose(root, name, None)
        self.assertEqual((d["model_calls"], d["worker_died"]), (1, True))
        self.assertEqual(paired.classify_failure(None, d), "transient")
        with patch.object(paired, "sessions_dir_for_workspace", lambda ws: sessions):
            self.assertEqual(len(be.session_dirs(root, name, None)), 1)

    def test_backend_diagnose_still_flags_a_real_credential_failure(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root, name = tmp / "w000-a1", "slugify-bugfix-r1-fable-aa"
        (root / name / "workspace").mkdir(parents=True)
        (root / name / "forge-output.txt").write_text(CRED_TAIL)
        with patch.object(paired, "sessions_dir_for_workspace", lambda ws: tmp / "no-sessions"):
            d = paired.ForgeBackend().diagnose(root, name, {"session_id": None, "infrastructure_failure": True})
        self.assertEqual((d["model_calls"], d["worker_died"]), (0, False))
        self.assertEqual(paired.classify_failure({"session_id": None}, d), "config_error")

    def test_a_wave_whose_workers_all_died_is_retried_whole_not_halted(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        scn = write_inline_scenario(t / "scn")
        design = make_design(t, scn)
        specs = {s.id: s for s in paired.load_specs(design)}
        plan = paired.build_plan(design, list(specs.values()), reps=1, hosts=["fable"], arms=["anchor", "aa", "shipped", "sticky"], seed=1,
                                 budget_usd=None, parallel=6, scenarios={"tiny-demo"})
        out = t / "out"
        out.mkdir()
        ctx = paired.Ctx(out=out, design=design, cells_doc={}, suites_doc={}, specs=specs,
                         snapshots={sid: str(ps.materialize(s, t / "snaps")) for sid, s in specs.items()}, plan=plan, campaign_root=t / "camp",
                         candidate_source="x", candidate_sha=None, baseline_source="x", seed=1, decide_fn=lambda p, w, c: "cheap", sleep=lambda s: None)
        victims = {f"tiny-demo-r1-fable-{a}" for a in ("anchor", "aa", "shipped", "sticky")}
        diag = {k: {"error_tail": paired.clean_tail(HEALTHY_TAIL), "model_calls": 0, "worker_died": True} for k in victims}
        be = FakeBackend(t / "b", specs, fail_first=victims, diag=diag)
        logs = []
        code = paired.run_campaign(ctx, be, budget_usd=1000, parallel=6, resume=False, policy_config={}, log=logs.append)
        self.assertEqual(code, 0)                                                      # not exit 4
        w = paired.State(out / "state.json").wave("tiny-demo-r1-fable")
        self.assertEqual([a["status"] for a in w["attempts"]], ["infra_failed", "done"])
        self.assertTrue(all(v == "transient" for v in w["attempts"][0]["failure_kinds"].values()))
        self.assertFalse(any("configuration error" in l for l in logs))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.scn = write_inline_scenario(self.tmp / "scn")
        self.design = make_design(self.tmp, self.scn)
        self.specs = {s.id: s for s in paired.load_specs(self.design)}
        self.cells = evals_run.load_cells(REPO_ROOT / "evals" / "cells.yaml")
        self.suites = evals_run.load_suites()

    def plan(self, **kw):
        args = dict(reps=1, hosts=["opus", "fable"], arms=list(self.design["arms"]), seed=7, budget_usd=None, parallel=6, scenarios={"tiny-demo"})
        args.update(kw)
        return paired.build_plan(self.design, list(self.specs.values()), **args)

    def ctx(self, plan, **kw):
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        snaps = {sid: str(ps.materialize(s, self.tmp / "snaps")) for sid, s in self.specs.items()}
        return paired.Ctx(out=out, design=self.design, cells_doc=self.cells, suites_doc=self.suites, specs=self.specs, snapshots=snaps,
                          plan=plan, campaign_root=self.tmp / "camp", candidate_source=str(REPO_ROOT), candidate_sha="abc", baseline_source=str(REPO_ROOT),
                          seed=7, decide_fn=lambda p, w, c: "cheap", sleep=lambda s: None, **kw)

    def run_it(self, plan, backend, ctx=None, **kw):
        ctx = ctx or self.ctx(plan)
        logs = []
        code = paired.run_campaign(ctx, backend, budget_usd=kw.pop("budget", 10_000), parallel=kw.pop("parallel", 6),
                                   resume=kw.pop("resume", False), policy_config={}, log=logs.append, **kw)
        return ctx, code, logs


class ConfigErrorRunTests(Base):
    def anchors(self):
        return {"tiny-demo-r1-opus-anchor", "tiny-demo-r1-fable-anchor"}

    def cred_backend(self):
        diag = {k: {"error_tail": paired.clean_tail(CRED_TAIL), "model_calls": 0} for k in self.anchors()}
        return FakeBackend(self.tmp / "b", self.specs, always_fail=self.anchors(), diag=diag)

    def test_config_error_is_not_retried_and_stops_the_run_with_exit_4(self):
        be = self.cred_backend()
        plan = self.plan()
        ctx, code, logs = self.run_it(plan, be, parallel=5)
        self.assertEqual(code, paired.EXIT_PRECONDITION)
        waves = paired.State(ctx.out / "state.json").d["waves"]
        failed = [w for w in waves.values() if w["status"] == "config_error"]
        self.assertEqual(len(failed), 1)
        self.assertEqual([a["status"] for a in failed[0]["attempts"]], ["config_error"])      # ONE attempt, not three
        self.assertEqual(len(be.prepared), 1)                                                  # the other wave never launched
        self.assertTrue(any("GOOGLE_API_KEY" in l for l in logs))                              # the error tail is printed
        self.assertTrue(any("No further wave was launched" in l for l in logs))

    def test_the_ledger_survives_a_config_error(self):
        ctx, _, _ = self.run_it(self.plan(), self.cred_backend(), parallel=5)
        led = json.loads((ctx.out / "ledger.json").read_text())
        self.assertEqual(len([k for k in led["spent"] if "#a1" in k]), 1)
        self.assertEqual(led["reserved"], {})

    def test_config_error_attempt_does_not_count_against_the_retry_limit_and_rerun_works(self):
        plan = self.plan(hosts=["opus"])
        ctx, code, _ = self.run_it(plan, self.cred_backend())
        self.assertEqual(code, paired.EXIT_PRECONDITION)
        good = FakeBackend(self.tmp / "b2", self.specs)
        ctx, code, _ = self.run_it(plan, good, ctx=ctx, resume=True)
        self.assertEqual(code, 0)
        w = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual([(a["attempt"], a["status"]) for a in w["attempts"]], [(1, "config_error"), (2, "done")])
        self.assertEqual(w["accepted_attempt"], 2)

    def test_transient_failures_still_retry_up_to_the_limit(self):
        plan = self.plan(hosts=["opus"])
        be = FakeBackend(self.tmp / "b", self.specs, always_fail={"tiny-demo-r1-opus-anchor"})     # default diag: transient
        ctx, code, _ = self.run_it(plan, be)
        w = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual((w["status"], len(w["attempts"]), code), ("excluded", 3, 0))

    def test_launcher_exception_is_a_transient_failure_not_a_crash(self):
        class Flaky(FakeBackend):
            def start(self, root, name):
                if name.endswith("-shipped") and str(root).endswith("-a1"):
                    raise RuntimeError("forge launch failed: Maximum sessions")
                super().start(root, name)

            def wait(self, root, name, timeout):
                if name.endswith("-shipped") and str(root).endswith("-a1"):
                    return False
                return super().wait(root, name, timeout)
        plan = self.plan(hosts=["opus"])
        be = Flaky(self.tmp / "b", self.specs)
        be.barriers = {}
        be.prepare_wave = lambda ctx, root, sessions: (FakeBackend.prepare_wave(be, ctx, root, sessions),
                                                       be.barriers.__setitem__(str(root), __import__("threading").Barrier(1)))[0]
        ctx, code, _ = self.run_it(plan, be)
        w = paired.State(ctx.out / "state.json").wave("tiny-demo-r1-opus")
        self.assertEqual(w["attempts"][0]["status"], "infra_failed")
        self.assertEqual(w["attempts"][0]["failure_kinds"], {"tiny-demo-r1-opus-shipped": "transient"})


class ResetWaveTests(Base):
    def test_reset_makes_an_excluded_wave_runnable_and_keeps_numbering_and_ledger(self):
        plan = self.plan(hosts=["opus"])
        bad = FakeBackend(self.tmp / "b", self.specs, always_fail={"tiny-demo-r1-opus-anchor"})
        ctx, _, _ = self.run_it(plan, bad)
        spent_before = json.loads((ctx.out / "ledger.json").read_text())["spent"]
        self.assertEqual(len(spent_before), 3)
        good = FakeBackend(self.tmp / "b2", self.specs)
        ctx, code, logs = self.run_it(plan, good, ctx=ctx, reset_waves_ids=["tiny-demo-r1-opus"])
        self.assertEqual(code, 0)
        state = paired.State(ctx.out / "state.json")
        w = state.wave("tiny-demo-r1-opus")
        self.assertEqual((w["status"], w["accepted_attempt"]), ("done", 4))                   # numbering continued after a1-a3
        self.assertEqual(len(w["history"]), 1)
        self.assertEqual(len(w["history"][0]["attempts"]), 3)                                  # old attempts archived, not lost
        spent_after = json.loads((ctx.out / "ledger.json").read_text())["spent"]
        self.assertTrue(set(spent_before) <= set(spent_after))
        self.assertTrue(str(good.prepared[0][0]).endswith("w000-a4"))
        self.assertTrue(any("reset wave" in l for l in logs))

    def test_reset_excluded_keyword_and_done_waves_are_refused(self):
        plan = self.plan(hosts=["opus"])
        ctx, _, _ = self.run_it(plan, FakeBackend(self.tmp / "b", self.specs, always_fail={"tiny-demo-r1-opus-anchor"}))
        st = paired.State(ctx.out / "state.json")
        self.assertEqual(paired.reset_waves(st, ["excluded"], lambda *_: None), ["tiny-demo-r1-opus"])
        ctx, code, _ = self.run_it(plan, FakeBackend(self.tmp / "b3", self.specs), ctx=ctx)
        self.assertEqual(code, 0)
        with self.assertRaises(paired.PairedError):
            paired.reset_waves(paired.State(ctx.out / "state.json"), ["tiny-demo-r1-opus"], lambda *_: None)


class PreflightTests(Base):
    def setUp(self):
        super().setUp()
        self.plan_ = self.plan(key_env=None) if False else self.plan()
        self.ctx_ = self.ctx(self.plan_, key_env={"aa": "ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY"})
        self.targets = paired.preflight_targets(self.ctx_)
        self.sessions_root = self.tmp / "sessions"
        patcher = patch.object(paired, "sessions_dir_for_workspace", lambda ws: self.sessions_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def backend(self, **kw):
        def events(name):
            t = self.targets[int(name[2:])]
            return [{"t": 1_800_000_000.0, "model": self.model_for.get(name, t["expected_models"][0]), "uncached": 10, "read": 0, "write": 100, "output": 5}]
        self.model_for = {}
        return FakeBackend(self.tmp / "pf", self.specs, events=events, sessions_root=self.sessions_root, **kw)

    def pf(self, be, **kw):
        led = paired.Ledger(self.ctx_.out / "ledger.json", 100.0)
        logs = []
        rep = paired.run_preflight(self.ctx_, be, led, parallel=6, log=logs.append, provider_info=lambda: {"module": "provider-anthropic", "version": "9.9", "git_sha": "deadbeef"})
        return rep, led, logs

    def test_targets_cover_every_distinct_cell_model_key_including_both_sticky_pin_cells(self):
        got = {(t["cell"], t["model"], t["key_env"]) for t in self.targets}
        self.assertEqual(len(got), len(self.targets))                                     # distinct
        for cell, model in (("plain-opus", "claude-opus-5-5"), ("plain", "claude-fable-5-1"), ("orch-default-opus", "claude-opus-5-5"),
                            ("orch-default", "claude-fable-5-1"), ("orch-pin-host-opus", "claude-opus-5-5"), ("orch-pin-cheap-opus", "claude-opus-5-5"),
                            ("orch-pin-host", "claude-fable-5-1"), ("orch-pin-cheap", "claude-fable-5-1"), ("plain-sonnet", "claude-sonnet-5")):
            self.assertIn((cell, model, None), got, cell)
        self.assertIn(("plain-opus", "claude-opus-5-5", "ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY"), got)   # the second key is its own target
        by = {t["cell"]: t for t in self.targets}
        self.assertEqual(by["orch-pin-cheap-opus"]["expected_models"], ["claude-sonnet-5"])
        self.assertEqual(by["orch-pin-host-opus"]["expected_models"], ["claude-opus-5-5"])
        self.assertEqual(by["orch-default-opus"]["expected_models"], ["claude-opus-5-5", "claude-sonnet-5"])

    def test_passes_records_cost_in_the_ledger_and_writes_the_report(self):
        rep, led, logs = self.pf(self.backend())
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(len(rep["sessions"]), len(self.targets))
        self.assertGreater(rep["total_cost_usd"], 0)
        spent = [v for k, v in led.d["spent"].items() if k.startswith("preflight#")]
        self.assertEqual(len(spent), 1)
        self.assertAlmostEqual(spent[0], rep["total_cost_usd"], places=4)
        saved = json.loads((self.ctx_.out / "preflight.json").read_text())
        self.assertEqual(saved["provider_module"]["git_sha"], "deadbeef")
        self.assertEqual(saved["campaign_provider"]["id"], "campaign-anthropic")
        self.assertNotIn("config", saved["campaign_provider"])        # key names only, never values
        self.assertNotIn("${", json.dumps(saved["campaign_provider"]))
        self.assertTrue(any("preflight PASSED" in l for l in logs))
        self.assertTrue(paired.preflight_is_fresh(self.ctx_))

    def test_wrong_model_response_fails(self):
        be = self.backend()
        i = next(i for i, t in enumerate(self.targets) if t["cell"] == "orch-pin-host-opus")
        rep, _, logs = self.pf(be)
        self.assertTrue(rep["ok"])
        be2 = self.backend()
        be2.model_for = {f"pf{i}": "claude-sonnet-5"}
        events = be2.events
        be2.events = lambda name: [{**r, "model": be2.model_for.get(name, r["model"])} for r in events(name)]
        rep, _, logs = self.pf(be2)
        self.assertFalse(rep["ok"])
        bad = [e for e in rep["sessions"] if not e["passed"]]
        self.assertEqual([e["cell"] for e in bad], ["orch-pin-host-opus"])
        self.assertIn("models seen", bad[0]["error_tail"])

    def test_missing_raw_payload_fails_the_preflight(self):
        be = self.backend()
        base = be.events
        be.events = lambda name: [{**r, "no_raw": True} for r in base(name)]
        rep, _, _ = self.pf(be)
        self.assertFalse(rep["ok"])
        self.assertTrue(all(e["failure_kind"] == "raw_events_missing" for e in rep["sessions"]))
        self.assertIn("raw: true", rep["sessions"][0]["error_tail"])

    def test_the_campaign_provider_turns_raw_events_on(self):
        self.assertIs(paired.load_design()["campaign_provider"]["config"]["raw"], True)

    def test_infra_failure_reports_the_error_tail_and_kind(self):
        diag = {"pf0": {"error_tail": paired.clean_tail(CRED_TAIL), "model_calls": 0}}
        rep, _, logs = self.pf(self.backend(always_fail={"pf0"}, diag=diag))
        self.assertFalse(rep["ok"])
        e = rep["sessions"][0]
        self.assertEqual((e["passed"], e["failure_kind"]), (False, "config_error"))
        self.assertIn("GOOGLE_API_KEY", e["error_tail"])
        self.assertTrue(any("GOOGLE_API_KEY" in l for l in logs))
        self.assertFalse(paired.preflight_is_fresh(self.ctx_))

    def test_freshness_depends_on_targets_and_age(self):
        self.pf(self.backend())
        self.assertTrue(paired.preflight_is_fresh(self.ctx_))
        self.ctx_.key_env = {}
        self.assertFalse(paired.preflight_is_fresh(self.ctx_))                              # key set changed -> stale
        self.ctx_.key_env = {"aa": "ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY"}
        rep = json.loads((self.ctx_.out / "preflight.json").read_text())
        rep["run_at"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        (self.ctx_.out / "preflight.json").write_text(json.dumps(rep))
        self.assertFalse(paired.preflight_is_fresh(self.ctx_))

    def test_run_aborts_before_any_wave_when_preflight_fails(self):
        diag = {"pf0": {"error_tail": paired.clean_tail(CRED_TAIL), "model_calls": 0}}
        be = self.backend(always_fail={"pf0"}, diag=diag)
        with patch.object(paired, "ForgeBackend", lambda: be), patch.object(paired, "_ctx_from_schedule", lambda out, args=None: self.ctx_), \
                patch.object(paired, "RealProbe", FakeProbe), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = paired.main(["run", "--out", str(self.ctx_.out), "--budget-usd", "100", "--parallel", "6"])
        self.assertEqual(code, paired.EXIT_PRECONDITION)
        self.assertEqual(len(be.prepared), 1)                                                # only the preflight root
        self.assertIn("pf-", be.prepared[0][0])
        self.assertIn("preflight FAILED", err.getvalue())
        self.assertFalse((self.ctx_.out / "state.json").exists())                            # no wave state at all

    def test_run_skips_a_fresh_preflight_and_launches_waves(self):
        self.pf(self.backend())
        be = FakeBackend(self.tmp / "w", self.specs)
        with patch.object(paired, "ForgeBackend", lambda: be), patch.object(paired, "_ctx_from_schedule", lambda out, args=None: self.ctx_), \
                patch.object(paired, "RealProbe", FakeProbe), redirect_stdout(io.StringIO()):
            code = paired.main(["run", "--out", str(self.ctx_.out), "--budget-usd", "1000", "--waves", "1", "--parallel", "6"])
        self.assertEqual(code, 0)
        self.assertTrue(all("pf-" not in root for root, _ in be.prepared))
        self.assertEqual(len(be.prepared), 1)

    def test_preflight_ledger_reserve_respects_the_hard_stop(self):
        led = paired.Ledger(self.ctx_.out / "ledger.json", 0.05)
        with self.assertRaises(paired.BudgetExceeded):
            paired.run_preflight(self.ctx_, self.backend(), led, parallel=6, log=lambda *_: None, provider_info=lambda: {})


class CampaignProviderProfileTests(unittest.TestCase):
    """The generated profile declares ONLY the campaign provider, so the user's global provider list is never mounted."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scn = write_inline_scenario(self.tmp / "scn")
        self.spec = ps.load_dir(scn)[0]
        ps.materialize(self.spec, self.tmp / "snaps")
        self.source = {"kind": "paired", "scenario_dir": str(scn), "snapshot_root": str(self.tmp / "snaps"), "ids": [self.spec.id]}
        forge_workloads.register_source(**self.source)
        self.addCleanup(forge_workloads._extra_tasks.clear)
        self.provider = paired.load_design()["campaign_provider"]

    def profiles(self, **cfg):
        sides = {"plain": {"source_root": str(REPO_ROOT), "mode": "off", "model": "claude-opus-5-5"},
                 "fd": {"source_root": str(REPO_ROOT), "mode": "active", "composition": "composed", "model": "claude-opus-5-5", "decision_overrides": {}}}
        prompt = ps.TURN_SEPARATOR.join(ps.turn_prompts(self.spec))
        runs = [{"name": f"t-{a}", "task": self.spec.id, "side": a, "rep": 1, "attempt": 1, "block": None, "seed": 1, "prompt": prompt} for a in sides]
        config = {"runs": runs, "sides": sides, "provider": "anthropic", "model": "claude-opus-5-5", "task_source": self.source,
                  "limits": {"timeout_seconds": 60, "max_iterations": 30, "extended_thinking": True}, "events_dir": str(self.tmp / "ev"), **cfg}
        root = self.tmp / f"r{len(list(self.tmp.glob('r*')))}"
        with patch.object(forge_e2e.subprocess, "run", wraps=forge_e2e.subprocess.run):
            forge_e2e.prepare(root, config)
        return {a: json.loads((root / f"t-{a}" / "profile.md").read_text().split("---\n")[1]) for a in sides}, root

    def test_plain_and_composed_profiles_declare_only_the_campaign_provider(self):
        profs, root = self.profiles(campaign_provider=self.provider)
        for arm, prof in profs.items():
            self.assertEqual([p["id"] for p in prof["providers"]], ["campaign-anthropic"], arm)
            p = prof["providers"][0]
            self.assertEqual((p["module"], p["config"]["api_key"], p["config"]["base_url"]), ("provider-anthropic", "${ANTHROPIC_API_KEY}", "https://api.anthropic.com"))
            self.assertIn("amplifier-module-provider-anthropic", p["source"])
        self.assertEqual(json.loads((root / "manifest.json").read_text())["campaign_provider"]["id"], "campaign-anthropic")

    def test_the_campaign_provider_id_cannot_collide_with_any_global_provider_key(self):
        keys = {None, "provider-anthropic", "anthropic-primary", "anthropic-sonnet", "anthropic-haiku", "runpod", "runpod-kimi"}
        self.assertNotIn(self.provider["id"], keys)
        self.assertTrue(self.provider["id"])

    def test_api_key_is_an_env_reference_never_a_literal(self):
        self.assertRegex(self.provider["config"]["api_key"], r"^\$\{[A-Z_]+\}$")

    def test_without_a_campaign_provider_plain_profiles_are_unchanged(self):
        profs, _ = self.profiles()
        self.assertNotIn("providers", profs["plain"])
        self.assertNotIn("providers", profs["fd"])

    def test_effort_still_merges_into_the_campaign_provider(self):
        profs, _ = self.profiles(campaign_provider=self.provider, amplifier_effort="medium")
        self.assertEqual(profs["plain"]["providers"][0]["config"]["reasoning_effort"], "medium")
        self.assertEqual(profs["plain"]["providers"][0]["id"], "campaign-anthropic")


if __name__ == "__main__":
    unittest.main()
