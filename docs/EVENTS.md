# Event contract v1.0

`probability_kind` describes score semantics. The local scorer emits
`token_mass_with_abstention_residual`: raw one-token probability mass with all
unrecognized/missing mass assigned to abstention. This is uncalibrated and does
not estimate real-world correctness. Other backends default to `backend_reported`.

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
| `shadow_observed` | Emitted from the same `tool:pre` call that took the snapshot behind `shadow_proposed` for this decision; carries `tool`, `tool_call_id`, `arguments_hash` -- what the LLM actually did, not what was proposed |
| `shadow_agreement` | A `shadow_proposed` proposal and its matching `shadow_observed` outcome were joined; `agreement` is `match` / `mismatch` / `abstained` / `unobserved`, plus `proposed_candidate`, `actual_tool`, `would_have_avoided_llm_turn`, `domain` |
| `role_proposed` | The shadow-only model-role router (P4) proposed a role for a `delegate` call, or recorded why it abstained (`explicit_role_present`, `role_resolver_unavailable`, `role_router_disabled`); carries `proposed_model_role`, `eligible_roles`, `reason_code`, `domain` (always `"model-role"`) |
| `role_agreement` | A `role_proposed` proposal and the delegate's actual routing were joined; `agreement` is `match` / `mismatch` / `unobserved`, plus `proposed_model_role`, `actual_model_role` (`null` = resolver default), `domain` |
| `observatory` | The auto-observatory's once-per-session `session:start` bootstrap; `action` is `reused` / `started` / `skipped` / `failed`, plus `reason` and (when relevant) `port` -- never the token-bearing URL, which never enters event data |

Fast tool IDs match the synthesized core ToolCall ID when the argument fingerprint still matches. If upstream modifies a call, or for ordinary slow-path calls, the tool facade may allocate an `observed_*` correlation ID instead. The native hook bridge can carry the original native ID. Do not assume these are identical in every path.

`duration_ms` has a `latency_kind` on score/provider completion events. The decision duration measures the backend call, not candidate collection, serialization, UI polling or total turn duration. Provider time includes whatever the provider does inside `complete()`. No ratio is presented as measured whole-task acceleration. Missing usage stays unknown, not zero. The synthetic tool-call envelope uses zero generative tokens; Jev input usage is recorded separately.

A fast `routed` event means a valid response envelope was submitted to the upstream loop. It does not mean that a tool was permitted or executed. A `tool_end` with success/error status is the execution observation. A shadow result never increments the fast-submission counter.

`routed` / `slow_start` / `slow_end` carry `transport_measured`: `"provider-complete"` or `"provider-stream"`, set at the point the provider facade is actually entered -- never a claim made at `turn_start`, since a single turn can enter the facade through both transports. The fast path is attempted only on the `provider-complete` transport; a `provider-stream` entry always routes slow with reason code `fast_path_unavailable_on_transport`, because loop-streaming's streaming branch cannot dispatch a tool call it receives (see `docs/UPSTREAM_CONTRACT.md`). Failing closed (defer to the real provider) is deliberate: the alternative is a prepared action silently dropped by upstream.

The visualizer's explanation is `reason_code`, not private model reasoning. Probability is neither calibrated task accuracy nor authority. The optional native hook bridge emits metadata for `execution:start`, `execution:end`, `provider:request`, `tool:pre`, `tool:post`, `provider:error`, `provider:retry`, `session:end`, and `context:compaction`. Retry metadata includes an optional attempt, HTTP status, and exception type; error bodies are excluded. Native hook observations do not prove the final outcome of the hook chain.

