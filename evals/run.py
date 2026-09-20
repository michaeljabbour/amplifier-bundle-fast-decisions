#!/usr/bin/env python3
"""evals/run.py -- thin driver over scripts/battery.py, scripts/campaign.py, and
scripts/battery_report.py. See evals/SPEC-for-builder.md for the full contract and
evals/STUDY-DESIGN.md for why. This file adds NO new measurement logic: every
number in its output comes from those three tools; run.py only sequences calls,
verifies preconditions, evaluates mechanism gates against receipts those tools
already produced, and writes a manifest.

Decision (2026-09-20): see cells.yaml header and STUDY-DESIGN.md "Decisions".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover -- exercised via a dedicated test with sys.modules faked
    yaml = None

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

DEFAULT_CELLS_FILE = HERE / "cells.yaml"
DEFAULT_SUITES_FILE = HERE / "suites.yaml"

SCHEMA_MANIFEST = "fast-decisions-evals/manifest/v1"

TOOL_SHA_FILES = (
    "battery.py",
    "battery_tasks.py",
    "polyglot_tasks.py",
    "battery_report.py",
    "forge_workloads.py",
)


class EvalsError(Exception):
    """Carries the exit code this failure must produce (see spec section 10)."""

    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------------------
# config loading (section 1 / 2)
# ---------------------------------------------------------------------------

def load_yaml_file(path):
    if yaml is None:
        raise EvalsError(2, f"pyyaml is not importable; install it to parse {path}")
    text = Path(path).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_cells(path=DEFAULT_CELLS_FILE):
    doc = load_yaml_file(path)
    if doc.get("schema") != "fast-decisions-evals/cells/v1":
        raise EvalsError(2, f"unexpected cells schema in {path}: {doc.get('schema')!r}")
    return doc


def load_suites(path=DEFAULT_SUITES_FILE):
    doc = load_yaml_file(path)
    if doc.get("schema") != "fast-decisions-evals/suites/v1":
        raise EvalsError(2, f"unexpected suites schema in {path}: {doc.get('schema')!r}")
    return doc


def resolve_cell_ids(requested, cells_doc):
    """`--cells all` or a comma list -> ordered list of cell ids, in cells.yaml's
    declared order (section 7 "declared cell order")."""
    declared = list(cells_doc["cells"].keys())
    if requested == "all":
        return declared
    wanted = [c.strip() for c in requested.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in cells_doc["cells"]]
    if unknown:
        raise EvalsError(2, f"unknown cell(s): {unknown}")
    # declared order, filtered to what was requested
    return [c for c in declared if c in wanted]


def validate_cell_dependencies(cell_ids, cells_doc):
    """section 5 #11 + anchor_cell (Decision 1): every requires_cells / anchor_cell
    entry of a requested cell must also be in the requested set (or a set the
    caller asserts is already present, e.g. on --resume; run.py callers pass the
    full requested+adopted set here)."""
    requested = set(cell_ids)
    for cid in cell_ids:
        cell = cells_doc["cells"][cid]
        for dep in cell.get("requires_cells", []):
            if dep not in requested:
                raise EvalsError(2, f"cell {cid!r} requires_cells {dep!r}, which is not in the requested set")
        anchor = cell.get("anchor_cell")
        if anchor and anchor not in requested:
            raise EvalsError(2, f"cell {cid!r} has anchor_cell {anchor!r}, which is not in the requested set")
        secondary = cell.get("secondary_anchor")
        if secondary and secondary not in requested:
            raise EvalsError(2, f"cell {cid!r} has secondary_anchor {secondary!r}, which is not in the requested set")


def validate_external_state_consent(cell_ids, cells_doc, allow_external_state):
    """section 5 #12: a cell with backend: jev requires allow_external_state: true
    in its own definition AND the CLI flag on this invocation."""
    for cid in cell_ids:
        cell = cells_doc["cells"][cid]
        fd = cell.get("fd") or {}
        if fd.get("backend") == "jev":
            if not fd.get("allow_external_state"):
                raise EvalsError(2, f"cell {cid!r}: fd backend 'jev' requires allow_external_state: true in cells.yaml")
            if not allow_external_state:
                raise EvalsError(2, f"cell {cid!r} uses backend 'jev'; pass --allow-external-state to consent")


# ---------------------------------------------------------------------------
# section 3: cell -> battery.py prepare argv
# ---------------------------------------------------------------------------

def _compact_json(obj):
    return json.dumps(obj, separators=(",", ":"))


def experiment_name(cell_id, suite_id, split, rep):
    return f"{cell_id}-{suite_id}-{split}-r{rep}"


def cell_to_argv(cell_id, cells_doc, suites_doc, suite_id, split, rep, *, out_root,
                  base_seed, baseline_source, candidate_source, candidate_sha,
                  polyglot_root=None):
    """The exact `battery.py prepare` argv for one (cell, suite, split, rep).
    Exhaustive per spec section 3: nothing is passed that isn't listed there."""
    cells = cells_doc["cells"]
    defaults = cells_doc.get("defaults", {})
    effort_profiles = cells_doc.get("effort_profiles", {})
    routing_profiles = cells_doc.get("model_routing_profiles", {})
    if cell_id not in cells:
        raise EvalsError(2, f"unknown cell {cell_id!r}")
    cell = cells[cell_id]
    if suite_id not in suites_doc["suites"]:
        raise EvalsError(2, f"unknown suite {suite_id!r}")
    suite = suites_doc["suites"][suite_id]

    exp = experiment_name(cell_id, suite_id, split, rep)
    seed = base_seed + rep
    amplifier_model = cell.get("amplifier_model") or defaults.get("amplifier_model")

    amplifier_bundle = cell.get("amplifier_bundle") or "foundation"
    if amplifier_bundle not in ("foundation", "lean"):
        raise EvalsError(2, f"unknown amplifier_bundle {amplifier_bundle!r} for cell {cell_id!r}")

    argv = [
        "--root", str(Path(out_root) / "campaign"),
        "--experiment", exp,
        "--harnesses", ",".join(cell["harnesses"]),
        "--seed", str(seed),
        "--deadline-seconds", str(suite["deadline_seconds"]),
        "--baseline-source", str(baseline_source),
        "--candidate-source", str(candidate_source),
        "--candidate-sha", str(candidate_sha),
        "--amplifier-model", str(amplifier_model),
        "--amplifier-bundle", amplifier_bundle,
        "--claude-permission-mode", "bypassPermissions",
    ]

    task_source = suite["task_source"]
    if task_source == "battery":
        splitcfg = suite["splits"][split]
        argv += ["--tasks", splitcfg["tasks_flag"]]
    elif task_source == "polyglot":
        poly = suite["polyglot"]
        splitcfg = suite["splits"][split]
        root = polyglot_root or os.environ.get(poly.get("root_env", "AFAST_POLYGLOT_ROOT"), "")
        argv += [
            "--task-source", "polyglot",
            "--polyglot-root", str(root),
            "--languages", ",".join(poly["languages"]),
            "--slice", str(poly["slice"]),
            "--split", splitcfg["split_flag"],
        ]
    else:
        raise EvalsError(2, f"unknown task_source {task_source!r} for suite {suite_id!r}")

    if cell_id == "externals":
        externals = defaults.get("external_models", {})
        if externals.get("claude"):
            argv += ["--claude-model", externals["claude"]]
        if externals.get("codex"):
            argv += ["--codex-model", externals["codex"]]
        if externals.get("opencode"):
            argv += ["--opencode-model", externals["opencode"]]
        argv += ["--claude-max-budget-usd", str(defaults.get("claude_max_budget_usd"))]

    if "amplifier-fd" in cell["harnesses"]:
        fd = cell.get("fd") or {}
        backend = fd.get("backend")
        if backend == "ollama":
            argv += ["--fd-backend", "ollama"]
        elif backend == "jev":
            if not fd.get("allow_external_state"):
                raise EvalsError(2, f"cell {cell_id!r}: fd backend 'jev' requires allow_external_state: true")
            argv += ["--fd-backend", "jev", "--allow-external-state"]
        elif backend in ("hosted", "gateway"):  # "gateway" is a legacy alias for "hosted"
            if not fd.get("allow_external_state"):
                raise EvalsError(2, f"cell {cell_id!r}: fd backend {backend!r} requires allow_external_state: true")
            argv += ["--fd-backend", backend, "--allow-external-state"]
        elif backend == "unavailable":
            argv += ["--fd-override", "backend=unavailable"]
        elif backend is not None:
            raise EvalsError(2, f"unknown fd backend {backend!r} for cell {cell_id!r}")

        if fd.get("model"):
            argv += ["--fd-override", f"model={fd['model']}"]

        if fd.get("effort_profile"):
            if fd["effort_profile"] not in effort_profiles:
                raise EvalsError(2, f"unknown effort_profile {fd['effort_profile']!r} for cell {cell_id!r}")
            profile = effort_profiles[fd["effort_profile"]]
            argv += ["--fd-override", "effort_routing=" + _compact_json(profile)]

        if fd.get("model_routing_profile"):
            if fd["model_routing_profile"] not in routing_profiles:
                raise EvalsError(2, f"unknown model_routing_profile {fd['model_routing_profile']!r} for cell {cell_id!r}")
            profile = routing_profiles[fd["model_routing_profile"]]
            argv += ["--fd-override", "model_routing=" + _compact_json(profile)]

    return argv


