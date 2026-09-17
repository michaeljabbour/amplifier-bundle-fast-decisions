# AGENTS.md

Coding-agent instructions for this repo live in `docs/AGENT-HANDOFF.md` --
read that file before making changes here.

Quick pointers:
- Layout: shared package in `src/amplifier_fast_decisions/`; thin module shims in `modules/*`; bundle composition in `bundle.md`, `behaviors/`, `bundles/`.
- Setup: `uv pip install -e '.[test]'` (or prefix commands with `PYTHONPATH=src`).
- Test command: `python3 -m unittest discover -s tests -v` (or `scripts/smoke_test.sh`, which sets the path for you)
- Health check: `python3 -m amplifier_fast_decisions doctor`
- Clean build/cache artifacts (egg-info, __pycache__, build/, .ruff_cache, .DS_Store): `git clean -fdX`
- Key docs: `README.md`, `docs/COMPATIBILITY.md`, `docs/PRIVACY.md`, `docs/ARCHITECTURE.md`
