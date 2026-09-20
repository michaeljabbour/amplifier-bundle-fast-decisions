"""Tests for scripts/polyglot_tasks.py and scripts/fetch_polyglot.py.

No network access. Only the Python evaluate() path is exercised against a
real toolchain (pytest); javascript/rust are checked at the load()/helper
level only, since jest/cargo toolchain availability in CI is not
guaranteed and we must not touch the network.
"""
from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_polyglot as fp  # noqa: E402
import polyglot_tasks as pt  # noqa: E402
import battery_tasks as bt  # noqa: E402


# ---------------------------------------------------------------------------
# Fake polyglot-benchmark tree builder
# ---------------------------------------------------------------------------

_PY_INSTRUCTIONS = "Implement `add(a, b)` returning the sum of `a` and `b`.\n"

_PY_EXAMPLE = "def add(a, b):\n    return a + b\n"

_PY_STUB = "def add(a, b):\n    pass\n"

_PY_TEST = """import unittest
from add_numbers import add


class AddNumbersTest(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative(self):
        self.assertEqual(add(-1, -1), -2)

    def test_zero(self):
        self.assertEqual(add(0, 0), 0)
"""

_PY_CONFIG = {
    "files": {
        "solution": ["add_numbers.py"],
        "test": ["add_numbers_test.py"],
        "example": [".meta/example.py"],
    }
}

_JS_INSTRUCTIONS = "Implement `addNumbers(a, b)` returning the sum of `a` and `b`.\n"

_JS_EXAMPLE = "export const addNumbers = (a, b) => a + b;\n"

_JS_STUB = "export const addNumbers = (a, b) => {\n  throw new Error('Remove this statement and implement this function');\n};\n"

_JS_TEST = """import { addNumbers } from './add-numbers';

describe('addNumbers', () => {
  test('adds two positive numbers', () => {
    expect(addNumbers(2, 3)).toEqual(5);
  });

  xtest('adds with a skipped extra-credit case', () => {
    expect(addNumbers(0, 0)).toEqual(0);
  });
});
"""

_JS_CONFIG = {
    "files": {
        "solution": ["add-numbers.js"],
        "test": ["add-numbers.spec.js"],
        "example": [".meta/proof.ci.js"],
    }
}

_JS_PACKAGE_JSON = json.dumps({"name": "add-numbers", "devDependencies": {"jest": "^29.7.0"}})

_RS_INSTRUCTIONS = "Implement `add(a, b)` returning the sum of `a` and `b`.\n"

_RS_EXAMPLE = "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"

_RS_STUB = "pub fn add(_a: i32, _b: i32) -> i32 {\n    todo!()\n}\n"

_RS_TEST = """use add_numbers::add;

#[test]
fn adds_two_positive_numbers() {
    assert_eq!(add(2, 3), 5);
}

#[test]
#[ignore]
fn adds_with_a_skipped_extra_credit_case() {
    assert_eq!(add(0, 0), 0);
}
"""

_RS_CARGO_TOML = "[package]\nname = \"add-numbers\"\nversion = \"0.0.0\"\nedition = \"2021\"\n"

_RS_CONFIG = {
    "files": {
        "solution": ["src/lib.rs", "Cargo.toml"],
        "test": ["tests/add_numbers.rs"],
        "example": [".meta/example.rs"],
    }
}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_fake_tree(root: Path) -> None:
    # python
    py_ex = root / "python" / "exercises" / "practice" / "add-numbers"
    _write(py_ex / ".docs" / "instructions.md", _PY_INSTRUCTIONS)
    _write(py_ex / ".meta" / "config.json", json.dumps(_PY_CONFIG))
    _write(py_ex / ".meta" / "example.py", _PY_EXAMPLE)
    _write(py_ex / "add_numbers.py", _PY_STUB)
    _write(py_ex / "add_numbers_test.py", _PY_TEST)

    # javascript
    js_ex = root / "javascript" / "exercises" / "practice" / "add-numbers"
    _write(js_ex / ".docs" / "instructions.md", _JS_INSTRUCTIONS)
    _write(js_ex / ".meta" / "config.json", json.dumps(_JS_CONFIG))
    _write(js_ex / ".meta" / "proof.ci.js", _JS_EXAMPLE)
    _write(js_ex / "add-numbers.js", _JS_STUB)
    _write(js_ex / "add-numbers.spec.js", _JS_TEST)
    _write(js_ex / "package.json", _JS_PACKAGE_JSON)

    # rust
    rs_ex = root / "rust" / "exercises" / "practice" / "add-numbers"
    _write(rs_ex / ".docs" / "instructions.md", _RS_INSTRUCTIONS)
    _write(rs_ex / ".meta" / "config.json", json.dumps(_RS_CONFIG))
    _write(rs_ex / ".meta" / "example.rs", _RS_EXAMPLE)
    _write(rs_ex / "src" / "lib.rs", _RS_STUB)
    _write(rs_ex / "tests" / "add_numbers.rs", _RS_TEST)
    _write(rs_ex / "Cargo.toml", _RS_CARGO_TOML)


