# Architecture and decisions

## Execution boundary

```text
Amplifier Rust-backed session / coordinator
    -> HybridOrchestrator.execute(...)
       -> StreamingOrchestrator.execute(...)  [unchanged implementation]
          -> RoutedProvider.complete(actual_chat_request, **actual_kwargs)
             -> deterministic eligibility/budget checks
             -> one bounded Jev choice over prepared candidates + reason
             -> shadow/threshold/state/revision checks
             -> fast: real ChatResponse + ToolCall envelope
             -> slow: original_provider.complete(same_request, **same_kwargs)
          -> upstream tool hooks and approvals
          -> ObservedTool.execute -> original_tool.execute
          -> upstream context bookkeeping / next iteration
```

The provider and tool mappings are copied per turn. No monkeypatching, global mounts, provider key changes, or kernel modifications are used. Upstream provider selection, model overrides and provider pins remain its responsibility; the facade does not choose another provider. Full compatibility with those upstream behaviors is a required host integration test, not inferred solely from this design.

The facade supplies only prepared arguments from trusted candidates, never arguments parsed from Jev-generated text. A synthetic response is recognizable by object identity inside the facade and parsed as its typed tool calls; native provider responses retain their original identity and parser.

The upstream loop receives tool requests in its ordinary format. A submission can still be denied or modified by native hooks. We measure actual execution in the tool facade, not in `tool:pre` because that event alone does not prove that execution occurred.

## Session-local service

Capabilities registered during mounting:

- `fast_decisions.service`: the `DecisionService` instance.
- `fast_decisions.runtime`: a `Runtime` holding that service, recorder, lifecycle and per-session execution lock.

The hook bridge reuses the existing runtime when the orchestrator already mounted. Cleanup is idempotent. Each executed turn resets its candidate-use set, fast counters and decision ID. A session-local circuit breaker can survive between turns for five seconds after a backend error.

The service's `choose(request, tools)` is orchestration-sensitive: it requires an active turn and serial use. It is not a stateless, concurrent general-purpose RPC API. Consumers should contribute prepared candidates rather than call it from parallel hooks. The independently reusable backend interface is `decide(state, candidates)`.

## State and candidates

The snapshot uses at most the latest 12 messages, bounded per-message and total size. It excludes system/developer text and private thinking blocks. It is not a rolling external memory cache. The actual request fingerprint includes messages/tools/model; no raw request is recorded in telemetry.

Candidate sources are trusted config, the `fast_decisions.candidates` capability callback, the native contribution channel of the same name, and explicitly mentioned workspace text files. Candidate arguments are copied. Duplicate conflicting IDs reject the candidate set. Tools must be present both in the request's advertised tools and the actual mounted tools and also appear in the policy allowlist.

Non-workspace tools additionally need `fast_decisions.validate_candidate`. The bundled workspace tool validates containment, excluded names, permitted operations, file revisions and size. File and conversation state are rechecked after inference. Neither eligibility nor confidence is an approval token.

## Deadlines, budgets and failures

A single cooperative asynchronous deadline covers candidate collection, inference and revalidation. Synchronous callbacks, local file-system operations or native hooks that block the event loop can exceed the wall-clock budget; this is not a hard real-time scheduler. Backend HTTP retries are disabled. A backend failure opens a five-second cooldown. Invalid labels, malformed probabilities, an abstention, stale state, missing key, unknown alternatives, no eligible candidate or a timeout return to the original generative provider.

Cancellation propagates. It does not authorize a pending action. SDK outages are not silently replaced with a scripted model. The active path cannot use a synthetic backend unless an explicit test-only policy flag is set; production configuration exposes only `jev` and `unavailable`.

The default limits are three consecutive fast submissions, twelve per turn, twelve candidate actions and a 750 ms decision deadline. Submission budgets count denied submissions too, to avoid repeating them indefinitely. Used candidate identity includes its revision and arguments.

## Observability

One event envelope is written to the recorder and emitted through `coordinator.hooks.emit`. Additional event names are contributed through Amplifier's `observability.events` channel. Event hooks carry observation only; their responses do not control the action. Native execution hooks remain upstream and retain their own semantics.

JSONL recording uses a bounded queue and a writer thread. Recorder failure is visible as health metadata but is not an authorization mechanism or durable audit guarantee. Mount failure can fail the experimental module; the baseline orchestrator should remain available as a rollback.

The web viewer polls an authenticated local read endpoint every 250 ms. Polling is intentionally simple and separate from routing latency. It supports replay without a running session. There is no browser control endpoint and no browser-to-agent execution channel.

## Deliberately not in v0.1.0

No local Jev weights, Rust kernel changes, learned action generation, autonomous stopping, model-role resolver integration, production accuracy claim, forced fleet-wide rollout, automatic transcript export, or mandatory replacement of Foundation. These are separate experiments with separate acceptance criteria.
