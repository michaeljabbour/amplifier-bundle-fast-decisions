"""``launch``: decide once, then start a coding-agent harness on the chosen model and effort.

    amplifier-fast-decisions launch --harness claude --host-model claude-fable-5-1 --task "fix the typo" -- -p "fix the typo"

The portable form of decide-once: the decision happens at launch, before the harness's prompt cache exists, so
nothing is switched mid-session. The harness is started with ``execvp`` (it replaces this process), so its exit
code, tty and signals are its own. ``--dry-run`` prints the decision and the exact argv instead.

Interfaces (checked against the CLIs' own ``--help``; see ``HARNESSES``):

* Claude Code  ``claude --model M --effort E ...``
* Codex        ``codex -c model="M" -c model_reasoning_effort="E" ...`` (``-c`` is accepted by ``codex``, ``codex exec`` and
  ``codex exec resume``)
* Copilot CLI  ``copilot --model M ...`` (no effort flag: model choice is its only lever; a decided effort is reported
  as ``effort_applied: false``)

The model is set only when the decision routes (``route`` true); a stay-on-host decision leaves the harness's own
model untouched so a user's configured default and subscription behavior are preserved. Effort is set whenever the
decision carries one.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .decide import Decision


@dataclass(frozen=True)
class Harness:
    name: str
    binary: str
    model_flags: tuple[str, ...]            # template: "{model}" is substituted
    effort_flags: tuple[str, ...] | None    # None: the harness has no effort control
    prompt_flags: tuple[str, ...]           # flags whose next token is the prompt text (task extraction)
    verified: str                           # what was checked, and what was not


HARNESSES: dict[str, Harness] = {
    "claude": Harness("claude", "claude", ("--model", "{model}"), ("--effort", "{effort}"), (),
                      "flags confirmed against `claude --help` 2.1.289; launch not run against a live session"),
    "codex": Harness("codex", "codex", ("-c", 'model="{model}"'), ("-c", 'model_reasoning_effort="{effort}"'), (),
                     "flags confirmed against `codex exec --help` 0.160.0; launch not run against a live session"),
    "copilot": Harness("copilot", "copilot", ("--model", "{model}"), None, ("-p", "--prompt"),
                       "flags confirmed against `copilot --help` 0.0.412; launch not run against a live session"),
}
# Words that are subcommands, not the prompt, when guessing the task from a harness command line.
_SUBCOMMANDS = frozenset({"exec", "e", "resume", "review", "fork", "login", "mcp", "help"})


def extract_task(harness: str, args: Sequence[str]) -> str | None:
    """Best-effort: the prompt text in a harness command line (``copilot -p TEXT``, ``claude -p TEXT``,
    ``codex exec TEXT``). None when there is none (an interactive launch): pass ``--task`` instead."""
    spec = HARNESSES[harness]
    items = list(args)
    for i, token in enumerate(items):
        if token in spec.prompt_flags and i + 1 < len(items):
            return items[i + 1]
        for flag in spec.prompt_flags:
            if flag.startswith("--") and token.startswith(flag + "="):
                return token.split("=", 1)[1]
    # Without a prompt flag the prompt is the one positional word. Value-taking flags (``--model sonnet``) put a
    # second positional in view, and which flags take values differs per harness, so an ambiguous line yields
    # None rather than a guess: pass ``--task``.
    positional = [t for t in items if not t.startswith("-") and t not in _SUBCOMMANDS]
    return positional[0] if len(positional) == 1 else None


def build_argv(harness: str, decision: Decision, args: Sequence[str] = (), *, binary: str | None = None) -> tuple[list[str], dict[str, Any]]:
    """The command to run and what was applied: ``(argv, {"model_applied": bool, "effort_applied": bool})``.

    For Codex, ``exec`` / ``resume`` subcommands must precede the options: the flags are inserted after any
    leading subcommand words so ``codex exec resume ID PROMPT`` stays valid."""
    spec = HARNESSES[harness]
    flags: list[str] = []
    applied = {"model_applied": False, "effort_applied": False}
    if decision.route and decision.model:
        flags += [part.format(model=decision.model) for part in spec.model_flags]
        applied["model_applied"] = True
    if decision.effort and spec.effort_flags is not None:
        flags += [part.format(effort=decision.effort) for part in spec.effort_flags]
        applied["effort_applied"] = True
    argv = [binary or spec.binary]
    rest = list(args)
    if harness == "codex":
        while rest and rest[0] in _SUBCOMMANDS:
            argv.append(rest.pop(0))
    return argv + flags + rest, applied


def launch(harness: str, decision: Decision, args: Sequence[str] = (), *, dry_run: bool = False,
           binary: str | None = None, _exec: Callable[[str, list[str]], Any] = os.execvp) -> dict[str, Any]:
    """Run (or, with ``dry_run``, describe) the launch. On a real launch this does not return."""
    if harness not in HARNESSES:
        raise ValueError(f"harness must be one of {', '.join(HARNESSES)}")
    argv, applied = build_argv(harness, decision, args, binary=binary)
    found = shutil.which(argv[0])
    report = {"harness": harness, "argv": argv, "binary_found": bool(found), **applied,
              "decision": decision.to_dict(), "verified": HARNESSES[harness].verified}
    if dry_run:
        return report
    if not found:
        raise FileNotFoundError(f"{argv[0]} is not on PATH")
    _exec(found, argv)
    return report  # only reached by a test double


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
