"""A 20-task benchmark battery for coding-agent harnesses.

Four families, five tasks each, three "dev" plus two "holdout" splits per
family:

  - repair:  a broken/partial `solution.py` behind a precise contract in
    README.md; hidden checks run randomized + boundary + invalid-input +
    immutability property tests against an INDEPENDENT oracle implemented
    here (never against the candidate's own helpers).
  - answer:  a small synthetic codebase (with deliberate decoys) plus a
    question whose answer is a single unambiguous token, checked by regex
    against the agent's final `ANSWER:` line.
  - edit:    a working small module plus a README describing ONE precise
    change; hidden checks verify the new behavior AND that existing
    behavior is unchanged (regression).
  - bugfix:  a small module with ONE planted bug and a public test that
    fails because of it; hidden checks cover the public case, a few more
    cases exposing the same bug, and several regression cases.

All candidate code is executed in a subprocess with a timeout -- never
imported into this evaluator process. Stdlib only.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

TIMEOUT = 20

PROMPT_SUFFIX = (
    "\n\nRules: work only inside this directory; do not use the network; do "
    "not modify README.md or test_public.py. Do not delegate to other "
    "agents. When finished, print one final line that starts with "
    "`ANSWER:` (for questions) or `DONE:` (for code changes) followed by a "
    "one-line summary."
)


@dataclass(frozen=True)
class Task:
    name: str
    family: str
    split: str
    kind: str
    prompt: str
    files: dict[str, str]
    protected: tuple[str, ...]
    expected_answer: str | None
    evaluate: Callable[[Path], dict]


# ---------------------------------------------------------------------------
# Subprocess execution harness -- candidate code always runs out-of-process.
# ---------------------------------------------------------------------------


def _run_snippet(workspace: Path, snippet: str, timeout: int = TIMEOUT) -> tuple[Any, str | None]:
    """Run `snippet` (trusted, harness-authored source) in a fresh subprocess
    with `workspace` on sys.path and as cwd. The snippet must print exactly
    one JSON value as its last stdout line. Never raises."""
    full = f"import sys, json\nsys.path.insert(0, {str(workspace)!r})\n" + snippet
    try:
        proc = subprocess.run(
            [sys.executable, "-c", full],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:  # pragma: no cover - defensive
        return None, f"subprocess_error:{e}"
    if proc.returncode != 0:
        return None, f"nonzero_exit:{proc.stderr[-500:]}"
    lines = proc.stdout.strip().splitlines()
    if not lines:
        return None, f"no_output:{proc.stderr[-300:]}"
    try:
        return json.loads(lines[-1]), None
    except Exception:
        return None, f"bad_output:{proc.stdout[:300]}"


def _run_cases(
    workspace: Path,
    func_name: str,
    module_name: str,
    cases: list[dict],
    timeout: int = TIMEOUT,
) -> tuple[list[dict] | None, str | None]:
    """Call `module_name.func_name(*args)` for each case (JSON-serializable
    args) inside one subprocess. Returns (results, error)."""
    cases_literal = json.dumps(json.dumps(cases))
    snippet = f"""
import copy
try:
    from {module_name} import {func_name} as _fn
except Exception as e:
    print(json.dumps({{"import_error": str(e)}}))
    raise SystemExit(0)
_cases = json.loads({cases_literal})
out = []
for c in _cases:
    args = c["args"]
    before = copy.deepcopy(args)
    entry = {{"id": c["id"]}}
    try:
        result = _fn(*args)
        entry["ok"] = True
        entry["result"] = result
    except ValueError as e:
        entry["ok"] = False
        entry["error"] = "ValueError"
        entry["message"] = str(e)
    except TypeError as e:
        entry["ok"] = False
        entry["error"] = "TypeError"
        entry["message"] = str(e)
    except Exception as e:
        entry["ok"] = False
        entry["error"] = "Exception:" + type(e).__name__
        entry["message"] = str(e)
    entry["immutable"] = (args == before)
    out.append(entry)
