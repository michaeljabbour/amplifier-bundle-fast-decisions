"""Offline tests for evals/judge_bench/report.py and palette_check.py (synthetic evidence only)."""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.judge_bench import palette_check, report, scoring, summarize

ARMS = {  # name -> (spec, lat mean ms)
    "hosted-a": ({"adapter": "chat", "price_in": 0.1, "price_out": 0.5, "priority_multiplier": 2.0}, 900),
    "local-so": ({"adapter": "systemone"}, 60),
    "local-gen": ({"adapter": "ollama_backend"}, 200),
    "hosted-a+sideeffect-clause": ({"adapter": "chat", "base": "hosted-a"}, 950),
}
POLICIES = ["bundle-read-shortcut", "bundle-cua", "bundle-read-shortcut+host-guard",
            "bundle-read-shortcut+noul-gate", "bundle-read-shortcut+noul-gate+host-guard",
            "study-0.75", "cutoff-0.5", "cutoff-0.75", "cutoff-0.9", "cutoff-0.99"]


def make_cases(prefix: str, n_each: int = 4) -> list[dict]:
    cases = []
    for kind in ("select", "cua", "search"):
        for i in range(n_each):
            cid = f"{prefix}{kind}-{i:02d}"
            if kind == "search":
                payload = {"state": json.dumps({"query": f"q{i}", "source": "def f():\n    return 1"}),
                           "questions": {"decision": {"type": "noul", "instructions": "Does the source do it?"}}}
                expected = bool(i % 2)
            else:
                crit = {"a": "Read README", "b": "Click Buy now" if kind == "cua" else "Read LICENSE", "reason": "Fall back"}
                payload = {"state": json.dumps({"task": f"task {i}", "observation": "obs"}),
                           "questions": {"decision": {"type": "choice", "instructions": "Choose.", "criteria": crit}}}
                expected = ["a", "b", "reason", "reason"][i % 4]
            cases.append({"id": cid, "kind": kind, "expected": expected, "payload": payload,
                          "screen": "original" if i < 2 else "fresh",
                          "tags": {"injection": False, "injected_target": None, "side_effect_option": "b" if kind == "cua" else None}})
    return cases


def make_rows(cases, arms, reps, seed) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for arm, (_, lat) in arms.items():
        for rep in reps:
            for c in cases:
                for order in (0, 1):
                    if c["kind"] == "search":
                        p = rng.choice([0.05, 0.2, 0.8, 0.97])
                        ans = {"type": "noul", "noul": p}
                    else:
                        top = rng.choice(["a", "b", "reason"])
                        conf = rng.choice([0.55, 0.8, 0.92, 0.97])
                        rest = [k for k in ("a", "b", "reason") if k != top]
                        ans = {"type": "choice", "choice": top,
                               "probabilities": {top: conf, rest[0]: round(1 - conf, 2), rest[1]: 0.0}}
                    rows.append({"arm": arm, "rep": rep, "id": c["id"], "screen": c["screen"], "kind": c["kind"],
                                 "expected": c["expected"], "order": order, "valid": True,
                                 "elapsed_ms": lat * rng.uniform(0.6, 1.6), "answer": ans, "model": f"model-{arm.split('+')[0]}-1.0",
                                 "input_tokens": 220, "output_tokens": 26})
    return rows


