---
{
  "smart_tool_format": 1,
  "name": "amplifier-fast-decisions",
  "version": "0.3.0",
  "description": "Decide once at session start which model and effort a coding session should run on (the same price-gated, scope-gated decision the Amplifier orchestrator makes), and use Jev for bounded read/list decisions, source relevance search, and proposals on observed UI controls. The host keeps execution and approval authority; uncertain decisions abstain.",
  "use_cases": [
    "Decide, before a Claude Code, Codex, Copilot CLI or Amplifier session starts, whether to run it on a cheaper model and at which effort",
    "Launch Claude Code, Codex or Copilot CLI on the model and effort that decision chose",
    "Choose among caller-validated workspace read targets",
    "Measure a local decision scorer independently of an agent harness",
    "Record advisory decisions alongside parent and child session metadata",
    "Find relevant source windows in an unfamiliar directory",
    "Propose an action on caller-observed UI controls without executing it"
  ],
  "platforms": [
    "macos",
    "linux",
    "windows"
  ],
  "requires": [
    {
      "name": "TypeSafe Jev",
      "purpose": "Default remote judge; TYPESAFE_API_KEY and external-state consent required. Search also requires jg.",
      "optional": true,
      "install": "https://github.com/michaeljabbour/amplifier-bundle-fast-decisions/blob/main/docs/MODEL-SETUP.md"
    },
    {
      "name": "Cloudflare Workers AI (clef, clef-flash)",
      "purpose": "Optional opt-in remote judge (--backend/--decider clef or clef-flash); CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID and external-state consent required.",
      "optional": true,
      "install": "https://github.com/michaeljabbour/amplifier-bundle-fast-decisions/blob/main/docs/CONFIGURATION.md#judge-backends"
    },
    {
      "name": "Jevgrep 0.4.0 (jg)",
      "purpose": "Default bounded source retrieval; experimental Laya retrieval separately requires ripgrep.",
      "optional": true,
      "install": "https://github.com/dzhng/jevgrep"
    }
  ]
}
---

The library `amplifier_fast_decisions.smart_tool` holds every capability. The
CLI works from any coding-agent harness (Claude Code, Codex, OpenCode,
Amplifier, ...) with shell access. No Amplifier runtime is imported by the
portable path. The CLI and deterministic/fixture contracts are checked on
macOS, Linux, and Windows. Real local-model latency has been exercised on
macOS; other hardware and Ollama installations need their own measurements.

Two jobs. `decide` answers one question at the start of a session: run it on the
cheaper start model at medium effort, or stay on the host model unchanged. `select`
answers a bounded read/list question for a caller that already has eligible targets.
Neither decides arbitrary commands, invents tool arguments, performs compaction, or
intercepts a harness's provider loop. Both return a suggestion; the caller owns
eligibility checks, approvals, execution and evaluation of the result.

## Decide once, at session start

```bash
amplifier-fast-decisions decide --host-model claude-fable-5-1 --workspace . \
  --task "Fix the off-by-one in pagination"
# {"route": true, "model": "claude-sonnet-5", "effort": "medium", "reason": "rules_cheap", "decider": "rules", "gate": {...}, ...}
amplifier-fast-decisions launch --harness claude --host-model claude-fable-5-1 -- -p "Fix the off-by-one in pagination"
```

`decide` is the Amplifier orchestrator's turn-1 decision, callable from any harness. It runs the same code (the
price gate, the workspace-size scope gate, the rule decider R*, the task-type opt-out, the effort-by-tier/by-host rule) over the defaults in
`behaviors/fast-decisions.yaml`; nothing here has its own thresholds. A user overlay at
`~/.amplifier/fast-decisions/settings.yaml` (or `$AFAST_SETTINGS`) is deep-merged over those defaults, and
`afast doctor` shows the result. The decision is made once because switching model or effort inside a session
rewrites the provider's prompt cache. `route: false` means: run the host model unchanged. The price gate is the
reason a session on an expensive-cache host (for example Opus 5.5) is not routed: at current prices the cheaper
model would cost more there.

