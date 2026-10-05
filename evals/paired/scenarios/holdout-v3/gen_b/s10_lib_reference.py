import ast, json, re
from lib import Scn, exists, facts, numrx, rx, sections

SHAPES = '''"""Areas and perimeters of simple shapes."""
import math


def area_rect(w: float, h: float) -> float:
    """Area of a rectangle."""
    if w < 0 or h < 0:
        raise ValueError("sides must be non-negative")
    return w * h


def area_circle(r: float, precision: int = 2) -> float:
    """Area of a circle, rounded to ``precision`` decimals."""
    if r < 0:
        raise ValueError("radius must be non-negative")
    return round(math.pi * r * r, precision)


def area_triangle(a: float, b: float, c: float) -> float:
    """Area of a triangle from its three sides (Heron's formula)."""
    if a + b <= c or a + c <= b or b + c <= a:
        raise ValueError("sides do not form a triangle")
    s = (a + b + c) / 2
    return math.sqrt(s * (s - a) * (s - b) * (s - c))


def perimeter_rect(w: float, h: float) -> float:
    """Perimeter of a rectangle."""
    return 2 * (w + h)


def _check(x):
    return x
'''
TRANSFORM = '''"""Point transformations on lists of (x, y) tuples."""
import math


def translate(points, dx: float = 0.0, dy: float = 0.0):
    """Shift every point by (dx, dy)."""
    return [(x + dx, y + dy) for x, y in points]


def scale(points, factor: float, origin=(0.0, 0.0)):
    """Scale points about ``origin``."""
    ox, oy = origin
    return [(ox + (x - ox) * factor, oy + (y - oy) * factor) for x, y in points]


def rotate(points, degrees: float, origin=(0.0, 0.0), precision: int = 6):
    """Rotate points counter-clockwise about ``origin``."""
    t = math.radians(degrees)
    ox, oy = origin
    return [(round(ox + (x - ox) * math.cos(t) - (y - oy) * math.sin(t), precision), round(oy + (x - ox) * math.sin(t) + (y - oy) * math.cos(t), precision)) for x, y in points]
'''
STATS = '''"""Summary statistics for point sets."""


def centroid(points):
    """Mean of the points."""
    if not points:
        raise ValueError("no points")
    n = len(points)
    return (sum(x for x, _ in points) / n, sum(y for _, y in points) / n)


def bounding_box(points):
    """Smallest axis-aligned box as (xmin, ymin, xmax, ymax)."""
    if not points:
        raise ValueError("no points")
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))
'''
MODS = {"geom.shapes": SHAPES, "geom.transform": TRANSFORM, "geom.stats": STATS}


def inspect_src(src):
    tree = ast.parse(src)
    out = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
            line = src.splitlines()[n.lineno - 1].rstrip(":")
            defaults = {}
            a = n.args
            pos = a.args
            for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults):
                defaults[arg.arg] = ast.unparse(d)
            raises = sorted({ast.unparse(r.exc.func) for r in ast.walk(n) if isinstance(r, ast.Raise) and r.exc is not None and isinstance(r.exc, ast.Call)})
            out.append(dict(name=n.name, sig=line, defaults=defaults, raises=raises, doc=ast.get_docstring(n)))
    return out


def all_info(mods):
    return {m: inspect_src(src) for m, src in mods.items()}


def skeleton(info):
    out = "# geom reference\n\n"
    for m, fs in info.items():
        out += f"## {m}\n\n" + "".join(f"### {f['name']}\n\n{f['doc']}\n\n" for f in fs)
    return out


def with_sigs(info):
    out = "# geom reference\n\n"
    for m, fs in info.items():
        out += f"## {m}\n\n" + "".join(f"### {f['name']}\n\n{f['doc']}\n\n```python\n{f['sig']}\n```\n\n" for f in fs)
    return out


def with_raises(info, raises_on=True, defaults=True):
    out = "# geom reference\n\n"
    for m, fs in info.items():
        out += f"## {m}\n\n"
        for f in fs:
            out += f"### {f['name']}\n\n{f['doc']}\n\n```python\n{f['sig']}\n```\n\n"
            if defaults and f["defaults"]:
                out += "| parameter | default |\n|---|---|\n" + "".join(f"| `{k}` | `{v}` |\n" for k, v in f["defaults"].items()) + "\n"
            if raises_on and f["raises"]:
                out += "**Raises:** " + ", ".join(f"`{r}`" for r in f["raises"]) + "\n\n"
    return out


