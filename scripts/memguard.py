#!/usr/bin/env python3
"""memguard: run untrusted/scenario code under a hard memory cap, a timeout and a system-memory floor.

Why: on 2026-10-01 a Go test binary (`dominoes.test`) grew to 120-470 GB while validating a scenario and drove a
128 GB Mac out of memory four times (JetsamEvents), once killing the Forge daemon mid-campaign. Every place that
executes scenario code must therefore go through here (graders, hidden tests, validators), and campaigns watch their
agent sessions with the same primitives (`process_table`, `available_memory_bytes`, `kill_pids`).

The command runs in its OWN SESSION / process group. Every 0.25 s the RSS of the whole tree (the process group plus
all descendants, so grandchildren and setsid'ed escapees are counted) is summed. The whole tree gets SIGTERM, then
SIGKILL after 2 s, when:
  * the tree exceeds ``cap``                         -> killed = "memory"
  * ``timeout`` passes                               -> killed = "timeout"
  * system AVAILABLE memory drops below ``floor``    -> killed = "system_floor"   (default min(24 GB, 20% of RAM))
Belt and braces in the child's environment: GOMEMLIMIT=<cap>, GOFLAGS=-p=2, CARGO_BUILD_JOBS=2, NODE_OPTIONS=
--max-old-space-size=<cap MiB>; on Linux also RLIMIT_AS (generous: it breaks Go/V8 when tight) and RLIMIT_CORE=0.

CLI:  python3 scripts/memguard.py run --cap-gb N --timeout S [--cwd DIR] [--floor-gb F] -- cmd ...
      stdout/stderr of the command pass through; the LAST line printed is a JSON object
      {"killed": "memory"|"timeout"|"system_floor"|null, "peak_rss_gb": x, "wall_s": y, "returncode": z}.
      Exit code: the command's, 137 when killed for memory/system_floor, 124 for a timeout.
Library: ``run(...)`` is a drop-in for ``subprocess.run`` (raises ``subprocess.TimeoutExpired`` on timeout and
``ResourceLimit`` on a memory / system-floor kill); ``run_guarded(...)`` returns the full ``GuardResult``.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field

try:  # optional: psutil is faster and more precise, everything works without it
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - exercised through the ps fallback tests
    psutil = None

GB = 1024 ** 3
DEFAULT_CAP_GB = 4.0
DEFAULT_TIMEOUT_S = 300.0
POLL_S = 0.25
KILL_GRACE_S = 2.0
ENV_CAP = "PAIRED_GRADER_CAP_GB"
ENV_TIMEOUT = "PAIRED_GRADER_TIMEOUT_S"
ENV_CONCURRENCY = "MEMGUARD_MAX_CONCURRENT"


class ResourceLimit(Exception):
    """A guarded command was killed for memory or system-floor reasons (a failed check, never an infra failure)."""

    def __init__(self, guard: "GuardResult"):
        super().__init__(f"killed ({guard.killed}): peak {guard.peak_rss_gb:.2f} GB in {guard.wall_s:.1f}s")
        self.guard = guard


@dataclass
class GuardResult:
    returncode: int | None = None
    killed: str | None = None
    peak_rss_gb: float = 0.0
    wall_s: float = 0.0
    stdout: str | bytes | None = None
    stderr: str | bytes | None = None
    killed_pids: list = field(default_factory=list)

    def summary(self) -> dict:
        return {"killed": self.killed, "peak_rss_gb": round(self.peak_rss_gb, 3), "wall_s": round(self.wall_s, 2),
                "returncode": self.returncode}


# ----------------------------------------------------------------------------------------- system memory

def total_memory_bytes() -> int:
    if psutil is not None:
        return int(psutil.virtual_memory().total)
    if sys.platform == "darwin":
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False).stdout.strip())
    return _meminfo_kb("MemTotal") * 1024


def _meminfo_kb(key: str) -> int:
    with open("/proc/meminfo", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(key + ":"):
                return int(line.split()[1])
    raise OSError(f"{key} not in /proc/meminfo")


def _vm_stat_available() -> int:
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, check=False).stdout
    page = 4096
    pages = {}
    for line in out.splitlines():
        if "page size of" in line:
            page = int(line.split("page size of")[1].split()[0])
        elif ":" in line:
            k, v = line.split(":", 1)
            digits = "".join(c for c in v if c.isdigit())
            if digits:
                pages[k.strip()] = int(digits)
    # free + inactive + speculative is what the OS can hand out without swapping (matches psutil's `available`)
    return page * (pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0))


def available_memory_bytes() -> int:
    """Memory the OS can give a new process right now (psutil, else vm_stat on macOS, /proc/meminfo on Linux)."""
    if psutil is not None:
        return int(psutil.virtual_memory().available)
    if sys.platform == "darwin":
        return _vm_stat_available()
    return _meminfo_kb("MemAvailable") * 1024


def default_floor_bytes() -> int:
    """System-floor default for a guarded command: min(24 GB, 20% of RAM)."""
    return int(min(24 * GB, 0.20 * total_memory_bytes()))


# ----------------------------------------------------------------------------------------- process tables

def process_table() -> list:
    """[{pid, ppid, pgid, rss}] (rss in bytes) for every process: psutil if available, else `ps`."""
    rows = []
    if psutil is not None:
        for p in psutil.process_iter(["pid", "ppid", "memory_info"]):
            try:
                mi = p.info["memory_info"]
                if mi is None:
                    continue
                rows.append({"pid": p.info["pid"], "ppid": p.info["ppid"], "pgid": os.getpgid(p.info["pid"]), "rss": int(mi.rss)})
            except (psutil.Error, ProcessLookupError, PermissionError, OSError):
                continue
        return rows
    out = subprocess.run(["ps", "-Ao", "pid=,ppid=,pgid=,rss="], capture_output=True, text=True, check=False).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and all(x.lstrip("-").isdigit() for x in parts):
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "pgid": int(parts[2]), "rss": int(parts[3]) * 1024})
    return rows


def tree_members(table: list, root_pid: int, pgid: int | None = None) -> list:
    """Rows of the process group ``pgid`` plus every descendant of ``root_pid`` (catches setsid'ed grandchildren)."""
    by_parent = {}
    for r in table:
        by_parent.setdefault(r["ppid"], []).append(r)
    want, stack = {}, [root_pid]
    while stack:
        pid = stack.pop()
        for child in by_parent.get(pid, []):
            if child["pid"] not in want:
                want[child["pid"]] = child
                stack.append(child["pid"])
    for r in table:
        if r["pid"] == root_pid or (pgid is not None and r["pgid"] == pgid):
            want[r["pid"]] = r
    return list(want.values())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie is dead for our purposes
    if psutil is not None:
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False
    return True


def kill_pids(pids, pgid: int | None = None, *, grace_s: float = KILL_GRACE_S, sleep=time.sleep, now=time.monotonic) -> list:
    """SIGTERM every pid (and the group), then SIGKILL survivors after ``grace_s``. Never touches our own group."""
    pids = [p for p in dict.fromkeys(pids) if p and p != os.getpid()]
    own = os.getpgrp()

    def send(sig):
        if pgid and pgid != own and pgid > 1:
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        for p in pids:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
    send(signal.SIGTERM)
    deadline = now() + grace_s
    while now() < deadline and any(_alive(p) for p in pids):
        sleep(0.05)
    if any(_alive(p) for p in pids):
        send(signal.SIGKILL)
    return pids


# ----------------------------------------------------------------------------------------- environment

def resource_env(cap_gb: float, base=None) -> dict:
    """Environment with the resource limits language runtimes honour (same for every caller, so no bias)."""
    env = dict(os.environ if base is None else base)
    mib = max(256, int(cap_gb * 1024))
    env["GOMEMLIMIT"] = f"{mib}MiB"
    flags = env.get("GOFLAGS", "")
    if "-p=" not in flags:
        env["GOFLAGS"] = (flags + " -p=2").strip()
    env["CARGO_BUILD_JOBS"] = "2"
    opts = env.get("NODE_OPTIONS", "")
    if "--max-old-space-size" not in opts:
        env["NODE_OPTIONS"] = (opts + f" --max-old-space-size={mib}").strip()
    return env


def _rlimit_wrap(argv: list, cap_gb: float) -> list:
    """Linux only: exec through a tiny python that sets RLIMIT_AS (deliberately loose: Go and V8 reserve large
    virtual ranges) and RLIMIT_CORE=0. macOS does not honour RLIMIT_AS/DATA, so nothing is wrapped there."""
    lim = int(max(cap_gb * 8, 32) * GB)
    code = ("import os,resource,sys\nl=int(sys.argv[1])\nresource.setrlimit(resource.RLIMIT_AS,(l,l))\n"
            "resource.setrlimit(resource.RLIMIT_CORE,(0,0))\nos.execvp(sys.argv[2],sys.argv[2:])")
    return [sys.executable, "-c", code, str(lim), *argv]


# ----------------------------------------------------------------------------------------- the guard

def run_guarded(argv, *, cap_gb: float = DEFAULT_CAP_GB, timeout_s: float = DEFAULT_TIMEOUT_S, cwd=None, env=None,
                floor_bytes: int | None = None, capture: bool = True, shell: bool = False, input_text: str | None = None,
                poll_s: float = POLL_S, grace_s: float = KILL_GRACE_S, rlimit: bool = True) -> GuardResult:
    cap = int(cap_gb * GB)
    floor = default_floor_bytes() if floor_bytes is None else int(floor_bytes)
    child_env = resource_env(cap_gb, env)
    cmd = argv
    if shell:
        cmd = ["/bin/sh", "-c", argv if isinstance(argv, str) else " ".join(argv)]
    cmd = list(cmd)
    if rlimit and sys.platform.startswith("linux"):
        cmd = _rlimit_wrap(cmd, cap_gb)
    out_f = tempfile.TemporaryFile() if capture else None
    err_f = tempfile.TemporaryFile() if capture else None
    in_f = None
    if input_text is not None:
        in_f = tempfile.TemporaryFile()
        in_f.write(input_text.encode())
        in_f.seek(0)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=child_env, stdout=out_f, stderr=err_f, stdin=in_f if in_f else subprocess.DEVNULL,
                                start_new_session=True)
    except BaseException:
        for f in (out_f, err_f, in_f):
            if f is not None:
                f.close()
        raise
    if in_f is not None:
        in_f.close()
    pgid, res, seen, tick = proc.pid, GuardResult(), {proc.pid}, 0
    try:
        while proc.poll() is None:
            time.sleep(poll_s)
            tick += 1
            members = tree_members(process_table(), proc.pid, pgid)
            seen.update(m["pid"] for m in members)
            rss = sum(m["rss"] for m in members)
            res.peak_rss_gb = max(res.peak_rss_gb, rss / GB)
            reason = None
            if rss > cap:
                reason = "memory"
            elif time.monotonic() - started > timeout_s:
                reason = "timeout"
            elif tick % 2 == 0 and available_memory_bytes() < floor:
                reason = "system_floor"
            if reason:
                res.killed = reason
                res.killed_pids = kill_pids(list(seen), pgid, grace_s=grace_s)
                break
    finally:
        if proc.poll() is None:
            kill_pids(list(seen), pgid, grace_s=grace_s)
        # stragglers that outlived the leader (e.g. leader exited normally, grandchild still running) must not linger
        stragglers = [m["pid"] for m in tree_members(process_table(), proc.pid, pgid) if m["pid"] != proc.pid]
        if stragglers:
            kill_pids(stragglers, pgid, grace_s=grace_s)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL already sent
        proc.kill()
        proc.wait()
    res.returncode = proc.returncode
    res.wall_s = time.monotonic() - started
    if capture:
        for f, attr in ((out_f, "stdout"), (err_f, "stderr")):
            f.seek(0)
            setattr(res, attr, f.read())
            f.close()
    return res


