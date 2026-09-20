#!/usr/bin/env python3
"""Shared, testable logic for the S3 SWE-bench Verified stage (STUDY-DESIGN.md
section 15): candidate.config.json rendering + preflight checks. Kept
separate from `run.sh` (a thin bash wrapper) so both pieces of non-trivial
logic are unit-testable with fakes -- no subprocess, no network, no docker
required to exercise the pure functions in tests/test_swebench_stage.py.

Two subcommands, both driven by `run.sh`:

  render-candidate   Render agents/amplifier-fd-candidate/install.yaml's
                      `{{FD_*}}` template against candidate.config.json.
  check               Print a JSON preflight report (tool availability, env,
                      candidate config state) and exit 0/1.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

REQUIRED_CANDIDATE_KEYS = (
    "schema",
    "status",
    "backend",
    "model",
    "effort_routing",
    "allow_external_state",
)


class CandidateConfigError(ValueError):
    """candidate.config.json is missing, malformed, or not yet confirmed."""


# ---------------------------------------------------------------------------
# candidate.config.json validation + template rendering
# ---------------------------------------------------------------------------


def load_candidate_config(path: Path) -> dict[str, Any]:
    """Parse candidate.config.json and check its shape (not its confirmation
    state -- that is render_candidate_install_yaml's job). Raises
    CandidateConfigError on a missing file, invalid JSON, or missing keys.
    """
    if not path.is_file():
        raise CandidateConfigError(f"candidate config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CandidateConfigError(
            f"candidate config is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise CandidateConfigError("candidate config must be a JSON object")
    missing = [k for k in REQUIRED_CANDIDATE_KEYS if k not in data]
    if missing:
        raise CandidateConfigError(f"candidate config missing required keys: {missing}")
    return data


def _effort_routing_yaml(effort_routing: dict[str, Any]) -> str:
    """Render the `effort_routing:` block at the same indentation as the
    `backend:`/`model:` lines it sits beside in the install.yaml template
    (10 spaces -- see agents/amplifier-fd-candidate/install.yaml).
    """
    if not effort_routing:
        return ""
    lines = ["          effort_routing:"]
    for key in ("orient", "explore", "implement"):
        if key in effort_routing and effort_routing[key] is not None:
            lines.append(f"            {key}: {effort_routing[key]}")
    if effort_routing.get("phase_judge") is not None:
        lines.append(
            f"            phase_judge: {str(bool(effort_routing['phase_judge'])).lower()}"
        )
    return "\n".join(lines)


def render_candidate_install_yaml(config: dict[str, Any], *, template_text: str) -> str:
    """Render `template_text` (agents/amplifier-fd-candidate/install.yaml's
    contents) against a CONFIRMED candidate config. Pure string
    substitution -- no filesystem access.

    Raises CandidateConfigError if `config["status"] != "confirmed"` (the
    shipped placeholder's state) or any required value is still null, so a
    run can never silently proceed against an unset S1/S2 decision.
    """
    missing = [k for k in REQUIRED_CANDIDATE_KEYS if k not in config]
    if missing:
        raise CandidateConfigError(f"candidate config missing required keys: {missing}")
    if config.get("status") != "confirmed":
        raise CandidateConfigError(
            "candidate.config.json status is "
            f"{config.get('status')!r}, not 'confirmed' -- fill it from the "
            "S1/S2 decision (STUDY-DESIGN.md section 8) before rendering. "
            "Refusing to render a template against an unconfirmed config."
        )
    for key in ("backend", "model", "effort_routing", "allow_external_state"):
        if config.get(key) is None and key != "model":
            # model may legitimately be null only for backend "jev" or
            # "unavailable" (no local model to name); backend/effort_routing/
            # allow_external_state are always required once confirmed.
            raise CandidateConfigError(
                f"candidate config field {key!r} is null; cannot render"
            )

    backend = config["backend"]
    model = config.get("model")
    allow_external_state = bool(config["allow_external_state"])
    effort_routing = config.get("effort_routing") or {}

    model_line = f"          model: {model}" if model else ""
    effort_yaml = _effort_routing_yaml(effort_routing)
    ollama_model = model if backend == "ollama" and model else "qwen3:0.6b"

    rendered = (
        template_text.replace("{{FD_BACKEND}}", str(backend))
        .replace("{{FD_MODEL_LINE}}", model_line)
        .replace("{{FD_EFFORT_ROUTING_YAML}}", effort_yaml)
        .replace("{{FD_ALLOW_EXTERNAL_STATE}}", str(allow_external_state).lower())
        .replace("{{FD_OLLAMA_MODEL}}", ollama_model)
    )
    if "{{FD_SHA}}" not in rendered:
        raise CandidateConfigError(
            "template is missing the {{FD_SHA}} placeholder; refusing to render"
        )
    return rendered


def render_candidate_agent_dir(
    config_path: Path,
    template_dir: Path,
    out_dir: Path,
    *,
    fd_sha: str,
) -> Path:
    """Render the full amplifier-fd-candidate agent dir (install.yaml
    substituted; meta.yaml/invocation.md/data.yaml copied verbatim) into
    `out_dir`. Returns `out_dir`. Raises CandidateConfigError if config is
    unconfirmed or malformed (see render_candidate_install_yaml).
    """
    config = load_candidate_config(config_path)
    template_text = (template_dir / "install.yaml").read_text(encoding="utf-8")
    rendered = render_candidate_install_yaml(config, template_text=template_text)
    rendered = rendered.replace("{{FD_SHA}}", fd_sha)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "install.yaml").write_text(rendered, encoding="utf-8")
    for name in ("meta.yaml", "invocation.md", "data.yaml"):
        src = template_dir / name
        if src.is_file():
            (out_dir / name).write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )
    return out_dir


# ---------------------------------------------------------------------------
# Preflight (run.sh --check). Every external probe is behind an injectable
# `run_cmd` so tests exercise the real decision logic with fakes -- no real
# subprocess, docker daemon, or network call runs in a test.
# ---------------------------------------------------------------------------

RunCmd = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _default_run_cmd(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=30, check=False
    )  # pragma: no cover


def check_preflight(
    *,
    which: Callable[[str], str | None] = shutil.which,
    run_cmd: RunCmd = _default_run_cmd,
    env: dict[str, str] | None = None,
    candidate_config_path: Path | None = None,
    pinned_ids_path: Path | None = None,
) -> dict[str, Any]:
    """Pure(ish) preflight check: every side effect (PATH lookup, subprocess,
    env read, file read) is passed in, so tests substitute fakes for all of
    them and this function's branching logic is exercised directly. Returns
    a JSON-safe report; never raises -- every failure is a field, matching
    this repo's other harness/report tools (e.g. scripts/battery.py).
    """
    env = env if env is not None else {}
    report: dict[str, Any] = {"ok": True, "checks": {}}

    def record(name: str, ok: bool, detail: str) -> None:
        report["checks"][name] = {"ok": ok, "detail": detail}
        if not ok:
            report["ok"] = False

    for tool in ("amplifier-digital-twin", "uv", "python3", "docker"):
        path = which(tool)
        record(f"tool:{tool}", path is not None, path or "not on PATH")

    if which("docker"):
        try:
            result = run_cmd(["docker", "info"])
            record(
                "docker-running",
                result.returncode == 0,
                "docker info"
                if result.returncode == 0
                else (result.stderr or "docker info failed"),
            )
        except (
            OSError
        ) as exc:  # pragma: no cover -- exercised via fake run_cmd raising in tests
            record("docker-running", False, f"docker info raised: {exc}")
    else:
        record("docker-running", False, "docker not on PATH")

    for key in ("ANTHROPIC_API_KEY",):
        record(f"env:{key}", bool(env.get(key)), "set" if env.get(key) else "missing")
    # TYPESAFE_API_KEY is optional (only needed if a future variant routes
    # through it); record its presence without failing preflight on it.
    report["checks"]["env:TYPESAFE_API_KEY"] = {
        "ok": True,
        "detail": "set" if env.get("TYPESAFE_API_KEY") else "not set (optional)",
    }

    if pinned_ids_path is not None:
        ids = (
            [
                ln.strip()
                for ln in pinned_ids_path.read_text(encoding="utf-8").splitlines()
            ]
            if pinned_ids_path.is_file()
            else []
        )
        ids = [i for i in ids if i]
        record("pinned-instance-ids", len(ids) >= 30, f"{len(ids)} id(s) (need >= 30)")

    if candidate_config_path is not None:
        try:
            cfg = load_candidate_config(candidate_config_path)
            confirmed = cfg.get("status") == "confirmed"
            record(
                "candidate-config",
                True,  # a well-formed placeholder is a legitimate pre-S1/S2 state; not a preflight failure
                "confirmed"
                if confirmed
                else f"status={cfg.get('status')!r} (S1/S2 not yet confirmed)",
            )
        except CandidateConfigError as exc:
            record("candidate-config", False, str(exc))

    return report


# ---------------------------------------------------------------------------
# {{FD_SHA}} substitution for the two static agents (amplifier-plain has none;
# amplifier-fd-incumbent's install.yaml carries a literal {{FD_SHA}} inside
# its embedded bundle-YAML heredoc, same as amplifier-fd-candidate's
# template). Kept as a pure function over text so it is unit-testable
# without touching a real agents/ directory.
# ---------------------------------------------------------------------------


def substitute_fd_sha_text(text: str, fd_sha: str) -> str:
    return text.replace("{{FD_SHA}}", fd_sha)


def substitute_fd_sha_in_agents_dir(agents_dir: Path, fd_sha: str) -> list[Path]:
    """Rewrite every `install.yaml` under `agents_dir/*/install.yaml` that
    contains a literal `{{FD_SHA}}`, substituting it in place. Agents with no
    such placeholder (amplifier-plain) are left untouched. Returns the list
    of files actually rewritten.
    """
    touched: list[Path] = []
    for install_path in sorted(agents_dir.glob("*/install.yaml")):
        text = install_path.read_text(encoding="utf-8")
        if "{{FD_SHA}}" not in text:
            continue
        install_path.write_text(substitute_fd_sha_text(text, fd_sha), encoding="utf-8")
        touched.append(install_path)
    return touched


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_substitute_fd_sha(args: argparse.Namespace) -> int:
    touched = substitute_fd_sha_in_agents_dir(Path(args.agents_dir), args.fd_sha)
    for p in touched:
        print(f"substituted FD_SHA in {p}", file=sys.stderr)
    return 0


def _cmd_render_candidate(args: argparse.Namespace) -> int:
    try:
        render_candidate_agent_dir(
            Path(args.config),
            Path(args.template).parent
            if Path(args.template).name == "install.yaml"
            else Path(args.template),
            Path(args.out).parent
            if Path(args.out).name == "install.yaml"
            else Path(args.out),
            fd_sha=args.fd_sha,
        )
    except CandidateConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"rendered candidate agent into {args.out}", file=sys.stderr)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    import os

    report = check_preflight(
        env=dict(os.environ),
        candidate_config_path=Path(args.config) if args.config else None,
        pinned_ids_path=Path(args.pinned_ids) if args.pinned_ids else None,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S3 SWE-bench stage helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    subs = sub.add_parser(
        "substitute-fd-sha",
        help="substitute {{FD_SHA}} in every agents/*/install.yaml that has it",
    )
    subs.add_argument("--agents-dir", required=True)
    subs.add_argument("--fd-sha", required=True)
    subs.set_defaults(func=_cmd_substitute_fd_sha)

    render = sub.add_parser(
        "render-candidate", help="render amplifier-fd-candidate's install.yaml template"
    )
    render.add_argument("--config", default=str(HERE / "candidate.config.json"))
    render.add_argument(
        "--template", default=str(HERE / "agents" / "amplifier-fd-candidate")
    )
    render.add_argument("--out", required=True)
    render.add_argument(
        "--fd-sha",
        required=True,
        help="pinned amplifier-bundle-fast-decisions commit sha",
    )
    render.set_defaults(func=_cmd_render_candidate)

    check = sub.add_parser("check", help="print a JSON preflight report")
    check.add_argument("--config", default=str(HERE / "candidate.config.json"))
    check.add_argument("--pinned-ids", default=str(HERE / "PINNED_INSTANCE_IDS"))
    check.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
