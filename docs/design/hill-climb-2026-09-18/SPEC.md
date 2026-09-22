# Fast Decisions: an evidence-driven hill-climbing campaign

Version 1 · 2026-09-18 · **Implementation specification; campaign not started.**

Companion files: [launch prompt](PROMPT.txt), [campaign defaults](campaign.json), and [entry point](START-HERE.md). The JSON is input to the supervisor to be built, **not an existing Amplifier configuration or executable recipe**. Proposed interfaces and event names below are design requirements, not claims about shipped APIs.

## 1. Mission and definition of success

Build a portable Smart Tool that measurably reduces the time and cost of completing useful agent tasks while preserving their quality, native permissions, and user control. Amplifier is the first deep integration. Other harnesses can call the same library/CLI; automatic optimization of their internal loops requires a separately verified host integration.

Optimize **validated completed work**, including recovery and verification. Do not optimize the fast-submission counter, number of model decisions, or animation density. Choosing not to invoke a classifier can be the best decision. A cheaper model that takes more attempts can be worse.

Campaign objectives, evaluated on a declared workload population:

| Objective | Target and interpretation |
|---|---|
| Fast decision boundary | Warm p95 below 500 ms, including state/candidate preparation, queueing, transport, inference, decoding and policy. Report maximum and violation count. Enforce the deadline and timely fallback; do not hide timeouts. |
| Task acceleration | First useful milestone: at least 20% lower paired task latency. Stretch: 2× throughput or half the task time on supported families. These are research targets, not guaranteed outcomes. |
| Cost | First milestone: at least 20% lower total measured or consistently estimated cost per successful task. Stretch: 50% lower. Include failed attempts, verification, scorer and hosting. |
| Quality | Zero new critical correctness/security failures; no known regression on required acceptance checks. Broad quality parity additionally requires the statistical gate in §7. |
| No-op overhead | When no optimization is eligible, aim for added warm p95 below 25 ms and no material whole-task regression. Measure instrumentation overhead separately. |
| Portability | Provider-free deterministic library/CLI; tested inference capability; explicit support matrix for each OS, backend and harness integration mode. |
| Operability | Durable histories, recoverable experiments, visible real parent/child activity, reproducible comparisons and a working rollback. |

Latency and cost are separate objectives. A candidate can improve one while respecting a predeclared regression limit on the other; label the result accordingly. Never report a quality loss as an efficiency win. The sub-500 ms target applies to a bounded decision, not to code generation or an entire task.

## 2. Starting evidence and reconciliation

Recheck these facts before implementation; do not blindly replay old patches.

| Location / artifact | Verified starting state on 2026-09-18 |
|---|---|
| `~/dev/amplifier-bundle-fast-decisions` | Dirty `feat/observatory-ledger`, HEAD `675a4b3291d5c77bb772dabfe5e0e23383588506`. Preserve all unrelated work. |
| Remote main | `74639ffef7003f38c632b50e6fc45ee73214b928`, checked with `git ls-remote`. This differs from the original working tree. |
| `~/dev/amplifier-fast-decisions-forge-e2e` | Branch `test/forge-matched-e2e`, base `74639ff`; uncommitted state repair, benchmark runner, controller tests and history helper. Review and port only unique changes. |
| `~/dev/afast-forge-evidence-20260918-02` | Six-run report, immutable original receipts, `ROOT-CAUSE.md`, `ROOT-CAUSE.json`, `OBSERVATIONS.md`, manifest and evaluator hashes. |
| `~/dev/afast-forge-evidence-20260918-01` | Two excluded overlapping pilots. Retain them and the documented exclusion; never mix with the primary sample. |
| `~/.amplifier/fast-decisions/history/2026-09-18-forge-root-cause` | Private metadata snapshot, native-history index/hashes, reports and reproduction files. Raw native content was not copied. |
| `~/Downloads/SMART-DECISION-REFACTOR.md` and `baseline-tests.txt` | Earlier v0.1.0 review inputs. Some gaps have since been fixed; use current source to reconcile them. |

Read repository `AGENTS.md`, `docs/AGENT-HANDOFF.md`, README, COMPATIBILITY, PRIVACY, BACKLOG and current design review. Existing B01–B14 backlog statuses are historical: establish present state instead of declaring everything unfinished. This campaign refines those items; it does not authorize overwriting another agent's work.

### What the real six-run experiment established

