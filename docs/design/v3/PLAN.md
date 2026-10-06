# fast-decisions v3 study program: plan

Status: design, for approval. Author: zen-architect. Date: 2026-10-05.
Inputs: `/tmp/v3-history.md`, `/tmp/v3-smarttool-audit.md`, `fd-paired@8e7faf3` (evals/paired.py, evals/judges.py,
docs/evidence/2026-10-02-paired-campaign, 2026-10-05-effort-control, 2026-10-06-effort-control-fable, paper 2026-10-02).
Budget: $20k total; ~$4.6k spent; **this plan: $10.08k planned, $1.95k contingent, $2.97k reserve (19.8%) = $15.0k.**

---

## 0. What the existing data already says (computed for this plan, $0, from main-v1 rows)

These four numbers decide the shape of v3. All come from `docs/evidence/2026-10-02-paired-campaign/data/` at `8e7faf3`.

1. **Per-session cost basis** (tools-normalized mean, ~11.2 scripted turns): plain Fable $5.31, plain Opus $2.13,
   plain Sonnet (default effort) $3.22, sticky on Fable $3.33, sticky on Opus $2.61. Mean wall 4.9-8.8 min per session.
   Throughput: 1,036 sessions in 30.9 h at `--parallel 4` waves (~33 sessions/h; ~26 min per wave slot incl. setup and hidden tests).
