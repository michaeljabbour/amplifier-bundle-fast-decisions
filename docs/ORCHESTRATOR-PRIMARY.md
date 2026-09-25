# Orchestrator-primary composition (v0.2)

Starting with v0.2, composing this bundle **replaces the host's orchestrator**.
`bundle.md` includes foundation and then `behaviors/fast-decisions.yaml`. That
behavior declares `session.orchestrator: loop-fast-decisions`, which wraps
foundation's `loop-streaming` rather than reimplementing it. Under the kernel's
composition rule (later wins; `session` is deep-merged), this puts
loop-fast-decisions in charge while keeping the root's own loop-streaming
settings.

## Why the orchestrator, not a hook

Only the provider call inside the orchestrator can change a turn. Upstream
loops never honor a hook's `modify` at `tool:pre` (see `router.py` and
[UPSTREAM_CONTRACT.md](UPSTREAM_CONTRACT.md)). A hook can observe or deny, but
it cannot route effort, pick a model, or substitute a prepared action. The
evidence ([EVIDENCE.md](EVIDENCE.md)) credits the speedup to **effort and model
routing**, and both can only run in `RoutedProvider.complete()`.

## What composes where

| You compose | Orchestrator | Use |
|---|---|---|
| `bundle.md` (foundation + behavior) | loop-fast-decisions (routing-only) | the product |
| `behaviors/fast-decisions.yaml` onto your own root, via `amplifier bundle add --app` | loop-fast-decisions (app bundles compose after the root, so it wins) | keep your root, swap the loop |
| a root that `includes:` the behavior | **the root's own** (the root composes last) | declare `session.orchestrator` in the root yourself if you want the swap |
| `behaviors/fast-decisions-shadow.yaml` | untouched | observer-only measurement |
| `bundles/active*.yaml` | loop-fast-decisions with a judge rung | the older judged read-shortcut rungs |

The behavior carrying `session.orchestrator` goes against the usual
convention that behaviors do not choose the orchestrator
(foundation `BUNDLE_GUIDE.md`). The exception is deliberate: the user asked
for exactly this swap. The observer-only behavior remains for anyone who wants
the convention.

## Default policy: the turn-start difficulty router

Before a turn's first provider call, one typed question ("simple or complex?") decides the model
**and** the effort for the entire turn:

| Tier | Model | Effort | Mid-turn switches |
|---|---|---|---|
| simple ("cheap") | `model_routing.start_model` (claude-sonnet-5), Anthropic providers only (`provider_match`) | `effort_routing.by_tier.cheap` (medium) | only on a provider error (later calls in the turn move to the host model) |
| complex ("strong") | the host model: exactly plain Amplifier | provider default | none |

Why per turn, not per request: Anthropic invalidates the cached conversation when the model or the
thinking/effort parameters change. The previous cheap-first policy re-wrote the ~37k-token conversation cache (up to 235k cache-write tokens over one
SWE-bench run) on
every escalation and every effort flip. On SWE-bench that made it 1.2x plain's time and 1.4x plain's
cost (`evals/STUDY-DESIGN.md` 18.7).

**Who judges.** The shipped config is `backend: jev` (hosted TypeSafe Jev, AUC 0.83 at ~0.16 s) with
`allow_external_state: true`: the first 2,500 characters of the turn's latest user message (system reminders removed; in delegated sub-sessions,
the delegation instruction) go to the Jev endpoint.
Without `TYPESAFE_API_KEY`, or on any Jev error or timeout, the turn uses the prompt-length rule
(AUC 0.60) and nothing leaves the machine. Change it through Amplifier's sanctioned per-user override in
`~/.amplifier/settings.yaml`. No bundle edit is needed:

```yaml
overrides:
  loop-fast-decisions:
    config:
      backend: none                 # length rule only; nothing leaves the machine
      allow_external_state: false
      # local alternatives (Ollama, nothing leaves the machine):
      #   backend: ollama, model: "qwen3:8b",    timeout_ms: 3000   # AUC 0.72 at ~0.36 s
      #   backend: ollama, model: "qwen:latest", timeout_ms: 8000   # AUC 0.85 at ~2.5 s
      # another Jev System One-compatible server:
      #   backend: jev, jev_url_env: MY_URL_VAR, jev_key_env: MY_KEY_VAR,
      #   model: <name>, backend_label: <dashboard name>
```

Measured trade-off to keep in mind: on the 12 everyday tuning tasks the current Jev default ran at 0.56–0.57x
time / 0.46–0.48x cost (two batches), against 0.55x / 0.38x for the length rule in an earlier batch, because Jev sent
about one turn in four to the host model while the rule kept all of them on Sonnet. Jev is the better judge of difficulty (AUC 0.83 vs 0.60); the length rule was cheaper on tasks
that were all easy. Re-measure on your own mix with `afast savings`.

