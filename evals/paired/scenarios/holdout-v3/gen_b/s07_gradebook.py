import json, random
from lib import Scn, csv_text, facts, numrx, rx, sections


def secrx(sec, n):
    """`A: 10`, `10 in A` or `10 students each in sections A, B, and C`."""
    return (r"(?<![\d.])" + sec + r"\D{0,6}" + numrx(n) + "|" + numrx(n) + r"\D{0,8}\b" + sec + r"\b|" + numrx(n) + r"\D{0,30}\beach\b\D{0,60}\b" + sec + r"\b")

W8 = {"homework": 0.4, "exams": 0.5, "participation": 0.1}
CATS = {"homework": [f"hw{i}" for i in range(1, 9)], "exams": ["ex1", "ex2"], "participation": ["pt1", "pt2", "pt3"]}
MAXP = {**{f"hw{i}": 10 + (i % 3) * 5 for i in range(1, 9)}, "ex1": 100, "ex2": 100, "pt1": 5, "pt2": 5, "pt3": 5}


def make(seed, n, sections_=("A", "B", "C")):
    R = random.Random(seed)
    students, scores, excused = [], [], []
    first = ["Ana", "Bo", "Cy", "Dee", "Eli", "Fay", "Gus", "Hal", "Ivy", "Jon", "Kai", "Lea", "Max", "Nia", "Oto"]
    for i in range(n):
        students.append([f"S{100 + i}", f"{R.choice(first)} {R.choice(['Reed', 'Diaz', 'Okafor', 'Lind', 'Park', 'Moss'])}", sections_[i % len(sections_)]])
        base = R.uniform(0.5, 0.97)
        for cat, names in CATS.items():
            for a in names:
                if R.random() < 0.04:
                    continue
                v = max(0, min(MAXP[a], round(MAXP[a] * (base + R.uniform(-0.15, 0.1)))))
                scores.append([students[-1][0], a, v])
    for _ in range(max(3, n // 3)):
        s_, a = R.choice(students)[0], R.choice(CATS["homework"])
        excused.append([s_, a])
    excused = sorted({tuple(e) for e in excused})
    return students, scores, [list(e) for e in excused]


def compute(students, scores, excused=None):
    sc = {(s, a): v for s, a, v in scores}
    ex = {tuple(e) for e in (excused or [])}
    out = []
    for sid, name, sec in students:
        cat = {}
        for c, names in CATS.items():
            pcts = [sc.get((sid, a), 0) / MAXP[a] * 100 for a in names if (sid, a) not in ex]
            if c == "homework" and len(pcts) > 1:
                pcts.remove(min(pcts))
            cat[c] = sum(pcts) / len(pcts)
        final = round(sum(W8[c] * cat[c] for c in CATS), 2)
        letter = "A" if final >= 90 else "B" if final >= 80 else "C" if final >= 70 else "D" if final >= 60 else "F"
        out.append([sid, round(cat["homework"], 2), round(cat["exams"], 2), round(cat["participation"], 2), final, letter])
    out.sort(key=lambda r: (-r[4], r[0]))
    return out


GRADE = '''"""Gradebook CLI: python3 scripts/grade.py [--data-dir DIR] -> JSON {student_id: {"final": x, "letter": L}} on stdout."""
import argparse, csv, json, os

W = {"homework": 0.4, "exams": 0.5, "participation": 0.1}
CATS = {"homework": ["hw%d" % i for i in range(1, 9)], "exams": ["ex1", "ex2"], "participation": ["pt1", "pt2", "pt3"]}


def rows(d, n):
    p = os.path.join(d, n)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def grade(d):
    mx = {r["assignment"]: float(r["max"]) for r in rows(d, "assignments.csv")}
    sc = {(r["student_id"], r["assignment"]): float(r["score"]) for r in rows(d, "scores.csv")}
    ex = {(r["student_id"], r["assignment"]) for r in rows(d, "excused.csv")}
    out = {}
    for s in rows(d, "students.csv"):
        sid, cat = s["id"], {}
        for c, names in CATS.items():
            pcts = [sc.get((sid, a), 0) / mx[a] * 100 for a in names if (sid, a) not in ex]
            if c == "homework" and len(pcts) > 1:
                pcts.remove(min(pcts))
            cat[c] = sum(pcts) / len(pcts)
        final = round(sum(W[c] * cat[c] for c in CATS), 2)
        out[sid] = {"final": final, "letter": "A" if final >= 90 else "B" if final >= 80 else "C" if final >= 70 else "D" if final >= 60 else "F"}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    print(json.dumps(grade(ap.parse_args().data_dir), indent=2))
'''


def files(students, scores, excused=None):
    f = {"data/students.csv": csv_text(["id", "name", "section"], students), "data/scores.csv": csv_text(["student_id", "assignment", "score"], scores),
         "data/assignments.csv": csv_text(["assignment", "category", "max"], [[a, c, MAXP[a]] for c, names in CATS.items() for a in names])}
    if excused is not None:
        f["data/excused.csv"] = csv_text(["student_id", "assignment"], excused)
    return f


def near_boundary(rows):
    return any(abs(r[4] - t) < 0.03 for r in rows for t in (60, 70, 80, 90))


def build():
    s = Scn("gradebook", "mixed", "mixed", "python",
            "Course gradebook CSVs: weighted category averages with drop-lowest and zero-for-missing, letter grades, distribution reports, an excused-assignment rule change, a CLI that generalises, docs.",
            ["new self-authored gradebook; weighted-report pattern similar to the amplifier-agent data-question benchmark tasks"],
            protected=["data/students.csv", "data/scores.csv", "data/assignments.csv", "data/excused.csv"])
    seed = 7707
    while True:
        students, scores, excused = make(seed, 30)
        base, rev = compute(students, scores), compute(students, scores, excused)
        ch = sum(1 for b, r in zip(sorted(base), sorted(rev)) if b[5] != r[5])
        if not near_boundary(base) and not near_boundary(rev) and 3 <= ch <= 8:
            break
        seed += 1
    for k, v in files(students, scores, excused).items():
        s.file(k, v)
    s.file("README.md", "# gradebook\n\nWeights: homework 40%, exams 50%, participation 10%. Each score is a percentage of the assignment's max (data/assignments.csv). A missing score row counts as 0. For homework the lowest percentage per student is dropped.\nLetter: A >= 90, B >= 80, C >= 70, D >= 60, otherwise F, using the final grade rounded to 2 decimals.\n")
    nsec = {}
    for st in students:
        nsec[st[2]] = nsec.get(st[2], 0) + 1
    ex1 = [v / MAXP["ex1"] * 100 for (sid, a, v) in scores if a == "ex1"]
    ex1m = round(sum(ex1) / len(ex1), 2)
    s.turn("How many students are in each section of data/students.csv, and how many rows does data/scores.csv have (excluding the header)? Do not change any files.",
           [facts(all=[secrx("A", nsec["A"]), secrx("B", nsec["B"]), secrx("C", nsec["C"]), numrx(len(scores))])],
           msg=f"ANSWER: A {nsec['A']}, B {nsec['B']}, C {nsec['C']}; {len(scores)} score rows", wrong_msg=f"ANSWER: A {nsec['A'] + 1}, B {nsec['B']}, C {nsec['C']}; {len(scores)} score rows", bump=True)
    s.turn("What is the class mean of ex1 as a percentage of its max, over the students who have an ex1 score row, to 2 decimals? Do not change any files.",
           [facts(all=[numrx(ex1m, 2)])], msg=f"ANSWER: {ex1m:.2f}", wrong_msg=f"ANSWER: {ex1m + 1.01:.2f}", bump=True)
    exp3 = {r[0]: {"final": r[4], "letter": r[5]} for r in base}
    s.func("t3", f"""
        import csv
        need((W / 'out/final.csv').exists(), 'missing out/final.csv')
        rd = list(csv.DictReader(open('out/final.csv', encoding='utf-8', newline='')))
        need(rd and list(rd[0].keys()) == ['id', 'homework_avg', 'exams_avg', 'participation_avg', 'final', 'letter'], 'header ' + str(rd and list(rd[0])))
        got = [[r['id'], round(float(r['homework_avg']), 2), round(float(r['exams_avg']), 2), round(float(r['participation_avg']), 2), round(float(r['final']), 2), r['letter']] for r in rd]
        want = {base!r}
        need([g[0] for g in got] == [w[0] for w in want], 'order/ids differ: ' + str([g[0] for g in got][:4]))
        for g, w in zip(got, want):
            need(all(abs(a - b) <= 0.011 for a, b in zip(g[1:5], w[1:5])) and g[5] == w[5], f'{{g}} != {{w}}')
        """)

    def fcsv(rows):
        return csv_text(["id", "homework_avg", "exams_avg", "participation_avg", "final", "letter"], [[r[0], f"{r[1]:.2f}", f"{r[2]:.2f}", f"{r[3]:.2f}", f"{r[4]:.2f}", r[5]] for r in rows])
    wr = [r[:] for r in base]
    wr[0][4] += 1.0
    s.turn("Create out/final.csv (header id,homework_avg,exams_avg,participation_avg,final,letter) with one row per student following the rules in README.md. Category averages and final have 2 decimals; sort by final descending, ties by id. Ignore data/excused.csv for now.",
           [s.g("t3")], files={"out/final.csv": fcsv(base)}, wrong_files={"out/final.csv": fcsv(wr)}, bump=True)
    dist = {L: sum(1 for r in base if r[5] == L) for L in "ABCDF"}
    s.turn("How many students got each letter (A, B, C, D, F) in out/final.csv? Do not change any files.",
           [facts(all=[rf"(?<![A-Za-z]){L}\D{{0,6}}" + numrx(dist[L]) for L in "ABCDF"])], msg="ANSWER: " + ", ".join(f"{L} {dist[L]}" for L in "ABCDF"),
           wrong_msg="ANSWER: " + ", ".join(f"{L} {dist[L] + (1 if L == 'B' else 0)}" for L in "ABCDF"), bump=True)
    top3 = base[:3]
    s.func("t5", f"""
        chk_table('report.md', 'distribution', {dist!r})
        rows = md_rows('report.md', 'top')
        got = [(r[0], num(r[1])) for r in rows if len(r) >= 2 and r[0].startswith('S') and num(r[1]) is not None]
        need([g[0] for g in got[:3]] == {[r[0] for r in top3]!r} and all(abs(g[1] - w) <= 0.011 for g, w in zip(got, {[r[4] for r in top3]!r})), 'top 3 table: ' + str(got[:3]))
        """)
    rep = "# Grade report\n\n## Letter distribution\n\n| letter | students |\n|---|---|\n" + "".join(f"| {L} | {dist[L]} |\n" for L in "ABCDF") + "\n## Top students\n\n| id | final |\n|---|---|\n" + "".join(f"| {r[0]} | {r[4]:.2f} |\n" for r in top3) + "\n## Notes\n\nMissing scores count as zero.\n"
    s.turn("Write report.md with level-2 sections Letter distribution, Top students and Notes. Letter distribution is a table (letter, students); Top students is a table of the three highest finals (id, final), best first.",
           [sections("report.md", "Letter distribution", "Top students", "Notes"), s.g("t5")], files={"report.md": rep},
           wrong_files={"report.md": rep.replace(f"| B | {dist['B']} |", f"| B | {dist['B'] + 1} |")}, bump=True)
    changed = [[b[0], b[5], r[5]] for b in base for r in rev if b[0] == r[0] and b[5] != r[5]]
    changed.sort()
    assert 2 <= len(changed) <= 12, len(changed)
    s.func("t6", f"""
        import csv
        rd = list(csv.DictReader(open('out/final.csv', encoding='utf-8', newline='')))
        got = [[r['id'], round(float(r['homework_avg']), 2), round(float(r['exams_avg']), 2), round(float(r['participation_avg']), 2), round(float(r['final']), 2), r['letter']] for r in rd]
        want = {rev!r}
        need([g[0] for g in got] == [w[0] for w in want], 'order/ids differ')
        for g, w in zip(got, want):
            need(all(abs(a - b) <= 0.011 for a, b in zip(g[1:5], w[1:5])) and g[5] == w[5], f'{{g}} != {{w}}')
        """)
    s.turn("data/excused.csv lists (student_id, assignment) pairs that are excused: an excused assignment is left out of that student's category average entirely (it is neither a zero nor a score; the homework drop-lowest applies to what remains). Rewrite out/final.csv with the same columns applying this rule.",
           [s.g("t6")], files={"out/final.csv": fcsv(rev)}, wrong_files={"out/final.csv": fcsv(base)}, bump=True)
    s.func("t7", f"""
        import csv
        need((W / 'out/letter_changes.csv').exists(), 'missing out/letter_changes.csv')
        rd = list(csv.reader(open('out/letter_changes.csv', encoding='utf-8', newline='')))
        need(rd[0] == ['id', 'before', 'after'], 'header ' + str(rd[0]))
        need(sorted(rd[1:]) == {changed!r}, 'changes differ: ' + str(rd[1:6]))
        """)
    s.turn("Compare the letters from before and after applying excused assignments. Write out/letter_changes.csv (header id,before,after) with one row per student whose letter changed, sorted by id. Keep out/final.csv as is.",
           [s.g("t7")], files={"out/letter_changes.csv": csv_text(["id", "before", "after"], changed)}, wrong_files={"out/letter_changes.csv": csv_text(["id", "before", "after"], changed[:-1])})
    ast, asc, aex = make(41, 9, ("X", "Y"))
    aout = {r[0]: {"final": r[4], "letter": r[5]} for r in compute(ast, asc, aex)}
    full = {r[0]: {"final": r[4], "letter": r[5]} for r in rev}
    altfiles = {f"_alt/{k.split('/')[1]}": v for k, v in files(ast, asc, aex).items()}
    s.func("t8", f"""
        for rel, text in {altfiles!r}.items():
            (W / rel).parent.mkdir(parents=True, exist_ok=True)
            (W / rel).write_text(text, encoding='utf-8')
        need((W / 'scripts/grade.py').exists(), 'missing scripts/grade.py')
        chk_cmd_json('python3 scripts/grade.py --data-dir _alt', {aout!r}, tol=0.011)
        chk_cmd_json('python3 scripts/grade.py', {full!r}, tol=0.011)
        """)
    s.turn("Add scripts/grade.py [--data-dir DIR] (default data): it applies the full rules, including excused.csv when that file exists in DIR, and prints JSON {student_id: {\"final\": number, \"letter\": letter}} on stdout.",
           [s.g("t8")], files={"scripts/grade.py": GRADE}, wrong_files={"scripts/grade.py": GRADE.replace("pcts.remove(min(pcts))", "pass")})
    s.turn("Add a '## Rules' section to README.md that restates the excused-assignment rule, names data/excused.csv, and shows how to run `python3 scripts/grade.py --data-dir data`.",
           [sections("README.md", "Rules"), rx("README.md", r"excused\.csv"), rx("README.md", r"(?i)excused"), rx("README.md", r"scripts/grade\.py --data-dir")],
           files={"README.md": s.files["README.md"] + "\n## Rules\n\nAn excused assignment listed in `data/excused.csv` is left out of the category average entirely.\nRun `python3 scripts/grade.py --data-dir data` for the JSON result.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Rules\n\nSee the code.\n"})
    return s