2. **Variance for power:** A/A per-session SD of log cost ratio 0.069-0.073. For routing contrasts the between-scenario SD of
   log ratio is 0.26-0.35 and within-scenario (rep) SD 0.08-0.12. For same-model effort contrasts, between-scenario SD is
   ~0.10 (back-computed from the effort follow-ups' CIs, half-width 0.04 at n=23). Turn-pass paired-difference SD ~0.058/scenario.
3. **Jev is nearly "always route" at the start tier:** the sticky decider chose Sonnet in 248/280 sticky sessions (89%).
   Any decider comparison can only differ on the ~11% of sessions where they disagree.
4. **New discovery: effort switching is a cache-busting model switch in disguise.** Sticky sessions that *kept* the host cost
   **1.255x** (Fable, n=16) and **1.357x** (Opus, n=16) the plain host on the same scenario/rep, with the same request count
   (0.98x / 1.09x). Cause: the phase effort map (orient medium / explore low / implement high) changed effort between
   requests, and every effort change rewrote the prompt cache. Requests following an effort change wrote **15,642** cache
   tokens on average (n=823) vs **900** when effort was unchanged (n=900). Cache writes per session were 1.63x (Fable) and
   1.74x (Opus) the anchor. The shipped `by_tier.strong: null` path (`orchestrator.py:1570-1576`) no longer applies the phase
   map on the host tier, so the shipped unrouted-Opus path *should* now cost ~1.0x. That is unmeasured (RQ3). The main-v1
   Opus penalty, and the price-gate constants (1.38 / 1.11) derived from those pairs, are partly this artifact. They must be
   re-derived (E7).
5. **Coverage gaps in main-v1 that a holdout must fix:** task types are mixed 28, bugfix 18, feature 13, review 4, docs 4,
   explain 3 scenarios. Only **1** scenario has more than 300 workspace files, so the scope gate is essentially untested in
   situ. The keep-on-host task-type result rests on 3-4 scenarios per type.

> ★ **Insight:** decide-once works for model choice because the prompt cache belongs to one model, and the same holds for
> effort here: cache writes after an effort change were 17x the unchanged case. Principle: in a cached harness, any
> per-request knob that enters the cache key is a session-level decision, not a step-level one.

---

## 1. Research questions, mapped to the story

The story has five acts: **(I)** curiosity about Jev and its competitors (quality/cost/speed), **(II)** the observatory, **(III)** measurement
tooling, **(IV)** harder in-situ comparisons, **(V)** plateau: the right placement and configuration of a system-1 decision model.

| RQ | Question | Act | Closes open Q (history §5) | Study |
|---|---|---|---|---|
| RQ1 | What decisions did the observatory see during its week, and why was shadow agreement only 7.1% (117/1,642)? Is that a judge failure, a label artifact, or a local-scorer artifact? | II | 11 | A1 (analysis) |
| RQ2 | At the decision that actually moves money (session-start tier), does a decision model beat a deterministic rule, "always route", "always host", a local model, Clef/Luna/Sol, or the host model deciding for itself? How far is each from an outcome-derived oracle? | I -> IV | 1, 6, 7 | A0 + A2 (offline) + S1 (in situ) |
| RQ3 | What does the bundle cost when it does **not** route (Opus host, price gate closed)? Is the shipped path ≈1.0x plain? | IV | 2 | S1 |
| RQ4 | Strong-host effort: Opus at `medium` (unmeasured) and Fable at `medium` inside the bundle; plain vs bundle (2x2 per host). | IV | 2 | S1 |
| RQ5 | Best user config per host, chosen from the factorial *routing {off, decide-once} x strong effort {default, medium} x decider {rule, Jev, Clef, local, self, always} x scope gate {on, off}*, then validated live end-to-end with the shipped defaults (price gate, decide-once, `cheap: medium`). | IV -> V | 2, 3, 4 | S1 + X |
| RQ6 | Selective routing by task type: is the post-hoc review/explain/feature loss real (keep_on_host)? | IV | 3 | S1 |
| RQ7 | Do the results hold over 40-turn sessions with idle gaps (cache TTL, keep-alive), and does the Opus price gate stay right as cache-read share rises? | IV | 4 | S2 |
| RQ8 | Delegation routing in situ: does routing sub-agent tasks save money at equal quality on both hosts? Hypothesis: it pays even on Opus, because child sessions start with a cold cache. | IV -> V | 8 | S3 |
| RQ9 | The decision model as a portable smart tool: does a `decide` capability (audit P0) used at session launch save money in Claude Code, Codex and Copilot CLI at equal quality? | V | 9 | S4 |
| RQ10 | External validity on hard tasks, plus honest closure of the stalled 2,000-run SWE-bench Verified campaign: does the final config hurt resolve rate on all 500 Verified issues? | IV | 10 | S5 + C1 |
| RQ11 | What does v3 imply for the owner's real workload, and for the GOAL targets (≤0.50x cost, ≤0.60x calls, ≤0.70x time)? | V | 4 | A3 (analysis) |

**Deliberately not studied further (decisive closure, $0).** These are graded and documented, not re-run: per-step levers
(prepared read shortcut, cheaper-step, turn planner, HC05/HC08-HC11, loop-stop nudges). Reasons: real-workload math shows
they add $17-46 on Opus; the trace study found no useful judge; and per-step switching is exactly the cache-busting pattern
in §0.4. They stay off and are labelled "not confirmed". The same applies to CUA and select/search savings claims (no
avoided calls were ever shown). Their existing evidence moves to the companion report.

---

## 2. Studies

### Shared method (all paired studies)

- **Harness:** `evals/paired.py`: every arm of a scenario-rep starts together from one frozen workspace with a per-session
  cache nonce. Applies the cache audit, the mechanism gate (served model + effort checked per session), memguard, and a
  ledger hard stop.
- **Cost basis:** `cost_usd_tools_normalized` from the fixed price table. The table is re-verified in E7. If any price moved,
  results are reported on both tables, and the table at preregistration time is primary. **Judge/decider charges are added
  to session cost** (E6g; closes open Q6).
- **Estimands:** geometric-mean cost ratio vs the host's plain default (scenario-cluster bootstrap, 10,000 resamples) and
  mean turn-pass difference (non-inferiority margin −0.05). Final hidden-test pass is a key secondary: exact McNemar, and a
  ≤5-point loss rule where the study is powered for it.
- **Preregistration:** one program-level `PREREGISTRATION-v3.md` is committed **before any S-study session**. It includes
  the frozen rule decider R*, the candidate configs C*_F and C*_O, all hypotheses, Holm families, and the deterministic
  config-freeze rule that S2-S5 inherit. Each study adds its design YAML, schedule and analysis script, all committed before
  its first session, with timestamps recorded in `prereg/PROVENANCE.md` (the main-v1 practice).
- **Concurrency:** `--parallel 8` waves admitted. Forge cap (30 sessions) and memguard bind first, so effective concurrency
  is ~25-30 sessions. Wall estimates use the measured ~26 min per 11-turn wave slot.
- **Generic stop rules:** ledger hard stop at each study's cap. Infra-failed waves >10% of attempted → pause and diagnose.
  Any mechanism-gate failure (wrong served model or effort) → stop. Cache-audit flags >2% of sessions → stop. Memory
  kills >2 → drop parallel by 2. **No outcome peeking:** the dashboard shows spend and infrastructure health only, never
  per-arm cost or quality, until the run is complete.

### A0: Phase-0 counterfactual on main-v1 (offline, $0, day 1-3)

- **Purpose:** freeze everything S1 needs before any new data exists, so S1 is a clean confirmation.
- **Method: potential-outcome policy evaluation.** Any decide-once decider produces a session that equals either the pinned
  host session or the pinned cheap session for that scenario. So its policy value is Σ_s cost(s, D(s)), computable from
  two pinned arms. On main-v1 the potential outcomes are approximated as follows. Cheap = the actual sticky-cheap session
  where one exists (124/140 per host); otherwise plain Sonnet × 0.821. Host = plain anchor (the §0.4 artifact is
  removed by construction).
- **Deciders:** recorded Jev decisions (`campaign/decisions.jsonl`); rule candidates fitted on the **train split only** (47:
  prompt length, task-type keywords, workspace files, combinations); always-route; always-host; cross-fitted oracle (choose
  on rep 1, evaluate on rep 2 and vice versa, so the oracle is not optimistic).
- **Outputs (frozen into the prereg):** R* (the best train rule); the disagreement rate d(Jev, R*); predicted S1 effects;
  candidate configs C*_F and C*_O; and the §0.4 effort-switch decomposition published as a finding with its own figure.

### A1: Observatory week (RQ1) (offline, ≤$40, days 1-5)

- **Data:** `~/.amplifier/fast-decisions/events/` (4,482 session files, 464,883 events, 09-17..10-05) and `events-eval/`.
- **Method:**
  1. Separate production from eval traffic. After 09-25, use the `AFAST_TRAFFIC` tag. Before it, use session cwd under
     campaign or Forge roots and the worker naming; report the unclassifiable share.
  2. Decompose the 1,642 `shadow_agreement` events by backend (local qwen3:0.6b vs Jev), date (before/after Jev became the
     default on 09-24), decision kind and abstention.
  3. Define what "match" compares: judge choice vs the host's next action. Matching the host is not correctness.
  4. Run a census of decision kinds per session, judge latency p50/p95 per backend, and the share of heartbeats (71%).
  5. Reconcile receipts vs measured for keep-alive ($222.66 receipt-estimated) and loop_stop.
  6. Only if the privacy allow-list kept enough fields: relabel 200 mismatches with a strong model ($40 cap) to estimate how
     many "mismatches" were defensible. Otherwise report the metric as unidentifiable.
- **Deliverable:** a privacy-safe `observatory-summary.json`, 2 figures, and `afast export --observatory-summary` (E9) so the
  analysis is reproducible.
- **Primary endpoint:** descriptive. Shadow agreement by backend and period, with Wilson CIs.

### A2: Start-tier decider benchmark (RQ2) (offline, ≤$60, after S1 scenarios are frozen)

- **Labelled set:** 130 session-start decisions (70 main-v1 + 60 S1 holdout scenarios: turn-1 prompt + workspace summary).
  Labels are **outcome-derived**, not annotated: the cross-fitted oracle choice from the pinned-arm potential outcomes
  (main-v1 approximated; holdout measured in S1).
- **Deciders:** Jev 1.13.0, Clef, Clef-Flash, Luna, Sol, local qwen3:0.6b, tev1-4B, Laya, R*, always-route, always-host, and
  host self-routing (Fable/Opus asked "keep or delegate to Sonnet?"). Five samples each for stochastic deciders; latency
  measured from this host.
- **Endpoints:**
  - **Regret** in $ per 1,000 sessions vs the oracle, at equal quality.
  - Decision cost and latency.
  - Agreement with R* (the disagreement set is where the money is).
- **Cost:** Jev $18/1M decisions; Sol at 49x is still pennies at n=130x5. Host self-routing is ~$0.02 per call, $26 for all.
  $60 cap.

### S1: Holdout decomposition panel (RQ2-RQ6) (the core study)

- **Scenarios: new `holdout-v3`, 60 scenarios, never run by any agent before S1.** 10 per task type (bugfix, feature,
  mixed, review, explain, docs). Families: polyglot 12, repos 20, mixed 16, knowledge 12. **≥12 with >300 workspace files**
  (scope gate). 8-16 turns, ≥6 with ≥2 idle gaps >5 min. Each scenario is validated by its reference solution and a single
  plain-Sonnet-default smoke session (not an analysed cell). Scenario hashes are frozen in the prereg. main-v1 test/train
  stays dev-only: its test split has already carried three confirmations.
- **Arms (10 per scenario-rep):**

| # | arm | host | config | est. $/session |
|---|---|---|---|---|
| 1 | A0F | Fable | plain, default effort (anchor) | 5.31 |
| 2 | A0F-m | Fable | plain, effort medium ("just set medium" competitor) | 4.57 |
| 3 | PhF | Fable | bundle, pinned host, strong default | 5.40 |
| 4 | PhF-m | Fable | bundle, pinned host, strong medium | 4.65 |
| 5 | ShF | Fable | **shipped defaults, live** (Jev decide-once, price gate, cheap medium) | 3.40 |
| 6 | Pc | any | bundle, pinned Sonnet medium (host-independent; potential "cheap" outcome) | 2.75 |
| 7 | A0O | Opus | plain, default effort (anchor) | 2.13 |
| 8 | A0O-m | Opus | plain, effort medium | 1.81 |
| 9 | ShO | Opus | **shipped defaults, live** (gate closed, strong default) | 2.17 |
| 10 | ShO-m | Opus | shipped + `strong: medium` (candidate C*_O) | 1.85 |

  Plus an A/A subsample: a second A0F and A0O on a seeded 10% of scenario-reps (12), for the holdout noise floor.
  **Every factorial cell is computed from these arms without running it.** Routing x strong effort x decider x scope
  gate x keep_on_host are all deterministic functions of (turn-1 prompt, workspace) applied to arms 3, 4 and 6 (Fable)
  and 9, 10 and 6 (Opus). So all decider and config combinations, and the oracle, cost nothing extra. Arm 5 (ShF) validates
  that a live decide-once session equals its predicted potential outcome.
- **Reps:** 2. **Sessions:** 120 x 10 + 24 A/A = 1,224.
- **Hypotheses** (Holm within family F1 = {H1, H3, H4, H6}; family F2 = {H2, H5, H7}):
  - **H1 (Fable value):** C*_F vs A0F: cost-ratio upper bound < 0.75 and turn-pass lower bound > −0.05.
  - **H2 (decision model vs rule):** policy(Jev) vs policy(R*) on Fable, equivalence on cost (±5%) and turn-pass (±0.02).
    The decision rule is stated in advance. If they are equivalent, **ship the simpler decider (R\*: no external call, no
    consent needed)**. If Jev is better beyond the margin, ship Jev. Also report the identity |Δ| ≤ d·|mean discordant
    difference|. If d < 0.15, the deciders cannot differ materially by construction.
  - **H3 (overhead, RQ3):** ShO/A0O inside [0.95, 1.05] (90% CI equivalence). Also PhF/A0F, decomposed into
    prompt tokens, cache writes, judge, keep-alive and guards.
  - **H4 (Opus effort, RQ4):** A0O-m/A0O upper < 1.0 and turn-pass non-inferior. Then ShO-m vs ShO for the shipped
    default.
  - **H5 (gate):** Pc/A0O lower bound > 1.0 (routing to Sonnet still loses on Opus, on fresh scenarios and without the
    effort-switch artifact).
  - **H6 (live = predicted):** ShF observed / decomposition-predicted inside [0.95, 1.05].
  - **H7 (task types, RQ6):** Pc − PhF-m turn-pass on review ∪ explain (20 scenarios). If the lower bound < −0.05, ship
    `keep_on_host: [review, explain]`; otherwise remove the opt-out example. Feature tested the same way, exploratory.
- **Power** (from §0.2, n=60, r=2):
  - Routing contrasts: half-width ≈ 1.96·√(0.30²/60 + 0.10²/120) = ±0.078 log (±8%).
  - Same-model contrasts (H3, H4): ±0.031, so the ±5% equivalence in H3 has ≈90% power if the true overhead is ≤1%.
  - Turn-pass: SE 0.0075, so the −0.05 margin has 85% power at a true Δ of −0.03 (the Fable-sticky case that previously
    reached −0.047).
  - H2: with d≈0.11-0.25 → 7-15 discordant scenarios, half-width ≈ ±6%. Power for ±5% equivalence is ~60-70%,
    reported as such. H2's bound argument carries the weight.
- **Config-freeze rule (preregistered, deterministic), per host:**
  1. Candidates: the configs whose cost upper bound < 1.0 vs the host default, turn-pass lower bound > −0.05, and
     final-state Δ point ≥ −0.03.
  2. Ship the cheapest candidate.
  3. Any candidate within 3% of the cheapest that is simpler wins, in Occam order: plain-medium < bundle-unrouted <
     bundle + rule decider < bundle + Jev decider.
  4. If the shipped choice ≠ the preregistered C*_h, it is labelled "selected on holdout" and must replicate in S2.
- **Cost:** 120 x $34.04 + $89 A/A = $4,174, +5% infra = **$4,380** (cap $5,000).
- **Wall time:** 240 waves (6-session Fable wave including Pc, 4-session Opus wave, adjacent admission per scenario-rep)
  x 26 min / ~5 concurrent waves ≈ 21 h, about 24 h with retries.
- **Stop rules:** the generic ones, plus: if H6's live ShF sessions fail the mechanism gate (decided once but switched),
  stop. That is a product bug, fixed before resuming.

### S2: Long sessions, 40 turns (RQ7)

- **Scenarios:** 10 (the 6 `long_block` candidates in `main-v1.yaml` + 4 from holdout-v3). Each is extended to 40 turns
  with authored follow-ups, checks and references (the TODO in `main-v1.yaml`). 3 scripted idle gaps of 6 min (beyond
  the 5-min cache TTL).
- **Arms (5):** A0F, ShF*, A0O, ShO*, Pc, where * = the config frozen by S1's rule. Keep-alive on in bundle arms (part of
  the product).
