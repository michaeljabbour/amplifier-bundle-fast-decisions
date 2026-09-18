---
{
  "smart_tool_format": 1,
  "name": "amplifier-fast-decisions",
  "version": "0.1.0",
  "description": "Suggests a prepared read or list action using a bounded local model call. Use when a harness has eligible workspace targets and wants a fast advisory choice with explicit abstention.",
  "use_cases": ["Choose among caller-validated workspace read targets", "Measure a local decision scorer independently of an agent harness", "Record advisory decisions alongside parent and child session metadata"],
  "platforms": ["macos", "linux", "windows"],
  "requires": [{"name": "ollama", "purpose": "Runs the local model for select. Without it, manifest, describe and help still work.", "optional": true, "install": "https://docs.ollama.com/"}]
}
---

The library `amplifier_fast_decisions.smart_tool` holds every capability. The
CLI works from Claude Code, Codex, Amplifier, or another harness with shell
access. No Amplifier runtime is imported by the portable path. The CLI and deterministic/fixture contracts are checked on macOS, Linux, and
Windows. Real local-model latency has been exercised on macOS; other hardware
and Ollama installations need their own measurements.

Use this when the caller already has eligible read/list targets. It does not
decide arbitrary commands, invent tool arguments, perform compaction, or
intercept a harness's provider loop. It returns a suggestion; the caller owns
eligibility checks, approvals, execution and evaluation of the result.

## Installation and setup

Install the local dependency with the tool:

```bash
uv tool install 'amplifier-fast-decisions[local] @ git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main'
ollama pull qwen3:0.6b
amplifier-fast-decisions manifest
amplifier-fast-decisions install-skill --host all
amplifier-fast-decisions select --help
```

During development use `uv tool install --editable '.[local]'` from this checkout.
`install-skill --host codex|claude|amplifier|all` adds a minimal discovery skill
to the selected user catalogs, with no overwrite of modified existing files.
Start Ollama and warm the model before latency-sensitive calls. The adapter
requires native generate token log probabilities. No API key is required; the
only endpoint accepted is literal loopback HTTP. A missing model is an explicit
failure, never a scripted substitute. No web server starts as a side effect.

## Calling from any harness

Ask for `describe` to obtain the full input contract. For example, `request.json`:

```json
{"task":"Read README.md, not LICENSE.md.","candidates":[{"id":"readme","operation":"read","path":"README.md"},{"id":"license","operation":"read","path":"LICENSE.md"}],"session_id":"example-parent","harness":"other"}
```

```bash
amplifier-fast-decisions select --input request.json
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
]})
```

Optional `context` is a bounded string containing caller-provided material.
Do not have an agent rewrite it to inflate confidence. No target existence,
file permission, or symlink claim is established by this advisory tool.

## Evidence and limits

The default model is Qwen3:0.6b, with a 500 ms scoring deadline, score threshold
0.90 and margin 0.20. Its token scores are uncalibrated. The current workload
is bounded workspace-action selection, not Jev architecture replication.

Each invocation appends metadata to a new JSONL file under
`~/.amplifier/fast-decisions/events` or explicit `--events`. Task/context/target
paths are not logged. Caller-supplied candidate IDs and session IDs are logged:
use opaque identifiers, not secrets. Provide `session_id`, optional
`parent_session_id`, and `harness` to preserve caller lineage. These are caller
assertions, not independently verified session identity. There is no default
claim that the caller is an active Amplifier session.

Events use `mode: advisory` and `event_source: portable-smart-tool`. A model
score proves scoring occurred. It proves neither execution nor a provider call
avoided. No fast-submission or tool-execution events are invented. For automatic
Amplifier interception use the separately configured active bundle and native
approval path. The portable interface is an advisory library/CLI surface.

Successful selections also return `confidence_kind: not_reported` and
`option_set_hash`, an order-sensitive digest of the local model's presented options
and ID bindings. The digest records neither actual execution nor correctness, and
is not a hash of the complete request.