print(json.dumps(out))
"""
    data, err = _run_snippet(workspace, snippet, timeout=timeout)
    if err:
        return None, err
    if isinstance(data, dict) and "import_error" in data:
        return None, f"import_error:{data['import_error']}"
    return data, None


def _mk(
    id_: str,
    args: tuple,
    *,
    expected: Any = None,
    invalid: bool = False,
    expected_error: str | None = None,
    expected_message: str | None = None,
    check_immutable: bool = False,
) -> dict:
    return {
        "id": id_,
        "args": list(args),
        "expected": expected,
        "invalid": invalid,
        "expected_error": expected_error,
        "expected_message": expected_message,
        "check_immutable": check_immutable,
    }


def _score_cases(actual: list[dict] | None, err: str | None, expected_by_id: dict[str, dict]) -> dict:
    total = len(expected_by_id)
    if err:
        return {"checks": total, "passed": 0, "failed": total, "failure_labels": [err]}
    failures: list[str] = []
    actual_by_id = {a["id"]: a for a in (actual or [])}
    for cid, exp in expected_by_id.items():
        a = actual_by_id.get(cid)
        if a is None:
            failures.append(cid + ":missing")
            continue
        if exp.get("invalid"):
            if a.get("ok"):
                failures.append(cid + ":expected-error-got-ok")
                continue
            expected_error = exp.get("expected_error")
            if expected_error and a.get("error") != expected_error:
                failures.append(cid + ":wrong-error-type:" + str(a.get("error")))
                continue
        else:
            if not a.get("ok"):
                failures.append(cid + ":unexpected-error:" + str(a.get("error")))
                continue
            if a.get("result") != exp.get("expected"):
                failures.append(cid + ":wrong-result")
                continue
        expected_message = exp.get("expected_message")
        if expected_message is not None and a.get("message") != expected_message:
            failures.append(cid + ":wrong-message")
            continue
        if exp.get("check_immutable") and not a.get("immutable", True):
            failures.append(cid + ":mutated-input")
    return {"checks": total, "passed": total - len(failures), "failed": len(failures), "failure_labels": failures}


def _merge_scores(*scores: dict) -> dict:
    return {
        "checks": sum(s["checks"] for s in scores),
        "passed": sum(s["passed"] for s in scores),
        "failed": sum(s["failed"] for s in scores),
        "failure_labels": [label for s in scores for label in s["failure_labels"]],
    }


def _gen_cases(prefix: str, arg_fn, oracle_fn, n: int, rng: random.Random, check_immutable: bool = True) -> list[dict]:
    specs = []
    for i in range(n):
        args = arg_fn(rng)
        try:
            expected = oracle_fn(*args)
            specs.append(_mk(f"{prefix}-{i}", args, expected=expected, check_immutable=check_immutable))
        except (ValueError, TypeError) as e:
            specs.append(_mk(f"{prefix}-{i}", args, invalid=True, expected_error=type(e).__name__))
    return specs


def _make_repair_evaluate(func_name: str, oracle_fn, arg_fn, boundary_specs: list[dict], n_random: int = 24, seed: int = 17):
    def _evaluate(workspace: Path) -> dict:
        rng = random.Random(seed)
        specs = _gen_cases("rand", arg_fn, oracle_fn, n_random, rng) + list(boundary_specs)
        cases = [{"id": s["id"], "args": s["args"]} for s in specs]
        expected = {s["id"]: s for s in specs}
        actual, err = _run_cases(workspace, func_name, "solution", cases)
        return _score_cases(actual, err, expected)

    return _evaluate


def check_answer(task: Task, final_message: str | None) -> dict:
    if final_message is None:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["no_final_message"]}
    m = re.search(r"^\s*ANSWER:\s*(.*)$", final_message, re.MULTILINE | re.IGNORECASE)
    if not m:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["no_answer_line"]}
    line = m.group(1)
    if task.expected_answer and re.search(task.expected_answer, line, re.IGNORECASE):
        return {"checks": 1, "passed": 1, "failed": 0, "failure_labels": []}
    return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": ["answer_mismatch"]}


def _answer_evaluate(_workspace: Path) -> dict:
    return {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}


# ---------------------------------------------------------------------------
# repair: independent oracles (never derived from candidate code)
# ---------------------------------------------------------------------------


def _oracle_parse_duration(s):
    if not isinstance(s, str):
        raise TypeError("not a string")
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
    if not m or not any(m.groups()):
        raise ValueError("bad duration")
    h, mm, ss = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mm * 60 + ss


def _gen_duration_arg(rng: random.Random):
    parts = []
    for unit in "hms":
        if rng.random() < 0.6:
            parts.append(f"{rng.randrange(0, 100)}{unit}")
    s = "".join(parts)
    if rng.random() < 0.15:
        s = s + "x"
    if rng.random() < 0.1:
        s = " " + s
    return (s,)


_PARSE_DURATION_BOUNDARY = [
    _mk("zero", ("0h",), expected=0, check_immutable=True),
    _mk("all-parts", ("1h2m3s",), expected=3723, check_immutable=True),
    _mk("only-seconds", ("59s",), expected=59, check_immutable=True),
    _mk("empty", ("",), invalid=True, expected_error="ValueError"),
    _mk("wrong-order", ("1m1h",), invalid=True, expected_error="ValueError"),
    _mk("bad-unit", ("1x",), invalid=True, expected_error="ValueError"),
    _mk("leading-space", (" 1h",), invalid=True, expected_error="ValueError"),
    _mk("not-a-string", (5,), invalid=True, expected_error="TypeError"),
]


def _oracle_merge_intervals(intervals):
    if not isinstance(intervals, list):
        raise TypeError("not a list")
    norm = []
    for iv in intervals:
        if not isinstance(iv, (list, tuple)) or len(iv) != 2:
            raise ValueError("bad interval")
        a, b = iv
        if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int) or not isinstance(b, int) or a > b:
            raise ValueError("bad interval bounds")
        norm.append([a, b])
    norm.sort(key=lambda p: p[0])
    merged: list[list[int]] = []
    for start, end in norm:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _gen_intervals_arg(rng: random.Random):
    n = rng.randrange(0, 6)
    intervals: list[Any] = []
    for _ in range(n):
        a = rng.randrange(-10, 20)
        b = a + rng.randrange(-3, 8)
        intervals.append([a, b])
    if intervals and rng.random() < 0.1:
        intervals[0] = [intervals[0][0], "x"]
    return (intervals,)


_MERGE_INTERVALS_BOUNDARY = [
    _mk("empty", ([],), expected=[], check_immutable=True),
    _mk("single", ([[1, 2]],), expected=[[1, 2]], check_immutable=True),
    _mk("touching", ([[1, 3], [3, 5]],), expected=[[1, 5]], check_immutable=True),
    _mk("overlap", ([[1, 5], [2, 3]],), expected=[[1, 5]], check_immutable=True),
    _mk("disjoint", ([[1, 2], [4, 5]],), expected=[[1, 2], [4, 5]], check_immutable=True),
    _mk("unsorted", ([[4, 5], [1, 2]],), expected=[[1, 2], [4, 5]], check_immutable=True),
    _mk("bad-order", ([[5, 1]],), invalid=True, expected_error="ValueError"),
    _mk("bad-item-type", ([[1, "x"]],), invalid=True, expected_error="ValueError"),
    _mk("not-a-list", ("x",), invalid=True, expected_error="TypeError"),
]

_SEMVER_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def _oracle_semver_parse(s):
    if not isinstance(s, str):
        raise TypeError("not a string")
    m = _SEMVER_RE.fullmatch(s)
    if not m:
        raise ValueError("bad semver")
    return tuple(int(x) for x in m.groups())


def _oracle_semver_compare(a, b):
    pa, pb = _oracle_semver_parse(a), _oracle_semver_parse(b)
    return (pa > pb) - (pa < pb)


def _gen_semver_arg(rng: random.Random):
    def token():
        if rng.random() < 0.85:
            return ".".join(str(rng.randrange(0, 5)) for _ in range(3))
        return rng.choice(["1.2", "1.2.3.4", "v1.2.3", "01.2.3", "1.2.x", ""])

    return (token(), token())


_SEMVER_BOUNDARY = [
    _mk("equal", ("1.2.3", "1.2.3"), expected=0, check_immutable=True),
    _mk("less", ("1.2.3", "1.2.4"), expected=-1, check_immutable=True),
    _mk("greater", ("2.0.0", "1.9.9"), expected=1, check_immutable=True),
    _mk("leading-zero", ("01.2.3", "1.2.3"), invalid=True, expected_error="ValueError"),
    _mk("too-few-parts", ("1.2", "1.2.3"), invalid=True, expected_error="ValueError"),
    _mk("non-numeric", ("1.2.x", "1.2.3"), invalid=True, expected_error="ValueError"),
    _mk("not-a-string", (1, "1.2.3"), invalid=True, expected_error="TypeError"),
]


def _oracle_tokenize_kv(s):
    if not isinstance(s, str):
        raise TypeError("not a string")
    if s == "":
        return {}
    parts, buf, in_quotes, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
            i += 1
        elif not in_quotes and s[i:i + 2] == ", ":
            parts.append("".join(buf))
            buf = []
            i += 2
        else:
            buf.append(ch)
            i += 1
    if in_quotes:
        raise ValueError("unterminated quote")
    parts.append("".join(buf))
    entry_re = re.compile(r'^([A-Za-z_]\w*)=(?:"([^"]*)"|([^,"]+))$')
    result: dict[str, str] = {}
    for part in parts:
        m = entry_re.match(part)
        if not m:
            raise ValueError("bad entry: " + part)
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else m.group(3)
        if key in result:
            raise ValueError("duplicate key: " + key)
        result[key] = value
    return result


def _gen_kv_arg(rng: random.Random):
    keys = rng.sample(["a", "b", "c", "d"], rng.randrange(0, 4))
    entries = []
    for k in keys:
        if rng.random() < 0.5:
            v = '"' + rng.choice(["x, y", "hello", "", "z"]) + '"'
        else:
            v = str(rng.randrange(0, 100))
        entries.append(f"{k}={v}")
    s = ", ".join(entries)
    if rng.random() < 0.15:
        s += ",bad"
    return (s,)


_TOKENIZE_KV_BOUNDARY = [
    _mk("empty", ("",), expected={}, check_immutable=True),
    _mk("single", ("a=1",), expected={"a": "1"}, check_immutable=True),
    _mk("quoted-with-comma", ('b="x, y"',), expected={"b": "x, y"}, check_immutable=True),
    _mk("multi", ('a=1, b="x, y", c=3',), expected={"a": "1", "b": "x, y", "c": "3"}, check_immutable=True),
    _mk("dup-key", ("a=1, a=2",), invalid=True, expected_error="ValueError"),
    _mk("unterminated-quote", ('a="x',), invalid=True, expected_error="ValueError"),
    _mk("no-equals", ("abc",), invalid=True, expected_error="ValueError"),
    _mk("not-a-string", (None,), invalid=True, expected_error="TypeError"),
]


def _oracle_word_wrap(text, width):
    if not isinstance(text, str) or not text:
        raise ValueError("bad text")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("bad width")
    if text != text.strip() or "  " in text or "\t" in text or "\n" in text:
        raise ValueError("bad spacing")
    words = text.split(" ")
    for w in words:
        if len(w) > width:
            raise ValueError("word too long")
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _gen_wrap_arg(rng: random.Random):
    words = ["".join(rng.choice("abc") for _ in range(rng.randrange(1, 6))) for _ in range(rng.randrange(1, 6))]
    text = " ".join(words)
    width = rng.randrange(1, 8)
    return (text, width)


_WORD_WRAP_BOUNDARY = [
    _mk("single-word", ("hi", 5), expected=["hi"], check_immutable=True),
    _mk("two-lines", ("aa bb cc", 5), expected=["aa bb", "cc"], check_immutable=True),
    _mk("exact-width", ("aa bb", 5), expected=["aa bb"], check_immutable=True),
    _mk("word-too-long", ("aaaaaa", 3), invalid=True, expected_error="ValueError"),
    _mk("bad-width-zero", ("a b", 0), invalid=True, expected_error="ValueError"),
    _mk("bad-width-bool", ("a b", True), invalid=True, expected_error="ValueError"),
    _mk("double-space", ("a  b", 5), invalid=True, expected_error="ValueError"),
    _mk("empty-text", ("", 5), invalid=True, expected_error="ValueError"),
]


# ---------------------------------------------------------------------------
# repair: README / starter / public-test content
# ---------------------------------------------------------------------------

_README_PARSE_DURATION = """# Duration parser repair
Repair `solution.py` using only the Python standard library. Keep the public
function `parse_duration(s)`. Run `python3 -m unittest -v test_public.py`.

