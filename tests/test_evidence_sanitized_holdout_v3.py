"""Guards docs/evidence/2026-10-06-holdout-v3 the same way tests/test_evidence_sanitized_effort_fable.py guards the effort-control package.

No home path, key or bearer token, no field that can hold prompt/response text, no unscrubbed terminal tail; SHA256SUMS covers every file; row counts
match data/summary.json; s1_result.json has the fields the v3 paper reads and agrees with a fresh run of the preregistered analysis; the preregistration
commit precedes the first session.  Reads files only: no model calls, no network.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_evidence_sanitized import FORBIDDEN_TEXT, MAX_JSON_STRING, json_values, lines

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "2026-10-06-holdout-v3"


def evidence_files():
    return sorted(p for p in EVIDENCE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def load(rel: str):
    return json.loads((EVIDENCE / rel).read_text(encoding="utf-8"))


class HoldoutV3EvidenceSanitized(unittest.TestCase):
    def test_present(self):
        self.assertTrue(EVIDENCE.is_dir(), EVIDENCE)
        self.assertGreater(len(evidence_files()), 15)

    def test_no_home_path_keys_or_tokens(self):
        hits = []
        for p in evidence_files():
            for n, line in lines(p):
                for label, rx in FORBIDDEN_TEXT:
                    m = rx.search(line)
                    if m:
                        hits.append(f"{p.relative_to(EVIDENCE)}:{n}: {label}: ...{line[max(m.start() - 15, 0):m.start() + 25].strip()!r}")
        self.assertFalse(hits, "\n".join(hits[:20]))

    def test_no_prompt_or_response_text_fields(self):
        hits = []
        for p in evidence_files():
            for n, key, val in json_values(p):
                if val is None:
                    hits.append(f"{p.relative_to(EVIDENCE)}:{n}: field {key!r} can hold prompt/response text")
                elif len(val) > (4000 if key in ("reason", "excluded_reason") else MAX_JSON_STRING):  # scrubbed per-session failure lists are long, tails are not
                    hits.append(f"{p.relative_to(EVIDENCE)}:{n}: string of {len(val)} chars under {key!r}")
        self.assertFalse(hits, "\n".join(hits[:20]))

    def test_no_terminal_tails_or_escapes(self):
        marker = re.compile(r" -- (?!\[terminal tail omitted: \d+ chars, sha256:[0-9a-f]{8}\])")
        hits = []
        for p in evidence_files():
            for n, line in lines(p):
                if "OUTPUT TRUNCATED" in line or "\x1b[" in line or "\\x1b[" in line:
                    hits.append(f"{p.relative_to(EVIDENCE)}:{n}: raw terminal output")
                if p.suffix == ".log" and ("transient infrastructure failure" in line or "worker vanished" in line) and marker.search(line):
                    hits.append(f"{p.relative_to(EVIDENCE)}:{n}: unscrubbed text after ' -- '")
        for n, k, v in json_values(EVIDENCE / "campaign" / "state.json"):
            if k in ("reason", "excluded_reason") and v and marker.search(v):
                hits.append(f"campaign/state.json:{n}: unscrubbed reason")
        self.assertFalse(hits, "\n".join(hits[:20]))

    def test_key_fingerprints_are_short_sha_prefixes(self):
        for n, key, val in json_values(EVIDENCE / "data" / "sessions.jsonl"):
            if key == "key_fingerprint":
                self.assertRegex(val, r"^[0-9a-f]{8,12}$", f"sessions.jsonl:{n}")

    def test_checksums_cover_every_file(self):
        listed = {}
        for line in (EVIDENCE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            digest, _, rel = line.partition("  ")
            listed[rel] = digest
        actual = {p.relative_to(EVIDENCE).as_posix(): p for p in evidence_files() if p.name not in ("SHA256SUMS", "README.md")}
        self.assertEqual(sorted(listed), sorted(actual), "SHA256SUMS out of date: rerun reproduce/package_evidence.py")
        bad = [r for r, p in actual.items() if hashlib.sha256(p.read_bytes()).hexdigest() != listed[r]]
        self.assertFalse(bad, bad[:10])

    def test_row_counts_and_flag_lists_match_summary(self):
        summary = load("data/summary.json")
        for name in ("sessions", "turns", "pairs", "requests"):
            f = EVIDENCE / "data" / (name + (".jsonl.gz" if name == "requests" else ".jsonl"))
            self.assertEqual(sum(1 for _ in lines(f)), summary[name], name)
        self.assertEqual((summary["sessions"], summary["turns"], summary["requests"], summary["pairs"]), (1224, 12856, 49254, 1104))
        self.assertEqual(len(summary["mechanism_failed"]), 8)
        self.assertTrue(all(k.startswith("bleach-sanitize-review-") and "-fable-" in k for k in summary["mechanism_failed"]))
        self.assertEqual(sorted(summary["cost_mismatch"]),
                         ["bleach-sanitize-review-r1-opus-anchor", "bleach-sanitize-review-r2-opus-anchor"])
        self.assertEqual(len(summary["cache_audit_flagged_sessions"]), 4)
        self.assertTrue(all(k.startswith("black-pipeline-explain-r2-") for k in summary["cache_audit_flagged_sessions"]))
        self.assertEqual(summary["killed_memory"], [])
        text = (EVIDENCE / "FLAGS.md").read_text(encoding="utf-8")
        for needle in ("bleach-sanitize-review", "claude-sonnet-5-5", "black-pipeline-explain", "3,642", "0.33%", "stop rule"):
            self.assertIn(needle, text)

    def test_result_has_the_fields_the_paper_reads(self):
        r = load("s1_result.json")
        self.assertEqual(r["schema"], "fast-decisions-v3-s1-result/v1")
        self.assertEqual((r["n_scenarios"], r["seed"], r["resamples"], r["health"]["n_sessions"]), (60, 20261005, 10000, 1224))
        for h in ("H1", "H2", "H3", "H3b", "H4", "H5", "H6", "H7"):
            e = r["hypotheses"][h]["estimate"]
            for k in ("gm_ratio", "gm_ratio_ci95", "d_turn_pass", "d_turn_pass_ci95"):
                self.assertIn(k, e, f"{h}.{k}")
            self.assertIn("p_holm", r["hypotheses"][h])
            self.assertIn("supported", r["hypotheses"][h])
        self.assertIn("decision", r["hypotheses"]["H2"])
        for host in ("fable", "opus"):
            f = r["freeze"][host]
            for k in ("chosen", "selected_on_holdout", "table"):
                self.assertIn(k, f)
            self.assertGreater(len(f["table"]), 5)
        self.assertEqual(load("result/s1_result.json"), r)
        self.assertTrue(r["freeze"]["fable"]["selected_on_holdout"])
        self.assertFalse(r["freeze"]["opus"]["selected_on_holdout"])
        sup = {h: r["hypotheses"][h]["supported"] for h in ("H1", "H2", "H3", "H4", "H5", "H6", "H7")}
        self.assertEqual(sup, {"H1": True, "H2": True, "H3": True, "H4": False, "H5": True, "H6": True, "H7": False})

    def test_result_reproduces_from_the_published_rows(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable, str(REPO / "evals" / "v3" / "s1_analysis.py"), "--sessions", str(EVIDENCE / "data" / "sessions.jsonl"),
                            "--out", td, "--resamples", "10000", "--seed", "20261005"], check=True, capture_output=True, cwd=REPO)
            self.assertEqual(json.loads((Path(td) / "s1_result.json").read_text(encoding="utf-8")), load("s1_result.json"))

    def test_preregistration_precedes_first_session(self):
        text = (EVIDENCE / "prereg" / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("**PASS**", text)
        self.assertTrue((EVIDENCE / "prereg" / "PREREGISTRATION-holdout-v3.md").is_file())
        starts = [json.loads(l)["actual_start"] for _, l in lines(EVIDENCE / "data" / "sessions.jsonl") if l.strip()]
        self.assertIn(min(starts), text)
        self.assertIn("6ea0fd3", text)
        self.assertIn(load("campaign/schedule.json")["created_at"], text)
        self.assertNotIn("CHANGED", text)


if __name__ == "__main__":
    unittest.main()
