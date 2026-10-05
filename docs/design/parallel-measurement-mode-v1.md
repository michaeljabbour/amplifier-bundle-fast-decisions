# Parallel measurement mode (dual-path counterfactuals)

Status: design, not built. Read against `origin/main` at `6206103`. Off by default; it never changes what the live session does.

## 0. Why

Today the savings numbers come from three sources, and none of them measures the path that was not taken:

- **Shadow mode** (`service.py:312`) scores a decision, emits `scored`, and then always takes the slow path. `ShadowScorer` (`observer.py:165`) records only whether the host's next tool call matched the proposal.
- **Receipts** (`efficiency.py`) estimate the baseline by repricing tokens: `prepared_step` uses "next call's prompt as cache reads", and `cheaper_model_step` reprices the call on the host model. The caching evidence (`origin/eval/judge-realistic:docs/evidence/2026-10-01-caching`) shows how far off this can be. Prepared-action receipts claimed $2.22 saved where $2.80 was lost, with a per-pair correlation of −0.12. The planner predicted savings on the Opus host and measured losses (wrong sign).
- **A/B arms** diverge from turn 1. The SD of the log cost ratio is 0.23 to 0.38, so each contrast needs dozens of pairs.

Measure mode runs the path we shut off **in parallel, on the same state**. The live session always gets the result of its own path. The other path's result is recorded and never used. The output is a paired dataset and receipts with `method="measured_parallel"`.

## 1. Unit of measurement per lever

### Common rules

- **Live path.** `measure.live_path: slow | fast` decides which path the live session takes (§4 has the config). The other path is the **branch**. A branch response is never returned to the loop. Its tool calls are never executed, except in a benchmark sandbox (phase 2b).
- **Two tiers.**
  - **Tier P** (production-safe): single-call branches with no tool execution.
  - **Tier B** (benchmark only): turn and session branches run in cloned workspaces under the Forge/battery harness.
- **Deferred launch and tail correction.** This is the one cache rule for every lever.
  - Prompt caches are keyed by (model, effort/thinking config, prefix). A branch that runs before the live path's next call on the same model would warm that call's prefix and hide the live path's cache writes. So each single-call branch is queued with `not_before` = the end of the live path's next call on the same model (or the end of the turn). The wait is capped at 240 s so the cache does not expire.
  - The branch then finds the cache warmer than it would have been in its own world. The surplus is the **tail**: tokens the live path wrote after the fork point. The branch's `tail_tokens` are repriced from cache read to cache write, and the adjustment is stored as `cache_correction_usd`.
  - Raw, repriced and corrected costs are all kept, so the correction can be recomputed.
- **Branch billing stays out of the session.** Branch calls go through a second instance of the same provider module, mounted on a private stub coordinator (`measure.branch_provider()`). Branch calls therefore never emit `llm:response` into the session's hooks, and session cost sums (`battery._native_cost_by_model`) stay clean. Branch usage goes only to the measurement dataset.
- **Every fork has a pair row** (§2). Every scheduled fork that does not run is still written, with `censored=<reason>`.

### (a) Read shortcut / prepared actions (Tier P)

| `live_path` | Live | Branch | Equivalence |
|---|---|---|---|
| `fast` (active mode) | Prepared action. This is the "shut-down transaction". | The host call that was skipped: the same `request` from `DecisionService.choose`, before the synthetic envelope. | Host's first tool call vs the candidate: `action_match` (tool and canonical args hash), `action_superset` (the candidate appears among parallel calls), `refetch` (the next live call re-read the path; already computed for `prepared_repeated_by_model`). |
| `slow` (shadow mode) | Host call 1, the tool runs, then host call 2. | **Lookahead.** Run the candidate (read-only, `Policy.allowed_tools`) on the same workspace, append the synthetic tool call and its result to a copy of `request`, then make one host call. | `action_match` as above. `next_action_match`: the branch's next action vs live call 2. `divergent=true` when the actions differ. |

