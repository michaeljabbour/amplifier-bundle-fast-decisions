# Event contract v1.0

Schema: `schemas/event.schema.json`. Names are added through the native `observability.events` contribution channel. Native events are not renamed or replaced.

Every event has `schema_version`, globally random `event_id`, `event`, `session_id`, optional `parent_session_id`, optional `turn_id`/`decision_id`, per-emitter `seq`, UTC `timestamp`, process-local `monotonic_ns`, a `synthetic` flag, and allowlisted `data`.

Session identity is read from the coordinator/session if exposed. A generated fallback ID is used otherwise. Parent linkage appears only when available; this is not a complete distributed trace protocol. Monotonic values cannot be compared across processes or machines. Event IDs support deduplication; wall time is display order, not a causal guarantee. The local viewer retains at most 20,000 events and 20,000 retained deduplication IDs by default. Export reflects that retained window; archive original JSONL separately for larger traces.

| Event suffix | Meaning |
|---|---|
| `turn_start` / `turn_end` | Hybrid turn boundary, mode, configured backend, `allow_external_state`, final submission/provider counters and recorder health |
| `requested` | Eligible prepared candidates sent for a decision; includes state hash, `state_chars`, `candidate_count`, `question_count`, `candidate_order_hash`, `domain`, no raw state |
| `scored` | Returned distribution/model/usage and measured backend wall time, whether or not acted on; carries `candidate_order_hash`, `domain` |
| `routed` | Actual fast submission or slow route, plus mechanical reason; shadow can include `proposed_route`; carries `domain` once a candidate set has been built (early guard-clause routes, e.g. `mode_off`, precede that and carry none) |
| `fallback` | Error/timeout/envelope incompatibility; exception type only |
| `slow_start` / `slow_end` | Actual original provider complete or stream invocation, destination, time and available usage |
| `tool_start` / `tool_end` | Actual `execute()` reached and outcome; a native pre-hook alone does not produce these |
| `cancelled` | Cancellation observed and propagated |
| `health` | Recorder or metadata-only native-hook bridge status |
| `shadow_proposed` | The shadow worker scored a snapshot taken from the mounted context manager (`state_source: "context_mount"`); off the critical path, includes `choice`, `probabilities`, `selected_probability`, `margin`, `duration_ms`, `state_source`, `candidate_count`, `domain`, `state_chars`; carries `allow_external_state` only on the first `shadow_proposed` emitted for a given `turn_id` (a per-turn context field, not repeated every decision) |
| `shadow_observed` | The next `tool:pre` after a `shadow_proposed` snapshot was seen; carries `tool`, `tool_call_id`, `arguments_hash` -- what the LLM actually did, not what was proposed |
| `shadow_agreement` | A `shadow_proposed` proposal and its matching `shadow_observed` outcome were joined; `agreement` is `match` / `mismatch` / `abstained` / `unobserved`, plus `proposed_candidate`, `actual_tool`, `would_have_avoided_llm_turn`, `domain` |
| `role_proposed` | The shadow-only model-role router (P4) proposed a role for a `delegate` call, or recorded why it abstained (`explicit_role_present`, `role_resolver_unavailable`); carries `proposed_model_role`, `eligible_roles`, `reason_code`, `domain` (always `"model-role"`) |
| `role_agreement` | A `role_proposed` proposal and the delegate's actual routing were joined; `agreement` is `match` / `mismatch` / `unobserved`, plus `proposed_model_role`, `actual_model_role` (`null` = resolver default), `domain` |

Fast tool IDs match the synthesized core ToolCall ID when the argument fingerprint still matches. If upstream modifies a call, or for ordinary slow-path calls, the tool facade may allocate an `observed_*` correlation ID instead. The native hook bridge can carry the original native ID. Do not assume these are identical in every path.

`duration_ms` has a `latency_kind` on score/provider completion events. The decision duration measures the backend call, not candidate collection, serialization, UI polling or total turn duration. Provider time includes whatever the provider does inside `complete()`. No ratio is presented as measured whole-task acceleration. Missing usage stays unknown, not zero. The synthetic tool-call envelope uses zero generative tokens; Jev input usage is recorded separately.

A fast `routed` event means a valid response envelope was submitted to the upstream loop. It does not mean that a tool was permitted or executed. A `tool_end` with success/error status is the execution observation. A shadow result never increments the fast-submission counter.

`routed` / `slow_start` / `slow_end` carry `transport_measured`: `"provider-complete"` or `"provider-stream"`, set at the point the provider facade is actually entered -- never a claim made at `turn_start`, since a single turn can enter the facade through both transports. The fast path is attempted only on the `provider-complete` transport; a `provider-stream` entry always routes slow with reason code `fast_path_unavailable_on_transport`, because loop-streaming's streaming branch cannot dispatch a tool call it receives (see `docs/UPSTREAM_CONTRACT.md`). Failing closed (defer to the real provider) is deliberate: the alternative is a prepared action silently dropped by upstream.

The visualizer's explanation is `reason_code`, not private model reasoning. Probability is neither calibrated task accuracy nor authority. The optional native hook bridge emits `health` metadata for `tool:pre`, `tool:post` and `provider:error`; it does not infer the final result of the whole hook chain.

**One backend request per state, regardless of question count.** `requested`
and `scored` both carry `candidate_order_hash`: the digest of the candidate
set in canonical `(origin, id)` order, computed once per request. Two runs
over the same candidate set produce the same hash. `question_count` is the
number of contributed judgment questions (`fast_decisions.questions`
channel) batched into that same request alongside the action choice --
batching is a pure latency/cost win because the vendor scores every
question independently; it never changes an individual answer. A
misbehaving contributor (wrong shape, conflicting identifiers, or over the
`max_candidates`/`max_questions` bound) is dropped and counted via
`fallback` events with reason codes `contribution_shape_invalid`,
`contribution_conflict`, `contribution_truncated`, `question_criteria_invalid`
-- it can never disable the fast path for the other contributors.

**Three bench measurement fields, all small privacy-safe scalars.** `domain`
(one of `tool-choice` / `read-target` / `model-role`) is decided once, at the
point a decision's candidate set is built, by the single classifier
`contracts.classify_domain`: `"model-role"` for router (model-role)
decisions; `"read-target"` when every candidate targets `fast_workspace`;
`"tool-choice"` otherwise. `state_chars` (an integer, never the state text)
is `len(canonical(state))` for the state actually sent to the backend, on
`requested` (the main decision path) and `shadow_proposed` (the shadow
path). `allow_external_state` (a boolean, the shipped policy's own
external-state opt-in) is on `turn_start`, and on the *first*
`shadow_proposed` per `turn_id` only -- it is turn-level context, not
per-decision, so it is not repeated on every shadow proposal within the
same turn. All three are in `privacy.SAFE_FIELDS`.

**Shadow scoring runs off the critical path; the snapshot does not.** `hooks.emit` applies no per-handler timeout, so only the *backend scoring* that produces `shadow_proposed`/`shadow_agreement` is deferred to a background worker owned by `Runtime`. The *snapshot* (reading the mounted context manager, collecting candidates, hashing) runs inline in the `provider:request` handler and is hard-bounded by `shadow_max_messages`, `max_state_chars` and `shadow_snapshot_budget_ms`. Exceeding the wall-clock budget is a normal, counted outcome -- the snapshot is abandoned and `fallback` fires with `reason_code: shadow_snapshot_budget_exceeded`, never an exception into the hook chain. No handler in the shadow scorer can raise into the hook chain or change the turn; every handler returns `continue` unconditionally.
