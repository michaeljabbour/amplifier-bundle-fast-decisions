# A1: the observatory week (offline, $0)

Plan: `docs/design/v3/PLAN.md` section A1 (RQ1). Code: `evals/v3/a1_observatory.py`. Input: the local store
`~/.amplifier/fast-decisions/events/` (and `events-eval/`), streamed line by line (never a whole file in memory),
snapshot cutoff **2026-10-05T17:00Z** (later events, written while this ran, are excluded). Only aggregates leave the
machine: no workspace names, labels, paths, prompts, responses, candidate ids or hashes. **$0 spent**: the planned
relabelling of 200 mismatches (step 6) was not possible, see below.

**Measured vs estimated.** Event counts, agreement counts, latencies and recorded per-call costs are measured (by the
recorder). Receipt dollars are the policy's own estimates. The "would have saved" figure is a projection that was
never measured. Each table says which.

## What was there (measured)

* **464,524 events** in 4,470 session files (1,597 distinct session ids) from 2026-09-17 to the cutoff; the week
  2026-09-17..09-23 holds **171,609** (matches HISTORY.md). `events-eval/`: 7,943 events, 307 files, all after 09-25.
* **Traffic** (`traffic_classification.csv`): production 398 sessions / 348,373 events (75%), test 1,136 sessions /
  115,505 events, unclassifiable 63 sessions / 646 events (0.14%). In the week: production 101,981, test 68,984,
  unclassifiable 644. Basis: the receipts' `AFAST_TRAFFIC` tag where present (93 sessions), a Forge session label
  (860), a scratch/eval workspace basename (260), else production (321); children inherit the parent's class.
* **Event mix** (`health_mix.csv`): `health` events are 71.5% of the store (the "71% heartbeats" in HISTORY.md), but
  true 15 s session heartbeats are **49.0%**; native-hook tool metadata is 18.1%; configuration, close, shadow and
  recorder status make up the rest. Decision-bearing events are a small minority.
* **Decision census, production sessions** (`decision_census.csv`): start-tier judgement (`difficulty_judged`) in 214
  of 398 sessions (54%), median 1 per session; per-request `model_routed` / `effort_routed` in 219 (12,094 each,
  median 25 per session); shadow proposals in 82 sessions (633); efficiency receipts in 77; keep-alive refreshes in 10;
  role proposals 5; waste guards 7. One production active fast path (`routed` fast); 11,955 production requests were
  routed slow because the read shortcut is disabled.

## Shadow agreement: what agreed with what (`shadow_agreement_rates.csv`, `shadow_agreement_decomposition.csv`)

**Definition.** `match` = the scorer's chosen prepared read candidate (always a `fast_workspace` read) has the same
tool AND argument digest as the host LLM's next actual tool call (`shadow.py:_emit_agreement`). It is agreement with
the host, not correctness. A host call to any other tool (`read_file`, `bash`, `grep`, ...) is a mismatch by
construction, even if it read the same file. `abstained` = the scorer chose the slow path.

| slice | match / n | rate (Wilson 95%) |
|---|---:|---:|
| all shadow_agreement events (the 7.1% headline) | 117 / 1,642 | 7.1% (6.0-8.5%) |
| scripted-demo backend (synthetic: always picks the first candidate; not a model) | 0 / 648 | 0% (0-0.6%) |
| real scorer (local qwen3:0.6b; one early event without a backend field) | 117 / 994 | 11.8% (9.9-13.9%) |
| real scorer, not abstained | 117 / 601 | 19.5% (16.5-22.8%) |
| real scorer, host's next call used the candidate tool | 117 / 151 | 77.5% (70.2-83.4%) |
| same, not abstained | 117 / 140 | 83.6% (76.6-88.8%) |
| any scorer, host used another tool (unmatchable) | 0 / 1,491 | 0% |
| production traffic | 1 / 633 | 0.2% |
| test traffic | 113 / 991 | 11.4% |

