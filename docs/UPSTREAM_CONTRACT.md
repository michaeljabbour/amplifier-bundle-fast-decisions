# Upstream contract: what we rely on in `loop-streaming`

This bundle wraps `amplifier_module_loop_streaming.StreamingOrchestrator` (the "upstream loop").
We do not vendor it, patch it, or reimplement it (see `docs/design/redesign-2026-09-17.md` §P2 for
the rationale: re-implementing the steering queue, ephemeral-injection modes, measured-context
transactions/rollback, provider budget preflight, context-overflow recovery, the `/goal`
auto-continue loop, cancellation exits, `conversation.provider_pin`, and `provider:resolve` would be
a standing complexity-budget violation, and it would make every upstream improvement a merge for us).

We depend on exactly the following four items. Anything outside this list is **not** ours to rely
on, and a change to it does not obligate upstream to warn us. `tests/test_upstream_contract.py`
asserts each item against the **installed** module in the real-kernel test lane, so a breaking
upstream change fails a test instead of silently breaking a user session.

## 1. Constructor

`StreamingOrchestrator(config: dict)` -- a plain dict. Unknown keys are ignored.

```python
StreamingOrchestrator({"max_iterations": 3})  # constructs without error
```

## 2. `execute()` signature

```python
async def execute(prompt, context, providers, tools, hooks, **kwargs) -> str
```

Matches `amplifier_core.interfaces.Orchestrator`. Accepts `coordinator=` in kwargs (we always pass
one via `kwargs.setdefault("coordinator", self.coordinator)` in `HybridOrchestrator.execute`).

## 3. Transport feature-detection and dispatch

Transport selection is `stream_provider = callable(getattr(provider, "stream", None))`. The
`complete()` branch (taken when this is `False`) is the one that parses and dispatches tool calls.
The `stream()` branch cannot: `_has_pending_tools` is hard-coded to return `False` ("Simplified -
would need to track tool calls properly") and `_process_tools` has no body on that path. A tool call
arriving on the stream transport is silently dropped -- this is why `RoutedProvider` never attempts
the fast path on `stream()` (see `docs/COMPATIBILITY.md`, "Transport tradeoff").

## 4. Tool dispatch

Tools are invoked as `await tool.execute(tool_call.arguments)` -- a single positional dict, no
keyword arguments. `tool:pre` fires before dispatch and `tool:post` fires after. A `tool:pre` hook
result's `deny` action is honored (via `coordinator.process_hook_result`); `modify` is **not**
honored -- the tool always executes with the original, unmodified arguments. A hook can observe and
block a tool call, never substitute one.

---

## Event ordering (must be understood by anything correlating our events with upstream's)

Our `fast_decisions:turn_start` is emitted in `HybridOrchestrator.execute` *before* we delegate to
`upstream.execute(...)`, so it **precedes** upstream's `execution:start`. Symmetrically,
`fast_decisions:turn_end` fires in our `finally` block, *after* upstream's `execution:end` (and
after `orchestrator:complete`). This is deliberate: our events bracket the whole delegation,
including the upstream call itself. Anything correlating the two event streams by wall-clock order
needs to know this -- do not assume `fast_decisions:turn_start` and `execution:start` are
interchangeable markers of "turn began."

Observed ordering for a single-tool-call turn:

```
fast_decisions:turn_start
execution:start
provider:request        (iteration 1)
tool:pre
tool:post
provider:request        (iteration 2)
execution:end
orchestrator:complete
fast_decisions:turn_end
```

`tests/test_lifecycle_events.py::test_event_ordering_note` asserts this ordering against the
installed module.

## What we do not emit

We emit none of the native lifecycle events (`execution:start` / `execution:end` /
`orchestrator:complete` / `provider:request` / `tool:pre` / `tool:post`). They are emitted by
`loop-streaming` and guaranteed by delegating to `upstream.execute()`. Emitting our own copies would
double-fire for every consumer of those events (`hooks-logging`, `amplifierd`'s `MetadataSaveHook`,
`amplifier-voice`). Our own events stay in the `fast_decisions:` namespace.
