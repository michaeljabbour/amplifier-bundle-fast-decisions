# Cloudflare Clef and Clef-Flash as judge arms (post-hoc)

> **Post-hoc status.** `clef` and `clef-flash` were not in the preregistration
> (`evals/judge_bench/holdout/PREREGISTRATION.md`, `evals/judge_bench/traces/PREREGISTRATION.md`). They were added on
> 2026-10-04, after the preregistered results were known. The holdout and trace-holdout rows below ran on the frozen
> cases and the unchanged scorer, but **no preregistered verdict applies to these two arms**; they are exploratory
> additions. Those runs carry `posthoc: true` in `run.json`, the summaries are labeled
> `post-hoc (arms added after the preregistration; cases and scorer unchanged)`, and the HTML reports show a banner.
> `jev-1.13` was re-run in the same invocation as the in-run reference so every comparison is paired in time. Its
> numbers here are that fresh run, not the committed 2026-09-30 / 2026-10-01 evidence.

## What was added

Clef and Clef-Flash are Cloudflare Workers AI decision models, called through
`POST https://api.cloudflare.com/client/v4/accounts/<account>/ai/run/@cf/cloudflare/{clef,clef-flash}` with the same
System One body Jev takes (`state`, `model`, `questions`). Per the task brief (not independently verified here): Clef
is built on a 27B Qwen3.8 base, Clef-Flash on a 9B Qwen3.5 base, both with a joint schema head. Workers AI bills
$0.24 per million input tokens for Clef and $0.09 for Clef-Flash, with no output charge (Jev: $0.042 per million input
tokens). The response is wrapped as `{result, success, errors}`.

Code and config changes (not committed; the author commits them):

- `evals/judge_bench/arms.py`: `SystemOneArm(envelope=True)` unwraps `result`; `success: false` or a non-empty `errors`
  makes the row invalid with Cloudflare's error text (also for HTTP 4xx bodies). Noul answers need no special case:
  the probability is already in `noul`. Auth and URL come from env var names in the arm spec (`token_env`,
  `account_env`, `{account}` in the URL template); no value is stored anywhere. Server timing is read from
  `x-processing-ms` / `server-timing` when present. Workers AI sends neither (only `cf-ai-neurons`), so latency is
  the client wall time, the same field the other arms use.
- `evals/judges.yaml`: arms `clef` and `clef-flash` (`native_form: systemone_body`, `local: false`, prices), and
  contrasts jev-1.13 vs each, and clef vs clef-flash. Nothing else changed.
- `evals/judges.py`: `--posthoc-arms` (below), `CLOUDFLARE_*` added to the secret scrubber.
- `evals/judge_bench/report.py`: the post-hoc banner (added after the runs; no numbers change).
- Tests: `tests/test_judge_workers_ai.py` (mocked envelope: choice, noul, error, HTTP error, native body, env-only
  secrets, the guard). `test_judge_replay.py` now also replays this directory. The existing judge tests pass
  unchanged apart from adding the two `CLOUDFLARE_*` names to their fake env.

### The holdout guard and `--posthoc-arms`

The default guard refuses to run a preregistered split when any of `evals/judge_bench/*.py`, `evals/judges.py` or
`evals/judges.yaml` differs from HEAD. Adding an arm necessarily edits `arms.py` and `judges.yaml`, so it refused
(by design). `--posthoc-arms` (holdout and trace-holdout only, needs `--arms`) keeps every other check and relaxes
only that one:

- PREREGISTRATION.md, the case files (`cases.json`; `pool.json` and `labels_final.json`) must be committed and
  unmodified, and the cases hash must equal the preregistered one;
- every `evals/judge_bench/*.py` except `arms.py` (scoring, cases, stats, summarize, decisions, native, ...) must be
  identical to HEAD, with no untracked additions;
- `judges.yaml` must equal HEAD's apart from added arms and contrasts (schema, defaults, budget, every existing arm
  spec and contrast compared); at least one selected arm must be new;