- **Measured saving in the `fast` row:** `branch.cost − (judge + prepared)`.
- **Measured saving in the `slow` row:** `(c1 + c2) − (judge + branch_corrected)`. Here `tail_tokens` is the `cache_write_tokens` of live call 1.
- **Divergent lookaheads.** These are truncated after one step. Their downstream cost comes only from session forks (§1c).

### (b) Model routing / turn-start tier

**Tier B, turn fork (phase 1).** At a sampled turn boundary k, the harness:

1. clones the workspace (`cp -c`, an APFS clone) and the Amplifier session dir (`scripts/fork_session.py`);
2. resumes the clone under the other cell's profile (routed ↔ plain on the same host) for turn k only;
3. starts the live turn and the branch turn together, so neither reads the other's first-request cache writes on a shared model.

Outcomes:

- per-turn checks (s1m-style), tests, `patch_hash`, `answer_hash`;
- full cost by model and by token class, including rebuild tokens after a switch (the same definition as `caching_survey.py`).

The live path alternates between host and routed across reps, balanced by scenario. One-sided cache history then shows up as a measured covariate, not a hidden bias.

**Tier B, session fork (phase 2).** A turn fork cannot see downstream divergence: a routed turn changes the context of every later turn. So for a sample:

1. fork at k ∈ {2, 5, 8};
2. continue both branches to the end of the session in separate clones;
3. compare remaining-session cost and final quality.

**Tier P is not used for routing.** A single-call host branch of a routed call finds the host cache cold, because the live world was routing. It would overstate the saving. So routing is never measured from single-call branches.

### (c) Effort routing, escalation, cheaper step

- **Cheaper step** (`_step_cheaper_model`) and **per-request effort.** These are Tier P single-call branches. When a step ran on a cheaper model or at a routed effort, the branch is the same request on the host model at the host's default effort. In this case the host cache is warm in both worlds, because the neighbouring steps run on the host. The single-call fork is therefore the right unit. Equivalence is `action_match`, plus `readonly_both` (`step_actions.response_readonly`).
- **Escalation** (phase 2b, Tier B). Sample an escalation decision near the gate, `|p − gate| ≤ 0.15`. Fork mid-turn:
  - branch E escalates;
  - branch N stays on the cheap model, and the reverse for non-escalations.

  Both continue to the end of the turn in `BranchRunner`, which runs inside a DTU or Docker sandbox. Equivalence is checks, tests and `resolved`.

### Side-effect safety (the I2 guard)

`measure.branch_tool_policy(name, args)` allows a tool call only if all of these hold:

1. the tool is in `step_actions.READ_ONLY_TOOLS`, or the branch is Tier B and the call is scoped to its clone;
2. neither the tool name nor its canonical arguments match `jev_cua.SIDE_EFFECT` (the confirmed I2 pattern: delete, send, post, push via "publish", merge, deploy, and the rest);
3. the tool is not `delegate`, `task` or a recipe tool.

Tier B bash runs with the network off. A denied call returns `[branch] blocked side effect` and sets `censored="side_effect_blocked"`. Tier P never executes tools, except the read-only candidate in a lookahead.

### Sampling, concurrency, caps, privacy

- **Sampling.** Deterministic: `sha256(seed|session_id|decision_id) < π`. Rates are set per lever. Decisions within `oversample_near_gate.band` of the gate are oversampled ×`factor`. **Declined decisions are sampled too**, so any gate can be simulated afterwards. Every row stores `sample_prob` and `sample_weight = 1/π`. **A/A null forks** (both sides on the same path) take 10% of forks.
- **Concurrency.** `BranchWorker` runs off the critical path, with the same pattern as `ShadowWorker`:
  - a bounded queue, `max_concurrent=1`;
  - overflow is dropped and counted;
  - drained at `Runtime.close` within `shadow_drain_ms`.

  An optional `branch_api_key_env` keeps branch traffic off the live key's rate limit.