- Three tasks, one baseline and one enabled run each, identical initial fixtures and configured generative model. Four sessions completed; both reconciliation sessions hit the fixed eight-minute deadline.
- Scheduler: 439.38 → 410.56 seconds. Event reducer: 393.20 → 378.84 seconds. The reconciliation pair has no completed-task speed comparison.
- Five fast submissions reached successful tool execution. Observed provider requests totaled **51 in each variant**, across intervals that include incomplete runs.
- All 594 independent functional checks passed on saved code. Passing partial output from a timed-out run is not successful task completion, superior quality, or general quality equivalence.
- Provider wall time accounted for roughly 93–95% of observed CLI time. This includes transport/queue/generation; it is not a measurement of model compute alone.
- Active scoring totaled 3.107 seconds across the enabled runs. Request-to-route p95 was about 85–107 ms, but excluded candidate preparation. Improving that scorer alone cannot explain hundreds of seconds of task acceleration.
- All native requests used `claude-fable-5-1`, `effort=max`, with thinking enabled. The 128,000-token setting was an output ceiling, not actual token consumption.
- 42/54 active scoring requests offered one prepared candidate plus abstention. The local Qwen backend handles prepared read/list choices; it is not Jev and does not provide generic question batching.
- Seven of 54 scoring states lost all observations. A candidate fix anchors the latest task and clips evidence within the serialized budget. It has regression coverage, but has **not** been installed or retested in the live six-run comparison.
- The live viewer did display receipt-backed movement. Its remaining issues include validation sessions mixed with work sessions, control-path status counted as errors, long provider waits appearing inactive, and incomplete baseline accounting. More animation is not the root-cause repair.

### Research interpretation

The user's LangChain article describes typed decisions, batching and model routing, not a general coding-task speedup of the advertised classification multiplier. Treat it as a mechanism to test. Jev architecture reconstructions supply hypotheses, not weights, calibration guarantees or a replication recipe. Do not label the local scorer a Jev replica. Preserve option-order and confidence-semantics tests when comparing backends.

## 3. Build the campaign before allowing it to optimize itself

Implement a small deterministic supervisor around the available Amplifier workflow facilities. Reuse installed evaluation/Attractor/Forge capabilities if their actual versions support the needed contract. Inspect their help and source before generating a recipe or DOT pipeline. **Do not invent a command such as `amplifier hill-climb`.** A plain Python supervisor plus files is acceptable.

The optimizer may edit product code and propose policy changes. It must not silently change its own objective, evaluator, acceptance gates, budgets or evidence filters. Changes to those create a new versioned campaign protocol, invalidate incompatible comparisons, and require a fresh baseline. LLM assessment can explain results; deterministic checks control transitions.

State machine:

```text
inventory → baseline → select hypothesis → preregister experiment → implement
    ↑                                                          ↓
checkpoint ← decide ← compare ← independent evaluation ← isolated execution
               │
               ├─ invalid evidence → repair measurement → rerun within budget
               ├─ regression → reject and retain evidence
               ├─ inconclusive → bounded replication or defer
               └─ promising → held-out gate → guarded canary → release gates
```

Supervisor responsibilities:

1. Acquire a campaign writer lease; snapshot source, environment and ownership.
2. Freeze protocol, task split, evaluators, thresholds, run order, resource class and budgets.
3. Allocate an immutable experiment ID and isolated candidate worktree.
4. Implement one causal change, run focused tests and record the exact diff/commit.
5. Launch real workers, observe receipts, enforce deadlines and independently verify output.
6. Compute paired outcomes without dropping failures. Record one machine-readable disposition.
7. Advance an experimental incumbent only under the search gate; keep release eligibility separate.
8. Atomically checkpoint after every transition and every completed run. Continue until a deterministic stop condition.

A future launched campaign may use separate builder, evaluator and reviewer agents for bounded work. The supervisor owns the budget and final decisions. Builders cannot edit evaluator fixtures or expected answers. Prefer OS/container separation for hidden evaluators; a different directory under the same unrestricted account is not a security boundary. If isolation is unavailable, mark evaluation contamination risk and withhold strong generalization claims.

Parallelize code review, documentation and offline checks when useful. Serialize timed runs on shared CPU/GPU/provider resources unless resource isolation is demonstrated. Every worker has an owner, lease, task ID and bounded runtime. Never run multiple optimizers against the same mutable worktree.

Implement this control logic with validated records; the following is pseudocode, not an existing API:

