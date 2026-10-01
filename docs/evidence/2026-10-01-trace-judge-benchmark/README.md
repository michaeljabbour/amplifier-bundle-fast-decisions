# Real read-shortcut decisions: a trace-derived judge benchmark (2026-10-01)

Follow-up to [2026-09-30-judge-benchmark](../2026-09-30-judge-benchmark/README.md), answering David's review: the
constructed cases may be too easy and too synthetic, so test fewer, higher-fidelity cases taken from real agent
runs. API spend: $1.05 (dev $0.33, holdout $0.72). Companion study on caching:
[2026-10-01-caching](../2026-10-01-caching/README.md).

## Verdict

- **On real read-shortcut decisions, no judge met the preregistered usefulness bar** (at least 4 of the 13 reads
  that were enough, taken automatically, with a wrong-automatic upper bound below 10%). See `holdout/rule2_useful.json`.
- **Jev delivers the most savings but also the most extra reads.** It took 10 of the 13 sufficient reads
  automatically, and also took 5 reads that both reviewers judged unnecessary (12% of 42). GPT-6.1 Sol took 7 with 2
  unnecessary, at a 3.1-3.4 s median and about 57x Jev's cost. GPT-6 Luna matched Jev's 5 unnecessary reads with fewer
  useful ones.
- **Jev, Luna and Sol are within noise of one another** on accuracy and wrong-automatic rate (all Holm-adjusted
  p = 1.0). Jev stays the default under the preregistered rule; nothing replaced it.
- **Local judges split into two bad modes:** Laya, Qwen3 4B and tev1 0.8B never cleared the bundle's 0.90 gate (zero
  automation); nimble, Qwen3 0.6B and Qwen3 8B automated freely and were wrong 9-13 times.
- **Always falling back** would have scored 29/42 on accuracy with no savings. Accuracy alone is the wrong lens here:
  the question is how many sufficient reads a judge captures for each unnecessary one.
- **Severity differs from the constructed screens.** A wrong automatic decision here is an unnecessary read of a file:
  no side effect, one wasted step and some extra context. It is not a purchase or a deletion.

## Why these cases are hard

- They are real decision points, replayed byte-for-byte in each judge's own request form where one exists.
- In the SWE-bench sessions the bundle's 2,048-character state cut the task message before the GitHub issue, so the
  judge never saw the issue ([finding](../../../evals/judge_bench/traces/FINDING-state-budget-clips-task.md)).
- The host model's actual next read and a careful reviewer's judgement disagree often: reviewers overrode the
  outcome-derived label in 19 of 63 kept cases. None of Jev's unnecessary reads matched the host's actual next read.

## Dev (21 cases, 3 repetitions; screen)

| Judge | Accuracy (majority, 95% CI) | Rep range | Wrong automatic (95% CI) | Coverage | p50 / p95 | $ / 1M decisions |
|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | 15/21 (50–86%) | 14–15 | 3–3 per rep | 12–14 | 1162–1247 / 1880–2370 ms | $112.49 |
| gpt-6.1-sol | 17/21 (60–92%) | 16–17 | 1–2 per rep | 6–11 | 2781–3074 / 4232–5287 ms | $2,330.67 |
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
| gpt-6-luna | 23/42 (40–69%) | 19–25 | 4–8 per rep | 13–16 | 1263–1305 / 1928–1983 ms | $122.31 |
| gpt-6.1-sol | 25/42 (44–73%) | 24–25 | 1–2 per rep | 7–11 | 3143–3445 / 4562–6358 ms | $2,648.43 |
| jev-1.13 | 23/42 (40–69%) | 23–24 | 5–5 per rep | 15–15 | 147–169 / 220–254 ms | $46.10 |
| laya-base | 11/42 (15–41%) | 11–11 | 0–0 per rep | 0–0 | 53–64 / 55–68 ms | $0 |
| nimble-9b | 13/42 (19–46%) | 13–13 | 9–9 per rep | 18–18 | 465–492 / 551–577 ms | $0 |
| qwen3-0.6b | 19/42 (31–60%) | 19–19 | 9–9 per rep | 15–15 | 32–37 / 42–55 ms | $0 |
| qwen3-4b | 29/42 (54–81%) | 29–29 | 0–0 per rep | 0–0 | 137–157 / 221–262 ms | $0 |
| qwen3-8b | 21/42 (36–64%) | 21–21 | 13–13 per rep | 20–20 | 179–258 / 298–434 ms | $0 |
| tev1-0.8b | 25/42 (44–73%) | 25–25 | 0–0 per rep | 0–0 | 77–82 / 92–100 ms | $0 |
| tev1-4b | 23/42 (40–69%) | 23–23 | 3–3 per rep | 7–7 | 243–270 / 334–385 ms | $0 |

Wrong automatic decisions and coverage are per repetition; accuracy is the per-case majority over repetitions. Cost per
million decisions is higher than on the constructed screens because real states are longer (about 1,100 tokens).

## How the cases were built

1. **Mined** 927 distinct read-shortcut decision points from earlier benchmark sessions (SWE-bench Verified, the
   polyglot slice, the synthetic battery); rebuilt each request from the transcript and verified it against five
   logged state numbers plus candidate-id and order hashes (70/70 sampled cases match).
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
- `JevBackend` pointed at Ollama's System One endpoint cannot answer read-shortcut questions: object-valued criteria
  return HTTP 400.
- Escalation, phase and tool-risk decisions could not be turned into trace cases ([why](../../../evals/judge_bench/traces/EXCLUDED.md)).

## Limits

42 holdout cases: only large differences are detectable, and the 13 read-labeled cases make the savings endpoint coarse.
Labels are reviewer judgements of sufficiency from the judge's view, not ground truth; the host's own next action is kept
as a secondary label. All cases come from this bundle's own benchmark sessions (no human-driven traffic), and most
ran at a 2,048-character state budget. Reviewers are Anthropic models.

## Reproduce

```bash
set -a; . ~/.amplifier/keys.env; set +a
PYTHONPATH=src:. python3 evals/judges.py --split trace-holdout --reps 3 --budget-usd 3 \
  --arms jev-1.13 nimble-9b tev1-4b tev1-0.8b laya-base qwen3-0.6b qwen3-4b qwen3-8b gpt-6-luna gpt-6.1-sol openai-decisions
PYTHONPATH=src:. python3 evals/judges.py --replay docs/evidence/2026-10-01-trace-judge-benchmark/holdout/requests.jsonl --out /tmp/x
PYTHONPATH=src:. python3 evals/judge_bench/traces/rule2_useful.py docs/evidence/2026-10-01-trace-judge-benchmark/holdout
python3 evals/judge_bench/traces/build_pool.py   # rebuilds the case pool from local session logs
```
