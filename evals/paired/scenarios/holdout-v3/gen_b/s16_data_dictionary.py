import csv, io, random, statistics
from lib import Scn, csv_text, exists, facts, numrx, rx, sections

COLS = ["order_id", "customer_id", "country", "channel", "order_date", "total", "discount_pct", "shipped", "notes"]


def make(seed, n):
    R = random.Random(seed)
    rows = []
    for i in range(n):
        d = f"2025-{R.randint(1, 3):02d}-{R.randint(1, 28):02d}"
        rows.append([f"O{5000 + i}", f"C{R.randint(1, 60):03d}", R.choice(["DE", "FR", "US", "UK", "ES", ""]) if R.random() > 0.05 else "",
                     R.choice(["web", "app", "store"]), d, f"{R.uniform(5, 400):.2f}", R.choice(["0", "5", "10", "15", ""]), R.choice(["true", "false"]), R.choice(["", "", "", "gift", "rush", "call first"])])
    return rows


def infer(vals):
    nn = [v for v in vals if v != ""]
    def isint(v):
        try:
            int(v)
            return "." not in v
        except ValueError:
            return False
    def isnum(v):
        try:
            float(v)
            return True
        except ValueError:
            return False
    if nn and all(v in ("true", "false") for v in nn):
        return "boolean"
    if nn and all(isint(v) for v in nn):
        return "integer"
    if nn and all(isnum(v) for v in nn):
        return "decimal"
    if nn and all(len(v) == 10 and v[4] == "-" and v[7] == "-" for v in nn):
        return "date"
    return "text"


def profile(rows):
    out = {}
    for j, c in enumerate(COLS):
        vals = [r[j] for r in rows]
        nn = [v for v in vals if v != ""]
        ty = infer(vals)
        d = dict(type=ty, nulls=len(vals) - len(nn), distinct=len(set(nn)))
        if ty in ("integer", "decimal"):
            nums = [float(v) for v in nn]
            d["min"], d["max"] = (str(int(min(nums))), str(int(max(nums)))) if ty == "integer" else (f"{min(nums):.2f}", f"{max(nums):.2f}")
        elif ty == "date":
            d["min"], d["max"] = min(nn), max(nn)
        else:
            d["min"] = d["max"] = "-"
        out[c] = d
    return out


PROFILE = '''"""Column profile: python3 scripts/profile.py [--csv FILE] -> JSON {column: {type, nulls, distinct, min, max}} on stdout."""
import argparse, csv, json


def infer(nn):
    def ok(f, v):
        try:
            f(v)
            return True
        except ValueError:
            return False
    if nn and all(v in ("true", "false") for v in nn):
        return "boolean"
    if nn and all(ok(int, v) and "." not in v for v in nn):
        return "integer"
    if nn and all(ok(float, v) for v in nn):
        return "decimal"
    if nn and all(len(v) == 10 and v[4] == "-" and v[7] == "-" for v in nn):
        return "date"
    return "text"


def profile(path):
    rd = list(csv.reader(open(path, encoding="utf-8", newline="")))
    head, rows = rd[0], rd[1:]
    out = {}
    for j, c in enumerate(head):
        nn = [r[j] for r in rows if r[j] != ""]
        ty = infer(nn)
        d = {"type": ty, "nulls": len(rows) - len(nn), "distinct": len(set(nn)), "min": "-", "max": "-"}
        if ty == "integer":
            d["min"], d["max"] = str(min(int(v) for v in nn)), str(max(int(v) for v in nn))
        elif ty == "decimal":
            d["min"], d["max"] = f"{min(float(v) for v in nn):.2f}", f"{max(float(v) for v in nn):.2f}"
        elif ty == "date":
            d["min"], d["max"] = min(nn), max(nn)
        out[c] = d
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/orders.csv")
    print(json.dumps(profile(ap.parse_args().csv), indent=2))
'''


def dd_table(prof):
    return "| column | type | nulls | distinct | min | max |\n|---|---|---|---|---|---|\n" + "".join(f"| `{c}` | {d['type']} | {d['nulls']} | {d['distinct']} | {d['min']} | {d['max']} |\n" for c, d in prof.items())


