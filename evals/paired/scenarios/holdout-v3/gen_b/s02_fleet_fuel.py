import datetime as dt, json, random
from decimal import ROUND_HALF_UP, Decimal
from lib import Scn, csv_text, dedent, facts, numrx, rx, sections


def make(seed, nveh, fills):
    R = random.Random(seed)
    veh = []
    for i in range(nveh):
        veh.append(dict(id=f"V-{i + 1:02d}", make=R.choice(["Hauler", "Courier", "Ranger", "Metro"]), cls=R.choice(["van", "truck", "sedan"]),
                        tank=R.choice([45, 60, 80, 100]), l100=R.uniform(6.5, 19.0)))
    rows = []
    for v in veh:
        d, odo = dt.date(2025, 1, 2) + dt.timedelta(R.randint(0, 6)), R.randint(12000, 90000)
        for _ in range(fills):
            km = R.randint(380, 720)
            odo += km
            lit = round(min(v["tank"] - 1, km * v["l100"] / 100 * R.uniform(0.96, 1.04)), 1)
            rows.append([d.isoformat(), v["id"], odo, lit, f"{R.uniform(1.45, 1.8):.2f}", R.choice(["Shell", "BP", "Costco", "Esso"])])
            d += dt.timedelta(R.randint(7, 12))
    # plant anomalies deterministically (never the first row of a vehicle)
    byv = {}
    for i, r in enumerate(rows):
        byv.setdefault(r[1], []).append(i)
    for k, vid in enumerate(sorted(byv)[:3]):
        i = byv[vid][4 + k]
        rows[i][2] = int(str(rows[i][2])[1:]) + 0           # lost leading digit -> odometer decrease
    tank = {v["id"]: v["tank"] for v in veh}
    for k, vid in enumerate(sorted(byv)[3:6]):
        i = byv[vid][6 + k]
        rows[i][3] = tank[vid] + 7 + k * 3
    rows.sort(key=lambda r: (r[0], r[1]))
    return veh, rows