- `run.json` gets `posthoc: true` and, per invocation, `posthoc.new_arms` / `reference_arms`.

`judges.py` is also allowed to differ (it carries the flag); it contains the run loop and the relabel, not scoring.

## What was run

```
PYTHONPATH=src:. python3 evals/judges.py --split <split> --reps 3 --arms clef clef-flash jev-1.13 \
    --out ~/dev/afast-paired/judge-clef/<split> --budget-usd 2 [--posthoc-arms]   # holdout, trace-holdout
```

dev (90 cases), holdout (63), trace-dev (21), trace-holdout (42); 3 repetitions x 2 option orders, 2 excluded
warm-ups per arm block, concurrency 1 per process. The four splits ran as four processes at the same time, so the API
saw about four requests in flight (this applies equally to all three arms). Trace splits use each arm's native form:
the bundle's own `next_action` body (object-valued criteria); dev and holdout use the bench choice-question form.
Policy: `bundle-read-shortcut` (0.90 and 0.20 margin, 3 s timeout). Unit: per-case majority over the three
repetitions, every case in the denominator.

Spend: **$0.2129** of a $2 budget (dev $0.0473, holdout $0.0416, trace-dev $0.0398, trace-holdout $0.0842).
No invalid answers: 0 of 540 / 378 / 126 / 252 requests per arm on dev / holdout / trace-dev / trace-holdout, so no
error text to report. Every `summary.json` replays byte-for-byte from `requests.jsonl` (`judges.py --replay`).

## Results

All tables are produced by `tables.py` in this directory from the committed `manifest/run/requests/summary` files.
`$/1M decisions` is billed input tokens times the price in `judges.yaml`. The providers tokenize differently:
Clef counts about 0.55-0.8x the tokens Jev does for the same request, yet costs 3.2-4.4x per decision.
Latency is client wall time over all valid requests, pooled across repetitions, from a US East client (Cloudflare
`cf-ray` ...-EWR).

### dev (90 cases, 3 reps x 2 option orders, label: screen)

| arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions | mean in tokens |
|---|---|---|---|---|---|---|---|---|
| clef | 85/90 = 0.944 | 1/90 = 0.011 (Wilson upper 0.060) | 69/90 = 0.767 | 0/540 | 422 | 725 | 51.4 | 214 |
| clef-flash | 77/90 = 0.856 | 7/90 = 0.078 (Wilson upper 0.152) | 70/90 = 0.778 | 0/540 | 321 | 825 | 19.3 | 214 |
| jev-1.13 | 86/90 = 0.956 | 2/90 = 0.022 (Wilson upper 0.077) | 68/90 = 0.756 | 0/540 | 152 | 231 | 15.9 | 379 |

Paired contrasts (McNemar exact on per-case majority; Holm over the rule-1 family of the two new arms; diff = first minus second):

| contrast | metric | first | second | diff [95% CI] | first only / second only | p | Holm p |
|---|---|---|---|---|---|---|---|
| clef vs jev-1.13 | accuracy | 0.944 | 0.956 | -0.011 [-0.056, +0.022] | 1 / 2 | 1.000 | 1.000 |
| clef vs jev-1.13 | wrong automatic | 0.011 | 0.022 | -0.011 [-0.033, +0.000] | 0 / 1 | 1.000 | 1.000 |
| clef-flash vs jev-1.13 | accuracy | 0.856 | 0.956 | -0.100 [-0.167, -0.044] | 0 / 9 | 0.004 | 0.008 |
| clef-flash vs jev-1.13 | wrong automatic | 0.078 | 0.022 | +0.056 [+0.011, +0.111] | 5 / 0 | 0.062 | 0.125 |
| clef vs clef-flash | accuracy | 0.944 | 0.856 | +0.089 [+0.022, +0.156] | 9 / 1 | 0.021 | 0.043 (pairwise family) |

