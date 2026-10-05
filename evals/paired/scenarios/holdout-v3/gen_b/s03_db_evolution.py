import json, random, re
from lib import Scn, dedent, exists, facts, numrx, rx, sections

TABLES = ["users", "orders", "items", "invoices", "payments", "audit", "sessions", "tags"]


def make(seed, n, tables, first_id=1):
    R = random.Random(seed)
    ids = [f"{first_id + i:03d}" for i in range(n)]
    rank = ids[:]
    R.shuffle(rank)                      # apply rank: dependencies only point to lower rank
    migs = {}
    created = set()
    for pos, mid in enumerate(rank):
        deps = sorted(R.sample(rank[:pos], min(pos, R.choice([0, 1, 1, 2])))) if pos else []
        touches = sorted(R.sample(tables, R.choice([1, 1, 2])))
        creates = [t for t in touches if t not in created][:1] if R.random() < 0.5 else []
        for t in creates:
            created.add(t)
        destructive = (not creates) and R.random() < 0.3
        down = None if destructive or (R.random() < 0.12 and not creates) else (f"DROP TABLE {creates[0]};" if creates else f"ALTER TABLE {touches[0]} DROP COLUMN c{mid};")
        migs[mid] = dict(id=mid, name=R.choice(["add", "extend", "rework", "backfill", "split", "tidy"]) + "_" + touches[0], deps=deps,
                         touches=touches, creates=creates, destructive=destructive, down=down)
    return migs


def text_of(m):
    lines = [f"-- migration: {m['id']}_{m['name']}", f"-- depends: {', '.join(m['deps']) if m['deps'] else 'none'}", f"-- touches: {', '.join(m['touches'])}",
             f"-- destructive: {'yes' if m['destructive'] else 'no'}"]
    if m["creates"]:
        lines.append(f"-- creates: {', '.join(m['creates'])}")
    if m["down"]:
        lines.append(f"-- down: {m['down']}")
    body = f"CREATE TABLE {m['creates'][0]} (id INTEGER PRIMARY KEY);" if m["creates"] else (f"ALTER TABLE {m['touches'][0]} DROP COLUMN legacy_{m['id']};" if m["destructive"] else f"ALTER TABLE {m['touches'][0]} ADD COLUMN c{m['id']} TEXT;")
    return "\n".join(lines) + "\n\n" + body + "\n"


def plan(migs):
    done, order, rest = set(), [], dict(migs)
    while rest:
        ready = sorted(i for i, m in rest.items() if all(d in done for d in m["deps"]))
        i = ready[0]
        order.append(i)
        done.add(i)
        del rest[i]
    anc = {}
    def ancestors(i):
        if i not in anc:
            s = set()
            for d in migs[i]["deps"]:
                s |= {d} | ancestors(d)
            anc[i] = s
        return anc[i]
    conflicts = []
    ids = sorted(migs)
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]
            if set(migs[a]["touches"]) & set(migs[b]["touches"]) and a not in ancestors(b) and b not in ancestors(a):
                conflicts.append([a, b])
    tables = {}
    for i in order:
        for t in migs[i]["touches"]:
            tables.setdefault(t, []).append(i)
    return dict(order=order, destructive=sorted(i for i in migs if migs[i]["destructive"]), tables=tables, conflicts=conflicts)


def rollback_lines(migs, order):
    return [migs[i]["down"] if migs[i]["down"] else f"-- IRREVERSIBLE: {i}" for i in reversed(order)]


