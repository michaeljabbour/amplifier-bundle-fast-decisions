import os, posixpath, random, re
from lib import Scn, exists, facts, numrx, rx, sections

SECS = ["guides", "api", "ops", "faq", "tutorials", "concepts", "security", "reference"]
TAGS = ["setup", "auth", "billing", "cli", "deploy", "errors", "limits", "metrics", "perf", "retries", "storage", "upgrade"]
WORDS = ["Alpha", "Birch", "Cedar", "Dune", "Ember", "Fjord", "Grove", "Harbor", "Iris", "Juniper", "Kelp", "Lagoon", "Maple", "Nectar", "Onyx", "Pine", "Quartz", "Reef", "Sage", "Tundra"]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def make(seed, per, secs):
    R = random.Random(seed)
    pages = {}
    for sec in secs:
        for i in range(per):
            slug = f"{WORDS[i % len(WORDS)].lower()}-{sec[:3]}-{i:02d}"
            title = f"{WORDS[i % len(WORDS)]} {sec} {i:02d}"
            pages[f"{sec}/{slug}.md"] = dict(title=title, tags=sorted(R.sample(TAGS, R.choice([1, 2, 2, 3]))), links=[])
    paths = sorted(pages)
    for p in paths:
        for t in R.sample(paths, R.choice([2, 3, 3])):
            if t == p:
                continue
            rel = posixpath.relpath(t, posixpath.dirname(p))
            pages[p]["links"].append((pages[t]["title"], rel + (R.choice(["", "", "#usage"]))))
    # plant renamed targets
    renames = {}
    cand = R.sample(paths, 24)
    for k in range(12):
        src, tgt = cand[2 * k], cand[2 * k + 1]
        old = tgt.replace(".md", "-old.md")
        renames[old] = tgt
        pages[src]["links"].append((pages[tgt]["title"], posixpath.relpath(old, posixpath.dirname(src))))
    return pages, renames


def page_text(p, d):
    body = f"# {d['title']}\n\nTags: {', '.join(d['tags'])}\n\n" + "".join(f"See [{t}]({l}).\n" for t, l in d["links"])
    return body


def resolve(src, target):
    t = target.split("#")[0]
    return posixpath.normpath(posixpath.join(posixpath.dirname(src), t))


def analyse(pages, extra_exist=()):
    exist = set(pages) | set(extra_exist)
    broken = sorted((p, l) for p, d in pages.items() for _, l in d["links"] if not l.startswith("#") and resolve(p, l) not in exist)
    inbound = {p: 0 for p in pages}
    for p, d in pages.items():
        for _, l in d["links"]:
            r = resolve(p, l)
            if r in inbound and r != p:
                inbound[r] += 1
    orphans = sorted(p for p, n in inbound.items() if n == 0)
    return broken, orphans


LINKCHECK = '''"""Link checker: python3 scripts/linkcheck.py [--root DIR] (default docs). Prints `BROKEN: <file relative to DIR> -> <target as written>` sorted, exit 1 if any; else `ok`."""
import argparse, os, posixpath, re

LINK = re.compile(r"\\[[^\\]]*\\]\\(([^)\\s]+)\\)")
ap = argparse.ArgumentParser()
ap.add_argument("--root", default="docs")
root = ap.parse_args().root
files = sorted(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/") for d, _, fs in os.walk(root) for f in fs if f.endswith(".md"))
exist = set(files)
bad = []
for f in files:
    for t in LINK.findall(open(os.path.join(root, f), encoding="utf-8").read()):
        if t.startswith(("http://", "https://", "#", "mailto:")):
            continue
        if posixpath.normpath(posixpath.join(posixpath.dirname(f), t.split("#")[0])) not in exist:
            bad.append(f"BROKEN: {f} -> {t}")
print("\\n".join(sorted(bad)) if bad else "ok")
raise SystemExit(1 if bad else 0)
'''