Rule-1 (replace Jev as default) checks, all against the preregistered thresholds:

| arm | non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|---|
| clef | False | True | none | False (725) | False ($51 vs $16) | True | False |
| clef-flash | False | False | none | False (825) | True ($19 vs $16) | True | False |

### holdout (63 cases, 3 reps x 2 option orders, label: post-hoc (arms added after the preregistration; cases and scorer unchanged))

| arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions | mean in tokens |
|---|---|---|---|---|---|---|---|---|
| clef | 57/63 = 0.905 | 3/63 = 0.048 (Wilson upper 0.131) | 46/63 = 0.730 | 0/378 | 391 | 722 | 65.2 | 272 |
| clef-flash | 50/63 = 0.794 | 6/63 = 0.095 (Wilson upper 0.193) | 46/63 = 0.730 | 0/378 | 328 | 665 | 24.5 | 272 |
| jev-1.13 | 56/63 = 0.889 | 1/63 = 0.016 (Wilson upper 0.085) | 40/63 = 0.635 | 0/378 | 169 | 231 | 18.4 | 438 |

Paired contrasts (McNemar exact on per-case majority; Holm over the rule-1 family of the two new arms; diff = first minus second):

| contrast | metric | first | second | diff [95% CI] | first only / second only | p | Holm p |
|---|---|---|---|---|---|---|---|
| clef vs jev-1.13 | accuracy | 0.905 | 0.889 | +0.016 [-0.032, +0.063] | 2 / 1 | 1.000 | 1.000 |
| clef vs jev-1.13 | wrong automatic | 0.048 | 0.016 | +0.032 [-0.032, +0.095] | 3 / 1 | 0.625 | 0.625 |
| clef-flash vs jev-1.13 | accuracy | 0.794 | 0.889 | -0.095 [-0.190, -0.016] | 1 / 7 | 0.070 | 0.141 |
| clef-flash vs jev-1.13 | wrong automatic | 0.095 | 0.016 | +0.079 [+0.000, +0.159] | 6 / 1 | 0.125 | 0.250 |
| clef vs clef-flash | accuracy | 0.905 | 0.794 | +0.111 [+0.048, +0.190] | 7 / 0 | 0.016 | 0.047 (pairwise family) |

Rule-1 (replace Jev as default) checks, all against the preregistered thresholds:

| arm | non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|---|
| clef | True | False | none | False (722) | False ($65 vs $18) | True | False |
| clef-flash | False | False | none | False (665) | True ($24 vs $18) | True | False |

### trace-dev (21 cases, 3 reps x 2 option orders, label: screen)

| arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions | mean in tokens |
|---|---|---|---|---|---|---|---|---|
| clef | 17/21 = 0.810 | 2/21 = 0.095 (Wilson upper 0.289) | 9/21 = 0.429 | 0/126 | 429 | 663 | 188.2 | 784 |
| clef-flash | 12/21 = 0.571 | 1/21 = 0.048 (Wilson upper 0.227) | 5/21 = 0.238 | 0/126 | 291 | 527 | 70.6 | 784 |
| jev-1.13 | 16/21 = 0.762 | 3/21 = 0.143 (Wilson upper 0.346) | 14/21 = 0.667 | 0/126 | 160 | 226 | 43.2 | 1028 |

Paired contrasts (McNemar exact on per-case majority; Holm over the rule-1 family of the two new arms; diff = first minus second):

