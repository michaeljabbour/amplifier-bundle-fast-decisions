# Microsoft Decision 1 (via OpenRouter) as a judge arm (post-hoc)

> **Post-hoc status.** `microsoft-decision-1` was not in the preregistration
> (`evals/judge_bench/holdout/PREREGISTRATION.md`, `evals/judge_bench/traces/PREREGISTRATION.md`). It was added on
> 2026-10-11, after the preregistered results were known. The holdout and trace-holdout runs used the frozen cases and
> the unchanged scorer, but **no preregistered verdict applies to this arm**; it is an exploratory addition. Those two
> runs carry `posthoc: true` in `run.json` and are labeled
> `post-hoc (arms added after the preregistration; cases and scorer unchanged)`. dev and trace-dev are the unfrozen
> screening splits (label `screen`). `jev-1.13` was re-run in the same invocations as the in-run reference, so every
> comparison here is paired in time; its numbers are that fresh run, not the committed 2026-09-30 / 2026-10-01 evidence.

## What it is

Microsoft Decision 1, a model released 2026-10-09, called through OpenRouter's alpha Decisions endpoint
(`POST https://openrouter.ai/api/alpha/decisions`, model `microsoft/microsoft-decision-1`; the responses name the
model `microsoft/microsoft-decision-1-20261009`). Per the provider's docs it is served by a single Azure provider.
Request: `{model, state, questions}` with the same System One question schema the bench already uses (`noul`,
`choice`, `score`), so the mapping is 1:1 (`OpenRouterDecisionsArm`, adapter `openrouter-decisions` in
`evals/judge_bench/arms.py`). Object-valued choice criteria are serialized to description text; bench `noul` questions
carry no criteria and none are sent. Responses carry one typed answer per question. The arm is billed at $0.042 per
1M input tokens, output free; OpenRouter's reported per-call cost is recorded beside the computed one.

## Method (identical to the Luna-Decisions run, `docs/evidence/2026-10-06-openai-decisions/`)

```
PYTHONPATH=src:. python3 evals/judges.py --split <split> --reps 3 --arms microsoft-decision-1 jev-1.13 \
    --concurrency 2 --out ~/dev/afast-paired/judge-msd1/<split> --budget-usd 1 \
    [--posthoc-arms --posthoc-base origin/main]    # holdout, trace-holdout
```

dev (90 cases), holdout (63), trace-dev (21), trace-holdout (42); 3 repetitions x 2 option orders, 2 excluded warm-ups
per arm block. Policy `bundle-read-shortcut` (0.90 and 0.20 margin, 3 s deadline). Unit: per-case majority over the
three repetitions, every case in the denominator, invalid rows counted as fallbacks. Four splits as four simultaneous
processes at `--concurrency 2` (at most 8 requests in flight; the Luna run used 1 per process, about 4 in flight).
Both arms ran in each process, sequentially. **No retries.** Every `summary.json` replays from `requests.jsonl`
(`judges.py --replay`). `run.json` files have the home directory shortened to `~`; the `manifest.json` files carry the
frozen case text as committed in `evals/judge_bench`, untouched.

Spend: $0.0506 per the runners' budget meters (dev $0.0111, holdout $0.0098, trace-dev $0.0096, trace-holdout
$0.0201), of which microsoft-decision-1 is $0.0168 (see Cost) and the Jev reference the rest, plus a smoke call of
about $0.000004.

## Results

Produced by `tables.py` (also `tables.md`, `summary.json`).

### Headline (3 s deadline view, primary policy)

| split | arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| dev (screen) | microsoft-decision-1 | 84/90 = 0.933 | 5/90 = 0.056 | 73/90 = 0.811 | 0/540 | 292 | 392 | 4.4 |
| dev (screen) | jev-1.13 | 85/90 = 0.944 | 3/90 = 0.033 | 69/90 = 0.767 | 0/540 | 232 | 284 | 15.9 |
| holdout (post-hoc) | microsoft-decision-1 | 57/63 = 0.905 | 5/63 = 0.079 | 49/63 = 0.778 | 0/378 | 292 | 356 | 6.9 |
| holdout (post-hoc) | jev-1.13 | 55/63 = 0.873 | 1/63 = 0.016 | 40/63 = 0.635 | 0/378 | 234 | 347 | 18.4 |
| trace-dev (screen) | microsoft-decision-1 | 16/21 = 0.762 | 4/21 = 0.190 | 15/21 = 0.714 | 0/126 | 316 | 551 | 29.8 |
| trace-dev (screen) | jev-1.13 | 16/21 = 0.762 | 3/21 = 0.143 | 14/21 = 0.667 | 0/126 | 239 | 523 | 43.2 |
| trace-holdout (post-hoc) | microsoft-decision-1 | 25/42 = 0.595 | 8/42 = 0.190 | 18/42 = 0.429 | 0/252 | 312 | 378 | 31.8 |
| trace-holdout (post-hoc) | jev-1.13 | 23/42 = 0.548 | 5/42 = 0.119 | 15/42 = 0.357 | 0/252 | 239 | 326 | 46.1 |

