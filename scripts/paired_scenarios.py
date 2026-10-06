"""Scenario spec, loader and graders for the paired multi-turn measurement harness.

A scenario is one scripted multi-turn session: a frozen workspace, N fixed user turns (identical
for every arm, hashed before launch -- STUDY-DESIGN R1), optional per-turn gaps, and deterministic
per-turn checks that run out-of-process against a private copy of the workspace (R3).

File format: one YAML per scenario under ``evals/paired/scenarios/<set>/``.

Check kinds (each counts as ONE check; a turn passes when none failed):
  tests         run a test runner on a private copy: runner python|go|rust|cmd, files, restore
                (shipped test files restored from the frozen snapshot first, defeating tampering),
                hidden (names from the scenario's ``hidden_files`` overlaid at grade time),
                cmd/expect_regex for runner=cmd
  file_exists   path
  file_regex    path, pattern, min_count (default 1), absent (bool)
  keyed_facts   all: [regex], any: [regex] (min_any, default 1) against the turn's final message
  doc_sections  path, headings: [regex] -- each must match a markdown heading line
Protected files are byte-compared against the snapshot after every turn (auto-added check).

Stdlib + PyYAML. Network is touched only by ``materialize`` (git fetch / pip download), never by
grading.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import memguard  # noqa: E402

# Every grader / hidden-test run executes scenario code under memguard: 4 GB cap on the whole process tree, 300 s,
# system-memory floor. A memory kill is a FAILED CHECK labelled `resource_limit`, never an infrastructure failure.
# (2026-10-01: an unguarded `dominoes.test` used 120-470 GB and OOMed the machine four times.) Override with
# PAIRED_GRADER_CAP_GB / PAIRED_GRADER_TIMEOUT_S.
os.environ.setdefault(memguard.ENV_CAP, str(memguard.DEFAULT_CAP_GB))
os.environ.setdefault(memguard.ENV_TIMEOUT, str(int(memguard.DEFAULT_TIMEOUT_S)))

TASK_TYPES = ("feature", "bugfix", "review", "mixed", "knowledge", "docs", "explain")
SPLITS = ("train", "test", "pilot", "holdout")
CHECK_KINDS = ("tests", "file_exists", "file_regex", "keyed_facts", "doc_sections")
DEFAULT_GAP_S = 10
TURN_SEPARATOR = "\n\n=== NEXT TURN ===\n\n"
RULES_SUFFIX = (
    "\n\nRules: work only inside this directory; do not use the network; do not modify the "
    "provided test files. Do not delegate to other agents. When finished, print one final line "
    "starting with `DONE:` (code/doc changes) or `ANSWER:` (questions) followed by a one-line summary."
)
_TEXT_LIMIT = 400_000
_SNAP_IGNORE = ("__pycache__", ".git", "target", "node_modules", "build", ".pytest_cache", ".amplifier")


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    kind: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TurnSpec:
    prompt: str
    checks: tuple = ()
    gap_before_s: int = DEFAULT_GAP_S


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    source: dict
    task_type: str
    language: str
    split: str
    workspace: dict
    turns: tuple
    protected: tuple = ()
    hidden_files: dict = field(default_factory=dict)

    @property
    def gap_schedule(self):
        return [t.gap_before_s for t in self.turns]

    @property
    def n_long_gaps(self):
        return sum(1 for t in self.turns[1:] if t.gap_before_s >= 300)


def _require(cond, msg):
    if not cond:
        raise ScenarioError(msg)


def parse(doc: dict, origin: str = "<doc>") -> ScenarioSpec:
    _require(isinstance(doc, dict), f"{origin}: scenario must be a mapping")
    sid = doc.get("id")
    _require(isinstance(sid, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,28}", sid or ""),
             f"{origin}: bad id {sid!r} (lowercase/digits/_-, <=29 chars: path-length defect, STUDY-DESIGN 17.1)")
    _require(doc.get("task_type") in TASK_TYPES, f"{origin}: task_type must be one of {TASK_TYPES}")
    _require(doc.get("split") in SPLITS, f"{origin}: split must be one of {SPLITS}")
    _require(isinstance(doc.get("language"), str), f"{origin}: language required")
    src = doc.get("source")
    _require(isinstance(src, dict) and src.get("desc"), f"{origin}: source.desc required")
    ws = doc.get("workspace")
    _require(isinstance(ws, dict) and ws.get("kind") in ("git", "inline"), f"{origin}: workspace.kind git|inline")
    if ws["kind"] == "git":
        _require(re.fullmatch(r"[0-9a-f]{40}", str(ws.get("sha", ""))), f"{origin}: workspace.sha must be a full 40-hex sha (pin)")
        _require(ws.get("repo"), f"{origin}: workspace.repo required")
    else:
        _require(isinstance(ws.get("files"), dict) and ws["files"], f"{origin}: inline workspace needs files")
    default_gap = int(doc.get("default_gap_s", DEFAULT_GAP_S))
    turns_raw = doc.get("turns")
    min_turns = 1 if doc.get("preflight") is True else 2      # only the preflight smoke scenario may be one turn
    _require(isinstance(turns_raw, list) and len(turns_raw) >= min_turns, f"{origin}: need >={min_turns} turns")
    hidden = dict(doc.get("hidden_files") or {})
    turns = []
    for i, t in enumerate(turns_raw, start=1):
        _require(isinstance(t, dict) and isinstance(t.get("prompt"), str) and t["prompt"].strip(),
                 f"{origin}: turn {i} needs a prompt")
        checks = []
        for c in t.get("checks") or []:
            _require(isinstance(c, dict) and c.get("kind") in CHECK_KINDS, f"{origin}: turn {i}: bad check {c!r}")
            args = {k: v for k, v in c.items() if k != "kind"}
            if c["kind"] == "tests":
                _require(args.get("runner") in ("python", "go", "rust", "cmd"), f"{origin}: turn {i}: tests.runner")
                for h in args.get("hidden") or []:
                    _require(h in hidden, f"{origin}: turn {i}: hidden file {h!r} not declared in hidden_files")
            if c["kind"] in ("file_exists", "file_regex", "doc_sections"):
                _require(args.get("path"), f"{origin}: turn {i}: {c['kind']}.path required")
            if c["kind"] == "keyed_facts":
                _require(args.get("all") or args.get("any"), f"{origin}: turn {i}: keyed_facts needs all or any")
                for rx in list(args.get("all") or []) + list(args.get("any") or []):
                    re.compile(rx)
            if c["kind"] == "file_regex":
                re.compile(args["pattern"])
            checks.append(Check(c["kind"], args))
        gap = int(t.get("gap_before_s", 0 if i == 1 else default_gap))
        _require(gap >= 0, f"{origin}: turn {i}: negative gap")
        turns.append(TurnSpec(prompt=t["prompt"].strip(), checks=tuple(checks), gap_before_s=gap))
    return ScenarioSpec(id=sid, source=src, task_type=doc["task_type"], language=doc["language"], split=doc["split"],
                        workspace=ws, turns=tuple(turns), protected=tuple(doc.get("protected") or ()),
                        hidden_files=hidden)


def load_dir(directory) -> list:
    """All scenarios under ``directory`` (``*.yaml``) -- or under every directory of a list -- sorted by id.
    Duplicate ids are an error."""
    dirs = [Path(d).expanduser() for d in (directory if isinstance(directory, (list, tuple)) else [directory])]
    specs = []
    for d in dirs:
        _require(d.is_dir(), f"scenario dir not found: {d}")
        specs += [parse(yaml.safe_load(p.read_text(encoding="utf-8")), str(p)) for p in sorted(d.glob("*.yaml"))]
    ids = [s.id for s in specs]
    _require(len(ids) == len(set(ids)), f"duplicate scenario ids in {directory}")
    return sorted(specs, key=lambda s: s.id)


def turn_prompts(spec: ScenarioSpec) -> list:
    """The exact prompt string of each turn (R1: this is what is hashed and what is sent)."""
    return [t.prompt + RULES_SUFFIX for t in spec.turns]


def _strip_local(obj):
    """Drop machine-specific ``local_hint`` paths: they are a fetch speed-up, not part of a scenario's identity."""
    if isinstance(obj, dict):
        return {k: _strip_local(v) for k, v in obj.items() if k != "local_hint"}
    if isinstance(obj, list):
        return [_strip_local(v) for v in obj]
    return obj