PLAN_PY = '''"""Migration planner: python3 scripts/plan.py [--dir DIR] -> JSON {order, destructive, tables, conflicts} on stdout."""
import argparse, glob, json, os, re


def load(d):
    migs = {}
    for p in sorted(glob.glob(os.path.join(d, "*.sql"))):
        h = {}
        for ln in open(p, encoding="utf-8"):
            m = re.match(r"--\\s*(\\w+):\\s*(.*)$", ln.strip())
            if m:
                h[m.group(1)] = m.group(2).strip()
        mid = os.path.basename(p).split("_")[0]
        lst = lambda k: [x.strip() for x in h.get(k, "").split(",") if x.strip() and x.strip() != "none"]
        migs[mid] = {"deps": lst("depends"), "touches": lst("touches"), "destructive": h.get("destructive") == "yes"}
    return migs


def plan(migs):
    done, order, rest = set(), [], dict(migs)
    while rest:
        i = sorted(k for k, m in rest.items() if all(d in done for d in m["deps"]))[0]
        order.append(i)
        done.add(i)
        del rest[i]
    memo = {}
    def anc(i):
        if i not in memo:
            memo[i] = set()
            for d in migs[i]["deps"]:
                memo[i] |= {d} | anc(d)
        return memo[i]
    ids = sorted(migs)
    conflicts = [[a, b] for x, a in enumerate(ids) for b in ids[x + 1:]
                 if set(migs[a]["touches"]) & set(migs[b]["touches"]) and a not in anc(b) and b not in anc(a)]
    tables = {}
    for i in order:
        for t in migs[i]["touches"]:
            tables.setdefault(t, []).append(i)
    return {"order": order, "destructive": sorted(i for i in migs if migs[i]["destructive"]), "tables": tables, "conflicts": conflicts}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="migrations")
    print(json.dumps(plan(load(ap.parse_args().dir)), indent=2))
'''


def seq_rx(ids):
    return r"(?<!\d)" + r"(?:\D|\d{4,})*?(?<!\d)".join(ids) + r"(?!\d)"