Paired contrasts, microsoft-decision-1 minus jev-1.13 (McNemar exact on per-case majority; Holm over the rule-1
tests of the split):

| split | metric | msd1 | jev | diff [95% CI] | msd1 only / jev only | p | Holm p |
|---|---|---|---|---|---|---|---|
| dev | accuracy | 0.933 | 0.944 | -0.011 [-0.067, +0.044] | 3 / 4 | 1.000 | 1.000 |
| dev | wrong automatic | 0.056 | 0.033 | +0.022 [-0.022, +0.067] | 3 / 1 | 0.625 | 0.625 |
| holdout | accuracy | 0.905 | 0.873 | +0.032 [-0.048, +0.111] | 4 / 2 | 0.688 | 0.688 |
| holdout | wrong automatic | 0.079 | 0.016 | +0.063 [+0.000, +0.143] | 5 / 1 | 0.219 | 0.219 |
| trace-dev | accuracy | 0.762 | 0.762 | +0.000 [+0.000, +0.000] | 0 / 0 | 1.000 | 1.000 |
| trace-dev | wrong automatic | 0.190 | 0.143 | +0.048 [+0.000, +0.143] | 1 / 0 | 1.000 | 1.000 |
| trace-holdout | accuracy | 0.595 | 0.548 | +0.048 [-0.071, +0.167] | 4 / 2 | 0.688 | 0.688 |
| trace-holdout | wrong automatic | 0.190 | 0.119 | +0.071 [+0.000, +0.167] | 3 / 0 | 0.250 | 0.250 |

Reading it: accuracy is statistically indistinguishable from Jev on all four splits (no contrast has p < 0.05, even
before Holm). The arm hands more cases to the shortcut than Jev on every split (coverage +4 to +14 points), and the
price is more wrong automatic decisions on every split (+2 to +7 points, none significant; the paired counts are 3/1,
5/1, 1/0, 3/0 for msd1-only / jev-only). Against the rule-1 gates (informational): p95 <= 500 ms passes on dev,
holdout and trace-holdout (trace-dev 551 ms); cost <= 2x Jev and valid >= 98% pass everywhere; accuracy
non-inferiority passes on holdout and trace-dev only; wrong-automatic non-inferiority (upper CI < 0.03) fails on every
split. Nothing replaces the default.

### Trace rule 2 (is the read shortcut useful with this judge?)

`rule2.json` in each trace directory (rule: at least 4 correct automatic reads and wrong-automatic Wilson upper 95%
below 0.10; `trace_analysis.json` holds the post-hoc analysis sections):

| split | arm | correct automatic reads | wrong automatic (Wilson upper) | useful |
|---|---|---|---|---|
| trace-dev | microsoft-decision-1 | 11 of 11 read cases | 4/21 (0.400) | no |
| trace-dev | jev-1.13 | 11 of 11 | 3/21 (0.346) | no |
| trace-holdout | microsoft-decision-1 | 10 of 13 | 8/42 (0.333) | no |
| trace-holdout | jev-1.13 | 10 of 13 | 5/42 (0.250) | no |

The read-case recall criterion is met by both (equal to Jev, and above luna-decisions on trace-holdout) but neither
judge is useful under rule 2 on either trace split, because the wrong-automatic bound is far above 0.10.

### Side by side with Luna-Decisions and earlier Jev runs

Different dates and network conditions: luna-decisions ran 2026-10-06 (four processes, 1 request in flight each),
this arm 2026-10-11 (four processes, 2 each). Each run has its own in-run Jev reference; compare each arm with its
own Jev, not across runs. Accuracy / wrong automatic / coverage, 3 s deadline view:

| split | msd1 (10-11) | jev (10-11) | luna-decisions (10-06) | jev (10-06) | jev (committed 09-30 / 10-01) |
|---|---|---|---|---|---|
| dev | 84 / 5 / 73 | 85 / 3 / 69 | 88 / 0 / 64 | 86 / 3 / 68 | 86 / 3 / 69 |
| holdout | 57 / 5 / 49 | 55 / 1 / 40 | 59 / 1 / 43 | 55 / 1 / 40 | 55 / 1 / 40 |
| trace-dev | 16 / 4 / 15 | 16 / 3 / 14 | 16 / 2 / 10 | 16 / 3 / 14 | 15 / 3 / 13 |
| trace-holdout | 25 / 8 / 18 | 23 / 5 / 15 | 30 / 1 / 7 | 23 / 5 / 15 | 23 / 5 / 15 |

