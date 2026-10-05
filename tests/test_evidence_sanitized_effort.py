"""Guards docs/evidence/2026-10-05-effort-control the same way tests/test_evidence_sanitized.py guards the main-v1 package.

No home path, key or bearer token, no field that can hold prompt/response text, no unscrubbed terminal tail; SHA256SUMS covers every
file; row counts match summary.json; summary.json (the paper-reader schema) agrees with result/effort-result.json; the preregistration
commit precedes the first session.  Reads files only: no model calls, no network.
"""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from test_evidence_sanitized import FORBIDDEN_TEXT, MAX_JSON_STRING, json_values, lines

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "2026-10-05-effort-control"


def evidence_files():
    return sorted(p for p in EVIDENCE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def load(rel: str):
    return json.loads((EVIDENCE / rel).read_text(encoding="utf-8"))


class EffortEvidenceSanitized(unittest.TestCase):
    def test_present(self):
        self.assertTrue(EVIDENCE.is_dir(), EVIDENCE)
        self.assertGreater(len(evidence_files()), 10)

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
                elif len(val) > MAX_JSON_STRING:
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
            if k == "reason" and v and marker.search(v):
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

    def test_row_counts_match_summary(self):
        summary = load("data/summary.json")
        for name in ("sessions", "turns", "pairs", "requests"):
            f = EVIDENCE / "data" / (name + (".jsonl.gz" if name == "requests" else ".jsonl"))
            self.assertEqual(sum(1 for _ in lines(f)), summary[name], name)
        for k in ("cache_audit_flagged_sessions", "mechanism_failed", "killed_memory", "cost_mismatch"):
            self.assertEqual(summary[k], [], k)

    def test_summary_schema_matches_result(self):
        s, r = load("summary.json"), load("result/effort-result.json")
        self.assertEqual(set(s) - {"quality", "HE_supported"}, {"description", "rows"})
        for row in s["rows"]:
            self.assertEqual(set(row), {"label", "n_pairs", "gm_ratio", "ci95"})
            self.assertLess(row["ci95"][0], row["gm_ratio"])
            self.assertLess(row["gm_ratio"], row["ci95"][1])
        a, c = s["rows"]
        self.assertEqual((a["n_pairs"], a["gm_ratio"], a["ci95"]), (46, r["cost"]["geo_mean_ratio"], r["cost"]["ci95"]))
        sec = r["secondary_vs_main_v1_sticky_sonnet"]
        self.assertEqual((c["gm_ratio"], c["ci95"]), (sec["geo_mean_ratio_medium_over_sticky_cheap"], sec["ci95"]))
        self.assertEqual(s["quality"]["mean_delta_turn_pass"], r["quality"]["mean_delta_turn_pass"])
        self.assertTrue(s["HE_supported"] and r["HE_supported"])
        self.assertLess(a["ci95"][1], 1.0)
        self.assertGreater(s["quality"]["ci95"][0], -0.05)

    def test_preregistration_precedes_first_session(self):
        text = (EVIDENCE / "prereg" / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("**PASS**", text)
        self.assertTrue((EVIDENCE / "prereg" / "PREREGISTRATION-effort-control-v1.md").is_file())
        starts = [json.loads(l)["actual_start"] for _, l in lines(EVIDENCE / "data" / "sessions.jsonl") if l.strip()]
        self.assertIn(min(starts), text)


if __name__ == "__main__":
    unittest.main()
