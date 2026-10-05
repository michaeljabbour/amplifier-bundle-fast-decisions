# Does switching models erase the routing saving in longer chats? (caching evidence, 2026-10-01)

## The question

David's review comment: *"For longer chats you have to be confident in savings for the smaller model
to be worth it."* Routing can send a turn to a cheaper model. But the provider's prompt cache is kept
per model, so the first request after a switch writes the whole conversation into a new cache, and
cache writes are the most expensive input tokens. The question is whether that cost, or anything else
about longer sessions, erases the saving.

This folder answers it with **measurements from runs we already have**, not modeled estimates.
`caching_survey.py` makes no model calls. It reads only local run records and Amplifier session logs,
using paths under `~`. Regenerate everything with:

```
python3 caching_survey.py --workers 10 --boot 3000   # about 30 s; the command is also recorded in results.json
```

Two runs on 2026-09-30 produced byte-identical `results.json`, `pairs.csv` and `sessions.csv`.
Reproducing them needs the local session logs, which are not committed. They are also archived in
`~/dev/afast-orch-primary-20260924/archive/session-logs-20260924.tar.gz`, but that archive covers
only the 2026-09-24 sessions.

| File | Contents |
|---|---|
| `caching_survey.py` | extraction and analysis (Python 3.10+, numpy) |
| `results.json` | every number quoted here; corrections are under `headline.corrections` |
| `pairs.csv` | 1,797 matched pairs (routed or control run vs its anchor), one row each |
| `sessions.csv` | 2,240 runs with per-session tokens, cost, switches and rebuild cost; home directory shown as `~` |

## Data and pairing

- **Runs:** 2,240 counted runs (the latest non-infrastructure attempt per campaign, cell, task and rep).
  2,232 have a session log; 8 are aborted runs with none.
- **Cost:** per-session cost is the sum of `cost_usd` over every `llm:response`, background calls
  included. It equals `result.json` cost exactly.
- **`cost_usd` is a price table, not billing.** It fits list prices to about 1e-15. $/M tokens:

  | Model | uncached input | cache read | cache write | output |
  |---|---|---|---|---|
  | Fable 5.1 | 10 | 0.25 | 12.5 | 50 |
  | Opus 5.5 | 4 | **0.20** | 5 | 20 |
  | Sonnet 5 | 3 | **0.30** | 3.75 | 15 |

  The fit also confirms the token convention: `input_tokens` includes cache reads and excludes cache
  writes.
- **Pairs:** same campaign, same task or scenario, same rep index; the routed run's anchor is the plain
  run on the same host model in the same batch. Ratios are geometric means. 95% CIs bootstrap over
  tasks (3,000 resamples, seed 7).
- **Suites:**
  - **S1:** small single-turn coding tasks.
  - **s1m:** the same kind of tasks as 4-turn sessions resumed with `--resume`, about 5 s between
    turns.
  - **S3:** SWE-bench Verified, single long turns.
- **Matched pairs (counts in `results.json` → `inventory`, `groups`):**

  | Suite | Contrast | Pairs |
  |---|---|---|
  | s1m 4-turn (`~/dev/afast-ev/{mt-dev,mt-smoke,planner-mt-dev,planner-smoke,planner-smoke2,v12-mt-dev,value-mt-dev,m-holdout3}`) | orch-default vs plain | 39 |
  | | orch-default-opus vs plain-opus | 45 |
  | | planner variants | 9–24 each |
  | | plain-sonnet vs plain / plain-opus | 42 / 45 |
  | S1 single-turn (12 campaigns under `~/dev/afast-ev`) | orch-default vs plain | 168 |
  | | orch-default-opus vs plain-opus | 204 |
  | | other routing cells | 7–48 each |
  | | plain-sonnet vs plain / plain-opus | 235 / 204 |
  | S3 routing (`~/dev/afast-orch-primary-20260924/swe-*`) | orch-primary (Sonnet first, escalate mid-turn) | 11 |
  | | orch-router-jev | 30 |
  | | orch-router-local | 10 |
  | | orch-router-rules | 20 |
  | | plain-sonnet | 11 |
  | swebench-complete v4 | Sonnet only, model routing off | used only for the receipt check |

  In total, 903 routed pairs.

## Headline

**Routing saved less money in 4-turn sessions than in single-turn ones on the Fable host, and cost
more than the anchor on the Opus host. Cache rebuilds after a switch explain part of this, not all of
it.**

