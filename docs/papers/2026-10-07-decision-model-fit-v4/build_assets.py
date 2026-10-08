#!/usr/bin/env python3
"""Generate every number, table and plot datum used by the paired-measurement report.

Reads only committed files, and committed refs and history read with `git` (`git show`, `git archive`, `git log`):
    docs/evidence/2026-10-02-paired-campaign/   (the campaign evidence package)
    docs/evidence/2026-10-05-effort-control/    (the effort-control follow-up)
    commit 94bb7b58ab75: judge-benchmark, trace-benchmark, caching-survey and Clef evidence (jb_import.py, `git show`)
    docs/design/parallel-measurement-mode.md    (design v2: power table)
    docs/design/pilot-20261001/                 (cache-semantics probe)
    evals/paired/                               (memory-safety README, design yaml, scenario directories)
    94bb7b58ab75:docs/evidence/2026-10-01-caching/results.json  (the earlier caching survey;
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
EVIDENCE_PIN = "94bb7b58ab75b71ce095a4eda9c19822765e7b55"  # recorded commit: every git-read input is pinned here, not to a moving branch
SURVEY_REF = f"{EVIDENCE_PIN}:docs/evidence/2026-10-01-caching/results.json"
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
    if s.startswith("-") and Decimal(s) == 0:
        s = s[1:]
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




# ---- no file paths in either PDF: describe file names in prose (scenario prompts, deviations, imported tables)
_EXT = {"py": "a Python file", "md": "a Markdown file", "json": "a JSON record", "jsonl": "a JSON-lines log",
        "yaml": "a YAML file", "yml": "a YAML file", "csv": "a CSV table", "tex": "a TeX file", "dat": "a data file"}


_PHRASES = [  # exact rewrites first, so sentences read naturally
    (r"dev/run.json and holdout/run.json", "the dev and holdout run records"),
    (r"`paired_model.py` (PREREG constant) and `MODEL.md`", "the savings-model script (its PREREG constant) and the model description"),
    (r"paired\_model.py (PREREG constant) and MODEL.md", "the savings-model script (its PREREG constant) and the model description"),
    (r"paired_model.py (PREREG constant) and MODEL.md", "the savings-model script (its PREREG constant) and the model description"),
    (r"the existing model.json", "the existing fitted model"),
    (r"from changes.json,", "from the change log,"),
    (r"changes.json", "the change log"),
]


def nopath(s: str) -> str:
    """Replace file names and paths (anything ending in a known extension) by a plain description,
    consuming a preceding determiner so the sentence keeps one article."""
    for a, b in _PHRASES:
        s = s.replace(a, b)
    s = re.sub(r"\\(?:texttt|code|path)\{([^{}]*\.(?:py|md|jsonl|json|yaml|yml|csv|tex|dat))\}", r"\1", s)
    return re.sub(r"(?:\b(?:[Tt]he|[Ii]ts|[Aa]n?)\s+)?(?<![\w])\.?[\w./\\-]*?[\w-]+(?:\\_[\w-]*)*\.(py|md|jsonl|json|yaml|yml|csv|tex|dat)\b(?!\()",
                  lambda m: _EXT[m.group(1)], s)

# ------------------------------------------------------------------ inputs

# Part I sources: the judge-benchmark paper's own build, run on evidence extracted from its branch
JR_SRC, JR_SHA = jb_import.run(REPO, OUT)
for _f in (OUT / "jb" / "tables").glob("*.tex"):
    _t = _f.read_text()
    _n = nopath(_t)
    if _n != _t:
        _f.write_text(_n)

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
            M(f"Cf{H}{A}{R}CIThree", ci(e["ci95"], 3))
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
    M(f"HThree{H}ArmSaving", pct(1 - h3a["gm_ratio"]))
    M(f"HThree{H}ArmN", h3a["n_pairs"])
    M(f"HThree{H}ArmTwo", hu(h3a["gm_ratio"], 2))
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
    return table("l l r r r r r", [r" & & \multicolumn{3}{c}{Pair reading (co-primary)} & \multicolumn{2}{c}{Arm reading (co-primary, unfiltered)} \\",
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
      "\n".join(r"\item " + nopath(tt(d)) + (r" [This report treats both readings as co-primary.]" if i == 2 else "")
                for i, d in enumerate(CONF["deviations"])) + "\n\\end{enumerate}\n")

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
JEV_REF = f"{EVIDENCE_PIN}:docs/evidence/2026-10-01-trace-judge-benchmark/holdout/summary.json"
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
    r" & \multicolumn{3}{c}{Pair reading (co-primary)} & \multicolumn{3}{c}{Arm reading (co-primary, unfiltered)} \\",
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


# ================================================================ Cloudflare Clef and Clef-Flash (post hoc arms)
# Committed at EVIDENCE_PIN; read with `git show` so a clean clone builds.
CLEF_REF = f"{EVIDENCE_PIN}:docs/evidence/2026-10-04-clef-judges"
JB_REF = f"{EVIDENCE_PIN}:docs/evidence/2026-09-30-judge-benchmark"


def gshow(path):
    try:
        return subprocess.run(["git", "-C", str(REPO), "show", path], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"build_assets.py: cannot read {path}: {exc.stderr}")


def wil(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def nr(v, q):
    v = sorted(v)
    return v[max(0, math.ceil(q * len(v)) - 1)]


CSPLITS = [("dev", "Dev"), ("holdout", "Hold"), ("trace-dev", "TrDev"), ("trace-holdout", "TrHold")]
CARMS = [("clef", "Clef", "Clef"), ("clef-flash", "Flash", "Clef-Flash"), ("jev-1.13", "Jev", "Jev 1.13 (in-run)")]
CL = {}
for sp, _ in CSPLITS:
    d = {"summary": json.loads(gshow(f"{CLEF_REF}/{sp}/summary.json")),
         "run": json.loads(gshow(f"{CLEF_REF}/{sp}/run.json")),
         "requests": [json.loads(x) for x in gshow(f"{CLEF_REF}/{sp}/requests.jsonl").splitlines() if x.strip()]}
    if sp.startswith("trace"):
        d["rule2"] = json.loads(gshow(f"{CLEF_REF}/{sp}/rule2_useful.json"))
    CL[sp] = d
M("ClefPosthocSplits", sum(1 for sp, _ in CSPLITS if CL[sp]["run"].get("posthoc")))
CM = {}
tot_req = defaultdict(int)
tot_slow = defaultdict(int)
for sp, S_ in CSPLITS:
    sm = CL[sp]["summary"]
    n = sm["n_cases"]
    M(f"Cl{S_}N", n)
    for a, A, _ in CARMS:
        mv_ = sm["arms"][a]["policies"][sm["primary_policy"]]["across_reps"]["majority_vote"]
        rq = [r for r in CL[sp]["requests"] if r["arm"] == a]
        el = [r["elapsed_ms"] for r in rq if r["valid"]]
        cost = sm["arms"][a]["reps"]["1"]["cost"]["usd_per_1m_decisions"]
        m_ = {"n": n, "acc": mv_["correct"], "accci": mv_["ci95"], "wa": mv_["automatic_errors"],
              "waci": mv_["wrong_automatic_rate"]["ci95"], "cov": mv_["automatic"], "covci": mv_["coverage"]["ci95"],
              "p50": nr(el, .5), "p95": nr(el, .95), "cost": cost, "req": len(rq), "slow": sum(1 for x in el if x > 3000),
              "inv": sum(1 for r in rq if not r["valid"])}
        CM[(sp, a)] = m_
        tot_req[a] += len(rq)
        tot_slow[a] += m_["slow"]
        M(f"Cl{S_}{A}Acc", m_["acc"])
        M(f"Cl{S_}{A}AccPct", hu(100 * m_["acc"] / n, 1))
        M(f"Cl{S_}{A}AccCI", f"{hu(100 * m_['accci'][0], 0)}--{hu(100 * m_['accci'][1], 0)}\\,\\%")
        M(f"Cl{S_}{A}Wa", m_["wa"])
        M(f"Cl{S_}{A}Cov", m_["cov"])
        M(f"Cl{S_}{A}Pfifty", f"{m_['p50']:.0f}")
        M(f"Cl{S_}{A}Pninetyfive", f"{m_['p95']:.0f}")
        M(f"Cl{S_}{A}Cost", hu(cost, 1))
for a, A, _ in CARMS:
    M(f"Cl{A}Requests", thousands(tot_req[a]))
    M(f"Cl{A}Slow", tot_slow[a])
    p95s = [CM[(sp, a)]["p95"] for sp, _ in CSPLITS]
    M(f"Cl{A}PninetyfiveLow", f"{min(p95s):.0f}")
    M(f"Cl{A}PninetyfiveHigh", f"{max(p95s):.0f}")
    p50s = [CM[(sp, a)]["p50"] for sp, _ in CSPLITS]
    M(f"Cl{A}PfiftyLow", f"{min(p50s):.0f}")
    M(f"Cl{A}PfiftyHigh", f"{max(p50s):.0f}")
for a, A in (("clef", "Clef"), ("clef-flash", "Flash")):
    xs = [CM[(sp, a)]["cost"] / CM[(sp, "jev-1.13")]["cost"] for sp, _ in CSPLITS]
    M(f"Cl{A}CostXLow", hu(min(xs), 1))
    M(f"Cl{A}CostXHigh", hu(max(xs), 1))
M("ClSlowest", hu(max(r["elapsed_ms"] for sp, _ in CSPLITS for r in CL[sp]["requests"]) / 1000, 1))
M("ClInvalid", sum(m_["inv"] for m_ in CM.values()))
spend = sum(inv["budget"]["realized_usd"] for sp, _ in CSPLITS for inv in CL[sp]["run"]["invocations"])  # incl. warm-ups
M("ClSpend", hu(spend, 2))
M("ClSpendFour", hu(spend, 4))
readme = gshow(f"{CLEF_REF}/README.md")
assert f"${hu(spend, 4)}" in readme.replace("**", ""), "Clef spend differs from the evidence README"
yaml_ = gshow(f"{EVIDENCE_PIN}:evals/judges.yaml")
for a, A in (("clef", "Clef"), ("clef-flash", "Flash")):
    blk = yaml_[yaml_.index(f"\n  {a}:"):]
    M(f"Cl{A}Price", "%.2f" % float(re.search(r"price_in:\s*([\d.]+)", blk).group(1)))
M("ClRuleOneMaxPninetyfive", "500")
M("ClRuleOneCostX", "2")
M("ClTimeoutS", f"{CL['holdout']['run']['timeout_ms'] / 1000:g}")

# results table (all four splits)
rows = []
for sp, S_ in CSPLITS:
    for a, A, lab in CARMS:
        m_ = CM[(sp, a)]
        rows.append(f"{sp if a == 'clef' else ''} & {lab} & {m_['acc']}/{m_['n']} & {m_['wa']} & {m_['cov']} & "
                    f"{m_['p50']:.0f} & {m_['p95']:.0f} & {m_['slow']}/{m_['req']} & {hu(m_['cost'], 1)} \\\\")
    rows.append(r"\addlinespace[2pt]")
write(TABLES / "clef-results.tex", table("l l r r r r r r r", [
    r"Split & Judge & correct & wrong auto & automatic & p50 ms & p95 ms & $>$\ClTimeoutS\,s & \$/1M \\"], rows[:-1]))

# paired contrasts
crow = []
for sp, S_ in CSPLITS:
    cons = CL[sp]["summary"]["pairwise"]["contrasts"]
    for met, key in (("accuracy", "correct"), ("wrong auto", "automatic_error")):
        for c in cons[key]:
            pair = f"{c['b']} vs {c['a']}" if c["a"] == "jev-1.13" else f"{c['a']} vs {c['b']}"
            sign = -1 if c["a"] == "jev-1.13" else 1
            dci = sorted(sign * x for x in c["diff_ci95"])
            ph_ = c["p_holm"]
            fam_ = "pairwise"
            if c["a"] == "jev-1.13":  # Holm over the rule-1 family of the two new arms (as in the evidence README)
                r1c = CL[sp]["summary"]["decisions"]["rule1_default_judge"]["candidates"][c["b"]]
                ph_ = r1c["accuracy" if key == "correct" else "wrong_automatic"]["p_holm"]
                fam_ = "rule 1"
            c = dict(c, p_holm=ph_)
            crow.append(f"{sp} & {pair} & {met} & {hu(100 * sign * c['diff'], 1)} [{hu(100 * dci[0], 1)}, {hu(100 * dci[1], 1)}] & "
                        f"{hu(c['p'], 3)} & {hu(ph_, 3)} ({fam_}) \\\\")
            key_ = (sp, pair, key)
            if key == "correct":
                nm = {"clef vs jev-1.13": "ClefJev", "clef-flash vs jev-1.13": "FlashJev", "clef vs clef-flash": "ClefFlash"}[pair]
                M(f"Cl{S_}{nm}Holm", hu(c["p_holm"], 3))
    crow.append(r"\addlinespace[2pt]")
write(TABLES / "clef-contrasts.tex", table("l l l r r r", [
    r"Split & Contrast & metric & difference, points [95\,\% CI] & $p$ & Holm $p$ \\"], crow[:-1]))

# rule-1 (descriptive) and rule-2
r1rows = []
for sp, S_ in CSPLITS:
    r1 = CL[sp]["summary"]["decisions"].get("rule1_default_judge", {}).get("candidates", {})
    for a, A, lab in CARMS[:2]:
        if a not in r1:
            continue
        c = r1[a]
        r1rows.append(f"{sp} & {lab} & {r'\ok' if c['non_inferior_accuracy'] else r'\no'} & "
                      f"{r'\ok' if c['non_inferior_wrong_auto'] else r'\no'} & {c['p95_ms']:.0f} & "
                      f"{hu(c['cost_usd_per_1m'] / c['cost_usd_per_1m_jev'], 1)}\\X & {r'\ok' if c['replaces_default'] else r'\no'} \\\\")
        assert not c["replaces_default"]
write(TABLES / "clef-rule1.tex", table("l l c c r r c", [
    r"Split & Judge & accuracy NI & wrong-auto NI & p95 ms & cost vs Jev & would replace Jev \\"], r1rows))
r2rows = []
for sp, S_ in (("trace-dev", "TrDev"), ("trace-holdout", "TrHold")):
    r2 = CL[sp]["rule2"]
    for a, A, lab in CARMS:
        v = r2[a]
        r2rows.append(f"{sp if a == 'clef' else ''} & {lab} & {v['correct_automatic_reads']}/{v['read_cases']} & "
                      f"{v['wrong_automatic']}/{v['n']} & {hu(100 * v['wrong_automatic_upper95'], 1)}\\,\\% & "
                      f"{r'\ok' if v['useful'] else r'\no'} \\\\")
        M(f"Cl{S_}{A}Reads", v["correct_automatic_reads"])
        M(f"Cl{S_}{A}ReadWa", v["wrong_automatic"])
        assert not v["useful"]
    M(f"Cl{S_}ReadCases", r2["clef"]["read_cases"])
write(TABLES / "clef-rule2.tex", table("l l r r r c", [
    r"Split & Judge & correct reads & wrong reads & upper 95\,\% & useful \\"], r2rows))

# ---- figures: post hoc points added to the reused judge-benchmark scatters (labels re-placed for all points)
JBH = json.loads(gshow(f"{JB_REF}/holdout/summary.json"))
M("PhAxisW", "14.5cm")
M("PhAxisH", "8cm")
LP.configure(OUT, DATA, 14.5, 8.0)


def tsv_points(name):
    rows_ = [ln.split("\t") for ln in (OUT / "jb" / "data" / f"labels-{name}.tsv").read_text().splitlines()[1:]]
    return [(r[0], r[1].replace(", ", ",\n") if "+" in r[0] else r[1], float(r[2]), float(r[3])) for r in rows_]


def merge(points, key, x, y, text):
    """Add a post hoc point unless it coincides with an existing marker; then extend that marker's label."""
    for i, (k, t, px, py) in enumerate(points):
        if abs(px - x) < 1e-3 and abs(py - y) < 1e-3:  # label TSVs store 4 decimals
            points[i] = (k, t + "\n(also in-run)", px, py)
            return False
    points.append((key, text, x, y))
    return True


def ph_rows(sp, cols):
    out_ = {}
    for a, A, lab in CARMS:
        m_ = CM[(sp, a)]
        n = m_["n"]
        cov, wa, acc = 100 * m_["cov"] / n, 100 * m_["wa"] / n, 100 * m_["acc"] / n
        out_[a] = [cov, cov - 100 * m_["covci"][0], 100 * m_["covci"][1] - cov, wa, wa - 100 * m_["waci"][0],
                   100 * m_["waci"][1] - wa, acc, acc - 100 * m_["accci"][0], 100 * m_["accci"][1] - acc, m_["p95"]]
    return out_


PHL = {"clef": "Clef (post hoc)", "clef-flash": "Clef-Flash (post hoc)", "jev-1.13": "Jev in-run (post hoc)"}
hold = ph_rows("holdout", None)
hdr = ["cov", "covminus", "covplus", "wa", "waminus", "waplus", "acc", "accminus", "accplus", "pninetyfive"]
dat("ph-hold-clef.dat", hdr, [[f"{v:.3f}" for v in hold[a]] for a in ("clef", "clef-flash")])
dat("ph-hold-jev.dat", hdr, [[f"{v:.3f}" for v in hold["jev-1.13"]]])
pts = tsv_points("wacov-holdout")
for a in ("clef", "clef-flash", "jev-1.13"):
    merge(pts, "ph-" + a, hold[a][0], hold[a][3], PHL[a])
