"""build_state keeps the head AND tail of an over-budget task and drops host reminders."""
from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.contracts import canonical
from amplifier_fast_decisions.state import build_state

RULES = "You are working in a git checkout. Rules: " + "follow the rules. " * 40
ISSUE_END = "Fix: the parser must reject trailing commas. END-OF-ISSUE"


def req(*texts):
    return NS(messages=[{"role": "user", "content": t} for t in texts])


def task_text(state):
    return state["observations"][0]["text"]


class TaskClipTests(unittest.TestCase):
    def test_long_swe_prompt_keeps_issue_tail(self):
        prompt = RULES + "\n\nIssue: " + ("details " * 300) + ISSUE_END
        stats: dict = {}
        state = build_state(req(prompt), 2048, stats)
        text = task_text(state)
        self.assertTrue(text.endswith(ISSUE_END))
        self.assertTrue(text.startswith("You are working"))
        self.assertRegex(text, r"…\[\d+ chars omitted\]…")
        self.assertLessEqual(len(canonical(state)), 2048)
        self.assertEqual(stats["observations_clipped"], 1)
        self.assertTrue(stats["task_anchored"])

    def test_tail_share_is_larger_than_head(self):
        text = task_text(build_state(req("H" * 5000 + "T" * 5000), 2048))
        self.assertGreater(text.count("T"), text.count("H"))

    def test_reminder_prefixed_prompt_keeps_real_task(self):
        reminder = "<system-reminders>\nhost boilerplate " + "x" * 3000 + "\n</system-reminders>\n"
        single = "<system-reminder source=\"a\">note</system-reminder>"
        state = build_state(req(reminder + single + "Fix the real bug in foo.py"), 2048)
        self.assertEqual(task_text(state), "Fix the real bug in foo.py")

    def test_short_task_unchanged(self):
        state = build_state(req("read foo.py"), 12000)
        self.assertEqual(task_text(state), "read foo.py")

    def test_budget_never_exceeded(self):
        for max_chars in (400, 700, 1024, 2048, 5000):
            for size in (10, 300, 1000, 2500, 9000, 50000):
                prompt = ("a" * (size // 2)) + ISSUE_END + ("b" * (size // 2))
                for messages in ((prompt,), (prompt, "second message " * 50)):
                    try:
                        state = build_state(req(*messages), max_chars)
                    except ValueError:
                        continue
                    self.assertLessEqual(len(canonical(state)), max_chars, (max_chars, size))


if __name__ == "__main__":
    unittest.main()
