#!/usr/bin/env python3
"""evals/apply_recommendation.py -- evidence-gated bundle reconfiguration.

Reads `<out>/results.json` (the schema `evals/run.py::main` writes -- see
`build_cell_result`/`q3_comparison` in `evals/run.py`) and, optionally,
`<out>/gates.json` (written by the same run, carrying each cell's mechanism
gate `flags` and, for judge cells, `latency_within_budget` -- see
`evals/run.py::gate_eval`), and applies ONLY the DESIGN-BRIDGE.md rules whose
evidence requirement is met with verdict == "confirmed". Screen-level results
are never applied -- see DESIGN-BRIDGE.md's "screen-level results ... are
never sufficient" language for rule (a), which this tool treats as the
policy for every rule.

This tool never re-derives a number: every figure it reads comes straight out
of `results.json`/`gates.json` (i.e. out of `evals/run.py`/`scripts/battery.py`
already-computed fields). It only applies DESIGN-BRIDGE.md's decision rules
and writes/refreshes bundle YAML.

Default output: an OPT-IN behavior file, `behaviors/fast-decisions-active.yaml`
(a `session.orchestrator` profile for `loop-fast-decisions`, in the shape of
`bundles/active.yaml`). The shadow default, `behaviors/fast-decisions.yaml`,
is left untouched unless `--promote-default` is passed, in which case ONLY
its hook's own `mode`/`backend` fields are flipped to the confirmed values
(never `allow_external_state: true` -- see DESIGN-BRIDGE.md rule (e), which
is a policy invariant no evidence overrides).

Exit codes: 0 = at least one rule applied (or would be, under --dry-run);
2 = no rule had confirmed evidence, nothing to apply (no files touched);
4 = malformed inputs (missing/unparseable results.json, cells.yaml, etc).
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover -- exercised via a dedicated test with sys.modules faked
    yaml = None

HERE = Path(__file__).resolve().parent

# The three cells DESIGN-BRIDGE.md's rules (a)/(b)/(c)/(d) key off of. See
# evals/cells.yaml for their fd/mechanism_gate definitions and
# evals/STUDY-DESIGN.md section 14 for the judge head-to-head cells.
MODE_CELL = "judge-local+effort"          # rules (a) and (c): mode + effort_routing default
JEV_MODE_TWIN_CELL = "judge-jev+effort"   # rule (b): judge backend default
ROUTING_CELL = "judge-local+effort+route"  # rule (d): model_routing default
ROUTING_ANCHOR = "plain-sonnet"           # R5's mandatory control (not just "plain")
CONFOUNDED_FLAG = "confounded_with_plain_sonnet"

ACTIVE_BEHAVIOR_RELPATH = "behaviors/fast-decisions-active.yaml"
DEFAULT_BEHAVIOR_RELPATH = "behaviors/fast-decisions.yaml"

RESULTS_SCHEMA = "fast-decisions-evals/results/v1"


class ApplyError(Exception):
    """Carries the exit code this failure must produce (malformed inputs -> 4)."""

    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------------------
# loading (mirrors evals/run.py's own reads -- no new derivation)
# ---------------------------------------------------------------------------

def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ApplyError(4, f"could not read/parse {path}: {e}") from e


def load_results(out_dir):
    path = Path(out_dir) / "results.json"
    if not path.exists():
        raise ApplyError(4, f"missing results.json at {path}")
    doc = _read_json(path)
    if doc.get("schema") != RESULTS_SCHEMA:
        raise ApplyError(4, f"unexpected results schema in {path}: {doc.get('schema')!r}")
    return doc


def load_gates(out_dir):
    """gates.json is optional -- an older/partial run may not have one. When
    absent, callers treat every cell's flags as unknown (empty set) and
    latency_within_budget as None (never fabricated)."""
    path = Path(out_dir) / "gates.json"
    if not path.exists():
        return {}
    return _read_json(path)


def load_cells_doc(repo):
    path = Path(repo) / "evals" / "cells.yaml"
    if not path.exists():
        raise ApplyError(4, f"missing cells.yaml at {path}")
    if yaml is None:
        raise ApplyError(4, f"pyyaml is not importable; install it to parse {path}")
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != "fast-decisions-evals/cells/v1":
        raise ApplyError(4, f"unexpected cells schema in {path}: {doc.get('schema')!r}")
    return doc


def by_cell(results_doc):
    return {row["cell"]: row for row in results_doc.get("cells", [])}


def cell_gate_entry(gates_doc, cell_id):
    return gates_doc.get(cell_id) or {}


# ---------------------------------------------------------------------------
# evidence gates (confirmed-only, per rule)
# ---------------------------------------------------------------------------

def is_confirmed_on_holdout(row, results_doc):
    """DESIGN-BRIDGE.md rule (a)'s evidence bar, applied to any row: verdict
    confirmed, split holdout, gate passed. Screen-level results never pass."""
    return bool(
        row is not None
        and row.get("verdict") == "confirmed"
        and results_doc.get("split") == "holdout"
        and row.get("gate_passed") is True
    )


def escalations_fired(gates_doc, cell_id):
    """True when the routing cell's mechanism_gate did NOT flag
    confounded_with_plain_sonnet (flag_if_zero_escalations fires only when
    total escalations == 0 -- see evals/run.py::gate_eval)."""
    entry = cell_gate_entry(gates_doc, cell_id)
    return CONFOUNDED_FLAG not in set(entry.get("flags", []))


def latency_within_budget(gates_doc, cell_id):
    entry = cell_gate_entry(gates_doc, cell_id)
    return entry.get("latency_within_budget")


# ---------------------------------------------------------------------------
# fd config lookup (mirrors evals/run.py::cell_to_argv's own reads of
# cells.yaml -- no new profile data invented here)
# ---------------------------------------------------------------------------

def build_fd_config(cell_id, cells_doc):
    """{backend, model?, effort_routing?, model_routing?} for one cell, read
    straight from cells.yaml's fd/effort_profiles/model_routing_profiles --
    the same source evals/run.py::cell_to_argv reads for `battery.py prepare`."""
    cell = cells_doc["cells"].get(cell_id)
    if cell is None:
        raise ApplyError(4, f"unknown cell {cell_id!r} in cells.yaml")
    fd = cell.get("fd") or {}
    config = {}
    if fd.get("backend"):
        config["backend"] = fd["backend"]
    if fd.get("model"):
        config["model"] = fd["model"]
    if fd.get("effort_profile"):
        profiles = cells_doc.get("effort_profiles", {})
        if fd["effort_profile"] not in profiles:
            raise ApplyError(4, f"unknown effort_profile {fd['effort_profile']!r} for cell {cell_id!r}")
        config["effort_routing"] = dict(profiles[fd["effort_profile"]])
    if fd.get("model_routing_profile"):
        profiles = cells_doc.get("model_routing_profiles", {})
        if fd["model_routing_profile"] not in profiles:
            raise ApplyError(4, f"unknown model_routing_profile {fd['model_routing_profile']!r} for cell {cell_id!r}")
        config["model_routing"] = dict(profiles[fd["model_routing_profile"]])
    return config


# ---------------------------------------------------------------------------
# recommendation assembly
# ---------------------------------------------------------------------------

def assemble_recommendation(results_doc, gates_doc, cells_doc):
    """Applies rules (a)/(b)/(c)/(d)/(e) to one results.json (+ its gates.json)
    and returns (active_config: dict|None, applied_rules: list[dict],
    notes: list[str]). active_config is None when nothing is confirmed --
    the caller must then apply no changes (exit 2)."""
    cells = by_cell(results_doc)
    applied_rules = []
    notes = []

    mode_row = cells.get(MODE_CELL)
    if not is_confirmed_on_holdout(mode_row, results_doc):
        verdict = mode_row.get("verdict") if mode_row else "not run"
        notes.append(
            f"mode: keep shadow -- {MODE_CELL} verdict is {verdict!r}, not confirmed on holdout "
            "with a passed mechanism gate (DESIGN-BRIDGE.md rule (a))."
        )
        return None, applied_rules, notes

    # (a) + (c): the confirmed arm's own fd config (backend + effort_routing)
    # becomes the active orchestrator profile. allow_external_state is never
    # copied here even if present -- rule (e) is enforced independently below.
    active_config = build_fd_config(MODE_CELL, cells_doc)
    active_config.pop("allow_external_state", None)
    r = mode_row["exec_time_ratio"]
    applied_rules.append({
        "rule": "mode+effort_routing", "cell": MODE_CELL,
        "detail": (f"confirmed on holdout: ratio={r['geomean']}, "
                   f"ci95=[{r['ci95_low']}, {r['ci95_high']}], "
                   f"quality_delta={mode_row['quality']['candidate_successes'] - mode_row['quality']['anchor_successes']:+d}"),
    })

    # (b) judge backend: never written automatically (rule (e)); only a note
    # when the jev twin independently clears the bar (confirmed, gate passed,
    # decision latency p95 within budget).
    jev_row = cells.get(JEV_MODE_TWIN_CELL)
    if jev_row and jev_row.get("verdict") == "confirmed" and jev_row.get("gate_passed") is True:
        lwb = latency_within_budget(gates_doc, JEV_MODE_TWIN_CELL)
        if lwb is True:
            notes.append(
                f"judge backend: {JEV_MODE_TWIN_CELL} also confirmed with decision latency "
                "within the 500ms budget -- recommend `backend: auto` semantics (jev when "
                "TYPESAFE_API_KEY is present AND allow_external_state is explicitly set by the "
                "operator, else local); NOT applied here -- external state stays opt-in "
                "(DESIGN-BRIDGE.md rule (e))."
            )
        else:
            notes.append(
                f"judge backend: keep ollama -- {JEV_MODE_TWIN_CELL} confirmed but decision "
                f"latency was not within the 500ms budget (latency_within_budget={lwb!r})."
            )

    # (d) model_routing: only when the routing cell is confirmed against its
    # mandatory plain-sonnet control AND escalations actually fired.
    routing_row = cells.get(ROUTING_CELL)
    if routing_row is not None:
        confirmed_vs_plain_sonnet = (
            routing_row.get("verdict") == "confirmed"
            and routing_row.get("gate_passed") is True
            and routing_row.get("anchor") == ROUTING_ANCHOR
        )
        if confirmed_vs_plain_sonnet and escalations_fired(gates_doc, ROUTING_CELL):
            routing_fd = build_fd_config(ROUTING_CELL, cells_doc)
            if "model_routing" in routing_fd:
                active_config["model_routing"] = routing_fd["model_routing"]
            applied_rules.append({
                "rule": "model_routing", "cell": ROUTING_CELL,
                "detail": "confirmed vs plain-sonnet (R5 control) with escalations firing",
            })
        elif confirmed_vs_plain_sonnet:
            notes.append(
                f"model_routing: {ROUTING_CELL} confirmed vs plain-sonnet but 0 escalations "
                "fired -- pin the cheaper model (amplifier_model: claude-sonnet-5) directly "
                "instead of routing (DESIGN-BRIDGE.md rule (d))."
            )
        else:
            notes.append(
                f"model_routing: keep off -- {ROUTING_CELL} verdict is "
                f"{routing_row.get('verdict')!r}, not confirmed against its plain-sonnet control."
            )
    else:
        notes.append("model_routing: keep off -- routing cell not present in this results.json.")

    notes.append(
        "external state (privacy): remains opt-in regardless of any result above "
        "(DESIGN-BRIDGE.md rule (e), docs/PRIVACY.md)."
    )

    return active_config, applied_rules, notes


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_active_behavior_yaml(active_config, notes):
    """behaviors/fast-decisions-active.yaml: an opt-in session.orchestrator
    profile in the shape of bundles/active.yaml, generated (never hand-edited)
    from a confirmed holdout result."""
    if yaml is None:
        raise ApplyError(4, "pyyaml is not importable; cannot render behaviors/fast-decisions-active.yaml")
    config = {"mode": "active"}
    config.update(active_config)
    doc = {
        "bundle": {
            "name": "fast-decisions-active",
            "version": "0.1.0",
            "description": (
                "GENERATED by evals/apply_recommendation.py from a confirmed holdout "
                "result -- see evals/DESIGN-BRIDGE.md. Opt-in active orchestrator "
                "profile; composes on top of bundle.md's shadow default, does not "
                "replace it."
            ),
        },
        "session": {
            "orchestrator": {
                "module": "loop-fast-decisions",
                "source": ("git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions"
                           "@main#subdirectory=modules/loop-fast-decisions"),
                "config": config,
            },
        },
    }
    header = "".join(f"# {n}\n" for n in notes)
    body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    return (header + "\n" if header else "") + body


def apply_promote_default(default_behavior_path, active_config):
    """--promote-default: flip ONLY behaviors/fast-decisions.yaml's hook
    `mode`/`backend` fields to the confirmed values. Never touches
    allow_external_state -- rule (e) is a policy invariant, not a result-
    driven decision, and no evidence promotes external state to default-on."""
    if yaml is None:
        raise ApplyError(4, f"pyyaml is not importable; cannot rewrite {default_behavior_path}")
    doc = yaml.safe_load(Path(default_behavior_path).read_text(encoding="utf-8"))
    hooks = doc.get("hooks") or []
    fd_hook = next((h for h in hooks if h.get("module") == "hooks-fast-decisions"), None)
    if fd_hook is None:
        raise ApplyError(4, f"no hooks-fast-decisions hook found in {default_behavior_path}")
    config = fd_hook.setdefault("config", {})
    config["mode"] = "active"
    if active_config.get("backend"):
        config["backend"] = active_config["backend"]
    config["allow_external_state"] = False  # invariant: never flipped by this tool
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)


def _unified_diff(old_text, new_text, path_label):
    old_lines = old_text.splitlines(keepends=True) if old_text is not None else []
    new_lines = new_text.splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        old_lines, new_lines, fromfile=f"a/{path_label}", tofile=f"b/{path_label}",
    ))


def render_changelog(applied_rules, notes):
    lines = ["# fast-decisions: apply confirmed evaluation recommendation", ""]
    if applied_rules:
        lines.append("Applied (confirmed evidence only):")
        for rule in applied_rules:
            lines.append(f"- {rule['rule']} ({rule['cell']}): {rule['detail']}")
    else:
        lines.append("Applied: nothing (no rule had confirmed evidence).")
    if notes:
        lines.append("")
        lines.append("Notes (not applied -- for human ratification):")
        for note in notes:
            lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    p = argparse.ArgumentParser(prog="evals/apply_recommendation.py")
    p.add_argument("--results", required=True, help="an <out> directory from evals/run.py (holds results.json, gates.json)")
    p.add_argument("--holdout-results", default=None,
                    help="a separate <out> directory to source holdout confirmation from, "
                         "when --results itself is not the holdout run")
    p.add_argument("--repo", required=True, help="the bundle repo worktree to read cells.yaml from and write behaviors/ into")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--promote-default", action="store_true",
                    help="also flip behaviors/fast-decisions.yaml's hook mode/backend to the confirmed values")
    return p


def _print(payload):
    print(json.dumps(payload))


def run(args):
    results_doc = load_results(args.results)
    gates_doc = load_gates(args.holdout_results or args.results)
    holdout_doc = load_results(args.holdout_results) if args.holdout_results else results_doc
    holdout_gates_doc = load_gates(args.holdout_results) if args.holdout_results else gates_doc
    cells_doc = load_cells_doc(args.repo)

    active_config, applied_rules, notes = assemble_recommendation(holdout_doc, holdout_gates_doc, cells_doc)

    if active_config is None:
        return {"applied": False, "exit": 2, "reason": "no rule had confirmed evidence; nothing to apply",
                "applied_rules": [], "notes": notes}

    active_yaml_text = render_active_behavior_yaml(active_config, notes)
    active_path = Path(args.repo) / ACTIVE_BEHAVIOR_RELPATH
    old_active_text = active_path.read_text(encoding="utf-8") if active_path.exists() else None
    diffs = {ACTIVE_BEHAVIOR_RELPATH: _unified_diff(old_active_text, active_yaml_text, ACTIVE_BEHAVIOR_RELPATH)}

    default_yaml_text = None
    if args.promote_default:
        default_path = Path(args.repo) / DEFAULT_BEHAVIOR_RELPATH
        default_yaml_text = apply_promote_default(default_path, active_config)
        old_default_text = default_path.read_text(encoding="utf-8")
        diffs[DEFAULT_BEHAVIOR_RELPATH] = _unified_diff(old_default_text, default_yaml_text, DEFAULT_BEHAVIOR_RELPATH)

    changelog = render_changelog(applied_rules, notes)

    payload = {
        "applied_rules": applied_rules, "notes": notes, "diff": diffs, "changelog": changelog,
    }

    if args.dry_run:
        payload.update({"applied": False, "exit": 0, "reason": "dry-run"})
        return payload

    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(active_yaml_text, encoding="utf-8")
    if args.promote_default:
        (Path(args.repo) / DEFAULT_BEHAVIOR_RELPATH).write_text(default_yaml_text, encoding="utf-8")
    payload.update({"applied": True, "exit": 0, "reason": "applied"})
    return payload


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        payload = run(args)
    except ApplyError as e:
        _print({"applied": False, "exit": e.code, "reason": e.reason})
        return e.code
    _print(payload)
    return payload["exit"]


if __name__ == "__main__":
    sys.exit(main())
