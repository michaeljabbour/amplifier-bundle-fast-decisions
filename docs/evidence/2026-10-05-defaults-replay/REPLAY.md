# Replay of the recorded main-v1 campaign through the shipped routing code

No model calls, no network, no scenario code. `evals/price_gate_replay.py` reads the recorded rows of
[`../2026-10-02-paired-campaign`](../2026-10-02-paired-campaign/README.md) (`data/sessions.jsonl`, `data/requests.jsonl.gz`,
`campaign/decisions.jsonl`) and drives the **real** decision code (`RoutedProvider` over a local `DemoProvider` stub) with the
policy parsed from the **shipped** `behaviors/fast-decisions.yaml`. Reproduce: `PYTHONPATH=src python3 evals/price_gate_replay.py all`
(also run by `tests/test_price_gate_replay.py`, under 10 s). Result: **PASS**. Ids and counts only; no prompts.

## 1. Constants re-derived from the data (`derive`)

| host | paired sticky-on-Sonnet pairs | derived request multiplier | shipped constant |
|---|---|---|---|
| claude-opus-5-5 | 124 | 1.3789 | 1.38 |
| claude-fable-5-1 | 124 | 1.1132 | 1.11 |

Reference request mix (pooled plain-host anchors, 280 sessions, 11,537 main requests; the
session token sums and the request rows agree): input 2.7, cache read 88,516,
cache write 5,376, output 541 tokens per request.

## 2. Wave replay (`replay`): 280 recorded waves, 3 scripted turns each

The stub judge answers `task_difficulty` with the wave's recorded sticky decision; the workspace file count is the recorded one.

| host | waves | result |
|---|---|---|
| Opus 5.5 | 140 | **140/140 not routed** (`price_gate_strong`, 0 judge calls, no request carries a `model` or `reasoning_effort`) |
| Fable 5.1 | 140 | **140/140 equal the recorded decision** (124 cheap, 16 host); judge asked once per wave (140/140); turns 2-3 reuse the session decision (140/140); cheap requests carry `claude-sonnet-5` at `medium` effort (140/140) |

Descriptive (not a pass criterion): mean tools-normalized session cost per recorded arm, all splits: Opus anchor $2.125, shipped (the previous default) $2.713, sticky $2.615; Fable anchor $5.311, shipped $3.557, sticky $3.331.
On Opus the new default keeps sessions on the host, so its expected cost is about the anchor's ($2.125, about 22% below the previous default's $2.713); this assumes the unrouted bundle adds no cost, which is **expected but not yet measured**.
On Fable the new default equals the recorded sticky arm ($3.331, about 6% below the previous default's $3.557).

## 3. Price sweep (`sweep`): is the gate sound across prices?

Re-priced every recorded Opus-host sticky and anchor session (test split, 46 cost-valid pairs) at each Opus cache-read price and compared the gate's decision with the measured geometric-mean ratio.
Gate break-even: $0.429/M. Pass criterion: wherever the gate routes, the measured ratio is below 1.0.

| Opus cache read, $/M | gate predicted | gate | measured sticky / anchor | sound |
|---|---|---|---|---|
| 0.20 | 1.366 | host | 1.203 | yes |
| 0.25 | 1.265 | host | 1.121 | yes |
| 0.30 | 1.178 | host | 1.051 | yes |
| 0.35 | 1.102 | host | 0.989 | yes |
| 0.38 | 1.061 | host | 0.956 | yes |
| 0.40 | 1.035 | host | 0.935 | yes |
| 0.43 | 0.999 | route | 0.905 | yes |
| 0.45 | 0.976 | route | 0.886 | yes |
| 0.50 | 0.923 | route | 0.842 | yes |

The measured column reproduces the paper's arm-reading break-even table (1.20 / 1.05 / 0.99 / 0.94), so the replay prices tokens the way the paper did.
The gate stays on the host between about $0.34 and $0.43/M although routing would save up to 10% there: it errs conservative on purpose.

## Not covered offline

Live cost of unrouted Opus sessions under the bundle; host-tier medium effort on judged-hard sessions; Opus effort response; delegated child sessions under
session scope. Candidates for the next preregistered campaign (cells `orch-session-gated`, `orch-session-gated-hostmed` in `evals/cells.yaml`).
