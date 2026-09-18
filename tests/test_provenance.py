"""HC00 ("freeze source"): package-level source provenance."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from amplifier_fast_decisions import provenance

HAS_GIT = shutil.which("git") is not None


def _git(*args, cwd):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, env=env, text=True
    )


class TreeSha256Tests(unittest.TestCase):
    def test_deterministic_and_ignores_pycache_and_non_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("print(1)\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.py").write_text("print(2)\n", encoding="utf-8")
            (root / "README.md").write_text("ignored\n", encoding="utf-8")
            pycache = root / "__pycache__"
            pycache.mkdir()
            (pycache / "a.cpython-312.pyc").write_bytes(b"\x00\x01")

            first = provenance.tree_sha256(root)
            second = provenance.tree_sha256(root)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 64)

            # Non-.py file must not change the hash.
            (root / "notes.txt").write_text("hello\n", encoding="utf-8")
            self.assertEqual(provenance.tree_sha256(root), first)

            # A .pyc under a nested __pycache__ must not change it either.
            nested_pycache = root / "sub" / "__pycache__"
            nested_pycache.mkdir()
            (nested_pycache / "b.cpython-312.pyc").write_bytes(b"\x00\x01")
            self.assertEqual(provenance.tree_sha256(root), first)

            # Changing a real .py file's content changes the hash.
            (root / "a.py").write_text("print(2)\n", encoding="utf-8")
            self.assertNotEqual(provenance.tree_sha256(root), first)


@unittest.skipUnless(HAS_GIT, "git binary not available")
class GitHeadShaTests(unittest.TestCase):
    def test_returns_none_without_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(provenance.git_head_sha(Path(tmp)))

    def test_plain_repo_and_worktree_agree_on_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git("init", "-q", cwd=repo)
            (repo / "f.txt").write_text("x", encoding="utf-8")
            _git("add", "f.txt", cwd=repo)
            _git("commit", "-q", "-m", "init", cwd=repo)
            head = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
            self.assertEqual(len(head), 40)

            self.assertEqual(provenance.git_head_sha(repo), head)

            # A detached worktree resolves through the .git FILE + commondir,
            # to the same HEAD sha as the main checkout.
            worktree = Path(tmp) / "wt"
            _git("worktree", "add", "--detach", str(worktree), cwd=repo)
            self.assertTrue((worktree / ".git").is_file())
            self.assertEqual(provenance.git_head_sha(worktree), head)


class DescribeSourceTests(unittest.TestCase):
    def test_returns_expected_keys_with_no_filesystem_paths(self):
        provenance.describe_source.cache_clear()
        data = provenance.describe_source()
        for key in (
            "source_kind",
            "source_git_sha",
            "source_tree_sha256",
            "source_py_files",
            "package_version",
        ):
            self.assertIn(key, data)
        self.assertIn(
            data["source_kind"],
            {"installed-cache", "worktree", "site-packages", "unknown"},
        )
        home = str(Path.home())
        for value in data.values():
            if isinstance(value, str):
                self.assertNotIn("/", value)
                self.assertNotIn(home, value)

    def test_source_event_data_never_raises_and_carries_mode_python_module(self):
        data = provenance.source_event_data(mode="shadow", module="hooks-fast-decisions")
        self.assertEqual(data["mode"], "shadow")
        self.assertEqual(data["module"], "hooks-fast-decisions")
        self.assertIn("python", data)
        self.assertIsInstance(data["python"], str)
        self.assertNotIn("/", data["python"])


if __name__ == "__main__":
    unittest.main()
