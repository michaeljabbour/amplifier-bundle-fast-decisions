# Result: S1 (holdout-v3), the v3 core study

**On 60 scenarios no agent had run, the shipped bundle's routing saves about 42% on Fable 5.1 with no measurable loss in turn-level quality, adds nothing on Opus 5.5, and the
deterministic rule does everything the decision model does. Six of seven preregistered hypotheses were decided as predicted; H4 (medium effort on Opus) and H7 (task types) were not supported.**

## What was run

60 holdout scenarios x 2 repetitions x two hosts (Fable 5.1, Opus 5.5), 10 session types per scenario-rep plus a repeat anchor on 12 scenario-reps: **1,224 sessions, 240 waves, 12,856 turns, 49,254 requests.**
Every arm of a scenario-rep started from the same frozen workspace with its own cache nonce. Cost is `cost_usd_tools_normalized` plus the decider charge. Intervals are scenario-cluster bootstrap percentile intervals,
10,000 resamples, seed 20261005; Holm adjustment inside each preregistered family (F1 = H1, H3, H4, H6; F2 = H2, H5, H7). Ratios below 1.0 mean the first arm is cheaper. Spend $4,975.51.
Command: `python3 evals/v3/s1_analysis.py --sessions data/sessions.jsonl --out result --resamples 10000 --seed 20261005` (output: `s1_result.json`).

## Hypotheses

| | question | estimate | interval | Holm p | verdict |
|---|---|---|---|---:|---|
| **H1** | Fable: rule R* routing + medium effort (C*_F) vs plain Fable. Need cost 95% upper < 0.75 and turn-pass lower > -0.05 | cost **0.581**; turn-pass **-0.013** | cost 0.542-0.625; turn-pass -0.028 to +0.002 | 0.0004 | **supported** (59 scenarios cost-valid) |
| **H2** | Fable: decision model (Jev) vs the rule R*: equivalent within +-5% cost and +-0.02 turn-pass | cost **1.008**; turn-pass -0.003 | 90%: cost 1.000-1.019; turn-pass -0.007 to 0.000 | 0.0003 | **supported (equivalent): ship R***, no external call, no consent |
| **H3** | Opus: shipped bundle vs plain Opus, overhead within +-5% | cost **0.999**; turn-pass +0.007 | 90%: 0.984-1.017 | 0.0004 | **supported** (no measurable overhead) |
| H3b | Fable: pinned-host bundle vs plain Fable (descriptive, no family) | cost 1.004; turn-pass +0.004 | 90%: 0.989-1.019 | none | descriptive: overhead about 0%; judge dollars $0, no keep-alive or waste-guard receipts |
| **H4** | Opus: plain at medium vs plain default: cost upper < 1.0 | cost **0.992**; turn-pass -0.002 | 95%: 0.974-1.009; turn-pass -0.013 to +0.009 | 0.187 | **not supported** (upper bound 1.009 is above 1.0). ShO-m vs ShO: cost 1.011 (0.996-1.029); turn-pass -0.003; final-state -0.025 |
| **H5** | Opus: routing to Sonnet (Pc) vs plain Opus: cost lower bound > 1.0 | cost **1.255**; turn-pass -0.004 | 95%: 1.197-1.321 | 0.0003 | **supported**: routing to Sonnet 5 still costs 26% more than plain Opus on fresh scenarios |
| **H6** | Fable: live shipped session vs the cost the decomposition predicts: within +-5% | **1.014**; turn-pass +0.004 | 90%: 0.996-1.032 | 0.0008 | **supported** (the live bundle behaves as the model predicts; 70% of scenario-reps routed) |
| **H7** | Review + explain (20 scenarios; 19 cost-valid): Pc vs PhF-m turn-pass non-inferior, lower bound > -0.05 | cost 0.616; turn-pass **-0.028** | 95%: -0.063 to +0.013 | 0.120 | **not supported**: a 5-point loss cannot be excluded => ship `keep_on_host: [review, explain]` |

