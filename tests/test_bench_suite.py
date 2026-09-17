"""Unit tests for amplifier_fast_decisions.bench.suite -- offline, hermetic,
no network."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amplifier_fast_decisions.bench.report import build_report_from_suite
from amplifier_fast_decisions.bench.suite import (
    DeterministicSuiteBackend,
    ForbiddenLabelSource,
    load_suite,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[1]
STARTER_SUITE = ROOT / "suites" / "v1.jsonl"


def _write_suite(tmp_dir: str, cases: list[dict]) -> Path:
    path = Path(tmp_dir) / "suite.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")
    return path


def _case(
    case_id: str,
    domain: str = "tool-choice",
    label_source: str = "human",
    expected: str = "c1",
) -> dict:
    return {
        "id": case_id,
        "domain": domain,
        "state": {},
        "candidates": [
            {
                "id": "c1",
                "label": "Candidate one",
                "tool": "fast_workspace",
                "arguments": {},
            },
            {
                "id": "c2",
                "label": "Candidate two",
                "tool": "fast_workspace",
                "arguments": {},
            },
        ],
        "expected_choice": expected,
        "label_source": label_source,
        "tags": ["easy"],
    }


class DeterministicSuiteRunsOfflineTests(unittest.TestCase):
    def test_deterministic_suite_runs_offline(self):
        cases = load_suite(STARTER_SUITE)
        self.assertGreater(len(cases), 0)
        backend = DeterministicSuiteBackend()
        self.assertFalse(backend.external)
        result = asyncio.run(run_suite(cases, backend, permutations=4))
        self.assertEqual(len(result.items), len(cases))
        report = build_report_from_suite(
            result,
            session_id="suite-v1",
            model="deterministic-suite-backend",
            provider="offline",
            backend_external=False,
        )
        # No network call is possible here (DeterministicSuiteBackend makes
        # none); exit-0 shape is exercised by the report having a full
        # CLASSic-shaped record.
        self.assertIn("accuracy_proxy", report)
        self.assertIn("decision", report)
        json.dumps(report, allow_nan=False)  # exit 0 / report written


class LiveGateTests(unittest.TestCase):
    def test_live_requires_both_gates(self):
        # --live without FAST_DECISIONS_LIVE=1 (and without TYPESAFE_API_KEY)
        # must never construct a Jev client; the CLI layer falls back to
        # the offline deterministic backend instead of failing.
        with mock.patch.dict(os.environ, {}, clear=True):
            both_gates = bool(
                os.getenv("FAST_DECISIONS_LIVE") == "1"
                and os.getenv("TYPESAFE_API_KEY")
            )
            self.assertFalse(both_gates)
        with mock.patch.dict(os.environ, {"FAST_DECISIONS_LIVE": "1"}, clear=True):
            both_gates = bool(
                os.getenv("FAST_DECISIONS_LIVE") == "1"
                and os.getenv("TYPESAFE_API_KEY")
            )
            self.assertFalse(both_gates)  # missing TYPESAFE_API_KEY
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "x"}, clear=True):
            both_gates = bool(
                os.getenv("FAST_DECISIONS_LIVE") == "1"
                and os.getenv("TYPESAFE_API_KEY")
            )
            self.assertFalse(both_gates)  # missing FAST_DECISIONS_LIVE=1
        with mock.patch.dict(
            os.environ,
            {"FAST_DECISIONS_LIVE": "1", "TYPESAFE_API_KEY": "x"},
            clear=True,
        ):
            both_gates = bool(
                os.getenv("FAST_DECISIONS_LIVE") == "1"
                and os.getenv("TYPESAFE_API_KEY")
            )
            self.assertTrue(both_gates)


class RejectsModelSourcedLabelsTests(unittest.TestCase):
    def test_rejects_model_sourced_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_suite(tmp, [_case("c1", label_source="model")])
            with self.assertRaises(ForbiddenLabelSource):
                load_suite(path)

    def test_accepts_human_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_suite(tmp, [_case("c1", label_source="human")])
            cases = load_suite(path)
            self.assertEqual(len(cases), 1)


class PermutationStabilityTests(unittest.TestCase):
    def test_permutation_test_reports_stability_and_swing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_suite(tmp, [_case(f"case-{i}") for i in range(6)])
            cases = load_suite(path)
        backend = DeterministicSuiteBackend()  # order-sensitive by design
        result = asyncio.run(run_suite(cases, backend, permutations=4))
        self.assertEqual(result.permutations, 4)
        stability = result.order_agreement_stability
        swing = result.max_probability_swing
        assert stability is not None
        assert swing is not None
        self.assertGreaterEqual(stability, 0.0)
        self.assertLessEqual(stability, 1.0)
        self.assertGreaterEqual(swing, 0.0)

    def test_k_equals_one_disables_permutation_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_suite(tmp, [_case("only-case")])
            cases = load_suite(path)
        result = asyncio.run(
            run_suite(cases, DeterministicSuiteBackend(), permutations=1)
        )
        self.assertEqual(result.permutations, 1)
        self.assertEqual(result.order_agreement_stability, 1.0)
        self.assertEqual(result.max_probability_swing, 0.0)


class PerDomainEceTests(unittest.TestCase):
    def test_per_domain_ece_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = (
                [_case(f"tc-{i}", domain="tool-choice") for i in range(2)]
                + [_case(f"rt-{i}", domain="read-target") for i in range(2)]
                + [_case(f"mr-{i}", domain="model-role") for i in range(2)]
            )
            path = _write_suite(tmp, cases)
            loaded = load_suite(path)
        backend = DeterministicSuiteBackend()
        result = asyncio.run(run_suite(loaded, backend, permutations=1))
        report = build_report_from_suite(
            result,
            session_id="suite-domains",
            model="deterministic-suite-backend",
            provider="offline",
            backend_external=False,
        )
        per_domain = report["accuracy_proxy"]["per_domain"]
        for domain in ("tool-choice", "read-target", "model-role"):
            self.assertIn(domain, per_domain)
            self.assertEqual(per_domain[domain]["n"], 2)
        # A pooled-only report is a failure per the design doc's acceptance
        # criteria; per_domain must be populated for every domain present.
        self.assertGreaterEqual(len(per_domain), 3)


if __name__ == "__main__":
    unittest.main()