| Contrast (routed vs plain, same host) | Pairs | Cost ratio [95% CI] | Time ratio [95% CI] | Pass |
|---|---|---|---|---|
| Fable host, single-turn S1, all routing cells | 295 | 0.44 [0.37, 0.54] | 0.55 [0.48, 0.64] | 293/294 |
| Fable host, 4-turn s1m, all routing cells | 75 | 0.60 [0.44, 0.73] | 0.43 [0.36, 0.52] | 74/73 |
| Opus host, single-turn S1, all routing cells | 360 | 0.80 [0.74, 0.88] | 0.93 [0.86, 1.00] | 356/358 |
| Opus host, 4-turn s1m, all routing cells | 90 | 1.19 [1.12, 1.26] | 1.00 [0.97, 1.04] | 86/85 |
| **Same cell:** orch-default-opus, 1-turn → 4-turn | 204 / 45 | **0.95** [0.92, 0.99] → **1.31** [1.19, 1.41] | 0.86 → 0.97 | |
| **Same cell:** orch-default (Fable), 1-turn → 4-turn | 168 / 39 | 0.49 [0.42, 0.59] → 0.62 [0.46, 0.74] | 0.52 → 0.42 | |
| **No-switch control:** plain-sonnet vs plain-opus, 1-turn → 4-turn | 204 / 45 | **0.97** [0.92, 1.03] → **1.35** [1.27, 1.41] | 0.98 → 1.14 | |
| S3, turn-start routers (Jev, local, rules) | 60 | 0.93 [0.78, 1.07] | 0.88 [0.75, 1.03] | **38/44** |
| S3, orch-primary (mid-turn escalation), 1 rep | 11 | 1.39 [1.09, 1.69] | 1.14 [0.73, 1.67] | 9/8 |

**Read the 1-turn vs 4-turn rows as a suite contrast, not a pure length effect.** The single-turn
and 4-turn sessions are different task suites. The pooled "all routing cells" rows also mix different
cells: Haiku-routed variants appear only in the single-turn pool. The same-cell rows are the fairer
comparison: orch-default-opus goes from 0.95x to 1.31x, and the Sonnet control that never switches
goes from 0.97x to 1.35x.

### Per turn inside the 4-turn sessions

Each ratio compares a routed turn with the same turn of the anchor session (`headline.per_turn_multiturn`).

| Host | Turn 1 | Turn 2 | Turn 3 | Turn 4 |
|---|---|---|---|---|
| Fable | 0.33 | 1.59 (0.67 without rebuild) | 0.70 | 0.66 |
| Opus | 0.89 | 1.93 (1.13 without rebuild) | 1.44 | 1.34 |

Turn 2 is where most routes move to the host model: 62 of the 110 turn-boundary switches.

### Why the Opus host loses: price and volume, about half each

From `headline.corrections.price_volume_plain_sonnet_vs_plain_opus`:

- **Price on identical tokens.** Sonnet reads cache at 1.5x Opus's price, and every other token class
  costs 0.75x. Re-pricing the same tokens:
  - In write-dominated single-turn sessions, Sonnet costs **0.87x** Opus.
  - In 4-turn sessions, where cache reads are 34% of Opus's cost, Sonnet costs **1.01x** Opus.
- **Volume.** In 4-turn sessions plain-sonnet also used **1.38x the requests** and **1.44x the
  cache-read tokens** of plain-opus.
- **Split.** Between 1-turn and 4-turn, plain-sonnet's ratio rises from 0.97x to 1.35x. About **46%**
  of that rise is the price edge eroding (0.87x → 1.01x) and **54%** is extra volume (volume factor
  1.12x → 1.34x).

## Cache rebuild after a switch

**What a "rebuild" counts.** On the first request after a switch: the cache-write tokens beyond the
new tail of the conversation, priced at write minus read on the new model.
- The same measure on requests with no switch totals $0.20 across all 2,232 sessions, so it isolates
  switches.
- The average switch rewrote about 28k tokens.

**Rebuild cost depends heavily on the stratum,** so a single pooled number would mislead
(`headline.corrections.rebuild_by_stratum`):

| Stratum | Pairs | Sessions with a switch | Rebuild share of routed cost |
|---|---|---|---|
| S1 single-turn routing | 667 | 1 | **0.3%** (about 0) |
| s1m 4-turn, Opus host | 90 | 29 | **11%** |
| s1m 4-turn, Fable host | 75 | 33 | **27%** |
| S3 orch-primary (mid-turn escalation) | 11 | 10 | **27%** rebuild only (42% with effort-change rewrites) |
| S3 turn-start routers | 60 | 17 | 13% |

The pooled totals across all 903 routed pairs are $38.86 rebuild, 10% of routed cost, and 23% of the
gross saving. They are kept in `results.json`, but the anchor cost in them double-counts: **only 593
unique anchor runs back the 903 pairs**, because several routed cells share one anchor.

Mid-turn switches all follow the same pattern:

- **Where they came from:** 28 in all.
  - 10 orch-primary on S3.
  - 17 from orch-router-jev and orch-router-local on S3.
  - 1 orch-router-rules on S1.
- **Pattern:** every one of them ran 6 Sonnet requests and then moved to the host. One local-router
  session switched after 5.