H7 feature scenarios (exploratory, 10 scenarios): cost 0.635, turn-pass +0.026 (-0.003 to +0.060).
Frozen prediction for H1 was 0.508 [0.483, 0.536] (turn-pass -0.019); observed cost 0.581 is higher and outside that interval; the turn-pass prediction held.

## H2 decision

Equivalent on both endpoints (ratio 90% CI inside [0.95, 1.05]; turn-pass 90% CI inside [-0.02, +0.02]) and the Jev-ships condition (cost upper < 0.95) fails, so the decision rule gives **ship R***
(`allow_external_state` stays false; Jev becomes an opt-in decider). The two deciders disagreed on 4 of 120 scenario-reps (d = 0.033 < 0.15), so they cannot differ materially by construction.

## Frozen configuration per host (preregistered deterministic rule)

* **Fable 5.1: `always_route | strong effort default | scope gate off | keep_on_host none`** (cost 0.528, 95% CI 0.503-0.558; turn-pass -0.017, 95% CI -0.032 to -0.002; final-state -0.017),
  the cheapest of the candidates that clear all three conditions; no simpler candidate is within 3% of it. **`selected_on_holdout` = true**: it differs from the preregistered
  C*_F (R*, strong medium, scope 300, no keep_on_host; 0.581), so it is labelled selected on holdout and **must replicate in S2 before it ships**. Not resolved here: this
  frozen config has no keep_on_host while H7 says to ship `keep_on_host: [review, explain]`; the freeze rule and H7 are separate preregistered rules and they point different ways. Candidates that keep review+explain on the host
  (`keep review+explain` rows in `s1_result.json`) cost 0.65-0.71 with turn-pass about 0.000 to -0.009.
* **Opus 5.5: no candidate qualifies; the host keeps the current shipped default** (`selected_on_holdout` = false). The preregistered C*_O (bundle-unrouted medium) is not a candidate: cost 1.009 (0.991-1.030).
  Every Opus candidate costs at least as much as plain Opus (plain medium 0.992, upper bound 1.009).
* Full candidate tables (Fable 24 rows, Opus 24 rows) are in `s1_result.json` under `freeze.{fable,opus}.table`.

## Flags and operations (details: `FLAGS.md`, `FAILURES.md`)

* 8 Fable sessions of bleach-sanitize-review were served partly by Opus 5.5 (the provider's fallback ladder is the likely cause; not provable from the retained logs). Preregistered handling: excluded from cost, kept in quality.
  **The preregistered stop rule for a mechanism-gate failure was not enforced while the campaign ran** (the gate is evaluated at row extraction); this is a disclosed deviation. Dropping the scenario changes no verdict or frozen config.
* 2 cost mismatches (one fallback-ladder background request priced differently by the provider and by us; <= 1.5% of one session each): kept, no effect.
* 4 cache-audit flags (all black-pipeline-explain rep 2; a few thousand surplus read tokens per session; 0.33% < 2%): excluded from cost, kept in quality, no effect.
* Operational: a Forge outage (943 git fsmonitor daemons exhausting file handles) between 03:24 and 07:07, 135 infrastructure-failed attempts rerun whole, the $5,000 budget cap raised to $6,300 mid-run, concurrency changed several times.
  Final ledger $4,975.51, which is below the original cap.
* A/A noise floor (descriptive; 11 scenario-reps): Fable ratio 1.044, turn-pass +0.018; Opus ratio 0.993, turn-pass -0.047. The Opus quality spread between two identical anchors is as big as the effects tested, so differences of a few points in turn-pass on single arms are not interpretable.

## Not claimed

* Nothing about a different date, host version or provider build; sessions ran 2026-10-05/06 against Fable 5.1, Opus 5.5 and Sonnet 5.
* No quality claim beyond turn-pass and final-state pass on these 60 scenarios; 20 of them are review/explain where the cheaper model is least certain (H7).
* The Fable freeze is a holdout selection among 24 configurations; its cost advantage over the preregistered C*_F (0.528 vs 0.581) is not confirmed until S2.