LP.place_labels("wacov-holdout-ph", pts, (15, 100), (0, 40))
pts = tsv_points("acclat-holdout")
for a in ("clef", "clef-flash", "jev-1.13"):
    merge(pts, "ph-" + a, hold[a][9], hold[a][6], PHL[a])
LP.place_labels("acclat-holdout-ph", pts, (25, 9000), (25, 102), xlog=True)
# accuracy with CI on the holdout: preregistered rows from the judge-benchmark data, post hoc rows after a gap
acc_rows = [ln.split() for ln in (OUT / "jb" / "data" / "accuracy.dat").read_text().splitlines()[1:]]
pre = []
for r in acc_rows:
    lab = " ".join(r[1:-6]).strip("{}")
    pre.append((lab, float(r[-3]), float(r[-2]), float(r[-1])))
pre.sort(key=lambda r: r[1])
dat("ph-acc-pre.dat", ["y", "label", "acc", "minus", "plus"],
    [[i, "{" + lab + "}", f"{a:.2f}", f"{mi:.2f}", f"{pl:.2f}"] for i, (lab, a, mi, pl) in enumerate(pre)])
base_ = len(pre) + 1
php = [(PHL[a], hold[a][6], hold[a][7], hold[a][8]) for a in ("jev-1.13", "clef-flash", "clef")]
dat("ph-acc-post.dat", ["y", "label", "acc", "minus", "plus"],
    [[base_ + i, "{" + lab + "}", f"{a:.2f}", f"{mi:.2f}", f"{pl:.2f}"] for i, (lab, a, mi, pl) in enumerate(php)])
M("PhAccYMax", base_ + len(php) - 1)
M("PhAccTicks", ",".join(str(i) for i in range(len(pre))) + "," + ",".join(str(base_ + i) for i in range(len(php))))
M("PhAccLabels", ",".join("{" + lab + "}" for lab, *_ in pre) + "," + ",".join("{" + lab + "}" for lab, *_ in php))
# cost per 1M decisions vs holdout accuracy (priced judges only)
cpts, crows_pre, crows_post = [], [], []
for a, lab in (("jev-1.13", "Jev 1.13"), ("gpt-6-luna", "GPT-6 Luna"), ("gpt-6.1-sol", "GPT-6.1 Sol")):
    mv_ = JBH["arms"][a]["policies"][JBH["primary_policy"]]["across_reps"]["majority_vote"]
    cst = JBH["arms"][a]["reps"]["1"]["cost"]["usd_per_1m_decisions"]
    acc = 100 * mv_["correct"] / JBH["n_cases"]
    crows_pre.append([f"{cst:.3f}", f"{acc:.3f}", f"{acc - 100 * mv_['ci95'][0]:.3f}", f"{100 * mv_['ci95'][1] - acc:.3f}"])
    cpts.append((a, lab, cst, acc))
for a in ("clef", "clef-flash", "jev-1.13"):
    m_ = CM[("holdout", a)]
    acc = 100 * m_["acc"] / m_["n"]
    crows_post.append([f"{m_['cost']:.3f}", f"{acc:.3f}", f"{acc - 100 * m_['accci'][0]:.3f}", f"{100 * m_['accci'][1] - acc:.3f}"])
    merge(cpts, "ph-" + a, m_["cost"], acc, PHL[a])
dat("ph-cost-pre.dat", ["cost", "acc", "minus", "plus"], crows_pre)
dat("ph-cost-post.dat", ["cost", "acc", "minus", "plus"], crows_post)
LP.configure(OUT, DATA, 12.0, 6.0)
M("CostAxisW", "12cm")
M("CostAxisH", "6cm")
LP.place_labels("costacc-holdout", cpts, (8, 2000), (70, 102), xlog=True)
# trace-holdout reads: post hoc points (taller axis: 9 cm, so every label can sit nearest its own marker)
LP.configure(OUT, DATA, 14.5, 9.0)
M("PhReadsH", "9cm")
r2h = CL["trace-holdout"]["rule2"]
rr = []
pts = tsv_points("reads-holdout")
for a in ("clef", "clef-flash", "jev-1.13"):
    v = r2h[a]
    lo_, hi_ = wil(v["correct_automatic_reads"], v["read_cases"])
    wlo, whi = wil(v["wrong_automatic"], v["n"])
    k, w = v["correct_automatic_reads"], v["wrong_automatic"]
    row = [k, f"{k - lo_ * v['read_cases']:.3f}", f"{hi_ * v['read_cases'] - k:.3f}", w,
           f"{w - wlo * v['n']:.3f}", f"{whi * v['n'] - w:.3f}"]
    if merge(pts, "ph-" + a, k, w, PHL[a]):
        rr.append((a, row))
    else:
        rr.append((a, row))
dat("ph-reads-clef.dat", ["reads", "readsminus", "readsplus", "wa", "waminus", "waplus"],
    [r for a, r in rr if a != "jev-1.13"])
dat("ph-reads-jev.dat", ["reads", "readsminus", "readsplus", "wa", "waminus", "waplus"],
    [r for a, r in rr if a == "jev-1.13"])
zone = (int(MACROS.get("TrUsefulMinReads", "4")) - 0.5, -1.5, 14.0, 0.5)
LP.place_labels("reads-holdout-ph", pts, (-1.0, 14.0), (-1.5, 22.0), obstacles=[zone])

# ================================================================ Review revisions (external peer review, 2026-10-05)
# Every number below is recomputed from the committed rows with the report's own estimator (paired_model).
from datetime import datetime as _dtr
import numpy as _np
SI = {(s["scenario_id"], s["rep"], s["host"], s["arm"]): s for s in SESS}
SI_K = {s["session_key"]: s for s in SESS}


def Cn(s):
    return s["cost_usd_tools_normalized"]


def gm_ci(vals, cl, key, B=10000, seed=None):
    e, lo, hi, n = PM.cluster_boot_mean(vals, cl, PM.rng_for(CONF["seed"] if seed is None else seed, *key), B)
    return math.exp(e), math.exp(lo), math.exp(hi), n


def rci(t, d=3):
    return f"{hu(t[0], d)} [{hu(t[1], d)}, {hu(t[2], d)}]"


# (1) the four hypotheses if quality had to hold for every routed cell
qv = {(h, a): CC["quality"][h][a]["verdict"] for h, _, _ in HOSTS for a, _, _ in ARMS}
M("RvNHypAllQuality", 3 + (1 if all(v == "confirmed" for v in qv.values()) else 0))
M("RvNQualCells", sum(1 for v in qv.values() if v == "confirmed"))
M("RvNRoutedCells", len(qv))

# (2) spend reduction (ratio of mean dollars) next to the geometric-mean saving
def spend_cut(host, arm, split=None):
    ps = [p for p in PAIRS if p["host"] == host and p["arm"] == arm and p["valid"]
          and (split is None or SPLIT["split"][p["scenario_id"]] == split)]
    a = sum(p["anchor_cost_usd"] for p in ps)
    return 1 - sum(p["anchor_cost_usd"] + p["delta_usd"] for p in ps) / a, a / len(ps), (a + sum(p["delta_usd"] for p in ps)) / len(ps)


cut_all, an_all, st_all = spend_cut("fable", "sticky")
cut_test, _, _ = spend_cut("fable", "sticky", "test")
M("RvSpendCutAll", pct(cut_all, 1))
M("RvSpendCutTest", pct(cut_test, 1))
M("RvSpendAnchor", money(an_all))
M("RvSpendSticky", money(st_all))
gm_all = math.exp(_st.mean(r["y"] for r in PM._cost_rows(DS["pairs"]) if r["host"] == "fable" and r["arm"] == "sticky"))
M("RvGMAllFableSticky", hu(gm_all, 3))
M("RvGMSavingAll", pct(1 - gm_all))
assert abs(1000 * (an_all - st_all) - emp[("fable", "all", "sticky")]["saving_per_1000_usd"]) < 0.5

# (3) task type x split coverage
tsplit = defaultdict(lambda: [0, 0])
for s in SESS:
    if s["arm"] == "anchor" and s["host"] == "fable" and s["rep"] == 1:
        tsplit[s["task_type"]][0 if s["split"] == "train" else 1] += 1
for t in TASKS:
    M(f"Rv{t.capitalize()}Train", tsplit[t][0])
    M(f"Rv{t.capitalize()}Test", tsplit[t][1])
write(TABLES / "task-split.tex", table("l r r r", [r"Task type & training & test & total \\"],
      [f"{t} & {tsplit[t][0]} & {tsplit[t][1]} & {sum(tsplit[t])} \\\\" for t in TASKS]))
best = max(TASKS, key=lambda t: emp[("fable", t, "sticky")]["saving_per_1000_usd"])
M("RvBestTaskFableSticky", best)
M("RvSavReviewFableSticky", money(emp[("fable", "review", "sticky")]["saving_per_1000_usd"], 0))
M("RvSavDocsFableSticky", money(emp[("fable", "docs", "sticky")]["saving_per_1000_usd"], 0))

# (4) quality beyond the test split, and Monte-Carlo noise of the test bound
rs_tr = [r for r in Q if r["host"] == "fable" and r["arm"] == "sticky" and r["split"] == "train"]
e, lo, hi, _ = PC.boot_interval([r["dtp"] for r in rs_tr], [r["scenario"] for r in rs_tr], PC.SEED, ("quality", "fable", "sticky"), PC.BOOT)
M("RvQTrainFableSticky", hu(e, 3))
M("RvQTrainFableStickyCI", f"{hu(lo, 3)} to {hu(hi, 3)}")
rs_te = [r for r in Q if r["host"] == "fable" and r["arm"] == "sticky" and r["split"] == "test"]
_, lo2, _, _ = PC.boot_interval([r["dtp"] for r in rs_te], [r["scenario"] for r in rs_te], PC.SEED, ("quality-rv", "fable", "sticky"), PC.BOOT)
M("RvQAltLow", hu(lo2, 4))
M("RvQNoise", hu(abs(lo2 - CC["quality"]["fable"]["sticky"]["ci95"][0]), 4))

# (5) joint savings x quality, by family and by task type
def joint(dimf, values):
    rows_ = []
    for v in values:
        cells_ = []
        for h, _, _ in HOSTS:
            for a, _, _ in ARMS:
                ps = [p for p in PAIRS if p["host"] == h and p["arm"] == a and dimf(p) == v]
                sav = -1000 * _st.mean(p["delta_usd"] for p in ps if p["valid"])
                dtp = _st.mean(p["delta_turn_pass"] for p in ps if p["delta_turn_pass"] is not None)
                flag = r"\textsuperscript{$\dagger$}" if dtp < CONF["ni_margin"] else ""
                cells_.append(f"{money(sav, 0)} / {hu(dtp, 3)}{flag}")
        rows_.append(f"{v} & " + " & ".join(cells_) + r" \\")
    return rows_


jhead = [r" & \multicolumn{3}{c}{Fable host} & \multicolumn{3}{c}{Opus host} \\", r"\cmidrule(lr){2-4}\cmidrule(l){5-7}",
         r" & sticky & shipped & sonnet & sticky & shipped & sonnet \\"]
write(TABLES / "joint-family.tex", table("l r r r r r r", [r"Family" + jhead[2][1:]] if False else jhead[:2] + [r"Family" + jhead[2]],
      joint(lambda p: famof[p["scenario_id"]], list(fam))))
write(TABLES / "joint-task.tex", table("l r r r r r r", jhead[:2] + [r"Task type" + jhead[2]],
      joint(lambda p: p["task_type"], TASKS)))
kn = [r for r in Q if r["host"] == "fable" and r["arm"] == "sticky" and famof[r["scenario"]] == "knowledge"]
e, lo, hi, _ = PC.boot_interval([r["dtp"] for r in kn], [r["scenario"] for r in kn], PC.SEED, ("quality-knowledge", "fable", "sticky"), PC.BOOT)
M("RvKnowFableSticky", hu(e, 3))
M("RvKnowFableStickyCI", f"{hu(lo, 3)} to {hu(hi, 3)}")
sc_ = defaultdict(lambda: [[], []])
for p in PAIRS:
    if p["host"] == "fable" and p["arm"] == "sticky" and p["valid"] and p["delta_turn_pass"] is not None:
        sc_[p["scenario_id"]][0].append(-p["delta_usd"])
        sc_[p["scenario_id"]][1].append(p["delta_turn_pass"])


def ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


xs_ = [_st.mean(v[0]) for v in sc_.values()]
ys_ = [_st.mean(v[1]) for v in sc_.values()]
rx, ry = ranks(xs_), ranks(ys_)
M("RvSpearman", hu(_np.corrcoef(rx, ry)[0, 1], 2))

# (6) tools normalization: cold vs warm first requests, by host and arm
tn = defaultdict(lambda: [0, 0.0, 0, 0.0])
warm_reads = defaultdict(lambda: defaultdict(int))
for r in REQS:
    if not r.get("tools_repriced_tokens"):
        continue
    k = (r["host"], r["arm"])
    cold = r["tokens"]["cache_read"] < 20000
    d = -r["tools_normalized_delta_usd"]
    if cold:
        tn[k][0] += 1
        tn[k][1] += d
    else:
        tn[k][2] += 1
        tn[k][3] += d
        warm_reads[r["model"]][int(r["tokens"]["cache_read"])] += 1
tnrows = []
order_tn = [("fable", "anchor"), ("fable", "aa"), ("fable", "shipped"), ("fable", "sticky"), ("opus", "anchor"),
            ("opus", "aa"), ("opus", "shipped"), ("opus", "sticky"), ("any", "sonnet")]
for h, a in order_tn:
    v = tn[(h, a)]
    ns = sum(1 for s in SESS if s["host"] == h and s["arm"] == a)
    tnrows.append(f"{'Sonnet control' if a == 'sonnet' else h.capitalize() + ' ' + a} & {ns} & {v[0]} & \\${money(v[1])} & {v[2]} & \\${money(v[3])} & \\${money(v[1] + v[3])} \\\\")
    if a in ("anchor", "sticky", "sonnet"):
        M(f"RvCold{h.capitalize() if h != 'any' else 'Sonnet'}{a.capitalize() if a != 'sonnet' else ''}", v[0])
tot = [sum(v[i] for v in tn.values()) for i in range(4)]
tnrows.append(r"\midrule")
tnrows.append(f"Total & {len(SESS)} & {tot[0]} & \\${money(tot[1])} & {tot[2]} & \\${money(tot[3])} & \\${money(tot[1] + tot[3])} \\\\")
assert abs(tot[1] + tot[3] - DSUM["tools_normalized_delta_usd_total"] * -1) < 0.01 or abs(tot[1] + tot[3] - abs(DSUM["tools_normalized_delta_usd_total"])) < 0.01
write(TABLES / "tools-norm.tex", table("l r r r r r r", [
    r" & & \multicolumn{2}{c}{cold first request} & \multicolumn{2}{c}{warm first request} & \\",
    r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}",
    r"Host and arm & sessions & requests & \$ moved & requests & \$ moved & total \\"], tnrows))
M("RvColdTotal", tot[0])
M("RvWarmTotal", thousands(tot[2]))
M("RvColdUSD", money(tot[1]))
M("RvWarmUSD", money(tot[3]))
for mdl, K in (("claude-fable-5-1", "Fable"), ("claude-sonnet-5", "Sonnet")):
    M(f"RvWarmRead{K}", thousands(max(warm_reads[mdl], key=warm_reads[mdl].get)))
    M(f"RvAllowGap{K}", int(MACROS["ToolsAllowance"].replace("{,}", "")) - max(warm_reads[mdl], key=warm_reads[mdl].get))
DSR = PM.load_dataset(EV / "data", basis="raw")
rawrows = []
for h, H, hn in HOSTS:
    for a, A, an in ARMS:
        ys = [r["y"] for r in PM._cost_rows(DSR["pairs"]) if r["host"] == h and r["arm"] == a and r["split"] == "test"
              and PC.pair_noninferior(r)]
        raw = math.exp(_st.mean(ys))
        rawrows.append(f"{hn} & {an} & {hu(raw, 3)} & {hu(pe('pair', h, a)['gm_ratio'], 3)} \\\\")
write(TABLES / "tools-ratios.tex", table("l l r r", [r"Host & Arm & raw ratio & tools-normalized ratio \\"], rawrows,
                                         width=r"0.7\textwidth"))

# (7) composition weighting vs actual sticky requests
for h, H in (("fable", "Fable"), ("opus", "Opus")):
    sts = [s for s in SESS if s["arm"] == "sticky" and s["host"] == h]
    p_ = sum(s["sticky_decision"] == "cheap" for s in sts) / len(sts)
    mean_ = lambda h_, a_: _st.mean(s["n_req"] for s in SESS if s["host"] == h_ and s["arm"] == a_ and s["cost_valid"])
    pred = p_ * mean_("any", "sonnet") + (1 - p_) * mean_(h, "anchor")
    act = mean_(h, "sticky")
    M(f"RvReqPred{H}", hu(pred, 1))
    M(f"RvReqAct{H}", hu(act, 1))
    M(f"RvReqGap{H}", pct(1 - act / pred, 1))

# (8) turn rows: 11,588 vs the 11,576 used in Part III's explorations
kill_key = [s["session_key"] for s in SESS if s["killed_memory"]][0]
M("RvKilledTurns", sum(1 for t in TURNS if t["session_key"] == kill_key))
skips = sorted((t["session_key"], t["turn_index"]) for t in TURNS if t["skipped"] and t["session_key"] in valid)
assert len(TURNS) - int(MACROS["RvKilledTurns"]) - len(skips) == int(MACROS["PerTurnN"])
M("RvNSkips", len(skips))
M("RvSkipList", "; ".join(f"\\code{{{tex_escape(k)}}} turn {i}" for k, i in skips))
M("PerTurnNFmt", thousands(int(MACROS["PerTurnN"])))

