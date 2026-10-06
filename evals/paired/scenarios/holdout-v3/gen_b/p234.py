from pathlib import Path
from lib import Scn, exists, facts, numrx, rx, sections

SHA = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
HINT = "~/dev/afast-campaign-corrected-polyglot-20260919/polyglot/polyglot-benchmark"
SRC = Path(HINT).expanduser()
REPO = "https://github.com/Aider-AI/polyglot-benchmark"
PY = {"python_check": None}


def ws(sub):
    return {"kind": "git", "repo": REPO, "sha": SHA, "subdir": sub, "local_hint": HINT, "remove": [".meta"]}


# ----------------------------------------------------------------------------- P2 python/simple-linked-list (docs)
def ll_src(docs=False, repr_=False, clear=False, types=False):
    ann = (lambda a, r: f"{a}{r}") if types else (lambda a, r: "")
    def sig(name, args, ret):
        return f"    def {name}({args}){(' -> ' + ret) if types else ''}:"
    D = (lambda t: f'\n        """{t}\n        """') if docs else (lambda t: "")
    out = '''class EmptyListException(Exception):
    """Exception raised when the linked list is empty.

    message: explanation of the error.

    """

    def __init__(self, message):
        self.message = message


class Node:
    def __init__(self, value):
        self._value = value
        self._next = None

    def value(self):
        return self._value

    def next(self):
        return self._next


class LinkedIterator:
    def __init__(self, linked_list):
        self.current = linked_list._head

    def __iter__(self):
        return self

    def __next__(self):
        if self.current is None:
            raise StopIteration
        value = self.current.value()
        self.current = self.current.next()
        return value


class LinkedList:
'''
    if docs:
        out += '    """A singly linked stack of values; the most recently pushed value is the head.\n\n    >>> ll = LinkedList([1, 2, 3])\n    >>> len(ll)\n    3\n    >>> ll.head().value()\n    3\n    >>> list(ll)\n    [3, 2, 1]\n    """\n\n'
    out += sig("__init__", "self, values=None", "None") + "\n        values = values if values is not None else []\n        self._head = None\n        self._len = 0\n        for value in values:\n            self.push(value)\n\n"
    out += sig("__iter__", "self", "LinkedIterator") + "\n        return LinkedIterator(self)\n\n"
    out += sig("__len__", "self", "int") + "\n        return self._len\n\n"
    if repr_:
        out += sig("__repr__", "self", "str") + '\n        return f"LinkedList({list(self)})"\n\n'
    out += sig("head", "self", "Node") + D("The head node. Raises EmptyListException when the list is empty.\n\n        >>> LinkedList([4]).head().value()\n        4") + "\n        if self._head is None:\n            raise EmptyListException('The list is empty.')\n        return self._head\n\n"
    out += sig("push", "self, value" + (": int" if types else ""), "None") + D("Add a value at the head.\n\n        >>> ll = LinkedList()\n        >>> ll.push(5)\n        >>> ll.head().value()\n        5") + "\n        new_node = Node(value)\n        new_node._next = self._head\n        self._head = new_node\n        self._len += 1\n\n"
    out += sig("pop", "self", "int") + D("Remove and return the head value.\n\n        >>> ll = LinkedList([1, 2])\n        >>> ll.pop()\n        2\n        >>> len(ll)\n        1") + "\n        if self._head is None:\n            raise EmptyListException('The list is empty.')\n        self._len -= 1\n        ret = self._head.value()\n        self._head = self._head.next()\n        return ret\n\n"
    out += sig("reversed", "self", "'LinkedList'") + D("A new list with the values in the opposite order; the original is unchanged.\n\n        >>> list(LinkedList([1, 2, 3]).reversed())\n        [1, 2, 3]") + "\n        return LinkedList(self)\n"
    if clear:
        out += "\n" + sig("clear", "self", "None") + D("Remove every value.") + "\n        self._head = None\n        self._len = 0\n"
    return out