- **Reps:** 2; 100 sessions.
- **Endpoints:**
  - **Primary (estimation, consistency band):** the 40-turn cost ratio divided by the S1 11-turn ratio for the same config,
    inside [0.80, 1.25].
  - **Secondary:** Pc/A0O at 40 turns > 1.0 (gate still right); cache-read share by turn; keep-alive receipts vs
    measured; turn-pass non-inferiority.
- **Power:** n=10 gives ±0.19 on a routing ratio. This is a replication and extrapolation check, not a new effect claim.
  The Opus gate effect (≈1.2-1.4x) is detectable.
- **Cost:** a 40-turn session ≈ 4.2x an 11-turn one (main-v1 turn scaling 16 → 5.9 units, extrapolated linearly, vs 3.86
  at 11.2 turns). 20 x $15.76 x 4.2 = $1,324, +8% = **$1,450** (cap $1,700).
- **Wall time:** 40 waves of ~100 min, 8 concurrent → ~9 h, about 12 h with memguard throttling.
- **Order:** after the S1 freeze. **Stop:** >2 memory kills → parallel 4.

### S3: Delegation routing in situ (RQ8)

- **Scenarios:** 20 new delegation-heavy scenarios (repo surveys, multi-file reviews, "find and explain" work where the
  foundation bundle naturally delegates to read-only agents). Prompts must not mention agents.
  **Pilot gate:** ≥2 delegations per session in ≥80% of 10 pilot sessions, else redesign before spending.
