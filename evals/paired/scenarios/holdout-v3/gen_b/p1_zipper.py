from pathlib import Path
from lib import Scn, exists, facts, numrx, rx, sections

SHA = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
HINT = "~/dev/afast-campaign-corrected-polyglot-20260919/polyglot/polyglot-benchmark"
SRC = Path(HINT).expanduser()


def src(depth=False, path=False, find=False, docs=False, types=False):
    d = (lambda t: f'\n        """{t}"""') if docs else (lambda t: "")
    ret = (lambda t: f" -> {t}") if types else (lambda t: "")
    opt = "Optional[Zipper]" if types else ""
    out = ""
    if types:
        out += "from __future__ import annotations\n\nfrom typing import Optional\n\n\n"
    out += "class Zipper:\n" + ('    """A zipper over a binary tree of nested dicts (value, left, right)."""\n\n' if docs else "")
    out += f'''    @staticmethod
    def from_tree(tree){ret("Zipper")}:{d("Focus the root of `tree`.")}
        return Zipper(dict(tree), [], [])

    def __init__(self, tree, ancestors, directions=None):
        self.tree = tree
        self.ancestors = ancestors
        self.directions = directions if directions is not None else []

    def value(self){ret("object")}:{d("Value at the focus.")}
        return self.tree['value']

    def set_value(self, value){ret("Zipper")}:{d("Replace the value at the focus and return self so calls can be chained.")}
        self.tree['value'] = value
        return self

    def left(self){ret(opt)}:{d("Focus the left child, or None when there is none.")}
        if self.tree['left'] is None:
            return None
        return Zipper(self.tree['left'], self.ancestors + [self.tree], self.directions + ['left'])

    def set_left(self, tree){ret("Zipper")}:{d("Replace the left subtree and return self.")}
        self.tree['left'] = tree
        return self

    def right(self){ret(opt)}:{d("Focus the right child, or None when there is none.")}
        if self.tree['right'] is None:
            return None
        return Zipper(self.tree['right'], self.ancestors + [self.tree], self.directions + ['right'])

    def set_right(self, tree){ret("Zipper")}:{d("Replace the right subtree and return self.")}
        self.tree['right'] = tree
        return self

    def up(self){ret(opt)}:{d("Focus the parent, or None at the root.")}
        if not self.ancestors:
            return None
        return Zipper(self.ancestors[-1], self.ancestors[:-1], self.directions[:-1])

    def to_tree(self){ret("dict")}:{d("The whole tree, regardless of the focus.")}
        if any(self.ancestors):
            return self.ancestors[0]
        return self.tree
'''
    if depth:
        out += f'''
    def depth(self){ret("int")}:{d("Number of steps from the root to the focus.")}
        return len(self.ancestors)
'''
    if path:
        out += f'''
    def path(self){ret("list[str]")}:{d("Directions ('left' or 'right') leading from the root to the focus.")}
        return list(self.directions)
'''
    if find:
        out += f'''
    def find(self, value){ret(opt)}:{d("First focus holding `value` in pre-order (node, left, right) within the current subtree, or None.")}
        if self.value() == value:
            return self
        for child in (self.left(), self.right()):
            if child is not None:
                hit = child.find(value)
                if hit is not None:
                    return hit
        return None
'''
    return out


