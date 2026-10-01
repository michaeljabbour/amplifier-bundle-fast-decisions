"""_judge_state's task_prompt_head is the real task, not the reminder envelope."""
from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.contracts import TurnState
from amplifier_fast_decisions.orchestrator import _judge_state


class JudgeStateTaskHeadTests(unittest.TestCase):
    def test_reminder_first_message_is_skipped(self):
        request = NS(messages=[
            {"role": "user", "content": "<system-reminders>\nNOT from the user\n</system-reminders>"},
            {"role": "user", "content": "<system-reminder source=\"x\">n</system-reminder>Fix foo.py"},
        ])
        state = _judge_state(request, TurnState("t1"), "act", 12000)
        self.assertEqual(state["task_prompt_head"], "Fix foo.py")

    def test_plain_first_message_unchanged(self):
        request = NS(messages=[{"role": "user", "content": "Do the thing"}])
        self.assertEqual(_judge_state(request, TurnState("t1"), "act", 12000)["task_prompt_head"], "Do the thing")

    def test_long_task_keeps_head_and_tail(self):
        task = "RULES " * 100 + "THE-ISSUE-END"
        request = NS(messages=[{"role": "user", "content": task}])
        head = _judge_state(request, TurnState("t1"), "act", 12000)["task_prompt_head"]
        self.assertLessEqual(len(head), 300)
        self.assertTrue(head.startswith("RULES"))
        self.assertTrue(head.endswith("THE-ISSUE-END"))
        self.assertIn("chars omitted", head)

    def test_multi_turn_uses_latest_turn_message(self):
        request = NS(messages=[{"role": "user", "content": "first task"},
                               {"role": "assistant", "content": "ok"},
                               {"role": "user", "content": "second task"}])
        self.assertEqual(_judge_state(request, TurnState("t1"), "act", 12000)["task_prompt_head"], "second task")


if __name__ == "__main__":
    unittest.main()