- **Arms (2 per host x 2 hosts):** frozen config with `delegation_routing: off` vs `enforce` (policy v3, read-only agents,
  750 ms deadline). Both hosts.
- **Reps:** 2; 160 sessions.
- **Endpoints:**
  - **Primary:** session cost ratio enforce/off. Upper < 0.95 per host (Holm across the 2 hosts).
  - **Co-primary quality:** turn-pass non-inferiority (−0.05), plus child-output acceptance by blind pairwise judge
    (labels stripped, randomized order, the method of the n=21 study), sign test with a 10-point margin.
  - **Secondary:** child model and effort actually served (from child events). This resolves the "child effort
    undetermined" gap.
- **Power:** if delegations are ~40% of session spend and the −57% replay result holds, session effect ≈ −23%. With
  σ_b≈0.2, n=20, r=2 → ±0.093, so >90% power for upper < 0.95.
- **Cost:** 40 scenario-reps x (2 x $5.10 Fable + 2 x $3.30 Opus) = $672, + judge $20, +8% = **$750** (cap $900).
- **Wall time:** 80 waves x ~30 min / 8 → ~5 h.
- **Order:** after the S1 freeze; runs alongside S2 inside the Forge cap.

### S4: Cross-harness `decide` (RQ9)

- **Prerequisite:** E1 (`decide` capability + `launch` shim) and E5 (Copilot host).
- **Mechanism:** the portable product is decide-once **at launch**.
  `amplifier-fast-decisions launch --harness {claude,codex,copilot} --host-model M -- <args>` calls `decide(task, host,
  workspace)` and execs the harness with the chosen `--model` / effort flag. This is the same Policy, price gate and scope
  gate as the orchestrator, so the in-situ Amplifier result is the prediction.
