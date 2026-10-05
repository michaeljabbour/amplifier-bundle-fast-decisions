import hashlib, json, random
from lib import Scn, csv_text, dedent, exists, facts, numrx, rx, sections

TEAMS = ["billing", "catalog", "checkout", "identity", "logistics", "search", "support", "telemetry"]
RULES5 = ["unpinned_image", "single_replica", "oversized_memory", "plaintext_secret", "no_healthcheck"]


def make(seed, teams, per_team):
    R = random.Random(seed)
    svcs = {}
    for t in teams:
        for k in range(per_team):
            name = f"{t}-{R.choice(['api', 'worker', 'cron', 'web', 'sync', 'proxy'])}-{k:02d}"
            tag = R.choices(["latest", "", "1.%d.%d" % (R.randint(0, 9), R.randint(0, 9)), "2.%d.0" % R.randint(0, 5)], [15, 5, 50, 30])[0]
            env = {"LOG_LEVEL": "info", "DB_HOST": f"{t}-db"}
            if R.random() < 0.3:
                env["API_TOKEN"] = R.choice(["${VAULT:api_token}", f"tok_{R.randint(10**5, 10**6)}"])
            if R.random() < 0.25:
                env["DB_PASSWORD"] = R.choice(["${VAULT:db_password}", "hunter%d" % R.randint(1, 99)])
            d = dict(name=name, team=t, tier=R.choice(["prod", "prod", "staging"]), image=f"registry.internal/{t}/{name}" + (f":{tag}" if tag else ""),
                     replicas=R.choice([1, 2, 2, 3, 4]), memory_mb=R.choice([256, 512, 1024, 2048, 4096, 8192]), ports=[8000 + R.randint(0, 99)],
                     env=env)
            if R.random() < 0.8:
                d["healthcheck"] = {"path": "/healthz", "interval_s": R.choice([5, 10, 30])}
            if R.random() < 0.9:
                d["owner"] = f"{t}-oncall@example.com"
            svcs[f"services/{t}/{name}.json"] = d
    return svcs


def tag_of(img):
    last = img.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else ""


def violations(d, rules):
    out = []
    if "unpinned_image" in rules and tag_of(d["image"]) in ("", "latest"):
        out.append("unpinned_image")
    if "single_replica" in rules and d["tier"] == "prod" and d["replicas"] == 1:
        out.append("single_replica")
    if "oversized_memory" in rules and d["memory_mb"] > 4096:
        out.append("oversized_memory")
    if "plaintext_secret" in rules and any(any(w in k for w in ("PASSWORD", "SECRET", "TOKEN")) and not str(v).startswith("${") for k, v in d["env"].items()):
        out.append("plaintext_secret")
    if "no_healthcheck" in rules and "healthcheck" not in d:
        out.append("no_healthcheck")
    if "missing_owner" in rules and not d.get("owner"):
        out.append("missing_owner")
    return out


def audit(svcs, rules):
    by, rows = {r: 0 for r in rules}, []
    for path, d in svcs.items():
        for v in violations(d, rules):
            by[v] += 1
            rows.append((d["team"], d["name"], v))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return {"services": len(svcs), "by_rule": by}, rows


def digest(rows):
    return hashlib.sha256("\n".join(f"{a},{b},{c}" for a, b, c in rows).encode()).hexdigest()


AUDIT_PY = '''"""Config audit: python3 scripts/audit.py [--root DIR] -> JSON {services, by_rule} on stdout."""
import argparse, glob, json, os

RULES = %r


def tag_of(img):
    last = img.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else ""


def violations(d):
    out = []
    if tag_of(d["image"]) in ("", "latest"):
        out.append("unpinned_image")
    if d.get("tier") == "prod" and d.get("replicas") == 1:
        out.append("single_replica")
    if d.get("memory_mb", 0) > 4096:
        out.append("oversized_memory")
    if any(any(w in k for w in ("PASSWORD", "SECRET", "TOKEN")) and not str(v).startswith("${") for k, v in d.get("env", {}).items()):
        out.append("plaintext_secret")
    if "healthcheck" not in d:
        out.append("no_healthcheck")
#OWNER#    return out


def audit(root):
    by, n = {r: 0 for r in RULES}, 0
    for p in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
        d = json.load(open(p, encoding="utf-8"))
        n += 1
        for v in violations(d):
            by[v] += 1
    return {"services": n, "by_rule": by}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="services")
    print(json.dumps(audit(ap.parse_args().root), indent=2))
'''
OWNER = '    if not d.get("owner"):\n        out.append("missing_owner")\n    return out\n'
AUDIT_V1 = (AUDIT_PY % RULES5).replace("#OWNER#    return out\n", "    return out\n")
AUDIT_V2 = (AUDIT_PY % (RULES5 + ["missing_owner"])).replace("#OWNER#    return out\n", OWNER)


