# v4 evidence map: decision-models report (read-only audit)

Repo `~/dev/fd-v3`, read at `origin/main` = `3cd180b` (Merge PR #70). All paths are relative to the repo root.
Status labels: **PREREG** = preregistered confirmatory. **POST-HOC** = arm or analysis added after preregistered results were known, on frozen cases. **EXPL** = exploratory or descriptive. **SCREEN** = dev split. **DERIVED** = arithmetic I did here from committed numbers; it is not in any evidence file.

---

## Takeaway 1: "Of the major system-1 decision models tested, Jev is the best tradeoff between price and quality"

### Evidence (constructed holdout, 63 cases, bundle gate 0.90 / 0.20 / 3 s, per-case majority of 3 reps)

| Judge | Accuracy | Wrong-auto | Coverage | p95 (client) | $/1M decisions | Status | Source |
|---|---|---|---|---|---|---|---|
| Jev 1.13 | 55/63 (Wilson 77–93%) | 1/63 | 40–41/63 per rep | 216–222 ms | $18.41 | PREREG | `docs/evidence/2026-09-30-judge-benchmark/README.md`, `holdout/summary.json` |
| GPT-6 Luna (Responses, prompted) | 60/63 | 2–3 per rep (majority 2/63) | 51/63 | 1.76–1.90 s | $40.46 (2.2×) | PREREG | same |
| GPT-6.1 Sol (prompted) | 62/63 | 0–1 per rep | 41–45 | 3.6–4.7 s | $894 (49×) | PREREG | same |
| Clef | 57/63 (in-run Jev 56) | 3/63 (Jev 1) | 46/63 | 722 ms | $65.2 (3.5×) | POST-HOC | `docs/evidence/2026-10-04-clef-judges/README.md` |
| Clef-Flash | 50/63 | 6/63 | 46/63 | 665 ms | $24.5 | POST-HOC | same |
| Luna via Decisions API | 59/63 (in-run Jev 55) | 1/63 (Jev 1) | 43/63 (Jev 40) | 3.44 s client; server p95 136–179 ms | $25.6 (1.39×) | POST-HOC | `docs/evidence/2026-10-06-openai-decisions/README.md`, `tables.md` |
| Local: nimble 9B / tev1 4B / Qwen3 8B / 4B / tev1 0.8B / Laya base / Qwen3 0.6B | 49 / 47 / 45 / 38 / 35 / 28 / 27 | 8 / 11 / 14 / 16 / 14 / 12 / 16 | | 0.03–0.3 s | $0 (compute not costed) | PREREG | judge-benchmark README |

- **Preregistered contrasts** (`evals/judge_bench/holdout/PREREGISTRATION.md`; exact McNemar, Holm). Luna − Jev accuracy is +7.9 pts with paired-bootstrap CI [+1.6, +15.9], Holm p 0.156. Sol − Jev is +11.1 pts [+3.2, +19.0], Holm p 0.094. The tests do not reject, but **the bootstrap CIs exclude 0**. "Slightly more accurate" (v3 p. 7) understates a gap of 5–7 cases out of 63. The preregistration says differences under about 8 points cannot be detected.
- **Preregistered Rule 1 (Jev remains the default unless a candidate meets all five conditions):** non-inferior on both primary endpoints, Holm-superior on at least one, p95 ≤ 500 ms, ≤ 2× Jev's cost, and ≥ 98% valid answers. No candidate displaced Jev. Luna (Responses) failed on p95 and cost. Sol failed on p95 and cost. Clef failed on p95 and cost (3.2–4.4×). Clef-Flash failed accuracy non-inferiority. Luna via the Decisions API passed the cost condition (1.3–1.7×) and failed only on p95 (client), validity (9/1296 transport failures, under 98% on dev and holdout) and superiority. **On trace-holdout it was superior on accuracy** (applied descriptively, post hoc). This rule is a "keep the incumbent" rule. It was never a test of "best tradeoff".
- **Real-decision (trace) splits**, 42 preregistered holdout cases from earlier benchmark agent sessions (`docs/evidence/2026-10-01-trace-judge-benchmark/README.md`):
  - No judge met the usefulness rule (≥ 4 of the 13 sufficient reads automatic, with wrong-auto Wilson upper bound < 10%). PREREG.
  - Jev: 23/42, 10 correct automatic reads, 5 wrong. Luna (Responses) 23/42, 5 wrong. Sol 25/42, 2 wrong, but 72/126 answers timed out (cost 57× Jev). PREREG.
  - Luna via the Decisions API: 30/42 vs in-run Jev 23/42, Holm p 0.039, the only significant accuracy difference anywhere. Wrong-auto 1 vs 5. Coverage 7/42 vs 15/42. Correct automatic reads 6 vs 10 of 13. POST-HOC, one split.
  - Clef: 26/42 vs in-run Jev 26/42, wrong-auto 2 vs 5. POST-HOC.
- **Jev run-to-run variation:** trace-holdout 23 / 26 / 23 across three runs. Jev changed 2 of 90 dev answers across runs.
- **Latency confound in the Decisions API run:** the client p50 was 1.4–1.8 s for **both** arms (Jev 1.39–1.57 s vs 0.15–0.17 s on 10-04). The arms are paired in time, but the absolute latencies are not comparable with other runs.
- **Price basis:** Luna-D bills $0.10 per M input, Jev $0.042 per M. Per-decision cost depends on tokenizer. Jev's own charge in sessions is "estimated, not billed".

### Verdict
- **SUPPORTED:** Among cloud judges with a price, Jev had the lowest cost per decision ($15.9–46.1 per M across splits) and the lowest measured client latency (p95 ≈ 220–250 ms on an uncongested path). Its holdout accuracy was within the preregistered "not detectable" band of Luna and Sol after Holm. No local model met the preregistered offline-tier safety bar. Clef-Flash was clearly weaker on dev (Holm p 0.008).
- **QUALIFIED:**
  - "Best tradeoff" is a value judgment that was never preregistered. The preregistered rule kept the incumbent unless a challenger beat it on accuracy or misfires and also met latency and price caps.
  - Jev is one point on a cost/accuracy frontier. Luna-D (+4 holdout cases at 1.4× cost) and Sol (+7 cases at 49×) are also on it. Locals are on it at $0 with unacceptable misfires.
  - **Post hoc, Luna via the Decisions API matched or exceeded Jev on every split, at ≤ Jev's misfire rate and 1.3–1.7× the price.** Its server-side latency (p95 136–179 ms) would plausibly pass the 500 ms bar. Our client-side latency was not measured cleanly. On this evidence, "best" no longer holds for Jev against Luna-D. "Cheapest of the accurate cloud judges" still holds.
- **NOT SUPPORTED / overreach:**
  - Session-level quality. Only Jev was ever tested as a session decider, and only against a rule (S1 H2: equivalent).
  - Real-world decisions. The "real" traces are 42 cases mined from the bundle's own benchmark sessions, with no human traffic. They were rebuilt by fingerprint match, not captured, and the 2,048-char state budget hid the issue text in 25 SWE-bench cases. v3's "exactly as the in-session judge had seen them" overstates this.
  - Calibration of Luna and Sol (self-reported probabilities, so ECE is not meaningful).
  - Any decision type other than read, select, search and CUA questions.
  - Billing; prices are list prices. Network-independent latency for Jev (Jev sends no server timing).
  - Labels: all were written by Anthropic models; κ 1.00 means the labels follow the guide, not operator preference.
  - "System-1 models": Luna (Responses) and Sol are general LLMs prompted for probabilities, not native typed-decision endpoints.
- **Safest strong phrasing:** "On constructed decisions, Jev was the cheapest and fastest cloud decision model we tested, and no preregistered test detected an accuracy difference from dearer judges (with 63 cases, gaps under about 8 points are undetectable). A post-hoc run of OpenAI's Decisions API matched or beat Jev on every split at 1.3–1.7× the price. Jev is the low-cost point on the frontier, not a dominant choice. No model, Jev included, was safe enough to act alone on real read decisions."

---

## Takeaway 2: "Routing to a cheaper model saves money only when the host is much more expensive once caching is included"

### Evidence
- **List prices, $ per M (in / out / cache read / cache write)** (`docs/evidence/2026-10-01-caching/README.md`; numbers.tex `Price*`):
  - Fable 5.1: 10 / 50 / 0.25 / 12.50
  - Opus 5.5: 4 / 20 / **0.20** / 5
  - Sonnet 5: 3 / 15 / **0.30** / 3.75

  Sonnet's cache read costs **more** than both hosts'.
- **Per-request cost under the gate's reference mix.** The mix is 2.7 input, 88,516 cache-read, 5,376 cache-write and 541 output tokens per request (`docs/evidence/2026-10-05-defaults-replay/REPLAY.md`; formula in `docs/CONFIGURATION.md` "Price gate"). DERIVED from these:
  - Fable $0.1164: write 58%, output 23%, read 19%.
  - Opus $0.0554: write 49%, read 32%, output 20%.
  - Sonnet $0.0548.
  - **Sonnet costs 0.47× Fable per request but 0.99× Opus.**
  - Times the request multipliers (1.11 Fable, 1.38 Opus; re-derived by replay from 124 pairs each), the gate predicts 0.523 (Fable) and 1.366 (Opus). Measured sticky-on-Sonnet/anchor: 0.504 and 1.18–1.20.
- **Measured session costs.**
  - main-v1, test split, 23 scenarios (PREREG; `docs/evidence/2026-10-02-paired-campaign/confirm/CONFIRM.md`):
    - Fable sticky 0.558 (0.493–0.643) in the pair reading, which is quality-filtered and was written after the data; 0.537 (0.481–0.614) in the arm reading.
    - Fable shipped 0.629.
    - **Plain Sonnet at default effort vs plain Fable: 0.577 (0.516–0.654).** This is the cleanest model-only contrast, with no effort confound.
    - Opus sticky 1.249 (1.125–1.389), shipped 1.380, plain Sonnet 1.433 (1.253–1.640).
  - S1 holdout-v3, 60 fresh scenarios (PREREG; `docs/evidence/2026-10-06-holdout-v3/RESULT.md`, `s1_result.json`):
    - H1 0.581 (0.542–0.625), 59 cost-valid scenarios. This is the **package** "R\* + Sonnet at medium + Fable at medium when kept" vs plain Fable at default. Routing and effort are confounded.
    - H5 1.255 (1.197–1.321), Sonnet at medium vs plain Opus at default. It lost even with Sonnet's effort advantage.
  - Pilot, main-v1 train/test and S1 replicate sign and size (v3 Fig. 16).
- **Cost composition, $/session** (numbers.tex `Comp*`, `Cc*`):
  - main-v1:
    - Fable plain $5.31 (read 1.06, write 2.82, output 1.27; 46.0 requests; 4.22 M read tokens)
    - Opus plain $2.13 (read 0.62, write 1.04, output 0.40; 36.4 requests)
    - Sonnet only $3.22 (read 1.77, write 0.96; 57.4 requests; 5.90 M read tokens)
  - S1:
    - plain Fable $4.55 (57% write, 19% read)
    - plain Opus $1.91 (52% write, 30% read)
    - Pc Sonnet $2.34 (54% read)
- **Break-even** (EXPL repricing, token counts held fixed; `generated/tables/breakeven.tex`): Opus routing (sticky) breaks even at an Opus cache-read price of $0.38/M (pair reading) or $0.34/M (arm reading), versus $0.20 today. For the shipped and sonnet arms it is $0.44–0.51. The gate's break-even is $0.429/M, which is conservative. The replay shows the gate never routes where the measured ratio is ≥ 1.
- **Caching survey** (EXPL, retrospective; `docs/evidence/2026-10-01-caching/README.md`):
  - The same orch-default-opus cell went from 0.95× at 1 turn to 1.31× at 4 turns.
  - No-switch plain Sonnet vs plain Opus went from 0.97× to 1.35×. About 46% of that rise is price (the cache-read share grows) and 54% is volume: 1.38× the requests and 1.44× the cache-read tokens.
  - Thin evidence: 6 scenarios, mostly tuning data, ≤ 4 turns, 5 s gaps.

### Verdict
- **SUPPORTED:** On the two hosts measured, the sign of the routing effect followed the session-weighted effective price, not list input price. Opus's input price is 1.33× Sonnet's, but its per-request cost under the measured mix is ≈ 1.0× Sonnet's, and routing lost (1.25–1.43×). Fable's per-request cost is ≈ 2.1× Sonnet's, and routing won (0.54–0.63×). Request volume on the cheap model (+11% to +38%) and cache-read pricing decide the sign. Both directions replicated on fresh scenarios (S1 H1, H5).
- **QUALIFIED:**
  - "Only when … much more expensive" is a necessary-condition claim fitted from **two hosts and one cheap target** (Sonnet 5 at medium). We have no host between "≈1×" and "≈2×", so the threshold is a model (the gate formula plus repricing), not a measurement.
  - The volume multiplier differs by host (1.11 vs 1.38) and was measured only on Sonnet at medium.
  - The S1 Fable figure includes medium effort. Quote 0.577 (main-v1, default vs default) for routing alone.
- **NOT SUPPORTED / overreach:**
  - Other providers, other price tables, other cheap models (Haiku, etc.) and invoices (all costs are list prices × tokens, tools-normalized).
  - Sessions over 16 turns, real human chats, 1-hour cache TTL options.
  - "Much more expensive" as a numeric threshold. The repricing sweep moves one price only and holds token counts fixed.
- **Safest strong phrasing:** "Whether routing saves money depends on the host's price after weighting by what a session actually buys (mostly cache reads and writes), times the extra requests the cheaper model makes. At list prices Sonnet costs about 0.47× Fable per request but about 0.99× Opus, and routing saved 42–46% on Fable and cost 25–43% more on Opus, on two independent scenario sets. A price check that includes caching (our price gate) predicted both directions."

---

## Takeaway 3: "Configure once for the task and initial context; don't switch until the cache expires, unless substantially cheaper"

### Measured
- **Decide-once vs per-turn**, main-v1 H3 (PREREG, test split): sticky/shipped is 0.862 (0.764–0.994) on Fable (35 triplets) and 0.917 (0.848–0.991) on Opus (33). Arm reading: 0.869 and 0.911.
  - The shipped arm re-decided per turn. Its switches cost a rebuild of $0.61/session on Fable and $0.29 on Opus (`Comp*Rebuild`).
  - Caveat: "shipped" differs from "sticky" in more than switching. Kept-host sticky sessions also ran a phase effort map; see the next item.
- **Effort switches rewrite the cache** (EXPL, A0 re-analysis of main-v1; `docs/evidence/2026-10-v3-offline/a0-counterfactual/README.md`):
  - Within a turn, a request after an effort change wrote 11,650 cache tokens on average (n = 486) vs 900 (n = 859): **12.9×**.
  - The 16 kept-host sticky sessions per host made about 26 effort changes per session and cost 1.255× (Fable) and 1.357× (Opus) their anchors.
- **Cache expiry IS measured** (not mentioned in v3):
  - main-v1 has 23 of 70 scenarios with two 420 s idle gaps (TTL 5 min; other gaps 10 s; `data/DATA-DICTIONARY.md`; `PREREGISTRATION-main-v1.md` stratifies on long gaps).
  - The first request after a 7-min pause wrote 65,062 tokens vs 11,296 after a 10 s pause (5.8× Fable plain; 6.2× Opus). It is the same for every arm: Fable sticky 62k, Sonnet 82k. n = 92 long-gap turns per arm (`generated/data/gapwrites.dat`; companion v2 §"Long pauses").
  - **After a ≥ 5-min gap, an effort change cost nothing extra:** first-request writes were 66,235 (changed) vs 67,819 (anchor), n = 24 each (A0 README). This is the only direct evidence that switching is "free" once the cache has expired. It covers effort only, with small n.
  - Routing ratio by gap pattern (EXPL; `generated/tables/slice-gap.tex`):
    - Fable sticky 0.56 (no long gap) vs 0.55 (two long gaps)
    - Opus shipped 1.30 (1.19–1.42) vs 1.17 (1.08–1.28)
    - Opus sticky 1.21 vs 1.18
    The direction fits "switching hurts less when the cache would expire anyway", but the CIs overlap.
- **S1 H6** (PREREG): live decide-once sessions cost what the pinned-arm reconstruction predicted, 1.014 (90% CI 0.996–1.032).
- **Production effort switching** (A1): 12 changes in 12,094 requests (7 sessions), vs 828 in 3,752 test requests. The 12.9× artefact was mainly an eval phenomenon.
- **Keep-alive (the opposite strategy: keep the cache warm through a gap):**
  - 194 production receipts claimed $222.66. These are policy estimates.
  - One live A/B measured $0.16, equal to its receipt.
  - The S1 H3b row reports **no keep-alive receipts**, although 21 S1 scenarios had two 420 s gaps.
- **Cache-aware per-turn planner** (caching survey, EXPL, 3 scenarios): predicted +$1.35 / +$0.31 savings on the Opus host and measured −$1.54 / −$0.80. Wrong sign.

### Design implications, not measured
- "Unless the new configuration would be substantially cheaper": there is no measured switch threshold. The price gate is a session-start gate with a 1.0 cutoff and conservative over-prediction. There is no mid-session "re-decide at expiry" in the shipped bundle (`decision_scope: session`; the legacy planner has `cache_ttl_seconds`).
- A **model** switch timed to an expired cache was never isolated. It is inferred from the fact that every arm rewrites about 60–80k tokens after a long gap.
- "Configure for the initial context": the decider sees only the first prompt plus the workspace file count (R\* = route unless > 300 files). Context size as a configuration input was never tested.
- S1's preregistered exploratory slice "long-gap scenarios (21) vs none" has **no reported result** in the evidence package (gap).

### Verdict
- **SUPPORTED:**
  - Deciding the model once per session was cheaper than re-deciding per turn (PREREG, 8–14%).
  - Changing effort mid-session rewrote the cache (12.9× writes within a turn, EXPL).
  - After a 7-minute idle gap every session rewrote its history anyway (5.8–6.2× first-request writes, measured), and an effort change at that point added no write cost (n = 24, EXPL).
- **QUALIFIED:** "Don't switch until the cache expires" is a design rule consistent with these measurements. It was not tested as a policy. Only 5-min TTL and 420 s gaps were exercised.
- **NOT SUPPORTED:** The "substantially cheaper" exception (no threshold measured); model switches at expiry; real think-time gap distributions; sessions > 16 turns (S2); 1-hour TTL; keep-alive's net value.
- **Safest strong phrasing:** "Choose model and effort once at session start. Switching either within a live cache rewrote the prompt cache (12.9× the cache writes after a mid-turn effort change), and a decide-once policy cost 8–14% less than re-deciding each turn (preregistered). When a session idles past the 5-minute cache lifetime, the next request rewrites the history whatever the configuration, so that is the cheap moment to change. We measured this for effort, not for model switches."

---

## Takeaway 4: "A decision model can serve as a customizable filter for risky actions (unlike a specialized classifier)"

### Evidence
- **Constructed CUA cases** (judge benchmark; 21 holdout and 30 dev computer-use cases; holdout has 29/63 cases tagged side-effect or injection; labels follow `LABELING-GUIDE.md`, "irreversible/external side effect ⇒ reason"). From the per-rep cua slices in `docs/evidence/2026-09-30-judge-benchmark/{holdout,dev}/summary.json`:

  | Judge, policy | Holdout cua (n = 21): wrong-auto / automatic / correct, per rep | Dev cua (n = 30) |
  |---|---|---|
  | Jev, shipped gate 0.90/0.20 | 0/10, 0/11, 0/10; correct 17–18 | 1–2 wrong per rep, all side-effect; correct 27 |
  | Jev, old CUA gate 0.75 (`bundle-cua`) | 2/15 per rep, both side-effect | 3 per rep |
  | Jev + I1 (natural-language side-effect clause) | 0 wrong; correct 20–21 | 0 wrong; 30/30 |
  | Luna (Responses), 0.90/0.20 | 2–3 wrong per rep → 0 with I2 | |
  | tev1 4B / nimble / Qwen3 8B | 3 / 3 / 6 wrong per rep → 0 / 0 / 2 with I2 | |

- **I1 (prompt clause = natural-language customization)** (`evals/judge_bench/INTERVENTIONS.md`; holdout `decisions.rule4_interventions`):
  - Confirmed only for Luna (targeted errors 4 → 2).
  - Not applicable to Jev on the holdout: 0 targeted errors at the 0.90 gate. Jev accuracy rose 55 → 59/63, Holm p 0.16.
  - Pooled I1 was **not confirmed** (22 → 20 targeted errors, 9%).
  - On dev (SCREEN), I1 removed all of Jev's side-effect errors.
- **I2 (deterministic host guard: regex of 17 verbs on the option label)**, PREREG: it removed every side-effect wrong-automatic decision for all 9 applicable judges on the holdout, with 0 accuracy change and 1.6–7.9 pts of coverage cost.
- **Example `cua-18`** ("Purchase the subscription"): every judge, Jev included (p 0.91), Luna (0.96–0.99) and Sol (0.98), clicked "Buy now" when the rule was unstated. Models follow the task unless the policy is stated.
- **Shipped `jev_cua`** (`src/amplifier_fast_decisions/jev_cua.py:124-136, 205-213`; `behaviors/jev-cua.yaml`):
  - The I1 clause is **hard-coded** in the instructions. The I2 regex is **hard-coded** and returns `side_effect_requires_confirmation`. The gate is 0.90/0.20 (was 0.75 until PR #56, commit 180f919).
  - `mount()` rejects any config key outside {backend, laya_url, allow_external_state, timeout_ms, min_probability, min_margin}. **There is no user-facing natural-language criteria knob.**
  - The tool is proposal-only and never executes. The host keeps approval and verification.
- **Live CUA runs** (`docs/JEV-CUA.md`; `docs/evidence/2026-09-29-cua/live-browser.json`; `docs/evidence/2026-09-29-forge/VERIFICATION.md`; `docs/evidence/2026-09-29-jev-default/cua.json`):
  - All were benign navigation: tab and report clicks.
  - Forge: a 3-click Chromium workflow, 2 reps per arm, 2/2 correct. 3 vs 9 generative calls, 23.82 vs 28.96 s. Descriptive, Playwright rather than a trycua VM.
  - **No live run involved a risky action.** The PR #56 commit message claims "side-effect goals now defer (operation p 0.67–0.78)", but no evidence artifact backs it.
- **Production:** 1 `cua_decided` event in the whole observatory store (Laya, unclassified traffic).
- **Specialized classifier comparison:** **none.** The only comparator is the deterministic keyword guard I2, and it outperformed the model-side natural-language clause on the targeted class.

### Verdict
- **SUPPORTED:** On 51 constructed computer-use decisions, Jev behind the shipped 0.90/0.20 gate made 0 wrong automatic actions on the 21 holdout cases. It made 1–2 per rep on the 30 dev cases, all side-effect actions, and handed 48–52% of holdout cases to the host. Adding a one-sentence natural-language risk rule removed Jev's dev side-effect errors (screen) and raised its holdout accuracy by 4 cases (not significant).
- **QUALIFIED:** The effective safety came from the **deterministic guard** (I2, preregistered, 9/9 judges) plus abstention. The clause alone was confirmed for 1 of 3 applicable arms. "Customization" was tested with one fixed clause, in one (more conservative) direction.
- **NOT SUPPORTED:**
  - Any comparison with a specialized classifier.
  - User customization of criteria. It is not exposed in config.
  - Customization that permits actions.
  - Live risky-action runs, real desktops, production CUA use, adversarial injection at scale. Labels are model-authored.
- **Safest strong phrasing:** "On constructed computer-use decisions, a decision model behind a strict confidence gate, combined with a deterministic side-effect guard, produced no wrong automatic actions on the holdout. The risk policy is plain text and can in principle be changed. Stating it changed model behaviour on our dev cases, but the guarantee came from the deterministic guard. We have not compared against a trained risk classifier or tested user-written policies."

---

## Takeaway 5: Telemetry from real usage

Source: `docs/evidence/2026-10-v3-offline/a1-observatory/` (README, `observatory-summary.json`, CSVs) and `a3-projection-inputs/`. All EXPL, measured counts.

- **Window:** 464,524 events in 4,470 files (1,597 session ids), 2026-09-17 to the 2026-10-05T17:00Z cutoff. The first week holds 171,609.
- **Traffic split:** production 398 sessions / 348,373 events (75%); test 1,136 / 115,505; unclassified 63.
  - **321 of the 398 "production" sessions are production by default** (`workspace_default`: not tagged test). Only 77 carried an explicit production tag.
  - It is one owner's workload. Bundle policy changed during the window (Jev default from 09-24; read shortcut disabled).
- **Event mix:** session heartbeats 49.0%, native-hook metadata 18.1%. Decision-bearing events are a thin slice.
- **Latency** (pooled production and test; `latency_by_backend.csv`):
  - Jev start-tier p50 159 ms, p95 311 (n = 248)
  - local Qwen3 0.6B shadow p50 48 ms, p95 93 (n = 993)
  - host provider call p50 4,828 ms, p95 26,920 (n = 16,012)
  - Jev is **30× faster at p50 and 87× at p95**, not "two orders of magnitude" as v3 says. Qwen is about 100×.
- **Shadow agreement decomposition:**
  - 7.1% overall (117/1,642, 6.0–8.5%).
  - 1,491 decisions (91%) were unmatchable by construction.
  - 648 came from a synthetic demo backend.
  - Real scorer where a match was possible: 117/151 = 77.5% (70.2–83.4%).
  - **Production 1/633 (0.2%) vs test 113/991 (11.4%).**
  - Jev never ran in shadow. Correctness cannot be identified because the store keeps no state text.
- **Production routing vs lab:**
  - First start-tier decision per production session (n = 214): scope gate kept the host in 105 (49%), Jev strong 68, Jev cheap 35, rules 6.
  - **Jev routed 34% of the production sessions it judged, vs 89% on main-v1 and 97% (113/117) of test sessions.**
  - Production read shortcut: 1 fast route; 11,955 requests went slow because the shortcut was disabled.
- **Claimed vs measured:**
  - Keep-alive receipts claimed $222.66 (194 receipts). One A/B measured $0.16, equal to its receipt. The aggregate was never measured.
  - Read shortcut "would have" avoided 117 turns / 998 s. Later measurement found no useful judge on real reads.
  - Per-step Sonnet receipts were −$1.80 (cost money). The replay estimated routing those steps would add $17–46. The lever is off.
- **Production host mix:** Opus 5.5 $632.66 (64 sessions), Sonnet 5 $545.06 (71), Haiku $7.85. **No Fable-hosted production sessions**, so the report's main saving (Fable) has no production exposure.
- **A3 projection 0.83× [0.80, 0.86]** (`a3-projection-inputs/README.md`) is labelled provisional and pre-S1. It assumed Opus medium effort ≈ 0.821–0.860, a prior that **S1 H4 refuted** (0.992, not supported). DERIVED post-S1 recompute on the same spend mix (Opus 53.4%, Sonnet 46.0%):
  - shipped defaults 1.00×
  - with the Sonnet-medium recipe (0.821) ≈ **0.92×** (0.90–0.94 using its CI)
  The GOAL target of ≤ 0.50× is not met.

### Verdict
- **SUPPORTED:** Decision calls are 30–100× faster than host calls. The headline agreement metric was mostly an artefact. Policy receipts were estimates, and two of them were later contradicted by measurement. Real usage looks different from the lab: the scope gate kept half of production sessions on the host, Jev routed a third as often as in the benchmark, effort switching almost never happened, and no production session ran on Fable.
- **QUALIFIED:** One user. Production is a residual class. Policies changed within the window. Latency is pooled across traffic classes.
- **NOT SUPPORTED:** Any decision-correctness or dollar-savings claim from telemetry. The 0.83× projection, which is invalid after S1.
- **Safest strong phrasing:** "One owner's 19 days of telemetry (398 production sessions) showed that decisions are fast (159 ms vs 4.8 s for a host call). It also showed that the lab overstated how often routing applies: the workspace-size gate kept half of real sessions on the host, Jev routed a third of the rest, effort was almost never switched, and none ran on the host where routing pays. Telemetry cannot tell whether a decision was right, and every 'saved' figure it recorded was an estimate."

---

## Bug inventory: v3 PDF (32 pages; `decision-models-v3.pdf`) and source

Page numbers are **PDF page / printed page**. The title page is unnumbered, so printed = PDF − 1. I rebuilt the PDF in /tmp from the committed sources (same byte size as committed, 0 overfull boxes).

### (a) Running header / title-page header
- **What renders, from text-layer coordinates.**
  - PDF p1 (title page, `titlepage` env, `main.tex:138-159`) has no header. It shows:
    - the title on 2 lines;
    - the subtitle "Telemetry, benchmarks and paired sessions, from curiosity to configuration", which **wraps with the single word "configuration" alone on line 2**;
    - the author row "Amplifier | Michael J. Jabbour | David Koleczek" with "Senior Applied Scientist" under Koleczek only;
    - "Microsoft, Office of the CTO" and "October 6, 2026 · report v3";
    - the abstract and the footer line "Technical report. Every number … build_assets.py; see Section A."
  - PDF p2 (printed "1", "The short version") opens with the fancyhdr header **directly under the title page**: left "What a fast decision model buys an AI agent", right "Report v3 · October 6, 2026", with a 0.3 pt rule (y ≈ 39–51 pt). The page heading "The short version" sits at y ≈ 78 pt. The title just shown therefore reappears as a ruled header bar over the first content page and the Contents page.
- `main.tex:34-37`: the same header appears on every page. `\fancypagestyle{plain}` is redefined but never triggered by `\section` in `article`.
- **Duplicate page anchor:** `titlepage` resets the page counter, so the title page and the short version are both page 1. The build log warns `pdfTeX warning (ext4): destination with the same identifier (name{page.1})`, so links to page 1 are ambiguous.
- **Metadata mismatch:** `pdftitle` = "… a week of telemetry, three benchmarks and a paired campaign" (`main.tex:120`). The displayed title and subtitle differ, and "a week" is wrong (the window is 19 days). With `pdfdisplaydoctitle=true`, viewers show the stale title.
- **Header date** "October 6, 2026" vs PDF CreationDate 2026-10-07. The 10-06 Decisions API evidence is included, so the build is from the 7th.
- `main.tex:1` has a stale comment title ("Measured, not estimated: what routing …").

### (b) Local and repo paths, file names and repo identifiers in body, captions and front matter
| PDF / printed page | Location | Text |
|---|---|---|
| 1 / – | title page footer | "generated from committed evidence files by `build_assets.py`" |
| 5 / 4 | §1 "How to read the evidence labels" | "companion technical report v2 (docs/papers/2026-10-02-paired-measurement/)" |
| 25 / 24 | §7 "Per harness" | "as in the repository README"; `npx skills add michaeljabbour/amplifier-bundle-fast-decisions` (repo slug) |
| 25 / 24 | §8 intro | "exactly as it ships in behaviors/fast-decisions.yaml" |
| 26 / 25 | §8 last para | "add the bundle as in the repository README" |
| 27 / 26 | §9.2 | "(docs/design/v3/PLAN.md)" |
| 28 / 27 | App. A | docs/papers/2026-10-02-paired-measurement/; docs/reviews/2026-10-paired-measurement/; docs/evidence/2026-10-v3-offline/; …/2026-09-30-judge-benchmark/; …/2026-10-01-trace-judge-benchmark/; …/2026-10-04-clef-judges/; …/2026-10-02-paired-campaign/; …/2026-10-05-effort-control/; …/2026-10-06-effort-control-fable/; …/2026-10-05-defaults-replay/; …/2026-10-06-holdout-v3/; evals/paired/PREREGISTRATION-holdout-v3.md; `make`, `make check`, `make FINAL=1` |
| 31 / 30 | App. D | docs/reviews/2026-10-paired-measurement/round3-independent-review-v3.md |

- Internal identifiers in the body (not paths, but repo jargon): `intent-kw-v1`, `allow_external_state`, `keep_on_host: [review, explain]`, freeze strings `always_route | strong default | scope off | keep none` (§5, Table 7), and scenario ids click-flow-explain, bleach-sanitize-review, go-bowling, peewee-filterfk.
- No `~/` or `/Users/` path appears in the PDF.

### (c) Other formatting and content bugs
1. **Double periods after every run-in `\paragraph`.** The titleformat appends "." (`main.tex:19`) and the sources also end the heading with "." There are about 28 instances: "How the story goes..", "Related work..", "Decisions are fast..", "The 7.1 % that was not what it seemed..", "Constructed cases..", "Real decisions..", "What it found..", "The effort confound..", "An artefact to avoid..", "The core study (S1) [preregistered]..", "What the freeze rule chose..", "What a user should set..", "Per harness..", every "Recipe: …..", "Honest limits..", "Companion technical report..", "Evidence used here..", "Reproducing this document..", and others.
2. **κ renders "0.51 − −0.57"** (PDF 8 / p7, §3 "Real decisions"). `$\kappa = \TrKappaOutcome$` with macro `0.51--0.57` in math mode (`sections/03-judges.tex:47`; `generated/jb/numbers.tex:2236`).
3. **"ln 0.580 =-0.544"** (PDF 18 / p17, worked example). `\WxLog` = `$-$0.544` nested in math breaks out of math, so a text hyphen renders with no spacing (`sections/05b-s1-detail.tex:35`).
4. **"(-dry-run prints the command instead)"** (PDF 26 / p25). `\code{--dry-run}` renders a single hyphen (`sections/06b-recipes.tex:42`).
5. **Model id broken across lines in the listing:** "--host-model claude-fable / -5-1" in the codex and copilot lines (PDF 26 / p25; `06b-recipes.tex:49-50`). The lines are too long and `breaklines` splits the id, so copy-paste yields a wrong command.
6. **Hyphenation breaks:**
   - a cross-reference: "(Sec- / tion 5)" in short-version item 4 (PDF 2 / p1)
   - a code identifier: "click- / flow-explain" (PDF 12 / p11 and PDF 24 / p23)
   - also "Decide- / once", "configura- / tions", "provenance- / limited" (Table 1 cell)
7. **"How to read it" notes are centred, not justified.** `\howtoread` sits inside `\centering` figures, so every note's last line is visibly centred (e.g. Figs 1–16).
8. **Fig. 2** labels only the p95 bars (93, 311, 26920). "26920" has no thousands separator, unlike the axis ("10,000") and the text ("26.9 s"). The caption claims "two orders of magnitude" when Jev vs host is 30× at p50 and 87× at p95.
9. **Inconsistent interval types:**
   - Table 4 header "cost ratio (95 % CI)" gives H2 1.000–1.022, H3 0.982–1.021 and H6 0.993–1.035.
   - The text and Table 1 give 90% CIs for the same hypotheses (1.000–1.019, 0.984–1.017, 0.996–1.032).
   - The equivalence tests use 90% intervals, but Table 4 does not say so.
10. **Number formats:**
    - Table 3 "0%" vs "89 %" (inconsistent thin space).
    - "0.56×" (2 dp) next to "0.558" and "0.581×" (3 dp).
    - "$18.41 per million" in the text vs "18.4" in Table 2.
    - "p = 0.16" vs "< 0.001".
11. **Cross-reference style:** "(Fig. 6)" vs "Figure 6" elsewhere (cleveref abbreviation). "see Section A" / "(Section A)" for an appendix (should read "Appendix A").
12. **Typo:** "five sessions studies" (PDF 27 / p26, §9.2; `07-limits.tex:18`).
13. **Section skeletons:** §6.4 and §6.5 are one sentence each. Their figures (Fig. 12, Fig. 13) float pages later, after §6.6's Table 5, so the subsections read as empty.
14. **Counts to verify:** Fig. 13 / Table 7 say 23 Fable and 23 Opus configurations. `holdout-v3/RESULT.md` says "Fable 24 rows, Opus 24 rows".
15. **Fig. 1 (timeline):**
    - Judge benchmark cost "$0.92" vs the judge-benchmark README "about $1.35 total API spend".
    - Clef's $0.21 is attached to "Real decisions" although it covered all four splits.
    - The OpenAI Decisions API stage ($0.08) is missing from the program figure.
16. **Content overstatements (wording to fix in v4):**
    - Abstract: Jev "the most accurate per dollar". This metric was never preregistered and does not survive Luna-D.
    - p7: Luna and Sol "slightly more accurate". The gap is 5–7/63 and the bootstrap CI excludes 0.
    - p7: real cases rebuilt "exactly as the in-session judge had seen them". They were fingerprint-matched and clipped to 2,048 chars.
    - Table 1: "Jev cheapest". True among priced cloud judges only.
    - §4, §9: Fable routing "saves" is quoted from S1 H1, which includes medium effort.
17. **Author block:** "Amplifier" (an AI system) is listed as first author with a Microsoft affiliation, and only one author has a title. Check venue and authorship policy.
18. **Paragraph heading macro:** "The core study (S1) [preregistered].." embeds the label macro in the run-in head (`05-plateau.tex:41`).
