import re
from lib import Scn, exists, facts, numrx, rx, sections

SPEC = {
    "add": dict(help="Add a task", pos=[("title", "Task title")], opts=[("--priority", "int", "3", "choices=[1, 2, 3, 4, 5]", "Priority from 1 (high) to 5"), ("--due", "str", None, "", "Due date as YYYY-MM-DD"), ("--tag", "str", None, "action='append'", "Tag to attach (repeatable)")]),
    "list": dict(help="List tasks", pos=[], opts=[("--status", "str", "open", "choices=['open', 'done', 'all']", "Which tasks to show"), ("--tag", "str", None, "", "Only tasks with this tag"), ("--limit", "int", "20", "", "Maximum rows to print")]),
    "done": dict(help="Mark a task done", pos=[("id", "Task id")], opts=[]),
    "export": dict(help="Export tasks", pos=[], opts=[("--format", "str", "json", "choices=['json', 'csv']", "Output format"), ("--output", "str", "-", "", "File to write, - for stdout")]),
    "purge": dict(help="Delete finished tasks", pos=[], opts=[("--dry-run", "flag", None, "", "Only report what would be deleted")]),
    "stats": dict(help="Show task counts", pos=[], opts=[]),
}


def cli_code():
    lines = ['"""taskq command line."""', "import argparse, json, os, sys", "", "", "def path():", '    return os.path.join(os.environ.get("TASKQ_HOME", os.path.expanduser("~/.taskq")), "tasks.json")', "",
             "", "def load():", "    return json.load(open(path(), encoding='utf-8')) if os.path.exists(path()) else []", "", "", "def save(items):",
             "    os.makedirs(os.path.dirname(path()), exist_ok=True)", "    json.dump(items, open(path(), 'w', encoding='utf-8'))", "", "", "def build():",
             '    p = argparse.ArgumentParser(prog="taskq", description="Tiny task queue")', '    sub = p.add_subparsers(dest="cmd", required=True)']
    for c, d in SPEC.items():
        lines.append(f'    s = sub.add_parser("{c}", help="{d["help"]}")')
        for n, h in d["pos"]:
            lines.append(f'    s.add_argument("{n}"' + (", type=int" if n == "id" else "") + f', help="{h}")')
        for n, ty, df, extra, h in d["opts"]:
            if ty == "flag":
                lines.append(f'    s.add_argument("{n}", action="store_true", help="{h}")')
            else:
                a = f'    s.add_argument("{n}", ' + (f"type={ty}, " if ty == "int" else "")
                a += (f"default={df if ty == 'int' else repr(df)}, " if df is not None else "") + (extra + ", " if extra else "") + f'help="{h}")'
                lines.append(a)
    lines += ["    return p", "", "", "def main(argv=None):", "    a = build().parse_args(argv)", "    items = load()",
              '    if a.cmd == "add":', '        n = max([t["id"] for t in items] + [0]) + 1',
              '        items.append({"id": n, "title": a.title, "priority": a.priority, "due": a.due, "tags": a.tag or [], "done": False})', "        save(items)", '        print(f"added #{n}")',
              '    elif a.cmd == "list":', '        rows = [t for t in items if (a.status == "all" or t["done"] == (a.status == "done")) and (not a.tag or a.tag in t["tags"])]',
              '        for t in sorted(rows, key=lambda t: (t["priority"], t["id"]))[: a.limit]:', '            print(f"#{t[\'id\']} [P{t[\'priority\']}] {t[\'title\']}" + (f" (due {t[\'due\']})" if t["due"] else ""))',
              '    elif a.cmd == "done":', '        for t in items:', '            if t["id"] == a.id:', '                t["done"] = True', "                save(items)", '                print(f"done #{a.id}")', "                return 0",
              '        print(f"error: no task with id {a.id}", file=sys.stderr)', "        return 3",
              '    elif a.cmd == "export":', '        out = json.dumps(items) if a.format == "json" else "\\n".join(f"{t[\'id\']},{t[\'title\']}" for t in items)',
              '        if a.output == "-":', "            print(out)", "        else:", "            open(a.output, 'w', encoding='utf-8').write(out)",
              '    elif a.cmd == "purge":', '        gone = [t for t in items if t["done"]]', "        if a.dry_run:", '            print(f"would purge {len(gone)} tasks")', "        else:", '            save([t for t in items if not t["done"]])', '            print(f"purged {len(gone)} tasks")',
              '    elif a.cmd == "stats":', '        print(f"open: {sum(1 for t in items if not t[\'done\'])}")', '        print(f"done: {sum(1 for t in items if t[\'done\'])}")', "    return 0", "", "", 'if __name__ == "__main__":', "    sys.exit(main())", ""]
    return "\n".join(lines)


