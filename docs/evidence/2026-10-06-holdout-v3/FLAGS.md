# The flags in this campaign, and how the preregistration handles each

`data/summary.json` lists 14 flagged sessions in three groups. None changes a verdict. The rules applied are the preregistered ones
(`prereg/PREREGISTRATION-holdout-v3.md`, "Estimands and rules shared by every hypothesis" and "Stop rules"); no rule was added.

Preregistered validity rule: a session is **valid** iff `wave_valid`, `cost_valid`, `mechanism_engaged`, `cache_audit_clean` and not an infrastructure failure.
**Cost endpoints** use a scenario-rep only if every session the contrast needs is valid. **Quality endpoints are unfiltered** (every session except
infrastructure failures). A failing session is "excluded from cost endpoints and counted". `cost_mismatch` is not in the validity rule.

## 1. Mechanism-gate failures: 8 Fable sessions of bleach-sanitize-review (r1 and r2; arms anchor, anchor_m, ph, ph_m)

* **Which gate failed:** "one model on every main request" and, for ph / ph_m, "decided once and never switched". Every one of the 8 sessions was
  requested on Fable 5.1 but had 1-3 main requests (2-6 model switches) **served by `claude-opus-5-5`**; the other 33-41 main requests were Fable. Effort was
  not the failure: ph_m ran `medium` on every main request including the Opus ones, and the default arms ran with effort absent throughout.
  Reasons recorded in `data/sessions.jsonl` (`mechanism_reasons`): "served model(s) ['claude-opus-5-5'] do not start with claude-fable-5-1", plus "main requests on
  [fable, opus]: a session on one model was required" and "N model switches in a session that must not route" for the ph arms.
* **Scope:** only this one scenario, only these 4 of the 6 Fable-wave arms. ShF (served Sonnet 5 on both reps) and Pc (Sonnet 5) in the same waves passed, and
  all 4 Opus-host arms of the scenario passed. No other scenario in the 1,224 sessions shows a served-model or switch failure.
* **Cause (inference, labelled as such):** the provider module's fallback ladder (`amplifier-module-provider-anthropic`, `_FALLBACK_NEXT_FAMILY`:
  fable -> opus -> sonnet -> haiku) retries a refused or overloaded request one rung down, and `refusal_fallback_enabled` defaults to true. bleach-sanitize-review is
  a security review of three planted vulnerabilities. In the raw requests the Opus request carries the whole conversation uncached
  (e.g. r1 anchor request 12: 13,877 uncached input + 32,029 + 36,931 = 82.8k tokens, the size of the context at request 11), and the next Fable request
  re-writes the cache (53,658 write tokens). That is the signature of the same conversation sent to a different model, not of a new task. The retained
  events do not contain the provider's fallback events, so refusal versus overload is **not proven** from this package; either way the model change happened in the provider, below the policy
  under test, and the product did not choose it. The two Opus-host anchors that cost-mismatched (group 2) also show a fallback-ladder artifact.
* **Handling (preregistered):** the 8 sessions are `mechanism_engaged: false`, so they are excluded from cost endpoints (every Fable contrast that needs an
  anchor, anchor_m, ph or ph_m session drops bleach r1 and r2: H1 and the Fable freeze rows use 59 scenarios; H7 uses 19 of 20) and counted in
  `health.by_arm`. They stay in the quality endpoints (unfiltered), where their turn-pass is 0.9-1.0.
* **Stop rule:** "any mechanism-gate failure (wrong served model, ...): stop; a failing ShF is a product bug, fixed before resuming; a fix restarts the
  campaign". **This stop did not happen.** The mechanism gate is evaluated when the rows are extracted (`paired.py rows`), not while the campaign runs, so the failures were found after the 240
  waves were done. `s1_result.json` reports it in `health.stop_rule_triggers`. We did not restart: the failing arms are not ShF/ShO (no product decision is involved), the
  cause is outside the product, and a restart would have spent a second ~$5k to exclude one scenario that the rule already excludes from cost. This is a deviation from
  the letter of the stop rule and is decided by the owner, not by this document; the verdicts below are the preregistered analysis as run.
* **Robustness (exploratory, same script, same seed, no new rule):** dropping bleach-sanitize-review entirely, and dropping it plus black-pipeline-explain (group 3):

  | analysis | scenarios | H1 cost (95% CI) | H1 turn-pass lb | H4 Holm p | H7 turn-pass lb | Fable freeze | Opus freeze |
  |---|---:|---|---:|---:|---:|---|---|
  | as run | 60 | 0.581 (0.542-0.625) | -0.028 | 0.187 | -0.063 | always_route, strong default, scope off | keep shipped default |
  | drop bleach | 59 | 0.581 (0.542-0.624) | -0.027 | 0.135 | -0.060 | same | same |
  | drop bleach + black-pipeline | 58 | 0.577 (0.538-0.620) | -0.028 | 0.139 | -0.064 | same | same |

  Every supported / not-supported verdict, the H2 decision and both frozen configs are identical in all three. Files: `result/robustness-*/s1_result.json`.

