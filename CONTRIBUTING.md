# Contributing

## Setup

```bash
uv pip install -e '.[test]'
```

The package uses a `src/` layout. If you'd rather not install it, put `src/`
on your path instead: `PYTHONPATH=src python3 ...`.

## Running tests

```bash
python3 -m unittest discover -s tests
```

Or use the smoke script, which sets `PYTHONPATH` for you and also runs
`amplifier_fast_decisions doctor`:

```bash
scripts/smoke_test.sh
```

Everything here is offline by default: no network calls, no installed
Amplifier runtime, no external judge required. Tests that need any of those
are marked (`upstream`, `live`) and skip cleanly when the prerequisite isn't
present.

## Benchmarks and evaluations

Benchmark and evaluation tooling lives under `evals/` and `scripts/`:

- `evals/` -- the decision-suite harness (`run.py`, `cells.yaml`,
  `suites.yaml`); start with `evals/STUDY-DESIGN.md` for what's measured and
  `evals/README.md` for how to run it.
- `scripts/battery.py` -- the wider agent-battery harness (`prepare` / `run` /
  `reevaluate` / `evaluate`).
- `afast bench replay` / `afast bench suite` -- offline telemetry analysis and
  the synthetic decision suite; see `docs/BENCH.md`.

## Conventions

- Keep modules self-contained: public interface in `__init__.py`, internals
  private, tests alongside the code they cover.
- Match the existing docstring style -- contracts and invariants are
  documented at the point they're enforced, not in a separate design doc that
  can drift out of sync.
- Commits: a plain, descriptive message is fine. If a commit was
  AI-assisted, adding an attribution trailer is welcome but not required.

## Pull requests

- Include or update tests for any behavior change.
- Update the relevant doc under `docs/` when a contract, config option, or
  CLI flag changes.
- Don't commit run output (event logs, benchmark results, generated
  profiles) -- see `.gitignore` and `evals/README.md` for what's excluded and
  why.
- Run the full test suite locally before opening the PR.
