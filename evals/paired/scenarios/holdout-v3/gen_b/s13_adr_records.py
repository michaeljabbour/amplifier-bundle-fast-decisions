import random, re
from lib import Scn, exists, facts, numrx, rx, sections

NOTES = [  # slug, title, date, status, replaces(slug|None), context, decision, consequences
    ("use-postgres", "Use PostgreSQL for orders", "2025-01-14", "accepted", None, "Orders outgrew the single SQLite file and need concurrent writers.", "Store orders in PostgreSQL 15 behind a repository interface.", "We must run and back up a database server; migrations become mandatory."),
    ("adopt-rest", "Expose a REST API", "2025-01-21", "accepted", None, "Partners ask for a stable integration surface.", "Publish a versioned REST API under /v1 with JSON bodies.", "Clients get a stable contract; breaking changes require /v2."),
    ("graphql-gateway", "Add a GraphQL gateway", "2025-02-03", "rejected", None, "The mobile team wanted flexible queries.", "Do not build a GraphQL gateway this year.", "Mobile keeps using REST with a few purpose-built endpoints."),
    ("queue-rabbit", "Use RabbitMQ for background jobs", "2025-02-11", "accepted", None, "Email and export jobs block request threads.", "Run jobs through RabbitMQ with a worker pool of 8.", "Operations owns another stateful service; jobs gain retries."),
    ("cache-memory", "Cache lookups in process memory", "2025-02-18", "accepted", None, "Catalogue reads dominate traffic.", "Keep a 60 second in-process cache for catalogue reads.", "Each instance warms its own cache; staleness is bounded by 60 seconds."),
    ("monorepo", "Move to a monorepo", "2025-02-25", "rejected", None, "Three repositories drift apart.", "Stay with separate repositories and share code through a package.", "Release coordination stays manual."),
    ("jobs-sqs", "Use SQS instead of RabbitMQ", "2025-03-05", "accepted", "queue-rabbit", "Running RabbitMQ costs more on-call time than the jobs justify.", "Move background jobs to the managed SQS service.", "No broker to patch; message size is capped at 256 KB."),
    ("structured-logs", "Emit structured JSON logs", "2025-03-12", "accepted", None, "Grepping free-text logs does not scale.", "All services log one JSON object per line.", "Log tooling must parse JSON; local reading is harder."),
    ("feature-flags", "Use a feature flag service", "2025-03-19", "proposed", None, "Releases are coupled to deploys.", "Evaluate a hosted flag service for a quarter.", "Decision deferred until the trial ends."),
    ("api-v2", "Replace /v1 with /v2 in 2026", "2025-03-27", "accepted", None, "The /v1 pagination model cannot be extended.", "Introduce /v2 with cursor pagination and sunset /v1 in 2026.", "Two versions run side by side for a year."),
    ("cache-redis", "Move the cache to Redis", "2025-04-02", "accepted", "cache-memory", "Per-instance caches show inconsistent prices.", "Use a shared Redis 7 cache with a 60 second TTL.", "A new dependency; cache is consistent across instances."),
    ("sunset-v1", "Announce the /v1 sunset date", "2025-04-09", "proposed", None, "Partners need a date to plan against.", "Propose 2026-06-30 as the /v1 shutdown date.", "Partner communication is required before acceptance."),
]
CUT = "2025-04-01"
STATUS = {"accepted": "Accepted", "rejected": "Rejected", "proposed": "Proposed", "superseded": "Superseded"}


def num_of(i):
    return f"{i:04d}"


def note_text(n):
    return f"slug: {n[0]}\ntitle: {n[1]}\ndate: {n[2]}\nstatus: {n[3]}\nreplaces: {n[4] or 'none'}\ncontext: {n[5]}\ndecision: {n[6]}\nconsequences: {n[7]}\n"


def adr(i, n, sup=None, sup_by=None, status=None):
    return (f"# ADR-{num_of(i)}: {n[1]}\n\n- Status: {STATUS[status or n[3]]}\n- Date: {n[2]}\n- Supersedes: {('ADR-' + num_of(sup)) if sup else 'none'}\n- Superseded by: {('ADR-' + num_of(sup_by)) if sup_by else 'none'}\n\n"
            f"## Context\n\n{n[5]}\n\n## Decision\n\n{n[6]}\n\n## Consequences\n\n{n[7]}\n")


def numbering(notes):
    order = sorted(notes, key=lambda n: (n[2], n[0]))
    return {n[0]: i for i, n in enumerate(order, 1)}, order


