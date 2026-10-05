#!/usr/bin/env python3
"""Generate every number, table and plot datum used by the paired-measurement report.

Reads ONLY committed files:
    docs/evidence/2026-10-02-paired-campaign/   (the campaign evidence package)
    docs/design/parallel-measurement-mode.md    (design v2: power table)
    docs/design/pilot-20261001/                 (cache-semantics probe)
    evals/paired/                               (memory-safety README, design yaml, scenario directories)
    origin/eval/judge-realistic:docs/evidence/2026-10-01-caching/results.json  (the earlier caching survey;
        read with `git show`, the build stops if that ref is missing)
and writes generated/:
    numbers.tex   \\newcommand macros for every number used in prose
    tables/*.tex  booktabs tables
    data/*.dat    pgfplots data
    labels/*.tex  placed scatter labels (labelplacer.py; the build stops if a label cannot be placed cleanly)

Deterministic: no clock, randomness, network or model calls. A few facts exist only as prose in committed
Markdown; they are read with anchored patterns and the build stops if the text no longer matches.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import subprocess
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import labelplacer as LP
import jb_import

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EV = REPO / "docs" / "evidence" / "2026-10-02-paired-campaign"
DESIGN = REPO / "docs" / "design" / "parallel-measurement-mode.md"
PROBE = REPO / "docs" / "design" / "pilot-20261001" / "step1_cache_probe.json"
PAIRED = REPO / "evals" / "paired"
SURVEY_REF = "origin/eval/judge-realistic:docs/evidence/2026-10-01-caching/results.json"
OUT = HERE / "generated"
TABLES, DATA = OUT / "tables", OUT / "data"

HOSTS = [("fable", "Fable", "Fable 5.1"), ("opus", "Opus", "Opus 5.5")]
ARMS = [("sticky", "Sticky", "sticky"), ("shipped", "Shipped", "shipped"), ("sonnet", "Sonnet", "sonnet")]
TASKS = ["bugfix", "feature", "mixed", "docs", "explain", "review"]
MACROS: dict[str, str] = {}

# ----------------------------------------------------------------- helpers


def M(name: str, value) -> None:
    if not name.isalpha():
        raise ValueError(f"macro name must be letters only: {name}")
    if name in MACROS and MACROS[name] != str(value):
        raise ValueError(f"macro {name} redefined: {MACROS[name]!r} vs {value!r}")
    MACROS[name] = str(value)


def hu(v, d=2) -> str:
    """Half-up rounding of the value as stored (0.5575 -> 0.56), with a typeset minus sign."""
    q = Decimal(1).scaleb(-d)
    s = str(Decimal(str(v)).quantize(q, rounding=ROUND_HALF_UP))
    return s.replace("-", "$-$")


def ci(c, d=2) -> str:
    return f"{hu(c[0], d)}--{hu(c[1], d)}"


def pct(x, d=0) -> str:
    return hu(100 * x, d)


def money(x, d=2) -> str:
    s = f"{abs(x):,.{d}f}".replace(",", "{,}")
    return ("$-$" if x < 0 else "") + s


def thousands(x) -> str:
    return f"{x:,.0f}".replace(",", "{,}")


def pval(p) -> str:
    return "1.00" if p >= 0.9995 else hu(p, 2) if p >= 0.01 else hu(p, 3)


def tex_escape(s: str) -> str:
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(rep.get(ch, ch) for ch in s)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def dat(name, header, rows):
    write(DATA / name, "\n".join([" ".join(header)] + [" ".join(str(x) for x in r) for r in rows]) + "\n")


def grab(path: Path, pattern: str, group=1, text=None):
    src = text if text is not None else path.read_text()
    m = re.search(pattern.replace(" ", r"\s+"), src, re.S)
    if not m:
        raise SystemExit(f"build_assets.py: pattern not found in {path}: {pattern!r}")
    return m.group(group)


def jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def table(spec, head, rows, width=r"\textwidth"):
    out = [rf"\begin{{tabular*}}{{{width}}}{{@{{\extracolsep{{\fill}}}}{spec}@{{}}}}", r"\toprule"]
    out += head + [r"\midrule"] + rows + [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ inputs

# Part I sources: the judge-benchmark paper's own build, run on evidence extracted from its branch
JR_SRC, JR_SHA = jb_import.run(REPO, OUT)

CONF = json.loads((EV / "confirm/confirm.json").read_text())
SUMM = json.loads((EV / "model/summary.json").read_text())
DSUM = json.loads((EV / "data/summary.json").read_text())
SESS = jsonl(EV / "data/sessions.jsonl")
PAIRS = jsonl(EV / "data/pairs.jsonl")
REQS = jsonl(EV / "data/requests.jsonl.gz")
STATE = json.loads((EV / "campaign/state.json").read_text())
LEDGER = json.loads((EV / "campaign/ledger.json").read_text())
DECIS = jsonl(EV / "campaign/decisions.jsonl")
SPLIT = json.loads((EV / "prereg/split.json").read_text())
PILOT = json.loads((EV / "pilot/summary.json").read_text())
PILOT_LEDGER = json.loads((EV / "pilot/ledger.json").read_text())
PROBE_J = json.loads(PROBE.read_text())
PRED = json.loads((EV / "model/predictions.json").read_text())
try:
    SURVEY = json.loads(subprocess.run(["git", "-C", str(REPO), "show", SURVEY_REF], capture_output=True,
                                       text=True, check=True).stdout)
except subprocess.CalledProcessError as exc:
    raise SystemExit(f"build_assets.py: cannot read {SURVEY_REF} (fetch the branch first): {exc.stderr}")
CC = CONF["confirmatory"]
EXP = CONF["exploratory"]

# ------------------------------------------------------------ campaign facts

M("NSessions", thousands(DSUM["sessions"]))
M("NTurns", thousands(DSUM["turns"]))
M("NRequests", thousands(DSUM["requests"]))
M("NPairs", DSUM["pairs"])
M("NPairsValid", sum(p["valid"] for p in PAIRS))
M("NWaves", len(STATE["waves"]))
M("NScenarios", len(SPLIT["split"]))
M("NTrain", sum(v == "train" for v in SPLIT["split"].values()))
M("NTest", sum(v == "test" for v in SPLIT["split"].values()))
M("NTestPairs", CONF["counts"]["test_pairs"])
M("SplitSeed", SPLIT["seed"])
M("NReps", max(s["rep"] for s in SESS))
fam = {}
for d in sorted((PAIRED / "scenarios" / "main-v1").iterdir()):
    if d.is_dir() and not d.name.startswith("_"):
        fam[d.name] = sorted(p.stem for p in d.glob("*.yaml"))
assert sum(len(v) for v in fam.values()) == len(SPLIT["split"])
for f, ids in fam.items():
    M("Fam" + f.capitalize(), len(ids))
M("NFamilies", len(fam))
M("MinTurns", min(s["scripted_turns"] for s in SESS))
M("MaxTurns", max(s["scripted_turns"] for s in SESS))
gaps = sorted({g for s in SESS for g in s["gap_schedule"]})
M("LongGapS", max(gaps))
M("LongGapMin", f"{max(gaps) / 60:g}")
M("ShortGapS", sorted(g for g in gaps if g > 0)[0])
anchors = [s for s in SESS if s["arm"] == "anchor" and s["host"] == "opus" and s["rep"] == 1]
M("NLongGapScen", sum(s["n_long_gaps"] > 0 for s in anchors))
M("LongGapsPerScen", max(s["n_long_gaps"] for s in anchors))
mean_turns = sum(s["scripted_turns"] for s in anchors) / len(anchors)
M("MeanTurns", hu(mean_turns, 1))
aa_frac = grab(PAIRED / "main-v1.yaml", r"subsample: \{fraction: ([\d.]+),")
M("AAPct", pct(float(aa_frac)))
M("NAAPairs", sum(p["arm"] == "aa" for p in PAIRS))
M("NIMargin", hu(CONF["ni_margin"], 2))
M("NIMarginPts", hu(abs(CONF["ni_margin"]) * 100, 0))
M("Boot", thousands(CONF["bootstrap"]))
M("BootSeed", CONF["seed"])
M("CacheTTLMin", grab(EV / "data/DATA-DICTIONARY.md", r"outlast the (\d+)-minute cache TTL"))
M("ToolsAllowance", thousands(SESS[0]["tools_prefix_allowance_tokens"]))
M("ToolsDeltaTotal", money(-DSUM["tools_normalized_delta_usd_total"]))
M("AuditFlagged", len(DSUM["cache_audit_flagged_sessions"]))
M("MechFailed", len(DSUM["mechanism_failed"]))
M("CostMismatch", len(DSUM["cost_mismatch"]))
cheap = defaultdict(int)
for d in DECIS:
    cheap[(d["host"], d["decision"])] += 1
M("StickyCheap", cheap[("fable", "cheap")])
M("StickyHost", cheap[("fable", "host")])
assert cheap[("fable", "cheap")] == cheap[("opus", "cheap")]
M("StickyDecisions", cheap[("fable", "cheap")] + cheap[("fable", "host")])
M("StickyCheapPct", pct(cheap[("fable", "cheap")] / (cheap[("fable", "cheap")] + cheap[("fable", "host")])))
M("PlanParallel", grab(EV / "campaign/plan.txt", r"parallel=(\d+)"))

# provenance and timing
prov = (EV / "prereg/PROVENANCE.md").read_text()
M("PreregSha", grab(EV / "prereg/PROVENANCE.md", r"\| `evals/paired/PREREGISTRATION-main-v1.md` \| preregistration \| `([0-9a-f]{7})"))
M("PreregTime", grab(EV / "prereg/PROVENANCE.md", r"preregistration commit time: 2026-10-01T(\d\d:\d\d):\d\d-04:00"))
M("SplitTime", grab(EV / "prereg/PROVENANCE.md", r"the split commit is earlier still \(2026-10-01T(\d\d:\d\d):\d\d-04:00\)"))
gap = grab(EV / "prereg/PROVENANCE.md", r"gap: preregistration is (\d+):(\d\d):(\d\d)", 0)
mm, ss = re.search(r"(\d+):(\d\d):(\d\d)", gap).group(2, 3)
M("PreregGapMin", int(mm))
M("PreregGapSec", int(ss))
M("HarnessSha", grab(EV / "prereg/PROVENANCE.md", r"committed as `([0-9a-f]{7})` on Oct 2"))
M("BuildSha", SESS[0]["build_sha"][:7])
assert all(s["build_sha"] == SESS[0]["build_sha"] for s in SESS)
starts = sorted(s["actual_start"] for s in SESS)
M("FirstStart", starts[0][:16].replace("T", " "))
M("LastStart", starts[-1][:16].replace("T", " "))
sup = (EV / "campaign/supervisor.log").read_text()
M("CompleteEDT", grab(EV / "campaign/supervisor.log", r"(\d\d:\d\d):\d\d EDT 2026 campaign complete"))
M("WallHours", grab(EV / "reproduce/README.md", r"\(about (\d+) h\)"))

# spend
spent = LEDGER["spent"]
M("SpendLedger", money(sum(spent.values())))
M("SpendBudget", money(LEDGER["budget_usd"], 0))
M("SpendSessions", money(sum(s["cost_usd_provider"] for s in SESS)))
M("SpendPreflight", money(sum(v for k, v in spent.items() if k.startswith("preflight#"))))
M("SpendPilotTwo", money(sum(PILOT_LEDGER["spent"].values())))
pilot1 = float(grab(EV / "reproduce/README.md", r"\| pilot-1 \(not packaged\) \| ([\d.]+) \|"))
M("SpendPilotOne", money(pilot1))
M("SpendPilots", money(pilot1 + sum(PILOT_LEDGER["spent"].values())))
M("SpendToolsNorm", money(sum(s["cost_usd_tools_normalized"] for s in SESS)))
M("PilotSessions", PILOT["sessions"])

# failures: section 7 table of FAILURES.md (one row per failed attempt), cross-checked with state.json
fail_rows = re.findall(r"^\| ([a-z0-9-]+-r\d-(?:opus|fable)) \| (\d+) \| ([a-z_>-]+) \| (\d+) \| [^|]+ \| ([a-z_]+) \| ([^|]+) \| ([\d.]+) \|$",
                       (EV / "campaign/FAILURES.md").read_text(), re.M)
n_failed_state = sum(1 for w in STATE["waves"].values() for a in w["attempts"] if a["status"] != "done") + \
    sum(len(h["attempts"]) for w in STATE["waves"].values() for h in w.get("history", []))
assert len(fail_rows) == n_failed_state, (len(fail_rows), n_failed_state)
M("NFailed", len(fail_rows))
M("NAttempts", len(fail_rows) + len(STATE["waves"]))
M("NWavesReset", sum(1 for w in STATE["waves"].values() if w.get("history")))
M("NFailedUSD", money(sum(float(r[6]) for r in fail_rows)))
M("NFailedInferred", sum("INFERRED" in r[5] for r in fail_rows))
causes = defaultdict(lambda: [0, 0, 0.0])
for r in fail_rows:
    c = causes[r[4]]
    c[0] += 1
    c[1] += int(r[3])
    c[2] += float(r[6])
CAUSE_NAMES = {"forge_session_cap": "Terminal-server session cap (harness bug)",
               "forge_daemon_restart": "Terminal-server daemon restart", "mac_sleep": "Laptop lid closed on battery"}
for k, t in (("forge_session_cap", "Cap"), ("forge_daemon_restart", "Restart"), ("mac_sleep", "Sleep")):
    M(f"Fail{t}", causes[k][0])
    M(f"Fail{t}USD", money(causes[k][2]))
rows = [f"{CAUSE_NAMES[k]} & {v[0]} & {v[1]} & \\${money(v[2])} \\\\" for k, v in sorted(causes.items(), key=lambda kv: -kv[1][0])]
rows.append(r"\midrule")
rows.append(f"Total & {len(fail_rows)} & {sum(v[1] for v in causes.values())} & \\${money(sum(v[2] for v in causes.values()))} \\\\")
write(TABLES / "failures.tex", table("l r r r", [r"Cause & failed attempts & sessions in them & spend \\"], rows))

# memory safety (evals/paired/README.md) and the one kill
mem = PAIRED / "README.md"
M("MemGrowLow", grab(mem, r"grew to (\d+)-\d+ GB"))
M("MemGrowHigh", grab(mem, r"grew to \d+-(\d+) GB"))
M("MemMacGB", grab(mem, r"drove a (\d+) GB Mac out of memory"))
M("MemTimes", grab(mem, r"out of memory (\w+)\s+times"))
M("MemPollS", grab(mem, r"polled every ([\d.]+) s"))
M("MemGraderGB", grab(mem, r"run under it: (\d+) GB, \d+ s"))
M("MemGraderS", grab(mem, r"run under it: \d+ GB, (\d+) s"))
M("MemHardFloorGB", grab(mem, r"below (\d+) GB \(`--hard-floor-gb`\)"))
M("MemWatchS", grab(mem, r"a watchdog thread \((\d+) s\)"))
killed = [s for s in SESS if s["killed_memory"]]
assert len(killed) == 1
ki = killed[0]["killed_memory_info"]
M("KillRSS", hu(ki["rss_gb"], 2))
M("KillCap", hu(ki["session_cap_gb"], 0))
M("KillAvail", hu(ki["available_gb"], 1))
M("KillSession", tex_escape(killed[0]["session_key"]))
M("KillTurnPass", hu(killed[0]["turn_pass_frac"], 1))

# ------------------------------------------------------------ prior evidence
M("SurveyRoutedPairs", SURVEY["headline"]["routed_pairs"])
M("SurveyReceipts", SURVEY["headline"]["routed_pairs_with_efficiency_receipts"])
cells = SURVEY["headline"]["corrections"]["same_cell_length_contrast"]["cells"]
M("SurveyOpusOne", hu(cells["orch-default-opus vs plain-opus"]["S1-single"]["cost"]["geomean"]))
M("SurveyOpusFour", hu(cells["orch-default-opus vs plain-opus"]["S1-multi"]["cost"]["geomean"]))
M("SurveyFableOne", hu(cells["orch-default vs plain"]["S1-single"]["cost"]["geomean"]))
M("SurveyFableFour", hu(cells["orch-default vs plain"]["S1-multi"]["cost"]["geomean"]))
M("SurveyTurns", len([k for k in SURVEY["headline"]["per_turn_multiturn"] if k.startswith("opus_turn")]))

# ------------------------------------------------------------ cache probe
PRB = PROBE_J["requests"]


def probe(test, label, model=None):
    hits = [r for r in PRB if r["test"] == test and r["label"] == label and (model is None or r["model"] == model)]
    assert hits, (test, label, model)
    u = hits[0]["usage"]
    return u["cache_creation_input_tokens"], u["cache_read_input_tokens"]


M("ProbeRequests", len(PRB))
M("ProbeUSD", money(PROBE_J["total_cost_usd"]))
prices = PROBE_J["prices_usd_per_mtok"]
for mdl, t in (("claude-opus-5-5", "Opus"), ("claude-fable-5-1", "Fable"), ("claude-sonnet-5", "Sonnet")):
    for i, c in enumerate(("In", "Read", "Write", "Out")):
        M(f"Price{t}{c}", f"{prices[mdl][i]:.2f}")
probe_rows = [
    ("Longer entry does not serve its own prefix", "Write prompt P+X, then ask for P alone", probe("a1", "P alone (bp P)", "claude-sonnet-5")),
    ("", "Ask for P alone again", probe("a1", "P alone again (bp P)", "claude-sonnet-5")),
    ("A growing conversation reuses the earlier entry", "Write P+X, then send P+X+Y", probe("a2", "P+X+Y (bp Y) extension")),
    ("Two API keys do not share", "Write with key 1, same request with key 2", probe("b", "same request with K2")),
    ("Simultaneous identical requests both pay", "Two at the same instant (each)", probe("c", "simultaneous #1 trial 0")),
    ("Reads keep an entry alive", "Read at 4 min, then again at 7 min", probe("d", "A: read t=420 (needs refresh at 240)")),
    ("", "Never read, asked again at 7 min", probe("d", "B: read t=420 (no refresh, expect miss)")),
    ("Each model has its own cache", "Written on Sonnet, then sent to Opus", probe("f", "same prefix on opus")),
    ("Sonnet caches per effort level", "Effort medium written, then no effort", probe("e2", "base adaptive (no effort)", "claude-sonnet-5")),
    ("", "Same pair on Opus", probe("e2", "base adaptive (no effort)", "claude-opus-5-5")),
]
rows = [f"{a} & {b} & {thousands(w)} & {thousands(r)} \\\\" for a, b, (w, r) in probe_rows]
write(TABLES / "probe.tex", table(r">{\raggedright\arraybackslash}p{0.3\textwidth} >{\raggedright\arraybackslash}p{0.38\textwidth} r r",
                                  [r"Question & What was sent & tokens written & tokens read \\"], rows))
w, _ = probe("a1", "P alone (bp P)", "claude-sonnet-5")
M("ProbePTokens", thousands(w))
w, r = probe("b", "same request with K2")
M("ProbeFullTokens", thousands(w))
M("ProbeYTokens", thousands(probe("a2", "P+X+Y (bp Y) extension")[0]))

# ------------------------------------------------------------ pilot & power (design doc)
pre = EV / "prereg/PREREGISTRATION-main-v1.md"
M("PilotSDFable", grab(pre, r"A/A noise SD of log ratio ([\d.]+) \(Fable\)"))
M("PilotSDOpus", grab(pre, r"and ([\d.]+) \(Opus\), centred"))
M("PilotScen", grab(pre, r"Pilot \(screen, (\d+) scenarios x 1 rep"))
M("CovLow", grab(pre, r"coverage must fall in\s+\[([\d.]+), [\d.]+\]"))
M("CovHigh", grab(pre, r"coverage must fall in\s+\[[\d.]+, ([\d.]+)\]"))
M("HTwoLower", grab(pre, r"\(CI lower bound > ([\d.]+) counts as confirmed"))
M("HThreeUpper", grab(pre, r"CI upper bound <= ([\d.]+)\),"))
power = re.findall(r"^\| (Routing, (?:Fable|Opus) \([^)]*\)) \| ([\d.]+) / ([\d.]+) \| ±(\d+)% \| ±(\d+)% \|$",
                   DESIGN.read_text(), re.M)
assert len(power) == 4, power
pw_s = re.search(r"\| S=(\d+), m=2 \| S=(\d+) \(train\), m=2 \|", DESIGN.read_text())
M("PowerSA", pw_s.group(1))
M("PowerSB", pw_s.group(2))
rows = [f"{tex_escape(n)} & {sb} & {sw} & $\\pm${a}\\,\\% & $\\pm${b}\\,\\% \\\\" for n, sb, sw, a, b in power]
write(TABLES / "power.tex", table("l r r r r", [r" & \multicolumn{2}{c}{SD of log ratio} & \multicolumn{2}{c}{95\,\% CI half-width} \\",
                                                r"\cmidrule(lr){2-3}\cmidrule(l){4-5}",
                                                r"Contrast (earlier data) & between scenarios & within & \PowerSA\ scenarios & \PowerSB\ scenarios \\"], rows))

# ------------------------------------------------------------ confirmatory


def pe(reading, host, arm):
    return CC["primary_endpoint"][reading][host][arm]


for h, H, _ in HOSTS:
    for a, A, _ in ARMS:
        for reading, R in (("pair", "Pair"), ("arm", "Arm")):
            e = pe(reading, h, a)
            M(f"Cf{H}{A}{R}", hu(e["gm_ratio"], 3))
            M(f"Cf{H}{A}{R}Two", hu(e["gm_ratio"], 2))
            M(f"Cf{H}{A}{R}CI", ci(e["ci95"], 2))
            M(f"Cf{H}{A}{R}CITwo", ci(e["ci95"], 2))
            M(f"Cf{H}{A}{R}N", e["n_pairs"])
        e = pe("pair", h, a)
        M(f"Cf{H}{A}Saving", pct(1 - e["gm_ratio"]))
        M(f"Cf{H}{A}Cents", pct(e["gm_ratio"]))
        M(f"Cf{H}{A}Extra", pct(e["gm_ratio"] - 1))
        M(f"Cf{H}{A}NValid", e["n_cost_valid"])
        q = CC["quality"][h][a]
        M(f"Q{H}{A}", hu(q["mean_delta_turn_pass"], 3))
        M(f"Q{H}{A}CI", ci(q["ci95"], 3))
        M(f"Q{H}{A}Low", hu(q["ci95"][0], 3))
        M(f"Q{H}{A}Verdict", q["verdict"])
    h3 = CC["h3_paired_ratio"]["pair"][h]
    M(f"HThree{H}", hu(h3["gm_ratio"], 3))
    M(f"HThree{H}CI", ci(h3["ci95"], 2))
    M(f"HThree{H}Upper", hu(h3["ci95"][1], 3))
    M(f"HThree{H}N", h3["n_pairs"])
    M(f"HThree{H}Saving", pct(1 - h3["gm_ratio"]))
    h3a = CC["h3_paired_ratio"]["arm"][h]
    M(f"HThree{H}Arm", hu(h3a["gm_ratio"], 3))
    M(f"HThree{H}ArmCI", ci(h3a["ci95"], 2))
for reading in ("pair", "arm"):
    for hyp in ("H1", "H2", "H3", "Quality"):
        assert CC["hypotheses"][reading][hyp]["verdict"] == "confirmed"
M("NHypConfirmed", sum(CC["hypotheses"]["pair"][k]["verdict"] == "confirmed" for k in ("H1", "H2", "H3", "Quality")))
M("NSeeds", EXP["seed_robustness"]["seeds"][1] - EXP["seed_robustness"]["seeds"][0] + 1)
M("SeedsChanged", len(EXP["seed_robustness"]["verdicts_that_changed"]))
M("SeedLo", EXP["seed_robustness"]["seeds"][0])
M("SeedHi", EXP["seed_robustness"]["seeds"][1])
M("NDeviations", len(CONF["deviations"]))
M("DecisionFable", CC["decision"]["pair"]["fable"]["recommendation"])
M("DecisionOpus", CC["decision"]["pair"]["opus"]["recommendation"].replace("do not route to Sonnet: ", "do not route to Sonnet; use the "))
mc = CC["model_check"]
o = mc["overall"]
M("MCCovLog", hu(o["coverage_log_ratio"], 3))
M("MCCovUSD", hu(o["coverage_saving_delta_model"], 3))
M("MCCovRatioModel", hu(o["coverage_saving_ratio_model"], 3))
M("MCObserved", money(o["observed_total_saving_usd"]))
M("MCPredicted", money(o["predicted_total_saving_usd"]))
M("MCPILow", money(o["predicted_total_pi90"][0]))
M("MCPIHigh", money(o["predicted_total_pi90"][1]))
M("MCSlope", hu(o["calibration_slope"], 2))
M("MCPairs", mc["n_test_pairs"])
M("MCDraws", thousands(mc["draws"]))
M("MCVerdict", mc["verdict"])
# test-mix per 1,000 check (CONFIRM.md table, parsed) and model-vs-empirical cells
ME = CONF["exploratory"]["per_1000_model"]
for key, v in mc["by_arm_host"].items():
    a, h = key.split("|")
    H, A = h.capitalize(), a.capitalize()
    M(f"TestMix{H}{A}Model", money(v["per_1000_test_mix_point"], 0))
    M(f"TestMix{H}{A}Obs", money(v["observed_test_per_1000"], 0))
    M(f"TestMix{H}{A}Lo", money(v["per_1000_test_mix_pi90"][0], 0))
    M(f"TestMix{H}{A}Hi", money(v["per_1000_test_mix_pi90"][1], 0))
    M(f"TestMix{H}{A}Inside", "yes" if v["per_1000_test_mix_pi90"][0] <= v["observed_test_per_1000"] <= v["per_1000_test_mix_pi90"][1] else "no")


def primary_table():
    rows = []
    for h, H, hn in HOSTS:
        for a, A, an in ARMS:
            rows.append(f"{hn} & {an} & \\Cf{H}{A}PairN/\\Cf{H}{A}NValid & \\Cf{H}{A}Pair & \\Cf{H}{A}PairCI & "
                        f"\\Cf{H}{A}Arm & \\Cf{H}{A}ArmCI \\\\")
        if h == "fable":
            rows.append(r"\addlinespace[3pt]")
    return table("l l r r r r r", [r" & & \multicolumn{3}{c}{Pair reading (primary)} & \multicolumn{2}{c}{Arm reading (sensitivity)} \\",
                                   r"\cmidrule(lr){3-5}\cmidrule(l){6-7}",
                                   r"Host & Arm & pairs kept & ratio & 95\,\% CI & ratio & 95\,\% CI \\"], rows)


write(TABLES / "primary.tex", primary_table())


def hyp_table():
    rows = []
    for part in CC["hypotheses"]["pair"]["H1"]["parts"]:
        H, A = part["host"].capitalize(), part["arm"].capitalize()
        rows.append(f"H1: routing is cheaper (upper end $<$ 1) & {part['host'].capitalize()} & {part['arm']} & \\Cf{H}{A}Pair & \\Cf{H}{A}PairCI & \\vconf \\\\")
    for i, part in enumerate(CC["hypotheses"]["pair"]["H2"]["parts"]):
        H, A = part["host"].capitalize(), part["arm"].capitalize()
        lab = r"H2: no saving (lower end $>$ \HTwoLower)" if i == 0 else ""
        rows.append(f"{lab} & {part['host'].capitalize()} & {part['arm']} & \\Cf{H}{A}Pair & \\Cf{H}{A}PairCI & \\vconf \\\\")
    for i, (h, H, _) in enumerate(HOSTS):
        lab = r"H3: sticky/shipped (upper end $\le$ \HThreeUpper)" if i == 0 else ""
        rows.append(f"{lab} & {H} & sticky/shipped & \\HThree{H} & \\HThree{H}CI & \\vconf \\\\")
    return table(r">{\raggedright\arraybackslash}p{0.33\textwidth} l l r r l",
                 [r"Hypothesis (test split, pair reading) & Host & Arm & ratio & 95\,\% CI & verdict \\"], rows)


write(TABLES / "hypotheses.tex", hyp_table())


def quality_table():
    rows = []
    for h, H, hn in HOSTS:
        for a, A, an in ARMS:
            v = CC["quality"][h][a]["verdict"]
            mark = r"\vconf" if v == "confirmed" else r"\textcolor{okorange}{\textsf{not confirmed}}"
            rows.append(f"{hn} & {an} & {CC['quality'][h][a]['n_pairs']} & \\Q{H}{A} & \\Q{H}{A}CI & {mark} \\\\")
    return table("l l r r r l", [r"Host & Arm & pairs & mean $\Delta$ turn-pass & 95\,\% CI & non-inferior \\"], rows)


write(TABLES / "quality.tex", quality_table())


def model_check_table():
    rows = []
    for key, v in sorted(mc["by_arm_host"].items()):
        a, h = key.split("|")
        rows.append(f"{a} / {h.capitalize()} & {v['n_pairs']} & {hu(v['coverage_log_ratio'], 3)} & {hu(v['coverage_saving_delta_model'], 3)} & "
                    f"\\${money(v['observed_total_saving_usd'])} & {money(v['predicted_total_pi90'][0])} to {money(v['predicted_total_pi90'][1])} & "
                    f"{r'\ok' if v['observed_total_in_pi'] else r'\no'} \\\\")
    return table("l r r r r r c", [r"Arm / host & pairs & coverage (log) & coverage (\$) & observed total & 90\,\% PI of total & inside \\"], rows)


write(TABLES / "model-check.tex", model_check_table())

# model check figure: predicted vs observed totals per arm/host, labelled with the placer
pts, mrows = [], []
for key, v in sorted(mc["by_arm_host"].items()):
    a, h = key.split("|")
    pred = PRED["by_arm_host"][key]["predicted_total_saving_usd"]
    assert PRED["by_arm_host"][key]["predicted_total_pi90"] == v["predicted_total_pi90"], key
    pts.append((key, f"{a}, {h.capitalize()}", pred, v["observed_total_saving_usd"]))
    mrows.append([f"{pred:.3f}", f"{pred - v['predicted_total_pi90'][0]:.3f}", f"{v['predicted_total_pi90'][1] - pred:.3f}",
                  f"{v['observed_total_saving_usd']:.3f}", "{" + h + "}"])
for h, _, _ in HOSTS:
    dat(f"model-check-{h}.dat", ["pred", "minus", "plus", "obs"], [r[:4] for r in mrows if r[4] == "{" + h + "}"])
MODEL_X, MODEL_Y = (-70.0, 150.0), (-70.0, 150.0)
LP.configure(OUT, DATA, 9.0, 7.0)
M("ModelAxisW", "9cm")
M("ModelAxisH", "7cm")
LP.place_labels("model-check", pts, MODEL_X, MODEL_Y)

# ------------------------------------------------------------ exploratory
pr = EXP["pass_rates_all_splits"]
for h, H, _ in HOSTS:
    for a, A, _ in ARMS:
        v = pr[h][a]
        M(f"Pass{H}{A}", hu(v["arm_pass_rate"], 3))
        M(f"Pass{H}{A}Anchor", hu(v["anchor_pass_rate_same_pairs"], 3))
        M(f"Pass{H}{A}AnchorOnly", v["anchor_only_pass"])
        M(f"Pass{H}{A}ArmOnly", v["arm_only_pass"])
        M(f"Pass{H}{A}P", pval(v["mcnemar_p"]))
    M(f"Pass{H}N", pr[h]["sticky"]["n_pairs"])
ps = [pr["fable"][a]["mcnemar_p"] for a, _, _ in ARMS]
M("PassFableMinP", pval(min(ps)))
M("PassFableMaxP", pval(max(ps)))
rows = []
for h, H, hn in HOSTS:
    for a, A, an in ARMS + [("aa", "AA", "second anchor (A/A)")]:
        v = pr[h][a]
        rows.append(f"{hn} & {an} & {v['n_pairs']} & {hu(v['arm_pass_rate'], 3)} & {hu(v['anchor_pass_rate_same_pairs'], 3)} & "
                    f"{v['anchor_only_pass']} / {v['arm_only_pass']} & {pval(v['mcnemar_p'])} \\\\")
    if h == "fable":
        rows.append(r"\addlinespace[3pt]")
write(TABLES / "passrates.tex", table("l l r r r r r", [r"Host & Arm & pairs & arm pass & anchor pass & anchor-only / arm-only & McNemar $p$ \\"], rows))

aa = EXP["aa_noise_all_splits"]
for k, K in (("fable", "Fable"), ("opus", "Opus"), ("all", "All")):
    v = aa[k]
    M(f"AA{K}", hu(math.exp(v["mean_log_ratio"]), 3))
    M(f"AA{K}CI", ci([math.exp(x) for x in v["mean_log_ratio_ci95"]], 2))
    M(f"AA{K}SD", hu(v["sd_log_ratio"], 2))
    M(f"AA{K}SDSession", hu(v["implied_sd_single_session"], 2))
    M(f"AA{K}N", v["n_pairs"])
    M(f"AA{K}Centred", "yes" if v["centred_on_zero"] else "no")
    M(f"AA{K}Pct", pct(abs(math.exp(v["mean_log_ratio"]) - 1), 0))
rows = []
for split, src in (("all", EXP["aa_noise_all_splits"]), ("test", EXP["aa_noise_test"])):
    for k in ("fable", "opus", "all"):
        v = src[k]
        rows.append(f"{split} & {k.capitalize() if k != 'all' else 'both'} & {v['n_pairs']} & {hu(math.exp(v['mean_log_ratio']), 3)} & "
                    f"{ci([math.exp(x) for x in v['mean_log_ratio_ci95']], 2)} & {hu(v['sd_log_ratio'], 3)} & "
                    f"{hu(v['implied_sd_single_session'], 3)} & {'yes' if v['centred_on_zero'] else 'no'} \\\\")
write(TABLES / "aa.tex", table("l l r r r r r l", [r"Split & Host & pairs & ratio & 95\,\% CI & SD (pair) & SD (session) & centred \\"], rows))

# interim vs final
ivf = EXP["interim_vs_final"]
STAGES = ["Pilot", "Interim", "Final train", "Final test", "Confirmatory"]
for h, H, _ in HOSTS:
    rows = []
    for a, A, _ in ARMS:
        vals = [ivf["interim"]["pilot"][h][a], ivf["interim"]["interim_train_partial"][h][a],
                ivf["final"]["train"][h][a]["gm_ratio"], ivf["final"]["test"][h][a]["gm_ratio"],
                pe("pair", h, a)["gm_ratio"]]
        rows.append(vals)
        M(f"Pilot{H}{A}", hu(vals[0], 2))
        M(f"Interim{H}{A}", hu(vals[1], 2))
        M(f"FinalTrain{H}{A}", hu(vals[2], 2))
        M(f"FinalTest{H}{A}", hu(vals[3], 2))
    dat(f"interim-{h}.dat", ["stage"] + [A for _, A, _ in ARMS],
        [[i] + [f"{rows[j][i]:.4f}" for j in range(len(ARMS))] for i in range(len(STAGES))])
rows = []
for h, H, hn in HOSTS:
    for a, A, an in ARMS:
        ft, fs = ivf["final"]["train"][h][a], ivf["final"]["test"][h][a]
        rows.append(f"{hn} & {an} & {hu(ivf['interim']['pilot'][h][a], 2)} & {hu(ivf['interim']['interim_train_partial'][h][a], 2)} & "
                    f"{hu(ft['gm_ratio'], 3)} ({ci(ft['ci95'], 2)}) & {hu(fs['gm_ratio'], 3)} ({ci(fs['ci95'], 2)}) & \\Cf{H}{A}Pair \\\\")
write(TABLES / "interim.tex", table("l l r r r r r", [r"Host & Arm & pilot & interim & final train (95\,\% CI) & final test (95\,\% CI) & confirmatory \\"], rows))

# savings per 1,000 sessions (empirical, all splits)
emp = {(r["host"], r["task_type"], r["arm"]): r for r in EXP["per_1000_empirical"]}
for h, H, _ in HOSTS:
    for a, A, _ in ARMS:
        r = emp[(h, "all", a)]
        M(f"Sav{H}{A}", money(r["saving_per_1000_usd"], 0))
        M(f"Sav{H}{A}Lo", money(r["range90"][0], 0))
        M(f"Sav{H}{A}Hi", money(r["range90"][1], 0))
    out = []
    order = TASKS + ["all"]
    for i, t in enumerate(reversed(order)):
        row = [i, "{" + ("all tasks" if t == "all" else t) + "}"]
        for a, _, _ in ARMS:
            r = emp[(h, t, a)]
            row += [f"{r['saving_per_1000_usd']:.2f}", f"{r['saving_per_1000_usd'] - r['range90'][0]:.2f}",
                    f"{r['range90'][1] - r['saving_per_1000_usd']:.2f}"]
        out.append(row)
    dat(f"savings-{h}.dat", ["idx", "label"] + [f"{k}{A}" for _, A, _ in ARMS for k in ("v", "m", "p")], out)
    M(f"SavMax{h.capitalize()}", math.ceil(max(emp[(h, t, a)]["range90"][1] for t in order for a, _, _ in ARMS) / 500) * 500)
    M(f"SavMin{h.capitalize()}", math.floor(min(emp[(h, t, a)]["range90"][0] for t in order for a, _, _ in ARMS) / 500) * 500)
M("SavRows", len(TASKS))
nsc = {t: emp[("fable", t, "sticky")]["n_scenarios"] for t in TASKS}
rows = []
for t in TASKS + ["all"]:
    cells_ = []
    for h, _, _ in HOSTS:
        for a, _, _ in ARMS:
            r = emp[(h, t, a)]
            cells_.append(f"{money(r['saving_per_1000_usd'], 0)}")
    lab = "all tasks" if t == "all" else t
    rows.append((r"\midrule " if t == "all" else "") + f"{lab} & {emp[('fable', t, 'sticky')]['n_scenarios']} & " + " & ".join(cells_) + r" \\")
write(TABLES / "per1000.tex", table("l r r r r r r r", [r" & & \multicolumn{3}{c}{Fable host: saving per 1,000 sessions (\$)} & \multicolumn{3}{c}{Opus host} \\",
                                                        r"\cmidrule(lr){3-5}\cmidrule(l){6-8}",
                                                        r"Task type & scenarios & sticky & shipped & sonnet & sticky & shipped & sonnet \\"], rows))
# full appendix table with ranges and the model's figure
mod = {(r["host"], r["task_type"], r["arm"]): r for r in ME}
rows = []
n_out = 0
for h, H, hn in HOSTS:
    for t in TASKS + ["all"]:
        for a, _, an in ARMS:
            e = emp[(h, t, a)]
            mkey = (h, "campaign mix" if t == "all" else t, a)
            m = mod.get(mkey)
            if m is None:
                raise SystemExit(f"model per-1000 row missing: {mkey}")
            inside = e["range90"][0] <= m["saving_usd_point"] <= e["range90"][1]
            n_out += not inside
            rows.append(f"{hn if (t == TASKS[0] and a == 'sticky') else ''} & {('all tasks' if t == 'all' else t) if a == 'sticky' else ''} & {an} & "
                        f"{money(e['saving_per_1000_usd'], 0)} & {money(e['range90'][0], 0)} to {money(e['range90'][1], 0)} & "
                        f"{money(m['saving_usd_point'], 0)} & {r'\ok' if inside else r'\no'} \\\\")
        rows.append(r"\addlinespace[2pt]")
    if h == "fable":
        rows.append(r"\midrule")
M("ModelOutside", n_out)
M("ModelCells", 2 * len(TASKS + ["all"]) * len(ARMS))
head = r"Host & Task type & Arm & measured / 1,000 & 90\,\% range & model / 1,000 & model inside \\"
lines = [r"\begin{xltabular}{\textwidth}{@{}l l l r r r c@{}}",
         r"\caption{Savings per 1,000 sessions by host, task type and arm, measured (all splits) and as predicted by the "
         r"preregistered model. Positive numbers are money saved, negative numbers money lost. Exploratory.}\label{tab:per1000full}\\",
         r"\toprule", head, r"\midrule", r"\endfirsthead",
         r"\multicolumn{7}{@{}l}{\small\emph{(continued)}}\\", r"\toprule", head, r"\midrule", r"\endhead",
         r"\bottomrule", r"\endlastfoot"] + rows[:-1] + [r"\end{xltabular}"]
write(TABLES / "per1000-full.tex", "\n".join(lines) + "\n")

# slices from model/summary.json: gap pattern and turn band
G = {(g["arm"], g["host"], g["dim"], g["value"]): g for g in SUMM["groups"]}


def slice_table(dim, values, labels):
    rows = []
    for h, H, hn in HOSTS:
        for a, A, an in ARMS:
            cells_ = []
            for v in values:
                g = G[(a, h, dim, v)]
                cells_.append(f"{hu(g['gm_cost_ratio'], 2)} ({ci(g['gm_cost_ratio_ci95'], 2)})")
            rows.append(f"{hn if a == 'sticky' else ''} & {an} & " + " & ".join(cells_) + r" \\")
        if h == "fable":
            rows.append(r"\addlinespace[3pt]")
    return table("l l " + "r " * len(values), ["Host & Arm & " + " & ".join(labels) + r" \\"], rows)


write(TABLES / "slice-gap.tex", slice_table("gap_pattern", ["no long gap", "2+ long gaps"], ["no long gap", "two long gaps"]))
write(TABLES / "slice-turns.tex", slice_table("turn_band", ["<=8", "9-12", ">=13"], [r"$\le$8 turns", "9--12 turns", r"$\ge$13 turns"]))
for h, H, _ in HOSTS:
    for a, A, _ in ARMS:
        M(f"Gap{H}{A}No", hu(G[(a, h, "gap_pattern", "no long gap")]["gm_cost_ratio"], 2))
        M(f"Gap{H}{A}Yes", hu(G[(a, h, "gap_pattern", "2+ long gaps")]["gm_cost_ratio"], 2))
        M(f"Turns{H}{A}Short", hu(G[(a, h, "turn_band", "<=8")]["gm_cost_ratio"], 2))
        M(f"Turns{H}{A}Long", hu(G[(a, h, "turn_band", ">=13")]["gm_cost_ratio"], 2))
    sh = G[("shipped", h, "overall", "all")]
    M(f"Switch{H}", hu(sh["mean_model_switches"], 2))
    M(f"SwitchShare{H}", pct(sh["share_sessions_with_switch"]))
    M(f"Rebuild{H}", pct(sh["rebuild_cost_share"]))
    st = G[("sticky", h, "overall", "all")]
    M(f"SwitchSticky{H}", hu(st["mean_model_switches"], 0))
for t in TASKS:
    M("Task" + t.capitalize() + "N", nsc[t])

# raw basis
raw = EXP["raw_basis_primary"]["pair"]
M("RawFableSticky", hu(raw["fable"]["sticky"]["gm_ratio"], 3))
M("RawOpusSticky", hu(raw["opus"]["sticky"]["gm_ratio"], 3))

# ------------------------------------------------------------ cost composition (requests + sessions)
# Per-class prices are recovered from the request rows by exact least squares (the cost field is a price table).
by_model = defaultdict(list)
for r in REQS:
    if r["cost_usd_recomputed"] is not None:
        by_model[r["model"]].append(r)


def solve4(rows_):
    # normal equations for cost = a*in + b*read + c*write + d*out (per token)
    keys = ("input", "cache_read", "cache_write", "output")
    A = [[0.0] * 4 for _ in range(4)]
    bvec = [0.0] * 4
    for r in rows_:
        x = [r["tokens"][k] for k in keys]
        for i in range(4):
            bvec[i] += x[i] * r["cost_usd_recomputed"]
            for j in range(4):
                A[i][j] += x[i] * x[j]
    # Gauss-Jordan
    for i in range(4):
        p = max(range(i, 4), key=lambda k: abs(A[k][i]))
        A[i], A[p] = A[p], A[i]
        bvec[i], bvec[p] = bvec[p], bvec[i]
        for k in range(4):
            if k != i:
                f = A[k][i] / A[i][i]
                for j in range(4):
                    A[k][j] -= f * A[i][j]
                bvec[k] -= f * bvec[i]
    return [bvec[i] / A[i][i] * 1e6 for i in range(4)]


PRICE = {m: solve4(v) for m, v in by_model.items()}
resid = max(abs(sum(p / 1e6 * r["tokens"][k] for p, k in zip(PRICE[r["model"]], ("input", "cache_read", "cache_write", "output")))
                - r["cost_usd_recomputed"]) for r in REQS if r["cost_usd_recomputed"] is not None)
assert resid < 1e-6, resid
for mdl, t in (("claude-opus-5-5", "Opus"), ("claude-fable-5-1", "Fable"), ("claude-sonnet-5", "Sonnet")):
    for i, c in enumerate(("In", "Read", "Write", "Out")):
        assert abs(PRICE[mdl][i] - prices[mdl][i]) < 1e-6, (mdl, c)  # campaign table = probe table
M("PriceResidual", "$10^{-6}$")
valid_keys = {s["session_key"] for s in SESS if s["cost_valid"]}
comp = defaultdict(lambda: [0.0] * 4)
for r in REQS:
    if r["session_key"] not in valid_keys or r["cost_usd_recomputed"] is None:
        continue
    p = PRICE[r["model"]]
    t = r["tokens"]
    c = comp[r["session_key"]]
    rep = r.get("tools_repriced_tokens") or 0.0
    c[0] += t["input"] * p[0] / 1e6
    c[1] += (t["cache_read"] + rep) * p[1] / 1e6
    c[2] += (t["cache_write"] - rep) * p[2] / 1e6
    c[3] += t["output"] * p[3] / 1e6
BARS = [("anchor", "fable", "Fable: plain host"), ("shipped", "fable", "Fable: shipped"), ("sticky", "fable", "Fable: sticky"),
        ("sonnet", "any", "Sonnet only (control)"),
        ("anchor", "opus", "Opus: plain host"), ("shipped", "opus", "Opus: shipped"), ("sticky", "opus", "Opus: sticky")]
crow, ctab = [], []
for i, (a, h, lab) in enumerate(reversed(BARS)):
    ss = [s for s in SESS if s["arm"] == a and s["host"] == h and s["cost_valid"]]
    n = len(ss)
    cls = [sum(comp[s["session_key"]][j] for s in ss) / n for j in range(4)]
    rebuild = sum(s["rebuild_usd"] for s in ss) / n
    total = sum(s["cost_usd_tools_normalized"] for s in ss) / n
    assert abs(sum(cls) - total) < 1e-6 * n + 1e-6, (a, h, sum(cls), total)
    crow.append([i, "{" + lab + "}", f"{cls[0]:.4f}", f"{cls[1]:.4f}", f"{cls[2] - rebuild:.4f}", f"{rebuild:.4f}", f"{cls[3]:.4f}", f"{total:.4f}"])
    nreq = sum(s["n_req"] for s in ss) / n
    cread = sum(sum(v["cache_read"] for v in s["tokens"].values()) for s in ss) / n
    ctab.append((lab, n, total, cls, rebuild, nreq, cread))
dat("composition.dat", ["idx", "label", "input", "read", "write", "rebuild", "output", "total"], crow)
rows = [f"{lab} & {n} & {money(tot)} & {money(cl[1])} & {money(cl[2] - rb)} & {money(rb)} & {money(cl[3])} & {hu(nr, 1)} & {hu(cr / 1e6, 2)}\\,M \\\\"
        for lab, n, tot, cl, rb, nr, cr in reversed(ctab)]
write(TABLES / "composition.tex", table("l r r r r r r r r",
                                        [r" & & & \multicolumn{4}{c}{of which (\$ per session)} & & \\",
                                         r"\cmidrule(lr){4-7}",
                                         r"Session kind & sessions & \$/session & cache read & cache write & rebuild & output & requests & tokens read \\"],
                                        rows))
comp_by = {(a, h): (tot, cl, rb, nr, cr) for (a, h, _), (_, _, tot, cl, rb, nr, cr) in zip(reversed(BARS), ctab)}
for (a, h), (tot, cl, rb, nr, cr) in comp_by.items():
    K = ("Sonnet" if a == "sonnet" else h.capitalize() + a.capitalize())
    M(f"Comp{K}Total", money(tot))
    M(f"Comp{K}Req", hu(nr, 1))
    M(f"Comp{K}Read", money(cl[1]))
    M(f"Comp{K}Write", money(cl[2]))
    M(f"Comp{K}Out", money(cl[3]))
    M(f"Comp{K}Rebuild", money(rb))
    M(f"Comp{K}ReadTok", hu(cr / 1e6, 2))
M("CompMax", math.ceil(max(r[2] for r in ctab) * 1.15))
M("ReqRatioOpusSticky", hu(comp_by[("sticky", "opus")][3] / comp_by[("anchor", "opus")][3], 2))
M("ReqRatioSonnetOpus", hu(comp_by[("sonnet", "any")][3] / comp_by[("anchor", "opus")][3], 2))
M("ReadShareOpusAnchor", pct(comp_by[("anchor", "opus")][1][1] / comp_by[("anchor", "opus")][0]))
M("WriteShareFableAnchor", pct(comp_by[("anchor", "fable")][1][2] / comp_by[("anchor", "fable")][0]))
M("SonnetOpusReadPriceX", hu(prices["claude-sonnet-5"][1] / prices["claude-opus-5-5"][1], 1))
M("SonnetOpusWritePriceX", hu(prices["claude-sonnet-5"][2] / prices["claude-opus-5-5"][2], 2))
M("SonnetFableWritePriceX", hu(prices["claude-sonnet-5"][2] / prices["claude-fable-5-1"][2], 1))

# ------------------------------------------------------------ forest plot data (test split)
frows = []
order = [("fable", "sticky"), ("fable", "shipped"), ("fable", "sonnet"), ("opus", "sticky"), ("opus", "shipped"), ("opus", "sonnet")]
for i, (h, a) in enumerate(reversed(order)):
    ep, ea = pe("pair", h, a), pe("arm", h, a)
    frows.append([i + (1 if h == "fable" else 0), "{" + f"{h.capitalize()} {a}" + "}", f"{ep['gm_ratio']:.5f}", f"{ep['gm_ratio'] - ep['ci95'][0]:.5f}",
                  f"{ep['ci95'][1] - ep['gm_ratio']:.5f}", f"{ea['gm_ratio']:.5f}", f"{ea['gm_ratio'] - ea['ci95'][0]:.5f}", f"{ea['ci95'][1] - ea['gm_ratio']:.5f}"])
dat("forest.dat", ["y", "label", "pair", "pm", "pp", "arm", "am", "ap"], frows)
hrows = []
for i, (h, H, _) in enumerate(reversed(HOSTS)):
    p, q = CC["h3_paired_ratio"]["pair"][h], CC["h3_paired_ratio"]["arm"][h]
    hrows.append([i, "{" + f"{H}: sticky/shipped" + "}", f"{p['gm_ratio']:.5f}", f"{p['gm_ratio'] - p['ci95'][0]:.5f}", f"{p['ci95'][1] - p['gm_ratio']:.5f}",
                  f"{q['gm_ratio']:.5f}", f"{q['gm_ratio'] - q['ci95'][0]:.5f}", f"{q['ci95'][1] - q['gm_ratio']:.5f}"])
dat("forest-h3.dat", ["y", "label", "pair", "pm", "pp", "arm", "am", "ap"], hrows)

# ------------------------------------------------------------ appendix: scenario list
anc = {(s["scenario_id"]): s for s in SESS if s["arm"] == "anchor" and s["host"] == "fable" and s["rep"] == 1}
famof = {sid: f for f, ids in fam.items() for sid in ids}
rows = []
for sid in sorted(anc, key=lambda k: (famof[k], k)):
    s = anc[sid]
    rows.append(f"{tex_escape(sid)} & {famof[sid]} & {s['task_type']} & {s['language']} & {s['scripted_turns']} & {s['n_long_gaps']} & {s['split']} \\\\")
head = r"Scenario & family & task type & language & turns & long gaps & split \\"
lines = [r"\begin{xltabular}{\textwidth}{@{}l l l l r r l@{}}",
         r"\caption{The \NScenarios\ scenarios, their family, task type, language, number of scripted turns, number of "
         r"long gaps and preregistered split.}\label{tab:scenarios}\\",
         r"\toprule", head, r"\midrule", r"\endfirsthead",
         r"\multicolumn{7}{@{}l}{\small\emph{(continued)}}\\", r"\toprule", head, r"\midrule", r"\endhead",
         r"\bottomrule", r"\endlastfoot"] + rows + [r"\end{xltabular}"]
write(TABLES / "scenarios.tex", "\n".join(lines) + "\n")
for f in fam:
    tr = sum(SPLIT["split"][s] == "train" for s in fam[f])
    M("Fam" + f.capitalize() + "Train", tr)
    M("Fam" + f.capitalize() + "Test", len(fam[f]) - tr)
types = defaultdict(int)
for s in anc.values():
    types[s["task_type"]] += 1
for t in TASKS:
    M("Type" + t.capitalize(), types[t])

# deviations from the preregistration, verbatim from confirm.json
def tt(text):
    parts = text.split("`")
    return "".join(r"\texttt{" + tex_escape(x).replace(r"\_", r"\_\allowbreak{}") + "}" if i % 2 else tex_escape(x)
                   for i, x in enumerate(parts))


write(TABLES / "deviations.tex", "\\begin{enumerate}[leftmargin=1.4em]\n" +
      "\n".join(r"\item " + tt(d) for d in CONF["deviations"]) + "\n\\end{enumerate}\n")

# ================================================================ review fixes (computed, not typed)
import sys as _sys
_sys.path.insert(0, str(REPO / "evals"))
import paired_confirm as PC  # the committed confirmatory estimator (numpy)
import paired_model as PM

# (B2) the shipped arm switches only between turns
shipped = [s for s in SESS if s["arm"] == "shipped"]
assert sum(s["switches_midturn"] for s in shipped) == 0
M("NShippedSessions", len(shipped))
M("ShippedMidturn", sum(s["switches_midturn"] for s in shipped))

# (R4) sticky sessions that ran Sonnet only
sticky = [s for s in SESS if s["arm"] == "sticky"]
son_only = [s for s in sticky if s["served_models"] == ["claude-sonnet-5"]]
M("NStickySessions", len(sticky))
M("NStickySonnetOnly", len(son_only))
M("NStickySonnetOnlyHost", sum(s["host"] == "fable" for s in son_only))
M("NStickyPerHost", sum(s["host"] == "fable" for s in sticky))
# the judge's own bill (not in session cost): Jev's cost per decision from the trace judge benchmark
JEV_REF = "origin/eval/judge-realistic:docs/evidence/2026-10-01-trace-judge-benchmark/holdout/summary.json"
try:
    TJ = json.loads(subprocess.run(["git", "-C", str(REPO), "show", JEV_REF], capture_output=True, text=True,
                                   check=True).stdout)
except subprocess.CalledProcessError as exc:
    raise SystemExit(f"build_assets.py: cannot read {JEV_REF}: {exc.stderr}")
jr = list(TJ["arms"]["jev-1.13"]["reps"].values())
jev_per_m = sum(r["cost"]["usd_per_1m_decisions"] for r in jr) / len(jr)
M("JevPerMillion", money(jev_per_m))
turns_mean = sum(s["scripted_turns"] for s in shipped) / len(shipped)
judge_shipped = jev_per_m * turns_mean / 1e6
fable_anchor = [s for s in SESS if s["arm"] == "anchor" and s["host"] == "fable" and s["cost_valid"]]
fa_cost = sum(s["cost_usd_tools_normalized"] for s in fable_anchor) / len(fable_anchor)
M("JudgeShippedCents", hu(judge_shipped * 100, 2))
M("JudgeShippedShare", hu(100 * judge_shipped / fa_cost, 3))

# (R7) launch stagger: seconds after the first session of the same wave started
from datetime import datetime as _dt
waves = defaultdict(list)
for s in SESS:
    waves[s["wave_id"]].append(s)
offs = defaultdict(list)
for v in waves.values():
    t0 = min(_dt.fromisoformat(x["actual_start"]) for x in v)
    for x in v:
        offs[x["arm"]].append((_dt.fromisoformat(x["actual_start"]) - t0).total_seconds())
for a, A in (("anchor", "Anchor"), ("aa", "AA"), ("shipped", "Shipped"), ("sticky", "Sticky"), ("sonnet", "Sonnet")):
    M(f"Stagger{A}", hu(sum(offs[a]) / len(offs[a]), 1))
    M(f"Stagger{A}Max", hu(max(offs[a]), 1))
aa_opus = math.exp(EXP["aa_noise_all_splits"]["opus"]["mean_log_ratio"])
M("AABiasPct", pct(aa_opus - 1))
adj = {a: pe("pair", "opus", a) for a, _, _ in ARMS}
M("OpusAdjLow", hu(min(v["gm_ratio"] for v in adj.values()) / aa_opus, 2))
M("OpusAdjHigh", hu(max(v["gm_ratio"] for v in adj.values()) / aa_opus, 2))
M("OpusAdjMinLower", hu(min(v["ci95"][0] for v in adj.values()) / aa_opus, 2))
assert min(v["ci95"][0] for v in adj.values()) / aa_opus > float(MACROS["HTwoLower"])

# (R3) the pair-level filter and the arm reading
d = [pe("pair", h, a)["gm_ratio"] - pe("arm", h, a)["gm_ratio"] for h, _, _ in HOSTS for a in ("sticky", "shipped")]
M("FilterLiftLow", hu(min(d), 2))
M("FilterLiftHigh", hu(max(d), 2))
for a, A, _ in ARMS:
    M(f"CfOpus{A}ArmExtra", pct(pe("arm", "opus", a)["gm_ratio"] - 1))

# (R2) quality of the recommended arm beyond the test split, with the committed estimator
DS = PM.load_dataset(EV / "data")
Q = [r for r in DS["pairs"] if r["quality_ok"] and r["dtp"] is not None]
rs = [r for r in Q if r["host"] == "fable" and r["arm"] == "sticky"]
est, lo, hi, nsc = PC.boot_interval([r["dtp"] for r in rs], [r["scenario"] for r in rs], PC.SEED,
                                    ("quality", "fable", "sticky"), PC.BOOT)
M("QAllFableSticky", hu(est, 3))
M("QAllFableStickyCI", f"{hu(lo, 3)} to {hu(hi, 3)}")
M("QAllFableStickyLow", hu(lo, 3))
M("QAllScen", nsc)
M("QFableStickyMarginGap", hu(CC["quality"]["fable"]["sticky"]["ci95"][0] - CONF["ni_margin"], 4))
fp = {}
for sp in ("all", "test"):
    rr = [r for r in Q if r["host"] == "fable" and r["arm"] in ("sticky", "shipped", "sonnet")
          and (sp == "all" or r["split"] == sp)]
    v = [float(r["arm_pass"]) - float(r["anchor_pass"]) for r in rr]
    fp[sp] = PC.boot_interval(v, [r["scenario"] for r in rr], PC.SEED, ("finalpass", "fable", sp), PC.BOOT)
    T = sp.capitalize()
    M(f"FinalPool{T}", hu(-100 * fp[sp][0], 1))
    M(f"FinalPool{T}CI", f"{hu(100 * fp[sp][1], 1)} to {hu(100 * fp[sp][2], 1)}")
gaps = [100 * (EXP["pass_rates_all_splits"]["fable"][a]["anchor_pass_rate_same_pairs"]
               - EXP["pass_rates_all_splits"]["fable"][a]["arm_pass_rate"]) for a, _, _ in ARMS]
M("FinalGapLow", hu(min(gaps), 1))
M("FinalGapHigh", hu(max(gaps), 1))

# (R1) Opus cache-read price: re-price recorded tokens, varying only that rate
rates_src = (REPO / "src" / "amplifier_fast_decisions" / "savings.py").read_text()
M("RatesVerified", grab(REPO / "src/amplifier_fast_decisions/savings.py", r"verified\s+#\s*(\d{4}-\d\d-\d\d)\s+against"))
assert re.search(r'"claude-opus-5-5": \(4\.0, 20\.0, 0\.20, 5\.0\)', rates_src)
OPUS = "claude-opus-5-5"


def costs_at(read_rate, normalized=True):
    c = defaultdict(float)
    for r in REQS:
        if r["cost_usd_recomputed"] is None:
            continue
        p = list(PRICE[r["model"]])
        if r["model"] == OPUS:
            p[1] = read_rate
        t = r["tokens"]
        rep_ = (r.get("tools_repriced_tokens") or 0.0) if normalized else 0.0
        c[r["session_key"]] += (t["input"] * p[0] + (t["cache_read"] + rep_) * p[1] + (t["cache_write"] - rep_) * p[2]
                                + t["output"] * p[3]) / 1e6
    return c


skey = {(s["scenario_id"], s["rep"], s["host"], s["arm"]): s["session_key"] for s in SESS}


def opus_ratio(c, arm, reading):
    ys = []
    for p in PAIRS:
        if p["host"] != "opus" or p["arm"] != arm or not p["valid"]:
            continue
        if SPLIT["split"][p["scenario_id"]] != "test":
            continue
        if reading == "pair" and not p["delta_turn_pass"] > CONF["ni_margin"]:
            continue
        a = c[skey[(p["scenario_id"], p["rep"], "any" if arm == "sonnet" else "opus", arm)]]
        b = c[skey[(p["scenario_id"], p["rep"], "opus", "anchor")]]
        ys.append(math.log(a / b))
    return math.exp(sum(ys) / len(ys))


base = costs_at(PRICE[OPUS][1])
for a, A, _ in ARMS:  # the re-pricer reproduces the confirmatory ratios at the table price
    assert abs(opus_ratio(base, a, "pair") - pe("pair", "opus", a)["gm_ratio"]) < 1e-4, a
    assert abs(opus_ratio(base, a, "arm") - pe("arm", "opus", a)["gm_ratio"]) < 1e-4, a
GRID = [0.20, 0.25, 0.30, 0.35, 0.40]
brows = []
for rate in GRID:
    c = costs_at(rate)
    vals = [opus_ratio(c, a, rd) for rd in ("pair", "arm") for a, _, _ in ARMS]
    brows.append(f"\\${rate:.2f}" + ("" if rate != GRID[0] else " (table)") + " & " +
                 " & ".join(hu(v, 2) for v in vals) + r" \\")
write(TABLES / "breakeven.tex", table("l r r r r r r", [
    r" & \multicolumn{3}{c}{Pair reading (primary)} & \multicolumn{3}{c}{Arm reading} \\",
    r"\cmidrule(lr){2-4}\cmidrule(l){5-7}",
    r"Opus cache-read price (per M) & sticky & shipped & sonnet & sticky & shipped & sonnet \\"], brows))


def breakeven(arm, reading, normalized=True):
    lo_, hi_ = PRICE[OPUS][1], 2.0
    for _ in range(40):
        mid = (lo_ + hi_) / 2
        if opus_ratio(costs_at(mid, normalized), arm, reading) > 1:
            lo_ = mid
        else:
            hi_ = mid
    return (lo_ + hi_) / 2


for a, A, _ in ARMS:
    for rd, R in (("pair", "Pair"), ("arm", "Arm")):
        M(f"BE{A}{R}", hu(breakeven(a, rd), 2))
for rate, T in ((0.30, "Thirty"), (0.35, "ThirtyFive"), (0.40, "Forty")):
    M(f"Rate{T}", f"{rate:.2f}")
    c = costs_at(rate)
    M(f"BESticky{T}", hu(opus_ratio(c, "sticky", "pair"), 2))
    craw = costs_at(rate, normalized=False)
    for a, A, _ in ARMS:
        M(f"BERaw{A}{T}", hu(opus_ratio(craw, a, "arm"), 2))
M("BEReadMultiple", hu(float(MACROS["BEStickyPair"]) / PRICE[OPUS][1], 2))

# (B3) the estimator was written after data collection
ci_time = subprocess.run(["git", "-C", str(REPO), "log", "--diff-filter=A", "--format=%cI", "--",
                          "evals/paired_confirm.py"], capture_output=True, text=True, check=True).stdout.split()[-1]
ci_sha = subprocess.run(["git", "-C", str(REPO), "log", "--diff-filter=A", "--format=%h", "--",
                         "evals/paired_confirm.py"], capture_output=True, text=True, check=True).stdout.split()[-1]
M("ConfirmSha", ci_sha[:7])
done = _dt.fromisoformat("2026-10-02T" + grab(EV / "campaign/supervisor.log", r"(\d\d:\d\d:\d\d) EDT 2026 campaign complete") + "-04:00")
M("ConfirmAfterMin", round((_dt.fromisoformat(ci_time) - done).total_seconds() / 60))
assert _dt.fromisoformat(ci_time) > done
M("DesignCovLow", grab(DESIGN, r"PI coverage between ([\d.]+) and [\d.]+;"))
M("DesignCovHigh", grab(DESIGN, r"PI coverage between [\d.]+ and ([\d.]+);"))
M("DesignSlopeLow", grab(DESIGN, r"calibration slope of predicted vs measured .{1,3} between ([\d.]+) and"))
M("DesignSlopeHigh", grab(DESIGN, r"calibration slope of predicted vs measured .{1,3} between [\d.]+ and (\d+\.\d+)"))
assert float(MACROS["DesignCovLow"]) <= o["coverage_log_ratio"] <= float(MACROS["DesignCovHigh"])
assert float(MACROS["DesignSlopeLow"]) <= o["calibration_slope"] <= float(MACROS["DesignSlopeHigh"])

# (R8) the pooled total nets Fable gains against Opus losses
fab = sum(v["observed_total_saving_usd"] for k, v in mc["by_arm_host"].items() if k.endswith("|fable"))
opu = sum(v["observed_total_saving_usd"] for k, v in mc["by_arm_host"].items() if k.endswith("|opus"))
M("MCFableTotal", money(fab))
M("MCOpusTotal", money(-opu))
M("MCNominal", "0.90")

# (R9) the survey's receipts subset
rc = SURVEY["headline"]["receipts"]["S3-v4 jev-prepared vs plain-matched"]
M("SurveyRcptPairs", rc["pairs"])
M("SurveyRcptClaimed", money(rc["sum_usd_saved_receipts"]))
M("SurveyRcptMeasured", money(rc["sum_measured_saving_usd"]))


# ================================================================ Part I extras: the four bundle defects (PR #58)
PR58 = 58  # PR number (stated by the maintainer; not recorded in the evidence)
M("PRFixNumber", PR58)
fixes = []
for sha in ("a15c439", "1f3b0e4"):
    out = subprocess.run(["git", "-C", str(REPO), "show", "-s", "--format=%h|%cI|%s", sha], capture_output=True,
                         text=True, check=True).stdout.strip().split("|")
    fixes.append(out)
M("PRFixSha", fixes[0][0])
M("PRFixReviewSha", fixes[1][0])
M("PRFixDate", fixes[0][1][:10])
msg = subprocess.run(["git", "-C", str(REPO), "show", "-s", "--format=%B", "1f3b0e4"], capture_output=True, text=True,
                     check=True).stdout
M("PRFixTaskBudget", grab(Path("1f3b0e4"), r"keeps the old (\d+)-char budget", text=msg))
stat = subprocess.run(["git", "-C", str(REPO), "show", "--shortstat", "--format=", "a15c439"], capture_output=True,
                      text=True, check=True).stdout
M("PRFixFiles", grab(Path("a15c439"), r"(\d+) files changed", text=stat))
M("PRFixTests", len(re.findall(r"tests/test_\w+\.py", subprocess.run(
    ["git", "-C", str(REPO), "show", "--stat", "--format=", "a15c439"], capture_output=True, text=True, check=True).stdout)))
M("JRSha", JR_SHA)


# ================================================================ Part II figures: caching survey and probe
CSV = json.loads((JR_SRC / "docs/evidence/2026-10-01-caching/results.json").read_text())
cc_cells = CSV["headline"]["corrections"]["same_cell_length_contrast"]["cells"]
crow = []
for i, (cell, lab) in enumerate((("plain-sonnet vs plain-opus", "Sonnet instead of Opus (no switch)"),
                                  ("orch-default vs plain", "Routed, Fable host"),
                                  ("orch-default-opus vs plain-opus", "Routed, Opus host"))):
    one, four = cc_cells[cell]["S1-single"]["cost"], cc_cells[cell]["S1-multi"]["cost"]
    crow.append([i, "{" + lab + "}", f"{one['geomean']:.4f}", f"{one['geomean'] - one['ci95'][0]:.4f}",
                 f"{one['ci95'][1] - one['geomean']:.4f}", f"{four['geomean']:.4f}",
                 f"{four['geomean'] - four['ci95'][0]:.4f}", f"{four['ci95'][1] - four['geomean']:.4f}"])
dat("survey-samecell.dat", ["y", "label", "one", "om", "op", "four", "fm", "fp"], crow)
pv = CSV["headline"]["corrections"]["price_volume_plain_sonnet_vs_plain_opus"]
dat("survey-pricevolume.dat", ["x", "label", "price", "volume", "total"],
    [[i, "{" + lab + "}", f"{pv[k]['price_factor_identical_tokens_pooled']:.4f}",
      f"{pv[k]['volume_factor_geomean']['geomean']:.4f}", f"{pv[k]['cost_ratio']['geomean']:.4f}"]
     for i, (k, lab) in enumerate((("S1-single", "single-turn"), ("S1-multi", "4-turn")))])
prow = []
for i, (q, what, (w, r)) in enumerate(probe_rows):
    prow.append([i, f"{w / 1000:.3f}", f"{r / 1000:.3f}"])
dat("probe.dat", ["idx", "written", "read"], prow)
M("ProbeRows", len(probe_rows) - 1)
write(TABLES / "probe-ticks.tex", ",".join("{" + f"P{i + 1}" + "}" for i in range(len(probe_rows))) + "\n")
write(TABLES / "probe-key.tex", "; ".join(f"\\textbf{{P{i + 1}}} {tex_escape(what)}" for i, (q, what, _) in enumerate(probe_rows)) + ".\n")


# ================================================================ Part III additions
import statistics as _st

# (D) power curves from step0_variance.json: 95% half-width of the ratio vs number of scenarios (m = 2 reps)
STEP0 = json.loads((REPO / "docs/design/pilot-20261001/step0_variance.json").read_text())
pcells = [c for c in STEP0["per_cell"] if c["cell"] in ("orch-default", "orch-default-opus")]
M("PowerPairs", thousands(STEP0["n_pairs_used"]))
prows, pnames = [], []
SGRID = list(range(10, 101, 5))
for c in pcells:
    pnames.append(f"{'Fable' if c['host'] == 'fable' else 'Opus'}, {'1-turn' if c['suite'] == 'S1' else '4-turn'}")
for S in SGRID:
    row = [S]
    for c in pcells:
        hw = 1.96 * math.sqrt(c["sigma_between"] ** 2 / S + c["sigma_within"] ** 2 / (2 * S))
        row.append(f"{100 * (math.exp(hw) - 1):.3f}")
    prows.append(row)
dat("power-curve.dat", ["S"] + [f"c{i}" for i in range(len(pcells))], prows)
write(TABLES / "power-legend.tex", "\n".join(f"\\addlegendentry{{{n}}}" for n in pnames) + "\n")
for c, n in zip(pcells, ("PowFableOne", "PowFableFour", "PowOpusOne", "PowOpusFour")):
    pass
for c in pcells:
    key = ("Fable" if c["host"] == "fable" else "Opus") + ("One" if c["suite"] == "S1" else "Four")
    M(f"Pow{key}SB", hu(c["sigma_between"], 2))
    M(f"Pow{key}SW", hu(c["sigma_within"], 2))
    M(f"Pow{key}ICC", hu(c["icc"], 2))

# (D) pilot-2 ratios against the final all-split ratios
PP = jsonl(EV / "pilot/pairs.jsonl")
plrows = []
order_ = [("fable", "sticky"), ("fable", "shipped"), ("fable", "sonnet"), ("fable", "aa"),
          ("opus", "sticky"), ("opus", "shipped"), ("opus", "sonnet"), ("opus", "aa")]
for i, (h, a_) in enumerate(reversed(order_)):
    ys = [p_["log_cost_ratio"] for p_ in PP if p_["host"] == h and p_["arm"] == a_ and p_["valid"]]
    g = G[(a_, h, "overall", "all")]
    plrows.append([i + (1 if h == "fable" else 0), "{" + f"{h.capitalize()} {'A/A' if a_ == 'aa' else a_}" + "}",
                   f"{math.exp(sum(ys) / len(ys)):.4f}", f"{g['gm_cost_ratio']:.4f}",
                   f"{g['gm_cost_ratio'] - g['gm_cost_ratio_ci95'][0]:.4f}", f"{g['gm_cost_ratio_ci95'][1] - g['gm_cost_ratio']:.4f}", len(ys)])
dat("pilot.dat", ["y", "label", "pilot", "final", "fm", "fp", "n"], plrows)
M("PilotPairs", len(PP))
M("PilotScenariosN", len({p_["scenario_id"] for p_ in PP}))

# (E) campaign progress: sessions finishing over time, spend, failure times
from datetime import timezone as _tz
t0 = min(_dt.fromisoformat(x["actual_start"]) for x in SESS)
fin = sorted((_dt.fromisoformat(x["actual_start"]) + __import__("datetime").timedelta(milliseconds=x["wall_ms"] or 0),
              x["cost_usd_provider"]) for x in SESS)
grow, cum, cs = [], 0, 0.0
for t, c_ in fin:
    cum += 1
    cs += c_
    grow.append([f"{(t - t0).total_seconds() / 3600:.3f}", cum, f"{cs:.2f}"])
dat("progress.dat", ["h", "sessions", "spend"], grow)
M("ProgressHours", hu((fin[-1][0] - t0).total_seconds() / 3600, 1))
ftimes = re.findall(r"^\| [a-z0-9-]+-r\d-(?:opus|fable) \| \d+ \| [a-z_>-]+ \| \d+ \| (\S+) \| ([a-z_]+) \|",
                     (EV / "campaign/FAILURES.md").read_text(), re.M)
assert len(ftimes) == int(MACROS["NFailed"])
frows = []
for ts, cause in ftimes:
    h_ = (_dt.fromisoformat(ts) - t0).total_seconds() / 3600
    frows.append([f"{h_:.3f}", {"forge_session_cap": 0, "forge_daemon_restart": 1, "mac_sleep": 2}[cause]])
dat("failures-time.dat", ["h", "cause"], frows)
hours = math.ceil((fin[-1][0] - t0).total_seconds() / 3600)
thr = [0] * hours
for t, _ in fin:
    thr[min(int((t - t0).total_seconds() // 3600), hours - 1)] += 1
dat("throughput.dat", ["h", "n"], [[i + 0.5, n] for i, n in enumerate(thr)])
M("ThroughputMax", max(thr))
M("ProgressMaxH", hours)

# (F) explorations from turns.jsonl
TURNS = jsonl(EV / "data/turns.jsonl")
valid = {x["session_key"] for x in SESS if x["cost_valid"]}
TV = [t for t in TURNS if t["session_key"] in valid and not t["skipped"]]
# F1 cost per turn by turn index, per arm and host
cpt = defaultdict(list)
for t in TV:
    cpt[(t["host"], t["arm"], t["turn_index"])].append(t["cost_usd_tools_normalized"])
for h in ("fable", "opus"):
    rows_ = []
    for k in range(1, 17):
        row = [k]
        for a_ in ("anchor", "shipped", "sticky"):
            v = cpt.get((h, a_, k), [])
            row.append(f"{_st.mean(v):.4f}" if v else "nan")
        v = cpt.get(("any", "sonnet", k), [])
        row.append(f"{_st.mean(v):.4f}" if v else "nan")
        rows_.append(row)
    dat(f"perturn-{h}.dat", ["turn", "anchor", "shipped", "sticky", "sonnet"], rows_)
M("TurnOneShareFable", pct(_st.mean(cpt[("fable", "anchor", 1)]) / (sum(x["cost_usd_tools_normalized"] for x in SESS if x["arm"] == "anchor" and x["host"] == "fable" and x["cost_valid"]) / 140)))
M("PerTurnN", sum(1 for t in TV))
# F2 composition by turn index (anchor sessions), dollars per class
for h, mdl in (("fable", "claude-fable-5-1"), ("opus", "claude-opus-5-5")):
    pr_ = PRICE[mdl]
    rows_ = []
    for k in range(1, 17):
        ts_ = [t for t in TV if t["host"] == h and t["arm"] == "anchor" and t["turn_index"] == k]
        if not ts_:
            continue
        cls = [_st.mean(t["tokens"][c] for t in ts_) * pr_[i] / 1e6
               for i, c in enumerate(("input", "cache_read", "cache_write", "output"))]
        rows_.append([k] + [f"{v:.4f}" for v in cls] + [len(ts_)])
    dat(f"turncomp-{h}.dat", ["turn", "input", "read", "write", "output", "n"], rows_)
# F3 first-request cache writes after a long gap vs a short gap
LG = int(MACROS["LongGapS"])
grows = []
gm_ = {}
for i, (h, a_, lab) in enumerate((("fable", "anchor", "Fable plain"), ("fable", "sticky", "Fable sticky"),
                                   ("opus", "anchor", "Opus plain"), ("opus", "sticky", "Opus sticky"),
                                   ("any", "sonnet", "Sonnet"))):
    sh_ = [t["first_req_cache_write"] for t in TV if t["host"] == h and t["arm"] == a_ and t["turn_index"] > 1
           and t["gap_before_s"] < LG and t["first_req_cache_write"] is not None]
    lo_ = [t["first_req_cache_write"] for t in TV if t["host"] == h and t["arm"] == a_ and t["gap_before_s"] >= LG
           and t["first_req_cache_write"] is not None]
    gm_[lab] = (_st.mean(sh_), _st.mean(lo_))
    grows.append([i, "{" + lab + "}", f"{_st.mean(sh_) / 1000:.3f}", f"{_st.mean(lo_) / 1000:.3f}", len(sh_), len(lo_)])
dat("gapwrites.dat", ["idx", "label", "short", "long", "nshort", "nlong"], grows)
M("GapWriteFableShort", thousands(gm_["Fable plain"][0]))
M("GapWriteFableLong", thousands(gm_["Fable plain"][1]))
M("GapWriteFableX", hu(gm_["Fable plain"][1] / gm_["Fable plain"][0], 1))
M("GapWriteOpusX", hu(gm_["Opus plain"][1] / gm_["Opus plain"][0], 1))
M("GapNLong", sum(r[5] for r in grows))
# F4 switch timing for the shipped arm
sw = defaultdict(int)
for t in TV:
    if t["arm"] == "shipped" and t["switched_in"]:
        sw[(t["host"], t["turn_index"])] += 1
dat("switch-timing.dat", ["turn", "fable", "opus"], [[k, sw[("fable", k)], sw[("opus", k)]] for k in range(2, 17)])
tot_sw = sum(sw.values())
M("SwitchTotal", tot_sw)
M("SwitchTurnTwoPct", pct((sw[("fable", 2)] + sw[("opus", 2)]) / tot_sw))
shp = [x for x in SESS if x["arm"] == "shipped" and x["cost_valid"]]
M("RebuildPerSwitchCents", hu(100 * sum(x["rebuild_usd"] for x in shp) / sum(x["model_switches"] for x in shp), 1))
# F5 scenario-level scatter: Fable host, mean anchor cost vs mean saving of sticky
sc = defaultdict(lambda: [[], []])
for p_ in PAIRS:
    if p_["host"] == "fable" and p_["arm"] == "sticky" and p_["valid"]:
        sc[p_["scenario_id"]][0].append(p_["anchor_cost_usd"])
        sc[p_["scenario_id"]][1].append(-p_["delta_usd"])
spts = sorted((sid, _st.mean(v[0]), _st.mean(v[1])) for sid, v in sc.items())
dat("scenario-scatter.dat", ["anchor", "saving"], [[f"{a:.4f}", f"{b:.4f}"] for _, a, b in spts])
by_save = sorted(spts, key=lambda r: r[2])
lab_ids = {by_save[0][0], by_save[1][0], by_save[2][0]}  # the three scenarios where sticky cost the most extra
lab_pts = [(sid, sid, a, b) for sid, a, b in spts if sid in lab_ids]
ext = [(a, b) for sid, a, b in spts if sid not in lab_ids]
SC_X = (0, math.ceil(max(r[1] for r in spts) * 1.1))
SC_Y = (math.floor(min(r[2] for r in spts) - 1), math.ceil(max(r[2] for r in spts) + 1))
for k_, v_ in (("ScXMax", SC_X[1]), ("ScYMin", SC_Y[0]), ("ScYMax", SC_Y[1])):
    M(k_, v_)
LP.configure(OUT, DATA, 13.0, 7.0)
M("ScAxisW", "13cm")
M("ScAxisH", "7cm")
LP.place_labels("scenario-scatter", lab_pts, SC_X, SC_Y, extra=ext)
write(DATA / "labels-scenario-scatter-markers.tsv",
      "x\ty\n" + "".join(f"{a:.4f}\t{b:.4f}\n" for _, a, b in spts))
M("ScNegative", sum(1 for r in spts if r[2] < 0))
M("ScN", len(spts))
# F6 A/A histogram of log ratios
aa_ = [(p_["host"], p_["log_cost_ratio"]) for p_ in PAIRS if p_["arm"] == "aa" and p_["valid"]]
edges = [round(-0.3 + 0.05 * i, 2) for i in range(13)]
hrows = []
for lo_e, hi_e in zip(edges[:-1], edges[1:]):
    hrows.append([f"{(lo_e + hi_e) / 2:.3f}", sum(1 for h, y in aa_ if h == "fable" and lo_e <= y < hi_e),
                  sum(1 for h, y in aa_ if h == "opus" and lo_e <= y < hi_e)])
assert sum(r[1] + r[2] for r in hrows) == len(aa_), "A/A values outside histogram range"
dat("aa-hist.dat", ["mid", "fable", "opus"], hrows)
# F7 quality per arm and family
famof_ = {sid: f for f, ids in fam.items() for sid in ids}
qrows = []
for f in fam:
    cells_ = []
    for h, _, _ in HOSTS:
        for a_ in ("sticky", "shipped", "sonnet"):
            ps_ = [p_ for p_ in PAIRS if p_["host"] == h and p_["arm"] == a_ and famof_[p_["scenario_id"]] == f
                   and p_["delta_turn_pass"] is not None]
            cells_.append(hu(_st.mean(p_["delta_turn_pass"] for p_ in ps_), 3))
    qrows.append(f"{f} & {len(fam[f])} & " + " & ".join(cells_) + r" \\")
write(TABLES / "quality-family.tex", table("l r r r r r r r", [
    r" & & \multicolumn{3}{c}{Fable host} & \multicolumn{3}{c}{Opus host} \\",
    r"\cmidrule(lr){3-5}\cmidrule(l){6-8}",
    r"Family & scenarios & sticky & shipped & sonnet & sticky & shipped & sonnet \\"], qrows))
# F8 requests per session (box-plot quantiles)
def q_(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p
    f_ = math.floor(k)
    return v[f_] + (v[min(f_ + 1, len(v) - 1)] - v[f_]) * (k - f_)
brow = []
blabels = []
for i, (a_, h, lab) in enumerate(reversed(BARS)):
    v = [x["n_req"] for x in SESS if x["arm"] == a_ and x["host"] == h and x["cost_valid"]]
    brow.append(f"\\addplot+[boxplot prepared={{lower whisker={q_(v, .05):.1f}, lower quartile={q_(v, .25):.1f}, "
                f"median={q_(v, .5):.1f}, upper quartile={q_(v, .75):.1f}, upper whisker={q_(v, .95):.1f}}}, "
                f"color={'okblue' if 'Fable' in lab else ('okorange' if 'Opus' in lab else 'okgreen')}] coordinates {{}};")
    blabels.append("{" + lab + "}")
write(TABLES / "requests-box.tex", "\n".join(brow) + "\n")
M("ReqBoxLabels", ",".join(blabels))
M("ReqBoxN", len(brow))
# F9 ratio by turn band (all splits)
trows = []
for i, (h, a_) in enumerate((("fable", "sticky"), ("fable", "shipped"), ("opus", "sticky"), ("opus", "shipped"))):
    for j, band in enumerate(("<=8", "9-12", ">=13")):
        g = G[(a_, h, "turn_band", band)]
        trows.append([f"{j + 1 + (i % 2) * 0.12 - 0.06:.2f}", h, a_, f"{g['gm_cost_ratio']:.4f}",
                      f"{g['gm_cost_ratio'] - g['gm_cost_ratio_ci95'][0]:.4f}", f"{g['gm_cost_ratio_ci95'][1] - g['gm_cost_ratio']:.4f}"])
for h in ("fable", "opus"):
    for a_ in ("sticky", "shipped"):
        dat(f"band-{h}-{a_}.dat", ["x", "r", "m", "p"], [[r[0], r[3], r[4], r[5]] for r in trows if r[1] == h and r[2] == a_])


# ================================================================ G: Cloudflare Clef judges (optional)
# Read only if the evidence directory exists (override with CLEF_EVIDENCE=<dir>); otherwise render nothing.
import os as _os
CLEF = Path(_os.environ.get("CLEF_EVIDENCE", str(HERE.parents[3] / "fd-judge-realistic" / "docs" / "evidence" / "2026-10-04-clef-judges")))
clef_tex = ""
rows_, splits_ = [], []
if CLEF.is_dir():
    rows_, splits_ = [], []
    for sp in ("dev", "holdout"):
        f = CLEF / sp / "summary.json"
        if not f.exists():
            continue
        js = json.loads(f.read_text())
        pol = js.get("primary_policy", "bundle-read-shortcut")
        for arm, v in sorted(js["arms"].items()):
            mv = v["policies"][pol]["across_reps"]["majority_vote"]
            n = js["n_cases"]
            rows_.append(f"{sp} & {tex_escape(arm)} & {mv['correct']}/{n} & {mv['automatic_errors']} & {mv['automatic']} \\\\")
        splits_.append(sp)
    if not rows_:
        print(f"build_assets.py: note: {CLEF} has no dev/ or holdout/ summary.json yet; Clef subsection omitted")
if CLEF.is_dir() and rows_:
    write(TABLES / "clef.tex", table("l l r r r", [r"Split & Judge & correct & wrong automatic & automatic \\"], rows_))
    clef_tex = (r"\subsection{Cloudflare Clef judges}\label{sec:clef}" "\n"
                f"The same judge-benchmark splits ({', '.join(splits_)}) were later run with Cloudflare Clef judges, "
                r"scored under the bundle's gate (majority over repetitions). Evidence: \path{" + tex_escape(CLEF.name) + "}.\n"
                r"\begin{table}[htbp]\centering\small\caption{Cloudflare Clef judges on the judge-benchmark splits.}"
                r"\label{tab:clef}\input{generated/tables/clef.tex}\end{table}" "\n")
write(OUT / "clef-section.tex", clef_tex)

# ------------------------------------------------------------ numbers.tex
header = ("% Generated by build_assets.py from docs/evidence/2026-10-02-paired-campaign/ and the files listed there. "
          f"Do not edit.\n% {len(MACROS)} macros.\n")
write(OUT / "numbers.tex", header + "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in sorted(MACROS.items())))
print(f"wrote {len(MACROS)} macros, {len(list(TABLES.glob('*.tex')))} tables, {len(list(DATA.glob('*.dat')))} data files")