Input is a string composed of optional components in this exact order: an
integer followed by "h", then an integer followed by "m", then an integer
followed by "s" (each component optional, but at least one must be present).
No other characters, spaces, or signs are allowed. Integers are written in
decimal without a leading "+"; leading zeros are fine (e.g. "05m").

Return the total number of seconds as a nonnegative int. Reject any other
string (wrong order, unknown unit, missing digits, extra characters, empty
string) with ValueError. Reject a non-string input with TypeError.
"""

_STARTER_PARSE_DURATION = """def parse_duration(s):
    total = 0
    for part in s.split('h'):
        pass
    return len(s)
"""

_TEST_PARSE_DURATION = """import unittest
from solution import parse_duration


class Public(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_duration("1h30m15s"), 5415)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_duration("bad")
"""

_FIX_PARSE_DURATION = """import re

_RE = re.compile(r'(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?')


def parse_duration(s):
    if not isinstance(s, str):
        raise TypeError("duration must be a string")
    m = _RE.fullmatch(s)
    if not m or not any(m.groups()):
        raise ValueError("invalid duration format")
    h, mm, ss = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mm * 60 + ss
"""

_README_MERGE_INTERVALS = """# Interval merger repair
Repair `solution.py` using only the Python standard library. Keep the public
function `merge_intervals(intervals)`. Run `python3 -m unittest -v test_public.py`.
Never mutate the input list or its interval items.

`intervals` is a list of two-element lists/tuples `[start, end]` of plain
ints (not bool) with `start <= end`. Reject anything else (wrong length,
non-int values, bool values, `start > end`) with ValueError. Reject a
non-list `intervals` with TypeError.

Return a new list of `[start, end]` pairs, sorted by start, where any two
intervals are merged into one whenever the next interval (in start order)
begins at or before the current merged interval's end. Non-overlapping,
non-touching intervals stay separate. Empty input returns an empty list.
"""

_STARTER_MERGE_INTERVALS = """def merge_intervals(intervals):
    return intervals
"""

_TEST_MERGE_INTERVALS = """import unittest
from solution import merge_intervals


class Public(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 6], [8, 10]]), [[1, 6], [8, 10]])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            merge_intervals([[5, 1]])
"""

_FIX_MERGE_INTERVALS = """def merge_intervals(intervals):
    if not isinstance(intervals, list):
        raise TypeError("intervals must be a list")
    norm = []
    for iv in intervals:
        if not isinstance(iv, (list, tuple)) or len(iv) != 2:
            raise ValueError("bad interval")
        a, b = iv
        if (
            isinstance(a, bool)
            or isinstance(b, bool)
            or not isinstance(a, int)
            or not isinstance(b, int)
            or a > b
        ):
            raise ValueError("bad interval bounds")
        norm.append([a, b])
    norm = sorted(norm, key=lambda p: p[0])
    merged = []
    for start, end in norm:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
"""

_README_SEMVER_COMPARE = """# Semantic version comparator repair
Repair `solution.py` using only the Python standard library. Keep the public
function `semver_compare(a, b)`. Run `python3 -m unittest -v test_public.py`.

Each of `a` and `b` must be a string of the exact form `MAJOR.MINOR.PATCH`
where each component is a nonnegative integer with no leading zeros (`"0"`
is the only valid zero form; `"01"` is invalid). No pre-release or build
metadata is supported. Reject any other string with ValueError. Reject a
non-string argument with TypeError.

Compare the two versions using standard tuple ordering on
`(major, minor, patch)`. Return `-1` if `a < b`, `0` if equal, `1` if `a > b`.
"""

_STARTER_SEMVER_COMPARE = """def semver_compare(a, b):
    return 0
"""

_TEST_SEMVER_COMPARE = """import unittest
from solution import semver_compare


class Public(unittest.TestCase):
    def test_compare(self):
        self.assertEqual(semver_compare("1.2.3", "1.2.4"), -1)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            semver_compare("01.2.3", "1.2.3")
"""

_FIX_SEMVER_COMPARE = """import re

_RE = re.compile(r'(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)')


def _parse(s):
    if not isinstance(s, str):
        raise TypeError("version must be a string")
    m = _RE.fullmatch(s)
    if not m:
        raise ValueError("invalid semver")
    return tuple(int(x) for x in m.groups())


def semver_compare(a, b):
    pa, pb = _parse(a), _parse(b)
    return (pa > pb) - (pa < pb)
"""

_README_TOKENIZE_KV = """# Key-value tokenizer repair
Repair `solution.py` using only the Python standard library. Keep the public
function `tokenize_kv(s)`. Run `python3 -m unittest -v test_public.py`.

`s` is a string of comma-space-separated `key=value` entries, e.g.
`a=1, b="x, y", c=3`. A key matches `[A-Za-z_][A-Za-z0-9_]*`. A value is
either a double-quoted string (any characters except `"`, no escaping) or an
unquoted run of one or more characters excluding `,` and `"`. Entries are
separated by exactly `", "` (comma then single space); this separator is not
recognized while inside a quoted value. Reject a non-string `s` with
TypeError. Reject any malformed entry, an unterminated quote, or a duplicate
key with ValueError. The empty string is valid and returns `{}`.

Return a dict mapping each key to its value (quotes stripped, not
unescaped). Never mutate any input.
"""

_STARTER_TOKENIZE_KV = """def tokenize_kv(s):
    return {}
"""

_TEST_TOKENIZE_KV = """import unittest
from solution import tokenize_kv