HID_REPR = '''import unittest

from simple_linked_list import LinkedList


class HiddenRepr(unittest.TestCase):
    def test_repr_empty(self):
        self.assertEqual(repr(LinkedList()), "LinkedList([])")

    def test_repr_values(self):
        self.assertEqual(repr(LinkedList([1, 2, 3])), "LinkedList([3, 2, 1])")

    def test_repr_after_pop(self):
        ll = LinkedList([1, 2, 3])
        ll.pop()
        self.assertEqual(repr(ll), "LinkedList([2, 1])")
'''
HID_CLEAR = '''import unittest

from simple_linked_list import EmptyListException, LinkedList


class HiddenClear(unittest.TestCase):
    def test_clear_resets_len(self):
        ll = LinkedList([1, 2, 3])
        ll.clear()
        self.assertEqual(len(ll), 0)

    def test_clear_empties_head(self):
        ll = LinkedList([1])
        ll.clear()
        with self.assertRaises(EmptyListException):
            ll.head()

    def test_clear_on_empty_list_is_fine(self):
        ll = LinkedList()
        ll.clear()
        self.assertEqual(list(ll), [])

    def test_push_after_clear(self):
        ll = LinkedList([9, 9])
        ll.clear()
        ll.push(4)
        self.assertEqual((len(ll), ll.head().value()), (1, 4))
'''
LL_README = '''# simple-linked-list

A tiny singly linked stack.

## Usage

`LinkedList(values)` pushes the values in order, so the last one becomes the head. Use `push`, `pop`, `head`, `reversed` and `len()`.

## API

`push(value)`, `pop()`, `head()`, `reversed()`, `clear()` and iteration from head to tail.

## Complexity

| operation | complexity |
|---|---|
| push | O(1) |
| pop | O(1) |
| head | O(1) |
| len | O(1) |
| reversed | O(n) |
'''
LL_CHANGE = "# Changelog\n\n## 0.2.0\n\n### Added\n\n- `__repr__` shows the values from head to tail, e.g. `LinkedList([3, 2, 1])`.\n- `clear()` removes every value.\n\n## 0.1.0\n\n- Initial linked list.\n"


CLR = "        self._head = None\n        self._len = 0\n"


