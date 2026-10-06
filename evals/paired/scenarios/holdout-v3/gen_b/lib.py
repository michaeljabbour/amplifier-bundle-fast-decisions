"""Authoring DSL for holdout-v3 batch B scenarios (mixed family + polyglot). Writes the scenario YAML into the repo and
the reference solutions OUTSIDE the repo (~/dev/afast-paired-refs/holdout-v3/<id>/turnN/{message.txt,files/**,meta.json}).
Expected values are computed by the generators themselves, so checks, hidden graders and references cannot disagree."""
import csv
import io
import json
import random  # noqa: F401  (used by scenario modules)
import re
import textwrap
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCEN_DIR = HERE.parent
REFS = Path("~/dev/afast-paired-refs/holdout-v3").expanduser()


def csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def dedent(s):
    return textwrap.dedent(s).lstrip("\n")


def numrx(v, dec=None):
    """Regex matching number v in prose: optional thousands commas, optional trailing zeros, not part of a bigger number."""
    if dec is None:
        dec = 0 if float(v) == int(v) else len(str(v).split(".")[1])
    s = f"{abs(v):.{dec}f}"
    ip, _, fp = s.partition(".")
    ipx = "".join(d + ",?" for d in ip[:-1]) + ip[-1]
    fp = fp.rstrip("0")
    fx = (r"\." + fp + "0*") if fp else r"(?:\.0+)?"
    neg = "-" if v < 0 else ""
    return r"(?<![\d.,])" + neg + ipx + fx + r"(?!\d|[.,]\d)"


def lblnum(label, v, gap=12):
    """Regex: `label: N` or `N label` (either order of a count and its label in prose)."""
    return label + r"\D{0," + str(gap) + "}" + numrx(v) + "|" + numrx(v) + r"\D{0,3}" + label + r"\b"


def facts(all=None, any=None, min_any=1):
    d = {"kind": "keyed_facts"}
    if all:
        d["all"] = list(all)
    if any:
        d["any"] = list(any)
        if min_any != 1:
            d["min_any"] = min_any
    return d


def rx(path, pattern, min_count=1, absent=False):
    d = {"kind": "file_regex", "path": path, "pattern": pattern}
    if min_count != 1:
        d["min_count"] = min_count
    if absent:
        d["absent"] = True
    return d


def sections(path, *headings):
    return {"kind": "doc_sections", "path": path, "headings": list(headings)}


def exists(path):
    return {"kind": "file_exists", "path": path}


PRELUDE = r'''
import csv, json, os, re, subprocess, sys
from pathlib import Path

W = Path(".")


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def need(cond, msg):
    if not cond:
        fail(msg)


def read(rel):
    p = W / rel
    need(p.exists(), f"missing {rel}")
    return p.read_text(encoding="utf-8")


def load_json(rel):
    try:
        return json.loads(read(rel))
    except ValueError as e:
        fail(f"{rel} is not valid JSON: {e}")


def close(a, b, tol=0.011):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def num(s):
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s))
    return float(m.group(0).replace(",", "")) if m else None


def run(cmd, timeout=60, stdin=None):
    p = subprocess.run(cmd, shell=True, cwd=W, capture_output=True, text=True, timeout=timeout, input=stdin)
    return p.returncode, p.stdout, p.stderr


def md_lines(rel, under=None):
    lines = read(rel).splitlines()
    if not under:
        return lines
    out, on, lvl = [], False, 0
    for ln in lines:
        m = re.match(r"^(#+)\s+(.*)", ln)
        if m:
            if on and len(m.group(1)) <= lvl:
                break
            if not on and re.search(under, m.group(2), re.I):
                on, lvl = True, len(m.group(1))
            continue
        if on:
            out.append(ln)
    need(on, f"no heading matching {under!r} in {rel}")
    return out


def md_rows(rel, under=None):
    rows = []
    for ln in md_lines(rel, under):
        if ln.strip().startswith("|") and not re.match(r"^\s*\|[\s:|-]+\|\s*$", ln):
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return rows


def cmp(got, want, tol, path):
    if isinstance(want, dict):
        need(isinstance(got, dict), f"{path}: expected an object, got {type(got).__name__}")
        for k, v in want.items():
            need(k in got, f"{path}.{k}: missing")
            cmp(got[k], v, tol, f"{path}.{k}")
    elif isinstance(want, list):
        need(isinstance(got, list) and len(got) == len(want), f"{path}: expected list of {len(want)}, got {got!r}")
        for i, (g, w) in enumerate(zip(got, want)):
            cmp(g, w, tol, f"{path}[{i}]")
    elif isinstance(want, bool) or want is None or isinstance(want, str):
        need(got == want, f"{path}: {got!r} != {want!r}")
    else:
        need(not isinstance(got, bool) and close(got, want, tol), f"{path}: {got!r} != {want!r}")


def chk_json(rel, exp, tol=0.051):
    cmp(load_json(rel), exp, tol, rel)


def chk_table(rel, under, exp, col=1, tol=0.051):
    rows = md_rows(rel, under)
    need(rows, f"no table under {under!r} in {rel}")
    got = {r[0].strip("* `"): num(r[col]) for r in rows if len(r) > col and num(r[col]) is not None}
    for k, v in exp.items():
        need(k in got and close(got[k], v, tol), f"{k}: {got.get(k)} != {v}")


def chk_cmd_json(cmd, exp, tol=0.051, stdin=None):
    rc, out, err = run(cmd, stdin=stdin)
    need(rc == 0, f"`{cmd}` exited {rc}: {err[-200:]}")
    try:
        d = json.loads(out)
    except ValueError as e:
        fail(f"`{cmd}` stdout is not JSON: {e}")
    cmp(d, exp, tol, cmd)


def chk_cmd_out(cmd, lines, stdin=None, expect_rc=0):
    rc, out, err = run(cmd, stdin=stdin)
    need(rc == expect_rc, f"`{cmd}` exited {rc} (want {expect_rc}): {err[-200:]}")
    got = [ln.rstrip() for ln in out.strip().splitlines()]
    need(got == list(lines), f"`{cmd}` output {got[:8]} != {list(lines)[:8]}")
'''