class Public(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(tokenize_kv('a=1, b="x, y", c=3'), {"a": "1", "b": "x, y", "c": "3"})

    def test_invalid(self):
        with self.assertRaises(ValueError):
            tokenize_kv("a=1, a=2")
"""

_FIX_TOKENIZE_KV = '''import re

_ENTRY_RE = re.compile(r'^([A-Za-z_]\\w*)=(?:"([^"]*)"|([^,"]+))$')


def tokenize_kv(s):
    if not isinstance(s, str):
        raise TypeError("s must be a string")
    if s == "":
        return {}
    parts, buf, in_quotes, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
            i += 1
        elif not in_quotes and s[i:i + 2] == ", ":
            parts.append("".join(buf))
            buf = []
            i += 2
        else:
            buf.append(ch)
            i += 1
    if in_quotes:
        raise ValueError("unterminated quote")
    parts.append("".join(buf))
    result = {}
    for part in parts:
        m = _ENTRY_RE.match(part)
        if not m:
            raise ValueError("bad entry: " + part)
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else m.group(3)
        if key in result:
            raise ValueError("duplicate key: " + key)
        result[key] = value
    return result
'''

_README_WORD_WRAP = """# Greedy word wrap repair
Repair `solution.py` using only the Python standard library. Keep the public
function `word_wrap(text, width)`. Run `python3 -m unittest -v test_public.py`.

`text` is a nonempty string of words separated by single spaces (no leading,
trailing, or doubled spaces, no tabs or newlines). `width` is a positive int
(not bool). Reject anything else, and reject any single word longer than
`width`, with ValueError.

Greedily pack words onto lines: add the next word to the current line if
doing so (joined by one space) keeps the line length at or under `width`;
otherwise start a new line with that word. Return the list of line strings,
in order. Never mutate the input.
"""

_STARTER_WORD_WRAP = """def word_wrap(text, width):
    return [text]
"""

_TEST_WORD_WRAP = """import unittest
from solution import word_wrap


class Public(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(word_wrap("aa bb cc", 5), ["aa bb", "cc"])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            word_wrap("aaaaaa", 3)
"""

_FIX_WORD_WRAP = """def word_wrap(text, width):
    if not isinstance(text, str) or not text:
        raise ValueError("bad text")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("bad width")
    if text != text.strip() or "  " in text or "\\t" in text or "\\n" in text:
        raise ValueError("bad spacing")
    words = text.split(" ")
    for w in words:
        if len(w) > width:
            raise ValueError("word too long")
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
"""


# ---------------------------------------------------------------------------
# edit: README / starter / evaluate content
# ---------------------------------------------------------------------------

_README_CLI_DRY_RUN = """# Add a --dry-run flag
Add a `--dry-run` boolean flag (argparse `action='store_true'`, default
False) to `cli_tool.py`. When `--dry-run` is given, the tool must NOT
create or delete any file, and must print exactly
`DRY RUN: would {action} {path}` (with the actual action and path
substituted) instead of performing the action. Without `--dry-run`,
existing behavior (performing the action and printing
`DONE: {action} {path}`) must be unchanged.
"""

_STARTER_CLI_DRY_RUN = """import argparse
import os


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--action", choices=["create", "delete"], required=True)
    args = parser.parse_args(argv)
    if args.action == "create":
        with open(args.path, "w", encoding="utf-8") as f:
            f.write("created\\n")
    else:
        if os.path.exists(args.path):
            os.remove(args.path)
    print(f"DONE: {args.action} {args.path}")


if __name__ == "__main__":
    main()
"""

_FIX_CLI_DRY_RUN = """import argparse
import os


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--action", choices=["create", "delete"], required=True)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args(argv)
    if args.dry_run:
        print(f"DRY RUN: would {args.action} {args.path}")
        return
    if args.action == "create":
        with open(args.path, "w", encoding="utf-8") as f:
            f.write("created\\n")
    else:
        if os.path.exists(args.path):
            os.remove(args.path)
    print(f"DONE: {args.action} {args.path}")


if __name__ == "__main__":
    main()
"""


def _evaluate_cli_dry_run(workspace: Path) -> dict:
    total = 0
    failures: list[str] = []
    script = workspace / "cli_tool.py"
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "out.txt"

        def run(*args):
            return subprocess.run(
                [sys.executable, str(script), *args],
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                cwd=str(workspace),
            )

        total += 1
        try:
            proc = run("--path", str(target), "--action", "create", "--dry-run")
            ok = (not target.exists()) and f"DRY RUN: would create {target}" in proc.stdout
        except Exception:
            ok = False
        if not ok:
            failures.append("dry-run-create")

        total += 1
        try:
            proc = run("--path", str(target), "--action", "create")
            ok = target.exists() and f"DONE: create {target}" in proc.stdout
        except Exception:
            ok = False
        if not ok:
            failures.append("real-create")

        total += 1
        try:
            proc = run("--path", str(target), "--action", "delete", "--dry-run")
            ok = target.exists() and f"DRY RUN: would delete {target}" in proc.stdout
        except Exception:
            ok = False
        if not ok:
            failures.append("dry-run-delete")

        total += 1
        try:
            proc = run("--path", str(target), "--action", "delete")
            ok = (not target.exists()) and f"DONE: delete {target}" in proc.stdout
        except Exception:
            ok = False
        if not ok:
            failures.append("real-delete")

    return {"checks": total, "passed": total - len(failures), "failed": len(failures), "failure_labels": failures}


_README_DEQUEUE_VALIDATION = """# Add empty-queue validation
Add validation to `dequeue(items)` in `queue_util.py`: if `items` is empty,
raise `ValueError('queue is empty')` with exactly that message. When
non-empty, existing behavior (remove and return the first element) must
remain unchanged. Do not change `remove_tag`-style helpers if present.
"""

_STARTER_DEQUEUE_VALIDATION = """def dequeue(items):
    return items.pop(0)
"""

_FIX_DEQUEUE_VALIDATION = """def dequeue(items):
    if not items:
        raise ValueError("queue is empty")
    return items.pop(0)
"""

_DEQUEUE_CASES = [
    _mk("empty", ([],), invalid=True, expected_error="ValueError", expected_message="queue is empty"),
    _mk("nonempty", ([1, 2, 3],), expected=1),
    _mk("nonempty2", ([9],), expected=9),
]


def _evaluate_dequeue(workspace: Path) -> dict:
    cases = [{"id": s["id"], "args": s["args"]} for s in _DEQUEUE_CASES]
    expected = {s["id"]: s for s in _DEQUEUE_CASES}
    actual, err = _run_cases(workspace, "dequeue", "queue_util", cases)
    return _score_cases(actual, err, expected)


_README_RECORD_TO_JSON = """# Add Record.to_json()
Add a `to_json()` method to the `Record` class in `record.py` that returns
`json.dumps(self.to_dict(), sort_keys=True)`. Do not change `to_dict()` or
`__init__`.
"""

_STARTER_RECORD_TO_JSON = """class Record:
    def __init__(self, name, value, tags):
        self.name = name
        self.value = value
        self.tags = tags

    def to_dict(self):
        return {"name": self.name, "value": self.value, "tags": list(self.tags)}
"""

_FIX_RECORD_TO_JSON = """import json


class Record:
    def __init__(self, name, value, tags):
        self.name = name
        self.value = value
        self.tags = tags

    def to_dict(self):
        return {"name": self.name, "value": self.value, "tags": list(self.tags)}

    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True)
"""


def _evaluate_record_to_json(workspace: Path) -> dict:
    snippet = """
import json as _json
from record import Record
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
r = Record("bob", 5, ["x", "y"])
try:
    js = r.to_json()
    expected = _json.dumps(r.to_dict(), sort_keys=True)
    check("to_json-matches", js == expected)
except Exception:
    check("to_json-matches", False)
check("to_dict-unchanged", r.to_dict() == {"name": "bob", "value": 5, "tags": ["x", "y"]})
r2 = Record("a", 1, [])
try:
    js2 = r2.to_json()
    check("to_json-empty-tags", js2 == _json.dumps({"name": "a", "value": 1, "tags": []}, sort_keys=True))
except Exception:
    check("to_json-empty-tags", False)
print(_json.dumps(out))
"""
    data, err = _run_snippet(workspace, snippet)
    if err:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err]}
    return data


_README_CLEAN_TEXT_STRICT = """# Add a strict= keyword-only parameter
Add a keyword-only parameter `strict` to `clean_text(text, *, strict=False)`
in `normalize.py`. When `strict=True`, raise `ValueError('non-ascii text')`
if `text` contains any non-ASCII character (checked before any other
processing); otherwise behave exactly as it does today: collapse all
whitespace runs to single spaces and strip leading/trailing whitespace.
When `strict=False` (the default, matching current calls with no `strict`
argument), behavior must be unchanged from today.
"""

_STARTER_CLEAN_TEXT_STRICT = """def clean_text(text):
    return " ".join(text.split())
"""

_FIX_CLEAN_TEXT_STRICT = """def clean_text(text, *, strict=False):
    if strict and not text.isascii():
        raise ValueError("non-ascii text")
    return " ".join(text.split())
"""


def _evaluate_clean_text_strict(workspace: Path) -> dict:
    snippet = """
import json as _json
from normalize import clean_text
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
check("default-unchanged", clean_text("  a   b  c ") == "a b c")
check("default-empty", clean_text("") == "")
try:
    check("strict-false-nonascii-ok", clean_text("café latte", strict=False) == "café latte")
except Exception:
    check("strict-false-nonascii-ok", False)
try:
    clean_text("café", strict=True)
    check("strict-true-rejects-nonascii", False)
except ValueError:
    check("strict-true-rejects-nonascii", True)
except Exception:
    check("strict-true-rejects-nonascii", False)
check("strict-true-accepts-ascii", clean_text("  a  b ", strict=True) == "a b")
print(_json.dumps(out))
"""
    data, err = _run_snippet(workspace, snippet)
    if err:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err]}
    return data


_README_POINT_REPR = """# Add Point.__repr__
Add `__repr__` to `Point` in `point.py` returning exactly
`f'Point(x={self.x}, y={self.y})'`. Do not change `__init__` or `__eq__`.
"""

_STARTER_POINT_REPR = """class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, Point) and self.x == other.x and self.y == other.y
"""

_FIX_POINT_REPR = """class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, Point) and self.x == other.x and self.y == other.y

    def __repr__(self):
        return f"Point(x={self.x}, y={self.y})"
"""


def _evaluate_point_repr(workspace: Path) -> dict:
    snippet = """
