# Amplifier Fast Decisions + Decision Observatory

Experimental v0.1.0. A Foundation-compatible bundle, a hybrid orchestrator, a hosted Jev adapter, structured events, and a read-only local visualizer.

No Jev key? Start with **Ollama + `qwen3:0.6b` (Q4_K_M)**. Our small development
benchmark measured 23.9 ms warm p95 on an M5 Max; this is an experimental
one-token classifier, not a Jev replica or a general latency/accuracy guarantee.
The [simple setup and tuning guide](docs/MODEL-SETUP.md) covers local use and
hosted judges; [pilot evidence](docs/LOCAL-SCORER.md) records the limits.

The decision service is also a [portable Smart Tool](docs/SMART-TOOL.md): a
Python library with its own local model capability, a manifest, and a thin CLI.
Its deterministic help/manifest/schema commands need no model.
The [current architecture review](docs/design/smart-decision-review-2026-09-18.md)
separates shipped portability from the proposed generic decision engine. Claude Code,
Codex, OpenCode, Amplifier, or any harness with shell access can call its advisory selection
capability; native Amplifier interception remains a separate adapter.

**A fast judgment is not a permission grant. A proposed action is not an executed action.**

The orchestrator composes `StreamingOrchestrator`; it does not replace the Rust kernel or duplicate its tool-execution loop. At each eligible `Provider.complete()` boundary, the decision service may return a prepared tool-call envelope instead of calling the generative provider. The upstream loop handles that envelope normally. This is an executable integration candidate, not a claim of production certification.

## Status

Experimental v0.1.0. Benchmark evidence lives in
[docs/BATTERY-2026-09-18.md](docs/BATTERY-2026-09-18.md) and the `evals/`
directory (cell definitions, mechanism gates, and study design); no result
here is a production SLA.

## Configuration

Three judge backends, chosen by `backend` (config) or `FAST_DECISIONS_JUDGE`
(env; profile config always wins):

