# Preregistration: holdout-v3 (S1), the v3 core study

DRAFT, not committed. To be committed, with its provenance record, BEFORE the S1 schedule is created and before any S1
session runs. Program plan: `docs/design/v3/PLAN.md` (section S1 and "Shared method"). Frozen inputs: `evals/v3/FROZEN.md`
(R*, C*_F, C*_O at commit `658f228`). Design: `evals/paired/holdout-v3.yaml`. Scenarios: `evals/paired/scenarios/holdout-v3/`
(`SPLIT.md`, `scenario-hashes.json`, panel sha256 `7356cf5211250ea0a2c527ad4ba78da689f3d761e600b2ce2219775823dd31bc`).
Analysis: `evals/v3/s1_analysis.py` (skeleton tested on synthetic data, `tests/test_s1_analysis.py`).
Program-level `PREREGISTRATION-v3.md` (PLAN E10) inherits the hypotheses, Holm families and the config-freeze rule from here.

## Question

At the decision that moves money (the session-start model choice) and at the host-model effort setting, on scenarios no agent
has run: what does the shipped bundle cost and what does it lose against the host's plain default, what does the decision
model add over a deterministic rule, and which configuration should ship per host (Fable 5.1, Opus 5.5)?

## Design

* **Scenarios:** 60 `holdout-v3` scenarios, `split: holdout`, never run by any agent (one disclosed exception: the smoke
  below). 10 per task type (bugfix, feature, mixed, review, explain, docs). Families: polyglot 12, repos 20, mixed 16,
  knowledge 12. 16 start with more than 300 workspace files (the scope gate counts the same 16), 21 have two idle gaps of 420 s,
  8-16 turns. Validated together in one serial memguarded run (`validation-combined.json`: 60/60 valid, 0 memguard kills):
  starting workspace fails turn 1, the reference solution passes every turn, every turn discriminates, snapshots rebuild to
  the same tree hash. No overlap with main-v1 or pilot-v1 by id, repo@sha/subdir, inline tree or same-language exercise slug
  (`SPLIT.md`). Reported and kept: four exercise slugs that exist in another language in main-v1/pilot-v1 (go-bowling vs
  pilot py-bowling, js-linkedlist and py-linked-list-docs vs main-v1 go-linkedlist, py-gradeschool vs main-v1 rust-gradeschool).
* **Reps:** 2. **Hosts:** Fable 5.1 (`claude-fable-5-1`), Opus 5.5 (`claude-opus-5-5`). Pc runs on Sonnet 5 (`claude-sonnet-5`).
* **Arms** (design arm key -> label; every arm of a scenario-rep starts together from one frozen workspace snapshot, each
  session isolated by its own cache nonce). All bundle cells are the shipped bundle at the frozen candidate commit
  (`behaviors/fast-decisions.yaml` after PR #64: Jev decide-once, price gate on, scope gate 300, `by_tier` cheap medium / strong
  default, keep-alive and waste guards on) and differ only by the listed override:

  | label | host | arm key | cell | what differs | est. $/session |
  |---|---|---|---|---|---|
  | A0F / A0O | Fable / Opus | `anchor` | `plain` / `plain-opus` | plain Amplifier, provider-default effort (anchor) | 5.3 / 2.1 |
  | A0F-m / A0O-m | Fable / Opus | `anchor_m` | `plain-medium` / `plain-opus-medium` | reasoning effort medium ("just set medium") | 4.6 / 1.8 |
  | PhF | Fable | `ph` | `v3-pin-host` | bundle, host pinned (decided once, no judge call), strong effort default | 5.4 |
  | PhF-m | Fable | `ph_m` | `v3-pin-host-medium` | PhF + `by_tier.strong: medium` | 4.7 |
  | ShF / ShO | Fable / Opus | `shipped` | `v3-shipped` / `v3-shipped-opus` | no override: the shipped defaults, live | 3.4 / 2.2 |
  | ShO-m | Opus | `shipped_m` | `v3-shipped-opus-medium` | ShO + `by_tier.strong: medium` (C*_O) | 1.9 |
  | Pc | any (Fable-hosted) | `pc` | `v3-pin-cheap` | bundle pinned to Sonnet 5 at the cheap-tier effort (medium), any workspace size, price and scope gates off | 2.8 |
  | A/A | both | `aa` | as `anchor` | a second anchor on a seeded 10% of scenario-reps (12; seed 20261005, stratified by gap pattern), both hosts | |

  `v3-pin-host` = `model_routing.start_policy: rules` with `complex_min_prompt_chars: 1` (every prompt is "complex": the
  host, decided once); `v3-pin-cheap` = `start_policy: rules`, `complex_min_prompt_chars: 1000000000`,
  `cheap_max_workspace_files: null`, `price_gate.enabled: false`. Rendering proof (no model call):
  `python3 evals/v3/s1_render_cells.py` loads each cell through the real bundle composition and requires every contrast to
  differ only where intended (A0-m vs A0: provider `reasoning_effort`; PhF vs ShF: `start_policy` and
  `complex_min_prompt_chars`; PhF-m vs PhF: `by_tier.strong`; Pc vs PhF: `complex_min_prompt_chars`,
  `cheap_max_workspace_files`, `price_gate`; ShO vs ShF: host model only; ShO-m vs ShO: `by_tier.strong`). Result committed as
  `evals/paired/holdout-v3-render.json`; 8/8 contrasts hold.