import json as _json
from point import Point
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
p = Point(1, 2)
check("repr-format", repr(p) == "Point(x=1, y=2)")
p2 = Point(-3, 0)
check("repr-format-neg", repr(p2) == "Point(x=-3, y=0)")
check("eq-unchanged", Point(1, 2) == Point(1, 2))
check("eq-unchanged-false", Point(1, 2) != Point(1, 3))
print(_json.dumps(out))
"""
    data, err = _run_snippet(workspace, snippet)
    if err:
        return {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err]}
    return data


# ---------------------------------------------------------------------------
# bugfix: README / starter (buggy) / public test / evaluate content
# ---------------------------------------------------------------------------

_README_PAGINATE_BUG = """# Pagination bug
`paginate.py` has a bug in `paginate(items, page, page_size)`: pages are
1-indexed (page 1 is the first page) but it returns the wrong slice. Fix
only the bug; do not change `total_pages` or `page_bounds`, and do not
modify `test_public.py`. Run `python3 -m unittest -v test_public.py`.
"""

_STARTER_PAGINATE_BUG = """def paginate(items, page, page_size):
    if not isinstance(items, list):
        raise TypeError("items must be a list")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive int")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive int")
    start = page * page_size  # BUG: should be (page - 1) * page_size
    end = start + page_size
    return items[start:end]


def total_pages(count, page_size):
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count must be a nonnegative int")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive int")
    if count == 0:
        return 0
    return (count + page_size - 1) // page_size


def page_bounds(page, page_size):
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive int")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive int")
    start = (page - 1) * page_size
    return start, start + page_size
"""

_FIX_PAGINATE_BUG = """def paginate(items, page, page_size):
    if not isinstance(items, list):
        raise TypeError("items must be a list")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive int")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive int")
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end]


def total_pages(count, page_size):
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count must be a nonnegative int")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive int")
    if count == 0:
        return 0
    return (count + page_size - 1) // page_size


def page_bounds(page, page_size):
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive int")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive int")
    start = (page - 1) * page_size
    return start, start + page_size
"""

_TEST_PAGINATE_BUG = """import unittest
from paginate import paginate


class Public(unittest.TestCase):
    def test_page_one(self):
        self.assertEqual(paginate([1, 2, 3, 4, 5], 1, 2), [1, 2])
"""

_PAGINATE_CASES = [
    _mk("public-page1", ([1, 2, 3, 4, 5], 1, 2), expected=[1, 2]),
    _mk("page2", ([1, 2, 3, 4, 5], 2, 2), expected=[3, 4]),
    _mk("last-partial", ([1, 2, 3, 4, 5], 3, 2), expected=[5]),
    _mk("page-beyond", ([1, 2, 3], 5, 2), expected=[]),
    _mk("bad-page", ([1, 2, 3], 0, 2), invalid=True, expected_error="ValueError"),
    _mk("bad-page-size", ([1, 2, 3], 1, 0), invalid=True, expected_error="ValueError"),
    _mk("not-a-list", ("x", 1, 2), invalid=True, expected_error="TypeError"),
]


def _evaluate_paginate_bug(workspace: Path) -> dict:
    cases = [{"id": s["id"], "args": s["args"]} for s in _PAGINATE_CASES]
    expected = {s["id"]: s for s in _PAGINATE_CASES}
    actual, err = _run_cases(workspace, "paginate", "paginate", cases)
    score1 = _score_cases(actual, err, expected)
    snippet = """
import json as _json
from paginate import total_pages, page_bounds
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
check("total-pages", total_pages(5, 2) == 3)
check("total-pages-zero", total_pages(0, 2) == 0)
check("page-bounds", page_bounds(2, 2) == [2, 4] or page_bounds(2, 2) == (2, 4))
print(_json.dumps(out))
"""
    data, err2 = _run_snippet(workspace, snippet)
    score2 = data if not err2 else {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err2]}
    return _merge_scores(score1, score2)


_README_SESSION_TTL_BUG = """# Session TTL bug
`session_ttl.py`'s `session_ttl_expired(created_iso, ttl_seconds, now_iso)`
raises an error for valid timezone-aware ISO 8601 timestamps (e.g. ending in
`+00:00`) instead of returning whether `now_iso` is at least `ttl_seconds`
after `created_iso`. Find and fix the bug; do not change
`format_expiry_message` or `test_public.py`. Run
`python3 -m unittest -v test_public.py`.
"""

_STARTER_SESSION_TTL_BUG = """from datetime import datetime


def session_ttl_expired(created_iso, ttl_seconds, now_iso):
    if not isinstance(created_iso, str) or not isinstance(now_iso, str):
        raise TypeError("timestamps must be strings")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 0:
        raise ValueError("ttl_seconds must be a nonnegative int")
    created = datetime.fromisoformat(created_iso)
    now = datetime.fromisoformat(now_iso).replace(tzinfo=None)  # BUG: drops tzinfo asymmetrically
    elapsed = (now - created).total_seconds()
    return elapsed >= ttl_seconds


def format_expiry_message(session_id, expired):
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a nonempty string")
    status = "expired" if expired else "active"
    return f"session {session_id} is {status}"
"""

_FIX_SESSION_TTL_BUG = """from datetime import datetime


def session_ttl_expired(created_iso, ttl_seconds, now_iso):
    if not isinstance(created_iso, str) or not isinstance(now_iso, str):
        raise TypeError("timestamps must be strings")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 0:
        raise ValueError("ttl_seconds must be a nonnegative int")
    created = datetime.fromisoformat(created_iso)
    now = datetime.fromisoformat(now_iso)
    elapsed = (now - created).total_seconds()
    return elapsed >= ttl_seconds


def format_expiry_message(session_id, expired):
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a nonempty string")
    status = "expired" if expired else "active"
    return f"session {session_id} is {status}"
"""

_TEST_SESSION_TTL_BUG = """import unittest
from session_ttl import session_ttl_expired


class Public(unittest.TestCase):
    def test_expired(self):
        self.assertTrue(
            session_ttl_expired("2024-01-01T00:00:00+00:00", 60, "2024-01-01T00:02:00+00:00")
        )
"""

_SESSION_TTL_CASES = [
    _mk("public-expired", ("2024-01-01T00:00:00+00:00", 60, "2024-01-01T00:02:00+00:00"), expected=True),
    _mk("not-expired", ("2024-01-01T00:00:00+00:00", 120, "2024-01-01T00:01:00+00:00"), expected=False),
    _mk("exact-boundary", ("2024-01-01T00:00:00+00:00", 60, "2024-01-01T00:01:00+00:00"), expected=True),
    _mk("zero-ttl", ("2024-01-01T00:00:00+00:00", 0, "2024-01-01T00:00:00+00:00"), expected=True),
    _mk("bad-ttl", ("2024-01-01T00:00:00+00:00", -1, "2024-01-01T00:00:00+00:00"), invalid=True, expected_error="ValueError"),
    _mk("bad-type", (1, 60, "2024-01-01T00:00:00+00:00"), invalid=True, expected_error="TypeError"),
]


def _evaluate_session_ttl_bug(workspace: Path) -> dict:
    cases = [{"id": s["id"], "args": s["args"]} for s in _SESSION_TTL_CASES]
    expected = {s["id"]: s for s in _SESSION_TTL_CASES}
    actual, err = _run_cases(workspace, "session_ttl_expired", "session_ttl", cases)
    score1 = _score_cases(actual, err, expected)
    snippet = """
import json as _json
from session_ttl import format_expiry_message
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
check("format-active", format_expiry_message("s1", False) == "session s1 is active")
check("format-expired", format_expiry_message("s1", True) == "session s1 is expired")
print(_json.dumps(out))
"""
    data, err2 = _run_snippet(workspace, snippet)
    score2 = data if not err2 else {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err2]}
    return _merge_scores(score1, score2)


_README_ADD_TAG_BUG = """# Tag aliasing bug
`tag_util.py`'s `add_tag(record, tag, tags=[])` uses a mutable default
argument for `tags`, so tags leak between unrelated calls that omit `tags`.
Fix `add_tag` so each call that omits `tags` starts from a fresh empty list
(unless the caller explicitly supplies `tags`, in which case work with that
list as given). Do not change `remove_tag` or `test_public.py`. Run
`python3 -m unittest -v test_public.py`.
"""

_STARTER_ADD_TAG_BUG = """def add_tag(record, tag, tags=[]):  # BUG: mutable default argument
    tags.append(tag)
    record["tags"] = tags
    return record


def remove_tag(record, tag):
    if "tags" in record and tag in record["tags"]:
        record["tags"].remove(tag)
    return record
"""

_FIX_ADD_TAG_BUG = """def add_tag(record, tag, tags=None):
    if tags is None:
        tags = []
    tags.append(tag)
    record["tags"] = tags
    return record