LINT = '''"""ADR lint: python3 scripts/adr_lint.py [--dir DIR] (default docs/adr). Prints one problem per line, sorted, exit 1 if any; else `ok`.
Problems: `ADR-NNNN: missing section <Name>` (Context, Decision, Consequences), `ADR-NNNN: bad status <value>` (allowed: Proposed, Accepted, Rejected, Superseded),
`ADR-NNNN: superseded without successor` (Status Superseded but `Superseded by: none`)."""
import argparse, glob, os, re

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="docs/adr")
out = []
for p in sorted(glob.glob(os.path.join(ap.parse_args().dir, "[0-9][0-9][0-9][0-9]-*.md"))):
    t = open(p, encoding="utf-8").read()
    ident = "ADR-" + os.path.basename(p)[:4]
    for sec in ("Context", "Decision", "Consequences"):
        if not re.search(r"^## " + sec + r"\\s*$", t, re.M):
            out.append(f"{ident}: missing section {sec}")
    m = re.search(r"^- Status:\\s*(.*?)\\s*$", t, re.M)
    st = m.group(1) if m else ""
    if st not in ("Proposed", "Accepted", "Rejected", "Superseded"):
        out.append(f"{ident}: bad status {st}")
    if st == "Superseded" and re.search(r"^- Superseded by:\\s*none\\s*$", t, re.M):
        out.append(f"{ident}: superseded without successor")
print("\\n".join(sorted(out)) if out else "ok")
raise SystemExit(1 if out else 0)
'''


