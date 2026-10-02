"""memguard: cap / timeout / system-floor kills, grandchild accounting, passthrough, env, CLI. Children allocate at most
~1 GB (and are killed long before that); nothing here runs scenario code."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import memguard  # noqa: E402

PY = sys.executable
ALLOC = ("import time\nc=[]\nfor i in range(40):\n    c.append(b'a'*(25*2**20)); time.sleep(0.05)\ntime.sleep(20)\n")   # <= 1 GB, resident
GRANDCHILD = ("import subprocess,sys,time\n"
              "p=subprocess.Popen([sys.executable,'-c',%r],start_new_session=%s)\n"
              "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(20)\n")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    if memguard.psutil is not None:
        try:
            return memguard.psutil.Process(pid).status() != memguard.psutil.STATUS_ZOMBIE
        except memguard.psutil.Error:
            return False
    return True


class GuardTests(unittest.TestCase):
    def test_memory_cap_kills_the_child(self):
        g = memguard.run_guarded([PY, "-c", ALLOC], cap_gb=0.3, timeout_s=30, floor_bytes=0)
        self.assertEqual(g.killed, "memory")
        self.assertGreater(g.peak_rss_gb, 0.3)
        self.assertLess(g.peak_rss_gb, 1.0)
        self.assertLess(g.wall_s, 10)
        self.assertNotEqual(g.returncode, 0)

    def test_timeout_kills_the_child(self):
        g = memguard.run_guarded([PY, "-c", "import time; time.sleep(30)"], cap_gb=1, timeout_s=1.0, floor_bytes=0)
        self.assertEqual(g.killed, "timeout")
        self.assertLess(g.wall_s, 6)

    def test_normal_exit_passes_through_output_and_code(self):
        g = memguard.run_guarded([PY, "-c", "import sys;print('hi');sys.stderr.write('err');sys.exit(3)"], cap_gb=1, timeout_s=20, floor_bytes=0)
        self.assertEqual((g.killed, g.returncode), (None, 3))
        self.assertEqual((g.stdout.strip(), g.stderr.strip()), (b"hi", b"err"))
        self.assertLess(g.peak_rss_gb, 0.5)

    def test_system_floor_kills_the_child(self):
        with patch.object(memguard, "available_memory_bytes", lambda: 1 * memguard.GB):
            g = memguard.run_guarded([PY, "-c", "import time; time.sleep(30)"], cap_gb=1, timeout_s=30, floor_bytes=2 * memguard.GB)
        self.assertEqual(g.killed, "system_floor")
        self.assertLess(g.wall_s, 6)

    def test_grandchild_memory_is_counted_and_killed(self):
        with tempfile.TemporaryDirectory() as t:
            pidfile = Path(t) / "pid"
            g = memguard.run_guarded([PY, "-c", GRANDCHILD % (ALLOC, "False"), str(pidfile)], cap_gb=0.3, timeout_s=30, floor_bytes=0)
            self.assertEqual(g.killed, "memory")
            gpid = int(pidfile.read_text())
            time.sleep(0.3)
            self.assertFalse(alive(gpid), "grandchild survived the kill")

    def test_setsid_escaped_grandchild_is_counted_and_killed(self):
        with tempfile.TemporaryDirectory() as t:
            pidfile = Path(t) / "pid"
            g = memguard.run_guarded([PY, "-c", GRANDCHILD % (ALLOC, "True"), str(pidfile)], cap_gb=0.3, timeout_s=30, floor_bytes=0)
            self.assertEqual(g.killed, "memory")
            gpid = int(pidfile.read_text())
            time.sleep(0.3)
            self.assertFalse(alive(gpid), "setsid grandchild survived the kill")

    def test_leader_exiting_does_not_leave_a_straggler(self):
        with tempfile.TemporaryDirectory() as t:
            pidfile = Path(t) / "pid"
            code = ("import subprocess,sys\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
                    "open(sys.argv[1],'w').write(str(p.pid))\n")
            g = memguard.run_guarded([PY, "-c", code, str(pidfile)], cap_gb=1, timeout_s=20, floor_bytes=0)
            self.assertEqual(g.returncode, 0)
            time.sleep(0.3)
            self.assertFalse(alive(int(pidfile.read_text())))

    def test_ps_fallback_works_without_psutil(self):
        with patch.object(memguard, "psutil", None):
            g = memguard.run_guarded([PY, "-c", ALLOC], cap_gb=0.3, timeout_s=30, floor_bytes=0)
        self.assertEqual(g.killed, "memory")
        rows = None
        with patch.object(memguard, "psutil", None):
            rows = memguard.process_table()
        self.assertTrue(any(r["pid"] == os.getpid() and r["rss"] > 0 for r in rows))

    def test_vm_stat_fallback_parses_available_memory(self):
        fake = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free:      1000.\nPages inactive:   500.\n"
                "Pages speculative: 100.\nPages active: 99999.\n")
        with patch.object(memguard.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, fake, "")):
            self.assertEqual(memguard._vm_stat_available(), 16384 * 1600)


class LibraryTests(unittest.TestCase):
    def test_run_is_subprocess_run_compatible(self):
        cp = memguard.run([PY, "-c", "print('ok')"], timeout=20, cap_gb=1, floor_bytes=0)
        self.assertEqual((cp.returncode, cp.stdout.strip()), (0, "ok"))
        self.assertIsNone(cp.guard.killed)
        sh = memguard.run("echo $((1+2))", shell=True, timeout=20, cap_gb=1, floor_bytes=0)
        self.assertEqual(sh.stdout.strip(), "3")
        self.assertEqual(memguard.run([PY, "-c", "import sys;print(sys.stdin.read())"], input="piped", timeout=20, cap_gb=1, floor_bytes=0).stdout.strip(), "piped")

    def test_run_raises_resource_limit_and_timeout_expired(self):
        with self.assertRaises(memguard.ResourceLimit) as cm:
            memguard.run([PY, "-c", ALLOC], timeout=30, cap_gb=0.3, floor_bytes=0)
        self.assertEqual(cm.exception.guard.killed, "memory")
        with self.assertRaises(subprocess.TimeoutExpired):
            memguard.run([PY, "-c", "import time;time.sleep(30)"], timeout=1.0, cap_gb=1, floor_bytes=0)

    def test_missing_binary_raises_file_not_found_like_subprocess(self):
        with self.assertRaises(FileNotFoundError):
            memguard.run(["definitely-not-a-binary-xyz"], timeout=5, cap_gb=1, floor_bytes=0)

    def test_environment_defaults_cap_and_timeout(self):
        with patch.dict(os.environ, {memguard.ENV_CAP: "0.3", memguard.ENV_TIMEOUT: "30"}):
            with self.assertRaises(memguard.ResourceLimit):
                memguard.run([PY, "-c", ALLOC], floor_bytes=0)
        with patch.dict(os.environ, {memguard.ENV_TIMEOUT: "1"}):
            with self.assertRaises(subprocess.TimeoutExpired):
                memguard.run([PY, "-c", "import time;time.sleep(30)"], cap_gb=1, floor_bytes=0)
            # an explicit timeout wins over the environment default
            self.assertEqual(memguard.run([PY, "-c", "import time;time.sleep(1.6);print('x')"], timeout=20, cap_gb=1, floor_bytes=0).stdout.strip(), "x")

    def test_concurrency_is_bounded(self):
        import threading
        peak, cur, lock = [0], [0], threading.Lock()
        real = memguard.run_guarded

        def spy(*a, **k):
            with lock:
                cur[0] += 1
                peak[0] = max(peak[0], cur[0])
            try:
                return real(*a, **k)
            finally:
                with lock:
                    cur[0] -= 1
        with patch.object(memguard, "_SEM", None), patch.dict(os.environ, {memguard.ENV_CONCURRENCY: "2"}), patch.object(memguard, "run_guarded", spy):
            ts = [threading.Thread(target=lambda: memguard.run([PY, "-c", "import time;time.sleep(0.6)"], timeout=20, cap_gb=1, floor_bytes=0)) for _ in range(5)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertLessEqual(peak[0], 2)


class EnvTests(unittest.TestCase):
    def test_resource_env_sets_runtime_limits_and_merges_goflags(self):
        e = memguard.resource_env(4, {"GOFLAGS": "-mod=mod", "NODE_OPTIONS": "--no-warnings", "PATH": "/bin"})
        self.assertEqual((e["GOMEMLIMIT"], e["CARGO_BUILD_JOBS"]), ("4096MiB", "2"))
        self.assertEqual(e["GOFLAGS"], "-mod=mod -p=2")
        self.assertEqual(e["NODE_OPTIONS"], "--no-warnings --max-old-space-size=4096")
        self.assertEqual(memguard.resource_env(4, {"GOFLAGS": "-p=8"})["GOFLAGS"], "-p=8")      # an explicit -p wins
        self.assertEqual(memguard.resource_env(0.1, {})["GOMEMLIMIT"], "256MiB")

    def test_child_sees_the_limits(self):
        g = memguard.run_guarded([PY, "-c", "import os;print(os.environ['GOMEMLIMIT'],os.environ['GOFLAGS'],os.environ['CARGO_BUILD_JOBS'])"],
                                 cap_gb=2, timeout_s=20, floor_bytes=0, env={"PATH": os.environ["PATH"]})
        self.assertEqual(g.stdout.decode().split(), ["2048MiB", "-p=2", "2"])

    def test_linux_rlimit_wrapper_is_built_but_loose(self):
        argv = memguard._rlimit_wrap(["go", "test"], 4)
        self.assertEqual((argv[0], argv[1]), (sys.executable, "-c"))
        self.assertEqual(argv[-2:], ["go", "test"])
        self.assertGreaterEqual(int(argv[3]), 32 * memguard.GB)

    def test_default_floor_is_min_24gb_or_20_percent(self):
        with patch.object(memguard, "total_memory_bytes", lambda: 128 * memguard.GB):
            self.assertEqual(memguard.default_floor_bytes(), 24 * memguard.GB)
        with patch.object(memguard, "total_memory_bytes", lambda: 16 * memguard.GB):
            self.assertEqual(memguard.default_floor_bytes(), int(3.2 * memguard.GB))


class TableTests(unittest.TestCase):
    def test_tree_members_counts_group_and_descendants(self):
        t = [{"pid": 10, "ppid": 1, "pgid": 10, "rss": 1}, {"pid": 11, "ppid": 10, "pgid": 10, "rss": 2},
             {"pid": 12, "ppid": 11, "pgid": 12, "rss": 4},          # setsid grandchild: reached through ppid
             {"pid": 13, "ppid": 1, "pgid": 10, "rss": 8},           # reparented but still in the group
             {"pid": 99, "ppid": 1, "pgid": 99, "rss": 1000}]
        self.assertEqual(sorted(m["pid"] for m in memguard.tree_members(t, 10, 10)), [10, 11, 12, 13])


class CliTests(unittest.TestCase):
    def cli(self, *args):
        p = subprocess.run([PY, str(REPO / "scripts" / "memguard.py"), "run", *args], capture_output=True, text=True, timeout=60)
        return p.returncode, json.loads(p.stdout.strip().splitlines()[-1]), p.stdout

    def test_cli_memory_kill_exit_137_and_json_line(self):
        code, j, _ = self.cli("--cap-gb", "0.3", "--timeout", "30", "--floor-gb", "0", "--", PY, "-c", ALLOC)
        self.assertEqual((code, j["killed"]), (137, "memory"))
        self.assertGreater(j["peak_rss_gb"], 0.3)

    def test_cli_timeout_exit_124(self):
        code, j, _ = self.cli("--cap-gb", "1", "--timeout", "1", "--floor-gb", "0", "--", PY, "-c", "import time;time.sleep(30)")
        self.assertEqual((code, j["killed"]), (124, "timeout"))

    def test_cli_passthrough(self):
        code, j, out = self.cli("--cap-gb", "1", "--timeout", "20", "--floor-gb", "0", "--cwd", "/tmp", "--", PY, "-c", "import os,sys;print(os.getcwd());sys.exit(5)")
        self.assertEqual((code, j["killed"], j["returncode"]), (5, None, 5))
        self.assertIn("tmp", out.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
