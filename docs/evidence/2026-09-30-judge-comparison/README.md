# Judge comparison: quality, calibration, latency and cost

Measured September 30, 2026 on an Apple M5 Max (128 GB). [Interactive report](index.html).

Ten decision judges answered the same 90 frozen screening cases from the Laya study: the original 60
(`evals/laya_quality.fixtures`) and the fresh 30 (`evals/laya_holdout.cases`), with unchanged instructions and
labels. Each case was asked twice with the choice options reversed; tables score the first pass. Scoring is the
Laya study's own `score()`: a decision is automatic at probability ≥ 0.75 (a non-"reason" choice, or yes/no
certainty). This is **not the bundle's full policy**. Reproduce the run with
`PYTHONPATH=src:. python3 evals/judge_comparison.py --output <dir>` and the report with
`python3 evals/judge_report.py <dir>`.

| Judge | All 90 | Original 60 | Fresh 30 | Automatic | Wrong automatic | Brier | Order flips | p50 | p95 | $ / 1M decisions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-6 Luna* (OpenAI API) | 90/90 (100.0%) | 60/60 | 30/30 | 70 | 0 | 0.006 | 0 | 1192 ms | 2045 ms | $34.95 |
| GPT-6.1 Sol (OpenAI API, effort low) | 88/90 (97.8%) | 58/60 | 30/30 | 72 | 2 | 0.022 | 0 | 2478 ms | 3332 ms | $753.04 |
| Jev 1.13 (TypeSafe API) | 86/90 (95.6%) | 57/60 | 29/30 | 72 | 4 | 0.051 | 0 | 147 ms | 214 ms | $15.91 |
| Qwen3 8B (bundle OllamaBackend) | 77/90 (85.6%) | 51/60 | 26/30 | 71 | 11 | 0.135 | 0 | 218 ms | 249 ms | $0.00 |
| Qwen3 4B (bundle OllamaBackend) | 76/90 (84.4%) | 51/60 | 25/30 | 44 | 4 | 0.139 | 0 | 150 ms | 164 ms | $0.00 |
| nimble 9B (Ollama System One) | 74/90 (82.2%) | 48/60 | 26/30 | 71 | 12 | 0.147 | 3 | 157 ms | 170 ms | $0.00 |
| tev1 4B (Ollama System One) | 71/90 (78.9%) | 47/60 | 24/30 | 66 | 11 | 0.161 | 4 | 104 ms | 111 ms | $0.00 |
| tev1 0.8B (Ollama System One) | 67/90 (74.4%) | 42/60 | 25/30 | 39 | 5 | 0.160 | 8 | 38 ms | 43 ms | $0.00 |
| Laya base (local) | 54/90 (60.0%) | 35/60 | 19/30 | 34 | 12 | 0.294 | 14 | 21 ms | 27 ms | $0.00 |
| Qwen3 0.6B (bundle OllamaBackend) | 54/90 (60.0%) | 36/60 | 18/30 | 56 | 22 | 0.366 | 0 | 45 ms | 50 ms | $0.00 |

