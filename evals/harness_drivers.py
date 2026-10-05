"""Multi-turn drivers for external coding-agent harnesses (study S4, plan E6a).

One scripted session = one `start` (turn 1) and N-1 `resume` calls (turns 2..N) against the same harness session,
exactly the shape `evals/paired.py` runs for Amplifier: scripted prompts, the same workspace, a validator after
each turn. Per-harness cost extraction:

  claude   `claude -p --output-format json`          cost = total_cost_usd (a token-based estimate, `reported`)
  codex    `codex exec --json` / `exec resume --json` cost = tokens x configured rates (`tokens_x_rates`); None if unpriced
  copilot  `copilot -p ... --resume UUID`            cost = premium requests x model multiplier x $0.04 (`premium_requests`);
                                                      a portability screen, not metered per token

A harness whose cost cannot be read yields `cost_usd=None` and `cost_basis=None`; nothing is estimated silently.

Interfaces were checked against each CLI's `--help` and exercised once with a one-sentence prompt (see
`docs/evidence/2026-10-05-harness-drivers/SMOKE.md`). Not covered: long sessions, tool-heavy turns, error paths
beyond a non-zero exit, and wiring these results into `paired.session_row` (which parses Amplifier events).
Stdlib only. Never prints environment values.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

COPILOT_PREMIUM_USD = 0.04      # list overage price per premium request
# Premium-request multipliers by model id prefix (GitHub Copilot model multipliers; verify before a study).
COPILOT_MULTIPLIERS: dict[str, float] = {"gpt-5-mini": 0.0, "gpt-4.1": 0.0, "claude-haiku": 0.33, "claude-sonnet": 1.0,
                                         "gpt-5": 1.0, "gemini": 1.0, "claude-opus": 3.0}


@dataclass
class TurnResult:
    harness: str
    session_id: str | None
    text: str
    exit_code: int
    wall_ms: float
    usage: dict[str, Any] = field(default_factory=dict)   # input/output/cache_read/cache_write tokens when reported
    cost_usd: float | None = None
    cost_basis: str | None = None                         # reported | tokens_x_rates | premium_requests | None
    model: str | None = None
    error: str | None = None
    argv: list[str] = field(default_factory=list)         # what was run (no secrets are ever in argv)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Runner = Callable[..., subprocess.CompletedProcess]


def _run(argv: Sequence[str], cwd: str | Path, timeout: float, env: dict[str, str] | None, runner: Runner | None):
    """Run one harness call. A timeout or a missing binary becomes a failed CompletedProcess (returncode 124 / 127), so
    a driver always returns a TurnResult and the caller decides what a failed turn means."""
    start = time.perf_counter()
    try:
        done = (runner or subprocess.run)(list(argv), cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                                          env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        done = subprocess.CompletedProcess(list(argv), 124, "", f"timed out after {timeout:g}s")
    except OSError as exc:
        done = subprocess.CompletedProcess(list(argv), 127, "", f"cannot run {argv[0]}: {type(exc).__name__}")
    return done, (time.perf_counter() - start) * 1000


class Driver:
    name = ""
    binary = ""

    def __init__(self, *, model: str | None = None, effort: str | None = None, timeout_s: float = 900,
                 env: dict[str, str] | None = None, extra_args: Sequence[str] = (), runner: Runner | None = None,
                 binary: str | None = None):
        self.model, self.effort, self.timeout_s = model, effort, timeout_s
        self.env, self.extra_args, self.runner = env or {}, list(extra_args), runner
        self.binary = binary or self.binary

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def start(self, prompt: str, cwd: str | Path) -> TurnResult:
        raise NotImplementedError

    def resume(self, session_id: str, prompt: str, cwd: str | Path) -> TurnResult:
        raise NotImplementedError


class ClaudeDriver(Driver):
    """`claude -p PROMPT --output-format json [--model M] [--effort E] [--resume SID]`."""
    name, binary = "claude", "claude"

    def _argv(self, prompt: str, resume: str | None) -> list[str]:
        argv = [self.binary, "-p", prompt, "--output-format", "json"]
        if self.model:
            argv += ["--model", self.model]
        if self.effort:
            argv += ["--effort", self.effort]
        if resume:
            argv += ["--resume", resume]
        return argv + self.extra_args

    def _turn(self, prompt: str, cwd, resume: str | None) -> TurnResult:
        argv = self._argv(prompt, resume)
        done, wall = _run(argv, cwd, self.timeout_s, self.env, self.runner)
        return self.parse(done.stdout, done.returncode, wall, done.stderr, argv)

    def start(self, prompt, cwd):
        return self._turn(prompt, cwd, None)

    def resume(self, session_id, prompt, cwd):
        return self._turn(prompt, cwd, session_id)

    @staticmethod
    def parse(stdout: str, code: int, wall_ms: float, stderr: str = "", argv: Sequence[str] = ()) -> TurnResult:
        try:
            data = json.loads(stdout)
        except ValueError:
            return TurnResult("claude", None, "", code, wall_ms, error=(stderr or stdout)[-300:] or "no JSON output", argv=list(argv))
        usage = data.get("usage") or {}
        cost = data.get("total_cost_usd")
        models = list((data.get("modelUsage") or {}).keys())
        return TurnResult(
            "claude", data.get("session_id"), str(data.get("result") or ""), code, wall_ms,
            usage={"input": usage.get("input_tokens"), "output": usage.get("output_tokens"),
                   "cache_read": usage.get("cache_read_input_tokens"), "cache_write": usage.get("cache_creation_input_tokens"),
                   "num_turns": data.get("num_turns")},
            cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
            cost_basis="reported" if isinstance(cost, (int, float)) else None,
            model=models[0] if len(models) == 1 else (",".join(models) or None),
            error=(data.get("result") if data.get("is_error") else None), argv=list(argv))


class CodexDriver(Driver):
    """`codex exec --json [-m M] [-c model_reasoning_effort="E"] PROMPT`; turns 2+: `codex exec resume SID PROMPT`.

    ``rates`` is {"input": usd/M, "cached_input": usd/M, "output": usd/M}; without it cost is None (never guessed)."""
    name, binary = "codex", "codex"

    def __init__(self, *, rates: dict[str, float] | None = None, resume_args: Sequence[str] = (), **kw):
        super().__init__(**kw)
        self.rates = rates
        # `exec resume` accepts fewer options than `exec` (no -s/--sandbox: the session keeps its sandbox), so
        # extra_args apply to the first turn only and resume_args to the later ones.
        self.resume_args = list(resume_args)
        self._cumulative: dict[str, dict[str, int]] = {}   # session id -> cumulative usage after the last call

    def _flags(self, resume: bool = False) -> list[str]:
        flags = ["--json", "--skip-git-repo-check"]
        if self.model:
            flags += ["-c", f'model="{self.model}"']
        if self.effort:
            flags += ["-c", f'model_reasoning_effort="{self.effort}"']
        return flags + (self.resume_args if resume else self.extra_args)

    def start(self, prompt, cwd):
        argv = [self.binary, "exec", *self._flags(), prompt]
        done, wall = _run(argv, cwd, self.timeout_s, self.env, self.runner)
        result = self.parse(done.stdout, done.returncode, wall, done.stderr, argv, self.rates, self.model)
        if result.session_id and getattr(result, "usage_cumulative", None):
            self._cumulative[result.session_id] = result.usage_cumulative
        return result

    def resume(self, session_id, prompt, cwd):
        argv = [self.binary, "exec", "resume", *self._flags(resume=True), session_id, prompt]
        done, wall = _run(argv, cwd, self.timeout_s, self.env, self.runner)
        result = self.parse(done.stdout, done.returncode, wall, done.stderr, argv, self.rates, self.model, session_id,
                            previous=self._cumulative.get(session_id))
        if getattr(result, "usage_cumulative", None):
            self._cumulative[session_id] = result.usage_cumulative
        return result

    USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")

    @staticmethod
    def parse(stdout: str, code: int, wall_ms: float, stderr: str = "", argv: Sequence[str] = (),
              rates: dict[str, float] | None = None, model: str | None = None, session_id: str | None = None,
              previous: dict[str, int] | None = None) -> TurnResult:
        """`turn.completed.usage` in `codex exec --json` is the THREAD's cumulative total (verified against the
        rollout file's total_token_usage vs last_token_usage on a two-turn session), not the turn's. This takes the
        last such event and subtracts ``previous`` (the cumulative total after the prior call) to get this call's usage."""
        text, cumulative, error = "", {}, None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "thread.started":
                session_id = event.get("thread_id") or session_id
            elif kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = str(item.get("text") or text)
            elif kind == "turn.completed":
                cumulative = {k: int((event.get("usage") or {}).get(k) or 0) for k in CodexDriver.USAGE_KEYS}
            elif kind in ("turn.failed", "error"):
                detail = event.get("error") or event
                error = str(detail.get("message") if isinstance(detail, dict) else detail)[:300]
        usage = {k: max(v - (previous or {}).get(k, 0), 0) for k, v in cumulative.items()} if cumulative else {}
        cost = basis = None
        if rates and usage:
            fresh = max(usage["input_tokens"] - usage["cached_input_tokens"], 0)
            cost = (fresh * rates["input"] + usage["cached_input_tokens"] * rates.get("cached_input", rates["input"])
                    + usage["output_tokens"] * rates["output"]) / 1e6
            basis = "tokens_x_rates"
        result = TurnResult("codex", session_id, text, code, wall_ms, usage=usage, cost_usd=cost, cost_basis=basis, model=model,
                            error=error or ((stderr or "")[-300:] if code else None), argv=list(argv))
        result.usage_cumulative = cumulative          # type: ignore[attr-defined]
        return result