| contrast | metric | first | second | diff [95% CI] | first only / second only | p | Holm p |
|---|---|---|---|---|---|---|---|
| clef vs jev-1.13 | accuracy | 0.810 | 0.762 | +0.048 [+0.000, +0.143] | 1 / 0 | 1.000 | 1.000 |
| clef vs jev-1.13 | wrong automatic | 0.095 | 0.143 | -0.048 [-0.143, +0.000] | 0 / 1 | 1.000 | 1.000 |
| clef-flash vs jev-1.13 | accuracy | 0.571 | 0.762 | -0.190 [-0.381, -0.048] | 0 / 4 | 0.125 | 0.250 |
| clef-flash vs jev-1.13 | wrong automatic | 0.048 | 0.143 | -0.095 [-0.238, +0.000] | 0 / 2 | 0.500 | 1.000 |
| clef vs clef-flash | accuracy | 0.810 | 0.571 | +0.238 [+0.048, +0.429] | 5 / 0 | 0.062 | 0.188 (pairwise family) |

Rule-1 (replace Jev as default) checks, all against the preregistered thresholds:

| arm | non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|---|
| clef | True | True | none | False (663) | False ($188 vs $43) | True | False |
| clef-flash | False | True | none | False (527) | True ($71 vs $43) | True | False |

### trace-holdout (42 cases, 3 reps x 2 option orders, label: post-hoc (arms added after the preregistration; cases and scorer unchanged))

| arm | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions | mean in tokens |
|---|---|---|---|---|---|---|---|---|
| clef | 26/42 = 0.619 | 2/42 = 0.048 (Wilson upper 0.158) | 6/42 = 0.143 | 0/252 | 418 | 738 | 203.4 | 847 |
| clef-flash | 21/42 = 0.500 | 3/42 = 0.071 (Wilson upper 0.190) | 6/42 = 0.143 | 0/252 | 337 | 600 | 76.3 | 847 |
| jev-1.13 | 26/42 = 0.619 | 5/42 = 0.119 (Wilson upper 0.250) | 15/42 = 0.357 | 0/252 | 169 | 252 | 46.1 | 1098 |

Paired contrasts (McNemar exact on per-case majority; Holm over the rule-1 family of the two new arms; diff = first minus second):

| contrast | metric | first | second | diff [95% CI] | first only / second only | p | Holm p |
|---|---|---|---|---|---|---|---|
| clef vs jev-1.13 | accuracy | 0.619 | 0.619 | +0.000 [-0.143, +0.143] | 4 / 4 | 1.000 | 1.000 |
| clef vs jev-1.13 | wrong automatic | 0.048 | 0.119 | -0.071 [-0.167, +0.000] | 0 / 3 | 0.250 | 0.500 |
| clef-flash vs jev-1.13 | accuracy | 0.500 | 0.619 | -0.119 [-0.262, +0.024] | 3 / 8 | 0.227 | 0.453 |
| clef-flash vs jev-1.13 | wrong automatic | 0.071 | 0.119 | -0.048 [-0.119, +0.000] | 0 / 2 | 0.500 | 0.500 |
| clef vs clef-flash | accuracy | 0.619 | 0.500 | +0.119 [-0.024, +0.262] | 8 / 3 | 0.227 | 0.680 (pairwise family) |

Rule-1 (replace Jev as default) checks, all against the preregistered thresholds:

| arm | non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|---|
| clef | False | True | none | False (738) | False ($203 vs $46) | True | False |
| clef-flash | False | True | none | False (600) | True ($76 vs $46) | True | False |


## Reading the results

- **Quality.** Clef (27B) is statistically indistinguishable from Jev on accuracy in all four splits (every Holm p
  = 1.0 on accuracy; diff within about +-0.05 on bench, 0.0 to +0.05 on traces). On the bench splits it is not worse
  at the automatic path either (wrong automatic 0.011 vs 0.022 on dev; 0.048 vs 0.016 on holdout, 3 vs 1 cases, p =
  0.625). On the traces it makes fewer wrong automatic reads (2 vs 3 and 2 vs 5), but at a small coverage (6/42 vs
  15/42 on trace-holdout), so it is simply abstaining more, and none of those differences is significant (Holm p
  0.5-1.0).
