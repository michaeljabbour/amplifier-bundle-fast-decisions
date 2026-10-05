"""The published skill must agree with the CLI it documents."""
import json
import re
import tomllib
import unittest
from pathlib import Path

from amplifier_fast_decisions import __version__, smart_tool
from amplifier_fast_decisions.smart_cli import main

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "amplifier-fast-decisions" / "SKILL.md"


class SkillParity(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")
        self.front = re.match(r"---\n(.*?)\n---\n", self.text, re.S).group(1)

    def test_frontmatter_follows_skills_spec(self):
        name = re.search(r"^name:\s*(.+)$", self.front, re.M).group(1).strip("\"'")
        desc = json.loads(re.search(r"^description:\s*(.+)$", self.front, re.M).group(1))
        self.assertEqual(name, SKILL.parent.name)
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), 64)
        self.assertTrue(0 < len(desc) <= 1024, len(desc))

    def test_versions_agree(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], __version__)
        self.assertEqual(smart_tool.manifest()["version"], __version__)
        minimum = re.search(r"should print (\d+\.\d+\.\d+) or later", self.text).group(1)
        self.assertEqual(minimum, __version__)

    def test_install_line_matches_generated_skill(self):
        self.assertIn(smart_tool.INSTALL_LINE, self.text)
        self.assertIn(smart_tool.INSTALL_LINE, smart_tool.agent_skill())

    def test_every_named_command_exists(self):
        for cmd in ("doctor", "decide", "launch", "select", "search", "cua"):
            self.assertIn(cmd, smart_tool.CAPABILITIES)
            self.assertIn(f"`{cmd}", self.text)
        for harness in re.search(r"--harness ([a-z|]+)", self.text).group(1).split("|"):
            from amplifier_fast_decisions import launch
            self.assertIn(harness, launch.HARNESSES)

    def test_version_flag(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["--version"]), 0)
        self.assertEqual(buf.getvalue().strip(), __version__)


if __name__ == "__main__":
    unittest.main()