def build():
    s = Scn("adr-records", "mixed", "docs", "markdown",
            "Turn meeting-note decisions into architecture decision records: numbering by date, exact section content, supersession chains, an index, an ADR linter, and a second batch of notes that changes the chain.",
            ["new self-authored decision notes; ADR-writing theme (cf. amplifier-agent documentation tasks)"],
            protected=[f"notes/{n[2]}-{n[0]}.txt" for n in NOTES])
    for n in NOTES:
        s.file(f"notes/{n[2]}-{n[0]}.txt", note_text(n))
    s.file("README.md", f"# decisions\n\n`notes/` holds one decision note per file (`slug`, `title`, `date`, `status`, `replaces`, `context`, `decision`, `consequences`). Architecture decision records go in `docs/adr/` as `NNNN-<slug>.md`, numbered 0001, 0002, ... in order of the note's date (ties by slug).\n")
    early = [n for n in NOTES if n[2] < CUT]
    num1, order1 = numbering(early)
    num2, order2 = numbering(NOTES)
    rej = sorted(n[0] for n in early if n[3] == "rejected")
    s.turn(f"How many decision notes in notes/ are dated before {CUT}, and which of those have status rejected (give their slugs)? Do not change any files.",
           [facts(all=[numrx(len(early)), *(re.escape(x) for x in rej)])], msg=f"ANSWER: {len(early)} notes; rejected: {', '.join(rej)}", wrong_msg=f"ANSWER: {len(early)} notes; rejected: {rej[0]}", bump=True)

    def grader(group, numbers, sup_info):
        exp = {}
        for n in group:
            i = numbers[n[0]]
            sup, by, st = sup_info.get(n[0], (None, None, None))
            exp[f"docs/adr/{num_of(i)}-{n[0]}.md"] = adr(i, n, sup, by, st)
        return exp
    s.func("t2", """
        def check(files):
            for p, want in files.items():
                got = read(p)
                need(got.strip() == want.strip(), f'{p}: content differs from expected (first lines: {got.splitlines()[:6]})')
        """)  # placeholder replaced below
    first4 = order1[:4]
    rest = order1[4:]
    f2 = grader(first4, num1, {})
    f3 = grader(rest, num1, {})
    def gfunc(name, files):
        s.func(name, f"""
        for p, want in {files!r}.items():
            got = read(p)
            def norm(t):
                return [l.rstrip() for l in t.strip().splitlines() if l.strip()]
            need(norm(got) == norm(want), f'{{p}}: expected {{norm(want)[:5]}} got {{norm(got)[:5]}}')
        import glob
        need(len(glob.glob('docs/adr/[0-9][0-9][0-9][0-9]-*.md')) == {len(files)}, 'unexpected number of ADR files: ' + str(sorted(glob.glob('docs/adr/*.md'))))
        """)
    del s.funcs["t2"]
    gfunc("t2", f2)
    ex = ("Each ADR is `docs/adr/<NNNN>-<slug>.md` and has exactly this layout: `# ADR-<NNNN>: <title>`, then the lines `- Status: <Accepted|Rejected|Proposed>` (from the note's status), `- Date: <date>`, `- Supersedes: none`, `- Superseded by: none`, then `## Context`, `## Decision` and `## Consequences` sections whose text is the note's context, decision and consequences lines verbatim.")
    w2 = dict(f2)
    k = next(iter(w2))
    w2[k] = w2[k].replace("## Decision", "## Decisions")
    s.turn(f"Write the ADRs for the four earliest notes dated before {CUT}. Number by note date (ties by slug), starting at 0001. {ex} Do not write ADRs for later notes yet.",
           [s.g("t2")], files=f2, wrong_files=w2)
    allf = {**f2, **f3}
    gfunc("t3", allf)
    w3 = dict(f3)
    k = list(w3)[-1]
    w3[k] = w3[k].replace("- Status: Accepted", "- Status: Proposed").replace("- Status: Rejected", "- Status: Accepted")
    s.turn(f"Write the remaining ADRs for the notes dated before {CUT}, continuing the numbering by date, same layout.",
           [s.g("t3")], files=f3, wrong_files=w3)
    # supersession (early set): jobs-sqs replaces queue-rabbit
    s1 = {}
    for n in early:
        if n[4]:
            s1[n[4]] = (None, num1[n[0]], "superseded")
            s1[n[0]] = (num1[n[4]], None, None)
    old, new = [n for n in early if n[4]][0], None
    new = old
    oldn = [n for n in early if n[0] == old[4]][0]
    s.turn("Which note replaces an earlier decision, which ADR number does it get, and what is the ADR number of the decision it replaces? Do not change any files.",
           [facts(all=[r"ADR-?" + num_of(num1[old[0]]) + "|" + str(num1[old[0]]), r"ADR-?" + num_of(num1[oldn[0]]) + "|" + str(num1[oldn[0]]), re.escape(old[0])])],
           msg=f"ANSWER: {old[0]} (ADR-{num_of(num1[old[0]])}) replaces {oldn[0]} (ADR-{num_of(num1[oldn[0]])})", wrong_msg="ANSWER: nothing is replaced", bump=False)
    f5 = grader(early, num1, s1)
    gfunc("t5", f5)
    changed = {p: t for p, t in f5.items() if t != allf[p]}
    wrongc = {p: allf[p] for p in changed}
    s.turn("Apply supersession from the `replaces` lines: in the replacing ADR set `- Supersedes: ADR-<number of the replaced ADR>`; in the replaced ADR set `- Status: Superseded` and `- Superseded by: ADR-<number of the replacing ADR>`. Leave everything else unchanged.",
           [s.g("t5")], files=changed, wrong_files=wrongc)
    def index_for(notes, numbers, sup_info):
        rows = sorted(notes, key=lambda n: numbers[n[0]])
        return "# Decision log\n\n| ADR | title | status | date |\n|---|---|---|---|\n" + "".join(
            f"| [ADR-{num_of(numbers[n[0]])}]({num_of(numbers[n[0]])}-{n[0]}.md) | {n[1]} | {STATUS[sup_info.get(n[0], (None, None, None))[2] or n[3]]} | {n[2]} |\n" for n in rows)
    def idx_grader(name, notes, numbers, sup_info):
        rows = sorted(notes, key=lambda n: numbers[n[0]])
        s.func(name, f"""
        rows = md_rows('docs/adr/README.md')
        need(rows and [c.lower() for c in rows[0][:4]] == ['adr', 'title', 'status', 'date'], 'header: ' + str(rows[:1]))
        want = {[(f"ADR-{num_of(numbers[n[0]])}", f"{num_of(numbers[n[0]])}-{n[0]}.md", n[1], STATUS[sup_info.get(n[0], (None, None, None))[2] or n[3]], n[2]) for n in rows]!r}
        got = []
        for r in rows[1:]:
            m = re.fullmatch(r'\\[([^\\]]+)\\]\\(([^)]+)\\)', r[0].strip())
            need(m, 'ADR cell must be a markdown link: ' + r[0])
            need((W / 'docs/adr' / m.group(2)).exists(), 'broken link ' + m.group(2))
            got.append((m.group(1), m.group(2), r[1], r[2], r[3]))
        need(got == want, 'index rows differ: ' + str([g for g in got if g not in want][:2]))
        """)
    idx_grader("t6", early, num1, s1)
    i1 = index_for(early, num1, s1)
    s.turn("Create docs/adr/README.md: a `# Decision log` title and a table (columns ADR, title, status, date), one row per ADR in number order. The ADR cell is a relative link like `[ADR-0001](0001-use-postgres.md)`; status is the ADR's current status.",
           [s.g("t6")], files={"docs/adr/README.md": i1}, wrong_files={"docs/adr/README.md": i1.replace("| Accepted |", "| Proposed |", 1)})
    alt = {"0001-a.md": "# ADR-0001: A\n\n- Status: Accepted\n- Date: 2025-01-01\n- Supersedes: none\n- Superseded by: none\n\n## Context\n\nx\n\n## Decision\n\ny\n\n## Consequences\n\nz\n",
           "0002-b.md": "# ADR-0002: B\n\n- Status: Maybe\n- Date: 2025-01-02\n- Supersedes: none\n- Superseded by: none\n\n## Context\n\nx\n\n## Decision\n\ny\n",
           "0003-c.md": "# ADR-0003: C\n\n- Status: Superseded\n- Date: 2025-01-03\n- Supersedes: none\n- Superseded by: none\n\n## Context\n\nx\n\n## Decision\n\ny\n\n## Consequences\n\nz\n"}
    want = sorted(["ADR-0002: bad status Maybe", "ADR-0002: missing section Consequences", "ADR-0003: superseded without successor"])
    s.func("t7", f"""
        for rel, text in {alt!r}.items():
            p = W / '_adr' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        need((W / 'scripts/adr_lint.py').exists(), 'missing scripts/adr_lint.py')
        chk_cmd_out('python3 scripts/adr_lint.py --dir _adr', {want!r}, expect_rc=1)
        chk_cmd_out('python3 scripts/adr_lint.py', ['ok'])
        """)
    s.turn("Add scripts/adr_lint.py [--dir DIR] (default docs/adr). For every NNNN-*.md in DIR it reports, one line each: `ADR-NNNN: missing section <Name>` for a missing Context, Decision or Consequences heading; `ADR-NNNN: bad status <value>` when the Status is not Proposed, Accepted, Rejected or Superseded; `ADR-NNNN: superseded without successor` when the status is Superseded but `Superseded by` is none. Print the lines sorted and exit 1, or print `ok` and exit 0.",
           [s.g("t7")], files={"scripts/adr_lint.py": LINT}, wrong_files={"scripts/adr_lint.py": LINT.replace('"Proposed", "Accepted", "Rejected", "Superseded"', '"Proposed", "Accepted", "Rejected", "Superseded", "Maybe"')})
    # second batch
    s2 = {}
    for n in NOTES:
        if n[4]:
            s2[n[4]] = (None, num2[n[0]], "superseded")
            s2[n[0]] = (num2[n[4]], None, None)
    late = [n for n in order2 if n[2] >= CUT]
    f8 = grader(NOTES, num2, s2)
    gfunc("t8", f8)
    renumbered = {p: t for p, t in f8.items() if p not in f5 or t != f5[p]}
    assert all(num2[n[0]] == num1[n[0]] for n in early), "late notes must not renumber early ones"
    wrong8 = {p: t for p, t in renumbered.items() if "cache-redis" not in p and "cache-memory" not in p}
    s.turn(f"Notes dated {CUT} or later are now in scope. Write ADRs for them, continuing the numbering by date, same layout, and apply the supersession their `replaces` lines imply (including the Status and Superseded by of the replaced ADR).",
           [s.g("t8")], files=renumbered, wrong_files={p: t for p, t in renumbered.items() if "cache-redis" in p})
    idx_grader("t9", NOTES, num2, s2)
    i2 = index_for(NOTES, num2, s2)
    s.turn("Update docs/adr/README.md so it lists every ADR, with current statuses.",
           [s.g("t9")], files={"docs/adr/README.md": i2}, wrong_files={"docs/adr/README.md": i1})
    cur = [n for n in NOTES if n[3] == "accepted" and n[0] not in s2 or False]
    s.turn("Add a '## Decisions' section to README.md that links docs/adr/README.md, explains the numbering rule (by note date, ties by slug) and mentions scripts/adr_lint.py.",
           [sections("README.md", "Decisions"), rx("README.md", r"docs/adr/README\.md"), rx("README.md", r"(?i)ties"), rx("README.md", r"scripts/adr_lint\.py")],
           files={"README.md": s.files["README.md"] + "\n## Decisions\n\nSee docs/adr/README.md. ADRs are numbered by note date, ties by slug. Run scripts/adr_lint.py to check them.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Decisions\n\nSee docs.\n"})
    return s
