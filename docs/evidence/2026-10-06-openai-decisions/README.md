# OpenAI Decisions API (`gpt-6-luna`) as a judge arm (post-hoc)

> **Post-hoc status.** `luna-decisions` was not in the preregistration
> (`evals/judge_bench/holdout/PREREGISTRATION.md`, `evals/judge_bench/traces/PREREGISTRATION.md`). It was added on
> 2026-10-06, after the preregistered results were known. The holdout and trace-holdout rows ran on the frozen cases
> and the unchanged scorer, but **no preregistered verdict applies to this arm**; it is an exploratory addition.
> Those two runs carry `posthoc: true` in `run.json` and the summaries are labeled
> `post-hoc (arms added after the preregistration; cases and scorer unchanged)`. dev and trace-dev are the
> unfrozen screening splits (label `screen`). `jev-1.13` was re-run in the same invocation as the in-run reference,
> so every comparison is paired in time; its numbers are that fresh run, not the committed 2026-09-30 / 2026-10-01
> evidence.

## What was added

OpenAI's Decisions API: `POST https://api.openai.com/v1/decisions`, model `gpt-6-luna`, public beta. A request is
`{model, input, questions}`; each question is typed `predicate`, `choice` or `score`; the response carries one typed
answer per question (choice: per-value probabilities, a pick and a confidence). Billing is $0.10 per million input
tokens, nothing for output or cache. Request/response shapes were verified live before this work.

- `evals/judge_bench/arms.py`: `DecisionsApiArm` (adapter `openai-decisions`). Mapping: bench `noul` -> `predicate`
  (answer `{"type": "noul", "noul": probability}`); `choice` -> `choice` (criteria value -> description; an
  object-valued criterion is serialized as JSON text), answer probabilities returned as `{value: p}` in the request's
  criteria order so argmax ties resolve like every other arm; `score` -> `score` levels (supported and tested; no bench
  case uses it). The state string is sent as `input`. Nothing is synthesized: HTTP errors, transport errors,
  unmappable bodies (wrong answer type, probabilities not matching the choices) all raise and the runner records an
  invalid row with the message (billed usage is still charged). `usage.input_tokens` is billed; the
  `openai-processing-ms` header is stored as `timing.server_ms`; each call has a 30 s transport timeout
  (`call_timeout_ms`) so slow answers are recorded.
- `evals/judges.yaml`: arm `luna-decisions` (`local: false`, no native form, so trace splits run the adapted bench
  form), price 0.10 / 0.0, and contrast `[jev-1.13, luna-decisions]`. Nothing else changed (the legacy
  `openai-decisions` placeholder arm is untouched).
- `tests/test_judge_decisions_api.py`: mocked choice, predicate, score, object-valued criteria, HTTP error, mismatched
  choices with billed usage, config/pricing, and the 3 s deadline scoring. `test_judge_replay.py` now also replays this
  directory.

### The two deadline views

The transport timeout was 30 s, but the bundle's real deadline is 3 s. The primary policy (`bundle-read-shortcut`)
already scores any answer slower than 3000 ms as `decision_timeout` (a fallback, so not automatic). The tables show
that view ("3 s deadline", the primary one) and, from the same logged answers, a "no deadline" view. Accuracy is
identical in both; only coverage can differ. The no-deadline view is hypothetical: no judge ran without a deadline.

## What was run

```
PYTHONPATH=src:. python3 evals/judges.py --split <split> --reps 3 --arms luna-decisions jev-1.13 \
    --out ~/dev/afast-paired/judge-decisions/<split> --budget-usd 1 [--posthoc-arms]   # holdout, trace-holdout
```

dev (90 cases), holdout (63), trace-dev (21), trace-holdout (42); 3 repetitions x 2 option orders, 2 excluded warm-ups
per arm block, concurrency 1 per process, four splits as four simultaneous processes (about four requests in flight,
equally for both arms). Policy `bundle-read-shortcut` (0.90 and 0.20 margin, 3 s deadline). Unit: per-case majority
over the three repetitions, every case in the denominator, invalid rows counted as fallbacks.