class CopilotDriver(Driver):
    """`copilot -p PROMPT --model M [--resume UUID] -s --allow-all-tools`.

    Copilot lets the caller choose the session id (`--resume UUID` starts a new session with that UUID), so the
    driver allocates one and reuses it. No token usage is reported: cost is premium requests x multiplier x $0.04,
    one premium request per prompt (agent-internal tool calls are not premium requests). Effort cannot be set."""
    name, binary = "copilot", "copilot"

    def __init__(self, *, multipliers: dict[str, float] | None = None, **kw):
        super().__init__(**kw)
        self.multipliers = multipliers or COPILOT_MULTIPLIERS

    def multiplier(self) -> float | None:
        model = self.model or ""
        for prefix in sorted(self.multipliers, key=len, reverse=True):
            if model.startswith(prefix):
                return self.multipliers[prefix]
        return None

    def _turn(self, prompt: str, cwd, session_id: str) -> TurnResult:
        argv = [self.binary, "-p", prompt, "-s", "--allow-all-tools", "--resume", session_id]
        if self.model:
            argv += ["--model", self.model]
        argv += self.extra_args
        done, wall = _run(argv, cwd, self.timeout_s, self.env, self.runner)
        mult = self.multiplier()
        return TurnResult("copilot", session_id, (done.stdout or "").strip(), done.returncode, wall,
                          usage={"premium_requests": 1, "multiplier": mult},
                          cost_usd=None if mult is None else round(mult * COPILOT_PREMIUM_USD, 6),
                          cost_basis=None if mult is None else "premium_requests", model=self.model,
                          error=(done.stderr or "")[-300:] if done.returncode else None, argv=argv)

    def start(self, prompt, cwd):
        return self._turn(prompt, cwd, str(uuid.uuid4()))

    def resume(self, session_id, prompt, cwd):
        return self._turn(prompt, cwd, session_id)


