# Amplifier Fast Decisions + Decision Observatory

Experimental v0.1.0. A Foundation-compatible bundle, a hybrid orchestrator, a hosted Jev adapter, structured events, and a read-only local visualizer.

**A fast judgment is not a permission grant. A proposed action is not an executed action.**

The orchestrator composes `StreamingOrchestrator`; it does not replace the Rust kernel or duplicate its tool-execution loop. At each eligible `Provider.complete()` boundary, the decision service may return a prepared tool-call envelope instead of calling the generative provider. The upstream loop handles that envelope normally. This is an executable integration candidate, not a claim of production certification.

## Start with the no-key demo

Python 3.11 or newer. No installation, API key, Node build, or network required:

```bash
cd amplifier-fast-decisions
python3 -m amplifier_fast_decisions demo --open
```

Open the localhost URL printed by the command. It includes a temporary access token. Stop with Ctrl+C. Use `--port 8766` if the default port is occupied.

The demo runs the real decision service and facades against **explicitly synthetic loop, model, and tool fixtures**. It demonstrates prepared-action execution, ambiguity, abstention, shadow mode, timeout, and a fast-path budget. Its artificial delays are not Jev benchmarks.

The observatory provides an animated routing graph, destination/model labels, decision distributions, mechanical fallback reasons, actual tool-execution timings, session selection, event inspection, playback, scrubbing, and JSONL import/export. It never displays private chain of thought.

## First real Amplifier test

Use a disposable checkout containing public files. Your existing Amplifier CLI must already work with a generative provider. Keep this repository extracted; do not install only the wheel for bundle use. Foundation activates the shared root Python package and the three local module packages.

In the extracted repository, set the workspace and generate an explicit **shadow** profile:

```bash
export WORKSPACE="$(pwd)"
# Set TYPESAFE_API_KEY in your shell or secret manager, never in bundle YAML.
python3 -m amplifier_fast_decisions configure \
  --bundle-root "$PWD" \
  --workspace "$WORKSPACE" \
  --mode shadow \
  --allow-external-state \
  --output "$PWD/local-shadow.md"

amplifier bundle add "file://$PWD/local-shadow.md"
amplifier run --bundle fast-decisions-shadow \
  "Read README.md and explain what this project does."
```

The second command selects this profile for this run. **Do not add `--app` during the initial test.** That option composes a bundle onto every session; this experimental orchestrator should not silently replace all your sessions' loops. Do not change your default bundle yet.

In a second terminal, from this repository:

```bash
python3 -m amplifier_fast_decisions serve --open
```

The viewer tails `~/.amplifier/fast-decisions/events`. An explicit `--events` or `AFAST_EVENTS_DIR` can be used; match the runtime and viewer directories. The configuration generator prints the profile location and never modifies Amplifier settings itself.

**External-state opt-in matters:** the shipped root bundle defaults to `shadow` with `allow_external_state: false`. Without the explicit opt-in, decisions route slow with `external_state_not_enabled`. The opt-in permits a bounded, scrubbed slice of user/tool/assistant public content, plus candidate descriptions, to go to TypeSafe. It does not permit arbitrary workspace upload. Read [PRIVACY.md](docs/PRIVACY.md) first. Shadow mode still sends this state when enabled.

To enable the prepared-action fast path after inspecting shadow traces:

```bash
python3 -m amplifier_fast_decisions configure \
  --bundle-root "$PWD" --workspace "$WORKSPACE" \
  --mode active --allow-external-state --output "$PWD/local-active.md"
amplifier bundle add "file://$PWD/local-active.md"
amplifier run --bundle fast-decisions-active \
  "Read README.md and explain what this project does."
```

Expected: `requested`, `scored`, then either `routed:fast` or a documented slow reason. A fast submission enters the upstream tool loop; a subsequent `tool_start` means actual `execute()` was reached. A denied native approval can prevent execution after submission. The final answer still comes from your generative provider.

Only user-explicit, eligible text-file paths become automatic built-in candidates. Asking a generic question, mentioning no suitable file, or lacking an automatic tool boundary correctly uses the slow path. The experiment does not claim to accelerate every prompt.