- **Caps.** Before launch, the cost is estimated as prompt tokens × write price. It is reserved against `max_usd_per_session`, `max_usd_per_day` and, in benchmarks, the campaign ledger (`campaign.py`). Over the cap, the fork is censored as `budget`.
- **Privacy.** Host branches send exactly what the live session already sends, to the same provider. Judge use keeps the `allow_external_state` gate. `store_text: false` (the default) keeps only hashes, tool names and token counts. Benchmark traffic may set `store_text: true`.

### Receipts (`method="measured_parallel"`)

`efficiency.measured_pair(...)` returns the standard receipt shape, plus these fields:

- `pair_id`;
- `realized`: true when `live_path=fast`, because the saving actually happened;
- `supersedes`: the event id of the estimated receipt for the same `decision_id`;
- `measurement_usd`: the branch's own spend;
- `detail.cache_correction_usd`;
- `detail.equivalence`.

`aggregate()` changes:

1. For each `decision_id`, a measured receipt replaces the estimated one.
2. `realized=false` receipts go to a separate `opportunity` block and never into totals.
3. New `measured` sub-totals, `measurement_spend`, and per-lever `calibration` (Σmeasured / Σestimated over paired decisions, with a bootstrap CI).

Recompute by repricing each row's raw tokens in `measure/*.jsonl`. Row and receipt are joined on `pair_id`.

## 2. Dataset schema: `fast-decisions-measure/v1`

One JSONL row per pair, written to `<events_dir>/measure/<session>.jsonl` (per run in benchmarks).

**Identity**
- `schema`, `pair_id`, `unit` (decision|call|turn|session)
- `fork_kind` (single_call|lookahead|turn|session|mid_turn|null)
- `lever` (prepared_action|cheaper_model|effort|turn_start|escalation)
- `campaign`, `suite`, `split`, `task_id`, `scenario_id`, `rep`, `session_id`
- `turn_index`, `step_index`, `decision_id`, `provider_call_id`
- `build_sha`, `policy_hash`, `traffic`
- `live_path`, `branch_order`, `start_offset_ms`
- `sample_prob`, `sample_weight`, `sample_stratum`, `seed`

**Features**
- Models and effort: `host_model`, `host_effort`, `candidate_model`, `candidate_effort`
- Judge: `decision_kind`, `judge_backend`, `judge_choice`, `judge_p`, `judge_margin`, `gate`, `would_act`
- Session position: `turns_so_far`, `calls_so_far_session`, `calls_so_far_turn`
- Context size: `context_tokens` (prompt at the fork), `tail_tokens`, `shared_warm_tokens`
- Cache state: `cache_state_host` and `cache_state_candidate` (warm|partial|cold, plus `secs_since_same_model_call`), `gap_since_prev_turn_s`
- Task and step: `step_kind`, `phase`, `prompt_chars`, `workspace_files`, `task_family`
- Load: `concurrent_live_calls`