# (10) A/A against launch offset (OLS slope per second, scenario-cluster bootstrap)
wave_t0 = {}
for s in SESS:
    t = _dtr.fromisoformat(s["actual_start"]).timestamp()
    wave_t0[s["wave_id"]] = min(wave_t0.get(s["wave_id"], t), t)
offs = {s["session_key"]: _dtr.fromisoformat(s["actual_start"]).timestamp() - wave_t0[s["wave_id"]] for s in SESS}
for h, H in (("fable", "Fable"), ("opus", "Opus")):
    aa = [r for r in PM._cost_rows(DS["pairs"]) if r["host"] == h and r["arm"] == "aa"]
    dx = [offs[SI[(r["scenario"], r["rep"], h, "aa")]["session_key"]] - offs[SI[(r["scenario"], r["rep"], h, "anchor")]["session_key"]] for r in aa]
    y = [r["y"] for r in aa]

    def fit(ix):
        X = _np.column_stack([[dx[i] for i in ix], _np.ones(len(ix))])
        return _np.linalg.lstsq(X, _np.array([y[i] for i in ix]), rcond=None)[0]

    b = fit(list(range(len(aa))))
    g_ = defaultdict(list)
    for i, r in enumerate(aa):
        g_[r["scenario"]].append(i)
    keys_ = list(g_)
    rng = _np.random.default_rng(7)
    sl = []
    for _ in range(4000):
        pick = rng.integers(0, len(keys_), len(keys_))
        ix = [i for k in pick for i in g_[keys_[k]]]
        try:
            sl.append(fit(ix)[0])
        except Exception:
            pass
    lo, hi = _np.percentile(sl, [2.5, 97.5])
    M(f"RvAASlope{H}", hu(b[0], 4))
    M(f"RvAASlope{H}CI", f"{hu(lo, 4)} to {hu(hi, 4)}")
    M(f"RvAAIntercept{H}", hu(math.exp(b[1]), 3))
    nr = [math.log(SI[(r["scenario"], r["rep"], h, "aa")]["n_req"] / SI[(r["scenario"], r["rep"], h, "anchor")]["n_req"]) for r in aa]
    M(f"RvAAReqCorr{H}", hu(_np.corrcoef(y, nr)[0, 1], 2))
    M(f"RvAAFirst{H}", pct(sum(1 for v in dx if v < 0) / len(dx)))

# (11) the effort confound: sticky that chose Sonnet against the plain-Sonnet control
bg = defaultdict(float)
eff = defaultdict(lambda: defaultdict(int))
for r in REQS:
    if not r["main"]:
        bg[r["session_key"]] += r["cost_usd_tools_normalized"] or 0.0
    else:
        eff[(r["arm"], SI[(r["scenario_id"], r["rep"], r["host"], r["arm"])].get("sticky_decision"))][r["effort"]] += 1
M("RvEffMediumSticky", thousands(eff[("sticky", "cheap")]["medium"]))
M("RvEffStickyTotal", thousands(sum(eff[("sticky", "cheap")].values())))
M("RvEffNoneControl", thousands(eff[("sonnet", None)][None]))
M("RvEffControlTotal", thousands(sum(eff[("sonnet", None)].values())))
for h, H in (("fable", "Fable"), ("opus", "Opus")):
    for sp, SP in (("all", "All"), ("test", "Test")):
        rows_ = []
        for s in SESS:
            if s["arm"] != "sticky" or s["host"] != h or s["sticky_decision"] != "cheap" or not s["cost_valid"]:
                continue
            if sp == "test" and s["split"] != "test":
                continue
            c = SI[(s["scenario_id"], s["rep"], "any", "sonnet")]
            if not c["cost_valid"]:
                continue
            a = SI[(s["scenario_id"], s["rep"], h, "anchor")]
            out_s = sum(v["output"] for v in s["tokens"].values())
            out_c = sum(v["output"] for v in c["tokens"].values())
            rows_.append(dict(sc=s["scenario_id"], y=math.log(Cn(s) / Cn(c)), n=math.log(s["n_req"] / c["n_req"]),
                              ex=math.log(s["exec_ms"] / c["exec_ms"]), d=s["turn_pass_frac"] - c["turn_pass_frac"],
                              os=out_s, oc=out_c, ya=math.log(Cn(s) / Cn(a)), yc=math.log(Cn(c) / Cn(a))))
        cl = [r["sc"] for r in rows_]
        b_ = lambda f, k: PM.cluster_boot_mean([r[f] for r in rows_], cl, PM.rng_for(CONF["seed"], "c11", h, sp, k), 10000)
        e, lo, hi, nsc = b_("y", "y")
        M(f"RvEff{H}{SP}", hu(math.exp(e), 3))
        M(f"RvEff{H}{SP}CI", f"{hu(math.exp(lo), 3)}--{hu(math.exp(hi), 3)}")
        M(f"RvEff{H}{SP}N", len(rows_))
        if sp == "all":
            e, lo, hi, _ = b_("n", "n")
            M(f"RvEffReq{H}", pct(1 - math.exp(e)))
            M(f"RvEffOut{H}", pct(1 - _st.mean(r["os"] for r in rows_) / _st.mean(r["oc"] for r in rows_)))
            e, _, _, _ = b_("ex", "ex")
            M(f"RvEffTime{H}", pct(1 - math.exp(e)))
            e, lo, hi, _ = b_("d", "d")
            M(f"RvEffDtp{H}", hu(e, 3))
            M(f"RvEffDtp{H}CI", f"{hu(lo, 3)} to {hu(hi, 3)}")
            M(f"RvEffVsAnchor{H}", hu(math.exp(_st.mean(r["ya"] for r in rows_)), 3))
            e, lo, hi, _ = b_("ya", "ya")
            M(f"RvEffVsAnchor{H}Two", hu(math.exp(e), 2))
            M(f"RvEffVsAnchor{H}CI", f"{hu(math.exp(lo), 2)}--{hu(math.exp(hi), 2)}")
            M(f"RvCtlVsAnchor{H}", hu(math.exp(_st.mean(r["yc"] for r in rows_)), 3))
    hs = [math.log(Cn(s) / Cn(SI[(s["scenario_id"], s["rep"], h, "anchor")])) for s in SESS
          if s["arm"] == "sticky" and s["host"] == h and s["sticky_decision"] == "host" and s["cost_valid"]]
    M(f"RvStickyHost{H}", hu(math.exp(_st.mean(hs)), 3))
    M(f"RvStickyHost{H}Two", hu(math.exp(_st.mean(hs)), 2))
    M(f"RvStickyHostN{H}", len(hs))
gaps_h = []
for s in SESS:
    if s["arm"] == "anchor" and s["host"] == "fable":
        c = SI[(s["scenario_id"], s["rep"], "any", "sonnet")]
        gaps_h.append(abs(_dtr.fromisoformat(c["actual_start"]).timestamp() - _dtr.fromisoformat(s["actual_start"]).timestamp()) / 3600)
M("RvSonnetWaveMedianH", hu(_st.median(gaps_h), 1))
M("RvSonnetWaveMaxH", hu(max(gaps_h), 1))
assert all(SI[(s["scenario_id"], s["rep"], "any", "sonnet")]["wave_id"].endswith("-opus") for s in SESS if s["arm"] == "anchor")