- **Clef-Flash (9B) is clearly weaker.** On dev it loses 9 cases to Jev and wins none (Holm p 0.008), and its wrong
  automatic rate is 0.078 vs 0.022. On holdout and the traces its accuracy deficit has the same sign but is not significant after Holm (p 0.14 to 0.45); its wrong-automatic rate is higher than Jev's on the bench splits and lower on the traces (it abstains on most trace cases), none significant.
  Clef beats Clef-Flash on accuracy on dev (p 0.043) and holdout (p 0.047, both after pairwise Holm).
- **Rule 1 (replace Jev as the default): neither arm qualifies on any split.** The binding failures are latency and
  cost, independent of accuracy: Clef p95 is 663-738 ms and Clef-Flash 527-825 ms against the 500 ms ceiling (Jev
  226-252 ms), and Clef costs 3.2-4.4x Jev per decision (limit 2x). Clef-Flash passes the cost limit (1.2-1.7x) but
  fails accuracy non-inferiority everywhere. Clef also misses the wrong-automatic non-inferiority bound on holdout
  (upper CI 0.095 against 0.03; 3 wrong automatic cases to Jev's 1).
  These checks are the preregistered rule applied descriptively; on the post-hoc rows they are not verdicts.
- **Latency.** Clef p50 is 391-429 ms (about 2.5x Jev) and Clef-Flash 291-337 ms (about 2x). Jev and Clef never reached the 3 s timeout (max 1.25 s). Clef-Flash did: 6 of 540 requests on dev, 3 of 378 on
  holdout, 1 of 252 on trace-holdout (slowest 24.9 s), none on trace-dev. They are valid answers that the bundle
  policy scores as `decision_timeout` fallbacks, so they count against Clef-Flash's accuracy; they are a tail
  risk the p95 does not show. Without server timing we cannot split network from compute.
- **Traces (rule 2, `rule2_useful.json`, `trace_analysis.json`).** No judge, Jev included, is "useful" on either
  trace split (needs at least 4 correct automatic reads and a Wilson upper bound under 0.10 on wrong automatic). On
  trace-holdout: Clef 4 correct automatic reads, 2 wrong (upper 0.158); Clef-Flash 3 and 3 (0.190); Jev 10 and 5
  (0.250). Jev's coverage on the reads is higher; Clef's wrong-automatic rate is lower; neither clears the bound.
  The post-hoc analysis sections a-g in `trace_analysis.json` are unplanned and change no verdict;
  Clef and Clef-Flash fall in the `other` family there (never an in-session judge).
- **Dev vs holdout.** Dev is labeled a screen in the benchmark; the holdout rows are the cleaner estimate, and for
  both arms they point the same way as dev.

## Files

```
dev/ holdout/ trace-dev/ trace-holdout/   manifest.json  run.json  requests.jsonl  summary.json
trace-dev/ trace-holdout/                 rule2_useful.json  trace_analysis.json   (rule2_useful.py --analysis)
index-bench.html   report for dev + holdout          index-trace.html   report for trace-dev + trace-holdout
tables.py          regenerates the tables above
```

Paths in `run.json` are shown with `~` for the home directory. The reports were built from this layout by staging
`dev`/`holdout` (or `trace-dev`/`trace-holdout` as `dev`/`holdout`) under one root, since `report.py` expects that
pair. The raw run directories live outside the repo in `~/dev/afast-paired/judge-clef/`.

## Verify

```
PYTHONPATH=src:. python3 -m unittest discover -s tests -p 'test_judge*.py'
PYTHONPATH=src:. python3 evals/judges.py --replay docs/evidence/2026-10-04-clef-judges/holdout/requests.jsonl --out /tmp/r
PYTHONPATH=src:. python3 docs/evidence/2026-10-04-clef-judges/tables.py docs/evidence/2026-10-04-clef-judges
```

Re-running the post-hoc holdout arms after `report.py` is edited will be refused by the guard until that edit is
committed (it is a frozen module under `--posthoc-arms`); the runs here predate that edit.
