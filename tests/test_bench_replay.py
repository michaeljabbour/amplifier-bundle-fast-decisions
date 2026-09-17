"""Unit tests for amplifier_fast_decisions.bench.replay -- offline, no
network, no LLM."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from amplifier_fast_decisions.bench.replay import (
    _unwrap_kernel_envelope,
    join_by_decision_id,
    load_events,
    replay_events,
)
from amplifier_fast_decisions.bench.report import build_report_from_replay

ROOT = Path(__file__).resolve().parents[1]
DEMO_EVENTS = ROOT / "examples" / "demo-events.jsonl"


def _event(event_id, decision_id, kind, data, seq=1, turn_id="t1"):
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event": f"fast_decisions:{kind}",
        "session_id": "s1",
        "parent_session_id": None,
        "turn_id": turn_id,
        "decision_id": decision_id,
        "seq": seq,
        "timestamp": "2026-09-17T00:00:00+00:00",
        "monotonic_ns": seq,
        "synthetic": True,
        "data": data,
    }


def _kernel_envelope(event_id, decision_id, kind, data, seq=1, turn_id="t1", session_id="s1"):
    """Build a record shaped exactly like the kernel's session-log envelope
    (``~/.amplifier/projects/*/sessions/<id>/events.jsonl``), one level of
    nesting deeper than the bundle's own recorder output: our whole flat
    record (event/event_id/decision_id/seq/turn_id/schema_version/synthetic/
    monotonic_ns/data) sits under the kernel envelope's own top-level
    ``data`` key, with the kernel's own ``event``/``session_id`` duplicated
    at the outer level and no ``session_id`` inside the inner record --
    this exact key set was verified against a real session file (see
    ``bench/replay.py::_unwrap_kernel_envelope``)."""
    return {
        "ts": "2026-09-17T00:00:00+00:00",
        "lvl": "INFO",
        "schema": {"name": "amplifier.log", "ver": "1.0.0"},
        "event": f"fast_decisions:{kind}",
        "redaction": {"applied": True, "rules": ["secrets", "pii-basic"]},
        "session_id": session_id,
        "data": {
            "data": data,
            "decision_id": decision_id,
            "event": f"fast_decisions:{kind}",
            "event_id": event_id,
            "monotonic_ns": seq,
            "parent_id": None,
            "parent_session_id": None,
            "schema_version": "1.0",
            "seq": seq,
            "synthetic": False,
            "turn_id": turn_id,
        },
    }


class JoinByDecisionIdTests(unittest.TestCase):
    def test_join_by_decision_id(self):
        # Out-of-order seq and a duplicate event_id must still produce
        # exactly one joined record per decision_id.
        events = [
            _event(
                "e2",
                "d1",
                "scored",
                {"duration_ms": 10, "latency_kind": "decision_model_wall_time"},
                seq=2,
            ),
            _event(
                "e1",
                "d1",
                "requested",
                {"candidates": [{"id": "c1", "tool": "fast_workspace"}]},
                seq=1,
            ),
            _event(
                "e1",
                "d1",
                "requested",
                {"candidates": [{"id": "c1", "tool": "fast_workspace"}]},
                seq=1,
            ),  # dup
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            loaded = load_events(path)
            self.assertEqual(len(loaded), 2)  # duplicate event_id collapsed
            joins = join_by_decision_id(loaded)
            self.assertEqual(len(joins), 1)
            join = joins["d1"]
            self.assertIsNotNone(join.requested)
            self.assertIsNotNone(join.scored)


class ReplayOnDemoEventsTests(unittest.TestCase):
    def test_replay_on_demo_events_produces_schema_valid_record(self):
        result = asyncio.run(replay_events(DEMO_EVENTS))
        self.assertGreater(result.n_decisions, 0)
        report = build_report_from_replay(result, session_id="demo-a44d85c7")
        for key in (
            "session_id",
            "model",
            "provider",
            "start_time",
            "end_time",
            "cost",
            "latency",
            "security",
            "stability",
            "accuracy_proxy",
            "decision",
        ):
            self.assertIn(key, report)
        self.assertIsInstance(report["accuracy_proxy"]["calibration_bins"], list)
        self.assertIsInstance(report["decision"]["projection_assumptions"], list)
        self.assertEqual(report["decision"]["projection_basis"], "model")
        # Missing usage is null, never zero, when unreported.
        self.assertIsInstance(report["cost"]["input_tokens"], (type(None), int, float))
        # Round-trips through the same JSON encoding the CLI's --json uses.
        encoded = json.dumps(report, sort_keys=True, allow_nan=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["session_id"], "demo-a44d85c7")

    def test_json_output_parses(self):
        result = asyncio.run(replay_events(DEMO_EVENTS))
        report = build_report_from_replay(result, session_id="demo-a44d85c7")
        encoded = json.dumps(report, sort_keys=True, allow_nan=False)
        # Must be valid, finite JSON -- no NaN/Infinity leaking through.
        json.loads(encoded)


class DemoEventsCarryExplicitFieldsTests(unittest.TestCase):
    """demo.py drives the real DecisionService, so its recorded events now
    carry the explicit domain/state_chars/allow_external_state fields --
    replay must be MEASURING, not inferring, when it reads them."""

    def test_state_chars_and_domain_measured_from_demo_events(self):
        result = asyncio.run(replay_events(DEMO_EVENTS))
        self.assertIsNotNone(result.state_chars_p50)
        self.assertIsNotNone(result.state_chars_p95)
        self.assertGreater(len(result.state_size_vs_latency), 0)
        self.assertIn("tool-choice", result.per_domain)
        # n_inferred == 0 proves the domain came from the explicit field,
        # not the legacy heuristic fallback.
        self.assertEqual(result.per_domain["tool-choice"]["n_inferred"], 0)


class LegacyDomainFallbackTests(unittest.TestCase):
    def test_legacy_recording_without_domain_field_is_inferred(self):
        # A recording made before this bundle emitted `domain` has none of
        # these fields on any event -- the fallback heuristic must still
        # classify it, and flag every decision as inferred.
        events = [
            _event(
                "req1",
                "d1",
                "requested",
                {"candidates": [{"id": "c1", "tool": "fast_workspace"}]},
                seq=1,
            ),
            _event(
                "sc1",
                "d1",
                "scored",
                {
                    "duration_ms": 10,
                    "latency_kind": "decision_model_wall_time",
                    "choice": "c1",
                    "selected_probability": 0.9,
                },
                seq=2,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertIn("read-target", result.per_domain)
        self.assertEqual(result.per_domain["read-target"]["n"], 1)
        self.assertEqual(result.per_domain["read-target"]["n_inferred"], 1)

    def test_explicit_domain_field_takes_precedence_over_heuristic(self):
        # requested declares tool-choice explicitly even though its lone
        # candidate targets fast_workspace (which the heuristic would
        # classify as read-target) -- the explicit field must win.
        events = [
            _event(
                "req1",
                "d1",
                "requested",
                {
                    "candidates": [{"id": "c1", "tool": "fast_workspace"}],
                    "domain": "tool-choice",
                },
                seq=1,
            ),
            _event(
                "sc1",
                "d1",
                "scored",
                {
                    "duration_ms": 10,
                    "latency_kind": "decision_model_wall_time",
                    "choice": "c1",
                    "selected_probability": 0.9,
                },
                seq=2,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "explicit.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertIn("tool-choice", result.per_domain)
        self.assertNotIn("read-target", result.per_domain)
        self.assertEqual(result.per_domain["tool-choice"]["n_inferred"], 0)


class StateSizeVsLatencyTests(unittest.TestCase):
    def test_state_size_vs_latency_buckets(self):
        # Proves the bucketing math using synthetic events that declare
        # state_chars explicitly (real demo/production events do too, as
        # of this PR -- see DemoEventsCarryExplicitFieldsTests above).
        events = []
        for i in range(20):
            decision_id = f"d{i}"
            events.append(
                _event(
                    f"req{i}",
                    decision_id,
                    "requested",
                    {
                        "candidates": [{"id": "c1", "tool": "fast_workspace"}],
                        "state_chars": 100 + i * 50,
                    },
                    seq=i * 2,
                    turn_id="t1",
                )
            )
            events.append(
                _event(
                    f"sc{i}",
                    decision_id,
                    "scored",
                    {
                        "duration_ms": 50 + i,
                        "latency_kind": "decision_model_wall_time",
                        "choice": "c1",
                        "selected_probability": 0.9,
                    },
                    seq=i * 2 + 1,
                    turn_id="t1",
                )
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertIsNotNone(result.state_chars_p50)
        self.assertIsNotNone(result.state_chars_p95)
        self.assertGreater(len(result.state_size_vs_latency), 0)
        for bucket in result.state_size_vs_latency:
            self.assertIn("decile", bucket)
            self.assertIn("state_chars", bucket)
            self.assertIn("mean_ms", bucket)
        # Larger states should land in higher-numbered deciles.
        first, last = result.state_size_vs_latency[0], result.state_size_vs_latency[-1]
        self.assertLess(first["state_chars"], last["state_chars"])


class HookOnlySessionTests(unittest.TestCase):
    """Hook-only (shadow-in-the-hook) sessions never call
    DecisionService.choose -- ShadowScorer builds its own ShadowJob
    directly, so `requested`/`scored` never fire (see observer.py). Before
    the fix, `replay_events` only counted a `decision` when `requested` was
    present, so every hook-only session's `agreement_rate`, `per_domain`
    and `state_chars_p50/p95` silently came back None/empty even though
    `shadow_proposed`/`shadow_agreement` telemetry existed on disk.
    """

    def _hook_only_events(self):
        return [
            _event(
                "sp1",
                "d1",
                "shadow_proposed",
                {
                    "choice": "read_d82ab49f91a6",
                    "domain": "read-target",
                    "state_chars": 4481,
                    "selected_probability": 0.97,
                },
                seq=1,
            ),
            _event(
                "so1",
                "d1",
                "shadow_observed",
                {"tool": "fast_workspace", "tool_call_id": "call_1"},
                seq=2,
            ),
            _event(
                "sa1",
                "d1",
                "shadow_agreement",
                {
                    "agreement": "match",
                    "proposed_candidate": "read_d82ab49f91a6",
                    "actual_tool": "fast_workspace",
                    "would_have_avoided_llm_turn": True,
                    "domain": "read-target",
                },
                seq=3,
            ),
        ]

    def test_hook_only_session_counts_as_a_decision(self):
        events = self._hook_only_events()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook_only.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertEqual(result.n_decisions, 1)

    def test_hook_only_session_produces_agreement_rate(self):
        events = self._hook_only_events()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook_only.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertEqual(result.agreement_rate, 1.0)

    def test_hook_only_session_populates_per_domain_from_shadow_proposed(self):
        events = self._hook_only_events()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook_only.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertIn("read-target", result.per_domain)
        self.assertEqual(result.per_domain["read-target"]["n"], 1)
        # domain came from the explicit shadow_proposed field, not inferred.
        self.assertEqual(result.per_domain["read-target"]["n_inferred"], 0)

    def test_hook_only_session_populates_state_chars(self):
        events = self._hook_only_events()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook_only.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertEqual(result.state_chars_p50, 4481.0)
        self.assertEqual(result.state_chars_p95, 4481.0)

    def test_mixed_active_and_hook_only_decisions_both_counted(self):
        # An active-path decision (requested/scored) alongside a hook-only
        # one (shadow_proposed only) -- both must contribute to n_decisions
        # and per_domain, not just whichever one carries `requested`.
        events = self._hook_only_events() + [
            _event(
                "req2",
                "d2",
                "requested",
                {
                    "candidates": [{"id": "c1", "tool": "fast_workspace"}],
                    "domain": "tool-choice",
                    "state_chars": 200,
                },
                seq=1,
            ),
            _event(
                "sc2",
                "d2",
                "scored",
                {
                    "duration_ms": 10,
                    "latency_kind": "decision_model_wall_time",
                    "choice": "c1",
                    "selected_probability": 0.9,
                },
                seq=2,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertEqual(result.n_decisions, 2)
        self.assertIn("read-target", result.per_domain)
        self.assertIn("tool-choice", result.per_domain)


class KernelEnvelopeUnwrapTests(unittest.TestCase):
    """Regression coverage for the kernel session-log envelope
    (``~/.amplifier/projects/*/sessions/<id>/events.jsonl``) -- verified
    against a real session file, not just a guessed shape (see
    ``bench/replay.py::_unwrap_kernel_envelope``)."""

    def _hook_only_envelope_events(self):
        return [
            _kernel_envelope(
                "so1",
                "d1",
                "shadow_observed",
                {"tool": "fast_workspace", "tool_call_id": "call_1"},
                seq=1,
            ),
            _kernel_envelope(
                "sp1",
                "d1",
                "shadow_proposed",
                {
                    "choice": "read_d82ab49f91a6",
                    "domain": "read-target",
                    "state_chars": 2416,
                    "selected_probability": 0.97,
                },
                seq=2,
            ),
            _kernel_envelope(
                "sa1",
                "d1",
                "shadow_agreement",
                {
                    "agreement": "match",
                    "proposed_candidate": "read_d82ab49f91a6",
                    "actual_tool": "fast_workspace",
                    "would_have_avoided_llm_turn": True,
                    "domain": "read-target",
                },
                seq=3,
            ),
        ]

    def test_unwrap_extracts_the_flat_inner_record(self):
        envelope = _kernel_envelope("e1", "d1", "shadow_proposed", {"domain": "read-target"})
        unwrapped = _unwrap_kernel_envelope(envelope)
        self.assertEqual(unwrapped["event"], "fast_decisions:shadow_proposed")
        self.assertEqual(unwrapped["event_id"], "e1")
        self.assertEqual(unwrapped["decision_id"], "d1")
        self.assertEqual(unwrapped["data"], {"domain": "read-target"})
        # session_id is absent from the inner record; unwrap fills it in
        # from the outer envelope.
        self.assertEqual(unwrapped["session_id"], "s1")

    def test_unwrap_is_a_noop_on_a_flat_recorder_record(self):
        flat = _event("e1", "d1", "shadow_proposed", {"domain": "read-target"})
        self.assertEqual(_unwrap_kernel_envelope(flat), flat)

    def test_load_events_reads_kernel_envelope_lines(self):
        events = self._hook_only_envelope_events()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            loaded = load_events(path)
        self.assertEqual(len(loaded), 3)
        kinds = {e["event"] for e in loaded}
        self.assertEqual(
            kinds,
            {
                "fast_decisions:shadow_observed",
                "fast_decisions:shadow_proposed",
                "fast_decisions:shadow_agreement",
            },
        )

    def test_kernel_envelope_session_dir_produces_agreement_rate_and_state_chars(self):
        events = self._hook_only_envelope_events()
        with tempfile.TemporaryDirectory() as tmp:
            # A session directory, e.g. .../sessions/<id>/, alongside a
            # non-fast_decisions sibling file (transcript.jsonl) that must
            # be ignored, not merely tolerated.
            session_dir = Path(tmp)
            (session_dir / "events.jsonl").write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            (session_dir / "transcript.jsonl").write_text(
                json.dumps({"role": "user", "content": "hi"}) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(session_dir))
        self.assertEqual(result.n_decisions, 1)
        self.assertEqual(result.agreement_rate, 1.0)
        self.assertEqual(result.state_chars_p50, 2416.0)
        self.assertIn("read-target", result.per_domain)
        self.assertEqual(result.per_domain["read-target"]["agreement_rate"], 1.0)

    def test_mixed_kernel_envelope_and_flat_recorder_lines_in_one_file(self):
        # One decision recorded in the kernel-envelope shape, another in
        # the bundle recorder's flat shape -- both must be counted.
        events = self._hook_only_envelope_events() + [
            _event(
                "sp2",
                "d2",
                "shadow_proposed",
                {"domain": "tool-choice", "state_chars": 100, "selected_probability": 0.9},
                seq=1,
            ),
            _event(
                "sa2",
                "d2",
                "shadow_agreement",
                {
                    "agreement": "match",
                    "actual_tool": "delegate",
                    "would_have_avoided_llm_turn": True,
                    "domain": "tool-choice",
                },
                seq=2,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.jsonl"
            path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            result = asyncio.run(replay_events(path))
        self.assertEqual(result.n_decisions, 2)
        self.assertIn("read-target", result.per_domain)
        self.assertIn("tool-choice", result.per_domain)


if __name__ == "__main__":
    unittest.main()
