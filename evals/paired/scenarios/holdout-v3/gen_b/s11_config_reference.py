import json
from lib import Scn, exists, facts, numrx, rx, sections

# section -> list of (key, type, default, required, description, enum, env)
SCHEMA = {
    "server": ("HTTP listener settings", [
        ("host", "string", "0.0.0.0", False, "Interface to bind", None, "APP_HOST"),
        ("port", "integer", 8080, False, "TCP port", None, "APP_PORT"),
        ("workers", "integer", 4, False, "Worker processes", None, None),
        ("request_timeout_s", "number", 30.0, False, "Per-request timeout in seconds", None, None),
        ("tls_enabled", "boolean", False, False, "Terminate TLS in the app", None, None)]),
    "database": ("Primary database", [
        ("url", "string", None, True, "Connection URL", None, "APP_DB_URL"),
        ("pool_size", "integer", 10, False, "Connections kept open", None, None),
        ("pool_timeout_s", "number", 5.5, False, "Seconds to wait for a connection", None, None),
        ("echo", "boolean", False, False, "Log every statement", None, None)]),
    "cache": ("Response cache", [
        ("backend", "string", "memory", False, "Cache implementation", ["memory", "redis", "memcached"], "APP_CACHE_BACKEND"),
        ("ttl_s", "integer", 300, False, "Entry lifetime in seconds", None, None),
        ("max_items", "integer", 5000, False, "Maximum entries for the memory backend", None, None),
        ("redis_url", "string", None, False, "Redis URL when backend is redis", None, "APP_REDIS_URL")]),
    "logging": ("Log output", [
        ("level", "string", "info", False, "Minimum level", ["debug", "info", "warning", "error"], "APP_LOG_LEVEL"),
        ("format", "string", "text", False, "Line format", ["text", "json"], None),
        ("file", "string", None, False, "Log file path; stdout when unset", None, None),
        ("rotate_mb", "integer", 50, False, "Rotate after this many MB", None, None)]),
    "auth": ("Sessions and cookies", [
        ("secret", "string", None, True, "Session signing secret", None, "APP_SECRET"),
        ("session_ttl_s", "integer", 3600, False, "Session lifetime in seconds", None, None),
        ("cookie_name", "string", "sid", False, "Session cookie name", None, None),
        ("secure_cookies", "boolean", True, False, "Send cookies over HTTPS only", None, None)]),
    "features": ("Feature flags", [
        ("dark_mode", "boolean", False, False, "Enable the dark theme", None, None),
        ("export_csv", "boolean", True, False, "Allow CSV export", None, None),
        ("signup_open", "boolean", True, False, "Allow self-service signup", None, "APP_SIGNUP_OPEN")]),
}
NEWKEY = ("beta_search", "boolean", False, False, "Enable the beta search backend", None, None)


def schema_json(schema):
    props = {}
    for sec, (desc, keys) in schema.items():
        p = {}
        for k, ty, df, req, d, en, env in keys:
            e = {"type": ty, "description": d}
            if df is not None:
                e["default"] = df
            if en:
                e["enum"] = en
            if env:
                e["x-env"] = env
            p[k] = e
        props[sec] = {"type": "object", "description": desc, "properties": p, "required": [k[0] for k in keys if k[3]]}
    return json.dumps({"$schema": "http://json-schema.org/draft-07/schema#", "title": "app config", "type": "object", "properties": props, "required": [s for s, (_, ks) in schema.items() if any(k[3] for k in ks)]}, indent=2) + "\n"


def lit(df):
    return "-" if df is None else json.dumps(df)


def cell(df):
    return "-" if df is None else f"`{json.dumps(df)}`"


def skeleton(schema):
    return "# Configuration\n\n" + "".join(f"## {sec}\n\n{desc}\n\n" for sec, (desc, _) in schema.items())


def tables(schema, extra=""):
    out = "# Configuration\n\n"
    for sec, (desc, keys) in schema.items():
        out += f"## {sec}\n\n{desc}\n\n| key | type | default | required |\n|---|---|---|---|\n" + "".join(f"| `{k[0]}` | {k[1]} | {cell(k[2])} | {'yes' if k[3] else 'no'} |\n" for k in keys) + "\n"
    return out