The result is typed: `route`, `tier`, `model` (what to run), `effort` (set it for the whole session, or null),
`reason`, `gate` (host and start-model rates, request multiplier, predicted cost ratio), `judge` (backend, status,
`p_complex`, `task_type`, duration), `workspace_files`, `scope_limit`, `latency_ms`, `usd` (estimated judge cost) and
`config_sha`. The shipped decider is the rule R* (`decider: rules`, `judge.status: not_used`): no model is asked and
no consent is needed. Route every session unless the price gate (Opus 5.5), the scope gate (more than 300 files) or
`keep_on_host` (review/explain-shaped first prompt) keeps it on the host; on Fable 5.1 the host effort is `medium`.
`--decider` selects another decider: `rules`, `always-host`, `always-cheap`, or any backend in the table below (Jev is
the opt-in judge). A remote judge receives the first 2,500 characters of the task, scrubbed of secret-shaped strings;
it needs `--allow-external-state` or `FAST_DECISIONS_ALLOW_EXTERNAL_STATE=true`. Without consent the answer falls
back to the prompt-length rule and `judge.status` says `no_consent`.

`launch --harness claude|codex|copilot` runs `decide` and then replaces itself with the harness, adding
`--model`/`--effort` (Claude Code), `-c model=... -c model_reasoning_effort=...` (Codex) or `--model` (Copilot CLI,
which has no effort control). The model flag is added only when the decision routes. Add `--dry-run` to see the
decision and the exact command. These flags are confirmed against each CLI's `--help`; a live launch of each
harness is not part of the offline checks.

## Installation and setup

Install the local dependency with the tool:

```bash
uv tool install 'amplifier-fast-decisions[local] @ git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main'
# Set TYPESAFE_API_KEY privately in the harness environment.
amplifier-fast-decisions manifest
amplifier-fast-decisions install-skill --host all
amplifier-fast-decisions select --help
```

During development use `uv tool install --editable '.[local]'` from this checkout.
`install-skill --host codex|claude|amplifier|opencode|copilot|all` adds a minimal discovery skill
to the selected user catalogs, with no overwrite of modified existing files.
Laya is experimental and requires explicit --backend laya and a separately started server. The optional
Ollama backend requires native token log probabilities. Loopback calls need no API key;
remote Laya requires HTTPS and explicit external-state consent. A missing model is an explicit
failure, never a scripted substitute. No web server starts as a side effect.

For a shared authenticated Laya endpoint, set `FAST_DECISIONS_LAYA_URL` and
`FAST_DECISIONS_LAYA_TOKEN` in the harness environment, and pass
`--allow-external-state` to each operation. See
[hosted deployment and onboarding](../../docs/HOSTED-LAYA.md).

Jev uses the existing TypeSafe backend and requires explicit external-state
consent. Set `TYPESAFE_API_KEY` in the process environment; never put it in a
request file. The optional SDK is not required: the stdlib transport is supported.

```bash
amplifier-fast-decisions select --backend jev --allow-external-state --input request.json
```

`--backend` overrides `FAST_DECISIONS_JUDGE` (`jev`, `clef`, `clef-flash`, `ollama`/`local` or `laya`; default
jev; the full list shared with the runtime and `afast configure` is under "Judge backends"). `--allow-external-state` and `--no-allow-external-state` override
`FAST_DECISIONS_ALLOW_EXTERNAL_STATE` (default false). Jev sends the bounded task,
context and candidate descriptions to TypeSafe; without consent no external
backend is constructed. The key is used only by the backend's authorization
header. `--model` defaults to `qwen3:0.6b` locally, or `TYPESAFE_DEFAULT_MODEL` /
`jev-1.13.0` for Jev. Actual returned model identity is preserved, including when
the requested name is an alias. Backend failures never switch to another model.

## Calling from any harness

Ask for `describe` to obtain the full input contract. For example, `request.json`:

```json
{"task":"Read README.md, not LICENSE.md.","candidates":[{"id":"readme","operation":"read","path":"README.md"},{"id":"license","operation":"read","path":"LICENSE.md"}],"session_id":"example-parent","harness":"other"}
```

```bash
amplifier-fast-decisions select --allow-external-state --input request.json
```

`select` returns JSON with `status: selected` and an offered `choice`, or
`status: abstain`. Check `ok`: a false value means failure and a nonzero CLI
exit. Ordinary model/policy abstention is a valid result. No target is read or
executed. Only invoke the model when that judgment is useful; calling it from
an already-running reasoning model adds a call and does not by itself save one.