# ---------------------------------------------------------------------------
# series_label (section 8, R5)
# ---------------------------------------------------------------------------

REQUIRED_LABEL_AXES = ("judge=", "effort ", "model routing:", "model=")


def validate_series_label(label):
    missing = [tok for tok in REQUIRED_LABEL_AXES if tok not in label]
    if missing:
        raise EvalsError(4, f"series label missing axes {missing}: {label!r}")
    return label


def series_label(cell_id, rep, harness, cell, defaults, effort_profiles, routing_profiles):
    """`<cell-id> r<N> <harness> [judge=<backend> <model>; effort <phases>;
    model routing: on|off; model=<amplifier_model>]` -- names all four axes (R5)."""
    amplifier_model = cell.get("amplifier_model") or defaults.get("amplifier_model")
    fd = cell.get("fd")
    if fd:
        backend = fd.get("backend") or "unavailable"
        model = fd.get("model")
        judge = f"{backend} {model}" if model else backend
        profile_name = fd.get("effort_profile")
        if profile_name:
            profile = effort_profiles[profile_name]
            phases = ", ".join(f"{phase}->{effort}" for phase, effort in profile.items())
        else:
            phases = "off"
        routing_name = fd.get("model_routing_profile")
        routing = "on" if routing_name else "off"
    else:
        judge = "off"
        phases = "off"
        routing = "off"
    amplifier_bundle = cell.get("amplifier_bundle") or "foundation"
    label = (f"{cell_id} r{rep} {harness} [judge={judge}; effort {phases}; "
             f"model routing: {routing}; model={amplifier_model}; bundle={amplifier_bundle}]")
    return validate_series_label(label)


def cross_check_series_label(declared_label, recorded_label):
    """section 8: declared judge/effort/routing config must agree with
    `comparison.json['amplifier_fd_series_label']`, which battery.py derives from
    the run's own recorded profile. Compares the 'judge=...; effort ...; model
    routing: ...' substring both labels share (recorded_label has no cell/rep/model
    prefix and no trailing model= field)."""
    def _bracket(label):
        start = label.find("[")
        end = label.rfind("]")
        return label[start:end] if start != -1 and end != -1 else label

    def _axis(label, prefix, stop_prefixes):
        idx = label.find(prefix)
        if idx == -1:
            return None
        rest = label[idx:]
        end = len(rest)
        for stop in stop_prefixes:
            j = rest.find(stop, len(prefix))
            if j != -1:
                end = min(end, j)
        return rest[:end].strip().rstrip(";").strip()

    declared_bracket = _bracket(declared_label)
    recorded_bracket = _bracket(recorded_label)
    stops = ("judge=", "effort ", "model routing:", "model=", "bundle=")
    for prefix in ("judge=", "effort ", "model routing:"):
        d = _axis(declared_bracket, prefix, stops)
        r = _axis(recorded_bracket, prefix, stops)
        if d != r:
            raise EvalsError(
                4,
                f"series label disagreement on {prefix!r}: declared {d!r} vs recorded {r!r} "
                f"(declared={declared_label!r} recorded={recorded_label!r})",
            )
    return True


# ---------------------------------------------------------------------------
# verify_prompts (section 5 #1, R1)
# ---------------------------------------------------------------------------

def _sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def verify_prompts(tasks, resolve_task, get_task_prompt, amplifier_prompts, external_harnesses):
    """R1: every task's prompt is identical (by hash) across every harness.

    tasks: list[str] task names from proposal.json["tasks"].
    resolve_task(name) -> task object, or None if unresolvable.
    get_task_prompt(task) -> str or None (caller falls back to task.prompt).
    amplifier_prompts: {task_name: {harness_name: stored_prompt_str_or_None}} --
        from each amplifier run's runs/amplifier/manifest.json 'prompt' field.
    external_harnesses: {task_name: [harness_name, ...]} -- external runs for that
        task; per spec these must carry NO 'prompt' key in runs/manifest.json,
        which the caller has already confirmed before calling this (recorded here
        as a static, not observed, guarantee).

    Returns {'ok': bool, 'tasks': {task_name: {...}}}.
    """
    report = {}
    ok = True
    for name in tasks:
        task = resolve_task(name)
        if task is None:
            ok = False
            report[name] = {"ok": False, "reason": "unresolvable task"}
            continue
        expected = get_task_prompt(task) or getattr(task, "prompt", None)
        if not expected:
            ok = False
            report[name] = {"ok": False, "reason": "empty/unresolvable prompt"}
            continue
        expected_sha = _sha256_text(expected)
        harnesses = {}
        task_ok = True
        for harness, stored in (amplifier_prompts.get(name) or {}).items():
            matched = stored is not None and _sha256_text(stored) == expected_sha
            harnesses[harness] = {"matched": matched, "source": "recorded"}
            task_ok = task_ok and matched
        for harness in external_harnesses.get(name) or ():
            harnesses[harness] = {"matched": True, "source": "static-fallback"}
        report[name] = {"ok": task_ok, "expected_sha": expected_sha, "harnesses": harnesses}
        ok = ok and task_ok
    return {"ok": ok, "tasks": report}


# ---------------------------------------------------------------------------
# gate_eval (section 6)
# ---------------------------------------------------------------------------

def gate_eval(mechanism_gate, mechanism):
    """Evaluate one cell's mechanism_gate against comparison.json['mechanism'] --
    never re-derived, only asserted against. Returns
    {'passed': bool, 'flags': [...], 'reason': str|None, 'counters': mechanism}."""
    flags = []
    reasons = []
    passed = True

    if mechanism is None:
        if mechanism_gate.get("no_fd_receipts"):
            return {"passed": True, "flags": [], "reason": None, "counters": mechanism}
        return {"passed": False, "flags": [], "reason": "no mechanism receipts recorded (no amplifier-fd runs)",
                "counters": mechanism}

    if mechanism.get("mechanism_engaged") is False:
        passed = False
        reasons.append(mechanism.get("mechanism_reason") or "mechanism_engaged is false")

    if mechanism_gate.get("no_fd_receipts"):
        all_zero = (
            sum(mechanism.get("scored_by_backend", {}).values()) == 0
            and mechanism.get("fallback_count", 0) == 0
            and sum(mechanism.get("routed_by_route", {}).values()) == 0
            and sum(mechanism.get("effort_routed_by_phase_effort", {}).values()) == 0
            and sum(mechanism.get("model_routed_requested_models", {}).values()) == 0
        )
        if not all_zero:
            passed = False
            reasons.append("no_fd_receipts required but receipts were non-zero (profile leaked into a plain arm)")

    if "scored_backend" in mechanism_gate:
        backend = mechanism_gate["scored_backend"]
        min_scored = mechanism_gate.get("min_scored", 1)
        got = mechanism.get("scored_by_backend", {}).get(backend, 0)
        if got < min_scored:
            passed = False
            reasons.append(f"scored_backend {backend!r} count {got} < min_scored {min_scored}")

    if "max_scored" in mechanism_gate:
        total = sum(mechanism.get("scored_by_backend", {}).values())
        if total > mechanism_gate["max_scored"]:
            passed = False
            reasons.append(f"scored total {total} > max_scored {mechanism_gate['max_scored']}")

    if "max_fallback_fraction" in mechanism_gate:
        fallback = mechanism.get("fallback_count", 0)
        total_scored = sum(mechanism.get("scored_by_backend", {}).values())
        denom = fallback + total_scored
        if denom:
            frac = fallback / denom
            if frac > mechanism_gate["max_fallback_fraction"]:
                passed = False
                reasons.append(f"fallback fraction {frac:.3f} > max_fallback_fraction {mechanism_gate['max_fallback_fraction']}")

    if "require_effort_phases" in mechanism_gate:
        erbpe = mechanism.get("effort_routed_by_phase_effort", {})
        for key in mechanism_gate["require_effort_phases"]:
            if erbpe.get(key, 0) <= 0:
                passed = False
                reasons.append(f"required effort phase {key!r} missing or zero")

    if "model_routed_model" in mechanism_gate:
        model = mechanism_gate["model_routed_model"]
        min_n = mechanism_gate.get("min_model_routed", 1)
        got = mechanism.get("model_routed_requested_models", {}).get(model, 0)
        if got < min_n:
            passed = False
            reasons.append(f"model_routed_model {model!r} count {got} < min_model_routed {min_n}")

    if "flag_if_zero_escalations" in mechanism_gate:
        total_esc = sum(mechanism.get("model_routed_escalations_by_reason", {}).values())
        if total_esc == 0:
            flags.append(mechanism_gate["flag_if_zero_escalations"])

    # STUDY-DESIGN.md section 14 "Judge head-to-head": a cell with
    # escalation_judge: "judge" or effort_routing.phase_judge: true declares
    # mechanism_gate: {..., require_judged: true}. scripts/battery.py's
    # _mechanism_report already computes the DATA half (judged_engaged /
    # judged_reason); this is the wiring of that data into the gate itself
    # (DESIGN-BRIDGE.md rule (d2)'s open item).
    if mechanism_gate.get("require_judged"):
        judged_engaged = mechanism.get("judged_engaged")
        if judged_engaged is not True:
            passed = False
            reasons.append(mechanism.get("judged_reason") or
                            "judged_engaged is not true (mechanism_gate.require_judged)")

    result = {"passed": passed, "flags": flags, "reason": "; ".join(reasons) if reasons else None,
              "counters": mechanism}
    # Expose decision-latency budget status for any judge cell (any cell
    # whose mechanism receipts were recorded at all -- amplifier-fd harnesses
    # only; DESIGN-BRIDGE.md rule (b) needs this for judge-backend cells that
    # don't carry require_judged, not only the require_judged HC05 cells).
    result["latency_within_budget"] = mechanism.get("latency_within_budget")
    return result


