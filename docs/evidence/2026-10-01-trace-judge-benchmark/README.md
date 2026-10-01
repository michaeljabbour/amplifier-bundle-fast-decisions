# Real read-shortcut decisions: a trace-derived judge benchmark (2026-10-01)

Follow-up to [2026-09-30-judge-benchmark](../2026-09-30-judge-benchmark/README.md), answering David's review: the
constructed cases may be too easy and too synthetic, so test fewer, higher-fidelity cases taken from real agent
runs. API spend: $1.07 (dev $0.33, holdout $0.72, adapter smoke test $0.02). Companion study on caching:
[2026-10-01-caching](../2026-10-01-caching/README.md).

## Verdict

**Scope first.** These are 42 real read-shortcut decisions that the in-session judge had *sent to the host model*
(a step must reach the host for its next action to provide a label). They are not a sample of all decisions: about
half are labeled "a read was enough" by design, against roughly 1 in 6 in the full pool.

- **No judge met the preregistered usefulness bar**: at least 4 of the 13 sufficient reads taken automatically, with
  a wrong-automatic Wilson upper bound below 10%, which at n = 42 means zero wrong. Every judge that took 4 or more
  reads also made at least one wrong automatic read. See `holdout/rule2_useful.json`.
- **Jev took the most sufficient reads (10 of 13)** and 5 reads that both reviewers judged not to be the right next
  step (12% of 42). Nimble, Qwen3 0.6B and Qwen3 8B made 9, 9 and 13 wrong automatic reads; GPT-6 Luna 5.
  GPT-6.1 Sol made 2 with 7 useful reads, but 72 of its 126 order-0 answers missed the 3 s timeout (median 3.1-3.4 s,
  about 57x Jev's cost); with no timeout the same answers would have taken 10 reads with 2 wrong (hypothetical).
- **Jev, Luna and Sol are within noise.** Jev-Luna and Luna-Sol: Holm-adjusted p = 1.0. Jev-Sol was missing from the
  run's contrast list; a post-hoc exact McNemar gives p = 0.63 (accuracy) and 0.25 (wrong automatic). Jev stays the
  default under the preregistered rule; nothing replaced it.
- **Local judges fail in two ways.** Laya and tev1 0.8B never cleared the 0.90 gate. Qwen3 4B is not a judgement at
  all: on the bundle's candidate path its first token is prose ("We ..."), so every answer becomes `reason` at p = 1.0
  ([finding](../../../evals/judge_bench/traces/FINDING-qwen3-4b-candidate-path.md)); it behaves as "always fall back".
  Nimble, Qwen3 0.6B and Qwen3 8B automate freely and are often wrong.
- **Always falling back scores 29/42**, but 21 of those 29 come from SWE-bench cases whose issue text the 2,048-character
  state budget hid; on the other tasks it scores 8/17. Accuracy alone is the wrong lens: the question is how many
  sufficient reads a judge captures for each unnecessary one.
- **A wrong automatic decision here is a read-only file read** (all offered candidates are reads) that replaces the
  host's next step. There is no irreversible side effect; the cost of one lost step and extra context is assumed, not
  measured.

## Read this before generalizing

- **Selection.** Jev made 0 wrong automatic reads on the 19 cases from its own sessions (cases its in-session self had
  already declined) and 5 on the 23 cases from other judges' sessions. Every case is one some judge declined.
- **Labels.** Reviewers overrode the host-derived label in 19 of 63 kept cases, leaning strict: of the 14 holdout
  overrides, 7 turned a read into `reason`, 1 turned `reason` into a read, and 6 swapped one read for another. Against the host's actual next read, Jev has 4 correct
  automatic reads and 11 wrong; Luna 4 and 9; Sol 4 and 5 (`holdout/trace_analysis.json`). None of Jev's 5 wrong
  automatic reads matched the host's next read. Reviewers saw the host's next actions; they were blind only to the
  proposed label and to judge answers.
- **Task clipping.** All 70 pool cases ran at a 2,048-character state budget (the bundle default is 12,000); in the
  25 SWE-bench holdout cases the judge saw the rules but not the issue
  ([finding](../../../evals/judge_bench/traces/FINDING-state-budget-clips-task.md)).
- **Clustering.** The 42 cases come from 25 task groups; Jev's 5 wrong reads fall in 4.
- **Erratum.** The preregistration says it was committed before any judge saw a trace case. A 3-case smoke test on
  `trace-dev` (rt-003, rt-028, rt-042; 9 arms incl. Jev, Luna, Sol; $0.02) ran about 2.5 minutes before that commit, to
  check the adapters. No holdout case was involved. The preregistration file is left unedited because the run guard
  pins it.
- **Deviation.** The trace preregistration widened rule 1's wrong-automatic margin to +0.05; the scorer's `decisions`
  block in `summary.json` still applies the earlier +0.03. The rule-1 outcome does not depend on it: no candidate was
  better than Jev on any primary endpoint (all Holm-adjusted p > 0.05), which rule 1 also requires.

## Dev (21 cases, 3 repetitions; screen)

| Judge | Accuracy (majority, 95% CI) | Rep range | Wrong automatic (95% CI) | Coverage | p50 / p95 | $ / 1M decisions |
|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | 15/21 (50–86%) | 14–15 | 3–3 per rep | 12–14 | 1162–1247 / 1880–2370 ms | $112.52 |
| gpt-6.1-sol | 17/21 (60–92%) | 16–17 | 1–2 per rep | 6–11 | 2781–3074 / 4232–5287 ms | $2,337.89 |
| jev-1.13 | 15/21 (50–86%) | 15–17 | 3–3 per rep | 13–14 | 148–164 / 206–217 ms | $43.18 |
| laya-base | 5/21 (11–45%) | 5–5 | 0–0 per rep | 0–0 | 44–45 / 46–49 ms | $0 |
| nimble-9b | 12/21 (37–76%) | 12–12 | 4–4 per rep | 15–15 | 407–422 / 471–491 ms | $0 |
| qwen3-0.6b | 12/21 (37–76%) | 12–12 | 4–4 per rep | 10–10 | 32–36 / 36–51 ms | $0 |
| qwen3-4b | 10/21 (28–68%) | 10–10 | 0–0 per rep | 0–0 | 102–106 / 165–175 ms | $0 |
| qwen3-8b | 13/21 (41–79%) | 13–13 | 4–4 per rep | 13–13 | 125–169 / 176–287 ms | $0 |
| tev1-0.8b | 11/21 (32–72%) | 11–11 | 0–0 per rep | 0–0 | 57–63 / 89–90 ms | $0 |
| tev1-4b | 16/21 (55–89%) | 16–16 | 1–1 per rep | 6–6 | 176–177 / 284–308 ms | $0 |

## Holdout (42 cases, preregistered, 3 repetitions)

Preregistered in [evals/judge_bench/traces/PREREGISTRATION.md](../../../evals/judge_bench/traces/PREREGISTRATION.md) (commit `1fe1d1b`, pushed before any judge saw a holdout case); run from clean commit `dc44ad7`. Every arm answered every case.

| Judge | Accuracy (majority, 95% CI) | Rep range | Wrong automatic (95% CI) | Coverage | p50 / p95 | $ / 1M decisions |
|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | 23/42 (40–69%) | 19–25 | 4–8 per rep | 13–16 | 1263–1305 / 1928–1983 ms | $122.34 |
| gpt-6.1-sol | 25/42 (44–73%) | 24–25 | 1–2 per rep | 7–11 | 3143–3445 / 4562–6358 ms | $2,637.32 |
| jev-1.13 | 23/42 (40–69%) | 23–24 | 5–5 per rep | 15–15 | 147–169 / 220–254 ms | $46.10 |
| laya-base | 11/42 (15–41%) | 11–11 | 0–0 per rep | 0–0 | 53–64 / 55–68 ms | $0 |
| nimble-9b | 13/42 (19–46%) | 13–13 | 9–9 per rep | 18–18 | 465–492 / 551–577 ms | $0 |
| qwen3-0.6b | 19/42 (31–60%) | 19–19 | 9–9 per rep | 15–15 | 32–37 / 42–55 ms | $0 |
| qwen3-4b | 29/42 (54–81%) | 29–29 | 0–0 per rep | 0–0 | 137–157 / 221–262 ms | $0 |
| qwen3-8b | 21/42 (36–64%) | 21–21 | 13–13 per rep | 20–20 | 179–258 / 298–434 ms | $0 |
| tev1-0.8b | 25/42 (44–73%) | 25–25 | 0–0 per rep | 0–0 | 77–82 / 92–100 ms | $0 |
| tev1-4b | 23/42 (40–69%) | 23–23 | 3–3 per rep | 7–7 | 243–270 / 334–385 ms | $0 |

Wrong automatic decisions and coverage are per repetition; accuracy is the per-case majority over repetitions. Cost per
million decisions is the mean over the three repetitions of each repetition's mean billed-token cost, and is higher
than on the constructed screens because real states are longer (about 1,100 tokens).

## How the cases were built

1. **Mined** 926 distinct host-routed read-shortcut decision points from earlier benchmark sessions (SWE-bench
   Verified, the polyglot slice, the synthetic battery); 226 steps the in-session judge automated were excluded because
   they have no host outcome. Each request was rebuilt from the transcript; a case was eligible only if the rebuild
   matched five logged state numbers plus the candidate-id and order hashes (18 decisions failed and were excluded).
   The wire bytes themselves were never logged, so this is a fingerprint match, not a capture.
2. **Drew** 70 (seed 20261001), stratified and hard-first on outcome-side features only, never on whether a logged
   judge was wrong; assigned whole tasks to holdout or dev before review.
3. **Labeled** blind by two reviewers who saw the judge's view and the host's next one or two actions, but not the
   outcome-derived label or any judge answer. Agreement with each other: Cohen's kappa 0.84; with the outcome label
   0.51-0.57. Kept 63 (reviewers agree); dropped 7. 29 of the 42 holdout labels are `reason`.
4. **Replayed natively:** Jev gets the bundle's System One `next_action` body; Laya and Qwen3 go through the bundle's
   own `LayaBackend` / `OllamaBackend` candidate code. GPT-6 Luna and Sol have no native form and get the bench choice
   shape, as do nimble and tev1, because Ollama 0.35's System One endpoint rejects the bundle's object-valued criteria
   (HTTP 400).

## Findings for the bundle (not fixed here)

- [State budget cuts the task](../../../evals/judge_bench/traces/FINDING-state-budget-clips-task.md): at 2,048 characters
  the judge saw SWE-bench rules but not the issue.
- [Escalation and phase judges see the wrong task text](../../../evals/judge_bench/traces/FINDING-judge-state-task-head.md):
  `_judge_state` takes the `<system-reminders>` block as the task (`orchestrator.py:517`). Neither judge has run in
  any logged session, so no measured result is affected.
- [Qwen3 4B never answers on the candidate path](../../../evals/judge_bench/traces/FINDING-qwen3-4b-candidate-path.md):
  its first token is prose, so `score_tokens` puts all mass on `reason` (126 of 126 holdout decisions). Its zero wrong
  automatic is an artifact, not caution.
- `JevBackend` pointed at Ollama's System One endpoint cannot answer read-shortcut questions: object-valued criteria
  return HTTP 400.
- Escalation, phase and tool-risk decisions could not be turned into trace cases ([why](../../../evals/judge_bench/traces/EXCLUDED.md)).

## Post-hoc analysis

`holdout/trace_analysis.json` (written by `rule2_useful.py --analysis`; chosen after the results were seen, not preregistered)
adds: counts against the host's actual next read, a split by suite, a selection-effect check by the in-session judge's
family, fallback reasons with a no-timeout counterfactual for Sol, Jev vs Sol and read-case paired tests, and clustering by
task. The preregistered rule-2 output is unchanged.

## Limits

42 holdout cases: only large differences are detectable, and the 13 read-labeled cases make the savings endpoint coarse.
Labels are reviewer judgements of sufficiency from the judge's view, not ground truth; the host's own next action is kept
as a secondary label. All cases come from this bundle's own benchmark sessions (no human-driven traffic), and all ran
at a 2,048-character state budget. Reviewers are Anthropic models.

## Reproduce

```bash
set -a; . ~/.amplifier/keys.env; set +a
PYTHONPATH=src:. python3 evals/judges.py --split trace-holdout --reps 3 --budget-usd 3 \
  --arms jev-1.13 nimble-9b tev1-4b tev1-0.8b laya-base qwen3-0.6b qwen3-4b qwen3-8b gpt-6-luna gpt-6.1-sol openai-decisions
PYTHONPATH=src:. python3 evals/judges.py --replay docs/evidence/2026-10-01-trace-judge-benchmark/holdout/requests.jsonl --out /tmp/x
PYTHONPATH=src:. python3 evals/judge_bench/traces/rule2_useful.py docs/evidence/2026-10-01-trace-judge-benchmark/holdout
python3 evals/judge_bench/traces/build_pool.py   # rebuilds the case pool from local session logs
```
