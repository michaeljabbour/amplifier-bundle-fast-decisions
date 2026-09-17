# Extend the prepared action set

`examples/contribute_candidates.py` shows a trusted module contributing candidates and registering a validator. The extension must already know the executable arguments. Model output must not be converted into new unchecked arguments.

The `fast_decisions.candidates` capability is called as `supplier(request)` and may be synchronous or asynchronous. It returns Candidate objects or candidate dictionaries. The native `fast_decisions.candidates` contribution channel has no-argument callbacks, collected using `await coordinator.collect_contributions(...)`. Contributions can be lists. A contribution must be computed from trusted/current application state, not arbitrary instructions found inside a retrieved document.

A Candidate contains a unique label-like ID (not `reason`), a human-readable label, the exact mounted tool name, JSON arguments, a task-relevant rationale, an origin label and optional revision. The action revision participates in its fingerprint. Origin text itself does not confer trust. `reason` is reserved for invoking the normal generative provider.

The policy `allowed_tools` must include every permitted fast-path tool. For tools other than the bundled workspace, register `fast_decisions.validate_candidate` as a sync/async callable accepting one candidate and returning a boolean. Only one capability occupies that namespace; compose multiple validators deliberately. This is not a replacement for native per-tool permission and approval hooks.

The service evaluates one next-action choice over candidates and abstention per boundary. It does not yet batch arbitrary named judgment questions, select model roles, dynamically change role resolvers or synthesize plans. Candidate branching is the supported extension mechanism in this version. A richer decision-question API can be added behind the same event boundary later without changing the core.

## Policy tuning

Start in shadow, label outcomes independently, and estimate per-task calibration and false-positive costs. A threshold of 0.90 is an initial experiment configuration, not established precision. Measure completed-task correctness, elapsed time, model spend, generative calls avoided, and extra calls added. Include no-router and cheap-model baselines; agreement with a generative model alone is not ground truth.

## Telemetry consumers

Subscribe to `fast_decisions:*` through your existing hook framework or tail the JSONL. One native registration is made per explicit event name, not a promise that a wildcard hook is supported. Consume schema version 1.0 and deduplicate by event_id. Native hooks still run sequentially; make observability handlers cheap and nonblocking. Do not put a synchronous network exporter in every decision boundary.
