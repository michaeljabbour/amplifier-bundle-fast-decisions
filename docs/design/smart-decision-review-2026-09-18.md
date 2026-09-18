# Smart Decisions review against the current source

Reviewed 2026-09-18 against main `2a55566`, plus the local changes described below.
Inputs: the user's `SMART-DECISION-REFACTOR.md` and `baseline-tests.txt`.
Those artifacts explicitly reviewed an older v0.1.0 archive: 89 tests, 86 passed,
3 skipped. They are useful design input, not a current defect inventory.

## Direction

The portable library is the product; a host supplies action bindings and authority.
Keep the Amplifier integration and compatibility imports while introducing a generic
API alongside the existing `select`. A package rename or new repository alone would
not establish that separation. Calling the tool and integrating it before a host's
expensive provider call remain different capabilities.

## Reconciliation

| Recommendation | Current status and next step |
|---|---|
| Library, thin CLI, descriptor, packaged manifest, Agent Skills | Already shipped. `smart_tool.py`, `smart_cli.py`, `smart-tool.json`, `SMART_TOOL.md`; deterministic capabilities need no provider or Amplifier. |
| Data-only portable invocation | Shipped for prepared read/list selection. `select` imports no Amplifier runtime, but internally still adapts to action-specific Candidate/DecisionRequest contracts. |
| Arbitrary typed questions without tool bindings | Still a real gap. Design a versioned `evaluate` API alongside `select`; keep tool names, approvals and executable arguments in the adapter. |
| Choice/Score/Noul batching | Partial. Jev submits contributed questions alongside `next_action`. Local Ollama explicitly rejects extra questions. Neither is yet the proposed generic typed batch engine. Do not claim shared computation or answer invariance from an API batch. |
| Exact option order and choice-set identity | Added backend-rendered `option_set_hash` to local/Jev results, portable results, active scores and shadow proposals. Existing canonical `candidate_order_hash` stays compatible; it is not order-sensitive. |
| Probability, confidence and calibration separated | Local token mass was already separate. Added `confidence_kind`, retained unknown remote formula/version, rejected invalid confidence values, and stopped replay averaging mixed or unspecified confidence statistics. Raw provider values remain visible. |
| Neutral event sink and nonblocking optional observers | Partial. Recorder is queued; Emitter callbacks/native hooks are still awaited. This change removes recorder shutdown polling and moves portable flush off the event loop. A bounded optional-observer dispatcher remains separate work; mandatory audit policy must remain explicit. |
| Neutral storage and event envelope | Deferred migration. Portable traces still use the shared `.amplifier/fast-decisions/events` default so the installed viewer can see them. `events_dir`/`--events` is explicit. Introduce platform state paths with compatibility discovery, not a silent directory move. |
| Platform support distinct from backend support | Already documented and exercised in the existing macOS/Linux/Windows portable CI. This review runs locally on macOS only; it does not rerun that matrix. MLX support would be a separate backend claim. |
| Proposed/accepted/executed evidence and savings | Already distinguished. Portable calls are advisory; actual host bypass/execution comes from the integration. Eliminated tool calls, net task savings and quality parity remain unmeasured. |

## What the sources actually support