# follow-up evidence: plain Sonnet at medium vs default effort (effort-control-v1, committed 2026-10-05)
EFF = REPO / "docs" / "evidence" / "2026-10-05-effort-control"
ej = json.loads((EFF / "summary.json").read_text())
er = json.loads((EFF / "result" / "effort-result.json").read_text())
he, sec = ej["rows"][0], ej["rows"][1]
assert "HE" in he["label"] and "exploratory" in sec["label"]
assert abs(he["gm_ratio"] - er["cost"]["geo_mean_ratio"]) < 1e-12
M("EcRatio", hu(he["gm_ratio"], 3))
M("EcCI", f"{hu(he['ci95'][0], 3)}--{hu(he['ci95'][1], 3)}")
M("EcCutPct", pct(1 - he["gm_ratio"]))
M("EcPairs", he["n_pairs"])
M("EcScen", er["cost"]["n_scenarios"])
M("EcReps", he["n_pairs"] // er["cost"]["n_scenarios"])
M("EcSeed", er["seed"])
M("EcResamples", thousands(er["resamples"]))
q_ = ej["quality"]
M("EcQual", hu(q_["mean_delta_turn_pass"], 3))
M("EcQualCI", f"{hu(q_['ci95'][0], 3)} to {hu(q_['ci95'][1], 3)}")
M("EcQualVerdict", "non-inferior" if q_["non_inferior"] else "not shown")
M("EcHE", "supported" if ej["HE_supported"] else "not supported")
assert ej["HE_supported"] and q_["non_inferior"]
M("EcSecRatio", hu(sec["gm_ratio"], 3))
M("EcSecCI", f"{hu(sec['ci95'][0], 3)}--{hu(sec['ci95'][1], 3)}")
M("EcSecN", sec["n_pairs"])
M("EcSecGapPct", pct(1 - sec["gm_ratio"]))
ep = jsonl(EFF / "data" / "pairs.jsonl")
M("EcCheaperPairs", sum(1 for p_ in ep if p_["delta_usd"] < 0))
eled = json.loads((EFF / "campaign" / "ledger.json").read_text())
espent = sum(eled["spent"].values()) if isinstance(eled["spent"], dict) else eled["spent"]
M("EcSpend", money(espent))
M("EcPreflight", money(json.loads((EFF / "campaign" / "preflight.json").read_text())["total_cost_usd"]))
M("EcBudget", money(eled["budget_usd"], 0))
M("SpendWithFollowup", money(sum(spent.values()) + espent))
prov = (EFF / "prereg" / "PROVENANCE.md").read_text()


def hms(txt):
    h_, m_, s_ = txt.split(":")
    sec_ = int(float(s_))  # whole seconds, truncated as in PROVENANCE.md's wording
    return (f"{int(m_)}\\,min {sec_}\\,s" if int(m_) else f"{sec_}\\,s")


M("EcScheduleBefore", hms(re.search(r"were created (\d+:\d+:[\d.]+) BEFORE", prov).group(1)))
M("EcFirstAfter", hms(re.search(r"first session started only (\d+:\d+:[\d.]+) after", prov).group(1)))
M("EcPreregSha", re.search(r"git diff (\w+) HEAD", prov).group(1))
erows = [f"Medium / default effort, plain Sonnet (confirmatory, concurrent) & {he['n_pairs']} pairs & {hu(he['gm_ratio'], 3)} & {hu(he['ci95'][0], 3)}--{hu(he['ci95'][1], 3)} \\\\",
         f"Medium plain Sonnet / main-v1 sticky-on-Sonnet (exploratory, not concurrent) & {sec['n_pairs']} scenarios & {hu(sec['gm_ratio'], 3)} & {hu(sec['ci95'][0], 3)}--{hu(sec['ci95'][1], 3)} \\\\",
         r"\midrule",
         f"Turn-pass difference, medium minus default (unfiltered) & {q_['n_pairs']} pairs & {hu(q_['mean_delta_turn_pass'], 3)} & {hu(q_['ci95'][0], 3)} to {hu(q_['ci95'][1], 3)} \\\\"]
write(TABLES / "effort-control.tex", table(r">{\raggedright\arraybackslash}p{0.5\textwidth} r r r",
                                           [r"Comparison & n & estimate & 95\,\% CI \\"], erows))


# ================================================================ Re-review fixes (2026-10-05)
qf = CC["quality"]["fable"]["sticky"]["ci95"]
M("RvQWidth", hu(qf[1] - qf[0], 2))
# B4: did the cold tools prefix depend on the anchor starting first in its wave?
cold_keys = {r["session_key"] for r in REQS if r.get("tools_repriced_tokens") and r["tokens"]["cache_read"] < 20000}
wv = defaultdict(list)
for s in SESS:
    wv[s["wave_id"]].append(s)
for h, H in (("fable", "Fable"), ("opus", "Opus")):
    cnt = defaultdict(int)
    for s in SESS:
        if s["arm"] == "anchor" and s["host"] == h:
            first = min(wv[s["wave_id"]], key=lambda x: x["actual_start"])["session_key"] == s["session_key"]
            cnt[(first, s["session_key"] in cold_keys)] += 1
    M(f"RvColdFirst{H}", f"{cnt[(True, True)]} of {cnt[(True, True)] + cnt[(True, False)]}")
    M(f"RvColdNotFirst{H}", f"{cnt[(False, True)]} of {cnt[(False, True)] + cnt[(False, False)]}")
# R3: sticky-on-Sonnet (medium) minus default-effort control, docs/explain/review vs the rest (post hoc)
KT = ("docs", "explain", "review")
for grp, G_ in (("in", "KT"), ("out", "Rest")):
    rr_ = []
    for s in SESS:
        if s["arm"] != "sticky" or s["sticky_decision"] != "cheap" or not s["cost_valid"]:
            continue
        if (s["task_type"] in KT) != (grp == "in"):
            continue
        c = SI[(s["scenario_id"], s["rep"], "any", "sonnet")]
        rr_.append((s["scenario_id"], s["turn_pass_frac"] - c["turn_pass_frac"]))
    e, lo, hi, nsc = PM.cluster_boot_mean([v for _, v in rr_], [k for k, _ in rr_], PM.rng_for(CONF["seed"], "r3", grp), 10000)
    M(f"Rv{G_}Dtp", hu(e, 3))
    M(f"Rv{G_}DtpCI", f"{hu(lo, 3)}, {hu(hi, 3)}")
    M(f"Rv{G_}N", nsc)


# ================================================================ Round-2 review (2026-10-05)
import yaml as _yaml
# R1: main-request effort by host x arm x model (sticky split by its decision)
effmix = defaultdict(int)
for r in REQS:
    if r["main"]:
        s_ = SI[(r["scenario_id"], r["rep"], r["host"], r["arm"])]
        arm_ = r["arm"] + (f" ({'Sonnet' if s_['sticky_decision'] == 'cheap' else 'host'})" if r["arm"] == "sticky" else "")
        effmix[(r["host"], arm_, r["model"], r["effort"] or "unset")] += 1
MODEL_NAME = {"claude-fable-5-1": "Fable 5.1", "claude-opus-5-5": "Opus 5.5", "claude-sonnet-5": "Sonnet 5"}
host_order = {"fable": 0, "opus": 1, "any": 2}
erows_ = []
for (h, a_, m_, e_), n_ in sorted(effmix.items(), key=lambda kv: (host_order[kv[0][0]], kv[0][1], kv[0][2], kv[0][3])):
    erows_.append(f"{'Sonnet control' if h == 'any' else h.capitalize()} & {a_} & {MODEL_NAME[m_]} & {e_} & {thousands(n_)} \\\\")
write(TABLES / "effort-mix.tex", table("l l l l r", [r"Host & Arm & Model & Effort & main requests \\"], erows_))
M("RgEffAnchorFable", thousands(effmix[("fable", "anchor", "claude-fable-5-1", "unset")]))
M("RgEffAnchorOpus", thousands(effmix[("opus", "anchor", "claude-opus-5-5", "unset")]))
for lv in ("high", "medium", "low"):
    M(f"RgStickyHost{lv.capitalize()}", thousands(sum(n_ for (h, a_, m_, e_), n_ in effmix.items() if a_ == "sticky (host)" and e_ == lv)))
# extrapolation from the Sonnet follow-up (labelled as such in the text)
eff_f = he["gm_ratio"]
fab = pe("pair", "fable", "sticky")["gm_ratio"]
M("RgEffShareFable", pct(math.log(eff_f) / math.log(fab)))
M("RgModelOnlyFable", hu(fab / eff_f, 3))
ops = float(MACROS["RvEffVsAnchorOpus"])
M("RgOpusMatched", hu(ops / eff_f, 2))
M("RgFabStickyPair", hu(fab, 3))
M("RgOverheadFable", pct(float(MACROS["RvStickyHostFable"]) - 1))
M("RgOverheadOpus", pct(float(MACROS["RvStickyHostOpus"]) - 1))
# optional plain-Fable effort follow-up (rendered only if committed)
EFFF = REPO / "docs" / "evidence" / "2026-10-06-effort-control-fable"
fj = json.loads((EFFF / "summary.json").read_text())
fsens = json.loads((EFFF / "result" / "sensitivity.json").read_text())
fprov = (EFFF / "prereg" / "PROVENANCE.md").read_text()
f1, f2, f3 = fj["rows"]
assert "HF" in f1["label"] and "sticky" in f2["label"] and "anchor" in f3["label"]
fq = fj["quality"]
assert fj["HF_supported"] and fq["non_inferior"]
M("EfRatio", hu(f1["gm_ratio"], 3))
M("EfCI", f"{hu(f1['ci95'][0], 3)}--{hu(f1['ci95'][1], 3)}")
M("EfCutPct", pct(1 - f1["gm_ratio"]))
M("EfPairs", f1["n_pairs"])
M("EfValid", fsens["as_run"]["n_valid_cost_pairs"])
M("EfScen", fsens["as_run"]["cost"]["n_scenarios"])
M("EfSeed", fsens["as_run"]["seed"])
M("EfQual", hu(fq["mean_delta_turn_pass"], 3))
M("EfQualCI", f"{hu(fq['ci95'][0], 3)} to {hu(fq['ci95'][1], 3)}")
fm = fq["final_pass_mcnemar"]
M("EfFinalBoth", fm["both_pass"])
M("EfFinalMed", fm["only_medium_passes"])
M("EfFinalDef", fm["only_default_passes"])
M("EfVsSticky", hu(f2["gm_ratio"], 3))
M("EfVsStickyCI", f"{hu(f2['ci95'][0], 3)}--{hu(f2['ci95'][1], 3)}")
M("EfStickyVsMedium", hu(1 / f2["gm_ratio"], 2))
M("EfVsAnchor", hu(f3["gm_ratio"], 3))
M("EfVsAnchorCI", f"{hu(f3['ci95'][0], 3)}--{hu(f3['ci95'][1], 3)}")
st44 = fsens["strict_44"]["cost"]
M("EfStrict", hu(st44["geo_mean_ratio"], 3))
M("EfStrictCI", f"{hu(st44['ci95'][0], 3)}--{hu(st44['ci95'][1], 3)}")
M("EfShare", pct(math.log(f1["gm_ratio"]) / math.log(pe("pair", "fable", "sticky")["gm_ratio"])))
M("EfPreregSha", re.search(r"git diff (\w+) HEAD", fprov).group(1))
M("EfScheduleAfter", hms(re.search(r"\((\d+:\d+:[\d.]+) AFTER the preregistration commit\)", fprov).group(1)))
fled = json.loads((EFFF / "campaign" / "ledger.json").read_text())
M("EfSpend", money(sum(fled["spent"].values()) if isinstance(fled["spent"], dict) else fled["spent"]))
M("EfSurplusTokens", re.search(r"read \*\*(\d+) more cache tokens\*\*", (EFFF / "FLAGS.md").read_text()).group(1))
frows = [f"Fable medium / default effort (confirmatory, concurrent) & {f1['n_pairs']} pairs ({fsens['as_run']['n_valid_cost_pairs']} cost-valid) & {hu(f1['gm_ratio'], 3)} & {hu(f1['ci95'][0], 3)}--{hu(f1['ci95'][1], 3)} \\\\",
         f"Same, excluding the audit-flagged pair (sensitivity) & {fsens['strict_44']['n_valid_cost_pairs'] if 'n_valid_cost_pairs' in fsens['strict_44'] else ''} pairs & {hu(st44['geo_mean_ratio'], 3)} & {hu(st44['ci95'][0], 3)}--{hu(st44['ci95'][1], 3)} \\\\",
         f"Fable medium / main-campaign Fable sticky (exploratory, not concurrent) & {f2['n_pairs']} scenarios & {hu(f2['gm_ratio'], 3)} & {hu(f2['ci95'][0], 3)}--{hu(f2['ci95'][1], 3)} \\\\",
         f"Fable medium / main-campaign Fable anchor (exploratory, not concurrent) & {f3['n_pairs']} scenarios & {hu(f3['gm_ratio'], 3)} & {hu(f3['ci95'][0], 3)}--{hu(f3['ci95'][1], 3)} \\\\",
         r"\midrule",
         f"Turn-pass difference, medium minus default (unfiltered) & {fq['n_pairs']} pairs & {hu(fq['mean_delta_turn_pass'], 3)} & {hu(fq['ci95'][0], 3)} to {hu(fq['ci95'][1], 3)} \\\\"]
write(TABLES / "effort-fable.tex", table(r">{\raggedright\arraybackslash}p{0.5\textwidth} r r r",
                                         [r"Comparison & n & estimate & 95\,\% CI \\"], frows))

# R2: Fable sticky by task type with scenario-cluster CIs
trows_ = []
fails_ = []
for t_ in TASKS:
    ps = [p for p in PAIRS if p["host"] == "fable" and p["arm"] == "sticky" and p["task_type"] == t_]
    sv = [(p["scenario_id"], -1000 * p["delta_usd"]) for p in ps if p["valid"]]
    dv = [(p["scenario_id"], p["delta_turn_pass"]) for p in ps if p["delta_turn_pass"] is not None]
    e1, l1, h1, n1 = PM.cluster_boot_mean([v for _, v in sv], [k for k, _ in sv], PM.rng_for(CONF["seed"], "r2s", t_), 10000)
    e2, l2, h2, _ = PM.cluster_boot_mean([v for _, v in dv], [k for k, _ in dv], PM.rng_for(CONF["seed"], "r2q", t_), 10000)
    flag = r"\textsuperscript{$\dagger$}" if e2 < CONF["ni_margin"] else ""
    trows_.append(f"{t_} & {n1} & {money(e1, 0)} & {money(l1, 0)} to {money(h1, 0)} & {hu(e2, 3)}{flag} & {hu(l2, 3)} to {hu(h2, 3)} \\\\")
    M(f"RgTask{t_.capitalize()}Dtp", hu(e2, 3))
    M(f"RgTask{t_.capitalize()}N", n1)
    M(f"RgTask{t_.capitalize()}Sav", money(e1, 0))
    if e2 < CONF["ni_margin"]:
        fails_.append((t_, e2))
write(TABLES / "task-fable-sticky.tex", table("l r r r r r", [
    r"Task type & scenarios & saving / 1,000 & 95\,\% CI & turn-pass $\Delta$ & 95\,\% CI \\"], trows_))
M("RgNTaskFail", len(fails_))
M("RgNTask", len(TASKS))
M("RgTaskFailList", ", ".join(f"{t_} {hu(v, 3)}" for t_, v in sorted(fails_, key=lambda x: x[1])))
M("RgNTaskThreeX", sum(1 for _, v in fails_ if v / CONF["ni_margin"] >= 2.5))

# R3: cross-arm read volume
cross = sum(s["cross_arm_read_tokens"] or 0 for s in SESS)
allread = sum(r["tokens"]["cache_read"] for r in REQS)
M("RgCrossTokens", thousands(int(cross)))
M("RgCrossShare", pct(cross / allread, 2))
M("RgCrossSessions", sum(1 for s in SESS if (s["cross_arm_read_tokens"] or 0) > 0))
M("RgForeignRequests", sum(s["foreign_read_requests"] for s in SESS))

# R4: static writes beyond the allowance
ALLOW = int(MACROS["ToolsAllowance"].replace("{,}", ""))
statics = [s["first_req_write_static"] for s in SESS if s["first_req_write_static"] is not None]
M("RgStaticMedian", thousands(int(_st.median(statics))))
BIG_T = 50000
M("RgBigThreshold", thousands(BIG_T))
big = [s for s in SESS if (s["first_req_write_static"] or 0) > BIG_T]
M("RgBigN", len(big))
M("RgBigAnchors", sum(1 for s in big if s["arm"] == "anchor"))
M("RgBigSonnet", sum(1 for s in big if s["arm"] == "sonnet"))
M("RgBigSticky", sum(1 for s in big if s["arm"] == "sticky"))
bigv = sorted(int(s["first_req_write_static"]) for s in big)
M("RgBigLow", thousands(bigv[0]))
M("RgBigHigh", thousands(bigv[-1]))
M("RgBigInCold", sum(1 for s in big if s["session_key"] in cold_keys))
first_main = {}
for r in REQS:
    if r["main"] and (r["session_key"] not in first_main or r["request_index"] < first_main[r["session_key"]]["request_index"]):
        first_main[r["session_key"]] = r
resid_usd = {}
for s in SESS:
    r = first_main.get(s["session_key"])
    if r is None or s["first_req_write_static"] is None:
        resid_usd[s["session_key"]] = 0.0
        continue
    pr = PRICE[r["model"]]
    resid_usd[s["session_key"]] = max(0.0, s["first_req_write_static"] - ALLOW) * (pr[2] - pr[1]) / 1e6
rrows = []
for h, a_ in order_tn:
    v = [resid_usd[s["session_key"]] for s in SESS if s["host"] == h and s["arm"] == a_]
    rrows.append(f"{'Sonnet control' if a_ == 'sonnet' else h.capitalize() + ' ' + a_} & \\${money(_st.mean(v), 3)} \\\\")
    if a_ in ("anchor", "sticky"):
        M(f"RgResid{h.capitalize()}{a_.capitalize()}", money(_st.mean(v), 3))
write(TABLES / "static-residual.tex", table("l r", [r"Host and arm & residual per session \\"], rrows, width=r"0.6\textwidth"))
key_of = {(s["scenario_id"], s["rep"], s["host"], s["arm"]): s["session_key"] for s in SESS}
shift = []
for h, H, _ in HOSTS:
    for a_, A_, _ in ARMS:
        ys = []
        for r in PM._cost_rows(DS["pairs"]):
            if r["host"] != h or r["arm"] != a_ or r["split"] != "test" or not PC.pair_noninferior(r):
                continue
            ka = key_of[(r["scenario"], r["rep"], h, "anchor")]
            kb = key_of.get((r["scenario"], r["rep"], h, a_)) or key_of[(r["scenario"], r["rep"], "any", a_)]
            ca, cb = SI_K[ka], SI_K[kb]
            ys.append(math.log((Cn(cb) - resid_usd[kb]) / (Cn(ca) - resid_usd[ka])))
        adj = math.exp(_st.mean(ys))
        shift.append(abs(adj - pe("pair", h, a_)["gm_ratio"]))
        if a_ == "sticky":
            M(f"RgResidAdj{H}Sticky", hu(adj, 3))
M("RgResidShiftMax", hu(max(shift), 3))

# R5: effort-control mechanism check
ereq = [json.loads(x) for x in gzip.open(EFF / "data" / "requests.jsonl.gz", "rt")]
med_main = [r for r in ereq if r["arm"] == "sonnet_medium" and r["main"]]
M("RgEcMainMedium", thousands(sum(1 for r in med_main if r["effort"] == "medium")))
M("RgEcMainTotal", thousands(len(med_main)))
M("RgEcNonMainDefault", sum(1 for r in ereq if r["arm"] == "sonnet_medium" and not r["main"] and r["effort"] is None))
assert sum(1 for r in ereq if r["arm"] == "sonnet_medium" and r["main"] and r["effort"] != "medium") == 0

# R7: the quality instrument
SCN = REPO / "evals" / "paired" / "scenarios" / "main-v1"
VAL = json.loads((SCN / "validation.json").read_text())
M("RgValN", len(VAL["scenarios"]))
M("RgValStartFail", sum(1 for s in VAL["scenarios"] if s["start_fail"]))
M("RgValOK", sum(1 for s in VAL["scenarios"] if s["validator_ok"]))
M("RgValRuns", thousands(sum(s["guarded_runs"] for s in VAL["scenarios"])))
M("RgValKills", sum(s["resource_limit_kills"] + s["timeouts"] for s in VAL["scenarios"]))
M("RgValWeak", sum(len(s["weak"]) for s in VAL["scenarios"]))
M("RgValWeakScen", sum(1 for s in VAL["scenarios"] if s["weak"]))
kinds = defaultdict(int)
nturns = 0
scen_yaml = {}
for f in sorted(SCN.glob("*/*.yaml")):
    d = _yaml.safe_load(f.read_text())
    scen_yaml[d["id"]] = (f.parent.name, d)
    for t in d["turns"]:
        nturns += 1
        for c in t.get("checks", []):
            kinds[c["kind"]] += 1
M("RgNTurnsScripted", thousands(nturns))
M("RgCheckKinds", ", ".join(f"{tex_escape(k)} ({thousands(v)})" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])))
for f_ in fam:
    v = [s["turn_pass_frac"] for s in SESS if s["arm"] == "anchor" and famof[s["scenario_id"]] == f_ and s["turn_pass_frac"] is not None]
    M(f"RgAnchorTP{f_.capitalize()}", hu(_st.mean(v), 3))


def ex_turn(sid, ti):
    fam_, d = scen_yaml[sid]
    t = d["turns"][ti - 1]
    pr_ = " ".join(t["prompt"].split())
    if len(pr_) > 260:
        pr_ = pr_[:257].rsplit(" ", 1)[0] + "\u2026"
    chk = "; ".join(", ".join(f"{k}: {v}" for k, v in c.items()) for c in t.get("checks", []))
    if len(chk) > 220:
        chk = chk[:217].rsplit(" ", 1)[0] + "\u2026"
    code = lambda x: re.sub(r"`([^`]*)`", r"\\texttt{\1}", x)
    return fam_, code(tex_escape(pr_)).replace("\u2026", r"\dots{}"), tex_escape(chk).replace("\u2026", r"\dots{}")


exs = []
for sid, ti in (("go-say", 1), ("fastrand-explain", 4), ("schema-wrongkey", 7)):
    if sid in scen_yaml:
        fam_, p_, c_ = ex_turn(sid, ti)
        exs.append(f"\\item \\textbf{{{fam_}, \\code{{{tex_escape(sid)}}} turn {ti}.}} User: ``{p_}'' Check: \\code{{{c_}}}")
brk = lambda x: x.replace(", ", ",\\allowbreak{} ").replace("/", "/\\allowbreak{}").replace("(", "\\allowbreak{}(")
write(TABLES / "quality-examples.tex", "{\\raggedright\n\\begin{itemize}[leftmargin=1.2em]\n" + "\n".join(brk(nopath(e)) for e in exs)
      + "\n\\end{itemize}\n\\par}\n")


def pbis(rows):
    xs = [r[0] for r in rows]
    ys = [1.0 if r[1] else 0.0 for r in rows]
    if len(set(ys)) < 2 or len(set(xs)) < 2:
        return None
    return float(_np.corrcoef(xs, ys)[0, 1])


crows_ = []
for a_ in ("anchor", "aa", "shipped", "sticky", "sonnet"):
    rows = [(s["turn_pass_frac"], s["final_state_pass"]) for s in SESS if s["arm"] == a_ and s["turn_pass_frac"] is not None]
    v = pbis(rows)
    crows_.append(f"{a_} & {len(rows)} & {'n/a' if v is None else hu(v, 2)} \\\\")
allrows = [(s["turn_pass_frac"], s["final_state_pass"]) for s in SESS if s["turn_pass_frac"] is not None]
M("RgPbisAll", hu(pbis(allrows), 2))
crows_.append(r"\midrule")
for f_ in fam:
    rows = [(s["turn_pass_frac"], s["final_state_pass"]) for s in SESS if famof[s["scenario_id"]] == f_ and s["turn_pass_frac"] is not None]
    v = pbis(rows)
    crows_.append(f"family: {f_} & {len(rows)} & {'n/a' if v is None else hu(v, 2)} \\\\")
    M(f"RgPbis{f_.capitalize()}", "n/a" if v is None else hu(v, 2))
write(TABLES / "tp-final-corr.tex", table("l r r", [r"Sessions & n & point-biserial $r$ \\"], crows_, width=r"0.6\textwidth"))


# ================================================================ v3 paper: observatory, A0 counterfactual, replay, S1 hook
import csv as _csv
import os as _os
V3 = REPO / "docs" / "evidence" / "2026-10-v3-offline"
OBS = json.loads((V3 / "a1-observatory" / "observatory-summary.json").read_text())
M("ObEvents", thousands(OBS["store"]["totals"]["events|all"]))
M("ObWeekEvents", thousands(OBS["store"]["week_events"]))
M("ObSessionFiles", thousands(OBS["store"]["session_files"]["events"]))
M("ObProdSessions", OBS["sessions_by_traffic"]["production"])
M("ObTestSessions", thousands(OBS["sessions_by_traffic"]["test"]))
SR = OBS["shadow"]["rates"]
for key, nm in (("all (the 7.1% headline)", "All"), ("real scorer (non-synthetic)", "Real"),
                ("real scorer, host used the candidate tool", "Cand"),
                ("real scorer, host used the candidate tool, not abstained", "CandNA"),
                ("any scorer, host used another tool (unmatchable by construction)", "Unmatch"),
                ("scripted-demo backend (synthetic: always the first candidate)", "Demo"),
                ("production traffic", "Prod")):
    v = SR[key]
    M(f"Ob{nm}Match", thousands(v["match"]))
    M(f"Ob{nm}N", thousands(v["n"]))
    M(f"Ob{nm}Rate", pct(v["rate"], 1))
    M(f"Ob{nm}CI", f"{pct(v['wilson95'][0], 1)}--{pct(v['wilson95'][1], 1)}\\,\\%")
lat = {(x["backend"], x["kind"]): x for x in OBS["latency"]}
jv = lat[("jev", "difficulty_judged:judge_call")]
M("ObJevPfifty", f"{jv['p50_ms']:.0f}")
M("ObJevPninetyfive", f"{jv['p95_ms']:.0f}")
M("ObJevN", jv["n"])
qs = [x for x in OBS["latency"] if "qwen" in str(x.get("model", "")) + str(x.get("backend", "")) and "shadow" in x["kind"]]
qs = qs[0] if qs else [x for x in OBS["latency"] if x["n"] == 993][0]
M("ObQwenPfifty", f"{qs['p50_ms']:.0f}")
M("ObQwenPninetyfive", f"{qs['p95_ms']:.0f}")
M("ObHostPfifty", hu(OBS["slow_end_ms"]["p50"] / 1000, 1))
M("ObHostPninetyfive", hu(OBS["slow_end_ms"]["p95"] / 1000, 1))
M("ObHostN", thousands(OBS["slow_end_ms"]["n"]))
latrows = [("local Qwen3 0.6B, read proposal", qs), ("Jev, start-tier judgement", jv)]
dat("obs-latency.dat", ["y", "label", "p50", "p95"],
    [[i, "{" + l + "}", f"{x['p50_ms']:.1f}", f"{x['p95_ms']:.1f}"] for i, (l, x) in enumerate(latrows)]
    + [[2, "{host model call}", f"{OBS['slow_end_ms']['p50']:.1f}", f"{OBS['slow_end_ms']['p95']:.1f}"]])
