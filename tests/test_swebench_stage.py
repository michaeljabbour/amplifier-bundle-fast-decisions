"""Tests for evals/swebench/ -- the S3 SWE-bench Verified stage
(STUDY-DESIGN.md section 15). No test invokes a real harness, DTU, Docker,
or the network: sample_swebench's dataset download/parquet load is never
called (only its pure `select_batch`/`build_task_dir` functions are
exercised against fakes), and swebench_stage's preflight subprocess/PATH
probes are injected fakes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SWEBENCH_DIR = REPO_ROOT / "evals" / "swebench"
sys.path.insert(0, str(SWEBENCH_DIR))

import sample_swebench  # noqa: E402
import summarize  # noqa: E402
import swebench_stage  # noqa: E402

REQUIRED_AGENT_FILES = ("meta.yaml", "install.yaml", "invocation.md", "data.yaml")
AGENT_NAMES = ("amplifier-plain", "amplifier-fd-incumbent", "amplifier-fd-candidate")

# Patterns that would indicate a real secret value leaked into a checked-in
# file (as opposed to an env-var reference like ${ANTHROPIC_API_KEY} or a
# YAML comment describing one). Deliberately narrow: it does not flag every
# mention of the word "key".
_SUSPECT_SECRET_RE_STRINGS = ("sk-ant-", "sk-proj-", "AKIA", "ghp_")


class AgentDirsTest(unittest.TestCase):
    def test_all_three_agents_have_required_files(self):
        for name in AGENT_NAMES:
            agent_dir = SWEBENCH_DIR / "agents" / name
            with self.subTest(agent=name):
                self.assertTrue(agent_dir.is_dir(), f"missing agent dir {agent_dir}")
                for fname in REQUIRED_AGENT_FILES:
                    self.assertTrue((agent_dir / fname).is_file(), f"missing {fname} for {name}")

    def test_no_agent_file_contains_a_literal_secret_value(self):
        for name in AGENT_NAMES:
            agent_dir = SWEBENCH_DIR / "agents" / name
            for fname in REQUIRED_AGENT_FILES:
                path = agent_dir / fname
                text = path.read_text(encoding="utf-8")
                for needle in _SUSPECT_SECRET_RE_STRINGS:
                    with self.subTest(agent=name, file=fname, needle=needle):
                        self.assertNotIn(needle, text)
                # api_key must be an env-var reference, never a bare value.
                if "api_key:" in text:
                    for line in text.splitlines():
                        if "api_key:" in line:
                            self.assertIn("${ANTHROPIC_API_KEY}", line)

    def test_amplifier_plain_install_yaml_is_valid_yaml_as_committed(self):
        import yaml

        data = yaml.safe_load((SWEBENCH_DIR / "agents" / "amplifier-plain" / "install.yaml").read_text())
        self.assertIn("setup_cmds", data)
        self.assertIn("requires", data)

    def test_amplifier_fd_incumbent_install_yaml_is_valid_yaml_and_active(self):
        import textwrap

        import yaml

        data = yaml.safe_load((SWEBENCH_DIR / "agents" / "amplifier-fd-incumbent" / "install.yaml").read_text())
        cmd = next(c for c in data["setup_cmds"] if "fd-incumbent-bundle.yaml" in c)
        inner = cmd.split("<<EOF\n", 1)[1].rsplit("\nEOF", 1)[0].replace("{{FD_SHA}}", "deadbeef")
        inner_data = yaml.safe_load(textwrap.dedent(inner))
        cfg = inner_data["session"]["orchestrator"]["config"]
        self.assertEqual(cfg["mode"], "active")
        self.assertEqual(cfg["backend"], "ollama")
        self.assertEqual(cfg["model"], "qwen3:0.6b")
        self.assertEqual(cfg["effort_routing"], {"explore": "low"})

    def test_amplifier_fd_candidate_install_yaml_is_a_template_not_valid_yaml(self):
        """Documented and intentional: the checked-in file is a template,
        never handed to the harness directly (see its own header comment).
        """
        import yaml

        text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        self.assertIn("{{FD_BACKEND}}", text)
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(text)


class CandidateConfigTest(unittest.TestCase):
    def test_placeholder_validates_shape_but_is_unconfirmed(self):
        cfg = swebench_stage.load_candidate_config(SWEBENCH_DIR / "candidate.config.json")
        self.assertEqual(cfg["status"], "unconfirmed")
        for key in swebench_stage.REQUIRED_CANDIDATE_KEYS:
            self.assertIn(key, cfg)

    def test_render_refuses_while_unconfirmed(self):
        cfg = swebench_stage.load_candidate_config(SWEBENCH_DIR / "candidate.config.json")
        template_text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        with self.assertRaises(swebench_stage.CandidateConfigError):
            swebench_stage.render_candidate_install_yaml(cfg, template_text=template_text)

    def test_render_succeeds_once_confirmed_and_produces_valid_yaml(self):
        import textwrap

        import yaml

        cfg = {
            "schema": "fast-decisions-swebench-candidate/v1",
            "status": "confirmed",
            "backend": "ollama",
            "model": "qwen3:0.6b",
            "effort_routing": {"orient": "medium", "explore": "low", "implement": "high"},
            "allow_external_state": False,
        }
        template_text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        rendered = swebench_stage.render_candidate_install_yaml(cfg, template_text=template_text)
        rendered = rendered.replace("{{FD_SHA}}", "cafef00d")
        for placeholder in (
            "{{FD_SHA}}", "{{FD_BACKEND}}", "{{FD_MODEL_LINE}}",
            "{{FD_EFFORT_ROUTING_YAML}}", "{{FD_ALLOW_EXTERNAL_STATE}}", "{{FD_OLLAMA_MODEL}}",
        ):
            self.assertNotIn(placeholder, rendered)

        outer = yaml.safe_load(rendered)
        cmd = next(c for c in outer["setup_cmds"] if "fd-candidate-bundle.yaml" in c)
        inner = cmd.split("<<EOF\n", 1)[1].rsplit("\nEOF", 1)[0]
        inner_data = yaml.safe_load(textwrap.dedent(inner))
        inner_cfg = inner_data["session"]["orchestrator"]["config"]
        self.assertEqual(inner_cfg["backend"], "ollama")
        self.assertEqual(inner_cfg["model"], "qwen3:0.6b")
        self.assertEqual(inner_cfg["effort_routing"]["explore"], "low")
        self.assertEqual(inner_cfg["allow_external_state"], False)

    def test_render_refuses_when_a_required_field_is_still_null(self):
        cfg = {
            "schema": "x",
            "status": "confirmed",
            "backend": None,
            "model": None,
            "effort_routing": None,
            "allow_external_state": None,
        }
        template_text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        with self.assertRaises(swebench_stage.CandidateConfigError):
            swebench_stage.render_candidate_install_yaml(cfg, template_text=template_text)

    def test_render_includes_model_routing_block_when_present(self):
        import textwrap

        import yaml

        cfg = {
            "schema": "fast-decisions-swebench-candidate/v1",
            "status": "confirmed",
            "backend": "ollama",
            "model": "qwen3:0.6b",
            "effort_routing": {"orient": "medium", "explore": "low", "implement": "high"},
            "allow_external_state": False,
            "model_routing": {
                "start_model": "claude-sonnet-5",
                "max_requests_before_escalation": 6,
                "escalate_on_test_failure": True,
                "escalate_on_provider_error": True,
            },
        }
        template_text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        rendered = swebench_stage.render_candidate_install_yaml(cfg, template_text=template_text)
        rendered = rendered.replace("{{FD_SHA}}", "cafef00d")
        self.assertNotIn("{{FD_MODEL_ROUTING_YAML}}", rendered)

        outer = yaml.safe_load(rendered)
        cmd = next(c for c in outer["setup_cmds"] if "fd-candidate-bundle.yaml" in c)
        inner = cmd.split("<<EOF\n", 1)[1].rsplit("\nEOF", 1)[0]
        inner_cfg = yaml.safe_load(textwrap.dedent(inner))["session"]["orchestrator"]["config"]
        self.assertEqual(
            inner_cfg["model_routing"],
            {
                "start_model": "claude-sonnet-5",
                "max_requests_before_escalation": 6,
                "escalate_on_test_failure": True,
                "escalate_on_provider_error": True,
            },
        )

    def test_render_omits_model_routing_block_when_absent(self):
        import textwrap

        import yaml

        cfg = {
            "schema": "fast-decisions-swebench-candidate/v1",
            "status": "confirmed",
            "backend": "ollama",
            "model": "qwen3:0.6b",
            "effort_routing": {"explore": "low"},
            "allow_external_state": False,
        }
        template_text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        rendered = swebench_stage.render_candidate_install_yaml(cfg, template_text=template_text)
        rendered = rendered.replace("{{FD_SHA}}", "cafef00d")
        self.assertNotIn("{{FD_MODEL_ROUTING_YAML}}", rendered)
        self.assertNotIn("model_routing", rendered)

        outer = yaml.safe_load(rendered)
        cmd = next(c for c in outer["setup_cmds"] if "fd-candidate-bundle.yaml" in c)
        inner = cmd.split("<<EOF\n", 1)[1].rsplit("\nEOF", 1)[0]
        inner_cfg = yaml.safe_load(textwrap.dedent(inner))["session"]["orchestrator"]["config"]
        self.assertNotIn("model_routing", inner_cfg)

    def test_render_screen_status_with_env_override_records_candidate_status(self):
        import os
        import tempfile

        cfg_dict = {
            "schema": "fast-decisions-swebench-candidate/v1",
            "status": "screen",
            "cell_name": "judge-local+effort+route",
            "backend": "ollama",
            "model": "qwen3:0.6b",
            "effort_routing": {"orient": "medium", "explore": "low", "implement": "high"},
            "allow_external_state": False,
            "model_routing": {
                "start_model": "claude-sonnet-5",
                "max_requests_before_escalation": 6,
                "escalate_on_test_failure": True,
                "escalate_on_provider_error": True,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg_path = tmp / "candidate.config.json"
            cfg_path.write_text(json.dumps(cfg_dict))
            out_dir = tmp / "rendered-agent"
            old_env = os.environ.get("S3_ALLOW_SCREEN_CANDIDATE")
            os.environ["S3_ALLOW_SCREEN_CANDIDATE"] = "1"
            try:
                swebench_stage.render_candidate_agent_dir(
                    cfg_path,
                    SWEBENCH_DIR / "agents" / "amplifier-fd-candidate",
                    out_dir,
                    fd_sha="0123456789abcdef",
                )
            finally:
                if old_env is None:
                    del os.environ["S3_ALLOW_SCREEN_CANDIDATE"]
                else:
                    os.environ["S3_ALLOW_SCREEN_CANDIDATE"] = old_env

            install_text = (out_dir / "install.yaml").read_text()
            self.assertIn("start_model: claude-sonnet-5", install_text)

            import yaml

            data = yaml.safe_load((out_dir / "data.yaml").read_text())
            self.assertEqual(data["candidate"]["cell_name"], "judge-local+effort+route")
            self.assertEqual(data["candidate"]["candidate_status"], "screen")

    def test_render_refuses_screen_status_without_env_override(self):
        cfg_dict = {
            "schema": "x",
            "status": "screen",
            "backend": "ollama",
            "model": "qwen3:0.6b",
            "effort_routing": {"explore": "low"},
            "allow_external_state": False,
        }
        template_text = (SWEBENCH_DIR / "agents" / "amplifier-fd-candidate" / "install.yaml").read_text()
        with self.assertRaises(swebench_stage.CandidateConfigError):
            swebench_stage.render_candidate_install_yaml(cfg_dict, template_text=template_text)

    def test_render_candidate_agent_dir_writes_a_full_agent(self):
        cfg_dict = {
            "schema": "x",
            "status": "confirmed",
            "backend": "jev",
            "model": None,
            "effort_routing": {"explore": "low"},
            "allow_external_state": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg_path = tmp / "candidate.config.json"
            cfg_path.write_text(json.dumps(cfg_dict))
            out_dir = tmp / "rendered-agent"
            swebench_stage.render_candidate_agent_dir(
                cfg_path,
                SWEBENCH_DIR / "agents" / "amplifier-fd-candidate",
                out_dir,
                fd_sha="0123456789abcdef",
            )
            for fname in REQUIRED_AGENT_FILES:
                self.assertTrue((out_dir / fname).is_file(), fname)
            install_text = (out_dir / "install.yaml").read_text()
            self.assertIn("0123456789abcdef", install_text)
            self.assertIn("backend: jev", install_text)
            for placeholder in (
                "{{FD_SHA}}", "{{FD_BACKEND}}", "{{FD_MODEL_LINE}}",
                "{{FD_EFFORT_ROUTING_YAML}}", "{{FD_ALLOW_EXTERNAL_STATE}}", "{{FD_OLLAMA_MODEL}}",
            ):
                self.assertNotIn(placeholder, install_text)


class SubstituteFdShaTest(unittest.TestCase):
    def test_substitutes_only_files_containing_the_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agents = tmp / "agents"
            shutil.copytree(SWEBENCH_DIR / "agents", agents)
            touched = swebench_stage.substitute_fd_sha_in_agents_dir(agents, "feedface")
            touched_names = {p.parent.name for p in touched}
            self.assertIn("amplifier-fd-incumbent", touched_names)
            self.assertNotIn("amplifier-plain", touched_names)  # never had a placeholder
            self.assertNotIn(
                "{{FD_SHA}}",
                (agents / "amplifier-fd-incumbent" / "install.yaml").read_text(),
            )
            self.assertIn(
                "feedface",
                (agents / "amplifier-fd-incumbent" / "install.yaml").read_text(),
            )


class SampleSweBenchTest(unittest.TestCase):
    """Builds a fake instance list -- no network, no HuggingFace, no
    parquet -- and exercises only the pure selection + task-dir-writing
    functions.
    """

    def _fake_instances(self, n=5):
        return [
            sample_swebench.SWEBenchInstance(
                instance_id=f"astropy__astropy-{1000 + i}",
                repo="astropy/astropy",
                base_commit=f"deadbeef{i:04d}",
                patch="--- a/x.py\n+++ b/x.py\n",
                test_patch="--- a/test_x.py\n+++ b/test_x.py\n",
                problem_statement=f"Fake issue body {i}",
                hints_text="",
                created_at="2024-01-01T00:00:00Z",
                version="5.0",
                fail_to_pass=json.dumps([f"test_x.py::test_{i}"]),
                pass_to_pass=json.dumps(["test_x.py::test_pass_a", "test_x.py::test_pass_b"]),
            )
            for i in range(n)
        ]

    def test_select_batch_prefers_pinned_ids_when_all_resolve(self):
        instances = self._fake_instances(5)
        pinned = [instances[3].instance_id, instances[1].instance_id]
        chosen = sample_swebench.select_batch(instances, n=2, seed=0, pinned_ids=pinned)
        self.assertEqual([c.instance_id for c in chosen], pinned)

    def test_select_batch_falls_back_to_seeded_sample_when_pinned_id_unresolvable(self):
        instances = self._fake_instances(5)
        pinned = ["does-not-exist", instances[1].instance_id]
        chosen = sample_swebench.select_batch(instances, n=2, seed=42, pinned_ids=pinned)
        self.assertEqual(len(chosen), 2)
        # deterministic given the seed
        chosen_again = sample_swebench.select_batch(instances, n=2, seed=42, pinned_ids=None)
        self.assertEqual([c.instance_id for c in chosen], [c.instance_id for c in chosen_again])

    def test_select_batch_raises_when_n_exceeds_available(self):
        instances = self._fake_instances(3)
        with self.assertRaises(SystemExit):
            sample_swebench.select_batch(instances, n=10, seed=0, pinned_ids=None)

    def test_read_pinned_ids_empty_when_missing(self):
        self.assertEqual(sample_swebench.read_pinned_ids(None), [])
        self.assertEqual(sample_swebench.read_pinned_ids(Path("/no/such/file")), [])

    def test_write_and_read_pinned_ids_roundtrip(self):
        instances = self._fake_instances(3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "PINNED"
            sample_swebench.write_pinned_ids(path, instances)
            ids = sample_swebench.read_pinned_ids(path)
            self.assertEqual(ids, [i.instance_id for i in instances])

    def test_build_all_task_dirs_from_a_fake_instance_list(self):
        instances = self._fake_instances(3)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "tasks"
            dirs = sample_swebench.build_all_task_dirs(
                out_dir, instances, parquet_sha256="fakesha", seed=42, pinned=True
            )
            self.assertEqual(len(dirs), 3)
            for i, d in enumerate(dirs, start=1):
                self.assertEqual(d.name, f"swebench-{i}")
                for fname in ("task.yaml", "meta.yaml", "profile.yaml", "grader.yaml"):
                    self.assertTrue((d / fname).is_file(), fname)
                self.assertTrue((d / "workspace" / "problem_statement.md").is_file())
                self.assertTrue((d / "grader-data" / "instance.json").is_file())
                instance_record = json.loads((d / "grader-data" / "instance.json").read_text())
                self.assertEqual(instance_record["instance_id"], instances[i - 1].instance_id)
                self.assertEqual(instance_record["fail_to_pass_count"], 1)
                self.assertEqual(instance_record["pass_to_pass_count"], 2)
                # profile.yaml has the concrete repo URL and base commit
                # baked in as literal values -- no ${...} launch-var
                # placeholder left for run.sh/the DTU CLI to resolve later
                # (this is exactly the substitution the S3 harness never
                # performed, causing "repository does not exist" at
                # provisioning for all 90 trials).
                profile_text = (d / "profile.yaml").read_text()
                instance = instances[i - 1]
                self.assertIn(
                    f"git clone https://github.com/{instance.repo}.git /workspace/repo",
                    profile_text,
                )
                self.assertIn(
                    f"git -C /workspace/repo checkout {instance.base_commit}",
                    profile_text,
                )
                self.assertNotIn("${", profile_text)
                grader_text = (d / "grader.yaml").read_text()
                self.assertIn("--dataset verified", grader_text)
                self.assertIn(f"{d.name}/grader-data/instance.json", grader_text)

    def test_count_tests_handles_malformed_and_empty_json(self):
        self.assertEqual(sample_swebench._count_tests(""), 0)
        self.assertEqual(sample_swebench._count_tests("not json"), 0)
        self.assertEqual(sample_swebench._count_tests(json.dumps(["a", "b"])), 2)
        self.assertEqual(sample_swebench._count_tests(json.dumps({"not": "a list"})), 0)

    def test_profile_yaml_renders_concrete_values_with_no_unresolved_placeholders(self):
        """Regression test for the S3 provisioning failure: all 90 trials
        failed in ~10s at `git clone ${SWE_REPO_1} /workspace/repo` because
        the ${SWE_REPO_N}/${SWE_COMMIT_N} launch-var placeholders were
        never substituted (run.sh never built the --launch-var flags for
        them). _profile_yaml now takes the concrete repo URL and base
        commit directly and bakes them into the clone/checkout lines --
        assert no ${...} placeholder survives rendering and the exact
        clone/checkout commands carry the real values.
        """
        rendered = sample_swebench._profile_yaml(
            "swebench-7",
            "https://github.com/django/django.git",
            "abc123def456",
        )
        self.assertNotIn("${", rendered)
        self.assertIn(
            "git clone https://github.com/django/django.git /workspace/repo",
            rendered,
        )
        self.assertIn(
            "git -C /workspace/repo checkout abc123def456",
            rendered,
        )


class UnresolvedPlaceholderTest(unittest.TestCase):
    """swebench_stage.find_unresolved_placeholders / check_preflight's
    tasks_dir wiring -- the guard against this exact class of regression
    reappearing (a generated profile.yaml still carrying a ${...}
    launch-var placeholder that nothing will ever substitute).
    """

    def test_empty_dict_when_tasks_dir_absent(self):
        missing = swebench_stage.find_unresolved_placeholders(Path("/no/such/dir"))
        self.assertEqual(missing, {})

    def test_empty_dict_when_all_profiles_fully_resolved(self):
        instances = [
            sample_swebench.SWEBenchInstance(
                instance_id="astropy__astropy-1000",
                repo="astropy/astropy",
                base_commit="deadbeef0000",
                patch="",
                test_patch="",
                problem_statement="fake",
                hints_text="",
                created_at="2024-01-01T00:00:00Z",
                version="5.0",
                fail_to_pass="[]",
                pass_to_pass="[]",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "tasks"
            sample_swebench.build_all_task_dirs(out_dir, instances)
            missing = swebench_stage.find_unresolved_placeholders(out_dir)
            self.assertEqual(missing, {})

    def test_detects_unresolved_placeholder_in_a_generated_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = Path(tmp) / "tasks"
            task_dir = tasks_dir / "swebench-1"
            task_dir.mkdir(parents=True)
            (task_dir / "profile.yaml").write_text(
                "provision:\n"
                "  setup_cmds:\n"
                "    - git clone ${SWE_REPO_1} /workspace/repo\n"
                "    - git -C /workspace/repo checkout ${SWE_COMMIT_1}\n"
            )
            missing = swebench_stage.find_unresolved_placeholders(tasks_dir)
            self.assertEqual(len(missing), 1)
            [(path, placeholders)] = missing.items()
            self.assertTrue(path.endswith("swebench-1/profile.yaml"))
            self.assertEqual(
                sorted(placeholders), ["${SWE_COMMIT_1}", "${SWE_REPO_1}"]
            )

    def test_check_preflight_fails_loudly_on_unresolved_task_profile_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = Path(tmp) / "tasks"
            task_dir = tasks_dir / "swebench-1"
            task_dir.mkdir(parents=True)
            (task_dir / "profile.yaml").write_text(
                "provision:\n"
                "  setup_cmds:\n"
                "    - git clone ${SWE_REPO_1} /workspace/repo\n"
            )
            report = swebench_stage.check_preflight(
                which=lambda name: f"/usr/bin/{name}",
                run_cmd=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
                env={"ANTHROPIC_API_KEY": "x"},
                tasks_dir=tasks_dir,
            )
            self.assertFalse(report["ok"])
            self.assertFalse(report["checks"]["task-profile-placeholders"]["ok"])
            self.assertIn(
                "SWE_REPO_1", report["checks"]["task-profile-placeholders"]["detail"]
            )

    def test_check_preflight_passes_when_tasks_dir_not_yet_generated(self):
        report = swebench_stage.check_preflight(
            which=lambda name: f"/usr/bin/{name}",
            run_cmd=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
            env={"ANTHROPIC_API_KEY": "x"},
            tasks_dir=Path("/no/such/dir"),
        )
        self.assertTrue(report["checks"]["task-profile-placeholders"]["ok"])


class SummarizeTest(unittest.TestCase):
    def _fake_summary(self, trials):
        return {"run_id": "fake-run", "counts": {}, "trials": trials}

    def _passing_trial(self, task_id="swebench-1", agent_id="amplifier-plain", trial_number=1):
        return {
            "trial_id": f"{agent_id}__{task_id}__trial-{trial_number}",
            "agent_id": agent_id,
            "task_id": task_id,
            "trial_number": trial_number,
            "state": "completed",
            "dtu_id": "dtu-abc123",
            "elapsed_s": 812.5,
            "error": None,
            "grader": {
                "status": "ok",
                "overall_score": 1.0,
                "evaluations": [{"name": "swebench-resolved", "score": 1.0, "weight": 1.0}],
                "elapsed_s": 120.0,
            },
        }

    def _failing_trial(self):
        t = self._passing_trial(agent_id="amplifier-fd-candidate")
        t["grader"]["overall_score"] = 0.0
        t["grader"]["evaluations"] = [{"name": "swebench-resolved", "score": 0.0, "weight": 1.0}]
        return t

    def test_outcome_passed_true_only_on_full_score(self):
        self.assertTrue(summarize._outcome_passed(self._passing_trial()))
        self.assertFalse(summarize._outcome_passed(self._failing_trial()))

    def test_outcome_passed_false_when_grader_failed_or_eval_missing(self):
        t = self._passing_trial()
        t["grader"] = {"status": "failed", "error": "boom"}
        self.assertFalse(summarize._outcome_passed(t))

        t2 = self._passing_trial()
        t2["grader"]["evaluations"] = [{"name": "some-other-eval", "score": 1.0, "weight": 1.0}]
        self.assertFalse(summarize._outcome_passed(t2))

    def test_cost_extraction_missing_ai_user_json_is_null_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "trial-1"
            trial_dir.mkdir()
            cost, source = summarize._extract_cost_from_trial_dir(trial_dir)
            self.assertIsNone(cost)
            self.assertEqual(source, "unknown")

    def test_cost_extraction_reads_cost_when_present_in_ai_user_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "trial-1"
            trial_dir.mkdir()
            (trial_dir / "ai_user.json").write_text(json.dumps({"verdict": "success", "cost_usd": 0.42}))
            cost, source = summarize._extract_cost_from_trial_dir(trial_dir)
            self.assertEqual(cost, 0.42)
            self.assertEqual(source, "ai_user_json")

    def test_summarize_trial_maps_all_expected_fields(self):
        trial = self._passing_trial()
        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / trial["trial_id"]
            trial_dir.mkdir()
            row = summarize.summarize_trial(trial, trial_dir)

        self.assertEqual(row["task"], "swebench-1")
        self.assertEqual(row["harness"], "amplifier-plain")
        self.assertTrue(row["outcome_passed"])
        self.assertEqual(row["exec_time_ms"], 812.5 * 1000.0)
        self.assertEqual(row["exec_time_source"], "harness_elapsed_s")
        self.assertEqual(row["wall_time_ms"], row["exec_time_ms"])
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(row["cost_source"], "unknown")
        self.assertFalse(row["cost_billable"])
        self.assertEqual(row["dtu_id"], "dtu-abc123")
        self.assertEqual(row["state"], "completed")
        self.assertEqual(row["notes"], [])

    def test_summarize_trial_notes_grader_failure_and_trial_error(self):
        trial = self._passing_trial()
        trial["grader"] = {"status": "failed", "error": "harness timed out"}
        trial["state"] = "failed"
        trial["error"] = "TimeoutError: boom"
        with tempfile.TemporaryDirectory() as tmp:
            row = summarize.summarize_trial(trial, Path(tmp) / "nonexistent-trial-dir")
        self.assertFalse(row["outcome_passed"])
        self.assertTrue(any(n.startswith("grader_failed:") for n in row["notes"]))
        self.assertTrue(any(n.startswith("trial_state:") for n in row["notes"]))
        self.assertTrue(any(n.startswith("trial_error:") for n in row["notes"]))

    def test_summarize_run_produces_one_row_per_trial_and_matches_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            trials_dir = tmp / "trials"
            passing = self._passing_trial()
            failing = self._failing_trial()
            for t in (passing, failing):
                d = trials_dir / t["trial_id"]
                d.mkdir(parents=True)
            (trials_dir / failing["trial_id"] / "ai_user.json").write_text(
                json.dumps({"cost_usd": 1.23})
            )

            rows = summarize.summarize_run(self._fake_summary([passing, failing]), trials_dir)
            self.assertEqual(len(rows), 2)
            by_harness = {r["harness"]: r for r in rows}
            self.assertTrue(by_harness["amplifier-plain"]["outcome_passed"])
            self.assertFalse(by_harness["amplifier-fd-candidate"]["outcome_passed"])
            self.assertEqual(by_harness["amplifier-fd-candidate"]["cost_usd"], 1.23)
            self.assertEqual(by_harness["amplifier-fd-candidate"]["cost_source"], "ai_user_json")
            self.assertIsNone(by_harness["amplifier-plain"]["cost_usd"])

    def test_main_writes_rows_file_and_reports_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            output_dir = tmp / "run-output"
            trials_dir = output_dir / "trials"
            passing = self._passing_trial()
            (trials_dir / passing["trial_id"]).mkdir(parents=True)
            output_dir.mkdir(exist_ok=True)
            (output_dir / "summary.json").write_text(json.dumps(self._fake_summary([passing])))

            out_path = tmp / "rows.json"
            rc = summarize.main(["--output-dir", str(output_dir), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            rows = json.loads(out_path.read_text())
            self.assertEqual(len(rows), 1)

    def test_main_reports_error_when_summary_json_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = summarize.main(["--output-dir", tmp, "--out", str(Path(tmp) / "rows.json")])
            self.assertEqual(rc, 1)


class PreflightCheckTest(unittest.TestCase):
    """run.sh --check delegates entirely to swebench_stage.check_preflight;
    this is that function's own testable-pure-function surface, exercised
    with injected fakes -- no real subprocess, PATH lookup, or file read of
    host state.
    """

    def _which_all_present(self, name):
        return f"/usr/bin/{name}"

    def _which_none(self, name):
        return None

    def _run_cmd_ok(self, argv):
        return subprocess.CompletedProcess(argv, 0, "", "")

    def _run_cmd_fails(self, argv):
        return subprocess.CompletedProcess(argv, 1, "", "docker daemon not running")

    def test_all_green_when_everything_present(self):
        report = swebench_stage.check_preflight(
            which=self._which_all_present,
            run_cmd=self._run_cmd_ok,
            env={"ANTHROPIC_API_KEY": "x"},
        )
        self.assertTrue(report["ok"])
        for name, check in report["checks"].items():
            self.assertTrue(check["ok"], f"{name}: {check['detail']}")

    def test_fails_overall_when_a_tool_is_missing(self):
        report = swebench_stage.check_preflight(
            which=self._which_none,
            run_cmd=self._run_cmd_ok,
            env={"ANTHROPIC_API_KEY": "x"},
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["tool:docker"]["ok"])

    def test_fails_overall_when_docker_daemon_not_running(self):
        report = swebench_stage.check_preflight(
            which=self._which_all_present,
            run_cmd=self._run_cmd_fails,
            env={"ANTHROPIC_API_KEY": "x"},
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["docker-running"]["ok"])

    def test_fails_overall_when_anthropic_key_missing(self):
        report = swebench_stage.check_preflight(
            which=self._which_all_present,
            run_cmd=self._run_cmd_ok,
            env={},
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["env:ANTHROPIC_API_KEY"]["ok"])

    def test_typesafe_key_optional_never_fails_preflight(self):
        report = swebench_stage.check_preflight(
            which=self._which_all_present,
            run_cmd=self._run_cmd_ok,
            env={"ANTHROPIC_API_KEY": "x"},
        )
        self.assertTrue(report["checks"]["env:TYPESAFE_API_KEY"]["ok"])

    def test_pinned_ids_check_counts_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "PINNED"
            path.write_text("a\nb\nc\n")
            report = swebench_stage.check_preflight(
                which=self._which_all_present,
                run_cmd=self._run_cmd_ok,
                env={"ANTHROPIC_API_KEY": "x"},
                pinned_ids_path=path,
            )
            self.assertFalse(report["checks"]["pinned-instance-ids"]["ok"])
            self.assertIn("3 id(s)", report["checks"]["pinned-instance-ids"]["detail"])

    def test_pinned_ids_check_passes_with_the_shipped_file(self):
        report = swebench_stage.check_preflight(
            which=self._which_all_present,
            run_cmd=self._run_cmd_ok,
            env={"ANTHROPIC_API_KEY": "x"},
            pinned_ids_path=SWEBENCH_DIR / "PINNED_INSTANCE_IDS",
        )
        self.assertTrue(report["checks"]["pinned-instance-ids"]["ok"])

    def test_candidate_config_check_reports_unconfirmed_without_failing_preflight(self):
        report = swebench_stage.check_preflight(
            which=self._which_all_present,
            run_cmd=self._run_cmd_ok,
            env={"ANTHROPIC_API_KEY": "x"},
            candidate_config_path=SWEBENCH_DIR / "candidate.config.json",
        )
        self.assertTrue(report["checks"]["candidate-config"]["ok"])
        self.assertIn("unconfirmed", report["checks"]["candidate-config"]["detail"])

    def test_candidate_config_check_fails_on_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.config.json"
            path.write_text("not json")
            report = swebench_stage.check_preflight(
                which=self._which_all_present,
                run_cmd=self._run_cmd_ok,
                env={"ANTHROPIC_API_KEY": "x"},
                candidate_config_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertFalse(report["checks"]["candidate-config"]["ok"])


class GradePyTest(unittest.TestCase):
    """grade.py is a copied, mostly-unmodified host-side wrapper (real
    invocation requires the swebench PyPI package + Docker); this only
    checks the one thing this stage changed (the default --dataset) and
    that it still exposes --dataset verified as a valid choice, without
    invoking main() (which shells out to python -m swebench.harness...).
    """

    def test_default_dataset_is_verified(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("swebench_grade", SWEBENCH_DIR / "grade.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn("verified", module._DATASETS)
        self.assertEqual(module._DATASETS["verified"], ("princeton-nlp/SWE-bench_Verified", "test"))


if __name__ == "__main__":
    unittest.main()