| Judge | What it is | Data leaving this machine |
|---|---|---|
| **Local** | Ollama (default) or Apple MLX (`mlx_lm.server`, Apple Silicon only) | None -- loopback only |
| **Hosted** | Any OpenAI-compatible endpoint you control that returns `top_logprobs` | The bounded decision state (task snapshot, candidates, questions), gated by `allow_external_state` |
| **Jev** | [typesafe.ai](https://typesafe.ai)'s hosted judge (external service) | Same bounded decision state, gated by `allow_external_state` |

Copy [`.env.example`](.env.example) to `.env` and adjust; see
[docs/MODEL-SETUP.md](docs/MODEL-SETUP.md) for full setup and
[docs/PRIVACY.md](docs/PRIVACY.md) for the complete data-path accounting per
backend.

**Install, per harness:**

```bash
# Amplifier (this repo's primary integration)
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=bundles/active.yaml"

# Any other coding-agent harness (Claude Code, Codex, OpenCode, ...)
uvx --from git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions amplifier-fast-decisions --help
```

## Install

Add the capability to your Amplifier app (hook + read-only `fast_workspace` tool, orchestrator untouched). The hook ships with shadow measurement on by default (`mode: shadow`), so this alone gets you "what would we have chosen" telemetry on top of whatever orchestrator you already run -- no orchestrator swap required:

```bash
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=behaviors/fast-decisions.yaml" --app
```

Start any session; the observatory opens at `http://127.0.0.1:8765` (token-protected, loopback) the first time a top-level session starts, with shadow measurement already on against the offline backend. It reuses an already-running viewer instead of spawning a second one. If port 8765 is busy, `afast serve` picks a free port instead; the state file and printed URL tell you which. Stop it with `afast serve --stop`. Disable auto-open with `observatory.open_browser: never` in the hook config, or `AFAST_OBSERVATORY=off` (or `AMPLIFIER_NO_BROWSER=1`) in the environment; it also stays off for child sessions and non-interactive (non-TTY) runs.

To run the decision orchestrator's active fast path (a fast decision model actually substituting a prepared read-only action for an LLM turn), load the standalone active bundle instead:

```bash
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=bundles/active.yaml"
amplifier run --bundle fast-decisions-active "Read README.md and explain what this project does."
```

This active profile enables external state transmission to TypeSafe. Review
[PRIVACY.md](docs/PRIVACY.md), install the Jev SDK in the host environment,
and supply `TYPESAFE_API_KEY` securely before this test. Use public files.

### Why the observatory can be live without a fast path

An `app` entry for `fast-decisions` confirms composition, not active routing.
The installed behavior uses shadow mode with an offline scripted scorer;
it never replaces a provider call. The bundle list's “No bundle active”
refers to primary bundle selection and does not disable app bundles.

Real model shadow proposals count as model decisions, but never as fast submissions.
Scripted shadow proposals are excluded from model and improvement counters.
The viewer shows native provider requests and tool post hooks separately
from measured provider invocations and actual `execute()` outcomes. Hook
observations do not establish successful execution or its duration.
The effective mode/backend appear in telemetry even before a score exists.
With no eligible prepared action, the observer reports
`no_eligible_candidates`; built-in candidates need an explicit eligible
text-file path under the configured workspace root. Generic prompts do not
automatically produce fast paths, and model-role suggestions remain shadow-only.

`bundles/shadow.yaml` still exists and still resolves, but it is **DEPRECATED** -- it forwards to `bundle.md` unchanged (your orchestrator stays in place) and no longer swaps `session.orchestrator`. Prefer composing `bundle.md` (or `behaviors/fast-decisions.yaml`) directly; the forwarding alias is removed in 0.3.0.

The `afast` CLI (local decision observatory + doctor) installs as a tool:

```bash
uv tool install "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main"
```

## Use a real local model without Jev

Use **`qwen3:0.6b` with Ollama** for the current prepared read/list pilot. Keep
your existing generative provider for reasoning and the final answer. A local
decision scorer does not make the whole Amplifier session local.

| Where to run | Starting configuration |
|---|---|
| Your Mac or workstation | Ollama + `qwen3:0.6b`, warmed before the session; 500 ms scoring deadline |
| Your own server or rented host | Run Amplifier and Ollama together on that host, using loopback; start with the same model and benchmark that hardware |
| A remote inference API from your laptop | Not supported by the current Ollama adapter; it accepts only literal loopback HTTP origins |

After installing and starting [Ollama](https://ollama.com/download), the model
setup is:

```bash
ollama pull qwen3:0.6b
curl --fail --silent --show-error http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:0.6b","stream":false,"keep_alive":"10m","options":{"num_ctx":4096}}'
ollama ps
```

Then follow the [copy/paste isolated session setup](docs/MODEL-SETUP.md#simple-local-setup)
to install the Python dependency, generate a local **shadow** profile, and run
a public two-file example. Generate a separate **active** profile to test actual
fast submissions after checking the shadow output. Installing the app behavior
alone still uses the scripted shadow scorer; it does not select Qwen.

The guide covers [configuration and tuning](docs/MODEL-SETUP.md#configuration-and-tuning),
[running the local judge remotely](docs/MODEL-SETUP.md#running-the-local-judge-on-a-remote-host), and common
setup failures. Leave the selection score at 0.90 and margin at 0.20 initially;
these are uncalibrated token thresholds. More accepted actions are useful only
if correctness and complete-task latency also improve.

## Start with the no-key demo

Python 3.11 or newer. No installation, API key, Node build, or network required:

```bash
cd amplifier-bundle-fast-decisions
python3 -m amplifier_fast_decisions demo --open
```

Open the localhost URL printed by the command. It includes a temporary access token. Stop with Ctrl+C. Use `--port 8766` if the default port is occupied.

The demo runs the real decision service and facades against **explicitly synthetic loop, model, and tool fixtures**. It demonstrates prepared-action execution, ambiguity, abstention, shadow mode, timeout, and a fast-path budget. Its artificial delays are not Jev benchmarks.

The Observatory groups **parent sessions**, includes child activity by default,
and lets you expand or select children separately.
It polls recorded bundle events across local sessions, separates observer presence
from working/idle state, and shows native activity, retries, real model decisions,
and instrumented fast-path executions. The default live-flow view shows successive recorded decision stages and
highlights new arrivals. Select a stage to inspect its candidate scores and
metadata. A muted neutral palette keeps long-running monitoring comfortable. Scripted/demo events are hidden by default
and excluded from improvement counters; enable them when inspecting the demo.

The feed supports pause/resume, time windows, JSONL import/export, and a recoverable
connection state if the viewer token is missing. Saved traces are labeled separately
from live updates. Generative calls bypassed require a recorded provider-boundary submission.
Tool calls eliminated, net time/cost savings, and task-quality parity stay
unmeasured until instrumented; shadow agreement is not independent correctness.
Decision p95 is backend scoring time, not whole-task speedup. Existing running sessions need to reload the updated observer to emit
15-second presence heartbeats. No prompts, tool contents, or private reasoning are
shown. See [event semantics and limits](docs/EVENTS.md).

## Optional Jev test (requires API access)

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

| Layer | What it provides |
|---|---|
| `bundle.md` | Root: telemetry hook (shadow measurement on by default) + `fast_workspace` tool; orchestrator untouched |
| `behaviors/fast-decisions.yaml` | `hooks-fast-decisions` (`mode: shadow` by default) + `tool-fast-workspace` |
| `bundles/shadow.yaml` | **DEPRECATED** -- forwards to `bundle.md` unchanged; no longer swaps the orchestrator |
| `bundles/active.yaml` | Root + decision orchestrator in active mode (opt-in fast path) |

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

## Operational diagnostics and measured comparisons

```bash
amplifier-fast-decisions diagnose
amplifier-fast-decisions measure --session PARENT_SESSION_ID
amplifier-fast-decisions compare --input runs.json
```

See [OPERATIONS.md](docs/OPERATIONS.md) for setup remediation, parent/child
accounting, exact receipt semantics and the opt-in live comparison runner.
These reports distinguish observed activity, actual executions and checked outcomes.

## Health checks and tests

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_viewer.cjs  # viewer regression tests; Node only needed for this check
python3 -m amplifier_fast_decisions doctor
```

Run `doctor --require-amplifier` **inside the same Python environment that hosts Amplifier**. A separate Python installation will not see a CLI managed by `uv tool` or another isolated environment. Foundation's module environments can also differ. The command checks imports and core response/execute signatures, not full runtime behavior.

For a dedicated integration environment with network access:

```bash
python3 -m venv .venv
. .venv/bin/activate
uv pip install -e '.[amplifier,jev,test]'
python -m amplifier_fast_decisions doctor --require-amplifier
python -m unittest discover -s tests -v
```

This installs the pinned core/loop snapshots in that venv, not into your existing Amplifier CLI environment. Do not treat it as a CLI upgrade. A Rust toolchain may be needed when the core builds from source.

The optional probe makes one billed TypeSafe request using fixed public sample content, and executes no tools:

```bash
AFAST_RUN_LIVE=1 python scripts/test_live_jev.py
```

API key must already be set. The live request is opt-in, not part of the default tests or demo.

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
[BENCH.md](docs/BENCH.md) for metric definitions and known gaps, and
[UAT.md](docs/UAT.md) for the full shadow-then-active walkthrough.

## Replay an actual trace

```bash
python3 -m amplifier_fast_decisions export \
  --events "$HOME/.amplifier/fast-decisions/events" \
  --output decision-observatory.html
```

Open the resulting HTML in a browser. Review telemetry before sharing: file/tool labels, session IDs, and timing information can still be sensitive.

## Compatibility and current limits

**Read this before production use:** [COMPATIBILITY.md](docs/COMPATIBILITY.md).

- Active decisions run at the upstream `complete()` boundary. A provider’s optional `.stream` transport is preserved and defers to the original provider; that branch has no active fast path. See [COMPATIBILITY.md](docs/COMPATIBILITY.md).
- Real Rust-backed sessions, live Jev accuracy/latency, Foundation loading, approval/steering combinations, and your installed provider set must be tested on your machine. They were not exercised in the build sandbox.
- Only prepared actions are accelerated. Automatic model-role selection, free-form tool argument synthesis, autonomous stopping, distributed telemetry aggregation, and native Rust inference are not implemented.
- Confidence thresholds are uncalibrated experimental settings, not measured safety guarantees. Permissions remain upstream.
- Deterministic logic currently handles eligibility, budget, and fallback checks. It does not independently execute application actions.
- The observer-only behavior reports native hook metadata, not fabricated Jev decisions or actual tool durations.
- The source pins identify indexed source snapshots, not a fully locked, tested dependency graph. Foundation and its transitive dependencies remain floating.

## Developer map

Start with [ARCHITECTURE.md](docs/ARCHITECTURE.md), [EVENTS.md](docs/EVENTS.md), [EXTENDING.md](docs/EXTENDING.md), [BENCH.md](docs/BENCH.md), [UAT.md](docs/UAT.md), and [AGENT-HANDOFF.md](docs/AGENT-HANDOFF.md).

MIT licensed. This experimental package is not an official Microsoft or TypeSafe release.
