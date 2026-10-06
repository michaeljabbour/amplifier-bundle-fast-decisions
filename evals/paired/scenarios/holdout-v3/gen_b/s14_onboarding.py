import re
from lib import Scn, exists, facts, numrx, rx, sections

TARGETS = [("help", None, "Show this help"), ("setup", 1, "Install dependencies and create the virtualenv"), ("migrate", 2, "Apply database migrations"), ("up", 3, "Start the local stack"),
           ("down", None, "Stop the local stack"), ("test", 4, "Run the unit tests"), ("lint", None, "Run the linters"), ("fmt", None, "Format the code"), ("build", None, "Build the container images"),
           ("clean", None, "Remove build artefacts"), ("seed", None, "Load demo data")]
ENVS = [("API_PORT", "8080", "Port the API listens on"), ("DATABASE_URL", "", "Database connection URL (required)"), ("REDIS_URL", "redis://localhost:6379/0", "Cache and queue URL"),
        ("LOG_LEVEL", "info", "Log verbosity"), ("SECRET_KEY", "", "Session signing key (required)"), ("WORKER_CONCURRENCY", "4", "Jobs processed in parallel"), ("SENTRY_DSN", "", "Error reporting DSN (optional)")]
SERVICES = [("api", "ghcr.io/acme/shop-api:2.3", "8080:8080"), ("worker", "ghcr.io/acme/shop-worker:2.3", None), ("db", "postgres:15", "5432:5432"), ("redis", "redis:7", "6379:6379"), ("web", "ghcr.io/acme/shop-web:1.9", "3000:80")]
SCRIPTS = [("backup.sh", "scripts/backup.sh <dest-dir>"), ("restore.sh", "scripts/restore.sh <archive>"), ("seed_demo.py", "python3 scripts/seed_demo.py [--count N]"), ("rotate_keys.sh", "scripts/rotate_keys.sh"), ("wait_for_db.sh", "scripts/wait_for_db.sh [timeout-seconds]")]
DIRS = [("api", "HTTP API service (FastAPI)."), ("worker", "Background job runner."), ("web", "Browser front end."), ("infra", "Docker and deployment manifests.")]


def makefile():
    lines = [".DEFAULT_GOAL := help", ".PHONY: " + " ".join(t[0] for t in TARGETS), ""]
    for t, n, d in TARGETS:
        lines.append(f"{t}: ## " + (f"[first-run {n}] " if n else "") + d)
        lines.append(f"\t@echo {t}")
    return "\n".join(lines) + "\n"


def envfile():
    return "".join(f"# {d}\n{k}={v}\n" for k, v, d in ENVS)


def compose():
    out = "services:\n"
    for n, img, port in SERVICES:
        out += f"  {n}:\n    image: {img}\n" + (f"    ports:\n      - \"{port}\"\n" if port else "")
    return out


def script_text(name, usage):
    return ("#!/usr/bin/env bash\n" if name.endswith(".sh") else "#!/usr/bin/env python3\n") + f"# Usage: {usage}\n# (internal notes below)\n" + ("echo ok\n" if name.endswith(".sh") else "print('ok')\n")


def tbl(head, rows):
    return "| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n" + "".join("| " + " | ".join(r) + " |\n" for r in rows) + "\n"


def sec(title, body):
    return f"## {title}\n\n{body}"


def targets_sec():
    return sec("Make targets", tbl(["target", "description"], [[f"`{t}`", d] for t, n, d in TARGETS]))


def env_sec():
    return sec("Environment variables", tbl(["variable", "default", "description"], [[f"`{k}`", f"`{v}`" if v else "-", d] for k, v, d in ENVS]))


def svc_sec():
    return sec("Services", tbl(["service", "image", "ports"], [[f"`{n}`", f"`{i}`", f"`{p}`" if p else "-"] for n, i, p in SERVICES]))


def scripts_sec():
    return sec("Scripts", tbl(["script", "usage"], [[f"`scripts/{n}`", f"`{u}`"] for n, u in SCRIPTS]))