Spend: **$0.0831** per the runner's budget meter (luna-decisions about $0.049 of OpenAI billing, the Jev reference
about $0.032, plus a $0.0002 smoke run). Every `summary.json` replays byte-for-byte from `requests.jsonl`
(`judges.py --replay`). `rule2.json` and `trace_analysis.json` in the trace directories come from
`evals/judge_bench/traces/rule2_useful.py --analysis`; the analysis sections are post-hoc.

## Results

Produced by `tables.py` in this directory (also written to `tables.md`, and `summary.json` for the paper).

### Headline (3 s deadline view, primary policy)

| split | arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| dev (screen) | luna-decisions | 88/90 = 0.978 | 0/90 = 0.000 | 64/90 = 0.711 | 4/540 | 1798 | 4796 | 20.3 |
| dev (screen) | jev-1.13 | 86/90 = 0.956 | 3/90 = 0.033 | 68/90 = 0.756 | 0/540 | 1460 | 4462 | 15.9 |
| holdout (post-hoc) | luna-decisions | 59/63 = 0.937 | 1/63 = 0.016 | 43/63 = 0.683 | 5/378 | 1473 | 3439 | 25.6 |
| holdout (post-hoc) | jev-1.13 | 55/63 = 0.873 | 1/63 = 0.016 | 40/63 = 0.635 | 1/378 | 1569 | 3730 | 18.4 |
| trace-dev (screen) | luna-decisions | 16/21 = 0.762 | 2/21 = 0.095 | 10/21 = 0.476 | 0/126 | 1679 | 3235 | 71.8 |
| trace-dev (screen) | jev-1.13 | 16/21 = 0.762 | 3/21 = 0.143 | 14/21 = 0.667 | 1/126 | 1404 | 4067 | 43.2 |
| trace-holdout (post-hoc) | luna-decisions | 30/42 = 0.714 | 1/42 = 0.024 | 7/42 = 0.167 | 0/252 | 1414 | 3002 | 76.3 |
| trace-holdout (post-hoc) | jev-1.13 | 23/42 = 0.548 | 5/42 = 0.119 | 15/42 = 0.357 | 2/252 | 1387 | 3436 | 46.1 |

Paired contrasts, luna-decisions minus jev-1.13 (McNemar exact on per-case majority; Holm over the rule-1 tests of
the split):

| split | metric | luna | jev | diff [95% CI] | luna only / jev only | p | Holm p |
|---|---|---|---|---|---|---|---|
| dev | accuracy | 0.978 | 0.956 | +0.022 [-0.022, +0.067] | 3 / 1 | 0.625 | 0.625 |
| dev | wrong automatic | 0.000 | 0.033 | -0.033 [-0.078, +0.000] | 0 / 3 | 0.250 | 0.250 |
| holdout | accuracy | 0.937 | 0.873 | +0.063 [-0.016, +0.159] | 6 / 2 | 0.289 | 0.289 |
| holdout | wrong automatic | 0.016 | 0.016 | +0.000 [-0.048, +0.048] | 1 / 1 | 1.000 | 1.000 |
| trace-dev | accuracy | 0.762 | 0.762 | +0.000 [-0.143, +0.143] | 1 / 1 | 1.000 | 1.000 |
| trace-dev | wrong automatic | 0.095 | 0.143 | -0.048 [-0.143, +0.000] | 0 / 1 | 1.000 | 1.000 |
| trace-holdout | accuracy | 0.714 | 0.548 | +0.167 [+0.048, +0.310] | 8 / 1 | 0.039 | 0.039 |
| trace-holdout | wrong automatic | 0.024 | 0.119 | -0.095 [-0.190, -0.024] | 0 / 4 | 0.125 | 0.125 |