* **Waves:** per scenario-rep a Fable wave of 6 sessions (A0F, A0F-m, PhF, PhF-m, ShF, Pc; 7 with the A/A) and an Opus wave of
  4 (A0O, A0O-m, ShO, ShO-m; 5 with the A/A), admitted back to back (`wave_order: scenario_rep_adjacent`); Pc is shared by
  both hosts. 120 scenario-reps x 10 sessions + 24 A/A = **1,224 sessions in 240 waves**. `--parallel` must be at least 7 (the
  design refuses a smaller value rather than splitting Pc off its wave). Wave order is seeded (`--seed 20261005`) and frozen in
  the schedule.
* **Cost basis:** `cost_usd_tools_normalized` (the fixed price table, sha `9cb9b9134ab7fa08` at drafting; re-verified in E7 before
  the freeze; results are also reported on any later table) plus the decider charge (`judge_usage` receipts x the frozen
  $1.8e-5 per Jev decision).
* **Mechanism gates** (per session, from its events; a failing session is excluded from cost endpoints and counted):
  served model (A0F/A0F-m/PhF/PhF-m: Fable on every main request; A0O/A0O-m/ShO/ShO-m: Opus; Pc: Sonnet 5);
  effort on main requests (`absent` = provider default for A0F, A0O, PhF, ShO; `medium` for A0F-m, A0O-m, PhF-m, ShO-m, Pc; ShF:
  `medium` on Sonnet, absent on Fable); effort constant within the session; one model on every main request (no switch of any
  kind); **ShF decided once and never switched** (exactly one fresh `session_routed` receipt, zero model switches); **ShO gate
  closed and no routing** (the one fresh decision is `price_gate_strong`, zero `model_routed` receipts); Pc routed (>= 1
  `model_routed`). Implemented in `evals/paired.py:_v3_gate_checks`, tested in `tests/test_paired_holdout_v3.py`.
* **Smoke (disclosed, not analysed):** `evals/paired/holdout-v3-smoke.yaml`, one plain Sonnet 5 session per scenario (60, cap
  $250), confirms each scenario is solvable and its graders behave live. It may cause a scenario to be repaired or swapped
  (hashes re-frozen) BEFORE this document is committed; after the commit it is never used to change the panel. Its cost and
  quality numbers enter no hypothesis and are never pooled with S1.
