# AGENTS.md

**Read `docs/GOAL.md` first: it states what this project must achieve and how success is measured.**

Coding-agent instructions for this repo live in `docs/AGENT-HANDOFF.md` --
read that file before making changes here.

Quick pointers:
- Layout: shared package in `src/amplifier_fast_decisions/`; thin module shims in `modules/*`; bundle composition in `bundle.md`, `behaviors/`, `bundles/`.
- Setup: `uv pip install -e '.[test]'` (or prefix commands with `PYTHONPATH=src`).
- Test command: `python3 -m unittest discover -s tests -v` (or `scripts/smoke_test.sh`, which sets the path for you)
- Health check: `python3 -m amplifier_fast_decisions doctor`
- Bench (offline telemetry analysis + synthetic suite): `afast bench replay <events-dir-or-jsonl> --json`, `afast bench suite [suites/v1.jsonl] --json` -- see `docs/BENCH.md`
- Auto-observatory (session-start viewer bootstrap): stop a running one with `afast serve --stop` (reads `~/.amplifier/fast-decisions/serve.json` by default; `--state-file` to override) -- do this before a manual `afast serve` in the same events dir/port to avoid two servers
- Clean build/cache artifacts (egg-info, __pycache__, build/, .ruff_cache, .DS_Store): `git clean -fdX`
- Key docs: `README.md`, `docs/COMPATIBILITY.md`, `docs/PRIVACY.md`, `docs/ARCHITECTURE.md`
