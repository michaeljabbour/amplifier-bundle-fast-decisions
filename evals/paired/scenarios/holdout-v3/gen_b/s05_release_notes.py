import random, re
from lib import Scn, dedent, exists, facts, lblnum, numrx, rx, sections

TYPES = ["feature", "bugfix", "removal", "doc", "misc"]
TITLE = {"feature": "Features", "bugfix": "Bug fixes", "removal": "Removals", "doc": "Documentation", "misc": "Miscellaneous"}
TEXT = {
    "feature": ["Add retry support to the HTTP client.", "Add a `--json` flag to `pkg export`.", "Support reading configuration from `PKG_CONFIG`.", "Add `Client.close()` for explicit shutdown.",
                "Allow custom headers per request.", "Add progress bars to long exports.", "Support gzip uploads.", "Add `pkg doctor` to diagnose setups.", "Allow UTF-16 input files.", "Add a dry-run mode to `pkg sync`."],
    "bugfix": ["Fix a crash when the cache directory is read-only.", "Fix off-by-one in pagination.", "Handle empty responses without raising.", "Fix timezone drift in schedule parsing.", "Close sockets after failed handshakes.",
               "Fix `pkg sync` ignoring `--exclude`.", "Preserve key order when exporting.", "Fix a deadlock under heavy parallelism.", "Escape unicode paths in logs.", "Fix wrong exit code on timeout.",
               "Stop leaking file handles on retry.", "Fix a race in the token refresher.", "Respect `NO_COLOR` in all output.", "Fix duplicate entries in the audit log."],
    "removal": ["Remove the deprecated `legacy_mode` option."],
    "doc": ["Document the retry policy.", "Clarify install steps for Windows.", "Add a troubleshooting section.", "Fix typos in the API reference.", "Describe the cache layout.", "Add an FAQ for proxies."],
    "misc": ["Bump the minimum Python version to 3.9.", "Refresh the vendored certificates.", "Switch the test runner to pytest.", "Update the CI matrix.", "Pin linter versions.", "Drop an unused dependency."],
}


def make(seed, counts, start=200):
    R = random.Random(seed)
    issues = R.sample(range(start, start + 400), sum(counts.values()))
    frags, k = [], 0
    for t in TYPES:
        texts = TEXT[t][:]
        R.shuffle(texts)
        for j in range(counts.get(t, 0)):
            frags.append((issues[k], t, texts[j % len(texts)] if j < len(texts) else texts[0] + " (again)"))
            k += 1
    return frags


def section(version, date, frags):
    lines = [f"## {version} ({date})", ""]
    for t in TYPES:
        items = sorted((i, x) for i, ty, x in frags if ty == t)
        if items:
            lines += [f"### {TITLE[t]}", ""] + [f"- {x} (#{i})" for i, x in items] + [""]
    return lines


def bump(version, frags):
    a, b, c = map(int, version.split("."))
    ts = {t for _, t, _ in frags}
    if "removal" in ts:
        return f"{a + 1}.0.0"
    if "feature" in ts:
        return f"{a}.{b + 1}.0"
    return f"{a}.{b}.{c + 1}"


BUILD = '''"""Build a changelog section from news fragments: python3 tools/build_changelog.py --version X --date YYYY-MM-DD [--changes DIR]"""
import argparse, os, re

TYPES = ["feature", "bugfix", "removal", "doc", "misc"]
TITLE = {"feature": "Features", "bugfix": "Bug fixes", "removal": "Removals", "doc": "Documentation", "misc": "Miscellaneous"}


def load(d):
    out = []
    for name in sorted(os.listdir(d)):
        m = re.fullmatch(r"(\\d+)\\.(feature|bugfix|removal|doc|misc)\\.md", name)
        if m:
            out.append((int(m.group(1)), m.group(2), open(os.path.join(d, name), encoding="utf-8").read().strip()))
    return out


def section(version, date, frags):
    lines = [f"## {version} ({date})", ""]
    for t in TYPES:
        items = sorted((i, x) for i, ty, x in frags if ty == t)
        if items:
            lines += [f"### {TITLE[t]}", ""] + [f"- {x} (#{i})" for i, x in items] + [""]
    return lines


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--changes", default="changes")
    a = ap.parse_args()
    print("\\n".join(section(a.version, a.date, load(a.changes))))
'''
CHECK = '''"""Fragment lint: python3 tools/check_fragments.py [--changes DIR]. Prints bad file names, exit 1 if any."""
import argparse, os, re

ap = argparse.ArgumentParser()
ap.add_argument("--changes", default="changes")
bad = sorted(n for n in os.listdir(ap.parse_args().changes) if not n.startswith(".") and not re.fullmatch(r"\\d+\\.(feature|bugfix|removal|doc|misc)\\.md", n))
print("\\n".join(bad) if bad else "ok")
raise SystemExit(1 if bad else 0)
'''