def build():
    s = Scn("db-evolution", "mixed", "mixed", "sql",
            "Schema migration set with dependency headers: ordering, destructive/conflict analysis, rollout and rollback artifacts, a planner CLI that generalises, extending the set.",
            ["~/dev/amplifier-agent .amplifier/evaluation migration-style tasks (pattern only); migrations are new and generated"],
            protected=[])
    migs = make(7342, 13, TABLES)
    for i, m in migs.items():
        s.file(f"migrations/{i}_{m['name']}.sql", text_of(m))
    s.protected = [f"migrations/{i}_{migs[i]['name']}.sql" for i in sorted(migs)]
    s.file("README.md", "# shop-db\n\nEach file in `migrations/` starts with a header: `depends` (ids that must run first, or none), `touches` (tables), `destructive` (yes/no), optional `creates` and `down`.\nMigrations without a `down` line cannot be reversed.\n")
    P = plan(migs)
    assert 3 <= len(P["conflicts"]) <= 40 and P["order"] != sorted(migs), (len(P["conflicts"]), P["order"])
    nd = {i: len(m["deps"]) for i, m in migs.items()}
    mx = max(nd.values())
    assert list(nd.values()).count(mx) == 1
    most_dep = [i for i in nd if nd[i] == mx][0]
    with_deps = sum(1 for v in nd.values() if v)
    tc = {t: len(v) for t, v in P["tables"].items()}
    top_t = max(tc, key=lambda k: tc[k])
    assert list(tc.values()).count(tc[top_t]) == 1

    s.turn("Read the headers in migrations/. How many migrations declare at least one dependency, and which migration id declares the most dependencies? Do not change any files.",
           [facts(all=[numrx(with_deps), r"(?<!\d)" + most_dep + r"(?!\d)"])], msg=f"ANSWER: {with_deps} migrations have dependencies; {most_dep} has the most ({mx})",
           wrong_msg=f"ANSWER: {with_deps + 1} migrations; {sorted(migs)[0] if sorted(migs)[0] != most_dep else sorted(migs)[1]} has the most", bump=False)
    s.turn("In which order must the migrations be applied? Every migration runs only after all of its dependencies; whenever several are ready, run the one with the smallest id first. List the ids in order. Do not change any files.",
           [facts(all=[seq_rx(P["order"])])], msg="ANSWER: " + ", ".join(P["order"]), wrong_msg="ANSWER: " + ", ".join(sorted(migs)), bump=False)
    s.func("t3", f"chk_json('out/plan.json', {{'order': {P['order']!r}, 'destructive': {P['destructive']!r}}})")
    s.turn("Create out/plan.json with `order` (the apply order from the previous answer) and `destructive` (ids of migrations whose header says destructive: yes, sorted ascending).",
           [s.g("t3")], files={"out/plan.json": json.dumps({"order": P["order"], "destructive": P["destructive"]}, indent=2) + "\n"},
           wrong_files={"out/plan.json": json.dumps({"order": P["order"][::-1], "destructive": P["destructive"]}) + "\n"})
    s.turn("Which table is touched by the most migrations (per the `touches` headers), and by how many? Do not change any files.",
           [facts(all=[r"\b" + top_t + r"\b", numrx(tc[top_t])])], msg=f"ANSWER: {top_t}, touched by {tc[top_t]} migrations",
           wrong_msg=f"ANSWER: {top_t}, touched by {tc[top_t] + 1} migrations", bump=False)
    full = {"order": P["order"], "destructive": P["destructive"], "tables": P["tables"], "conflicts": P["conflicts"]}
    s.func("t5", f"chk_json('out/plan.json', {full!r}, tol=0)")
    s.turn("Extend out/plan.json with `tables` (an object: table name -> migration ids touching it, in apply order) and `conflicts` (every pair [a, b] with a < b of migrations that touch a common table where neither is a direct or transitive dependency of the other; pairs sorted ascending).",
           [s.g("t5")], files={"out/plan.json": json.dumps(full, indent=2) + "\n"},
           wrong_files={"out/plan.json": json.dumps({**full, "conflicts": P["conflicts"][1:]}) + "\n"})
    rows = "".join(f"| {k} | {i} | {'yes' if migs[i]['destructive'] else 'no'} |\n" for k, i in enumerate(P["order"], 1))
    s.func("t6", f"""
        rows = md_rows('docs/rollout.md', 'order')
        got = [(r[1], r[2].lower()) for r in rows[1:] if len(r) >= 3 and r[0].strip().isdigit()]
        need(got == {[(i, 'yes' if migs[i]['destructive'] else 'no') for i in P['order']]!r}, 'rollout table rows: ' + str(got[:4]))
        need([int(r[0]) for r in rows[1:] if r[0].strip().isdigit()] == list(range(1, {len(migs)} + 1)), 'step numbers')
        """)
    doc = "# Rollout\n\n## Phases\n\nApply in the order below; stop before any destructive step and take a backup.\n\n## Apply order\n\n| step | migration | destructive |\n|---|---|---|\n" + "".join(f"| {k} | {i} | {'yes' if migs[i]['destructive'] else 'no'} |\n" for k, i in enumerate(P["order"], 1)) + "\n## Risks\n\n" + f"{len(P['destructive'])} destructive migrations; {len(P['conflicts'])} potentially conflicting pairs.\n"
    s.turn("Write docs/rollout.md with level-2 sections Phases, Apply order and Risks. Apply order is a table with columns step (1..N), migration (id) and destructive (yes/no), one row per migration in the correct order.",
           [sections("docs/rollout.md", "Phases", "Apply order", "Risks"), s.g("t6")], files={"docs/rollout.md": doc},
           wrong_files={"docs/rollout.md": doc.replace(f"| 1 | {P['order'][0]} |", f"| 1 | {P['order'][1]} |")})
    rb = rollback_lines(migs, P["order"])
    irr = [i for i in migs if not migs[i]["down"]]
    s.func("t7", f"""
        got = [ln.strip() for ln in read('out/rollback.sql').splitlines() if ln.strip()]
        need(got == {rb!r}, 'rollback lines differ: ' + str(got[:4]))
        """)
    s.turn("Write out/rollback.sql: one line per migration, in the reverse of the apply order. The line is the migration's `-- down:` statement exactly as written after the header key, or `-- IRREVERSIBLE: <id>` when it has no down line.",
           [s.g("t7")], files={"out/rollback.sql": "\n".join(rb) + "\n"}, wrong_files={"out/rollback.sql": "\n".join(rb[::-1]) + "\n"})
    amigs = make(88, 7, TABLES[:5], first_id=21)
    aplan = plan(amigs)
    s.func("t8", f"""
        for rel, text in {({f'_alt/migrations/{i}_{m["name"]}.sql': text_of(m) for i, m in amigs.items()})!r}.items():
            p = W / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        need((W / 'scripts/plan.py').exists(), 'missing scripts/plan.py')
        chk_cmd_json('python3 scripts/plan.py --dir _alt/migrations', {aplan!r}, tol=0)
        chk_cmd_json('python3 scripts/plan.py', {full!r}, tol=0)
        """)
    s.turn("Add scripts/plan.py: it reads the migration headers from a directory (--dir, default migrations) and prints on stdout exactly the JSON that out/plan.json holds (order, destructive, tables, conflicts).",
           [s.g("t8")], files={"scripts/plan.py": PLAN_PY}, wrong_files={"scripts/plan.py": PLAN_PY.replace("sorted(k for k, m in rest.items()", "sorted((k for k, m in rest.items()").replace("[0]\n        order", ", reverse=True)[0]\n        order")})
    creator = next(i for i, m in migs.items() if "orders" in m["creates"])
    new = dict(id="014", name="orders_index", deps=[creator], touches=["orders"], creates=[], destructive=False, down="DROP INDEX idx_orders_created;")
    newtext = "-- migration: 014_orders_index\n-- depends: " + creator + "\n-- touches: orders\n-- destructive: no\n-- down: DROP INDEX idx_orders_created;\n\nCREATE INDEX idx_orders_created ON orders (created_at);\n"
    s.turn("Add migrations/014_orders_index.sql in the same header format: depends on the migration whose header says `-- creates: orders`, touches orders, destructive no, down `DROP INDEX idx_orders_created;`, body `CREATE INDEX idx_orders_created ON orders (created_at);`.",
           [exists("migrations/014_orders_index.sql"), rx("migrations/014_orders_index.sql", r"^-- depends: " + creator + r"\s*$"), rx("migrations/014_orders_index.sql", r"^-- touches: orders\s*$"),
            rx("migrations/014_orders_index.sql", r"^-- destructive: no\s*$"), rx("migrations/014_orders_index.sql", r"^-- down: DROP INDEX idx_orders_created;\s*$"),
            rx("migrations/014_orders_index.sql", r"CREATE INDEX idx_orders_created ON orders \(created_at\);")],
           files={"migrations/014_orders_index.sql": newtext}, wrong_files={"migrations/014_orders_index.sql": newtext.replace(creator, sorted(migs)[0] if sorted(migs)[0] != creator else sorted(migs)[1])})
    allm = {**migs, "014": new}
    P2 = plan(allm)
    full2 = {"order": P2["order"], "destructive": P2["destructive"], "tables": P2["tables"], "conflicts": P2["conflicts"]}
    s.func("t10", f"chk_json('out/plan.json', {full2!r}, tol=0)")
    s.turn("Regenerate out/plan.json so it includes migration 014 (use scripts/plan.py).",
           [s.g("t10")], files={"out/plan.json": json.dumps(full2, indent=2) + "\n"}, wrong_files={"out/plan.json": json.dumps(full) + "\n"})
    rb2 = rollback_lines(allm, P2["order"])
    s.func("t11", f"""
        got = [ln.strip() for ln in read('out/rollback.sql').splitlines() if ln.strip()]
        need(got == {rb2!r}, 'rollback lines differ: ' + str(got[:4]))
        """)
    s.turn("Regenerate out/rollback.sql for the new apply order (it now includes migration 014; same one-line-per-migration rule, reverse apply order).",
           [s.g("t11")], files={"out/rollback.sql": "\n".join(rb2) + "\n"}, wrong_files={"out/rollback.sql": "\n".join(rb) + "\n"})
    pos = {i: k for k, i in enumerate(P2["order"], 1)}
    first_conf = P2["conflicts"][0]
    s.turn("How many conflicting pairs does the updated plan list, and what is the first pair? Do not change any files.",
           [facts(all=[numrx(len(P2["conflicts"])), r"(?<!\d)" + first_conf[0] + r"(?!\d)", r"(?<!\d)" + first_conf[1] + r"(?!\d)"])], msg=f"ANSWER: {len(P2['conflicts'])} pairs; first is {first_conf[0]} and {first_conf[1]}", wrong_msg=f"ANSWER: {len(P2['conflicts']) + 2} pairs", bump=True)
    s.turn("Add a '## Planning' section to README.md explaining that `python3 scripts/plan.py` prints the apply order, how --dir changes the folder, and that conflicts means two migrations touching the same table with no dependency path between them.",
           [sections("README.md", "Planning"), rx("README.md", r"scripts/plan\.py"), rx("README.md", r"--dir"), rx("README.md", r"(?i)conflict"), rx("README.md", r"(?i)no dependency path|neither")],
           files={"README.md": s.files["README.md"] + "\n## Planning\n\nRun `python3 scripts/plan.py` (or `--dir DIR`) to print the apply order as JSON.\nA conflict is a pair of migrations touching the same table where neither depends on the other, so there is no dependency path between them.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Planning\n\nRun the planner.\n"})
    return s