WH = OBS["would_have_saved_estimate"]
M("ObClaimTurns", WH["avoided_llm_turns_claimed"])
M("ObClaimDecisions", WH["decisions"])
M("ObClaimSeconds", thousands(round(WH["projected_latency_saved_s"])))
rc = defaultdict(float)
rn = defaultdict(int)
for x in OBS["receipts"]:
    if x["traffic"] == "production":
        rc[x["lever"]] += x["usd_saved_sum"]
        rn[x["lever"]] += x["n"]
M("ObKeepaliveUSD", money(rc["cache_keepalive"]))
M("ObKeepaliveN", rn["cache_keepalive"])
M("ObCheaperUSD", money(rc["cheaper_model"]))
st1 = {(x["reason_code"], x["traffic"]): x["sessions"] for x in OBS["a3_inputs"]["start_tier_first_per_session"]}
prod_total = sum(v for (r_, t_), v in st1.items() if t_ == "production")
M("ObStScope", st1[("scope_strong", "production")])
M("ObStJevStrong", st1[("judge_strong", "production")])
M("ObStJevCheap", st1[("judge_cheap", "production")])
M("ObStTotal", prod_total)
M("ObStScopePct", pct(st1[("scope_strong", "production")] / prod_total))

# A0 counterfactual (all scenarios, both hosts)
A0 = json.loads((V3 / "a0-counterfactual" / "summary.json").read_text())
pol = {(r["host"], r["policy"], r["split"]): r for r in _csv.DictReader(open(V3 / "a0-counterfactual" / "policies.csv"))}
A0ROWS = [("fable", "always_host", "Fable: always host (plain)"), ("fable", "jev_recorded", "Fable: Jev decides once"),
          ("fable", "rule_R*", "Fable: rule R* (always route, scope gate)"), ("fable", "oracle_xfit", "Fable: oracle, equal quality"),
          ("opus", "shipped_jev_price_gate", "Opus: shipped (price gate, never routes)"),
          ("opus", "jev_recorded", "Opus: Jev decides once, no gate"), ("opus", "always_route", "Opus: always route"),
          ("opus", "oracle_xfit", "Opus: oracle, equal quality")]
arows, adat = [], []


def _ci(s):
    return [float(x) for x in s.strip("[]").split(",")]


for i, (h, p, lab) in enumerate(A0ROWS):
    r = pol[(h, p, "all")]
    g, gci, dt, dci = float(r["gm_cost_ratio"]), _ci(r["gm_cost_ratio_ci95"]), float(r["d_turn_pass"]), _ci(r["d_turn_pass_ci95"])
    arows.append(f"{lab} & {pct(float(r['route_share']))}\\,\\% & {hu(g, 3)} [{hu(gci[0], 3)}, {hu(gci[1], 3)}] & "
                 f"{hu(dt, 3)} [{hu(dci[0], 3)}, {hu(dci[1], 3)}] & {money(float(r['usd_per_1000_sessions']), 0)} \\\\")
    key = h.capitalize() + {"always_host": "Host", "jev_recorded": "Jev", "rule_R*": "Rstar", "oracle_xfit": "Oracle",
                            "shipped_jev_price_gate": "Shipped", "always_route": "Route"}[p]
    M(f"Ao{key}", hu(g, 3))
    M(f"Ao{key}CI", f"{hu(gci[0], 3)}--{hu(gci[1], 3)}")
    M(f"Ao{key}Dtp", hu(dt, 3))
    M(f"Ao{key}Regret", money(float(r["regret_usd_per_1000_vs_oracle_xfit"]), 0))
    M(f"Ao{key}Route", pct(float(r["route_share"])))
    if gci[0] != gci[1]:
        adat.append([len(A0ROWS) - 1 - i + (0 if h == "opus" else 1), "{" + lab + "}", f"{g:.4f}", f"{g - gci[0]:.4f}", f"{gci[1] - g:.4f}"])
write(TABLES / "a0-policies.tex", table("l r r r r", [r"Policy (decided once per session) & routed & cost ratio [95\,\% CI] & turn-pass $\Delta$ [95\,\% CI] & \$ / 1,000 \\"], arows))
dat("a0-policies.dat", ["y", "label", "r", "m", "p"], adat)
M("AoTicks", ",".join(str(r[0]) for r in adat))
M("AoLabels", ",".join(r[1] for r in adat))
dg = A0["disagreement"]["fable"]["jev_vs_R*"]
M("AoJevRstarD", hu(dg["d"], 2))
M("AoJevRstarN", dg["n_discordant"])
M("AoJevRstarUnits", dg["n_units"])
M("AoJevRstarUSD", money(dg["implied_mean_cost_diff_usd"]))
EC = A0["effort_cache"]["by_position"]
M("AoEcChanged", thousands(round(EC["sticky_host|changed|within_turn"]["mean_cache_write"])))
M("AoEcUnchanged", thousands(round(EC["sticky_host|unchanged|within_turn"]["mean_cache_write"])))
M("AoEcX", hu(EC["sticky_host|changed|within_turn"]["mean_cache_write"] / EC["sticky_host|unchanged|within_turn"]["mean_cache_write"], 1))
fr = json.loads((REPO / "evals" / "v3" / "frozen_rule.json").read_text())
M("AoScopeFiles", fr.get("spec", fr).get("scope_gate_max_workspace_files", 300) if isinstance(fr, dict) else 300)

# replay of the shipped routing code
RP = json.loads((REPO / "docs" / "evidence" / "2026-10-05-defaults-replay" / "replay.json").read_text())
for m_, K in (("claude-opus-5-5", "Opus"), ("claude-fable-5-1", "Fable")):
    M(f"RpMult{K}", hu(RP["derive"]["multipliers"][m_]["derived"], 2))
M("RpPass", "passed" if RP.get("pass") else "failed")

SH = json.loads((REPO / "evals" / "paired" / "scenarios" / "holdout-v3" / "scenario-hashes.json").read_text())
M("SOnePanelN", SH["n"])
# ---------------------------------------------------------------- S1 hook (holdout-v3)
S1DIR = Path(_os.environ.get("S1_EVIDENCE", str(REPO / "docs" / "evidence" / "2026-10-06-holdout-v3")))  # override only for testing the hook
s1 = None
for name in ("s1_result.json", "confirm.json", "summary.json"):
    f = S1DIR / name
    if f.exists():
        j = json.loads(f.read_text())
        if "hypotheses" in j and "freeze" in j:
            s1, s1name = j, name
            break
FINAL = _os.environ.get("FINAL") == "1"
if s1 is None:
    if FINAL:
        raise SystemExit(f"build_assets.py: FINAL=1 but no S1 result in {S1DIR} "
                         "(need s1_result.json, confirm.json or summary.json with 'hypotheses' and 'freeze')")
    write(OUT / "s1-section.tex", r"""\begin{caution}[title={S1 pending}]
The core study S1 (holdout-v3) had not finished when this preview was built, so this subsection has no results yet.
The final build reads its committed result from \path{docs/evidence/2026-10-06-holdout-v3/} and renders the
preregistered verdicts for H1--H7 and the configuration each host gets under the freeze rule. Until then, the
configuration table below shows the configurations the preregistration predicts, labelled as predictions.
\end{caution}
""")
    M("SOnePending", "1")
else:
    M("SOnePending", "0")
    H = s1["hypotheses"]

    def ci(v):
        return f"{hu(v[0], 3)}--{hu(v[1], 3)}" if v else "--"

    hrows = []
    for h in ("H1", "H2", "H3", "H3b", "H4", "H5", "H6", "H7"):
        if h not in H:
            hrows.append(f"{h} & not computed & & & \\\\")
            continue
        v, e = H[h], H[h]["estimate"]
        verdict = {True: r"\ok\ supported", False: r"\no\ not supported", None: "descriptive"}[v.get("supported")]
        _eq = h in ("H2", "H3", "H3b", "H6")  # equivalence hypotheses are judged on 90% intervals
        hrows.append(f"{h} & {hu(e['gm_ratio'], 3)} ({ci(e.get('gm_ratio_ci90' if _eq else 'gm_ratio_ci95'))}){r'$^{\dagger}$' if _eq else ''} & {hu(e['d_turn_pass'], 3)} "
                     f"({hu(e['d_turn_pass_ci95'][0], 3)} to {hu(e['d_turn_pass_ci95'][1], 3)}) & {'--' if v.get('p_holm') is None else ('$<$\\,0.001' if v['p_holm'] < 0.001 else hu(v['p_holm'], 3))} & {verdict} \\\\")
    write(TABLES / "s1-hypotheses.tex", table("l r r r l", [r"Hypothesis & cost ratio (95\,\% CI$^{\dagger}$) & turn-pass $\Delta$ (95\,\% CI) & Holm $p$ & verdict \\"], hrows)
          + r"\par\smallskip{\footnotesize $^{\dagger}$\,H2, H3, H3b and H6 are equivalence tests; their cost interval is the 90\,\% interval the preregistration uses.}" + "\n")
    frz = s1["freeze"]
    parts = []
    for h in ("fable", "opus"):
        fz = frz[h]
        ch = fz["chosen"] or "the current shipped default (no candidate qualified)"
        parts.append(f"\\item \\textbf{{{h.capitalize()}:}} \\code{{{tex_escape(ch)}}}"
                     + (" (\\emph{selected on holdout}: must replicate in S2 before it ships)" if fz["selected_on_holdout"] else
                        " (the preregistered candidate)" if fz["chosen"] else ""))
        crow = [f"{tex_escape(r['config'])} & {r['class']} & {hu(r['gm_ratio'], 3)} & {ci(r.get('gm_ratio_ci95'))} & "
                f"{ci(r.get('d_turn_pass_ci95'))} & {r'\ok' if r['candidate'] else ''} \\\\" for r in sorted(fz["table"], key=lambda r: r["gm_ratio"])]
        write(TABLES / f"s1-freeze-{h}.tex", table(r">{\raggedright\arraybackslash}p{0.36\textwidth} l r r r c",
              [r"Configuration & class & cost ratio & 95\,\% CI & turn-pass $\Delta$ 95\,\% CI & candidate \\"], crow))
    M("SOneScen", s1.get("n_scenarios", ""))
    M("SOneSessions", thousands(s1.get("health", {}).get("n_sessions", 0)))
    M("SOneDecisionHTwo", tex_escape(H.get("H2", {}).get("decision", "not computed")))
    write(OUT / "s1-section.tex", r"""\begin{table}[htbp]\centering\small
\caption{S1 (holdout-v3) preregistered hypotheses. Cost ratios are geometric means over scenarios; Holm within the two
preregistered families. H3b is descriptive.}\label{tab:s1hyp}
\input{generated/tables/s1-hypotheses.tex}\end{table}
""")

# ---------------------------------------------------------------- S1 details (rendered only when the result exists)
S1EV = S1DIR
if s1 is not None:
    H = s1["hypotheses"]
    for h in ("H1", "H2", "H3", "H3b", "H4", "H5", "H6", "H7"):
        e, k = H[h]["estimate"], h.replace("3b", "ThreeB").replace("1", "One").replace("2", "Two").replace("3", "Three") \
            .replace("4", "Four").replace("5", "Five").replace("6", "Six").replace("7", "Seven")
        M(f"S{k}Ratio", hu(e["gm_ratio"], 3))
        M(f"S{k}CI", f"{hu(e['gm_ratio_ci95'][0], 3)}--{hu(e['gm_ratio_ci95'][1], 3)}")
        M(f"S{k}CINinety", f"{hu(e['gm_ratio_ci90'][0], 3)}--{hu(e['gm_ratio_ci90'][1], 3)}")
        M(f"S{k}Dtp", hu(e["d_turn_pass"], 3))
        M(f"S{k}DtpCI", f"{hu(e['d_turn_pass_ci95'][0], 3)} to {hu(e['d_turn_pass_ci95'][1], 3)}")
        M(f"S{k}DtpLow", hu(e["d_turn_pass_ci95"][0], 3))
        M(f"S{k}N", e["n_scenarios"])
        M(f"S{k}Verdict", {True: "supported", False: "not supported", None: "descriptive"}[H[h]["supported"]])
    M("SHTwoDisc", H["H2"]["discordant_scenario_reps"])
    M("SThreshOne", re.search(r"< ([0-9.]+)", H["H1"]["rule"]).group(1))
    M("SResamples", thousands(s1["resamples"]))
    M("SHTwoReps", H["H2"]["n_scenario_reps"])
    pr = A0["s1_predictions"]["C*_F"]
    M("SPredRatio", hu(pr["gm_cost_ratio"], 3))
    M("SPredCI", f"{hu(pr['gm_cost_ratio_ci95'][0], 3)}--{hu(pr['gm_cost_ratio_ci95'][1], 3)}")
    assert H["H1"]["estimate"]["gm_ratio"] > pr["gm_cost_ratio_ci95"][1], "H1 observed now inside the prediction: fix the text"
    fz = s1["freeze"]
    chosen_f = [r for r in fz["fable"]["table"] if r["config"] == fz["fable"]["chosen"]][0]
    M("SFreezeFable", tex_escape(fz["fable"]["chosen"]))
    M("SFreezeFableRatio", hu(chosen_f["gm_ratio"], 3))
    M("SFreezeFablePrereg", tex_escape(fz["fable"]["preregistered_C*"]))
    assert fz["fable"]["selected_on_holdout"] and fz["opus"]["chosen"] is None
    M("SNoiseOpusDtp", hu(s1["noise_floor"]["opus"]["d_turn_pass"], 3))
    M("SNoiseN", s1["noise_floor"]["opus"]["n"])
    led = json.loads((S1EV / "campaign" / "ledger.json").read_text())
    M("SSpend", money(sum(led["spent"].values()) if isinstance(led["spent"], dict) else led["spent"]))
    M("SBudgetFinal", thousands(int(led["budget_usd"])))
    fails_md = (S1EV / "FAILURES.md").read_text()
    m_ = re.search(r"Budget cap raised (\d+) -> (\d+)", fails_md)
    M("SBudgetOrig", thousands(int(m_.group(1))))
    assert int(m_.group(2)) == int(led["budget_usd"])
    stt = json.loads((S1EV / "campaign" / "state.json").read_text())["waves"]
    att = [a["status"] for w in stt.values() for a in w["attempts"]]
    M("SAttempts", len(att))
    M("SInfraAttempts", sum(1 for a in att if a == "infra_failed"))
    M("SInfraPct", pct(sum(1 for a in att if a == "infra_failed") / len(att)))
    ss = [json.loads(x) for x in (S1EV / "data" / "sessions.jsonl").read_text().splitlines() if x.strip()]
    bad = [x for x in ss if not x.get("mechanism_engaged", True)]
    M("SGateFail", len(bad))
    M("SGateScen", tex_escape(sorted({x["scenario_id"] for x in bad})[0]))
    rob_same = True
    for sub in ("robustness-drop_bleach", "robustness-drop_bleach_and_black_pipeline"):
        rj = json.loads((S1EV / "result" / sub / "s1_result.json").read_text())
        rob_same &= all(rj["hypotheses"][h]["supported"] == H[h]["supported"] for h in H)
        rob_same &= rj["freeze"]["fable"]["chosen"] == fz["fable"]["chosen"] and rj["freeze"]["opus"]["chosen"] == fz["opus"]["chosen"]
    assert rob_same, "robustness reruns changed a verdict: fix the text"

# ---------------------------------------------------------------- keep_on_host under the rule decider: keyword proxy (exploratory replay)
if s1 is not None:
    import importlib as _il
    import yaml as _yaml2
    _sys.path.insert(0, str(REPO / "evals" / "v3"))
    _A = _il.import_module("s1_analysis")
    _RL = _il.import_module("rules")
    M("KpClassifier", tex_escape(_RL.INTENT_CLASSIFIER))
    prom = {}
    for sub in ("holdout-v3", "main-v1", "pilot-v1"):
        for f in sorted((REPO / "evals" / "paired" / "scenarios" / sub).rglob("*.yaml")):
            y = _yaml2.safe_load(f.read_text())
            if isinstance(y, dict) and "turns" in y and "id" in y:
                prom[y["id"]] = (y.get("task_type"), y["turns"][0]["prompt"])
    kept = {s for s, (t, p) in prom.items() if _RL.classify_intent(p) == "question"}
    rex = [s for s, (t, p) in prom.items() if t in _A.KEEP_TYPES]
    caught = sum(1 for s in rex if s in kept)
    M("KpPrompts", len(prom))
    M("KpRexN", len(rex))
    M("KpCaught", caught)
    M("KpOthers", len(kept) - caught)
    M("KpPrecision", pct(caught / len(kept)))
    rows_s1 = [json.loads(x) for x in (S1EV / "data" / "sessions.jsonl").read_text().splitlines() if x.strip()]
    dd = _A.Data(rows_s1)
    bb = _A.Boot(dd.scenarios, s1["resamples"], s1["seed"])
    base_f = _A.arm_outcomes(dd, "fable", "anchor")
    orc = _A.contrast(_A.policy(dd, "fable", decider="rstar", strong="medium", scope=True, keep=_A.KEEP_TYPES), base_f, bb)
    for s in dd.scenarios:
        dd.meta[s]["task_type"] = "explain" if s in kept else "bugfix"
    prx = _A.contrast(_A.policy(dd, "fable", decider="rstar", strong="medium", scope=True, keep=_A.KEEP_TYPES), base_f, bb)
    for nm, c in (("Oracle", orc), ("Proxy", prx)):
        M(f"Kp{nm}Ratio", hu(c["gm_ratio"], 3))
        M(f"Kp{nm}CI", f"{hu(c['gm_ratio_ci95'][0], 3)}--{hu(c['gm_ratio_ci95'][1], 3)}")
        M(f"Kp{nm}Dtp", hu(c["d_turn_pass"], 3))
    M("KpProxyTwo", hu(prx["gm_ratio"], 2))
    M("KpRstarTwo", hu(H["H1"]["estimate"]["gm_ratio"], 2))