def p2():
    s = Scn("py-linked-list-docs", "polyglot", "docs", "python", "Aider polyglot-benchmark python/simple-linked-list (Exercism): implement, then docstrings with runnable doctests, a complexity table, __repr__/clear against hidden tests, type hints, changelog.",
            [], protected=["simple_linked_list_test.py"], long_gaps=[4, 8])
    s.workspace = ws("python/exercises/practice/simple-linked-list")
    s.hidden = {"hidden_repr_test.py": HID_REPR, "hidden_clear_test.py": HID_CLEAR}
    base = (SRC / "python/exercises/practice/simple-linked-list/.meta/example.py").read_text(encoding="utf-8")
    t = lambda *h: {"kind": "tests", "runner": "python", "files": ["simple_linked_list_test.py"] + list(h), "restore": ["simple_linked_list_test.py"], "hidden": list(h)}
    dt = {"kind": "tests", "runner": "cmd", "cmd": "python3 -m doctest -v simple_linked_list.py", "expect_regex": r"\b([6-9]|\d{2,}) passed( and 0 failed)?\.", "timeout": 60}
    s.turn("Read .docs/instructions.md and implement the linked list in simple_linked_list.py (Node, LinkedList, EmptyListException) so that simple_linked_list_test.py passes. Do not edit the test file.",
           [t()], files={"simple_linked_list.py": base}, wrong_files={"simple_linked_list.py": base.replace("self._len -= 1", "pass")})
    s.turn("What does `head()` raise on an empty list, and what is the error message? Do not change any files.",
           [facts(all=[r"EmptyListException", r"The list is empty"])], msg="ANSWER: EmptyListException with the message 'The list is empty.'", wrong_msg="ANSWER: it returns None", bump=False)
    v3 = ll_src(docs=True)
    s.turn("Document the code: add a class docstring to LinkedList and a docstring to head, push, pop and reversed, each containing a runnable doctest example (`>>>` lines with the real output). `python3 -m doctest -v simple_linked_list.py` must pass with at least six examples and the shipped tests must still pass.",
           [rx("simple_linked_list.py", r"^\s+>>> ", 6), dt, t()], files={"simple_linked_list.py": v3}, wrong_files={"simple_linked_list.py": v3.replace("    [3, 2, 1]", "    [1, 2, 3]")})
    s.turn("Write README.md with the sections `## Usage`, `## API` and `## Complexity`. Complexity is a table (columns operation, complexity) with one row each for push, pop, head, len (all O(1)) and reversed (O(n)).",
           [sections("README.md", "Usage", "API", "Complexity"), *[rx("README.md", rf"^\|\s*`?{op}`?\s*\|\s*{c}\s*\|") for op, c in [("push", r"O\(1\)"), ("pop", r"O\(1\)"), ("head", r"O\(1\)"), ("len", r"O\(1\)"), ("reversed", r"O\(n\)")]]],
           files={"README.md": LL_README}, wrong_files={"README.md": LL_README.replace("| reversed | O(n) |", "| reversed | O(1) |")})
    v5 = ll_src(docs=True, repr_=True)
    s.turn("Add a `__repr__` to LinkedList that shows the values from head to tail, e.g. `LinkedList([3, 2, 1])` for `LinkedList([1, 2, 3])` and `LinkedList([])` when empty.",
           [t("hidden_repr_test.py"), dt], files={"simple_linked_list.py": v5}, wrong_files={"simple_linked_list.py": v5.replace('f"LinkedList({list(self)})"', 'f"LinkedList({list(self)[::-1]})"')})
    v6 = ll_src(docs=True, repr_=True, clear=True)
    s.turn("Add a `clear()` method that removes every value (len becomes 0, head() raises EmptyListException again, push works afterwards).",
           [t("hidden_repr_test.py", "hidden_clear_test.py"), dt], files={"simple_linked_list.py": v6}, wrong_files={"simple_linked_list.py": v6[:v6.rindex(CLR)] + "        self._head = None\n"})
    v7 = ll_src(docs=True, repr_=True, clear=True, types=True)
    s.turn("Add type annotations: `push(self, value: int) -> None`, `pop(self) -> int`, `__len__(self) -> int` and `clear(self) -> None`. Keep every test and doctest passing.",
           [rx("simple_linked_list.py", r"def push\(self, value: int\) -> None:"), rx("simple_linked_list.py", r"def pop\(self\) -> int:"), rx("simple_linked_list.py", r"def __len__\(self\) -> int:"), rx("simple_linked_list.py", r"def clear\(self\) -> None:"), t("hidden_repr_test.py", "hidden_clear_test.py"), dt],
           files={"simple_linked_list.py": v7}, wrong_files={"simple_linked_list.py": v6})
    s.turn("Does `reversed()` modify the original list or return a new one, and why is it O(n)? Two sentences. Do not change any files.",
           [facts(all=[r"leaves? the original|original (is|stays|remains) (unchanged|untouched|intact)|does not (modify|mutate|change)|not (modif|mutat)", r"every|each|all (the )?(nodes|values|elements)|visits|iterates|linear"])], msg="ANSWER: it returns a new list and leaves the original unchanged; it is O(n) because it visits every node once to push it onto the new list",
           wrong_msg="ANSWER: it modifies the list", bump=False)
    s.turn("Create CHANGELOG.md with `## 0.2.0` / `### Added` listing `__repr__` and `clear()` (names in backticks, one bullet each) above a `## 0.1.0` section.",
           [rx("CHANGELOG.md", r"^## 0\.2\.0"), rx("CHANGELOG.md", r"^### Added"), rx("CHANGELOG.md", r"^- `__repr__`"), rx("CHANGELOG.md", r"^- `clear\(\)`"), rx("CHANGELOG.md", r"^## 0\.1\.0")],
           files={"CHANGELOG.md": LL_CHANGE}, wrong_files={"CHANGELOG.md": LL_CHANGE.replace("- `clear()`", "- clear")})
    return s


