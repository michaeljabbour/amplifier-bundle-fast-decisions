# Measured results

Every number quoted in `README.md` is recorded here with its provenance and
its limits. Nothing here is a production SLA.

## aider-polyglot screen (2026-09-20, one repetition)

40 aider-polyglot exercises, one repetition per exercise, one harness at a
time on the same machine, run under the protocol in
[evals/STUDY-DESIGN.md](../evals/STUDY-DESIGN.md) (section 3, suite S2).
"Working time" is the median per-exercise working time defined in section 6
of that document.

| Configuration | Passed | Median working time |
|---|---|---|
| Amplifier, plain (upstream loop) | 40/40 | 100 s |
| Amplifier + fast-decisions, local judge (`bundles/active.yaml`) | 40/40 | 51 s |
| Amplifier + fast-decisions, judge + routing (`bundles/active-routing.yaml`) | 40/40 | 26 s |
| Amplifier, plain, on `claude-sonnet-5` (control) | 39/40 | 128 s |
| Codex | 37/40 | 35 s |
| Claude Code | 35/40 | 28 s |
| OpenCode | 24/40 | 28 s |

The plain-on-sonnet control is what separates "routing and escalation helped"
from "the cheaper model was simply faster": the control is both slower and no
more correct than the routed configuration, so the gain is not attributable to
the model swap alone.

**Limits.** One repetition per exercise. This is a screen, not a
repetition-confirmed result: no confidence intervals, no repeated-measures
statistics, and each third-party harness ran on its own configured default
model on one machine. Repetition-confirmed results update
`bundles/active-routing.yaml` through `evals/apply_recommendation.py`; that
file's header records the subset that has landed so far. Each harness's own
startup time is included in its working time, and OpenCode cost is not
metered here (see [evals/STUDY-DESIGN.md](../evals/STUDY-DESIGN.md)
sections 9 and 10).

## Synthetic harness battery (2026-09-18)

20 prompts across 5 harnesses, including a paired same-model comparison
(time ratio 0.68 geometric mean, sign test p = 0.041, identical quality,
one repetition per task). Full tables, cost accounting and the measurement
corrections applied are in [BATTERY-2026-09-18.md](BATTERY-2026-09-18.md).

## Judge decision suites

Per-judge decision latency and agreement, measured on the checked-in decision
suites (`suites/v1.jsonl`, `suites/local-robustness.jsonl`) with
`afast bench suite --live --backend <backend>`. Agreement is the fraction of
suite cases whose selected candidate matches the labelled expectation; it is
not independent correctness (see [BENCH.md](BENCH.md)).

| Judge | Agreement | Decision latency (warm) |
|---|---|---|
| Ollama `qwen3:0.6b` | 0.75-0.80 | ~23 ms |
| Laya (typed-decision classifier) | 0.60-0.63 | ~10 ms |
| Apple MLX, Qwen3-0.6B 8-bit | 0.70-0.88 | ~105 ms |
| Jev (typesafe.ai) | 1.00 | ~190 ms with connection keep-alive |

One run per judge on one Apple Silicon machine. The Ollama warm p95 is also
recorded verbatim in [evidence/local-qwen3-06b.json](evidence/local-qwen3-06b.json)
(23.85 ms warm p95, 42 requests, 0 errors, suite `suites/v1.jsonl`), alongside
a `llama3.1:8b` comparison run. MLX being both slower and lower-agreement than
Ollama is what moved the `make-amplifier-faster` recipe's default judge host to
Ollama on every machine, including Apple Silicon (see the v1.2.0 entry in
[recipes/make-amplifier-faster.yaml](../recipes/make-amplifier-faster.yaml)).

Reproduce any local row:

```bash
afast bench suite --live --backend ollama --model qwen3:0.6b
afast bench suite --live --backend laya
```

`--backend jev --live` additionally requires `FAST_DECISIONS_LIVE=1` and
`TYPESAFE_API_KEY`, and sends bounded decision state off the machine --
read [PRIVACY.md](PRIVACY.md) first.

## Calibration gates: fit from data, not assumed

`min_probability`/`min_margin` (see `docs/MODEL-SETUP.md`) are currently
fixed defaults, not fitted thresholds. Independent Jev audits found
accuracy flat across roughly 0.50-0.95 reported confidence and
discriminative only at confidence >=0.99 on some workloads -- a shape a
single global threshold like `0.90` may not capture well.
`afast bench calibrate --receipts <events-dir-or-jsonl> --labels
<labels.jsonl>` (see `docs/BENCH.md`) turns judged-decision receipts into
an ECE report plus a coverage/accuracy gate curve at seven thresholds, so
the actual gate can be picked from that curve on your own judged data
rather than carried over unverified from this document.

## What these numbers do not establish

- Decision latency is backend scoring time, not whole-task speedup.
- Shadow agreement is not independent correctness.
- Tool calls eliminated, net cost savings and task-quality parity stay
  unmeasured until separately instrumented (see [EVENTS.md](EVENTS.md)).
- Live Jev accuracy and latency, Foundation loading, and your installed
  provider set must be measured on your own machine
  (see [COMPATIBILITY.md](COMPATIBILITY.md)).