def build():
    s = Scn("svc-config-audit", "mixed", "mixed", "python",
            "320 per-service JSON configs across 8 teams: audit rules, exact violation counts, CSV/markdown reports, an audit CLI that generalises, a new rule, a bulk fix, rule docs.",
            ["config-audit pattern from ~/dev/amplifier-agent .amplifier/evaluation tasks; configs are new and generated"],
            long_gaps=[5, 10])
    svcs = make(7404, TEAMS, 40)
    for p, d in svcs.items():
        s.file(p, json.dumps(d, indent=2) + "\n")
    s.file("README.md", "# service-configs\n\nOne JSON file per service under `services/<team>/`. Fields: name, team, tier (prod|staging), image (registry/name[:tag]), replicas, memory_mb, ports, env, optional healthcheck and owner.\n")
    s.file("scripts/.keep", "")
    s.file("POLICY.md", "# Policy\n\nProduction services run at least 2 replicas, pin their images and read secrets from the vault.\n")
    s.protected = ["POLICY.md"]
    A5, rows5 = audit(svcs, RULES5)
    A6, rows6 = audit(svcs, RULES5 + ["missing_owner"])
    teams_ct = {t: sum(1 for r in rows5 if r[0] == t) for t in TEAMS}
    mx, mn = max(teams_ct, key=lambda k: teams_ct[k]), min(teams_ct, key=lambda k: teams_ct[k])
    assert sorted(teams_ct.values())[-1] > sorted(teams_ct.values())[-2] and sorted(teams_ct.values())[0] < sorted(teams_ct.values())[1], teams_ct
    unp = A5["by_rule"]["unpinned_image"]
    secrets = len({(r[1]) for r in rows5 if r[2] == "plaintext_secret"})
    nfiles = len(svcs)

    s.turn("How many service config files are under services/, and how many distinct teams (sub-folders) do they belong to? Do not change any files.",
           [facts(all=[numrx(nfiles), numrx(len(TEAMS))])], msg=f"ANSWER: {nfiles} configs across {len(TEAMS)} teams", wrong_msg=f"ANSWER: {nfiles - 4} configs across {len(TEAMS)} teams", bump=True)
    s.turn("How many services use an unpinned image, meaning the image reference has no tag at all or the tag `latest`? Do not change any files.",
           [facts(all=[numrx(unp)])], msg=f"ANSWER: {unp}", wrong_msg=f"ANSWER: {unp + 3}", bump=True)
    s.turn("How many services have a plaintext secret: an env variable whose name contains PASSWORD, SECRET or TOKEN and whose value is a literal rather than a `${...}` reference? Count services, not variables. Do not change any files.",
           [facts(all=[numrx(secrets)])], msg=f"ANSWER: {secrets} services", wrong_msg=f"ANSWER: {secrets - 2} services", bump=True)
    s.func("t4", f"chk_json('out/audit.json', {A5!r}, tol=0)")
    s.turn("Create out/audit.json: {\"services\": <file count>, \"by_rule\": {<rule>: <number of services violating it>}} for the rules unpinned_image, single_replica (tier prod with replicas 1), oversized_memory (memory_mb above 4096), plaintext_secret and no_healthcheck (no healthcheck key).",
           [s.g("t4")], files={"out/audit.json": json.dumps(A5, indent=2) + "\n"},
           wrong_files={"out/audit.json": json.dumps({**A5, "by_rule": {**A5["by_rule"], "no_healthcheck": A5["by_rule"]["no_healthcheck"] + 1}}) + "\n"}, bump=True)
    s.func("t5", f"""
        import csv, hashlib
        need((W / 'out/violations.csv').exists(), 'missing out/violations.csv')
        rd = list(csv.reader(open('out/violations.csv', encoding='utf-8', newline='')))
        need(rd and rd[0] == ['team', 'service', 'rule'], 'header ' + str(rd[:1]))
        body = rd[1:]
        need(len(body) == {len(rows5)}, f'{{len(body)}} rows, want {len(rows5)}')
        need(hashlib.sha256('\\n'.join(','.join(r) for r in body).encode()).hexdigest() == {digest(rows5)!r}, 'rows or ordering differ')
        """)
    vcsv = csv_text(["team", "service", "rule"], rows5)
    s.turn("Write out/violations.csv with the header team,service,rule and one row per (service, violated rule), sorted by team, then service name, then rule name (plain string order).",
           [s.g("t5")], files={"out/violations.csv": vcsv}, wrong_files={"out/violations.csv": csv_text(["team", "service", "rule"], rows5[::-1])}, bump=False)
    s.turn("Which team has the most violations in out/violations.csv, and which has the fewest? Give both counts. Do not change any files.",
           [facts(all=[mx, numrx(teams_ct[mx]), mn, numrx(teams_ct[mn])])], msg=f"ANSWER: most {mx} ({teams_ct[mx]}), fewest {mn} ({teams_ct[mn]})",
           wrong_msg=f"ANSWER: most {mx} ({teams_ct[mx] + 2}), fewest {mn} ({teams_ct[mn]})", bump=True)
    s.func("t7", f"chk_table('report.md', 'by team', {teams_ct!r})")
    rep = "# Config audit\n\n## Summary\n\n" + f"{nfiles} services audited, {len(rows5)} violations.\n\n## Violations by team\n\n| team | violations |\n|---|---|\n" + "".join(f"| {t} | {v} |\n" for t, v in teams_ct.items()) + "\n## Rules\n\n" + ", ".join(RULES5) + "\n"
    s.turn("Write report.md with level-2 sections Summary, Violations by team and Rules. Violations by team is a table: team in the first column, number of violations (rows in out/violations.csv) in the second.",
           [sections("report.md", "Summary", "Violations by team", "Rules"), s.g("t7")], files={"report.md": rep},
           wrong_files={"report.md": rep.replace(f"| {mx} | {teams_ct[mx]} |", f"| {mx} | {teams_ct[mx] - 1} |")}, bump=True)
    alt = make(99, ["alpha", "beta", "gamma"], 5)
    aA5, _ = audit(alt, RULES5)
    aA6, _ = audit(alt, RULES5 + ["missing_owner"])
    altfiles = {f"_alt/{p}": json.dumps(d, indent=2) + "\n" for p, d in alt.items()}
    s.func("t8", f"""
        for rel, text in {altfiles!r}.items():
            p = W / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        need((W / 'scripts/audit.py').exists(), 'missing scripts/audit.py')
        chk_cmd_json('python3 scripts/audit.py --root _alt/services', {aA5!r}, tol=0)
        """)
    s.turn("Add scripts/audit.py: `python3 scripts/audit.py [--root DIR]` (default services) walks DIR recursively for *.json service configs and prints the same {services, by_rule} JSON as out/audit.json on stdout.",
           [s.g("t8")], files={"scripts/audit.py": AUDIT_V1}, wrong_files={"scripts/audit.py": AUDIT_V1.replace("> 4096", ">= 4096")}, bump=False)
    s.func("t9", f"""
        for rel, text in {altfiles!r}.items():
            p = W / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        chk_json('out/audit.json', {A6!r}, tol=0)
        chk_cmd_json('python3 scripts/audit.py --root _alt/services', {aA6!r}, tol=0)
        """)
    s.turn("Add a sixth rule, missing_owner: the config has no `owner` key or it is empty. Update scripts/audit.py and regenerate out/audit.json so by_rule includes it.",
           [s.g("t9")], files={"scripts/audit.py": AUDIT_V2, "out/audit.json": json.dumps(A6, indent=2) + "\n"},
           wrong_files={"scripts/audit.py": AUDIT_V2, "out/audit.json": json.dumps(A5) + "\n"}, bump=False)
    # bulk pin for team X
    X = max(TEAMS, key=lambda t: sum(1 for p, d in svcs.items() if d["team"] == t and tag_of(d["image"]) in ("", "latest")))
    after, new_files = {}, {}
    for p, d in svcs.items():
        if d["team"] == X:
            d2 = json.loads(json.dumps(d))
            if tag_of(d["image"]) in ("", "latest"):
                d2["image"] = d["image"].split(":")[0] + ":1.0.0"
            after[p] = d2["image"]
            new_files[p] = json.dumps(d2, indent=2) + "\n"
    svcs2 = {p: (json.loads(new_files[p]) if p in new_files else d) for p, d in svcs.items()}
    A6b, _ = audit(svcs2, RULES5 + ["missing_owner"])
    others_unp = sum(1 for p, d in svcs.items() if d["team"] != X and tag_of(d["image"]) in ("", "latest"))
    s.func("t11", f"""
        import glob
        exp = {after!r}
        for rel, img in exp.items():
            d = load_json(rel)
            need(d.get('image') == img, f'{{rel}}: image {{d.get("image")}} != {{img}}')
        need(len(exp) == {len(after)}, 'x')
        cnt = 0
        for p in glob.glob('services/**/*.json', recursive=True):
            if p.replace(os.sep, '/') in exp:
                continue
            tag = load_json(p)['image'].rsplit('/', 1)[-1]
            cnt += 1 if (':' not in tag or tag.endswith(':latest')) else 0
        need(cnt == {others_unp}, f'other teams touched: {{cnt}} unpinned left, want {others_unp}')
        """)
    pin_wrong = dict(new_files)
    for p in new_files:
        if tag_of(svcs[p]["image"]) in ("", "latest"):
            pin_wrong[p] = json.dumps(svcs[p], indent=2) + "\n"
            break
    s.turn(f"Team {X} must stop shipping unpinned images. In every config under services/{X}/ whose image has no tag or the tag `latest`, set the tag to `1.0.0` (keep the image name). Do not touch other teams or other fields.",
           [s.g("t11")], files=new_files, wrong_files=pin_wrong, bump=False)
    s.func("t12", f"chk_json('out/audit.json', {A6b!r}, tol=0)")
    s.turn("Regenerate out/audit.json with all six rules after the pinning change.",
           [s.g("t12")], files={"out/audit.json": json.dumps(A6b, indent=2) + "\n"}, wrong_files={"out/audit.json": json.dumps(A6) + "\n"}, bump=True)
    top6 = max(A6b["by_rule"], key=lambda k: A6b["by_rule"][k])
    assert list(A6b["by_rule"].values()).count(A6b["by_rule"][top6]) == 1
    s.turn("After the pinning change, which rule is violated by the most services, and by how many? Do not change any files.",
           [facts(all=[r"\b" + top6 + r"\b", numrx(A6b["by_rule"][top6])])], msg=f"ANSWER: {top6}, {A6b['by_rule'][top6]} services", wrong_msg=f"ANSWER: {top6}, {A6b['by_rule'][top6] + 5} services", bump=True)
    _, rows6b = audit(svcs2, RULES5 + ["missing_owner"])
    s.func("t13", f"""
        import csv, hashlib
        rd = list(csv.reader(open('out/violations.csv', encoding='utf-8', newline='')))
        need(rd and rd[0] == ['team', 'service', 'rule'], 'header')
        body = rd[1:]
        need(len(body) == {len(rows6b)}, f'{{len(body)}} rows, want {len(rows6b)}')
        need(hashlib.sha256('\\n'.join(','.join(r) for r in body).encode()).hexdigest() == {digest(rows6b)!r}, 'rows or ordering differ')
        """)
    s.turn("Regenerate out/violations.csv (same header and sorting as before) for all six rules on the current configs.",
           [s.g("t13")], files={"out/violations.csv": csv_text(["team", "service", "rule"], rows6b)}, wrong_files={"out/violations.csv": vcsv}, bump=False)
    s.turn("Write docs/audit-rules.md with a level-3 heading for each of the six rule ids (unpinned_image, single_replica, oversized_memory, plaintext_secret, no_healthcheck, missing_owner). Under each, one sentence saying what it flags; mention the 4096 MB limit under oversized_memory and the PASSWORD, SECRET, TOKEN name patterns under plaintext_secret.",
           [sections("docs/audit-rules.md", *[f"^#{{3}}\\s*{r}" for r in RULES5 + ["missing_owner"]]), rx("docs/audit-rules.md", r"4096"), rx("docs/audit-rules.md", r"PASSWORD"), rx("docs/audit-rules.md", r"SECRET"), rx("docs/audit-rules.md", r"TOKEN")],
           files={"docs/audit-rules.md": "# Audit rules\n\n" + "".join(f"### {r}\n\n{ {'oversized_memory': 'Flags memory_mb above 4096 MB.', 'plaintext_secret': 'Flags env names containing PASSWORD, SECRET or TOKEN with a literal value.'}.get(r, 'Flags ' + r.replace('_', ' ') + '.') }\n\n" for r in RULES5 + ["missing_owner"])},
           wrong_files={"docs/audit-rules.md": "# Audit rules\n\n### unpinned_image\n\nFlags latest.\n"})
    s.turn("Add a '## Auditing' section to README.md that tells how to run `python3 scripts/audit.py`, mentions --root, and links to docs/audit-rules.md.",
           [sections("README.md", "Auditing"), rx("README.md", r"scripts/audit\.py"), rx("README.md", r"--root"), rx("README.md", r"docs/audit-rules\.md")],
           files={"README.md": s.files["README.md"] + "\n## Auditing\n\nRun `python3 scripts/audit.py` (or `--root DIR`) to print the violation counts; the rules are described in docs/audit-rules.md.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Auditing\n\nRun the script.\n"})
    return s
