import datetime as dt, json, random
from lib import Scn, csv_text, exists, facts, numrx, rx, sections


def make(seed, n, n_mis, n_bank_only, n_ledger_only, n_prob):
    R = random.Random(seed)
    used_amt, bank, ledger = set(), [], []

    def amt():
        while True:
            a = R.randint(1500, 480000)
            if a not in used_amt:
                used_amt.add(a)
                return a if R.random() < 0.8 else -a
    day0 = dt.date(2025, 3, 1)
    for i in range(n):
        ref, a, d = f"TX-{1000 + i}", amt(), day0 + dt.timedelta(R.randint(0, 27))
        bank.append([d, ref, a])
        ledger.append([d + dt.timedelta(R.choice([0, 0, 1, 2])), ref, a])
    drop = sorted(R.sample(range(n), n_bank_only + n_ledger_only))
    for i in sorted(R.sample([x for x in range(n) if x not in drop], n_mis)):
        ledger[i][2] = bank[i][2] + R.choice([-90, 90, 450, -1800])
        used_amt.add(abs(ledger[i][2]))
    rng = drop[:]
    bo = rng[:n_bank_only]
    lo = rng[n_bank_only:]
    typo = {}
    for k, i in enumerate(bo[:n_prob]):
        typo[i] = f"TX-{9000 + k}"
    new_ledger = []
    for i, row in enumerate(ledger):
        if i in bo:
            if i in typo:
                new_ledger.append([row[0] + dt.timedelta(1), typo[i], row[2]])
            continue
        new_ledger.append(row)
    # ledger_only: remove from bank
    new_bank = [row for i, row in enumerate(bank) if i not in lo]
    for k in range(2):  # extra pure ledger-only rows
        new_ledger.append([day0 + dt.timedelta(20 + k), f"TX-{8000 + k}", amt()])
    new_bank.append([day0 + dt.timedelta(26), "TX-7001", amt()])
    new_bank.sort(key=lambda r: (r[0], r[1]))
    new_ledger.sort(key=lambda r: (r[0], r[1]))
    return new_bank, new_ledger


def cents(a):
    return f"{a / 100:.2f}"


def analyse(bank, ledger):
    b, l = {r[1]: r for r in bank}, {r[1]: r for r in ledger}
    matched = [r for r in b if r in l and b[r][2] == l[r][2]]
    mism = sorted(r for r in b if r in l and b[r][2] != l[r][2])
    bo = sorted(r for r in b if r not in l)
    lo = sorted(r for r in l if r not in b)
    prob = []
    used = set()
    for br in bo:
        for lr in lo:
            if lr not in used and l[lr][2] == b[br][2] and abs((l[lr][0] - b[br][0]).days) <= 3:
                prob.append([br, lr])
                used.add(lr)
                break
    out = dict(matched=len(matched), amount_mismatch=len(mism), bank_only=len(bo), ledger_only=len(lo),
               bank_only_total=round(sum(b[r][2] for r in bo) / 100, 2), ledger_only_total=round(sum(l[r][2] for r in lo) / 100, 2))
    ext = dict(probable_matches=len(prob), bank_only_unexplained=len(bo) - len(prob), ledger_only_unexplained=len(lo) - len(prob))
    unrec = []
    for ref in sorted(set(mism) | set(bo) | set(lo)):
        kind = "amount_mismatch" if ref in mism else ("bank_only" if ref in bo else "ledger_only")
        if ref in b:
            unrec.append(["bank", ref, b[ref][0].isoformat(), cents(b[ref][2]), kind])
        if ref in l:
            unrec.append(["ledger", ref, l[ref][0].isoformat(), cents(l[ref][2]), kind])
    return out, ext, prob, unrec, matched, mism, bo, lo


RECON = '''"""Bank vs ledger reconciliation: python3 scripts/recon.py [--bank F] [--ledger F] -> JSON counts on stdout."""
import argparse, csv, datetime as dt, json


def load(p):
    return {r["ref"]: (dt.date.fromisoformat(r["date"]), round(float(r["amount"]) * 100)) for r in csv.DictReader(open(p, encoding="utf-8"))}


def recon(bank, ledger):
    b, l = load(bank), load(ledger)
    matched = [r for r in b if r in l and b[r][1] == l[r][1]]
    mism = [r for r in b if r in l and b[r][1] != l[r][1]]
    bo = sorted(r for r in b if r not in l)
    lo = sorted(r for r in l if r not in b)
    prob, used = [], set()
    for br in bo:
        for lr in lo:
            if lr not in used and l[lr][1] == b[br][1] and abs((l[lr][0] - b[br][0]).days) <= 3:
                prob.append((br, lr))
                used.add(lr)
                break
    out = {"matched": len(matched), "amount_mismatch": len(mism), "bank_only": len(bo), "ledger_only": len(lo),
           "bank_only_total": round(sum(b[r][1] for r in bo) / 100, 2), "ledger_only_total": round(sum(l[r][1] for r in lo) / 100, 2)}
#EXT#    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="data/bank.csv")
    ap.add_argument("--ledger", default="data/ledger.csv")
    a = ap.parse_args()
    print(json.dumps(recon(a.bank, a.ledger), indent=2))
'''
EXT = '''    out.update(probable_matches=len(prob), bank_only_unexplained=len(bo) - len(prob), ledger_only_unexplained=len(lo) - len(prob))
    return out
'''
RECON_V1 = RECON.replace("#EXT#    return out\n", "    return out\n")
RECON_V2 = RECON.replace("#EXT#    return out\n", EXT)


