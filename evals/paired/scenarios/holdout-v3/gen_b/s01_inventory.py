import csv, io, json, random
from lib import Scn, csv_text, dedent, exists, facts, numrx, rx, sections

SNAP = "2025-03-01"


def make(seed, nsku, whs):
    R = random.Random(seed)
    words = ["Bolt", "Washer", "Bracket", "Hinge", "Gasket", "Valve", "Sensor", "Relay", "Cable", "Clamp", "Spring", "Bearing"]
    skus = []
    for i in range(nsku):
        skus.append(dict(sku=f"SKU-{1000 + i * 7}", name=f"{R.choice(words)} {R.choice('ABCDEFGH')}{R.randint(10, 99)}",
                         cost=round(R.uniform(1.5, 48), 2), rp=R.randint(8, 48), sup=R.choice(["Acme", "Borealis", "Cato", "Delta"])))
    system = [(s["sku"], w, R.randint(0, 40)) for s in skus for w in whs]
    counts = []
    for sku, w, q in system:
        if R.random() < 0.72:
            d = 0 if R.random() < 0.6 else R.choice([-9, -7, -5, -4, -3, -2, -1, 1, 2, 3, 4, 6, 8])
            day = R.randint(0, 9)
            counts.append((sku, w, max(0, q + d), f"2025-02-{20 + day:02d}" if day < 9 else f"2025-03-0{day - 8}"))
    sq = {(a, b): c for a, b, c in system}
    for i, (a, b, c, d) in enumerate(counts):
        if sq[(a, b)] >= 20 and len(skus) > 10:
            counts[i] = (a, b, sq[(a, b)] - 17, d)
            break
    po = []
    for i in range(max(6, nsku * 5 // 8)):
        po.append((f"PO-{4400 + i}", R.choice(skus)["sku"], R.choice([10, 20, 25, 40, 50, 60]), f"2025-03-{R.randint(5, 28):02d}",
                   R.choice(["open", "open", "open", "received", "cancelled"])))
    return skus, system, counts, po


def compute(skus, system, counts, po):
    cost = {s["sku"]: s["cost"] for s in skus}
    sysq = {(a, b): c for a, b, c in system}
    rows = [(a, b, c - sysq[(a, b)], d) for a, b, c, d in counts]
    out = dict(rows_counted=len(rows), mismatched=sum(1 for r in rows if r[2]), net_variance_units=sum(r[2] for r in rows),
               abs_variance_units=sum(abs(r[2]) for r in rows), variance_value=round(sum(r[2] * cost[r[0]] for r in rows), 2))
    fresh = [r for r in rows if r[3] >= SNAP]
    out_f = dict(rows_counted_fresh=len(fresh), mismatched_fresh=sum(1 for r in fresh if r[2]), net_variance_units_fresh=sum(r[2] for r in fresh))
    onhand, openq = {}, {}
    for a, b, c in system:
        onhand[a] = onhand.get(a, 0) + c
    for _, a, q, _, st in po:
        if st == "open":
            openq[a] = openq.get(a, 0) + q
    reo = []
    for s in skus:
        av = onhand[s["sku"]] + openq.get(s["sku"], 0)
        if av < s["rp"]:
            reo.append([s["sku"], onhand[s["sku"]], openq.get(s["sku"], 0), s["rp"] - av, s["cost"]])
    reo.sort(key=lambda r: (-r[3], r[0]))
    return rows, out, out_f, reo


def files_of(skus, system, counts, po):
    return {"data/skus.csv": csv_text(["sku", "name", "unit_cost", "reorder_point", "supplier"], [[s["sku"], s["name"], f"{s['cost']:.2f}", s["rp"], s["sup"]] for s in skus]),
            "data/system_stock.csv": csv_text(["sku", "warehouse", "qty_system"], system),
            "data/cycle_counts.csv": csv_text(["sku", "warehouse", "qty_counted", "counted_on"], counts),
            "data/inbound.csv": csv_text(["po", "sku", "qty", "eta", "status"], po)}


RECON = '''"""Reconciliation CLI: python3 scripts/recon.py [--data-dir DIR]  -> JSON on stdout."""
import argparse, csv, json, os

SNAPSHOT = "%s"


def rows(d, name):
    with open(os.path.join(d, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def recon(d):
    cost = {r["sku"]: float(r["unit_cost"]) for r in rows(d, "skus.csv")}
    sysq = {(r["sku"], r["warehouse"]): int(r["qty_system"]) for r in rows(d, "system_stock.csv")}
    diffs = []
    for r in rows(d, "cycle_counts.csv"):
        diffs.append((r["sku"], int(r["qty_counted"]) - sysq[(r["sku"], r["warehouse"])], r["counted_on"]))
    out = {"rows_counted": len(diffs), "mismatched": sum(1 for x in diffs if x[1]), "net_variance_units": sum(x[1] for x in diffs),
           "abs_variance_units": sum(abs(x[1]) for x in diffs), "variance_value": round(sum(x[1] * cost[x[0]] for x in diffs), 2)}
#FRESH#    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    print(json.dumps(recon(ap.parse_args().data_dir), indent=2))
''' % SNAP
FRESH = '''    fresh = [x for x in diffs if x[2] >= SNAPSHOT]
    out.update(rows_counted_fresh=len(fresh), mismatched_fresh=sum(1 for x in fresh if x[1]),
               net_variance_units_fresh=sum(x[1] for x in fresh))
    return out
'''
RECON_V1 = RECON.replace('#FRESH#    return out\n', '    return out\n')
RECON = RECON.replace('#FRESH#    return out\n', FRESH)


def build():
    s = Scn("inventory-recon", "mixed", "mixed", "python",
            "Warehouse stock reconciliation: cycle counts vs system stock CSVs; exact variance figures, JSON/markdown/CSV reports, a small CLI that must generalise to another dataset, docs.",
            ["~/dev/amplifier-agent/.amplifier/evaluation/tasks (data-question-into-file pattern); inventory data is new and self-authored"],
            protected=["data/skus.csv", "data/system_stock.csv", "data/cycle_counts.csv", "data/inbound.csv"], long_gaps=[5, 9])
    skus, system, counts, po = make(7101, 48, ["WH-A", "WH-B"])
    rows, out, out_f, reo = compute(skus, system, counts, po)
    for k, v in files_of(skus, system, counts, po).items():
        s.file(k, v)
    s.file("README.md", dedent(f"""
        # stockroom

        Monthly stock reconciliation inputs live in `data/`:

        - `skus.csv` - sku, name, unit_cost, reorder_point, supplier
        - `system_stock.csv` - the ERP stock snapshot taken {SNAP} (sku, warehouse, qty_system)
        - `cycle_counts.csv` - physical counts (sku, warehouse, qty_counted, counted_on). Counts dated before {SNAP} are stale.
        - `inbound.csv` - purchase orders (po, sku, qty, eta, status = open | received | cancelled)

        Variance = qty_counted - qty_system. Outputs go to `out/`; helper scripts go to `scripts/`.
        """))
    top = sorted(rows, key=lambda r: (-abs(r[2]), r[0]))
    assert abs(top[0][2]) > abs(top[1][2]), "top variance must be unique"
    byw = {}
    cost = {x["sku"]: x["cost"] for x in skus}
    for a, b, d, _ in rows:
        byw[b] = round(byw.get(b, 0) + d * cost[a], 2)
    uncounted = len(system) - len({(a, b) for a, b, _, _ in rows})
    short_val = round(sum(r[3] * r[4] for r in reo), 2)
    assert 4 <= len(reo) <= 14, len(reo)
    full = {**out, **out_f}

    s.turn("Compare data/cycle_counts.csv with data/system_stock.csv (variance = qty_counted - qty_system, matched on sku + warehouse). How many count rows have a non-zero variance, and what is the total absolute variance in units? Do not change any files.",
           [facts(all=[numrx(out["mismatched"]), numrx(out["abs_variance_units"])])],
           msg=f"ANSWER: {out['mismatched']} of {out['rows_counted']} count rows differ; total absolute variance {out['abs_variance_units']} units",
           wrong_msg=f"ANSWER: {out['mismatched'] + 3} rows differ; absolute variance {out['abs_variance_units'] + 5} units", bump=True)
    t = top[0]
    s.turn("Which single count row has the largest absolute variance? Give the sku, the warehouse and the signed variance in units. Do not change any files.",
           [facts(all=[t[0], t[1], r"(?<![\d.,])" + ("-" if t[2] < 0 else r"\+?") + str(abs(t[2])) + r"(?!\d)"])],
           msg=f"ANSWER: {t[0]} in {t[1]}, variance {t[2]:+d} units", wrong_msg=f"ANSWER: {top[1][0]} in {top[1][1]}, variance {top[1][2]:+d}", bump=False)
    s.func("t3", f"chk_json('out/variance.json', {({k: full[k] for k in out})!r})")
    s.turn("Create out/variance.json with the keys rows_counted, mismatched, net_variance_units, abs_variance_units and variance_value (net variance units multiplied by each sku's unit_cost, summed, rounded to 2 decimals).",
           [s.g("t3")], files={"out/variance.json": json.dumps(out, indent=2) + "\n"}, wrong_files={"out/variance.json": json.dumps({**out, "variance_value": out["variance_value"] + 1.5}) + "\n"}, bump=True)
    s.turn("How many of the (sku, warehouse) rows in data/system_stock.csv have no row at all in data/cycle_counts.csv? Do not change any files.",
           [facts(all=[numrx(uncounted)])], msg=f"ANSWER: {uncounted} system rows were never counted", wrong_msg=f"ANSWER: {uncounted + 2} rows", bump=True)
    exp_w = {k: v for k, v in byw.items()}
    top5 = top[:5]
    s.func("t6", f"chk_table('report.md', 'by warehouse', {exp_w!r})")
    s.func("t6b", "rows = md_rows('report.md', 'top 5')\nneed(len(rows) >= 6, 'need header + 5 rows')\n"
                  f"got = [r for r in rows[1:] if r[0].startswith('SKU-')]\nneed([r[0] for r in got] == {[x[0] for x in top5]!r}, 'top-5 order: ' + str([r[0] for r in got]))\n"
                  f"need([int(num(r[-1])) for r in got] == {[abs(x[2]) for x in top5]!r}, 'absolute variances')")
    rep = dedent(f"""
        # Cycle count reconciliation

        ## Summary

        {out['rows_counted']} rows counted, {out['mismatched']} with a variance (net {out['net_variance_units']:+d} units, absolute {out['abs_variance_units']} units).

        ## Variance by warehouse

        | warehouse | net variance value |
        |---|---|
        """) + "".join(f"| {w} | {v:.2f} |\n" for w, v in sorted(exp_w.items())) + dedent("""
        ## Top 5 variances

        | sku | warehouse | absolute variance |
        |---|---|---|
        """) + "".join(f"| {x[0]} | {x[1]} | {abs(x[2])} |\n" for x in top5) + "\n## Open questions\n\n- Why are some counts older than the snapshot?\n"
    s.turn("Write report.md with level-2 sections Summary, Variance by warehouse, Top 5 variances and Open questions. Under Variance by warehouse put a table (warehouse in the first column, net variance value = sum of variance x unit_cost, 2 decimals, in the second). Under Top 5 variances put a table of the five largest absolute variances, largest first (ties by sku): sku, warehouse, absolute variance.",
           [sections("report.md", "Summary", "Variance by warehouse", "Top 5 variances", "Open questions"), s.g("t6"), s.g("t6b")],
           files={"report.md": rep}, wrong_files={"report.md": rep.replace(f"| {sorted(exp_w)[0]} | {exp_w[sorted(exp_w)[0]]:.2f} |", f"| {sorted(exp_w)[0]} | {exp_w[sorted(exp_w)[0]] + 1:.2f} |")}, bump=True)
    s.func("t7", f"""
        import csv
        need((W / 'out/reorder.csv').exists(), 'missing out/reorder.csv')
        with open('out/reorder.csv', encoding='utf-8', newline='') as f:
            rd = list(csv.DictReader(f))
        need(rd and list(rd[0].keys()) == ['sku', 'on_hand', 'open_inbound', 'reorder_point', 'shortfall'], 'header: ' + str(rd and list(rd[0].keys())))
        got = [[r['sku'], int(r['on_hand']), int(r['open_inbound']), int(r['shortfall'])] for r in rd]
        need(got == {[r[:4] for r in reo]!r}, 'rows differ: ' + str(got[:4]))
        """)
    RP = {x["sku"]: x["rp"] for x in skus}
    reo_csv = csv_text(["sku", "on_hand", "open_inbound", "reorder_point", "shortfall"], [[r[0], r[1], r[2], RP[r[0]], r[3]] for r in reo])
    wrong_reo = csv_text(["sku", "on_hand", "open_inbound", "reorder_point", "shortfall"], [[r[0], r[1], r[2], RP[r[0]], r[3]] for r in reo[:-1]])
    s.turn("Write out/reorder.csv listing every sku whose on-hand stock (sum of qty_system over both warehouses) plus open inbound quantity (inbound.csv rows with status open only) is below its reorder_point. Columns: sku, on_hand, open_inbound, reorder_point, shortfall (reorder_point minus on_hand minus open_inbound). Sort by shortfall descending, ties by sku ascending.",
           [s.g("t7")], files={"out/reorder.csv": reo_csv}, wrong_files={"out/reorder.csv": wrong_reo}, bump=True)
    s.turn("What is the total value of the shortfall, i.e. the sum of shortfall x unit_cost over the rows of out/reorder.csv, to 2 decimals? Do not change any files.",
           [facts(all=[numrx(short_val, 2)])], msg=f"ANSWER: {short_val:.2f}", wrong_msg=f"ANSWER: {short_val + 10:.2f}", bump=True)
    alt = make(55, 5, ["WH-A", "WH-B", "WH-C"])
    ar, aout, aout_f, _ = compute(*alt)
    afull = {**aout, **aout_f}
    altfiles = files_of(*alt)
    s.func("t10", f"""
        import os
        for rel, text in {altfiles!r}.items():
            p = W / '_alt' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        need((W / 'scripts/recon.py').exists(), 'missing scripts/recon.py')
        chk_cmd_json('python3 scripts/recon.py --data-dir _alt/data', {({k: afull[k] for k in out})!r})
        chk_cmd_json('python3 scripts/recon.py', {({k: full[k] for k in out})!r})
        """)
    s.turn("Add scripts/recon.py: a CLI that recomputes the five out/variance.json figures from the CSVs and prints them as JSON on stdout. It must take --data-dir (default data) so it can run against another folder holding the same four CSV files.",
           [s.g("t10")], files={"scripts/recon.py": RECON_V1}, wrong_files={"scripts/recon.py": RECON_V1.replace("sysq[(r[\"sku\"], r[\"warehouse\"])]", "0")}, bump=False)
    s.func("t11", f"chk_json('out/variance.json', {({k: full[k] for k in out_f} | {k: full[k] for k in out})!r})")
    s.turn(f"The ERP snapshot is dated {SNAP}, so counts dated before then are stale. Extend out/variance.json (keep the five existing keys) with rows_counted_fresh, mismatched_fresh and net_variance_units_fresh, computed only over counts dated on or after {SNAP}.",
           [s.g("t11")], files={"out/variance.json": json.dumps(full, indent=2) + "\n"},
           wrong_files={"out/variance.json": json.dumps({**full, "mismatched_fresh": out_f["mismatched_fresh"] + 2}) + "\n"}, bump=True)
    s.func("t12", f"""
        chk_cmd_json('python3 scripts/recon.py', {full!r})
        """)
    s.turn("Update scripts/recon.py so its JSON output also contains the three *_fresh keys, exactly as in out/variance.json.",
           [s.g("t12")], files={"scripts/recon.py": RECON}, wrong_files={"scripts/recon.py": RECON.replace("if x[2] >= SNAPSHOT", "if x[2] > SNAPSHOT")}, bump=False)
    s.turn("Add a '## Reconciliation' section to README.md that explains how to run `python3 scripts/recon.py`, names the --data-dir option, and lists the output files out/variance.json, out/reorder.csv and report.md.",
           [sections("README.md", "Reconciliation"), rx("README.md", r"scripts/recon\.py"), rx("README.md", r"--data-dir"), rx("README.md", r"out/reorder\.csv"), rx("README.md", r"out/variance\.json"), rx("README.md", r"report\.md", 1)],
           files={"README.md": s.files["README.md"] + "\n## Reconciliation\n\nRun `python3 scripts/recon.py` (optionally `--data-dir DIR`) to print the variance figures as JSON.\nOutputs: `out/variance.json`, `out/reorder.csv` and `report.md`.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Reconciliation\n\nRun the script.\n"})
    return s
