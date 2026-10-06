"""Tests for evals/paired_dashboard.py: synthetic campaign, partial/missing files, and pilot-2 cost parity."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import paired as P  # noqa: E402
import paired_dashboard as D  # noqa: E402

PILOT = Path.home() / "dev" / "afast-paired" / "pilot-2"
MODEL = "claude-opus-5-5"


def write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def events(path: Path, outputs):
    lines = []
    for i, out in enumerate(outputs):
        lines.append({"event": "llm:request", "request_id": f"r{i}", "ts": "2026-10-01T10:00:00+00:00",
                      "data": {"model": MODEL, "has_system": True, "raw": {"tools": []}}})
        lines.append({"event": "llm:response", "request_id": f"r{i}", "ts": "2026-10-01T10:00:05+00:00",
                      "data": {"model": MODEL, "usage": {"input_tokens": 1000, "output_tokens": out,
                                                         "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.1}}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


class Fixture:
    """Two train waves (anchor/aa/shipped; shipped is ~half the anchor's output), one test wave, one running, one pending."""

    def __init__(self, tmp: Path):
        self.out = tmp / "camp"
        self.sess_root = tmp / "sessions"
        arms = ["anchor", "aa", "shipped"]
        scen = {"t1": {"split": "train", "turns": 3}, "t2": {"split": "train", "turns": 3},
                "x1": {"split": "test", "turns": 3}, "r1": {"split": "train", "turns": 3}, "p1": {"split": "train", "turns": 3}}
        waves, state_waves, spent = {}, {}, {}
        for i, (sid, wid) in enumerate([("t1", "t1-r1-opus"), ("t2", "t2-r1-opus"), ("x1", "x1-r1-opus")]):
            sess = [{"key": f"{wid}-{a}", "wave_id": wid, "scenario": sid, "rep": 1, "host": "opus", "arm": a, "est_usd": 2.0}
                    for a in arms]
            waves[wid] = sess
            root = self.out / f"w{i:03d}-a1"
            for s in sess:
                d = root / s["key"]
                out_tokens = {"anchor": 20000, "aa": 20000, "shipped": 10000}[s["arm"]] * (50 if sid == "x1" else 1)
                write(d / "result.json", {"session_id": "sid-" + s["key"], "outcome_passed": True,
                                          "started_at": "2026-10-01T10:00:00+00:00", "ended_at": f"2026-10-01T1{i}:30:00+00:00",
                                          "turns": [{"turn_passed": True}, {"turn_passed": s["arm"] != "shipped"}]})
                events(self.sess_root / ("sid-" + s["key"]) / "events.jsonl", [out_tokens])
            state_waves[wid] = {"status": "done", "accepted_attempt": 1,
                                "attempts": [{"attempt": 1, "root": str(root), "status": "done", "sessions": sess, "wave_valid": True}]}
            spent[f"{wid}#a1"] = 3.0
        rw = "r1-r1-opus"
        rs = [{"key": f"{rw}-anchor", "wave_id": rw, "scenario": "r1", "rep": 1, "host": "opus", "arm": "anchor", "est_usd": 2.0}]
        waves[rw] = rs
        state_waves[rw] = {"status": "running", "accepted_attempt": None,
                           "attempts": [{"attempt": 1, "root": str(self.out / "w003-a1"), "status": "running", "sessions": rs}]}
        rd = self.out / "w003-a1" / f"{rw}-anchor"
        write(rd / "running.json", {"started_at": "2026-10-01T12:00:00+00:00", "controller_pid": 999999999, "turn": 2})
        (rd / "turn-snapshots").mkdir(parents=True)
        (rd / "turn-snapshots" / "t1.tar.gz").write_bytes(b"x")          # one graded turn of three
        waves["p1-r1-opus"] = [{"key": "p1-r1-opus-anchor", "wave_id": "p1-r1-opus", "scenario": "p1", "rep": 1, "host": "opus",
                                "arm": "anchor", "est_usd": 2.0}]
        write(self.out / "schedule.json", {"plan_id": "fx", "design": "no-such-design", "scenarios": scen, "waves": waves,
                                           "wave_order": list(waves), "parallel": 4, "budget_usd": 100.0, "est_total_usd": 20.0})
        write(self.out / "state.json", {"waves": state_waves})
        write(self.out / "ledger.json", {"budget_usd": 100.0, "reserved": {f"{rw}#a1": 2.0}, "spent": spent})
        (self.out / "run.log").write_text("ok\nTraceback: boom\n", encoding="utf-8")


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

    def collect(self, fx, **kw):
        patch = mock.patch.object(P, "sessions_dir_for_workspace", lambda ws: fx.sess_root)
        patch.start()
        self.addCleanup(patch.stop)
        return D.collect(fx.out, self.tmp_path / "cache.json", **kw)

    def test_synthetic_campaign(self):
        fx = Fixture(self.tmp_path)
        m = self.collect(fx)
        self.assertEqual(m["counts"], {"done": 3, "running": 1, "pending": 1, "excluded": 0, "config_error": 0, "other": 0})
        self.assertEqual(m["total_waves"], 5)
        self.assertEqual(m["done_sessions"], 9)
        self.assertEqual(m["running"][0]["sessions"][0]["turn"], 2)
        self.assertEqual(m["running"][0]["sessions"][0]["state"], "not alive")
        self.assertAlmostEqual(m["spend"]["spent"], 9.0)
        self.assertAlmostEqual(m["spend"]["reserved"], 2.0)
        self.assertEqual(m["spend"]["costed"], 9)
        rows = {r["arm"]: r for r in m["interim"]}
        self.assertEqual(rows["aa"]["n"], 2)                       # the two TRAIN waves only
        self.assertAlmostEqual(rows["aa"]["gm"], 1.0)
        self.assertLess(rows["shipped"]["gm"], 1.0)
        self.assertGreater(rows["shipped"]["saved"], 0)
        self.assertAlmostEqual(rows["shipped"]["q_arm"], 0.5)
        self.assertEqual(rows["shipped"]["q_anchor"], 1.0)
        # exact cost: 1000 input * opus rate + 20000 output * rate, on the same function paired.py uses
        want = P.recompute_cost(MODEL, 1000, 0, 0, 20000)
        e = next(v for k, v in D.Cache(self.tmp_path / "cache.json").sessions.items() if k.endswith("t1-r1-opus-anchor"))
        self.assertAlmostEqual(e["cost_norm"], want)

    def test_progress_is_work_weighted(self):
        fx = Fixture(self.tmp_path)
        m = self.collect(fx)
        pg = m["progress"]
        o = pg["overall"]
        self.assertEqual((o["n"], o["done"], o["running"], o["pending"], o["excluded"]), (11, 9, 1, 1, 0))
        self.assertEqual(o["turns"], 33)                           # 11 sessions x 3 scripted turns
        self.assertEqual(o["turns_done"], 28)                      # 9 finished x 3 + 1 graded turn of the running one
        self.assertAlmostEqual(o["est_done"], 9 * 2.0 + 2.0 / 3)   # running session counts 1/3 of its estimate
        ah = {r["label"]: r for r in pg["by_arm_host"]}
        self.assertEqual(ah["anchor x opus"]["n"], 5)
        self.assertEqual(ah["anchor x opus"]["running"], 1)
        self.assertEqual(ah["shipped x opus"]["done"], 3)
        splits = {r["label"]: r for r in pg["by_split"]}
        self.assertEqual(splits["test"]["done"], 3)                # progress counts for test are shown
        self.assertEqual(sum(r["n"] for r in pg["by_band"]), 11)
        pairs = {(r["host"], r["arm"]): r for r in pg["pairs"]}
        self.assertEqual((pairs[("opus", "shipped")]["complete"], pairs[("opus", "shipped")]["total"]), (3, 3))
        self.assertEqual(pairs[("opus", "shipped")]["train_complete"], 2)
        self.assertIsNotNone(pg["turns_left"])
        html = D.render(m)
        for needle in ("Progress by arm and host", "Anchor-paired comparisons", "% turns done", "ETA (uses turns/hour)"):
            self.assertIn(needle, html)

    def test_holdout_split_is_blinded_like_test(self):
        """holdout-v3 scenarios all carry split `holdout`: the dashboard must show spend and health, never per-arm results."""
        fx = Fixture(self.tmp_path)
        sched = json.loads((fx.out / "schedule.json").read_text(encoding="utf-8"))
        for v in sched["scenarios"].values():
            v["split"] = "holdout"
        (fx.out / "schedule.json").write_text(json.dumps(sched), encoding="utf-8")
        m = self.collect(fx)
        self.assertEqual(m["interim"], [])
        self.assertIn("holdout", D.render(m))
        self.assertTrue(self.collect(fx, show_test=True)["interim"])

    def test_html_hides_test_split_and_is_self_contained(self):
        fx = Fixture(self.tmp_path)
        html = D.render(self.collect(fx))
        self.assertIn("INTERIM, NOT CONFIRMATORY", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", html)
        for needle in ("prefers-color-scheme", "<caption>", 'scope="col"', 'http-equiv="refresh"', "STALE"):
            self.assertIn(needle, html)
        shown = D.render(self.collect(fx, show_test=True))
        self.assertIn("breaks the preregistered blinding", shown)
        hidden = {r["arm"]: r for r in self.collect(fx)["interim"]}
        with_test = {r["arm"]: r for r in self.collect(fx, show_test=True)["interim"]}
        self.assertEqual(hidden["shipped"]["n"], 2)
        self.assertEqual(with_test["shipped"]["n"], 3)

    def test_parse_budget_defers_then_completes(self):
        fx = Fixture(self.tmp_path)
        m = self.collect(fx, parse_budget_s=-1)                     # budget already exhausted
        self.assertEqual(m["spend"]["costed"], 0)
        self.assertEqual(m["spend"]["uncosted"], 9)
        D.render(m)
        m = self.collect(fx, parse_budget_s=60)
        self.assertEqual(m["spend"]["costed"], 9)

    def test_missing_files_render(self):
        empty = self.tmp_path / "empty"
        empty.mkdir()
        html = D.render(D.collect(empty, self.tmp_path / "c.json"))
        self.assertIn("missing or unreadable", html)
        partial = self.tmp_path / "partial"
        write(partial / "state.json", {"waves": {"a": {"status": "excluded", "attempts": [{"attempt": 1, "status": "config_error", "reason": "bad"}]}}})
        m = D.collect(partial, self.tmp_path / "c2.json")
        D.render(m)
        self.assertEqual(m["counts"]["excluded"], 1)

    @unittest.skipUnless((PILOT / "rows" / "sessions.jsonl").exists(), "pilot-2 campaign not on this machine")
    def test_pilot2_matches_paired_rows(self):
        m = D.collect(PILOT, self.tmp_path / "pilot.json")
        D.render(m)
        rows = [json.loads(x) for x in (PILOT / "rows" / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
        want = sum(r["cost_usd_tools_normalized"] for r in rows)
        self.assertEqual(m["spend"]["costed"], len(rows))
        self.assertLess(abs(m["spend"]["measured_norm"] - want) / want, 0.01)
        self.assertLess(abs(m["spend"]["measured_provider"] - sum(r["cost_usd_provider"] for r in rows)) / want, 0.01)


if __name__ == "__main__":
    unittest.main()