- **Driver:** E6a adds multi-turn resume drivers (`claude -p --resume --output-format json`, `codex exec resume --json`,
  `copilot -p --resume`) to the paired harness. Scripted turns and validators are the same as in S1.
- **Scenarios:** 24 from holdout-v3 (4 per task type; seeded), 2 reps.

| harness | arms | sessions | est. $/scenario-rep | cost |
|---|---|---|---|---|
| Claude Code | Fable native, Fable decide, Fable medium; Opus native, Opus decide | 240 | 10.35 | $497 |
| Codex (gpt-6-astra, high) | native, decide (tier pair from price table, fixed in prereg after a 6-session pilot), effort-medium only | 144 | 10.20 | $490 |
| Copilot CLI | native default model, decide (model multiplier choice) | 48 (12 scenarios) | 3.00 | $72 |

- **Endpoints, per harness (no pooling, no cross-harness winner):**
  - Cost ratio decide/native: upper < 1.0 on the Fable host; on the Opus host, decide = whatever S1 froze (expected:
    effort only).
  - Turn-pass non-inferiority.
- **Cost bases:**
  - Claude Code: `total_cost_usd`, a token-based estimate.
  - Codex: tokens x published rates.
  - Copilot: premium requests x multiplier x $0.04 list overage. Copilot is labelled a **portability screen**, because its
    dollar cost is not metered per token.
- **Power:** Claude Code Fable effect ≈0.55-0.65 → ±0.12 at n=24, so the cost claim is decisive. Quality SE 0.012.
- **Cost:** $1,059 + 10% = **$1,200** (cap $1,450).
- **Wall time:** ~8 h; 4 waves per harness, in parallel with S5.
- **Stop:** a harness whose cost cannot be read per session → report the quality and time endpoints only; never estimate
  silently.

### S5: SWE-bench Verified, full 500, two arms (RQ10)

