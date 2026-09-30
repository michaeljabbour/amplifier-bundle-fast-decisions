#!/usr/bin/env python3
"""Render the judge comparison as one self-contained HTML report.

    python3 evals/judge_report.py docs/evidence/2026-09-30-judge-comparison

Reads manifest.json, requests.jsonl and summary.json from that directory and
writes index.html next to them. No network, no external scripts or fonts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ARMS = {  # display name, family, where it runs, size note
    "jev-1.13": ("Jev 1.13", "cloud", "TypeSafe API", "hosted"),
    "gpt-6-luna": ("GPT-6 Luna*", "cloud", "OpenAI API", "hosted"),
    "nimble-9b": ("nimble 9B", "decision", "Ollama System One", "9.5 GB"),
    "tev1-4b": ("tev1 4B", "decision", "Ollama System One", "4.5 GB"),
    "tev1-0.8b": ("tev1 0.8B", "decision", "Ollama System One", "0.8 GB"),
    "laya-base": ("Laya base", "decision", "Local Laya server", "PyTorch MPS"),
    "qwen3-8b": ("Qwen3 8B", "general", "Bundle OllamaBackend", "5.2 GB"),
    "qwen3-4b": ("Qwen3 4B", "general", "Bundle OllamaBackend", "2.5 GB"),
    "qwen3-0.6b": ("Qwen3 0.6B", "general", "Bundle OllamaBackend", "0.5 GB"),
}
FAMILIES = {"cloud": "Cloud API", "decision": "Local decision model", "general": "Local general LLM"}


def load(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    rows = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines() if line.strip()]
    summary = json.loads((directory / "summary.json").read_text())
    tasks = {}
    for case in manifest["cases"]:
        state = json.loads(case["payload"]["state"])
        question = case["payload"]["questions"]["decision"]
        tasks[case["id"]] = {"task": state.get("task") or state.get("query"),
                             "context": state.get("observation") or state.get("source"),
                             "options": question.get("criteria") or {"true": "yes", "false": "no"},
                             "kind": case["kind"], "screen": case["screen"], "expected": case["expected"]}
    compact = []
    for r in rows:
        answer = r.get("answer") or {}
        p_correct = None
        if r.get("valid"):
            if r["kind"] == "search":
                p = answer.get("noul")
                p_correct = p if r["expected"] else 1 - p
            else:
                p_correct = (answer.get("probabilities") or {}).get(r["expected"])
        compact.append({"arm": r["arm"], "id": r["id"], "order": r["order"], "valid": r.get("valid", False),
                        "kind": r["kind"], "screen": r["screen"], "expected": r["expected"],
                        "predicted": r.get("predicted"), "correct": r.get("correct"),
                        "certainty": r.get("certainty"), "automatic": r.get("automatic"),
                        "automatic_error": r.get("automatic_error"), "p_correct": p_correct,
                        "ms": r.get("elapsed_ms"), "error": r.get("error")})
    arms = [a for a in ARMS if a in summary]
    return {"manifest": {k: manifest[k] for k in ("threshold", "order_passes", "prices_usd_per_mtok",
                                                   "production_timeout_ms", "source")},
            "arms": [{"id": a, "name": ARMS[a][0], "family": ARMS[a][1], "runs": ARMS[a][2], "size": ARMS[a][3]}
                     for a in arms],
            "families": FAMILIES, "summary": summary, "rows": compact, "tasks": tasks}


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fast Decisions judge comparison</title>
<style>
:root {
  color-scheme: light;
  --surface-0: #f4f3f0; --surface-1: #fcfcfb; --rule: #e4e2dd; --grid: #ecebe7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #7b7a75;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --seq-0: #f0efec; --seq-1: #cde2fb; --seq-2: #9ec5f4; --seq-3: #6da7ec; --seq-4: #3987e5; --seq-5: #256abf; --seq-6: #184f95; --seq-7: #0d366b;
  --critical: #d03b3b; --good: #0ca30c; --diag: #b9b7b0;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-0: #121211; --surface-1: #1a1a19; --rule: #2e2e2c; --grid: #262624;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --seq-0: #262624; --seq-1: #104281; --seq-2: #184f95; --seq-3: #1c5cab; --seq-4: #256abf; --seq-5: #3987e5; --seq-6: #6da7ec; --seq-7: #b7d3f6;
    --diag: #55544f;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-0: #121211; --surface-1: #1a1a19; --rule: #2e2e2c; --grid: #262624;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --seq-0: #262624; --seq-1: #104281; --seq-2: #184f95; --seq-3: #1c5cab; --seq-4: #256abf; --seq-5: #3987e5; --seq-6: #6da7ec; --seq-7: #b7d3f6;
  --diag: #55544f;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface-0); color: var(--text-primary);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
header, main { max-width: 1180px; margin: 0 auto; padding: 0 24px; }
header { padding-top: 32px; }
h1 { font-size: 26px; margin: 0 0 6px; font-weight: 650; letter-spacing: -0.01em; }
h2 { font-size: 18px; margin: 0 0 4px; font-weight: 620; }
h3 { font-size: 13px; margin: 0 0 6px; font-weight: 600; color: var(--text-secondary); }
p { margin: 6px 0; }
.lede { color: var(--text-secondary); max-width: 860px; }
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 16px 0 8px; }
.toolbar button, .toolbar select { font: inherit; background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--rule); border-radius: 8px; padding: 6px 10px; cursor: pointer; }
.toolbar button[aria-pressed="true"] { border-color: var(--series-1); box-shadow: inset 0 0 0 1px var(--series-1); }
.card { background: var(--surface-1); border: 1px solid var(--rule); border-radius: 14px; padding: 20px; margin: 16px 0; }
.card .sub { color: var(--text-secondary); font-size: 13px; margin-bottom: 12px; max-width: 900px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 16px 0; }
.tile { background: var(--surface-1); border: 1px solid var(--rule); border-radius: 14px; padding: 16px; }
.tile .k { color: var(--text-secondary); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.tile .v { font-size: 30px; font-weight: 650; margin: 4px 0 2px; }
.tile .d { color: var(--text-secondary); font-size: 13px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; }
.multiples { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 16px; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--text-secondary); margin: 4px 0 10px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
svg { display: block; overflow: visible; }
svg text { fill: var(--text-secondary); font-size: 11px; }
svg .label { fill: var(--text-primary); font-size: 12px; font-weight: 550; }
svg .axis line, svg .axis path { stroke: var(--rule); }
svg .gridline { stroke: var(--grid); stroke-width: 1; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 7px 8px; border-bottom: 1px solid var(--rule); text-align: right; white-space: nowrap; }
th { white-space: normal; vertical-align: bottom; min-width: 52px; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-secondary); font-weight: 600; cursor: pointer; user-select: none; position: sticky; top: 0; background: var(--surface-1); }
th[aria-sort="descending"]::after { content: " ▾"; } th[aria-sort="ascending"]::after { content: " ▴"; }
td.num { font-variant-numeric: tabular-nums; }
.scroll { overflow: auto; max-height: 520px; }
.tip { position: fixed; pointer-events: none; background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--rule); border-radius: 10px; padding: 8px 10px; font-size: 12px; max-width: 360px;
  box-shadow: 0 6px 24px rgba(0,0,0,.18); opacity: 0; transition: opacity .08s; z-index: 10; }
.tip b { font-weight: 600; } .tip .m { color: var(--text-secondary); }
.note { color: var(--text-secondary); font-size: 13px; }
.flag { color: var(--critical); font-weight: 600; }
ul.tight { margin: 6px 0; padding-left: 20px; } ul.tight li { margin: 3px 0; }
details summary { cursor: pointer; color: var(--text-secondary); margin-top: 8px; }
footer { max-width: 1180px; margin: 24px auto 48px; padding: 0 24px; color: var(--text-muted); font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>Fast Decisions: which judge should make the small decisions?</h1>
  <p class="lede">Nine decision judges on the same 90 frozen, hand-labeled screening cases from the Laya study
  (60 original + 30 fresh): prepared-action selection, source-code relevance and computer-use target selection.
  Each case was asked twice with the options reversed; scores use the first pass. Measured __DATE__ on an Apple M5 Max.</p>
  <div class="toolbar" role="toolbar" aria-label="Report controls">
    <span class="note">Screen:</span>
    <button data-screen="all" aria-pressed="true">All 90</button>
    <button data-screen="original" aria-pressed="false">Original 60</button>
    <button data-screen="fresh" aria-pressed="false">Fresh 30</button>
    <span style="flex:1"></span>
    <button id="theme" aria-pressed="false">Dark mode</button>
  </div>
</header>
<main>
  <section class="tiles" id="tiles" aria-label="Headlines"></section>

  <section class="card"><h2>What this means</h2><div id="takeaways"></div></section>

  <section class="card">
    <h2>Leaderboard</h2>
    <div class="sub">Click a column to sort. Accuracy counts invalid or failed replies as wrong. "Automatic" is a
    decision made at probability ≥ 0.75 (the study's cutoff, not the bundle's full policy); a wrong automatic decision
    is the costly failure. Cost is per 1,000 decisions at vendor list prices; local models have no API charge.</div>
    <div class="scroll"><table id="board"></table></div>
  </section>

  <div class="grid2">
    <section class="card"><h2>Quality vs. speed</h2>
      <div class="sub">Up and to the left is better. Median latency per decision (log scale) against accuracy.</div>
      <div class="legend" id="legend1"></div><div id="scatterLatency"></div></section>
    <section class="card"><h2>Quality vs. cost</h2>
      <div class="sub">Up and to the left is better. API cost per million decisions at list price; local judges sit at $0
      (hardware and electricity not included).</div>
      <div class="legend" id="legend2"></div><div id="scatterCost"></div></section>
  </div>

  <section class="card"><h2>Automation frontier</h2>
    <div class="sub">How many decisions a judge is confident enough to make on its own (coverage) against how many of
    those confident decisions are wrong. The ideal judge is far right and at the bottom.</div>
    <div class="legend" id="legend3"></div><div id="frontier"></div></section>

  <section class="card"><h2>Raising the confidence cutoff</h2>
    <div class="sub">As the cutoff for acting automatically rises from 0.75 to 0.99, how many decisions each judge still
    makes on its own (filled area) and how many of those are wrong (red line). A trustworthy judge's red line reaches
    zero while the area is still large; an overconfident judge keeps making wrong calls at 98% certainty.</div>
    <div class="legend"><span><span class="swatch" style="background:var(--seq-3)"></span>Automatic decisions</span>
    <span><svg width="18" height="10"><line x1="0" x2="18" y1="5" y2="5" stroke="var(--critical)" stroke-width="2"/></svg>Wrong automatic decisions</span></div>
    <div class="multiples" id="sweep"></div></section>

  <section class="card"><h2>Accuracy by task type</h2>
    <div class="sub">Share of cases answered correctly. Color runs from 50% (lightest) to 100% (darkest).</div>
    <div id="kindMatrix"></div></section>

  <section class="card"><h2>Every case, every judge</h2>
    <div class="sub">Each cell is the probability the judge put on the correct answer (darker = more right). A red ×
    marks a wrong automatic decision; an empty cell is an invalid or failed reply. Hover for the case.</div>
    <div id="caseMatrix"></div></section>

  <section class="card"><h2>Confusion matrices (choice questions)</h2>
    <div class="sub">Rows are the correct answer, columns the judge's answer, for the 60 choice cases in view: option a,
    option b, or "reason" (fall back to normal reasoning). The diagonal is correct; "reason → a/b" means the judge acted
    when it should have deferred.</div>
    <div class="multiples" id="confusion"></div></section>

  <section class="card"><h2>Calibration (reliability diagrams)</h2>
    <div class="sub">When a judge says it is x% sure, is it right x% of the time? Points on the diagonal are well
    calibrated; below the diagonal is overconfident. Point size shows how many decisions fall in the bin. Mean Brier
    score in each title (lower is better).</div>
    <div class="multiples" id="reliability"></div></section>

  <div class="grid2">
    <section class="card"><h2>Latency distribution</h2>
      <div class="sub">Every valid decision (both passes), log scale. The red line at 3 s is Fast Decisions'
      production judge timeout.</div><div id="latency"></div></section>
    <section class="card"><h2>Stability when options are reordered</h2>
      <div class="sub">Cases whose answer changed when the choice options were listed in reverse order (out of 90).
      Fewer is better. Qwen arms average both orders inside the bundle backend, so they are stable by construction.</div>
      <div id="stability"></div></section>
  </div>

  <section class="card"><h2>Method and caveats</h2><div id="method"></div></section>
</main>
<footer>Generated from requests.jsonl and summary.json in this directory by evals/judge_report.py. Self-contained: no
network requests.</footer>
<div class="tip" id="tip" role="tooltip"></div>
<script>
const DATA = __DATA__;
const ARMS = DATA.arms, FAM = DATA.families;
const FAMCOLOR = {cloud: "var(--series-1)", decision: "var(--series-2)", general: "var(--series-3)"};
const FAMSHAPE = {cloud: "circle", decision: "square", general: "triangle"};
let SCREEN = "all";
const ns = "http://www.w3.org/2000/svg";
const tip = document.getElementById("tip");
const fmtPct = v => v == null ? "—" : (100 * v).toFixed(v >= .995 || v === 0 ? 0 : 1) + "%";
const fmtMs = v => v == null ? "—" : v >= 1000 ? (v / 1000).toFixed(2) + " s" : Math.round(v) + " ms";
const fmtUsd = v => v == null ? "—" : v === 0 ? "$0" : v < 0.01 ? "$" + v.toFixed(4) : "$" + v.toFixed(2);
const armName = id => ARMS.find(a => a.id === id).name;
function el(tag, attrs = {}, parent) { const e = document.createElementNS(ns, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e); return e; }
function showTip(evt, html) { tip.innerHTML = html; tip.style.opacity = 1;
  const x = Math.min(evt.clientX + 14, innerWidth - tip.offsetWidth - 8), y = Math.min(evt.clientY + 14, innerHeight - tip.offsetHeight - 8);
  tip.style.left = x + "px"; tip.style.top = y + "px"; }
function hideTip() { tip.style.opacity = 0; }
function hover(node, html) { node.addEventListener("mousemove", e => showTip(e, html)); node.addEventListener("mouseleave", hideTip); }
function stat(arm, key = "all") { return DATA.summary[arm][SCREEN + "/" + key]; }
function costPer1k(arm) { return DATA.summary[arm].cost.usd_per_1k_decisions; }
function shape(g, fam, x, y, r, attrs) {
  if (FAMSHAPE[fam] === "circle") return el("circle", {cx: x, cy: y, r, ...attrs}, g);
  if (FAMSHAPE[fam] === "square") return el("rect", {x: x - r * .9, y: y - r * .9, width: r * 1.8, height: r * 1.8, rx: 2, ...attrs}, g);
  return el("path", {d: `M${x},${y - r * 1.15} L${x + r * 1.1},${y + r * .8} L${x - r * 1.1},${y + r * .8} Z`, ...attrs}, g);
}
function legend(id) { const box = document.getElementById(id); box.innerHTML = "";
  for (const [fam, label] of Object.entries(FAM)) { const s = document.createElement("span");
    const sv = el("svg", {width: 14, height: 14}); shape(sv, fam, 7, 7, 5.5, {fill: FAMCOLOR[fam]}); s.appendChild(sv);
    s.appendChild(document.createTextNode(label)); box.appendChild(s); } }
function niceStep(range, count) { const raw = range / count, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / mag; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag; }
function seqColor(v) { if (v == null) return "none"; const i = Math.max(0, Math.min(7, Math.round(v * 7))); return `var(--seq-${i})`; }
function seqInk(v) { return v != null && v > .62 ? "#ffffff" : "var(--text-primary)"; }

/* ---------- tiles & takeaways ---------- */
function tiles() {
  const box = document.getElementById("tiles"); box.innerHTML = "";
  const acc = a => stat(a).accuracy, sorted = [...ARMS].sort((x, y) => acc(y.id) - acc(x.id));
  const best = sorted[0], bestLocal = sorted.find(a => a.family !== "cloud");
  const fastest = [...ARMS].filter(a => acc(a.id) >= .75).sort((x, y) => stat(x.id).p50_ms - stat(y.id).p50_ms)[0] || sorted[0];
  const safest = [...ARMS].filter(a => stat(a.id).coverage >= .5).sort((x, y) => stat(x.id).automatic_errors - stat(y.id).automatic_errors || stat(y.id).coverage - stat(x.id).coverage)[0];
  const items = [
    ["Most accurate", best.name, fmtPct(acc(best.id)) + " correct · " + fmtMs(stat(best.id).p50_ms) + " median"],
    ["Best local judge", bestLocal.name, fmtPct(acc(bestLocal.id)) + " correct · no API cost"],
    ["Fastest at ≥ 75% accuracy", fastest.name, fmtMs(stat(fastest.id).p50_ms) + " median · " + fmtPct(acc(fastest.id))],
    safest ? ["Fewest wrong automatic calls", safest.name, stat(safest.id).automatic_errors + " wrong of " + stat(safest.id).automatic + " automatic (" + fmtPct(stat(safest.id).coverage) + " coverage)"] : null,
  ].filter(Boolean);
  for (const [k, v, d] of items) { const t = document.createElement("div"); t.className = "tile";
    t.innerHTML = `<div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div>`; box.appendChild(t); }
}

/* ---------- leaderboard ---------- */
const COLS = [
  ["Judge", a => a.name, "text"], ["Runs on", a => a.runs, "text"],
  ["Accuracy", a => stat(a.id).accuracy, "pct"], ["Select", a => stat(a.id, "select")?.accuracy, "pct"],
  ["Code relevance", a => stat(a.id, "search")?.accuracy, "pct"], ["Computer use", a => stat(a.id, "cua")?.accuracy, "pct"],
  ["Automatic", a => stat(a.id).coverage, "pct"], ["Wrong automatic", a => stat(a.id).automatic_errors, "int"],
  ["Brier", a => stat(a.id).mean_brier, "f3"], ["Order flips", a => DATA.summary[a.id].order_check.changed, "int"],
  ["p50", a => stat(a.id).p50_ms, "ms"], ["p95", a => stat(a.id).p95_ms, "ms"],
  ["≤ 3 s", a => stat(a.id).within_production_timeout, "pct"], ["$ / 1k decisions", a => costPer1k(a.id), "usd"],
];
let sortCol = 2, sortDir = -1;
function board() {
  const t = document.getElementById("board"); t.innerHTML = "";
  const head = t.createTHead().insertRow();
  COLS.forEach(([label], i) => { const th = document.createElement("th"); th.textContent = label; th.scope = "col";
    if (i === sortCol) th.setAttribute("aria-sort", sortDir < 0 ? "descending" : "ascending");
    th.onclick = () => { sortDir = sortCol === i ? -sortDir : (COLS[i][2] === "text" ? 1 : -1); sortCol = i; board(); }; head.appendChild(th); });
  const rows = [...ARMS].sort((x, y) => { const a = COLS[sortCol][1](x), b = COLS[sortCol][1](y);
    return (a > b ? 1 : a < b ? -1 : 0) * sortDir; });
  const body = t.createTBody();
  for (const a of rows) { const tr = body.insertRow();
    COLS.forEach(([, get, kind], i) => { const td = tr.insertCell(); const v = get(a);
      td.textContent = kind === "pct" ? fmtPct(v) : kind === "ms" ? fmtMs(v) : kind === "usd" ? fmtUsd(v)
        : kind === "f3" ? (v == null ? "—" : v.toFixed(3)) : v ?? "—";
      if (kind !== "text") td.className = "num";
      if (i === 0) { td.innerHTML = ""; const sv = el("svg", {width: 12, height: 12, style: "display:inline-block;margin-right:8px;vertical-align:-1px"});
        shape(sv, a.family, 6, 6, 5, {fill: FAMCOLOR[a.family]}); td.appendChild(sv); td.appendChild(document.createTextNode(a.name)); }
      if (COLS[i][0] === "Wrong automatic" && v > 0) td.classList.add("flag"); }); }
}

/* ---------- scatter maps ---------- */
function scatter(id, {xOf, xLabel, xLog, xFmt, yOf = a => stat(a.id).accuracy, yLabel = "Accuracy", yFmt = fmtPct, yMin, yMax, invertY}) {
  const box = document.getElementById(id); box.innerHTML = "";
  const W = box.clientWidth || 520, H = 340, m = {l: 64, r: 24, t: 14, b: 44};
  const svg = el("svg", {width: W, height: H, role: "img", "aria-label": yLabel + " versus " + xLabel}, box);
  const xs = ARMS.map(xOf).filter(v => v != null), ys = ARMS.map(yOf).filter(v => v != null);
  let x0 = xLog ? Math.min(...xs) / 1.6 : 0, x1 = xLog ? Math.max(...xs) * 1.6 : Math.max(...xs) * 1.12 || 1;
  const xStep = xLog ? null : niceStep(x1 - x0, 4); if (!xLog) x1 = Math.ceil(x1 / xStep) * xStep;
  const y0 = yMin ?? Math.max(0, Math.floor((Math.min(...ys) - .06) * 10) / 10); const yStep = niceStep((yMax ?? 1) - y0, 5); const y1 = yMax == null ? 1 : Math.ceil(yMax / yStep) * yStep;
  const sx = v => m.l + (xLog ? (Math.log(v) - Math.log(x0)) / (Math.log(x1) - Math.log(x0)) : (v - x0) / (x1 - x0)) * (W - m.l - m.r);
  const sy = v => invertY ? m.t + (v - y0) / (y1 - y0) * (H - m.t - m.b) : H - m.b - (v - y0) / (y1 - y0) * (H - m.t - m.b);
  const g = el("g", {}, svg);
  for (let v = y0; v <= y1 + 1e-9; v += yStep) { const y = sy(v);
    el("line", {x1: m.l, x2: W - m.r, y1: y, y2: y, class: "gridline"}, g);
    el("text", {x: m.l - 8, y: y + 4, "text-anchor": "end"}, g).textContent = yFmt(v); }
  const xt = xLog ? [10, 30, 100, 300, 1000, 3000, 10000].filter(v => v >= x0 && v <= x1) : Array.from({length: Math.round((x1 - x0) / xStep) + 1}, (_, i) => x0 + i * xStep);
  for (const v of xt) { el("text", {x: sx(v), y: H - m.b + 18, "text-anchor": "middle"}, g).textContent = xFmt(v); }
  el("line", {x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: "var(--rule)"}, g);
  el("text", {x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle"}, g).textContent = xLabel;
  el("text", {x: 10, y: (m.t + H - m.b) / 2, transform: `rotate(-90 10 ${(m.t + H - m.b) / 2})`, "text-anchor": "middle"}, g).textContent = yLabel;
  const pts = [];
  for (const a of ARMS) { const xv = xOf(a), yv = yOf(a); if (xv == null || yv == null) continue;
    pts.push({a, xv, yv, x: sx(xv), y: sy(yv)}); }
  // Labels: right of the point (left near the edge), then pushed apart vertically; leader line when moved.
  const labels = pts.map(p => { const w = p.a.name.length * 6.6 + 4, right = p.x + 10 + w < W - m.r;
    return {p, w, right, x: right ? p.x + 10 : p.x - 10 - w, y: p.y + 4}; });
  const obstacles = pts.map(p => ({x: p.x - 8, w: 16, y: p.y + 4}));
  const blocked = (L, self) => obstacles.some(O => !(O.x === self.x - 8 && O.y === self.y + 4) && L.x < O.x + O.w && O.x < L.x + L.w && Math.abs(L.y - O.y) < 12);
  for (const L of labels) if (L.right && blocked(L, L.p)) { const left = {...L, x: L.p.x - 10 - L.w};
    if (left.x > m.l && !blocked(left, L.p)) { L.x = left.x; L.right = false; } }
  for (let iter = 0; iter < 80; iter++) { let moved = false;
    for (const A of labels) for (const O of obstacles) { if (O.x === A.p.x - 8 && O.y === A.p.y + 4) continue;
      if (A.x < O.x + O.w && O.x < A.x + A.w && Math.abs(A.y - O.y) < 12) { A.y += A.y <= O.y ? -1.5 : 1.5; moved = true; } }
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) { const A = labels[i], B = labels[j];
      if (A.x < B.x + B.w && B.x < A.x + A.w && Math.abs(A.y - B.y) < 14) { const push = (14 - Math.abs(A.y - B.y)) / 2 + .5;
        if (A.y <= B.y) { A.y -= push; B.y += push; } else { A.y += push; B.y -= push; } moved = true; } }
    if (!moved) break; }
  for (const L of labels) { const p = L.p;
    if (Math.abs(L.y - 4 - p.y) > 7) el("line", {x1: p.x + (L.right ? 6 : -6), y1: p.y, x2: L.right ? L.x - 2 : L.x + L.w + 2, y2: L.y - 4, stroke: "var(--text-muted)", "stroke-width": 1}, g);
    el("text", {x: L.x, y: L.y, class: "label"}, g).textContent = p.a.name; }
  for (const p of pts) { shape(g, p.a.family, p.x, p.y, 6.5, {fill: FAMCOLOR[p.a.family], stroke: "var(--surface-1)", "stroke-width": 2});
    const hit = el("circle", {cx: p.x, cy: p.y, r: 16, fill: "transparent"}, g);
    hover(hit, `<b>${p.a.name}</b> <span class="m">${FAM[p.a.family]}</span><br>${yLabel}: ${yFmt(p.yv)}<br>${xLabel}: ${xFmt(p.xv)}`); }
}
function scatters() {
  ["legend1", "legend2", "legend3"].forEach(legend);
  scatter("scatterLatency", {xOf: a => stat(a.id).p50_ms, xLabel: "Median latency per decision", xLog: true, xFmt: fmtMs});
  scatter("scatterCost", {xOf: a => 1000 * costPer1k(a.id), xLabel: "API cost per million decisions", xFmt: v => "$" + Math.round(v)});
  scatter("frontier", {xOf: a => stat(a.id).coverage, xLabel: "Coverage: share decided automatically", xFmt: v => Math.round(100 * v) + "%",
    yOf: a => stat(a.id).automatic ? stat(a.id).automatic_errors / stat(a.id).automatic : 0, yLabel: "Wrong share of automatic decisions",
    yFmt: v => Math.round(100 * v) + "%", yMin: 0, yMax: Math.max(.2, ...ARMS.map(a => stat(a.id).automatic ? stat(a.id).automatic_errors / stat(a.id).automatic : 0)) * 1.05, invertY: false});
}

/* ---------- threshold sweep multiples ---------- */
function sweep() {
  const box = document.getElementById("sweep"); box.innerHTML = "";
  const ts = []; for (let t = .75; t <= .9901; t += .01) ts.push(+t.toFixed(2));
  for (const a of [...ARMS].sort((x, y) => stat(y.id).accuracy - stat(x.id).accuracy)) {
    const rows = DATA.rows.filter(r => r.arm === a.id && r.order === 0 && r.valid && (SCREEN === "all" || r.screen === SCREEN));
    const pts = ts.map(t => { const auto = rows.filter(r => r.predicted !== "reason" && r.certainty >= t);
      return [t, auto.length, auto.filter(r => !r.correct).length]; });
    const card = document.createElement("div"); const zero = pts.find(p => p[2] === 0);
    card.innerHTML = `<h3>${a.name}</h3>`; box.appendChild(card);
    const W = 170, H = 110, m = {l: 26, r: 6, t: 6, b: 20}, n = rows.length || 1;
    const sx = t => m.l + (t - .75) / .24 * (W - m.l - m.r), sy = v => H - m.b - v / n * (H - m.t - m.b);
    const svg = el("svg", {width: W, height: H, role: "img", "aria-label": a.name + " threshold sweep"}, card);
    [0, .5, 1].forEach(f => { el("line", {x1: m.l, x2: W - m.r, y1: sy(f * n), y2: sy(f * n), class: "gridline"}, svg);
      el("text", {x: m.l - 4, y: sy(f * n) + 4, "text-anchor": "end"}, svg).textContent = Math.round(f * n); });
    [.75, .87, .99].forEach(t => el("text", {x: sx(t), y: H - 6, "text-anchor": "middle"}, svg).textContent = t.toFixed(2));
    el("path", {d: `M${sx(.75)},${sy(0)} ` + pts.map(p => `L${sx(p[0])},${sy(p[1])}`).join(" ") + ` L${sx(.99)},${sy(0)} Z`, fill: "var(--seq-3)", opacity: .55}, svg);
    el("path", {d: pts.map((p, i) => (i ? "L" : "M") + sx(p[0]) + "," + sy(p[2])).join(" "), fill: "none", stroke: "var(--critical)", "stroke-width": 2}, svg);
    const hit = el("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent"}, svg);
    hit.addEventListener("mousemove", e => { const bb = svg.getBoundingClientRect(); const t = Math.min(.99, Math.max(.75, .75 + (e.clientX - bb.left - m.l) / (W - m.l - m.r) * .24));
      const p = pts.reduce((b, q) => Math.abs(q[0] - t) < Math.abs(b[0] - t) ? q : b);
      showTip(e, `<b>${a.name}</b> at cutoff ${p[0].toFixed(2)}<br>${p[1]} automatic decisions, ${p[2]} wrong<br><span class="m">${zero ? "First zero-error cutoff: " + zero[0].toFixed(2) + " (" + zero[1] + " automatic)" : "Never reaches zero wrong below 0.99"}</span>`); });
    hit.addEventListener("mouseleave", hideTip);
  }
}

/* ---------- accuracy by kind matrix ---------- */
function kindMatrix() {
  const box = document.getElementById("kindMatrix"); box.innerHTML = "";
  const kinds = [["select", "Prepared-action selection"], ["search", "Code relevance"], ["cua", "Computer-use target"], ["all", "All"]];
  const rows = [...ARMS].sort((x, y) => stat(y.id).accuracy - stat(x.id).accuracy);
  const W = Math.min(box.clientWidth || 900, 900), rowH = 34, left = 130, cellW = (W - left) / kinds.length, H = 30 + rows.length * rowH;
  const svg = el("svg", {width: W, height: H, role: "img", "aria-label": "Accuracy by task type"}, box);
  kinds.forEach(([, label], j) => el("text", {x: left + j * cellW + cellW / 2, y: 16, "text-anchor": "middle"}, svg).textContent = label);
  rows.forEach((a, i) => { const y = 26 + i * rowH;
    el("text", {x: left - 10, y: y + rowH / 2 + 4, "text-anchor": "end", class: "label"}, svg).textContent = a.name;
    kinds.forEach(([k, label], j) => { const s = stat(a.id, k); const v = s?.accuracy;
      const f = v == null ? null : Math.max(0, (v - .5) / .5);
      const r = el("rect", {x: left + j * cellW + 1, y: y + 1, width: cellW - 2, height: rowH - 2, rx: 4, fill: seqColor(f)}, svg);
      el("text", {x: left + j * cellW + cellW / 2, y: y + rowH / 2 + 4, "text-anchor": "middle", style: `fill:${seqInk(f)};font-weight:600`}, svg).textContent = fmtPct(v);
      hover(r, `<b>${a.name}</b> · ${label}<br>${s ? s.correct + " of " + s.n + " correct" : ""}`); }); });
}

/* ---------- per-case matrix ---------- */
function caseMatrix() {
  const box = document.getElementById("caseMatrix"); box.innerHTML = "";
  const cases = Object.entries(DATA.tasks).filter(([, t]) => SCREEN === "all" || t.screen === SCREEN)
    .sort((a, b) => a[1].kind.localeCompare(b[1].kind) || a[0].localeCompare(b[0]));
  const arms = [...ARMS].sort((x, y) => stat(y.id).accuracy - stat(x.id).accuracy);
  const W = box.clientWidth || 1100, left = 96, top = 22, cw = Math.max(6, Math.min(12, (W - left - 10) / cases.length)), ch = 22;
  const H = top + arms.length * ch + 30;
  const svg = el("svg", {width: left + cases.length * cw + 10, height: H, role: "img", "aria-label": "Per-case correctness matrix"}, box);
  const byKey = {}; for (const r of DATA.rows) if (r.order === 0) byKey[r.arm + "|" + r.id] = r;
  let prev = null; cases.forEach(([id, t], j) => { if (t.kind !== prev) { prev = t.kind;
      el("text", {x: left + j * cw, y: 14}, svg).textContent = {select: "Prepared-action selection", search: "Code relevance", cua: "Computer-use target"}[t.kind];
      if (j) el("line", {x1: left + j * cw, x2: left + j * cw, y1: top - 4, y2: top + arms.length * ch, stroke: "var(--text-muted)", "stroke-width": 1}, svg); } });
  arms.forEach((a, i) => { const y = top + i * ch;
    el("text", {x: left - 8, y: y + ch / 2 + 4, "text-anchor": "end", class: "label"}, svg).textContent = a.name;
    cases.forEach(([id, t], j) => { const r = byKey[a.id + "|" + id]; const x = left + j * cw;
      const v = r && r.valid ? r.p_correct : null;
      const cell = el("rect", {x: x + .5, y: y + 1, width: cw - 1, height: ch - 2, rx: 1.5, fill: v == null ? "transparent" : seqColor(v), stroke: v == null ? "var(--rule)" : "none"}, svg);
      if (r && r.automatic_error) { el("path", {d: `M${x + 1.5},${y + 5} L${x + cw - 1.5},${y + ch - 5} M${x + cw - 1.5},${y + 5} L${x + 1.5},${y + ch - 5}`, stroke: "var(--critical)", "stroke-width": 1.6}, svg); }
      const opts = Object.entries(t.options).map(([k, d]) => `${k}: ${d}`).join("<br>");
      hover(cell, `<b>${a.name}</b> · ${id}<br><span class="m">${t.task}</span><br><span class="m">${(t.context || "").toString().slice(0, 160)}</span><br>${opts}<br>Expected <b>${t.expected}</b> · answered <b>${r?.predicted ?? "—"}</b>${r?.valid ? ` · p(correct) ${fmtPct(v)}` : " · " + (r?.error || "no reply")}${r?.automatic_error ? '<br><span class="flag">Wrong automatic decision</span>' : ""}`); }); });
  const ly = top + arms.length * ch + 18; el("text", {x: left, y: ly}, svg).textContent = "p(correct):";
  for (let k = 0; k <= 7; k++) { el("rect", {x: left + 70 + k * 22, y: ly - 10, width: 20, height: 12, rx: 2, fill: `var(--seq-${k})`}, svg); }
  el("text", {x: left + 70, y: ly + 14}, svg).textContent = "0"; el("text", {x: left + 70 + 7 * 22 + 8, y: ly + 14}, svg).textContent = "1";
}

/* ---------- confusion multiples ---------- */
function confusion() {
  const box = document.getElementById("confusion"); box.innerHTML = "";
  const labels = ["a", "b", "reason"];
  for (const a of [...ARMS].sort((x, y) => stat(y.id).accuracy - stat(x.id).accuracy)) {
    const rows = DATA.rows.filter(r => r.arm === a.id && r.order === 0 && r.kind !== "search" && (SCREEN === "all" || r.screen === SCREEN));
    const M = labels.map(() => labels.map(() => 0)); let invalid = 0;
    for (const r of rows) { if (!r.valid) { invalid++; continue; } const i = labels.indexOf(r.expected), j = labels.indexOf(r.predicted); if (i >= 0 && j >= 0) M[i][j]++; }
    const max = Math.max(1, ...M.flat()); const card = document.createElement("div");
    card.innerHTML = `<h3>${a.name}</h3>`; box.appendChild(card);
    const c = 36, left = 50, top = 16, svg = el("svg", {width: left + 3 * c + 4, height: top + 3 * c + 22, role: "img", "aria-label": a.name + " confusion matrix"}, card);
    labels.forEach((l, j) => el("text", {x: left + j * c + c / 2, y: 11, "text-anchor": "middle"}, svg).textContent = l);
    labels.forEach((l, i) => { el("text", {x: left - 6, y: top + i * c + c / 2 + 4, "text-anchor": "end"}, svg).textContent = l;
      labels.forEach((m, j) => { const v = M[i][j], f = v / max;
        const r = el("rect", {x: left + j * c + 1, y: top + i * c + 1, width: c - 2, height: c - 2, rx: 4, fill: v ? seqColor(.15 + .85 * f) : "var(--seq-0)"}, svg);
        const txt = el("text", {x: left + j * c + c / 2, y: top + i * c + c / 2 + 4, "text-anchor": "middle", style: `fill:${seqInk(v ? .15 + .85 * f : 0)};font-weight:${i === j ? 650 : 500}`}, svg); txt.textContent = v;
        hover(r, `<b>${a.name}</b><br>Correct answer <b>${l}</b>, judge said <b>${m}</b>: ${v} case${v === 1 ? "" : "s"}${i === 2 && j < 2 ? '<br><span class="flag">Acted when it should have deferred</span>' : ""}`); }); });
    el("text", {x: left, y: top + 3 * c + 16}, svg).textContent = invalid ? `${invalid} invalid` : "rows: correct · cols: judged";
  }
}

/* ---------- reliability multiples ---------- */
function reliability() {
  const box = document.getElementById("reliability"); box.innerHTML = "";
  const edges = [.5, .6, .7, .8, .9, 1.0001];
  for (const a of [...ARMS].sort((x, y) => (stat(x.id).mean_brier ?? 9) - (stat(y.id).mean_brier ?? 9))) {
    const rows = DATA.rows.filter(r => r.arm === a.id && r.order === 0 && r.valid && (SCREEN === "all" || r.screen === SCREEN));
    const card = document.createElement("div"); const brier = stat(a.id).mean_brier;
    card.innerHTML = `<h3>${a.name} · Brier ${brier == null ? "—" : brier.toFixed(3)}</h3>`; box.appendChild(card);
    const S = 140, m = 34, svg = el("svg", {width: S + m + 14, height: S + m, role: "img", "aria-label": a.name + " reliability diagram"}, card);
    const sx = v => m + (v - .5) / .5 * S, sy = v => S - v * S + 4;
    [0, .5, 1].forEach(v => { el("line", {x1: m, x2: m + S, y1: sy(v), y2: sy(v), class: "gridline"}, svg); el("text", {x: m - 5, y: sy(v) + 4, "text-anchor": "end"}, svg).textContent = Math.round(100 * v) + "%"; });
    [.5, .75, 1].forEach(v => el("text", {x: sx(v), y: S + 20, "text-anchor": "middle"}, svg).textContent = Math.round(100 * v) + "%");
    el("line", {x1: sx(.5), y1: sy(.5), x2: sx(1), y2: sy(1), stroke: "var(--diag)", "stroke-width": 1.5}, svg);
    const pts = [];
    for (let k = 0; k < edges.length - 1; k++) { const inBin = rows.filter(r => r.certainty >= edges[k] && r.certainty < edges[k + 1]);
      if (!inBin.length) continue; const conf = inBin.reduce((s, r) => s + r.certainty, 0) / inBin.length, acc = inBin.filter(r => r.correct).length / inBin.length;
      pts.push([conf, acc, inBin.length]); }
    if (pts.length > 1) el("path", {d: pts.map((p, i) => (i ? "L" : "M") + sx(p[0]) + "," + sy(p[1])).join(" "), fill: "none", stroke: FAMCOLOR[a.family], "stroke-width": 2}, svg);
    for (const [conf, acc, n] of pts) { const r = 3 + Math.sqrt(n) * 1.2;
      const c = el("circle", {cx: sx(conf), cy: sy(acc), r, fill: FAMCOLOR[a.family], stroke: "var(--surface-1)", "stroke-width": 2}, svg);
      const hit = el("circle", {cx: sx(conf), cy: sy(acc), r: Math.max(12, r + 4), fill: "transparent"}, svg);
      hover(hit, `<b>${a.name}</b><br>Said ${fmtPct(conf)} sure on average<br>Right ${fmtPct(acc)} of the time<br>${n} decisions`); }
  }
}

/* ---------- latency strips ---------- */
function latency() {
  const box = document.getElementById("latency"); box.innerHTML = "";
  const arms = [...ARMS].sort((x, y) => stat(x.id).p50_ms - stat(y.id).p50_ms);
  const W = box.clientWidth || 520, left = 96, rowH = 30, top = 8, H = top + arms.length * rowH + 34;
  const all = DATA.rows.filter(r => r.valid).map(r => r.ms); const x0 = Math.max(5, Math.min(...all) / 1.3), x1 = Math.max(...all, 3500) * 1.3;
  const sx = v => left + (Math.log(v) - Math.log(x0)) / (Math.log(x1) - Math.log(x0)) * (W - left - 12);
  const svg = el("svg", {width: W, height: H, role: "img", "aria-label": "Latency distribution per judge"}, box);
  [10, 30, 100, 300, 1000, 3000, 10000].filter(v => v >= x0 && v <= x1).forEach(v => { el("line", {x1: sx(v), x2: sx(v), y1: top, y2: top + arms.length * rowH, class: "gridline"}, svg);
    el("text", {x: sx(v), y: top + arms.length * rowH + 16, "text-anchor": "middle"}, svg).textContent = fmtMs(v); });
  el("line", {x1: sx(3000), x2: sx(3000), y1: top - 4, y2: top + arms.length * rowH, stroke: "var(--critical)", "stroke-width": 1.5}, svg);
  el("text", {x: sx(3000) + 4, y: top + 6, style: "fill:var(--critical)"}, svg).textContent = "3 s timeout";
  arms.forEach((a, i) => { const y = top + i * rowH + rowH / 2; el("text", {x: left - 8, y: y + 4, "text-anchor": "end", class: "label"}, svg).textContent = a.name;
    const ms = DATA.rows.filter(r => r.arm === a.id && r.valid).map(r => r.ms);
    ms.forEach((v, k) => el("circle", {cx: sx(v), cy: y + ((k * 37) % 13 - 6), r: 1.8, fill: FAMCOLOR[a.family], opacity: .45}, svg));
    const s = stat(a.id); el("line", {x1: sx(s.p50_ms), x2: sx(s.p50_ms), y1: y - 10, y2: y + 10, stroke: "var(--text-primary)", "stroke-width": 2}, svg);
    const hit = el("rect", {x: left, y: y - rowH / 2, width: W - left, height: rowH, fill: "transparent"}, svg);
    hover(hit, `<b>${a.name}</b><br>p50 ${fmtMs(s.p50_ms)} · p95 ${fmtMs(s.p95_ms)}<br>${fmtPct(s.within_production_timeout)} within the 3 s timeout<br>${ms.length} decisions, both passes`); });
  el("text", {x: left, y: H - 4}, svg).textContent = "Dots: individual decisions · bar: median";
}

/* ---------- stability ---------- */
function stability() {
  const box = document.getElementById("stability"); box.innerHTML = "";
  const arms = [...ARMS].sort((x, y) => DATA.summary[x.id].order_check.changed - DATA.summary[y.id].order_check.changed);
  const W = box.clientWidth || 520, left = 96, rowH = 30, H = 8 + arms.length * rowH + 20;
  const max = Math.max(5, ...arms.map(a => DATA.summary[a.id].order_check.changed));
  const svg = el("svg", {width: W, height: H, role: "img", "aria-label": "Answers changed under option reordering"}, box);
  arms.forEach((a, i) => { const y = 8 + i * rowH, oc = DATA.summary[a.id].order_check, w = oc.changed / max * (W - left - 60);
    el("text", {x: left - 8, y: y + rowH / 2 + 4, "text-anchor": "end", class: "label"}, svg).textContent = a.name;
    const bar = el("rect", {x: left, y: y + 7, width: Math.max(w, 1.5), height: rowH - 14, rx: 4, fill: FAMCOLOR[a.family]}, svg);
    el("text", {x: left + Math.max(w, 1.5) + 6, y: y + rowH / 2 + 4}, svg).textContent = `${oc.changed} of ${oc.pairs}`;
    hover(bar, `<b>${a.name}</b><br>${oc.changed} of ${oc.pairs} answers changed when options were reversed`); });
}

function method() {
  const m = DATA.manifest, p = m.prices_usd_per_mtok;
  document.getElementById("method").innerHTML = `<ul class="tight">
  <li><b>Cases.</b> ${m.source}. Hand-authored labels, not independently audited. Constructed text decisions over public observations: diagnostic screens, not live browser tasks, tool executions or SWE-bench. The screens were built before Jev and Laya were queried; they were never shown to nimble, tev1, Qwen or Luna before this run, and no prompt was tuned for any arm.</li>
  <li><b>Protocol.</b> Jev, nimble, tev1 and Laya received byte-identical System One payloads. Qwen models ran through the bundle's production OllamaBackend, which asks both option orders and averages them (two model calls per decision); the backend's rule that drops an option named "reason" was disabled so every arm answered the same three-way question. GPT-6 Luna ran through Chat Completions with reasoning effort "none" and stated its probabilities in strict structured output, renormalized to sum to 1.</li>
  <li><b>GPT-6 Luna* is a stand-in.</b> OpenAI's Decisions API (announced September 29, limited preview, built on GPT-6 Luna) has no public endpoint, model ID or schema, and this key cannot see it. Luna returns no token probabilities, so its confidence is self-reported: compare its accuracy and latency directly, and treat its calibration and automatic-decision numbers with care.</li>
  <li><b>Scoring.</b> The Laya study's own <code>score()</code>: automatic = non-"reason" choice or yes/no certainty ≥ ${m.threshold}. Accuracy counts invalid replies as wrong. Brier is averaged over valid replies. First pass only; the reversed pass is used for the stability check.</li>
  <li><b>Latency.</b> Wall-clock per decision from this machine, two warmups per arm excluded. Each arm ran as one contiguous block so Ollama did not swap models mid-run. Cloud latency includes the network. Local latency depends on this Apple M5 Max (128 GB) and on what else was running.</li>
  <li><b>Cost.</b> List prices on 2026-09-30: Jev $${p.jev[0]} per million input tokens, output free (docs.typesafe.ai/models); GPT-6 Luna $${p["gpt-6-luna"][0]} input and $${p["gpt-6-luna"][1]} output per million (developers.openai.com). Token counts come from each API's usage report. Local judges have no API charge; hardware, electricity and memory pressure are not priced.</li>
  <li><b>Small samples.</b> 90 cases; per-type cells have 30 or fewer, and the fresh screen alone has 10 per type. Differences of a few cases are within noise. This screens candidates; it does not establish production savings or safety.</li></ul>`;
}

function takeaways() {
  const acc = a => stat(a).accuracy; const byAcc = [...ARMS].sort((x, y) => acc(y.id) - acc(x.id));
  const lines = byAcc.map(a => `<li><b>${a.name}</b>: ${fmtPct(acc(a.id))} correct, ${stat(a.id).automatic_errors} wrong automatic of ${stat(a.id).automatic}, median ${fmtMs(stat(a.id).p50_ms)}, ${fmtUsd(costPer1k(a.id))} per 1k decisions.</li>`).join("");
  document.getElementById("takeaways").innerHTML = (window.TAKEAWAYS || "") + `<details><summary>All judges at a glance</summary><ul class="tight">${lines}</ul></details>`;
}

function render() { tiles(); takeaways(); board(); scatters(); sweep(); kindMatrix(); caseMatrix(); confusion(); reliability(); latency(); stability(); method(); }
document.querySelectorAll("[data-screen]").forEach(b => b.onclick = () => { SCREEN = b.dataset.screen;
  document.querySelectorAll("[data-screen]").forEach(x => x.setAttribute("aria-pressed", x === b)); render(); });
const themeBtn = document.getElementById("theme");
themeBtn.onclick = () => { const dark = document.documentElement.dataset.theme !== "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light"; themeBtn.setAttribute("aria-pressed", dark); themeBtn.textContent = dark ? "Light mode" : "Dark mode"; };
let resizeTimer; addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150); });
window.TAKEAWAYS = __TAKEAWAYS__;
render();
</script>
</body>
</html>
"""


def main():
    directory = Path(sys.argv[1])
    takeaways_file = directory / "takeaways.html"
    data = load(directory)
    html = (TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
            .replace("__TAKEAWAYS__", json.dumps(takeaways_file.read_text() if takeaways_file.exists() else ""))
            .replace("__DATE__", "September 30, 2026"))
    (directory / "index.html").write_text(html)
    print(directory / "index.html")


if __name__ == "__main__":
    main()