- **The shipped default does not switch mid-turn:** orch-router-rules on S3 made 0 switches and came
  in at 0.98x.

**"Without rebuild" is an accounting residual, not a ratio you can achieve.** It subtracts the
measured rebuild premium (and, for orch-primary, the effort-change premium too) and assumes nothing
else would change.
- S3 orch-primary goes from 1.39x to **0.75x [0.56, 0.97]** on that basis. That rests on 11 instances
  at 1 rep.

## Receipts vs measured

- **The routing sessions carry no efficiency receipts (0 of 903).** All routing runs predate them.
- **The planner's own per-turn cost predictions:**

  | Planner cells | Predicted saving | Measured saving | Agreement |
  |---|---|---|---|
  | Fable host | $13.52 / $7.04 / $6.68 | $7.01 / $6.66 / $5.30 | Original planner overstated about 1.9x; later versions within 6–26% |
  | **Opus host, 4-turn** (orch-planner-opus / -value-opus) | **+$1.35 / +$0.31** | **−$1.54 / −$0.80** | **Wrong sign.** Negative in all 3 scenarios for both; only 3 scenarios, so no significance claim |

- **SWE-bench v4 prepared-action receipts** (same model, no routing): receipts claimed $2.22 saved over
  35 runs. Measured −$2.80, and per-pair correlation was −0.12.

## Risks and limits

- **First requests were often already warm.** Runs ran three at a time, so some sessions found the
  system prompt cached by another run. How often differs by arm: in 4-turn sessions, 83% of routed vs
  67% of anchor sessions; plain-sonnet only 38%. Normalizing both arms to all-cold or all-warm gives
  these ranges:

  | 4-turn contrast | Raw | Normalized range |
  |---|---|---|
  | Opus host routing | 1.19 | 1.16–1.27 |
  | Fable host routing | 0.60 | 0.565–0.65 |
  | plain-sonnet vs plain-opus | 1.35 | 1.19–1.34 |

  The conclusions hold across these ranges. (`headline.corrections.first_request_warmth`)
- **The multi-turn evidence is thin and partly tuning data.**
  - Only 6 scenarios. **84 of the 90 Opus 4-turn pairs (69 of 75 on Fable) come from the 3 dev
    scenarios**, which were used for tuning; they were rerun across seven campaigns and several builds.
  - The 3 holdout scenarios have 1 rep.
  - Everything is synthetic, at most 4 turns, with about 5 s between turns.
- **The switch itself is not isolated.** Routed cells also change effort settings and add the
  orchestrator, and no arm "decides once and never switches".
- **Quality is near ceiling on S1 and s1m.** On S3 the turn-start routers resolved 38 of 60 against
  44 of 60.

## What is NOT measured

- **Longer sessions.** Nothing longer than 4 turns, and no real human chats.
- **Cache expiry.** Turns were about 5 s apart, so the anchor's cache never expired (it expires after
  5 minutes). With real think time the anchor would also pay rewrites, which changes both sides of
  the comparison.
- **Receipts in routing sessions.** Routed sessions have no `usd_saved` receipts.
- **Cold-start costs without concurrency.**
- **Actual billing.**

## Proposed experiment (about $500, about 10 h unattended; needs approval before running)

**Purpose:** measure the saving against chat length and cache expiry, isolate the cost of switching,
and collect receipts from routed sessions.

- **Tasks:** 6 new, preregistered, **8-turn** scenarios, with checks after each turn.
- **Arms, Opus host:**
  - plain-opus
  - plain-sonnet (no-switch control)
  - orch-default on the current build, which emits efficiency receipts
  - orch-planner-v12
  - **orch-sticky**, a new cell that decides once per session and never switches, so the switch is
    isolated
- **Arms, Fable host:** plain, orch-default, orch-planner-v12, orch-sticky.
- **Reps:** 3, cell order shuffled. Either serialize per scenario or record first-request warmth.
- **Cache-expiry factor:** 6 minutes between turns vs none. Opus host only, arms plain-opus,
  plain-sonnet and orch-default, 18 sessions each.
- **Power:**
  - Measured SD of the log cost ratio: 0.23 for Opus routing, 0.17 for the Sonnet control, 0.38 for
    Fable.
  - 18 pairs detect a 1.2x effect on the Opus host at 80% power.
  - Fable needs about 34 pairs: add 3 reps there or treat it as a screen.
- **Cost:** about $320 for the no-gap block plus about $130 for the 6-minute block, plus 10% for
  retries. This assumes 8-turn sessions cost about 2.5x the measured 4-turn means.
- **Time:** about 3 h for the no-gap block and 6–7 h for the 6-minute block (mostly idle waiting).
- **Optional (about $50, 2 h):** re-run 10 SWE-bench instances × {plain, shipped default} × 2 reps on
  the current build, to collect S3 receipts and confirm no mid-turn switches.

This is a proposal only. Nothing has been run, and it should not run until approved.