# ================================================================ v3 rich: figure data (S1 and cross-study)
if s1 is not None:
    rowsR = [json.loads(x) for x in (S1EV / "data" / "sessions.jsonl").read_text().splitlines() if x.strip()]
    DR = _A.Data(rowsR)
    BR = _A.Boot(DR.scenarios, s1["resamples"], s1["seed"])
    famS = {}
    for f in sorted((REPO / "evals" / "paired" / "scenarios" / "holdout-v3").glob("*/*.yaml")):
        y = _yaml2.safe_load(f.read_text())
        if isinstance(y, dict) and "id" in y:
            famS[y["id"]] = f.parent.name
    anchF, anchO = _A.arm_outcomes(DR, "fable", "anchor"), _A.arm_outcomes(DR, "opus", "anchor")
    cstarF = _A.policy(DR, "fable", decider="rstar", strong="medium", scope=True)
    pcO = _A.arm_outcomes(DR, "opus", "pc")

    # --- F2: S1 forest (cost and quality panels)
    HLAB = {"H1": "H1 Fable frozen config vs plain", "H2": "H2 Jev vs rule R* (Fable)", "H3": "H3 bundle overhead, Opus",
            "H3b": "H3b bundle overhead, Fable", "H4": "H4 Opus medium vs default", "H5": "H5 Sonnet vs plain Opus",
            "H6": "H6 live vs predicted (Fable)", "H7": "H7 Sonnet vs Fable, review+explain"}
    order = ["H1", "H2", "H3", "H3b", "H4", "H5", "H6", "H7"]
    fr_rows = []
    for i, h in enumerate(order):
        e = H[h]["estimate"]
        y = len(order) - 1 - i
        fr_rows.append([y, "{" + HLAB[h] + "}", f"{e['gm_ratio']:.4f}", f"{e['gm_ratio'] - e['gm_ratio_ci95'][0]:.4f}",
                        f"{e['gm_ratio_ci95'][1] - e['gm_ratio']:.4f}", f"{e['d_turn_pass']:.4f}",
                        f"{e['d_turn_pass'] - e['d_turn_pass_ci95'][0]:.4f}", f"{e['d_turn_pass_ci95'][1] - e['d_turn_pass']:.4f}"])
    dat("s1-forest.dat", ["y", "label", "r", "rm", "rp", "d", "dm", "dp"], fr_rows)

    # --- F3: freeze candidates (numbered, label-placed)
    LP.configure(OUT, DATA, 10.6, 5.2)
    fz = s1["freeze"]
    keyrows = []
    for h in ("fable", "opus"):
        tab = sorted(fz[h]["table"], key=lambda r: (r["gm_ratio"], r["config"]))
        groups_ = []  # merge configurations that land on (nearly) the same point
        for r in tab:
            for g in groups_:
                if abs(g["x"] - r["gm_ratio"]) < 0.012 and abs(g["y"] - r["d_turn_pass"]) < 0.0045:
                    g["rows"].append(r)
                    break
            else:
                groups_.append({"x": r["gm_ratio"], "y": r["d_turn_pass"], "rows": [r]})
        pts, cand, non = [], [], []
        for j, g in enumerate(groups_, 1):
            k = f"{h[0].upper()}{j}"
            for r in g["rows"]:
                keyrows.append(f"{k} & {h.capitalize()} & {tex_escape(r['config'])} & {r['gm_ratio']:.3f} & {r['d_turn_pass']:.3f} & "
                               + (r"\ok" if r["candidate"] else "") + r" \\")
                (cand if r["candidate"] else non).append([f"{r['gm_ratio']:.4f}", f"{r['d_turn_pass']:.4f}"])
            pts.append((k, k, g["x"], g["y"]))
        xs = [p[2] for p in pts]
        ys = [p[3] for p in pts]
        xr = (min(xs) - 0.05, max(xs) + 0.05)
        yr = (min(ys) - 0.012, max(ys) + 0.012)
        M(f"Fz{h.capitalize()}Xmin", f"{xr[0]:.3f}"); M(f"Fz{h.capitalize()}Xmax", f"{xr[1]:.3f}")
        M(f"Fz{h.capitalize()}Ymin", f"{yr[0]:.3f}"); M(f"Fz{h.capitalize()}Ymax", f"{yr[1]:.3f}")
        dat(f"fz-{h}-cand.dat", ["x", "y"], cand or [["nan", "nan"]])
        dat(f"fz-{h}-non.dat", ["x", "y"], non or [["nan", "nan"]])
        ch = [r for r in tab if r["config"] == fz[h]["chosen"]]
        pre = [r for r in tab if r["config"] == fz[h]["preregistered_C*"]]
        plots = []
        sty = {"cand": r"only marks, mark=*, mark size=2.4pt, color=okblue",
               "non": r"only marks, mark=o, mark size=2.4pt, color=okgray, mark options={line width=0.9pt}",
               "chosen": r"only marks, mark=star, mark size=5pt, color=okorange, mark options={line width=1.3pt}",
               "prereg": r"only marks, mark=diamond, mark size=4.5pt, color=okgreen, mark options={line width=1.3pt}"}
        nonempty = {"cand": bool(cand), "non": bool(non),
                    "chosen": any(r["config"] == fz[h]["chosen"] for r in tab),
                    "prereg": any(r["config"] == fz[h]["preregistered_C*"] for r in tab)}
        for kk, lab in (("cand", "candidate"), ("non", "not a candidate"), ("chosen", "chosen by the freeze rule"), ("prereg", "preregistered C*")):
            if nonempty[kk]:
                plots.append(f"\\addplot[{sty[kk]}] table[x=x, y=y]{{generated/data/fz-{h}-{kk}.dat}};")
                plots.append(f"\\addlegendentry{{{lab}}}")
            else:
                plots.append(f"\\addlegendimage{{{sty[kk]}}}\\addlegendentry{{{lab}}}")
        write(OUT / f"fz-{h}-plots.tex", "\n".join(plots) + "\n")
        dat(f"fz-{h}-chosen.dat", ["x", "y"], [[f"{r['gm_ratio']:.4f}", f"{r['d_turn_pass']:.4f}"] for r in ch] or [["nan", "nan"]])
        dat(f"fz-{h}-prereg.dat", ["x", "y"], [[f"{r['gm_ratio']:.4f}", f"{r['d_turn_pass']:.4f}"] for r in pre] or [["nan", "nan"]])
        LP.place_labels(f"fz-{h}", pts, xr, yr)
        M(f"Fz{h.capitalize()}N", len(tab))
        M(f"Fz{h.capitalize()}Groups", len(groups_))
        M(f"Fz{h.capitalize()}Cand", sum(1 for r in tab if r["candidate"]))
    write(TABLES / "fz-key.tex", table(r"l l >{\raggedright\arraybackslash}p{0.5\textwidth} r r c",
                                       [r"Key & Host & Configuration & cost ratio & turn-pass $\Delta$ & candidate \\"], keyrows))
    hdr = r"\toprule Key & Host & Configuration & {cost ratio} & {turn-pass $\Delta$} & candidate \\ \midrule"
    write(TABLES / "fz-key-long.tex", "\\begin{xltabular}{\\textwidth}{l l >{\\raggedright\\arraybackslash}X S[table-format=1.3] S[table-format=-1.3] c}\n"
          + r"\caption{Every configuration the S1 freeze rule considered (keys as in \cref{fig:fz}). Cost ratio and turn-pass difference against the host's plain default.}\label{tab:fzkey}\\" + "\n"
          + hdr + r" \endfirsthead" + "\n" + hdr + r" \endhead" + "\n" + "\n".join(keyrows) + "\n\\bottomrule\n\\end{xltabular}\n")

    # --- F4: Fable routing by task type and by family (C*_F vs plain Fable)
    sub_rows = []
    groups = [("task", t) for t in ("bugfix", "feature", "mixed", "docs", "explain", "review")] + \
             [("family", f) for f in ("polyglot", "repos", "mixed", "knowledge")]
    for i, (kind, g) in enumerate(groups):
        subset = {s for s in DR.scenarios if (DR.meta[s]["task_type"] if kind == "task" else famS.get(s)) == g}
        c = _A.contrast(cstarF, anchF, BR, subset=subset)
        y = len(groups) - 1 - i + (0 if kind == "family" else 1)
        lab = ("task: " if kind == "task" else "family: ") + g + f" ({c['n_scenarios']})"
        sub_rows.append([y, "{" + lab + "}", f"{c['gm_ratio']:.4f}", f"{c['gm_ratio'] - c['gm_ratio_ci95'][0]:.4f}",
                         f"{c['gm_ratio_ci95'][1] - c['gm_ratio']:.4f}", f"{c['d_turn_pass']:.4f}",
                         f"{c['d_turn_pass'] - c['d_turn_pass_ci95'][0]:.4f}", f"{c['d_turn_pass_ci95'][1] - c['d_turn_pass']:.4f}"])
        M(f"Sub{g.capitalize()}{kind.capitalize()}Dtp", hu(c["d_turn_pass"], 3))
        M(f"Sub{g.capitalize()}{kind.capitalize()}Low", hu(c["d_turn_pass_ci95"][0], 3))
        M(f"Sub{g.capitalize()}{kind.capitalize()}Ratio", hu(c["gm_ratio"], 3))
    dat("s1-subgroups.dat", ["y", "label", "r", "rm", "rp", "d", "dm", "dp"], sub_rows)
    M("SubTicks", ",".join(str(r[0]) for r in sub_rows))
    M("SubLabels", ",".join(r[1] for r in sub_rows))

    # --- F5: per-scenario paired ratios
    def per_scen(a, b):
        out = {}
        for s in DR.scenarios:
            ok = [k for k in a if k[0] == s and k in b and a[k]["_cost_ok"] and b[k]["_cost_ok"]]
            if ok:
                ca = _st.mean(_A.cost(a[k]) for k in ok)
                cb = _st.mean(_A.cost(b[k]) for k in ok)
                out[s] = (ca / cb, ok, ca, cb)
        return out
    psF, psO = per_scen(cstarF, anchF), per_scen(pcO, anchO)
    for nm, ps in (("fable", psF), ("opus", psO)):
        vals = sorted(v[0] for v in ps.values())
        dat(f"perscen-{nm}.dat", ["x", "r"], [[i + 1, f"{v:.4f}"] for i, v in enumerate(vals)])
        M(f"Ps{nm.capitalize()}N", len(vals))
        M(f"Ps{nm.capitalize()}Min", hu(vals[0], 2))
        M(f"Ps{nm.capitalize()}Max", hu(vals[-1], 2))
        M(f"Ps{nm.capitalize()}Above", sum(1 for v in vals if v > 1))
    # worked example: the Fable scenario whose ratio is closest to the geometric mean
    gmF = math.exp(_st.mean(math.log(v[0]) for v in psF.values()))
    wx = min(psF, key=lambda s: abs(math.log(psF[s][0]) - math.log(gmF)))
    r_, ok_, ca_, cb_ = psF[wx]
    M("WxScen", tex_escape(wx).replace("-", "-\\allowbreak{}"))
    M("WxReps", len(ok_))
    M("WxRouted", money(ca_))
    M("WxPlain", money(cb_))
    M("WxRatio", hu(r_, 3))
    M("WxLog", hu(math.log(r_), 3))
    M("WxArm", "routed to Sonnet" if cstarF[ok_[0]]["arm"] == "pc" else "kept on Fable")
    M("WxGM", hu(gmF, 3))
    M("WxNScen", len(psF))
    M("WxKeptByProxy", "kept on Fable" if wx in kept else "routed to Sonnet")
    M("WxTaskType", DR.meta[wx]["task_type"])

    # --- F6: decision model vs rule: discordant scenario-reps and the bound
    jevP = _A.policy(DR, "fable", decider="jev", strong="medium", scope=True)
    disc = sorted(k for k in jevP if k in cstarF and jevP[k]["arm"] != cstarF[k]["arm"])
    drows, dcost, dtp_ = [], [], []
    for k in disc:
        a, b = jevP[k], cstarF[k]
        dc = _A.cost(a) - _A.cost(b)
        dcost.append(dc)
        dtp_.append(a["turn_pass_frac"] - b["turn_pass_frac"])
        nm = lambda r: "Sonnet (Pc)" if r["arm"] == "pc" else "Fable, medium"
        drows.append(f"{tex_escape(k[0])} & {k[1]} & {nm(a)} & {nm(b)} & \\${money(_A.cost(a))} & \\${money(_A.cost(b))} & "
                     f"{hu(a['turn_pass_frac'], 3)} & {hu(b['turn_pass_frac'], 3)} \\\\")
    write(TABLES / "discordant.tex", table("l r l l r r r r", [
        r" & & \multicolumn{2}{c}{model chosen by} & \multicolumn{2}{c}{session cost} & \multicolumn{2}{c}{turn-pass} \\",
        r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}\cmidrule(l){7-8}",
        r"Scenario & rep & Jev & rule R* & Jev & R* & Jev & R* \\"], drows))
    nrep = len([k for k in jevP if k in cstarF])
    meanF = _st.mean(_A.cost(cstarF[k]) for k in cstarF)
    M("DcN", len(disc)); M("DcUnits", nrep)
    M("DcD", hu(len(disc) / nrep, 3))
    M("DcMeanDiff", money(_st.mean(dcost)))
    M("DcMeanAbsDiff", money(_st.mean(abs(x) for x in dcost)))
    M("DcBound", money(len(disc) / nrep * _st.mean(abs(x) for x in dcost), 3))
    M("DcMeanCost", money(meanF))
    M("DcBoundPct", pct(len(disc) / nrep * _st.mean(abs(x) for x in dcost) / meanF, 1))

    # --- F7: effort across hosts (three studies)
    eff_rows = []
    effs = [("Sonnet 5 (follow-up 1)", ej["rows"][0]["gm_ratio"], ej["rows"][0]["ci95"], ej["quality"]["mean_delta_turn_pass"], ej["quality"]["ci95"]),
            ("Fable 5.1 (follow-up 2)", f1["gm_ratio"], f1["ci95"], fq["mean_delta_turn_pass"], fq["ci95"]),
            ("Opus 5.5 (S1, H4)", H["H4"]["estimate"]["gm_ratio"], H["H4"]["estimate"]["gm_ratio_ci95"],
             H["H4"]["estimate"]["d_turn_pass"], H["H4"]["estimate"]["d_turn_pass_ci95"])]
    for i, (lab, g, ci, d, dci) in enumerate(effs):
        eff_rows.append([2 - i, "{" + lab + "}", f"{g:.4f}", f"{g - ci[0]:.4f}", f"{ci[1] - g:.4f}", f"{d:.4f}", f"{d - dci[0]:.4f}", f"{dci[1] - d:.4f}"])
    dat("effort-hosts.dat", ["y", "label", "r", "rm", "rp", "d", "dm", "dp"], eff_rows)

    # --- F8: where the money goes (S1, mean $ per session by token class)
    groupsC = [("plain Fable", lambda r: r["host"] == "fable" and r["arm"] == "anchor"),
               ("shipped, Fable host", lambda r: r["host"] == "fable" and r["arm"] == "shipped"),
               ("Sonnet decided once (Pc)", lambda r: r["arm"] == "pc"),
               ("plain Opus", lambda r: r["host"] == "opus" and r["arm"] == "anchor")]
    comp_rows = []
    for i, (lab, fn) in enumerate(groupsC):
        ss = [r for r in rowsR if fn(r) and r.get("cost_valid")]
        acc = [0.0, 0.0, 0.0, 0.0]
        for r in ss:
            for mdl, tk in r["tokens"].items():
                pr = PRICE.get(mdl)
                if pr is None:
                    continue
                for j, cls in enumerate(("input", "cache_read", "cache_write", "output")):
                    acc[j] += tk.get(cls, 0) * pr[j] / 1e6
        acc = [a / len(ss) for a in acc]
        comp_rows.append([3 - i, "{" + lab + "}"] + [f"{a:.4f}" for a in acc])
        key = "".join(w.capitalize() for w in re.sub(r"[^a-z ]", "", lab.lower()).split())[:14]
        M(f"Cc{key}Total", money(sum(acc)))
        M(f"Cc{key}ReadShare", pct(acc[1] / sum(acc)))
        M(f"Cc{key}WriteShare", pct(acc[2] / sum(acc)))
    dat("s1-composition.dat", ["y", "label", "inp", "rd", "wr", "out"], comp_rows)

    # --- F9: cumulative evidence for routing, per host
    PIL = [json.loads(x) for x in (REPO / "docs/evidence/2026-10-02-paired-campaign/pilot/pairs.jsonl").read_text().splitlines() if x.strip()]
    cum = []

    def gmci(vals, cl, key):
        e, lo, hi, n = PM.cluster_boot_mean(vals, cl, PM.rng_for(20261005, *key), 10000)
        return math.exp(e), math.exp(lo), math.exp(hi), n
    for h in ("fable", "opus"):
        pv = [p for p in PIL if p["host"] == h and p["arm"] == "sticky" and p.get("valid", p.get("cost_valid", True)) and p.get("log_cost_ratio") is not None]
        stages = [("pilot (sticky, 5 scenarios)", gmci([p["log_cost_ratio"] for p in pv], [p["scenario_id"] for p in pv], ("cum", h, "pilot")))]
        for sp in ("train", "test"):
            rr = [r for r in PM._cost_rows(DS["pairs"]) if r["host"] == h and r["arm"] == "sticky" and r["split"] == sp]
            stages.append((f"main-v1 {sp} (sticky)", gmci([r["y"] for r in rr], [r["scenario"] for r in rr], ("cum", h, sp))))
        e = H["H1" if h == "fable" else "H5"]["estimate"]
        stages.append(("S1 holdout (" + ("frozen config, H1" if h == "fable" else "Sonnet, H5") + ")",
                       (e["gm_ratio"], e["gm_ratio_ci95"][0], e["gm_ratio_ci95"][1], e["n_scenarios"])))
        for j, (lab, (g, lo, hi, n)) in enumerate(stages):
            cum.append([(3 - j) + (5 if h == "fable" else 0), "{" + f"{h.capitalize()}: {lab}" + "}", f"{g:.4f}", f"{g - lo:.4f}", f"{hi - g:.4f}"])
            M(f"Cum{h.capitalize()}{['Pilot', 'Train', 'Test', 'Sone'][j]}", hu(g, 3))
            M(f"Cum{h.capitalize()}{['Pilot', 'Train', 'Test', 'Sone'][j]}N", n)
    dat("cumulative.dat", ["y", "label", "r", "rm", "rp"], cum)
    M("CumTicks", ",".join(str(r[0]) for r in cum))
    M("CumLabels", ",".join(r[1] for r in cum))

    # --- F10a: observatory event mix and latency by backend
    hm = list(_csv.DictReader(open(V3 / "a1-observatory" / "health_mix.csv")))
    hm = sorted([r for r in hm if r["store"] == "events"], key=lambda r: -float(r["share_of_store_events"]))[:7]
    dat("obs-mix.dat", ["y", "label", "share"], [[len(hm) - 1 - i, "{" + r["health_kind"].replace("_", " ") + "}",
                                                  f"{100 * float(r['share_of_store_events']):.2f}"] for i, r in enumerate(hm)])
    M("ObMixTop", hm[0]["health_kind"].replace("_", " "))
    M("ObMixTopPct", pct(float(hm[0]["share_of_store_events"]), 1))

    # --- Findings at a glance
    def ci2(v):
        return f"{hu(v[0], 3)}--{hu(v[1], 3)}"
    FIND = [
        ("Decision calls are fast next to host calls", f"Jev p50 \\ObJevPfifty{{}}\\,ms; host p50 \\ObHostPfifty{{}}\\,s", "observatory", "measured"),
        ("Shadow ``agreement'' was mostly unmatchable", f"\\ObUnmatchN{{}} of \\ObAllN{{}} could not match", "observatory", "measured"),
        ("No accuracy difference detected between Jev and the best judges (after correction); Jev cheapest", f"\\JevHoldAccK{{}}/\\HoldN{{}} correct", "judge benchmark", "preregistered"),
        ("No judge useful on real read decisions", f"\\TrNUseful{{}} of \\NumBase{{}} judges", "trace study", "preregistered"),
        ("Routing on Fable saves", f"\\CfFableStickyPairTwo{{}}\\X\\ (\\CfFableStickyPairCITwo{{}})", "main-v1", "preregistered"),
        ("Routing on Fable saves, fresh scenarios", f"{hu(H['H1']['estimate']['gm_ratio'], 3)}\\X\\ ({ci2(H['H1']['estimate']['gm_ratio_ci95'])})", "S1, H1", "preregistered, replicated"),
        ("Routing on Opus costs more", f"{hu(H['H5']['estimate']['gm_ratio'], 3)}\\X\\ ({ci2(H['H5']['estimate']['gm_ratio_ci95'])})", "S1, H5", "preregistered, replicated"),
        ("Rule R* equals the decision model at session start", f"{hu(H['H2']['estimate']['gm_ratio'], 3)}\\X\\ (90\\,\\% {ci2(H['H2']['estimate']['gm_ratio_ci90'])})", "S1, H2", "preregistered"),
        ("Bundle cost-equivalent on Opus within the preregistered $\\pm$5\\,\\% margin", f"{hu(H['H3']['estimate']['gm_ratio'], 3)}\\X\\ (90\\,\\% {ci2(H['H3']['estimate']['gm_ratio_ci90'])})", "S1, H3", "preregistered"),
        ("Medium effort: Sonnet", f"\\EcRatio{{}}\\X\\ (\\EcCI{{}})", "follow-up 1", "preregistered, provenance-limited"),
        ("Medium effort: Fable", f"\\EfRatio{{}}\\X\\ (\\EfCI{{}})", "follow-up 2", "preregistered"),
        ("Medium effort on Opus: saving not demonstrated", f"{hu(H['H4']['estimate']['gm_ratio'], 3)}\\X\\ ({ci2(H['H4']['estimate']['gm_ratio_ci95'])})", "S1, H4", "preregistered"),
        ("Noninferiority not established for review/explain on Sonnet", f"lower bound {hu(H['H7']['estimate']['d_turn_pass_ci95'][0], 3)}", "S1, H7", "preregistered"),
        ("Live decide-once equals its prediction", f"{hu(H['H6']['estimate']['gm_ratio'], 3)}\\X\\ (90\\,\\% {ci2(H['H6']['estimate']['gm_ratio_ci90'])})", "S1, H6", "preregistered"),
        ("Effort switches rewrite the cache", f"\\CwWithinX{{}}\\X\\ cache writes vs the plain host", "main-v1 re-analysis", "exploratory"),
        ("Keyword proxy keeps quality at a cost", f"\\KpProxyRatio{{}}\\X, turn-pass \\KpProxyDtp{{}}", "S1 replay", "exploratory"),
    ]
    write(TABLES / "findings.tex", table(r">{\raggedright\arraybackslash}p{0.30\textwidth} >{\raggedright\arraybackslash}p{0.25\textwidth} l >{\raggedright\arraybackslash}p{0.17\textwidth}",
                                         [r"Finding & Number (95\,\% CI unless noted) & Study & Evidence \\"],
                                         [f"{a} & {b} & {c} & {d} \\\\" for a, b, c, d in FIND]))

    # --- Configuration recipe: the shipped orchestrator config, verbatim from behaviors/fast-decisions.yaml
    beh = (REPO / "behaviors" / "fast-decisions.yaml").read_text().splitlines()
    i0 = next(i for i, l in enumerate(beh) if l.strip() == "config:" and i > 0 and "orchestrator" in "".join(beh[max(0, i - 3):i]))
    blk = []
    for l in beh[i0:]:
        if blk and l.strip() and not l.startswith("      ") and not l.startswith("    config"):
            break
        if l.strip().startswith("#"):
            continue
        blk.append(l[4:] if l.startswith("    ") else l)
    write(OUT / "recipe-shipped.yaml", "\n".join(b for b in blk if b.strip()) + "\n")
    M("BundleVersion", re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M).group(1))