T = '''import unittest

from zipper import Zipper

TREE = {"value": 1, "left": {"value": 2, "left": None, "right": {"value": 3, "left": None, "right": None}}, "right": {"value": 4, "left": None, "right": None}}


class %s(unittest.TestCase):
%s'''
HID_DEPTH = T % ("HiddenDepth", '''    def test_root_depth_zero(self):
        self.assertEqual(Zipper.from_tree(TREE).depth(), 0)

    def test_depth_follows_moves(self):
        z = Zipper.from_tree(TREE)
        self.assertEqual(z.left().right().depth(), 2)
        self.assertEqual(z.right().depth(), 1)

    def test_depth_after_up(self):
        z = Zipper.from_tree(TREE).left().right()
        self.assertEqual(z.up().depth(), 1)
        self.assertEqual(z.up().up().depth(), 0)
''')
HID_PATH = T % ("HiddenPath", '''    def test_root_path_empty(self):
        self.assertEqual(Zipper.from_tree(TREE).path(), [])

    def test_path_records_directions(self):
        self.assertEqual(Zipper.from_tree(TREE).left().right().path(), ["left", "right"])

    def test_path_after_up(self):
        z = Zipper.from_tree(TREE).left().right().up()
        self.assertEqual(z.path(), ["left"])

    def test_path_length_equals_depth(self):
        z = Zipper.from_tree(TREE).right()
        self.assertEqual(len(z.path()), z.depth())
''')
HID_FIND = T % ("HiddenFind", '''    def test_find_root(self):
        self.assertEqual(Zipper.from_tree(TREE).find(1).value(), 1)

    def test_find_deep(self):
        z = Zipper.from_tree(TREE).find(3)
        self.assertEqual((z.value(), z.path(), z.depth()), (3, ["left", "right"], 2))

    def test_find_missing(self):
        self.assertIsNone(Zipper.from_tree(TREE).find(99))

    def test_find_is_preorder(self):
        tree = {"value": 5, "left": {"value": 7, "left": None, "right": None}, "right": {"value": 7, "left": None, "right": None}}
        self.assertEqual(Zipper.from_tree(tree).find(7).path(), ["left"])

    def test_find_searches_current_subtree_only(self):
        z = Zipper.from_tree(TREE).right()
        self.assertIsNone(z.find(2))
''')

README = '''# zipper

A zipper over binary trees represented as nested dicts.

## Usage

Build a zipper with `Zipper.from_tree(tree)`, move with `left()`, `right()` and `up()`, and read with `value()`.

## API

`from_tree`, `value`, `set_value`, `left`, `set_left`, `right`, `set_right`, `up`, `to_tree`, `depth`, `path`, `find`.

## Examples

```
>>> from zipper import Zipper
>>> tree = {"value": 1, "left": {"value": 2, "left": None, "right": None}, "right": None}
>>> z = Zipper.from_tree(tree)
>>> z.value()
1
>>> z.left().value()
2
>>> z.left().depth()
1
>>> z.left().path()
['left']
>>> z.find(2).value()
2
>>> print(z.find(9))
None

```
'''
CHANGELOG = "# Changelog\n\n## 0.2.0\n\n### Added\n\n- `depth()` returns the number of steps from the root.\n- `path()` returns the directions taken from the root.\n- `find(value)` searches the current subtree in pre-order.\n\n## 0.1.0\n\n- Initial zipper implementation.\n"
DOCTEST = {"kind": "tests", "runner": "cmd", "cmd": "python3 -m doctest -v README.md", "expect_regex": r"\b([4-9]|\d{2,}) passed( and 0 failed)?\.", "timeout": 60}


