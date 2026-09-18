# Fast context-retention decisions

Research/design only; no runtime compaction or default configuration changed.
Reviewed September 17, 2026, following the owner's fast-jev-compaction example.

## Reference and applicability

Reviewed [fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction)
at `e3f262a7f4d42bd8dd32ced30d26176f7cb545b0`. Its library pairs tool calls/results,
pins recent exchanges, asks separate call/result retention questions and rebuilds
the retained conversation. Its Claude Code hook uses a context-usage trigger and
falls back when pruning fails or achieves too little reduction. This is relevant
as an additional decision domain, separate from selecting the next tool.
See [compact.ts](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/src/compact.ts)
and [hook](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/hooks/fast-jev.ts).

Two limitations matter for our evaluation: the scorer's state omits result bodies,
and the repository's animated demo is explicitly scripted. Neither interface
design nor a recorded animation establishes task quality or end-to-end savings.
The [state builder](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/src/state.ts)
and [README](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/README.md)
make those distinctions visible. The supplied X post could not be fetched (403),
so no claim here relies on its contents.

## Existing Amplifier boundary

The installed context-simple implementation owns canonical history and creates
ephemeral request views via `get_messages_for_request()`. It already provides
sticky compaction decisions and the `context.request_retention` capability.
Loop-streaming consumes that capability during request assembly and measured
budget fitting. Our orchestrator delegates context ownership to that loop.

Therefore this feature should propose retention decisions to the context owner,
with an opt-in adapter and an explicit extension contract. A telemetry hook is
not authority to rewrite history. Verify both the ordinary request path and the
retention-capability path; wrapping one getter while the capability still points
at the original context would silently miss requests. Do not wrap private state
or bypass the existing measured-budget fitting contract.

## Proposed portable library contract

Input: a revisioned task snapshot, complete tool-exchange groups with stable IDs,
eligibility/pinning metadata, budget, and bounded supporting evidence.
Output: a typed plan of KEEP, SHORTEN, or OMIT_FROM_REQUEST decisions, score
semantics, source revision, model identity and deadline outcome.

The host validates the plan against the current snapshot before building its
request view. Preserve the canonical log and a retrieval reference for anything
omitted. Retain system/developer instructions, user requirements, native retention
pins, recent exchanges, pending tool calls, and provider-specific structural
blocks. Preserve call/result validity across multi-tool messages. Side-effect
receipts and unique error evidence need explicit protection; re-running a tool
is not a general recovery strategy.

Unknown score semantics, unsupported structures, stale plans, timeout or invalid
answers default to KEEP and existing context behavior. Scoring may run in the
background; applicability must be checked again when the next request is built.
Avoid rescoring every pair on every iteration. Cache decisions by task revision
and content identity with explicit invalidation when the goal changes.

Our current Ollama backend supports prepared workspace actions only. Its small
prompt benchmark cannot establish performance on long-history retention or
batched questions. Add a separate typed retention backend; do not relabel
workspace candidates or reuse uncalibrated scores as deletion confidence.
External history scoring requires its own consent/scrubbing policy because the
input is broader than today's bounded workspace decision snapshot.

## First experiment and acceptance

Start with a public replay corpus and shadow plans; do not modify live requests.
Include stale/redundant reads, unique failure details, changed goals, multi-tool
groups, cancellation, native retention pins and irreversible-action receipts.
Compare existing context-simple, deterministic redundancy pruning, and learned
retention on held-out sessions with matched tasks/providers.

Measure actual provider input tokens, cache reads/writes, score wall time,
time-to-first-token, full task wall time, repeated tool calls, task correctness,
and lost constraints. Token reduction alone is insufficient: pruning an old
prefix may invalidate prompt caching, and deleting useful output may force a
slow re-read. The 500 ms warm target applies to the full retention pass including
queueing/batches, not each individual chunk. Late plans must not block the turn.

The Observatory should show proposed versus applied omissions, protected groups,
stale/timeout outcomes, provider-measured token changes and observed latency.
Call savings “estimated” until matched end-to-end measurements support them.
Keep event payloads metadata-only. Active rollout requires quality and protocol
parity first, then demonstrated net task-time or cost improvement.
