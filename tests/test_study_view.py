"""Read-only study projection and exclusion of benchmark-internal test receipts."""
import json
from pathlib import Path
import tempfile
import unittest
from amplifier_fast_decisions.study_view import StudyView
from amplifier_fast_decisions.server import EventIndex

class StudyViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.job = dict(job_id="one", harness="amplifier", arm="fd-local")
        (self.root / "schedule.json").write_text(json.dumps({"jobs": [self.job]}))
        (self.root / "state.json").write_text(json.dumps({"status": "running", "private": "SECRET"}))
        self.row = dict(self.job, grade={"accepted": True, "private": "SECRET"},
                        wall_seconds=12, fd_event_counts={"fast_decisions:requested": 2})
        self.results = self.root / "results.jsonl"
        self.results.write_text(json.dumps(self.row) + "\n")
    def tearDown(self):
        self.temp.cleanup()
    def test_partial_summary_is_allowlisted_and_does_not_invent_savings(self):
        with self.results.open("a") as stream:
            stream.write('{"job_id":')
        summary = StudyView(self.root).summary()
        self.assertEqual(summary["completed"], 1)
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["net_time_saved_seconds"])
        self.assertNotIn("SECRET", json.dumps(summary))
        arm = next(a for a in summary["arms"] if a["harness"] == "amplifier" and a["arm"] == "fd-local")
        self.assertEqual((arm["passed"], arm["fd_requests"], arm["median_seconds"]), (1, 2, 12))
    def test_duplicate_or_mismatched_assignment_is_unavailable(self):
        self.results.write_text((json.dumps(self.row) + "\n") * 2)
        self.assertFalse(StudyView(self.root).summary()["available"])
        self.results.write_text(json.dumps(dict(self.row, arm="fd-jev")) + "\n")
        self.assertFalse(StudyView(self.root).summary()["available"])
    def test_only_matched_root_receipts_and_new_appends_are_visible(self):
        run = self.root / "runs" / "one"
        events = run / "fd-events"
        events.mkdir(parents=True)
        (run / "result.json").write_text(json.dumps({"session_id": "real"}))
        def event(identity, session):
            return dict(schema_version="1.0", event_id=identity, session_id=session,
                        event="fast_decisions:requested", data={"prompt": "SECRET", "candidate_count": 2})
        real = events / "real-receipts.jsonl"
        real.write_text(json.dumps(event("one", "real")) + "\n" + json.dumps(event("wrong", "test-session")) + "\n")
        (events / "test-session-receipts.jsonl").write_text(json.dumps(event("test", "test-session")) + "\n")
        index = EventIndex(self.root / "ordinary", study=StudyView(self.root))
        first = index.get()
        self.assertEqual([e["event_id"] for e in first["events"]], ["one"])
        self.assertNotIn("SECRET", json.dumps(first))
        with real.open("a") as stream:
            stream.write(json.dumps(event("two", "real")) + "\n")
        self.assertEqual([e["event_id"] for e in index.get(after=first["cursor"])["events"]], ["two"])