def fcsv(rows, extra=()):
    return csv_text(["date", "ref", "amount"], [[r[0].isoformat(), r[1], cents(r[2])] for r in rows])


def build():
    s = Scn("bank-recon", "mixed", "mixed", "python",
            "Bank statement vs ledger CSV reconciliation: matched/mismatch/one-sided counts and totals, unreconciled CSV, probable-match heuristics, a CLI that generalises, docs.",
            ["new self-authored reconciliation dataset (amounts in exact cents); report-from-CSV pattern as in the amplifier-agent benchmark data tasks"],
            protected=["data/bank.csv", "data/ledger.csv"])
    bank, ledger = make(7606, 80, 5, 8, 6, 4)
    s.file("data/bank.csv", fcsv(bank))
    s.file("data/ledger.csv", fcsv(ledger))
    s.file("README.md", "# bank-recon\n\n`data/bank.csv` and `data/ledger.csv` (date, ref, amount) cover March 2025. Rows are matched on `ref`. Amounts are signed (negative = money out) with two decimals.\n")
    out, ext, prob, unrec, matched, mism, bo, lo = analyse(bank, ledger)
    full = {**out, **ext}
    assert len(prob) == 4 and out["amount_mismatch"] == 5, (prob, out)
    msum = round(sum(r[2] for r in bank if r[1] in set(matched)) / 100, 2)
    diff = round((sum(r[2] for r in bank) - sum(r[2] for r in ledger)) / 100, 2)
    s.turn("Match data/bank.csv against data/ledger.csv on the `ref` column. How many refs match with an identical amount, and what is the sum of those matched amounts (2 decimals)? Do not change any files.",
           [facts(all=[numrx(out["matched"]), numrx(msum, 2)])], msg=f"ANSWER: {out['matched']} matched, total {msum:.2f}", wrong_msg=f"ANSWER: {out['matched'] + 1} matched, total {msum:.2f}", bump=True)
    s.turn("Which refs exist in both files but with different amounts? List them. Do not change any files.",
           [facts(all=mism)], msg="ANSWER: " + ", ".join(mism), wrong_msg="ANSWER: " + ", ".join(mism[:-1]), bump=False)
    s.func("t3", f"chk_json('out/recon.json', {out!r}, tol=0.0051)")
    s.turn("Create out/recon.json with the integer counts matched, amount_mismatch, bank_only (refs only in the bank file) and ledger_only (refs only in the ledger), plus bank_only_total and ledger_only_total (signed sums, 2 decimals).",
           [s.g("t3")], files={"out/recon.json": json.dumps(out, indent=2) + "\n"}, wrong_files={"out/recon.json": json.dumps({**out, "ledger_only": out["ledger_only"] + 1}) + "\n"}, bump=True)
    s.turn("What is the signed sum of all amounts in the bank file minus the signed sum of all amounts in the ledger file, to 2 decimals? Do not change any files.",
           [facts(all=[numrx(diff, 2)])], msg=f"ANSWER: {diff:.2f}", wrong_msg=f"ANSWER: {diff + 5:.2f}", bump=True)
    s.func("t5", f"""
        import csv
        rd = list(csv.reader(open('out/unreconciled.csv', encoding='utf-8', newline=''))) if (W / 'out/unreconciled.csv').exists() else fail('missing out/unreconciled.csv')
        need(rd[0] == ['side', 'ref', 'date', 'amount', 'kind'], 'header ' + str(rd[0]))
        got = [[r[0], r[1], r[2], r[3], r[4]] for r in rd[1:]]
        need(got == {unrec!r}, 'rows differ; first diff: ' + str([g for g in got if g not in {unrec!r}][:2]))
        """)
    s.turn("Write out/unreconciled.csv (header side,ref,date,amount,kind): one row for every side of every ref that is not an exact match. side is bank or ledger; kind is amount_mismatch, bank_only or ledger_only; sort by ref, then bank before ledger; amount with two decimals.",
           [s.g("t5")], files={"out/unreconciled.csv": csv_text(["side", "ref", "date", "amount", "kind"], unrec)}, wrong_files={"out/unreconciled.csv": csv_text(["side", "ref", "date", "amount", "kind"], unrec[:-1])}, bump=False)
    kinds = {"amount_mismatch": out["amount_mismatch"], "bank_only": out["bank_only"], "ledger_only": out["ledger_only"]}
    s.func("t6", f"chk_table('report.md', 'unreconciled', {kinds!r})")
    rep = "# Reconciliation report\n\n## Summary\n\n" + f"{out['matched']} refs match exactly; bank minus ledger is {diff:.2f}.\n\n## Unreconciled items\n\n| kind | refs |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in kinds.items()) + "\n## Next steps\n\nInvestigate each listed ref.\n"
    s.turn("Write report.md with level-2 sections Summary, Unreconciled items and Next steps. Unreconciled items is a table with the kind in the first column (amount_mismatch, bank_only, ledger_only) and the number of refs in the second.",
           [sections("report.md", "Summary", "Unreconciled items", "Next steps"), s.g("t6")], files={"report.md": rep},
           wrong_files={"report.md": rep.replace(f"| bank_only | {kinds['bank_only']} |", f"| bank_only | {kinds['bank_only'] + 1} |")}, bump=True)
    s.func("t7", f"chk_json('out/probable.json', {prob!r}, tol=0)")
    s.turn("Some bank-only rows are really typos in the ledger ref. Create out/probable.json: a list of [bank_ref, ledger_ref] pairs where a bank-only ref and a ledger-only ref have the same amount and dates at most 3 days apart; each ledger ref is used once; sorted by bank_ref.",
           [s.g("t7")], files={"out/probable.json": json.dumps(prob) + "\n"}, wrong_files={"out/probable.json": json.dumps([[b, b] for b, _ in prob]) + "\n"})
    alt = make(31, 20, 2, 3, 3, 2)
    aout, aext, *_ = analyse(*alt)
    s.func("t8", f"""
        for rel, text in {({'_alt/bank.csv': fcsv(alt[0]), '_alt/ledger.csv': fcsv(alt[1])})!r}.items():
            (W / rel).parent.mkdir(parents=True, exist_ok=True)
            (W / rel).write_text(text, encoding='utf-8')
        need((W / 'scripts/recon.py').exists(), 'missing scripts/recon.py')
        chk_cmd_json('python3 scripts/recon.py --bank _alt/bank.csv --ledger _alt/ledger.csv', {aout!r}, tol=0.0051)
        chk_cmd_json('python3 scripts/recon.py', {out!r}, tol=0.0051)
        """)
    s.turn("Add scripts/recon.py [--bank FILE] [--ledger FILE] (defaults data/bank.csv and data/ledger.csv): prints the six out/recon.json figures as JSON on stdout. Compare amounts as exact cents, not floats.",
           [s.g("t8")], files={"scripts/recon.py": RECON_V1}, wrong_files={"scripts/recon.py": RECON_V1.replace("b[r][1] == l[r][1]", "True")})
    full2 = {**out, **ext}
    s.func("t9", f"""
        for rel, text in {({'_alt/bank.csv': fcsv(alt[0]), '_alt/ledger.csv': fcsv(alt[1])})!r}.items():
            (W / rel).parent.mkdir(parents=True, exist_ok=True)
            (W / rel).write_text(text, encoding='utf-8')
        chk_json('out/recon.json', {full2!r}, tol=0.0051)
        chk_cmd_json('python3 scripts/recon.py --bank _alt/bank.csv --ledger _alt/ledger.csv', {({**aout, **aext})!r}, tol=0.0051)
        """)
    s.turn("Add the probable-match figures to both out/recon.json and the output of scripts/recon.py: probable_matches (pairs as in out/probable.json), bank_only_unexplained and ledger_only_unexplained (the one-sided counts minus the probable pairs).",
           [s.g("t9")], files={"scripts/recon.py": RECON_V2, "out/recon.json": json.dumps(full2, indent=2) + "\n"},
           wrong_files={"scripts/recon.py": RECON_V2, "out/recon.json": json.dumps(out) + "\n"}, bump=True)
    s.turn("Add a '## Matching rules' section to README.md: say that rows match on ref with an exact cent amount, name the three kinds (amount_mismatch, bank_only, ledger_only), explain the probable-match rule (same amount, at most 3 days apart), and show how to run `python3 scripts/recon.py --bank ... --ledger ...`.",
           [sections("README.md", "Matching rules"), rx("README.md", "amount_mismatch"), rx("README.md", "bank_only"), rx("README.md", "ledger_only"), rx("README.md", r"(?i)3 days"), rx("README.md", r"scripts/recon\.py --bank")],
           files={"README.md": s.files["README.md"] + "\n## Matching rules\n\nRows match on `ref` with an exact amount in cents. Kinds: amount_mismatch, bank_only, ledger_only.\nA probable match is a bank-only and a ledger-only row with the same amount at most 3 days apart.\nRun `python3 scripts/recon.py --bank data/bank.csv --ledger data/ledger.csv`.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Matching rules\n\nSee code.\n"})
    return s