## 2. Cost mismatch: bleach-sanitize-review-r1-opus-anchor and -r2-opus-anchor

* **What the check saw:** `cost_usd_provider` differs from `cost_usd_recomputed` (r1 2.306 vs 2.341; r2 2.503 vs 2.519).
* **Where it comes from, per request:** exactly one **background** (not main-loop) request per session names a model id `claude-sonnet-5-5` (r1 request 14, turn 4,
  11,074 input / 159 output tokens; r2 request 15, turn 4, 5,213 input / 0 output). That id is not in the price table: the provider reported $0.00 for it, our recomputation priced it at
  $0.0356 (r1) and $0.0156 (r2). It is the same turn-4 spot where the Fable sessions of this scenario show their Opus fallback requests, and "opus -> sonnet" is the next rung of the fallback ladder.
  The model id looks like a ladder-built string (family sonnet + the opus version 5-5), not a real model; whether it was served is unknown. That this id appears nowhere else in 49,254 requests supports a fallback artifact.
* **Cost impact:** $0.036 of $2.34 (1.5%) and $0.016 of $2.52 (0.6%) on one session each; the cost basis (`cost_usd_tools_normalized`) uses the recomputed price, so it is included at the conservative (higher) value.
* **Handling (preregistered):** `cost_mismatch` is not part of the validity rule, `cost_valid` is true and the sessions are mechanism-clean (all main requests were Opus 5.5), so both sessions stay in every endpoint.
  Excluding the two requests would lower those two anchor costs by 1.5% / 0.6%, raising ShO/A0O by that much on one scenario; the effect on a geometric mean over 60 scenarios is below 0.1% and no verdict is within reach of it.

## 3. Cache audit: 4 sessions, all black-pipeline-explain rep 2

| session | surplus read tokens per request | requests flagged | cost of the surplus |
|---|---:|---:|---|
| black-pipeline-explain-r2-fable-anchor | 3,642 | 7 | read $0.25/M: $0.006 per request; one-time write-vs-read difference about $0.04 |
| black-pipeline-explain-r2-any-pc (Sonnet 5) | 401 | 3 | < $0.01 |
| black-pipeline-explain-r2-opus-anchor | 1,125 | 3 | < $0.02 |
| black-pipeline-explain-r2-opus-aa | 964 | 3 | < $0.02 |

* **What the audit saw:** from some request on, each main request reads a constant block of cache tokens larger than the session's own earlier writes plus the shared tools prefix
  (e.g. fable-anchor request 11: read 91,964 = 56,293 own + 32,029 shared + 3,642 surplus). The surplus is constant across the flagged requests: one discrepancy that persists, not
  new events each time. The same pattern was seen once in the effort-control study (`../2026-10-06-effort-control-fable/FLAGS.md`, 421 tokens).
* **Why it is not leakage between arms, as far as the logs show:** all four are rep 2 of one scenario in waves that ran together, but each session has its own nonce in the system prompt and the surplus
  is a few thousand tokens (one prompt block), not a shared prefix. The retained logs do not show which earlier call produced the cached block; that is not provable here.
* **Handling (preregistered):** `cache_audit_clean: false`, so each is excluded from cost endpoints (the scenario-rep drops from any contrast that needs it) and kept in quality (unfiltered).
  4 of 1,224 sessions is 0.33%, under the 2% stop rule. The pair rows in this campaign were built after the harness fix, so `pairs.jsonl` carries both sessions' flags.
* The anchor/pc/opus-aa flags sit in black-pipeline-explain r2 only; the robustness table in section 1 includes the run without this scenario.

## Memory watchdog

`killed_memory` is empty (0 kills; the stop rule allows 2).

## Summary

| group | sessions | gate / rule | handling | verdict impact |
|---|---:|---|---|---|
| mechanism failed | 8 | served model, one-model, decided-once | cost-excluded, quality kept, counted; stop rule not enforced live (disclosed) | none (robustness table) |
| cost mismatch | 2 | not in the validity rule | kept | none (< 0.1%) |
| cache audit | 4 | `cache_audit_clean` | cost-excluded, quality kept; 0.33% < 2% | none |