def scenario_hash(spec: ScenarioSpec) -> str:
    body = {"id": spec.id, "workspace": _strip_local(spec.workspace), "protected": list(spec.protected),
            "prompts": turn_prompts(spec), "gaps": spec.gap_schedule,
            "checks": [[[c.kind, c.args] for c in t.checks] for t in spec.turns],
            "hidden": _strip_local(spec.hidden_files), "task_type": spec.task_type, "language": spec.language}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def prompt_hash(spec: ScenarioSpec) -> str:
    return hashlib.sha256(TURN_SEPARATOR.join(turn_prompts(spec)).encode()).hexdigest()


# --------------------------------------------------------------------------- snapshots

def _sh(cmd, cwd=None, timeout=600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise ScenarioError(f"{cmd[:3]} failed: {p.stderr.decode(errors='replace')[-400:]}")
    return p.stdout


def _has_commit(repo: Path, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha + "^{commit}"], capture_output=True).returncode == 0


def _git_source(repo_url, sha, local_hint, cache_root: Path) -> Path:
    """A local git dir containing ``sha``: ``local_hint`` if it has it, else a cached shallow fetch."""
    if local_hint:
        hint = Path(local_hint).expanduser()
        if hint.exists() and _has_commit(hint, sha):
            return hint
    cache = cache_root / "_repos" / hashlib.sha256(repo_url.encode()).hexdigest()[:12]
    if not cache.exists():
        cache.mkdir(parents=True)
        _sh(["git", "init", "-q", str(cache)])
    if not _has_commit(cache, sha):
        _sh(["git", "-C", str(cache), "fetch", "-q", "--depth", "1", repo_url, sha])
    return cache


