# Bench: offline replay and the synthetic suite

`afast bench` is an **analysis** tool, not a second measurement system. It reads
JSONL the system already writes (`fast_decisions:*` events) or a checked-in
labelled suite, and computes pure functions of that data. Zero network unless
you explicitly opt a live backend in.

```
afast bench replay <events-dir-or-jsonl> [--session ID] [--out report.jsonl] [--md report.md] [--json]
afast bench suite  [<suite.jsonl>] [--backend deterministic|jev] [--live]
                   [--permutations K] [--domain tool-choice|read-target|model-role] [--out ...] [--md ...] [--json]
```

`--json` prints the record to stdout. It is the same record `--out` appends
(JSONL) -- there is one output shape, not two, because a future Amplifier
Smart Tool packaging of this service needs `--json` to already be the
canonical machine surface (see the design doc's "Smart-tool packaging
target").

## `afast bench replay`

Offline replay over recorded telemetry. Joins `requested` -> `scored` ->
`routed` -> `shadow_proposed` -> `shadow_agreement` / `role_agreement` by
`decision_id`.

**Input formats accepted (freely mixed within one file or directory):**

- A directory of `*.jsonl` files -- the bundle recorder's own layout
  (`events_dir`, e.g. `~/.amplifier/fast-decisions/events`, one file per
  session).
- A single JSONL file (e.g. `examples/demo-events.jsonl`), each line the
  bundle recorder's **flat** record: `{event, event_id, decision_id, seq,
  turn_id, session_id, data: {...payload...}, ...}`.
- A **kernel session directory** (`~/.amplifier/projects/*/sessions/<id>/`)
  or its `events.jsonl` directly. The kernel's own session logger wraps our
  flat record one level deeper, inside its own log envelope's `data` field:
  `{ts, lvl, schema, event, redaction, session_id, data: {data:
  {...payload...}, decision_id, event, event_id, monotonic_ns, parent_id,
  parent_session_id, schema_version, seq, synthetic, turn_id}}`.
  `load_events` detects this shape (a top-level `data` that is itself a
  dict carrying its own `event`/`event_id`) and unwraps it automatically --
  every other line in the same directory or file (recorder-flat, or a
  sibling non-`fast_decisions:*` file like `transcript.jsonl`) is read
  normally or skipped, never misclassified.

```bash
afast bench replay examples/demo-events.jsonl --json | python3 -m json.tool
afast bench replay ~/.amplifier/fast-decisions/events --md uat.md
afast bench replay ~/.amplifier/projects/<project>/sessions/<id>/ --json
```

## `afast bench suite`

Runs a small, checked-in, labelled decision suite (`suites/v1.jsonl`) against
a backend:

- `--backend deterministic` (the default): a fully offline, seeded, **order-
  sensitive** stand-in (`DeterministicSuiteBackend`). Hermetic -- no network,
  runs in CI. It is not an accuracy claim about Jev; it exists so the suite
  runner, permutation test, and metrics pipeline can be exercised without a
  network call.
- `--backend jev --live`: the real TypeSafe backend. Requires **both**
  `FAST_DECISIONS_LIVE=1` and `TYPESAFE_API_KEY` in the environment. Missing
  either falls back to the offline deterministic backend with a warning on
  stderr and exit code 0 -- it never silently fails, and never constructs a
  Jev client without both gates.
- **Refuses to run** (non-zero exit, no report written) if any case in the
  suite declares `"label_source": "model"` -- a model-derived label is never
  ground truth.

Every suite case: `{"id", "domain", "state", "candidates", "expected_choice",
"label_source", "tags"}`. `domain` is one of `tool-choice`, `read-target`,
`model-role`. Negative cases (`expected_choice: "reason"`, i.e. abstention is
correct) and trap cases (a plausible-looking candidate is wrong) are
required, not optional -- a suite without traps measures nothing.

### Permutation test (runs by default)

Independent research on the vendor's order sensitivity found that reversing
a candidate list or adding an irrelevant option measurably shifts the
returned probability. `bench suite` therefore scores every case under `k`
candidate orderings (`--permutations k`, default `4`; `1` disables it) and
reports:

- `order_agreement_stability`: fraction of items whose argmax (chosen
  candidate) is unchanged across all `k` orderings.
- `max_probability_swing`: the largest (max - min) probability of the
  *chosen* option for any single item across its `k` orderings.

A `max_probability_swing > 0.15` prints a prominent warning: at that
magnitude the thresholds are measuring candidate serialisation, not the task.
Only the canonical (as-declared, k=0) ordering feeds `agreement_rate`,
calibration, abstention, and per-domain numbers -- the other `k-1` orderings
feed only this diagnostic.

## Output shape

Both commands emit the **CLASSic-compatible record** (verified against
`michaeljabbour/amplifier-eval-taxonomies`,
`modules/hooks-eval-metrics/.../models.py`): top-level `session_id, model,
provider, start_time, end_time`, nested `cost`, `latency`, `security`,
`stability`, and `accuracy_proxy` (the taxonomy's own escape hatch for
non-ground-truth accuracy), plus one `decision` sub-block this bundle adds.
It joins the taxonomy's own JSONL on `session_id` -- no mapping layer.

### `decision` block

| Field | Meaning |
|---|---|
| `decision_latency_ms_p50` / `_p95` | From `scored.duration_ms` where `latency_kind == "decision_model_wall_time"`. Nearest-rank percentile; n=1 returns that value for any p, n=2 splits at the 50th percentile (documented, not interpolated). |
| `decision_cost_usd` | `sum(scored.input_tokens) x $0.042/1e6` (verified Jev pricing, output is $0). `null` when no usage was reported at all -- **never `0`**. For the suite's offline deterministic backend, usage is genuinely `0` (no real tokens spent), which is reported as `0`, not `null`. |
| `avoided_llm_turn_rate` | `would_have_avoided_llm_turn` count / total decisions. |
| `projected_task_latency_delta_ms` / `_cost_delta_usd` | **A model, not a measurement.** `projection_basis: "model"` and `projection_assumptions` (holds generation/tool time constant, avoided turns independent) are always present alongside the number. |
| `unsafe_autonomous_actions` | Count of `routed` events with `route == "fast"` whose destination is outside the default `allowed_tools` (`fast_workspace`). By construction (`DecisionService._eligible`) this must be `0`; non-zero is a release blocker, not a metric to trend. |
| `state_chars_p50/p95`, `state_size_vs_latency` | From the explicit `state_chars` field on `requested`, falling back to `shadow_proposed` for hook-only sessions that never call `DecisionService.choose` (paired with `scored.duration_ms` for the size-vs-latency series -- that pairing needs `scored`, so it stays empty for hook-only sessions). See "Telemetry fields this bench relies on" below for what emits it and the legacy fallback. |
| `shadow_snapshot_budget_exceeded`, `dropped_shadow_jobs` | From `fallback` events (reason code `shadow_snapshot_budget_exceeded`) and the `health` event's worker-health fields, respectively -- how an operator learns shadow is costing more than it admits. |

### `accuracy_proxy` block

| Field | Meaning |
|---|---|
| `calibration_ece` | Expected Calibration Error on the **chosen option's probability**, never on `confidence` -- a different statistic that happens to correlate with it. >=10 equal-width bins; each bin carries its own `n`; bins with `n < 30` are `"reliable": false` and excluded from the headline (reported separately under `ece_low_n_bins`). `mean_reported_confidence` is reported alongside, never substituted for it. |
| `per_domain` | Mandatory per domain (`tool-choice`, `read-target`, `model-role`) present in the data -- a pooled-only report is treated as a failure of the reporting, not an acceptable summary. For `suite`, domain comes directly from each case. For `replay`, domain comes from the explicit `domain` field recorded on the joined events (see below); each domain's entry carries `n_inferred` -- the count of decisions in that group whose domain had to fall back to the legacy heuristic, `0` for any recording made with the current telemetry. |
| `order_agreement_stability`, `max_probability_swing`, `permutations` | Suite-only (see above). `replay` reports `permutations: 1` and `null` for the other two -- a single already-recorded production trace has no alternate orderings to compare. |
| `agreement_with_deterministic` | `replay` reconstructs each decision's candidate set from the `requested` event and re-scores it with the offline `DeterministicSuiteBackend`, comparing its choice to what was actually recorded. This is a self-consistency check against a fixed, versioned scorer -- not a claim that the deterministic backend is "right". |

## Telemetry fields this bench relies on

Three small, privacy-safe fields (integers, a fixed label, a boolean --
never state text) make `state_chars_p50/p95`, `state_size_vs_latency`, and
`accuracy_proxy.per_domain` **measured from real telemetry** rather than
inferred. All three are documented in full in `docs/EVENTS.md` and are in
`privacy.SAFE_FIELDS`:

- **`domain`** (`tool-choice` | `read-target` | `model-role`) -- decided
  once, at the point a decision's candidate set is built, by
  `contracts.classify_domain`, and recorded on `requested`, `scored`,
  `routed` (once known), `shadow_proposed`, `shadow_agreement`,
  `role_proposed`, `role_agreement`. `bench replay` reads it directly off
  whichever joined event carries it (checked in that order).
- **`state_chars`** -- `len(canonical(state))` for the state actually sent
  to the backend, an integer never the state text itself. Recorded on
  `requested` (the main decision path) and `shadow_proposed` (the shadow
  path).
- **`allow_external_state`** -- the policy's own external-state opt-in, a
  boolean. Recorded on `turn_start`, and on the first `shadow_proposed`
  per `turn_id` (turn-level context, not repeated every decision).

**Legacy fallback, clearly labelled.** A recording made before this bundle
emitted `domain` has none of these fields. `bench replay` still classifies
such decisions with a documented heuristic (a decision with a
`role_agreement` event is `model-role`; a decision whose candidates/routed
destination are all `fast_workspace` is `read-target`; everything else is
`tool-choice`), and reports how many decisions in each domain group needed
that fallback via `per_domain[domain]["n_inferred"]`. `n_inferred == 0`
for every domain means the whole breakdown came from real telemetry, not
inference.

## The viewer's four bench additions

`afast serve` / `afast export` render, on top of the existing event stream
(no new backend endpoint):

1. **Decision list** -- one row per `decision_id`: proposed vs actual,
   agreement, probability, margin, latency, reason code. Toggle "mismatch
   first" to sort disagreements to the top.
2. **Reliability plot** -- 10 bins, stated probability (x) vs empirical
   correctness (y), diagonal drawn; low-n bins render lighter.
3. **Rung banner** -- mode, backend, policy version, and the **real**
   `allow_external_state` field from `turn_start` (no longer a backend-name
   guess).
4. **"What would have changed" counter** -- avoided LLM turns, and,
   **kept visually distinct**, mismatches that would have produced a
   *different action* (a different risk than a plain miss).

All four are computed client-side in `app.js` from the already-ingested
event stream; no control endpoint was added.

## Confidence and local robustness checks

Replay leaves `mean_reported_confidence` null when the formula is unspecified or
records mix backend/model/statistic identities. The individual provider values
remain in the trace. This summary is not an estimate of correctness. Legacy
records without statistic metadata cannot establish comparability. The synthetic
suite's single-backend summary is only a fixture statistic.

The local development probes cover option reversal, distractor insertion, duplicate
distractors, insufficient information, missing targets, negation, generation requests
and conflicting tool observations:

```bash
PYTHONPATH=src python scripts/bench_local.py \
  --suite suites/local-robustness.jsonl --repeats 3 --output /tmp/local-robustness.json
```

Requires the local extra and running Ollama. These are specification-derived public
fixtures authored during development, not independent human labels or a held-out
quality evaluation. Repeats are not independent examples. Labels and tags are never
sent to the model. Reported timing includes loopback scoring with a reused client;
CLI startup, target execution and full-task quality are outside this benchmark.
The runner records raw distributions, option fingerprints, probability shifts and
both argmax and policy order stability. Model revision remains null unless verified
separately; the model name alone does not pin its weights.
