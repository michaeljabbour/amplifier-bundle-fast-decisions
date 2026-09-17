# Event contract v1.0

Schema: `schemas/event.schema.json`. Names are added through the native `observability.events` contribution channel. Native events are not renamed or replaced.

Every event has `schema_version`, globally random `event_id`, `event`, `session_id`, optional `parent_session_id`, optional `turn_id`/`decision_id`, per-emitter `seq`, UTC `timestamp`, process-local `monotonic_ns`, a `synthetic` flag, and allowlisted `data`.

Session identity is read from the coordinator/session if exposed. A generated fallback ID is used otherwise. Parent linkage appears only when available; this is not a complete distributed trace protocol. Monotonic values cannot be compared across processes or machines. Event IDs support deduplication; wall time is display order, not a causal guarantee. The local viewer retains at most 20,000 events and 20,000 retained deduplication IDs by default. Export reflects that retained window; archive original JSONL separately for larger traces.

| Event suffix | Meaning |
|---|---|
| `turn_start` / `turn_end` | Hybrid turn boundary, mode, configured backend, final submission/provider counters and recorder health |
| `requested` | Eligible prepared candidates sent for a decision; includes state hash, no raw state |
| `scored` | Returned distribution/model/usage and measured backend wall time, whether or not acted on |
| `routed` | Actual fast submission or slow route, plus mechanical reason; shadow can include `proposed_route` |
| `fallback` | Error/timeout/envelope incompatibility; exception type only |
| `slow_start` / `slow_end` | Actual original provider complete or stream invocation, destination, time and available usage |
| `tool_start` / `tool_end` | Actual `execute()` reached and outcome; a native pre-hook alone does not produce these |
| `cancelled` | Cancellation observed and propagated |
| `health` | Recorder or metadata-only native-hook bridge status |

Fast tool IDs match the synthesized core ToolCall ID when the argument fingerprint still matches. If upstream modifies a call, or for ordinary slow-path calls, the tool facade may allocate an `observed_*` correlation ID instead. The native hook bridge can carry the original native ID. Do not assume these are identical in every path.

`duration_ms` has a `latency_kind` on score/provider completion events. The decision duration measures the backend call, not candidate collection, serialization, UI polling or total turn duration. Provider time includes whatever the provider does inside `complete()`. No ratio is presented as measured whole-task acceleration. Missing usage stays unknown, not zero. The synthetic tool-call envelope uses zero generative tokens; Jev input usage is recorded separately.

A fast `routed` event means a valid response envelope was submitted to the upstream loop. It does not mean that a tool was permitted or executed. A `tool_end` with success/error status is the execution observation. A shadow result never increments the fast-submission counter.

`routed` / `slow_start` / `slow_end` carry `transport_measured`: `"provider-complete"` or `"provider-stream"`, set at the point the provider facade is actually entered -- never a claim made at `turn_start`, since a single turn can enter the facade through both transports. The fast path is attempted only on the `provider-complete` transport; a `provider-stream` entry always routes slow with reason code `fast_path_unavailable_on_transport`, because loop-streaming's streaming branch cannot dispatch a tool call it receives (see `docs/UPSTREAM_CONTRACT.md`). Failing closed (defer to the real provider) is deliberate: the alternative is a prepared action silently dropped by upstream.

The visualizer's explanation is `reason_code`, not private model reasoning. Probability is neither calibrated task accuracy nor authority. The optional native hook bridge emits `health` metadata for `tool:pre`, `tool:post` and `provider:error`; it does not infer the final result of the whole hook chain.