OLD = """# Changelog

## 1.5.0 (2025-02-10)

### Features

- Add `--json` output to the CLI. (#101)
- Support environment overrides. (#118)

### Bug fixes

- Fix a crash on empty config files. (#122)

## 1.4.0 (2025-01-05)

### Features

- Add the `pkg sync` command. (#87)

### Bug fixes

- Fix wrong default timeout. (#90)
"""


def build():
    s = Scn("release-fragments", "mixed", "mixed", "python",
            "News-fragment directory to release notes: counts, SemVer bump rule, CHANGELOG section, version files, a build tool and a lint tool that generalise, a late removal that changes the version.",
            ["changelog-generation theme from ~/dev/amplifier-agent .amplifier/evaluation/tasks/benchmark/git-changelog-generator (rewritten: fragment directory instead of git log)"],
            protected=["pyproject.toml"], long_gaps=[4, 7])
    counts = {"feature": 10, "bugfix": 14, "doc": 6, "misc": 6}
    frags = make(7505, counts)
    # two issues with two fragments each
    frags[1] = (frags[0][0], frags[1][1], frags[1][2])           # same issue as the first feature (feature + feature) -> make it a bugfix/doc pair instead
    frags = sorted(frags)
    dup_base = frags[-1][0]
    frags = make(7505, counts)
    d1 = frags[0][0]
    frags[10] = (d1, frags[10][1], frags[10][2])                  # first bugfix shares an issue with the first feature
    d2 = frags[26][0]
    frags[30] = (d2, frags[30][1], frags[30][2])                  # a misc shares with a doc
    assert len({(i, t) for i, t, _ in frags}) == len(frags)
    dups = sorted({i for i, _, _ in frags if sum(1 for j, _, _ in frags if j == i) > 1})
    for i, t, x in frags:
        s.file(f"changes/{i}.{t}.md", x + "\n")
    s.file("CHANGELOG.md", OLD)
    s.file("VERSION", "1.5.0\n")
    s.file("src/pkg/__init__.py", '"""pkg - small example package."""\n__version__ = "1.5.0"\n')
    s.file("pyproject.toml", '[project]\nname = "pkg"\ndynamic = ["version"]\n')
    s.file("README.md", "# pkg\n\nRelease notes are assembled from the news fragments in `changes/` (`<issue>.<type>.md`, one line of text each).\nTypes: feature, bugfix, removal, doc, misc.\n")
    tc = {t: sum(1 for _, ty, _ in frags if ty == t) for t in TYPES}
    s.turn("Count the news fragments in changes/ by type (the second dot-separated part of the file name). Give the number of feature, bugfix, doc and misc fragments. Do not change any files.",
           [facts(all=[lblnum("feature", tc["feature"]), lblnum("bugfix", tc["bugfix"]), lblnum("doc", tc["doc"]), lblnum("misc", tc["misc"])])],
           msg=f"ANSWER: feature {tc['feature']}, bugfix {tc['bugfix']}, doc {tc['doc']}, misc {tc['misc']}",
           wrong_msg=f"ANSWER: feature {tc['feature']}, bugfix {tc['bugfix'] + 1}, doc {tc['doc']}, misc {tc['misc']}", bump=True)
    nv = bump("1.5.0", frags)
    s.turn("The current version is in VERSION. Release rule: any removal fragment means a major bump, otherwise any feature fragment means a minor bump, otherwise a patch bump. What is the next version? Do not change any files.",
           [facts(all=[r"(?<![\d.])" + re.escape(nv) + r"(?![\d])"])], msg=f"ANSWER: {nv}", wrong_msg="ANSWER: 1.5.1", bump=True)
    date = "2025-04-15"
    exp = section(nv, date, frags)
    s.func("t3", f"""
        lines = read('CHANGELOG.md').splitlines()
        idx = [i for i, ln in enumerate(lines) if ln.startswith('## ')]
        heads = [lines[i] for i in idx]
        need(heads[:3] == ['## {nv} ({date})', '## 1.5.0 (2025-02-10)', '## 1.4.0 (2025-01-05)'], 'section headings: ' + str(heads[:4]))
        end = idx[1]
        got = [l.rstrip() for l in lines[idx[0]:end]]
        while got and not got[-1]:
            got.pop()
        want = {exp[:-1]!r}
        need(got == want, 'new section differs: ' + str([g for g in got if g not in want][:3]) + ' / missing ' + str([w for w in want if w not in got][:3]))
        need('(#101)' in read('CHANGELOG.md') and '(#90)' in read('CHANGELOG.md'), 'old sections damaged')
        """)
    newcl = OLD.replace("# Changelog\n\n", "# Changelog\n\n" + "\n".join(exp) + "\n")
    wrongcl = newcl.replace(f"(#{frags[0][0]})", f"(#{frags[0][0] + 1})", 1)
    s.turn(f"Add a section for the next version, dated {date}, at the top of CHANGELOG.md (above 1.5.0). Format: `## <version> ({date})`, then a `### <Title>` block per type in the order Features, Bug fixes, Removals, Documentation, Miscellaneous (skip empty ones), each entry `- <fragment text> (#<issue>)` sorted by issue number ascending. Leave the old sections alone.",
           [s.g("t3")], files={"CHANGELOG.md": newcl}, wrong_files={"CHANGELOG.md": wrongcl}, bump=True)
    s.turn(f"Set the version to {nv} in both VERSION and src/pkg/__init__.py (`__version__`).",
           [rx("VERSION", r"^" + re.escape(nv) + r"\s*$"), rx("src/pkg/__init__.py", r'^__version__ = "' + re.escape(nv) + '"'), rx("VERSION", r"1\.5\.0", absent=True), rx("src/pkg/__init__.py", r"1\.5\.0", absent=True)],
           files={"VERSION": nv + "\n", "src/pkg/__init__.py": f'"""pkg - small example package."""\n__version__ = "{nv}"\n'},
           wrong_files={"VERSION": nv + "\n", "src/pkg/__init__.py": s.files["src/pkg/__init__.py"]}, bump=True)
    alt = make(66, {"feature": 2, "bugfix": 2, "removal": 1, "doc": 1}, start=500)
    aexp = section("3.0.0", "2025-06-01", alt)
    altfiles = {f"_alt/changes/{i}.{t}.md": x + "\n" for i, t, x in alt}
    s.func("t5", f"""
        for rel, text in {altfiles!r}.items():
            p = W / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        need((W / 'tools/build_changelog.py').exists(), 'missing tools/build_changelog.py')
        chk_cmd_out('python3 tools/build_changelog.py --version 3.0.0 --date 2025-06-01 --changes _alt/changes', {aexp[:-1]!r})
        rc, out, err = run('python3 tools/build_changelog.py --version {nv} --date {date}')
        need(rc == 0 and [l.rstrip() for l in out.rstrip().splitlines()] == {exp[:-1]!r}, 'default dir output differs')
        """)
    s.turn("Add tools/build_changelog.py: `python3 tools/build_changelog.py --version X --date YYYY-MM-DD [--changes DIR]` (default changes) prints on stdout exactly the changelog section described above (heading line, blank line, blocks), built from the fragments in DIR.",
           [s.g("t5")], files={"tools/build_changelog.py": BUILD}, wrong_files={"tools/build_changelog.py": BUILD.replace("sorted((i, x) for i, ty, x in frags if ty == t)", "sorted(((i, x) for i, ty, x in frags if ty == t), reverse=True)")})
    s.turn("A removal just landed: the `legacy_mode` option is dropped (issue 412). Add the fragment for it with the text `Remove the deprecated \\`legacy_mode\\` option.` (put the text in backticks exactly as written, one line).",
           [exists("changes/412.removal.md"), rx("changes/412.removal.md", r"^Remove the deprecated `legacy_mode` option\.\s*$")],
           files={"changes/412.removal.md": "Remove the deprecated `legacy_mode` option.\n"}, wrong_files={"changes/412.removal.md": "Remove legacy mode.\n"})
    frags2 = frags + [(412, "removal", "Remove the deprecated `legacy_mode` option.")]
    nv2 = bump("1.5.0", frags2)
    exp2 = section(nv2, date, frags2)
    s.func("t8", f"""
        lines = read('CHANGELOG.md').splitlines()
        heads = [l for l in lines if l.startswith('## ')]
        need(heads[:3] == ['## {nv2} ({date})', '## 1.5.0 (2025-02-10)', '## 1.4.0 (2025-01-05)'], 'headings: ' + str(heads[:4]))
        idx = [i for i, l in enumerate(lines) if l.startswith('## ')]
        got = [l.rstrip() for l in lines[idx[0]:idx[1]]]
        while got and not got[-1]:
            got.pop()
        need(got == {exp2[:-1]!r}, 'section differs')
        need(read('VERSION').strip() == '{nv2}' and '__version__ = "{nv2}"' in read('src/pkg/__init__.py'), 'version files')
        """)
    newcl2 = OLD.replace("# Changelog\n\n", "# Changelog\n\n" + "\n".join(exp2) + "\n")
    s.turn("Because the release is not out yet, recompute the next version with the removal fragment included, and replace the unreleased section at the top of CHANGELOG.md with the new one (no duplicate section for the old number). Update VERSION and src/pkg/__init__.py too.",
           [s.g("t8")], files={"CHANGELOG.md": newcl2, "VERSION": nv2 + "\n", "src/pkg/__init__.py": f'"""pkg - small example package."""\n__version__ = "{nv2}"\n'},
           wrong_files={"CHANGELOG.md": newcl, "VERSION": nv2 + "\n", "src/pkg/__init__.py": f'"""pkg - small example package."""\n__version__ = "{nv2}"\n'}, bump=True)
    s.turn("Which issue numbers appear in more than one fragment in changes/ (same number, different type)? List them. Do not change any files.",
           [facts(all=[r"(?<!\d)" + str(d) + r"(?!\d)" for d in dups])], msg="ANSWER: " + ", ".join(map(str, dups)), wrong_msg=f"ANSWER: {dups[0]}", bump=False)
    bad = ["12.feat.md", "abc.feature.md", "7.bugfix.txt", "notes.md"]
    good = ["5.feature.md", "9.doc.md"]
    s.func("t10", f"""
        d = W / '_lint'
        d.mkdir(exist_ok=True)
        for n in {bad + good + ['.gitkeep']!r}:
            (d / n).write_text('x\\n', encoding='utf-8')
        need((W / 'tools/check_fragments.py').exists(), 'missing tools/check_fragments.py')
        chk_cmd_out('python3 tools/check_fragments.py --changes _lint', {sorted(bad)!r}, expect_rc=1)
        for n in {bad!r}:
            (d / n).unlink()
        chk_cmd_out('python3 tools/check_fragments.py --changes _lint', ['ok'])
        chk_cmd_out('python3 tools/check_fragments.py', ['ok'])
        """)
    s.turn("Add tools/check_fragments.py [--changes DIR] (default changes): it prints every file name in DIR (ignoring names that start with a dot) that does not match `<digits>.<feature|bugfix|removal|doc|misc>.md`, one per line sorted, and exits 1; if all names are valid it prints `ok` and exits 0.",
           [s.g("t10")], files={"tools/check_fragments.py": CHECK}, wrong_files={"tools/check_fragments.py": CHECK.replace("raise SystemExit(1 if bad else 0)", "raise SystemExit(0)")})
    return s