# ---------------------------------------------------------------------------
# resume_detection (section 7 "Resume semantics")
# ---------------------------------------------------------------------------

def resume_detection(experiment_dir, requested_argv):
    """An experiment directory with proposal.json is never re-prepared; instead
    its recorded argv (run.py's own receipt, run-argv.json, written the first
    time it prepared this experiment) is re-verified against the requested argv.

    Returns ('prepare'|'reuse'|'error', reason_or_None).
    """
    experiment_dir = Path(experiment_dir)
    proposal_path = experiment_dir / "proposal.json"
    if not proposal_path.exists():
        return "prepare", None
    recorded_path = experiment_dir / "run-argv.json"
    if not recorded_path.exists():
        return "error", "existing experiment has proposal.json but no run-argv.json to verify against"
    recorded = json.loads(recorded_path.read_text(encoding="utf-8"))
    if recorded != requested_argv:
        return "error", "the cell definition changed under an existing run"
    return "reuse", None


# ---------------------------------------------------------------------------
# scan_incomplete_runs (exit 6, Task #3 amendment): a --resume batch that
# still has a planned run with no result.json and no live worker is not
# actually finished, even though every cell/rep loop iteration "completed"
# (battery.py run adopts and returns once nothing more can be launched right
# now -- e.g. a worker crashed outside battery.py's own retry path).
# ---------------------------------------------------------------------------


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return False
    return True