The [Archer investigation](https://archerhume.com/posts/jevs-architecture-unmasked/)
is black-box experimental work. Its isolation and option-set probes are useful
validation patterns. They do not supply weights or prove a causal/MoE/readout design.
We retain Qwen's bounded one-token scorer without calling it a Jev reproduction.

[TypeSafe's confidence documentation](https://docs.typesafe.ai/confidence)
defines confidence as a statistic derived from the distribution. Its public
[adapter at fb52b103](https://github.com/typesafe-ai/system-one-adapter-python/blob/fb52b1030b7fc1f4f1cf39910afa5da54f9835e3/src/system_one_adapter/_utils/confidence_metrics.py)
uses a normalized maximum for Choice. The [OpenJev README](https://github.com/daseinlabs/open-jev)
describes normalized entropy and includes the full options in each question prompt
before scoring label continuations. Matching API shapes therefore do not establish
matching statistics or model behavior. The hosted Jev response used by this bundle
does not version its formula, so the adapter records `typesafe_reported_unspecified`
instead of assigning the public adapter's formula to an unverified server.

## Measurements behind the changes

Local machine: Apple M5 Max, macOS 26.6.2 arm64, Python 3.13.12, Ollama 0.34.1.
Model: `qwen3:0.6b`, Q4_K_M; local installed digest
`7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435`.
The digest identifies the model present during this run, not a general pin for the tag.

### Shutdown and end-to-end CLI overhead

Ten idle-recorder measurements on each implementation: median close was 98.8 ms
in installed `2a55566`, versus 0.05 ms with immediate queue wakeup. The writer still
flushes accepted events; regression tests cover idle shutdown, ordered drain,
a full queue and asynchronous caller responsiveness.

Twenty alternating warm CLI calls from `/tmp`, ten per implementation, using the
same Python interpreter, public README/LICENSE request and isolated event storage:

| Implementation | Full CLI median | Full CLI p95 | Correct selections |
|---|---:|---:|---:|
| Installed main `2a55566` | 251.7 ms | 372.2 ms | 10/10 |
| Modified source | 151.1 ms | 173.5 ms | 10/10 |

Timing includes process startup, local scoring, recording and shutdown. This small
run supports a local overhead improvement, not a task-level speedup or general p95
claim. Scoring/model settings were unchanged. Raw local receipt:
`/tmp/afast-refactor-cli-comparison.json` (temporary, not shipped).

### Model robustness

`suites/local-robustness.jsonl`: eight specification-derived public cases, each in
forward/reverse option order, repeated three times. These labels are developer-authored
expectations, not independently adjudicated human ground truth. Suite SHA-256:
`b709c81f6626065fa382b9842faf71adaf432ae7015b09acfee17b67dc641a2f`.

- 48 warm loopback scoring requests, no errors; p50 22.0 ms, p95 42.9 ms, max 45.6 ms.
- Initial warmup request: 943.5 ms. The model was not forcibly unloaded, so this is
  warmup timing, not a controlled cold-start measurement.
- At unchanged score 0.90 / margin 0.20: 24 accepted, zero wrong accepted relative
  to these fixture labels. All 24 paired policy outcomes were order-stable.
- Raw argmax agreed in 21/24 pairs; maximum option-probability shift was 0.558
  (55.8 percentage points). Raw model stability is not established by stable policy.
- Explicit README/LICENSE, distractor and duplicate-distractor cases were selected
  correctly; insufficient state, missing target and generation requests abstained.
- Conflicting tool-output instructions caused all six cases to abstain rather than
  selecting the requested README. This loses coverage and is not a correct completion.
- Overall policy agreement: 42/48 (87.5%). Repeats are not independent examples,
  so do not interpret the accepted-call count as a calibrated quality guarantee.

Raw local receipt: `/tmp/afast-refactor-robustness.json` (temporary, not shipped).
Reproduce with the command in [BENCH.md](../BENCH.md#confidence-and-local-robustness-checks).

**Tuning decision:** keep Qwen3:0.6b and current thresholds. Lowering thresholds to
increase the number of accepted calls is unsupported by these data. Do not add
runtime permutation ensembles: those multiply latency; keep these probes in evals.
Compare other models/backends on the same task outcomes before choosing a replacement.

## Next acceptance gates

1. Add generic ordered Choice/Boolean/ordinal contracts and a data-only evaluate API,
   with per-question success/abstention/error and explicit backend capabilities.
   Keep `select` compatible. Test malformed/missing/extra results and unsupported types.
2. Stage dependent questions; require backends to disclose request partitioning.
   Test sibling-question leakage only on backends that support the batch contract.
3. Isolate optional observers behind a bounded dispatcher with dropped-event counts,
   owned shutdown and cancellation. Keep mandatory audit delivery a separate policy.
4. Add a neutral event envelope and platform state paths with old-trace translation
   and shared-viewer discovery. Do not strand existing session telemetry.
5. Evaluate held-out full tasks with independently checked outcomes, matched baseline
   runs, model revisions, hardware and cold/warm timing before claiming quality parity
   or net savings. Include set-valued labels for semantically duplicate correct options.

This review does not implement that full migration, an OpenJev adapter, a new model,
a hosted deployment, or automatic acceleration in Claude/Codex. The immediate changes
are compatible evidence and overhead improvements in this working tree.

## Validation of these local changes

- Current pre-change source: 244 tests discovered in the generic Python environment;
  205 passed, 39 host/browser-dependent checks skipped.
- Modified source in the installed Amplifier Python environment: **251 passed,
  zero skipped**. This includes installed core/loop contract tests; it is not a new
  billed provider session or live Jev acceptance run.
- No-key demo completed with events isolated in `/tmp/afast-refactor-review-demo`.
- Built and installed a separate non-editable package in a temporary environment;
  Smart Tools conformance at spec revision `70432044f26e2094b5894516adab68aa14f88592`:
  **16 passed, zero failed or skipped** with that installed CLI on PATH.
- Existing global CLI, skills, default Amplifier configuration and active viewer
  were preserved. These changes are local and are not merged or installed globally.
