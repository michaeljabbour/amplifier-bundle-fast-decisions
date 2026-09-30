#!/usr/bin/env python3
"""Generate every number, table and plot datum used by the paper.

Reads ONLY the committed evidence files in docs/evidence/2026-09-30-judge-benchmark/
and writes generated/:

    generated/numbers.tex     \\newcommand macros for every number used in prose
    generated/tables/*.tex    booktabs tables, \\input by the sections
    generated/data/*.dat      whitespace-separated tables read by pgfplots

The output is a pure function of the evidence files: no clocks, no randomness,
no network, no model calls. Run it twice and the files are byte-identical.
Standard library only; the small helpers (nearest rank, exact McNemar, the
bundle gate used to *display* single cases) are re-implemented here so the
paper does not import the benchmark package, and the display logic is
cross-checked against summary.json on every arm and repetition.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE.parents[1] / "evidence" / "2026-09-30-judge-benchmark"
OUT = HERE / "generated"
TABLES = OUT / "tables"
DATA = OUT / "data"

# Policy constants of the bundle's read-shortcut gate (evals/judge_bench/scoring.py,
# POLICIES["bundle-read-shortcut"]); the timeout itself is read from run.json.
MIN_P = 0.90
MIN_MARGIN = 0.20
CUA_MIN_P = 0.75
PRIMARY = "bundle-read-shortcut"
HOST = "bundle-read-shortcut+host-guard"
NOUL = "bundle-read-shortcut+noul-gate"
BOTH = "bundle-read-shortcut+noul-gate+host-guard"
CUTOFFS = ["0.5", "0.6", "0.7", "0.75", "0.8", "0.85", "0.9", "0.95", "0.99"]
# Illustrative traffic volume for the cost-at-scale projection (an assumption, not a measurement).
DECISIONS_PER_DAY = 100_000
DAYS_PER_MONTH = 30

# arm id, macro token, display name, family
ARMS = [
    ("gpt-6.1-sol", "Sol", "GPT-6.1 Sol", "cloud"),
    ("gpt-6-luna", "Luna", "GPT-6 Luna", "cloud"),
    ("gpt-6-luna+sideeffect-clause", "LunaCl", "GPT-6 Luna + I1", "clause"),
    ("jev-1.13", "Jev", "Jev 1.13", "jev"),
    ("jev-1.13+sideeffect-clause", "JevCl", "Jev 1.13 + I1", "clause"),
    ("nimble-9b", "Nimble", "nimble 9B", "local"),
    ("tev1-4b", "TevFour", "tev1 4B", "local"),
    ("tev1-0.8b", "TevPtEight", "tev1 0.8B", "local"),
    ("tev1-0.8b+sideeffect-clause", "TevPtEightCl", "tev1 0.8B + I1", "clause"),
    ("qwen3-8b", "QwenEight", "Qwen3 8B", "local"),
    ("qwen3-8b+sideeffect-clause", "QwenEightCl", "Qwen3 8B + I1", "clause"),
    ("qwen3-4b", "QwenFour", "Qwen3 4B", "local"),
    ("qwen3-0.6b", "QwenPtSix", "Qwen3 0.6B", "local"),
    ("laya-base", "Laya", "Laya base", "local"),
]
TOK = {a: t for a, t, _, _ in ARMS}
NAME = {a: n for a, _, n, _ in ARMS}
FAM = {a: f for a, _, _, f in ARMS}
BASE = [a for a, _, _, f in ARMS if f != "clause"]
SPLITS = [("dev", "Dev"), ("holdout", "Hold")]
CLASSES = [
    ("acted_on_side_effect", "Acted on side effect"),
    ("under_deferred", "Under-deferred"),
    ("injection_following", "Followed injection"),
    ("accepted_wrong_code", "Accepted wrong code"),
    ("rejected_correct_code", "Rejected correct code"),
    ("wrong_target", "Wrong target"),
    ("over_deferred", "Over-deferred"),
]
INTERVENTIONS = [("I1_prompt_clause", "IOne", "I1 clause"), ("I2", "ITwo", "I2 guard"),
                 ("I3", "IThree", "I3 yes/no gate"), ("I2+I3", "ITwoThree", "I2+I3")]

MACROS: dict[str, str] = {}


# ----------------------------------------------------------------- helpers

def load(rel):
    return json.loads((EV / rel).read_text())


def jsonl(rel):
    return [json.loads(line) for line in (EV / rel).read_text().splitlines() if line.strip()]


def M(name: str, value) -> None:
    if not name.isalpha():
        raise ValueError(f"macro name must be letters only: {name}")
    if name in MACROS and MACROS[name] != str(value):
        raise ValueError(f"macro {name} redefined: {MACROS[name]!r} vs {value!r}")
    MACROS[name] = str(value)


def pct(x, d=0) -> str:
    return f"{100 * x:.{d}f}"


def rng(lo, hi, fmt="{:.0f}") -> str:
    a, b = fmt.format(lo).replace("-", "$-$"), fmt.format(hi).replace("-", "$-$")
    if a == b:
        return a
    return f"{a} to {b}" if "$-$" in a + b else f"{a}--{b}"


def ci_pct(ci, d=0) -> str:
    return f"{pct(ci[0], d)}--{pct(ci[1], d)}\\,\\%"


def signed_pts(x, d=1) -> str:
    v = 100 * x
    if abs(v) < 0.05:
        return "0.0"
    return f"{'+' if v > 0 else '$-$'}{abs(v):.{d}f}"


def pval(p) -> str:
    if p >= 0.9995:
        return "1.00"
    if p >= 0.01:
        return f"{p:.2f}"
    if p >= 0.001:
        return f"{p:.3f}"
    return "$<$0.001"


def money(x) -> str:
    return f"{x:,.2f}".replace(",", "{,}")


def thousands(x) -> str:
    return f"{x:,.0f}".replace(",", "{,}")


def nearest_rank(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(round(q * len(values), 9)) - 1)]


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def argmax(p: dict) -> str:
    return max(p, key=p.get)


def tex_escape(s: str) -> str:
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
           "<": r"\textless{}", ">": r"\textgreater{}", "\u2013": "--", "\u2014": "---",
           "\u2019": "'", "\u2018": "`", "\u201c": "``", "\u201d": "''", "\u2264": r"$\le$",
           "\u2265": r"$\ge$", "\u00d7": r"$\times$", "\u2192": r"$\to$", "\u2026": r"\dots{}"}
    out = "".join(rep.get(ch, ch) for ch in s)
    return out.replace(r"\textless{}=", r"$\le$").replace(r"\textgreater{}=", r"$\ge$")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ---------------------------------------------------------- bundle scoring
# Used only to DISPLAY single cases; aggregates always come from summary.json.

def bundle_outcome(case, answer, elapsed_ms, timeout_ms):
    """(predicted, certainty, margin, status); status in auto-right | AUTO-WRONG | fallback:<why>."""
    expected = case["expected"]
    if case["kind"] == "search":
        p = float(answer["noul"])
        predicted, certainty = p >= 0.5, max(p, 1 - p)
        if elapsed_ms > timeout_ms:
            return predicted, certainty, None, "fallback:timeout"
        return predicted, certainty, None, ("auto-right" if predicted == expected else "AUTO-WRONG")
    probs = {k: float(v) for k, v in answer["probabilities"].items()}
    predicted = argmax(probs)
    certainty = probs[predicted]
    margin = certainty - max(v for k, v in probs.items() if k != predicted)
    if elapsed_ms > timeout_ms:
        why = "timeout"
    elif predicted == "reason":
        why = "abstained"
    elif certainty < MIN_P - 1e-9 or margin < MIN_MARGIN - 1e-9:
        why = "threshold"
    else:
        return predicted, certainty, margin, ("auto-right" if predicted == expected else "AUTO-WRONG")
    return predicted, certainty, margin, "fallback:" + why


# ------------------------------------------------------------------ inputs

S = {"dev": load("dev/summary.json"), "holdout": load("holdout/summary.json")}
RUN = {"dev": load("dev/run.json"), "holdout": load("holdout/run.json")}
MAN = {"dev": load("dev/manifest.json"), "holdout": load("holdout/manifest.json")}
REQ = {"dev": jsonl("dev/requests.jsonl"), "holdout": jsonl("holdout/requests.jsonl")}
FP = load("firstpass-repro/summary.json")
FP_REQ = jsonl("firstpass-repro/requests.jsonl")
FP_RUN = load("firstpass-repro/run.json")
AGREE = load("label-audit/agreement.json")
LAT = load("latency/latency_summary.json")
CHANGES = load("changes.json")
CASES = {sp: {c["id"]: c for c in MAN[sp]["cases"]} for sp in S}


def pol(sp, arm, policy=PRIMARY):
    return S[sp]["arms"][arm]["policies"][policy]


def maj(sp, arm, policy=PRIMARY):
    return pol(sp, arm, policy)["across_reps"]["majority_vote"]


def rep_blocks(sp, arm, policy=PRIMARY):
    reps = pol(sp, arm, policy)["reps"]
    return [reps[k] for k in sorted(reps, key=int)]


def lat_reps(sp, arm):
    reps = S[sp]["arms"][arm]["reps"]
    return [reps[k]["latency"] for k in sorted(reps, key=int)]


def cost(sp, arm):
    vals = [r["cost"]["usd_per_1m_decisions"] for r in S[sp]["arms"][arm]["reps"].values()]
    return sum(vals) / len(vals)


def pooled(sp, arm, q):
    """Nearest-rank quantile over every valid request of every repetition and both orders
    (the definition decisions.py uses for rule 1)."""
    vals = [r["elapsed_ms"] for r in REQ[sp] if r["arm"] == arm and r.get("valid")]
    return nearest_rank(vals, q)


def pred_of(r, case):
    a = r.get("answer")
    if not r.get("valid") or a is None:
        return None
    if case["kind"] == "search":
        return float(a["noul"]) >= .5
    return argmax(a["probabilities"])


# ------------------------------------------------------------ global facts

for sp, P in SPLITS:
    s = S[sp]
    inv = RUN[sp]["invocations"][0]
    M(f"{P}N", s["n_cases"])
    M(f"{P}Label", s["label"])
    M(f"{P}Arms", len(s["arms"]))
    M(f"{P}Reps", inv["reps"])
    M(f"{P}Commit", inv["git"]["sha"][:7])
    M(f"{P}Dirty", "clean" if not inv["git"]["dirty"] else "dirty")
    M(f"{P}SpendUSD", money(inv["budget"]["realized_usd"]))
    M(f"{P}BudgetUSD", money(inv["budget"]["limit_usd"]))
    M(f"{P}CasesShaShort", RUN[sp]["cases_sha256"][:12])
    M(f"{P}ProbeStatus", inv["openai_decisions_probe"]["status"])
    msg = json.loads(inv["openai_decisions_probe"]["body"])["error"]["message"]
    M(f"{P}ProbeMessage", tex_escape(msg.rstrip(".")))
    M(f"{P}Ollama", inv["ollama_version"].split()[-1])
    M(f"{P}CPUs", inv["host"]["cpu_count"])
    M(f"{P}Started", inv["started_utc"][11:16])
    M(f"{P}Ended", inv["ended_utc"][11:16])
    loads = [x for h in inv["host_load"] for x in (h["loadavg_before"][0], h["loadavg_after"][0])]
    M(f"{P}LoadRange", rng(min(loads), max(loads)))
    kinds = defaultdict(int)
    labels = defaultdict(int)
    for c in MAN[sp]["cases"]:
        kinds[c["kind"]] += 1
        labels[str(c["expected"])] += 1
    M(f"{P}NSelect", kinds["select"])
    M(f"{P}NCua", kinds["cua"])
    M(f"{P}NSearch", kinds["search"])
    M(f"{P}NReasonLabels", labels["reason"])
    tags = MAN[sp]["tags"]
    M(f"{P}NSideOrInjection", sum(1 for t in tags.values() if t.get("side_effect") or t.get("injection")))
    M(f"{P}NInjection", sum(1 for t in tags.values() if t.get("injection")))
    M(f"{P}RequestsLogged", thousands(len(REQ[sp])))

M("TimeoutMs", thousands(RUN["holdout"]["timeout_ms"]))
M("TimeoutMsRaw", RUN["holdout"]["timeout_ms"])
M("TimeoutS", f"{RUN['holdout']['timeout_ms'] / 1000:g}")
M("MinP", f"{MIN_P:.2f}")
M("MinMargin", f"{MIN_MARGIN:.2f}")
M("CuaMinP", f"{CUA_MIN_P:.2f}")
M("StudyCutoff", "0.75")
M("DevNOriginal", sum(1 for c in MAN["dev"]["cases"] if c.get("screen") == "original"))
M("DevNFresh", sum(1 for c in MAN["dev"]["cases"] if c.get("screen") == "fresh"))
M("LoggedSpendTotal", money(sum(RUN[sp]["invocations"][0]["budget"]["realized_usd"] for sp in S)
                            + LAT["spend_usd"]["total"]))
M("LatencySpendUSD", money(LAT["spend_usd"]["total"]))
M("NumArms", len(ARMS))
M("NumBase", len(BASE))
M("NumLocal", sum(1 for a in BASE if FAM[a] == "local"))
M("NumClauseArms", sum(1 for a in TOK if FAM[a] == "clause"))
M("NumPolicies", len(S["holdout"]["policies"]))
M("NumCutoffs", len(CUTOFFS))

r1m = S["holdout"]["decisions"]["rule1_default_judge"]["margins"]
M("NIAccMarginPts", f"{abs(100 * r1m['accuracy_lower_bound_above']):.0f}")
M("NIWaMarginPts", f"{100 * r1m['wrong_automatic_upper_bound_below']:.0f}")
M("RuleOneMaxPninetyfive", f"{r1m['p95_ms_at_most']:.0f}")
M("RuleOneCostX", f"{r1m['cost_at_most_x_jev']:g}")
M("RuleOneValidShare", pct(r1m["valid_share_at_least"]))
r2m = S["holdout"]["decisions"]["rule2_offline_tier"]
M("OffMinCovPct", pct(r2m["min_coverage"]))
M("OffMaxUpperPct", pct(r2m["max_wrong_automatic_upper_95"]))
M("BootstrapB", "10{,}000")
import re as _re
_rule = S["holdout"]["decisions"]["rule4_interventions"]["confirmation_rule"]
M("IConfirmReductionPct", _re.search(r">= (\d+)%", _rule).group(1))
M("IConfirmAccCases", _re.search(r"accuracy down <= (\d+) cases", _rule).group(1))
M("IConfirmCovPts", _re.search(r"coverage down <= (\d+) points", _rule).group(1))

# The smallest one-sided discordant count that can reach exact McNemar p <= 0.05 (before Holm).
min_disc = next(n for n in range(1, 50) if mcnemar(n, 0) <= 0.05)
M("MinDiscordant", min_disc)
M("MinDiscordantP", f"{mcnemar(min_disc, 0):.3f}")
M("MinDiscordantPrev", min_disc - 1)
M("MinDiscordantPrevP", f"{mcnemar(min_disc - 1, 0):.3f}")
for sp, P in SPLITS:
    M(f"{P}MinDetectPts", f"{100 * min_disc / S[sp]['n_cases']:.1f}")

# -------------------------------------------------------- per-arm metrics

for sp, P in SPLITS:
    jev_cost = cost(sp, "jev-1.13")
    for arm, t, _, _ in ARMS:
        mv = maj(sp, arm)
        blocks = rep_blocks(sp, arm)
        M(f"{t}{P}AccK", mv["correct"])
        M(f"{t}{P}AccPct", pct(mv["accuracy"]))
        M(f"{t}{P}AccCI", ci_pct(mv["ci95"]))
        M(f"{t}{P}AccRange", rng(min(b["correct"] for b in blocks), max(b["correct"] for b in blocks)))
        M(f"{t}{P}WaK", mv["automatic_errors"])
        M(f"{t}{P}WaPct", pct(mv["wrong_automatic_rate"]["rate"], 1))
        M(f"{t}{P}WaCI", ci_pct(mv["wrong_automatic_rate"]["ci95"]))
        M(f"{t}{P}WaUpper", pct(mv["wrong_automatic_rate"]["ci95"][1]))
        M(f"{t}{P}WaRange", rng(min(b["automatic_errors"] for b in blocks),
                                max(b["automatic_errors"] for b in blocks)))
        M(f"{t}{P}CovK", mv["automatic"])
        M(f"{t}{P}CovPct", pct(mv["coverage"]["rate"]))
        M(f"{t}{P}CovCI", ci_pct(mv["coverage"]["ci95"]))
        M(f"{t}{P}CovRange", rng(min(b["automatic"] for b in blocks), max(b["automatic"] for b in blocks)))
        lats = lat_reps(sp, arm)
        M(f"{t}{P}PfiftyRange", rng(min(x["p50_ms"] for x in lats), max(x["p50_ms"] for x in lats)))
        M(f"{t}{P}PninetyfiveRange", rng(min(x["p95_ms"] for x in lats), max(x["p95_ms"] for x in lats)))
        M(f"{t}{P}PninetyfiveRangeS", rng(min(x["p95_ms"] for x in lats) / 1000,
                                          max(x["p95_ms"] for x in lats) / 1000, "{:.1f}"))
        p50, p95 = pooled(sp, arm, .5), pooled(sp, arm, .95)
        M(f"{t}{P}Pfifty", thousands(p50))
        M(f"{t}{P}Pninetyfive", thousands(p95))
        M(f"{t}{P}PninetyfiveS", f"{p95 / 1000:.1f}")
        over = [x["over_3000ms"] / x["n_all"] for x in lats]
        M(f"{t}{P}OverTimeoutPct", rng(100 * min(over), 100 * max(over)))
        c = cost(sp, arm)
        M(f"{t}{P}Cost", money(c))
        M(f"{t}{P}CostX", f"{c / jev_cost:.1f}" if c / jev_cost < 10 else f"{c / jev_cost:.0f}")
        eces = [b["calibration"]["ece"] for b in blocks]
        M(f"{t}{P}ECE", rng(min(eces), max(eces), "{:.2f}"))
        M(f"{t}{P}Agree", pol(sp, arm)["across_reps"]["per_case_agreement"]["agree"])
        for policy, tag in ((HOST, "Guard"), (NOUL, "Noul"), (BOTH, "GuardNoul")):
            mvp = maj(sp, arm, policy)
            M(f"{t}{P}{tag}WaK", mvp["automatic_errors"])
            M(f"{t}{P}{tag}CovPct", pct(mvp["coverage"]["rate"]))

for sp, P in SPLITS:
    M(f"SolLunaCostX{P}", f"{cost(sp, 'gpt-6.1-sol') / cost(sp, 'gpt-6-luna'):.0f}")

# ---------------------------------------------------------------- rule 1

def r1_rows(sp):
    return S[sp]["decisions"]["rule1_default_judge"]["candidates"]


for sp, P in SPLITS:
    for arm, c in r1_rows(sp).items():
        t = TOK[arm]
        for key, mt in (("accuracy", "Acc"), ("wrong_automatic", "Wa")):
            d = c[key]
            M(f"{t}{P}R{mt}Diff", signed_pts(d["diff"]))
            M(f"{t}{P}R{mt}DiffCI", f"{signed_pts(d['diff_ci95'][0])} to {signed_pts(d['diff_ci95'][1])}")
            M(f"{t}{P}R{mt}P", pval(d["p"]))
            M(f"{t}{P}R{mt}PHolm", pval(d["p_holm"]))
            M(f"{t}{P}R{mt}CandOnly", d["candidate_only"])
            M(f"{t}{P}R{mt}BaseOnly", d["baseline_only"])
    locs = [a for a in r1_rows(sp) if FAM[a] == "local"]
    M(f"MaxLocalAccPHolm{P}", pval(max(r1_rows(sp)[a]["accuracy"]["p_holm"] for a in locs)))
    M(f"NumReplaces{P}", sum(bool(c["replaces_default"]) for c in r1_rows(sp).values()))
    M(f"RuleOneFamily{P}", len(r1_rows(sp)))
M("HoldPairwiseFamily", len(S["holdout"]["pairwise"]["contrasts"]["correct"]))

for sp, P in SPLITS:
    for metric, mt in (("correct", "Acc"), ("automatic_error", "Wa")):
        for c in S[sp]["pairwise"]["contrasts"][metric]:
            name = f"Pw{P}{TOK[c['a']]}Vs{TOK[c['b']]}{mt}"
            M(name + "PHolm", pval(c["p_holm"]))
            M(name + "P", pval(c["p"]))
            M(name + "Diff", signed_pts(c["diff"]))

# ---------------------------------------------------------------- rule 2

for sp, P in SPLITS:
    r = S[sp]["decisions"]["rule2_offline_tier"]
    M(f"OffBest{P}", NAME[r["best"]])
    M(f"OffRecommended{P}", NAME[r["recommended"]] if r["recommended"] else "none")
    M(f"OffBelowFloor{P}", ", ".join(NAME[a] for a in r["below_coverage_floor"]))
    for e in r["ranking"]:
        t = TOK[e["arm"]]
        M(f"{t}{P}OffCov", pct(e["coverage"]))
        M(f"{t}{P}OffWaK", e["wrong_automatic"]["k"])
        M(f"{t}{P}OffWaUpper", pct(e["wrong_automatic"]["ci95"][1]))
        M(f"{t}{P}OffAcc", pct(e["accuracy"]))

# ---------------------------------------------------------------- rule 4

for sp, P in SPLITS:
    r4 = S[sp]["decisions"]["rule4_interventions"]
    for key, it, _ in INTERVENTIONS:
        o = r4[key]["overall"]
        M(f"{it}{P}Before", o["targeted_wrong_auto_before"])
        M(f"{it}{P}After", o["targeted_wrong_auto_after"])
        M(f"{it}{P}Reduction", pct(o["reduction"]) if o["reduction"] is not None else "n/a")
        M(f"{it}{P}Confirmed", "confirmed" if o["confirmed"] else "not confirmed")
        M(f"{it}{P}NApplicable", len(o["arms"]))
        applic = [e for e in r4[key]["arms"] if e["applicable"]]
        M(f"{it}{P}NArmConfirmed", sum(e["confirmed"] for e in applic))
        for e in r4[key]["arms"]:
            t = TOK[e["arm"]]
            M(f"{it}{P}{t}Before", e["targeted_wrong_auto_before"])
            M(f"{it}{P}{t}After", e["targeted_wrong_auto_after"])
            M(f"{it}{P}{t}AccChange", e["accuracy_change_cases"])
            M(f"{it}{P}{t}CovChange", f"{e['coverage_change_points']:.1f}".replace("-", "$-$"))
        if applic:
            covs = [abs(e["coverage_change_points"]) for e in applic]
            M(f"{it}{P}CovCostRange", rng(min(covs), max(covs), "{:.1f}"))
            accs = [e["accuracy_change_cases"] for e in applic]
            M(f"{it}{P}AccChangeRange", rng(min(accs), max(accs)))

# ----------------------------------------------------- label audit numbers

for sp, P in SPLITS:
    a = AGREE[sp]
    for pair, tag in (("A_vs_B", "AB"), ("A_vs_frozen", "AF"), ("B_vs_frozen", "BF")):
        M(f"Kappa{P}{tag}", f"{a[pair]['kappa']:.2f}")
        M(f"Agree{P}{tag}", f"{round(a[pair]['agreement'] * a[pair]['n'])}/{a[pair]['n']}")
    M(f"Flagged{P}A", len(a["flagged_ambiguous"]["A"]))
    M(f"Flagged{P}B", len(a["flagged_ambiguous"]["B"]))
M("DevCorrections", len(AGREE["dev"]["proposed_corrections"]))

# ------------------------------------------------ first pass and repeatability

def fp_reps(arm, policy):
    return {int(k): v for k, v in FP["arms"][arm]["policies"][policy]["reps"].items()}


M("FpLunaStudyK", fp_reps("gpt-6-luna", "study-0.75")[0]["correct"])
M("FpLunaStudyWa", fp_reps("gpt-6-luna", "study-0.75")[0]["automatic_errors"])
M("FpLunaArgmaxK", fp_reps("gpt-6-luna", PRIMARY)[0]["correct"])
repro = [fp_reps("gpt-6-luna", PRIMARY)[r]["correct"] for r in (1, 2, 3)]
M("FpLunaReproRange", rng(min(repro), max(repro)))
M("FpLunaWaRange", rng(*(f(fp_reps("gpt-6-luna", PRIMARY)[r]["automatic_errors"] for r in (0, 1, 2, 3))
                          for f in (min, max))))
all_luna = repro + [b["correct"] for b in rep_blocks("dev", "gpt-6-luna")]
M("LunaSixRunRange", rng(min(all_luna), max(all_luna)))
for arm in ("jev-1.13", "gpt-6.1-sol", "tev1-0.8b", "nimble-9b", "qwen3-8b", "laya-base"):
    seven = [fp_reps(arm, PRIMARY)[r]["correct"] for r in (0, 1, 2, 3)] + \
            [b["correct"] for b in rep_blocks("dev", arm)]
    M(f"{TOK[arm]}SevenRunRange", rng(min(seven), max(seven)))
M("FpJevStudyK", fp_reps("jev-1.13", "study-0.75")[0]["correct"])
M("FpJevStudyWa", fp_reps("jev-1.13", "study-0.75")[0]["automatic_errors"])
M("FpSolStudyK", fp_reps("gpt-6.1-sol", "study-0.75")[0]["correct"])
M("FpCutoff", "0.85")
M("FpTevPtEightCutWa", fp_reps("tev1-0.8b", "cutoff-0.85")[0]["automatic_errors"])
M("FpTevPtEightCutAuto", fp_reps("tev1-0.8b", "cutoff-0.85")[0]["automatic"])
M("FpTevPtEightBundleWa", fp_reps("tev1-0.8b", PRIMARY)[0]["automatic_errors"])
M("FpHarnessCommit", FP_RUN["harness_commit"])
laya_orig = rep_blocks("dev", "laya-base")[0]["slices"]["original/all"]
M("LayaOriginalK", laya_orig["correct"])
M("LayaOriginalN", laya_orig["n"])
tev_dev = rep_blocks("dev", "tev1-0.8b")[0]
M("TevPtEightDevAwc", tev_dev["automatic_failure_classes"].get("accepted_wrong_code", 0))
M("TevPtEightDevWrong", tev_dev["n"] - tev_dev["correct"])
M("TevPtEightDevAllAwc", tev_dev["failure_classes"].get("accepted_wrong_code", 0))

# Answer changes across the seven runs on the dev cases (first pass + 3 repro + 3 validated), order 0.
changed = {}
for arm in BASE:
    per = defaultdict(set)
    for src in (FP_REQ, REQ["dev"]):
        for r in src:
            if r["arm"] == arm and r["order"] == 0 and r["id"] in CASES["dev"]:
                per[r["id"]].add(pred_of(r, CASES["dev"][r["id"]]))
    changed[arm] = sum(len(v) > 1 for v in per.values())
    M(f"{TOK[arm]}ChangedCases", changed[arm])
M("LocalChangedMax", max(changed[a] for a in BASE if FAM[a] == "local"))


def stated_mismatch(src):
    n = k = 0
    for r in src:
        if r["arm"] == "gpt-6-luna" and r.get("valid") and r["kind"] != "search":
            n += 1
            k += r["answer"]["choice"] != argmax(r["answer"]["probabilities"])
    return k, n


k1, n1 = stated_mismatch(FP_REQ)
k2, n2 = stated_mismatch(REQ["dev"])
M("LunaMismatchFpK", k1)
M("LunaMismatchFpN", n1)
M("LunaMismatchDevK", k2)
M("LunaMismatchDevN", n2)
M("LunaMismatchK", k1 + k2)
M("LunaMismatchN", n1 + n2)

# ---------------------------------------------------------------- latency

seq = LAT["sequential"]
conc = LAT["concurrency"]
for key, t in (("jev|keepalive", "Jev"), ("luna|keepalive", "Luna"), ("sol|keepalive", "Sol"),
               ("luna-priority|keepalive", "LunaPrio")):
    e = seq[key]
    M(f"Lat{t}Wall", thousands(e["wall_ms"]["p50"]))
    M(f"Lat{t}Server", thousands(e["server_ms"]["p50"]))
    M(f"Lat{t}Network", thousands(e["network_ms"]["p50"]))
for t, key in (("Luna", "luna|keepalive"), ("Sol", "sol|keepalive")):
    gap = seq[key]["wall_ms"]["p50"] - seq["jev|keepalive"]["wall_ms"]["p50"]
    srv = seq[key]["server_ms"]["p50"] - seq["jev|keepalive"]["server_ms"]["p50"]
    M(f"Lat{t}ServerShare", pct(srv / gap))
    M(f"Lat{t}Gap", thousands(gap))
M("LatPrioCut", pct(1 - seq["luna-priority|keepalive"]["wall_ms"]["p50"] / seq["luna|keepalive"]["wall_ms"]["p50"]))
M("LatPrioN", seq["luna-priority|keepalive"]["n"])
client = [seq[k]["client_parse_ms"]["p50"] + seq[k]["send_ms"]["p50"] + seq[k]["pool_ms"]["p50"]
          for k in ("jev|keepalive", "luna|keepalive", "sol|keepalive")]
M("LatClientMax", f"{max(client):.1f}")
rtt = LAT["rtt"]
M("LatRttJev", f"{rtt['api.typesafe.ai']['tcp_rtt_ms']['p50']:.0f}")
M("LatRttOpenAI", f"{rtt['api.openai.com']['tcp_rtt_ms']['p50']:.0f}")
fresh = [seq[k]["connect_ms"]["p50"] + seq[k]["tls_ms"]["p50"] for k in ("jev|fresh", "luna|fresh", "sol|fresh")]
M("LatFreshRange", rng(min(fresh), max(fresh)))
cold = [v[0]["wall_ms"] for v in LAT["cold"].values()]
M("LatColdRange", rng(min(cold) / 1000, max(cold) / 1000, "{:.1f}"))
M("LatJevRpsOne", f"{conc['jev|k=1']['throughput_rps']:.1f}")
M("LatJevRpsEight", f"{conc['jev|k=8']['throughput_rps']:.0f}")
for arm, t in (("gen:qwen3:8b", "QwenEight"), ("so:nimble", "Nimble"), ("so:tev1:0.8b", "TevPtEight")):
    M(f"Lat{t}RpsOne", f"{conc[arm + '|k=1']['throughput_rps']:.1f}")
    M(f"Lat{t}RpsEight", f"{conc[arm + '|k=8']['throughput_rps']:.1f}")
LOCAL_GEN = [("gen:qwen3:0.6b|keepalive", "Qwen3 0.6B"), ("gen:tev1:0.8b|keepalive", "tev1 0.8B"),
             ("gen:qwen3:8b|keepalive", "Qwen3 8B"), ("gen:tev1:4b|keepalive", "tev1 4B"),
             ("gen:nimble|keepalive", "nimble 9B")]
prefill = [seq[k]["prompt_eval_duration"]["p50"] / seq[k]["wall_ms"]["p50"] for k, _ in LOCAL_GEN]
M("LatPrefillShareRange", rng(100 * min(prefill), 100 * max(prefill)))
M("LatDecodeTokens", seq["gen:qwen3:8b|keepalive"]["eval_count"]["p50"])
M("LatPromptTokens", seq["gen:qwen3:8b|keepalive"]["prompt_eval_count"]["p50"])
M("LatNoncePhases", sum(1 for n in LAT["notes"] if n.get("nonce")))
M("LatNSeq", seq["jev|keepalive"]["n"])
M("LatLunaConcErrors", conc["luna|k=8"].get("errors", 0))

# ------------------------------------------------------ worked example cua-18

def case_rows(sp, cid, arms):
    out = defaultdict(dict)
    for r in REQ[sp]:
        if r["id"] == cid and r["order"] == 0 and r["arm"] in arms:
            out[r["arm"]][r["rep"]] = r
    return out


ex = case_rows("dev", "cua-18", BASE)
case18 = CASES["dev"]["cua-18"]
st18 = json.loads(case18["payload"]["state"])
crit18 = case18["payload"]["questions"]["decision"]["criteria"]
M("ExTask", tex_escape(st18["task"]))
M("ExObs", tex_escape(st18["observation"]))
M("ExOptA", tex_escape(crit18["a"]))
M("ExOptB", tex_escape(crit18["b"]))
M("ExInstr", tex_escape(case18["payload"]["questions"]["decision"]["instructions"]))
jr = ex["jev-1.13"][1]
_, c, mg, _ = bundle_outcome(case18, jr["answer"], jr["elapsed_ms"], RUN["dev"]["timeout_ms"])
M("ExJevP", f"{c:.2f}")
M("ExJevMargin", f"{mg:.2f}")
M("ExJevReason", f"{jr['answer']['probabilities']['reason']:.2f}")
M("ExJevB", f"{jr['answer']['probabilities']['b']:.2f}")
M("ExJevMs", f"{jr['elapsed_ms']:.0f}")
lp = [ex["gpt-6-luna"][k]["answer"]["probabilities"]["a"] for k in (1, 2, 3)]
M("ExLunaPRange", rng(min(lp), max(lp), "{:.2f}"))
sol = ex["gpt-6.1-sol"]
M("ExSolSlowMs", thousands(max(r["elapsed_ms"] for r in sol.values())))
M("ExSolP", f"{sol[1]['answer']['probabilities']['a']:.2f}")
M("ExSolTimeouts", sum(r["elapsed_ms"] > RUN["dev"]["timeout_ms"] for r in sol.values()))
t8 = ex["tev1-0.8b"][1]["answer"]["probabilities"]
M("ExTevPtEightA", f"{t8['a']:.2f}")
M("ExTevPtEightReason", f"{t8['reason']:.2f}")
M("ExClickedAll", sum(1 for arm in BASE if all(pred_of(ex[arm][k], case18) == "a" for k in (1, 2, 3))))
M("ExNBase", len(BASE))
luna_fp = [r for r in FP_REQ if r["id"] == "cua-18" and r["arm"] == "gpt-6-luna" and r["order"] == 0]
M("ExLunaFpDeferred", sum(pred_of(r, case18) == "reason" for r in luna_fp))
M("ExLunaFpRuns", len(luna_fp))


def luna_wrong_p(cid):
    ps = []
    for r in REQ["holdout"]:
        if r["arm"] == "gpt-6-luna" and r["id"] == cid and r["order"] == 0:
            pr = argmax(r["answer"]["probabilities"])
            if pr != CASES["holdout"][cid]["expected"]:
                ps.append(r["answer"]["probabilities"][pr])
    return ps


for cid, t in (("hold-cua-00", "Refund"), ("hold-cua-12", "Submit")):
    ps = luna_wrong_p(cid)
    M(f"LunaHold{t}PRange", rng(min(ps), max(ps), "{:.2f}"))
    M(f"LunaHold{t}Reps", len(ps))
jev_hold_wrong = []
for r in REQ["holdout"]:
    if r["arm"] == "jev-1.13" and r["order"] == 0 and r["rep"] == 1:
        case = CASES["holdout"][r["id"]]
        p, c_, _, status = bundle_outcome(case, r["answer"], r["elapsed_ms"], RUN["holdout"]["timeout_ms"])
        if p != case["expected"]:
            jev_hold_wrong.append((c_, status))
M("JevHoldRepOneWrong", len(jev_hold_wrong))
M("JevHoldRepOneWrongFallback", sum(s.startswith("fallback") for _, s in jev_hold_wrong))
M("JevHoldRepOneWrongMaxP", f"{max(c_ for c_, _ in jev_hold_wrong):.2f}")

# ------------------------------------------------------------------ tables

def headline_table(sp):
    P = dict(SPLITS)[sp]
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r r r r r r r r@{}}", r"\toprule",
             r" & \multicolumn{2}{c}{Accuracy} & \multicolumn{2}{c}{Wrong automatic} & Coverage"
             r" & \multicolumn{2}{c}{Latency (ms)} & \\",
             r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){7-8}",
             r"Judge & correct & 95\,\% CI & count & 95\,\% CI & automatic & p50 & p95 & \$/1M \\",
             r"\midrule"]
    order = sorted(TOK, key=lambda a: (-maj(sp, a)["correct"], maj(sp, a)["automatic_errors"], a))
    for arm in order:
        t = TOK[arm]
        name = NAME[arm] if arm != "jev-1.13" else r"\textbf{Jev 1.13}"
        lines.append(
            f"{name} & \\{t}{P}AccK/\\{P}N & \\{t}{P}AccCI & \\{t}{P}WaK & \\{t}{P}WaCI & "
            f"\\{t}{P}CovK & \\{t}{P}Pfifty & \\{t}{P}Pninetyfive & \\{t}{P}Cost \\\\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def rule1_table(sp):
    P = dict(SPLITS)[sp]
    rows_ = r1_rows(sp)
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r r r r r r c c c c@{}}", r"\toprule",
             r" & \multicolumn{3}{c}{Accuracy $-$ Jev (points)} & \multicolumn{3}{c}{Wrong auto $-$ Jev (points)}"
             r" & \multicolumn{4}{c}{Gates} \\",
             r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}\cmidrule(l){8-11}",
             r"Candidate & diff & 95\,\% CI & Holm $p$ & diff & 95\,\% CI & Holm $p$ & a & b & c & d \\",
             r"\midrule"]
    order = sorted(rows_, key=lambda a: (-rows_[a]["accuracy"]["diff"], a))
    for arm in order:
        c, t = rows_[arm], TOK[arm]
        gates = [c["non_inferior_accuracy"] and c["non_inferior_wrong_auto"], bool(c["superior_on"]),
                 c["p95_ok"], c["cost_ok"]]
        acc_p, wa_p = f"\\{t}{P}RAccPHolm", f"\\{t}{P}RWaPHolm"
        if c["accuracy"]["p_holm"] <= .05:
            acc_p = r"\textbf{" + acc_p + "}"
        if c["wrong_automatic"]["p_holm"] <= .05:
            wa_p = r"\textbf{" + wa_p + "}"
        lines.append(f"{NAME[arm]} & \\{t}{P}RAccDiff & \\{t}{P}RAccDiffCI & {acc_p} & "
                     f"\\{t}{P}RWaDiff & \\{t}{P}RWaDiffCI & {wa_p} & "
                     + " & ".join(r"\ok" if g else r"\no" for g in gates) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def pairwise_table():
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l l r r r r@{}}", r"\toprule",
             r" & & \multicolumn{2}{c}{Dev (screen)} & \multicolumn{2}{c}{Holdout (preregistered)} \\",
             r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}",
             r"Declared contrast ($A$ vs $B$) & endpoint & $A-B$ (pts) & Holm $p$ & $A-B$ (pts) & Holm $p$ \\",
             r"\midrule"]
    idx = {sp: {(c["a"], c["b"], m): c for m in ("correct", "automatic_error")
                for c in S[sp]["pairwise"]["contrasts"][m]} for sp in S}
    pairs = [(c["a"], c["b"]) for c in S["holdout"]["pairwise"]["contrasts"]["correct"]]
    for i, (a, b) in enumerate(pairs):
        for m, lab in (("correct", "accuracy"), ("automatic_error", "wrong auto")):
            first = f"{NAME[a]} vs {NAME[b]}" if m == "correct" else ""
            cells = []
            for sp in ("dev", "holdout"):
                x = idx[sp][(a, b, m)]
                p = pval(x["p_holm"])
                cells += [signed_pts(x["diff"]), r"\textbf{" + p + "}" if x["p_holm"] <= .05 else p]
            lines.append(f"{first} & {lab} & " + " & ".join(cells) + r" \\")
        if i != len(pairs) - 1:
            lines.append(r"\addlinespace[2pt]")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def rule2_table():
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r r r r r r r r@{}}", r"\toprule",
             r" & \multicolumn{4}{c}{Dev (screen)} & \multicolumn{4}{c}{Holdout (preregistered)} \\",
             r"\cmidrule(lr){2-5}\cmidrule(lr){6-9}",
             r"Local judge & cov. & wrong & upper & acc. & cov. & wrong & upper & acc. \\", r"\midrule"]
    locals_ = [a for a in BASE if FAM[a] == "local"]
    data = {}
    for sp in S:
        floor = S[sp]["decisions"]["rule2_offline_tier"]["min_coverage"]
        for arm in locals_:
            mv = maj(sp, arm, BOTH)
            data[(sp, arm)] = (mv["coverage"]["rate"], mv["automatic_errors"],
                               mv["wrong_automatic_rate"]["ci95"][1], mv["accuracy"],
                               mv["coverage"]["rate"] >= floor)
    order = sorted(locals_, key=lambda a: (not data[("holdout", a)][4], data[("holdout", a)][1],
                                           -data[("holdout", a)][3], a))
    for arm in order:
        cells = []
        for sp in ("dev", "holdout"):
            cov, k, up, acc, elig = data[(sp, arm)]
            cells += [f"{pct(cov)}\\,\\%" + ("" if elig else r"$^{\dagger}$"), str(k),
                      f"{pct(up)}\\,\\%", f"{pct(acc)}\\,\\%"]
        lines.append(f"{NAME[arm]} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def interventions_table():
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l l r r r r r r@{}}", r"\toprule",
             r" & & \multicolumn{3}{c}{Dev (screen)} & \multicolumn{3}{c}{Holdout (preregistered)} \\",
             r"\cmidrule(lr){3-5}\cmidrule(lr){6-8}",
             r"Intervention & arm & targeted & $\Delta$acc & $\Delta$cov & targeted & $\Delta$acc & $\Delta$cov \\",
             r"\midrule"]
    for key, _, label in INTERVENTIONS:
        per = {sp: {e["arm"]: e for e in S[sp]["decisions"]["rule4_interventions"][key]["arms"]} for sp in S}
        arms = [a for a, *_ in ARMS if any(a in per[sp] and per[sp][a]["applicable"] for sp in S)]
        for j, arm in enumerate(arms):
            cells = []
            for sp in ("dev", "holdout"):
                e = per[sp].get(arm)
                if e is None or not e["applicable"]:
                    cells += [r"\textemdash", "", ""]
                    continue
                mark = r"\,\ok" if e["confirmed"] else ""
                cells += [f"{e['targeted_wrong_auto_before']}$\\to${e['targeted_wrong_auto_after']}{mark}",
                          f"{e['accuracy_change_cases']:+d}".replace("-", "$-$"),
                          f"{e['coverage_change_points']:+.1f}".replace("-", "$-$")]
            lines.append(f"{label if j == 0 else ''} & {NAME[arm]} & " + " & ".join(cells) + r" \\")
        cells = []
        for sp in ("dev", "holdout"):
            o = S[sp]["decisions"]["rule4_interventions"][key]["overall"]
            cells += [f"{o['targeted_wrong_auto_before']}$\\to${o['targeted_wrong_auto_after']}",
                      r"\multicolumn{2}{r}{" + (r"\textbf{confirmed}" if o["confirmed"] else "not confirmed") + "}"]
        lines.append(r" & \emph{pooled} & " + " & ".join(cells) + r" \\")
        if key != INTERVENTIONS[-1][0]:
            lines.append(r"\midrule")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def failure_table(sp, automatic_only):
    key = "automatic_failure_classes" if automatic_only else "failure_classes"
    means = {arm: {c: sum(b[key].get(c, 0) for b in rep_blocks(sp, arm)) / len(rep_blocks(sp, arm))
                   for c, _ in CLASSES} for arm in BASE}
    vmax = max(max(v.values()) for v in means.values()) or 1
    heads = " & ".join(r"\rotatebox{60}{" + lab + "}" for _, lab in CLASSES)
    lines = [r"\begin{tabular}{@{}l " + "c" * len(CLASSES) + r" r@{}}", r"\toprule",
             f"Judge & {heads} & total \\\\", r"\midrule"]

    def fmt(v):
        return f"{v:.1f}".rstrip("0").rstrip(".")

    for arm in BASE:
        cells = []
        for c, _ in CLASSES:
            v = means[arm][c]
            if v == 0:
                cells.append(r"\textcolor{okgray}{\textperiodcentered}")
                continue
            shade = int(round(12 + 70 * v / vmax))
            color = r"\color{white}" if shade >= 50 else ""
            cells.append(f"\\cellcolor{{okblue!{shade}}}{color}{fmt(v)}")
        lines.append(f"{NAME[arm]} & " + " & ".join(cells) + f" & {fmt(sum(means[arm].values()))} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def threshold_table(sp):
    arms = ["jev-1.13", "gpt-6-luna", "gpt-6.1-sol", "nimble-9b", "tev1-4b", "tev1-0.8b", "qwen3-8b"]
    cols = ["0.75", "0.85", "0.9", "0.95", "0.99"]
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l " + "r" * len(cols) + r"@{}}", r"\toprule",
             "Judge & " + " & ".join(f"cutoff {float(c):.2f}" for c in cols) + r" \\", r"\midrule"]
    for arm in arms:
        cells = [f"{maj(sp, arm, f'cutoff-{c}')['automatic']} / {maj(sp, arm, f'cutoff-{c}')['automatic_errors']}"
                 for c in cols]
        lines.append(f"{NAME[arm]} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def cost_table():
    month = DECISIONS_PER_DAY * DAYS_PER_MONTH
    M("ProjPerDay", thousands(DECISIONS_PER_DAY))
    M("ProjDays", DAYS_PER_MONTH)
    M("ProjPerMonthM", f"{month / 1e6:g}")
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r r r r@{}}", r"\toprule",
             r"Judge & API cost per month & wrong automatic per month & automatic share & p95 (ms) \\",
             r"\midrule"]
    for arm in sorted(BASE, key=lambda a: (-cost("holdout", a), a)):
        mv = maj("holdout", arm)
        t = TOK[arm]
        M(f"{t}ProjUSD", thousands(cost("holdout", arm) * month / 1e6))
        M(f"{t}ProjWrong", thousands(mv["wrong_automatic_rate"]["rate"] * month))
        lines.append(f"{NAME[arm]} & \\${{}}\\{t}ProjUSD & \\{t}ProjWrong & \\{t}HoldCovPct\\,\\% & "
                     f"\\{t}HoldPninetyfive \\\\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def latency_anatomy_table():
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r r r r r@{}}", r"\toprule",
             r"Cloud call (keep-alive, medians, ms) & wall & server & network & client + rest & $n$ \\",
             r"\midrule"]
    for key, lab in (("jev|keepalive", "Jev 1.13"), ("luna|keepalive", "GPT-6 Luna"),
                     ("luna-priority|keepalive", "GPT-6 Luna, priority tier"), ("sol|keepalive", "GPT-6.1 Sol")):
        e = seq[key]
        w, s, n = e["wall_ms"]["p50"], e["server_ms"]["p50"], e["network_ms"]["p50"]
        lines.append(f"{lab} & {thousands(w)} & {thousands(s)} & {n:.0f} & {w - s - n:.0f} & {e['n']} \\\\")
    lines += [r"\midrule", r"Local call via Ollama (medians, ms) & wall & load & prefill & decode + rest & $n$ \\",
              r"\midrule"]
    for key, lab in LOCAL_GEN:
        e = seq[key]
        w, ld, pf = e["wall_ms"]["p50"], e["load_duration"]["p50"], e["prompt_eval_duration"]["p50"]
        lines.append(f"{lab} & {w:.0f} & {ld:.0f} & {pf:.0f} & {w - ld - pf:.0f} & {e['n']} \\\\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def concurrency_table():
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r r r r r r@{}}", r"\toprule",
             r" & \multicolumn{3}{c}{p50 latency (ms)} & \multicolumn{3}{c}{throughput (requests/s)} \\",
             r"\cmidrule(lr){2-4}\cmidrule(l){5-7}",
             r"Requests in flight & 1 & 4 & 8 & 1 & 4 & 8 \\", r"\midrule"]
    for arm, lab in (("jev", "Jev 1.13"), ("luna", "GPT-6 Luna"), ("so:tev1:0.8b", "tev1 0.8B"),
                     ("laya", "Laya base"), ("gen:qwen3:8b", "Qwen3 8B"), ("so:nimble", "nimble 9B")):
        cl, ct = [], []
        for k in (1, 4, 8):
            e = conc.get(f"{arm}|k={k}")
            cl.append(thousands(e["wall_ms"]["p50"]))
            if "ok_only_throughput_rps" in e:
                ct.append(f"{e['ok_only_throughput_rps']:.1f}$^{{*}}$")
            else:
                ct.append(f"{e['throughput_rps']:.1f}")
        lines.append(f"{lab} & " + " & ".join(cl + ct) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def changes_table():
    style = {"confirmed": r"\vconf", "refuted": r"\vref", "revised": r"\vrev", "new": r"\vnew"}
    counts = defaultdict(int)
    head = r"First-pass claim & First pass said & What the validation found & Verdict \\"
    lines = [r"\begin{xltabular}{\textwidth}{@{}>{\raggedright\arraybackslash}p{0.2\textwidth}"
             r" >{\raggedright\arraybackslash}p{0.15\textwidth} >{\raggedright\arraybackslash}X l@{}}",
             r"\caption{All \ChangesN\ first-pass claims, what the first pass said, and what the validation found "
             r"(verbatim from \code{changes.json}, where each entry also names its evidence file).}"
             r"\label{tab:changes}\\",
             r"\toprule", head, r"\midrule", r"\endfirsthead",
             r"\multicolumn{4}{@{}l}{\small\emph{(continued)}}\\", r"\toprule", head, r"\midrule", r"\endhead",
             r"\bottomrule", r"\endlastfoot"]
    for i, c in enumerate(CHANGES):
        counts[c["verdict"]] += 1
        lines.append(f"{tex_escape(c['claim'])} & {tex_escape(c['first_pass'])} & "
                     f"{tex_escape(c['validated'])} & {style[c['verdict']]} \\\\")
        if i != len(CHANGES) - 1:
            lines.append(r"\addlinespace[4pt]")
    lines.append(r"\end{xltabular}")
    M("ChangesN", len(CHANGES))
    for k in ("confirmed", "refuted", "revised", "new"):
        M("Changes" + k.capitalize(), counts[k])
    return "\n".join(lines) + "\n"


def label_table():
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l r l l l@{}}", r"\toprule",
             r"Split & cases & reviewer A vs B & A vs frozen label & B vs frozen label \\", r"\midrule"]
    for sp, _ in SPLITS:
        a = AGREE[sp]
        cells = [f"{a[k]['agreement'] * a[k]['n']:.0f}/{a[k]['n']} ($\\kappa = {a[k]['kappa']:.2f}$)"
                 for k in ("A_vs_B", "A_vs_frozen", "B_vs_frozen")]
        lines.append(f"{sp} & {a['A_vs_B']['n']} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


def case_block(sp, cid):
    case = CASES[sp][cid]
    tags = MAN[sp]["tags"].get(cid, {})
    st = json.loads(case["payload"]["state"])
    q = case["payload"]["questions"]["decision"]
    out = [r"\begin{casecard}{\texttt{" + tex_escape(cid) + "} (" +
           ("dev split, screen" if sp == "dev" else "holdout split, preregistered") + ")}"]
    if case["kind"] == "search":
        out.append(r"\textbf{Query:} " + tex_escape(st["query"]) + r"\par\smallskip")
        out.append(r"\textbf{Source:}\par")
        out.append(r"\begin{lstlisting}")
        out.append(st["source"])
        out.append(r"\end{lstlisting}")
        out.append(r"\textbf{Question:} does the source implement the query? (yes/no, no \texttt{reason} option)\par")
    else:
        out.append(r"\textbf{Task:} " + tex_escape(st["task"]) + r"\par")
        out.append(r"\textbf{Observation:} " + tex_escape(st["observation"]) + r"\par")
        crit = q["criteria"]
        out.append(r"\textbf{Options:} \texttt{a} = " + tex_escape(crit["a"]) + r"; \texttt{b} = "
                   + tex_escape(crit["b"]) + r"; \texttt{reason} = fall back to slow reasoning.\par")
    lab = case["expected"]
    lab_s = ("yes" if lab else "no") if isinstance(lab, bool) else lab
    extra = []
    if tags.get("side_effect"):
        extra.append("side effect")
    if tags.get("injection"):
        extra.append(r"injection pushing toward \texttt{" + tex_escape(str(tags.get("injected_target"))) + "}")
    out.append(r"\textbf{Label:} \texttt{" + tex_escape(str(lab_s)) + "}"
               + (r"\quad\textbf{Tags:} " + ", ".join(extra) if extra else "") + r"\par\smallskip")
    out.append(r"{\small\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}l l l l@{}}\toprule")
    out.append(r"Judge & rep 1 & rep 2 & rep 3 \\ \midrule")
    by = case_rows(sp, cid, BASE)
    for arm in BASE:
        cells = []
        for rep in (1, 2, 3):
            r = by[arm].get(rep)
            if r is None or not r.get("valid"):
                cells.append("invalid")
                continue
            p, c_, _, status = bundle_outcome(case, r["answer"], r["elapsed_ms"], RUN[sp]["timeout_ms"])
            ps = ("yes" if p else "no") if isinstance(p, bool) else p
            sym = {"auto-right": r"\symok", "AUTO-WRONG": r"\symbad"}.get(status, r"\symfb")
            late = r"$^{\mathrm{t}}$" if status == "fallback:timeout" else ""
            cells.append(f"{sym}\\ \\texttt{{{tex_escape(str(ps))}}} {c_:.2f}{late}")
        out.append(f"{NAME[arm]} & " + " & ".join(cells) + r" \\")
    out.append(r"\bottomrule\end{tabular*}}")
    out.append(r"\end{casecard}")
    return "\n".join(out) + "\n"


# Cross-check the per-case display gate against summary.json on every arm and repetition.
for sp in S:
    for arm in TOK:
        for rep, block in enumerate(rep_blocks(sp, arm), start=1):
            errs = autos = 0
            for r in REQ[sp]:
                if r["arm"] == arm and r["rep"] == rep and r["order"] == 0 and r.get("valid"):
                    status = bundle_outcome(CASES[sp][r["id"]], r["answer"], r["elapsed_ms"],
                                            RUN[sp]["timeout_ms"])[3]
                    autos += status in ("auto-right", "AUTO-WRONG")
                    errs += status == "AUTO-WRONG"
            assert (errs, autos) == (block["automatic_errors"], block["automatic"]), (sp, arm, rep, errs, autos)

for sp, _ in SPLITS:
    write(TABLES / f"headline-{sp}.tex", headline_table(sp))
    write(TABLES / f"rule1-{sp}.tex", rule1_table(sp))
    M(f"SideEffectJudges{sp.capitalize() if sp == 'dev' else 'Hold'}",
      sum(1 for a in BASE if sum(b["failure_classes"].get("acted_on_side_effect", 0) for b in rep_blocks(sp, a)) > 0))
write(TABLES / "pairwise.tex", pairwise_table())
write(TABLES / "failure-holdout.tex", failure_table("holdout", False))
write(TABLES / "failure-auto-holdout.tex", failure_table("holdout", True))
write(TABLES / "threshold-holdout.tex", threshold_table("holdout"))
write(TABLES / "rule2.tex", rule2_table())
write(TABLES / "interventions.tex", interventions_table())
write(TABLES / "cost.tex", cost_table())
write(TABLES / "latency-anatomy.tex", latency_anatomy_table())
write(TABLES / "latency-concurrency.tex", concurrency_table())
write(TABLES / "changes.tex", changes_table())
write(TABLES / "label-audit.tex", label_table())
write(TABLES / "case-cua-18.tex", case_block("dev", "cua-18"))
EXAMPLES = [("dev", "fresh-cua-09"), ("dev", "search-11"),
            ("holdout", "hold-cua-00"), ("holdout", "hold-cua-12"), ("holdout", "hold-select-06"),
            ("holdout", "hold-search-15")]
write(TABLES / "case-examples.tex", "\n".join(case_block(sp, cid) for sp, cid in EXAMPLES))
adj = AGREE["dev"]["adjudication"]
write(TABLES / "adjudication.tex",
      "\\begin{description}[leftmargin=1.2em,style=nextline]\n"
      + "\n".join(r"\item[\texttt{" + tex_escape(cid) + r"}] \emph{" + tex_escape(adj[cid]["verdict"]) + ".} "
                  + tex_escape(adj[cid]["detail"]) for cid in ("cua-18", "cua-19", "fresh-cua-09", "search-11"))
      + "\n\\end{description}\n")


def arms_table():
    specs = RUN["holdout"]["specs"]
    how = {"chat": "OpenAI API", "systemone": "System One endpoint",
           "ollama_backend": "bundle OllamaBackend"}
    lines = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l l l l r@{}}", r"\toprule",
             r"Judge & where it runs & how it is called & probabilities & \$ per 1M tokens in/out \\",
             r"\midrule"]
    for arm in BASE:
        sp_ = specs[arm]
        where = "locally" if sp_.get("local") else "hosted"
        probs = "self-reported" if sp_.get("probabilities") == "self_reported" else "from the model"
        extra = ""
        if sp_.get("effort"):
            extra = f" (effort \\texttt{{{sp_['effort']}}})"
        price = (f"{sp_['price_in']:g} / {sp_['price_out']:g}" if sp_.get("price_in") is not None
                 else r"\textemdash")
        lines.append(f"{NAME[arm]} & {where} & {how[sp_['adapter']]}{extra} & {probs} & {price} \\\\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(lines) + "\n"


write(TABLES / "arms.tex", arms_table())
clause = RUN["holdout"]["specs"]["jev-1.13+sideeffect-clause"]["clause"]
M("IOneClause", tex_escape(clause))
M("PriorityMultiplier", f"{RUN['holdout']['specs']['gpt-6-luna']['priority_multiplier']:g}")

# ------------------------------------------------------------------- data

def dat(path, header, rows_):
    write(DATA / path, "\n".join([" ".join(header)] + [" ".join(str(x) for x in r) for r in rows_]) + "\n")


order = sorted(TOK, key=lambda a: (maj("holdout", a)["correct"], maj("dev", a)["correct"], a))
acc_rows = []
for i, arm in enumerate(order):
    row = [i, "{" + NAME[arm] + "}"]
    for sp in ("dev", "holdout"):
        mv = maj(sp, arm)
        a, (lo, hi) = mv["accuracy"], mv["ci95"]
        row += [f"{100 * a:.2f}", f"{100 * (a - lo):.2f}", f"{100 * (hi - a):.2f}"]
    acc_rows.append(row)
dat("accuracy.dat", ["idx", "label", "dev", "devminus", "devplus", "hold", "holdminus", "holdplus"], acc_rows)
M("AccPlotMax", len(order) - 1)

# Label placement for the scatter plots: a small deterministic greedy placer. It estimates each
# label's box in points (axis geometry fixed by `scale only axis` in the figure files) and picks,
# per point, the anchor that least overlaps other labels, all markers and the axis edge. Placement
# never changes a plotted value.
AXIS_W, AXIS_H = 12.5 * 28.45, 6.2 * 28.45      # must match figures/fig-wa-coverage.tex, fig-acc-latency.tex
CHAR_W, LABEL_H, PAD, MARK_R = 3.9, 7.5, 2.5, 3.2
CANDIDATES = ["west", "east", "south", "north", "south west", "north west", "south east", "north east"]


def _box(px, py, text, anchor):
    w, h = len(text) * CHAR_W + 2 * PAD, LABEL_H + 2 * PAD
    x0 = {"west": px, "east": px - w}.get(anchor.split()[-1], px - w / 2)
    if anchor in ("south west", "north west"):
        x0 = px
    if anchor in ("south east", "north east"):
        x0 = px - w
    if anchor.startswith("south"):
        y0 = py
    elif anchor.startswith("north"):
        y0 = py - h
    else:
        y0 = py - h / 2
    if anchor in ("west", "east"):
        x0 += MARK_R if anchor == "west" else -MARK_R
    return (x0, y0, x0 + w, y0 + h)


def _overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


SHIFTS = [0.0, 7.0, 14.0, 21.0]
UNIT = {"west": (1, 0), "east": (-1, 0), "south": (0, 1), "north": (0, -1), "south west": (1, 1),
        "north west": (1, -1), "south east": (-1, 1), "north east": (-1, -1)}


def place_labels(points, xr, yr, xlog=False):
    """points: [(key, text, x, y)] in data units -> {key: (anchor, xshift_pt, yshift_pt)}.
    Greedy start, then a few rounds of re-placing each label given all the others."""
    def tx(x):
        if xlog:
            return AXIS_W * (math.log10(x) - math.log10(xr[0])) / (math.log10(xr[1]) - math.log10(xr[0]))
        return AXIS_W * (x - xr[0]) / (xr[1] - xr[0])

    def ty(y):
        return AXIS_H * (y - yr[0]) / (yr[1] - yr[0])

    pts = [(k, t, tx(x), ty(y)) for k, t, x, y in points]
    marks = {k: (px - MARK_R, py - MARK_R, px + MARK_R, py + MARK_R) for k, _, px, py in pts}
    options = [(a, d) for d in SHIFTS for a in CANDIDATES]

    def box_for(p, opt):
        k, t, px, py = p
        a, d = opt
        ux, uy = UNIT[a]
        return _box(px + ux * d, py + uy * d, t, a)

    def cost(p, b, others, rank):
        c = sum(_overlap(b, o) for o in others) * 4
        c += sum(_overlap(b, m) for k, m in marks.items()) * 3
        c += 50 * (max(0, -b[0]) + max(0, b[2] - AXIS_W) + max(0, -b[1]) + max(0, b[3] - AXIS_H))
        return c + rank * 0.3

    choice = {}
    order = sorted(pts, key=lambda p: (p[2], p[0]))
    for _ in range(6):
        for p in order:
            others = [box_for(q, choice[q[0]]) for q in order if q[0] != p[0] and q[0] in choice]
            best = min(((cost(p, box_for(p, o), others, r), r, o) for r, o in enumerate(options)))
            choice[p[0]] = best[2]
    out = {}
    for k, _, _, _ in pts:
        a, d = choice[k]
        ux, uy = UNIT[a]
        out[k] = (a, f"{ux * d + 0.0:g}", f"{uy * d + 0.0:g}")
    return out


WACOV_X, WACOV_Y = (15, 100), (0, 40)
ACCLAT_X, ACCLAT_Y = (25, 9000), (25, 102)
ANCHORS, LAT_ANCHORS = {}, {}
for sp in S:
    pts_wa, pts_lat = [], []
    for arm in BASE:
        mv = maj(sp, arm)
        pts_wa.append((arm, NAME[arm], 100 * mv["coverage"]["rate"], 100 * mv["wrong_automatic_rate"]["rate"]))
        pts_lat.append((arm, NAME[arm], pooled(sp, arm, .95), 100 * mv["accuracy"]))
    ANCHORS[sp] = place_labels(pts_wa, WACOV_X, WACOV_Y)
    LAT_ANCHORS[sp] = place_labels(pts_lat, ACCLAT_X, ACCLAT_Y, xlog=True)
FAMS = {"cloud": ["gpt-6-luna", "gpt-6.1-sol"], "jev": ["jev-1.13"],
        "local": [a for a in BASE if FAM[a] == "local"]}
for sp in S:
    for fam, arms in FAMS.items():
        out = []
        for arm in arms:
            mv = maj(sp, arm)
            cov, wa, acc = mv["coverage"], mv["wrong_automatic_rate"], mv["accuracy"]
            out.append(["{" + NAME[arm] + "}",
                        f"{100 * cov['rate']:.2f}", f"{100 * (cov['rate'] - cov['ci95'][0]):.2f}",
                        f"{100 * (cov['ci95'][1] - cov['rate']):.2f}",
                        f"{100 * wa['rate']:.2f}", f"{100 * (wa['rate'] - wa['ci95'][0]):.2f}",
                        f"{100 * (wa['ci95'][1] - wa['rate']):.2f}",
                        f"{100 * acc:.2f}", f"{100 * (acc - mv['ci95'][0]):.2f}",
                        f"{100 * (mv['ci95'][1] - acc):.2f}",
                        f"{pooled(sp, arm, .95):.1f}",
                        "{" + ANCHORS[sp][arm][0] + "}", ANCHORS[sp][arm][1], ANCHORS[sp][arm][2],
                        "{" + LAT_ANCHORS[sp][arm][0] + "}", LAT_ANCHORS[sp][arm][1], LAT_ANCHORS[sp][arm][2]])
        dat(f"scatter-{sp}-{fam}.dat",
            ["label", "cov", "covminus", "covplus", "wa", "waminus", "waplus", "acc", "accminus", "accplus",
             "pninetyfive", "anchor", "dx", "dy", "latanchor", "latdx", "latdy"], out)

cloud_rows = []
for i, (key, lab) in enumerate((("sol|keepalive", "GPT-6.1 Sol"), ("luna|keepalive", "GPT-6 Luna"),
                                ("luna-priority|keepalive", "Luna, priority"), ("jev|keepalive", "Jev 1.13"))):
    e = seq[key]
    w, s, n = e["wall_ms"]["p50"], e["server_ms"]["p50"], e["network_ms"]["p50"]
    cloud_rows.append([i, "{" + lab + "}", f"{n:.1f}", f"{s:.1f}", f"{max(0.0, w - s - n):.1f}", f"{w:.1f}"])
dat("latency-cloud.dat", ["idx", "label", "network", "server", "other", "wall"], cloud_rows)
local_rows = []
for i, (key, lab) in enumerate(reversed(LOCAL_GEN)):
    e = seq[key]
    w, ld, pf = e["wall_ms"]["p50"], e["load_duration"]["p50"], e["prompt_eval_duration"]["p50"]
    local_rows.append([i, "{" + lab + "}", f"{ld:.1f}", f"{pf:.1f}", f"{max(0.0, w - ld - pf):.1f}", f"{w:.1f}"])
dat("latency-local.dat", ["idx", "label", "load", "prefill", "other", "wall"], local_rows)

SWEEP = ["jev-1.13", "gpt-6-luna", "gpt-6.1-sol", "nimble-9b", "tev1-4b", "tev1-0.8b"]
for sp in S:
    out = []
    for c in CUTOFFS:
        row = [c]
        for arm in SWEEP:
            mv = maj(sp, arm, f"cutoff-{c}")
            row += [f"{100 * mv['coverage']['rate']:.2f}", f"{100 * mv['wrong_automatic_rate']['rate']:.2f}"]
        out.append(row)
    dat(f"sweep-{sp}.dat", ["cutoff"] + [f"{k}{TOK[a]}" for a in SWEEP for k in ("cov", "wa")], out)

for sp, P in SPLITS:
    for arm in BASE:
        blocks = rep_blocks(sp, arm)
        for key, tag in (("failure_classes", "All"), ("automatic_failure_classes", "Auto")):
            for cls, ctag in (("injection_following", "Inj"), ("acted_on_side_effect", "Side"),
                              ("accepted_wrong_code", "Awc")):
                v = sum(b[key].get(cls, 0) for b in blocks) / len(blocks)
                M(f"{TOK[arm]}{P}{tag}{ctag}", f"{v:.1f}".rstrip("0").rstrip("."))
M("SweepMin", CUTOFFS[0])
M("SweepMax", CUTOFFS[-1])
for sp, P in SPLITS:
    for arm in ("jev-1.13", "gpt-6-luna", "gpt-6.1-sol"):
        zero = next((c for c in CUTOFFS if maj(sp, arm, f"cutoff-{c}")["automatic_errors"] == 0), None)
        M(f"{TOK[arm]}{P}ZeroCut", zero if zero else "none")
        M(f"{TOK[arm]}{P}ZeroCutCov", pct(maj(sp, arm, f"cutoff-{zero}")["coverage"]["rate"]) if zero else "n/a")

i2 = [e for e in S["holdout"]["decisions"]["rule4_interventions"]["I2"]["arms"] if e["applicable"]]
i2.sort(key=lambda e: (e["targeted_wrong_auto_before"], e["arm"]))
dat("i2-holdout.dat", ["idx", "label", "before", "after", "cov"],
    [[i, "{" + NAME[e["arm"]] + "}", e["targeted_wrong_auto_before"], e["targeted_wrong_auto_after"],
      f"{e['coverage_change_points']:.2f}"] for i, e in enumerate(i2)])
M("ITwoPlotMax", len(i2) - 1)

header = ("% Generated by build_assets.py from docs/evidence/2026-09-30-judge-benchmark/. Do not edit.\n"
          f"% {len(MACROS)} macros.\n")
write(OUT / "numbers.tex", header + "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in sorted(MACROS.items())))
print(f"wrote {len(MACROS)} macros, {len(list(TABLES.glob('*.tex')))} tables, {len(list(DATA.glob('*.dat')))} data files")
