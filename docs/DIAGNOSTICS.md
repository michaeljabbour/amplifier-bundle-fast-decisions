# Diagnostics, health checks and replay

Operator-facing checks that used to live in `README.md`. For what the
diagnose/measure/compare reports mean in detail, see
[OPERATIONS.md](OPERATIONS.md).

## Operational diagnostics and measured comparisons

```bash
amplifier-fast-decisions diagnose
amplifier-fast-decisions measure --session PARENT_SESSION_ID
amplifier-fast-decisions compare --input runs.json
```

See [OPERATIONS.md](OPERATIONS.md) for setup remediation, parent/child
accounting, exact receipt semantics and the opt-in live comparison runner.
These reports distinguish observed activity, actual executions and checked
outcomes.

## Health checks and tests

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_viewer.cjs  # viewer regression tests; Node only needed for this check
python3 -m amplifier_fast_decisions doctor
```

Run `doctor --require-amplifier` **inside the same Python environment that
hosts Amplifier**. A separate Python installation will not see a CLI managed by
`uv tool` or another isolated environment. Foundation's module environments can
also differ. The command checks imports and core response/execute signatures,
not full runtime behavior.

For a dedicated integration environment with network access:

```bash
python3 -m venv .venv
. .venv/bin/activate
uv pip install -e '.[amplifier,jev,test]'
python -m amplifier_fast_decisions doctor --require-amplifier
python -m unittest discover -s tests -v
```

This installs the pinned core/loop snapshots in that venv, not into your
existing Amplifier CLI environment. Do not treat it as a CLI upgrade. A Rust
toolchain may be needed when the core builds from source.

The optional probe makes one billed TypeSafe request using fixed public sample
content, and executes no tools:

```bash
AFAST_RUN_LIVE=1 python scripts/test_live_jev.py
```

API key must already be set. The live request is opt-in, not part of the
default tests or demo.

## Bench: offline replay and the synthetic suite

```bash
afast bench replay examples/demo-events.jsonl --json | python3 -m json.tool
afast bench suite suites/v1.jsonl --json
```

`afast bench replay` computes decision latency/cost, agreement, calibration
(ECE), and abstention from telemetry the system already wrote -- zero
network. `afast bench suite` runs a small, checked-in, labelled suite
against a fully offline deterministic backend by default (`--backend jev
--live` requires both `FAST_DECISIONS_LIVE=1` and `TYPESAFE_API_KEY`). See
[BENCH.md](BENCH.md) for metric definitions and known gaps, and
[UAT.md](UAT.md) for the full shadow-then-active walkthrough.

## Replay an actual trace

```bash
python3 -m amplifier_fast_decisions export \
  --events "$HOME/.amplifier/fast-decisions/events" \
  --output decision-observatory.html
```

Open the resulting HTML in a browser. Review telemetry before sharing:
file/tool labels, session IDs, and timing information can still be sensitive.

## Developer map

Start with [ARCHITECTURE.md](ARCHITECTURE.md), [EVENTS.md](EVENTS.md),
[EXTENDING.md](EXTENDING.md), [BENCH.md](BENCH.md), [UAT.md](UAT.md), and
[AGENT-HANDOFF.md](AGENT-HANDOFF.md).

## What ships

| Layer | What it provides |
|---|---|
| `bundle.md` | Root: telemetry hook (shadow measurement on by default) + `fast_workspace` tool; orchestrator untouched |
| `behaviors/fast-decisions.yaml` | `hooks-fast-decisions` (`mode: shadow` by default) + `tool-fast-workspace` |
| `bundles/shadow.yaml` | **DEPRECATED** -- forwards to `bundle.md` unchanged; no longer swaps the orchestrator |
| `bundles/active.yaml` | Root + decision orchestrator in active mode (opt-in fast path) |
| `bundles/active-routing.yaml` | Root + active mode plus phase effort routing and opt-in model routing/escalation |

| Part | Implementation |
|---|---|
| Hybrid orchestrator | `loop-fast-decisions`, composing the installed upstream loop |
| Native observer | `hooks-fast-decisions`, optional metadata-only hook bridge |
| Prepared tool | `tool-fast-workspace`, constrained read/list operations |
| Decision backend | TypeSafe `AsyncTypeSafeClient`, with explicit timeout and no automatic retries |
| Emitters | Versioned `fast_decisions:*` events to native hooks and bounded JSONL recorder |
| Visualizer | Loopback-only, token-protected HTTP server; no external frontend assets |
| Replay | JSONL import/export and a self-contained HTML export |
| Tests | Offline unit/contract-double tests, optional real-envelope checks, explicit live SDK probe |