CHECK = '''"""Docs coverage: python3 scripts/check_docs.py [--src DIR] [--docs FILE]
Prints `MISSING: <module>.<function>` for every public function of the package that has no `### <function>` heading
under its `## <module>` heading in the reference, then exits 1; prints `ok` and exits 0 when everything is documented."""
import argparse, ast, os, re

ap = argparse.ArgumentParser()
ap.add_argument("--src", default="geom")
ap.add_argument("--docs", default="docs/reference.md")
a = ap.parse_args()
docs, cur, seen = open(a.docs, encoding="utf-8").read().splitlines(), None, set()
for ln in docs:
    if ln.startswith("## "):
        cur = ln[3:].strip()
    elif ln.startswith("### ") and cur:
        seen.add((cur, ln[4:].strip()))
pkg = os.path.basename(os.path.abspath(a.src))
missing = []
for fn in sorted(os.listdir(a.src)):
    if fn.endswith(".py") and not fn.startswith("_"):
        mod = f"{pkg}.{fn[:-3]}"
        for n in ast.parse(open(os.path.join(a.src, fn), encoding="utf-8").read()).body:
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_") and (mod, n.name) not in seen:
                missing.append(f"MISSING: {mod}.{n.name}")
print("\\n".join(missing) if missing else "ok")
raise SystemExit(1 if missing else 0)
'''


