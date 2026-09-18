"""Tests for cli.py's bench-suite wiring: backend selection, per-case
latency, and the ``agreement_with_expected`` alias.

Stdlib only, hermetic -- ``ScriptedBackend`` never makes a network call.
Exercises ``cli._TimingBackend`` and ``cli._augment_suite_report`` directly
(the pure post-processing helpers), rather than driving the full argparse
CLI, to keep the test focused on the bench-suite wiring itself.
"""

from __future__ import annotations

import asyncio
import unittest

from amplifier_fast_decisions.backends import ScriptedBackend
from amplifier_fast_decisions.bench import SuiteCase, build_report, run_suite
from amplifier_fast_decisions.cli import _augment_suite_report, _TimingBackend
from amplifier_fast_decisions.contracts import Candidate


def _case(case_id: str, expected: str) -> SuiteCase:
    return SuiteCase(
        id=case_id,
        domain="tool-choice",
        state={},
        candidates=(
            Candidate("c1", "Candidate one", "fast_workspace", {}),
            Candidate("c2", "Candidate two", "fast_workspace", {}),
        ),
        expected_choice=expected,
        label_source="human",
    )


class TimingBackendTests(unittest.TestCase):
    def test_records_one_latency_per_ask_call(self):
        inner = ScriptedBackend(script=[{"choice": "c1", "delay_ms": 0}])
        timed = _TimingBackend(inner)
        cases = [_case("a", "c1"), _case("b", "c1")]
        result = asyncio.run(run_suite(cases, timed, permutations=1))
        self.assertEqual(len(result.items), 2)
        # permutations=1 disables the permutation test: exactly one ask()
        # call per case (the canonical order).
        self.assertEqual(len(timed.latencies_ms), 2)
        self.assertTrue(all(v >= 0 for v in timed.latencies_ms))


class SuiteAgreementAndLatencyTests(unittest.TestCase):
    def test_two_case_suite_gives_agreement_one_half_and_latency_fields(self):
        # Case "a": backend picks c1, expected c1 -> correct.
        # Case "b": backend picks c2, expected c1 -> incorrect.
        # agreement_with_expected == 1/2 == 0.5
        inner = ScriptedBackend(
            script=[{"choice": "c1", "delay_ms": 0}, {"choice": "c2", "delay_ms": 0}]
        )
        timed = _TimingBackend(inner)
        cases = [_case("a", "c1"), _case("b", "c1")]
        permutations = 1
        result = asyncio.run(run_suite(cases, timed, permutations=permutations))
        report = build_report(
            "suite",
            result,
            session_id="suite-test",
            model="scripted-demo-not-jev",
            provider="offline",
            backend_external=False,
        )
        report = _augment_suite_report(report, timed, permutations)

        self.assertEqual(report["accuracy_proxy"]["agreement_rate"], 0.5)
        self.assertEqual(report["accuracy_proxy"]["agreement_with_expected"], 0.5)
        self.assertIsNotNone(report["decision"]["decision_latency_ms_p50"])
        self.assertIsNotNone(report["decision"]["decision_latency_ms_p95"])
        self.assertGreaterEqual(report["decision"]["decision_latency_ms_p95"], 0)
        self.assertIn("abstention_rate", report["accuracy_proxy"])

    def test_canonical_latency_slicing_with_permutations(self):
        # permutations=3 means each case gets 3 ask() calls (1 canonical +
        # 2 permuted); only the canonical (index 0 of each group of 3)
        # should feed the reported p50/p95.
        inner = ScriptedBackend(script=[{"choice": "c1", "delay_ms": 0}])
        timed = _TimingBackend(inner)
        cases = [_case("a", "c1"), _case("b", "c1")]
        permutations = 3
        result = asyncio.run(run_suite(cases, timed, permutations=permutations))
        self.assertEqual(len(timed.latencies_ms), 2 * permutations)
        report = build_report(
            "suite",
            result,
            session_id="suite-test-perm",
            model="scripted-demo-not-jev",
            provider="offline",
            backend_external=False,
        )
        report = _augment_suite_report(report, timed, permutations)
        self.assertIsNotNone(report["decision"]["decision_latency_ms_p50"])


if __name__ == "__main__":
    unittest.main()
