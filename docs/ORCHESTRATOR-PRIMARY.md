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

## Default policy: routing-only

```yaml
mode: active
backend: none            # no judge; set jev (+ allow_external_state) or ollama to add the read shortcut
effort_routing: {orient: medium, explore: low, implement: high, ...}
model_routing:  {start_model: claude-sonnet-5, provider_match: anthropic, max_requests_before_escalation: 6,
                 escalate_on_test_failure: true, escalate_on_provider_error: true}
```

- **`backend: none`** (an alias of `unavailable`). `DecisionService.choose`
  routes slow with `reason_code: judge_disabled` before collecting candidates,
  so no state is built and no circuit breaker trips. The judged read shortcut
  rarely fired in the studies, and a judge call sits in front of every slow
  request, so the default leaves it off.
- **`provider_match: anthropic`**. The start model is applied only to providers
  whose mount key or name contains `anthropic`. On a root with several
  providers, an Anthropic model id is never sent to an OpenAI or vLLM provider
  (`reason_code: provider_not_matched`).
- **Sub-sessions** inherit the parent's orchestrator and config (app-cli's
  `session_spawner`), so delegated agents are routed too.

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

```bash
python3 evals/run.py --suite s1 --split dev \
  --cells plain,plain-sonnet,orch-primary,orch-primary-effort-only --reps 3 \
  --candidate-sha "$(git rev-parse HEAD)" --parallel 3 \
  --out .amplifier/evaluation/fast-decisions/$(date -u +%Y%m%dT%H%M%SZ)
```

A one-repetition dev run is a screen, not a finding (`evals/STUDY-DESIGN.md`
section 8). Confirmation needs a preregistered holdout (`PREREGISTRATION.md`).