**Outcomes, per side** (`policy.*` and `baseline.*`)
- `models[]`, `calls`, `input_tokens`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens`
- `cost_usd_provider`, `cost_usd_repriced`, `cost_usd_corrected`
- `wall_s`, `model_s`, `judge_s`
- `switches`, `rebuild_tokens`
- `first_action` (tool, args_hash), `finish_reason`
- `checks_passed`, `tests_passed`, `patch_hash`, `answer_hash`, `resolved`, `rubric_score`

**Comparison**
- `action_match`, `action_superset`, `next_action_match`, `refetch`
- `outcome` (identical|equivalent|both_pass|policy_worse|policy_better|indeterminate), `equivalence_method`
- `delta_usd`, `log_cost_ratio`, `delta_s`, `log_time_ratio`
- `cache_correction_usd`
- Flags: `divergent`, `ttl_refresh_risk`, `censored` (null|budget|queue|deferred_expired|side_effect_blocked|error)
- `estimated_usd_saved` (what `efficiency.py` would have claimed), `receipt_event_id`

## 3. Measurement campaign (≤ $10k)

### Workloads

New multi-turn suites go in `scripts/battery_tasks.py`. Each turn has its own check. Scenarios are preregistered, and the split is by scenario.

- **`s1l`**: 24 scenarios of 8–12 turns (12 m8-dev, 12 m8-holdout), built from S1 and S2 tasks.
- **`s1xl`**: 8 scenarios of 16–24 turns.

| Block | Workload | Design | Pairs | Est. $ |
|---|---|---|---|---|
| P0 pilot | s1m m-dev + 2 s1l, 10 S3 | both hosts, 2 reps, fork every turn, single-call forks at 100% | ~250 | 200 |
| A | single-call forks piggybacked on every block | prepared, cheaper-step, effort; π=1 in benchmark | ~6,000 | 400 |
| B | s1l | 24 × {Opus 5.5, Fable 5.1} × cache {warm, cold: 6-min gap} × 3 reps; turn fork at every turn; live path balanced | ~2,800 turns | 2,020 |
| C | s1xl | 8 × 2 hosts × 2 reps, warm, fork every 2nd turn | ~300 | 560 |
| D | s1l session forks (phase 2) | k ∈ {2, 5, 8}; Opus 2 reps, Fable 1 | 216 | 650 |
| E | S3 SWE-bench Verified | 60 instances (30/30) Opus × 2 reps + 30 Fable × 1; turn-start fork + mid-turn escalation forks | ~400 | 410 |
| F | Deep SWE (`~/dev/amplifier-agent/.amplifier/evaluation/deep-swe`) | 40 tasks × 2 reps, Opus; turn-start fork; `partial` as the quality score | 80 + ~600 calls | 960 |
| G | JobBench easy split | 30 tasks × 2 reps; turn-start fork; rubric judge | 60 | 420 |
| H | measure-off control | 20 s1l sessions, Opus, no measurement | n/a | 40 |
| | **Subtotal + 25% retry/infra reserve** | | | **≈ 7,100** |

**Cost assumptions.** Unit costs are scaled from measured means:

- 4-turn s1m session: about $0.8 on Opus.
- 8-turn session: about 2.5× the 4-turn cost (the caching README's assumption).
- Fable session: about 2.5× Opus.
- S3 instance: about $1.
- Deep SWE task: about $6. JobBench task: about $3. Both of these are **unmeasured**.

P0 recalibrates every unit cost before anything else launches. The remaining **$2.9k is held back**. It is released only by a preregistered rule after the interim analysis: top up the strata whose 95% CI on the savings ratio misses ±10%.

**Wall time.** About 7–9 days of elapsed time on 6 lanes, mostly unattended. The cold-cache block (6-minute gaps) and Deep SWE's Docker runs dominate.

**Power.** The target is a 95% CI on the geometric-mean cost ratio within ×/÷1.10, i.e. a half-width of ln 1.10 = 0.095. The effective sample size is n = (1.96σ/0.095)².

- Separate-arm σ was 0.17–0.38. Same-prefix forks should be tighter. With a conservative σ = 0.35, n = 52.
- Turns are clustered within sessions (m ≈ 8, assumed ICC 0.2), giving a design effect of 2.4. That makes **about 125 turn pairs (about 16 sessions) per stratum**.
- The core strata are host (2) × length band (turns 1–3, 4–8, 9+) × cache state (2) = 12 strata, needing about 1,500 pairs. Block B and C supply about 3,100, which leaves room to split by decision kind.
- Read-shortcut equivalence within ±3 points needs about 1,000 forks per judge configuration, which Block A covers.
- P0 measures σ and the ICC. If σ exceeds 0.45, the held-back reserve goes to Block B.

### Analysis (`evals/measure_analysis.py`)

1. **Recompute every row from raw tokens.** Repriced costs must equal `cost_usd_provider` to within 1e-6. Reconcile against a billing export for the **dedicated campaign API key**, because `cost_usd` is a price table, not a bill.
2. **Describe by stratum.** Weighted geometric-mean ratios, with a cluster bootstrap (resample tasks, then sessions). Each lever is compared with its A/A noise floor; equivalence is reported as a rate above the A/A disagreement rate.
3. **Savings model.** A linear mixed model on `log_cost_ratio` (statsmodels MixedLM; bambi for a Bayesian check).
   - Fixed effects: host, lever/decision kind, log `context_tokens`, turn band, cache state, `switch_in`, a spline in `judge_p`, suite.
   - Interactions: host × cache and host × log context.
   - Random intercepts: task and session.
   - A companion logistic mixed model on `outcome ∈ {policy_worse}` handles quality.
4. **Session-level prediction.** Predicted Δ$ = Σ_t baseline_cost_t·(1 − exp(ŷ_t)·smear), with Duan smearing. Prediction intervals come from a parametric bootstrap that includes the random effects. Session-fork rows (Block D) validate whether summing turn-level predictions holds up against measured downstream divergence.
5. **Validation.** Hold out scenarios, plus the holdout halves of S3, Deep SWE and JobBench, and preregister them in `docs/design/parallel-measurement-PREREG.md` before they run. Success targets:
   - 90% PI coverage between 0.85 and 0.95;
   - calibration slope between 0.8 and 1.2;
   - session Δ$ MAPE reported.

   Also report each lever's bias for `efficiency.py`'s estimators (measured / estimated).

## 4. Implementation plan

### New files

- `src/amplifier_fast_decisions/measure.py`
  - `MeasureConfig.from_policy`, `sample(kind, key, p, gate) -> (bool, prob)`
  - `BranchWorker` with `submit`, `defer_until_same_model_call`, `run`, `health`
  - `BudgetLedger`
  - `branch_provider(coordinator, provider_key)` (second instance, stub hooks)
  - `branch_tool_policy`
  - `tail_correction(usage, tail_tokens, model, effort)`
  - `PairRow` and `write_row`
- `src/amplifier_fast_decisions/measured_provider.py`
  - `MeasuredProvider(TransparentFacade)` wraps the **raw** provider, inside `RoutedProvider`. On `complete()` it returns the live response unchanged (same object identity). If the call was routed (correlated through the preceding `slow_start`, `model_routed`, `effort_routed` or step event), it schedules a host or default-effort branch.
- `scripts/fork_session.py`: clones the workspace and session dir under a new session id, and asserts that the message-history hash is unchanged.
- `scripts/branch_runs.py`: the Tier B driver (turn and session forks), built on `battery.py`'s launcher, waiter and evaluator, and the campaign ledger.
- `evals/measure_analysis.py`
- `behaviors/fast-decisions-measure.yaml`: composes `fast-decisions.yaml` and adds the `measure:` block. **Not default-on.**

### Changes to existing files

- `contracts.py`:
  - add `Policy.measure: dict | None = None` and `validate_measure()`. Keys: `enabled`, `live_path`, `levers`, `sample`, `oversample_near_gate`, `null_fork_rate`, `seed`, `lookahead`, `max_usd_per_session`, `max_usd_per_day`, `max_concurrent`, `queue_capacity`, `store_text`, `branch_api_key_env`, `dataset_dir`;
  - add `measured_pair` to the event list.
- `service.py`:
  - `DecisionService.add_listener(fn)`, called from `emit`;
  - two guarded calls: `self.measure.on_shadow_decision(request, candidate, ...)` before the `slow("shadow_only")` return (`:312`), and `self.measure.on_fast_decision(request, candidate, ...)` before `return candidate` (`:346`).
- `runtime.py`: build `self.measure` when `policy.measure` is set; drain it in `close`.
- `observer.py` `mount`: when `policy.measure` is set, replace the provider mount point with `MeasuredProvider(raw)`. No change to `ShadowScorer`: its `shadow_agreement` joins rows on `decision_id`.
- `efficiency.py`: add `measured_pair()`; extend `aggregate()` (§1).
- `evals/cells.yaml`: `measure-*` cells with an R4 mechanism gate: `measured_pair` count ≥ expected, and censored ≤ 15%.
- `scripts/battery_tasks.py`: add the s1l and s1xl scenarios.

### `orchestrator.py`: do not touch

`complete()`, `decide_start_tier`, `_call_provider`, the escalation and planner blocks, and `_step_cheaper_model` all stay as they are. All correlation comes from events that are already emitted. The single allowed hook, used **only if** the P0 spike shows the kernel does not pass the replaced mount point to `execute()`, is one guarded line in `RoutedProvider.__init__`:

```python
provider = runtime.measure.wrap(provider) if runtime.measure else provider
```

Known approximation: with HC12 easy-turn shaping on, `MeasuredProvider` sees the shaped request. Measurement cells turn shaping off.

### Tests

- `tests/test_measure.py`:
  - sampling is deterministic and weights are correct;
  - budget refusal;
  - queue overflow is counted;
  - `branch_tool_policy` denies every `SIDE_EFFECT` match and every tool outside the allowlist;
  - tail-correction arithmetic.
- `tests/test_measured_provider.py`, against a fake provider:
  - the live response keeps its identity;
  - the branch uses the host model and the default effort;
  - the branch is deferred until after the next live call on the same model;
  - branch calls emit nothing to the session hooks.
- `tests/test_efficiency_measured.py`:
  - a measured receipt supersedes the estimated one;
  - `realized=false` stays out of totals;
  - recompute is exact.
- `tests/test_fork_session.py`
- A byte-identity test: with `measure=None`, the event sequence of a fake run is unchanged.

### Phases

- **P0 spike (1–2 days).** Verify three things: the stub-hook branch provider, mount-point wrapping, and resuming a forked session. Then run the pilot.
- **Phase 1.** Read-shortcut single-call and lookahead forks, cheaper-step and effort forks, turn-level routing forks in the harness, receipts, and analysis. Blocks A, B, C, E (turn start), H.
- **Phase 2.** Session forks (D). `BranchRunner` for mid-turn escalation in DTU sandboxes (E). Deep SWE and JobBench adapters (F, G).

## 5. Threats to validity

| Threat | Mitigation |
|---|---|
| Cache contamination between branches | Deferred launch plus `tail_correction`. Caches differ by model, which isolates them by construction. Turn and session branches start simultaneously. Rows record `shared_warm_tokens` and `cache_state_*`. Results are reported raw and corrected. |
| Cache history is one-sided (the live path shapes what is warm) | Live path alternated and balanced. Cache state is both a model covariate and an experimental factor (6-minute gap). Session forks measure the policy as a whole. |
| Ordering effects | `branch_order` randomized, `start_offset_ms` logged; order is included in the model as a nuisance term. |
| Nondeterminism | 10% A/A null forks give the noise floor for both cost and equivalence; replicate reps. |
| Measuring changes the cost: TTL refresh, rate limits, CPU | Branch calls never warm the live path. `ttl_refresh_risk` is flagged. A separate branch API key is used. Block H compares live cost with measurement on and off. Keep-alive receipts in measured sessions are flagged. |
| Selection, as in the trace study (only judge-declined cases were seen) | Sample every decision, accepted or declined, by preregistered π with IPW weights. Never select on outcomes. Live path balanced. Split by scenario. Holdout preregistered. |
| Informative censoring (blocked, budget, expired) | Every censored fork is written as a row. Report the rate by stratum, with worst- and best-case bounds. |
| Equivalence labels are weak | Deterministic checks first: tests, `patch_hash`, checks. Rubric or LLM grading only for JobBench, reported separately. Host-next-action agreement is secondary. |
| Synthetic workloads; price table, not billing | Deep SWE and JobBench added. Billing reconciled against the dedicated key. Production measure mode (Tier P, low π) supplies the real-traffic check. |
