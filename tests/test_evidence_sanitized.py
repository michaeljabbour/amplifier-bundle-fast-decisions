"""Guards the committed campaign evidence directory (docs/evidence/2026-10-02-paired-campaign).

Fails when the directory contains the home path, a key or bearer token, a field that can hold prompt/response text, or
an unscrubbed terminal tail; also checks SHA256SUMS and that the row counts match summary.json.  Reads files only:
no model calls, no network, nothing outside the repository.

The word `api_key` is allowed as a config-key NAME (sessions rows list the provider's config key names); an
`api_key` followed by a value is not.  `sk-` only counts at a word start, so ordinary words ending in "sk" do not trip it.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "docs" / "evidence" / "2026-10-02-paired-campaign"

HOME = str(Path.home())
FORBIDDEN_TEXT = [
    ("home directory", re.compile(re.escape(HOME))),
    ("user home path", re.compile(r"/Users/[^/\s\"']+|/home/[a-z_][a-z0-9_-]*/|[A-Za-z]:\\\\Users\\\\")),
    ("username", re.compile(re.escape(Path.home().name))),
    ("sk- key", re.compile(r"(?<![A-Za-z0-9])sk-")),
    ("Bearer token", re.compile(r"Bearer ")),
    ("api_key with a value", re.compile(r"api[_-]key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{6,}", re.IGNORECASE)),
    ("key env assignment", re.compile(r"[A-Z_]*API_KEY\s*=\s*\S")),
]
# JSON keys that could hold prompt or response text; none exists in the published rows
FORBIDDEN_KEYS = {"prompt", "prompts", "response", "responses", "text", "content", "message", "messages", "stdout",
                  "stderr", "output_text", "tail", "transcript", "completion", "body"}
MAX_JSON_STRING = 600
SKIP_DIRS = {"__pycache__"}


def evidence_files():
    return sorted(p for p in EVIDENCE.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.parts))


def lines(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        yield from enumerate(fh, start=1)


def json_values(path: Path):
    """Yield (line_no, key, value) for every JSON leaf; (line_no, key, None) for a forbidden key."""
    name = path.name
    if name.endswith((".jsonl", ".jsonl.gz")):
        objs = ((n, json.loads(line)) for n, line in lines(path) if line.strip())
    elif name.endswith(".json"):
        objs = [(0, json.loads(path.read_text(encoding="utf-8")))]
    else:
        return

    def walk(n, v, key):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in FORBIDDEN_KEYS:
                    yield n, k, None
                yield from walk(n, x, k)
        elif isinstance(v, list):
            for x in v:
                yield from walk(n, x, key)
        elif isinstance(v, str):
            yield n, key, v

    for n, o in objs:
        yield from walk(n, o, None)


class EvidenceSanitized(unittest.TestCase):
    def test_evidence_dir_present(self):
        self.assertTrue(EVIDENCE.is_dir(), EVIDENCE)
        self.assertGreater(len(evidence_files()), 20)

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

    def test_failure_reasons_have_no_terminal_tails(self):
        """Harness failure reasons embed the last lines of agent terminal output after ' -- '; only the scrubbed marker may follow."""
        hits = []
        marker = re.compile(r" -- (?!\[terminal tail omitted: \d+ chars, sha256:[0-9a-f]{8}\])")
        for p in evidence_files():
            if p.suffix in (".log", ".html"):
                cands = ((n, l) for n, l in lines(p) if "transient infrastructure failure" in l or "worker vanished" in l)
            elif p.name in ("state.json",):
                cands = ((n, v) for n, k, v in json_values(p) if k == "reason" and v)
            else:
                continue
            for n, text in cands:
                if marker.search(text):
                    hits.append(f"{p.relative_to(EVIDENCE)}:{n}: unscrubbed text after ' -- '")
        self.assertFalse(hits, "\n".join(hits[:20]))

    def test_no_raw_terminal_output_markers(self):
        hits = [f"{p.relative_to(EVIDENCE)}:{n}" for p in evidence_files() if p.name != "FAILURES.md"
                for n, line in lines(p) if "OUTPUT TRUNCATED" in line or "\x1b[" in line or "\\x1b[" in line]
        self.assertFalse(hits, "\n".join(hits[:20]))

    def test_key_fingerprints_are_short_sha_prefixes(self):
        for name in ("data/sessions.jsonl", "pilot/sessions.jsonl"):
            for n, key, val in json_values(EVIDENCE / name):
                if key == "key_fingerprint":
                    self.assertRegex(val, r"^[0-9a-f]{8,12}$", f"{name}:{n}")

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
        summary = json.loads((EVIDENCE / "data" / "summary.json").read_text(encoding="utf-8"))
        for name in ("sessions", "turns", "pairs", "requests"):
            f = EVIDENCE / "data" / (name + (".jsonl.gz" if name == "requests" else ".jsonl"))
            self.assertEqual(sum(1 for _ in lines(f)), summary[name], name)


if __name__ == "__main__":
    unittest.main()
