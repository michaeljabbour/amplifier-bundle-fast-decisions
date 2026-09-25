"""Per-step receipts: what each model call produced (tool calls / final answer)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from amplifier_fast_decisions.orchestrator import step_fields
from amplifier_fast_decisions.privacy import safe_data


class StepFieldsTests(unittest.TestCase):
    def test_tool_call_step(self):
        r = NS(tool_calls=[NS(name="bash", arguments={"command": "SECRET ls"}), NS(name="read_file", arguments={})],
               finish_reason="tool_use")
        f = step_fields(r)
        self.assertEqual(f, {"tool_calls": 2, "tools": ["bash", "read_file"], "finish_reason": "tool_use",
                             "step_kind": "tool_call"})
        self.assertNotIn("SECRET", repr(safe_data(f)))

    def test_final_answer_step(self):
        self.assertEqual(step_fields(NS(tool_calls=None, finish_reason="end_turn")),
                         {"tool_calls": 0, "finish_reason": "end_turn", "step_kind": "final_answer"})

    def test_dict_shaped_response_and_privacy_allowlist(self):
        f = step_fields({"tool_calls": [{"name": "grep"}], "finish_reason": "tool_use"})
        self.assertEqual(safe_data(f), f)   # every field survives the allowlist


if __name__ == "__main__":
    unittest.main()