def tree_hash(root: Path) -> str:
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob("*")) if p.is_file() and not any(x in p.parts for x in _SNAP_IGNORE)}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def snapshot_dir_for(spec: ScenarioSpec, snapshot_root) -> Path:
    return Path(snapshot_root).expanduser() / f"{spec.id}-{scenario_hash(spec)[:10]}"


def materialize(spec: ScenarioSpec, snapshot_root) -> Path:
    """Build (idempotently) the frozen snapshot ``<root>/<id>-<hash10>/{workspace,hidden,snapshot.json}``.

    Reproducible from the spec alone: git sources are fetched by pinned sha (``local_hint`` is only
    a speed-up), vendored packages by exact pip pin. A second call verifies the stored tree hash.
    """
    snap = snapshot_dir_for(spec, snapshot_root)
    meta_path = snap / "snapshot.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("tree_sha256") == tree_hash(snap / "workspace"):
            return snap
        raise ScenarioError(f"snapshot {snap} no longer matches its recorded tree hash (snapshots are frozen)")
    tmp = snap.with_name(snap.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    dst = tmp / "workspace"
    dst.mkdir(parents=True)
    (tmp / "hidden").mkdir()
    ws = spec.workspace
    if ws["kind"] == "inline":
        for rel, text in ws["files"].items():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            (dst / rel).write_text(text, encoding="utf-8")
    else:
        src = _git_source(ws["repo"], ws["sha"], ws.get("local_hint"), Path(snapshot_root).expanduser())
        sub = (ws.get("subdir") or "").strip("/")
        archive = subprocess.Popen(["git", "-C", str(src), "archive", ws["sha"]] + ([sub] if sub else []),
                                   stdout=subprocess.PIPE)
        strip = len(sub.split("/")) if sub else 0
        tar = subprocess.run(["tar", "-x", f"--strip-components={strip}", "-C", str(dst)], stdin=archive.stdout,
                             capture_output=True)
        archive.stdout.close()
        if archive.wait() != 0 or tar.returncode != 0:
            raise ScenarioError(f"git archive/tar failed for {spec.id}: {tar.stderr.decode(errors='replace')[-300:]}")
        for rel, text in (ws.get("add_files") or {}).items():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            (dst / rel).write_text(text, encoding="utf-8")
        for rel in ws.get("remove") or []:
            target = dst / rel
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        for pkg in ws.get("pip_vendor") or []:
            _sh([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--target", str(dst), pkg])
            for junk in list(dst.glob("*.dist-info")) + list(dst.rglob("__pycache__")):
                shutil.rmtree(junk, ignore_errors=True)
    for rel, body in spec.hidden_files.items():
        out = tmp / "hidden" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, dict) and "from_git" in body:
            g = body["from_git"]
            gsrc = _git_source(g["repo"], g["sha"], g.get("local_hint"), Path(snapshot_root).expanduser())
            out.write_bytes(_sh(["git", "-C", str(gsrc), "show", f"{g['sha']}:{g['path']}"]))
        else:
            out.write_text(str(body), encoding="utf-8")
    meta = {"scenario": spec.id, "scenario_hash": scenario_hash(spec), "tree_sha256": tree_hash(dst),
            "files": sum(1 for p in dst.rglob("*") if p.is_file())}
    (tmp / "snapshot.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    tmp.rename(snap)
    return snap


def workspace_stats(snapshot: Path) -> dict:
    files = [p for p in (Path(snapshot) / "workspace").rglob("*") if p.is_file()]
    return {"workspace_files": len(files), "workspace_bytes": sum(p.stat().st_size for p in files)}


def text_files(snapshot: Path) -> dict:
    """Text-decodable snapshot files {relpath: text} (Task.files / protected comparison)."""
    out, base = {}, Path(snapshot) / "workspace"
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.stat().st_size <= _TEXT_LIMIT and not any(x in p.parts for x in _SNAP_IGNORE):
            try:
                out[str(p.relative_to(base))] = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


# --------------------------------------------------------------------------- grading

def _result(passed, label=None):
    return {"checks": 1, "passed": 1 if passed else 0, "failed": 0 if passed else 1,
            "failure_labels": [] if passed else [label or "check_failed"]}


def _fold(parts):
    out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
    for q in parts:
        for k in ("checks", "passed", "failed"):
            out[k] += q[k]
        out["failure_labels"] += q["failure_labels"]
    return out


def _check_tests(args, workspace, snapshot):
    import polyglot_tasks  # per-language runners; candidate code only ever runs out-of-process
    with tempfile.TemporaryDirectory(prefix="paired-grade-") as tmp:
        root = Path(tmp) / "ws"
        shutil.copytree(workspace, root, ignore=shutil.ignore_patterns(*_SNAP_IGNORE))
        for rel in args.get("restore") or []:
            src = snapshot / "workspace" / rel
            if src.exists():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, root / rel)
        for rel in args.get("hidden") or []:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot / "hidden" / rel, root / rel)
        files, runner = list(args.get("files") or []), args["runner"]
        if runner == "python":
            q = polyglot_tasks._python_run(root, files)
        elif runner == "go":
            q = polyglot_tasks._go_run(root, files)
        elif runner == "rust":
            q = polyglot_tasks._rust_run(root, files)
        else:
            try:
                p = memguard.run(args["cmd"], shell=True, cwd=root, capture_output=True, text=True,
                                 timeout=min(float(args.get("timeout", memguard.DEFAULT_TIMEOUT_S)),
                                             float(os.environ.get(memguard.ENV_TIMEOUT, memguard.DEFAULT_TIMEOUT_S))),
                                 env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
            except subprocess.TimeoutExpired:
                return _result(False, "timeout")
            except memguard.ResourceLimit:
                return _result(False, "resource_limit")
            ok = p.returncode == 0 and (not args.get("expect_regex") or re.search(args["expect_regex"], p.stdout + p.stderr))
            return _result(bool(ok), "cmd_failed")
    return _result(q["failed"] == 0 and q["passed"] > 0, ",".join(q["failure_labels"]) or "tests_failed")


def _check_file_regex(args, workspace):
    path, absent = workspace / args["path"], bool(args.get("absent"))
    if not path.exists():
        return _result(absent, f"missing:{args['path']}")
    n = len(re.findall(args["pattern"], path.read_text(encoding="utf-8", errors="replace"), re.M))
    return _result((n == 0) if absent else (n >= int(args.get("min_count", 1))), f"regex:{args['path']}")


def _check_keyed_facts(args, message):
    text = message or ""
    miss = [rx for rx in args.get("all") or [] if not re.search(rx, text, re.I | re.S)]
    anys = args.get("any") or []
    hit = sum(1 for rx in anys if re.search(rx, text, re.I | re.S))
    return _result(not miss and (not anys or hit >= int(args.get("min_any", 1))), "keyed_facts_missing")


def _check_doc_sections(args, workspace):
    path = workspace / args["path"]
    if not path.exists():
        return _result(False, f"missing:{args['path']}")
    heads = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.lstrip().startswith("#")]
    return _result(all(any(re.search(h, ln, re.I) for ln in heads) for h in args["headings"]), "doc_sections_missing")


def protected_modified(spec, workspace, snapshot) -> list:
    bad = []
    for rel in spec.protected:
        src, dst = Path(snapshot) / "workspace" / rel, Path(workspace) / rel
        if not dst.exists() or not src.exists() or dst.read_bytes() != src.read_bytes():
            bad.append(rel)
    return bad


def grade_turn(spec: ScenarioSpec, turn_index: int, workspace, final_message, snapshot) -> dict:
    """Grade turn ``turn_index`` (1-based) against the workspace as it stands right after that turn.
    A crashing check is a failed check labelled ``evaluate_error`` (never silently dropped)."""
    workspace, snapshot = Path(workspace), Path(snapshot)
    parts = []
    if spec.protected:
        bad = protected_modified(spec, workspace, snapshot)
        parts.append(_result(not bad, "protected_modified:" + ",".join(bad)))
    for c in spec.turns[turn_index - 1].checks:
        try:
            if c.kind == "tests":
                parts.append(_check_tests(c.args, workspace, snapshot))
            elif c.kind == "file_exists":
                parts.append(_result((workspace / c.args["path"]).exists(), f"missing:{c.args['path']}"))
            elif c.kind == "file_regex":
                parts.append(_check_file_regex(c.args, workspace))
            elif c.kind == "keyed_facts":
                parts.append(_check_keyed_facts(c.args, final_message))
            elif c.kind == "doc_sections":
                parts.append(_check_doc_sections(c.args, workspace))
        except Exception as exc:  # noqa: BLE001
            parts.append(_result(False, f"evaluate_error:{type(exc).__name__}"))
    return _fold(parts) if parts else {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}


def load_task_source(scenario_dir, snapshot_root, ids=None) -> dict:
    """{id: battery_tasks.Task(kind='scenario', spec=(ScenarioSpec, snapshot_dir))} for
    forge_workloads.register_source('paired', ...)."""
    import battery_tasks as bt
    tasks = {}
    for spec in load_dir(scenario_dir):
        if ids is not None and spec.id not in ids:
            continue
        snap = snapshot_dir_for(spec, snapshot_root)
        if not (snap / "snapshot.json").exists():
            raise ScenarioError(f"snapshot for {spec.id} not built (run `paired.py plan`): {snap}")
        tasks[spec.id] = bt.Task(
            name=spec.id, family="paired", split=spec.split, kind="scenario",
            prompt=TURN_SEPARATOR.join(turn_prompts(spec)), files=text_files(snap),
            protected=tuple(spec.protected), expected_answer=None, evaluate=bt._scenario_evaluate_placeholder,
            subtasks=tuple(f"t{i}" for i in range(1, len(spec.turns) + 1)), spec=(spec, str(snap)))
    return tasks