# ---------------------------------------------------------------- row identity: ascending rows + a printed value per row
# Every bar/forest chart prints its row's value next to the row (column v); check_figures.py verifies that each rendered
# row label sits beside its own value. Charts whose tick labels come from `yticklabels from table` must list rows in
# ascending y, the order pgfplots assigns those labels to ascending ticks.
ROWVALUE = {  # file -> (sort ascending?, value column(s), format)
    "obs-latency.dat": (True, ["p95"], lambda v: f"{float(v[0]):,.0f}"),
    "obs-mix.dat": (True, ["share"], lambda v: f"{float(v[0]):.1f}"),
    "a0-policies.dat": (False, ["r"], lambda v: f"{float(v[0]):.3f}"),
    "forest.dat": (True, ["pair"], lambda v: f"{float(v[0]):.3f}"),
    "forest-h3.dat": (True, ["pair"], lambda v: f"{float(v[0]):.3f}"),
    "s1-forest.dat": (True, ["r"], lambda v: f"{float(v[0]):.3f}"),
    "s1-subgroups.dat": (False, ["r"], lambda v: f"{float(v[0]):.3f}"),
    "effort-hosts.dat": (True, ["r"], lambda v: f"{float(v[0]):.3f}"),
    "s1-composition.dat": (True, ["inp", "rd", "wr", "out"], lambda v: f"{sum(float(x) for x in v):.2f}"),
    "cumulative.dat": (False, ["r"], lambda v: f"{float(v[0]):.3f}"),
}
for fname, (asc, cols, fmt) in ROWVALUE.items():
    f = DATA / fname
    lines = f.read_text().splitlines()
    head = lines[0].split()
    rows = []
    for ln in lines[1:]:
        lab = re.search(r"\{[^}]*\}", ln).group(0)
        rest = ln.replace(lab, "LABEL", 1).split()
        rows.append([lab if x == "LABEL" else x for x in rest])
    if asc:
        rows.sort(key=lambda r: float(r[head.index("y")]))
    if "v" not in head:
        head.append("v")
        for r in rows:
            r.append(fmt([r[head.index(c)] for c in cols]))
    write(f, "\n".join([" ".join(head)] + [" ".join(r) for r in rows]) + "\n")

# composition: the stacked bars' totals as explicit nodes (nodes near coords cannot label a stack's end)
_cl = (DATA / "s1-composition.dat").read_text().splitlines()
_h = _cl[0].split()
_nodes = []
for ln in _cl[1:]:
    lab = re.search(r"\{[^}]*\}", ln).group(0)
    r = ln.replace(lab, "L", 1).split()
    tot = sum(float(r[_h.index(c)]) for c in ("inp", "rd", "wr", "out"))
    _nodes.append(f"\\node[anchor=west, font=\\scriptsize, text=black!80] at (axis cs:{tot:.4f},{r[0]}) {{{r[_h.index('v')]}}};")
write(OUT / "composition-totals.tex", "\n".join(_nodes) + "\n")

# ================================================================ round-3 review additions
_wk = OBS["store"]["week"]
M("ObWeekStart", _wk[0])
M("ObWeekEnd", _wk[1])
M("ObCutoff", OBS["store"]["cutoff_utc"][:10])
_pr = (REPO / "docs" / "evidence" / "2026-10-06-holdout-v3" / "prereg" / "PREREGISTRATION-holdout-v3.md").read_text()
_m = re.search(r"smoke run \((\d+) plain-Sonnet sessions, \$([\d.,]+), mean turn-pass ([\d.]+)\) led to defect\s+fixes in (\d+) scenarios", _pr)
M("SmokeN", _m.group(1))
M("SmokeUSD", _m.group(2))
M("SmokeFixed", _m.group(4))


def _norm_share(d):
    ss = [s for s in jsonl(REPO / "docs" / "evidence" / d / "data" / "sessions.jsonl")
          if s.get("cost_valid") and s.get("cost_usd_recomputed") is not None]
    a = sum(s["cost_usd_recomputed"] for s in ss)
    b = sum(s["cost_usd_tools_normalized"] for s in ss)
    return (a - b) / a


M("NormShareMain", pct(_norm_share("2026-10-02-paired-campaign"), 2))
M("NormShareSone", pct(_norm_share("2026-10-06-holdout-v3"), 3))
if s1 is not None:
    M("SHSevenQualN", len({s for s in DR.scenarios if DR.meta[s]["task_type"] in _A.KEEP_TYPES}))


# ---------------------------------------------------------------- OpenAI Decisions API judge (post hoc; rendered only if committed)
OAI = Path(_os.environ.get("OPENAI_DECISIONS_EVIDENCE", str(REPO / "docs" / "evidence" / "2026-10-06-openai-decisions")))
oai_tex = ""
if (OAI / "summary.json").exists():
    oj = json.loads((OAI / "summary.json").read_text())
    try:
        ORW = {(r["split"], r["arm"]): r for r in oj["rows"]}
        SPL = ["dev", "holdout", "trace-dev", "trace-holdout"]
        LUNA, JEV = "luna-decisions", "jev-1.13"
        assert all((s, a) in ORW for s in SPL for a in (LUNA, JEV))
    except (KeyError, TypeError, AssertionError) as exc:
        raise SystemExit(f"build_assets.py: {OAI}/summary.json lacks the expected rows: {exc!r}")

    def _wil(k, n, z=1.959964):
        p = k / n
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return c - h, c + h
    trows, frows = [], []
    for i, s in enumerate(SPL):
        for j, a in enumerate((LUNA, JEV)):
            r = ORW[(s, a)]
            k = round(r["accuracy"] * r["n"])
            K = "".join(w.capitalize() for w in s.split("-")) + ("Luna" if a == LUNA else "Jev")
            M(f"Oa{K}K", k)
            M(f"Oa{K}N", r["n"])
            M(f"Oa{K}Usd", hu(r["usd_per_1m"], 1))
            trows.append(f"{s} & {'GPT-6 Luna, Decisions API' if a == LUNA else 'Jev 1.13 (in-run reference)'} & {k}/{r['n']} & "
                         f"{100 * r['wrong_automatic']:.1f} & {100 * r['coverage']:.1f} & {r['p50_ms'] / 1000:.2f} & "
                         f"{r['p95_ms'] / 1000:.2f} & {r['usd_per_1m']:.1f} \\\\")
            lo, hi = _wil(k, r["n"])
            y = (len(SPL) - 1 - i) * 3 + (1 - j)
            frows.append([y, "{" + f"{s}: {'Luna (Decisions API)' if a == LUNA else 'Jev 1.13'}" + "}", f"{k / r['n']:.4f}",
                          f"{k / r['n'] - lo:.4f}", f"{hi - k / r['n']:.4f}", f"{k / r['n']:.3f}"])
        if i < len(SPL) - 1:
            trows.append(r"\addlinespace[2pt]")
    write(TABLES / "openai-decisions.tex", table("l l r S[table-format=2.1] S[table-format=2.1] S[table-format=1.2] S[table-format=1.2] S[table-format=2.1]", [
        r"Split & Judge & correct & {wrong auto.\ (\%)} & {coverage (\%)} & {p50 s} & {p95 s} & {\$ / 1M} \\"], trows))
    frows.sort(key=lambda r: r[0])
    dat("openai-acc.dat", ["y", "label", "r", "rm", "rp", "v"], frows)
    M("OaTicks", ",".join(str(r[0]) for r in frows))
    M("OaLabels", ",".join(r[1] for r in frows))
    cons = {(c["split"], c["metric"]): c for c in oj["contrasts"]}
    sig = [c for c in oj["contrasts"] if c["p_holm"] < 0.05]
    M("OaNSig", len(sig))
    M("OaTrHoldHolm", hu(cons[("trace-holdout", "accuracy")]["p_holm"], 3))
    M("OaWrongNeverHigher", "yes" if all(ORW[(s, LUNA)]["wrong_automatic"] <= ORW[(s, JEV)]["wrong_automatic"] for s in SPL) else "no")
    assert all(ORW[(s, LUNA)]["wrong_automatic"] <= ORW[(s, JEV)]["wrong_automatic"] for s in SPL), "text says wrong automatic <= Jev"
    assert all(cons[(s, "wrong automatic")]["p_holm"] >= 0.05 for s in SPL)
    lat = {(l["split"], l["arm"]): l for l in oj["latency"]}
    cl50 = [lat[(s, LUNA)]["client_wall_ms"]["p50"] / 1000 for s in SPL]
    cl95 = [lat[(s, LUNA)]["client_wall_ms"]["p95"] / 1000 for s in SPL]
    sv50 = [lat[(s, LUNA)]["server_ms"]["p50"] for s in SPL]
    sv95 = [lat[(s, LUNA)]["server_ms"]["p95"] for s in SPL]
    jv50 = [lat[(s, JEV)]["client_wall_ms"]["p50"] / 1000 for s in SPL]
    M("OaClientPfiftyLo", hu(min(cl50), 1)); M("OaClientPfiftyHi", hu(max(cl50), 1))
    M("OaClientPninetyfiveLo", hu(min(cl95), 1)); M("OaClientPninetyfiveHi", hu(max(cl95), 1))
    M("OaServerPfiftyLo", f"{min(sv50):.0f}"); M("OaServerPfiftyHi", f"{max(sv50):.0f}")
    M("OaServerPninetyfiveLo", f"{min(sv95):.0f}"); M("OaServerPninetyfiveHi", f"{max(sv95):.0f}")
    M("OaJevClientLo", hu(min(jv50), 1)); M("OaJevClientHi", hu(max(jv50), 1))
    _rd = (OAI / "README.md").read_text()
    _m = re.search(r"against about ([\d.]+)-([\d.]+) s in the (\d{4}-\d\d-\d\d) clef runs", _rd)
    M("OaJevEarlierLo", _m.group(1)); M("OaJevEarlierHi", _m.group(2)); M("OaJevEarlierDate", _m.group(3))
    usdL = [ORW[(s, LUNA)]["usd_per_1m"] for s in SPL]
    usdJ = [ORW[(s, JEV)]["usd_per_1m"] for s in SPL]
    M("OaUsdLo", f"{min(usdL):.0f}"); M("OaUsdHi", f"{max(usdL):.0f}")
    M("OaJevUsdLo", f"{min(usdJ):.0f}"); M("OaJevUsdHi", f"{max(usdJ):.0f}")
    inv = [x for x in oj["invalid"] if x["arm"] == LUNA]
    M("OaInvalid", len(inv))
    M("OaInvalidJev", len([x for x in oj["invalid"] if x["arm"] == JEV]))
    M("OaTrHoldLunaCovK", round(ORW[("trace-holdout", LUNA)]["coverage"] * ORW[("trace-holdout", LUNA)]["n"]))
    M("OaTrHoldJevCovK", round(ORW[("trace-holdout", JEV)]["coverage"] * ORW[("trace-holdout", JEV)]["n"]))
    M("OaTrHoldLunaCovPct", pct(ORW[("trace-holdout", LUNA)]["coverage"], 1))
    M("OaTrHoldJevCovPct", pct(ORW[("trace-holdout", JEV)]["coverage"], 1))
    M("OaTrHoldN", ORW[("trace-holdout", LUNA)]["n"])
    M("OaRequests", thousands(sum(lat[(s, LUNA)]["n_requests"] for s in SPL)))
    useful = []
    for s in ("trace-dev", "trace-holdout"):
        r2 = json.loads((OAI / s / "rule2.json").read_text())
        useful += [r2[a]["useful"] for a in (LUNA, JEV)]
    M("OaAnyUseful", "yes" if any(useful) else "no")
    assert not any(useful), "text says neither judge is useful under rule 2"
    oai_tex = r"""\subsection{OpenAI Decisions API (post hoc)}\label{sec:openai}
OpenAI's Decisions API is a native endpoint for exactly this kind of typed question: GPT-6 Luna returns a probability per
allowed answer. We ran it after the preregistered work, so everything here is post hoc and exploratory, against an
in-run Jev 1.13 reference on the same cases: three repetitions in two option orders, the bundle's gate with its
3\,s deadline, and the per-case majority over repetitions (\cref{tab:openai,fig:openai}).
\begin{itemize}
  \item \textbf{Accuracy.} Luna was right on \OaDevLunaK/\OaDevLunaN\ development cases (Jev \OaDevJevK/\OaDevJevN),
    \OaHoldoutLunaK/\OaHoldoutLunaN\ holdout cases (Jev \OaHoldoutJevK/\OaHoldoutJevN), \OaTraceDevLunaK/\OaTraceDevLunaN\
    real trace-dev decisions (Jev \OaTraceDevJevK/\OaTraceDevJevN) and \OaTraceHoldoutLunaK/\OaTraceHoldoutLunaN\
    trace-holdout decisions (Jev \OaTraceHoldoutJevK/\OaTraceHoldoutJevN). Only the trace-holdout accuracy difference
    survived the Holm correction ($p = \OaTrHoldHolm$; exploratory).
  \item \textbf{Misfires.} Luna's wrong-automatic rate was no higher than Jev's on every split; none of these differences
    was significant. Under the trace usefulness rule, neither judge was useful on either trace split.
  \item \textbf{Speed.} OpenAI's servers reported \OaServerPfiftyLo--\OaServerPfiftyHi\,ms at the median and
    \OaServerPninetyfiveLo--\OaServerPninetyfiveHi\,ms at p95, but from our machine the client saw
    \OaClientPfiftyLo--\OaClientPfiftyHi\,s at the median and \OaClientPninetyfiveLo--\OaClientPninetyfiveHi\,s at p95.
    The network was slow in this run for both providers: Jev's client median was \OaJevClientLo--\OaJevClientHi\,s,
    against \OaJevEarlierLo--\OaJevEarlierHi\,s on \OaJevEarlierDate. The comparison between the two judges is paired in
    time; the absolute latencies are not comparable with earlier evidence.
  \item \textbf{Cost and reliability.} \$\OaUsdLo--\OaUsdHi\ per million decisions against Jev's \$\OaJevUsdLo--\OaJevUsdHi.
    In transport, \OaInvalid\ of \OaRequests\ Luna requests and \OaInvalidJev\ of Jev's failed.
\end{itemize}
\begin{figure}[htbp]
\centering
\pgfplotslegendfromname{oalegend}\par\smallskip
\input{figures/fig-openai.tex}
\caption{The Decisions API was at or above Jev on every split (post hoc). OpenAI Decisions API (GPT-6 Luna) against the in-run Jev reference: per-case majority accuracy with 95\,\%
Wilson intervals on the four splits (post hoc).}
\label{fig:openai}
\howtoread{Each pair of rows is one split. Luna is at or above Jev on every split; only the trace-holdout gap survived the
correction. Overlapping whiskers mean no difference was detected, not that the judges are equivalent.}
\end{figure}
\begin{table}[htbp]\centering\footnotesize\setlength\tabcolsep{4pt}
\caption{OpenAI Decisions API (post hoc) against the in-run Jev reference: correct decisions, wrong automatic actions,
coverage, client latency (from our machine, slow network in this run) and dollars per million decisions.}\label{tab:openai}
\input{generated/tables/openai-decisions.tex}\end{table}
\begin{keyidea}
A native typed-decision endpoint from OpenAI matched or exceeded Jev's accuracy on our cases at \OaPriceXLo--\OaPriceXHi\X\ the price, but automated fewer real reads. Its
servers answer in tens of milliseconds, but from here each call took seconds. It does not change the session-start
finding: a one-line rule matched the decision model there.
\end{keyidea}
"""
elif FINAL:
    raise SystemExit(f"build_assets.py: FINAL=1 but the OpenAI Decisions evidence is missing ({OAI}/summary.json)")