DRIVERS: dict[str, type[Driver]] = {"claude": ClaudeDriver, "codex": CodexDriver, "copilot": CopilotDriver}


def run_scripted_session(driver: Driver, prompts: Sequence[str], cwd: str | Path, *,
                         after_turn: Callable[[int, TurnResult], Any] | None = None,
                         stop_on_failure: bool = True) -> dict[str, Any]:
    """Run the scripted turns in one harness session. ``after_turn(i, result)`` is the hook for the per-turn validator
    (the same checks as S1). Stops at the first failed turn unless told otherwise (a resume needs a session id)."""
    results: list[TurnResult] = []
    session_id: str | None = None
    for i, prompt in enumerate(prompts):
        result = driver.start(prompt, cwd) if i == 0 else driver.resume(session_id or "", prompt, cwd)
        results.append(result)
        session_id = result.session_id or session_id
        if after_turn:
            after_turn(i, result)
        if stop_on_failure and (result.exit_code != 0 or result.session_id is None):
            break
    costs = [r.cost_usd for r in results]
    complete = len(results) == len(prompts) and all(r.exit_code == 0 for r in results)
    return {"harness": driver.name, "session_id": session_id, "turns": [r.to_dict() for r in results],
            "complete": complete, "wall_ms": round(sum(r.wall_ms for r in results), 1),
            # the session cost is only stated when every turn's cost was read; otherwise None, never a partial sum
            "cost_usd": round(sum(costs), 6) if costs and all(c is not None for c in costs) else None,
            "cost_basis": results[0].cost_basis if results and len({r.cost_basis for r in results}) == 1 else None}


def make_driver(harness: str, **kw: Any) -> Driver:
    if harness not in DRIVERS:
        raise ValueError(f"harness must be one of {', '.join(DRIVERS)}")
    return DRIVERS[harness](**kw)
