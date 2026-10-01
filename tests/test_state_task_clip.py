"""build_state keeps the head AND tail of an over-budget task and drops host reminders."""
from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

import hashlib

from amplifier_fast_decisions.contracts import Candidate, DecisionRequest, Policy, canonical
from amplifier_fast_decisions.local_backend import _build_label_prompt
from amplifier_fast_decisions.state import _head_tail, build_state, clip_head_tail

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


def long_request(task_len, nobs=8, obs_len=1400):
    messages = [{"role": "user", "content": "T" * (task_len // 2) + "U" * (task_len - task_len // 2)}]
    for i in range(nobs):
        messages.append({"role": "assistant" if i % 2 == 0 else "tool", "content": f"obs{i} " + "o" * obs_len})
    return NS(messages=messages)


def digest(state):
    return hashlib.sha256(canonical(state).encode()).hexdigest()[:12]


class TaskCapTests(unittest.TestCase):
    """The task keeps at most Policy.max_task_chars (2000) as before; nothing else moves."""

    def test_digest_unchanged_for_tasks_within_cap(self):
        # Digest and kept-observation count taken from the pre-change build_state (6206103).
        state = build_state(long_request(1500), 12000)
        self.assertEqual(digest(state), "779c97f5accd")
        self.assertEqual(len(state["observations"]), 9)

    def test_observation_count_matches_old_code_for_long_tasks(self):
        old = {2500: 8, 3200: 8, 6000: 8}  # observations kept by the pre-change code at 12000
        for length, expected in old.items():
            with self.subTest(length=length):
                state = build_state(long_request(length), 12000)
                self.assertEqual(len(state["observations"]), expected)
                self.assertLessEqual(len(state["observations"][0]["text"]), 2000)

    def test_task_cap_is_configurable_and_validated(self):
        state = build_state(long_request(6000), 12000, task_chars=500)
        self.assertLessEqual(len(state["observations"][0]["text"]), 500)
        self.assertEqual(Policy().max_task_chars, 2000)
        with self.assertRaises(ValueError):
            Policy(max_task_chars=10)

    def test_ollama_prompt_builder_accepts_states_from_long_tasks(self):
        cand = (Candidate("c0", "Read a", "fast_workspace", {"operation": "read", "path": "a.py"}),)
        for length in (1500, 2500, 3200, 6000):
            with self.subTest(length=length):
                state = build_state(long_request(length), 2048)
                _build_label_prompt(DecisionRequest(state=state, candidates=cand), format_tag="t")

    def test_ollama_prompt_builder_accepts_default_budget_long_tasks(self):
        # Default 12000-char budget, a couple of short tool results: the case where an
        # uncapped task pushed the Ollama prompt past its 3500-byte limit.
        cand = (Candidate("c0", "Read a", "fast_workspace", {"operation": "read", "path": "a.py"}),)
        for length in (1500, 2500, 3200, 6000):
            with self.subTest(length=length):
                state = build_state(long_request(length, nobs=2, obs_len=300), 12000)
                _build_label_prompt(DecisionRequest(state=state, candidates=cand), format_tag="t")

    def test_question_path_still_sees_tool_results(self):
        state = build_state(long_request(6000), 12000)
        front = canonical(state["observations"])[:3501]  # what the Laya/question scorer keeps
        self.assertIn("obs1", front)  # oldest kept tool result follows the capped task

    def test_stats_clipped_when_task_exceeds_cap_only(self):
        stats: dict = {}
        build_state(long_request(1500, nobs=0), 12000, stats)
        self.assertEqual(stats["observations_clipped"], 0)
        build_state(long_request(6000, nobs=0), 12000, stats)
        self.assertEqual(stats["observations_clipped"], 1)

    def test_exact_fit_is_never_longer_and_unmarked(self):
        text = "x" * 300
        self.assertEqual(clip_head_tail(text, 300), text)
        for cap in range(1, 320):
            self.assertLessEqual(len(clip_head_tail(text, cap)), 300)
        self.assertEqual(clip_head_tail("short", 300), "short")
        self.assertEqual(len(clip_head_tail("z" * 1000, 300)), 300)
        # Marker would not save space: full text returned, no marker.
        self.assertEqual(_head_tail("y" * 40, 39), "y" * 40)
        for keep in range(0, 41):
            self.assertLessEqual(len(_head_tail("y" * 40, keep)), 40)

    def test_reminders_stripped_anywhere(self):
        text = "<system-reminders>a</system-reminders>Do X<system-reminder source=\"s\">b</system-reminder>"
        state = build_state(req(text), 2048)
        self.assertEqual(task_text(state), "Do X")


if __name__ == "__main__":
    unittest.main()