def _py(obj):
    return repr(obj)


class Scn:
    def __init__(self, sid, family, ttype, lang, desc, adapted, protected=(), long_gaps=()):
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,28}", sid), sid
        self.id, self.family, self.ttype, self.lang = sid, family, ttype, lang
        self.desc, self.adapted, self.protected = desc, adapted, list(protected)
        self.long_gaps = set(long_gaps)
        self.files, self.hidden, self.funcs, self.turns = {}, {}, {}, []
        self.workspace = None   # polyglot: git workspace dict
        self.fname = sid

    def file(self, path, text):
        self.files[path] = text

    def func(self, name, body):
        """Hidden grader function `name` (body: statements, no indentation needed)."""
        self.funcs[name] = textwrap.dedent(body).strip("\n")

    def g(self, name, timeout=60):
        assert name in self.funcs, name
        return {"kind": "tests", "runner": "cmd", "cmd": f"python3 _grade.py {name}", "hidden": ["_grade.py"], "timeout": timeout}

    def turn(self, prompt, checks, msg="DONE: done", files=None, delete=(), wrong_msg=None, wrong_files=None, bump=False):
        self.turns.append(dict(prompt=" ".join(prompt.split()), checks=checks, msg=msg, files=files or {},
                               delete=list(delete), wrong_msg=wrong_msg, wrong_files=wrong_files, bump=bump))

    # ------------------------------------------------------------------ emit
    def grader_source(self):
        body = [PRELUDE.strip("\n"), ""]
        for name, code in self.funcs.items():
            body.append(f"\ndef {name}():\n" + textwrap.indent(code, "    ") + "\n")
        body.append('\nif __name__ == "__main__":\n    fn = globals().get(sys.argv[1]) if len(sys.argv) > 1 else None\n'
                    '    need(callable(fn) and sys.argv[1] in %s, "unknown check " + str(sys.argv[1:]))\n    fn()\n    print("OK")\n' % _py(sorted(self.funcs)))
        return "\n".join(body)

    def to_doc(self):
        doc = {"id": self.id, "task_type": self.ttype, "language": self.lang, "split": "holdout", "default_gap_s": 10,
               "source": {"desc": self.desc, "kind": "self-authored deterministic workspace", "adapted_from": self.adapted}}
        if self.workspace:
            doc["source"] = {"desc": self.desc, "repo": self.workspace["repo"], "sha": self.workspace["sha"]}
            doc["workspace"] = self.workspace
        else:
            doc["workspace"] = {"kind": "inline", "files": self.files}
        if self.protected:
            doc["protected"] = self.protected
        hidden = dict(self.hidden)
        if self.funcs:
            hidden["_grade.py"] = self.grader_source()
        if hidden:
            doc["hidden_files"] = hidden
        doc["turns"] = []
        for i, t in enumerate(self.turns, 1):
            d = {"prompt": t["prompt"], "checks": t["checks"]}
            if i in self.long_gaps:
                d["gap_before_s"] = 420
            doc["turns"].append(d)
        return doc

    def write(self):
        doc = self.to_doc()
        out = SCEN_DIR / self.family / f"{self.fname}.yaml"
        header = f"# holdout-v3 batch B ({self.ttype}, {len(self.turns)} turns): {self.desc}\n"
        out.write_text(header + yaml.dump(doc, Dumper=_Dumper, sort_keys=False, width=120, allow_unicode=True), encoding="utf-8")
        back = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert back == doc, f"yaml roundtrip mismatch for {self.id}"
        base = REFS / self.id
        import shutil
        if base.exists():
            shutil.rmtree(base)
        for i, t in enumerate(self.turns, 1):
            td = base / f"turn{i}"
            td.mkdir(parents=True)
            (td / "message.txt").write_text(t["msg"], encoding="utf-8")
            for rel, text in t["files"].items():
                p = td / "files" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            if t["delete"]:
                (td / "delete.txt").write_text("\n".join(t["delete"]), encoding="utf-8")
            (td / "meta.json").write_text(json.dumps({"bump": t["bump"]}), encoding="utf-8")
            if t["wrong_msg"] is not None or t["wrong_files"]:
                wd = td / "wrong"
                wd.mkdir()
                (wd / "message.txt").write_text(t["wrong_msg"] or "", encoding="utf-8")
                for rel, text in (t["wrong_files"] or {}).items():
                    p = wd / "files" / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(text, encoding="utf-8")
        return out


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, data):
    if "\n" in data and not any(ln != ln.rstrip() for ln in data.split("\n")) and "\t" not in data and "\r" not in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str)