# ----------------------------------------------------------------------------- P3 go/crypto-square (mixed)
def cs_src(decode=False, rect=False, normalize=False, docs=False):
    c = (lambda t: f"// {t}\n") if docs else (lambda t: "")
    out = (c("Package cryptosquare implements the square-code cipher.") + "package cryptosquare\n\nimport (\n\t\"math\"\n\t\"strings\"\n)\n\n")
    out += "func norm(r rune) rune {\n\tswitch {\n\tcase r >= 'a' && r <= 'z' || r >= '0' && r <= '9':\n\t\treturn r\n\tcase r >= 'A' && r <= 'Z':\n\t\treturn r + 'a' - 'A'\n\t}\n\treturn -1\n}\n\n"
    if normalize:
        out += c("Normalize lower-cases s and drops everything except letters and digits.") + "func Normalize(s string) string {\n\treturn strings.Map(norm, s)\n}\n\n"
    out += c("Encode returns the square-code ciphertext of pt: the normalised text is read column by column and the columns are joined with spaces.")
    out += "func Encode(pt string) string {\n\tpt = " + ("Normalize(pt)" if normalize else "strings.Map(norm, pt)") + "\n\tnumCols := int(math.Ceil(math.Sqrt(float64(len(pt)))))\n\tpadding := numCols*(numCols-1) - len(pt)\n\tif padding < 0 {\n\t\tpadding = numCols*numCols - len(pt)\n\t}\n\tcols := make([]string, numCols)\n\tfor i, r := range pt {\n\t\tcols[i%numCols] += string(r)\n\t}\n\tfor i := 0; i < padding; i++ {\n\t\tcols[numCols-i-1] += \" \"\n\t}\n\treturn strings.Join(cols, \" \")\n}\n"
    if decode:
        out += "\n" + c("Decode reverses Encode and returns the normalised plaintext.") + "func Decode(ct string) string {\n\tn := len(ct)\n\tfor c := 1; c <= n+1; c++ {\n\t\tfor _, rows := range []int{c, c - 1} {\n\t\t\tif rows >= 1 && c*rows+c-1 == n {\n\t\t\t\tvar sb strings.Builder\n\t\t\t\tfor r := 0; r < rows; r++ {\n\t\t\t\t\tfor i := 0; i < c; i++ {\n\t\t\t\t\t\tsb.WriteByte(ct[i*(rows+1)+r])\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t\treturn strings.ReplaceAll(sb.String(), \" \", \"\")\n\t\t\t}\n\t\t}\n\t}\n\treturn \"\"\n}\n"
    if rect:
        out += "\n" + c("Rectangle returns the number of rows and columns used to encode pt (0, 0 when it has no letters or digits).") + "func Rectangle(pt string) (rows, cols int) {\n\tn := len(strings.Map(norm, pt))\n\tif n == 0 {\n\t\treturn 0, 0\n\t}\n\tcols = int(math.Ceil(math.Sqrt(float64(n))))\n\tif cols*(cols-1) >= n {\n\t\treturn cols - 1, cols\n\t}\n\treturn cols, cols\n}\n"
    return out


GO_DECODE = '''package cryptosquare

import "testing"

func TestHiddenDecodeRoundTrip(t *testing.T) {
	want := map[string]string{
		"s#$%^&plunk":                              "splunk",
		"1, 2, 3 GO!":                              "123go",
		"1234":                                     "1234",
		"123456789abc":                             "123456789abc",
		"Never vex thine heart with idle woes":     "nevervexthineheartwithidlewoes",
		"ZOMG! ZOMBIES!!!":                         "zomgzombies",
		"Time is an illusion. Lunchtime doubly so.": "timeisanillusionlunchtimedoublyso",
	}
	for in, norm := range want {
		if got := Decode(Encode(in)); got != norm {
			t.Errorf("Decode(Encode(%q)) = %q, want %q", in, got, norm)
		}
	}
}

func TestHiddenDecodeKnownCipher(t *testing.T) {
	if got := Decode("wneiaw eorene awssci liprer lneoid ktcms "); got != "weallknowinterspeciesromanceisweird" {
		t.Errorf("got %q", got)
	}
	if got := Decode(""); got != "" {
		t.Errorf("empty: %q", got)
	}
}
'''
GO_RECT = '''package cryptosquare

import "testing"

func TestHiddenRectangle(t *testing.T) {
	cases := []struct {
		in         string
		rows, cols int
	}{{"s#$%^&plunk", 2, 3}, {"123456789", 3, 3}, {"1234", 2, 2}, {"123456789abc", 3, 4}, {"", 0, 0}, {"!!!", 0, 0}, {"a", 1, 1}}
	for _, c := range cases {
		if r, k := Rectangle(c.in); r != c.rows || k != c.cols {
			t.Errorf("Rectangle(%q) = %d,%d want %d,%d", c.in, r, k, c.rows, c.cols)
		}
	}
}
'''
GO_NORM = '''package cryptosquare

import "testing"

func TestHiddenNormalize(t *testing.T) {
	cases := map[string]string{"Hello, World!": "helloworld", "1, 2, 3 GO!": "123go", "": "", "---": "", "MiXeD 42": "mixed42"}
	for in, want := range cases {
		if got := Normalize(in); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
}
'''
GO_EXTRA = '''package cryptosquare

import "testing"

func TestExtraEncodeSquare(t *testing.T) {
	if got := Encode("123456789"); got != "147 258 369" {
		t.Errorf("got %q", got)
	}
}

func TestExtraEncodeEmpty(t *testing.T) {
	if got := Encode(""); got != "" {
		t.Errorf("got %q", got)
	}
}

func TestExtraDecodeRoundTrip(t *testing.T) {
	if got := Decode(Encode("Vampires are people too!")); got != "vampiresarepeopletoo" {
		t.Errorf("got %q", got)
	}
}

func TestExtraRectangle(t *testing.T) {
	if r, c := Rectangle("123456789abc"); r != 3 || c != 4 {
		t.Errorf("got %d,%d", r, c)
	}
}

func TestExtraNormalize(t *testing.T) {
	if got := Normalize("A-b C"); got != "abc" {
		t.Errorf("got %q", got)
	}
}
'''
CS_README = '''# crypto-square

## Usage

`Encode(text)` returns the square-code ciphertext; `Decode(cipher)` reverses it; `Rectangle(text)` reports the rows and columns; `Normalize(text)` is the clean-up step.

## Algorithm

Normalise to lower-case letters and digits, lay the text out in a rectangle with c columns and r rows where c >= r and c - r <= 1, read it column by column and join the columns with spaces; short columns are padded with a space.

## Examples

```go
Encode("s#$%^&plunk")                           // "su pn lk"
Encode("We all know interspecies romance is weird.") // "wneiaw eorene awssci liprer lneoid ktcms "
Decode("su pn lk")                              // "splunk"
rows, cols := Rectangle("s#$%^&plunk")          // 2, 3
```
'''


