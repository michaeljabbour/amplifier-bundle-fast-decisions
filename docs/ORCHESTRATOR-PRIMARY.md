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
| simple ("cheap") | `model_routing.start_model` (claude-sonnet-5), Anthropic providers only (`provider_match`) | `effort_routing.by_tier.cheap` (medium) | escalation on test failure, provider error or after 6 requests |
| complex ("strong") | the host model: exactly plain Amplifier | provider default | none |

Why per turn, not per request: Anthropic invalidates the cached conversation when the model or the
thinking/effort parameters change. The previous cheap-first policy re-wrote a 37k–235k-token cache on
every escalation and every effort flip. On SWE-bench that made it 1.2x plain's time and 1.4x plain's
cost (`evals/STUDY-DESIGN.md` 18.7).

**Who judges.** The shipped config is `backend: none`: a prompt-length rule decides (AUC 0.60) and
nothing leaves the machine. Upgrade through Amplifier's sanctioned per-user override in
`~/.amplifier/settings.yaml`. No bundle edit is needed:

```yaml
overrides:
  loop-fast-decisions:
    config:
      backend: jev                  # TypeSafe Jev (needs TYPESAFE_API_KEY), AUC 0.83 at ~0.2 s
      allow_external_state: true    # explicit consent: the task text goes to the judge
      # local alternatives (Ollama, nothing leaves the machine):
      #   backend: ollama, model: "qwen3:8b",    timeout_ms: 3000   # AUC 0.72 at ~0.36 s
      #   backend: ollama, model: "qwen:latest", timeout_ms: 8000   # AUC 0.85 at ~1-2.5 s
```

The AUCs are measured by `evals/difficulty/probe.py` on SWE-bench Verified human difficulty labels.
Local judges answer typed questions from first-token letter mass, with a chat prefill and permutation
debiasing (`local_backend.py`). qwen3:0.6b cannot do this judgment (AUC 0.50).

**Other defaults.**
- `read_shortcut: false`: the judged read shortcut rarely fired in the studies, and it would put a
  scoring call in front of every slow request.
- `provider_match: anthropic`: the start model id is never sent to a non-Anthropic provider.
- Sub-sessions inherit the parent's orchestrator and config, so delegated agents are routed too.

**Evidence so far** (screens, 1 rep; confirmation at 3 reps running):

| Suite | Router (Jev) vs plain: time | cost | quality |
|---|---|---|---|
| S1 simple (12 tasks) | 0.61x | 0.55x | 12/12 vs 12/12 |
| S3 SWE-bench Verified (10) | 0.90x | 0.94x | 7/10 vs 7/10 |

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

`evals/cells.yaml` adds three cells, all built with `--fd-composition composed`.
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
