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

The service's `choose(request, tools)` is orchestration-sensitive: it requires an active turn and serial use. It is not a stateless, concurrent general-purpose RPC API. Consumers should contribute prepared candidates (and questions) rather than call it from parallel hooks. The independently reusable backend interface is `ask(request: DecisionRequest) -> DecisionResult`: one batched call carrying the action candidates plus every contributed judgment question, scored independently by the vendor in a single request.

## Shadow measurement (the hook, not the orchestrator)

`hooks-fast-decisions` composes onto **any** orchestrator, including the untouched upstream loop, to measure "what would we have chosen" without ever touching the turn. This is the shipped default (`bundle.md`, `behaviors/fast-decisions.yaml`, config `mode: shadow`): no orchestrator swap is required to get shadow telemetry.

```text
provider:request  -> snapshot (context mount, candidates, hashing) -- ON the critical path, hard-bounded
                   -> enqueue ShadowJob onto Runtime's shadow worker -- OFF the critical path
tool:pre          -> resolve the pending job into a ShadowOutcome; emit shadow_observed
worker (background) -> score the job against the backend; emit shadow_proposed, then shadow_agreement
execution:end     -> sweep any proposal that never saw a matching tool:pre this turn
```

The snapshot reads the mounted context manager (`coordinator.get("context")`), not the request object -- `provider:request` carries no request, so this is the only available seam. That view is close to, but not identical to, what the orchestrator actually dispatches (injections/compaction apply later); every shadow record carries `state_source` so an eval never silently mixes the two. The snapshot is bounded by `shadow_max_messages` (messages read), `max_state_chars` (total snapshot size) and `shadow_snapshot_budget_ms` (wall clock, enforced with `asyncio.timeout`); exceeding any of them abandons the snapshot, counts `shadow_snapshot_budget_exceeded`, and returns `continue` -- never an exception into the hook chain.

Policy ownership: the orchestrator, when present, is the sole owner of `Policy` (mode, thresholds, allowed tools) via `get_runtime(..., owner=True)`. The hook never requests ownership and cannot make `mode: active` stick (it downgrades to `shadow` and emits `fallback` with `hook_cannot_own_active` if its own config asks for it). Mount order across module types is a documented, guaranteed kernel contract (orchestrator mounts before hooks within a session), so no race exists between the two mounting the shared `Runtime` -- the owner re-apply in `get_runtime` is defensive, covering only out-of-session construction (unit tests, `afast demo`, a future non-kernel host).

The shadow worker is a single background `asyncio.Task` owned by `Runtime`: created lazily (on first submit, so construction outside a running event loop is safe), drained with a bounded budget (`shadow_drain_ms`, default 2s) and then cancelled in `Runtime.close()`, so no shadow work outlives the session and no task is left pending at interpreter exit.

`bundles/shadow.yaml` is retained for one release cycle as a **deprecated forwarding bundle**: it composes `bundle.md` unchanged and no longer swaps `session.orchestrator`. `bundles/active.yaml` remains the only standalone bundle that swaps the orchestrator, because that is a root-bundle concern.

## State and candidates

The snapshot uses at most the latest 12 messages, bounded per-message and total size. It excludes system/developer text and private thinking blocks. It is not a rolling external memory cache. The actual request fingerprint includes messages/tools/model; no raw request is recorded in telemetry.

Candidate sources are trusted config, the `fast_decisions.candidates` capability callback, the native contribution channel of the same name, and explicitly mentioned workspace text files. Candidate arguments are copied. Candidates are collected as groups, one per contributor; a group with an internal or cross-group conflicting ID is dropped in full and counted (`contribution_conflict`) -- it cannot remove another contributor's candidates. The surviving set is serialised in canonical `(origin, id)` order; a `candidate_order_hash` digest of that order is computed once per request and appears on `requested`/`scored`. Tools must be present both in the request's advertised tools and the actual mounted tools and also appear in the policy allowlist.

Judgment questions (`fast_decisions.questions`, new) follow the identical per-contributor rejection model, bounded by `max_questions` (default 8) with `choice` questions further bounded to 2..255 criteria. Both channels are validated and truncated inside the same shared decision deadline, and both feed the single batched `ask()` call -- one backend request per state regardless of question count.

The model-role router (P4) is a second, independent consumer of the same shadow measurement path: at `delegate` calls it proposes a `model_role`, records it against what the delegate actually resolved, and never mutates the call (the upstream loop does not honor `modify` at `tool:pre`, so an active router through this seam is not just undesired but structurally impossible today). It is off by default (`role_router: false`), reads `model_role_resolver` read-only to enumerate live roles once per session, and never reads or writes `conversation.provider_pin`.

Non-workspace tools additionally need `fast_decisions.validate_candidate`. The bundled workspace tool validates containment, excluded names, permitted operations, file revisions and size. File and conversation state are rechecked after inference. Neither eligibility nor confidence is an approval token.

## Deadlines, budgets and failures

A single cooperative asynchronous deadline covers candidate collection, inference and revalidation. Synchronous callbacks, local file-system operations or native hooks that block the event loop can exceed the wall-clock budget; this is not a hard real-time scheduler. Backend HTTP retries are disabled. A backend failure opens a five-second cooldown. Invalid labels, malformed probabilities, an abstention, stale state, missing key, unknown alternatives, no eligible candidate or a timeout return to the original generative provider.

Cancellation propagates. It does not authorize a pending action. SDK outages are not silently replaced with a scripted model. Production configuration exposes three `backend` choices -- `jev`, `deterministic` (in-process, offline, `external=False`, never gated by `allow_external_state`; the shipped shadow default) and `unavailable`. The active path cannot submit a synthetic decision unless the explicit `allow_synthetic_active` policy flag is set, regardless of which backend produced it.

The default limits are three consecutive fast submissions, twelve per turn, twelve candidate actions and a 750 ms decision deadline. Submission budgets count denied submissions too, to avoid repeating them indefinitely. Used candidate identity includes its revision and arguments.

## Observability

One event envelope is written to the recorder and emitted through `coordinator.hooks.emit`. Additional event names are contributed through Amplifier's `observability.events` channel. Event hooks carry observation only; their responses do not control the action. Native execution hooks remain upstream and retain their own semantics.

JSONL recording uses a bounded queue and a writer thread. Recorder failure is visible as health metadata but is not an authorization mechanism or durable audit guarantee. Mount failure can fail the experimental module; the baseline orchestrator should remain available as a rollback.

The web viewer polls an authenticated local read endpoint every 250 ms. Polling is intentionally simple and separate from routing latency. It supports replay without a running session. There is no browser control endpoint and no browser-to-agent execution channel.

## Deliberately not in v0.1.0

No local Jev weights, Rust kernel changes, learned action generation, autonomous stopping, an *active* model-role router (shadow-only only -- see P4), production accuracy claim, forced fleet-wide rollout, automatic transcript export, or mandatory replacement of Foundation. These are separate experiments with separate acceptance criteria.
