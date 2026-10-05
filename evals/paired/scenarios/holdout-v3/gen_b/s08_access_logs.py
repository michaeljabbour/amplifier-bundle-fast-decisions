import json, math, random, re
from lib import Scn, csv_text, exists, facts, numrx, rx, sections

PATHS = ["/api/items", "/api/items/17", "/api/orders", "/api/orders/204", "/login", "/logout", "/static/app.js", "/static/app.css", "/health", "/search", "/api/users/me", "/checkout", "/cart", "/"]
MON = {"Mar": 3}
LINE = re.compile(r'^(\S+) \S+ \S+ \[(\d\d)/(\w{3})/(\d{4}):(\d\d):\d\d:\d\d [+-]\d{4}\] "(\w+) (\S+) HTTP/\d\.\d" (\d{3}) (\d+) (\d+\.\d+)$')


def make(seed, days, per_day, bad):
    R = random.Random(seed)
    ips = [f"10.{R.randint(0, 3)}.{R.randint(0, 255)}.{R.randint(1, 254)}" for _ in range(40)]
    files = {}
    badlist = list(bad)
    for d in range(days):
        lines = []
        for _ in range(per_day):
            p = R.choices(PATHS, [14, 5, 8, 4, 4, 2, 10, 5, 6, 6, 4, 3, 3, 2])[0]
            q = "?q=" + R.choice(["a", "tea", "mug"]) if p == "/search" else ("?page=%d" % R.randint(1, 4) if p == "/api/items" else "")
            st = R.choices([200, 200, 304, 301, 404, 403, 500, 502, 503], [60, 10, 10, 3, 8, 3, 3, 2, 1])[0]
            ms = R.lognormvariate(3.8, 0.8) * (3 if p.startswith("/api/orders") or p == "/checkout" else 1)
            lines.append(f'{R.choice(ips)} - - [{d + 1:02d}/Mar/2025:{R.randint(0, 23):02d}:{R.randint(0, 59):02d}:{R.randint(0, 59):02d} +0000] "{R.choice(["GET", "GET", "POST"]) if p != "/health" else "GET"} {p}{q} HTTP/1.1" {st} {R.randint(120, 90000)} {ms / 1000:.3f}')
        for _ in range(len(badlist) // days + (1 if d < len(badlist) % days else 0)):
            lines.insert(R.randint(0, len(lines)), badlist.pop())
        files[f"logs/access-2025-03-{d + 1:02d}.log"] = "\n".join(lines) + "\n"
    return files


BAD = ['10.0.0.9 - - [01/Mar/2025:10:00:00 +0000] "GET /api/items HTTP/1.1" 200', '10.0.0.7 - - [bad-date] "GET / HTTP/1.1" 200 5 0.010',
       '10.1.2.3 - - [02/Mar/2025:11:11:11 +0000] "GET /cart HTTP/1.1" abc 100 0.050', 'garbage line with no structure', '10.2.2.2 - - [03/Mar/2025:01:02:03 +0000] "GET /login HTTP/1.1" 200 100',
       '10.3.3.3 - - [01/Mar/2025:12:00:00 +0000] GET /health HTTP/1.1 200 10 0.001', '- - - [02/Mar/2025:09:09:09 +0000] "GET / HTTP/1.1" 200 12 0.002 extra']


def parse_all(files):
    good, nbad, total = [], 0, 0
    for name in sorted(files):
        for ln in files[name].splitlines():
            if not ln.strip():
                continue
            total += 1
            m = LINE.match(ln)
            if not m:
                nbad += 1
                continue
            ip, dd, mon, yy, hh, meth, tgt, st, by, sec = m.groups()
            good.append(dict(ip=ip, day=int(dd), hour=int(hh), method=meth, path=tgt.split("?")[0], status=int(st), bytes=int(by), sec=float(sec)))
    return good, nbad, total


def stats(good, nbad):
    ms = sorted(round(g["sec"] * 1000) for g in good)
    cls = {f"{c}xx": sum(1 for g in good if g["status"] // 100 == c) for c in (2, 3, 4, 5)}
    return {"requests": len(good), "malformed_lines": nbad, "unique_ips": len({g["ip"] for g in good}), "status_classes": cls,
            "bytes_total": sum(g["bytes"] for g in good), "p95_ms": ms[math.ceil(0.95 * len(ms)) - 1]}


def top_paths(good, k=10):
    by = {}
    for g in good:
        by.setdefault(g["path"], []).append(g)
    rows = [[p, len(v), round(sum(x["sec"] for x in v) / len(v) * 1000, 1), round(sum(1 for x in v if x["status"] >= 500) / len(v) * 100, 1)] for p, v in by.items()]
    return by, sorted(rows, key=lambda r: (-r[1], r[0]))[:k]


LOGSTATS = '''"""Access-log statistics: python3 scripts/logstats.py [--logs DIR] -> JSON on stdout."""
import argparse, glob, json, math, os, re

LINE = re.compile(r'^(\\S+) \\S+ \\S+ \\[(\\d\\d)/(\\w{3})/(\\d{4}):(\\d\\d):\\d\\d:\\d\\d [+-]\\d{4}\\] "(\\w+) (\\S+) HTTP/\\d\\.\\d" (\\d{3}) (\\d+) (\\d+\\.\\d+)$')


def stats(logs):
    ips, cls, ms, nbytes, bad, n = set(), {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}, [], 0, 0, 0
    for p in sorted(glob.glob(os.path.join(logs, "*.log"))):
        for ln in open(p, encoding="utf-8"):
            if not ln.strip():
                continue
            m = LINE.match(ln.rstrip("\\n"))
            if not m:
                bad += 1
                continue
            n += 1
            ips.add(m.group(1))
            cls[m.group(8)[0] + "xx"] += 1
            nbytes += int(m.group(9))
            ms.append(round(float(m.group(10)) * 1000))
    ms.sort()
    return {"requests": n, "malformed_lines": bad, "unique_ips": len(ips), "status_classes": cls, "bytes_total": nbytes, "p95_ms": ms[math.ceil(0.95 * len(ms)) - 1]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="logs")
    print(json.dumps(stats(ap.parse_args().logs), indent=2))
'''

TESTS = '''import json, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import logstats

GOOD = '10.0.0.1 - - [01/Mar/2025:10:00:00 +0000] "GET /a HTTP/1.1" 200 100 0.100\\n'


def run(lines):
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "x.log"), "w", encoding="utf-8") as f:
            f.write(lines)
        return logstats.stats(d)


class LogStatsTests(unittest.TestCase):
    def test_counts_one_request(self):
        self.assertEqual(run(GOOD)["requests"], 1)

    def test_malformed_line_is_counted_not_parsed(self):
        s = run(GOOD + "garbage\\n")
        self.assertEqual((s["requests"], s["malformed_lines"]), (1, 1))

    def test_blank_lines_ignored(self):
        self.assertEqual(run(GOOD + "\\n\\n")["malformed_lines"], 0)

    def test_status_classes(self):
        s = run(GOOD + GOOD.replace(" 200 ", " 503 "))
        self.assertEqual((s["status_classes"]["2xx"], s["status_classes"]["5xx"]), (1, 1))

    def test_bytes_total(self):
        self.assertEqual(run(GOOD * 3)["bytes_total"], 300)

    def test_p95_nearest_rank(self):
        lines = "".join(GOOD.replace("0.100", "0.%03d" % i) for i in range(1, 21))
        self.assertEqual(run(lines)["p95_ms"], 19)


if __name__ == "__main__":
    unittest.main()
'''


def build():
    s = Scn("access-log-stats", "mixed", "mixed", "python",
            "Three days of web access logs with malformed lines: totals, busiest hour, status classes, p95, top-paths CSV, a stats CLI that generalises, unit tests, docs.",
            ["log-analysis pattern from the amplifier-agent benchmark (nginx/apache log tasks); logs are new and generated"],
            protected=["logs/access-2025-03-01.log", "logs/access-2025-03-02.log", "logs/access-2025-03-03.log"])
    files = make(7808, 3, 220, BAD)
    for k, v in files.items():
        s.file(k, v)
    s.file("README.md", "# access-logs\n\nLog format (one request per line, files in `logs/`):\n\n`<ip> - - [<dd/Mon/yyyy:HH:MM:SS +0000>] \"<METHOD> <target> HTTP/1.1\" <status> <bytes> <seconds>`\n\nA line that does not match this format exactly is malformed. Blank lines are not lines.\n")
    good, nbad, total = parse_all(files)
    st = stats(good, nbad)
    by_hour = {}
    for g in good:
        by_hour[(g["day"], g["hour"])] = by_hour.get((g["day"], g["hour"]), 0) + 1
    bh = max(by_hour, key=lambda k: (by_hour[k], -k[0], -k[1]))
    assert sorted(by_hour.values())[-1] > sorted(by_hour.values())[-2]
    s.turn("How many non-blank lines are in logs/*.log in total, and how many of them are well-formed according to README.md? Do not change any files.",
           [facts(all=[numrx(total), numrx(len(good))])], msg=f"ANSWER: {total} lines, {len(good)} well-formed", wrong_msg=f"ANSWER: {total} lines, {total} well-formed", bump=True)
    err5 = st["status_classes"]["5xx"]
    s.turn("Among the well-formed requests, how many have a 5xx status, and which hour (date and hour of day) has the most requests and how many? Do not change any files.",
           [facts(all=[numrx(err5), rf"0?{bh[0]}/Mar|2025-03-0?{bh[0]}", r"(?<!\d)" + (f"{bh[1]:02d}" if bh[1] < 10 else str(bh[1])) + r"(?!\d)", numrx(by_hour[bh])])],
           msg=f"ANSWER: {err5} 5xx; busiest hour 2025-03-{bh[0]:02d} {bh[1]:02d}:00 with {by_hour[bh]} requests", wrong_msg=f"ANSWER: {err5} 5xx; busiest hour 2025-03-{bh[0]:02d} {bh[1]:02d}:00 with {by_hour[bh] - 4} requests", bump=True)
    s.func("t3", f"chk_json('out/stats.json', {st!r}, tol=0)")
    s.turn("Create out/stats.json from the well-formed requests: requests, malformed_lines, unique_ips, status_classes (object with 2xx, 3xx, 4xx, 5xx counts), bytes_total and p95_ms (95th percentile of request time in whole milliseconds, nearest-rank: sort the integer-rounded millisecond values and take the element at position ceil(0.95*n)).",
           [s.g("t3")], files={"out/stats.json": json.dumps(st, indent=2) + "\n"}, wrong_files={"out/stats.json": json.dumps({**st, "p95_ms": st["p95_ms"] + 7}) + "\n"}, bump=True)
    by, tp = top_paths(good)
    s.func("t4", f"""
        import csv
        need((W / 'out/top_paths.csv').exists(), 'missing out/top_paths.csv')
        rd = list(csv.DictReader(open('out/top_paths.csv', encoding='utf-8', newline='')))
        need(rd and list(rd[0].keys()) == ['path', 'requests', 'avg_ms', 'error_rate_pct'], 'header')
        got = [[r['path'], int(r['requests']), round(float(r['avg_ms']), 1), round(float(r['error_rate_pct']), 1)] for r in rd]
        need(got == {tp!r}, 'rows differ: ' + str(got[:3]))
        """)
    tcsv = csv_text(["path", "requests", "avg_ms", "error_rate_pct"], [[r[0], r[1], f"{r[2]:.1f}", f"{r[3]:.1f}"] for r in tp])
    s.turn("Write out/top_paths.csv (header path,requests,avg_ms,error_rate_pct) for the ten most requested paths: the path is the request target without its query string; avg_ms is the mean request time in ms to 1 decimal; error_rate_pct is the share of 5xx responses to 1 decimal. Sort by requests descending, ties by path.",
           [s.g("t4")], files={"out/top_paths.csv": tcsv}, wrong_files={"out/top_paths.csv": csv_text(["path", "requests", "avg_ms", "error_rate_pct"], [[r[0], r[1] + (1 if i == 0 else 0), f"{r[2]:.1f}", f"{r[3]:.1f}"] for i, r in enumerate(tp)])}, bump=True)
    cand = [(round(sum(x["sec"] for x in v) / len(v) * 1000, 1), p, len(v)) for p, v in by.items() if len(v) >= 20]
    slow = max(cand)
    assert sorted(cand)[-1][0] > sorted(cand)[-2][0]
    s.turn("Among paths with at least 20 well-formed requests, which has the highest average request time, and what is it in ms to 1 decimal? Do not change any files.",
           [facts(all=[r"(?<![\w/])" + slow[1].replace("/", r"\/") + r"(?![\w/])", numrx(slow[0], 1)])], msg=f"ANSWER: {slow[1]} at {slow[0]:.1f} ms", wrong_msg=f"ANSWER: {slow[1]} at {slow[0] + 3:.1f} ms", bump=True)
    alt = make(81, 2, 40, BAD[:3])
    ag, ab, _ = parse_all(alt)
    ast = stats(ag, ab)
    s.func("t6", f"""
        for rel, text in {({k.replace('logs/', '_alt/'): v for k, v in alt.items()})!r}.items():
            (W / rel).parent.mkdir(parents=True, exist_ok=True)
            (W / rel).write_text(text, encoding='utf-8')
        need((W / 'scripts/logstats.py').exists(), 'missing scripts/logstats.py')
        chk_cmd_json('python3 scripts/logstats.py --logs _alt', {ast!r}, tol=0)
        chk_cmd_json('python3 scripts/logstats.py', {st!r}, tol=0)
        """)
    s.turn("Add scripts/logstats.py [--logs DIR] (default logs): it reads every *.log in DIR and prints on stdout the same JSON as out/stats.json.",
           [s.g("t6")], files={"scripts/logstats.py": LOGSTATS}, wrong_files={"scripts/logstats.py": LOGSTATS.replace("ms[math.ceil(0.95 * len(ms)) - 1]", "ms[len(ms) // 2]")})
    s.func("t7", """
        rc, out, err = run('python3 -m unittest discover -s tests -v', timeout=120)
        need(rc == 0, 'unittest failed: ' + (out + err)[-300:])
        m = re.search(r'Ran (\\d+) tests?', out + err)
        need(m and int(m.group(1)) >= 5, 'need at least 5 tests: ' + str(m and m.group(0)))
        need(len(re.findall(r'^\\s*def test_', read('tests/test_logstats.py'), re.M)) >= 5, 'need >= 5 def test_ in tests/test_logstats.py')
        need('logstats' in read('tests/test_logstats.py'), 'tests must exercise logstats')
        """)
    s.turn("Add tests/test_logstats.py using the standard library unittest (at least 5 test methods, each name starting with test_) that exercise scripts/logstats.py, including a malformed line and the p95 rule. `python3 -m unittest discover -s tests` must pass.",
           [s.g("t7", timeout=120)], files={"tests/test_logstats.py": TESTS}, wrong_files={"tests/test_logstats.py": TESTS[:TESTS.index("    def test_blank")] + '\n\nif __name__ == "__main__":\n    unittest.main()\n'})
    s.turn("Add a '## Usage' section to README.md: how to run `python3 scripts/logstats.py --logs logs`, the JSON keys it prints (requests, malformed_lines, unique_ips, status_classes, bytes_total, p95_ms), and how to run the tests.",
           [sections("README.md", "Usage"), rx("README.md", r"scripts/logstats\.py --logs"), rx("README.md", "malformed_lines"), rx("README.md", "p95_ms"), rx("README.md", "status_classes"), rx("README.md", "unittest")],
           files={"README.md": s.files["README.md"] + "\n## Usage\n\n`python3 scripts/logstats.py --logs logs` prints JSON with requests, malformed_lines, unique_ips, status_classes, bytes_total and p95_ms.\nRun the tests with `python3 -m unittest discover -s tests`.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Usage\n\nRun the script.\n"})
    return s