- **Why this instead of finishing the 4-arm campaign:** the stalled campaign tests prepared actions, Laya and jevgrep
  (levers now off or rejected), and it ran 29 of 2,000 runs. S5 instead tests the **shipped final config** on hard external
  tasks. On SWE repos (>300 files) the scope gate keeps every session on the host, so S5 measures overhead, guards and
  strong-host effort on hard tasks: the residual quality risk of shipping `strong: medium`.
- **Arms:** Opus host, plain default vs frozen final config. Opus is the cheapest host per run, and it is where the
  shipped default does not route. Dataset revision `c104f840…`, swebench 4.1.0 grader, 1 rep, shuffled task blocks.
  The accounting fixes from `SWEBENCH-RECOVERY.md` are retained.
- **Endpoints:**
  - **Primary:** resolved-rate Δ (final − plain), 90% CI lower bound > −0.05 (non-inferiority).
  - **Secondary:** cost per resolved issue; time.
- **Power:** n=500 paired, discordance ~15% → SE 0.017, giving 0.89 power at a true Δ = 0.
- **Cost:** 500 x ($1.30 + $1.15), +10% retries/infra = **$1,450** (cap $1,700). The per-run estimate is the campaign's
  $2/run Sonnet cap x the main-v1 Opus/Sonnet ratio 0.66. **Recalibrate after a 40-run pilot (in E budget); if the mean is
  >$2/run, cut to 300 issues** (cut line).
- **Wall time:** 1,000 runs x ~15 min / 8 + grading ≈ 1.5 days.
- **Stop:** grader or image drift → stop. Unknown cost on >2% of runs → stop and report the partial result with honest
  denominators.

### X: Ship check (RQ5 end-to-end) ($100)

Install the tagged release from the package (not the working tree). Then:
1. `afast doctor` prints the effective config (E3).
2. Offline replay of all S1 bundle sessions through the release code reproduces 100% of recorded decisions.
3. `decide` agrees with the orchestrator on 100% of the 130 A2 prompts.
4. 20 live sessions (5 holdout scenarios x 2 hosts x {plain, release}) land inside the S1 CIs.

### A3: Real-workload projection (RQ11) ($0)

- Apply S1 per-task-type, per-host ratios to the observatory's production mix (A1) and to the 30-day waste census
  ($13,924). Report projected cost/time ratios against the GOAL targets.
- Restate GOAL.md honestly: met, not met, or replaced by the per-host config table.

### C: Closures (no spend; each a committed `WITHDRAWN.md` or `CLOSED.md`)

- **C1, SWE-bench 4-arm:** publish the 29 completed runs as a terminated campaign with spend, the reasons for stopping, and
  "no savings conclusion". Point to S5 as the replacement.
- **C2, native three-arm (09-22):** withdraw. It tested the read/list select helper, which the trace study showed is not
  useful. Its Codex/Jev arm was blocked on an interface that S4 now supplies for `decide`. First verify and record that no
  outcome data was analysed.
- **C3, holdout3 (planner v12):** withdraw. Its policy was superseded by H3 (decide-once is cheaper) and §0.4 (per-turn
  switching rewrites the cache). Verify and record that no batch was launched.
- **C4, large-repo L2 confirmation, HC10/HC11, phase effort map:** marked "screen only, off". The phase map is **deleted**
  from the shipped YAML (E2), because it is inert under `by_tier` and harmful without it (§0.4).

---

## 3. Configuration and engineering work (before S1; week 1)

