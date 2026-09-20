"""Aider polyglot-benchmark task adapter -- exposes the same contract shape as
`battery_tasks` (see that module for the `Task` dataclass) so a runner can
dispatch to either battery in the future.

Source corpus: https://github.com/Aider-AI/polyglot-benchmark (fetched via
`scripts/fetch_polyglot.py`). Each exercise directory under
`<lang>/exercises/practice/<slug>/` becomes one `Task` named
`poly_<lang>_<slug>`.

Notes on fields borrowed from `battery_tasks.Task`:
  - `family` is `poly_<lang>` (e.g. `poly_python`).
  - `split` is always set to `"dev"` at load time -- polyglot tasks don't
    have a fixed dev/holdout assignment baked into the corpus the way the
    20-task battery does. Use `select_slice()` to produce a deterministic
    dev/holdout partition of a chosen slice; don't rely on `Task.split` for
    polyglot tasks.
  - `kind` is always `"code"`.
  - `expected_answer` is always `None` (no answer-only polyglot tasks).
  - `protected` is the shipped test file(s) for the exercise (from
    `.meta/config.json`'s `files.test`); the agent must not edit them.
  - `files` contains every file in the exercise directory except the whole
    `.meta/` tree (which holds the reference solution and generator
    metadata -- never shipped to the agent) and any path listed under
    `.meta/config.json`'s `files.example` (the reference/example solution,
    which for this corpus always happens to live under `.meta/` anyway, but
    is excluded explicitly in case a future exercise ships it elsewhere).

All candidate code is executed out-of-process (subprocess, bounded timeout).
Stdlib only.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battery_tasks as bt  # noqa: E402  (Task dataclass + PROMPT_SUFFIX contract)

TIMEOUT = 120

LANGUAGES: tuple[str, ...] = ("python", "javascript", "rust", "go", "cpp", "java")


# ---------------------------------------------------------------------------
# Toolchain probing
# ---------------------------------------------------------------------------


def toolchains() -> dict[str, bool]:
    """Probe for the binaries needed to evaluate each supported language."""
    binaries = {
        "python3": "python3",
        "node": "node",
        "cargo": "cargo",
        "go": "go",
        "javac": "javac",
        "cmake": "cmake",
    }
    return {name: shutil.which(binary) is not None for name, binary in binaries.items()}


def find_junit_console_jar(root: Path) -> Path | None:
    """Look for a bundled JUnit Platform Console Standalone jar under `root`.

    The polyglot-benchmark corpus does not ship one (Java exercises assume a
    Gradle + Maven Central toolchain), so this normally returns None and
    Java exercises are excluded from `load()`. If a jar is ever vendored
    into the corpus (or the caller's data dir) under this name pattern, it
    will be picked up automatically.
    """
    root = Path(root)
    if not root.is_dir():
        return None
    for candidate in root.rglob("*junit-platform-console-standalone*.jar"):
        return candidate
    return None


# ---------------------------------------------------------------------------
# Pure helpers used both by evaluate() and directly by tests
# ---------------------------------------------------------------------------


def unskip_js_test_source(source: str) -> str:
    """Un-skip Jest tests written with Exercism's `xtest`/`xit` convention.

    Aider's harness does the same textual substitution before running the
    JS test suite so that skipped ("extra credit") cases are exercised too.
    """
    source = re.sub(r"\bxtest\(", "test(", source)
    source = re.sub(r"\bxit\(", "it(", source)
    return source


def strip_rust_ignore(source: str) -> str:
    """Remove `#[ignore]` attribute lines so all Rust tests run.

    Aider un-ignores tests the same way (textually, in a temp copy) rather
    than editing the protected test file that ships to the candidate.
    """
    lines = source.splitlines(keepends=True)
    return "".join(line for line in lines if line.strip() != "#[ignore]")


def _toolchain_missing(tool: str) -> dict:
    return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [f"toolchain_missing:{tool}"]}


def _timeout_result() -> dict:
    return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["timeout"]}


# ---------------------------------------------------------------------------
# Per-language evaluate() runners. Each takes (exercise_root, test_files) and
# returns {"checks", "passed", "failed", "failure_labels"}. Called on a
# private temp copy of the exercise, never on the candidate's real
# workspace, and candidate code is always exercised via subprocess.
# ---------------------------------------------------------------------------


def _parse_pytest_output(text: str) -> dict:
    m_passed = re.search(r"(\d+) passed", text)
    m_failed = re.search(r"(\d+) failed", text)
    m_error = re.search(r"(\d+) error", text)
    passed = int(m_passed.group(1)) if m_passed else 0
    failed = int(m_failed.group(1)) if m_failed else 0
    failed += int(m_error.group(1)) if m_error else 0
    checks = passed + failed
    if checks == 0:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["no_tests_collected"]}
    labels = [] if failed == 0 else ["pytest_failures"]
    return {"checks": checks, "passed": passed, "failed": failed, "failure_labels": labels}


def _python_run(exercise_root: Path, test_files: list[str]) -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *test_files],
            cwd=str(exercise_root),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        )
    except FileNotFoundError:
        return _toolchain_missing("python3")
    except subprocess.TimeoutExpired:
        return _timeout_result()
    return _parse_pytest_output(proc.stdout + "\n" + proc.stderr)


def _parse_cargo_output(text: str) -> dict:
    matches = re.findall(r"(\d+) passed; (\d+) failed;", text)
    if not matches:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["compile_error"]}
    passed = sum(int(p) for p, _ in matches)
    failed = sum(int(f) for _, f in matches)
    checks = passed + failed
    labels = [] if failed == 0 else ["cargo_test_failures"]
    return {"checks": checks, "passed": passed, "failed": failed, "failure_labels": labels}


def _rust_run(exercise_root: Path, test_files: list[str]) -> dict:
    for rel in test_files:
        path = exercise_root / rel
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        path.write_text(strip_rust_ignore(src), encoding="utf-8")
    try:
        proc = subprocess.run(
            ["cargo", "test", "--offline", "--quiet"],
            cwd=str(exercise_root),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return _toolchain_missing("cargo")
    except subprocess.TimeoutExpired:
        return _timeout_result()
    return _parse_cargo_output(proc.stdout + "\n" + proc.stderr)


def _parse_go_json_output(stdout: str) -> dict:
    names_actions: dict[str, str] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("Action") in ("pass", "fail") and event.get("Test"):
            names_actions[event["Test"]] = event["Action"]
    all_names = set(names_actions)
    # Keep only leaf tests: a name that is a strict subtest prefix of another
    # recorded name is an aggregate roll-up, not an independent check.
    leaf = [n for n in all_names if not any(other.startswith(n + "/") for other in all_names)]
    passed = sum(1 for n in leaf if names_actions[n] == "pass")
    failed = sum(1 for n in leaf if names_actions[n] == "fail")
    checks = passed + failed
    if checks == 0:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["build_failed"]}
    labels = [] if failed == 0 else ["go_test_failures"]
    return {"checks": checks, "passed": passed, "failed": failed, "failure_labels": labels}


def _go_run(exercise_root: Path, test_files: list[str]) -> dict:
    try:
        proc = subprocess.run(
            ["go", "test", "-json", "./..."],
            cwd=str(exercise_root),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return _toolchain_missing("go")
    except subprocess.TimeoutExpired:
        return _timeout_result()
    return _parse_go_json_output(proc.stdout)


_CATCH2_SUMMARY_RE = re.compile(r"assertions:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed")
_CATCH2_ALL_PASSED_RE = re.compile(r"All tests passed \((\d+) assertions? in \d+ test cases?\)")


def _parse_catch2_output(text: str) -> dict:
    m = _CATCH2_SUMMARY_RE.search(text)
    if m:
        checks, passed, failed = int(m.group(1)), int(m.group(2)), int(m.group(3))
        labels = [] if failed == 0 else ["catch2_failures"]
        return {"checks": checks, "passed": passed, "failed": failed, "failure_labels": labels}
    m2 = _CATCH2_ALL_PASSED_RE.search(text)
    if m2:
        n = int(m2.group(1))
        return {"checks": n, "passed": n, "failed": 0, "failure_labels": []}
    return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["compile_error"]}


def _cpp_run(exercise_root: Path, test_files: list[str]) -> dict:
    if not (exercise_root / "CMakeLists.txt").is_file():
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["unsupported:no_cmakelists"]}
    build_dir = exercise_root / "build"
    try:
        cfg = subprocess.run(
            ["cmake", "-S", str(exercise_root), "-B", str(build_dir), "-DEXERCISM_RUN_ALL_TESTS=1"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return _toolchain_missing("cmake")
    except subprocess.TimeoutExpired:
        return _timeout_result()
    if cfg.returncode != 0:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["cmake_configure_error"]}
    try:
        build = subprocess.run(
            ["cmake", "--build", str(build_dir)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return _timeout_result()
    text = cfg.stdout + cfg.stderr + build.stdout + build.stderr
    return _parse_catch2_output(text)


def _parse_jest_json(stdout: str, stderr: str) -> dict:
    try:
        data = json.loads(stdout)
    except ValueError:
        lowered = stderr.lower()
        if "not found" in lowered or "could not determine executable" in lowered or "npm error" in lowered:
            return _toolchain_missing("jest")
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["jest_output_unparseable"]}
    passed = data.get("numPassedTests", 0)
    failed = data.get("numFailedTests", 0)
    checks = passed + failed
    if checks == 0:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["no_tests_collected"]}
    labels = [] if failed == 0 else ["jest_failures"]
    return {"checks": checks, "passed": passed, "failed": failed, "failure_labels": labels}


def _parse_node_test_output(text: str) -> dict:
    m_pass = re.search(r"# pass (\d+)", text)
    m_fail = re.search(r"# fail (\d+)", text)
    if not (m_pass or m_fail):
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["node_test_output_unparseable"]}
    passed = int(m_pass.group(1)) if m_pass else 0
    failed = int(m_fail.group(1)) if m_fail else 0
    checks = passed + failed
    labels = [] if failed == 0 else ["node_test_failures"]
    return {"checks": checks, "passed": passed, "failed": failed, "failure_labels": labels}


def _js_uses_jest(exercise_root: Path) -> bool:
    pkg = exercise_root / "package.json"
    if not pkg.is_file():
        return False
    try:
        cfg = json.loads(pkg.read_text(encoding="utf-8"))
    except ValueError:
        return False
    deps = {**cfg.get("dependencies", {}), **cfg.get("devDependencies", {})}
    return "jest" in deps


def _js_run(exercise_root: Path, test_files: list[str]) -> dict:
    for rel in test_files:
        path = exercise_root / rel
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        path.write_text(unskip_js_test_source(src), encoding="utf-8")

    if _js_uses_jest(exercise_root):
        try:
            proc = subprocess.run(
                ["npx", "--no-install", "jest", "--ci", "--json", *test_files],
                cwd=str(exercise_root),
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
        except FileNotFoundError:
            return _toolchain_missing("node")
        except subprocess.TimeoutExpired:
            return _timeout_result()
        return _parse_jest_json(proc.stdout, proc.stderr)

    try:
        proc = subprocess.run(
            ["node", "--test", *test_files],
            cwd=str(exercise_root),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return _toolchain_missing("node")
    except subprocess.TimeoutExpired:
        return _timeout_result()
    return _parse_node_test_output(proc.stdout + "\n" + proc.stderr)


_RUNNERS: dict[str, Callable[[Path, list[str]], dict]] = {
    "python": _python_run,
    "javascript": _js_run,
    "rust": _rust_run,
    "go": _go_run,
    "cpp": _cpp_run,
}


def _check_protected(workspace: Path, test_files: list[str], protected_originals: dict[str, str]) -> list[str]:
    labels: list[str] = []
    for rel in test_files:
        original = protected_originals.get(rel)
        if original is None:
            continue
        actual_path = workspace / rel
        try:
            actual = actual_path.read_text(encoding="utf-8")
        except OSError:
            labels.append(f"protected_missing:{rel}")
            continue
        if actual != original:
            labels.append(f"protected_modified:{rel}")
    return labels


# Never copy VCS metadata or build/dependency output into the evaluator's temp
# copy: `.git` can contain non-regular files (e.g. a Watchman/fsmonitor unix
# socket) that `shutil.copytree` cannot copy, and the others are pure waste.
_COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "node_modules", "target", "build")


def _make_polyglot_evaluate(
    lang: str,
    slug: str,
    test_files: list[str],
    protected_originals: dict[str, str],
) -> Callable[[Path], dict]:
    runner = _RUNNERS.get(lang)

    def _evaluate(workspace: Path) -> dict:
        protected_labels = _check_protected(workspace, test_files, protected_originals)

        if runner is None:
            result = {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [f"unsupported:{lang}"]}
        else:
            tmp_root = Path(tempfile.mkdtemp(prefix="polyglot_eval_"))
            try:
                # Some toolchains (CMake/Cargo/Go) derive the exercise/package
                # name from the containing directory name, so the temp copy
                # must be named after the exercise slug, not a generic name.
                tmp_exercise = tmp_root / slug
                try:
                    shutil.copytree(workspace, tmp_exercise, ignore=_COPY_IGNORE)
                except OSError:
                    result = {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["evaluator_copy_error"]}
                else:
                    result = runner(tmp_exercise, test_files)
            except Exception as e:  # pragma: no cover - defensive, never crash
                result = {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [f"harness_error:{e}"]}
            finally:
                shutil.rmtree(tmp_root, ignore_errors=True)

        if protected_labels:
            result = {
                "checks": result["checks"] + len(protected_labels),
                "passed": result["passed"],
                "failed": result["failed"] + len(protected_labels),
                "failure_labels": result["failure_labels"] + protected_labels,
            }
        return result

    return _evaluate


# ---------------------------------------------------------------------------
# Task assembly from an on-disk polyglot-benchmark checkout
# ---------------------------------------------------------------------------


def _collect_files(ex_dir: Path, example_paths: set[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(ex_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ex_dir).as_posix()
        if rel == ".meta" or rel.startswith(".meta/"):
            continue
        if rel in example_paths:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files[rel] = content
    return files


def _build_prompt(ex_dir: Path, solution_files: list[str]) -> str:
    parts: list[str] = []
    intro_path = ex_dir / ".docs" / "introduction.md"
    instr_path = ex_dir / ".docs" / "instructions.md"
    if intro_path.is_file():
        parts.append(intro_path.read_text(encoding="utf-8").strip())
    if instr_path.is_file():
        parts.append(instr_path.read_text(encoding="utf-8").strip())
    instructions = "\n\n".join(p for p in parts if p)

    prompt_body = (
        f"{instructions}\n\nUse the above instructions to modify the supplied files: "
        f"{', '.join(solution_files)}. Keep and implement the existing function or "
        "class stubs, they will be called from unit tests. Only use standard "
        "libraries, don't suggest installing any packages."
    )
    return prompt_body + bt.PROMPT_SUFFIX


def _build_task(lang: str, ex_dir: Path) -> bt.Task | None:
    config_path = ex_dir / ".meta" / "config.json"
    if not config_path.is_file():
        return None
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except ValueError:
        return None

    files_cfg = cfg.get("files", {})
    solution_files = list(files_cfg.get("solution", []))
    test_files = list(files_cfg.get("test", []))
    example_files = set(files_cfg.get("example", []))
    if not solution_files or not test_files:
        return None

    if lang == "cpp" and not (ex_dir / "CMakeLists.txt").is_file():
        return None

    files = _collect_files(ex_dir, example_files)
    if any(p not in files for p in (*solution_files, *test_files)):
        return None

    protected_originals = {p: files[p] for p in test_files}
    evaluate = _make_polyglot_evaluate(lang, ex_dir.name, test_files, protected_originals)

    return bt.Task(
        name=f"poly_{lang}_{ex_dir.name}",
        family=f"poly_{lang}",
        split="dev",
        kind="code",
        prompt=_build_prompt(ex_dir, solution_files),
        files=files,
        protected=tuple(test_files),
        expected_answer=None,
        evaluate=evaluate,
    )


def load(root: str | Path, languages: list[str] | None = None) -> dict[str, bt.Task]:
    """Load every eligible exercise under `root` (a polyglot-benchmark
    checkout, i.e. the directory containing `python/`, `javascript/`, ...)
    into `Task`s keyed by `poly_<lang>_<slug>`.

    Java exercises are skipped unless a bundled JUnit console-standalone jar
    is found under `root` (none ships with the corpus today). A C++
    exercise is skipped if it lacks a `CMakeLists.txt`.
    """
    root = Path(root).expanduser()
    langs = list(languages) if languages else list(LANGUAGES)
    junit_jar = find_junit_console_jar(root)

    tasks: dict[str, bt.Task] = {}
    for lang in langs:
        if lang == "java" and junit_jar is None:
            continue
        practice = root / lang / "exercises" / "practice"
        if not practice.is_dir():
            continue
        for ex_dir in sorted(p for p in practice.iterdir() if p.is_dir()):
            task = _build_task(lang, ex_dir)
            if task is not None:
                tasks[task.name] = task
    return tasks


# ---------------------------------------------------------------------------
# Deterministic stratified slicing
# ---------------------------------------------------------------------------


def _family_language(family: str) -> str:
    return family[len("poly_"):] if family.startswith("poly_") else family


def select_slice(
    tasks: dict[str, bt.Task],
    n: int,
    seed: int,
    languages: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Deterministically sample up to `n` task names, stratified evenly
    across languages, then split 60/40 into (dev, holdout).

    Both returned lists are sorted. Given the same `tasks`, `n`, `seed`, and
    `languages`, the result is always identical.
    """
    by_lang: dict[str, list[str]] = {}
    for name, task in tasks.items():
        lang = _family_language(task.family)
        if languages is not None and lang not in languages:
            continue
        by_lang.setdefault(lang, []).append(name)

    langs_sorted = sorted(by_lang)
    if not langs_sorted:
        return [], []
    for lang in langs_sorted:
        by_lang[lang].sort()

    rng = random.Random(seed)

    base = n // len(langs_sorted)
    remainder = n - base * len(langs_sorted)
    quotas = {lang: base + (1 if i < remainder else 0) for i, lang in enumerate(langs_sorted)}

    # Clamp to availability, then redistribute any leftover deterministically
    # (round-robin over languages with spare capacity, in sorted order).
    taken = {lang: min(quotas[lang], len(by_lang[lang])) for lang in langs_sorted}
    leftover = n - sum(taken.values())
    guard = sum(len(v) for v in by_lang.values()) + 1
    idx = 0
    while leftover > 0 and guard > 0:
        lang = langs_sorted[idx % len(langs_sorted)]
        if taken[lang] < len(by_lang[lang]):
            taken[lang] += 1
            leftover -= 1
        idx += 1
        guard -= 1

    dev_all: list[str] = []
    holdout_all: list[str] = []
    for lang in langs_sorted:
        k = taken[lang]
        candidates = by_lang[lang]
        chosen = rng.sample(candidates, k)
        rng.shuffle(chosen)
        dev_count = round(len(chosen) * 0.6)
        dev_all.extend(chosen[:dev_count])
        holdout_all.extend(chosen[dev_count:])

    return sorted(dev_all), sorted(holdout_all)
