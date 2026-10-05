# Preregistration: trace-derived read-shortcut holdout (2026-10-01)

cases_sha256: f6b186a170cb59d486a6953ade377695f92e248571f4f6a43bbd5add4fdc62df

Committed before any judge was asked any trace case in this study. `evals/judges.py --split trace-holdout`
refuses to run unless this file, `pool.json` and `labels_final.json` are committed and unmodified, the scorer
files are clean, and the hash above matches the final cases.

## Why this split exists

A reviewer (David) judged the constructed screens likely too easy and too synthetic, and asked for fewer cases
with higher fidelity, ideally taken from real agent trajectories. These cases are real read-shortcut decisions
from earlier fast-decisions benchmark sessions (SWE-bench Verified, the polyglot slice and the synthetic battery),
replayed in each judge's own request form.

## Cases and labels

- 70 decision points were drawn (seed 20261001), stratified by suite and hard-first on outcome-side features
  only (number of candidates, line-window candidates, dropped observations), never on whether a logged judge was
  wrong. Whole tasks were assigned to holdout or dev before review. Every payload was rebuilt from the session
  transcript and checked against five logged state numbers, the candidate ids and the order hash (70/70 match).
- Each case had an outcome-derived proposal (the host model's actual next read, else `reason`). Two blind
  reviewers labeled every case from the judge's view plus the host's next one or two actions, without the
  proposal or any judge answer. Reviewer agreement: 63/70 exact (Cohen's kappa 0.84); with the outcome proposal
  0.51-0.57.
- **Final label** = the reviewers' shared label (`agreed` when it matches the outcome proposal: 44; `adjudicated`
  when both override it: 19). The 7 cases where reviewers disagreed are dropped. **Holdout: 42 cases**
  (29 `reason`, 13 a read); dev: 21. The outcome label is kept for a secondary endpoint.
- Known property of the data, not a labeling choice: in the SWE-bench sessions the bundle's 2,048-character state
  clips the user message at about 746 characters, so the judge never sees the issue text. Many `reason` labels
  follow from that. This is what the judge really sees and is reported as a finding.

## Arms, forms, repetitions

The 10 base judge arms in `evals/judges.yaml`, 3 repetitions, both option orders (order 0 scored).
Native forms: Jev (System One `next_action` body), Laya base (`LayaBackend`), Qwen3 0.6B/4B/8B (`OllamaBackend`
candidate path). Adapted (bench choice shape): GPT-6 Luna, GPT-6.1 Sol (no native form), nimble 9B and tev1 4B/0.8B
(Ollama 0.35's System One endpoint rejects the bundle's object-valued criteria with HTTP 400). Side-effect-clause
arms are not run: no read decision here has a side effect. `openai-decisions` is probed and runs only on HTTP 200.

## Endpoints

Unit: order-0 answers, per-case majority over repetitions (ties to rep 1); policy `bundle-read-shortcut`, the gate
the bundle applies to exactly this decision (argmax; fallback on `reason`, p < 0.90, margin < 0.20, or > 3000 ms).

**Primary**
1. Wrong-automatic rate (all 42 cases).
2. Correct automatic decisions on the 13 cases whose label is a read: the savings a judge actually delivers.

**Secondary**: accuracy (against the always-fall-back reference, which scores 29/42 with zero automation);
coverage; agreement with the outcome label; p95 latency; USD per million decisions; failure classes.

## Contrasts and decision rules

Statistics as in `evals/judge_bench/holdout/PREREGISTRATION.md` (exact McNemar, Holm within each endpoint family,
Wilson and paired-bootstrap intervals). Contrasts: Jev vs every other arm; GPT-6 Luna vs GPT-6.1 Sol.

1. **Default judge** (unchanged rule): Jev stays the default unless a candidate is non-inferior on wrong-automatic
   rate (upper 95% bound of candidate - Jev < +0.05, widened from 0.03 because n = 42) and on accuracy
   (lower bound > -0.05), better on a primary endpoint with Holm p <= 0.05, p95 <= 500 ms, <= 2x Jev's cost, and
   >= 98% valid answers per repetition.
2. **Is the read shortcut worth running on real traffic?** Reported per judge, not a default change: a judge is
   "useful here" if it makes at least 4 correct automatic reads (of 13) with a wrong-automatic upper 95% bound
   below 0.10. If no judge meets this, the finding is that the read shortcut, as configured, saves little on these
   sessions.
3. Everything on `trace-dev` is a screen.

## Budget

$3.00 (`--budget-usd 3`). Case text is from public benchmark repositories.