_SEM: threading.BoundedSemaphore | None = None
_SEM_LOCK = threading.Lock()


def _semaphore() -> threading.BoundedSemaphore:
    """Process-wide bound on concurrent guarded runs (validators use thread pools): default 3."""
    global _SEM
    with _SEM_LOCK:
        if _SEM is None:
            _SEM = threading.BoundedSemaphore(max(1, int(os.environ.get(ENV_CONCURRENCY, "3"))))
        return _SEM


def run(args, *, cwd=None, env=None, timeout=None, capture_output=True, text=True, shell=False, input=None,
        cap_gb: float | None = None, floor_bytes: int | None = None, check: bool = False) -> subprocess.CompletedProcess:
    """Drop-in for ``subprocess.run`` for scenario code. Raises ``subprocess.TimeoutExpired`` on timeout and
    ``ResourceLimit`` on a memory / system-floor kill. ``cap_gb`` and the timeout default from the environment
    (PAIRED_GRADER_CAP_GB=4, PAIRED_GRADER_TIMEOUT_S=300); an explicit ``timeout`` wins."""
    cap = float(os.environ.get(ENV_CAP, DEFAULT_CAP_GB)) if cap_gb is None else cap_gb
    tmo = float(timeout) if timeout is not None else float(os.environ.get(ENV_TIMEOUT, DEFAULT_TIMEOUT_S))
    with _semaphore():
        g = run_guarded(args, cap_gb=cap, timeout_s=tmo, cwd=cwd, env=env, floor_bytes=floor_bytes, capture=capture_output,
                        shell=shell, input_text=input)
    out, err = g.stdout, g.stderr
    if text and capture_output:
        out, err = (out or b"").decode(errors="replace"), (err or b"").decode(errors="replace")
    if g.killed == "timeout":
        raise subprocess.TimeoutExpired(args, tmo, output=out, stderr=err)
    if g.killed in ("memory", "system_floor"):
        raise ResourceLimit(g)
    cp = subprocess.CompletedProcess(args, g.returncode, out, err)
    cp.guard = g  # type: ignore[attr-defined]
    if check:
        cp.check_returncode()
    return cp


# ----------------------------------------------------------------------------------------- CLI

def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cap-gb", type=float, default=DEFAULT_CAP_GB)
    r.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    r.add_argument("--cwd")
    r.add_argument("--floor-gb", type=float, help="system-available floor (default min(24, 20%% of RAM))")
    r.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    cmd = a.command[1:] if a.command and a.command[0] == "--" else a.command
    if not cmd:
        ap.error("no command given (use: run ... -- cmd args)")
    g = run_guarded(cmd, cap_gb=a.cap_gb, timeout_s=a.timeout, cwd=a.cwd, capture=False,
                    floor_bytes=None if a.floor_gb is None else int(a.floor_gb * GB))
    sys.stdout.flush()
    print(json.dumps(g.summary()), flush=True)
    if g.killed == "timeout":
        return 124
    if g.killed:
        return 137
    return g.returncode if g.returncode is not None and g.returncode >= 0 else 128 + abs(g.returncode or 0)


if __name__ == "__main__":
    sys.exit(_cli())
