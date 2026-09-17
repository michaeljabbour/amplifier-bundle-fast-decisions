# Extend the prepared action set

`examples/contribute_candidates.py` shows a trusted module contributing candidates and registering a validator. The extension must already know the executable arguments. Model output must not be converted into new unchecked arguments.

The `fast_decisions.candidates` capability is called as `supplier(request)` and may be synchronous or asynchronous. It returns Candidate objects or candidate dictionaries. The native `fast_decisions.candidates` contribution channel has no-argument callbacks, collected using `await coordinator.collect_contributions(...)`. Contributions can be lists. A contribution must be computed from trusted/current application state, not arbitrary instructions found inside a retrieved document.

A Candidate contains a unique label-like ID (not `reason`), a human-readable label, the exact mounted tool name, JSON arguments, a task-relevant rationale, an origin label and optional revision. The action revision participates in its fingerprint. Origin text itself does not confer trust. `reason` is reserved for invoking the normal generative provider.

The policy `allowed_tools` must include every permitted fast-path tool. For tools other than the bundled workspace, register `fast_decisions.validate_candidate` as a sync/async callable accepting one candidate and returning a boolean. Only one capability occupies that namespace; compose multiple validators deliberately. This is not a replacement for native per-tool permission and approval hooks.

The service evaluates one next-action choice over candidates and abstention per boundary, batched in a single backend request with every contributed judgment question (see below). It does not synthesize plans or actively change model routing. Candidate branching and contributed questions are the supported extension mechanisms in this version.

## Contributing judgment questions

`fast_decisions.questions` is the native contribution channel for bounded judgment questions, evaluated in the *same* batched backend request as the action choice -- one request per state regardless of how many questions are attached. Register a no-argument callback returning a list of `Question` objects or dictionaries:

```python
coordinator.register_contributor("fast_decisions.questions", "my-module", lambda: [
    {"name": "needs_fresh_context", "type": "noul",
     "instructions": "Is the workspace state in the observations stale for this task?"},
    {"name": "risk", "type": "score",
     "instructions": "How risky is acting without another LLM turn? 0 safe, 1 dangerous."},
])
```

A `Question` has a `name` (`^[a-z][a-z0-9_]{0,31}$`, never `next_action`), a `type` matching the vendor's own primitives (`choice`, `score`, `noul` -- no translation table), `instructions` (<=512 chars), and `criteria` (a `choice`-only dict of 2..255 labels). The service adds `next_action` itself; contributed questions never include it.

Bounded by `max_questions` (default 8, `0` disables contributed questions entirely). Malformed or conflicting contributions from one module are dropped and counted (`contribution_shape_invalid`, `contribution_conflict`, `contribution_truncated`, `question_criteria_invalid`) -- they never disable the fast path for other contributors' candidates or questions. As with candidates, this is extensibility, never authority: contributing a question grants no execution rights.

## The model-role router (shadow-only)

`hooks-fast-decisions` also runs a shadow-only model-role router (P4): at `delegate` calls it proposes a `model_role` and records it against what the delegate actually resolved, without ever changing the call. It is opt-in (`role_router: false` by default) and reads the `model_role_resolver` capability, when one is mounted (e.g. by a routing-matrix bundle), purely to enumerate live roles -- an explicit `model_role` on the call always makes it abstain, and it never reads or writes `conversation.provider_pin`.

## Policy tuning

Start in shadow, label outcomes independently, and estimate per-task calibration and false-positive costs. A threshold of 0.90 is an initial experiment configuration, not established precision. Measure completed-task correctness, elapsed time, model spend, generative calls avoided, and extra calls added. Include no-router and cheap-model baselines; agreement with a generative model alone is not ground truth.

## Telemetry consumers

Subscribe to `fast_decisions:*` through your existing hook framework or tail the JSONL. One native registration is made per explicit event name, not a promise that a wildcard hook is supported. Consume schema version 1.0 and deduplicate by event_id. Native hooks still run sequentially; make observability handlers cheap and nonblocking. Do not put a synchronous network exporter in every decision boundary.
