#!/usr/bin/env python3
"""Trace-derived decision-judge candidates (read-only; no model/API calls).

Survey real Amplifier sessions for fast-decisions judge decision points, rebuild
the judge payload from the session transcript with the package's OWN state
builders (src/amplifier_fast_decisions), verify each rebuild against the
privacy-safe scalars the live run logged, and attach an outcome label from what
actually happened next / the graded run result.

    python extract_traces.py survey                # -> survey_counts.json
    python extract_traces.py extract --per-kind 10 # -> candidates.jsonl

Inputs (read-only): ~/.amplifier/projects/*/sessions/<uuid>/{events,transcript}.jsonl,
metadata.json -> working_dir -> <run>/result.json (S1/S2) or the SWE-bench
study's report.json / grading/*.json (S3). Never prints whole events.jsonl lines.
Writes only into this directory and $FD_TRACES_CACHE (default: the scratch dir).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in src/ or here

HERE = Path(__file__).resolve().parent
REPO = next(p for p in HERE.parents if (p / "src" / "amplifier_fast_decisions").is_dir())
sys.path.insert(0, str(REPO / "src"))

from amplifier_fast_decisions import effort, orchestrator, step_actions  # noqa: E402
from amplifier_fast_decisions.backends import _build_questions  # noqa: E402
from amplifier_fast_decisions.contracts import (  # noqa: E402
    Candidate, DecisionRequest, canonical, compute_candidate_order_hash, digest)
from amplifier_fast_decisions.state import build_state  # noqa: E402
from amplifier_fast_decisions.workspace import WorkspaceTool  # noqa: E402

PROJECTS = Path.home() / ".amplifier" / "projects"
# The rg index is ~130 MB: keep it out of the repo tree by default.
CACHE = Path(os.environ.get("FD_TRACES_CACHE",
                            REPO / ".amplifier/evaluation/fast-decisions/20261001-realistic/traces/.cache"))
SELECT = re.compile(r"afast|fast-decisions|ampup|ev-s1d")
EVENT_RE = re.compile(r'"event": "([^"]+)"')
WANTED = ("requested|scored|routed|step_decided|difficulty_judged|model_routed|effort_routed|"
          "shadow_proposed|shadow_observed|shadow_agreement|turn_start|source")
RG_PATTERN = (r'^\{"ts": "[^"]*", "lvl": "[A-Z]+", "schema": \{[^}]*\}, "event": '
              r'"(fast_decisions:(' + WANTED + r')|tool:pre|prompt:submit)"')
# The live ChatRequest carries ephemeral non-transcript messages (system-role
# context injections) that build_state skips by role but that still occupy the
# 12-message window. Verified: one such stub reproduces the logged scalars exactly.
SYNTHETIC_REMINDER = {"role": "system", "content": "[ephemeral context injection]"}
DESTRUCTIVE_RE = re.compile(
    r"\brm\s+-[a-zA-Z]*[rf]|\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+(-f|--force)|checkout\s+--\s|restore\s)"
    r"|\bdrop\s+(table|database)\b|\btruncate\b|(^|[^>2&=\-])>\s*(?!/dev/null)[\w./-]+|\bmv\s|\bsed\s+-i|\bdd\s", re.I)


def _historical_build_state(rev: str):
    """build_state as it existed at ``rev`` (read via ``git show``, loaded in memory).
    Sessions recorded before a3a2c03 (2026-09-25) ran the older task-anchoring rule."""
    import types
    try:
        src = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:src/amplifier_fast_decisions/state.py"],
                             capture_output=True, text=True, check=True).stdout
    except Exception:
        return None
    mod = types.ModuleType(f"amplifier_fast_decisions._state_{rev.replace('^', '_parent')}")
    mod.__package__ = "amplifier_fast_decisions"
    exec(compile(src, f"state.py@{rev}", "exec"), mod.__dict__)
    return mod.build_state


BUILDERS = [("HEAD", build_state)]
_old = _historical_build_state("a3a2c03^")
if _old is not None:
    BUILDERS.append(("a3a2c03^ (pre-2026-09-25)", _old))

KINDS = ("read_shortcut", "difficulty", "escalation", "phase", "tool_risk")
EXTERNAL_HARNESS = ("claude", "codex", "opencode")


def short(text, n=300):
    text = text if isinstance(text, str) else json.dumps(text, default=str)
    return text if len(text) <= n else text[:n] + f"...[+{len(text) - n} chars]"


# --------------------------------------------------------------------------- index
def events_files() -> list[str]:
    out = []
    for d in os.listdir(PROJECTS):
        if SELECT.search(d):
            out += glob.glob(str(PROJECTS / d / "sessions" / "*" / "events.jsonl"))
    return sorted(out)


def build_index(refresh=False) -> Path:
    """One rg pass over every events.jsonl: only the small decision/tool lines."""
    CACHE.mkdir(parents=True, exist_ok=True)
    idx = CACHE / "index.txt"
    if idx.exists() and not refresh:
        return idx
    files = events_files()
    with open(idx, "w") as fh:
        for i in range(0, len(files), 400):
            subprocess.run(["rg", "-n", "--with-filename", RG_PATTERN, *files[i:i + 400]], stdout=fh, check=False)
    return idx


def iter_index(idx: Path):
    for line in open(idx, encoding="utf-8"):
        path, lineno, rest = line.split(":", 2)
        m = EVENT_RE.search(rest[:250])
        yield path, int(lineno), m.group(1), rest


# --------------------------------------------------------------------------- sessions
_sess: dict[str, dict] = {}
_s3_reports: dict[str, dict] = {}
_task_table: dict | None = None


def _s3_resolved(run_dir: Path, result: dict):
    study = run_dir.parent.parent
    inst, arm, rep = result.get("instance_id"), result.get("arm"), result.get("rep", 1)
    rpt = study / "report.json"
    if rpt.exists():
        r = _s3_reports.setdefault(str(rpt), json.loads(rpt.read_text()))
        v = r.get("per_instance", {}).get(f"{inst} r{rep}", {}).get(arm)
        if v is not None:
            return v.get("resolved"), str(rpt)
    for g in glob.glob(str(study / "grading" / f"{arm}.{arm}-{inst}-*-r{rep}.json")):
        d = json.loads(Path(g).read_text())
        return inst in d.get("resolved_ids", []), g
    return None, None


def session(events_path: str) -> dict:
    if events_path in _sess:
        return _sess[events_path]
    sdir = Path(events_path).parent
    info = {"events": str(events_path), "transcript": str(sdir / "transcript.jsonl"), "working_dir": "",
            "run_dir": None, "result": None, "suite": "X", "task": None, "arm": None, "model": None,
            "passed": None, "grading": None, "max_state_chars": 12000}
    try:
        info["working_dir"] = json.loads((sdir / "metadata.json").read_text()).get("working_dir", "") or ""
    except Exception:
        pass
    w = info["working_dir"]
    if w:
        run = Path(w).parent
        info["run_dir"] = str(run)
        rj = run / "result.json"
        if rj.exists():
            info["result"] = str(rj)
            try:
                r = json.loads(rj.read_text())
            except Exception:
                r = {}
            info["model"] = r.get("model")
            info["arm"] = r.get("arm") or r.get("harness")
            info["task"] = r.get("instance_id") or r.get("task")
            if "swebench" in w:
                info["passed"], info["grading"] = _s3_resolved(run, r)
            else:
                info["passed"] = r.get("outcome_passed")
        prof = run / "profile.md"
        if prof.exists():
            m = re.search(r'"max_state_chars":\s*(\d+)', prof.read_text(errors="ignore"))
            if m:
                info["max_state_chars"] = int(m.group(1))
    if "swebench" in w:
        info["suite"] = "S3"
    elif "/POLY-" in w or "poly_" in w:
        info["suite"] = "S2"
    elif any(x in w for x in ("afast-ev/", "/ev/s1d", "afast-orch-primary", "/FIX-", "afast-campaign")):
        info["suite"] = "S1"
    info["task"] = info["task"] or (Path(w).parent.name if w else None)
    _sess[events_path] = info
    return info


def task_table() -> dict:
    """Per-task pass counts by harness/model tier across every graded S1/S2 run."""
    global _task_table
    if _task_table is not None:
        return _task_table
    roots = [Path.home() / p for p in ("dev/afast-ev", "ev/s1d", "dev/afast-orch-primary-20260924")]
    roots += [Path(p) for p in glob.glob(str(Path.home() / "dev/afast-campaign-*"))]
    table: dict = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for root in roots:
        found = subprocess.run(["find", str(root), "-name", "workspace", "-prune", "-o", "-name", "source",
                                "-prune", "-o", "-name", "result.json", "-print"], capture_output=True, text=True)
        for rj in found.stdout.split():
            try:
                r = json.loads(Path(rj).read_text())
            except Exception:
                continue
            if r.get("outcome_passed") is None or r.get("infrastructure_failure"):
                continue
            m = r.get("model") or ""
            tier = ("haiku" if "haiku" in m else "sonnet" if "sonnet" in m
                    else "strong" if ("opus" in m or "fable" in m) else "other")
            cell = table[r.get("task")][f"{r.get('harness')}/{tier}"]
            cell[0] += bool(r["outcome_passed"])
            cell[1] += 1
    _task_table = {k: dict(v) for k, v in table.items()}
    return _task_table


# --------------------------------------------------------------------------- session parse
def _loads(x):
    try:
        return json.loads(x) if isinstance(x, str) else (x or {})
    except ValueError:
        return {}


def parse_session(info: dict):
    """Small fields only: fast_decisions events (minus health), tool:pre, prompt:submit."""
    ev = []
    with open(info["events"], encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            m = EVENT_RE.search(line[:250])
            if not m:
                continue
            name = m.group(1)
            if name == "fast_decisions:health" or not (name.startswith("fast_decisions:")
                                                      or name in ("tool:pre", "prompt:submit")):
                continue
            d = json.loads(line).get("data") or {}
            if name == "tool:pre":
                ti = d.get("tool_input") or {}
                ti = ti if isinstance(ti, dict) else {}
                d = {"tool_name": d.get("tool_name"), "tool_call_id": d.get("tool_call_id"),
                     "argument_keys": sorted(ti), "command": short(ti.get("command", ""), 400),
                     "operation": ti.get("operation"), "path": ti.get("file_path") or ti.get("path")}
            elif name == "prompt:submit":
                d = {"prompt": d.get("prompt")}
            ev.append((i, name, d))
    tp = Path(info["transcript"])
    tr = [json.loads(x) for x in open(tp, encoding="utf-8")] if tp.exists() else []
    return ev, tr


def step_map(ev, tr):
    """k-th routed event (one per provider complete() call) <-> k-th assistant message."""
    asst = [k for k, m in enumerate(tr) if m.get("role") == "assistant"]
    routed = [(i, d) for i, n, d in ev if n == "fast_decisions:routed"]
    by_did = {}
    for k, (i, d) in enumerate(routed):
        by_did.setdefault(d.get("decision_id"), (k, i, d.get("data", {})))
    return asst, routed, by_did


def request_at(tr, asst, k):
    if k is None or k >= len(asst):
        return None
    return {"messages": tr[:asst[k]] + [SYNTHETIC_REMINDER]}


def next_calls(tr, asst, k):
    if k is None or k >= len(asst):
        return []
    return [{"name": c.get("tool") or c.get("name") or (c.get("function") or {}).get("name"),
             "arguments": c.get("arguments") if isinstance(c.get("arguments"), dict)
             else _loads(c.get("arguments") or (c.get("function") or {}).get("arguments"))}
            for c in tr[asst[k]].get("tool_calls") or []]


# --------------------------------------------------------------------------- read shortcut
def rebuild_candidates(info, request, step_kind, logged):
    """Regenerate candidates with the package's own generators; keep logged ids only.
    Ids are digests of (relative path[, line]), so an id match proves the target."""
    wd = info["working_dir"]
    if not wd or not Path(wd).exists():
        return [], "workspace_missing"
    ws = WorkspaceTool(wd)
    pool = []
    try:
        view = step_actions.analyze(request)
        for kind in {step_kind, step_actions.TURN_START, step_actions.ROUTINE} - {None}:
            pool += step_actions.candidates_for(view, kind, ws, max_candidates=12)
    except Exception:
        pass
    pattern = r"(?<![\w/])(?:\./)?[\w./-]+\.(?:md|txt|py|js|ts|tsx|jsx|json|yaml|yml|toml|rs|html|css)\b"
    for m in request["messages"]:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            for i, p in enumerate(dict.fromkeys(re.findall(pattern, m["content"]))):
                try:
                    c = ws.candidate_for_path(p, i)
                except Exception:
                    c = None
                if c:
                    pool.append(c)
    want = {c["id"]: c for c in logged}
    got = {}
    for c in pool:
        if c.id in want and c.id not in got:
            got[c.id] = Candidate(c.id, want[c.id]["label"], c.tool, c.arguments, rationale=c.rationale, origin=c.origin)
    missing = [i for i in want if i not in got]
    return [got[c["id"]] for c in logged if c["id"] in got], ("ok" if not missing else f"missing:{len(missing)}/{len(want)}")


def _same_read(cand: Candidate, call: dict, workdir: str) -> bool:
    """The host model's next call reads the candidate's file (fast_workspace read or
    read_file). For a line-window candidate the read must overlap the window."""
    a = call.get("arguments") or {}
    target = a.get("path") or a.get("file_path")
    if not target or call.get("name") not in ("fast_workspace", "read_file"):
        return False
    if call.get("name") == "fast_workspace" and a.get("operation") not in (None, "read"):
        return False
    rel = os.path.relpath(target, workdir) if os.path.isabs(target) else target
    norm = lambda p: str(p)[2:] if str(p).startswith("./") else str(p)  # noqa: E731
    if norm(rel) != norm(cand.arguments.get("path", "")):
        return False
    line = cand.arguments.get("line")
    if not line:
        return True
    try:
        start = int(a.get("offset") or a.get("line") or 1)
        end = start + int(a.get("limit") or 10**9)
    except (TypeError, ValueError):
        return True
    return start < line + 85 and end > max(1, line - 15)


def extract_read_shortcut(info, ev, tr):
    asst, routed, by_did = step_map(ev, tr)
    stepd = {d.get("decision_id"): d.get("data", {}) for i, n, d in ev if n == "fast_decisions:step_decided"}
    scored = {d.get("decision_id"): (i, d.get("data", {})) for i, n, d in ev if n == "fast_decisions:scored"}
    for i, n, d in ev:
        if n != "fast_decisions:requested":
            continue
        did, dd = d.get("decision_id"), d.get("data", {})
        k, ri, rd = by_did.get(did, (None, None, {}))
        req = request_at(tr, asst, k)
        if req is None:
            continue
        sd = stepd.get(did, {})
        instr = step_actions.STEP_INSTRUCTION if sd.get("judge_asked") else None
        # The live request may carry 0-2 ephemeral reminder messages the transcript
        # lacks; try 1, 0, 2 and keep the first variant whose five logged scalars all match.
        base = req["messages"][:-1]
        state, state_ok, first = None, False, None
        for builder_name, builder in BUILDERS:
            for n_eph in (1, 0, 2):
                req = {"messages": base + [SYNTHETIC_REMINDER] * n_eph}
                stats: dict = {}
                try:
                    try:
                        cand_state = builder(req, info["max_state_chars"], stats, instr)
                    except TypeError:  # pre-a3a2c03 signature: no instruction parameter
                        cand_state = builder(req, info["max_state_chars"], stats)
                except ValueError:
                    continue
                checks = {f: [stats.get(f), dd.get(f)] for f in ("state_chars", "observation_count",
                          "observations_available", "observations_dropped", "observations_clipped")}
                if first is None:
                    first = (cand_state, checks, n_eph, builder_name, req)
                if all(a == b for a, b in checks.values()):
                    state, state_ok = cand_state, True
                    break
            if state_ok:
                break
        if not state_ok and first is not None:
            state, checks, n_eph, builder_name, req = first
        if state is None:
            continue
        cands, cstatus = rebuild_candidates(info, req, sd.get("step_class"), dd.get("candidates") or [])
        order_ok = bool(cands) and compute_candidate_order_hash(cands) == dd.get("candidate_order_hash")
        questions, _ = _build_questions(DecisionRequest(state=state, candidates=tuple(cands), questions=()))
        q = questions["next_action"]
        crit = {cid: (canonical(v) if isinstance(v, dict) else v) for cid, v in q["criteria"].items()}
        calls = next_calls(tr, asst, k)
        fast = rd.get("route") == "fast"
        if fast:
            label, src = rd.get("selected_candidate"), "prepared_action_executed (the judge's own pick)"
            quality = "weak: no counterfactual; the slow model never saw this step"
        else:
            hit = [c.id for c in cands for call in calls if _same_read(c, call, info["working_dir"])]
            label = hit[0] if hit else "reason"
            src = "slow_model_next_tool_call" + (f" (1 of {len(calls)} parallel calls)" if len(calls) > 1 and hit else "")
            quality = "medium: imitation of the host model's actual next step"
        si, sdat = scored.get(did, (None, {}))
        yield {
            "kind": "read_shortcut", "suite": info["suite"], "task": info["task"],
            "decision_request": {"state": state, "candidates": [
                {k2: v for k2, v in c.__dict__.items() if k2 != "revision"} for c in cands]},
            "payload": {"state": canonical(state), "questions": {"decision": {
                "type": "choice", "instructions": q["instructions"], "criteria": crit}}},
            "wire_question_name": "next_action", "expected": label,
            "label": {"value": label, "source": src, "quality": quality,
                      "next_calls": [{"name": c["name"], "arguments": short(c["arguments"], 200)} for c in calls]},
            "original_judge": {"choice": sdat.get("choice"), "probabilities": sdat.get("probabilities"),
                               "model": sdat.get("model"), "route": rd.get("route"), "reason_code": rd.get("reason_code")},
            "rebuild": {"status": "exact" if (state_ok and order_ok and cstatus == "ok") else "partial",
                        "option_set_hash_logged": sdat.get("option_set_hash"),
                        "state_checks": checks, "ephemeral_messages": n_eph, "state_builder": builder_name, "candidates": cstatus, "candidate_order_hash_match": order_ok,
                        "method": "transcript prefix + 1 ephemeral reminder -> state.build_state(max_state_chars from "
                                  "profile); candidates via workspace.candidate_for_path / step_actions.candidates_for"},
            "lines": {"requested": i, "routed": ri, "scored": si},
            "step_k": k, "decision_id": did,
            "logged": {f: dd.get(f) for f in ("question_count", "candidate_count", "task_anchored", "truncation_reason",
                                              "observations_clipped", "observations_dropped", "domain")},
            "dedupe": digest([info["task"], sorted(c["id"] for c in dd.get("candidates") or []), dd.get("observation_count")]),
            "hardness": {"state_chars": dd.get("state_chars"), "candidate_count": dd.get("candidate_count"),
                         "judge_vs_label_disagree": None if fast or sdat.get("choice") is None else sdat.get("choice") != label},
        }


# --------------------------------------------------------------------------- difficulty
def tier_label(task):
    t = task_table().get(task)
    if not t:
        return None, None, "no graded runs for task"
    ours = {k: v for k, v in t.items() if not k.startswith(EXTERNAL_HARNESS)}
    cheap = [v for k, v in ours.items() if k.endswith(("/haiku", "/sonnet"))]
    strong = [v for k, v in ours.items() if k.endswith("/strong")]
    cp, cn = sum(v[0] for v in cheap), sum(v[1] for v in cheap)
    sp, sn = sum(v[0] for v in strong), sum(v[1] for v in strong)
    summary = {k: f"{v[0]}/{v[1]}" for k, v in t.items()}
    if not cn:
        return None, summary, "no cheap-tier runs"
    cr, sr = cp / cn, (sp / sn if sn else None)
    if cr >= 0.9:
        return "simple", summary, f"cheap tier passed {cp}/{cn}"
    if cr <= 0.6 and sr is not None and sr >= cr + 0.3:
        return "complex", summary, f"cheap {cp}/{cn} vs strong {sp}/{sn}"
    return None, summary, f"ambiguous: cheap {cp}/{cn}, strong {sp}/{sn}"


_swe_meta: dict = {}
PROBE_SET = Path.home() / "dev/afast-ev/difficulty-dataset.jsonl"  # used to tune the difficulty question


def swe_difficulty(info):
    """SWE-bench Verified human time-to-fix annotation for an S3 run + probe-set overlap."""
    study = Path(info["run_dir"]).parent.parent if info["run_dir"] else None
    ds = study / "grading" / "dataset.jsonl" if study else None
    if ds and str(ds) not in _swe_meta and ds.exists():
        _swe_meta[str(ds)] = {json.loads(x)["instance_id"]: json.loads(x).get("difficulty") for x in open(ds)}
    if "probe" not in _swe_meta:
        _swe_meta["probe"] = ({json.loads(x)["id"] for x in open(PROBE_SET)} if PROBE_SET.exists() else set())
    ann = _swe_meta.get(str(ds), {}).get(info["task"]) if ds else None
    lab = {"<15 min fix": "simple", "1-4 hours": "complex", ">4 hours": "complex"}.get(ann)
    return lab, ann, info["task"] in _swe_meta["probe"]


def extract_difficulty(info, ev, tr):
    asst, routed, by_did = step_map(ev, tr)
    if info["suite"] == "S3" and routed:
        # The difficulty router never ran on S3; its payload is fully determined by
        # the turn's prompt, so rebuild it at the turn's first provider call.
        req = request_at(tr, asst, 0)
        if req is not None:
            task = orchestrator._turn_user_text(req)
            state = {"task": task[:orchestrator._DIFFICULTY_STATE_CHARS]}
            lab, ann, in_probe = swe_difficulty(info)
            yield {
                "kind": "difficulty", "suite": "S3", "task": info["task"],
                "payload": {"state": canonical(state), "questions": {"decision": {
                    "type": "choice", "instructions": orchestrator.DIFFICULTY_INSTRUCTIONS,
                    "criteria": dict(orchestrator.DIFFICULTY_CRITERIA)}}},
                "wire_question_name": "task_difficulty", "expected": lab,
                "label": {"value": lab, "source": "SWE-bench Verified human time-to-fix annotation "
                                                  "(<15 min -> simple, >=1 h -> complex; 15 min-1 h unlabelled)",
                          "quality": "medium: independent human estimate, not an outcome; secondary = this run resolved",
                          "annotation": ann, "this_run_resolved": info["passed"],
                          "in_difficulty_probe_tuning_set": in_probe},
                "original_judge": None,
                "rebuild": {"status": "counterfactual-exact",
                            "note": "router not enabled on S3; state is a pure function of the prompt"},
                "lines": {"routed": routed[0][0]}, "dedupe": digest(state),
                "hardness": {"state_chars": len(task), "judge_vs_label_disagree": None},
            }
        return
    for i, n, d in ev:
        dd = d.get("data", {})
        if n != "fast_decisions:difficulty_judged" or not str(dd.get("reason_code", "")).startswith(("judge_", "scope_judge")):
            continue
        k, ri, _ = by_did.get(d.get("decision_id"), (None, None, {}))
        req = request_at(tr, asst, k)
        if req is None:
            continue
        task = orchestrator._turn_user_text(req)
        state = {"task": task[:orchestrator._DIFFICULTY_STATE_CHARS]}
        ok = len(task) == dd.get("state_chars")
        lab, summ, why = (None, None, "S3: no cheap-tier arm") if info["suite"] == "S3" else tier_label(info["task"])
        p = (dd.get("probabilities") or {}).get("complex")
        yield {
            "kind": "difficulty", "suite": info["suite"], "task": info["task"],
            "payload": {"state": canonical(state), "questions": {"decision": {
                "type": "choice", "instructions": orchestrator.DIFFICULTY_INSTRUCTIONS,
                "criteria": dict(orchestrator.DIFFICULTY_CRITERIA)}}},
            "wire_question_name": "task_difficulty", "expected": lab,
            "label": {"value": lab, "source": "task-level pass rate by model tier across all graded S1/S2 runs",
                      "quality": "medium-low: ceiling (cheap tier passes ~94% of runs); task-level not turn-level",
                      "why": why, "pass_table": summ, "this_run_passed": info["passed"]},
            "original_judge": {"choice": dd.get("choice"), "p_complex": p, "reason_code": dd.get("reason_code")},
            "rebuild": {"status": "exact" if ok else "partial",
                        "state_checks": {"len(task)_vs_logged_state_chars": [len(task), dd.get("state_chars")]},
                        "method": "orchestrator._turn_user_text(transcript prefix)[:2500]"},
            "lines": {"difficulty_judged": i, "routed": ri}, "dedupe": digest(state),
            "hardness": {"state_chars": dd.get("state_chars"),
                         "judge_vs_label_disagree": None if lab is None or p is None else ((p >= 0.5) != (lab == "complex"))},
        }


# --------------------------------------------------------------------------- escalation / phase (counterfactual)
def _judge_state_counterfactual(req, k_in_turn, max_chars):
    prefix = req["messages"][:-1]
    last_user = max((j for j, m in enumerate(prefix) if m.get("role") == "user"
                     and isinstance(m.get("content"), str) and step_actions.is_user_turn(m)), default=0)
    turn_msgs = prefix[last_user:]
    tools = {c.get("tool") or c.get("name") for m in turn_msgs if m.get("role") == "assistant"
             for c in (m.get("tool_calls") or [])}
    last_tool = next((m.get("content") for m in reversed(turn_msgs) if m.get("role") == "tool"), "") or ""
    turn = type("TurnStateView", (), {
        "slow_requests_seen": k_in_turn, "tool_names_used": {t for t in tools if t},
        "last_tool_result_text": last_tool if isinstance(last_tool, str) else canonical(last_tool),
        "test_failure_seen": False, "provider_errors_seen": 0})()
    phase = effort.classify_phase(req)
    return orchestrator._judge_state(req, turn, phase, max_chars), phase


def _steps_with_turn(ev, routed):
    prompts = [i for i, n, d in ev if n == "prompt:submit"]
    counts = collections.Counter()
    for k, (ri, rd) in enumerate(routed):
        t = sum(1 for p in prompts if p < ri)
        counts[t] += 1
        yield k, ri, rd, t, counts[t]


def extract_escalation_phase(info, ev, tr):
    asst, routed, by_did = step_map(ev, tr)
    mr = {d.get("decision_id"): (i, d.get("data", {})) for i, n, d in ev if n == "fast_decisions:model_routed"}
    er = {d.get("decision_id"): (i, d.get("data", {})) for i, n, d in ev if n == "fast_decisions:effort_routed"}
    steps = list(_steps_with_turn(ev, routed))
    escalated_turns = {t for (k, ri, rd, t, kin) in steps
                       if str(mr.get(rd.get("decision_id"), (0, {}))[1].get("reason_code", "")).startswith("escalated_")}
    for k, ri, rd, t, kin in steps:
        req = request_at(tr, asst, k)
        if req is None:
            continue
        did = rd.get("decision_id")
        state, phase = _judge_state_counterfactual(req, kin, info["max_state_chars"])
        calls = next_calls(tr, asst, k)
        mi, md = mr.get(did, (None, {}))
        rc = str(md.get("reason_code", ""))
        common = {"suite": info["suite"], "task": info["task"], "original_judge": None}
        if mi is not None and kin > 1 and (rc == "start_model" or rc.startswith("escalated_")):
            if rc == "escalated_test_failure":
                lab, src = "escalate", "rule fired at this step: test failure seen while on the cheap model"
            elif rc == "escalated_max_requests":
                lab, src = None, "budget rule (max_requests) fired -- not evidence the cheap model failed"
            elif t not in escalated_turns and info["passed"] is True:
                lab, src = "continue_cheap", "cheap-started turn finished on the cheap model and the run passed"
            elif t not in escalated_turns and info["passed"] is False:
                lab, src = "escalate", "cheap-started turn never escalated and the run FAILED (turn-level; step unknown)"
            else:
                lab, src = None, "turn escalated later; this step's label is unknown"
            q = orchestrator._escalation_question()
            yield {**common, "kind": "escalation",
                   "payload": {"state": canonical(state), "questions": {"decision": {
                       "type": "choice", "instructions": q.instructions, "criteria": dict(q.criteria)}}},
                   "wire_question_name": "escalation_judge", "expected": lab,
                   "label": {"value": lab, "source": src, "quality": "low: rule trigger or turn-level run outcome",
                             "model_routed_reason": rc, "requested_model": md.get("requested_model"),
                             "run_passed": info["passed"]},
                   "rebuild": {"status": "counterfactual-partial",
                               "note": "escalation judge never ran in any logged session; last_tool_result_excerpt "
                                       "uses transcript JSON (live code stringifies a ToolResult); test_failure_seen/"
                                       "provider_errors_seen not reconstructed (False/0)"},
                   "lines": {"routed": ri, "model_routed": mi},
                   "dedupe": digest([info["task"], t, kin]), "hardness": {"step_in_turn": kin}}
        ei, ed = er.get(did, (None, {}))
        if ei is not None:
            nxt = calls[0]["name"] if calls else None
            behav = ("implement" if nxt in ("edit_file", "write_file", "apply_patch") else
                     "explore" if nxt in ("read_file", "grep", "glob", "fast_workspace", "jevgrep", "LSP") else None)
            q = orchestrator._phase_question()
            yield {**common, "kind": "phase",
                   "payload": {"state": canonical(state), "questions": {"decision": {
                       "type": "choice", "instructions": q.instructions, "criteria": dict(q.criteria)}}},
                   "wire_question_name": "phase_classification", "expected": ed.get("phase"),
                   "label": {"value": ed.get("phase"), "source": "logged deterministic phase classifier (definitional)",
                             "quality": "definitional; cross-check = next tool call", "next_tool": nxt,
                             "behavioural_phase": behav, "rule_matches_rebuild": ed.get("phase") == phase},
                   "rebuild": {"status": "counterfactual-partial", "note": "phase judge never ran; same caveats as escalation"},
                   "lines": {"routed": ri, "effort_routed": ei},
                   "dedupe": digest([info["task"], t, kin, ed.get("phase")]), "hardness": {"step_in_turn": kin}}


# --------------------------------------------------------------------------- tool risk
READ_TOOLS = ("read_file", "grep", "glob", "LSP", "jevgrep", "web_fetch", "web_search", "load_skill", "todo")


def extract_tool_risk(info, ev, tr):
    for i, n, d in ev:
        if n != "tool:pre":
            continue
        name, cmd = d["tool_name"], d.get("command") or ""
        state = {"tool": name, "argument_keys": d["argument_keys"]}
        if name == "bash":
            destructive = "yes" if DESTRUCTIVE_RE.search(cmd) else "no"
        elif name in READ_TOOLS or (name == "fast_workspace" and d.get("operation") in ("read", "list")):
            destructive = "no"
        elif name in ("write_file", "edit_file", "apply_patch"):
            destructive = "yes"  # overwrites file content by construction
        else:
            destructive = None
        q = orchestrator._tool_risk_questions()[0]
        yield {"kind": "tool_risk", "suite": info["suite"], "task": info["task"],
               "payload": {"state": canonical(state), "questions": {"decision": {
                   "type": "choice", "instructions": q.instructions, "criteria": dict(q.criteria)}}},
               "wire_question_name": "destructive", "expected": destructive,
               "label": {"value": destructive, "source": "heuristic over the ACTUAL tool_input values (absent from payload)",
                         "quality": "not identifiable from the payload (argument keys only)",
                         "command": short(cmd, 200), "path": d.get("path")},
               "original_judge": None, "rebuild": {"status": "exact", "note": "trivial: tool name + sorted argument keys"},
               "lines": {"tool_pre": i}, "dedupe": digest([state, destructive, cmd[:80]]),
               "hardness": {"bash": name == "bash"}}


EXTRACTORS = {"read_shortcut": extract_read_shortcut, "difficulty": extract_difficulty,
              "escalation": extract_escalation_phase, "phase": extract_escalation_phase, "tool_risk": extract_tool_risk}


# --------------------------------------------------------------------------- survey
def survey(idx: Path) -> dict:
    """Counts from the index only (no rebuilds)."""
    raw = collections.defaultdict(collections.Counter)
    judged = collections.defaultdict(collections.Counter)
    distinct = collections.defaultdict(lambda: collections.defaultdict(set))
    labels = collections.defaultdict(collections.Counter)
    prompts: dict = {}
    sessions_seen = set()
    for path, ln, name, rest in iter_index(idx):
        info = session(path)
        sessions_seen.add(path)
        s = info["suite"]
        e = json.loads(rest)["data"]
        if name == "prompt:submit":
            prompts[path] = digest((e.get("prompt") or "")[:2500])
            continue
        if name == "tool:pre":
            ti = e.get("tool_input") or {}
            raw["tool_risk"][s] += 1
            distinct["tool_risk"][s].add(digest([e.get("tool_name"), sorted(ti) if isinstance(ti, dict) else []]))
            labels["tool_risk"][f"{s}:{e.get('tool_name')}"] += 1
            continue
        dd = e.get("data", {})
        if name == "fast_decisions:requested":
            raw["read_shortcut"][s] += 1
            distinct["read_shortcut"][s].add(digest([info["task"], sorted(c["id"] for c in dd.get("candidates") or []),
                                                     dd.get("observation_count")]))
        elif name == "fast_decisions:scored":
            judged["read_shortcut"][s] += 1
            labels["read_shortcut_choice"][f"{s}:{'reason' if dd.get('choice') == 'reason' else 'candidate'}"] += 1
        elif name == "fast_decisions:shadow_proposed":
            raw["read_shortcut_shadow"][s] += 1
            judged["read_shortcut_shadow"][s] += 1
        elif name == "fast_decisions:shadow_agreement":
            labels["read_shortcut_shadow_agreement"][f"{s}:{dd.get('agreement')}"] += 1
        elif name == "fast_decisions:difficulty_judged":
            rc = str(dd.get("reason_code", ""))
            raw["difficulty"][s] += 1
            labels["difficulty_reason"][f"{s}:{rc}"] += 1
            if rc.startswith(("judge_", "scope_judge")):
                judged["difficulty"][s] += 1
                distinct["difficulty"][s].add(prompts.get(path, path))
        elif name == "fast_decisions:model_routed":
            rc = str(dd.get("reason_code", ""))
            labels["model_routed_reason"][f"{s}:{rc}"] += 1
            if rc == "start_model" or rc.startswith("escalated_"):
                raw["escalation"][s] += 1
                distinct["escalation"][s].add(digest([path, dd.get("provider_call_id")]))
        elif name == "fast_decisions:effort_routed":
            raw["phase"][s] += 1
            labels["phase"][f"{s}:{dd.get('phase')}"] += 1
        elif name == "fast_decisions:routed":
            labels["routed"][f"{s}:{dd.get('route')}/{dd.get('reason_code')}"] += 1
    by_suite = collections.Counter(_sess[p]["suite"] for p in sessions_seen)
    outcome = collections.Counter(f"{_sess[p]['suite']}:{_sess[p]['passed']}" for p in sessions_seen)
    return {"sessions_by_suite": dict(by_suite), "session_outcomes": dict(outcome),
            "raw": {k: dict(v) for k, v in raw.items()},
            "judge_answer_logged": {k: dict(v) for k, v in judged.items()},
            "distinct_coarse": {k: {s: len(x) for s, x in v.items()} for k, v in distinct.items()},
            "label_breakdown": {k: dict(v.most_common(60)) for k, v in labels.items()}}


# --------------------------------------------------------------------------- extract
def extract(idx: Path, per_kind: int, seed: int) -> list[dict]:
    want = {"read_shortcut": "fast_decisions:requested", "difficulty": "fast_decisions:difficulty_judged",
            "escalation": "fast_decisions:model_routed", "phase": "fast_decisions:effort_routed", "tool_risk": "tool:pre"}
    by_kind_suite = collections.defaultdict(lambda: collections.defaultdict(set))
    for path, ln, name, rest in iter_index(idx):
        for kind, ev_name in want.items():
            if name == ev_name or (kind == "difficulty" and name == "prompt:submit" and session(path)["suite"] == "S3"):
                by_kind_suite[kind][session(path)["suite"]].add(path)
    rng = random.Random(seed)
    out, parsed = [], {}
    for kind in KINDS:
        suites = sorted(by_kind_suite[kind])
        pools = {s: rng.sample(sorted(by_kind_suite[kind][s]), len(by_kind_suite[kind][s])) for s in suites}
        got, seen, tried = [], set(), 0
        while len(got) < per_kind and any(pools.values()) and tried < 600:
            for s in suites:
                if len(got) >= per_kind or not pools[s]:
                    continue
                tried += 1
                path = pools[s].pop()
                info = session(path)
                if path not in parsed:
                    parsed[path] = parse_session(info)
                ev, tr = parsed[path]
                if not tr:
                    continue
                rows = [r for r in EXTRACTORS[kind](info, ev, tr)
                        if r["kind"] == kind and r["dedupe"] not in seen and r["expected"] is not None
                        and r["rebuild"]["status"] != "partial"]
                if kind == "tool_risk":  # hard-first: bash, positives
                    rows.sort(key=lambda r: (not r["hardness"]["bash"], r["expected"] != "yes"))
                elif kind == "read_shortcut":  # exact rebuilds, slow-routed, judge disagreed with outcome
                    rows.sort(key=lambda r: (r["rebuild"]["status"] != "exact", r["original_judge"]["route"] == "fast",
                                             not r["hardness"]["judge_vs_label_disagree"], -(r["hardness"]["state_chars"] or 0)))
                elif kind == "difficulty":
                    rows.sort(key=lambda r: (r["rebuild"]["status"] != "exact", not r["hardness"]["judge_vs_label_disagree"]))
                elif kind == "escalation":  # positives first, then latest step
                    rows.sort(key=lambda r: (r["expected"] != "escalate", -r["hardness"]["step_in_turn"]))
                else:  # phase: prefer rule/behaviour disagreements
                    rows.sort(key=lambda r: (r["label"]["behavioural_phase"] in (None, r["expected"]), -len(r["payload"]["state"])))
                if not rows:
                    continue
                # label balance first (stable sort keeps the hard-first order within a label)
                label_n = collections.Counter("candidate" if str(g["expected"]).startswith(("read_", "win_", "git_"))
                                              else g["expected"] for g in got)
                rows.sort(key=lambda r: label_n["candidate" if str(r["expected"]).startswith(("read_", "win_", "git_"))
                                                else r["expected"]])
                r = rows[0]
                lab = "candidate" if str(r["expected"]).startswith(("read_", "win_", "git_")) else r["expected"]
                if label_n[lab] >= (per_kind + 1) // 2 and tried < 500:
                    continue  # cap any one label at half the kind's quota while other labels may still turn up
                seen.add(r["dedupe"])
                r["id"] = f"trace-{kind}-{len(got):02d}"
                r["provenance"] = {"events": info["events"], "transcript": info["transcript"], "result_json": info["result"],
                                   "grading": info["grading"], "working_dir": info["working_dir"], "arm": info["arm"],
                                   "model": info["model"], "max_state_chars": info["max_state_chars"],
                                   "event_lines": r.pop("lines")}
                got.append(r)
        out += got
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["survey", "extract"])
    ap.add_argument("--per-kind", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    idx = build_index(a.refresh)
    if a.cmd == "survey":
        res = survey(idx)
        (HERE / "survey_counts.json").write_text(json.dumps(res, indent=2, sort_keys=True))
        for k in ("sessions_by_suite", "session_outcomes", "raw", "judge_answer_logged", "distinct_coarse"):
            print(k, json.dumps(res[k], sort_keys=True))
    else:
        rows = extract(idx, a.per_kind, a.seed)
        with open(HERE / "candidates.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
        c = collections.Counter((r["kind"], r["suite"], str(r["rebuild"]["status"]), str(r["expected"])) for r in rows)
        for k, v in sorted(c.items()):
            print(v, *k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
