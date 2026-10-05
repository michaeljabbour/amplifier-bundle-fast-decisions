"""Per-session cache nonce: unique per session, leads the system instruction, identical prompts across arms
(hash-verified), stable across --resume turns; plus the per-turn gap / per-turn grade / per-side model path of the
spec worker and per-arm API key selection. Uses the real forge_e2e.prepare; no model, no network."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from paired_helpers import REPO_ROOT, paired, ps, write_inline_scenario

import forge_e2e
import forge_workloads

BASE_INSTRUCTION = "@foundation:context/shared/common-system-base.md"


class NonceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scn = write_inline_scenario(self.tmp / "scn")
        self.spec = ps.load_dir(scn)[0]
        ps.materialize(self.spec, self.tmp / "snaps")
        self.source = {"kind": "paired", "scenario_dir": str(scn), "snapshot_root": str(self.tmp / "snaps"), "ids": [self.spec.id]}
        forge_workloads.register_source(**self.source)
        self.addCleanup(forge_workloads._extra_tasks.clear)

    def prepare(self, nonces, sides=None):
        sides = sides or {
            "anchor": {"source_root": str(REPO_ROOT), "mode": "off", "model": "claude-opus-5-5"},
            "aa": {"source_root": str(REPO_ROOT), "mode": "off", "model": "claude-opus-5-5"},
            "shipped": {"source_root": str(REPO_ROOT), "mode": "active", "composition": "composed", "model": "claude-opus-5-5",
                        "decision_overrides": {}}}
        prompt = ps.TURN_SEPARATOR.join(ps.turn_prompts(self.spec))
        runs = [{"name": f"tiny-{arm}", "task": self.spec.id, "side": arm, "rep": 1, "attempt": 1, "block": None, "seed": 1,
                 "nonce": nonces.get(arm), "prompt": prompt, "deadline_seconds": 60} for arm in sides]
        config = {"runs": runs, "sides": sides, "provider": "anthropic", "model": "claude-opus-5-5",
                  "limits": {"timeout_seconds": 60, "max_iterations": 30, "extended_thinking": True}, "task_source": self.source,
                  "events_dir": str(self.tmp / "ev")}
        root = self.tmp / f"root{len(list(self.tmp.glob('root*')))}"
        with patch.object(forge_e2e, "_base_instruction", lambda p: BASE_INSTRUCTION):
            return root, forge_e2e.prepare(root, config)

    def test_nonce_leads_the_instruction_and_is_unique(self):
        nonces = {"anchor": "n-1", "aa": "n-2", "shipped": "n-3"}
        root, man = self.prepare(nonces)
        for arm, n in nonces.items():
            body = (root / f"tiny-{arm}" / "profile.md").read_text().split("\n---\n", 1)[1]
            self.assertTrue(body.startswith(f"run-nonce: {n}\n"), arm)
            self.assertIn(BASE_INSTRUCTION, body)              # the instruction a root body would REPLACE is preserved
            self.assertEqual(man["runs"][f"tiny-{arm}"]["nonce"], n)
        self.assertEqual(len({man["runs"][k]["nonce"] for k in man["runs"]}), 3)

    def test_prompts_identical_across_arms_and_only_the_nonce_differs(self):
        root, man = self.prepare({"anchor": "n-1", "aa": "n-2", "shipped": "n-3"})
        self.assertEqual(len({r["prompt_sha256"] for r in man["runs"].values()}), 1)
        self.assertEqual(man["runs"]["tiny-anchor"]["prompt_sha256"], hashlib.sha256(
            ps.TURN_SEPARATOR.join(ps.turn_prompts(self.spec)).encode()).hexdigest())
        a, b = (man["runs"][f"tiny-{x}"]["profile_sans_nonce_sha256"] for x in ("anchor", "aa"))
        # the two plain anchors differ only in workspace-local paths and the nonce; their instruction bodies match
        body = lambda arm: (root / f"tiny-{arm}" / "profile.md").read_text().split("\n---\n", 1)[1]
        self.assertEqual(body("anchor").replace("n-1", "N"), body("aa").replace("n-2", "N"))
        self.assertTrue(a and b)

    def test_no_nonce_leaves_the_profile_body_empty(self):
        root, man = self.prepare({})
        self.assertEqual((root / "tiny-anchor" / "profile.md").read_text().split("\n---\n", 1)[1].strip(), "")
        self.assertNotIn("nonce", man["runs"]["tiny-anchor"])

    def test_workspaces_start_from_the_identical_snapshot(self):
        root, man = self.prepare({"anchor": "a", "aa": "b", "shipped": "c"})
        self.assertEqual(len({r["workspace_hash"] for r in man["runs"].values()}), 1)
        snap_hash = ps.tree_hash(Path(forge_workloads.task_snapshot(self.spec.id)) / "workspace")
        self.assertEqual(len(snap_hash), 64)


class FakePopen:
    """Stands in for `amplifier run` : the first turn creates the session dir, every call writes a JSON response."""
    calls: list = []
    sessions: Path = None

    def __init__(self, command, cwd=None, env=None, stdout=None):
        FakePopen.calls.append({"command": command, "env": env})
        n = len(FakePopen.calls)
        if n == 1:
            sdir = FakePopen.sessions / "sid-123"
            sdir.mkdir(parents=True)
            (sdir / "events.jsonl").write_text("{}\n")
        if n == 1 and cwd:
            (Path(cwd) / "solution.py").write_text("def f():\n    return 1\n")
        if n == 3 and cwd:
            (Path(cwd) / "NOTES.md").write_text("## Usage\n")
        stdout.write(json.dumps({"response": "It will return 1. DONE: ok"}))
        stdout.flush()
        self.pid = 4242

    def wait(self, timeout=None):
        return 0


class SpecWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scn = write_inline_scenario(self.tmp / "scn")
        self.spec = ps.load_dir(scn)[0]
        self.snap = ps.materialize(self.spec, self.tmp / "snaps")
        self.run = self.tmp / "run"
        self.ws = self.run / "workspace"
        shutil.copytree(self.snap / "workspace", self.ws)
        (self.run).mkdir(exist_ok=True)
        (self.run / "profile.md").write_text("---\n{}\n---\nrun-nonce: n-9\n\n" + BASE_INSTRUCTION + "\n")
        FakePopen.calls, FakePopen.sessions = [], self.tmp / "sessions"
        FakePopen.sessions.mkdir()
        task = type("T", (), {"spec": (self.spec, str(self.snap))})()
        self.args = dict(root=self.tmp, name="n", manifest={"provider": "anthropic", "model": "host-model", "limits": {"timeout_seconds": 5},
                                                             "sides": {"s": {"model": "side-model"}}, "host_python": "python3"},
                         item={"side": "s", "prompt": ps.TURN_SEPARATOR.join(ps.turn_prompts(self.spec)), "attempt": 1},
                         task=task, workspace=self.ws, sessions=FakePopen.sessions, env={}, run=self.run)

    def run_turns(self):
        sleeps = []
        shim = types.SimpleNamespace(Popen=FakePopen, TimeoutExpired=subprocess.TimeoutExpired, run=subprocess.run)
        with patch.object(forge_e2e, "subprocess", shim), patch.object(forge_e2e.time, "sleep", sleeps.append):
            turns, sid = forge_e2e._run_scenario_turns(**self.args)
        return turns, sid, sleeps

    def test_turn_gaps_resume_model_and_stable_profile(self):
        turns, sid, sleeps = self.run_turns()
        self.assertEqual(sid, "sid-123")
        sleeps = [s for s in sleeps if s >= 1]                         # memguard polls with 0.25 s sleeps; gaps are >= 1 s
        self.assertEqual(sleeps, [10, 420])                            # turn 1 has no gap; turns 2,3 as scripted
        cmds = [c["command"] for c in FakePopen.calls]
        self.assertEqual(len({c[c.index("--bundle") + 1] for c in cmds}), 1)           # same profile (same nonce) every turn
        self.assertTrue(all(c[c.index("--model") + 1] == "side-model" for c in cmds))  # per-side model
        self.assertNotIn("--resume", cmds[0])
        self.assertTrue(all(c[c.index("--resume") + 1] == "sid-123" for c in cmds[1:]))
        self.assertEqual([c[-1] for c in cmds], ps.turn_prompts(self.spec))             # byte-identical scripted prompts
        self.assertEqual([t["gap_before_s"] for t in turns], [0, 10, 420])

    def test_each_turn_is_graded_and_snapshotted_right_after_it_ends(self):
        turns, _, _ = self.run_turns()
        self.assertTrue(all(t["turn_passed"] for t in turns), [t["quality"] for t in turns])
        for i in (1, 2, 3):
            self.assertTrue((self.run / "turn-snapshots" / f"t{i}.tar.gz").exists())
        # turn 1 was graded before NOTES.md existed: its snapshot must not contain it
        import tarfile
        with tarfile.open(self.run / "turn-snapshots" / "t1.tar.gz") as tf:
            names = tf.getnames()
        self.assertFalse(any(n.endswith("NOTES.md") for n in names))
        with tarfile.open(self.run / "turn-snapshots" / "t3.tar.gz") as tf:
            self.assertTrue(any(n.endswith("NOTES.md") for n in tf.getnames()))

    def test_prompt_mismatch_refuses_to_launch(self):
        self.args["item"]["prompt"] = "something else"
        with self.assertRaises(SystemExit):
            self.run_turns()
        self.assertEqual(FakePopen.calls, [])


class ApiKeySelectionTests(unittest.TestCase):
    def test_per_arm_key_sets_both_provider_vars_and_returns_only_a_fingerprint(self):
        env = {"ANTHROPIC_API_KEY": "key-one"}
        src = {"ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY": "key-two", "ANTHROPIC_API_KEY": "key-one"}
        fp = forge_e2e._apply_side_api_key(env, {"api_key_env": "ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY"}, src)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "key-two")
        self.assertEqual(env["ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY"], "key-two")
        self.assertEqual(fp, hashlib.sha256(b"key-two").hexdigest()[:10])
        self.assertNotIn("key-two", fp)

    def test_no_override_keeps_the_ambient_key(self):
        env = {"ANTHROPIC_API_KEY": "key-one"}
        self.assertEqual(forge_e2e._apply_side_api_key(env, {}, {}), hashlib.sha256(b"key-one").hexdigest()[:10])
        self.assertEqual(env["ANTHROPIC_API_KEY"], "key-one")

    def test_missing_env_var_fails_loud(self):
        with self.assertRaises(SystemExit):
            forge_e2e._apply_side_api_key({}, {"api_key_env": "NOPE"}, {})

    def test_plan_checks_key_env_names_only(self):
        names = paired.key_env_names_available()
        self.assertIsInstance(names, set)
        self.assertTrue(all(isinstance(n, str) for n in names))


if __name__ == "__main__":
    unittest.main()
