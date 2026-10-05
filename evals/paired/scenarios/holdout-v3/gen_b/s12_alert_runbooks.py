import random
from lib import Scn, csv_text, exists, facts, numrx, rx, sections

TEAMS = [("platform", "pat.lee@example.com", "#platform-oncall"), ("payments", "dana.cho@example.com", "#payments-oncall"), ("search", "omar.nash@example.com", "#search-oncall"), ("data", "ines.wu@example.com", "#data-oncall")]
SERVICES = [("gateway", "tier1"), ("checkout-api", "tier1"), ("ledger", "tier1"), ("search-api", "tier2"), ("indexer", "tier2"), ("etl", "tier3"), ("reports", "tier3"), ("mailer", "tier3")]
KINDS = [("High error rate", "error_rate_5m > {a}%"), ("High latency", "p99_latency_ms > {b}"), ("Queue backlog", "queue_depth > {b}"), ("Disk nearly full", "disk_used_pct > {a}"), ("Pod restarts", "restarts_15m >= {c}"),
         ("Low throughput", "requests_per_s < {c}"), ("Cert expiring", "cert_days_left < {c}"), ("Stale data", "data_age_min > {b}")]


def make(seed, n):
    R = random.Random(seed)
    sevs = ["P1"] * 3 + ["P2"] * 4 + ["P3"] * 4 + ["P4"] * (n - 11)
    rows = []
    for i in range(n):
        name, expr = R.choice(KINDS)
        svc = SERVICES[R.randrange(len(SERVICES))][0]
        rows.append([f"AL-{101 + i * 3}", f"{name} ({svc})", sevs[i], svc, expr.format(a=R.choice([2, 5, 85, 90, 95]), b=R.choice([200, 500, 1000, 5000]), c=R.choice([3, 5, 7, 14, 30])),
                     TEAMS[R.randrange(len(TEAMS))][0], R.choice([5, 10, 15, 30, 60]) if True else 0])
    R.shuffle(rows)
    return rows


def runbook(a, tier, team):
    return (f"# {a[1]}\n\n## Trigger\n\n`{a[4]}` on service `{a[3]}` ({tier}).\n\n## Severity\n\n{a[2]}\n\n## Owner\n\n"
            f"{a[5]}, on-call {team[1]}, channel {team[2]}\n\n## Escalation\n\nEscalate after {a[6]} minutes.\n")