## What ships

| Part | Implementation |
|---|---|
| Bundle composition | `bundle.md` composes `behaviors/hybrid.yaml` by default. `behaviors/observe-only.yaml` is a reference profile, not included by default -- compose it explicitly (`includes: - bundle: fast-decisions:behaviors/observe-only.yaml`) in place of `hybrid.yaml` for metadata-only observation. |
| Hybrid orchestrator | `loop-fast-decisions`, composing the installed upstream loop |
| Native observer | `hooks-fast-decisions`, optional metadata-only hook bridge |
| Prepared tool | `tool-fast-workspace`, constrained read/list operations |
| Decision backend | TypeSafe `AsyncTypeSafeClient`, with explicit timeout and no automatic retries |
| Emitters | Versioned `fast_decisions:*` events to native hooks and bounded JSONL recorder |
| Visualizer | Loopback-only, token-protected HTTP server; no external frontend assets |
| Replay | JSONL import/export and a self-contained HTML export |
| Tests | Offline unit/contract-double tests, optional real-envelope checks, explicit live SDK probe |

## Health checks and tests

```bash
python3 -m unittest discover -s tests -v
python3 -m amplifier_fast_decisions doctor
```

Run `doctor --require-amplifier` **inside the same Python environment that hosts Amplifier**. A separate Python installation will not see a CLI managed by `uv tool` or another isolated environment. Foundation's module environments can also differ. The command checks imports and core response/execute signatures, not full runtime behavior.

For a dedicated integration environment with network access:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[amplifier,jev,test]'
python -m amplifier_fast_decisions doctor --require-amplifier
python -m unittest discover -s tests -v
```

This installs the pinned core/loop snapshots in that venv, not into your existing Amplifier CLI environment. Do not treat it as a CLI upgrade. A Rust toolchain may be needed when the core builds from source.

The optional probe makes one billed TypeSafe request using fixed public sample content, and executes no tools:

```bash
AFAST_RUN_LIVE=1 python scripts/test_live_jev.py
```

API key must already be set. The live request is opt-in, not part of the default tests or demo.

## Replay an actual trace

```bash
python3 -m amplifier_fast_decisions export \
  --events "$HOME/.amplifier/fast-decisions/events" \
  --output decision-observatory.html
```

Open the resulting HTML in a browser. Review telemetry before sharing: file/tool labels, session IDs, and timing information can still be sensitive.

## Compatibility and current limits

**Read this before production use:** [COMPATIBILITY.md](docs/COMPATIBILITY.md).

- This release deliberately uses the upstream `complete()` branch. It hides a provider's optional `.stream` attribute. A provider that streams internally during `complete()` may retain that behavior; a provider relying on the separate `.stream` API will not use that transport here.
- Real Rust-backed sessions, live Jev accuracy/latency, Foundation loading, approval/steering combinations, and your installed provider set must be tested on your machine. They were not exercised in the build sandbox.
- Only prepared actions are accelerated. Automatic model-role selection, free-form tool argument synthesis, autonomous stopping, distributed telemetry aggregation, and native Rust inference are not implemented.
- Confidence thresholds are uncalibrated experimental settings, not measured safety guarantees. Permissions remain upstream.
- Deterministic logic currently handles eligibility, budget, and fallback checks. It does not independently execute application actions.
- The observer-only behavior reports native hook metadata, not fabricated Jev decisions or actual tool durations.
- The source pins identify indexed source snapshots, not a fully locked, tested dependency graph. Foundation and its transitive dependencies remain floating.

## Developer map

Start with [ARCHITECTURE.md](docs/ARCHITECTURE.md), [EVENTS.md](docs/EVENTS.md), [EXTENDING.md](docs/EXTENDING.md), and [AGENT-HANDOFF.md](docs/AGENT-HANDOFF.md). The build evidence and exact test status are in [BUILD-REPORT.md](BUILD-REPORT.md).

MIT licensed. This experimental package is not an official Microsoft or TypeSafe release.
