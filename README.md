# Fast Decisions

Fast Decisions is a decision layer for coding-agent harnesses. Rather than send
every step of a session to a large generative model, it hands the small, bounded
decisions -- which file to read, how much reasoning effort a phase needs, whether
a turn still fits on a cheaper model -- to a fast judge: a tiny local classifier
you run yourself, or [Jev](https://typesafe.ai). The judge substitutes a prepared
read-only action for a full LLM turn, routes thinking effort by phase, and can
start a turn on a cheap model that escalates on evidence. Amplifier is the
first-class integration; Claude Code, Codex and OpenCode call the same service as
a portable [Smart Tool](docs/SMART-TOOL.md).

Experimental v0.1.0, MIT licensed, benchmark evidence in
[docs/EVIDENCE.md](docs/EVIDENCE.md); no result here is a production SLA, and this
is not an official Microsoft or TypeSafe release. **A fast judgment is not a
permission grant, and a proposed action is not an executed action**: the
orchestrator composes the upstream streaming loop rather than replacing it, and
permissions, approvals and execution stay upstream.

## Results at a glance

40 aider-polyglot exercises, one repetition each, same machine (2026-09-20):

| Configuration | Passed | Median working time |
|---|---|---|
| Amplifier, plain | 40/40 | 100 s |
| Amplifier + fast-decisions, local judge | 40/40 | 51 s |
| Amplifier + fast-decisions, judge + routing | 40/40 | 26 s |
| Amplifier, plain, on `claude-sonnet-5` (control) | 39/40 | 128 s |
| Codex | 37/40 | 35 s |
| Claude Code | 35/40 | 28 s |
| OpenCode | 24/40 | 28 s |

One repetition, screen-grade; repetition-confirmed results pending. The
plain-on-sonnet control is slower and no more correct than the routed
configuration, so the gain is not attributable to the cheaper model alone.
Protocol: [evals/STUDY-DESIGN.md](evals/STUDY-DESIGN.md); full numbers and limits:
[docs/EVIDENCE.md](docs/EVIDENCE.md); earlier 20-prompt battery:
[docs/BATTERY-2026-09-18.md](docs/BATTERY-2026-09-18.md).

## Quick start

Requires a local judge: install [Ollama](https://ollama.com/download), then
`ollama pull qwen3:0.6b` (or let the recipe below do it).

**Amplifier.** Install one of the two rungs:

```bash
# judge-only fast path (incumbent default)
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=bundles/active.yaml"
# judge + phase effort routing + opt-in model routing/escalation
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=bundles/active-routing.yaml"
```

The routing rung needs a provider that serves `claude-sonnet-5` alongside the
pinned judge model. Or ask an Amplifier session to run the
[`make-amplifier-faster` recipe](recipes/make-amplifier-faster.yaml): it checks the
machine, installs Ollama and the judge model, and installs a rung behind an
approval gate (`profile: routing` picks the second).

**Any other harness.** The decision service is a callable Smart Tool, verified
from Claude Code, Codex, OpenCode and Amplifier ([docs/SMART-TOOL.md](docs/SMART-TOOL.md)):

```bash
uvx --from git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions amplifier-fast-decisions --help
```

To measure before switching anything, install the app behavior instead: shadow
measurement, orchestrator untouched. See
[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md), which also covers the no-key
demo and the optional Jev test.

## How it works

- At an eligible `Provider.complete()` boundary the judge may return a
  **prepared tool-call envelope** instead of calling the generative provider;
  the upstream loop handles that envelope normally.
- Prepared actions are **read/list only** under an explicit workspace root --
  never arbitrary commands or free-form tool arguments.
- **Effort by phase:** orient / explore / implement each get their own
  reasoning-effort setting, set by deterministic rules or by the judge.
- **Cheap-first model routing:** a turn starts pinned to a cheaper model and
  escalates on failure signals -- test failures, provider errors, request count,
  or a judge decision.
- **Confidence gates:** each judged decision has a probability floor and a margin
  requirement, scaled by what being wrong costs; below the gate it routes slow.
  Phase and escalation asks due together are batched into one judge call.
- **Receipts:** every decision emits versioned `fast_decisions:*` events --
  proposed, happened, why -- read by the observatory and `afast bench`.
- **Privacy default:** nothing leaves the machine; an external backend is
  constructed only after an explicit `allow_external_state` opt-in.

Mechanism detail and non-goals: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Judges

Select with `backend` in config or `FAST_DECISIONS_JUDGE` in the environment;
profile config wins. Measured figures are one run per judge on the checked-in
decision suites ([docs/EVIDENCE.md](docs/EVIDENCE.md)); agreement is against suite
labels, not independent correctness.

| Judge | What it is | Measured | State leaving the machine |
|---|---|---|---|
| **Local** | Ollama (default, `qwen3:0.6b`), Apple MLX (Apple Silicon), or Laya (typed-decision classifier) | Ollama 0.75-0.80 @ ~23 ms; Laya 0.60-0.63 @ ~10 ms; MLX 8-bit 0.70-0.88 @ ~105 ms | None -- loopback only |
| **Hosted** | Any OpenAI-compatible endpoint you control that returns `top_logprobs`; a tiny-Qwen deployment package is in [`deploy/hosted-judge/`](deploy/hosted-judge/) | Same model as the local judge; latency is your network | The bounded decision state, gated by `allow_external_state` |
| **Jev** | [typesafe.ai](https://typesafe.ai)'s hosted judge (external service) | 1.00 @ ~190 ms with keep-alive | Same bounded decision state, gated by `allow_external_state` |

Setup and tuning: [docs/MODEL-SETUP.md](docs/MODEL-SETUP.md). Per-backend data
paths: [docs/PRIVACY.md](docs/PRIVACY.md).

## Configuration

Copy [`.env.example`](.env.example) to `.env` and edit:

| Variable | Default | Meaning |
|---|---|---|
| `FAST_DECISIONS_JUDGE` | `local` | `local` / `hosted` / `jev` / `deterministic` |
| `FAST_DECISIONS_LOCAL_HOST` / `_MODEL` | `ollama` / `qwen3:0.6b` | Local judge host (`ollama`, `mlx`, `laya`) and its model; `mlx`/`laya` also take a loopback `_MLX_URL` / `_LAYA_URL` |
| `FAST_DECISIONS_HOSTED_URL` / `_MODEL` / `_TOKEN` | unset | Hosted judge endpoint, model, and API token (token from the environment only, never logged) |
| `FAST_DECISIONS_ALLOW_EXTERNAL_STATE` | `false` | Must be true before any external backend is contacted |
| `TYPESAFE_API_KEY` | unset | Required only for the Jev backend |
| `AFAST_EVENTS_DIR` | `~/.amplifier/fast-decisions/events` | Where decision telemetry is recorded and read |

Every policy key a bundle or profile can set -- modes, deadlines, budgets, effort
routing, model routing, confidence gates -- is in
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Observatory

A loopback-only viewer of the decision ledger: one row per
decision, showing what the judge proposed, what the recorded events say
happened, and a labelled verdict -- metadata only, no prompts, tool contents or
private reasoning. `afast serve` starts (or reuses) it, `afast serve --stop`
stops it. Event semantics, and what a row does not establish:
[docs/EVENTS.md](docs/EVENTS.md).

## Development

```bash
uv pip install -e '.[test]'
python3 -m unittest discover -s tests -v          # test suite
python3 -m amplifier_fast_decisions doctor        # environment health check
afast bench suite suites/v1.jsonl --json          # offline decision suite
```

Benchmark cells live in [`evals/`](evals/README.md), metric definitions in
[docs/BENCH.md](docs/BENCH.md), diagnostics/receipts/trace replay and the developer
map in [docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md). Also
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Compatibility and current limits

**Read this before production use:** [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

- Active decisions run at the upstream `complete()` boundary. A provider's
  optional `.stream` transport is preserved, defers to the original provider,
  and has no fast path.
- Real Rust-backed sessions, live Jev accuracy/latency, Foundation loading,
  approval/steering combinations and your provider set were not exercised in the
  build sandbox; test them on your machine.
- Only prepared actions are accelerated: free-form tool argument synthesis,
  autonomous stopping, distributed telemetry aggregation and native Rust
  inference are not implemented. Confidence thresholds are uncalibrated
  experimental settings, not safety guarantees.
- Deterministic logic handles eligibility, budget and fallback checks; it does not
  execute application actions. The observer-only behavior reports native hook
  metadata, not fabricated decisions or tool durations.
- The source pins identify indexed source snapshots, not a locked, tested
  dependency graph; Foundation's transitive dependencies stay floating.

## License

MIT. See [LICENSE](LICENSE).