* **Preflight (disclosed):** one "Reply with OK" session per distinct cell (10 cells, $4.78, scratch directory, candidate commit
  `a11c24e`; `evals/paired/holdout-v3-preflight.json`), not analysed. Served model and effort on main requests matched the design in
  every cell: plain Fable/Opus effort absent; plain-medium and plain-opus-medium `medium`; PhF Fable absent; PhF-m Fable `medium`;
  ShF routed to Sonnet 5 at `medium` (Jev judged "cheap"); Pc Sonnet 5 at `medium`; ShO and ShO-m served by Opus 5.5 with the price
  gate closed (`price_gate_strong`, predicted ratio 1.366) at absent / `medium`. The first run flagged six gate failures that were
  bugs in the preflight's receipt reading (receipts nest one level deeper in session files; `model_routed` with reason
  `start_strong` is emitted on every host-kept request); fixed, tested, and the same sessions re-read offline
  (`paired.py preflight --reevaluate`). The preflight is one turn: multi-turn "decided once, restored on resume" is checked by
  the ShF gate on the first S1 waves (a failure stops the run).
* **Budget:** hard cap $5,000. Estimate $4,087 sessions + 5% infra reserve = $4,292 (PLAN $4,380). Wall-time estimate
  (FIFO waves, 26 min per 11.2-turn wave slot): 133 h at `--parallel 8`, 67 h at 12, 35 h at 20, 24 h at 30.

## Estimands and rules shared by every hypothesis

* A **scenario** is the cluster. Per scenario, per contrast, the within-scenario mean over its valid reps. Cost ratio =
  **geometric mean over scenarios** of (policy cost / comparator cost). Turn-pass difference = mean over scenarios of the
  mean-over-reps difference of `turn_pass_frac`. Final-state difference likewise on `final_state_pass`.
* **Bootstrap:** resample the 60 scenarios with replacement, 10,000 resamples, seed **20261005**, one shared index draw for every
  contrast. 95% percentile intervals for non-inferiority and superiority; 90% intervals for equivalence (TOST). p-values are the
  one-sided bootstrap percentile p (1 + count)/(B + 1); an equivalence p is the larger of its two one-sided p; a hypothesis with
  two endpoints takes the larger p (intersection-union).
* **Validity:** a session is valid iff `wave_valid`, `cost_valid`, `mechanism_engaged`, `cache_audit_clean` and not an
  infrastructure failure. **Cost endpoints** use a scenario-rep only if every session the contrast needs is valid. **Quality
  endpoints are unfiltered** (all sessions except infrastructure failures), as in the effort-control studies, so that a memory
  kill or a flag cannot hide a quality loss. A scenario with no valid rep drops out of that endpoint (reported).
* **Potential-outcome policies.** A decide-once policy's session equals the pinned host session or the pinned cheap session
  of the same scenario-rep. On Fable the host outcome is PhF (strong default) or PhF-m (strong medium) and the cheap outcome is
  Pc; on Opus the host outcome is ShO or ShO-m (the gate keeps the host) and the cheap outcome is Pc. The factorial (decider
  {R*, Jev, always route, always host} x strong effort {default, medium} x scope gate {300, off} x keep_on_host {none,
  review+explain}) is evaluated this way, at no extra cost. The Jev decision of a scenario-rep is read from its ShF session
  (served model Sonnet = cheap). Jev with the scope gate off, and any decider the live session cannot reveal, is not computed.
  R* is the frozen rule (`evals/v3/frozen_rule.json`): route unless the starting workspace has more than 300 files.