```python
with campaign_writer_lease():
    reconcile_checkpoint_with_ledger_and_live_workers()
    freeze_or_verify_protocol()
    while capacity_for_next_reserved_experiment():
        proposal = preregister_one_hypothesis()
        candidate = build_in_owned_worktree(proposal)
        if not required_correctness_and_authority_checks(candidate):
            record_rejection_and_checkpoint(candidate)
            continue
        runs = execute_frozen_paired_schedule(candidate)
        evidence = independently_evaluate_every_assigned_run(runs)
        decision = deterministic_gate_evaluation(evidence)
        append_decision_and_checkpoint(decision)
        if decision.experimental_incumbent_eligible:
            update_experimental_incumbent(candidate, evidence)
        if decision.pilot_eligible:
            queue_guarded_canary_within_remaining_budget(candidate)
        if stop_condition():
            break
    reconcile_owned_jobs_and_write_continuation()
```

Supervisor acceptance tests must inject termination during launch, inference, evaluation and checkpoint replacement; resume without duplicated side effects or lost completed receipts. Inject unknown spend, a corrupted result, a full disk and a failed evaluator. None may produce a promotion. Record all state transitions even when a worker fails to start. Use [experiment-template.json](experiment-template.json) as a starting record, validate/fill its unresolved fields, and freeze it before execution.

### Resume and failure semantics

- On resume, inspect saved process identity, host session ID and result artifact before relaunching. Deduplicate by run ID plus attempt number. A stale lease does not prove the worker stopped.
- A Forge observation timeout is **not** worker completion. The previous controller's 60-second observation limit caused overlapping pilots; preserve its regression test. Wait for worker exit/result or the actual task deadline before starting the next timed run.
- A completion receipt requires process/session terminal status and evaluation. A truncated JSONL tail is a recoverable reader condition, not permission to fabricate completion.
- Persist partial usage and mark unanswered requests/costs unknown. Bound retries: one infrastructure retry by default, with both attempts retained; candidate-caused errors remain candidate outcomes.
- Stop or cancel only campaign-owned processes after verifying PID start identity/session ownership. Never kill the user's unrelated terminals or viewer.
- Do not resume from a narrative summary alone: read manifest, ledger, checkpoint, actual Git state and outstanding worker receipts.

## 4. Product architecture and control boundaries

