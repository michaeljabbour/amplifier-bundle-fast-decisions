"""Preregistered trace rule 2 (traces/PREREGISTRATION.md): is the read shortcut useful with this judge?

A judge is "useful here" if, on per-case majorities under bundle-read-shortcut, it makes at least 4 correct
automatic reads (cases whose final label is a read) and its wrong-automatic rate has a Wilson upper 95% bound
below 0.10. Also reports, descriptively, how many wrong automatic decisions match the host's actual next read.

    PYTHONPATH=src:. python3 evals/judge_bench/traces/rule2_useful.py docs/evidence/<dir>/holdout

With `--analysis` the same rule-2 JSON is printed first (unchanged), and POST-HOC sections a-g are written to
`<run_dir>/trace_analysis.json`. They were chosen after the results were seen, they are not preregistered, and
nothing in them changes a verdict. See `analysis()`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.judge_bench import scoring, stats
from evals.judge_bench.summarize import case_outcomes

HERE = Path(__file__).resolve().parent
LABELS = HERE / "labels_final.json"
POOL = HERE / "pool.json"


def _load(run: Path):
    cases = json.loads((run / "manifest.json").read_text())["cases"]
    rows = [json.loads(line) for line in (run / "requests.jsonl").read_text().splitlines() if line.strip()]
    return cases, rows


def main(run_dir: str) -> dict:
    run = Path(run_dir)
    cases, rows = _load(run)
    labels = json.loads(LABELS.read_text())["labels"]
    policy = scoring.resolve_policy("bundle-read-shortcut")
    out = {}
    for arm in sorted({r["arm"] for r in rows if r["arm"] != "openai-decisions"}):
        oc = case_outcomes(rows, cases, policy, arm)
        reads = [c for c in cases if c["expected"] != "reason"]
        correct_reads = sum(oc[c["id"]]["correct"] and oc[c["id"]]["automatic"] for c in reads)
        wrong = sum(oc[c["id"]]["automatic_error"] for c in cases)
        lo, hi = stats.wilson(wrong, len(cases))
        out[arm] = {"correct_automatic_reads": correct_reads, "read_cases": len(reads),
                    "wrong_automatic": wrong, "n": len(cases), "wrong_automatic_upper95": hi,
                    "useful": correct_reads >= 4 and hi < 0.10}
    return out


# ------------------------------------------------------------------ post-hoc analysis

SUITE_SLICES = {"S3": "S3 (SWE-bench: the task is clipped before the issue)", "S12": "S1+S2 (battery and polyglot)"}
# Which in-session judge sent a case's step to the host: the backend whose rendering matches the option-set hash the
# session logged (56 of 70; the other 14 fall back to the run's profile.md). pool.json `native.sent.backend`.
# Which evaluated arm belongs to that family: Jev -> jev, Laya -> laya, every Qwen3 model -> ollama. nimble, tev1
# and the GPT-6 models were never an in-session judge, so every case counts as "other" for them.
ARM_FAMILY = {"jev-1.13": "jev", "laya-base": "laya", "qwen3-0.6b": "ollama", "qwen3-4b": "ollama",
              "qwen3-8b": "ollama"}
HYPOTHETICAL = ("HYPOTHETICAL: same logged answers, the 3000 ms decision timeout ignored. No judge ran without a "
                "timeout; a slower judge would also change the host's wait.")


def _rate(k, n):
    lo_hi = stats.wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "upper95": lo_hi[1] if lo_hi else None}


def _counts(oc, ids, read_ids, expected_of):
    """Correct automatic reads / wrong automatic / accuracy over `ids` for per-case outcomes `oc`."""
    reads = [i for i in ids if i in read_ids]
    correct_reads = sum(oc[i]["correct"] and oc[i]["automatic"] for i in reads)
    wrong = sum(oc[i]["automatic_error"] for i in ids)
    return {"n": len(ids), "read_cases": len(reads), "correct_automatic_reads": correct_reads,
            "wrong_automatic": _rate(wrong, len(ids)), "correct": sum(oc[i]["correct"] for i in ids),
            "automatic": sum(oc[i]["automatic"] for i in ids)}


def _always_fall_back(ids, expected_of):
    return {"n": len(ids), "correct": sum(expected_of[i] == "reason" for i in ids), "correct_automatic_reads": 0,
            "wrong_automatic": _rate(0, len(ids)), "automatic": 0}


def _paired(a, b, ids, B=10000):
    only_a = sum(a[i] and not b[i] for i in ids)
    only_b = sum(b[i] and not a[i] for i in ids)
    diffs = [int(a[i]) - int(b[i]) for i in ids]
    n = len(ids)
    return {"n_pairs": n, "a_only": only_a, "b_only": only_b, "diff": (sum(diffs) / n) if n else None,
            "diff_ci95": stats.bootstrap_ci(diffs, B=B), "p_exact_mcnemar": stats.mcnemar_exact(only_a, only_b)}


def analysis(run_dir, labels_path=None, pool_path=None, bootstrap_b=10000) -> dict:
    """POST-HOC sections a-g for a trace run dir, from the committed evidence + labels_final.json + pool.json."""
    from evals.judge_bench.summarize import Ctx
    run = Path(run_dir)
    cases, rows = _load(run)
    labels = json.loads(Path(labels_path or LABELS).read_text())["labels"]
    pool = {c["id"]: c for c in json.loads(Path(pool_path or POOL).read_text())["cases"]}
    policy = scoring.resolve_policy("bundle-read-shortcut")
    ids = [c["id"] for c in cases]
    expected_of = {c["id"]: c["expected"] for c in cases}
    outcome_of = {i: labels[i]["outcome_label"] for i in ids}
    read_ids = {i for i in ids if expected_of[i] != "reason"}
    outcome_read_ids = {i for i in ids if outcome_of[i] != "reason"}
    arms = sorted({r["arm"] for r in rows if r["arm"] != "openai-decisions"})
    outcome_cases = [dict(c, expected=outcome_of[c["id"]]) for c in cases]
    no_timeout = dict(policy, name="bundle-read-shortcut+no-timeout", timeout_ms=float("inf"))
    final = {a: case_outcomes(rows, cases, policy, a) for a in arms}
    by_outcome = {a: case_outcomes(rows, outcome_cases, policy, a) for a in arms}
    ctx = Ctx(rows, cases, {}, {})
    out = {"label": "POST-HOC analysis: chosen after the holdout results were seen; not preregistered; no verdict "
                    "depends on it",
           "unit": "per-case majority over repetitions under bundle-read-shortcut, all cases in the denominator",
           "n_cases": len(ids), "read_cases_final_label": len(read_ids)}

    # a. against the host's actual next read
    a_out = {}
    for arm in arms:
        wrong_final = [i for i in ids if final[arm][i]["automatic_error"]]
        match = [i for i in wrong_final if by_outcome[arm][i]["correct"] and by_outcome[arm][i]["automatic"]]
        a_out[arm] = {"final_label": _counts(final[arm], ids, read_ids, expected_of),
                      "outcome_label": _counts(by_outcome[arm], ids, outcome_read_ids, outcome_of),
                      "wrong_automatic_matching_host_next_read": {"k": len(match), "of_wrong_automatic": len(wrong_final),
                                                                  "case_ids": match}}
    out["a_outcome_label"] = {
        "definition": "outcome label = the host model's actual next read, or reason (labels_final.json outcome_label). "
                      "A wrong automatic read 'matches the host's next read' when it is wrong against the final label "
                      "but right (automatic) against the outcome label.",
        "outcome_read_cases": len(outcome_read_ids), "judges": a_out}

    # b. by suite
    b_out = {}
    for key, title in SUITE_SLICES.items():
        sl = [c["id"] for c in cases if c["tags"].get("stratum") == key]
        sl_reads = {i for i in sl if i in read_ids}
        b_out[key] = {"title": title, "n": len(sl), "read_cases": len(sl_reads),
                      "always_fall_back": _always_fall_back(sl, expected_of),
                      "judges": {arm: _counts(final[arm], sl, read_ids, expected_of) for arm in arms}}
    out["b_by_suite"] = b_out

    # c. selection effect
    families = {i: pool[i]["native"]["sent"]["backend"] for i in ids}
    c_out = {"mapping": "case family = pool.json native.sent.backend (the in-session judge that sent the step to the "
                        "host; matched by logged option-set hash for 56 of 70 pool cases, profile.md for 14). "
                        "Arm family: " + ", ".join(f"{a}->{f}" for a, f in sorted(ARM_FAMILY.items())) + ". Other arms "
                        "have no own family.",
             "cases_by_family": {f: sum(v == f for v in families.values()) for f in sorted(set(families.values()))},
             "judges": {}}
    for arm in arms:
        fam = ARM_FAMILY.get(arm)
        if fam is None:
            c_out["judges"][arm] = {"own_family": None}
            continue
        own = [i for i in ids if families[i] == fam]
        other = [i for i in ids if families[i] != fam]
        c_out["judges"][arm] = {"own_family": fam,
                                "own_family_cases": _counts(final[arm], own, read_ids, expected_of),
                                "all_other_cases": _counts(final[arm], other, read_ids, expected_of)}
    out["c_selection_effect"] = c_out

    # d. fallback reasons and the no-timeout counterfactual
    d_out = {}
    for arm in arms:
        reasons: dict[str, int] = {}
        for rep in ctx.reps(arm):
            for i in ids:
                status, s = ctx.scored(arm, rep, i, policy)
                key = status if s is None else (s["fallback_reason"] or "automatic")
                reasons[key] = reasons.get(key, 0) + 1
        cf = case_outcomes(rows, cases, no_timeout, arm)
        d_out[arm] = {"fallback_reasons_all_reps": dict(sorted(reasons.items())),
                      "hypothetical_no_timeout": _counts(cf, ids, read_ids, expected_of)}
    out["d_fallback_reasons"] = {"unit": "one count per (repetition, case), order 0", "hypothetical_label": HYPOTHETICAL,
                                 "judges": d_out}

    # e. Jev vs Sol (post hoc; not in the run's Holm family)
    e_out = {"note": "exact McNemar, post hoc; the run's contrast list omitted this pair"}
    if {"jev-1.13", "gpt-6.1-sol"} <= set(arms):
        for metric in ("correct", "automatic_error"):
            va = {i: final["jev-1.13"][i][metric] for i in ids}
            vb = {i: final["gpt-6.1-sol"][i][metric] for i in ids}
            e_out[metric] = {"a": "jev-1.13", "b": "gpt-6.1-sol", **_paired(va, vb, ids, bootstrap_b)}
    out["e_jev_vs_sol"] = e_out

    # f. correct automatic reads, paired, on the read cases
    f_out = {"cases": sorted(read_ids), "n_read_cases": len(read_ids), "note": "exact McNemar on the discordant read cases"}
    for other in ("gpt-6-luna", "gpt-6.1-sol"):
        if {"jev-1.13", other} <= set(arms):
            va = {i: final["jev-1.13"][i]["correct"] and final["jev-1.13"][i]["automatic"] for i in read_ids}
            vb = {i: final[other][i]["correct"] and final[other][i]["automatic"] for i in read_ids}
            f_out[f"jev-1.13_vs_{other}"] = {"jev_correct_automatic_reads": sum(va.values()),
                                             "other_correct_automatic_reads": sum(vb.values()),
                                             **_paired(va, vb, sorted(read_ids), bootstrap_b)}
    out["f_correct_automatic_reads_paired"] = f_out

    # g. clustering by task group
    groups: dict[str, list[str]] = {}
    for c in cases:
        groups.setdefault(c["tags"].get("group"), []).append(c["id"])
    g_out = {"n_groups": len(groups), "cases_per_group": {g: len(v) for g, v in sorted(groups.items())}}
    if "jev-1.13" in final:
        per = {g: sum(final["jev-1.13"][i]["automatic_error"] for i in v) for g, v in sorted(groups.items())}
        g_out["jev_wrong_automatic_by_group"] = {g: k for g, k in per.items() if k}
        g_out["jev_wrong_automatic_total"] = sum(per.values())
        g_out["jev_groups_with_a_wrong_automatic"] = sum(1 for k in per.values() if k)
    out["g_clustering"] = g_out
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--analysis"]
    print(json.dumps(main(args[0]), indent=1, sort_keys=True))
    if "--analysis" in sys.argv[1:]:
        result = analysis(args[0])
        (Path(args[0]) / "trace_analysis.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
        print(f"wrote {Path(args[0]) / 'trace_analysis.json'}", file=sys.stderr)