**Savings.** `afast savings [--since 7d] [--json]` and the observatory's savings panel estimate what
routing saved: every cheaper-model turn's recorded tokens priced at host-model rates (the provider's
own `cost_usd` is the actual when recorded), and its model time scaled by the measured host/start
generation-rate ratio once both models have 20+ measured requests. Host-model turns run the standard
setup and save nothing. These are estimates, not matched comparisons; after a session's first turn the host is assumed to have the
conversation cached (a cheap turn's cache writes are priced as host cache reads), and a host turn right after a cheap
turn is charged its cache rebuild; rate samples need at least 200 output tokens; the eval suites remain the
evidence for net savings and quality.

The AUCs are measured by `evals/difficulty/probe.py` on SWE-bench Verified human difficulty labels.
Local judges answer typed questions from first-token letter mass, with a chat prefill and permutation
debiasing (`local_backend.py`). qwen3:0.6b cannot do this judgment (AUC 0.50).

**Other defaults.**
- `read_shortcut: false`: the judged read shortcut rarely fired in the studies, and it would put a
  scoring call in front of every slow request.
- `provider_match: anthropic`: the start model id is never sent to a non-Anthropic provider.
- Sub-sessions inherit the parent's orchestrator and config, so delegated agents are routed too.

**Evidence** (details in `docs/RESULTS-2026-09-24.md`, update at the top):

| Suite | Current default vs plain (same host): time | cost | quality |
|---|---|---|---|
| S1 holdout (8 × 3 reps, preregistered), host Fable 5.1 | 0.42x [0.35-0.50] | 0.50x | 24/24 vs 24/24 (confirmed) |
| S1 holdout (8 × 3 reps, preregistered), host Opus 5.5 | 1.01x [0.86-1.17] | 0.98x | 24/24 vs 24/24 (no effect) |
| S3 SWE-bench Verified (10 × 2 reps), scope gate → host model | 1.00x | 0.98x | 13/20 vs 14/20 |

Before the scope gate, the Jev router on S3 (10 × 3 reps) ran 0.86x / 0.91x but fixed 19/30 vs 23/30.

## Staying compliant while replacing loop-streaming

| Obligation | How |
|---|---|
| The root's loop-streaming config (e.g. foundation's `extended_thinking: true`) | deep-merged to our top level; `orchestrator.upstream_config` forwards loop-streaming's own keys (and `goal_*`) to the wrapped loop; an explicit `upstream:` block wins |
| `session.steer`, `conversation.provider_pin` capabilities; loop-streaming observability event names | `_register_upstream_capabilities`: exactly what upstream `mount()` registers (we build the loop directly, so its `mount()` never runs) |
| `execution:end` on every exit path | loop-streaming skips it on early returns and exceptions; `HybridOrchestrator` observes `execution:start/end` and backfills a missing end (`source: loop-fast-decisions`) |
| Native events, hooks, approvals, cancellation, context, compaction | unchanged: all delegated to the wrapped loop |
| Custom events registered | `fast_decisions:*` via the `observability.events` contributor (unchanged) |

## Dashboard

The observatory now launches from the orchestrator's `mount()` (a
`session:start` handler shared with the hook through
`observer.install_auto_observatory`). A runtime flag makes sure only one
launcher is installed per session, even when both modules are mounted. When
the orchestrator owns the runtime, the hook's shadow scorer and role router
stand down, because they would only re-score what the orchestrator already
decided. The hook stays in the behavior for session presence (the heartbeat and
the native-event bridge the viewer's session list uses).

## Measuring it

`evals/cells.yaml` adds these cells, all built with `--fd-composition composed`.
That profile includes the frozen bundle root and **never names the orchestrator
module**. `model_routed` and `effort_routed` receipts therefore prove that
composition did the swap, and `effective-loop-config.json` records the config
the run actually got.

| Cell | Question |
|---|---|
| `orch-primary` | the product as shipped vs `plain` (anchor) and `plain-sonnet` (confound control) |
| `orch-primary-effort-only` | ablation: how much is the sonnet start model vs phase effort? |
| `orch-primary+jev` | does the judged read shortcut on top help, hurt or do nothing? |
| `orch-primary-monotonic` | cache-aware effort (never step effort down within a turn) |
| `orch-router-jev` | the turn-start difficulty router judged by Jev |

```bash
python3 evals/run.py --suite s1 --split dev \
  --cells plain,plain-sonnet,orch-primary,orch-primary-effort-only --reps 3 \
  --candidate-sha "$(git rev-parse HEAD)" --parallel 3 \
  --out .amplifier/evaluation/fast-decisions/$(date -u +%Y%m%dT%H%M%SZ)
```

A one-repetition dev run is a screen, not a finding (`evals/STUDY-DESIGN.md`
section 8). Confirmation needs a preregistered holdout (`PREREGISTRATION.md`).
