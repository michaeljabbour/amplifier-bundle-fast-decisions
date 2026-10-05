# Parallel measurement v2: paired multi-turn sessions

Status: spec, not built. Base: `origin/main` `6206103`. Supersedes v1 (`docs/design/parallel-measurement-mode.md`).
Inputs: the pre-flight review (blockers B1–B3) and the 2026-10-01 pilot (`.amplifier/evaluation/fast-decisions/20261001-pilot/`:
`findings.md`, `step0_table.md`).

## 0. What changed from v1, and why

- **Single-call forks are no longer a savings unit (B1).** A skipped call's cache-tail write moves to the next call,
  so a single-call fork only re-derives the estimator.
- **Turn forks are gone (B2).** They measure a switch from a foreign history, not the policy's own-world cost.
- **Power is counted in scenarios (B3).**
- **Isolation uses a per-session nonce**, not deferral (§1.2).
- **Cache state is an outcome**, not a covariate.

The **primary unit** is a pair: one scripted multi-turn session per arm, all started from the same snapshot, compared
with the anchor arm on the same scenario, rep and host. Savings are reported in **Δ$ per session** (additive, and well
defined when an arm's cost is near 0) and as a cost ratio. Both are reported conditional on quality being
non-inferior.

## 1. Campaign design

### 1.1 Arms (per host stratum: Opus 5.5 = `claude-opus-5-5`, Fable 5.1 = `claude-fable-5-1`)

| Arm | Cell | What it isolates |
|---|---|---|
| **A0 anchor** | `plain-opus` / `plain` | The host alone |
| **A1 shipped** | `orch-default-opus` / `orch-default` (frozen `behaviors/fast-decisions.yaml`: `start_policy: judge`, `read_shortcut: false`) | The product as shipped |
| **A2 sticky** | `orch-sticky-opus` / `orch-sticky` (new) | Decides the model once, at session start, and never switches. A1 − A2 is the cost of switching. |
| **A3 cheap control** | `plain-sonnet` (`claude-sonnet-5`, no effort set, which means high) | "Just use the cheap model" (R5). **Host-independent**: run once per scenario and rep, and used as the control for both strata. |
| **A4 read shortcut** (Opus only) | `orch-default-rs-opus` (new: A1 with `read_shortcut: true`, default local judge) | The read-shortcut factor, run on one stratum only to keep cost down |

**A2 is built in the harness, not the orchestrator.**
1. `evals/paired.py` calls `orchestrator.decide_start_tier` once, read-only, on the turn-1 prompt. It uses the frozen
   judge and a stub service, the same pattern as `evals/judges.py`.
2. It writes the decision to the run manifest.
3. It launches either `orch-pin-host` (the orchestrator bundle with `model_routing: null`) or `orch-pin-cheap`
   (`model_routing.start_policy: cheap`, `start_model: claude-sonnet-5`, the same `start_effort` as A1, no escalation
   except on provider error).

`orchestrator.py` is not touched.

### 1.2 Cache isolation and "parallel": per-session nonce, one key, concurrent start

Probe facts that decide this:
- **A cache entry exists only at a marker, and only for its exact prefix** (a): a longer cached prompt does not serve
  its own prefixes.
- **Two keys in one org do not share** (b).
- **Simultaneous identical first requests both pay the write** (c).
- **Caches are per model** (f), and **on Sonnet 5, per effort level** (e).

Arms that could read each other's cache on a shared key:
- A0, A1, A2 and A4 on the host model;
- A1, A2 and A4 on Sonnet at the same effort.

A3 is isolated already: Sonnet at high effort never shares with Sonnet at medium.

With only 2 keys, key-per-arm cannot separate 4 or more mutually-sharing arms. A **staggered start** does not work
either: every read refreshes the 5-minute TTL (d), so the live arm keeps the shared prefix warm for its whole
session. Isolation would need the arms to run one after another, with gaps of more than 5 minutes.

**Decision.** `forge_e2e._side_profile` adds one line to each session's system instruction:
`run-nonce: <uuid4>`. It is constant across a session's `--resume`s and different for every session.
- Every cache entry contains the system block, so every entry becomes session-unique, by fact (a).
- All arms of a scenario can then start **at the same moment on one key**, matching the time of day.
- No arm can read another arm's cache, and no artificial double write occurs, because the requests are never
  identical.
- Each session's first request is cold. That is the same for every arm, and it is recorded:
  - `first_req_write_static`: the tools and system prefix written by the first request;
  - a deterministic "warm-start" repricing, which treats those tokens as reads. It is reported as a sensitivity
    check only.
- The second key is used **only in the pilot**, to show by contrast that without the nonce, same-key arms do share.

Residual risk: if the provider places a marker on the tools block alone, an entry made of tools only could be shared.
The pilot measures `cross_arm_read_tokens`, which is the cache reads on a session's first request.

### 1.3 Scenarios: 60 new, 8–16 turns, none from the old dev tuning set

| Type | n | Source (public, untouched by earlier tuning) | Turn script (examples) | Graders |
|---|---|---|---|---|
| Code fix | 20 | SWE-bench Verified instances **not in any S3 run** (excludes every id under `~/dev/afast-orch-primary-20260924/swe-*` and the v4 set) | fix → explain the root cause → add a regression test → handle an edge case → refactor → docstring → review your own diff | Official grader after turn 1 and at the end of the session. Hidden per-turn tests run through `.swe/run`. Keyed facts for the explain/review turns. |
| Feature add | 20 | Aider polyglot exercises **outside the S2 40-exercise slice** (seeded draw, Python, Go and Rust) | implement → extend the API → add tests → performance change → error handling → README section | Exercism tests per turn, with hidden extra tests added at grading time (R3) |
| Review / explain / docs | 12 | Small pinned public Python repos (commit sha frozen) | explain a module → review a planted diff → write the docs page → fix the issue you found | Keyed-fact rubric (deterministic regex sets), doc-section checks, tests for the fix turns |
| Knowledge work | 8 | JobBench easy split, if the pilot shows it runs under `forge_e2e` within one day; otherwise 8 more review/docs scenarios | produce the deliverable → revise for new data → summarise | JobBench rubric judge (frozen model), reported separately |

**How turns are scripted.** The follow-up turns are **fixed scripts**, identical for every arm and hashed before
launch (R1). An adaptive AI-user simulator would make later prompts depend on each arm's output. That breaks the
pairing and adds variance the design cannot separate. The `AIUser` building block (`amplifier-evaluation
src/eval/ai_user/ai_user.py`) is used in two other places only:
- **(a) Authoring.** `scripts/scenarios/author_followups.py` drafts realistic follow-ups from each task. A human
  reviews them, then they are frozen in YAML.
- **(b) A sensitivity screen.** 6 scenarios × {A0, A1} with a live AIUser, to check whether scripting biases the
  saving. This is labelled screen.

Follow-ups are written to be safe for any arm: they refer to files and behaviour, never to the previous answer's
wording.

**Turn gaps** are part of the scenario and the same for every arm.
- 10 s by default.
- For a third of scenarios (stratified by type, seeded), two fixed turns follow a **7-minute gap**, which forces the
  5-minute entries to expire.
- `gap_schedule` is a design feature.

**Split.** Seeded, stratified by type: **train 40 / test 20**. It is preregistered in
`docs/design/paired-campaign-PREREG.md` (scenario hashes, arms, hosts, decision rules, model spec) before any paid run.

**Long-session block (external validity).** 6 extra scenarios of **40 turns**, Opus stratum only, arms
{A0, A1, A2, A3}, 1 rep. Real sessions run 50–200 turns. Predictions beyond 40 turns are labelled extrapolation.

### 1.4 Quality

- **Per turn:** pass/fail from that turn's checks.
- **Per session:** `turn_pass_frac`, `final_state_pass` (all hidden tests at the end), and `critical` (a protected
  file was modified, the evaluator crashed, or the anchor passed a check this arm failed on the same scenario and rep).
- **Non-inferiority per arm and host:**
  - the paired mixed-model difference in `turn_pass_frac` has a 95% lower bound ≥ −0.05;
  - session-level McNemar on `final_state_pass` is reported.
- **Savings** are reported (i) over all pairs and (ii) over pairs where both sessions passed. An arm that fails
  non-inferiority gets **no savings claim**.

### 1.5 Power (scenarios are what binds)

The CI half-width on the mean log ratio is 1.96·√(σ_b²/S + σ_w²/(S·m)), using the cell-adjusted values from
`step0_table.md`.

| Contrast | σ_b / σ_w used | S=60, m=2 | S=40 (train), m=2 |
|---|---|---|---|
| Routing, Fable (s1m values) | 0.265 / 0.297 | ±9% | ±11% |
| Routing, Fable (S1 values, worst case) | 0.433 / 0.258 | ±13% | ±16% |
| Routing, Opus (S1 values) | 0.162 / 0.266 | ±7% | ±8% |
| Routing, Opus (s1m values) | 0.027 / 0.211 | ±4% | ±5% |

- Opus reaches ±10%.
- Fable reaches ±9–13% pooled. The pilot's floor for ±10% on Fable was about 80 scenarios. The reserve rule (§4)
  can add 20 scenarios, or a third rep on Fable.
- Quality power is modest: with 120 pairs per arm and host, McNemar detects a drop of about 10 points.

## 2. Dataset

Files: `<root>/rows/sessions.jsonl` (one row per session per arm) and `<root>/rows/turns.jsonl` (one row per turn per
arm). Schema id: `fast-decisions-paired/v1`.

**Pre-session features** (known before launch; the only allowed covariates):
- Identity: `scenario_id`, `scenario_hash`, `source`, `task_type`, `language`, `split`
- Design: `host_model`, `arm`, `cell`, `rep`, `scripted_turns`, `gap_schedule`, `n_long_gaps`
- Prompt sizes: `turn1_prompt_chars`, `total_prompt_chars`
- Workspace size: `workspace_files`, `workspace_bytes`
- Difficulty: `swe_difficulty` (SWE-bench label, where present)
- **`anchor_*` proxies:** the A0 session's tokens or cost at each turn. They are not affected by the treatment of any
  other arm, so they are valid covariates for the other arms. They are never used for A0 itself.

**Provenance:** `build_sha`, `bundle_tree_sha`, `price_table_sha` (sha256 of `savings.DEFAULT_RATES`), `model_ids`,
`served_models`, `nonce_mode`, `key_fingerprint` (sha256 prefix only), `scheduled_start`, `actual_start`,
`wave_id`, `concurrent_sessions`.

**Session outcomes:**
- Cost: `cost_usd_provider`, `cost_usd_recomputed`
- Per model: `tokens.{model: {input, cache_read, cache_write, output}}`
- Calls and time: `n_req`, `n_bg`, `wall_ms`, `exec_ms`
- Switching: `model_switches`, `switches_turn_boundary`, `switches_midturn`, `rebuild_write_tokens`, `rebuild_usd`
  (same definitions as `caching_survey.py`)
- Cache: `cache_hit_share`, `first_req_write_static`, `cross_arm_read_tokens`, `warm_start_cost_usd`
- Quality: `turn_pass_frac`, `final_state_pass`, `critical`, `failure_labels`
- Receipts: `receipt_usd_saved_sum` (for calibration)
- Status: `status` (ok | agent_fail | infra_fail), `attempt`

**Turn rows:**
- Design (pre-treatment): `turn_index`, `turn_prompt_chars`, `gap_before_s`
- Outcomes: `models_used`, tokens by class, `cost_usd`, `calls`, `wall_ms`, `switched_in`, `pass`

**Pair rows** (derived by `rows`): (scenario, rep, host, arm) vs A0, with `delta_usd`, `log_cost_ratio`, `delta_s`,
`delta_turn_pass`, `both_pass`.

Rules:
- `cache_hit_share`, `model_switches`, per-arm context size and every per-turn token count are **outcomes**. They may
  be described, mediated or decomposed, but never used as covariates.
- Every cost is recomputed from tokens with the frozen price table. It must match `cost_usd` within 1e-6, or the run
  is flagged.

### Savings model (`evals/measure_model.py`)

1. **Effect estimates:** a paired mixed model per host stratum, comparing each arm with A0, with fixed effects for
   `task_type` and `n_long_gaps`. Fitted with statsmodels MixedLM. A bambi fit confirms the intervals. Two outcomes:
   - `log_cost_ratio ~ arm·task_type + arm·n_long_gaps + log(anchor_cost) + (1|scenario) + (1|scenario:rep)`;
   - `delta_usd ~` the same terms, weighted by 1/anchor_cost² for heteroscedasticity.
2. **Prediction:**
   - For a new session with known features: Δ$ = anchor_cost × (exp(ŷ) − 1). `anchor_cost` comes from an anchor-cost
     submodel fitted on A0 rows using pre-session features only.
   - **Per-1k-sessions:** sum over a target feature mix. Two mixes: the campaign's own, and the owner's production
     mix, scanned from `afast savings` logs for turn counts and gap distribution.
   - **Prediction intervals** come from a parametric bootstrap that draws fixed effects, new-scenario random effects
     and residuals. The 1k-session interval treats sessions as distinct scenarios.
3. **Validation on the 20 test scenarios** (preregistered):
   - 90% per-session PI coverage between 0.83 and 0.97;
   - the measured total Δ$ on the test set falls inside the predicted 90% interval;
   - calibration slope of predicted vs measured Δ$ between 0.7 and 1.3.
4. **Receipt calibration** (descriptive): `receipt_usd_saved_sum` vs measured Δ$ per arm. This is the measured check
   on `efficiency.py`.

## 3. Budget and wall time (≤ $6,000)

**Unit costs** come from `fd-judge-realistic/docs/evidence/2026-10-01-caching/sessions.csv` (non-infra runs, means).

4-turn s1m sessions:

| Cell | Mean cost |
|---|---|
| plain-opus | $0.52 |
| orch-default-opus | $0.68 |
| plain (Fable) | $1.34 |
| orch-default (Fable) | $0.85 |
| plain-sonnet | $0.70 |

Single-turn S3 sessions: plain (Fable) $1.22, Sonnet $1.06.

Scaling assumptions:
- A 12-turn session costs **4.2×** a 4-turn session. The caching README's 8-turn = 2.5× assumption, extrapolated
  linearly in context.
- Tasks are bigger than S1: SWE ×1.5, polyglot ×1.2, docs ×1.0. That gives a mixed-scenario factor of about 1.25.

| Arm | Est. $ per session (≈11.5 turns) |
|---|---|
| A0 Opus | 2.60 |
| A1 Opus | 3.10 |
| A2 Opus | 2.70 |
| A4 Opus | 3.10 |
| A3 Sonnet | 3.50 |
| A0 Fable | 6.70 |
| A1 Fable | 4.00 |
| A2 Fable | 4.00 |
| **One scenario-rep (8 sessions)** | **≈ 29.70** |

| Block | Sessions | Est. $ |
|---|---|---|
| Pilot (§5) | ~40 | ≤ 150 (planned 130) |
| Main: 60 scenarios × 2 reps × 8 sessions | 960 | 3,564 |
| Long block: 6 × 40 turns × 4 arms (about $12 each) | 24 | 288 |
| AIUser sensitivity screen (6 × 2, plus simulator cost) | 12 | 50 |
| **Planned** | | **≈ 4,030** |
| **Reserve** | | **≈ 1,970** |

Reserve rules, preregistered, applied in order:
1. Infrastructure retries (expected about 8%): about $300.
2. Unit-cost overrun. If the pilot shows more than 1.3× the estimates, drop A4 first, then the long block. Never go
   below 40 scenarios.
3. Top-up. If the Fable CI on the train split is wider than ±12%: add 20 scenarios, about $600 for the Fable
   stratum plus A3. Otherwise run a third rep on Fable train scenarios, about $590.

A hard stop is reserved in the `campaign.py` ledger at $6,000.

**Wall time** at 6 concurrent sessions.
- A **wave** is all the arms of one host stratum of one scenario-rep, started together:
  - Opus wave: A0, A1, A2, A4 and A3 (5 sessions);
  - Fable wave: A0, A1 and A2 (3 sessions).

  The two Fable waves of consecutive scenario-reps run together. So 2 scenario-reps take 3 slots of time.
- A session averages 11.5 turns × about 1 min, plus about 4.7 min of scripted gaps (s1m was 0.4–0.65 min per turn;
  SWE turns are longer). A wave is set by its slowest arm, about 1.4×, so about 24 min.
- Main block: 180 wave slots × 24 min ≈ **72 h**. Long block: about 6.5 h. Pilot: about 4 h.
- **Total: about 3.5–4 days unattended.**

## 4. Threats to validity

| Threat | Handling |
|---|---|
| Cache sharing | Nonce. `cross_arm_read_tokens` is audited. Cold start is equal for every arm; warm-start repricing is a sensitivity check. |
| Ordering and time of day | Arms start together within a wave; wave order is seeded and randomised. |
| Nondeterminism | 2 reps, pilot A/A, and a scenario:rep random effect. |
| Informative censoring | Agent failures are outcomes. An infra failure reruns **the whole wave**. A wave that fails 3 times is excluded and reported with best- and worst-case bounds. |
| Post-treatment covariates | A whitelist in `rows` allows only pre-session features and `anchor_*` proxies. |
| Tuning data reused | All 60 scenarios are new; the test split is preregistered and never tuned on. |
| External validity | The 40-turn block, the AIUser screen and the production mix. Beyond 40 turns is labelled extrapolation. |
| Frozen inputs | Candidate sha (R6). Model ids are pinned, and a run is refused if `served_model` differs. Price-table sha and scenario hashes are recorded. |
| Receipts mixed with measurements | `AFAST_TRAFFIC=test`. `efficiency.aggregate` gets `method_class` (measured \| usage_verified \| model_predicted \| estimated) and never sums across classes. |
| Grader drift | Deterministic, out-of-process grading. `paired.py grade` re-grades without any model call. |

## 5. Pilot (≤ $150, about 4 h) and what to build first

Pilot scenarios: 3 polyglot, 1 SWE and 1 review scenario, 8 turns each, with one carrying the 7-minute gaps.

| Check | Sessions | Pass criterion |
|---|---|---|
| P1 nonce isolation | 2 scenarios × {A0, A1, A2, A3} Opus, concurrent | `cross_arm_read_tokens` = 0, or at most the tools-only size, on every first request |
| P2 the contrast without a nonce | 2 × A0 clones, same key, offsets 0 s and 60 s; repeated on key 2 | Sharing shows up on the same key (the expected reads); none on key 2. This shows the nonce is needed. |
| P3 A/A noise | 3 scenarios × {A0, A1} Opus, each ×2, concurrent | SD of the A/A log ratio < 0.15 (otherwise move to 3 reps) |
| P4 gap expiry | 1 gap scenario × {A0, A1} | The first request after a 7-minute gap writes again |
| P5 Fable unit costs | 2 × {A0, A1} Fable | Within 1.3× of §3 (otherwise apply reserve rule 2) |
| P6 SWE multi-turn smoke | 1 × {A0, A3} | Per-turn grading and the official grader both run |
| P7 grader determinism | re-grade everything twice | Identical results |

Go/no-go: P1, P3, P6 and P7 must pass, and the infrastructure failure rate must stay under 10%.

**Build order for the pilot:** the spec and loader, 5 scenarios, nonce, per-turn gaps, the paired driver (plan, run,
rows), A2 decision logic, the cache audit, then the tests in §6.

## 6. Implementation spec (campaign harness)

**New files**

- `scripts/scenarios/spec.py`
  - `TurnSpec(prompt: str, checks: list[Check], gap_before_s: int = 10, add_files: dict = {})`
  - `ScenarioSpec(id, source, task_type, language, split, workspace: WorkspaceRef, turns: list[TurnSpec], protected)`
  - `load(dir) -> list[ScenarioSpec]`, `scenario_hash(spec)`, `to_battery_task(spec) -> battery_tasks.Task`
    (`kind="scenario"`)
  - Check kinds: `tests`, `hidden_tests`, `swe_official`, `keyed_facts`, `doc_sections`, `rubric`
- `scripts/scenarios/build_{swebench,polyglot,repos,jobbench}.py`: build frozen YAML into
  `evals/scenarios/msess-v1/*.yaml`, plus `INDEX.json` with hashes. SWE reuses `evals/swebench/forge_swebench.py`
  workspace and image logic.
- `scripts/scenarios/author_followups.py`: AIUser-assisted drafting; output goes to `drafts/` and never straight to
  `msess-v1/`.
- `evals/paired.py`: the campaign driver (stdlib plus yaml). Exit codes 0 / 3 (budget) / 4 (precondition), as in
  `battery.py`:

  ```
  paired.py plan   --design evals/paired/msess-v1.yaml --out ROOT [--seed 20261002]  # schedule.json, budget reservation, prompt hashes (R1)
  paired.py pilot  --out ROOT --budget-usd 150                                      # P1-P7, writes pilot_verdict.json
  paired.py run    --out ROOT --parallel 6 [--waves N] [--resume]                   # adopts finished/live workers (R6)
  paired.py grade  --out ROOT                                                       # re-grade preserved workspaces, no model
  paired.py rows   --out ROOT                                                       # sessions.jsonl, turns.jsonl, pairs.jsonl
  paired.py report --out ROOT                                                       # descriptive, NI, receipt calibration -> report.md
  ```

  Internals:
  - `plan` runs `battery.py prepare` once per (cell, split, rep), with `--tasks` limited to the schedule's scenario
    ids.
  - `run` launches each wave through `forge_e2e.launch_run` / `wait_for_result`, with a semaphore of 6. A wave's
    launches must fall within 60 s of each other, or the wave is restarted.
  - A2: `sticky_decision(turn1_prompt, frozen_policy) -> "host" | "cheap"` is recorded in `schedule.json`.
- `evals/paired/msess-v1.yaml`: the design (arms → cells, hosts, splits, reps, gap fraction, nonce mode, budget).
- `evals/measure_model.py`: `fit --rows ROOT/rows --prereg ...`, `validate --split test`, `predict --mix production.json`.
- `docs/design/paired-campaign-PREREG.md`: committed and hashed before the main run (the runner checks the hash).

**Changes to existing files**

- `scripts/battery_tasks.py`
  - Register the splits `msess-pilot`, `msess-train`, `msess-test` and `msess-long` through `spec.load`.
  - `evaluate_scenario_turn` dispatches to `spec` checks for spec-based scenarios. The existing m-dev and m-holdout3
    paths stay unchanged.
- `scripts/forge_e2e.py`
  - `_run_scenario_turns`: per-turn `gap_before_s` from the task spec (falls back to `turn_gap_seconds`); record
    `turn_started_at` and `turn_ended_at`.
  - `_side_profile` and `_composed_profile`: when the manifest has `cache_nonce: per_session`, add `run-nonce: <uuid>`
    to the system instruction; record the nonce.
  - `api_key_env`: per-run override (used for the pilot's P2 only).
- `scripts/battery.py`
  - Add `msess-*` to the `--split` choices.
  - `_window_metrics`: per-turn token windows from the turn timestamps.
- `evals/cells.yaml`: add `orch-sticky`, `orch-sticky-opus`, `orch-pin-host(-opus)`, `orch-pin-cheap(-opus)` and
  `orch-default-rs-opus`. Each has an R4 mechanism gate:
  - A1: `difficulty_judged` is present;
  - A2: at most one `difficulty_judged` per session and `model_switches == 0`;
  - A4: `scored` is present.
- `evals/suites.yaml`: add an `msess` suite.
- `src/amplifier_fast_decisions/efficiency.py`: add `method_class` to receipts; `aggregate()` returns totals per
  class, with no cross-class sum.

`orchestrator.py`: **no change.**

**Tests (offline CI, `unittest discover -s tests`)**

- `test_scenario_spec.py`: stable hashes, deterministic prompts, gap schedule honored.
- `test_paired_schedule.py`: waves co-start, at most `--parallel` sessions, seeded order, exit 3 on budget, an infra
  failure reruns the whole wave, `--resume` adopts finished workers.
- `test_paired_rows.py`: recomputed cost equals `cost_usd` within 1e-6, per-turn windows, the cross-arm read audit,
  the covariate whitelist.
- `test_nonce_profile.py`: the nonce is unique per session and stable across `--resume`.
- `test_sticky_arm.py`: the decision is deterministic and maps to the right cell.
- `test_measure_model.py`: recovers synthetic effects; PI coverage is 0.85–0.95.
- `test_efficiency_method_class.py`: classes are never mixed; old receipts count as `estimated`.

## 7. Phase 2 (not in this campaign): production measure mode

This is the cheapest sound version given the probe facts. It needs no extra model calls and no orchestrator change.

- **Usage-verified skip receipts** (`src/amplifier_fast_decisions/efficiency_verify.py`, run post hoc by
  `afast efficiency verify`):
  - For each prepared-action skip, the next same-model call is located in `slow_end` events.
  - The skip is `usage_verified` only if **all** of these hold:
    1. at most 18 content blocks between the last written cache entry and the next call;
    2. the time since the last same-model call is under 270 s;
    3. the model is the same, and on Sonnet the effort is the same;
    4. the next call's `cache_read_tokens` is at least the expected prefix (a confirmed read).
  - When all hold, the saving is the skipped call's read, uncached input and output (the size of the `tool_use`
    envelope). Probe g1/g2 showed cache writes are neutral under these conditions. Otherwise the receipt is flagged
    `conditions_failed` and charged the observed excess write. Each condition is recorded on the receipt.
- **Routing and switching in production** cannot be paired within a session. Receipts stay `estimated`. A
  `model_predicted` column applies the campaign's frozen savings model to each session's pre-session features, with
  its prediction interval.
- **Optional, sampled:** offline paired replays of real sessions through the campaign driver, as a scenario source.
  This needs explicit consent (docs/PRIVACY.md).