| ID | Work | Source | Acceptance |
|---|---|---|---|
| E1 | **`decide` capability.** Library `decide(task, host_model, workspace=None, config=None) -> Decision{tier, model, effort, reason, gate, decider, latency_ms, usd}` built on the **same** `Policy`, `price_gate`, scope gate and `decide_start_tier` code, with defaults loaded once from `behaviors/fast-decisions.yaml`. CLI `amplifier-fast-decisions decide` + `afast decide` alias + `launch --harness …`. `--decider {jev,rules,clef,local,always-host,always-cheap}` for studies. SMART_TOOL.md use_cases updated. | audit P0, 2b/2c | `decide` == orchestrator on 130 prompts (test); manifest/--help conformance tests extended |
| E2 | Fix or deprecate `bundles/active*.yaml` and `afast configure --mode active`; update `test_composition.py:384-399`; add a parity test (`fast-decisions.yaml` == `fast-decisions-registry.yaml` orchestrator config); **delete the inert phase map**; add an invariant test: "effort is constant within a session on every tier". | audit P0, §0.4 | tests green on the 3-OS CI |
| E3 | `afast doctor` loads the effective config (behavior + user settings → `Policy.from_config`) and prints backend, consent, scope, price-gate result for the real host model, `by_tier`, read_shortcut and decider. Smart `diagnose` calls the same function. | audit P1 | snapshot test of doctor output |
| E4 | One backend vocabulary table (runtime, smart tool and `configure` accept the same list). Clef is documented as benchmark-only unless S1/A2 promote it. | audit P1 | single source table + test |
| E5 | Copilot: `SKILL_HOSTS` entry + `launch` support + test. Commit `docs/evidence/<date>-smart-tool/` with a model-backed `select` and `decide` per harness (Claude Code, Codex, OpenCode, Copilot, Amplifier). Fix the dangling evidence reference (`SMART-TOOL.md:86`). | audit P1, 2e/2f | evidence dir exists and is linked |
| E6 | Paired harness: (a) multi-turn resume drivers for 3 external harnesses with per-harness cost extraction; (b) cells `orch-pin-host-medium(-opus)`, `plain-opus-medium`, `orch-default-medium-opus`; (c) `evals/paired_policy.py`: potential-outcome policy evaluator, cross-fitted oracle, bootstrap, the H2 bound; (d) 10 long scenarios at 40 turns; (e) holdout-v3: 60 scenarios + validation; (f) 20 delegation scenarios; (g) judge/decider usage added to session cost. | §2 | each with unit tests; preflight passes |
| E7 | Re-verify the price table (dated 2026-06-10) and the model availability of Fable 5.1, Opus 5.5 and Sonnet 5. Re-derive the price-gate constants after S1 from artifact-free pairs. | §0.4 | table sha recorded in prereg |
| E8 | Fix stale banners: GOAL.md, JEV-CUA.md, JEVGREP.md (Laya → Jev). | history §0.5 | grep check in CI |
| E9 | `afast export --observatory-summary` (privacy allow-list only). | RQ1 | test_evidence_sanitized passes |
| E10 | Program preregistration + closure notes C1-C4. | §2 | committed before the first S1 session |

**Ship criteria for final defaults (all must hold):**
1. Every default that changes is backed by a confirmatory pass (S1 for routing, effort and decider; S3 for delegation;
   S2 replication if selected on holdout). Screen-only levers stay opt-in.
2. H6 passes: the live decide-once behaviour equals its prediction. X passes, with 100% replay and decide parity.
3. Effort-constancy invariant test green; registry/behavior parity green; `doctor` == `diagnose`.
4. Privacy follows the decider: if R* ships, `allow_external_state` defaults to **false** and Jev becomes an opt-in decider.
   If Jev ships, the consent docs and doctor warning are updated.
5. Smart-tool claims per harness cite committed S4/E5 evidence, and nothing else.
6. All evidence directories are sanitized, with SHA256SUMS, reproduce scripts, and a ledger reconciled to provider-reported
   spend within 2%.

---

## 4. Budget (remaining $15,000; ≥15% reserve = $2,250)

| Item | RQ | Sessions/runs | Planned | Hard cap |
|---|---|---|---|---|
| E: pilots, scenario smoke (90), harness/driver pilots, SWE 40-run pilot | — | ~170 | $500 | $600 |
| A0 Phase-0 counterfactual | 2 | 0 | $0 | $0 |
| A1 Observatory week | 1 | 0 (+200 relabels) | $40 | $60 |
| A2 Start-tier decider benchmark | 2 | 130 x 12 deciders x 5 | $60 | $100 |
| **S1 Holdout decomposition panel** | 2-6 | 1,224 | **$4,380** | $5,000 |
| S2 Long 40-turn | 7 | 100 | $1,450 | $1,700 |
| S3 Delegation in situ | 8 | 160 | $750 | $900 |
| S4 Cross-harness `decide` | 9 | 432 | $1,200 | $1,450 |
| S5 SWE-bench Verified 500 x 2 | 10 | 1,000 | $1,450 | $1,700 |
| X Ship check | 5 | 20 + replay | $100 | $150 |
| Analysis/review LLM compute | — | — | $150 | $200 |
| **Planned subtotal** | | | **$10,080** | $11,860 |
| Contingent K1: S1 rep 3 on the primary arms (A0F, PhF-m, Pc, A0O, ShO-m), only if a primary turn-pass bound lands in [−0.06, −0.04] | | 300 | $1,050 | |
| Contingent K2: S4 Claude Code +24 scenarios, only if its cost CI straddles 1.0 | | 240 | $500 | |
| Contingent K3: re-runs beyond the infra allowance | | | $400 | |
| **Contingent subtotal** | | | **$1,950** | |
| **Reserve (unallocated)** | | | **$2,970 (19.8%)** | |
| **Total** | | | **$15,000** | |

Program total: $4.6k spent + $10.08k planned = **$14.7k expected**. Worst case with every contingent spent and every cap hit:
$4.6k + $13.81k = $18.4k, still under $20k.

**Cut line.** If projected spend passes $12,750 (85% of remaining), cut in this order:
1. Copilot arm and the Codex effort-only arm (−$260).
2. S5 → 300 issues (−$580).
3. S3 → Opus host only (−$330).
4. S2 → 6 scenarios (−$580).
5. S4 Claude Code Opus arms (−$230).
6. S1 → drop A0F-m and A0O-m (−$750), falling back to the existing effort studies for the "just set medium" competitor.

