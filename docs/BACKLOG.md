# Smart Decisions implementation backlog

Updated 2026-09-18. Ordered implementation plan, grounded in the
[current source review](design/smart-decision-review-2026-09-18.md).
B01 was merged in PR #18. B02/B03 diagnostics and accounting, and B04 comparison
tooling are implemented in the operational-measurement change. B04's broader
held-out quality and pinned-provider evaluation gate remains open. The ledger UI
is tracked separately in PR #19. Release/install receipts are reported separately
from local implementation.

Product direction: a portable decision library with its own inference capability,
a thin CLI and optional adapters. Amplifier is the first deep integration. The
Observatory reports real activity and measured benefits across parent and child
sessions. The user-facing latency budget is under 500 ms per warm decision,
including transport and wrapper overhead.

## P0 — Deliver the existing improvements and establish useful evidence

| ID | Work | Completion criteria | Dependency |
|---|---|---|---|
| B01 | Release the local latency and evidence fixes. Commit the owned changes, open a PR, run CI, merge, and update the installed Smart Tool. Include option fingerprints, explicit confidence semantics and robustness fixtures. | Reviewed changes exclude unrelated work; CI passes; the installed revision is verified outside the checkout. Current evidence: 251 local tests and 16 conformance checks passed. | Merged PR #18; installed revision verified at release |
| B02 | Make operational status obvious. Add a diagnostic that follows installation → host composition → effective backend/mode → eligible decisions → telemetry delivery → viewer connection. Provide an explicit local-model setup command/profile and actionable remediation. | A fresh Amplifier parent/child session is visible. The UI distinguishes absent integration, scripted shadow, real-model shadow, active routing, idle, disconnected and failed inference. Existing global configuration is preserved. | B01 |
| B03 | Instrument actual efficiency and execution outcomes. Add correlation for provider calls, tool calls, retries, token usage, decision overhead, fallback and completion across a session tree. | A bypass requires host evidence; tool suppression requires its own receipt. Unknown costs remain unknown. Parent totals include children once, with drill-down. No advice is counted as execution or savings. | B02 |
| B04 | Build matched baseline-versus-enabled task evaluations. Use isolated equivalent workspaces, checked task outcomes, fixed model/backend revisions and recorded timing. | Report complete-task time, actual call/token counts, attributable costs where available, failure/retry rates and outcome quality. Hold out evaluation tasks from tuning. Establish outcome parity for each supported workflow before expanding active use. | B03 |

## P1 — Make the core genuinely general and keep observation inexpensive

| ID | Work | Completion criteria | Dependency |
|---|---|---|---|
| B05 | Add a generic `evaluate` library API alongside compatible `select`. Introduce versioned state, ordered options, Choice/Boolean/ordinal question contracts, limits and per-question outcomes. Keep executable bindings in adapters. | A plain Python program obtains a decision without importing Amplifier or supplying tool objects. Deterministic validation works with no provider. Unknown types, malformed results, cancellation and deadlines have explicit behavior. | B01; use B04's evaluation requirements |
| B06 | Define backend capabilities and batch semantics. Implement supported types per backend, explicit partitioning and staged dependencies between questions. | Report actual inference request counts and unsupported capabilities. Preserve model-facing option order. Test missing/extra answers and sibling-question leakage where batching is supported. Never infer shared GPU work from one HTTP request. | B05 |
| B07 | Isolate optional observers from the decision path. Add bounded dispatch, queue/drop/error health, owned cleanup and cancellation. Keep mandatory audit delivery a separate explicit contract. | A stalled optional callback or viewer cannot delay inference. Queue saturation and shutdown are covered by regression tests. Native approval hooks retain their existing authority and execution semantics. | B01 |
| B08 | Introduce neutral events and platform-appropriate storage. Add request/batch/question identities, producer and harness metadata, backend/model revision when known, policy version and execution feedback. | macOS/Linux/Windows deterministic checks pass. Existing JSONL traces and the current viewer continue working through translation and directory discovery; no silent move strands history. Sensitive state is excluded. | B05, B07 |
| B09 | Finish the live Observatory experience around diagnosis and outcomes. Keep the neutral charcoal palette, parent grouping and child inclusion. Improve decision-to-execution timelines, backend status and efficiency/quality panels. | Every moving stage corresponds to a received event. Users can identify which session benefited, which action was proposed/accepted/executed, why fallback occurred, and what evidence supports a savings figure. Reconnect, pause and replay remain distinct. | B02, B03; adopt B08 incrementally |
| B10 | Add a reusable warm engine lifecycle. Reuse backend clients in-process; add an explicitly started local service only where cross-process reuse is needed. Include warmup/readiness, queue limits and model revision reporting. | Measure the caller's full warm decision path against the 500 ms budget; publish p50/p95/max and over-budget counts. Cold starts are reported separately. No daemon starts on import and failures produce timely fallback. | B05, B06 |

## P2 — Expand integrations and optimization only where results justify it

| ID | Work | Completion criteria | Dependency |
|---|---|---|---|
| B11 | Provide thin access adapters and documented host recipes. Keep the installed CLI/skills; add an MCP surface over the same library when useful. Investigate supported execution-boundary integration separately for Claude Code, Codex and other hosts. | Demonstrate invocation and telemetry in each named host. Label advisory-only integrations accurately. Claim automatic provider-call reduction only where a supported host integration is actually exercised. | B05, B08; host capability investigation |
| B12 | Add measured call-avoidance strategies. Start with narrowly eligible repeated reads or reusable results, with explicit freshness, scope and authorization checks; then evaluate other repeated routing decisions. | Host receipts identify every skipped call and reused result. Stale state, changed files, permission changes and unsupported operations disable reuse. B04 shows preserved task outcomes and positive net savings. | B03, B04, B05; an executable host integration |
| B13 | Pilot context retention/compaction as a separate capability. Select what to retain using bounded decisions; use a generative model only where rewriting is necessary. | Tests preserve required facts, instructions, unresolved tasks and tool-call/result pairs. Measure downstream quality, token savings and added decision costs. Do not enable globally on development-fixture results. | B04–B06; host context integration |
| B14 | Compare additional local/hosted inference backends. Evaluate a direct-readout scorer or OpenJev-compatible implementation, then consider Jev when access exists and managed hosting when it solves an observed need. | Use the same held-out workloads, semantics and full latency accounting. Record model revision, calibration domain, hardware, operating cost and network overhead. Adopt a replacement only for a measured benefit. | B04–B06, B10 |

## Delivery rules

- Ship small compatible PRs. Keep `amplifier-fast-decisions select`, existing bundle
  configuration and readable historical traces working while adding the generic core.
- Start with B01–B04. B05 and B07 can then progress independently; model/backend
  expansion should not postpone making the current installation useful and observable.
- Keep Qwen3:0.6b, the 0.90 selection score and 0.20 margin until workload evidence
  supports a change. Scores and provider confidence are not permission grants or
  independent correctness estimates.
- Measure quality and complete-task savings together. A faster isolated decision,
  a shadow agreement, and an avoided provider call establish different things.
- Track source, CI, merged revision, installed revision and live-host acceptance
  separately. Compatibility expectations do not count as verified host support.
- A package rename, exact Jev replication and paid GPU deployment are not prerequisites
  for this backlog. Model experiments and hosting decisions follow measured need.