For library composition, pass data directly:

```python
from amplifier_fast_decisions.smart_tool import select
result = await select({"task": "Read README.md", "candidates": [
    {"id": "readme", "operation": "read", "path": "README.md"}
]}, allow_external_state=True)
```

Optional `context` is a bounded string containing caller-provided material.
Do not have an agent rewrite it to inflate confidence. No target existence,
file permission, or symlink claim is established by this advisory tool.

## Evidence and limits

The default judge is Jev 1.13.0 with explicit external-state consent. Selection reads its scoring deadline,
score threshold and margin from the shared `Policy` of the effective configuration (3000 ms, 0.90 and 0.20 as
shipped; `diagnose` and `afast doctor` print them). Results preserve each backend's
`probability_kind` and `confidence_kind`; the numbers are not calibrated
correctness probabilities or necessarily comparable statistics across backends.
The current workload is bounded workspace-action selection.

Each invocation appends metadata to a new JSONL file under
`~/.amplifier/fast-decisions/events`, `AFAST_EVENTS_DIR`, or explicit `--events`
(the explicit argument wins). Task/context/target
paths are not logged. Caller-supplied candidate IDs and session IDs are logged:
use opaque identifiers, not secrets. Provide `session_id`, optional
`parent_session_id`, and `harness` to preserve caller lineage. These are caller
assertions, not independently verified session identity. There is no default
claim that the caller is an active session of any particular harness.

Events use `mode: advisory` and `event_source: portable-smart-tool`. A model
score proves scoring occurred. It proves neither execution nor a provider call
avoided. No fast-submission or tool-execution events are invented. For automatic
Amplifier interception use the separately configured active bundle and native
approval path. The portable interface is an advisory library/CLI surface.

Laya preserves its model-reported confidence when present; Ollama reports `not_reported`. Jev preserves
its own reported confidence semantics. `option_set_hash` is an order-sensitive
digest of the backend's presented options and ID bindings. The digest records neither actual execution nor correctness, and
is not a hash of the complete request.

## Judge backends

One list, shared by the runtime (`backend:` in the orchestrator config), `select`/`decide` and
`afast configure --backend` (`src/amplifier_fast_decisions/judge_backends.py`; a test fails if a surface drifts):

| backend | external | notes |
|---|---|---|
| `jev` | yes | shipped default. `TYPESAFE_API_KEY` |
| `clef`, `clef-flash` | yes | opt-in. Cloudflare Workers AI decision models, System One body in the Workers AI envelope. `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`; nothing is stored. Benchmark arms only (not a shipped default) until a study promotes them |
| `ollama` (`local`) | no | local token-probability scorer |
| `laya` | no (loopback) | experimental |
| `mlx`, `hosted` (`gateway`), `anyjev`, `deterministic`, `unavailable` (`none`) | varies | runtime/configure only (`select` refuses them: no scripted substitute) |

## Operational evidence

Use `diagnose` to inspect installation, effective session configuration, local model
and authenticated viewer health. Use `measure --session PARENT_ID` for execution
counts including children. Use `compare --input runs.json` for paired baseline/enabled
runs with explicit outcome checks. These capabilities invoke no model.
`diagnose --offline` also disables loopback health probes. Each command's `--help`
describes its arguments; JSON statuses, coverage and eligibility determine what
its results establish. A successful command exit alone does not prove improvement.

## Local retrieval and computer-use decisions

`search --allow-external-state --input query.json --root PUBLIC_WORKSPACE` uses
upstream Jevgrep (`jg`) with bounded source sharing. Ignore rules, source/output
limits, hidden/sensitive-path exclusions and containment checks apply. Install
`jg` as described in docs/JEVGREP.md. Experimental `--backend laya` uses a
separate local relevance implementation and requires `rg`.

`cua --allow-external-state --input ui.json` batches operation and target selection through Jev.
It returns a proposal or a reason to hand back to the host; it never clicks, types,
or verifies completion itself. Fresh state and native approvals remain mandatory.
Use `search --help` and `cua --help` for exact inputs and bounds.

Both capabilities are Python library calls in `smart_tool` and need no Amplifier runtime.
`install-skill --host opencode` also supports OpenCode's ~/.config/opencode/skills directory.