* **Oracle and regret:** cross-fitted (the choice for rep r is made from the other rep: the cheaper outcome unless its turn-pass
  is lower than the host's); regret = $ per 1,000 sessions against it at the same strong effort.
* **Families (Holm, alpha 0.05, within family):** F1 = {H1, H3, H4, H6}; F2 = {H2, H5, H7}. "Supported" means Holm-adjusted
  p < 0.05 AND the stated bound holds. All other analyses are descriptive.

## Hypotheses

* **H1 (Fable value).** C*_F (decider R*, price gate on, scope gate 300, `by_tier` cheap medium / strong medium, `keep_on_host`
  off; composed as R* choosing between Pc and PhF-m) vs A0F: cost-ratio 95% upper bound **< 0.75** and turn-pass 95% lower
  bound **> -0.05**. Prediction (frozen, A0): 0.508 [0.483, 0.536]; turn-pass -0.019 [-0.052, +0.010]. The quality bound is the
  binding one at n=60.
* **H2 (decision model vs rule).** policy(Jev) vs policy(R*) on Fable (both strong medium, scope gate on): equivalence on cost
  (90% CI of the ratio inside [0.95, 1.05]) and turn-pass (90% CI inside [-0.02, +0.02]). **Decision rule, stated in advance:**
  equivalent => ship R* (no external call, no consent; `allow_external_state` defaults to false and Jev becomes an opt-in decider);
  Jev ships only if the ratio's 90% upper bound is < 0.95 and its turn-pass 90% lower bound is >= -0.02; any other outcome
  (including inconclusive) ships R*. Also reported: the identity |delta| <= d x |mean discordant difference| with the observed
  disagreement rate d; if d < 0.15 the deciders cannot differ materially by construction. Power for the +-5% equivalence is
  about 60-70% (PLAN); the bound argument carries the weight.
* **H3 (overhead, RQ3).** ShO/A0O: 90% CI of the cost ratio inside **[0.95, 1.05]**. Also PhF/A0F, decomposed into prompt
  tokens, cache writes, cache reads, outputs, requests, judge dollars, keep-alive and waste-guard receipts (descriptive, outside
  the Holm families).
* **H4 (Opus effort, RQ4).** A0O-m/A0O: cost 95% upper bound **< 1.0** and turn-pass 95% lower bound **> -0.05**. Then ShO-m vs
  ShO (the shipped-default question), same endpoints, reported with H4.
* **H5 (gate).** Pc/A0O: cost 95% lower bound **> 1.0** (routing to Sonnet still loses on Opus, on fresh scenarios, without the
  effort-switch artifact).
* **H6 (live = predicted).** ShF observed / decomposition-predicted (each ShF session against the Pc or PhF session its own
  routing corresponds to): 90% CI inside **[0.95, 1.05]**.
* **H7 (task types, RQ6).** Pc - PhF-m turn-pass on review union explain (20 scenarios): non-inferior iff the 95% lower bound is
  **> -0.05**. If it is not non-inferior, ship `keep_on_host: [review, explain]`; otherwise remove the opt-out example from the
  configuration docs. Feature is tested the same way, exploratory.

## Config-freeze rule (deterministic, per host)

1. Candidates: configurations (the enumerated factorial plus A0-m and the bundle-unrouted arms) whose cost 95% upper bound vs the
   host's plain default is < 1.0, whose turn-pass 95% lower bound is > -0.05 and whose final-state difference point estimate
   is >= -0.03.
2. Ship the cheapest candidate (point estimate of the geometric-mean cost ratio).
3. Any candidate within 3% of the cheapest that is simpler wins, in Occam order: plain-medium < bundle-unrouted <
   bundle + rule decider < bundle + Jev decider (ties: cheaper, then name).
4. If no candidate qualifies, the host keeps the current shipped default.
5. If the shipped choice differs from the preregistered C*_h (Fable: R*, strong medium, scope 300, no keep_on_host; Opus:
   bundle-unrouted, strong medium), it is labelled **selected on holdout** and must replicate in S2 before it ships.
Implemented in `s1_analysis.py:freeze`; the full candidate table is published, not only the winner.

## Stop rules

The generic program rules, plus S1's: ledger hard stop at $5,000; infra-failed waves above 10% of attempted: pause and diagnose;
**any mechanism-gate failure (wrong served model, wrong or changing effort, ShF switched after deciding, ShO routed): stop** (a
failing ShF is a product bug, fixed before resuming; a fix restarts the campaign from the first wave); cache-audit flags on more
than 2% of sessions: stop; more than 2 memory-watchdog kills: drop `--parallel` by 2. A stop is never resumed by relaxing a gate.
**No outcome peeking:** the dashboard shows spend, progress and infrastructure health only (`paired_dashboard.py` blinds the
`holdout` split exactly like `test`; `--show-test` is not used before the run is complete). The analysis script is run only on
the complete data.

## Exploratory (no decision rule)

A/A noise floor per host; oracle regret per decider; the full factorial table with intervals; per task type and per family;
scope gate in situ (the 16 large workspaces: ShF routing there vs the gate's prediction); long-gap scenarios (21) vs none;
final-state McNemar for each primary contrast; per-scenario cost ratios; Jev decision agreement with R* and with the oracle.

## Deviations from the PLAN, disclosed before data

1. The bundle cells are composed on the shipped config with explicit overrides (rules-policy pins) instead of harness-level
   sticky pin cells, so a host-kept ShF session runs the identical machinery as PhF; the earlier `orch-pin-*` cells carried the
   phase effort map, which the shipped YAML no longer has.
2. The A/A subsample is stratified by gap pattern (the loader's split is constant here); 12 scenario-reps, both hosts.
3. Quality endpoints are unfiltered (see Validity). The dashboard blind was extended to `holdout`.
4. The cost model uses data-derived type factors (`evals/v3/s1_cost_calibration.py`), not main-v1's assumed table; the estimate is
   3% below the PLAN's.
5. `--parallel` 8/12 under the memory guard gives 133/67 h, not the PLAN's ~21 h at ~5 concurrent waves (about 30 sessions); the
   PLAN's figure assumed the Forge terminal cap is the only limit.

6. Smoke triage (before this commit): the smoke run (60 plain-Sonnet sessions, $182.80, mean turn-pass 0.912) led to defect
   fixes in 30 scenarios (prompts that did not state what a check required, checks that rejected correct answers, e.g. row order,
   spacing, exact fix shape), documented per turn in `evals/paired/scenarios/holdout-v3/SMOKE-TRIAGE.md` (commit 5612559);
   genuine agent mistakes were left as they were. Re-grading the smoke snapshots with the fixed checks gives 0.961. The scenarios
   were not re-smoked after the fixes; all 60 re-validated (start fails, reference passes, wrong variants fail).
7. S1 runs at `--parallel 24` (Forge cap 30), not 12: main-v1 ran stably at 24-28 sessions with >= 85% free memory; the memory
   watchdog floors (pause below 32 GB free, kill below 16 GB) and the per-session cap are unchanged.

## Not claimed

Nothing about other hosts, other prices (the price-gate constants are re-derived after S1, E7), sessions beyond 16 turns (S2),
delegation (S3), other harnesses (S4), SWE-bench-scale tasks (S5), or the owner's production workload (A3). A hypothesis that
fails is reported as failed; no redefinition, no second look, no new scenario after the commit.

## Freeze checklist (commands, run at the preregistration commit; results go to `evals/paired/prereg-holdout-v3/PROVENANCE.md`)

```bash
export PYTHONPATH=src:.:scripts:evals
python3 evals/paired/scenarios/holdout-v3/panel.py                      # exit 0; panel sha256 equals the one above
python3 evals/v3/s1_render_cells.py --out /tmp/render.json              # 8/8 contrasts hold, equals the committed render
python3 -m unittest discover -s tests -p 'test_paired_*.py'; python3 -m unittest discover -s tests -p 'test_s1_analysis.py'
sha256sum evals/paired/holdout-v3.yaml evals/cells.yaml evals/paired.py evals/v3/s1_analysis.py evals/v3/frozen_rule.json \
  evals/v3/rules.py evals/paired/scenarios/holdout-v3/scenario-hashes.json
git rev-parse HEAD                                                        # the frozen candidate commit (--candidate-sha)
```