def build():
    s = Scn("alert-runbooks", "mixed", "docs", "markdown",
            "Turn alert definitions (CSV) into runbook pages, an index, an escalation matrix and link-checked cross references; exact per-file content checks across 14 generated pages.",
            ["new self-authored alert catalogue; runbook-writing theme (cf. amplifier-agent docs/ops tasks)"],
            protected=["data/alerts.csv", "data/teams.csv", "data/services.csv"])
    alerts = make(7912, 14)
    s.file("data/alerts.csv", csv_text(["alert_id", "name", "severity", "service", "threshold", "owner_team", "escalate_after_min"], alerts))
    s.file("data/teams.csv", csv_text(["team", "oncall", "channel"], TEAMS))
    s.file("data/services.csv", csv_text(["service", "tier"], SERVICES))
    s.file("README.md", "# ops-docs\n\nAlert definitions live in `data/alerts.csv`; owners in `data/teams.csv`; service tiers in `data/services.csv`. Runbooks go in `docs/runbooks/`.\n")
    tier = dict(SERVICES)
    team = {t[0]: t for t in TEAMS}
    sev = {p: sum(1 for a in alerts if a[2] == p) for p in ("P1", "P2", "P3", "P4")}
    tc = {}
    for a in alerts:
        tc[a[5]] = tc.get(a[5], 0) + 1
    top = max(tc, key=lambda k: tc[k])
    assert list(tc.values()).count(tc[top]) == 1, tc
    s.turn("How many alerts are defined at each severity (P1, P2, P3, P4) in data/alerts.csv? Do not change any files.",
           [facts(all=[rf"{p}\D{{0,6}}" + numrx(sev[p]) for p in sev])], msg="ANSWER: " + ", ".join(f"{p} {sev[p]}" for p in sev), wrong_msg="ANSWER: " + ", ".join(f"{p} {sev[p] + (p == 'P2')}" for p in sev), bump=True)
    s.turn("Which team owns the most alerts, and how many? Do not change any files.",
           [facts(all=[r"\b" + top + r"\b", numrx(tc[top])])], msg=f"ANSWER: {top} owns {tc[top]}", wrong_msg=f"ANSWER: {top} owns {tc[top] + 1}", bump=True)
    order = sorted(alerts, key=lambda a: (a[2], a[0]))
    s.func("t3", f"""
        rows = md_rows('docs/runbooks/index.md')
        need(rows and [c.lower() for c in rows[0][:5]] == ['alert_id', 'name', 'severity', 'service', 'owner'], 'header: ' + str(rows[:1]))
        got = [[c.strip('` ') for c in r[:5]] for r in rows[1:]]
        want = {[[a[0], a[1], a[2], a[3], a[5]] for a in order]!r}
        need(got == want, 'index rows differ: first mismatch ' + str(next(((g, w) for g, w in zip(got, want) if g != w), len(got))))
        """)
    idx = "# Runbooks\n\n| alert_id | name | severity | service | owner |\n|---|---|---|---|---|\n" + "".join(f"| {a[0]} | {a[1]} | {a[2]} | {a[3]} | {a[5]} |\n" for a in order)
    s.turn("Create docs/runbooks/index.md titled `# Runbooks` with a table (columns alert_id, name, severity, service, owner) listing every alert, sorted by severity (P1 first) and then alert_id.",
           [s.g("t3")], files={"docs/runbooks/index.md": idx}, wrong_files={"docs/runbooks/index.md": idx.replace(order[0][0], order[1][0], 1)})
    def rb_grader(ids):
        exp = {a[0]: dict(title=a[1], trig=a[4], svc=a[3], tier=tier[a[3]], sev=a[2], team=a[5], oncall=team[a[5]][1], chan=team[a[5]][2], esc=a[6]) for a in alerts if a[0] in ids}
        return f"""
        for aid, e in {exp!r}.items():
            p = f'docs/runbooks/{{aid}}.md'
            t = read(p)
            need(t.splitlines()[0].strip() == '# ' + e['title'], aid + ': title')
            def sec(name):
                m = re.search(r'^## ' + name + r'\\s*$(.*?)(?=^## |\\Z)', t, re.M | re.S)
                need(m, aid + ': missing ## ' + name)
                return m.group(1)
            need(e['trig'] in sec('Trigger') and e['svc'] in sec('Trigger') and e['tier'] in sec('Trigger'), aid + ': trigger section')
            need(sec('Severity').strip() == e['sev'], aid + ': severity section must be just ' + e['sev'])
            o = sec('Owner')
            need(e['team'] in o and e['oncall'] in o and e['chan'] in o, aid + ': owner section')
            need(re.search(r'(?<!\\d)' + str(e['esc']) + r'(?!\\d)', sec('Escalation')), aid + ': escalation minutes')
        """
    p1 = [a for a in order if a[2] == "P1"]
    p2 = [a for a in order if a[2] == "P2"]
    rest = [a for a in order if a[2] in ("P3", "P4")]
    ids1, ids2, ids3 = [a[0] for a in p1], [a[0] for a in p1 + p2], [a[0] for a in alerts]
    s.func("t4", rb_grader(ids1))
    s.func("t5", rb_grader(ids2))
    s.func("t6", rb_grader(ids3))
    files = lambda grp: {f"docs/runbooks/{a[0]}.md": runbook(a, tier[a[3]], team[a[5]]) for a in grp}
    tpl = ("Create one runbook page per P1 alert as docs/runbooks/<alert_id>.md with exactly this layout: `# <name>`; `## Trigger` with the threshold in backticks, the service in backticks and its tier from data/services.csv in parentheses (e.g. `error_rate_5m > 5%` on service `ledger` (tier1).); "
           "`## Severity` containing only the severity; `## Owner` with `<team>, on-call <oncall email>, channel <channel>` from data/teams.csv; `## Escalation` saying `Escalate after <N> minutes.`")
    w4 = files(p1)
    k = next(iter(w4))
    w4[k] = w4[k].replace("minutes", "minutes").replace(f"after {p1[0][6]} minutes", f"after {p1[0][6] + 5} minutes")
    s.turn(tpl, [s.g("t4")], files=files(p1), wrong_files=w4)
    w5 = files(p2)
    k = next(iter(w5))
    w5[k] = w5[k].replace(team[p2[0][5]][2], "#wrong")
    s.turn("Do the same for every P2 alert (same layout, same sources).", [s.g("t5")], files=files(p2), wrong_files=w5)
    w6 = files(rest)
    k = next(iter(w6))
    w6[k] = w6[k].replace(f"`{rest[0][4]}`", "`x > 1`")
    s.turn("Do the same for all remaining alerts (P3 and P4). Every alert in data/alerts.csv must now have a runbook.", [s.g("t6")], files=files(rest), wrong_files=w6)
    quick = sorted(a[0] for a in alerts if a[6] <= 10)
    s.turn("Which alerts escalate after 10 minutes or less? List their alert ids. Do not change any files.",
           [facts(all=[a for a in quick])], msg="ANSWER: " + ", ".join(quick), wrong_msg="ANSWER: " + ", ".join(quick[:-1]), bump=False)
    grid = {t[0]: {p: sum(1 for a in alerts if a[5] == t[0] and a[2] == p) for p in ("P1", "P2", "P3", "P4")} for t in TEAMS}
    s.func("t8", f"""
        rows = md_rows('docs/escalation-matrix.md')
        need(rows and [c.lower() for c in rows[0][:6]] == ['team', 'p1', 'p2', 'p3', 'p4', 'total'], 'header: ' + str(rows[:1]))
        got = {{r[0].strip('` '): [int(num(c)) for c in r[1:6]] for r in rows[1:] if len(r) >= 6}}
        want = {({t: [g["P1"], g["P2"], g["P3"], g["P4"], sum(g.values())] for t, g in grid.items()})!r}
        need(got == want, f'matrix {{got}} != {{want}}')
        need(len(got) == {len(TEAMS)}, 'one row per team')
        """)
    mat = "# Escalation matrix\n\n| team | P1 | P2 | P3 | P4 | total |\n|---|---|---|---|---|---|\n" + "".join(f"| {t} | {g['P1']} | {g['P2']} | {g['P3']} | {g['P4']} | {sum(g.values())} |\n" for t, g in grid.items())
    s.turn("Write docs/escalation-matrix.md with a table (columns team, P1, P2, P3, P4, total): one row per team in data/teams.csv order, counting the alerts it owns at each severity, plus the row total.",
           [s.g("t8")], files={"docs/escalation-matrix.md": mat}, wrong_files={"docs/escalation-matrix.md": mat.replace(f"| {TEAMS[0][0]} |", f"| {TEAMS[0][0]} | 9 |", 1)}, bump=True)
    idx2 = "# Runbooks\n\n| alert_id | name | severity | service | owner | runbook |\n|---|---|---|---|---|---|\n" + "".join(f"| {a[0]} | {a[1]} | {a[2]} | {a[3]} | {a[5]} | [{a[0]}]({a[0]}.md) |\n" for a in order)
    s.func("t9", f"""
        rows = md_rows('docs/runbooks/index.md')
        need(len(rows[0]) >= 6 and rows[0][5].lower() == 'runbook', 'sixth column must be runbook')
        for r, a in zip(rows[1:], {[a[0] for a in order]!r}):
            m = re.fullmatch(r'\\[([^\\]]+)\\]\\(([^)]+)\\)', r[5].strip())
            need(m and m.group(1) == a and m.group(2) == a + '.md', a + ': link cell ' + r[5])
            need((W / 'docs/runbooks' / m.group(2)).exists(), 'broken link ' + m.group(2))
        need([r[0] for r in rows[1:]] == {[a[0] for a in order]!r}, 'row order preserved')
        """)
    s.turn("Add a sixth column `runbook` to the table in docs/runbooks/index.md: a relative markdown link `[<alert_id>](<alert_id>.md)` for each row. Keep the row order.",
           [s.g("t9")], files={"docs/runbooks/index.md": idx2}, wrong_files={"docs/runbooks/index.md": idx2.replace(f"({order[0][0]}.md)", f"({order[0][0]}.txt)")})
    s.turn("Add a '## Runbooks' section to README.md that links docs/runbooks/index.md and docs/escalation-matrix.md and says every alert in data/alerts.csv has a page.",
           [sections("README.md", "Runbooks"), rx("README.md", r"docs/runbooks/index\.md"), rx("README.md", r"docs/escalation-matrix\.md"), rx("README.md", r"data/alerts\.csv", 2)],
           files={"README.md": s.files["README.md"] + "\n## Runbooks\n\nSee docs/runbooks/index.md and docs/escalation-matrix.md. Every alert in data/alerts.csv has a runbook page.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Runbooks\n\nSee docs.\n"})
    return s