def enums(schema):
    out = ""
    for sec, (_, keys) in schema.items():
        ek = [k for k in keys if k[5]]
        if ek:
            out += f"### Allowed values ({sec})\n\n" + "".join(f"- `{k[0]}`: " + " | ".join(k[5]) + "\n" for k in ek) + "\n"
    return out


def with_enums(schema):
    out = "# Configuration\n\n"
    for sec, (desc, keys) in schema.items():
        out += f"## {sec}\n\n{desc}\n\n| key | type | default | required |\n|---|---|---|---|\n" + "".join(f"| `{k[0]}` | {k[1]} | {cell(k[2])} | {'yes' if k[3] else 'no'} |\n" for k in keys) + "\n"
        ek = [k for k in keys if k[5]]
        if ek:
            out += "### Allowed values\n\n" + "".join(f"- `{k[0]}`: " + " | ".join(k[5]) + "\n" for k in ek) + "\n"
    return out


def env_section(schema):
    return "## Environment overrides\n\n| variable | key |\n|---|---|\n" + "".join(f"| `{k[6]}` | `{sec}.{k[0]}` |\n" for sec, (_, keys) in schema.items() for k in keys if k[6]) + "\n"


def example(schema):
    ex = {}
    for sec, (_, keys) in schema.items():
        r = {k[0]: ("postgres://localhost/app" if k[0] == "url" else "change-me") for k in keys if k[3]}
        if r:
            ex[sec] = r
    return ex


def example_block(schema):
    return "## Example\n\nMinimal config (only required keys):\n\n```json\n" + json.dumps(example(schema), indent=2) + "\n```\n\n"


CHECK = '''"""Docs vs schema: python3 scripts/check_config_docs.py [--schema FILE] [--docs FILE].
Prints `UNDOCUMENTED: <section>.<key>` for schema keys missing from the docs tables and `UNKNOWN: <section>.<key>` for documented keys the schema does not have (sorted); exit 1 if any, else `ok`, exit 0."""
import argparse, json, re

ap = argparse.ArgumentParser()
ap.add_argument("--schema", default="schema/app.schema.json")
ap.add_argument("--docs", default="docs/configuration.md")
a = ap.parse_args()
schema = json.load(open(a.schema, encoding="utf-8"))["properties"]
want = {f"{s}.{k}" for s, v in schema.items() for k in v["properties"]}
have, sec = set(), None
for ln in open(a.docs, encoding="utf-8").read().splitlines():
    m = re.match(r"^## (.*?)\\s*$", ln)
    if m:
        sec = m.group(1)
        continue
    m = re.match(r"^\\|\\s*`([\\w]+)`\\s*\\|", ln)
    if m and sec in schema:
        have.add(f"{sec}.{m.group(1)}")
out = [f"UNDOCUMENTED: {x}" for x in sorted(want - have)] + [f"UNKNOWN: {x}" for x in sorted(have - want)]
print("\\n".join(out) if out else "ok")
raise SystemExit(1 if out else 0)
'''


