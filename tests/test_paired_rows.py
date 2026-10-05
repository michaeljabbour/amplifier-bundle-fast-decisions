"""rows: recomputed cost == provider cost (1e-6), per-turn windows, cache-read audit, switches, mechanism gates,
covariate whitelist, pairs, and an end-to-end extract from a synthetic campaign. Synthetic events only."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paired_helpers import FakeBackend, INLINE_SCENARIO, paired, ps, ts, write_events

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5"
T0 = 1_800_000_000.0


def result_doc(turn_windows, passed=(True, True), sid="sid-x", **extra):
    turns = []
    for i, ((s, e), ok) in enumerate(zip(turn_windows, passed), start=1):
        turns.append({"index": i, "started_at": ts(s), "ended_at": ts(e), "elapsed_ms": (e - s) * 1000, "gap_before_s": 0 if i == 1 else 10,
                      "turn_passed": ok, "skipped": False, "quality": {"checks": 2, "passed": 2 if ok else 1, "failed": 0 if ok else 1,
                                                                        "failure_labels": [] if ok else ["x"]}})
    return {"session_id": sid, "infrastructure_failure": False, "outcome_passed": all(passed), "turns": turns,
            "source_expected": {"git_sha": "abc", "tree_sha256": "def"}, "started_at": ts(turn_windows[0][0]), **extra}


def meta(**kw):
    m = {"key": "tiny-demo-r1-opus-anchor", "wave_id": "w", "scenario": "tiny-demo", "rep": 1, "host": "opus", "arm": "anchor",
         "kind": "plain", "cell": "plain-opus", "model": OPUS, "scenario_hash": "h", "nonce": "n-1", "attempt": 1}
    m.update(kw)
    return m


SPEC = ps.parse(copy.deepcopy(INLINE_SCENARIO))


class EventParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.reqs = [
            {"t": T0 + 1, "model": OPUS, "uncached": 100, "read": 0, "write": 50_000, "output": 200},
            {"t": T0 + 5, "model": OPUS, "uncached": 50, "read": 50_000, "write": 400, "output": 100},
            {"t": T0 + 9, "model": "claude-haiku-4-5", "uncached": 300, "read": 0, "write": 0, "output": 20, "main": False},
            {"t": T0 + 21, "model": OPUS, "uncached": 40, "read": 50_400, "write": 300, "output": 150},
        ]
        write_events(self.tmp / "events.jsonl", self.reqs)
        self.parsed = paired.parse_events(self.tmp)

    def test_requests_parsed_and_background_separated(self):
        self.assertEqual(len(self.parsed["requests"]), 4)
        self.assertEqual([r["main"] for r in self.parsed["requests"]], [True, True, False, True])
        self.assertEqual(self.parsed["requests"][0]["write"], 50_000)

    def test_session_row_cost_recomputed_equals_provider(self):
        windows = [(T0, T0 + 10), (T0 + 20, T0 + 30)]
        row, trows = paired.session_row(meta(), result_doc(windows), self.parsed, SPEC, {"workspace_files": 2, "workspace_bytes": 10},
                                        {"build_sha": "abc", "price_table_sha": paired.price_table_sha()})
        self.assertAlmostEqual(row["cost_usd_provider"], row["cost_usd_recomputed"], places=6)
        self.assertFalse(row["cost_mismatch"])
        self.assertEqual(row["n_req"], 3)
        self.assertEqual(row["n_bg"], 1)
        self.assertEqual(row["tokens"][OPUS]["cache_write"], 50_700)
        self.assertEqual(row["served_models"], [OPUS])
        self.assertEqual(row["nonce"], "n-1")
        # per-turn windows: the haiku background call at T0+9 belongs to turn 1; turn 2 has one request
        self.assertEqual([t["calls"] for t in trows], [2, 1])
        self.assertEqual([t["bg_calls"] for t in trows], [1, 0])
        self.assertAlmostEqual(sum(t["cost_usd"] for t in trows), row["cost_usd_provider"], places=6)
        self.assertEqual(trows[1]["first_req_cache_read"], 50_400)
        self.assertEqual(trows[1]["gap_before_s"], 10)
        self.assertGreater(trows[0]["working_ms"], 0)

    def test_cost_mismatch_is_flagged(self):
        lines = (self.tmp / "events.jsonl").read_text().splitlines()
        tampered = []
        for l in lines:
            e = json.loads(l)
            if e["event"] == "llm:response" and e["request_id"] == "req0":
                e["data"]["usage"]["cost_usd"] = "9.99"
            tampered.append(json.dumps(e))
        (self.tmp / "events.jsonl").write_text("\n".join(tampered) + "\n")
        row, _ = paired.session_row(meta(), result_doc([(T0, T0 + 10), (T0 + 20, T0 + 30)]), paired.parse_events(self.tmp), SPEC, {}, {})
        self.assertTrue(row["cost_mismatch"])


class CacheAuditTests(unittest.TestCase):
    def reqs(self, *specs):
        return [{"main": True, "effort": None, "ts_req": i, "ts_resp": i + 1, "uncached": 1, "output": 1, **s} for i, s in enumerate(specs)]

    def test_clean_session_has_no_flags(self):
        a = paired.cache_audit(self.reqs({"model": OPUS, "read": 0, "write": 1000}, {"model": OPUS, "read": 1000, "write": 200},
                                         {"model": OPUS, "read": 1200, "write": 50}))
        self.assertTrue(a["cache_audit_clean"])
        self.assertEqual(a["cross_arm_read_tokens"], 0)

    def test_read_on_first_request_is_flagged_as_cross_session(self):
        a = paired.cache_audit(self.reqs({"model": OPUS, "read": 700, "write": 300}, {"model": OPUS, "read": 1000, "write": 10}))
        self.assertFalse(a["cache_audit_clean"])
        self.assertEqual(a["cross_arm_read_tokens"], 700)
        self.assertEqual(a["cache_audit_flags"][0]["request_index"], 1)
        self.assertEqual(a["foreign_read_tokens_total"], 1400)   # 700 on request 1, then 1000 read vs 300 own writes

    def test_shared_tools_prefix_is_reported_but_not_flagged_up_to_the_allowance(self):
        r = self.reqs({"model": OPUS, "read": 700, "write": 300}, {"model": OPUS, "read": 1000, "write": 10})
        a = paired.cache_audit(r, tools_prefix_tokens=700)
        self.assertTrue(a["cache_audit_clean"])
        self.assertEqual(a["cross_arm_read_tokens"], 700)             # still reported: the spec's P1 measurement
        self.assertFalse(paired.cache_audit(r, tools_prefix_tokens=699)["cache_audit_clean"])
        # the allowance never excuses a read on a request that follows an own write for that model
        r2 = self.reqs({"model": OPUS, "read": 0, "write": 1000}, {"model": OPUS, "read": 1700, "write": 0})
        self.assertEqual([f["foreign_read_tokens"] for f in paired.cache_audit(r2, tools_prefix_tokens=700)["cache_audit_flags"]], [700])

    def test_read_beyond_own_writes_is_flagged_even_mid_session(self):
        a = paired.cache_audit(self.reqs({"model": OPUS, "read": 0, "write": 1000}, {"model": OPUS, "read": 1600, "write": 0}))
        self.assertEqual([f["foreign_read_tokens"] for f in a["cache_audit_flags"]], [600])

    def test_caches_are_per_model(self):
        a = paired.cache_audit(self.reqs({"model": OPUS, "read": 0, "write": 1000}, {"model": SONNET, "read": 500, "write": 10}))
        self.assertFalse(a["cache_audit_clean"])            # a Sonnet read cannot come from an Opus write

    def test_sonnet_cache_is_per_effort(self):
        r = self.reqs({"model": SONNET, "read": 0, "write": 1000, "effort": "medium"}, {"model": SONNET, "read": 1000, "write": 0, "effort": None})
        self.assertFalse(paired.cache_audit(r)["cache_audit_clean"])
        r2 = self.reqs({"model": OPUS, "read": 0, "write": 1000, "effort": "medium"}, {"model": OPUS, "read": 1000, "write": 0, "effort": None})
        self.assertTrue(paired.cache_audit(r2)["cache_audit_clean"])   # Opus effort is not part of the key

    def test_background_requests_are_not_audited(self):
        r = self.reqs({"model": OPUS, "read": 0, "write": 10})
        r.append(dict(main=False, effort=None, ts_req=9, ts_resp=10, uncached=1, output=1, model="claude-haiku-4-5", read=999, write=0))
        self.assertTrue(paired.cache_audit(r)["cache_audit_clean"])


class SwitchTests(unittest.TestCase):
    def test_boundary_vs_midturn_switches(self):
        main = [dict(ts_req=T0 + 1, ts_resp=T0 + 2, model=OPUS, uncached=10, read=0, write=1000),
                dict(ts_req=T0 + 3, ts_resp=T0 + 4, model=SONNET, uncached=10, read=0, write=1010),   # mid-turn switch
                dict(ts_req=T0 + 21, ts_resp=T0 + 22, model=OPUS, uncached=10, read=0, write=1030)]   # turn-boundary switch
        sw = paired.switch_metrics(main, [(T0, T0 + 10), (T0 + 20, T0 + 30)])
        self.assertEqual((sw["model_switches"], sw["switches_midturn"], sw["switches_turn_boundary"]), (2, 1, 1))
        self.assertGreater(sw["rebuild_usd"], 0)


class GateTests(unittest.TestCase):
    def test_plain_arm_must_have_no_receipts(self):
        self.assertTrue(paired.mechanism_gate({"kind": "plain"}, {}, 0, [OPUS])["mechanism_engaged"])
        g = paired.mechanism_gate({"kind": "plain"}, {"difficulty_judged": 1}, 0, [OPUS])
        self.assertFalse(g["mechanism_engaged"])

    def test_fd_arm_needs_difficulty_judged(self):
        self.assertFalse(paired.mechanism_gate({"kind": "fd"}, {"effort_routed": 3}, 0, [OPUS])["mechanism_engaged"])
        self.assertTrue(paired.mechanism_gate({"kind": "fd"}, {"difficulty_judged": 4}, 2, [OPUS, SONNET])["mechanism_engaged"])

    def test_sticky_must_never_switch(self):
        s = {"kind": "sticky", "expected_main_model": SONNET}
        self.assertTrue(paired.mechanism_gate(s, {"effort_routed": 5}, 0, [SONNET] * 5)["mechanism_engaged"])
        bad = paired.mechanism_gate(s, {"effort_routed": 5}, 1, [SONNET, OPUS])
        self.assertFalse(bad["mechanism_engaged"])
        self.assertTrue(any("switched" in r for r in bad["mechanism_reasons"]))
        self.assertFalse(paired.mechanism_gate(s, {"difficulty_judged": 3, "effort_routed": 1}, 0, [SONNET])["mechanism_engaged"])
        self.assertFalse(paired.mechanism_gate(s, {}, 0, [SONNET])["mechanism_engaged"])           # orchestrator not engaged
        self.assertFalse(paired.mechanism_gate(s, {"effort_routed": 1}, 0, [OPUS])["mechanism_engaged"])  # wrong model


class CovariateTests(unittest.TestCase):
    def test_whitelist_and_anchor_proxies_only(self):
        paired.assert_covariates(["task_type", "n_long_gaps", "turn1_prompt_chars", "anchor_cost_usd", "anchor_turn_costs"])
        for bad in ("cache_hit_share", "model_switches", "cost_usd_recomputed", "n_req", "tokens", "wall_ms", "arm_cost_usd"):
            with self.assertRaises(ValueError, msg=bad):
                paired.assert_covariates(["task_type", bad])

    def test_no_outcome_is_whitelisted(self):
        self.assertFalse(set(paired.OUTCOME_FIELDS) & set(paired.COVARIATE_WHITELIST))


class PairTests(unittest.TestCase):
    def row(self, arm, host, cost, **kw):
        r = {"scenario_id": "s", "rep": 1, "host": host, "arm": arm, "task_type": "feature", "n_long_gaps": 0, "cost_usd_recomputed": cost,
             "wall_ms": 60_000, "turn_pass_frac": 1.0, "final_state_pass": True, "wave_valid": True, "status": "ok", "n_req": 5,
             "mechanism_engaged": True, "cache_audit_clean": True}
        r.update(kw)
        return r

    def test_pairs_against_anchor_with_anchor_proxies(self):
        rows = [self.row("anchor", "opus", 1.0), self.row("shipped", "opus", 0.8, wall_ms=30_000), self.row("sonnet", "any", 0.5),
                self.row("anchor", "fable", 2.0)]
        turns = [{"scenario_id": "s", "rep": 1, "host": h, "arm": "anchor", "cost_usd_recomputed": c} for h, c in (("opus", 1.0), ("fable", 2.0))]
        pairs = paired.build_pairs(rows, turns)
        ship = next(p for p in pairs if p["arm"] == "shipped")
        self.assertAlmostEqual(ship["delta_usd"], -0.2)
        self.assertAlmostEqual(ship["log_cost_ratio"], __import__("math").log(0.8), places=5)
        self.assertEqual(ship["delta_s"], -30.0)
        self.assertEqual(rows[1]["anchor_cost_usd"], 1.0)
        self.assertNotIn("anchor_cost_usd", rows[0])             # never for the anchor itself
        sonnet = [p for p in pairs if p["arm"] == "sonnet"]
        self.assertEqual(sorted(p["host"] for p in sonnet), ["fable", "opus"])      # the control pairs with each stratum


class ToolsNormalizationTests(unittest.TestCase):
    """cost_usd_tools_normalized: the first request's tools-prefix tokens are repriced as a cache READ in every session."""
    ALLOW = 30_000

    def session(self, first_read, first_write, allowance=None):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reqs = [{"t": T0 + 1, "model": OPUS, "uncached": 100, "read": first_read, "write": first_write, "output": 50},
                {"t": T0 + 21, "model": OPUS, "uncached": 100, "read": 50_000, "write": 100, "output": 50},
                {"t": T0 + 25, "model": "claude-haiku-4-5", "uncached": 300, "read": 0, "write": 500, "output": 20, "main": False}]
        write_events(tmp / "events.jsonl", reqs)
        return paired.session_row(meta(), result_doc([(T0, T0 + 10), (T0 + 20, T0 + 30)]), paired.parse_events(tmp), SPEC, {}, {},
                                  self.ALLOW if allowance is None else allowance)

    def test_cold_first_request_is_repriced_as_a_read(self):
        row, trows = self.session(0, 40_000)
        r = paired._rates()._rates_for(OPUS, paired._rates().DEFAULT_RATES)
        expect_delta = -self.ALLOW * (r[3] - r[2]) / 1e6
        self.assertEqual(row["tools_repriced_tokens"], self.ALLOW)
        self.assertAlmostEqual(row["tools_normalized_delta_usd"], expect_delta, places=6)
        self.assertAlmostEqual(row["cost_usd_tools_normalized"], row["cost_usd_recomputed"] + expect_delta, places=6)
        self.assertGreater(row["cost_usd_recomputed"], row["cost_usd_tools_normalized"])
        self.assertAlmostEqual(row["cost_usd_provider"], row["cost_usd_recomputed"], places=6)        # raw basis untouched
        self.assertAlmostEqual(trows[0]["tools_normalized_delta_usd"], expect_delta, places=6)       # lands on turn 1 only
        self.assertEqual((trows[1]["tools_repriced_tokens"], trows[1]["tools_normalized_delta_usd"]), (0, 0))
        self.assertAlmostEqual(sum(t["cost_usd_tools_normalized"] for t in trows), row["cost_usd_tools_normalized"], places=6)

    def test_a_session_that_already_read_the_prefix_is_not_repriced_twice(self):
        warm, _ = self.session(self.ALLOW, 10_000)
        self.assertEqual((warm["tools_repriced_tokens"], warm["tools_normalized_delta_usd"]), (0, 0))
        self.assertEqual(warm["cost_usd_tools_normalized"], warm["cost_usd_recomputed"])
        part, _ = self.session(12_000, 40_000)              # read 12k already: only the remaining 18k are repriced
        self.assertEqual(part["tools_repriced_tokens"], self.ALLOW - 12_000)

    def test_cold_and_warm_sessions_converge_to_the_same_normalized_first_request(self):
        cold, _ = self.session(0, 40_000)
        warm, _ = self.session(self.ALLOW, 10_000)
        rc, rw = cold["cost_usd_tools_normalized"], warm["cost_usd_tools_normalized"]
        self.assertAlmostEqual(rc, rw, places=6)                                    # normalized: identical
        self.assertGreater(cold["cost_usd_recomputed"], warm["cost_usd_recomputed"])   # raw: the cold session paid the writes

    def test_zero_allowance_disables_the_normalization_and_background_is_untouched(self):
        row, _ = self.session(0, 40_000, allowance=0)
        self.assertEqual((row["tools_repriced_tokens"], row["cost_usd_tools_normalized"]), (0, row["cost_usd_recomputed"]))
        row, _ = self.session(0, 40_000)
        self.assertEqual(row["n_bg"], 1)
        self.assertEqual(sum(1 for q in row["_request_rows"] if q["tools_repriced_tokens"]), 1)      # only the first main request

    def test_request_rows_sum_to_the_session_totals(self):
        row, _ = self.session(0, 40_000)
        self.assertAlmostEqual(sum(q["cost_usd_tools_normalized"] for q in row["_request_rows"]), row["cost_usd_tools_normalized"], places=6)
        self.assertEqual([q["request_index"] for q in row["_request_rows"]], [1, 2, 3])

    def test_a_model_switch_also_normalizes_the_new_models_first_request(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        write_events(tmp / "events.jsonl", [
            {"t": T0 + 1, "model": OPUS, "uncached": 10, "read": 0, "write": 40_000, "output": 5},
            {"t": T0 + 21, "model": SONNET, "uncached": 10, "read": 0, "write": 41_000, "output": 5}])
        row, _ = paired.session_row(meta(), result_doc([(T0, T0 + 10), (T0 + 20, T0 + 30)]), paired.parse_events(tmp), SPEC, {}, {}, self.ALLOW)
        self.assertEqual(row["tools_repriced_tokens"], 2 * self.ALLOW)

    def test_pairs_carry_raw_and_normalized_with_normalized_primary(self):
        def row(arm, raw, norm, host="opus"):
            return {"scenario_id": "s", "rep": 1, "host": host, "arm": arm, "task_type": "feature", "n_long_gaps": 0, "cost_usd_recomputed": raw,
                    "cost_usd_tools_normalized": norm, "wall_ms": 1000, "turn_pass_frac": 1.0, "final_state_pass": True, "wave_valid": True,
                    "status": "ok", "n_req": 1, "mechanism_engaged": True, "cache_audit_clean": True}
        rows = [row("anchor", 1.0, 0.8), row("shipped", 0.9, 0.5)]
        turns = [{"scenario_id": "s", "rep": 1, "host": "opus", "arm": "anchor", "cost_usd_recomputed": 1.0, "cost_usd_tools_normalized": 0.8}]
        p = paired.build_pairs(rows, turns)[0]
        self.assertEqual(p["cost_basis"], "tools_normalized")
        self.assertAlmostEqual(p["delta_usd"], -0.3)
        self.assertAlmostEqual(p["delta_usd_raw"], -0.1)
        self.assertAlmostEqual(p["log_cost_ratio"], __import__("math").log(0.5 / 0.8), places=5)
        self.assertAlmostEqual(p["log_cost_ratio_raw"], __import__("math").log(0.9), places=5)
        self.assertEqual((p["anchor_cost_usd"], p["anchor_cost_usd_raw"]), (0.8, 1.0))
        self.assertEqual(rows[1]["anchor_turn_costs"], [0.8])

    def test_normalized_cost_is_an_outcome_not_a_covariate(self):
        with self.assertRaises(ValueError):
            paired.assert_covariates(["task_type", "cost_usd_tools_normalized"])
        self.assertIn("cost_usd_tools_normalized", paired.OUTCOME_FIELDS)

    def test_extract_rows_writes_requests_and_normalized_columns(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        sess_root, root = tmp / "sessions", tmp / "camp" / "w000-a1"
        sessions = []
        for arm, kind, write in (("anchor", "plain", 40_000), ("shipped", "fd", 25_000)):
            key = f"tiny-demo-r1-opus-{arm}"
            sessions.append(meta(key=key, arm=arm, kind=kind, nonce=f"n-{arm}"))
            (root / key / "workspace").mkdir(parents=True)
            (root / key / "result.json").write_text(json.dumps(result_doc([(T0, T0 + 10), (T0 + 20, T0 + 30)], sid=f"sid-{arm}")))
            extra = [{"ts": ts(T0 + 2), "event": "fast_decisions:difficulty_judged", "event_id": "e1", "data": {}}] if kind == "fd" else []
            write_events(sess_root / f"sid-{arm}" / "events.jsonl", [
                {"t": T0 + 1, "model": OPUS, "uncached": 10, "read": 25_000 if kind == "fd" else 0, "write": write, "output": 5},
                {"t": T0 + 21, "model": OPUS, "uncached": 10, "read": 60_000, "write": 10, "output": 5}], extra)
        out = tmp / "out"
        out.mkdir()
        (out / "schedule.json").write_text(json.dumps({"nonce_mode": "per_session", "plan_id": "p", "scenarios": {"tiny-demo": {"scenario_hash": "h"}}}))
        (out / "state.json").write_text(json.dumps({"waves": {"w": {"status": "done", "accepted_attempt": 1, "attempts": [
            {"attempt": 1, "root": str(root), "status": "done", "sessions": sessions, "wave_valid": True}]}}}))
        with patch.object(paired, "sessions_dir_for_workspace", lambda ws: sess_root):
            summary = paired.extract_rows(out, FakeBackend(tmp / "b", []), specs={"tiny-demo": SPEC}, snap_stats={}, tools_prefix_tokens=25_000)
        self.assertEqual(summary["requests"], 4)
        rows = {json.loads(l)["arm"]: json.loads(l) for l in (out / "rows" / "sessions.jsonl").read_text().splitlines()}
        self.assertEqual(rows["anchor"]["tools_repriced_tokens"], 25_000)
        self.assertEqual(rows["shipped"]["tools_repriced_tokens"], 0)            # already read the shared prefix
        self.assertGreater(rows["anchor"]["cost_usd_recomputed"], rows["shipped"]["cost_usd_recomputed"] - 1)
        pair = json.loads((out / "rows" / "pairs.jsonl").read_text().splitlines()[0])
        self.assertNotEqual(pair["delta_usd"], pair["delta_usd_raw"])
        self.assertEqual(len((out / "rows" / "requests.jsonl").read_text().splitlines()), 4)


class ExtractEndToEnd(unittest.TestCase):
    def test_extract_rows_from_a_synthetic_campaign(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        sess_root = tmp / "sessions"
        be = FakeBackend(tmp / "b", [])
        root = tmp / "camp" / "w000-a1"
        sessions = []
        for arm, kind, cost_scale in (("anchor", "plain", 1), ("shipped", "fd", 1)):
            key = f"tiny-demo-r1-opus-{arm}"
            sessions.append(meta(key=key, arm=arm, kind=kind, nonce=f"n-{arm}"))
            (root / key / "workspace").mkdir(parents=True)
            (root / key / "events").mkdir()
            windows = [(T0, T0 + 10), (T0 + 20, T0 + 30), (T0 + 40, T0 + 50)]
            (root / key / "result.json").write_text(json.dumps(result_doc(windows, (True, True, True), sid=f"sid-{arm}")))
            reqs = [{"t": T0 + 1, "model": OPUS, "uncached": 100, "read": 0, "write": 50_000 * cost_scale, "output": 100},
                    {"t": T0 + 21, "model": OPUS, "uncached": 100, "read": 50_000, "write": 100, "output": 100},
                    {"t": T0 + 41, "model": OPUS, "uncached": 100, "read": 50_100, "write": 100, "output": 100}]
            extra = [{"ts": ts(T0 + 2), "event": "fast_decisions:difficulty_judged", "event_id": "e1", "data": {}}] if kind == "fd" else []
            write_events(sess_root / f"sid-{arm}" / "events.jsonl", reqs, extra)
        out = tmp / "out"
        out.mkdir()
        plan = {"nonce_mode": "per_session", "plan_id": "p", "scenarios": {"tiny-demo": {"scenario_hash": "h"}}}
        (out / "schedule.json").write_text(json.dumps(plan))
        (out / "state.json").write_text(json.dumps({"waves": {"w": {"status": "done", "accepted_attempt": 1, "attempts": [
            {"attempt": 1, "root": str(root), "status": "done", "sessions": sessions, "wave_valid": True}]}}}))
        with patch.object(paired, "sessions_dir_for_workspace", lambda ws: sess_root):
            summary = paired.extract_rows(out, be, specs={"tiny-demo": SPEC}, snap_stats={"tiny-demo": {"workspace_files": 2, "workspace_bytes": 99}})
        self.assertEqual((summary["sessions"], summary["turns"], summary["pairs"]), (2, 6, 1))
        self.assertEqual(summary["mechanism_failed"], [])
        self.assertEqual(summary["cache_audit_flagged_sessions"], [])
        rows = [json.loads(l) for l in (out / "rows" / "sessions.jsonl").read_text().splitlines()]
        by = {r["arm"]: r for r in rows}
        self.assertEqual(by["shipped"]["anchor_cost_usd"], by["anchor"]["cost_usd_recomputed"])
        self.assertEqual(by["anchor"]["workspace_files"], 2)
        self.assertEqual(by["anchor"]["price_table_sha"], paired.price_table_sha())
        self.assertEqual(by["anchor"]["status"], "ok")
        self.assertTrue(by["anchor"]["final_state_pass"])
        pair = json.loads((out / "rows" / "pairs.jsonl").read_text().splitlines()[0])
        self.assertEqual(pair["arm"], "shipped")
        self.assertTrue(pair["valid"])


if __name__ == "__main__":
    unittest.main()