EXAMPLE = [("taskq add \"Write docs\" --priority 2 --due 2025-05-01", ["added #1"]), ("taskq add \"Fix bug\"", ["added #2"]), ("taskq list", ["#1 [P2] Write docs (due 2025-05-01)", "#2 [P3] Fix bug"]),
           ("taskq done 1", ["done #1"]), ("taskq stats", ["open: 1", "done: 1"]), ("taskq purge --dry-run", ["would purge 1 tasks"])]


def opt_rows(c):
    return [(n, ("`" + df + "`") if df is not None else "-" if ty != "flag" else "off", h) for n, ty, df, extra, h in SPEC[c]["opts"]]


def doc_skeleton():
    return "# taskq CLI\n\n## Commands\n\n" + "".join(f"### {c}\n\n{d['help']}\n\n" for c, d in SPEC.items())


def doc_options():
    out = "# taskq CLI\n\n## Commands\n\n"
    for c, d in SPEC.items():
        out += f"### {c}\n\n{d['help']}\n\n"
        if d["pos"]:
            out += "Arguments: " + ", ".join(f"`{n}` ({h.lower()})" for n, h in d["pos"]) + "\n\n"
        if d["opts"]:
            out += "| option | default | description |\n|---|---|---|\n" + "".join(f"| `{n}` | {df} | {h} |\n" for n, df, h in opt_rows(c)) + "\n"
    return out


def examples_block():
    return "## Examples\n\n```console\n" + "\n".join("$ " + c + "\n" + "\n".join(o) for c, o in EXAMPLE) + "\n```\n"


