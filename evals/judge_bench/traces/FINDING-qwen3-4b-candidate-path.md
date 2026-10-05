# Finding: `qwen3:4b` on the native candidate path answers `reason` with p = 1.0 on every case

Status: **open, not fixed** (documented only; `src/` untouched). Found 2026-10-01 in the trace-derived study
(`docs/evidence/2026-10-01-trace-judge-benchmark/`).

## What

On the bundle's Ollama candidate path (`OllamaBackend.ask` -> `ask_candidates`), `qwen3:4b` returns
`{reason: 1.0, every candidate: 0.0}` for every read-shortcut decision. It never automates anything, so the study
scores it as "safe" (0 wrong automatic) with accuracy equal to always falling back. That number says nothing about
the model's judgement: the model never gets to pick a letter.

## Evidence

- **Logged answers.** In the committed run logs every `qwen3-4b` request has `probabilities.reason == 1.0` exactly:
  holdout 252 of 252 requests (126 of 126 at order 0 = 42 cases x 3 repetitions) and dev 126 of 126 requests
  (`holdout/requests.jsonl`, `dev/requests.jsonl`). The same files give `qwen3-8b` a reason probability between
  5e-8 and 0.9999999 and `qwen3-0.6b` between 3e-6 and 0.97, i.e. letters were scored for both.
- **Live check (2026-10-01, local Ollama, same request bodies).** On `rt-003`, `rt-010` and `rt-013`, the top
  generated tokens of `qwen3:4b` were `We`, `First` and `Okay`: it starts a prose answer despite `think: false`.
  `qwen3:8b` on the same bodies put its mass on the option letters.

## Mechanism

1. The candidate request asks for exactly one generated token: `_prepare_request`
   (`src/amplifier_fast_decisions/local_backend.py:266-273`) sends `"think": False`, `"num_predict": 1`,
   `"top_logprobs": 20`, `"temperature": 0`, to `/api/generate`, with the prompt ending in
   `Z. None of the above / ask the reasoning model.` (`_build_label_prompt`, line 236).
2. `ask_candidates` (lines 336-371) posts that one body, requires `eval_count == 1` and no `thinking` field
   (line 360), and passes the response to `score_tokens`.
3. `score_tokens` (lines 170-202) adds the mass of tokens that are exactly an option letter
   (lines 190-191, "Exact single-letter tokens only" / `if token in labels`) and then sets
   `probabilities[SLOW] = max(0.0, 1.0 - sum(probabilities.values()))` (line 201). If the first token is `We`,
   no letter has any mass, so the whole probability goes to `reason`.
4. Nothing checks how much mass landed on letters. `ask_candidates` has no minimum-mass test and no second attempt.

## The question path has a fallback; the candidate path does not

The typed-question path (`_answer_once`, lines 296-334) first asks `/api/generate`, scores the first token with
`answer_from_top_logprobs`, and raises when the option letters hold less than `MIN_OPTION_MASS = 0.2`
(lines 60 and 117). `_answer_once` catches that (lines 313-316, "not an option letter: try the prefilled chat form") and
retries once on `/api/chat` with the assistant turn prefilled with `Answer:` (lines 317-334), which forces the next
token to be the letter.

`ask_candidates` does neither. There is no `MIN_OPTION_MASS` check (it calls `score_tokens`, not
`answer_from_top_logprobs`) and no `/api/chat` retry. The only other `/api/chat` call in the class is
`warmup` (line 377), which sends `"warm"` and discards the answer.

## Impact

- **Study:** `qwen3-4b` rows in the trace results (holdout accuracy 29/42, 0 wrong automatic, 0 coverage) are an
  artifact of the candidate path, not a finding about the model. The README's "Qwen3 4B never cleared the bundle's
  0.90 gate" is true but should not be read as caution on the model's part.
- **Bundle:** an operator who configures `qwen3:4b` (or any model that opens with prose despite `think: false`) for
  the read shortcut gets a judge that silently never fires. The question path would have recovered via the prefill.
  The failure is visible only as 0% automation.

## Not done

No change to `src/`. A fix would apply the question path's guard to the candidate path (reject below a letter-mass
floor and retry through `/api/chat` with an `Answer:` prefill). It would change what `qwen3:4b` scores here and needs
its own measurement; the preregistered holdout is not re-run for it.
