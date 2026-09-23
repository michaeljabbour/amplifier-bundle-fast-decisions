# Getting started

Walkthroughs that used to live in `README.md`: the no-key demo, the local
model setup, the optional Jev test, and why the observatory can be live
before any fast path is.

## Start with the no-key demo

Python 3.11 or newer. No installation, API key, Node build, or network required:

```bash
cd amplifier-bundle-fast-decisions
python3 -m amplifier_fast_decisions demo --open
```

Open the localhost URL printed by the command. It includes a temporary access
token. Stop with Ctrl+C. Use `--port 8766` if the default port is occupied.

The demo runs the real decision service and facades against **explicitly
synthetic loop, model, and tool fixtures**. It demonstrates prepared-action
execution, ambiguity, abstention, shadow mode, timeout, and a fast-path
budget. Its artificial delays are not Jev benchmarks.

The Observatory groups **parent sessions**, includes child activity by default,
and lets you expand or select children separately.
It polls recorded bundle events across local sessions, separates observer presence
from working/idle state, and shows native activity, retries, real model decisions,
and instrumented fast-path executions. The default live-flow view shows successive
recorded decision stages and highlights new arrivals. Select a stage to inspect its
candidate scores and metadata. A muted neutral palette keeps long-running monitoring
comfortable. Scripted/demo events are hidden by default and excluded from
improvement counters; enable them when inspecting the demo.

The feed supports pause/resume, time windows, JSONL import/export, and a recoverable
connection state if an explicitly token-protected viewer is missing its token. Saved traces are labeled separately
from live updates. Generative calls bypassed require a recorded provider-boundary
submission. Tool calls eliminated, net time/cost savings, and task-quality parity stay
unmeasured until instrumented; shadow agreement is not independent correctness.
Decision p95 is backend scoring time, not whole-task speedup. Existing running sessions
need to reload the updated observer to emit 15-second presence heartbeats. No prompts,
tool contents, or private reasoning are shown.
See [event semantics and limits](EVENTS.md).

The dashboard combines a live **Decision path** with a compact **Decision ledger**.
Choose **Inspect** on a ledger row to pin its path, expand its recorded stages,
and read the evidence in the shared inspector. **Follow latest decision** returns
the path to the newest record. In-progress rows show their stages automatically.
Collapse the path to give the ledger more room; that preference survives refresh.
Session filters, pause state, event categories, and trace imports apply to both.
Incoming records briefly highlight rows, nodes, and routes. Native observations
can light the host node without implying a judge decision or a fast execution.
Older `?view=circuit` and `?view=ledger` links both open this unified dashboard.

## Install the app behavior (shadow measurement only)

Add the capability to your Amplifier app (hook + read-only `fast_workspace`
tool, orchestrator untouched). The hook ships with shadow measurement on by
default (`mode: shadow`), so this alone gets you "what would we have chosen"
telemetry on top of whatever orchestrator you already run -- no orchestrator
swap required:

```bash
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=behaviors/fast-decisions.yaml" --app
```

Start any session; the observatory opens at `http://127.0.0.1:8765`
(loopback-only) the first time a top-level session starts, with
shadow measurement already on against the offline backend. It reuses an
already-running viewer instead of spawning a second one. If port 8765 is busy,
`afast serve` picks a free port instead; the state file and printed URL tell
you which. Stop it with `afast serve --stop`. Disable auto-open with
`observatory.open_browser: never` in the hook config, or `AFAST_OBSERVATORY=off`
(or `AMPLIFIER_NO_BROWSER=1`) in the environment; it also stays off for child
sessions and non-interactive (non-TTY) runs.

The `afast` CLI (local decision observatory + doctor) installs as a tool:

```bash
uv tool install "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main"
```

## Why the observatory can be live without a fast path

An `app` entry for `fast-decisions` confirms composition, not active routing.
The installed behavior uses shadow mode with an offline scripted scorer;
it never replaces a provider call. The bundle list's "No bundle active"
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

`bundles/shadow.yaml` still exists and still resolves, but it is **DEPRECATED**
-- it forwards to `bundle.md` unchanged (your orchestrator stays in place) and
no longer swaps `session.orchestrator`. Prefer composing `bundle.md` (or
`behaviors/fast-decisions.yaml`) directly; the forwarding alias is removed in
0.3.0.

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

Then follow the [copy/paste isolated session setup](MODEL-SETUP.md#simple-local-setup)
to install the Python dependency, generate a local **shadow** profile, and run
a public two-file example. Generate a separate **active** profile to test actual
fast submissions after checking the shadow output. Installing the app behavior
alone still uses the scripted shadow scorer; it does not select Qwen.

The guide covers [configuration and tuning](MODEL-SETUP.md#configuration-and-tuning),
[running the local judge remotely](MODEL-SETUP.md#running-the-local-judge-on-a-remote-host), and common
setup failures. Leave the selection score at 0.90 and margin at 0.20 initially;
these are uncalibrated token thresholds. More accepted actions are useful only
if correctness and complete-task latency also improve.

## Optional Jev test (requires API access)

Use a disposable checkout containing public files. Your existing Amplifier CLI
must already work with a generative provider. Keep this repository extracted;
do not install only the wheel for bundle use. Foundation activates the shared
root Python package and the three local module packages.

In the extracted repository, set the workspace and generate an explicit
**shadow** profile:

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

The second command selects this profile for this run. **Do not add `--app`
during the initial test.** That option composes a bundle onto every session;
this experimental orchestrator should not silently replace all your sessions'
loops. Do not change your default bundle yet.

In a second terminal, from this repository:

```bash
python3 -m amplifier_fast_decisions serve --open
```

The viewer tails `~/.amplifier/fast-decisions/events`. An explicit `--events` or
`AFAST_EVENTS_DIR` can be used; match the runtime and viewer directories. The
configuration generator prints the profile location and never modifies Amplifier
settings itself.

**External-state opt-in matters:** the shipped root bundle defaults to `shadow`
with `allow_external_state: false`. Without the explicit opt-in, decisions route
slow with `external_state_not_enabled`. The opt-in permits a bounded, scrubbed
slice of user/tool/assistant public content, plus candidate descriptions, to go
to TypeSafe. It does not permit arbitrary workspace upload. Read
[PRIVACY.md](PRIVACY.md) first. Shadow mode still sends this state when enabled.

To enable the prepared-action fast path after inspecting shadow traces:

```bash
python3 -m amplifier_fast_decisions configure \
  --bundle-root "$PWD" --workspace "$WORKSPACE" \
  --mode active --allow-external-state --output "$PWD/local-active.md"
amplifier bundle add "file://$PWD/local-active.md"
amplifier run --bundle fast-decisions-active \
  "Read README.md and explain what this project does."
```

Expected: `requested`, `scored`, then either `routed:fast` or a documented slow
reason. A fast submission enters the upstream tool loop; a subsequent
`tool_start` means actual `execute()` was reached. A denied native approval can
prevent execution after submission. The final answer still comes from your
generative provider.

Only user-explicit, eligible text-file paths become automatic built-in
candidates. Asking a generic question, mentioning no suitable file, or lacking
an automatic tool boundary correctly uses the slow path. The experiment does not
claim to accelerate every prompt.

The standalone active bundle (`bundles/active.yaml`) can also be installed
directly instead of generating a profile:

```bash
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=bundles/active.yaml"
amplifier run --bundle fast-decisions-active "Read README.md and explain what this project does."
```

Next: [UAT.md](UAT.md) for the full shadow-then-active walkthrough, and
[DIAGNOSTICS.md](DIAGNOSTICS.md) for health checks, receipts and trace replay.