def p3():
    s = Scn("go-crypto-docs", "polyglot", "mixed", "go", "Aider polyglot-benchmark go/crypto-square (Exercism): implement Encode, add Decode/Rectangle/Normalize against hidden tests, then Go doc comments, a README with exact cipher examples and extra tests.",
            [], protected=["crypto_square_test.go"])
    s.workspace = ws("go/exercises/practice/crypto-square")
    s.hidden = {"hidden_decode_test.go": GO_DECODE, "hidden_rect_test.go": GO_RECT, "hidden_norm_test.go": GO_NORM}
    base = (SRC / "go/exercises/practice/crypto-square/.meta/example.go").read_text(encoding="utf-8")
    t = lambda *h: {"kind": "tests", "runner": "go", "restore": ["crypto_square_test.go"], "hidden": list(h)}
    s.turn("Read .docs/instructions.md and implement `Encode` in crypto_square.go so that `go test ./...` passes. Do not edit the provided test file.",
           [t()], files={"crypto_square.go": base}, wrong_files={"crypto_square.go": base.replace("numCols*(numCols-1) - len(pt)", "numCols*numCols - len(pt)")})
    s.turn("Add `func Decode(ct string) string` to crypto_square.go: it reverses Encode and returns the normalised plaintext (lower-case letters and digits only, padding removed). Decode of the empty string is the empty string.",
           [t("hidden_decode_test.go")], files={"crypto_square.go": cs_src(decode=True)}, wrong_files={"crypto_square.go": cs_src(decode=True).replace('strings.ReplaceAll(sb.String(), " ", "")', "sb.String()")})
    s.turn("What is the padding rule: when are spaces added to the encoded columns, and how many? Answer in two sentences. Do not change any files.",
           [facts(all=[r"pad|space", r"column|chunk", r"rectangle|row|short|incomplete|c\s*-\s*r|square"])], msg="ANSWER: when the text does not fill the rectangle, the last columns are padded with one trailing space each so every chunk has the same number of rows",
           wrong_msg="ANSWER: no padding is ever added", bump=False)
    s.turn("Add `func Rectangle(pt string) (rows, cols int)` returning the dimensions Encode uses for pt (columns c = ceil(sqrt(n)) of the normalised length n; rows is c-1 when c*(c-1) >= n, otherwise c). It returns 0, 0 when pt has no letters or digits.",
           [t("hidden_decode_test.go", "hidden_rect_test.go")], files={"crypto_square.go": cs_src(decode=True, rect=True)}, wrong_files={"crypto_square.go": cs_src(decode=True, rect=True).replace("cols*(cols-1) >= n", "cols*(cols-1) > n")})
    s.turn("Export the normalisation step as `func Normalize(s string) string` (lower-case letters and digits only) and make `Encode` use it.",
           [t("hidden_decode_test.go", "hidden_rect_test.go", "hidden_norm_test.go"), rx("crypto_square.go", r"Normalize\(pt\)")], files={"crypto_square.go": cs_src(decode=True, rect=True, normalize=True)},
           wrong_files={"crypto_square.go": cs_src(decode=True, rect=True, normalize=True).replace("strings.Map(norm, s)", "s")})
    full = t("hidden_decode_test.go", "hidden_rect_test.go", "hidden_norm_test.go")
    s.turn("Add Go doc comments: a package comment starting `// Package cryptosquare` and a comment starting with the function name for each of Encode, Decode, Rectangle and Normalize. No behaviour change.",
           [rx("crypto_square.go", r"^// Package cryptosquare "), rx("crypto_square.go", r"^// Encode "), rx("crypto_square.go", r"^// Decode "), rx("crypto_square.go", r"^// Rectangle "), rx("crypto_square.go", r"^// Normalize "), full],
           files={"crypto_square.go": cs_src(True, True, True, True)}, wrong_files={"crypto_square.go": cs_src(True, True, True, True).replace("// Rectangle returns", "// Returns")})
    s.turn("Create README.md with `## Usage`, `## Algorithm` and `## Examples` sections. In Examples show, in a fenced block, these exact results: Encode(\"s#$%^&plunk\") is \"su pn lk\" and Encode(\"We all know interspecies romance is weird.\") is \"wneiaw eorene awssci liprer lneoid ktcms \" (note the trailing space).",
           [sections("README.md", "Usage", "Algorithm", "Examples"), rx("README.md", r'"su pn lk"'), rx("README.md", r"wneiaw eorene awssci liprer lneoid ktcms \""), rx("README.md", r"```")],
           files={"README.md": CS_README}, wrong_files={"README.md": CS_README.replace("wneiaw eorene awssci liprer lneoid ktcms ", "wneiaw eorene awssci liprer lneoid ktcms")})
    s.turn("Add extra_test.go (package cryptosquare) with at least four `func Test...` functions covering Encode, Decode, Rectangle and Normalize; `go test ./...` must pass.",
           [rx("extra_test.go", r"^func Test", 4), full], files={"extra_test.go": GO_EXTRA}, wrong_files={"extra_test.go": GO_EXTRA.replace("got != \"147 258 369\"", "got == \"147 258 369\"")})
    return s