def _materialize(files: dict, extra: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    merged = dict(files)
    if extra:
        merged.update(extra)
    for name, content in merged.items():
        path = d / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return d


class FakeTreeTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        _build_fake_tree(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestLoadShape(FakeTreeTestCase):
    def test_loads_one_task_per_language(self):
        tasks = pt.load(self.root, languages=["python", "javascript", "rust"])
        self.assertEqual(
            set(tasks),
            {"poly_python_add-numbers", "poly_javascript_add-numbers", "poly_rust_add-numbers"},
        )

    def test_task_naming_and_family(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        self.assertEqual(t.name, "poly_python_add-numbers")
        self.assertEqual(t.family, "poly_python")
        self.assertEqual(t.kind, "code")
        self.assertIsNone(t.expected_answer)

    def test_prompt_contains_instructions_and_ends_with_suffix(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        self.assertIn("Implement `add(a, b)`", t.prompt)
        self.assertIn("add_numbers.py", t.prompt)
        self.assertTrue(t.prompt.endswith(bt.PROMPT_SUFFIX))

    def test_meta_excluded_and_example_excluded(self):
        tasks = pt.load(self.root, languages=["python", "javascript", "rust"])
        for name in ("poly_python_add-numbers", "poly_javascript_add-numbers", "poly_rust_add-numbers"):
            t = tasks[name]
            for rel in t.files:
                self.assertFalse(rel.startswith(".meta"), f"{name}: {rel} should be excluded")
            self.assertNotIn(".meta/example.py", t.files)
            self.assertNotIn(".meta/proof.ci.js", t.files)
            self.assertNotIn(".meta/example.rs", t.files)

    def test_protected_is_test_files(self):
        tasks = pt.load(self.root, languages=["python", "javascript", "rust"])
        self.assertEqual(tasks["poly_python_add-numbers"].protected, ("add_numbers_test.py",))
        self.assertEqual(tasks["poly_javascript_add-numbers"].protected, ("add-numbers.spec.js",))
        self.assertEqual(tasks["poly_rust_add-numbers"].protected, ("tests/add_numbers.rs",))

    def test_solution_and_test_files_present_in_files_dict(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        self.assertIn("add_numbers.py", t.files)
        self.assertIn("add_numbers_test.py", t.files)


class TestPythonEvaluate(FakeTreeTestCase):
    def test_stub_fails(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        ws = _materialize(t.files)
        try:
            result = t.evaluate(ws)
            self.assertGreater(result["failed"], 0)
            self.assertEqual(result["checks"], 3)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_reference_solution_passes(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        ws = _materialize(t.files, {"add_numbers.py": _PY_EXAMPLE})
        try:
            result = t.evaluate(ws)
            self.assertEqual(result["failed"], 0, result)
            self.assertEqual(result["checks"], 3)
            self.assertEqual(result["passed"], 3)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_tampered_test_file_yields_protected_failure_label(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        tampered_test = t.files["add_numbers_test.py"] + "\n# tampered\n"
        ws = _materialize(t.files, {"add_numbers.py": _PY_EXAMPLE, "add_numbers_test.py": tampered_test})
        try:
            result = t.evaluate(ws)
            self.assertIn("protected_modified:add_numbers_test.py", result["failure_labels"])
            self.assertGreater(result["failed"], 0)
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestInterpreterWithPytestProbe(unittest.TestCase):
    """Defect: the Python evaluator used `sys.executable` unconditionally, so any
    caller whose own interpreter lacks pytest (e.g. the Amplifier host venv) scored
    every Python exercise `no_tests_collected` regardless of candidate correctness.
    `_interpreter_with_pytest` must discover an interpreter that can actually
    `import pytest`, trying `sys.executable` first and falling through candidates.
    """

    def setUp(self):
        pt._interpreter_with_pytest.cache_clear()
        self.addCleanup(pt._interpreter_with_pytest.cache_clear)

    def _fake_run(self, ok_for):
        def _run(argv, capture_output=True, timeout=10):
            interp = argv[0]
            proc = mock.Mock()
            proc.returncode = 0 if interp in ok_for else 1
            return proc

        return _run

    def test_falls_through_to_second_candidate_when_first_lacks_pytest(self):
        with (
            mock.patch.object(pt.sys, "executable", "/fake/no-pytest/python"),
            mock.patch.object(pt.shutil, "which", side_effect=lambda name: "/fake/has-pytest/python3" if name == "python3" else None),
            mock.patch.object(pt.subprocess, "run", side_effect=self._fake_run(ok_for={"/fake/has-pytest/python3"})),
        ):
            interp = pt._interpreter_with_pytest()
        self.assertEqual(interp, "/fake/has-pytest/python3")

    def test_none_when_no_candidate_has_pytest(self):
        with (
            mock.patch.object(pt.sys, "executable", "/fake/no-pytest/python"),
            mock.patch.object(pt.shutil, "which", side_effect=lambda name: "/fake/also-no-pytest/python3" if name == "python3" else None),
            mock.patch.object(pt.subprocess, "run", side_effect=self._fake_run(ok_for=set())),
        ):
            interp = pt._interpreter_with_pytest()
        self.assertIsNone(interp)

    def test_python_run_labels_toolchain_missing_pytest_when_no_interpreter_qualifies(self):
        with mock.patch.object(pt, "_interpreter_with_pytest", return_value=None):
            result = pt._python_run(Path(tempfile.mkdtemp()), ["add_numbers_test.py"])
        self.assertEqual(result["failure_labels"], ["toolchain_missing:pytest"])
        self.assertNotIn("no_tests_collected", result["failure_labels"])

    def test_parse_pytest_output_distinguishes_module_not_found_from_no_tests_collected(self):
        module_not_found = "ModuleNotFoundError: No module named 'pytest'\n"
        result = pt._parse_pytest_output(module_not_found)
        self.assertEqual(result["failure_labels"], ["toolchain_missing:pytest"])

        genuinely_empty = "no tests ran in 0.01s\n"
        result = pt._parse_pytest_output(genuinely_empty)
        self.assertEqual(result["failure_labels"], ["no_tests_collected"])


class TestEvaluatorCopySafety(FakeTreeTestCase):
    """Defect A: shutil.copytree(workspace, tmp_exercise) must never crash on
    non-regular files under .git (e.g. a Watchman/fsmonitor unix socket), and
    any copy failure must degrade to a failure_labels result, never an
    unhandled/leaked exception string with paths in it.

    Defect B: the temp copy must be named after the exercise slug (not a
    generic "exercise" name), since CMake/Cargo/Go derive target/package
    names from the containing directory name.
    """

    def test_git_socket_in_workspace_does_not_crash_evaluate(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        ws = _materialize(t.files, {"add_numbers.py": _PY_EXAMPLE})
        sock = None
        try:
            git_dir = ws / ".git"
            git_dir.mkdir()
            sock_path = git_dir / "fsmonitor--daemon.ipc"
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(sock_path))
            result = t.evaluate(ws)
            self.assertEqual(result["failed"], 0, result)
            self.assertEqual(result["checks"], 3)
            self.assertNotIn("evaluator_copy_error", result["failure_labels"])
        finally:
            if sock is not None:
                sock.close()
            shutil.rmtree(ws, ignore_errors=True)

    def test_copytree_oserror_becomes_evaluator_copy_error_label(self):
        tasks = pt.load(self.root, languages=["python"])
        t = tasks["poly_python_add-numbers"]
        ws = _materialize(t.files, {"add_numbers.py": _PY_EXAMPLE})
        try:
            with mock.patch.object(pt.shutil, "copytree", side_effect=OSError("Operation not supported")):
                result = t.evaluate(ws)
            self.assertEqual(result["failure_labels"], ["evaluator_copy_error"])
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["checks"], 1)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_temp_copy_directory_named_after_exercise_slug(self):
        captured = {}
        real_runner = pt._python_run

        def _spy(exercise_root, test_files):
            captured["name"] = exercise_root.name
            return real_runner(exercise_root, test_files)

        with mock.patch.dict(pt._RUNNERS, {"python": _spy}):
            tasks = pt.load(self.root, languages=["python"])
            t = tasks["poly_python_add-numbers"]
            ws = _materialize(t.files, {"add_numbers.py": _PY_EXAMPLE})
            try:
                result = t.evaluate(ws)
            finally:
                shutil.rmtree(ws, ignore_errors=True)
        self.assertEqual(captured["name"], "add-numbers")
        self.assertEqual(result["failed"], 0, result)

    def test_copy_ignores_dot_git_and_build_output_dirs(self):
        captured = {}
        real_runner = pt._python_run

        def _spy(exercise_root, test_files):
            captured["copied"] = sorted(p.name for p in exercise_root.iterdir())
            return real_runner(exercise_root, test_files)

        with mock.patch.dict(pt._RUNNERS, {"python": _spy}):
            tasks = pt.load(self.root, languages=["python"])
            t = tasks["poly_python_add-numbers"]
            ws = _materialize(t.files, {"add_numbers.py": _PY_EXAMPLE})
            try:
                (ws / ".git").mkdir()
                (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
                (ws / "__pycache__").mkdir()
                (ws / "__pycache__" / "add_numbers.cpython-312.pyc").write_bytes(b"\x00")
                result = t.evaluate(ws)
            finally:
                shutil.rmtree(ws, ignore_errors=True)
        self.assertNotIn(".git", captured["copied"])
        self.assertNotIn("__pycache__", captured["copied"])
        self.assertEqual(result["failed"], 0, result)


class TestPureHelpers(unittest.TestCase):
    def test_unskip_js_test_source(self):
        src = "xtest('a', () => {});\nit('b', () => {});\nxit('c', () => {});\n"
        out = pt.unskip_js_test_source(src)
        self.assertNotIn("xtest(", out)
        self.assertNotIn("xit(", out)
        self.assertIn("test('a'", out)
        self.assertIn("it('c'", out)
        # Untouched normal `it(` call stays exactly as-is.
        self.assertIn("it('b', () => {});", out)

    def test_unskip_js_test_source_no_matches_is_noop(self):
        src = "test('a', () => {});\n"
        self.assertEqual(pt.unskip_js_test_source(src), src)

    def test_strip_rust_ignore(self):
        src = "#[test]\n#[ignore]\nfn a() {}\n\n#[test]\nfn b() {}\n"
        out = pt.strip_rust_ignore(src)
        self.assertNotIn("#[ignore]", out)
        self.assertIn("#[test]\nfn a() {}", out)
        self.assertIn("#[test]\nfn b() {}", out)

    def test_strip_rust_ignore_no_matches_is_noop(self):
        src = "#[test]\nfn a() {}\n"
        self.assertEqual(pt.strip_rust_ignore(src), src)

    def test_strip_rust_ignore_only_strips_bare_attribute_lines(self):
        # A line that merely mentions #[ignore] as part of other content
        # (e.g. inside a string or comment) is left untouched; only an
        # exact `#[ignore]` attribute line is removed.
        src = "// see #[ignore] docs\n#[ignore]\nfn a() {}\n"
        out = pt.strip_rust_ignore(src)
        self.assertIn("// see #[ignore] docs", out)
        self.assertNotIn("\n#[ignore]\n", out)


class TestGoJsonParsing(unittest.TestCase):
    def test_leaf_subtests_counted_not_parent(self):
        lines = [
            json.dumps({"Action": "run", "Test": "TestSolve"}),
            json.dumps({"Action": "fail", "Test": "TestSolve/case_a"}),
            json.dumps({"Action": "pass", "Test": "TestSolve/case_b"}),
            json.dumps({"Action": "fail", "Test": "TestSolve"}),
        ]
        result = pt._parse_go_json_output("\n".join(lines))
        self.assertEqual(result["checks"], 2)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 1)

    def test_no_events_is_build_failed(self):
        result = pt._parse_go_json_output("")
        self.assertEqual(result["failure_labels"], ["build_failed"])


class TestCatch2Parsing(unittest.TestCase):
    def test_all_passed_message(self):
        text = "All tests passed (17 assertions in 17 test cases)\n"
        result = pt._parse_catch2_output(text)
        self.assertEqual(result, {"checks": 17, "passed": 17, "failed": 0, "failure_labels": []})

    def test_summary_line_with_failures(self):
        text = "test cases: 17 | 2 passed | 15 failed\nassertions: 17 | 2 passed | 15 failed\n"
        result = pt._parse_catch2_output(text)
        self.assertEqual(result["checks"], 17)
        self.assertEqual(result["passed"], 2)
        self.assertEqual(result["failed"], 15)
        self.assertEqual(result["failure_labels"], ["catch2_failures"])

    def test_unparseable_is_compile_error(self):
        result = pt._parse_catch2_output("some unrelated compiler spew\n")
        self.assertEqual(result["failure_labels"], ["compile_error"])


class TestToolchains(unittest.TestCase):
    def test_returns_expected_keys(self):
        result = pt.toolchains()
        self.assertEqual(
            set(result),
            {"python3", "node", "cargo", "go", "javac", "cmake"},
        )
        for v in result.values():
            self.assertIsInstance(v, bool)

    def test_find_junit_console_jar_absent(self):
        d = Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(pt.find_junit_console_jar(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_find_junit_console_jar_present(self):
        d = Path(tempfile.mkdtemp())
        try:
            jar = d / "libs" / "junit-platform-console-standalone-1.10.0.jar"
            jar.parent.mkdir(parents=True, exist_ok=True)
            jar.write_bytes(b"not a real jar")
            self.assertEqual(pt.find_junit_console_jar(d), jar)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestSelectSlice(FakeTreeTestCase):
    def _bigger_tree(self) -> Path:
        # Extend the fake tree with a couple more python/js/rust exercises
        # so select_slice has more than one candidate per language.
        root = self.root
        for i in range(2, 6):
            py_ex = root / "python" / "exercises" / "practice" / f"add-numbers-{i}"
            _write(py_ex / ".docs" / "instructions.md", _PY_INSTRUCTIONS)
            _write(py_ex / ".meta" / "config.json", json.dumps(_PY_CONFIG))
            _write(py_ex / ".meta" / "example.py", _PY_EXAMPLE)
            _write(py_ex / "add_numbers.py", _PY_STUB)
            _write(py_ex / "add_numbers_test.py", _PY_TEST)

            js_ex = root / "javascript" / "exercises" / "practice" / f"add-numbers-{i}"
            _write(js_ex / ".docs" / "instructions.md", _JS_INSTRUCTIONS)
            _write(js_ex / ".meta" / "config.json", json.dumps(_JS_CONFIG))
            _write(js_ex / ".meta" / "proof.ci.js", _JS_EXAMPLE)
            _write(js_ex / "add-numbers.js", _JS_STUB)
            _write(js_ex / "add-numbers.spec.js", _JS_TEST)
            _write(js_ex / "package.json", _JS_PACKAGE_JSON)
        return root

    def test_deterministic_for_same_seed(self):
        root = self._bigger_tree()
        tasks = pt.load(root, languages=["python", "javascript"])
        dev1, holdout1 = pt.select_slice(tasks, 6, seed=7)
        dev2, holdout2 = pt.select_slice(tasks, 6, seed=7)
        self.assertEqual(dev1, dev2)
        self.assertEqual(holdout1, holdout2)

    def test_sorted_and_no_overlap(self):
        root = self._bigger_tree()
        tasks = pt.load(root, languages=["python", "javascript"])
        dev, holdout = pt.select_slice(tasks, 6, seed=1)
        self.assertEqual(dev, sorted(dev))
        self.assertEqual(holdout, sorted(holdout))
        self.assertEqual(set(dev) & set(holdout), set())

    def test_stratified_across_languages(self):
        root = self._bigger_tree()
        tasks = pt.load(root, languages=["python", "javascript"])
        dev, holdout = pt.select_slice(tasks, 6, seed=3)
        all_selected = dev + holdout
        py_count = sum(1 for n in all_selected if n.startswith("poly_python_"))
        js_count = sum(1 for n in all_selected if n.startswith("poly_javascript_"))
        self.assertEqual(py_count, 3)
        self.assertEqual(js_count, 3)

    def test_languages_filter(self):
        root = self._bigger_tree()
        tasks = pt.load(root, languages=["python", "javascript"])
        dev, holdout = pt.select_slice(tasks, 4, seed=5, languages=["python"])
        for name in dev + holdout:
            self.assertTrue(name.startswith("poly_python_"))

    def test_empty_tasks_returns_empty(self):
        dev, holdout = pt.select_slice({}, 10, seed=1)
        self.assertEqual(dev, [])
        self.assertEqual(holdout, [])


class TestManifestBuilder(unittest.TestCase):
    def test_build_manifest_from_fake_tree(self):
        root = Path(tempfile.mkdtemp())
        try:
            _build_fake_tree(root)
            manifest = fp.build_manifest(root, sha="deadbeef")
            self.assertEqual(manifest["sha"], "deadbeef")
            self.assertEqual(manifest["languages"], {"javascript": 1, "python": 1, "rust": 1})
            self.assertEqual(manifest["total_exercises"], 3)
            self.assertEqual(manifest["exercise_slugs"]["python"], ["add-numbers"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_build_manifest_empty_dir(self):
        root = Path(tempfile.mkdtemp())
        try:
            manifest = fp.build_manifest(root, sha=None)
            self.assertEqual(manifest["languages"], {})
            self.assertEqual(manifest["total_exercises"], 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_build_manifest_nonexistent_dir(self):
        manifest = fp.build_manifest(Path("/nonexistent/does/not/exist"), sha=None)
        self.assertEqual(manifest["languages"], {})
        self.assertEqual(manifest["total_exercises"], 0)


if __name__ == "__main__":
    unittest.main()
