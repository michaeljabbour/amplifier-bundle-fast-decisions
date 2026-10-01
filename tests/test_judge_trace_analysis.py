"""Post-hoc trace analysis (traces/rule2_useful.py --analysis) on a tiny synthetic run dir. No network."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

SCRIPT = ROOT / "evals" / "judge_bench" / "traces" / "rule2_useful.py"
spec = importlib.util.spec_from_file_location("rule2_useful", SCRIPT)
rule2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rule2)

EVIDENCE = ROOT / "docs" / "evidence" / "2026-10-01-trace-judge-benchmark" / "holdout"

# id: (final label, outcome label, stratum, group, in-session backend)
CASES = {"t1": ("r1", "r1", "S3", "g1", "jev"), "t2": ("r1", "r2", "S3", "g1", "jev"),
         "t3": ("reason", "reason", "S3", "g2", "jev"), "t4": ("reason", "reason", "S12", "g3", "laya"),
         "t5": ("r2", "r1", "S12", "g3", "laya"), "t6": ("reason", "reason", "S12", "g4", "ollama")}


def answer(pick):
    probs = {"r1": .025, "r2": .025, "reason": .95}
    probs = {k: (.95 if k == pick else .025) for k in probs}
    return {"type": "choice", "probabilities": probs, "choice": pick}


def build(tmp, picks, elapsed=None):
    """picks: arm -> {case id: option picked at p=.95}; elapsed: (arm, id) -> ms."""
    run = Path(tmp) / "run"
    run.mkdir()
    criteria = {"r1": "Read a", "r2": "Read b", "reason": "Fall back"}
    cases = [{"id": i, "kind": "read_shortcut", "expected": v[0], "screen": "trace-holdout",
              "payload": {"state": "{}", "questions": {"decision": {"type": "choice", "instructions": "x",
                                                                    "criteria": criteria}}},
              "tags": {"stratum": v[2], "group": v[3]}} for i, v in CASES.items()]
    (run / "manifest.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
    rows = [{"arm": arm, "rep": 1, "id": i, "order": 0, "valid": True, "screen": "trace-holdout",
             "kind": "read_shortcut", "expected": CASES[i][0], "model": "m", "input_tokens": None, "output_tokens": None,
             "elapsed_ms": (elapsed or {}).get((arm, i), 100.0), "answer": answer(pick)}
            for arm, by in picks.items() for i, pick in by.items()]
    (run / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    labels = Path(tmp) / "labels_final.json"
    labels.write_text(json.dumps({"labels": {i: {"outcome_label": v[1], "label": v[0], "decision": "agreed"}
                                             for i, v in CASES.items()}}), encoding="utf-8")
    pool = Path(tmp) / "pool.json"
    pool.write_text(json.dumps({"cases": [{"id": i, "native": {"sent": {"backend": v[4]}}}
                                          for i, v in CASES.items()]}), encoding="utf-8")
    return run, labels, pool


JEV = {"t1": "r1", "t2": "r2", "t3": "r1", "t4": "reason", "t5": "r2", "t6": "reason"}
PERFECT = {i: v[0] for i, v in CASES.items()}


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        run, labels, pool = build(cls.tmp.name, {"jev-1.13": JEV, "gpt-6.1-sol": PERFECT, "gpt-6-luna": PERFECT,
                                                "laya-base": {i: "reason" for i in CASES}},
                                  elapsed={("gpt-6.1-sol", "t1"): 4000.0})
        cls.out = rule2.analysis(run, labels, pool, bootstrap_b=200)
        cls.rule2 = rule2.main(str(run))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_labeled_post_hoc(self):
        self.assertIn("POST-HOC", self.out["label"])
        self.assertIn("not preregistered", self.out["label"])

    def test_a_outcome_label_and_host_next_read_match(self):
        a = self.out["a_outcome_label"]["judges"]["jev-1.13"]
        self.assertEqual((a["final_label"]["correct_automatic_reads"], a["final_label"]["wrong_automatic"]["k"]), (2, 2))
        # outcome labels: t1 r1, t2 r2, t5 r1 are reads; Jev reads t1, t2 right and t5 wrong, and t3 is wrong
        self.assertEqual(self.out["a_outcome_label"]["outcome_read_cases"], 3)
        self.assertEqual((a["outcome_label"]["correct_automatic_reads"], a["outcome_label"]["wrong_automatic"]["k"]), (2, 2))
        match = a["wrong_automatic_matching_host_next_read"]
        self.assertEqual((match["k"], match["of_wrong_automatic"], match["case_ids"]), (1, 2, ["t2"]))
        self.assertGreater(a["final_label"]["wrong_automatic"]["upper95"], .3)  # Wilson upper for 2/6
        sol = self.out["a_outcome_label"]["judges"]["gpt-6.1-sol"]
        self.assertEqual(sol["wrong_automatic_matching_host_next_read"]["of_wrong_automatic"], 0)

    def test_b_by_suite_and_always_fall_back(self):
        b = self.out["b_by_suite"]
        self.assertEqual((b["S3"]["n"], b["S12"]["n"]), (3, 3))
        self.assertEqual((b["S3"]["read_cases"], b["S12"]["read_cases"]), (2, 1))
        self.assertEqual((b["S3"]["always_fall_back"]["correct"], b["S12"]["always_fall_back"]["correct"]), (1, 2))
        self.assertEqual(b["S3"]["always_fall_back"]["correct_automatic_reads"], 0)
        jev3, jev12 = b["S3"]["judges"]["jev-1.13"], b["S12"]["judges"]["jev-1.13"]
        self.assertEqual((jev3["correct_automatic_reads"], jev3["wrong_automatic"]["k"]), (1, 2))
        self.assertEqual((jev12["correct_automatic_reads"], jev12["wrong_automatic"]["k"]), (1, 0))
        # an arm that always falls back equals the reference on accuracy
        self.assertEqual(b["S3"]["judges"]["laya-base"]["correct"], b["S3"]["always_fall_back"]["correct"])

    def test_c_selection_effect_uses_the_in_session_backend(self):
        c = self.out["c_selection_effect"]
        self.assertEqual(c["cases_by_family"], {"jev": 3, "laya": 2, "ollama": 1})
        self.assertIn("native.sent.backend", c["mapping"])
        jev = c["judges"]["jev-1.13"]
        self.assertEqual(jev["own_family"], "jev")
        self.assertEqual((jev["own_family_cases"]["n"], jev["own_family_cases"]["wrong_automatic"]["k"]), (3, 2))
        self.assertEqual((jev["all_other_cases"]["n"], jev["all_other_cases"]["wrong_automatic"]["k"]), (3, 0))
        self.assertIsNone(c["judges"]["gpt-6.1-sol"]["own_family"])  # never an in-session judge

    def test_d_fallback_reasons_and_hypothetical_no_timeout(self):
        d = self.out["d_fallback_reasons"]
        self.assertIn("HYPOTHETICAL", d["hypothetical_label"])
        self.assertEqual(d["judges"]["jev-1.13"]["fallback_reasons_all_reps"], {"automatic": 4, "model_abstained": 2})
        sol = d["judges"]["gpt-6.1-sol"]
        self.assertEqual(sol["fallback_reasons_all_reps"]["decision_timeout"], 1)
        self.assertEqual(sol["hypothetical_no_timeout"]["correct_automatic_reads"], 3)  # t1 counts once the timeout is ignored
        self.assertEqual(d["judges"]["gpt-6-luna"]["hypothetical_no_timeout"]["correct_automatic_reads"], 3)
        self.assertEqual(d["judges"]["laya-base"]["fallback_reasons_all_reps"], {"model_abstained": 6})

    def test_e_jev_vs_sol_exact_mcnemar(self):
        e = self.out["e_jev_vs_sol"]
        self.assertEqual((e["correct"]["a_only"], e["correct"]["b_only"], e["correct"]["p_exact_mcnemar"]), (0, 2, .5))
        self.assertEqual((e["automatic_error"]["a_only"], e["automatic_error"]["b_only"],
                          e["automatic_error"]["p_exact_mcnemar"]), (2, 0, .5))
        self.assertEqual(e["correct"]["n_pairs"], 6)
        self.assertIn("omitted", e["note"])

    def test_f_correct_automatic_reads_paired_on_read_cases(self):
        f = self.out["f_correct_automatic_reads_paired"]
        self.assertEqual(f["cases"], ["t1", "t2", "t5"])
        vs_sol = f["jev-1.13_vs_gpt-6.1-sol"]  # Sol's t1 timed out, so it keeps t2 and t5; Jev keeps t1 and t5
        self.assertEqual((vs_sol["jev_correct_automatic_reads"], vs_sol["other_correct_automatic_reads"]), (2, 2))
        self.assertEqual((vs_sol["a_only"], vs_sol["b_only"], vs_sol["p_exact_mcnemar"]), (1, 1, 1.0))
        vs_luna = f["jev-1.13_vs_gpt-6-luna"]
        self.assertEqual((vs_luna["a_only"], vs_luna["b_only"], vs_luna["p_exact_mcnemar"]), (0, 1, 1.0))

    def test_g_clustering(self):
        g = self.out["g_clustering"]
        self.assertEqual(g["n_groups"], 4)
        self.assertEqual(g["cases_per_group"], {"g1": 2, "g2": 1, "g3": 2, "g4": 1})
        self.assertEqual(g["jev_wrong_automatic_by_group"], {"g1": 1, "g2": 1})
        self.assertEqual((g["jev_wrong_automatic_total"], g["jev_groups_with_a_wrong_automatic"]), (2, 2))

    def test_preregistered_rule2_output_is_unchanged_and_independent(self):
        self.assertEqual(self.rule2["jev-1.13"], {"correct_automatic_reads": 2, "read_cases": 3, "wrong_automatic": 2,
                                                  "n": 6, "wrong_automatic_upper95": self.rule2["jev-1.13"]["wrong_automatic_upper95"],
                                                  "useful": False})
        self.assertNotIn("analysis", json.dumps(self.rule2))


@unittest.skipUnless(EVIDENCE.exists(), "trace evidence not present")
class CommittedEvidenceCliTests(unittest.TestCase):
    def run_cli(self, *flags):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "holdout"
            run.mkdir()
            for name in ("manifest.json", "requests.jsonl"):
                (run / name).write_bytes((EVIDENCE / name).read_bytes())
            done = subprocess.run([sys.executable, str(SCRIPT), str(run), *flags], capture_output=True, text=True,
                                  env={"PYTHONPATH": f"{ROOT}:{ROOT / 'src'}", "PATH": "/usr/bin:/bin"})
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout, (run / "trace_analysis.json").exists(), (
                json.loads((run / "trace_analysis.json").read_text()) if (run / "trace_analysis.json").exists() else None)

    def test_stdout_identical_with_and_without_analysis_and_file_only_with_flag(self):
        plain, wrote_plain, _ = self.run_cli()
        flagged, wrote_flag, analysis = self.run_cli("--analysis")
        self.assertEqual(plain, flagged)
        self.assertEqual(json.loads(plain), json.loads((EVIDENCE / "rule2_useful.json").read_text()))
        self.assertFalse(wrote_plain)
        self.assertTrue(wrote_flag)
        self.assertEqual(sorted(k for k in analysis if len(k) > 2 and k[0] in "abcdefg" and k[1] == "_"),
                         ["a_outcome_label", "b_by_suite", "c_selection_effect", "d_fallback_reasons",
                          "e_jev_vs_sol", "f_correct_automatic_reads_paired", "g_clustering"])
        self.assertEqual(analysis["a_outcome_label"]["judges"]["jev-1.13"]["wrong_automatic_matching_host_next_read"]["k"], 0)


if __name__ == "__main__":
    unittest.main()