# ----------------------------------------------------------------------------- P4 go/sublist (docs)
def sl_src(contains_pub=False, docs_contains=False):
    cn = "Contains" if contains_pub else "contains"
    out = ('package sublist\n\nimport "reflect"\n\n// Sublist checks difference of two lists and\n// returns equal, sublist, superlist or unequal according\n// to their relation to each other.\n'
           f'func Sublist(l1, l2 []int) Relation {{\n\tswitch {{\n\tcase reflect.DeepEqual(l1, l2):\n\t\treturn RelationEqual\n\tcase {cn}(l1, l2):\n\t\treturn RelationSuperlist\n\tcase {cn}(l2, l1):\n\t\treturn RelationSublist\n\tdefault:\n\t\treturn RelationUnequal\n\t}}\n}}\n\n')
    if docs_contains:
        out += "// Contains reports whether small occurs as a contiguous run inside big; an empty small is contained in every list.\n"
    out += f"func {cn}(l1, l2 []int) bool {{\n\tif len(l2) == 0 {{\n\t\treturn true\n\t}} else if len(l2) > len(l1) {{\n\t\treturn false\n\t}}\n\tfor i := 0; i <= len(l1)-len(l2); i++ {{\n\t\tif l1[i] != l2[0] {{\n\t\t\tcontinue\n\t\t}}\n\t\trest := true\n\t\tfor j, e := range l2 {{\n\t\t\trest = rest && l1[i+j] == e\n\t\t}}\n\t\tif rest {{\n\t\t\treturn true\n\t\t}}\n\t}}\n\treturn false\n}}\n"
    return out