Never cut: S1 core arms, A0-A3, X, the closures.

**Calendar (≈4 weeks):**
- Week 1: E1-E10, A0, A1, scenario authoring (the critical path: 90 scenarios).
- Week 2: S1 (~1 day run + 1 day analysis) → config freeze → release candidate.
- Weeks 2-3: two lanes inside the Forge cap. Lane A: S2 + S3 (Amplifier paired, ≤18 sessions). Lane B: S4 + S5 (≤12).
- Week 4: X, A2/A3 final, paper, peer-review round.

---

## 5. The v3 paper

**Working title:** *Where a system-1 decision model belongs in an agent harness: measured cost, quality and configuration
(fast-decisions v3).*

**Main text (≤30 pages; one claim per section; every number traces to an evidence file via `check_figures.py`):**

1. **Answer first** (1 page). One config table per host (Fable-class, Opus-class, Sonnet-class) and per harness, with the
   one-sentence placement rule: *decide once, at session start (or at delegation), price- and cache-aware, with
   deterministic guards; keep the decision model off the per-step hot path.* State what the decision model is worth vs a
   rule (H2) in dollars per 1,000 sessions.
2. **Why we looked** (Act I): the promise of a cheap typed system-1 model. Judge benchmark headline only: Jev 55/63 at
   p95 ~220 ms, $18/1M; Luna/Sol/Clef not significantly better and slower and costlier; no local judge qualified.
3. **What the observatory saw** (Act II, A1): the decision census; 7.1% shadow agreement decomposed by backend and period;
   why observation cannot show savings.
4. **Measuring it properly** (Act III): the paired multi-turn method, a cache-economics primer, and the A/A noise floor.
   Condensed from v2.
5. **What actually saves money** (Act IV-a): main-v1 + effort follow-ups recapped. **New:** the §0.4 effort-switch cache
   finding, and the potential-outcome decomposition (model choice + effort ≈ all of the saving).
6. **v3 confirmation on fresh scenarios** (Act IV-b, S1): decider value vs rule and vs oracle (regret); overhead on Opus;
   Opus/Fable medium; task types; scope gate; live = predicted.
7. **Does it hold up?** S2 (40 turns, idle gaps), S3 (delegation, cold-cache hypothesis), S5 (SWE-bench Verified 500).
8. **Beyond Amplifier** (Act V, S4): `decide` as a smart tool, with measured savings in Claude Code, Codex and Copilot.
   What a portable decision tool can and cannot do: it changes launch decisions, and it cannot remove turns.
9. **The design that results** (plateau): placement principles; the shipped defaults with evidence grades; the user
   configuration guide (what to set per host and harness, what it costs, and what you give up).
10. **Discoveries**: a numbered list of the new science (e.g. effort switching busts the cache; on cached hosts a cheaper
    model can be dearer; decide-once beats per-turn; decider headroom is bounded by the disagreement rate; oracle regret;
    the delegation cold-cache result; observatory agreement is not correctness).
11. **Limits and threats**: one host provider; price-table dependence and the break-even sweep; scenario realism;
    single-owner workload.
12. **Reproducibility**: commits, preregistrations, ledgers, SHA256SUMS.

**Companion report (not main text):**
- The full judge benchmark and trace study (v2 part 1).
- Clef and the caching survey.
- All per-type, per-arm tables.
- Every preregistration with deviations and provenance.
- The peer-review records.
- The closures C1-C4.
- The lever inventory with an evidence grade per lever.
- The observatory data dictionary.
- Harness driver details.
- The price table and gate derivation.
- The scenario catalogue.
- The history and timeline (388 commits).

**Definition of done (v3 is complete when all hold):**
1. Every RQ1-RQ11 has a committed RESULT.md, or a CLOSED.md with its reason. Every preregistration in the repository
   (main-v1, both effort studies, holdout2, holdout3, three-arm, SWE 4-arm, judge bench, v3) has a RESULT or a WITHDRAWN.
2. Every lever in the inventory carries an evidence grade (confirmed / replicated / screen / negative / untested), and its
   shipped default matches the grade.
3. The final defaults are released (tagged), pass the ship criteria (§3), and pass X.
4. Audit P0 and P1 are closed. P2 is filed as tracked items.
5. The cross-harness evidence directory is committed. SMART-TOOL.md claims only what it shows.
6. All evidence is sanitized, checksummed and reproducible from committed rows. Ledgers reconcile within 2%. The total
   program spend is reported (target ≤$15k, hard ≤$20k).
7. The paper builds; `check_figures.py` passes; one external peer-review round is addressed in writing.
8. No stale doc banner remains (CI grep).