def scan_incomplete_runs(campaign_root, experiment_names, pid_alive=_pid_alive):
    """For each experiment, read its runs/manifest.json run_order; a run is
    incomplete when it has no result.json AND (no running.json, or
    running.json names a pid that is not alive). Returns {experiment:
    [run_name, ...]} for experiments with at least one incomplete run."""
    incomplete = {}
    for exp in experiment_names:
        exp_dir = Path(campaign_root) / "experiments" / exp
        manifest_path = exp_dir / "runs" / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing = []
        for name in manifest.get("run_order", []):
            item = manifest["runs"][name]
            harness = item.get("harness")
            run_dir = (exp_dir / "runs" / "amplifier" / name if harness in ("amplifier-plain", "amplifier-fd")
                       else exp_dir / "runs" / name)
            if (run_dir / "result.json").exists():
                continue
            running_path = run_dir / "running.json"
            if running_path.exists():
                try:
                    running = json.loads(running_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    running = {}
                pid = running.get("pid")
                if pid and pid_alive(pid):
                    continue  # still running -- not incomplete
            missing.append(name)
        if missing:
            incomplete[exp] = missing
    return incomplete


# ---------------------------------------------------------------------------
# cost_estimate (section 7 --dry-run, section 12 #7)
# ---------------------------------------------------------------------------

def cost_estimate(num_cells, reps, cells_doc):
    """Deterministic dry-run estimate: experiments = num_cells * reps;
    estimated_usd = experiments * budget.per_launch_usd. No statistics, no
    per-task modeling -- exactly what the spec's non-goals (section 13) allow."""
    per_launch = cells_doc["budget"]["per_launch_usd"]
    experiments = num_cells * reps
    return {"experiments": experiments, "per_launch_usd": per_launch,
            "estimated_usd": round(experiments * per_launch, 2)}


# ---------------------------------------------------------------------------
# manifest (section 9)
# ---------------------------------------------------------------------------

def _sha256_file(path):
    path = Path(path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_tool_shas(scripts_dir=SCRIPTS_DIR):
    return {name: _sha256_file(Path(scripts_dir) / name) for name in TOOL_SHA_FILES}


def verify_tool_shas(recorded, current):
    changed = {name: (recorded.get(name), current.get(name))
               for name in TOOL_SHA_FILES if recorded.get(name) != current.get(name)}
    if changed:
        raise EvalsError(4, f"tool sha drift since this campaign started: {changed}")
    return True


def build_manifest(*, argv, suite_id, split, reps, suite_doc, candidate, baseline,
                    cells_report, budget_report, tool_shas):
    return {
        "schema": SCHEMA_MANIFEST,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "invocation": {"argv": list(argv), "suite": suite_id, "split": split, "reps": reps},
        "suite": suite_doc,
        "candidate": candidate,
        "baseline": baseline,
        "cells": cells_report,
        "budget": budget_report,
        "verification": {"prompt_hashes": "prompt-verification.json", "preflight": "preflight.json"},
        "tool_shas": tool_shas,
    }


REQUIRED_MANIFEST_KEYS = ("schema", "created_at_utc", "invocation", "suite", "candidate",
                          "baseline", "cells", "budget", "verification", "tool_shas")


def validate_manifest_shape(manifest):
    missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        raise EvalsError(4, f"manifest missing required keys: {missing}")
    return True


# ---------------------------------------------------------------------------
# subprocess seam -- the ONLY place run.py talks to battery.py/campaign.py/
# battery_report.py. Every test replaces this with a fake.
# ---------------------------------------------------------------------------

def invoke_tool(tool, argv):
    """Run `python3 scripts/<tool>.py <argv>` and return its parsed one-line JSON
    stdout contract. Raises EvalsError(code) on a non-zero exit whose stdout
    carries a documented {'exit': N, ...} envelope; re-raises unexpected failures."""
    script = SCRIPTS_DIR / f"{tool}.py"
    proc = subprocess.run(
        [sys.executable, str(script), *argv],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
    )
    out = (proc.stdout or "").strip().splitlines()
    payload = None
    if out:
        try:
            payload = json.loads(out[-1])
        except ValueError:
            payload = None
    if proc.returncode != 0:
        reason = (payload or {}).get("reason") if payload else (proc.stderr or "").strip()[-2000:]
        code = (payload or {}).get("exit", proc.returncode)
        raise EvalsError(code if isinstance(code, int) else proc.returncode,
                          f"{tool} {argv[:2]} failed: {reason}")
    return payload if payload is not None else {}


# ---------------------------------------------------------------------------
# precondition verification (section 5)
# ---------------------------------------------------------------------------

_EXTERNAL_BINARY = {"claude": "claude", "codex": "codex", "opencode": "opencode"}


def check_permission_mode(proposal, cell):
    """#2 R2: bypassPermissions everywhere, and the claude command template carries it."""
    if proposal.get("claude_permission_mode") != "bypassPermissions":
        return False, f"claude_permission_mode={proposal.get('claude_permission_mode')!r}, expected bypassPermissions"
    if "claude" in cell["harnesses"]:
        argv = proposal.get("commands", {}).get("claude") or []
        if "--permission-mode" not in argv or "bypassPermissions" not in argv:
            return False, "claude command template missing --permission-mode bypassPermissions"
    return True, None


def check_command_templates(proposal, cell, defaults):
    """#3: external harness command templates match the expected argv shape
    (binary name, model flag present iff a model was requested)."""
    for h in cell["harnesses"]:
        if h not in _EXTERNAL_BINARY:
            continue
        argv = proposal.get("commands", {}).get(h)
        if not argv or argv[0] != _EXTERNAL_BINARY[h]:
            return False, f"{h} command template does not start with {_EXTERNAL_BINARY[h]!r}: {argv!r}"
        model = proposal.get("models", {}).get(h)
        model_flag = {"claude": "--model", "codex": "-m", "opencode": None}.get(h)
        if model and model_flag and model_flag not in argv:
            return False, f"{h} command template missing model flag {model_flag!r} for requested model {model!r}"
    return True, None


def check_task_count(proposal, suite, split):
    expected = suite["splits"][split]["expected_task_count"]
    actual = len(proposal.get("tasks", []))
    if actual != expected:
        return False, f"task count {actual} != expected_task_count {expected} for split {split!r} (the split moved)"
    return True, None


def check_corpus_sha(proposal, suite):
    if suite.get("task_source") != "polyglot":
        return True, None
    pinned = suite["polyglot"]["pinned_corpus_sha"]
    actual = (proposal.get("task_source") or {}).get("sha") or ""
    if not actual.startswith(pinned):
        return False, f"polyglot corpus sha {actual!r} does not start with pinned {pinned!r}"
    return True, None


def check_frozen_candidate(proposal, candidate_sha):
    snap = proposal.get("candidate_source_snapshot")
    if not snap:
        return True, None  # plain-only cell: no candidate snapshot to freeze
    if not (snap.get("git_sha") or "").startswith(candidate_sha):
        return False, f"candidate snapshot sha {snap.get('git_sha')!r} does not start with requested {candidate_sha!r}"
    if not Path(snap.get("snapshot_source_root", "")).exists():
        return False, f"candidate snapshot missing on disk: {snap.get('snapshot_source_root')!r}"
    return True, None


def check_workspace_identity(experiment_dir, proposal):
    """#7: re-assert prepare's own per-task workspace-hash invariant (never
    re-derive an outcome, just re-check the hashes it already asserted)."""
    try:
        import forge_e2e
    except ImportError as e:  # pragma: no cover
        return False, f"cannot import forge_e2e to re-hash workspaces: {e}", {}
    by_task = {}
    for r in proposal.get("frozen_run_schedule", []):
        run_dir = Path(experiment_dir) / "runs"
        run_dir = (run_dir / "amplifier" / r["name"]) if r["harness"] in ("amplifier-plain", "amplifier-fd")             else (run_dir / r["name"])
        ws = run_dir / "workspace"
        if not ws.exists():
            continue
        by_task.setdefault(r["task"], []).append(forge_e2e.hash_files(ws))
    mismatched = {t: h for t, h in by_task.items() if len(set(h)) > 1}
    if mismatched:
        return False, f"workspace hash mismatch: {mismatched}", by_task
    return True, None, {t: (h[0] if h else None) for t, h in by_task.items()}


def check_toolchains(required, which=None):
    import shutil as _shutil
    which = which or _shutil.which
    missing = [name for name in required if not which(name)]
    if missing:
        return False, f"missing required toolchains on PATH: {missing}"
    return True, None


def run_forge_doctor(host_python, forge_py, runner=None):
    runner = runner or (lambda argv: subprocess.run(argv, capture_output=True, text=True, check=False))
    proc = runner([str(host_python), str(forge_py), "doctor"])
    ok = getattr(proc, "returncode", 1) == 0
    return ok, (None if ok else (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[-2000:])


def check_budget_headroom(remaining_usd, num_runs, per_launch_usd):
    estimated = num_runs * per_launch_usd
    if remaining_usd < estimated:
        return False, f"remaining budget ${remaining_usd:.2f} < estimated ${estimated:.2f} for {num_runs} runs"
    return True, None


def verify_prompts_for_experiment(experiment_dir, proposal):
    """Wires the pure `verify_prompts` to the real on-disk artifacts of one
    prepared experiment (R1)."""
    import forge_workloads
    experiment_dir = Path(experiment_dir)
    task_source = proposal.get("task_source")
    if task_source:
        forge_workloads.register_source(task_source["kind"],
                                         **{k: v for k, v in task_source.items() if k != "kind"})
    amp_manifest_path = experiment_dir / "runs" / "amplifier" / "manifest.json"
    amp_manifest = json.loads(amp_manifest_path.read_text(encoding="utf-8")) if amp_manifest_path.exists() else {}
    ext_manifest_path = experiment_dir / "runs" / "manifest.json"
    ext_manifest = json.loads(ext_manifest_path.read_text(encoding="utf-8")) if ext_manifest_path.exists() else {}

    amplifier_prompts = {}
    external_harnesses = {}
    for r in proposal.get("frozen_run_schedule", []):
        task, harness, name = r["task"], r["harness"], r["name"]
        if harness in ("amplifier-plain", "amplifier-fd"):
            stored = (amp_manifest.get("runs", {}).get(name) or {}).get("prompt")
            amplifier_prompts.setdefault(task, {})[harness] = stored
        else:
            item = ext_manifest.get("runs", {}).get(name) or {}
            if "prompt" in item:
                return {"ok": False, "tasks": {task: {"ok": False,
                        "reason": f"external run {name!r} carries a prompt override"}}}
            external_harnesses.setdefault(task, []).append(harness)

    def resolve_task(name):
        import forge_workloads as fw
        try:
            return fw.get_task(name)
        except Exception:
            return None

    def get_prompt(task):
        import forge_workloads as fw
        return fw.task_prompt(task)

    return verify_prompts(proposal.get("tasks", []), resolve_task, get_prompt,
                           amplifier_prompts, external_harnesses)


def run_verification(experiment_dir, proposal, cell, suite, split, candidate_sha, defaults,
                      required_toolchains, host_python, forge_py, budget_status=None,
                      num_runs=0, per_launch_usd=0.0, which=None, doctor_runner=None):
    """Section 5, all checks that are decidable from proposal.json plus a small
    amount of real filesystem/PATH/subprocess verification. Returns
    (ok: bool, preflight: dict, prompt_verification: dict)."""
    checks = {}

    ok, reason = check_permission_mode(proposal, cell)
    checks["permission_mode"] = {"passed": ok, "reason": reason}

    ok2, reason2 = check_command_templates(proposal, cell, defaults)
    checks["command_templates"] = {"passed": ok2, "reason": reason2}

    ok3, reason3 = check_task_count(proposal, suite, split)
    checks["task_count"] = {"passed": ok3, "reason": reason3}

    ok4, reason4 = check_corpus_sha(proposal, suite)
    checks["corpus_sha"] = {"passed": ok4, "reason": reason4}

    ok5, reason5 = check_frozen_candidate(proposal, candidate_sha)
    checks["frozen_candidate"] = {"passed": ok5, "reason": reason5}

    ok6, reason6, hashes = check_workspace_identity(experiment_dir, proposal)
    checks["workspace_identity"] = {"passed": ok6, "reason": reason6, "per_task_hash": hashes}

    ok7, reason7 = check_toolchains(required_toolchains, which=which)
    checks["toolchains"] = {"passed": ok7, "reason": reason7}

    ok8, reason8 = run_forge_doctor(host_python, forge_py, runner=doctor_runner)
    checks["forge_doctor"] = {"passed": ok8, "reason": reason8}

    if budget_status is not None:
        ok9, reason9 = check_budget_headroom(budget_status, num_runs, per_launch_usd)
    else:
        ok9, reason9 = True, "no budget status supplied; skipped"
    checks["budget_headroom"] = {"passed": ok9, "reason": reason9}

    prompt_verification = verify_prompts_for_experiment(experiment_dir, proposal)
    checks["prompt_identity"] = {"passed": prompt_verification["ok"], "reason": None}

    ok_all = all(c["passed"] for c in checks.values())
    return ok_all, {"checks": checks}, prompt_verification


# ---------------------------------------------------------------------------
# Task #2/#4 amendment (2026-09-20b, see STUDY-DESIGN.md section 12 and
# SPEC-for-builder.md section 14): a results-verdict layer and a results ->
# design-bridge recommendation. Every number here is read from a
# `comparison.json` dict that `battery.py evaluate` already produced (the
# cross-campaign anchor comparison, or the same-experiment paired comparison
# for `externals`); the only genuinely new computation is the bootstrap
# confidence interval and the verdict classification, both pure and tested
# below. See evals/DESIGN-BRIDGE.md for the decision rules this feeds.
# ---------------------------------------------------------------------------

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260919
MIN_REPS_FOR_CLAIM = 3
MIN_PAIRED_TASKS_FOR_CLAIM = 8
NO_EFFECT_BAND = 0.03  # ratio within [0.97, 1.03] with enough evidence => "no-effect"


def aggregate_task_pairs(comparisons, anchor_harness="amplifier-plain", candidate_harness="amplifier-fd"):
    """Regroup already-computed per-task numbers from a list of one cell's
    per-rep `comparison.json` dicts into {task: {candidate_exec_s: [...per rep],
    candidate_passed: [...], anchor_exec_s: [...], anchor_passed: [...]}}.

    Prefers `comparison['cross']['baselines'][anchor_harness]['per_task']`
    (the cross-campaign anchor comparison battery.py already computed via
    `--baseline-root`/`--baseline-experiment`); falls back to the
    same-experiment `comparison['per_task']` table (used by `externals`, which
    embeds its own amplifier-plain harness instead of using an anchor_cell).
    No new derivation happens here -- only regrouping numbers that already
    exist in the dicts battery.py wrote.
    """
    by_task = {}

    def _slot(task):
        return by_task.setdefault(task, {"candidate_exec_s": [], "candidate_passed": [],
                                          "anchor_exec_s": [], "anchor_passed": []})

    for comp in comparisons or []:
        if comp is None:
            continue
        cross = comp.get("cross")
        if cross:
            baseline = (cross.get("baselines") or {}).get(anchor_harness)
            rows = (baseline or {}).get("per_task") or {}
            for task, row in rows.items():
                slot = _slot(task)
                slot["candidate_exec_s"].append(row.get("candidate_exec_s"))
                slot["candidate_passed"].append(bool(row.get("candidate_passed")))
                slot["anchor_exec_s"].append(row.get(f"{anchor_harness}_exec_s"))
                slot["anchor_passed"].append(bool(row.get(f"{anchor_harness}_passed")))
        else:
            for task, row in (comp.get("per_task") or {}).items():
                c = row.get(candidate_harness)
                a = row.get(anchor_harness)
                if c is None or a is None:
                    continue
                slot = _slot(task)
                c_ms, a_ms = c.get("penalized_ms"), a.get("penalized_ms")
                slot["candidate_exec_s"].append((c_ms / 1000.0) if c_ms is not None else None)
                slot["candidate_passed"].append(bool(c.get("outcome_passed")))
                slot["anchor_exec_s"].append((a_ms / 1000.0) if a_ms is not None else None)
                slot["anchor_passed"].append(bool(a.get("outcome_passed")))
    return by_task


def _majority_pass(flags):
    n = len(flags)
    return (sum(1 for f in flags if f) * 2) > n if n else False


def per_task_log_ratios(task_pairs):
    """Median-across-reps exec time per task (only reps where both sides
    passed), then the natural-log candidate/anchor ratio. STUDY-DESIGN.md
    section 5: 'Per-task time is aggregated across reps by median before the
    paired comparison.'"""
    log_ratios = {}
    for task, series in task_pairs.items():
        pairs = [
            (c, a) for c, a, cp, ap in
            zip(series["candidate_exec_s"], series["anchor_exec_s"],
                series["candidate_passed"], series["anchor_passed"])
            if cp and ap and c is not None and a is not None and c > 0 and a > 0
        ]
        if not pairs:
            continue
        c_med = statistics.median(p[0] for p in pairs)
        a_med = statistics.median(p[1] for p in pairs)
        if c_med > 0 and a_med > 0:
            log_ratios[task] = math.log(c_med / a_med)
    return log_ratios


def quality_counts(task_pairs):
    """Majority-vote pass per task across reps, for candidate and anchor
    separately, over every task with any recorded data. Feeds the
    non-inferiority check (STUDY-DESIGN.md section 8)."""
    candidate_successes = 0
    anchor_successes = 0
    paired_task_count = 0
    for series in task_pairs.values():
        paired_task_count += 1
        if _majority_pass(series["candidate_passed"]):
            candidate_successes += 1
        if _majority_pass(series["anchor_passed"]):
            anchor_successes += 1
    return candidate_successes, anchor_successes, paired_task_count


def bootstrap_ci_log_ratio(log_ratios, n_resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED):
    """95% bootstrap CI on the geometric-mean ratio: resample per-task
    log-ratios with replacement, `n_resamples` times, stdlib `random.Random`
    with a fixed seed for reproducibility. Returns (point, ci_low, ci_high) as
    plain ratios (exp of the mean log-ratio), or (None, None, None) if empty."""
    values = list(log_ratios.values())
    n = len(values)
    if n == 0:
        return None, None, None
    point = math.exp(sum(values) / n)
    rng = random.Random(seed)
    means = []
    for _ in range(n_resamples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo_idx = int(0.025 * n_resamples)
    hi_idx = min(n_resamples - 1, int(0.975 * n_resamples))
    return point, math.exp(means[lo_idx]), math.exp(means[hi_idx])


def sign_test_p_from_log_ratios(log_ratios):
    """Exact two-sided sign test over the aggregated per-task log-ratios,
    reusing `battery._sign_test` (already implemented, already unit-tested in
    battery.py's own suite) rather than re-deriving it here."""
    import battery  # local import: this module stays importable without scripts/ on sys.path for unrelated tests
    return battery._sign_test(list(log_ratios.values()))["p_value"]


def cost_ratio_from_cell_comparisons(candidate_comparisons, anchor_comparisons,
                                      candidate_harness="amplifier-fd", anchor_harness="amplifier-plain"):
    """Median-across-reps `mean_cost_known_usd` for each side, read straight
    from `comparison['per_harness']` (already computed by battery.py evaluate).
    Returns (ratio_or_None, unknown_cost_count)."""
    def _costs(comparisons, harness):
        vals, unknown = [], 0
        for comp in comparisons or []:
            if comp is None:
                continue
            row = (comp.get("per_harness") or {}).get(harness) or {}
            if row.get("mean_cost_known_usd") is not None:
                vals.append(row["mean_cost_known_usd"])
            unknown += row.get("unknown_cost_count", 0) or 0
        return vals, unknown

    c_vals, c_unknown = _costs(candidate_comparisons, candidate_harness)
    a_vals, a_unknown = _costs(anchor_comparisons, anchor_harness)
    c_med = statistics.median(c_vals) if c_vals else None
    a_med = statistics.median(a_vals) if a_vals else None
    ratio = (c_med / a_med) if (c_med is not None and a_med) else None
    return ratio, c_unknown + a_unknown


def classify_verdict(*, reps, split, gate_passed, quality_non_inferior, ratio_point,
                      ratio_ci_low, ratio_ci_high, sign_p, paired_task_count, cost_ratio):
    """STUDY-DESIGN.md section 8 decision rules applied to one cell's
    aggregated-across-reps numbers. Never recomputes a statistic -- every
    input here was already produced by battery.py or the pure helpers above."""
    if not gate_passed:
        return "gate-failed"
    if not quality_non_inferior:
        return "quality-regressed"
    enough_evidence = (reps >= MIN_REPS_FOR_CLAIM and paired_task_count >= MIN_PAIRED_TASKS_FOR_CLAIM
                        and split == "holdout")
    speedup_confirmed_by_ci = (ratio_ci_high is not None and ratio_ci_high < 1.0)
    sign_significant = (sign_p is not None and sign_p <= 0.05)
    cost_ok = (cost_ratio is None) or (cost_ratio <= 1.00)
    if enough_evidence and speedup_confirmed_by_ci and sign_significant and cost_ok:
        return "confirmed"
    if (ratio_point is not None and (1.0 - NO_EFFECT_BAND) <= ratio_point <= (1.0 + NO_EFFECT_BAND)
            and reps >= MIN_REPS_FOR_CLAIM and paired_task_count >= MIN_PAIRED_TASKS_FOR_CLAIM):
        return "no-effect"
    return "screen"


def build_cell_result(cell_id, anchor_id, comparisons, anchor_comparisons, gate_passed, split, reps,
                       candidate_harness="amplifier-fd", anchor_harness="amplifier-plain"):
    """Assemble one cell's verdict row for results.json/RESULTS.md."""
    task_pairs = aggregate_task_pairs(comparisons, anchor_harness, candidate_harness)
    log_ratios = per_task_log_ratios(task_pairs)
    ratio_point, ci_low, ci_high = bootstrap_ci_log_ratio(log_ratios)
    p_value = sign_test_p_from_log_ratios(log_ratios) if log_ratios else None
    candidate_successes, anchor_successes, paired_task_count = quality_counts(task_pairs)
    quality_non_inferior = candidate_successes >= (anchor_successes - 1)
    cost_ratio, unknown_cost_count = cost_ratio_from_cell_comparisons(
        comparisons, anchor_comparisons, candidate_harness, anchor_harness)
    verdict = classify_verdict(
        reps=reps, split=split, gate_passed=gate_passed, quality_non_inferior=quality_non_inferior,
        ratio_point=ratio_point, ratio_ci_low=ci_low, ratio_ci_high=ci_high,
        sign_p=p_value, paired_task_count=paired_task_count, cost_ratio=cost_ratio,
    )
    return {
        "cell": cell_id, "anchor": anchor_id, "reps": reps, "split": split, "gate_passed": gate_passed,
        "paired_task_count": paired_task_count,
        "exec_time_ratio": {"geomean": ratio_point, "ci95_low": ci_low, "ci95_high": ci_high,
                             "sign_test_p": p_value},
        "cost_ratio": cost_ratio, "unknown_cost_count": unknown_cost_count,
        "quality": {"candidate_successes": candidate_successes, "anchor_successes": anchor_successes,
                    "non_inferior": quality_non_inferior},
        "verdict": verdict,
    }


def q3_comparison(champion_comparisons, externals_comparisons, champion_harness="amplifier-fd"):
    """Q3: the champion cell's own aggregated exec times against every
    external harness present in the `externals` cell's per-task table
    (STUDY-DESIGN.md section 1, Q3)."""
    champ_by_task = {}
    for comp in champion_comparisons or []:
        if comp is None:
            continue
        cross = comp.get("cross")
        if cross:
            baselines = cross.get("baselines") or {}
            rows = next(iter(baselines.values()), {}).get("per_task", {}) if baselines else {}
            for task, row in rows.items():
                if row.get("candidate_passed") and row.get("candidate_exec_s") is not None:
                    champ_by_task.setdefault(task, []).append(row["candidate_exec_s"])
        else:
            for task, row in (comp.get("per_task") or {}).items():
                c = row.get(champion_harness)
                if c and c.get("outcome_passed") and c.get("penalized_ms") is not None:
                    champ_by_task.setdefault(task, []).append(c["penalized_ms"] / 1000.0)
    champ_median = {t: statistics.median(v) for t, v in champ_by_task.items()}

    ext_harnesses = set()
    for comp in externals_comparisons or []:
        if comp:
            ext_harnesses |= set((comp.get("per_harness") or {}).keys())
    ext_harnesses -= {"amplifier-plain", "amplifier-fd"}

    results = {}
    for h in sorted(ext_harnesses):
        ext_by_task = {}
        for comp in externals_comparisons or []:
            if not comp:
                continue
            for task, row in (comp.get("per_task") or {}).items():
                e = row.get(h)
                if e and e.get("outcome_passed") and e.get("penalized_ms") is not None:
                    ext_by_task.setdefault(task, []).append(e["penalized_ms"] / 1000.0)
        ext_median = {t: statistics.median(v) for t, v in ext_by_task.items()}
        common = sorted(set(champ_median) & set(ext_median))
        log_ratios = {t: math.log(champ_median[t] / ext_median[t]) for t in common
                      if champ_median[t] > 0 and ext_median[t] > 0}
        point, lo, hi = bootstrap_ci_log_ratio(log_ratios)
        p_value = sign_test_p_from_log_ratios(log_ratios) if log_ratios else None
        results[h] = {"ratio": point, "ci95_low": lo, "ci95_high": hi,
                      "sign_test_p": p_value, "n_paired": len(log_ratios)}
    return results


def _fmt_ratio(ratio):
    if not ratio or ratio.get("geomean") is None:
        return "n/a"
    lo, hi = ratio.get("ci95_low"), ratio.get("ci95_high")
    if lo is None or hi is None:
        return f"{ratio['geomean']:.2f}"
    return f"{ratio['geomean']:.2f} [{lo:.2f}, {hi:.2f}]"


def _fmt_p_value(p):
    return "n/a" if p is None else f"{p:.4g}"


def render_results_markdown(results):
    """RESULTS.md: the verdict table plus Q3/Q4 sections and evidence limits,
    every figure read straight from `results` (see build_cell_result/q3_comparison)."""
    lines = [f"# Results -- {results['suite']} {results['split']} (reps={results['reps']})", "",
             "## Verdict table (vs anchor)", "",
             ("| Cell | Anchor | Passed/Total | Ratio (95% CI) | sign-test p | Cost ratio | "
              "Quality delta | Gate | Verdict |"),
             "|---|---|---|---|---|---|---|---|---|"]
    for row in results["cells"]:
        q = row["quality"]
        ratio_str = _fmt_ratio(row["exec_time_ratio"])
        cost_str = "unknown" if row["cost_ratio"] is None else f"{row['cost_ratio']:.2f}"
        if row["unknown_cost_count"]:
            cost_str += f" ({row['unknown_cost_count']} unknown)"
        delta = q["candidate_successes"] - q["anchor_successes"]
        gate_str = "green" if row["gate_passed"] else "RED"
        lines.append(
            f"| {row['cell']} | {row['anchor']} | {q['candidate_successes']}/{row['paired_task_count']} | "
            f"{ratio_str} | {_fmt_p_value(row['exec_time_ratio']['sign_test_p'])} | {cost_str} | "
            f"{delta:+d} | {gate_str} | **{row['verdict']}** |"
        )
        if row.get("vs_plain"):
            vp = row["vs_plain"]
            lines.append(f"  - {row['cell']} vs `{vp['anchor']}` (secondary): "
                         f"ratio={_fmt_ratio(vp['exec_time_ratio'])}")
    lines.append("")

    if results.get("q3"):
        lines.append("## Q3 -- champion vs external harnesses")
        lines.append("")
        lines.append("| Harness | Ratio (95% CI) | sign-test p | n paired |")
        lines.append("|---|---|---|---|")
        for h, row in results["q3"].items():
            ratio_str = ("n/a" if row["ratio"] is None
                         else f"{row['ratio']:.2f} [{row['ci95_low']:.2f}, {row['ci95_high']:.2f}]")
            lines.append(f"| {h} | {ratio_str} | {_fmt_p_value(row['sign_test_p'])} | {row['n_paired']} |")
        lines.append("")

    q4_rows = [r for r in results["cells"] if r["split"] == "holdout"]
    if q4_rows:
        lines.append("## Q4 -- holdout confirmation")
        lines.append("")
        for r in q4_rows:
            lines.append(f"- {r['cell']}: verdict={r['verdict']}")
        lines.append("")

    lines.append("## Evidence limits")
    lines.append("")
    for el in results.get("evidence_limits", []):
        lines.append(f"- {el}")
    lines.append("")
    return "\n".join(lines) + "\n"


def design_recommendation_text(results, cells_doc):
    """Fills evals/DESIGN-BRIDGE.md's decision rules from one results.json.
    Every figure quoted is read straight from `results` (traceable to
    battery.py's own comparison.json fields via build_cell_result/q3_comparison
    above) -- this function only applies the DESIGN-BRIDGE.md decision rules,
    it never invents a number. Marked 'for human ratification': it recommends,
    it does not flip any config on its own."""
    by_cell = {r["cell"]: r for r in results.get("cells", [])}
    lines = ["# Design recommendation (for human ratification)", "",
             (f"Generated from results for {results.get('suite')} {results.get('split')} "
              f"(reps={results.get('reps')}). See evals/DESIGN-BRIDGE.md for the rules applied here."),
             ""]

    # (a) mode: shadow vs active
    champion = by_cell.get("judge-local+effort")
    if champion and champion["verdict"] == "confirmed" and results.get("split") == "holdout":
        r = champion["exec_time_ratio"]
        delta = champion["quality"]["candidate_successes"] - champion["quality"]["anchor_successes"]
        lines.append(
            f"- **mode**: recommend `active` -- judge-local+effort confirmed on holdout "
            f"(ratio={r['geomean']:.2f}, CI=[{r['ci95_low']:.2f}, {r['ci95_high']:.2f}], "
            f"quality delta={delta:+d})."
        )
    else:
        v = champion["verdict"] if champion else "not run"
        lines.append(f"- **mode**: keep `shadow` -- judge-local+effort verdict is {v!r}, "
                     "not confirmed on holdout with quality non-inferior.")

    # (b) judge backend default
    jev = by_cell.get("judge-jev+effort")
    if jev and jev["verdict"] == "confirmed" and jev.get("gate_passed"):
        lines.append("- **judge backend default**: recommend `jev` (opt-in, requires "
                     "allow_external_state) -- confirmed and mechanism-gated scored on `jev`.")
    else:
        v = jev["verdict"] if jev else "not run"
        lines.append(f"- **judge backend default**: keep `ollama` -- jev verdict is {v!r}, not confirmed.")

    # (c) effort_routing default map
    if champion and champion["verdict"] in ("confirmed", "screen") and champion["quality"]["non_inferior"]:
        lines.append("- **effort_routing default**: recommend all-phase (orient/explore/implement) -- "
                     "no quality regression observed for judge-local+effort.")
    else:
        lines.append("- **effort_routing default**: keep the incumbent explore-only profile -- "
                     "all-phase did not clear the bar without a quality regression.")

    # (d) model_routing default
    routing = by_cell.get("judge-local+effort+route")
    if routing:
        primary = routing["exec_time_ratio"]
        cost_ok = (routing.get("cost_ratio") is None) or (routing.get("cost_ratio") <= 1.0)
        beats_plain_sonnet = bool(
            primary.get("geomean") is not None and primary["geomean"] < 1.0
            and primary.get("sign_test_p") is not None and primary["sign_test_p"] <= 0.05
            and cost_ok
        )
        vs_plain = routing.get("vs_plain")
        beats_plain_only = (
            not beats_plain_sonnet and vs_plain is not None
            and vs_plain["exec_time_ratio"].get("geomean") is not None
            and vs_plain["exec_time_ratio"]["geomean"] < 1.0
        )
        if beats_plain_sonnet:
            lines.append("- **model_routing default**: recommend `on` -- the routing cell beats its "
                         "plain-sonnet control (the confounding control, R5), with a passed mechanism gate.")
        elif beats_plain_only:
            lines.append("- **model_routing default**: recommend `off` -- pin the cheaper model "
                         "(sonnet) directly rather than routing; the routing cell beats plain but does "
                         "not beat its plain-sonnet control, so the gain is explained by the cheaper "
                         "model alone, not by routing.")
        else:
            lines.append("- **model_routing default**: recommend `off` -- no demonstrated gain over "
                         "either plain or plain-sonnet; routing adds complexity without a payoff.")
    else:
        lines.append("- **model_routing default**: keep `off` -- routing cell not run this pass.")

    lines.append("")
    lines.append("- **external state (privacy)**: remains opt-in regardless of any result above "
                 "(docs/PRIVACY.md).")
    lines.append("")
    lines.append("## Evidence limits")
    for el in results.get("evidence_limits", []):
        lines.append(f"- {el}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    p = argparse.ArgumentParser(prog="evals/run.py")
    p.add_argument("--suite", choices=["s1", "s2"])
    p.add_argument("--split", choices=["dev", "holdout"])
    p.add_argument("--cells")
    p.add_argument("--reps", type=int, default=None,
                    help="default: 5 on --split holdout, else 3 (Decision 2026-09-20b, "
                         "STUDY-DESIGN.md section 12)")
    p.add_argument("--out", required=True)
    p.add_argument("--baseline-source")
    p.add_argument("--candidate-source", default=str(REPO_ROOT))
    p.add_argument("--candidate-sha")
    p.add_argument("--polyglot-root", default=os.environ.get("AFAST_POLYGLOT_ROOT"))
    p.add_argument("--installed-cache")
    p.add_argument("--history-index")
    p.add_argument("--host-python", default=sys.executable)
    p.add_argument("--events-dir")
    p.add_argument("--base-seed", type=int, default=20260919)
    p.add_argument("--allow-external-state", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--report-only", action="store_true")
    p.add_argument("--backfill-exec", action="store_true")
    p.add_argument("--cells-file", default=str(DEFAULT_CELLS_FILE))
    p.add_argument("--suites-file", default=str(DEFAULT_SUITES_FILE))
    return p


def _print_result(payload):
    print(json.dumps(payload))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def init_or_adopt_campaign(out_dir, cells_doc, *, baseline_source, candidate_source,
                            installed_cache, history_index, host_python, events_dir):
    """section 4: idempotent `campaign.py init`. Skips (does not error) when
    <out>/campaign/protocol.json already exists."""
    campaign_root = Path(out_dir) / "campaign"
    if (campaign_root / "protocol.json").exists():
        return {"adopted": True}
    proposal_path = Path(out_dir) / "campaign-proposal.json"
    _write_json(proposal_path, {
        "campaign_name": "fast-decisions-evals",
        "fast_decisions_budget": cells_doc.get("budget", {}),
    })
    invoke_tool("campaign", [
        "init", "--root", str(campaign_root), "--proposal", str(proposal_path),
        "--baseline-source", str(baseline_source), "--candidate-worktree", str(candidate_source),
        "--installed-cache", str(installed_cache), "--history-index", str(history_index),
        "--host-python", str(host_python), "--events-dir", str(events_dir),
    ])
    return {"adopted": False}


def run_one_experiment(*, cell_id, cells_doc, suites_doc, suite_id, split, rep, out_dir,
                        base_seed, baseline_source, candidate_source, candidate_sha,
                        polyglot_root, installed_cache, host_python, events_dir,
                        backfill_exec=False, which=None, doctor_runner=None):
    """prepare (skip if resuming unchanged) -> verify -> run -> reevaluate -> evaluate -> gate,
    for one (cell, suite, split, rep). Returns a dict describing what happened; raises
    EvalsError(4) pre-launch, never after `battery.py run` has been invoked."""
    cells_doc_cells = cells_doc["cells"]
    cell = cells_doc_cells[cell_id]
    suite = suites_doc["suites"][suite_id]
    defaults = cells_doc.get("defaults", {})
    campaign_root = Path(out_dir) / "campaign"
    exp = experiment_name(cell_id, suite_id, split, rep)
    experiment_dir = campaign_root / "experiments" / exp

    argv = cell_to_argv(cell_id, cells_doc, suites_doc, suite_id, split, rep,
                        out_root=out_dir, base_seed=base_seed,
                        baseline_source=baseline_source, candidate_source=candidate_source,
                        candidate_sha=candidate_sha, polyglot_root=polyglot_root)

    action, reason = resume_detection(experiment_dir, argv)
    if action == "error":
        raise EvalsError(2, f"{exp}: {reason}")
    if action == "prepare":
        invoke_tool("battery", ["prepare", *argv])
        _write_json(experiment_dir / "run-argv.json", argv)

    proposal = _read_json(experiment_dir / "proposal.json")

    budget_status = None
    try:
        status = invoke_tool("campaign", ["budget", "status", "--root", str(campaign_root)])
        budget_status = status.get("remaining")
    except EvalsError:
        budget_status = None

    ok, preflight, prompt_verification = run_verification(
        experiment_dir, proposal, cell, suite, split, candidate_sha, defaults,
        suite.get("required_toolchains", []), host_python,
        Path.home() / ".agents/skills/amplifier-skill-forge/tools/forge.py",
        budget_status=budget_status, num_runs=len(proposal.get("frozen_run_schedule", [])),
        per_launch_usd=cells_doc.get("budget", {}).get("per_launch_usd", 0.0),
        which=which, doctor_runner=doctor_runner,
    )
    _write_json(Path(out_dir) / "preflight.json", preflight)
    _write_json(Path(out_dir) / "prompt-verification.json", prompt_verification)
    if not ok:
        raise EvalsError(4, f"{exp}: precondition failed: {preflight}")

    if backfill_exec:
        invoke_tool("battery", ["backfill-exec", "--root", str(campaign_root), "--experiment", exp])

    invoke_tool("battery", ["run", "--root", str(campaign_root), "--experiment", exp])
    invoke_tool("battery", ["reevaluate", "--root", str(campaign_root), "--experiment", exp,
                            "--reason", "post-run rescore"])

    anchor = cell.get("anchor_cell")
    evaluate_argv = ["evaluate", "--root", str(campaign_root), "--experiment", exp]
    if anchor:
        anchor_exp = experiment_name(anchor, suite_id, split, rep)
        evaluate_argv += ["--baseline-root", str(campaign_root), "--baseline-experiment", anchor_exp]
    comparison = invoke_tool("battery", evaluate_argv)

    mechanism = comparison.get("mechanism")
    gate = gate_eval(cell["mechanism_gate"], mechanism)

    if "amplifier-fd" in cell["harnesses"]:
        recorded_label = comparison.get("amplifier_fd_series_label")
        if recorded_label:
            declared = series_label(cell_id, rep, "amplifier-fd", cell, defaults,
                                     cells_doc.get("effort_profiles", {}),
                                     cells_doc.get("model_routing_profiles", {}))
            cross_check_series_label(declared, recorded_label)

    return {"experiment": exp, "argv": argv, "gate": gate, "comparison": comparison}


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    out_dir = Path(args.out).expanduser().resolve()

    try:
        cells_doc = load_cells(args.cells_file)
        suites_doc = load_suites(args.suites_file)

        if args.resume or args.report_only:
            manifest_path = out_dir / "manifest.json"
            if not manifest_path.exists():
                raise EvalsError(2, f"--resume/--report-only requires an existing manifest at {manifest_path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            current_shas = compute_tool_shas()
            verify_tool_shas(manifest.get("tool_shas", {}), current_shas)
            suite_id = manifest["invocation"]["suite"]
            split = manifest["invocation"]["split"]
            reps = manifest["invocation"]["reps"]
            cell_ids = [c["id"] for c in manifest["cells"]]
            candidate_sha = manifest["candidate"]["frozen_git_sha"]
            baseline_source = manifest["baseline"]["source"]
            candidate_source = manifest["candidate"]["source"]
        else:
            if not args.suite or not args.split or not args.cells:
                raise EvalsError(2, "--suite, --split, and --cells are required for a fresh run")
            if not args.candidate_sha:
                raise EvalsError(2, "--candidate-sha is required unless --resume/--report-only")
            suite_id, split = args.suite, args.split
            reps_defaults = suites_doc.get("reps_defaults", {})
            default_reps = reps_defaults.get(split, 5 if split == "holdout" else 3)
            reps = args.reps if args.reps is not None else default_reps
            cell_ids = resolve_cell_ids(args.cells, cells_doc)
            candidate_sha = args.candidate_sha
            baseline_source = args.baseline_source
            candidate_source = args.candidate_source

        validate_cell_dependencies(cell_ids, cells_doc)
        validate_external_state_consent(cell_ids, cells_doc, args.allow_external_state)

        if split == "holdout" and not (out_dir / "PREREGISTRATION.md").exists():
            raise EvalsError(2, "--split holdout requires PREREGISTRATION.md to exist in --out first")

        if args.dry_run:
            all_argv = []
            for cid in cell_ids:
                for rep in range(1, reps + 1):
                    all_argv.append(cell_to_argv(
                        cid, cells_doc, suites_doc, suite_id, split, rep,
                        out_root=out_dir, base_seed=args.base_seed,
                        baseline_source=baseline_source or "", candidate_source=candidate_source,
                        candidate_sha=candidate_sha, polyglot_root=args.polyglot_root,
                    ))
            est = cost_estimate(len(cell_ids), reps, cells_doc)
            payload = {"out": str(out_dir), "cells": cell_ids, "exit": 0, "reason": "dry-run",
                       "argv": [["prepare", *a] for a in all_argv], "estimate": est}
            _print_result(payload)
            return 0

        if not args.report_only:
            init_or_adopt_campaign(
                out_dir, cells_doc, baseline_source=baseline_source, candidate_source=candidate_source,
                installed_cache=args.installed_cache, history_index=args.history_index,
                host_python=args.host_python, events_dir=args.events_dir,
            )

        cells_report = []
        gates_report = {}
        comparisons_by_cell = {}
        any_gate_failed = False
        candidate_snapshot = {"source": candidate_source, "requested_sha": candidate_sha}
        baseline_report = {"source": baseline_source}

        def _write_partial_state(reason):
            """Exit-3 (budget/launch-cap refused) partial state: write whatever
            manifest/gates exist so far, with placeholder entries for cells not
            yet reached, so --resume can pick up the whole batch later."""
            done_ids = {c["id"] for c in cells_report}
            partial_cells_report = list(cells_report)
            for rcid in cell_ids:
                if rcid in done_ids:
                    continue
                partial_cells_report.append({
                    "id": rcid, "experiments": [], "seeds": [],
                    "gate": {"passed": False, "flags": []}, "excluded_from_claims": True,
                })
            tool_shas = compute_tool_shas()
            manifest = build_manifest(
                argv=(argv or sys.argv[1:]), suite_id=suite_id, split=split, reps=reps,
                suite_doc=suites_doc["suites"][suite_id], candidate=candidate_snapshot,
                baseline=baseline_report, cells_report=partial_cells_report,
                budget_report=cells_doc.get("budget", {}), tool_shas=tool_shas,
            )
            _write_json(out_dir / "manifest.json", manifest)
            _write_json(out_dir / "gates.json", gates_report)
            payload = {"out": str(out_dir), "cells": cell_ids, "exit": 3, "reason": f"budget_refused: {reason}"}
            _print_result(payload)

        for cid in cell_ids:
            cell = cells_doc["cells"][cid]
            experiments = []
            seeds = []
            cell_gate = {"passed": True, "flags": []}
            comparisons_by_cell[cid] = []
            for rep in range(1, reps + 1):
                seeds.append(args.base_seed + rep)
                try:
                    if args.report_only:
                        campaign_root = out_dir / "campaign"
                        exp = experiment_name(cid, suite_id, split, rep)
                        invoke_tool("battery", ["reevaluate", "--root", str(campaign_root), "--experiment", exp,
                                                "--reason", "report-only rescore"])
                        evaluate_argv = ["evaluate", "--root", str(campaign_root), "--experiment", exp]
                        anchor = cell.get("anchor_cell")
                        if anchor:
                            anchor_exp = experiment_name(anchor, suite_id, split, rep)
                            evaluate_argv += ["--baseline-root", str(campaign_root),
                                              "--baseline-experiment", anchor_exp]
                        comparison = invoke_tool("battery", evaluate_argv)
                        gate = gate_eval(cell["mechanism_gate"], comparison.get("mechanism"))
                        result = {"experiment": exp, "gate": gate, "comparison": comparison}
                    else:
                        result = run_one_experiment(
                            cell_id=cid, cells_doc=cells_doc, suites_doc=suites_doc, suite_id=suite_id,
                            split=split, rep=rep, out_dir=out_dir, base_seed=args.base_seed,
                            baseline_source=baseline_source, candidate_source=candidate_source,
                            candidate_sha=candidate_sha, polyglot_root=args.polyglot_root,
                            installed_cache=args.installed_cache, host_python=args.host_python,
                            events_dir=args.events_dir, backfill_exec=args.backfill_exec,
                        )
                except EvalsError as e:
                    if e.code == 3:
                        gates_report[cid] = cell_gate
                        cells_report.append({
                            "id": cid, "experiments": experiments, "seeds": seeds,
                            "gate": cell_gate, "excluded_from_claims": True,
                        })
                        _write_partial_state(e.reason)
                        return 3
                    raise
                experiments.append(result["experiment"])
                comparisons_by_cell[cid].append(result.get("comparison"))
                if not result["gate"]["passed"]:
                    cell_gate["passed"] = False
                    any_gate_failed = True
                cell_gate["flags"] = sorted(set(cell_gate["flags"]) | set(result["gate"].get("flags", [])))
                if "latency_within_budget" in result["gate"]:
                    cell_gate.setdefault("latency_within_budget_by_rep", []).append(
                        result["gate"]["latency_within_budget"])
            if "latency_within_budget_by_rep" in cell_gate:
                per_rep = cell_gate["latency_within_budget_by_rep"]
                # None means "no latency figure this rep" (never fabricated);
                # a judge cell is within budget only when every rep that did
                # report a figure was within it.
                known = [v for v in per_rep if v is not None]
                cell_gate["latency_within_budget"] = all(known) if known else None
            gates_report[cid] = cell_gate
            cells_report.append({
                "id": cid, "experiments": experiments, "seeds": seeds,
                "gate": cell_gate, "excluded_from_claims": not cell_gate["passed"],
            })

        _write_json(out_dir / "gates.json", gates_report)

        # Task #4 amendment: an optional secondary anchor per cell (e.g. the
        # routing cell also compared against plain `plain`, not only its
        # `anchor_cell` `plain-sonnet`) -- a read-only extra `battery.py
        # evaluate` call (no new paid launches, no new measurement logic: pure
        # recompute from already-collected result files). The primary
        # evaluate (against anchor_cell) is re-run afterwards so the persisted
        # comparison.json on disk is left exactly as the primary flow set it.
        secondary_comparisons_by_cell = {}
        if not args.dry_run:
            campaign_root = out_dir / "campaign"
            for cid in cell_ids:
                cell = cells_doc["cells"][cid]
                secondary_anchor = cell.get("secondary_anchor")
                if not secondary_anchor:
                    continue
                secondary_comparisons_by_cell[cid] = []
                for rep in range(1, reps + 1):
                    exp = experiment_name(cid, suite_id, split, rep)
                    secondary_exp = experiment_name(secondary_anchor, suite_id, split, rep)
                    try:
                        secondary_comparisons_by_cell[cid].append(invoke_tool("battery", [
                            "evaluate", "--root", str(campaign_root), "--experiment", exp,
                            "--baseline-root", str(campaign_root), "--baseline-experiment", secondary_exp,
                        ]))
                    except EvalsError:
                        secondary_comparisons_by_cell[cid].append(None)
                    primary_anchor = cell.get("anchor_cell")
                    if primary_anchor:
                        primary_anchor_exp = experiment_name(primary_anchor, suite_id, split, rep)
                        try:
                            invoke_tool("battery", [
                                "evaluate", "--root", str(campaign_root), "--experiment", exp,
                                "--baseline-root", str(campaign_root), "--baseline-experiment", primary_anchor_exp,
                            ])
                        except EvalsError:
                            pass

        # section 8: report -- one series per (cell, rep, harness), one battery_report.py call
        series_args = []
        for cid in cell_ids:
            cell = cells_doc["cells"][cid]
            for rep in range(1, reps + 1):
                exp = experiment_name(cid, suite_id, split, rep)
                for harness in cell["harnesses"]:
                    label = series_label(cid, rep, harness, cell, cells_doc.get("defaults", {}),
                                          cells_doc.get("effort_profiles", {}),
                                          cells_doc.get("model_routing_profiles", {}))
                    series_args.append(f"{label}={out_dir / 'campaign'}:{exp}:{harness}")

        report_out = out_dir / "report"
        report_argv = ["--out", str(report_out),
                       "--title", f"fast-decisions {suite_id} {split} (reps={reps})"]
        for s_arg in series_args:
            report_argv += ["--series", s_arg]
        invoke_tool("battery_report", report_argv)

        tool_shas = compute_tool_shas()
        manifest = build_manifest(
            argv=(argv or sys.argv[1:]), suite_id=suite_id, split=split, reps=reps,
            suite_doc=suites_doc["suites"][suite_id], candidate=candidate_snapshot,
            baseline=baseline_report, cells_report=cells_report,
            budget_report=cells_doc.get("budget", {}), tool_shas=tool_shas,
        )
        validate_manifest_shape(manifest)
        _write_json(out_dir / "manifest.json", manifest)
        _write_json(out_dir / "cells.resolved.json", cells_report)

        # Task #2/#4: the results -> verdict -> design-recommendation layer.
        cell_results = []
        for cid in cell_ids:
            cell = cells_doc["cells"][cid]
            anchor = cell.get("anchor_cell")
            if not anchor:
                continue  # 'plain'/'plain-sonnet' are anchors, not candidates; 'externals' is Q3-only
            gate_passed = gates_report.get(cid, {}).get("passed", False)
            row = build_cell_result(
                cid, anchor, comparisons_by_cell.get(cid, []), comparisons_by_cell.get(anchor, []),
                gate_passed, split, reps,
            )
            secondary_anchor = cell.get("secondary_anchor")
            if secondary_anchor:
                secondary_comparisons = [c for c in secondary_comparisons_by_cell.get(cid, []) if c]
                if secondary_comparisons:
                    secondary_row = build_cell_result(
                        cid, secondary_anchor, secondary_comparisons,
                        comparisons_by_cell.get(secondary_anchor, []), gate_passed, split, reps,
                    )
                    row["vs_plain"] = {"anchor": secondary_anchor,
                                        "exec_time_ratio": secondary_row["exec_time_ratio"],
                                        "cost_ratio": secondary_row["cost_ratio"],
                                        "quality": secondary_row["quality"]}
            cell_results.append(row)

        q3 = None
        if "externals" in cell_ids:
            champion_id = next((c for c, d in cells_doc["cells"].items() if d.get("champion")), None)
            if champion_id and comparisons_by_cell.get(champion_id):
                q3 = q3_comparison(comparisons_by_cell[champion_id], comparisons_by_cell.get("externals", []))

        evidence_limits = set()
        for comps in comparisons_by_cell.values():
            for comp in comps:
                if not comp:
                    continue
                for el in (comp.get("evidence_limits") or []):
                    evidence_limits.add(el)
                cross = comp.get("cross")
                if cross:
                    for el in (cross.get("evidence_limits") or []):
                        evidence_limits.add(el)
        evidence_limits.add(f"bootstrap_ci: {BOOTSTRAP_RESAMPLES} resamples, seed={BOOTSTRAP_SEED}")
        evidence_limits.add(f"confirmed requires >= {MIN_REPS_FOR_CLAIM} reps, "
                            f">= {MIN_PAIRED_TASKS_FOR_CLAIM} paired passing tasks, and split=holdout")

        results = {
            "schema": "fast-decisions-evals/results/v1",
            "suite": suite_id, "split": split, "reps": reps,
            "cells": cell_results, "q3": q3,
            "evidence_limits": sorted(evidence_limits),
        }
        _write_json(out_dir / "results.json", results)
        (out_dir / "RESULTS.md").write_text(render_results_markdown(results), encoding="utf-8")
        (out_dir / "DESIGN-RECOMMENDATION.md").write_text(
            design_recommendation_text(results, cells_doc), encoding="utf-8")

        # Exit 6: on --resume, any planned experiment still missing a result.json
        # with no live worker means the batch did not actually finish.
        if args.resume and not args.report_only:
            campaign_root = out_dir / "campaign"
            all_experiments = [e for c in cells_report for e in c["experiments"]]
            incomplete = scan_incomplete_runs(campaign_root, all_experiments)
            if incomplete:
                payload = {"out": str(out_dir), "cells": cell_ids, "exit": 6,
                           "reason": f"runs incomplete after resume: {incomplete}"}
                _print_result(payload)
                return 6

        exit_code = 5 if any_gate_failed else 0
        payload = {"out": str(out_dir), "cells": cell_ids, "exit": exit_code,
                   "reason": "mechanism gate failed for at least one cell" if any_gate_failed else "ok"}
        _print_result(payload)
        return exit_code
    except EvalsError as e:
        _print_result({"out": str(out_dir), "cells": [], "exit": e.code, "reason": e.reason})
        return e.code


if __name__ == "__main__":
    sys.exit(main())
