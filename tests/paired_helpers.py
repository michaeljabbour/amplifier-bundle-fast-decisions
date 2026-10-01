"""Shared fakes for the paired-harness tests: synthetic events.jsonl, an in-memory launcher backend, a tiny
inline scenario. No test here touches a model, the network or Forge."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "evals", REPO_ROOT / "scripts", REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import paired  # noqa: E402
import paired_scenarios as ps  # noqa: E402

INLINE_SCENARIO = {
    "id": "tiny-demo", "task_type": "feature", "language": "python", "split": "pilot",
    "source": {"desc": "inline fixture"},
    "workspace": {"kind": "inline", "files": {"solution.py": "def f():\n    return 0\n", "test_public.py": "from solution import f\n\ndef test_f():\n    assert f() == 1\n"}},
    "protected": ["test_public.py"],
    "turns": [
        {"prompt": "Make test_public.py pass.", "checks": [{"kind": "tests", "runner": "cmd", "cmd": "python3 -m pytest -q -p no:cacheprovider test_public.py", "expect_regex": "passed"}]},
        {"prompt": "Explain the change.", "checks": [{"kind": "keyed_facts", "all": ["return"]}]},
        {"prompt": "Write NOTES.md with a Usage section.", "gap_before_s": 420,
         "checks": [{"kind": "doc_sections", "path": "NOTES.md", "headings": ["Usage"]}, {"kind": "file_regex", "path": "solution.py", "pattern": "return 1"}]},
    ],
}


def ts(sec: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(sec, timezone.utc).isoformat()


def usage_cost(model, uncached, read, write, output):
    return paired.recompute_cost(model, uncached, read, write, output)


def write_events(path: Path, requests: list, extra_events: list | None = None) -> None:
    """requests: dicts {t, model, uncached, read, write, output, [effort], [main=True], [dur=1.0]}."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, r in enumerate(requests):
        rid = f"req{i}"
        raw = {"tools": [{"name": "x"}]} if r.get("main", True) else {}
        if r.get("effort"):
            raw["output_config"] = {"effort": r["effort"]}
        lines.append({"ts": ts(r["t"]), "event": "llm:request", "request_id": rid,
                      "data": {"model": r["model"], "has_system": r.get("main", True), "raw": raw, "thinking_enabled": True}})
        cost = usage_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"])
        lines.append({"ts": ts(r["t"] + r.get("dur", 1.0)), "event": "llm:response", "request_id": rid, "duration_ms": r.get("dur", 1.0) * 1000,
                      "data": {"model": r["model"], "usage": {"input_tokens": r["uncached"] + r["read"], "cache_read_tokens": r["read"],
                                                              "cache_write_tokens": r["write"], "output_tokens": r["output"],
                                                              "cost_usd": str(cost)}}})
    for ev in extra_events or []:
        lines.append(ev)
    path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")


class FakeBackend:
    """Same interface as paired.ForgeBackend. Sessions 'run' in threads; a wave's sessions all block until every
    session of the wave has started (proves co-start), and in-flight concurrency is recorded."""

    def __init__(self, tmp: Path, specs, fail_first: set | None = None, always_fail: set | None = None, hold=0.0):
        self.tmp, self.specs = Path(tmp), specs
        self.fail_first, self.always_fail = fail_first or set(), always_fail or set()
        self.started, self.inflight, self.max_inflight, self.lock = [], 0, 0, threading.Lock()
        self.prepared, self.hold = [], hold
        self.wave_size, self.wave_started = {}, {}
        self.barriers = {}

    def run_dir(self, root, name):
        return Path(root) / name

    def workspace(self, root, name):
        return Path(root) / name / "workspace"

    def prepare_wave(self, ctx, root, sessions):
        root = Path(root)
        runs = {}
        for s in sessions:
            (root / s["key"] / "workspace").mkdir(parents=True)
            spec = ctx.specs[s["scenario"]]
            import hashlib
            runs[s["key"]] = {"prompt_sha256": hashlib.sha256(ps.TURN_SEPARATOR.join(ps.turn_prompts(spec)).encode()).hexdigest(),
                              "nonce": s.get("nonce")}
            s["model"] = s["model"] or "claude-sonnet-5"
            if s["kind"] == "sticky" and not s.get("cell"):
                raise AssertionError("sticky cell must be resolved before prepare")
        (root / "manifest.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")
        self.prepared.append((str(root), [dict(s) for s in sessions]))
        self.barriers[str(root)] = threading.Barrier(len(sessions), timeout=20)

    def start(self, root, name):
        with self.lock:
            self.started.append((str(root), name, time.time()))
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)

    def wait(self, root, name, timeout):
        try:
            self.barriers[str(root)].wait()          # every arm of the wave has started before any finishes
        finally:
            pass
        time.sleep(self.hold)
        attempt = int(Path(root).name.rsplit("-a", 1)[1])
        bad = name in self.always_fail or (name in self.fail_first and attempt == 1)
        self._write_result(Path(root), name, infra=bad)
        with self.lock:
            self.inflight -= 1
        return True

    def _write_result(self, root, name, infra):
        run = root / name
        res = {"name": name, "session_id": None if infra else "sid-" + name, "infrastructure_failure": infra,
               "outcome_passed": not infra, "turns": [], "source_expected": {"git_sha": "abc", "tree_sha256": "def"},
               "started_at": ts(1000.0)}
        (run / "result.json").write_text(json.dumps(res), encoding="utf-8")

    def status(self, root, name):
        return "done" if (Path(root) / name / "result.json").exists() else "missing"

    def result(self, root, name):
        p = Path(root) / name / "result.json"
        return json.loads(p.read_text()) if p.exists() else None

    def close(self, root, name):
        pass


def make_design(tmp: Path, scenario_dir: Path) -> dict:
    d = paired.load_design()
    d["scenario_dir"] = str(scenario_dir)
    d["snapshot_root"] = str(tmp / "snaps")
    d["campaign_root_base"] = str(tmp / "camp")
    return d


def write_inline_scenario(dirpath: Path, **over) -> Path:
    import yaml
    dirpath.mkdir(parents=True, exist_ok=True)
    doc = {**INLINE_SCENARIO, **over}
    (dirpath / f"{doc['id']}.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    return dirpath