\* GPT-6 Luna is a stand-in for OpenAI's Decisions API (announced September 29, limited preview, built on GPT-6
Luna). The Decisions API has no public endpoint, model ID or schema, and this key cannot see it. Luna returns no
token probabilities, so it stated its probabilities in strict structured output (reasoning effort `none`).
Compare its accuracy and latency directly; treat its calibration and automatic-decision numbers with care.
GPT-6.1 Sol (added the same day, appended with `--append`; the other nine judges' results are unchanged) ran the
same way at reasoning effort `low`, its fastest setting (it has no `none`), priced at $2 input and $10 output per
million tokens ([developers.openai.com](https://developers.openai.com/api/docs/models/gpt-6.1-sol)).

## Findings

- **Jev remains the best default.** 95.6% correct (86/90), 147 ms median, about $16 per million decisions. Among judges with measured token probabilities, it is the only one that reaches **zero wrong automatic decisions at a 0.95 cutoff** while still deciding 41 of 90 cases on its own. Three of its four misses were side-effect actions it chose to take (purchase, delete, post) instead of deferring.
- **GPT-6 Luna was right on all 90 cases**, with no wrong automatic decisions at any cutoff. It was also **8× slower** than Jev (1.19 s median, 2.0 s p95; 3 of 90 exceeded Fast Decisions' 3 s timeout) and about 2.2× the price ($35 per million). Its confidence is self-reported because Luna returns no token probabilities. This is a stand-in: OpenAI's Decisions API is built on Luna and claims about 150 ms, but it is a limited preview with no public endpoint, so it could not be measured.
- **A stronger OpenAI model is not a better judge.** GPT-6.1 Sol scored 88/90, but both misses were side-effect actions it took with near-certainty (clicked "Buy now" at 0.98 and "Delete project" at 0.99), so no cutoff removes them. It was the slowest judge (2.48 s median, 17% over the 3 s timeout, at its fastest "low" effort) and by far the most expensive: about $753 per million decisions, 47× Jev and 21× Luna.
- **The best local judges reach 82–86%, not Jev's 96%.** Qwen3 8B 85.6% (218 ms), Qwen3 4B 84.4% (150 ms) and nimble 82.2% (157 ms), all free to run. The Qwen scores use the bundle backend's two calls per decision, averaging both option orders.
- **Local judges are overconfident.** Raising the cutoff does not make them safe: at 0.98 certainty Qwen3 8B still makes 8 wrong automatic decisions and nimble 3. Qwen3 4B is the most cautious good local judge (1 wrong at 0.95, but only 25 automatic).
- **tev1 0.8B is a credible fast tier.** 74.4% correct at 38 ms, and **zero wrong automatic decisions from a 0.85 cutoff**, although it then decides only 20 of 90 on its own. Qwen3 0.6B (60%, 22 wrong automatic) and Laya base (60%, 14 answers flipped by option order) are not usable judges here; Laya's score reproduces the earlier study exactly (35/60).
- **Every judge except Luna, including GPT-6.1 Sol, shares the same two failure modes:** acting on a side-effect action when it should defer (buy, delete, send, publish), and accepting code that does not do what was asked. That argues for **deterministic host guards on side-effect actions whatever judge is used**, as the Laya study recommended.
**Suggested routing (to validate on live traffic before adopting):** keep Jev as the default judge; use tev1 0.8B at a cutoff of 0.85 or higher only as an offline or no-network fallback; revisit GPT-6 Luna, or the Decisions API once it is public, for decisions where correctness matters more than speed. Treat these as screening results over 90 constructed cases, not production estimates.

## Threshold sweep (first pass, all 90): automatic decisions / wrong automatic decisions

| Judge | 0.75 | 0.85 | 0.90 | 0.95 | 0.98 |
|---|---:|---:|---:|---:|---:|
| Jev 1.13 | 72 / 4 | 67 / 4 | 63 / 2 | 41 / 0 | 14 / 0 |
| GPT-6 Luna* | 70 / 0 | 70 / 0 | 70 / 0 | 68 / 0 | 65 / 0 |
| GPT-6.1 Sol | 72 / 2 | 72 / 2 | 72 / 2 | 72 / 2 | 71 / 2 |
| nimble 9B | 71 / 12 | 67 / 9 | 65 / 8 | 62 / 6 | 46 / 3 |
| tev1 4B | 66 / 11 | 59 / 8 | 52 / 6 | 35 / 4 | 16 / 3 |
| tev1 0.8B | 39 / 5 | 20 / 0 | 11 / 0 | 3 / 0 | 1 / 0 |
| Qwen3 8B | 71 / 11 | 69 / 10 | 68 / 9 | 66 / 8 | 66 / 8 |
| Qwen3 4B | 44 / 4 | 34 / 3 | 30 / 3 | 25 / 1 | 9 / 1 |
| Qwen3 0.6B | 56 / 22 | 50 / 20 | 47 / 19 | 44 / 18 | 34 / 14 |
| Laya base | 34 / 12 | 16 / 7 | 2 / 1 | 0 / 0 | 0 / 0 |

## Protocol

- **System One payloads, byte-identical:** Jev (`https://api.typesafe.ai/v1/systemone`, model `jev-1.13.0`),
  nimble and tev1 through Ollama 0.35's local `/v1/systemone`, Laya base through the local `/v1/decide` server.
  Ollama's System One endpoint accepts only its decision models (nimble, tev1); it rejects general models.
- **Qwen3 through the bundle's production `OllamaBackend`,** which asks both option orders and averages them (two
  model calls per decision), so its order check is stable by construction. That backend drops any option named
  `reason` (its `SLOW` sentinel) and renormalizes the rest, which would stop a local model from choosing this
  screen's fallback. The harness disabled that rule so every judge answered the same three-way question.
  **Finding:** bundle questions that use a literal `reason` option cannot be answered correctly by the local
  backends.
- **Order and timing:** each judge ran as one contiguous block with two warmups excluded. A first attempt
  rotated judges per case, but Ollama keeps only three models resident, so it swapped models and inflated
  latency; that run was discarded.
- **Validation of the harness:** Laya base scored 35/60 on the original screen, exactly as in
  `docs/evidence/2026-09-29-laya-hosted`; Jev scored 57/60 here against 56/60 there.
- **Cost:** list prices on 2026-09-30. Jev $0.042 per million input tokens, output free
  ([docs.typesafe.ai/models](https://docs.typesafe.ai/models)). GPT-6 Luna $0.10 input and $0.50 output per
  million ([developers.openai.com](https://developers.openai.com/api/docs/models/gpt-6-luna)). Token counts come
  from each API's usage report (Jev about 380 input tokens per decision; Luna 219 input and 26 output). Local
  judges have no API charge; hardware, electricity and memory are not priced.

## Limits

Ninety constructed text decisions with hand-authored labels (not independently audited), 30 or fewer per task
type. These are screening results, not live browser tasks, tool executions, SWE-bench or production estimates.
Differences of a few cases are within noise. The screens were built before Jev and Laya were queried; nimble,
tev1, Qwen and Luna had not been run on them before, and no prompt was tuned for any judge. Local latency depends
on this machine and its concurrent load; cloud latency includes the network.

## Files

`manifest.json` (+ `.sha256`) frozen cases and prices · `requests.jsonl` every request and answer ·
`summary.json` aggregated metrics · `takeaways.html` findings shown in the report · `index.html` the report.