(counts out of 90 / 63 / 21 / 42 cases). Jev's own numbers are stable across all three occasions (one case apart on
dev and trace-dev), so the relative read against Jev is fair. In that relative read, luna-decisions is the more
accurate and much more cautious judge (fewer wrong automatic decisions, far lower coverage; only it clears
p < 0.05, on trace-holdout accuracy), while microsoft-decision-1 is a bigger-coverage, Jev-like judge that is cheaper per
decision than both (see Cost) but makes more wrong automatic decisions than Jev. The two are not statistically
compared against each other here; both are contrasted with Jev only.

### The "no deadline" view

Every answer arrived within 3 s, so the 3 s-deadline and no-deadline views are identical on all four splits for both
arms (`no_deadline_rows` in `summary.json` equals `rows`).

### Latency caveat (read before quoting any latency)

**Latency is client wall time measured from one Mac over the network against an alpha endpoint, four processes at
once, at concurrency 2 each. It is not server time and it does not describe the service.**

- microsoft-decision-1, pooled valid requests: p50 292-316 ms, p95 356-551 ms, p99 529-941 ms, max 640-1374 ms. No
  request exceeded 3000 ms.
- jev-1.13 in the same invocations: p50 232-239 ms, p95 284-523 ms. So in this session the new arm was about 60-80 ms
  (about 25-30%) slower at the median than Jev, from the same Mac at the same time.
- Jev ran at p50 ~160 ms in the committed 2026-09-30 / 10-01 runs and ~1.4-1.6 s on 2026-10-06; absolute numbers
  across days are not comparable (network path and concurrency differ). Only the in-run pairing is a fair read.
- OpenRouter returns no processing-time header: the only timing-related header is `x-generation-id`, so `server_ms`
  is absent (`latency[].server_ms.n = 0`) and server time is unknown.
- Smoke call before the run: 200 in about 1.55 s (one cold call, 3 questions).

### Cost

At $0.042 per 1M input tokens, output free: computed and OpenRouter-reported cost agree to the displayed precision
on every split (the `cost` section of `summary.json`):

| split | requests | input tokens | computed USD | reported USD |
|---|---|---|---|---|
| dev | 540 | 56,784 | 0.002385 | 0.002385 |
| holdout | 378 | 62,535 | 0.002626 | 0.002626 |
| trace-dev | 126 | 89,520 | 0.003760 | 0.003760 |
| trace-holdout | 252 | 190,815 | 0.008014 | 0.008014 |

Total $0.0168 for 1,296 requests. $/1M decisions in the headline table is the runner's per-repetition figure
(`price_in` x tokens, 6 requests per case; mean input tokens per call are 105-757 for this arm versus 379-1098 for Jev
on these splits, and its cost per decision is below Jev's on every split).
Jev's own spend is not reported by its API (`reported_usd` null).

### Invalid answers and failures

0 of 1,296 requests invalid for microsoft-decision-1 and 0 of 1,296 for jev-1.13: no transport failures, API errors
or unparseable bodies, no account-routing block. (luna-decisions had 9 of 1,296 on its day, all transport timeouts.)

## What is NOT claimed

- No preregistered verdict, and no claim that this arm should replace or sit beside Jev. Rule-1 numbers are
  informational.
- No significant accuracy difference from Jev (accuracy p >= 0.688 on every split), and no direct statistical comparison with
  luna-decisions; the side-by-side table is descriptive across different days.
- Latency is one client's wall time over a particular network at one moment, with no server-side timing available. It
  says nothing about the service's own speed, load behavior or tail beyond this sample.
- Splits are small (21 and 42 trace cases): confidence intervals are wide; one case is 2.4-4.8 points.
- Cost is for the benchmark prompts at this price; the alpha endpoint's price or routing may change.
- Model behavior may change under the alias; the dated model id recorded is `microsoft/microsoft-decision-1-20261009`.

## Files

`dev/`, `holdout/`, `trace-dev/`, `trace-holdout/`: `manifest.json`, `requests.jsonl`, `run.json`,
`summary.json` (the trace dirs also `rule2.json`, `trace_analysis.json`); `summary.json` (paper-facing, top level);
`tables.py`, `tables.md`. No key or token appears in any file; per-row `timing.headers` holds `x-generation-id` only.