DOCGO = "// Package sublist compares two integer lists and reports whether they are equal, one is a\n// contiguous sub-list of the other, or they are unequal.\n//\n// Use Sublist for the relation and Contains for the underlying containment test.\npackage sublist\n"
EXAMPLE_GO = 'package sublist\n\nimport "fmt"\n\nfunc ExampleSublist() {\n\tfmt.Println(Sublist([]int{1, 2}, []int{1, 2}))\n\tfmt.Println(Sublist([]int{1, 2}, []int{0, 1, 2, 3}))\n\tfmt.Println(Sublist([]int{0, 1, 2, 3}, []int{1, 2}))\n\tfmt.Println(Sublist([]int{1, 2}, []int{2, 1}))\n\t// Output:\n\t// equal\n\t// sublist\n\t// superlist\n\t// unequal\n}\n'
GO_CONTAINS = '''package sublist

import "testing"

func TestHiddenContains(t *testing.T) {
	cases := []struct {
		big, small []int
		want       bool
	}{
		{[]int{1, 2, 3}, []int{2, 3}, true},
		{[]int{1, 2, 3}, []int{}, true},
		{[]int{}, []int{}, true},
		{[]int{}, []int{1}, false},
		{[]int{1, 2, 3}, []int{3, 2}, false},
		{[]int{1, 1, 2}, []int{1, 2}, true},
		{[]int{1, 2}, []int{1, 2, 3}, false},
	}
	for _, c := range cases {
		if got := Contains(c.big, c.small); got != c.want {
			t.Errorf("Contains(%v,%v) = %v, want %v", c.big, c.small, got, c.want)
		}
	}
}
'''
SL_README = '''# sublist

## Usage

`Sublist(l1, l2)` compares two int lists and returns a `Relation`. `Contains(big, small)` reports whether `small` is a contiguous run inside `big`.

## Relations

| relation | meaning |
|---|---|
| equal | both lists hold the same values in the same order |
| sublist | the first list is a contiguous part of the second |
| superlist | the second list is a contiguous part of the first |
| unequal | none of the above |

## Examples

```go
Sublist([]int{1, 2}, []int{0, 1, 2, 3}) // sublist
Sublist([]int{}, []int{})               // equal
Sublist([]int{1, 2}, []int{2, 1})       // unequal
```
'''
SL_CHANGE = "# Changelog\n\n## [0.2.0]\n\n### Added\n\n- `Contains` is exported.\n- `ExampleSublist` documents the four relations.\n- `doc.go` carries the package comment.\n\n## [0.1.0]\n\n- Initial `Sublist`.\n"