* **The 7.1% is mostly a label artifact.** 1,491 of 1,642 decisions (91%) followed a host call to a tool the
  candidate set could not contain, so they could never match. 648 (39%) were scored by the synthetic `scripted-demo`
  backend that the shadow rung shipped with, not by a model. Where a match was possible at all, the local scorer
  agreed with the host 77-84% of the time.
* **Jev never ran in shadow.** 1,641 of the 1,642 events fall in the week (09-17..09-23), before Jev became the
  default (09-24); the one later event is scripted-demo. Jev's observatory footprint is start-tier judgements only.
* **Not identifiable as correctness.** The store keeps no state text (privacy allow-list: hashes, counts, ids), so a
  stronger model cannot be asked whether a mismatch was defensible. The relabel step was therefore not run ($0); the
  correctness of shadow choices is unidentifiable from this store.

## Latency (measured; `latency_by_backend.csv`)

| decision | backend | n | p50 ms | p95 ms |
|---|---|---:|---:|---:|
| shadow proposal | local qwen3:0.6b | 993 | 48 | 93 |
| active read decision (`scored`) | local qwen3:0.6b | 736 | 69 | 97 |
| shadow proposal | scripted-demo (fixed 35 ms sleep) | 648 | 36 | 52 |
| start tier, judge call | Jev | 248 | 159 | 311 |
| judge usage record | Jev 1.13.0 | 26 | 176 | 296 |
| for scale: host provider call (`slow_end`) | provider | 16,012 | 4,828 | 26,920 |

Start-tier decisions that did not call the judge (scope gate, rules) record ~0 ms (n=302) and are excluded above.

## Would-have-saved (estimated) vs measured later

| lever | what the observatory/receipts claimed (estimate) | measured later |
|---|---|---|
| read shortcut (shadow, week) | 117 of 994 real-scorer decisions "would have avoided an LLM turn"; projected 998 s over the week (994 x (8,586 - 56 ms) x 11.8%) | one task 39% faster, a repair task 8% slower (2026-09-28-decisions); no judge useful on 42 real read decisions (2026-10-01 trace study); shipped off |
| cache keep-alive | 194 production receipts, net **$222.66** (172 kept warm +$229.95, 16 missed -$6.99, 6 not needed -$0.31) | one live A/B (330 s wait): measured $0.160384 = receipt $0.160384. The aggregate is not measured |
| loop_stop (poll in place) | 3 receipts, $0.70, 28.7 s | waste-guards A/B: measured $0.0558 vs receipt $0.0514 |
| cheaper_model (per-step Sonnet) | 170 production step receipts: **-$1.80** (cost more), +432.5 s; 68 kept-on-host: -15.3 s judge latency | real-workload replay: routing routine steps to Sonnet would ADD $17-46; lever off |
| context_rightsize | 3 receipts, $0.11 | not measured |

## Inputs for A3 (`a3_workload.csv`, `a3_start_tier_first_per_session.csv`; see `../a3-projection-inputs/`)

* Production recorded spend by host model (recorder price-table estimate per call): Opus 5.5 $632.66 (64 sessions),
  Sonnet 5 $545.06 (71), Haiku $7.85; no Fable-hosted production sessions.
* First start-tier decision per production session (n=214): scope gate kept the host 105 (49%), Jev judged strong 68
  (32%), Jev judged cheap 35 (16%), rules 6. Jev routed 34% of the sessions it judged in production vs 89% on main-v1.
* Effort switching in production was rare: 12 changes in 12,094 requests (7 sessions), vs 828 in 3,752 test requests.
  The section-0.4 cache artifact was an eval-traffic phenomenon.

Reproduce: `nice -n 10 python3 -m evals.v3.a1_observatory` (a few seconds; needs the local store). The output's
`excluded_after_cutoff` grows with the live store; every other number is fixed by the cutoff.