def build():
    s = Scn("config-reference", "mixed", "docs", "json",
            "Write a configuration reference from a JSON schema: section/key inventory, exact type/default/required tables, enum lists, env-var table, a validated example block, a schema change that needs code and docs, a docs-vs-schema checker, rename notes.",
            ["new self-authored schema; config-documentation theme (cf. amplifier-agent docs tasks)"],
            protected=["schema/CHANGES.txt", "config/README.txt"])
    s.file("schema/app.schema.json", schema_json(SCHEMA))
    s.file("schema/CHANGES.txt", "v1 -> v2 renames (old key -> new key):\nserver.timeout -> server.request_timeout_s\ndatabase.max_conn -> database.pool_size\ncache.size -> cache.max_items\nlogging.rotate -> logging.rotate_mb\nremoved: server.debug\n")
    s.file("config/README.txt", "Config files are JSON documents validated against schema/app.schema.json.\n")
    s.file("README.md", "# app\n\nConfiguration is described by `schema/app.schema.json`; docs belong in `docs/`.\n")
    nsec = len(SCHEMA)
    nkeys = sum(len(v[1]) for v in SCHEMA.values())
    nreq = sum(1 for v in SCHEMA.values() for k in v[1] if k[3])
    s.turn("Read schema/app.schema.json. How many top-level sections does it define, how many keys in total across all sections, and how many of those keys are required (listed in a section's `required` array)? Do not change any files.",
           [facts(all=[r"sections?\D{0,12}" + numrx(nsec) + "|" + numrx(nsec) + r"\D{0,12}sections?", numrx(nkeys), numrx(nreq)])], msg=f"ANSWER: {nsec} sections, {nkeys} keys, {nreq} required", wrong_msg=f"ANSWER: {nsec} sections, {nkeys + 2} keys, {nreq} required", bump=True)
    s.func("t2", f"""
        got = [(re.sub(r'^##\\s*', '', l).strip()) for l in read('docs/configuration.md').splitlines() if l.startswith('## ')]
        need(got == {list(SCHEMA)!r}, 'sections: ' + str(got))
        for sec, d in {({k: v[0] for k, v in SCHEMA.items()})!r}.items():
            need(d in ' '.join(md_lines('docs/configuration.md', '^' + sec + '$')), 'description missing for ' + sec)
        need(read('docs/configuration.md').lstrip().startswith('# Configuration'), 'title')
        """)
    s.turn("Create docs/configuration.md with the title `# Configuration` and one `## <section>` heading per schema section, in schema order, each followed by the section's description from the schema.",
           [s.g("t2")], files={"docs/configuration.md": skeleton(SCHEMA)}, wrong_files={"docs/configuration.md": skeleton(SCHEMA).replace("## auth", "## security")})
    exp = {sec: {k[0]: [k[1], lit(k[2]), "yes" if k[3] else "no"] for k in v[1]} for sec, v in SCHEMA.items()}
    s.func("t3", f"""
        for sec, keys in {exp!r}.items():
            rows = md_rows('docs/configuration.md', '^' + sec + '$')
            need(rows and [c.lower() for c in rows[0][:4]] == ['key', 'type', 'default', 'required'], 'table header under ' + sec + ': ' + str(rows[:1]))
            got = {{r[0].strip('` '): [r[1], r[2].strip('` '), r[3].lower()] for r in rows[1:] if len(r) >= 4}}
            need(got == keys, f'{{sec}}: {{got}} != {{keys}}')
        """)
    s.turn("Under each section add a table with columns key, type, default, required. type is the JSON schema type; default is the schema default as a JSON literal in backticks (strings keep their double quotes, booleans are true/false) or `-` in the cell when the schema has none (no backticks around the dash); required is yes or no.",
           [s.g("t3")], files={"docs/configuration.md": tables(SCHEMA)}, wrong_files={"docs/configuration.md": tables(SCHEMA).replace("| `port` | integer | `8080` |", "| `port` | integer | `80` |")})
    ek = [(sec, k[0], k[5]) for sec, v in SCHEMA.items() for k in v[1] if k[5]]
    s.turn("Which schema keys restrict their value with an `enum`, and what are the allowed values? Do not change any files.",
           [facts(all=[r"\bbackend\b", r"\blevel\b", r"\bformat\b", r"memcached", r"warning", r"\bjson\b"])], msg="ANSWER: cache.backend memory|redis|memcached; logging.level debug|info|warning|error; logging.format text|json",
           wrong_msg="ANSWER: only logging.level has an enum", bump=False)
    s.func("t5", f"""
        for sec, items in {({sec: {k[0]: k[5] for k in v[1] if k[5]} for sec, v in SCHEMA.items() if any(k[5] for k in v[1])})!r}.items():
            body = md_lines('docs/configuration.md', '^' + sec + '$')
            idx = [i for i, l in enumerate(body) if False]
            txt = '\\n'.join(body)
            need(re.search(r'^#{{3,4}}\\s*Allowed values', read('docs/configuration.md'), re.M), 'missing Allowed values heading')
            got = {{}}
            sub = md_lines('docs/configuration.md', '^' + sec + '$')
            full = read('docs/configuration.md')
            seg = re.search(r'^## ' + sec + r'\\s*$(.*?)(?=^## |\\Z)', full, re.M | re.S).group(1)
            for m in re.finditer(r'^- `(\\w+)`:\\s*(.*)$', seg, re.M):
                got[m.group(1)] = [x.strip() for x in m.group(2).split('|')]
            need(got == items, f'{{sec}} enums {{got}} != {{items}}')
        for sec in {[sec for sec, v in SCHEMA.items() if not any(k[5] for k in v[1])]!r}:
            full = read('docs/configuration.md')
            seg = re.search(r'^## ' + sec + r'\\s*$(.*?)(?=^## |\\Z)', full, re.M | re.S).group(1)
            need('Allowed values' not in seg, sec + ' has no enums')
        """)
    s.turn("For sections that have enum-constrained keys add a `### Allowed values` subsection (after the table) with one bullet per such key: `- `key`: a | b | c` using the enum order from the schema. Sections without enums get no such subsection.",
           [s.g("t5")], files={"docs/configuration.md": with_enums(SCHEMA)}, wrong_files={"docs/configuration.md": with_enums(SCHEMA).replace("memory | redis | memcached", "memory | redis")})
    envmap = {k[6]: f"{sec}.{k[0]}" for sec, v in SCHEMA.items() for k in v[1] if k[6]}
    s.func("t6", f"""
        rows = md_rows('docs/configuration.md', 'environment overrides')
        got = {{r[0].strip('` '): r[1].strip('` ') for r in rows[1:] if len(r) >= 2}}
        need(got == {envmap!r}, f'env table {{got}}')
        """)
    base6 = with_enums(SCHEMA)
    s.turn("Some keys carry an `x-env` entry in the schema. Add a `## Environment overrides` section with a table (columns variable, key): the environment variable in backticks and the dotted config key (`section.key`) it overrides, in schema order.",
           [s.g("t6")], files={"docs/configuration.md": base6 + env_section(SCHEMA)}, wrong_files={"docs/configuration.md": base6 + env_section(SCHEMA).replace("`server.port`", "`server.workers`")})
    s.func("t7", f"""
        txt = read('docs/configuration.md')
        m = re.search(r'^## Example\\s*$(.*?)(?=^## |\\Z)', txt, re.M | re.S)
        need(m, 'missing ## Example')
        b = re.search(r'```json\\n(.*?)```', m.group(1), re.S)
        need(b, 'no json block')
        try:
            d = json.loads(b.group(1))
        except ValueError as e:
            fail('example is not valid JSON: ' + str(e))
        need(d == {example(SCHEMA)!r}, 'example must contain exactly the required keys with placeholder values: ' + str(d))
        """)
    full7 = base6 + env_section(SCHEMA) + example_block(SCHEMA)
    s.turn("Add a `## Example` section with a ```json block holding a minimal valid config: only the required keys (as listed in the schema), nested under their sections. Use `postgres://localhost/app` for database.url and `change-me` for auth.secret.",
           [s.g("t7")], files={"docs/configuration.md": full7}, wrong_files={"docs/configuration.md": base6 + env_section(SCHEMA) + example_block(SCHEMA).replace('"change-me"', '"x"')})
    s2 = {**SCHEMA, "features": (SCHEMA["features"][0], SCHEMA["features"][1] + [NEWKEY])}
    s.func("t8", """
        sc = load_json('schema/app.schema.json')
        e = sc['properties']['features']['properties'].get('beta_search')
        need(e and e.get('type') == 'boolean' and e.get('default') is False and e.get('description'), 'schema entry for features.beta_search: ' + str(e))
        need(len(sc['properties']['features']['properties']) == 4, 'features must have 4 keys')
        rows = md_rows('docs/configuration.md', '^features$')
        got = {r[0].strip('` '): [r[1], r[2].strip('` '), r[3].lower()] for r in rows[1:] if len(r) >= 4}
        need(got.get('beta_search') == ['boolean', 'false', 'no'], 'docs row: ' + str(got.get('beta_search')))
        need(len(got) == 4, 'features table must have 4 rows')
        """)
    s.turn("Add a new boolean key `beta_search` to the features section of schema/app.schema.json (default false, description `Enable the beta search backend`, not required) and add its row to the features table in docs/configuration.md.",
           [s.g("t8")], files={"schema/app.schema.json": schema_json(s2), "docs/configuration.md": with_enums(s2) + env_section(s2) + example_block(s2)},
           wrong_files={"schema/app.schema.json": schema_json(s2), "docs/configuration.md": full7})
    alt = {"net": ("Network", [("port", "integer", 1, False, "p", None, None), ("host", "string", "x", False, "h", None, None)])}
    s.func("t9", f"""
        (W / '_alt').mkdir(exist_ok=True)
        (W / '_alt/schema.json').write_text({schema_json(alt)!r}, encoding='utf-8')
        (W / '_alt/docs.md').write_text('# C\\n\\n## net\\n\\n| key | type |\\n|---|---|\\n| `port` | integer |\\n| `colour` | string |\\n', encoding='utf-8')
        need((W / 'scripts/check_config_docs.py').exists(), 'missing scripts/check_config_docs.py')
        chk_cmd_out('python3 scripts/check_config_docs.py --schema _alt/schema.json --docs _alt/docs.md', ['UNDOCUMENTED: net.host', 'UNKNOWN: net.colour'], expect_rc=1)
        chk_cmd_out('python3 scripts/check_config_docs.py', ['ok'])
        """)
    s.turn("Add scripts/check_config_docs.py [--schema FILE] [--docs FILE] (defaults schema/app.schema.json and docs/configuration.md): print `UNDOCUMENTED: <section>.<key>` for schema keys with no row in that section's docs table, then `UNKNOWN: <section>.<key>` for documented keys the schema lacks (each group sorted), exit 1 if anything was printed, otherwise print `ok` and exit 0.",
           [s.g("t9")], files={"scripts/check_config_docs.py": CHECK}, wrong_files={"scripts/check_config_docs.py": CHECK.replace("raise SystemExit(1 if out else 0)", "raise SystemExit(0)")})
    ren = [("server.timeout", "server.request_timeout_s"), ("database.max_conn", "database.pool_size"), ("cache.size", "cache.max_items"), ("logging.rotate", "logging.rotate_mb")]
    s.func("t10", f"""
        rows = md_rows('docs/migration.md', 'renamed')
        got = [(r[0].strip('` '), r[1].strip('` ')) for r in rows[1:] if len(r) >= 2]
        need(got == {ren!r}, 'rename table: ' + str(got))
        need(re.search(r'(?i)server\\.debug', '\\n'.join(md_lines('docs/migration.md', 'removed'))), 'removed key server.debug not listed under Removed')
        """)
    mig = "# Migrating v1 to v2\n\n## Renamed keys\n\n| old | new |\n|---|---|\n" + "".join(f"| `{a}` | `{b}` |\n" for a, b in ren) + "\n## Removed keys\n\n- `server.debug`\n"
    s.turn("Using schema/CHANGES.txt write docs/migration.md with a `## Renamed keys` table (columns old, new; keys in backticks, same order as the file) and a `## Removed keys` section listing the removed key.",
           [s.g("t10")], files={"docs/migration.md": mig}, wrong_files={"docs/migration.md": mig.replace("`cache.max_items`", "`cache.max_size`")})
    s.turn("Add a '## Documentation' section to README.md linking docs/configuration.md and docs/migration.md and mentioning scripts/check_config_docs.py.",
           [sections("README.md", "Documentation"), rx("README.md", r"docs/configuration\.md"), rx("README.md", r"docs/migration\.md"), rx("README.md", r"scripts/check_config_docs\.py")],
           files={"README.md": s.files["README.md"] + "\n## Documentation\n\nSee docs/configuration.md and docs/migration.md. Run scripts/check_config_docs.py to compare docs with the schema.\n"},
           wrong_files={"README.md": s.files["README.md"] + "\n## Documentation\n\nSee docs.\n"})
    return s