def dirs_sec():
    return sec("Directory map", tbl(["directory", "purpose"], [[f"`{d}/`", p] for d, p in DIRS]))


def steps_sec():
    ft = sorted((n, t) for t, n, d in TARGETS if n)
    return sec("First run", "1. `cp .env.example .env`\n" + "".join(f"{i}. `make {t}`\n" for i, (n, t) in enumerate(ft, 2)) + "\n")


def build():
    s = Scn("onboarding-guide", "mixed", "docs", "markdown",
            "Write an onboarding guide for a repo from its Makefile, .env.example, docker-compose.yml, scripts and per-directory READMEs: exact tables for each, an ordered first-run procedure, consistency with the sources.",
            ["new self-authored repo skeleton; onboarding/CONTRIBUTING docs theme (cf. amplifier-agent docs tasks)"],
            protected=["Makefile", ".env.example", "docker-compose.yml"], long_gaps=[3, 7])
    s.file("Makefile", makefile())
    s.file(".env.example", envfile())
    s.file("docker-compose.yml", compose())
    for n, u in SCRIPTS:
        s.file(f"scripts/{n}", script_text(n, u))
    for d, p in DIRS:
        s.file(f"{d}/README.txt", p + "\nMore notes follow.\n")
    s.file("docs/.keep", "")
    s.file("README.md", "# shop\n\nA small web shop. See docs/onboarding.md (to be written) for how to get started.\n")
    noneref = [k for k, v, d in ENVS if not v]
    ntg = sum(1 for t in TARGETS)
    s.turn("How many targets in the Makefile have a `##` description comment, and which target is the default goal? Do not change any files.",
           [facts(all=[numrx(ntg), r"\bhelp\b"])], msg=f"ANSWER: {ntg} documented targets; default goal is help", wrong_msg=f"ANSWER: {ntg - 1} documented targets; default goal is setup", bump=True)

    def tfunc(name, rows_expr, header, under, want, unordered=False):
        cmpx = "sorted(got) == sorted({want!r})" if unordered else "got == {want!r}"
        s.func(name, f"""
        rows = md_rows('docs/onboarding.md', {under!r})
        need(rows and [c.lower() for c in rows[0]] == {header!r}, 'header under {under}: ' + str(rows[:1]))
        got = [[c.strip('` ') for c in r] for r in rows[1:]]
        need({cmpx.format(want=want)}, 'rows differ: ' + str([g for g in got if g not in {want!r}][:2]) + ' / want ' + str({want!r}[:2]))
        """)
    tfunc("t2", None, ["target", "description"], "make targets", [[t, d] for t, n, d in TARGETS])
    hdr = "# Onboarding\n\nWelcome to the shop codebase.\n\n"
    d2 = hdr + targets_sec()
    s.turn("Create docs/onboarding.md titled `# Onboarding` with a `## Make targets` section: a table (columns target, description) of every Makefile target in file order; the target name in backticks and its `##` description without any `[first-run N]` tag.",
           [s.g("t2")], files={"docs/onboarding.md": d2}, wrong_files={"docs/onboarding.md": d2.replace("| `up` | Start the local stack |", "| `up` | Start everything |")})
    s.turn("Which environment variables in .env.example have an empty value (no default)? Do not change any files.",
           [facts(all=noneref)], msg="ANSWER: " + ", ".join(noneref), wrong_msg="ANSWER: DATABASE_URL", bump=False)
    tfunc("t4", None, ["variable", "default", "description"], "environment variables", [[k, v if v else "-", d] for k, v, d in ENVS])
    d4 = d2 + env_sec()
    s.turn("Add a `## Environment variables` section with a table (columns variable, default, description): every variable from .env.example in order, the default in backticks (or `-` when empty, no backticks), and the comment line above it as the description.",
           [s.g("t4")], files={"docs/onboarding.md": d4}, wrong_files={"docs/onboarding.md": d4.replace("`8080`", "`80`")})
    tfunc("t5", None, ["service", "image", "ports"], "services", [[n, i, p or "-"] for n, i, p in SERVICES], unordered=True)
    d5 = d4 + svc_sec()
    s.turn("Add a `## Services` section with a table (columns service, image, ports) from docker-compose.yml: service and image in backticks, ports as `host:container` in backticks, or `-` for services that publish none.",
           [s.g("t5")], files={"docs/onboarding.md": d5}, wrong_files={"docs/onboarding.md": d5.replace("`3000:80`", "`3000:3000`")})
    tfunc("t6", None, ["script", "usage"], "^scripts$", [[f"scripts/{n}", u] for n, u in SCRIPTS], unordered=True)
    d6 = d5 + scripts_sec()
    s.turn("Add a `## Scripts` section with a table (columns script, usage) covering every file in scripts/: the path in backticks and the text after `Usage:` on the script's second line, in backticks.",
           [s.g("t6")], files={"docs/onboarding.md": d6}, wrong_files={"docs/onboarding.md": d6.replace("scripts/backup.sh <dest-dir>", "scripts/backup.sh")})
    tfunc("t7", None, ["directory", "purpose"], "directory map", [[f"{d}/", p] for d, p in DIRS], unordered=True)
    d7 = d6 + dirs_sec()
    s.turn("Add a `## Directory map` section with a table (columns directory, purpose) for every top-level directory that contains a README.txt: the directory with a trailing slash in backticks, and the first line of its README.txt.",
           [s.g("t7")], files={"docs/onboarding.md": d7}, wrong_files={"docs/onboarding.md": d7.replace("Background job runner.", "Jobs.")})
    ft = sorted((n, t) for t, n, d in TARGETS if n)
    want_steps = ["cp .env.example .env"] + [f"make {t}" for n, t in ft]
    s.func("t8", f"""
        txt = read('docs/onboarding.md')
        m = re.search(r'^## First run\\s*$(.*?)(?=^## |\\Z)', txt, re.M | re.S)
        need(m, 'missing ## First run')
        steps = re.findall(r'^(\\d+)\\.\\s+`([^`]+)`\\s*$', m.group(1), re.M)
        need([int(a) for a, _ in steps] == list(range(1, {len(want_steps)} + 1)), 'numbering: ' + str(steps))
        need([b for _, b in steps] == {want_steps!r}, 'steps: ' + str([b for _, b in steps]))
        """)
    d8 = d7 + steps_sec()
    s.turn("Add a `## First run` section: a numbered list that starts with copying .env.example to .env (`cp .env.example .env`) and then runs, in order, the Makefile targets tagged `[first-run N]` (N = their position), each item being one command in backticks.",
           [s.g("t8")], files={"docs/onboarding.md": d8}, wrong_files={"docs/onboarding.md": d8.replace("3. `make migrate`", "3. `make up`")})
    s.func("t9", f"""
        txt = read('docs/onboarding.md')
        heads = [l[3:].strip() for l in txt.splitlines() if l.startswith('## ')]
        need(heads == ['First run', 'Make targets', 'Environment variables', 'Services', 'Scripts', 'Directory map'], 'section order: ' + str(heads))
        """)
    d9 = hdr + steps_sec() + targets_sec() + env_sec() + svc_sec() + scripts_sec() + dirs_sec()
    s.turn("Reorder docs/onboarding.md so the sections appear as: First run, Make targets, Environment variables, Services, Scripts, Directory map. Do not change their content.",
           [s.g("t9")], files={"docs/onboarding.md": d9}, wrong_files={"docs/onboarding.md": d8})
    s.turn("Replace the placeholder sentence in README.md with a link to [docs/onboarding.md](docs/onboarding.md) and keep the `# shop` title.",
           [rx("README.md", r"^# shop\s*$"), rx("README.md", r"\]\(docs/onboarding\.md\)"), rx("README.md", r"to be written", absent=True)],
           files={"README.md": "# shop\n\nA small web shop. Start with [docs/onboarding.md](docs/onboarding.md).\n"}, wrong_files={"README.md": "# shop\n\nA small web shop. See docs/onboarding.md (to be written) for how to get started.\n"})
    return s
