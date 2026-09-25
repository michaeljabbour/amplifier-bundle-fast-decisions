#!/usr/bin/env python3
"""Live A/B measurement of the cache keep-alive and loop-stop levers.

Runs small disposable tasks through the real ``amplifier run`` with this
checkout's orchestrator (PYTHONPATH=src), once with the levers off and once
on, each in its own workspace and events dir, and reports per run: model
calls, provider-reported cost, keep-alive refreshes, the post-wait call's
cache reads/writes, loop notes, and the efficiency receipts -- then whether
the receipts' sums match the measured OFF-ON differences.

Always test traffic (AFAST_TRAFFIC=test). Uses the configured Anthropic
provider (normal API charges). Keys come from the caller's environment.

    set -a; . ~/.amplifier/keys.env; set +a
    python3 scripts/levers_live.py run --out /tmp/afast-levers --tasks wait330 --reps 1
    python3 scripts/levers_live.py report --out /tmp/afast-levers
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

JOB = """#!/bin/sh
# Background job: writes result.txt after {secs} seconds.
( sleep {secs}; echo "job finished: 42" > result.txt ) >/dev/null 2>&1 &
echo "job started"
"""
BUILD = """#!/bin/sh
# Fake build: one progress line every 15 s for 180 s.
i=0
while [ $i -lt 12 ]; do i=$((i+1)); echo "step $i/12 compiling..."; sleep 15; done
echo "BUILD OK: 12 targets"
"""
CHECK = """#!/bin/sh
echo "acquiring build lock..."
echo "error: build lock is held by another process (pid 4242); it is usually released within a minute, retry shortly" >&2
exit 1
"""

TASKS = {
    # A long tool wait: the next call's cache fate is the keep-alive measurement.
    "wait330": {"files": {}, "prompt": (
        "Use the bash tool to run exactly this command, with timeout 420: sleep 330 && echo waited-ok . "
        "Then reply with only the command's output."), "levers": ("cache_keepalive",)},
    # Polling: a background job finishes after 150 s.
    "poll": {"files": {"start_job.sh": JOB.format(secs=150)}, "prompt": (
        "Run ./start_job.sh (it starts a background job that creates result.txt when it is done). "
        "Wait for the job to finish, then reply with the exact contents of result.txt."), "levers": ("loop_stop",)},
    # Polling a long background build with short checks (the measured real pattern: `sleep 28 && tail log`).
    "monitor": {"files": {"build.sh": BUILD}, "prompt": (
        "Start ./build.sh in the background (nohup, output to build.log); it takes about 3 minutes. Check "
        "build.log every 20-30 seconds with a short command (each command must finish in under 30 seconds), "
        "and when the build is done reply with the last line of build.log."), "levers": ("loop_stop",)},
    # Retrying the same failure one attempt per command.
    "retry": {"files": {"check.sh": CHECK}, "prompt": (
        "Run ./check.sh. It fails while a build lock is held by another process; retry it, one attempt per "
        "command, until it passes. Do not edit check.sh or kill processes. Reply with its final output."),
        "levers": ("loop_stop",)},
    # The same failure every time.
    "fail": {"files": {"check.sh": CHECK}, "prompt": (
        "Run ./check.sh until it succeeds; the lock it reports is transient. Do not edit check.sh or kill "
        "processes. Reply with the final output of ./check.sh."), "levers": ("loop_stop",)},
}
LEVER_CONFIG = {"cache_keepalive": {"enabled": True}, "loop_stop": {"enabled": True}}


def _profile(run_dir: Path, workspace: Path, events: Path, levers_on: tuple[str, ...], name: str) -> Path:
    from amplifier_fast_decisions.cli import main as afast
    profile = run_dir / "profile.md"
    with contextlib.redirect_stdout(io.StringIO()):
        code = afast(["configure", "--bundle-root", str(ROOT), "--workspace", str(workspace), "--mode", "active",
                      "--backend", "deterministic", "--events", str(events), "--local-sources",
                      "--output", str(profile)])
    if code:
        raise RuntimeError("afast configure failed")
    data = json.loads(profile.read_text().split("---")[1])
    config = data["session"]["orchestrator"]["config"]
    # Plain Amplifier on the default model: no judge, no routing -- only the lever(s) under test.
    config.pop("effort_routing", None)
    config.update(mode="off", read_shortcut=False)
    for lever in levers_on:
        config[lever] = dict(LEVER_CONFIG[lever])
    data["bundle"]["name"] = name
    profile.write_text("---\n" + json.dumps(data, indent=2) + "\n---\n")
    return profile


def run_one(out: Path, task: str, arm: str, rep: int, model: str, provider: str, timeout: int) -> dict:
    spec = TASKS[task]
    run_dir = out / f"{task}-{arm}-r{rep}"
    workspace, events = run_dir / "ws", run_dir / "events"
    (workspace / ".amplifier").mkdir(parents=True, exist_ok=False)
    (workspace / ".amplifier" / "settings.local.yaml").write_text("bundle:\n  app: []\n")
    for rel, text in spec["files"].items():
        path = workspace / rel
        path.write_text(text)
        path.chmod(0o755)
    name = f"afast-levers-{task}-{arm}-r{rep}-{int(time.time())}"
    profile = _profile(run_dir, workspace, events, spec["levers"] if arm == "on" else (), name)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), AFAST_TRAFFIC="test", AFAST_OBSERVATORY="off",
               AMPLIFIER_MEMORY_CAPTURE="off")
    cmd = ["amplifier", "run", "--bundle", profile.as_uri(), "--mode", "single", "--provider", provider,
           "--model", model, "--output-format", "json", spec["prompt"]]
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True, timeout=timeout)
        code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, stdout, stderr = -1, "", "timeout"
    wall = time.time() - started
    (run_dir / "stdout.txt").write_text(stdout[-20000:])
    (run_dir / "stderr.txt").write_text(stderr[-20000:])
    subprocess.run(["amplifier", "bundle", "remove", name], capture_output=True, text=True, timeout=120)
    result = {"task": task, "arm": arm, "rep": rep, "exit_code": code, "wall_s": round(wall, 1)}
    (run_dir / "run.json").write_text(json.dumps(result, indent=2))
    return result


def _events(run_dir: Path) -> list[dict]:
    out = []
    for path in sorted((run_dir / "events").glob("*.jsonl")):
        for line in path.read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    out.sort(key=lambda e: (e.get("monotonic_ns") or 0))
    return out


def analyze_run(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "run.json").read_text())
    events = _events(run_dir)
    root_sessions = {e["session_id"] for e in events if e["event"] == "fast_decisions:turn_start"
                     and not e.get("parent_session_id")}
    calls, refreshes, receipts, notes, tools = [], [], [], [], []
    for e in events:
        d, kind = e.get("data") or {}, e["event"]
        if kind == "fast_decisions:slow_end" and d.get("status") == "ok":
            calls.append({k: d.get(k) for k in ("cost_usd", "input_tokens", "output_tokens", "cache_read_tokens",
                                                "cache_write_tokens", "duration_ms", "tools")})
        elif kind == "fast_decisions:cache_refresh":
            refreshes.append({k: d.get(k) for k in ("status", "cost_usd", "cache_read_tokens", "cache_write_tokens",
                                                    "output_tokens", "duration_ms")})
        elif kind == "fast_decisions:efficiency":
            receipts.append(d)
        elif kind == "fast_decisions:loop_note":
            notes.append(d.get("reason_code"))
        elif kind == "fast_decisions:tool_end":
            tools.append({"tool": d.get("tool"), "status": d.get("status"),
                          "seconds": round((d.get("duration_ms") or 0) / 1000, 1)})
    cost = sum(c["cost_usd"] or 0 for c in calls)
    refresh_cost = sum(r["cost_usd"] or 0 for r in refreshes)
    # The first model call after the longest tool wait.
    post_wait = None
    long_tools = [i for i, e in enumerate(events) if e["event"] == "fast_decisions:tool_end"
                  and (e["data"].get("duration_ms") or 0) > 250_000]
    if long_tools:
        after = [e for e in events[long_tools[-1]:] if e["event"] == "fast_decisions:slow_end"
                 and e["data"].get("status") == "ok"]
        if after:
            d = after[0]["data"]
            post_wait = {k: d.get(k) for k in ("cache_read_tokens", "cache_write_tokens", "cost_usd", "duration_ms")}
    return {**meta, "sessions": len(root_sessions), "model_calls": len(calls), "cost_usd": round(cost, 6),
            "refresh_calls": len(refreshes), "refresh_cost_usd": round(refresh_cost, 6),
            "total_cost_usd": round(cost + refresh_cost, 6), "post_wait_call": post_wait, "loop_notes": notes,
            "tools": tools, "calls": calls, "refreshes": refreshes, "receipts": receipts,
            "receipt_sums": {"calls_saved": sum(r.get("calls_saved") or 0 for r in receipts),
                             "usd_saved": round(sum(r.get("usd_saved") or 0 for r in receipts), 6)}}


def report(out: Path) -> dict:
    runs = [analyze_run(p) for p in sorted(out.iterdir()) if (p / "run.json").exists()]
    by_task: dict[str, dict] = {}
    for r in runs:
        by_task.setdefault(r["task"], {}).setdefault(r["arm"], []).append(r)
    comparison = {}
    for task, arms in by_task.items():
        off, on = arms.get("off", []), arms.get("on", [])
        if not off or not on:
            continue
        mean = lambda rs, k: sum(r[k] for r in rs) / len(rs)
        # Calls including refreshes, as the receipts count them.
        mean_calls = lambda rs: sum(r["model_calls"] + r["refresh_calls"] for r in rs) / len(rs)
        comparison[task] = {
            "n_off": len(off), "n_on": len(on),
            "measured_cost_diff_usd(off-on)": round(mean(off, "total_cost_usd") - mean(on, "total_cost_usd"), 6),
            "measured_call_diff(off-on)": round(mean_calls(off) - mean_calls(on), 3),
            "receipts_usd_saved_mean(on)": round(sum(r["receipt_sums"]["usd_saved"] for r in on) / len(on), 6),
            "receipts_calls_saved_mean(on)": round(sum(r["receipt_sums"]["calls_saved"] for r in on) / len(on), 3),
        }
    summary = {"runs": [{k: v for k, v in r.items() if k not in ("calls", "refreshes")} for r in runs],
               "comparison": comparison}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--out", required=True)
    run.add_argument("--tasks", default="wait330,poll,fail")
    run.add_argument("--arms", default="off,on")
    run.add_argument("--reps", type=int, default=1)
    run.add_argument("--rep-start", type=int, default=1)
    run.add_argument("--model", default="claude-opus-5-5")
    run.add_argument("--provider", default="anthropic")
    run.add_argument("--timeout", type=int, default=1500)
    run.add_argument("--parallel", type=int, default=6)
    rep = sub.add_parser("report")
    rep.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()
    if args.cmd == "run":
        if os.environ.get("AFAST_TRAFFIC", "test") != "test":
            raise SystemExit("AFAST_TRAFFIC must be test for this script")
        out.mkdir(parents=True, exist_ok=True)
        jobs = [(t, a, r) for r in range(args.rep_start, args.rep_start + args.reps)
                for t in args.tasks.split(",") for a in args.arms.split(",")]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = [pool.submit(run_one, out, t, a, r, args.model, args.provider, args.timeout) for t, a, r in jobs]
            for f in concurrent.futures.as_completed(futures):
                print(json.dumps(f.result()), flush=True)
    print(json.dumps(report(out)["comparison"], indent=2))


if __name__ == "__main__":
    main()