The [Smart Tools specification](https://github.com/microsoft/amplifier-smart-tools) defines a library, manifest and thin CLI with optional adapters; deterministic capabilities remain usable without a model. Keep that dependency direction. Pin the conformance specification revision used in CI and report skipped checks honestly.

| Layer | Responsibility and acceptance evidence |
|---|---|
| Portable core | Data-only typed request/result contracts; validation, inference lifecycle, batching, policy, calibration/evaluation and event sink. Imports and deterministic commands work without Amplifier, keys or a running model. |
| Backend | Declares supported question kinds, batching behavior, calibration meaning, deadlines, model revision and usage. Local warm scorer first; Jev/other hosting optional. Unsupported capabilities return explicit outcomes. |
| Harness adapter | Collects state, constructs eligible prepared actions, consults the core at a supported boundary, applies native policy, submits normal envelopes and reports actual results. |
| CLI / optional MCP or HTTP | Thin access to the same library. Persistent warm service is explicit, authenticated where appropriate, and has owned lifecycle. No daemon on import. |
| Observatory / history | Consumes neutral events, preserves provenance and shows evidence of outcomes. Optional slow observers cannot block the decision path. |

### Proposed decision contract

`evaluate(request)` accepts JSON-compatible state and context, schema version, state revision, ordered typed questions, absolute deadline, privacy policy and correlation IDs. No host coordinator, registry, executable binding, raw thinking or live Python callable belongs in that public payload.

Question kinds: ordered Choice; Boolean probability; ordinal Score with defined levels. Results include per-question success/abstention/error/timeout, raw distribution, selected option if applicable, exact model-facing option-set fingerprint, backend/model revision, backend confidence value **and definition**, empirical calibration-profile ID if any, usage and measured durations. Unknown values remain null with a reason.

Independent questions can share a batch. Dependent questions require staged evaluation. Report logical question count, transport request count and actual inference count when known; a single HTTP call does not prove parallel GPU execution. Capabilities must distinguish native batching from serial emulation. Test order permutations, distractors, duplicated choices, missing information and cross-question interference.

Keep existing `select`, configuration and traces compatible through an adapter/migration layer. Do not require a package rename to achieve portability. The CLI, Python interface and optional adapters must yield equivalent typed outcomes for the same request.

### Actual opportunities at the host boundary

Before each costly generative step, determine whether existing state permits:

1. A deterministic decision or already-authorized prepared action batch.
2. A bounded classifier decision among eligible alternatives.
3. Generation with an appropriate configured model/effort tier.
4. Verification, recovery, escalation or termination based on observed results.

A classifier cannot invent a correct patch by choosing an option. Generated plans can supply bounded future steps, but every step needs preconditions, file/state revisions, expiry, invalidation after steering, and host-owned action bindings. Reuse a plan only when those conditions remain true. Never substitute a synthetic final answer for unfinished work.

Preserve native approval deny/modify paths, tool-call/result pairing, streaming, cancellation, provider pins, user model constraints, context metering and child isolation. An unsupported transport or boundary falls back visibly. Risk classification may add a restriction; it cannot grant permission or weaken mandatory host policy.

### Model and effort routing

Define configured roles such as `bounded_decision`, `routine_generation`, `deep_generation`, and `verification`. Discover actual provider/model/effort support; no guessed names, silent provider changes or global effort reduction. Explicit user pins outrank optimization policy. Log requested and effective settings.

Start with one permitted effort change on one task phase using the same model. Then separately test model tier selection. Escalate on failed acceptance checks, contradictory evidence, repeated repair or out-of-domain input. Include escalation latency and cost in the result. Use deterministic verification where it is adequate; an expensive judge on every step can erase savings. Keep routing confidence distinct from verified correctness.

## 5. Measurements that cannot be gamed by a fast-path counter

Record monotonic durations locally and wall-clock timestamps for correlation. Do not subtract timestamps from unsynchronized hosts. Never sum overlapping provider/tool/child spans as parent wall time.

| Metric | Definition |
|---|---|
| Task success | Session completes within the declared limit; required output exists; frozen acceptance checks pass; protected fixtures and required constraints remain intact. |
| Task latency | User request admission to finished accepted result, including failed internal attempts, routing, verification and escalation. Publish startup-inclusive and warm execution values separately. |
| Penalized time | For each assigned run: successful latency, otherwise the predeclared task deadline. Display beside success rate and successful-only latency; it is a conservative ranking statistic, not the true completion time of failures. |
| Task cost | All attributable provider/scorer/verification/retry/hosting costs. Separate billed, provider-estimated and modeled cost. Missing receipts make total unknown or a labeled lower bound. |
| Calls | Actual native provider requests, provider transport retries, completed/failed/cancelled tools, batch sizes and scorer requests. Count each child event once. |
| Boundary overhead | Entry before state/candidate construction through valid decision or fallback release. Break down preparation, queue, transport/inference, validation/policy and observer enqueue. |
| Quality | Task-level success and severity-weighted defect rubric, plus task-specific semantic checks. Individual assertions are not independent task samples. |
| Bypass | Native evidence that a particular provider boundary was replaced. It proves a bypass, not the time or money that hypothetical generation would have cost. |
| Reuse / suppression | Receipt identifies prior result, freshness and permission validation, the suppressed operation and eventual downstream outcome. Count this separately from routing. |
| Net improvement | Paired baseline–candidate task differences, with denominators, uncertainty, failures and source/config revisions. No extrapolation from classifier speed. |

Count optimization workload and campaign-development spend separately, both within the campaign budget. Exclude neither shadow inference nor remote service idle cost when claiming operational savings. Track native cache reads/writes according to provider semantics; do not double-count token totals.

## 6. Evaluation design

### Baselines and ablations

- **B0:** upstream ordinary loop, same permitted tools and passive measurement, no active or shadow scoring. Measure passive-observer overhead on an additional small uninstrumented control.
- **B1:** frozen currently installed fast-decisions behavior, with effective mode/backend established. Never assume an app bundle implies active routing.
- **C:** the candidate, with one declared change against the current experimental incumbent.
- Recompare a finalist to B0 and B1 as well as its immediate predecessor. Local hill climbing must not hide accumulated regressions.
- When testing effort/model routing, changing effective settings is the treatment, not a matched constant. Keep task, tools, permissions, acceptance and initial state fixed; report all actual model settings. Ablate scorer-only versus routing versus the combination before attributing gains.

### Task portfolio

Use the existing scheduler/reconciler/reducer as **development fixtures**, not fresh held-out evidence. Add independent tasks from at least these families: read/explain and repository mapping; localized repairs; multi-file refactors; difficult algorithm/debugging; tool-result validation and recovery; parent/child delegation; long-context retention; insufficient information and unsupported operations; approval denial/modify/cancellation; stale files and steering.

Freeze task specifications, quality rubric, evaluator hashes, fixture hashes and split membership before optimizing. Every task needs an observable success oracle. For prose outputs use blinded review against a fixed rubric, not the optimization agent's own praise. Model judges are supplementary, identified, and periodically checked against deterministic or human labels.

Separate development, validation, release holdout and real-use canary pools. Builders may inspect development failures. A sealed evaluator should return only aggregate release-gate results until the decision; once detailed answers are revealed, retire those cases from the holdout. Do not repeatedly select candidates on the same release holdout. Maintain a sealed reserve or acquire new tasks for the next release family.

### Execution protocol

1. Restore identical fixture state, record hardware/load/provider revisions and seed when controllable. Never claim provider determinism just because a seed is supplied.
2. Warm models explicitly outside warm timing; also measure cold startup separately. Record provider cache conditions. Randomize baseline/candidate order in paired blocks and stratify by task family.
3. Run a two-task, one-pair-per-task screen for cheap rejection only. For finalists use at least three repetitions per task and eight distinct tasks from four relevant families. This is a **minimum pilot dataset**, not proof of universal quality parity.
4. Use the same predeclared deadline per task in both variants. Initial coding default: 20 minutes, replacing the old overly short eight-minute cutoff. Short decision tests have their own 500 ms boundary. Freeze deadline changes before a new comparison block.
5. Preserve every assigned run, start failure, timeout, contamination and retry. Infrastructure exclusions require documented variant-independent criteria. Publish intention-to-test outcomes alongside any restricted analysis.
6. Timing on shared resources is serial. If testing intended concurrent usage, make contention a separate declared workload and compare equal concurrency.
7. Repetitions do not substitute for task diversity. Bootstrap paired latency/cost effects by task cluster, with seed, estimator and interval method frozen. Show per-family and worst-case regressions.

## 7. Gates, acceptance and hill-climbing rules

Gate results are `pass`, `fail`, `inconclusive`, `blocked`, or `not_run`, with evidence links. Missing evidence is never a pass.

| Gate | Required evidence |
|---|---|
| G0 — Measurement | Both variants have reconciled native requests/results, complete run identity, fixed oracle, no unexplained dropped events or overlapping timed jobs. Budget/controller interruption tests pass. |
| G1 — Correctness and authority | Required unit/integration tests, privacy checks, native deny/modify/cancel/stale-state behavior, user pins, tool pairing and protected fixtures all pass. Any new critical defect rejects the candidate. |
| G2 — Development improvement | Fixed development checks have no observed regressions. Paired screening points to a mechanism and useful effect; this can advance the **experimental** incumbent only. Label small samples provisional. |
| G3 — Guarded pilot | Minimum finalist dataset (§6), no observed task-quality regressions, no new critical defects; task-cluster 95% interval for the primary latency or cost ratio lies below 1.0, point estimate at most 0.80. Secondary ratio point estimate at most 1.10, with its uncertainty disclosed. Otherwise replicate within budget or mark inconclusive. |
| G4 — Broad quality claim | On independent tasks, one-sided 95% lower confidence bound for candidate-minus-baseline success rate exceeds −0.02, with preregistered paired/task-cluster analysis; all hard constraints still pass. A small all-pass sample will often be insufficient. Continue collecting independent tasks rather than treating 594 assertions as 594 tasks. |
| G5 — Release and installation | Clean owned diff, required CI/conformance, exact immutable artifact, installed-version verification, live supported-host smoke tests and tested rollback. Merge, release, install and live acceptance are separate fields. |

G3 permits a scoped experimental canary, not a broad “no quality compromise” marketing claim. A sub-500 ms claim additionally needs at least 200 representative warm boundary observations, including noneligible/abstention/failure paths and load conditions; report empirical p95, interval, max and all deadline violations. Small backend microbenchmarks do not certify end-to-end p95.

Use penalized task time as the default primary comparison so failed runs cannot disappear from a latency win. Publish successful-only latency beside it. Cost per successful task divides all assigned-run cost by successful completions; zero successes has no finite value. Unknown cost blocks a cost claim and the cost guardrail, rather than becoming zero. Gate evaluation must return the failed predicate and evidence reference, not just an LLM verdict. Statistical methods and task-family weights are frozen before results; if there are too few independent task clusters for a defensible interval, return `inconclusive`.

Selection policy:

- Preregister each hypothesis, changed variables, expected mechanism, affected families, primary metric, guardrails, run allocation and stop rule before results.
- Keep a Pareto archive of qualified latency/cost/quality outcomes. Never collapse a critical quality failure into a favorable weighted score.
- Select the highest expected useful impact supported by the current bottleneck evidence. First fix broken state/evidence; then change control flow; only then optimize already-small scorer time.
- Allocate roughly 80% of candidate effort to the best-supported neighborhood and at most 20% to a materially different approach. Defaults are guidance; record actual choices.
- Compose individually promising changes only after isolated tests; the combination is a new candidate with interaction tests and a new comparison.
- After three valid candidates without useful improvement, reprofile once and change the hypothesis neighborhood. If another three yield no improvement, stop with a plateau report. Invalid measurement runs do not count as negative optimization evidence, but consume budget.
- Promotion does not reset spending or erase prior failures. No result means “not yet established,” not “probably faster.”

## 8. First experiments and implementation backlog

Every row has a concrete exit condition. Reconcile with existing B01–B14 rather than duplicate delivered work.

| ID / priority | Work and hypothesis | Acceptance / falsification |
|---|---|---|
| HC00 / P0 | Freeze source, independent evaluation and complete boundary/native usage instrumentation. Generalize the existing Forge runner's hardcoded environment/model paths. | Reproduce one matched pair; interruption/restart does not duplicate workers; metadata accounts for each request. Timing includes preparation; no model invocation is needed for deterministic commands. |
| HC01 / P0 | Port the candidate state repair after reviewing current main. Task anchor plus recent evidence should prevent information-free scoring. | Long tool output, Unicode/escaping, >12-message history and steering retain required state within budget. Record observation count/truncation reason. Repeat matched live tasks; do not promise the seven abstentions become saves. |
| HC02 / P0 | Version-aware completed-read tracking and prepared batching. Avoid redundant reads and needless fragmentation. | Native and fast reads update the same freshness ledger; changed files, permissions, task revision and dependencies invalidate reuse. Compare separate ablations for suppression and batching, including tools that cannot parallelize. |
| HC03 / P1 | Phase-specific effort routing on the same generative model. Routine read/inspect phases may not need maximum effort. | Requested/effective effort receipts match policy; pins preserved; difficult/ambiguous phases escalate; all recovery cost counted. Reject if faster output fails semantic checks or total task time worsens. |
| HC04 / P1 | Select a smaller configured generative model for bounded generation, then escalate. | Active host routing, not shadow labels. Compare fixed model, effort-only and model+effort treatments. No provider is selected unless configured and allowed. |
| HC05 / P1 | Deterministic test/result interpretation and bounded continuation plans. Remove generative bookkeeping between known steps. | Exit status and structured assertions drive declared transitions; unexpected output goes to reasoning. No premature final response, skipped required verification or duplicate side effect. |
| HC06 / P1 | General typed engine, explicit backend capabilities, warm lifecycle and nonblocking observation. | Standalone library works; typed batching tested; stalled viewer cannot stall decisions; controlled queue/deadline/cancel behavior and measured overhead. Preserve native approval hooks. |
| HC07 / P1 | Durable history and Observatory outcome comparison. | Parent grouping with children included once; real waits remain visible; validation/demo sessions labeled; history survives restart; every animated stage has a real event ID; comparisons link matched runs and quality gates. |
| HC08 / P2 | Context selection/compaction as a separate optimization. | Preserve task constraints, provenance, unresolved work and tool pairs; retest delayed facts and correction after steering. Measure downstream quality/cost, not just tokens removed. Use host context APIs only. |
| HC09 / P2 | Backend alternatives, including full-option readout or small classifier models. | Same labeled decisions, abstention coverage/error tradeoff, calibration and latency under realistic load. Quantization/ablation requires accuracy evidence. Jev access or paid GPU is not a prerequisite. |
| HC10 / P2 | Claude Code, Codex and additional host adapters. | Demonstrate invocation first; investigate supported interception separately. Publish verified mode and receipts per host. Unsupported deep control is an explicit limitation, not a reason to modify private host internals. |
| HC11 / P2 | Cross-platform distribution, setup, promotion and rollback. | Install outside checkout, provider-free checks, configured inference, pinned manifest/conformance, actual supported OS matrix, local/hosted setup docs and exact rollback verification. |

First campaign order: HC00 → HC01 → HC02 → HC03, while building only the minimum generic contracts needed for those experiments. Reprofile before HC04 onward. Do not spend the first campaign rewriting every package or deploying GPUs while generation remains the demonstrated bottleneck.

Start with existing Ollama `qwen3:0.6b` Q4_K_M for the narrow local decision baseline, preserving current 0.90 score / 0.20 margin until labeled evidence supports changes. These are uncalibrated thresholds. Benchmark target hardware; do not assume a development Mac's result transfers to a CPU server. Hosting may colocate the scorer with the harness; remote latency must include network and service queue. Record idle hourly cost and cost per useful completed task. Validate current model availability, license, hardware and serving configuration before recommending a new deployment.

## 9. Durable campaign and session history

Use a new private campaign directory outside the installation and source worktrees. Proposed layout:

```text
campaign/
  campaign.json                 # frozen settings and recorded authorization scope
  protocol.json                 # metric/gate definitions, splits, evaluator hashes
  environment.json              # exact source/runtime/backend/hardware identities
  checkpoint.json               # atomic replace; pointers, never sole evidence
  ledger.jsonl                  # append-only transitions, including rejections
  champion.json                 # experimental incumbent, not automatically released
  pareto.json                   # qualified alternatives with evidence
  tasks/manifest.json           # public IDs; sealed evaluator elsewhere
  experiments/HC01-0001/
    proposal.json               # preregistered hypothesis and budget
    source.patch
    runs/<run-id>/
      manifest.json
      receipts.jsonl
      result.json
      evaluation.json
    comparison.json
    decision.json
  history/index.json
  reports/LATEST.md
  handoff/CONTINUE.md
```

Each run manifest records campaign/experiment/run/attempt IDs, task family and split, seed, baseline/candidate assignment, task/evaluator/fixture hashes, Git SHA plus dirty-diff hash, policy/backend/model revision, effective provider settings, OS/hardware, cache/warmup conditions, session/root/parent IDs, limits and ownership. Each result records terminal status, success verdict, quality artifact references, latency/cost/call totals, missing-data reasons and source receipts.

Neutral events need schema version, unique event ID, producer sequence, request/batch/question/decision IDs when applicable, root/session/parent IDs, harness and source revision, state/option-set/policy hashes, timestamps, durations and outcome codes. Distinguish request, inference result, proposal, host acceptance/rejection, execution start/end and evaluation. Do not mark host acceptance just because a core API returned a choice. Unknown parents remain explicit; reconnect must deduplicate, identify gaps and avoid counting child work twice.

Save allowlisted metadata by default. Public fixture source/output may be retained as benchmark artifacts. Index existing native session histories with paths/hashes; that is not a full-content backup. Any full transcript backup for private work needs an explicit separate retention policy, redaction and access control. Do not copy native private thinking into training data, reports or the shared ledger. Never archive credentials, HTTP bodies or `~/.amplifier/fast-decisions/serve.json` and its bearer URL. No user-memory writes are part of this campaign.

Use private filesystem permissions where supported, crash-tolerant append/read behavior, disk-usage reporting and an explicit retention setting. Do not silently prune evidence or existing history. On a storage limit, stop new runs and checkpoint. Keep optional UI transport loss separate from durable run evidence; an incomplete required evidence trail blocks performance promotion.

## 10. Observatory product acceptance

The default screen answers: which root sessions are working; what each is waiting on; which optimization actually ran; whether it reduced completed-work time/cost; and whether quality checks passed.

- Root sessions are the navigation unit; **include children by default**, with drill-down and a clear inclusion control. Preserve root context when selecting a child.
- Distinguish active, waiting on provider, tool executing, idle, completed, failed, disconnected, demo and validation. A long provider call remains waiting until evidence says otherwise; freshness is shown separately.
- Animate actual observed transitions. A conceptual diagram is labeled conceptual. Replay is labeled replay; missing events show a gap rather than an invented motion.
- Show ordinary model/tool activity alongside fast decisions. “No eligible fast route” can coexist with healthy active work.
- Show bypasses, reused/suppressed calls, routing overhead, total provider/tool counts, measured paired savings, unknown cost and quality status separately. Show the comparison population and sample size.
- Link every displayed claim to session/run IDs and evidence. Historical sessions are discoverable across viewer restarts; transient display limits do not imply disk history loss.
- Use a neutral charcoal/slate theme with muted text and restrained accent colors. Avoid large bright-white surfaces, perpetual motion and a giant decorative loop that conceals operational state.
- Verify through a real browser: two roots, actual nested child work, long provider wait, cancellation, reconnect, historical replay and a baseline comparison. Child-checkbox defaults alone do not establish live child support.

## 11. Budget, stop conditions and scope

The companion JSON proposes an initial **12-hour, $150 campaign ceiling**, eight candidates and 60 benchmark worker launches. These are conservative planning defaults, not a bill already incurred or a guarantee of completion. Starting the supplied prompt adopts those limits; change them before launching if desired. The first checkpoint reports configured limits and estimated evaluation capacity. Large quality claims may require later campaigns and more independent tasks.

Include orchestrator/build/evaluation model calls and retries in the spend ledger. Do not start a paid job if incurred cost plus reservations could exceed the cap. Derive conservative per-job reservations from known pricing and enforced token/runtime limits; a nominal $5 benchmark reservation is only a floor, not a guarantee. If pricing/spend cannot be bounded, pause paid launches and continue deterministic work. Update estimates against receipts; retain a separate unknown-spend field. No automatic budget doubling or indefinite continuation.

Stop launching work when any limit is reached: wall time, spend plus reservations, candidates, worker launches, storage or repeated plateau. Finish/cancel owned work within reserved limits, checkpoint and write a continuation handoff. Stop immediately on a critical permission/privacy regression or corrupted evaluator. A task deadline is a task failure, not a reason to bypass checks.

Use existing configured providers and local hardware. This launch does not provision paid infrastructure, change global default bundles, migrate active user sessions or alter provider secrets. Prepare a measured hosting option if local resources are the bottleneck. Commit owned changes and prepare reviewable PRs within recorded session authority. The default campaign stops before merge/global installation; existing explicit authorization can be recorded and applied after G5 prerequisites without repeatedly requesting it. Never infer publication authority from a benchmark win.

## 12. Promotion, rollback and deliverables

Maintain distinct states: implemented → locally checked → host validated → pilot qualified → quality claim qualified → merged → packaged → installed → observed live. A correctness repair may ship independently with normal validation even if it does not meet the performance threshold; label it as a repair, not a speed win.

Before installation capture the prior package/source/config identity and exact restore procedure. Canary an explicitly selected session/workspace, preserve the global default, and roll back on native policy regression, incorrect result, unexplained missing receipts or unacceptable measured overhead. An unknown integration path stays disabled. Verify rollback by running the ordinary provider/tool path and reading its receipts.

Required campaign output:

1. Reproducible supervisor and restart tests, protocol, run ledger and history index.
2. Focused product changes with tests and compatibility migrations, not an unreviewable rewrite.
3. Standalone Smart Tool usage and actual conformance results; host/OS/backend capability matrix marked tested, untested or unsupported.
4. Paired report with successful completion rates, quality defects, latency distributions, cost provenance, all failed/censored runs, per-family effects and uncertainty.
5. Actual receipt-backed Observatory demonstration including child activity and stored history.
6. README/model setup for local and colocated/hosted operation, warmup, tuning, privacy and troubleshooting; no RunPod requirement.
7. Reviewable PR information, exact installation/rollback evidence if authorized, and a concise continuation file stating the next experiment and remaining limits.

If the campaign fails to find a useful improvement, deliver the negative results and supported root cause. Do not lower thresholds, rename a proxy as savings, or claim completion because the budget is exhausted.

## 13. Sources and reproducibility notes

- [Smart Tools specification and conformance kit](https://github.com/microsoft/amplifier-smart-tools): packaging requirements; pin the selected revision during implementation.
- [LangChain: Building a Harness with Jev](https://www.langchain.com/blog/building-a-harness-with-jev): mechanism inspiration, supplied in full by the user; live retrieval was unavailable during this specification pass. No benchmark multiplier is adopted as our target evidence.
- [Earlier source reconciliation](~/dev/amplifier-bundle-fast-decisions/docs/design/smart-decision-review-2026-09-18.md), [existing backlog](~/dev/amplifier-bundle-fast-decisions/docs/BACKLOG.md), and [host acceptance instructions](~/dev/amplifier-bundle-fast-decisions/docs/AGENT-HANDOFF.md).
- Local six-run and root-cause evidence paths in §2. Source and report files were inspected for this specification; no new benchmark or installation was performed.