def cost(r):
    """Cost of a fill: litres x price_per_l rounded half up to 2 decimals (decimal arithmetic)."""
    return (Decimal(str(r[3])) * Decimal(str(r[4]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def analyse(veh, rows):
    tank = {v["id"]: v["tank"] for v in veh}
    last, anomalies, clean = {}, [], []
    for r in sorted(rows, key=lambda r: (r[1], r[0])):
        prev = last.get(r[1])
        if prev is not None and r[2] < prev:
            anomalies.append({"vehicle": r[1], "date": r[0], "reason": "odometer_decrease"})
        elif r[3] > tank[r[1]]:
            anomalies.append({"vehicle": r[1], "date": r[0], "reason": "over_tank"})
        else:
            clean.append(r)
            last[r[1]] = r[2]
    anomalies.sort(key=lambda a: (a["date"], a["vehicle"]))
    spend = float(sum(cost(r) for r in clean))
    monthly = {}
    for r in clean:
        monthly[r[0][:7]] = round(monthly.get(r[0][:7], 0) + float(cost(r)), 2)
    eco, prev = {}, {}
    for r in sorted(clean, key=lambda r: (r[1], r[0])):
        if r[1] in prev:
            e = eco.setdefault(r[1], [0, 0.0])
            e[0] += r[2] - prev[r[1]]
            e[1] += float(r[3])
        prev[r[1]] = r[2]
    table = sorted(([v, km, round(l, 1), round(l / km * 100, 2)] for v, (km, l) in eco.items()), key=lambda x: (x[3], x[0]))
    return anomalies, clean, spend, monthly, table


FUEL = '''"""Fleet fuel economy. Usage: python3 scripts/fuel.py [--csv PATH]  -> JSON {vehicle: l_per_100km}; needs vehicles.csv next to the log."""
import argparse, csv, json, os


def economy(path):
    vehicles = {r["vehicle"]: float(r["tank_l"]) for r in csv.DictReader(open(os.path.join(os.path.dirname(path) or ".", "vehicles.csv"), encoding="utf-8"))}
    rows = sorted(csv.DictReader(open(path, encoding="utf-8")), key=lambda r: (r["vehicle"], r["date"]))
    last, tot = {}, {}
    for r in rows:
        odo, lit = int(r["odometer_km"]), float(r["litres"])
        if r["vehicle"] in last and odo < last[r["vehicle"]]:
            continue
        if lit > vehicles[r["vehicle"]]:
            continue
        if r["vehicle"] in last:
            t = tot.setdefault(r["vehicle"], [0, 0.0])
            t[0] += odo - last[r["vehicle"]]
            t[1] += lit
        last[r["vehicle"]] = odo
    return {v: round(l / km * 100, 2) for v, (km, l) in sorted(tot.items())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/fuel_log.csv")
    print(json.dumps(economy(ap.parse_args().csv), indent=2))
'''


def files(veh, rows):
    return {"data/fuel_log.csv": csv_text(["date", "vehicle", "odometer_km", "litres", "price_per_l", "station"], rows),
            "data/vehicles.csv": csv_text(["vehicle", "make", "class", "tank_l"], [[v["id"], v["make"], v["cls"], v["tank"]] for v in veh])}


def build():
    s = Scn("fleet-fuel", "mixed", "mixed", "python",
            "Fleet fuel log CSV: anomaly detection, spend and L/100km tables, a generalising CLI, methodology docs.",
            ["new self-authored fleet dataset; pattern follows data-question/report tasks in ~/dev/amplifier-agent/.amplifier/evaluation/tasks"],
            protected=["data/fuel_log.csv", "data/vehicles.csv"])
    veh, rows = make(7202, 12, 14)
    for k, v in files(veh, rows).items():
        s.file(k, v)
    s.file("README.md", "# fleet-fuel\n\n`data/fuel_log.csv` holds one row per fill-up (date, vehicle, odometer_km, litres, price_per_l, station).\n`data/vehicles.csv` lists tank capacity per vehicle. Cost of a fill = litres x price_per_l rounded half up to 2 decimals.\n")
    anomalies, clean, spend, monthly, table = analyse(veh, rows)
    assert len(anomalies) == 6, anomalies
    over = [a for a in anomalies if a["reason"] == "over_tank"]
    dec = [a for a in anomalies if a["reason"] == "odometer_decrease"]
    tl = round(sum(float(r[3]) for r in rows), 1)
    assert len({t[3] for t in table}) == len(table)
    best, worst = table[0], table[-1]

    s.turn("How many fill-up rows are in data/fuel_log.csv, how many distinct vehicles appear, and what is the total of the litres column over all rows (1 decimal)? Do not change any files.",
           [facts(all=[numrx(len(rows)), numrx(len(veh)), numrx(tl, 1)])], msg=f"ANSWER: {len(rows)} rows, {len(veh)} vehicles, {tl} litres",
           wrong_msg=f"ANSWER: {len(rows)} rows, {len(veh)} vehicles, {tl + 1.5} litres", bump=True)
    s.turn("Some fills are physically impossible: litres larger than the vehicle's tank_l in data/vehicles.csv. How many such rows are there, and which vehicles are involved? Do not change any files.",
           [facts(all=[numrx(len(over))] + sorted({a["vehicle"] for a in over}))], msg=f"ANSWER: {len(over)} rows; vehicles {', '.join(sorted({a['vehicle'] for a in over}))}",
           wrong_msg=f"ANSWER: {len(over) + 1} rows; vehicles V-01", bump=True)
    s.func("t3", f"""
        d = load_json('out/anomalies.json')
        need(isinstance(d, list), 'must be a list')
        norm = sorted((a.get('vehicle'), a.get('date'), a.get('reason')) for a in d)
        need(norm == {sorted((a['vehicle'], a['date'], a['reason']) for a in anomalies)!r}, 'anomalies differ: ' + str(norm))
        """)
    aj = json.dumps(anomalies, indent=2) + "\n"
    s.turn("Create out/anomalies.json: a JSON list with one object {vehicle, date, reason} per bad row. reason is `over_tank` (litres > tank_l) or `odometer_decrease` (odometer lower than the vehicle's previous kept fill-up by date; a row flagged earlier does not become the reference). If both apply use odometer_decrease.",
           [s.g("t3")], files={"out/anomalies.json": aj}, wrong_files={"out/anomalies.json": json.dumps(anomalies[:-1]) + "\n"}, bump=True)
    s.turn("Ignoring every row listed in out/anomalies.json, what is the total fuel spend over the remaining rows? A fill costs litres x price_per_l rounded half up to 2 decimals; give the sum to 2 decimals. Do not change any files.",
           [facts(all=[numrx(spend, 2)])], msg=f"ANSWER: {spend:.2f}", wrong_msg=f"ANSWER: {spend + 12.34:.2f}", bump=True)
    s.func("t5", f"""
        import csv
        need((W / 'out/economy.csv').exists(), 'missing out/economy.csv')
        rd = list(csv.DictReader(open('out/economy.csv', encoding='utf-8', newline='')))
        need(rd and list(rd[0].keys()) == ['vehicle', 'km', 'litres', 'l_per_100km'], 'header ' + str(rd and list(rd[0])))
        got = [[r['vehicle'], int(r['km']), round(float(r['litres']), 1), round(float(r['l_per_100km']), 2)] for r in rd]
        need(got == {table!r}, 'economy rows differ: ' + str(got[:3]))
        """)
    ec = csv_text(["vehicle", "km", "litres", "l_per_100km"], [[t[0], t[1], f"{t[2]:.1f}", f"{t[3]:.2f}"] for t in table])
    s.turn("Write out/economy.csv with columns vehicle, km, litres, l_per_100km over the non-anomalous rows only. Per vehicle, order its rows by date; the first kept row is only a baseline; km is the sum of odometer differences between consecutive kept rows and litres is the sum of the litres of every kept row except the baseline. l_per_100km = litres / km * 100 rounded to 2 decimals (litres to 1 decimal). Sort by l_per_100km ascending.",
           [s.g("t5")], files={"out/economy.csv": ec}, wrong_files={"out/economy.csv": ec.replace(f"{best[3]:.2f}", f"{best[3] + 0.5:.2f}", 1)}, bump=True)
    s.turn("Using out/economy.csv, which vehicle is the most economical and which the least, and what are their l_per_100km values? Do not change any files.",
           [facts(all=[best[0], numrx(best[3], 2), worst[0], numrx(worst[3], 2)])], msg=f"ANSWER: best {best[0]} at {best[3]:.2f}; worst {worst[0]} at {worst[3]:.2f}",
           wrong_msg=f"ANSWER: best {best[0]} at {best[3]:.2f}; worst {worst[0]} at {worst[3] - 1.1:.2f}", bump=True)
    s.func("t7", f"chk_table('report.md', 'monthly', {monthly!r})")
    rep = "# Fleet fuel report\n\n## Summary\n\n" + f"{len(clean)} clean fills; total spend {spend:.2f}.\n\n## Monthly spend\n\n| month | spend |\n|---|---|\n" + "".join(f"| {m} | {v:.2f} |\n" for m, v in sorted(monthly.items())) + "\n## Data quality\n\n" + f"{len(anomalies)} rows were excluded (see out/anomalies.json).\n"
    s.turn("Write report.md with level-2 sections Summary, Monthly spend and Data quality. Monthly spend is a table (month as YYYY-MM in the first column, spend in the second, 2 decimals) over non-anomalous rows only.",
           [sections("report.md", "Summary", "Monthly spend", "Data quality"), s.g("t7")], files={"report.md": rep},
           wrong_files={"report.md": rep.replace(f"| {sorted(monthly)[0]} | {monthly[sorted(monthly)[0]]:.2f} |", f"| {sorted(monthly)[0]} | {monthly[sorted(monthly)[0]] + 3:.2f} |")}, bump=True)
    alt_veh, alt_rows = make(77, 4, 9)
    _, _, _, _, atable = analyse(alt_veh, alt_rows)
    aexp = {t[0]: t[3] for t in atable}
    full = {t[0]: t[3] for t in table}
    s.func("t8", f"""
        for rel, text in {files(alt_veh, alt_rows)!r}.items():
            p = W / '_alt' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        need((W / 'scripts/fuel.py').exists(), 'missing scripts/fuel.py')
        chk_cmd_json('python3 scripts/fuel.py --csv _alt/data/fuel_log.csv', {aexp!r}, tol=0.0051)
        chk_cmd_json('python3 scripts/fuel.py', {full!r}, tol=0.0051)
        """)
    s.turn("Add scripts/fuel.py: it prints a JSON object {vehicle: l_per_100km} (2 decimals, same rules as out/economy.csv, anomalous rows ignored). --csv PATH selects the fuel log (default data/fuel_log.csv); vehicles.csv is read from the same folder as that log.",
           [s.g("t8")], files={"scripts/fuel.py": FUEL}, wrong_files={"scripts/fuel.py": FUEL.replace("if lit > vehicles[r[\"vehicle\"]]:", "if False:")}, bump=False)
    s.turn("Add a '## Methodology' section to README.md describing how anomalies are detected (name both reasons, over_tank and odometer_decrease), how l_per_100km is computed, and how to run scripts/fuel.py with --csv.",
           [sections("README.md", "Methodology"), rx("README.md", "over_tank"), rx("README.md", "odometer_decrease"), rx("README.md", r"--csv"), rx("README.md", r"scripts/fuel\.py"), rx("README.md", r"(?i)baseline")],
           files={"README.md": s.files["README.md"] + "\n## Methodology\n\nAnomalies: `over_tank` rows (litres above tank_l) and `odometer_decrease` rows are ignored.\nl_per_100km = litres / km * 100 from consecutive kept fills; the first kept fill is a baseline.\nRun `python3 scripts/fuel.py --csv data/fuel_log.csv`.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Methodology\n\nSee the code.\n"})
    return s