At mount, `health` with `phase: configuration` records effective mode, backend, external-state setting, policy version, an optional configured `session_label`, and `workspace_name`: the basename of the process working directory (or the hook's `workspace_name` config), a single path component and never a full path. The viewer names a session by `session_label`, then `workspace_name`, then its short id. A `session_heartbeat` is emitted every 15 seconds while the observer is mounted; cleanup cancels that task and emits `session_closed`. A heartbeat proves recent observer presence, not that the session is doing work. The viewer uses native turn lifecycle records for working/idle state and treats presence older than 45 seconds as unknown. Existing sessions need to reload the updated observer before they can emit these heartbeats.

The viewer's live view is a decision ledger: one row per decision key (session and `decision_id`), showing what the scorer proposed, what the recorded events say happened, and a labelled verdict (fast executed / submitted / failed, reasoning model, match / mismatch / abstained, no candidate, fallback, advisory, scripted, in flight, not scored). A native `tool:pre` / `tool:post` pair joins the decision whose `shadow_observed`, `tool_start` or `tool_end` recorded the same `tool_call_id` in the same session; otherwise it forms its own hook-observation row. A row is "in flight" only while the viewer is live, its latest record is under 90 seconds old, and no terminal record (`tool_end`, `slow_end`, `shadow_agreement`, `fallback`, `role_agreement`, `advisory_result`, or a native `tool:post`) has arrived; that is a display state, never an inference about execution. The viewer defaults to parent sessions, with children included in aggregate activity by default and expanded or selected separately on demand. The connection indicator describes the viewer connection, independently of each session's presence. Its default time window is one hour. Saved traces are labeled and do not receive live updates. Live records are polled every 500 ms. Live-flow cards highlight newly arriving recorded stages only; history has no animated execution clock. Replay is inspection of saved records, not a simulated execution.

Scripted and explicitly synthetic decision chains are hidden by default and never counted as model decisions or measured improvements. Native observations from a session using the scripted shadow scorer remain visible: the surrounding Amplifier execution is not thereby synthetic. `shadow_proposed` includes backend/model identity and score provenance; shadow proposals never count as fast submissions or executions. Unlabeled historical fixtures cannot be reliably identified as fixtures after the fact; producers must mark their provenance.

The mechanics view projects the recorded sequence for one session and decision ID. Native pre/post observations may also form a separate tool flow when their session and native tool-call IDs match; they remain hook observations, not measured execution. Missing stages stay missing; events from another session cannot complete a path even if their decision IDs match. A successful instrumented `tool_end` paired with a fast `routed` event establishes a completed fast-path tool. Counters of native tool results are labeled as reports; they do not imply equivalent execution instrumentation. Decision p95 measures backend scoring duration in the selected window, including shadow model scores. A `routed` fast event with `status: submitted_to_upstream` records a generative provider invocation bypassed at that boundary. It does not establish that a tool call was eliminated. Net task time, monetary savings, and task-quality parity require separate baseline/outcome evidence and are not inferred from counts or shadow agreement.

Portable Smart Tool calls emit `requested`, `scored`, and `health` with `phase: advisory_result`, `mode: advisory`, and `event_source: portable-smart-tool`. These prove only scoring and a returned suggestion. The caller supplies lineage IDs; no persistent session heartbeat, execution, or provider bypass is inferred. Failure returns typed abstention and is not counted as successful advice.

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

**Shadow scoring runs off the critical path; the snapshot does not.** `hooks.emit` applies no per-handler timeout, so only the *backend scoring* that produces `shadow_proposed`/`shadow_agreement` is deferred to a background worker owned by `Runtime`. The *snapshot* (reading the mounted context manager, collecting candidates, hashing) runs inline in the `tool:pre` handler, immediately before tool dispatch, and is hard-bounded by `shadow_max_messages`, `max_state_chars` and `shadow_snapshot_budget_ms`. Exceeding the wall-clock budget is a normal, counted outcome -- the snapshot is abandoned and `fallback` fires with `reason_code: shadow_snapshot_budget_exceeded`, never an exception into the hook chain. No handler in the shadow scorer can raise into the hook chain or change the turn; every handler returns `continue` unconditionally.

**Why `tool:pre`, not `provider:request`.** The snapshot used to run in the `provider:request` handler. A live DTU trace against the real Amplifier CLI showed `amplifier_module_loop_streaming` emits iteration 1's `provider:request` *before* appending the turn's own user message to the mounted context (see `docs/UPSTREAM_CONTRACT.md`), so `context.get_messages()` was empty on that call for every turn: no candidates were ever found, and the real tool call that followed was never scored (no `shadow_observed`). The next iteration's snapshot then produced an unmatched, one-iteration-stale `shadow_proposed` that `execution:end`'s `sweep_unobserved()` silently discarded. Moving the snapshot to `on_tool_pre` -- the earliest point observed to reliably include this iteration's own messages -- fixed both: see `docs/design/redesign-2026-09-17.md` P3 postmortem addendum.

**The shipped `backend: deterministic` default actually measures something.** `allow_external_state` gates any call to an *external* backend (`backend.external == True`, i.e. `jev`) -- it never gated the in-process `deterministic` backend (`ScriptedBackend`, `external == False`), but before this fix `get_runtime` only accepted `jev` or `unavailable` as config values, and the shipped `behaviors/fast-decisions.yaml` set `backend: jev` alongside `allow_external_state: false`. That combination is internally consistent (the gate correctly refuses to call Jev without opt-in) but means the shadow rung never produced a `shadow_proposed`/`shadow_agreement` -- only a `fallback` with `reason_code: external_state_not_enabled`, forever. `backend: deterministic` is now a first-class option: an in-process, offline scorer that is never subject to the external-state gate, matching the rung ladder in `docs/design/redesign-2026-09-17.md` P3 (`off -> shadow, external=false (deterministic only) -> shadow, external=true (real jev) -> active`). Set `backend: jev` and `allow_external_state: true` together to move to the next rung.

**The model-role router's `actual_model_role` is read from the tool's own return value, not a top-level hook field.** `tool:post`'s real payload (`loop-streaming:6348-6357`) carries the tool's dumped `ToolResult` under `result`; `tool-delegate` places its routing summary at `result.output.provider_routing.model_role`, never at a top-level `data["provider_routing"]`. Reading the wrong location always returned `None` for `actual`, so every observed `role_agreement` reported `"mismatch"` regardless of what the delegate actually resolved to. `router.on_delegate_post` now reads the nested field via `field_value`, which duck-types across a plain dict or an attribute-bearing object.

**The router is never silent, even when disabled.** `role_router: false` (the unconfigured library default; the shipped `behaviors/fast-decisions.yaml` sets `role_router: true`) previously made `on_delegate_pre` return with no event at all for a `delegate` call -- indistinguishable from a crash or a missed registration. It now emits `role_proposed` with `reason_code: role_router_disabled` (no job enqueued, no probe, no turn behaviour change) so "no telemetry" never has to be interpreted as "the router isn't wired up".