def p4():
    s = Scn("go-sublist-docs", "polyglot", "docs", "go", "Aider polyglot-benchmark go/sublist (Exercism): implement, then package comment in doc.go, README relation table, a testable Example, an exported helper against hidden tests, godoc and changelog.",
            [], protected=["sublist_test.go", "cases_test.go", "relations.go"], long_gaps=[4, 8])
    s.workspace = ws("go/exercises/practice/sublist")
    s.hidden = {"hidden_contains_test.go": GO_CONTAINS}
    base = (SRC / "go/exercises/practice/sublist/.meta/example.go").read_text(encoding="utf-8")
    t = lambda *h: {"kind": "tests", "runner": "go", "restore": ["sublist_test.go", "cases_test.go"], "hidden": list(h)}
    s.turn("Read .docs/instructions.md and implement `Sublist` in sublist.go so that `go test ./...` passes. relations.go and the provided tests must stay untouched.",
           [t()], files={"sublist.go": base}, wrong_files={"sublist.go": base.replace("case contains(l1, l2):\n\t\treturn RelationSuperlist\n\tcase contains(l2, l1):\n\t\treturn RelationSublist", "case contains(l1, l2):\n\t\treturn RelationSublist\n\tcase contains(l2, l1):\n\t\treturn RelationSuperlist")})
    s.turn("Which relation does `Sublist` return for two empty lists, and which for an empty first list against a non-empty second list? Do not change any files.",
           [facts(all=[r"\bequal\b", r"\bsublist\b"])], msg="ANSWER: two empty lists are equal; an empty first list against a non-empty one is a sublist", wrong_msg="ANSWER: unequal in both cases", bump=False)
    s.turn("Create doc.go containing the package comment, starting `// Package sublist ` and running at least three comment lines, followed by `package sublist`. No other file may carry a `// Package sublist` comment.",
           [exists("doc.go"), rx("doc.go", r"^// Package sublist "), rx("doc.go", r"^//.*\n//.*\n//.*\npackage sublist", 1), rx("sublist.go", r"^// Package sublist", absent=True), rx("relations.go", r"^// Package sublist", absent=True), t()],
           files={"doc.go": DOCGO}, wrong_files={"doc.go": "// Package sublist compares lists.\npackage sublist\n"})
    s.turn("Write README.md with `## Usage`, `## Relations` and `## Examples`. Relations is a table (columns relation, meaning) with exactly one row each for equal, sublist, superlist and unequal. Examples is a fenced go block showing `Sublist([]int{1, 2}, []int{0, 1, 2, 3})` is sublist, `Sublist([]int{}, []int{})` is equal and `Sublist([]int{1, 2}, []int{2, 1})` is unequal.",
           [sections("README.md", "Usage", "Relations", "Examples"), *[rx("README.md", rf"^\|\s*{r}\s*\|") for r in ("equal", "sublist", "superlist", "unequal")], rx("README.md", r"Sublist\(\[\]int\{1, 2\}, \[\]int\{0, 1, 2, 3\}\)"), rx("README.md", r"Sublist\(\[\]int\{\}, \[\]int\{\}\)"), rx("README.md", r"Sublist\(\[\]int\{1, 2\}, \[\]int\{2, 1\}\)")],
           files={"README.md": SL_README}, wrong_files={"README.md": SL_README.replace("| unequal | none of the above |\n", "")})
    s.turn("Add example_test.go (package sublist) with a `func ExampleSublist()` that prints, one per line via fmt.Println, the relation for: [1 2] vs [1 2], [1 2] vs [0 1 2 3], [0 1 2 3] vs [1 2], [1 2] vs [2 1], and declares the four expected lines in an `// Output:` block. `go test ./...` must pass.",
           [rx("example_test.go", r"func ExampleSublist\(\)"), rx("example_test.go", r"// Output:\n\s*// equal\n\s*// sublist\n\s*// superlist\n\s*// unequal"), t()],
           files={"example_test.go": EXAMPLE_GO}, wrong_files={"example_test.go": EXAMPLE_GO.replace("// sublist\n\t// superlist", "// superlist\n\t// sublist")})
    s.turn("Export the containment helper as `func Contains(big, small []int) bool` (rename `contains`, keep the behaviour: an empty small list is contained in everything) and keep Sublist working.",
           [t("hidden_contains_test.go"), rx("sublist.go", r"func Contains\(")], files={"sublist.go": sl_src(True)}, wrong_files={"sublist.go": sl_src(True).replace("if len(l2) == 0 {\n\t\treturn true", "if len(l2) == 0 {\n\t\treturn false")})
    s.turn("Give `Contains` a doc comment that starts with `// Contains ` and mentions what an empty list does, and mention `Contains` in README.md under `## Usage`.",
           [rx("sublist.go", r"^// Contains .*(?i:empty)"), rx("README.md", r"Contains"), t("hidden_contains_test.go")], files={"sublist.go": sl_src(True, True)}, wrong_files={"sublist.go": sl_src(True, False)})
    s.turn("What is the time complexity of `Contains` (and so of Sublist) for lists of length n and m? Answer in one sentence. Do not change any files.",
           [facts(all=[r"O\(\s*n\s*[*x×·]?\s*m\s*\)|quadratic|n\s*times\s*m|n \* m|product"])], msg="ANSWER: O(n*m) in the worst case, because for every start position it may compare up to m elements", wrong_msg="ANSWER: O(1)", bump=False)
    s.turn("Create CHANGELOG.md with a `## [0.2.0]` section and an `### Added` list (three bullets: `Contains` is exported, `ExampleSublist`, `doc.go`) above `## [0.1.0]`.",
           [rx("CHANGELOG.md", r"^## \[0\.2\.0\]"), rx("CHANGELOG.md", r"^### Added"), rx("CHANGELOG.md", r"^- .*Contains"), rx("CHANGELOG.md", r"^- .*ExampleSublist"), rx("CHANGELOG.md", r"^- .*doc\.go"), rx("CHANGELOG.md", r"^## \[0\.1\.0\]")],
           files={"CHANGELOG.md": SL_CHANGE}, wrong_files={"CHANGELOG.md": SL_CHANGE.replace("- `doc.go` carries the package comment.\n", "")})
    return s