def build():
    s = Scn("data-dictionary", "mixed", "docs", "markdown",
            "Write a data dictionary for an orders CSV: exact row/column facts, per-column type/null/distinct/min/max table, categorical value lists, a profiling CLI that generalises, and a revised dictionary after a data refresh.",
            ["new self-authored dataset; data-documentation theme (cf. amplifier-agent csv/data tasks)"],
            protected=["data/orders.csv", "data/orders_refresh.csv"])
    rows = make(8114, 180)
    refresh = rows + make(8115, 60)
    s.file("data/orders.csv", csv_text(COLS, rows))
    s.file("data/orders_refresh.csv", csv_text(COLS, refresh))
    s.file("README.md", "# orders-data\n\n`data/orders.csv` is the Q1 order extract; `data/orders_refresh.csv` is the same extract after a late refresh. Empty cells mean null.\n")
    P = profile(rows)
    P2 = profile(refresh)
    cat = {c: sorted({r[j] for r in rows if r[j] != ""}) for j, c in enumerate(COLS) if c in ("country", "channel", "discount_pct", "notes")}
    totals = [float(r[5]) for r in rows]
    s.turn("How many data rows (excluding the header) and how many columns does data/orders.csv have? Do not change any files.",
           [facts(all=[numrx(len(rows)), numrx(len(COLS))])], msg=f"ANSWER: {len(rows)} rows, {len(COLS)} columns", wrong_msg=f"ANSWER: {len(rows) + 1} rows, {len(COLS)} columns", bump=True)
    s.func("t2", f"""
        rows = md_rows('docs/data-dictionary.md', 'columns')
        need(rows and [c.lower() for c in rows[0][:3]] == ['column', 'type', 'nulls'], 'header: ' + str(rows[:1]))
        got = {{r[0].strip('` '): [r[1], int(num(r[2]))] for r in rows[1:] if len(r) >= 3}}
        want = {({c: [d['type'], d['nulls']] for c, d in P.items()})!r}
        need(got == want, 'type/nulls differ: ' + str({{k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}}))
        need(list(got) == {COLS!r}, 'column order')
        """)
    d2 = "# Data dictionary\n\n## Columns\n\n" + "| column | type | nulls |\n|---|---|---|\n" + "".join(f"| `{c}` | {d['type']} | {d['nulls']} |\n" for c, d in P.items())
    s.turn("Create docs/data-dictionary.md with a `## Columns` section holding a table (columns column, type, nulls): one row per CSV column in file order. type is the narrowest of boolean (only true/false), integer, decimal, date (YYYY-MM-DD) or text that fits every non-empty value; nulls is the number of empty cells.",
           [s.g("t2")], files={"docs/data-dictionary.md": d2}, wrong_files={"docs/data-dictionary.md": d2.replace("| `discount_pct` | integer |", "| `discount_pct` | text |")}, bump=True)
    cc = {c: P[c]["distinct"] for c in ("country", "channel", "customer_id")}
    s.turn("How many distinct non-empty values do country, channel and customer_id have? Do not change any files.",
           [facts(all=[r"country\D{0,10}" + numrx(cc["country"]), r"channel\D{0,10}" + numrx(cc["channel"]), r"customer_id\D{0,10}" + numrx(cc["customer_id"])])],
           msg=f"ANSWER: country {cc['country']}, channel {cc['channel']}, customer_id {cc['customer_id']}", wrong_msg=f"ANSWER: country {cc['country'] + 1}, channel {cc['channel']}, customer_id {cc['customer_id']}", bump=True)
    s.func("t4", f"""
        rows = md_rows('docs/data-dictionary.md', 'columns')
        need([c.lower() for c in rows[0][:6]] == ['column', 'type', 'nulls', 'distinct', 'min', 'max'], 'header: ' + str(rows[:1]))
        got = {{r[0].strip('` '): [r[1], int(num(r[2])), int(num(r[3])), r[4].strip('` '), r[5].strip('` ')] for r in rows[1:] if len(r) >= 6}}
        want = {({c: [d['type'], d['nulls'], d['distinct'], d['min'], d['max']] for c, d in P.items()})!r}
        need(got == want, 'differs: ' + str({{k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}}))
        """)
    d4 = "# Data dictionary\n\n## Columns\n\n" + dd_table(P)
    s.turn("Extend the Columns table with columns distinct (number of distinct non-empty values), min and max. For integer, decimal and date columns min/max are the smallest and largest value (decimals with 2 places); for boolean and text columns write `-` in both.",
           [s.g("t4")], files={"docs/data-dictionary.md": d4}, wrong_files={"docs/data-dictionary.md": d4.replace(f"| {P['total']['min']} |", f"| {float(P['total']['min']) + 1:.2f} |")}, bump=True)
    s.func("t5", f"""
        txt = read('docs/data-dictionary.md')
        m = re.search(r'^## Categorical values\\s*$(.*?)(?=^## |\\Z)', txt, re.M | re.S)
        need(m, 'missing ## Categorical values')
        got = {{}}
        for mm in re.finditer(r'^- `(\\w+)`:\\s*(.*)$', m.group(1), re.M):
            got[mm.group(1)] = [x.strip('` ') for x in mm.group(2).split(',')]
        need(got == {cat!r}, f'categorical lists differ: {{got}}')
        """)
    catsec = "\n## Categorical values\n\n" + "".join(f"- `{c}`: " + ", ".join(f"`{v}`" for v in vs) + "\n" for c, vs in cat.items())
    s.turn("Add a `## Categorical values` section with one bullet per column among country, channel, discount_pct and notes: ``- `column`: `a`, `b`, ...`` listing its distinct non-empty values sorted as plain strings (each value in backticks).",
           [s.g("t5")], files={"docs/data-dictionary.md": d4 + catsec}, wrong_files={"docs/data-dictionary.md": d4 + catsec.replace("`FR`, ", "")})
    byc = {}
    for r in rows:
        byc[r[3]] = round(byc.get(r[3], 0) + float(r[5]), 2)
    s.turn("What is the sum of the total column per channel in data/orders.csv, to 2 decimals? Do not change any files.",
           [facts(all=[numrx(v, 2) for v in byc.values()])], msg="ANSWER: " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(byc.items())), wrong_msg="ANSWER: " + ", ".join(f"{k} {v + 1:.2f}" for k, v in sorted(byc.items())), bump=True)
    s.func("t7", f"""
        rows = md_rows('docs/data-dictionary.md', 'revenue by channel')
        got = {{r[0].strip('` '): num(r[1]) for r in rows[1:] if len(r) >= 2}}
        need(sorted(got) == {sorted(byc)!r} and all(abs(got[k] - v) <= 0.011 for k, v in {byc!r}.items()), 'channel sums: ' + str(got))
        need(len(rows[1:]) == 3, 'three rows')
        """)
    rev = "\n## Revenue by channel\n\n| channel | total |\n|---|---|\n" + "".join(f"| {k} | {v:.2f} |\n" for k, v in sorted(byc.items()))
    s.turn("Add a `## Revenue by channel` section with a table (channel, total): the sum of the total column per channel, 2 decimals, channels sorted alphabetically.",
           [s.g("t7")], files={"docs/data-dictionary.md": d4 + catsec + rev}, wrong_files={"docs/data-dictionary.md": d4 + catsec + rev.replace(f"| app | {byc['app']:.2f} |", f"| app | {byc['app'] + 2:.2f} |")}, bump=True)
    s.func("t8", f"""
        import tempfile
        (W / '_alt').mkdir(exist_ok=True)
        (W / '_alt/t.csv').write_text('id,flag,amount,day,note\\n1,true,2.5,2025-01-02,\\n2,false,10.25,2025-01-09,x\\n3,true,,2025-02-01,x\\n', encoding='utf-8')
        need((W / 'scripts/profile.py').exists(), 'missing scripts/profile.py')
        chk_cmd_json('python3 scripts/profile.py --csv _alt/t.csv', {{
            'id': {{'type': 'integer', 'nulls': 0, 'distinct': 3, 'min': '1', 'max': '3'}},
            'flag': {{'type': 'boolean', 'nulls': 0, 'distinct': 2, 'min': '-', 'max': '-'}},
            'amount': {{'type': 'decimal', 'nulls': 1, 'distinct': 2, 'min': '2.50', 'max': '10.25'}},
            'day': {{'type': 'date', 'nulls': 0, 'distinct': 3, 'min': '2025-01-02', 'max': '2025-02-01'}},
            'note': {{'type': 'text', 'nulls': 1, 'distinct': 1, 'min': '-', 'max': '-'}}}}, tol=0)
        chk_cmd_json('python3 scripts/profile.py', {({c: d for c, d in P.items()})!r}, tol=0)
        """)
    s.turn("Add scripts/profile.py [--csv FILE] (default data/orders.csv): it prints JSON {column: {type, nulls, distinct, min, max}} using the same type rules as the dictionary and the same min/max formatting (strings; `-` when not applicable).",
           [s.g("t8")], files={"scripts/profile.py": PROFILE}, wrong_files={"scripts/profile.py": PROFILE.replace('"decimal"', '"number"')})
    s.func("t9", f"""
        rows = md_rows('docs/data-dictionary.md', 'columns')
        got = {{r[0].strip('` '): [r[1], int(num(r[2])), int(num(r[3])), r[4].strip('` '), r[5].strip('` ')] for r in rows[1:] if len(r) >= 6}}
        want = {({c: [d['type'], d['nulls'], d['distinct'], d['min'], d['max']] for c, d in P2.items()})!r}
        need(got == want, 'refresh profile differs: ' + str({{k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}}))
        need('{len(refresh)}' in read('docs/data-dictionary.md'), 'mention the new row count {len(refresh)}')
        """)
    dr = "# Data dictionary\n\n" + f"Based on data/orders_refresh.csv ({len(refresh)} rows).\n\n## Columns\n\n" + dd_table(P2)
    s.turn("data/orders_refresh.csv replaces the extract. Regenerate the Columns table in docs/data-dictionary.md from it (same rules as before: one row per CSV column, so the three id/date columns and all six value columns) and add one sentence naming the file and its row count.",
           [s.g("t9")], files={"docs/data-dictionary.md": dr}, wrong_files={"docs/data-dictionary.md": d4}, bump=True)
    s.turn("Add a '## Data dictionary' section to README.md linking docs/data-dictionary.md and showing how to run `python3 scripts/profile.py --csv data/orders_refresh.csv`.",
           [sections("README.md", "Data dictionary"), rx("README.md", r"docs/data-dictionary\.md"), rx("README.md", r"scripts/profile\.py --csv data/orders_refresh\.csv")],
           files={"README.md": s.files["README.md"] + "\n## Data dictionary\n\nSee docs/data-dictionary.md. Regenerate the profile with `python3 scripts/profile.py --csv data/orders_refresh.csv`.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Data dictionary\n\nSee docs.\n"})
    return s