def build():
    s = Scn("cli-manual", "mixed", "docs", "python",
            "Document a small argparse CLI (taskq): command inventory, exact option/default tables, exit codes, runnable console examples whose output is executed, TOC anchors, a roff man page, and a code+docs change.",
            ["new self-authored CLI; docs-from-code theme (cf. amplifier-agent docs tasks)"],
            protected=["taskq/__init__.py", "taskq/__main__.py"], long_gaps=[4, 8])
    s.file("taskq/__init__.py", '"""taskq: a tiny task queue."""\n')
    s.file("taskq/__main__.py", "import sys\nfrom .cli import main\n\nsys.exit(main())\n")
    s.file("taskq/cli.py", cli_code())
    s.file("README.md", "# taskq\n\nA tiny task queue. Run it with `python3 -m taskq <command>`; data lives in `$TASKQ_HOME/tasks.json` (default `~/.taskq`).\n")
    nopts = {c: len(d["opts"]) + len(d["pos"]) for c, d in SPEC.items()}
    mx = max(nopts, key=lambda k: nopts[k])
    assert list(nopts.values()).count(nopts[mx]) == 1
    s.turn("Read taskq/cli.py. List the subcommands, and say which subcommand takes the most arguments and options in total (positional arguments plus options) and how many. Do not change any files.",
           [facts(all=[*(r"\b" + c + r"\b" for c in SPEC), r"\b" + mx + r"\b", numrx(nopts[mx])])], msg=f"ANSWER: commands {', '.join(SPEC)}; {mx} takes the most ({nopts[mx]})", wrong_msg=f"ANSWER: commands {', '.join(SPEC)}; list takes the most (5)", bump=False)
    s.func("t2", f"""
        heads = [re.sub(r'^#+\\s*', '', l).strip() for l in read('docs/cli.md').splitlines() if l.startswith('### ')]
        need(heads == {list(SPEC)!r}, 'command headings: ' + str(heads))
        for c, h in {({c: d['help'] for c, d in SPEC.items()})!r}.items():
            need(h in ' '.join(md_lines('docs/cli.md', '^' + c + '$')), 'description missing under ' + c)
        need(any(l.startswith('## Commands') for l in read('docs/cli.md').splitlines()), 'missing ## Commands')
        """)
    s.turn("Create docs/cli.md with a `# taskq CLI` title, a `## Commands` section and one `### <command>` heading per subcommand (in the order they are defined in taskq/cli.py). Under each heading write the command's help string from the code, verbatim, as the first line.",
           [s.g("t2")], files={"docs/cli.md": doc_skeleton()}, wrong_files={"docs/cli.md": doc_skeleton().replace("### purge", "### clean")})
    exp = {c: {n: df for n, df, h in opt_rows(c)} for c in SPEC if SPEC[c]["opts"]}
    s.func("t3", f"""
        for c, opts in {exp!r}.items():
            rows = md_rows('docs/cli.md', '^' + c + '$')
            need(rows, 'no option table under ' + c)
            got = {{r[0].strip('` '): r[1].strip() for r in rows[1:] if len(r) >= 3}}
            need(got == opts, f'{{c}} options {{got}} != {{opts}}')
        for c, d in {({c: [h for *_, h in SPEC[c]['opts']] for c in SPEC if SPEC[c]['opts']})!r}.items():
            body = ' '.join(md_lines('docs/cli.md', '^' + c + '$'))
            for h in d:
                need(h in body, 'description missing: ' + h)
        """)
    s.turn("Under each command that has options, add a table with columns option, default and description: one row per option written as in the code (e.g. `--priority`), the default value in backticks (`-` when there is none, `off` for flags that default to false), and the option's help text verbatim. Positional arguments go in a line starting `Arguments:` instead.",
           [s.g("t3")], files={"docs/cli.md": doc_options()}, wrong_files={"docs/cli.md": doc_options().replace("| `--limit` | `20` |", "| `--limit` | `10` |")})
    ch = [(n, c) for c, d in SPEC.items() for n, ty, df, extra, h in d["opts"] if "choices" in extra]
    s.turn("Which options restrict their value to a fixed set of choices, and what are the allowed values? Do not change any files.",
           [facts(all=[r"--priority", r"--status", r"--format", r"\b5\b", r"\bdone\b", r"\bcsv\b", r"\bopen\b"])], msg="ANSWER: --priority 1-5, --status open|done|all (list), --format json|csv (export)",
           wrong_msg="ANSWER: only --format json|csv", bump=False)
    s.func("t5", """
        rows = md_rows('docs/cli.md', 'exit codes')
        got = {r[0].strip('` '): r[1].lower() for r in rows[1:] if len(r) >= 2}
        need(set(got) == {'0', '2', '3'}, 'exit codes listed: ' + str(sorted(got)))
        need('success' in got['0'] or 'ok' in got['0'], 'code 0 meaning')
        need('usage' in got['2'] or 'argument' in got['2'], 'code 2 meaning')
        need('not found' in got['3'] or 'no task' in got['3'] or 'unknown' in got['3'], 'code 3 meaning')
        """)
    d5 = doc_options() + "## Exit codes\n\n| code | meaning |\n|---|---|\n| 0 | success |\n| 2 | usage error (bad arguments) |\n| 3 | task not found |\n"
    s.turn("Add a `## Exit codes` section to docs/cli.md: a table with columns code and meaning covering every exit status the program can return (0, 2 from argparse usage errors, and the one `main` returns for an unknown task id).",
           [s.g("t5")], files={"docs/cli.md": d5}, wrong_files={"docs/cli.md": doc_options() + "## Exit codes\n\n| code | meaning |\n|---|---|\n| 0 | success |\n| 1 | error |\n"})
    ex = examples_block()
    cmds = [(c, o) for c, o in EXAMPLE]
    s.func("t6", f"""
        import tempfile, os
        body = '\\n'.join(md_lines('docs/cli.md', 'examples'))
        m = re.search(r'```(?:console|shell|sh|bash)?\\n(.*?)```', body, re.S)
        need(m, 'no fenced example block under Examples')
        steps, cur = [], None
        for ln in m.group(1).splitlines():
            if ln.startswith('$ '):
                cur = [ln[2:], []]
                steps.append(cur)
            elif cur is not None and ln.strip():
                cur[1].append(ln.rstrip())
        need([c for c, _ in steps] == {[c for c, _ in cmds]!r}, 'example commands: ' + str([c for c, _ in steps]))
        home = tempfile.mkdtemp()
        env = dict(os.environ, TASKQ_HOME=home)
        import shlex
        for c, want in steps:
            argv = ['python3', '-m', 'taskq'] + shlex.split(c)[1:]
            p = subprocess.run(argv, cwd=W, capture_output=True, text=True, env=env, timeout=30)
            need(p.returncode == 0, c + ' failed: ' + p.stderr[-200:])
            need([l.rstrip() for l in p.stdout.splitlines()] == want, f'{{c}}: documented output {{want}} != real {{p.stdout.splitlines()}}')
        """)
    s.turn("Add a `## Examples` section with one fenced console block that shows this exact session, each command on a line starting `$ ` followed by the output the program really prints: add \"Write docs\" with --priority 2 and --due 2025-05-01, add \"Fix bug\", list, done 1, stats, purge --dry-run. Use `taskq` as the command name.",
           [s.g("t6")], files={"docs/cli.md": d5 + "\n" + ex}, wrong_files={"docs/cli.md": d5 + "\n" + ex.replace("#2 [P3] Fix bug", "#2 [P4] Fix bug")})
    s.turn("What does `done` print on stderr and return when the id does not exist, e.g. `done 99`? Do not change any files.",
           [facts(all=[r"error: no task with id 99", r"(?<!\d)3(?!\d)"])], msg="ANSWER: prints `error: no task with id 99` to stderr and returns exit code 3", wrong_msg="ANSWER: prints `task not found` and returns 1", bump=False)
    toc = "## Contents\n\n" + "".join(f"- [{c}](#{c})\n" for c in SPEC) + "\n"
    full = d5.replace("## Commands", toc + "## Commands", 1) + "\n" + ex
    s.func("t8", f"""
        txt = read('docs/cli.md')
        m = re.search(r'^##\\s+Contents\\s*\\n(.*?)(?=^#)', txt, re.M | re.S)
        need(m, 'no ## Contents section before the first other heading')
        links = re.findall(r'\\[([^\\]]+)\\]\\(#([^)]+)\\)', m.group(1))
        need([l[0] for l in links] == {list(SPEC)!r} and all(a == t for t, a in links), 'toc entries: ' + str(links))
        need(txt.index('## Contents') < txt.index('## Commands'), 'Contents must precede Commands')
        """)
    s.turn("Add a `## Contents` section above `## Commands` in docs/cli.md: a bullet list with one markdown link per command, `[<command>](#<anchor>)`, where the anchor is the heading's GitHub-style slug, in command order.",
           [s.g("t8")], files={"docs/cli.md": full}, wrong_files={"docs/cli.md": full.replace("(#list)", "(#listing)")})
    man = ".TH TASKQ 1\n.SH NAME\ntaskq \\- tiny task queue\n.SH SYNOPSIS\n.B taskq\n<command> [options]\n.SH COMMANDS\n" + "".join(f".TP\n.B {c}\n{d['help']}\n" for c, d in SPEC.items()) + ".SH OPTIONS\n" + "".join(f".TP\n.B {n}\n{h}\n" for c, d in SPEC.items() for n, ty, df, ex_, h in d["opts"]) + ".SH EXIT STATUS\n0 success, 2 usage error, 3 task not found.\n"
    s.func("t9", f"""
        t = read('docs/taskq.1')
        need(re.search(r'^\\.TH\\s+TASKQ\\s+1', t, re.M), 'missing .TH TASKQ 1')
        for sh in ['NAME', 'SYNOPSIS', 'COMMANDS', 'OPTIONS', 'EXIT STATUS']:
            need(re.search(r'^\\.SH\\s+' + sh + r'\\s*$', t, re.M), 'missing .SH ' + sh)
        for c in {list(SPEC)!r}:
            need(re.search(r'^\\.B\\s+' + c + r'\\s*$', t, re.M), 'command not listed: ' + c)
        for o in {sorted({n for d in SPEC.values() for n, *_ in d['opts']})!r}:
            need(re.search(r'^\\.B\\s+' + re.escape(o) + r'\\s*$', t, re.M), 'option not listed: ' + o)
        """)
    s.turn("Write a roff man page docs/taskq.1: `.TH TASKQ 1`, sections NAME, SYNOPSIS, COMMANDS, OPTIONS and EXIT STATUS (each as `.SH <NAME>`); under COMMANDS and OPTIONS use a `.TP` block per entry with the command or option name on a `.B` line and the description on the next line.",
           [s.g("t9")], files={"docs/taskq.1": man}, wrong_files={"docs/taskq.1": man.replace(".B --limit\n", ".B -n\n")})
    s.turn("Add a '## Documentation' section to README.md that links docs/cli.md and docs/taskq.1 and says the CLI reference was written from taskq/cli.py.",
           [sections("README.md", "Documentation"), rx("README.md", r"docs/cli\.md"), rx("README.md", r"docs/taskq\.1"), rx("README.md", r"taskq/cli\.py")],
           files={"README.md": s.files["README.md"] + "\n## Documentation\n\nSee [docs/cli.md](docs/cli.md) and the man page docs/taskq.1; both were written from taskq/cli.py.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Documentation\n\nSee the docs.\n"})
    return s