Reading it: on accuracy the arm is at least as good as Jev everywhere, and ahead on trace-holdout (post-hoc, the
only contrast that clears p < 0.05 after Holm; this is exploratory, one split, no preregistered claim). Wrong
automatic decisions are lower or equal everywhere. The price is coverage: on the trace splits it hands far fewer
cases to the shortcut (7/42 vs 15/42 on trace-holdout; `rule2.json`: correct automatic reads 6 vs 10 of 13 read
cases, 8 vs 11 of 11 on trace-dev). Neither judge is "useful" under trace rule 2 on either trace split. Against
the rule-1 gates (informational here): the p95 <= 500 ms gate fails on every split and valid >= 98% fails on dev and
holdout (the invalid rows below); accuracy non-inferiority passes on dev, holdout and trace-holdout (not trace-dev,
n = 21), wrong-automatic non-inferiority passes on dev, trace-dev and trace-holdout (not holdout). Nothing replaces
the default.

### The "no deadline" view

Same answers, no 3 s deadline: luna-decisions coverage 65/90 (dev, +1 case), 44/63 (holdout, +1), unchanged on both
trace splits; jev-1.13 +1 case on dev only. Accuracy and wrong automatic are identical in both views. So the 3 s
deadline barely changes any conclusion here (full table in `tables.md`, `no_deadline_rows` in `summary.json`).

### Latency caveat (read before quoting any latency)

**Latency is client wall time measured from a Mac over the network against a public-beta endpoint, four processes at
once. It is not server time and it does not describe the service.**

- luna-decisions client wall time, pooled valid requests: p50 1.4-1.8 s, p95 3.0-4.8 s, max 25.7 s (dev). Share of
  valid requests over 3000 ms: dev 74/536 (14%), holdout 29/373 (8%), trace-dev 7/126 (6%), trace-holdout 13/252 (5%).
- Server-side processing time from the `openai-processing-ms` header: p50 59-62 ms, p95 136-179 ms, max 1064 ms. The
  server is about 25x faster than the client saw; the rest is network, TLS and queuing on this client.
- The same session measured `jev-1.13` at p50 1.39-1.57 s, against about 0.15-0.17 s in the 2026-10-04 clef runs from
  the same Mac. So this network path was slow in this session for both providers; the comparison between the two arms
  is paired in time, but absolute numbers are not comparable with earlier evidence. Jev sends no timing header.
- An earlier single-process probe showed 2.1-8.3 s per call (n=7) and the 6-call smoke run 1.0-2.4 s.

`summary.json` has the full distribution (min, p50, p90, p95, p99, max; server p50/p95/max) in `latency`.

### Invalid answers

luna-decisions: 9 of 1296 requests, all transport failures, none a parse or API error: 3 `ReadTimeout` at 30 s (dev
fresh-cua-03 rep 1, dev fresh-search-05 rep 3, holdout hold-cua-13 rep 3), 1 more `ReadTimeout` at 31.6 s (holdout
hold-cua-17 rep 2), 1 `ConnectTimeout` (holdout hold-cua-18), 3 `ReadError` at 17-27 s (dev select-16, dev
fresh-select-08, holdout hold-search-18) and 1 `RemoteProtocolError: Server disconnected without sending a response`
(holdout hold-cua-14). jev-1.13 had 4 of 1296 on the same network path (3 `ReadError`, 1 `ReadTimeout` at 60 s).
Full list with elapsed time in `summary.json` `invalid`. No retries were made; each is a fallback in the scoring.

## Files

`dev/`, `holdout/`, `trace-dev/`, `trace-holdout/`: `manifest.json`, `requests.jsonl`, `run.json`, `summary.json`
(the trace dirs also `rule2.json`, `trace_analysis.json`); `summary.json` (paper-facing, top level); `tables.py`,
`tables.md`. No key or token appears in any file (the runner scrubs error text; `grep -r "Bearer\|sk-"` is empty).