def build():
    s = Scn("py-zipper-docs", "polyglot", "mixed", "python",
            "Aider polyglot-benchmark python/zipper (Exercism): implement, extend with depth/path/find against hidden tests, then docstrings, a doctested README, type hints and a changelog.",
            [], protected=["zipper_test.py"], long_gaps=[5, 9])
    s.workspace = {"kind": "git", "repo": "https://github.com/Aider-AI/polyglot-benchmark", "sha": SHA, "subdir": "python/exercises/practice/zipper", "local_hint": HINT, "remove": [".meta"]}
    s.hidden = {"hidden_depth_test.py": HID_DEPTH, "hidden_path_test.py": HID_PATH, "hidden_find_test.py": HID_FIND}
    base = (SRC / "python/exercises/practice/zipper/.meta/example.py").read_text(encoding="utf-8")
    # NOTE: the reference for turn 1 is the exercise's own example solution; later stages are the staged `src` above.
    v0 = src()
    t = lambda *h: {"kind": "tests", "runner": "python", "files": ["zipper_test.py"] + list(h), "restore": ["zipper_test.py"], "hidden": list(h)}
    s.turn("Read .docs/instructions.md and implement the Zipper class in zipper.py so that every test in zipper_test.py passes. Do not edit the test file.",
           [t()], files={"zipper.py": base}, wrong_files={"zipper.py": base.replace("self.ancestors[:-1]", "self.ancestors")})
    s.turn("In two or three sentences, explain what `up()` returns when the focus is already the root, and what `left()` returns when the focus has no left child. Do not change any files.",
           [facts(all=[r"\bNone\b", r"root", r"left"])], msg="ANSWER: up() returns None at the root (no ancestors); left() returns None when there is no left child", wrong_msg="ANSWER: both raise an exception", bump=False)
    s.turn("Add a `depth()` method to Zipper: the number of steps from the root to the focus (0 at the root). It must stay correct after `up()`.",
           [t("hidden_depth_test.py")], files={"zipper.py": src(depth=True)}, wrong_files={"zipper.py": src(depth=True).replace("len(self.ancestors)", "len(self.ancestors) + 1")})
    s.turn("Add a `path()` method that returns the list of directions, 'left' or 'right', taken from the root to the focus (empty at the root). It must stay correct after `up()`.",
           [t("hidden_depth_test.py", "hidden_path_test.py")], files={"zipper.py": src(depth=True, path=True)}, wrong_files={"zipper.py": src(depth=True).replace("    def depth", "    def path(self):\n        return []\n\n    def depth")})
    s.turn("Add `find(value)`: search the subtree under the current focus in pre-order (node, then left, then right) and return the Zipper focused on the first node holding `value`, or None if absent. The returned zipper must report the right depth() and path().",
           [t("hidden_depth_test.py", "hidden_path_test.py", "hidden_find_test.py")], files={"zipper.py": src(depth=True, path=True, find=True)},
           wrong_files={"zipper.py": src(depth=True, path=True, find=True).replace("for child in (self.left(), self.right()):", "for child in (self.right(), self.left()):")})
    meths = ["from_tree", "value", "set_value", "left", "set_left", "right", "set_right", "up", "to_tree", "depth", "path", "find"]
    full = [t("hidden_depth_test.py", "hidden_path_test.py", "hidden_find_test.py")]
    s.turn("Document the code: give the Zipper class and each of its public methods a docstring (the line right after the `def` line / class line), in zipper.py. Behaviour must not change.",
           [*[rx("zipper.py", rf"def {m}\([^)]*\)[^:\n]*:\n\s+\"\"\"") for m in meths], rx("zipper.py", r'class Zipper:\n\s+"""'), *full],
           files={"zipper.py": src(depth=True, path=True, find=True, docs=True)}, wrong_files={"zipper.py": src(depth=True, path=True, find=True, docs=True).replace('"""Number of steps from the root to the focus."""', "")})
    s.turn("Create README.md with the sections `## Usage`, `## API` and `## Examples`. Examples must be a fenced block of doctest-style `>>>` lines (importing `from zipper import Zipper`) that really run: it must demonstrate value(), left(), depth(), path() and find(), and `python3 -m doctest -v README.md` must pass.",
           [sections("README.md", "Usage", "API", "Examples"), rx("README.md", r"^>>> from zipper import Zipper", 1), rx("README.md", r"find\("), rx("README.md", r"path\(\)"), DOCTEST],
           files={"README.md": README}, wrong_files={"README.md": README.replace("['left']", "['right']")})
    s.turn("Add return-type annotations: `depth() -> int`, `path() -> list[str]` and `find(...)` returning an Optional Zipper (use `from __future__ import annotations` and `typing.Optional`). Keep every test passing.",
           [rx("zipper.py", r"def depth\(self\) -> int:"), rx("zipper.py", r"def path\(self\) -> list\[str\]:"), rx("zipper.py", r"def find\(self, value\) -> Optional\[Zipper\]:"), rx("zipper.py", r"^from __future__ import annotations"), *full],
           files={"zipper.py": src(depth=True, path=True, find=True, docs=True, types=True)}, wrong_files={"zipper.py": src(depth=True, path=True, find=True, docs=True)})
    s.turn("Why does `set_value` return `self`, and what does that allow callers to do? One or two sentences. Do not change any files.",
           [facts(all=[r"self|zipper|same", r"chain"])], msg="ANSWER: it returns the zipper itself so calls can be chained, e.g. z.set_value(5).set_left(None)", wrong_msg="ANSWER: it returns the old value", bump=False)
    s.turn("Create CHANGELOG.md with a `## 0.2.0` section and a `### Added` list that names `depth()`, `path()` and `find(value)` (one bullet each, method names in backticks), above a `## 0.1.0` section.",
           [rx("CHANGELOG.md", r"^## 0\.2\.0"), rx("CHANGELOG.md", r"^### Added"), rx("CHANGELOG.md", r"^- `depth\(\)`"), rx("CHANGELOG.md", r"^- `path\(\)`"), rx("CHANGELOG.md", r"^- `find\(value\)`"), rx("CHANGELOG.md", r"^## 0\.1\.0")],
           files={"CHANGELOG.md": CHANGELOG}, wrong_files={"CHANGELOG.md": CHANGELOG.replace("- `find(value)`", "- find")})
    return s