def build():
    s = Scn("lib-reference", "mixed", "docs", "python",
            "Write an API reference for a small geometry library from its source: public-function inventory, exact signatures, defaults tables, raised exceptions, a new function that must be added to code and docs, a docs-coverage checker, an index table.",
            ["new self-authored library; reference-docs theme (cf. amplifier-agent api documentation tasks)"],
            protected=["geom/__init__.py", "geom/transform.py", "geom/stats.py"])
    s.file("geom/__init__.py", '"""geom: small geometry helpers."""\n')
    for m, src in MODS.items():
        s.file(m.replace(".", "/") + ".py", src)
    s.file("README.md", "# geom\n\nSmall geometry helpers. Modules: `geom.shapes`, `geom.transform`, `geom.stats`. Private helpers start with an underscore.\n")
    info = all_info(MODS)
    count = {m: len(fs) for m, fs in info.items()}
    total = sum(count.values())
    s.turn("How many public functions (names not starting with an underscore) does each geom module define, and how many in total? Do not change any files.",
           [facts(all=[r"shapes\D{0,8}" + numrx(count["geom.shapes"]), r"transform\D{0,8}" + numrx(count["geom.transform"]), r"stats\D{0,8}" + numrx(count["geom.stats"]), r"total\D{0,8}" + numrx(total)])],
           msg=f"ANSWER: shapes {count['geom.shapes']}, transform {count['geom.transform']}, stats {count['geom.stats']}; total {total}", wrong_msg=f"ANSWER: shapes {count['geom.shapes'] + 1}, transform {count['geom.transform']}, stats {count['geom.stats']}; total {total + 1}", bump=True)
    exp_heads = {m: [f["name"] for f in fs] for m, fs in info.items()}
    s.func("t2", f"""
        cur, got = None, {{}}
        for ln in read('docs/reference.md').splitlines():
            if ln.startswith('## '):
                cur = ln[3:].strip()
                got[cur] = []
            elif ln.startswith('### ') and cur:
                got[cur].append(ln[4:].strip())
        need(got == {exp_heads!r}, 'headings differ: ' + str(got))
        """)
    s.turn("Create docs/reference.md titled `# geom reference`: one `## <module>` heading per module (e.g. `## geom.shapes`) and one `### <function>` heading for every public function, in source order. Put the function's docstring first line under its heading. Leave private helpers out.",
           [s.g("t2")], files={"docs/reference.md": skeleton(info)}, wrong_files={"docs/reference.md": skeleton(info).replace("### area_circle\n\n", "### area_circle\n\n").replace("### rotate", "### spin")})
    sigs = {f["name"]: f["sig"] for fs in info.values() for f in fs}
    s.func("t3", f"""
        for name, sig in {sigs!r}.items():
            body = '\\n'.join(md_lines('docs/reference.md', '^' + name + '$'))
            m = re.search(r'```python\\n(.*?)```', body, re.S)
            need(m, 'no python block under ' + name)
            need(sig in m.group(1), f'signature for {{name}}: want {{sig}}, block has {{m.group(1).strip()}}')
        """)
    s.turn("Under every function heading add a ```python fenced block containing its exact `def` line from the source (name, parameters with annotations and defaults, return annotation), without the trailing colon or the body.",
           [s.g("t3")], files={"docs/reference.md": with_sigs(info)}, wrong_files={"docs/reference.md": with_sigs(info).replace("precision: int = 2", "precision: int = 3")})
    rs = sorted({r for fs in info.values() for f in fs for r in f["raises"]})
    rf = [f["name"] for fs in info.values() for f in fs if f["raises"]]
    s.turn("Which public functions raise an exception, and which exception type do they raise? Do not change any files.",
           [facts(all=[*(r"\b" + n + r"\b" for n in rf), *(r"\b" + r + r"\b" for r in rs)])], msg=f"ANSWER: {', '.join(rf)} raise {', '.join(rs)}", wrong_msg=f"ANSWER: only area_rect raises ValueError", bump=False)
    rm = {f["name"]: f["raises"] for fs in info.values() for f in fs}
    s.func("t5", f"""
        for name, rs in {rm!r}.items():
            body = '\\n'.join(md_lines('docs/reference.md', '^' + name + '$'))
            if rs:
                m = re.search(r'^\\*\\*Raises:\\*\\*\\s*(.*)$', body, re.M)
                need(m, 'no **Raises:** line under ' + name)
                got = sorted(x.strip('` ') for x in m.group(1).split(','))
                need(got == rs, f'{{name}} raises {{got}} != {{rs}}')
            else:
                need('**Raises:**' not in body, name + ' wrongly documents Raises')
        """)
    s.turn("Document the exceptions: under each function that raises, add a line `**Raises:** ` followed by the exception type names in backticks, comma-separated. Functions that raise nothing get no Raises line.",
           [s.g("t5")], files={"docs/reference.md": with_raises(info, True, False)}, wrong_files={"docs/reference.md": with_raises(info, False, False)})
    dd = {f["name"]: f["defaults"] for fs in info.values() for f in fs if f["defaults"]}
    s.func("t6", f"""
        for name, d in {dd!r}.items():
            rows = md_rows('docs/reference.md', '^' + name + '$')
            need(rows, 'no defaults table under ' + name)
            got = {{r[0].strip('` '): r[1].strip('` ') for r in rows[1:] if len(r) >= 2}}
            need(got == d, f'{{name}} defaults {{got}} != {{d}}')
        for name in {[n for n in sigs if n not in dd]!r}:
            need(not md_rows('docs/reference.md', '^' + name + '$'), name + ' has no defaults, so no table')
        """)
    s.turn("For every function that has parameters with default values, add a table (columns parameter, default) with one row per defaulted parameter; defaults exactly as written in the code, in backticks. Functions without defaults get no table.",
           [s.g("t6")], files={"docs/reference.md": with_raises(info)}, wrong_files={"docs/reference.md": with_raises(info).replace("| `origin` | `(0.0, 0.0)` |", "| `origin` | `(0, 0)` |")})
    # new function
    new_src = SHAPES.replace("\n\ndef _check(x):", '''

def perimeter_triangle(a: float, b: float, c: float) -> float:
    """Perimeter of a triangle."""
    if a + b <= c or a + c <= b or b + c <= a:
        raise ValueError("sides do not form a triangle")
    return a + b + c


def _check(x):''')
    mods2 = {**MODS, "geom.shapes": new_src}
    info2 = all_info(mods2)
    s.func("t7", """
        import importlib, sys
        sys.path.insert(0, '.')
        sh = importlib.import_module('geom.shapes')
        need(sh.perimeter_triangle(3, 4, 5) == 12, 'perimeter_triangle(3,4,5)')
        try:
            sh.perimeter_triangle(1, 2, 9)
            fail('no ValueError for impossible triangle')
        except ValueError:
            pass
        need(sh.area_rect(2, 3) == 6, 'existing code broken')
        body = '\\n'.join(md_lines('docs/reference.md', '^perimeter_triangle$'))
        need('def perimeter_triangle(a: float, b: float, c: float) -> float' in body, 'signature block missing')
        need(re.search(r'^\\*\\*Raises:\\*\\*.*ValueError', body, re.M), 'Raises line missing')
        heads = [l for l in read('docs/reference.md').splitlines() if l.startswith('### ')]
        need(heads.index('### perimeter_triangle') == heads.index('### perimeter_rect') + 1, 'must follow perimeter_rect in source order')
        """.replace("sys.path.insert(0, '.')", "sys.path.insert(0, os.getcwd())"))
    s.turn("Add `perimeter_triangle(a: float, b: float, c: float) -> float` to geom/shapes.py right after `perimeter_rect`: it returns a + b + c and raises ValueError when the sides do not form a triangle (same condition as area_triangle). Document it in docs/reference.md like the other functions (docstring line, signature block, Raises line), in source order.",
           [s.g("t7")], files={"geom/shapes.py": new_src, "docs/reference.md": with_raises(info2)}, wrong_files={"geom/shapes.py": new_src, "docs/reference.md": with_raises(info)}, bump=False)
    alt_src = "def alpha(x):\n    return x\n\n\ndef beta(x):\n    return x\n\n\ndef _hidden():\n    pass\n"
    alt_doc = "# ref\n\n## demo.m\n\n### alpha\n\ntext\n"
    s.func("t8", f"""
        d = W / '_altpkg' / 'demo'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'm.py').write_text({alt_src!r}, encoding='utf-8')
        (W / '_altpkg' / 'ref.md').write_text({alt_doc!r}, encoding='utf-8')
        need((W / 'scripts/check_docs.py').exists(), 'missing scripts/check_docs.py')
        chk_cmd_out('python3 scripts/check_docs.py --src _altpkg/demo --docs _altpkg/ref.md', ['MISSING: demo.m.beta'], expect_rc=1)
        chk_cmd_out('python3 scripts/check_docs.py', ['ok'])
        """)
    s.turn("Add scripts/check_docs.py [--src DIR] [--docs FILE] (defaults geom and docs/reference.md): for every public function in DIR/*.py (skip files and functions starting with an underscore) that lacks a `### <function>` heading under its `## <package>.<module>` heading in FILE, print `MISSING: <package>.<module>.<function>`, sorted, and exit 1; otherwise print `ok` and exit 0.",
           [s.g("t8")], files={"scripts/check_docs.py": CHECK}, wrong_files={"scripts/check_docs.py": CHECK.replace("raise SystemExit(1 if missing else 0)", "raise SystemExit(0)")})
    idx = "# geom docs\n\n## Module summary\n\n| module | functions | summary |\n|---|---|---|\n" + "".join(f"| {m} | {len(fs)} | {ast.get_docstring(ast.parse(mods2[m]))} |\n" for m, fs in info2.items())
    s.func("t9", f"""
        rows = md_rows('docs/index.md', 'module summary')
        got = [(r[0].strip('` '), int(num(r[1])), r[2]) for r in rows[1:] if len(r) >= 3]
        need(got == {[(m, len(fs), ast.get_docstring(ast.parse(mods2[m]))) for m, fs in info2.items()]!r}, 'module summary rows: ' + str(got))
        """)
    s.turn("Create docs/index.md with a `## Module summary` table (columns module, functions, summary): one row per module, the number of public functions it now defines, and its module docstring verbatim.",
           [s.g("t9")], files={"docs/index.md": idx}, wrong_files={"docs/index.md": idx.replace("| geom.shapes | 5 |", "| geom.shapes | 4 |")})
    s.turn("Add a '## Reference' section to README.md that links docs/reference.md and docs/index.md and explains how to run `python3 scripts/check_docs.py`.",
           [sections("README.md", "Reference"), rx("README.md", r"docs/reference\.md"), rx("README.md", r"docs/index\.md"), rx("README.md", r"scripts/check_docs\.py")],
           files={"README.md": s.files["README.md"] + "\n## Reference\n\nSee docs/reference.md and docs/index.md. Run `python3 scripts/check_docs.py` to find undocumented functions.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Reference\n\nSee the docs folder.\n"})
    return s