write(OUT / "openai-section.tex", oai_tex)


# ================================================================ v4: takeaway-organised paper (main + supplement)
_jbn = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", (OUT / "jb" / "numbers.tex").read_text()))
# --- T2: per-request cost under the price gate's reference request mix (DERIVED from list prices x replay mix)
_mix = RP["derive"]["reference_mix"]["from_request_rows"]
_cls = ("input", "cache_read", "cache_write", "output")
_rq = {}
for _m, _k in (("claude-fable-5-1", "Fable"), ("claude-opus-5-5", "Opus"), ("claude-sonnet-5", "Sonnet")):
    parts = [_mix[c] * PRICE[_m][j] / 1e6 for j, c in enumerate(_cls)]
    _rq[_k] = parts
    M(f"Rq{_k}", hu(sum(parts), 4))
    M(f"Rq{_k}WriteShare", pct(parts[2] / sum(parts)))
    M(f"Rq{_k}ReadShare", pct(parts[1] / sum(parts)))
    M(f"Rq{_k}OutShare", pct(parts[3] / sum(parts)))
for _k in ("Fable", "Opus"):
    r_ = sum(_rq["Sonnet"]) / sum(_rq[_k])
    mult = RP["derive"]["multipliers"]["claude-fable-5-1" if _k == "Fable" else "claude-opus-5-5"]["derived"]
    M(f"RqSonnetOver{_k}", hu(r_, 2))
    M(f"RqPred{_k}", hu(r_ * mult, 3))
for _k in ("Mix",):
    pass
M("RqMixRead", thousands(round(_mix["cache_read"])))
M("RqMixWrite", thousands(round(_mix["cache_write"])))
M("RqMixOut", thousands(round(_mix["output"])))
M("RqMixAnchors", RP["derive"]["reference_mix"]["anchor_sessions"])
_rqrows = []
for _k, lab in (("Fable", "Fable 5.1 (host)"), ("Opus", "Opus 5.5 (host)"), ("Sonnet", "Sonnet 5 (routing target)")):
    p_ = _rq[_k]
    tot = sum(p_)
    if _k == "Sonnet":
        tail = r" & -- & -- & -- \\"
    else:
        mult = RP["derive"]["multipliers"]["claude-fable-5-1" if _k == "Fable" else "claude-opus-5-5"]["derived"]
        meas = (MACROS["CfFableSonnetPair"] if _k == "Fable" else MACROS["CfOpusSonnetPair"])
        tail = f" & {hu(sum(_rq['Sonnet']) / tot, 2)} & {hu(mult, 2)} & {hu(sum(_rq['Sonnet']) / tot * mult, 3)} \\\\"
    _rqrows.append(f"{lab} & {tot:.4f} & {100 * p_[2] / tot:.0f} & {100 * p_[1] / tot:.0f} & {100 * p_[3] / tot:.0f}" + tail)
write(TABLES / "v4-perrequest.tex", table(r"l S[table-format=1.4] S[table-format=2.0] S[table-format=2.0] S[table-format=2.0] c c c", [
    r" & {\$ per request} & \multicolumn{3}{c}{share of request cost (\%)} & \multicolumn{3}{c}{routing to Sonnet} \\",
    r"\cmidrule(lr){3-5}\cmidrule(l){6-8}",
    r"Model & & {write} & {read} & {output} & per request & requests & predicted \\"], _rqrows))

# --- Decisions API price ratio range (post hoc)
_oai = json.loads((REPO / "docs/evidence/2026-10-06-openai-decisions/summary.json").read_text())
_orw = {(r["split"], r["arm"]): r for r in _oai["rows"]}
_px = [_orw[(s, "luna-decisions")]["usd_per_1m"] / _orw[(s, "jev-1.13")]["usd_per_1m"]
       for s in ("dev", "holdout", "trace-dev", "trace-holdout")]
M("OaPriceXLo", hu(min(_px), 1))
M("OaPriceXHi", hu(max(_px), 1))

# --- F1: cost-accuracy frontier on the constructed holdout (cloud judges with a price)
_fr = [("jev", "Jev 1.13", float(_jbn["JevHoldCost"]), int(_jbn["JevHoldAccK"]), "pre"),
       ("luna", "GPT-6 Luna (prompted)", float(_jbn["LunaHoldCost"]), int(_jbn["LunaHoldAccK"]), "pre"),
       ("sol", "GPT-6.1 Sol (prompted)", float(_jbn["SolHoldCost"]), int(_jbn["SolHoldAccK"]), "pre"),
       ("clef", "Clef", float(MACROS["ClHoldClefCost"]), int(MACROS["ClHoldClefAcc"]), "post"),
       ("flash", "Clef-Flash", float(MACROS["ClHoldFlashCost"]), int(MACROS["ClHoldFlashAcc"]), "post"),
       ("lunad", "Luna, Decisions API", _orw[("holdout", "luna-decisions")]["usd_per_1m"],
        round(_orw[("holdout", "luna-decisions")]["accuracy"] * _orw[("holdout", "luna-decisions")]["n"]), "post")]
_hn = int(_jbn["HoldN"])
dat("v4-frontier-pre.dat", ["x", "y", "k"], [[f"{c:.2f}", f"{100 * a / _hn:.2f}", k] for k, _, c, a, s in _fr if s == "pre"])
dat("v4-frontier-post.dat", ["x", "y", "k"], [[f"{c:.2f}", f"{100 * a / _hn:.2f}", k] for k, _, c, a, s in _fr if s == "post"])
LP.configure(OUT, DATA, 10.0, 5.6)
_short = {"jev": "Jev", "luna": "Luna", "sol": "Sol", "clef": "Clef", "flash": "Clef-Flash", "lunad": "Luna-D"}
LP.place_labels("v4-frontier", [(k, f"{_short[k]} {a}", c, 100 * a / _hn) for k, lab, c, a, s in _fr], (8, 3000), (74, 102), xlog=True)

# --- F3: cache writes after an effort change vs never switching, by position in the session (A0 re-analysis of main-v1)
_bp = A0["effort_cache"]["by_position"]
_cw = [("within a turn", "anchor|unchanged|within_turn", "sticky_host|changed|within_turn"),
       ("first request after a short pause", "anchor|unchanged|turn_first_short_gap", "sticky_host|changed|turn_first_short_gap"),
       ("first request after a 7-minute pause", "anchor|unchanged|turn_first_long_gap", "sticky_host|changed|turn_first_long_gap")]
_cwrows = []
for i, (lab, a_, c_) in enumerate(_cw):
    _cwrows.append([i, "{" + lab + "}", f"{_bp[a_]['mean_cache_write'] / 1000:.2f}", f"{_bp[c_]['mean_cache_write'] / 1000:.2f}",
                    f"{_bp[c_]['mean_cache_write'] / 1000:.1f}", f"{_bp[a_]['mean_cache_write'] / 1000:.1f}"])
dat("v4-cachewrites.dat", ["y", "label", "anchor", "changed", "v", "av"], _cwrows)
# the figure's baseline is the plain host (never switches); the text uses the same baseline
M("CwWithinAnchor", thousands(round(_bp["anchor|unchanged|within_turn"]["mean_cache_write"])))
M("CwWithinChanged", thousands(round(_bp["sticky_host|changed|within_turn"]["mean_cache_write"])))
M("CwWithinX", hu(_bp["sticky_host|changed|within_turn"]["mean_cache_write"] / _bp["anchor|unchanged|within_turn"]["mean_cache_write"], 1))
M("CwWithinAnchorN", thousands(_bp["anchor|unchanged|within_turn"]["n"]))
for _pos, _key in (("Within", "within_turn"), ("Short", "turn_first_short_gap"), ("Long", "turn_first_long_gap")):
    _an, _ch = _bp[f"anchor|unchanged|{_key}"], _bp[f"sticky_host|changed|{_key}"]
    M(f"Cw{_pos}AnchorVal", thousands(round(_an["mean_cache_write"])))
    M(f"Cw{_pos}ChangedVal", thousands(round(_ch["mean_cache_write"])))
    M(f"Cw{_pos}AnchorNn", thousands(_an["n"]))
    M(f"Cw{_pos}ChangedNn", thousands(_ch["n"]))
    M(f"Cw{_pos}Ratio", hu(_ch["mean_cache_write"] / _an["mean_cache_write"], 2))
M("CwLongChanged", thousands(round(_bp["sticky_host|changed|turn_first_long_gap"]["mean_cache_write"])))
M("CwLongAnchor", thousands(round(_bp["anchor|unchanged|turn_first_long_gap"]["mean_cache_write"])))
M("CwLongN", _bp["sticky_host|changed|turn_first_long_gap"]["n"])
M("CwWithinChangedN", _bp["sticky_host|changed|within_turn"]["n"])
M("CwWithinUnchangedN", _bp["sticky_host|unchanged|within_turn"]["n"])

# --- T5: telemetry extras
_tc = list(_csv.DictReader(open(V3 / "a1-observatory" / "traffic_classification.csv")))
M("ObProdDefault", sum(int(r["sessions"]) for r in _tc if r["store"] == "events" and r["traffic"] == "production" and r["basis"] == "workspace_default"))
M("ObProdTagged", sum(int(r["sessions"]) for r in _tc if r["store"] == "events" and r["traffic"] == "production" and r["basis"] != "workspace_default"))
import datetime as _dt
M("ObDays", (_dt.date.fromisoformat(OBS["store"]["cutoff_utc"][:10]) - _dt.date.fromisoformat(OBS["store"]["week"][0])).days + 1)
M("ObTestRate", pct(OBS["shadow"]["rates"]["test traffic"]["rate"], 1))
_es = {x["traffic"]: x for x in OBS["a3_inputs"]["effort_switching"]}
M("ObEffSwitchProd", _es["production"]["effort_changes"])
M("ObEffReqProd", thousands(_es["production"]["requests"]))
M("ObEffSwitchTest", _es["test"]["effort_changes"])
M("ObEffReqTest", thousands(_es["test"]["requests"]))
_st = {(x["reason_code"], x["traffic"]): x["sessions"] for x in OBS["a3_inputs"]["start_tier_first_per_session"]}
M("ObJevRouteProd", pct(_st[("judge_cheap", "production")] / (_st[("judge_cheap", "production")] + _st[("judge_strong", "production")])))
M("ObJevRouteTest", pct(_st[("judge_cheap", "test")] / (_st[("judge_cheap", "test")] + _st[("judge_strong", "test")])))
_wl = OBS["a3_inputs"]["workload"]
M("ObFableProdSessions", sum(x["sessions"] for x in _wl if x["traffic"] == "production" and "fable" in x["host_model"]))
M("ObJevHostXFifty", f"{OBS['slow_end_ms']['p50'] / float(MACROS['ObJevPfifty']):.0f}")
_jl = [x for x in OBS["latency"] if x["backend"] == "jev" and x["kind"] == "difficulty_judged:judge_call"][0]
M("ObJevHostXNinetyfive", f"{OBS['slow_end_ms']['p95'] / _jl['p95_ms']:.0f}")

# --- A3 projection, corrected after S1 (H4: Opus medium effort did not demonstrate a saving)
_a3 = json.loads((V3 / "a3-projection-inputs" / "projection.json").read_text())
_sp = _a3["production_recorded_spend_usd_by_host"]
_tot = sum(_sp.values())
_sh = {k: v / _tot for k, v in _sp.items()}
_son = _a3["ratios_used"]["sonnet"]["plain medium"]
_new = {q: _sh["opus"] * 1.0 + _sh["sonnet"] * _son[q] + _sh["other"] * 1.0 for q in ("point", "low", "high")}
_old = _a3["projection_on_recorded_mix"]["C*"]
M("AthreeOld", hu(_old["ratio"], 2))
M("AthreeOldBand", f"{hu(_old['band'][0], 2)}--{hu(_old['band'][1], 2)}")
M("AthreeNew", hu(_new["point"], 2))
M("AthreeNewBand", f"{hu(_new['low'], 2)}--{hu(_new['high'], 2)}")
M("AthreeOpusShare", pct(_sh["opus"]))
M("AthreeSonnetShare", pct(_sh["sonnet"]))
M("AthreeOpusPriorLo", hu(_a3["ratios_used"]["opus"]["C*_O (strong medium)"]["low"], 3))
M("AthreeOpusPriorHi", hu(_a3["ratios_used"]["opus"]["C*_O (strong medium)"]["high"], 3))
M("AthreeGoal", hu(_a3["goal_cost_target"], 2))
PAPER_EVIDENCE_COMMIT = "3cd180b7523dd2318fdc3036d701c6b4614c69e2"  # origin/main holding every evidence package used
subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", PAPER_EVIDENCE_COMMIT + "^{commit}"], check=True)
M("RepoCommit", PAPER_EVIDENCE_COMMIT[:12])

# ------------------------------------------------------------ numbers.tex
header = ("% Generated by build_assets.py from docs/evidence/2026-10-02-paired-campaign/ and the files listed there. "
          f"Do not edit.\n% {len(MACROS)} macros.\n")
write(OUT / "numbers.tex", header + "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in sorted(MACROS.items())))
print(f"wrote {len(MACROS)} macros, {len(list(TABLES.glob('*.tex')))} tables, {len(list(DATA.glob('*.dat')))} data files")