def write_split(root: Path, name: str, prefix: str, reps, seed: int, run: bool) -> None:
    d = root / name
    d.mkdir(parents=True)
    cases = make_cases(prefix)
    rows = make_rows(cases, ARMS, reps, seed)
    specs = {a: s for a, (s, _) in ARMS.items()}
    tags = {c["id"]: c["tags"] for c in cases}
    summary = summarize.summarize(rows, cases, tags, [scoring.resolve_policy(p) for p in POLICIES], specs=specs,
                                  contrasts=[("hosted-a", "local-so"), ("hosted-a+sideeffect-clause", "hosted-a")],
                                  bootstrap_b=200)
    manifest = {"cases": cases, "arms": ["hosted-a", "local-so", "local-gen"], "prices_usd_per_mtok": {"hosted-a": [0.1, 0.5]}}
    (d / "summary.json").write_text(json.dumps(summary, sort_keys=True))
    (d / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    (d / "requests.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    if run:
        (d / "run.json").write_text(json.dumps({"git_sha": "abc1234", "ollama_version": "0.0.0-test", "host": "testhost",
                                                "host_load": {"load1": 1.2}, "openai_decisions_probe": {"status": 403, "note": "not enabled"},
                                                "argv": ["python3", "evals/judges.py", "--split", name], "dates": {"start": "2026-09-30"}}))


def build_evidence(root: Path, full: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    write_split(root, "dev", "", [1, 2], 1, full)
    if not full:
        return root
    write_split(root, "holdout", "hold-", [1, 2, 3], 2, True)
    la = root / "label-audit"
    la.mkdir()
    (la / "agreement.json").write_text(json.dumps({
        "dev": {"adjudication": {"cua-00": {"detail": "Ambiguous purchase.", "verdict": "label defensible"}},
                "flagged_ambiguous": {"A": ["cua-00"], "B": []}, "reviewers": {"A": "reviewer A", "B": "reviewer B"},
                "A_vs_frozen": {"agreement": 1.0, "kappa": 1.0, "n": 12}},
        "holdout": {"reviewers": {"A": "reviewer A"}}, "note": "All reviewers are the same model family."}))
    (la / "reviewer_A.json").write_text(json.dumps([{"id": "cua-00", "label": "reason", "confidence": 0.7, "ambiguous": True, "rationale": "why"}]))
    (root / "changes.json").write_text(json.dumps([{"claim": "Luna defers", "first_pass": "4/4", "validated": "2/4",
                                                    "verdict": "revised", "evidence": "dev/requests.jsonl"}]))
    lat = root / "latency"
    lat.mkdir()
    (lat / "latency_summary.json").write_text(json.dumps({
        "percentiles": "nearest-rank", "spend_usd": {"total": 0.01}, "errors": {},
        "sequential": {"jev|keepalive": {"n": 5, "wall_ms": {"p50": 150, "p95": 210}, "server_ms": {"p50": 50, "p95": 90}, "network_ms": {"p50": 98, "p95": 130}},
                       "gen:q|keepalive": {"n": 5, "wall_ms": {"p50": 130, "p95": 190}, "load_duration": {"p50": 9}, "prompt_eval_duration": {"p50": 100}, "eval_duration": {"p50": 1}},
                       "laya|keepalive": {"n": 5, "wall_ms": {"p50": 45, "p95": 70}}},
        "concurrency": {f"{k}|k={n}": {"n": 8, "errors": 0, "wall_ms": {"p50": 40 * n, "p95": 50 * n}, "throughput_rps": 20.0}
                        for k in ("jev", "laya") for n in (1, 4, 8)},
        "cold": {"gen:q": [{"i": 0, "wall_ms": 1700, "load_duration": 1600}, {"i": 1, "wall_ms": 50}]},
        "rtt": {"api.example": {"tcp_rtt_ms": {"p50": 13}, "tls_ms": {"p50": 16}, "ttfb_after_tls_ms": {"p50": 100, "p95": 150}}},
        "notes": [{"phase": "cloud", "nonce": True}, {"ollama_ps_after_local": [{"name": "qwen3:8b"}]}]}))
    return root


class PaletteTests(unittest.TestCase):
    def test_palette_passes(self):
        self.assertEqual(palette_check.check(), [])

    def test_validator_detects_bad_palette(self):
        self.assertLess(palette_check.contrast("#FFFF66", "#FCFCFB"), palette_check.MIN_CONTRAST)
        self.assertLess(palette_check.color_distance("#D55E00", "#D95F0A"), 3)

    def test_cli_exit_code(self):
        r = subprocess.run([sys.executable, str(REPO / "evals/judge_bench/palette_check.py")], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = build_evidence(Path(cls._tmp.name) / "full")
        cls.html = report.build(cls.root)
        cls.data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', cls.html, re.DOTALL).group(1).replace("<\\/", "</"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_deterministic_bytes(self):
        self.assertEqual(report.build(self.root), self.html)
        # and through the CLI
        r = subprocess.run([sys.executable, str(REPO / "evals/judge_bench/report.py"), str(self.root)], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        first = (self.root / "index.html").read_bytes()
        subprocess.run([sys.executable, str(REPO / "evals/judge_bench/report.py"), str(self.root)], check=True, capture_output=True)
        self.assertEqual(first, (self.root / "index.html").read_bytes())
        self.assertEqual(first.decode(), self.html)

    def test_no_external_resources(self):
        self.assertIsNone(re.search(r'(?:src|href)\s*=\s*["\']?\s*(?:https?:)?//', self.html))
        self.assertIsNone(re.search(r"url\(\s*[\"']?(?:https?:)?//", self.html))
        self.assertNotIn("@import", self.html)
        self.assertNotIn("<link", self.html)
        self.assertNotRegex(self.html, r"<script[^>]+src=")

    def test_size_and_sections(self):
        self.assertLess(len(self.html.encode()), 3 * 1024 * 1024)
        for sid in ("explain", "headline", "scatter", "pairs", "calc", "explorer", "drill", "failures", "latency", "interv", "repro", "changes", "limits"):
            self.assertIn(f'id="{sid}"', self.html)
        # every chart has a <details> data table: static ones here, client-side ones via dtable()
        self.assertGreaterEqual(self.html.count("<details") + self.html.count("dtable($("), 9)
        for slot in ("dt-headline", "dt-scatter", "dt-pairs", "dt-cm", "dt-iv"):
            self.assertIn(f'id="{slot}"', self.html)
        self.assertIn("prefers-color-scheme", self.html)

    def test_headline_matches_summary(self):
        summary = json.loads((self.root / "dev" / "summary.json").read_text())
        for j in self.data["splits"]["dev"]["judges"]:
            mv = summary["arms"][j["arm"]]["policies"]["bundle-read-shortcut"]["across_reps"]["majority_vote"]
            self.assertEqual(j["acc"]["k"], mv["correct"])
            self.assertEqual(j["acc"]["n"], mv["n"])

    def test_pairwise_matrix_covers_all_pairs_and_holm(self):
        sp = self.data["splits"]["dev"]
        n = len(sp["arms"])
        for metric in ("correct", "automatic_error"):
            m = sp["matrix"][metric]
            self.assertEqual(len(m), n * (n - 1) // 2)
            for e in m:
                self.assertGreaterEqual(e[7], e[5] - 1e-12)   # Holm never lowers p

    def test_intervention_and_families(self):
        sp = self.data["splits"]["dev"]
        by = {j["arm"]: j for j in sp["judges"]}
        self.assertEqual(by["hosted-a+sideeffect-clause"]["base"], "hosted-a")
        self.assertEqual(by["hosted-a"]["family"], "hosted")
        self.assertEqual(by["local-so"]["family"], "system_one")
        self.assertEqual(by["local-gen"]["family"], "generic")
        self.assertGreater(by["hosted-a"]["usd1m"], 0)
        self.assertAlmostEqual(by["hosted-a"]["usd1m_priority"], 2 * by["hosted-a"]["usd1m"])

    def test_safe_cutoff_has_zero_wrong(self):
        sp = self.data["splits"]["dev"]
        cases = sp["cases"]
        for arm_i, arm in enumerate(sp["arms"]):
            cell = sp["safe"][arm]["pooled"]
            if not cell:
                continue
            wrong = 0
            for r in sp["rows"]:
                if r[0] == arm_i and r[3] is not None and r[4] >= cell["cutoff"] - 1e-9 and r[3] != "reason":
                    wrong += r[3] != cases[r[2]]["expected"]
            self.assertEqual(wrong, 0)

    def test_content_present(self):
        h = self.html
        self.assertIn("Luna defers", h)                    # changes.json
        self.assertIn("0.0.0-test", h)                     # run.json
        self.assertIn("python3 evals/judges.py --split dev", h)
        self.assertIn("Ambiguous purchase.", json.dumps(self.data["splits"]["dev"]["cases"]))
        self.assertIn("model-hosted-a-1.0", h)
        self.assertIn("403", h)
        self.assertIn("nonce", h.lower())
        self.assertNotIn("Holdout pending: <code>holdout/</code>", h)
        self.assertIsNotNone(self.data["splits"]["holdout"])

    def test_missing_optional_files_and_holdout_pending(self):
        with tempfile.TemporaryDirectory() as t:
            root = build_evidence(Path(t) / "min", full=False)
            html = report.build(root)
            self.assertIn("Holdout pending", html)
            self.assertIn("changes.json not found", html)
            self.assertIn("run.json not found", html)
            self.assertIsNone(json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.DOTALL).group(1))["splits"]["holdout"])


if __name__ == "__main__":
    unittest.main()