def build():
    s = Scn("docs-corpus", "mixed", "docs", "markdown",
            "A 320-page documentation tree with broken links, renames, tags and orphans: exact counts, broken-link and orphan reports, rename fixes across many files, tag index, per-section indexes, a link-checker CLI.",
            ["new generated documentation corpus; docs-maintenance theme (cf. amplifier-agent docs tasks); >300 files for the scope-gate subset"],
            protected=["docs/RENAMES.txt"], long_gaps=[4, 9])
    pages, renames = make(8013, 40, SECS)
    for p, d in pages.items():
        s.file(f"docs/{p}", page_text(p, d))
    s.file("docs/RENAMES.txt", "# renamed pages (old path -> new path, relative to docs/)\n" + "".join(f"{o} -> {n}\n" for o, n in renames.items()))
    s.file("docs/index.md", "# Documentation\n\nWelcome. Sections: " + ", ".join(SECS) + ".\n")
    s.file("README.md", "# docsite\n\nPages live in `docs/<section>/<slug>.md`. Each page has a `# Title` line, a `Tags:` line and links written as `[text](relative/path.md)`.\n")
    broken, orphans0 = analyse(pages)
    assert len(broken) == 12, len(broken)
    # after fixing renames
    fixed = {p: {**d, "links": [(t, (posixpath.relpath(renames[resolve(p, l)], posixpath.dirname(p)) + ("#" + l.split("#")[1] if "#" in l else "")) if resolve(p, l) in renames else l) for t, l in d["links"]]} for p, d in pages.items()}
    broken1, orphans1 = analyse(fixed)
    assert not broken1 and len(orphans1) != len(orphans0), (len(orphans0), len(orphans1))
    n = len(pages)
    s.turn("How many pages are under docs/<section>/ (every .md file in a section sub-folder), and how many internal links across them point to a file that does not exist? A link is `[text](target)`; resolve the target relative to the page's folder and ignore any `#fragment`. Do not change any files.",
           [facts(all=[numrx(n), numrx(len(broken))])], msg=f"ANSWER: {n} pages; {len(broken)} broken links", wrong_msg=f"ANSWER: {n} pages; {len(broken) + 3} broken links", bump=True)
    s.func("t2", f"""
        rows = md_rows('docs/_reports/broken-links.md')
        need(rows and [c.lower() for c in rows[0][:2]] == ['source', 'target'], 'header: ' + str(rows[:1]))
        got = [(r[0].strip('` '), r[1].strip('` ')) for r in rows[1:]]
        need(got == {broken!r}, 'rows differ: missing ' + str([w for w in {broken!r} if w not in got][:2]) + ' extra ' + str([g for g in got if g not in {broken!r}][:2]))
        """)
    rep = "# Broken links\n\n| source | target |\n|---|---|\n" + "".join(f"| {a} | {b} |\n" for a, b in broken)
    s.turn("Write docs/_reports/broken-links.md: a table (columns source, target) with one row per broken link: the page path relative to docs/ and the link target exactly as written; sorted by source, then target.",
           [s.g("t2")], files={"docs/_reports/broken-links.md": rep}, wrong_files={"docs/_reports/broken-links.md": rep.replace(f"| {broken[0][0]} | {broken[0][1]} |\n", "")})
    s.turn("Right now, how many section pages have no inbound link at all from any other section page (links to missing files do not count, self-links do not count)? Do not change any files.",
           [facts(all=[numrx(len(orphans0))])], msg=f"ANSWER: {len(orphans0)}", wrong_msg=f"ANSWER: {len(orphans0) + 4}", bump=True)
    fix_files = {}
    for p, d in pages.items():
        if any(resolve(p, l) in renames for _, l in d["links"]):
            fix_files[f"docs/{p}"] = page_text(p, fixed[p])
    s.func("t4", f"""
        import glob
        for rel, want in {fix_files!r}.items():
            need(read(rel).strip() == want.strip(), rel + ': link not fixed as expected')
        LINK = re.compile(r'\\[[^\\]]*\\]\\(([^)\\s]+)\\)')
        files = [p.replace(os.sep, '/') for p in glob.glob('docs/*/*.md')]
        exist = set(files)
        import posixpath
        bad = 0
        for f in files:
            if f.startswith('docs/_reports/'):
                continue
            for t in LINK.findall(read(f)):
                if not t.startswith(('http', '#')) and posixpath.normpath(posixpath.join(posixpath.dirname(f), t.split('#')[0])) not in exist:
                    bad += 1
        need(bad == 0, f'{{bad}} broken links remain')
        need(len([f for f in files if not f.startswith('docs/_reports/')]) == {n}, 'page count changed')
        """)
    w4 = dict(list(fix_files.items())[1:])
    s.turn("docs/RENAMES.txt lists pages that were renamed (old -> new). Fix every broken link by pointing it at the renamed page: keep the link text and any `#fragment`, change only the path (relative to the linking page). Do not touch other lines.",
           [s.g("t4")], files=fix_files, wrong_files=w4)
    tagpages = {}
    for p, d in pages.items():
        for t in d["tags"]:
            tagpages.setdefault(t, []).append(p)
    tagrows = {t: sorted((pages[p]["title"], p) for p in ps) for t, ps in tagpages.items()}
    tagdoc = "# Tags\n\n" + "".join(f"## {t}\n\n" + "".join(f"- [{ti}]({p})\n" for ti, p in tagrows[t]) + "\n" for t in sorted(tagrows))
    s.func("t5", f"""
        txt = read('docs/tags.md')
        got = {{}}
        for m in re.finditer(r'^## (\\S+)\\s*$(.*?)(?=^## |\\Z)', txt, re.M | re.S):
            got[m.group(1)] = re.findall(r'^- \\[([^\\]]+)\\]\\(([^)]+)\\)\\s*$', m.group(2), re.M)
        want = {({t: [(ti, p) for ti, p in v] for t, v in tagrows.items()})!r}
        need(list(got) == sorted(want), 'tag headings: ' + str(list(got)))
        need(got == want, 'tag membership/order differs for: ' + str([t for t in want if got.get(t) != want[t]][:3]))
        """)
    s.turn("Create docs/tags.md: for every tag used in the `Tags:` lines of the section pages a `## <tag>` heading (alphabetical) followed by a bullet per page with that tag, `- [<page title>](<path relative to docs/>)`, sorted by title.",
           [s.g("t5")], files={"docs/tags.md": tagdoc}, wrong_files={"docs/tags.md": tagdoc.replace(f"- [{tagrows[sorted(tagrows)[0]][0][0]}]", "- [X]", 1)})
    tc = {t: len(v) for t, v in tagpages.items()}
    top = max(tc, key=lambda k: tc[k])
    assert list(tc.values()).count(tc[top]) == 1
    s.turn("Which tag is used by the most pages, and by how many? Do not change any files.",
           [facts(all=[r"\b" + top + r"\b", numrx(tc[top])])], msg=f"ANSWER: {top}, {tc[top]} pages", wrong_msg=f"ANSWER: {top}, {tc[top] - 3} pages", bump=True)
    idxs = {}
    for sec in SECS:
        ps = sorted(((d["title"], p) for p, d in pages.items() if p.startswith(sec + "/")))
        idxs[f"docs/{sec}/index.md"] = f"# {sec.title()}\n\n" + "".join(f"- [{t}]({posixpath.basename(p)})\n" for t, p in ps)
    s.func("t7", f"""
        for rel, want in {idxs!r}.items():
            need(read(rel).strip() == want.strip(), rel + ': differs from the expected index')
        """)
    wi = dict(idxs)
    k = next(iter(wi))
    wi[k] = wi[k].replace("- [", "* [", 1)
    s.turn("Create docs/<section>/index.md for every section: a `# <Section>` title (section folder name capitalised, e.g. `# Guides`) and a bullet per page of that section, `- [<title>](<file name>)`, sorted by title. Do not list index.md itself.",
           [s.g("t7")], files=idxs, wrong_files=wi)
    alt = {"a.md": "# A\n\n[b](b.md) [ghost](ghost.md#x) [web](https://example.com/x.md)\n", "sub/c.md": "# C\n\n[up](../a.md) [bad](../zzz.md)\n"}
    s.func("t8", f"""
        for rel, text in {alt!r}.items():
            p = W / '_lc' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        (W / '_lc' / 'b.md').write_text('# B\\n', encoding='utf-8')
        need((W / 'scripts/linkcheck.py').exists(), 'missing scripts/linkcheck.py')
        chk_cmd_out('python3 scripts/linkcheck.py --root _lc', ['BROKEN: a.md -> ghost.md#x', 'BROKEN: sub/c.md -> ../zzz.md'], expect_rc=1)
        chk_cmd_out('python3 scripts/linkcheck.py', ['ok'])
        """)
    s.turn("Add scripts/linkcheck.py [--root DIR] (default docs): it walks DIR for *.md files and checks every `[text](target)` link that is not http(s), mailto or a bare #anchor; the target (fragment removed) resolved against the linking file's folder must be an existing .md file under DIR. Print `BROKEN: <file relative to DIR> -> <target as written>` sorted, exit 1; or print `ok` and exit 0.",
           [s.g("t8")], files={"scripts/linkcheck.py": LINKCHECK}, wrong_files={"scripts/linkcheck.py": LINKCHECK.replace('t.split("#")[0]', "t")})
    orph = "# Orphan pages\n\n" + "".join(f"- {p}\n" for p in orphans1)
    s.func("t9", f"""
        got = [l[2:].strip() for l in read('docs/_reports/orphans.md').splitlines() if l.startswith('- ')]
        need(got == {orphans1!r}, f'orphans: {{len(got)}} listed, want {len(orphans1)}; first diffs: ' + str([g for g in got if g not in {orphans1!r}][:2]))
        """)
    s.turn("Now that the renamed links are fixed, write docs/_reports/orphans.md: `# Orphan pages` and a bullet `- <path relative to docs/>` for every section page with no inbound link from another section page, sorted by path.",
           [s.g("t9")], files={"docs/_reports/orphans.md": orph}, wrong_files={"docs/_reports/orphans.md": "# Orphan pages\n\n" + "".join(f"- {p}\n" for p in orphans0)})
    s.turn("Add a '## Maintenance' section to README.md that explains `python3 scripts/linkcheck.py`, points at docs/_reports/broken-links.md and docs/_reports/orphans.md, and mentions docs/RENAMES.txt.",
           [sections("README.md", "Maintenance"), rx("README.md", r"scripts/linkcheck\.py"), rx("README.md", r"docs/_reports/orphans\.md"), rx("README.md", r"docs/RENAMES\.txt")],
           files={"README.md": s.files["README.md"] + "\n## Maintenance\n\nRun `python3 scripts/linkcheck.py`. Reports: docs/_reports/broken-links.md and docs/_reports/orphans.md. Renames are recorded in docs/RENAMES.txt.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Maintenance\n\nCheck links.\n"})
    return s