def remove_tag(record, tag):
    if "tags" in record and tag in record["tags"]:
        record["tags"].remove(tag)
    return record
"""

_TEST_ADD_TAG_BUG = """import unittest
from tag_util import add_tag


class Public(unittest.TestCase):
    def test_no_leak(self):
        add_tag({}, "a")
        r2 = add_tag({}, "b")
        self.assertEqual(r2["tags"], ["b"])
"""

_ADD_TAG_CASES = [
    _mk("first-call", ({}, "a"), expected={"tags": ["a"]}),
    _mk("second-call-no-leak", ({}, "b"), expected={"tags": ["b"]}),
    _mk("third-call-no-leak", ({}, "c"), expected={"tags": ["c"]}),
    _mk("explicit-tags", ({"existing": 1}, "x", ["pre"]), expected={"existing": 1, "tags": ["pre", "x"]}),
]


def _evaluate_add_tag_bug(workspace: Path) -> dict:
    cases = [{"id": s["id"], "args": s["args"]} for s in _ADD_TAG_CASES]
    expected = {s["id"]: s for s in _ADD_TAG_CASES}
    actual, err = _run_cases(workspace, "add_tag", "tag_util", cases)
    score1 = _score_cases(actual, err, expected)
    snippet = """
import json as _json
from tag_util import remove_tag
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
r = {"tags": ["a", "b"]}
remove_tag(r, "a")
check("remove-tag", r["tags"] == ["b"])
print(_json.dumps(out))
"""
    data, err2 = _run_snippet(workspace, snippet)
    score2 = data if not err2 else {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err2]}
    return _merge_scores(score1, score2)


_README_MERGE_CONFIG_BUG = """# Config merge precedence bug
`config_merge.py`'s `merge_config(base, override)` is supposed to return a
dict where `override`'s values win over `base`'s for any shared key, and all
keys from both dicts are present. It currently does the opposite. Fix only
this function; do not change `diff_keys` or `test_public.py`. Run
`python3 -m unittest -v test_public.py`.
"""

_STARTER_MERGE_CONFIG_BUG = """def merge_config(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise TypeError("base and override must be dicts")
    return {**override, **base}  # BUG: override should win, not base


def diff_keys(base, override):
    return sorted(k for k in override if k not in base or base[k] != override[k])
"""

_FIX_MERGE_CONFIG_BUG = """def merge_config(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise TypeError("base and override must be dicts")
    return {**base, **override}


def diff_keys(base, override):
    return sorted(k for k in override if k not in base or base[k] != override[k])
"""

_TEST_MERGE_CONFIG_BUG = """import unittest
from config_merge import merge_config


class Public(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(
            merge_config({"a": 1, "b": 2}, {"b": 9, "c": 3}), {"a": 1, "b": 9, "c": 3}
        )
"""

_MERGE_CONFIG_CASES = [
    _mk("public", ({"a": 1, "b": 2}, {"b": 9, "c": 3}), expected={"a": 1, "b": 9, "c": 3}),
    _mk("override-new-key", ({"x": 1}, {"y": 2}), expected={"x": 1, "y": 2}),
    _mk("empty-override", ({"a": 1}, {}), expected={"a": 1}),
    _mk("empty-base", ({}, {"a": 1}), expected={"a": 1}),
    _mk("bad-type", ("x", {}), invalid=True, expected_error="TypeError"),
]


def _evaluate_merge_config_bug(workspace: Path) -> dict:
    cases = [{"id": s["id"], "args": s["args"]} for s in _MERGE_CONFIG_CASES]
    expected = {s["id"]: s for s in _MERGE_CONFIG_CASES}
    actual, err = _run_cases(workspace, "merge_config", "config_merge", cases)
    score1 = _score_cases(actual, err, expected)
    snippet = """
import json as _json
from config_merge import diff_keys
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
check("diff-keys", diff_keys({"a": 1, "b": 2}, {"b": 9, "c": 3}) == ["b", "c"])
print(_json.dumps(out))
"""
    data, err2 = _run_snippet(workspace, snippet)
    score2 = data if not err2 else {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err2]}
    return _merge_scores(score1, score2)


_README_AVERAGE_SCORE_BUG = """# Average rounding bug
`scoring.py`'s `average_score(scores)` truncates instead of rounding to the
nearest integer (round-half-up: a fractional part of exactly 0.5 rounds up).
Fix only this function; do not change `score_grade` or `test_public.py`. Run
`python3 -m unittest -v test_public.py`.
"""

_STARTER_AVERAGE_SCORE_BUG = """def average_score(scores):
    if not isinstance(scores, list) or not scores:
        raise ValueError("scores must be a nonempty list")
    for s in scores:
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError("scores must be ints")
    return sum(scores) // len(scores)  # BUG: truncates instead of rounding


def score_grade(average):
    if average >= 90:
        return "A"
    if average >= 80:
        return "B"
    if average >= 70:
        return "C"
    return "F"
"""

_FIX_AVERAGE_SCORE_BUG = """def average_score(scores):
    if not isinstance(scores, list) or not scores:
        raise ValueError("scores must be a nonempty list")
    for s in scores:
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError("scores must be ints")
    total = sum(scores)
    n = len(scores)
    return (total * 2 + n) // (2 * n)


def score_grade(average):
    if average >= 90:
        return "A"
    if average >= 80:
        return "B"
    if average >= 70:
        return "C"
    return "F"
"""

_TEST_AVERAGE_SCORE_BUG = """import unittest
from scoring import average_score


class Public(unittest.TestCase):
    def test_rounds_up(self):
        self.assertEqual(average_score([1, 2]), 2)
"""

_AVERAGE_SCORE_CASES = [
    _mk("public", ([1, 2],), expected=2),
    _mk("exact", ([2, 4, 6],), expected=4),
    _mk("round-down", ([1, 1, 2],), expected=1),
    _mk("round-half-up", ([3, 4],), expected=4),
    _mk("empty", ([],), invalid=True, expected_error="ValueError"),
    _mk("bad-type", ([1, "x"],), invalid=True, expected_error="ValueError"),
]


def _evaluate_average_score_bug(workspace: Path) -> dict:
    cases = [{"id": s["id"], "args": s["args"]} for s in _AVERAGE_SCORE_CASES]
    expected = {s["id"]: s for s in _AVERAGE_SCORE_CASES}
    actual, err = _run_cases(workspace, "average_score", "scoring", cases)
    score1 = _score_cases(actual, err, expected)
    snippet = """
import json as _json
from scoring import score_grade
out = {"checks": 0, "passed": 0, "failed": 0, "failure_labels": []}
def check(label, cond):
    out["checks"] += 1
    if cond:
        out["passed"] += 1
    else:
        out["failed"] += 1
        out["failure_labels"].append(label)
check("grade-a", score_grade(95) == "A")
check("grade-f", score_grade(10) == "F")
print(_json.dumps(out))
"""
    data, err2 = _run_snippet(workspace, snippet)
    score2 = data if not err2 else {"checks": 1, "passed": 0, "failed": 1, "failure_labels": [err2]}
    return _merge_scores(score1, score2)


# ---------------------------------------------------------------------------
# answer: synthetic codebases
# ---------------------------------------------------------------------------

_ANSWER_AUDIT_FILES = {
    "README.md": """# Trace the audit log key

Read every file in this directory. `service.checkout(order_id)` is the only
entry point that triggers an audit log write.

Question: what is the exact string key written into the audit log dict when
`service.checkout("7781")` is called?

Answer with the exact key as a single token on your final `ANSWER:` line.
""",
    "config.py": '''"""Shared configuration constants."""

AUDIT_PREFIX = "AUD"
METRICS_PREFIX = "MET"
''',
    "audit.py": '''"""The only module in this codebase that writes to the audit log."""
from config import AUDIT_PREFIX


def _format_key(kind, ident):
    return f"{AUDIT_PREFIX}-{kind.upper()}-{ident}"


def write_audit(kind, ident, log=None):
    log = {} if log is None else log
    key = _format_key(kind, ident)
    log[key] = True
    return log
''',
    "service.py": '''"""Order checkout flow."""
from audit import write_audit


def checkout(order_id):
    write_audit("order", order_id)
    return order_id
''',
    "decoy_metrics.py": '''"""Looks similar to audit.py but writes to an in-memory metrics dict,
never to the audit log."""
from config import METRICS_PREFIX


def _format_metric_key(kind, ident):
    return f"{METRICS_PREFIX}-{kind.upper()}-{ident}"


def record_metric(kind, ident, metrics=None):
    metrics = {} if metrics is None else metrics
    metrics[_format_metric_key(kind, ident)] = 1
    return metrics
''',
    "decoy_cache.py": '''"""Unrelated in-memory cache helper. Never touches the audit log."""

_CACHE = {}


def cache_get(key, default=None):
    return _CACHE.get(key, default)


def cache_set(key, value):
    _CACHE[key] = value
    return value
''',
}

_ANSWER_FEE_FILES = {
    "README.md": """# Trace the computed fee

Read every file in this directory. `service2.compute_fee(amount_cents, tier)`
is the only entry point; it calls into exactly two of the other modules.

Question: what integer does `service2.compute_fee(1000, "gold")` return?

Answer with the exact integer as a single token on your final `ANSWER:` line.
""",
    "pricing.py": '''"""Base fee calculation."""

BASE_FEE = 500


def base_fee(amount_cents):
    return BASE_FEE + amount_cents // 10
''',
    "discounts.py": '''"""Loyalty tier discounts."""

TIERS = {"bronze": 0, "silver": 10, "gold": 20, "platinum": 30}


def apply_discount(fee, tier):
    pct = TIERS.get(tier, 0)
    return fee - (fee * pct) // 100
''',
    "service2.py": '''"""Fee computation entry point."""
from pricing import base_fee
from discounts import apply_discount


def compute_fee(amount_cents, tier):
    fee = base_fee(amount_cents)
    return apply_discount(fee, tier)
''',
    "decoy_shipping.py": '''"""Unrelated shipping fee helper; not used by compute_fee."""

SHIPPING_BASE = 500


def compute_shipping_fee(weight_grams):
    return SHIPPING_BASE + weight_grams // 5
''',
    "decoy_tax.py": '''"""Looks like it could apply to compute_fee, but nothing imports it."""

TIERS = {"bronze": 5, "silver": 15, "gold": 25, "platinum": 35}


def apply_tax(fee, tier):
    pct = TIERS.get(tier, 0)
    return fee + (fee * pct) // 100
''',
}

_ANSWER_SQLITE_FILES = {
    "README.md": """# Find the module that talks to SQLite

Read every file in this directory.

Question: which module (the filename without the `.py` extension) is the
only one that imports the `sqlite3` standard library module?

Answer with the exact module name as a single token on your final `ANSWER:`
line.
""",
    "storage.py": '''"""Persists records to a local SQLite database."""
import sqlite3


def connect(path):
    return sqlite3.connect(path)
''',
    "cache.py": '''"""In-memory cache, no persistence."""

_CACHE = {}


def get(key, default=None):
    return _CACHE.get(key, default)
''',
    "network.py": '''"""Tiny HTTP-ish request helper, no persistence."""


def build_url(host, path):
    return f"https://{host}{path}"
''',
    "decoy_db_helpers.py": '''"""Mentions 'sqlite' in comments and strings, but never imports the
sqlite3 module."""

DB_KIND = "sqlite-like"


def describe():
    return f"backing store: {DB_KIND}"
''',
    "utils.py": '''"""Generic helpers, no database access."""


def clamp(value, low, high):
    return max(low, min(high, value))
''',
}

_ANSWER_PORT_FILES = {
    "README.md": """# Find the default port

Read every file in this directory.

Question: what port does `settings.get_port()` return when the
`SERVICE_PORT` environment variable is not set?

Answer with the exact integer as a single token on your final `ANSWER:`
line.
""",
    "settings.py": '''"""Service network settings."""
import os

DEFAULT_PORT = 8765


def get_port():
    value = os.environ.get("SERVICE_PORT")
    if value is None:
        return DEFAULT_PORT
    return int(value)
''',
    "server.py": '''"""Starts the service using the configured port."""
from settings import get_port


def describe_binding():
    return f"listening on port {get_port()}"
''',
    "decoy_constants.py": '''"""Unrelated constants for a different, unused service."""

PORT = 9999
HOST = "0.0.0.0"
''',
    "decoy_client.py": '''"""A client that talks to some other service on a hardcoded port,
unrelated to settings.get_port()."""

REMOTE_PORT = 443


def remote_url(host):
    return f"https://{host}:{REMOTE_PORT}"
''',
    "main4.py": '''"""Entry point that wires the server together."""
from server import describe_binding


def run():
    print(describe_binding())
''',
}

_ANSWER_EXCEPTION_FILES = {
    "README.md": """# Count the distinct exceptions

Read `validators.py` carefully (and only `validators.py` for this count;
the other files are provided for context but are not part of the count).

Question: how many distinct exception classes are raised (via a `raise`
statement) anywhere in `validators.py`? Count each class once even if it is
raised more than once.

Answer with the exact integer as a single token on your final `ANSWER:`
line.
""",
    "validators.py": '''class InvalidEmailError(ValueError):
    pass


class InvalidAgeError(ValueError):
    pass


class InvalidNameError(ValueError):
    pass


def validate_email(value):
    if "@" not in value:
        raise InvalidEmailError(f"bad email: {value}")
    return value


def validate_age(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("age must be int")
    if value < 0 or value > 150:
        raise InvalidAgeError(f"bad age: {value}")
    return value


def validate_name(value):
    if not value or not value.strip():
        raise InvalidNameError("name is empty")
    if len(value) > 100:
        raise InvalidNameError("name too long")
    return value


def validate_email_or_default(value, default):
    try:
        return validate_email(value)
    except InvalidEmailError:
        return default
''',
    "helpers.py": '''"""Thin wrapper around validators, raises nothing of its own."""
from validators import validate_email, validate_age, validate_name


def validate_all(email, age, name):
    validate_email(email)
    validate_age(age)
    validate_name(name)
    return True
''',
    "decoy_parsers.py": '''"""Raises its own exceptions, but this file is not validators.py."""


class ParseError(Exception):
    pass


def parse_int(value):
    try:
        return int(value)
    except ValueError as e:
        raise ParseError(str(e))
''',
    "decoy_config.py": '''"""Unrelated configuration loader, raises nothing."""


def load_defaults():
    return {"retries": 3, "timeout": 5}
''',
    "main5.py": '''"""Entry point that exercises the validators."""
from helpers import validate_all


def run():
    return validate_all("a@b.com", 30, "Ann")
''',
}


def _answer_task(name: str, split_name: str, files: dict, expected_answer: str) -> Task:
    return Task(
        name=name,
        family="answer",
        split=split_name,
        kind="answer",
        prompt=(
            "Read README.md and every other file in this directory, then "
            "answer the question precisely." + PROMPT_SUFFIX
        ),
        files=files,
        protected=("README.md",),
        expected_answer=expected_answer,
        evaluate=_answer_evaluate,
    )


# ---------------------------------------------------------------------------
# Task assembly
# ---------------------------------------------------------------------------

TASKS: dict[str, Task] = {}


def _add(task: Task) -> None:
    TASKS[task.name] = task


_add(Task(
    name="repair_parse_duration",
    family="repair",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, then repair `solution.py` so it "
        "satisfies the documented contract. Verify with "
        "`python3 -m unittest -v test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_PARSE_DURATION, "solution.py": _STARTER_PARSE_DURATION, "test_public.py": _TEST_PARSE_DURATION},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_make_repair_evaluate("parse_duration", _oracle_parse_duration, _gen_duration_arg, _PARSE_DURATION_BOUNDARY),
))

_add(Task(
    name="repair_merge_intervals",
    family="repair",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, then repair `solution.py` so it "
        "satisfies the documented contract. Verify with "
        "`python3 -m unittest -v test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_MERGE_INTERVALS, "solution.py": _STARTER_MERGE_INTERVALS, "test_public.py": _TEST_MERGE_INTERVALS},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_make_repair_evaluate("merge_intervals", _oracle_merge_intervals, _gen_intervals_arg, _MERGE_INTERVALS_BOUNDARY),
))

_add(Task(
    name="repair_semver_compare",
    family="repair",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, then repair `solution.py` so it "
        "satisfies the documented contract. Verify with "
        "`python3 -m unittest -v test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_SEMVER_COMPARE, "solution.py": _STARTER_SEMVER_COMPARE, "test_public.py": _TEST_SEMVER_COMPARE},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_make_repair_evaluate("semver_compare", _oracle_semver_compare, _gen_semver_arg, _SEMVER_BOUNDARY),
))

_add(Task(
    name="repair_tokenize_kv",
    family="repair",
    split="holdout",
    kind="code",
    prompt=(
        "Read README.md in this directory, then repair `solution.py` so it "
        "satisfies the documented contract. Verify with "
        "`python3 -m unittest -v test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_TOKENIZE_KV, "solution.py": _STARTER_TOKENIZE_KV, "test_public.py": _TEST_TOKENIZE_KV},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_make_repair_evaluate("tokenize_kv", _oracle_tokenize_kv, _gen_kv_arg, _TOKENIZE_KV_BOUNDARY),
))

_add(Task(
    name="repair_word_wrap",
    family="repair",
    split="holdout",
    kind="code",
    prompt=(
        "Read README.md in this directory, then repair `solution.py` so it "
        "satisfies the documented contract. Verify with "
        "`python3 -m unittest -v test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_WORD_WRAP, "solution.py": _STARTER_WORD_WRAP, "test_public.py": _TEST_WORD_WRAP},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_make_repair_evaluate("word_wrap", _oracle_word_wrap, _gen_wrap_arg, _WORD_WRAP_BOUNDARY),
))

_add(Task(
    name="edit_cli_dry_run",
    family="edit",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, then make the exact change it "
        "describes to `cli_tool.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_CLI_DRY_RUN, "cli_tool.py": _STARTER_CLI_DRY_RUN},
    protected=("README.md",),
    expected_answer=None,
    evaluate=_evaluate_cli_dry_run,
))

_add(Task(
    name="edit_dequeue_validation",
    family="edit",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, then make the exact change it "
        "describes to `queue_util.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_DEQUEUE_VALIDATION, "queue_util.py": _STARTER_DEQUEUE_VALIDATION},
    protected=("README.md",),
    expected_answer=None,
    evaluate=_evaluate_dequeue,
))

_add(Task(
    name="edit_record_to_json",
    family="edit",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, then make the exact change it "
        "describes to `record.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_RECORD_TO_JSON, "record.py": _STARTER_RECORD_TO_JSON},
    protected=("README.md",),
    expected_answer=None,
    evaluate=_evaluate_record_to_json,
))

_add(Task(
    name="edit_clean_text_strict",
    family="edit",
    split="holdout",
    kind="code",
    prompt=(
        "Read README.md in this directory, then make the exact change it "
        "describes to `normalize.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_CLEAN_TEXT_STRICT, "normalize.py": _STARTER_CLEAN_TEXT_STRICT},
    protected=("README.md",),
    expected_answer=None,
    evaluate=_evaluate_clean_text_strict,
))

_add(Task(
    name="edit_point_repr",
    family="edit",
    split="holdout",
    kind="code",
    prompt=(
        "Read README.md in this directory, then make the exact change it "
        "describes to `point.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_POINT_REPR, "point.py": _STARTER_POINT_REPR},
    protected=("README.md",),
    expected_answer=None,
    evaluate=_evaluate_point_repr,
))

_add(Task(
    name="bugfix_paginate_off_by_one",
    family="bugfix",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, find the bug in `paginate.py`, "
        "and fix it so `python3 -m unittest -v test_public.py` passes. Do "
        "not modify `test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_PAGINATE_BUG, "paginate.py": _STARTER_PAGINATE_BUG, "test_public.py": _TEST_PAGINATE_BUG},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_evaluate_paginate_bug,
))

_add(Task(
    name="bugfix_session_ttl_naive_tz",
    family="bugfix",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, find the bug in `session_ttl.py`, "
        "and fix it so `python3 -m unittest -v test_public.py` passes. Do "
        "not modify `test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_SESSION_TTL_BUG, "session_ttl.py": _STARTER_SESSION_TTL_BUG, "test_public.py": _TEST_SESSION_TTL_BUG},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_evaluate_session_ttl_bug,
))

_add(Task(
    name="bugfix_add_tag_mutable_default",
    family="bugfix",
    split="dev",
    kind="code",
    prompt=(
        "Read README.md in this directory, find the bug in `tag_util.py`, "
        "and fix it so `python3 -m unittest -v test_public.py` passes. Do "
        "not modify `test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_ADD_TAG_BUG, "tag_util.py": _STARTER_ADD_TAG_BUG, "test_public.py": _TEST_ADD_TAG_BUG},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_evaluate_add_tag_bug,
))

_add(Task(
    name="bugfix_merge_config_precedence",
    family="bugfix",
    split="holdout",
    kind="code",
    prompt=(
        "Read README.md in this directory, find the bug in "
        "`config_merge.py`, and fix it so "
        "`python3 -m unittest -v test_public.py` passes. Do not modify "
        "`test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_MERGE_CONFIG_BUG, "config_merge.py": _STARTER_MERGE_CONFIG_BUG, "test_public.py": _TEST_MERGE_CONFIG_BUG},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_evaluate_merge_config_bug,
))

_add(Task(
    name="bugfix_average_score_truncation",
    family="bugfix",
    split="holdout",
    kind="code",
    prompt=(
        "Read README.md in this directory, find the bug in `scoring.py`, "
        "and fix it so `python3 -m unittest -v test_public.py` passes. Do "
        "not modify `test_public.py`." + PROMPT_SUFFIX
    ),
    files={"README.md": _README_AVERAGE_SCORE_BUG, "scoring.py": _STARTER_AVERAGE_SCORE_BUG, "test_public.py": _TEST_AVERAGE_SCORE_BUG},
    protected=("README.md", "test_public.py"),
    expected_answer=None,
    evaluate=_evaluate_average_score_bug,
))

_add(_answer_task("answer_audit_log_key", "dev", _ANSWER_AUDIT_FILES, r"AUD-ORDER-7781"))
_add(_answer_task("answer_compute_fee", "dev", _ANSWER_FEE_FILES, r"\b480\b"))
_add(_answer_task("answer_sqlite_import_module", "dev", _ANSWER_SQLITE_FILES, r"\bstorage\b"))
_add(_answer_task("answer_default_port", "holdout", _ANSWER_PORT_FILES, r"\b8765\b"))
_add(_answer_task("answer_exception_count", "holdout", _ANSWER_EXCEPTION_FILES, r"\b(4|four)\b"))


REFERENCE_SOLUTIONS: dict[str, dict[str, str]] = {
    "repair_parse_duration": {"solution.py": _FIX_PARSE_DURATION},
    "repair_merge_intervals": {"solution.py": _FIX_MERGE_INTERVALS},
    "repair_semver_compare": {"solution.py": _FIX_SEMVER_COMPARE},
    "repair_tokenize_kv": {"solution.py": _FIX_TOKENIZE_KV},
    "repair_word_wrap": {"solution.py": _FIX_WORD_WRAP},
    "edit_cli_dry_run": {"cli_tool.py": _FIX_CLI_DRY_RUN},
    "edit_dequeue_validation": {"queue_util.py": _FIX_DEQUEUE_VALIDATION},
    "edit_record_to_json": {"record.py": _FIX_RECORD_TO_JSON},
    "edit_clean_text_strict": {"normalize.py": _FIX_CLEAN_TEXT_STRICT},
    "edit_point_repr": {"point.py": _FIX_POINT_REPR},
    "bugfix_paginate_off_by_one": {"paginate.py": _FIX_PAGINATE_BUG},
    "bugfix_session_ttl_naive_tz": {"session_ttl.py": _FIX_SESSION_TTL_BUG},
    "bugfix_add_tag_mutable_default": {"tag_util.py": _FIX_ADD_TAG_BUG},
    "bugfix_merge_config_precedence": {"config_merge.py": _FIX_MERGE_CONFIG_BUG},
    "bugfix_average_score_truncation": {"scoring.py": _FIX_AVERAGE_SCORE_BUG},
}


def families() -> list[str]:
    seen: list[str] = []
    for t in TASKS.values():
        if t.family not in seen:
            seen.append(t.family)
    return seen


def split(name: str) -> list[str]:
    if name == "all":
        return list(TASKS.keys())
    if name not in ("dev", "holdout"):
        raise ValueError(f"unknown split: {name}")
    return [n for n, t in TASKS.items() if t.split == name]
