# Policy configuration reference

Every key `Policy.from_config(config: dict)` accepts (`amplifier_fast_decisions/contracts.py::Policy`),
in one place. `from_config` silently ignores unrecognized keys (it filters
by `cls.__dataclass_fields__`); a typo in a key name here is a silent
no-op, not an error -- double-check spelling against this table. Keys
inside a nested dict (`effort_routing`, `model_routing`, `confidence_gates`)
ARE validated and DO raise `ValueError` on an unknown sub-key or an
out-of-range value (see `contracts.validate_effort_routing`,
`validate_model_routing`, `validate_confidence_gates`).

## Library default vs shipped default

Two layers of defaults exist. A key **absent** from `Policy` config takes the *library default* in the tables below
(mostly "off", so existing configs behave as before). `behaviors/fast-decisions.yaml` and
`behaviors/fast-decisions-registry.yaml` (the shipped behavior you get by composing the bundle) *set* several keys
explicitly. The research-backed shipped defaults are:

| Setting | Library default (key absent) | Shipped default |
|---|---|---|
| `model_routing.price_gate` | off (legacy: route whenever the start model's list price is lower) | `{enabled: true}` |
| `model_routing.decision_scope` | `turn` (decide at every turn) | `session` (decide once, reuse) |
| `effort_routing.by_tier.cheap` | unset | `medium` |
| `effort_routing.by_tier.strong` (host effort) | unset | `null` (provider default; opt-in `medium`) |
| `model_routing.keep_on_host` | off | off (commented example) |
| `read_shortcut` | `True` | `false` |
| `backend` | none | `jev` |

Evidence: the paired campaign ([README](evidence/2026-10-02-paired-campaign/README.md),
[confirmatory results](evidence/2026-10-02-paired-campaign/confirm/CONFIRM.md)), the
[paper](papers/2026-10-02-paired-measurement/README.md), and the offline [replay of the recorded campaign through the
shipped code](evidence/2026-10-05-defaults-replay/REPLAY.md).

## Top-level keys

Backend construction is separate from `Policy`. The optional `backend: anyjev`
accepts `model` (required served identity), `anyjev_url` (literal loopback HTTP,
default `http://127.0.0.1:8091`), and `anyjev_level` (`L2` by default; `L0` is
refused in active mode). It uses `timeout_ms` and supports fixed choice/noul
questions only; keep the read shortcut off. See [AnyJev setup](ANYJEV.md).

| Key | Default | Meaning |
|---|---|---|
| `mode` | `"shadow"` | `"off"` / `"shadow"` / `"active"`. Only `"active"` can submit a fast-path candidate; `"shadow"` scores but always routes slow. |
| `timeout_ms` | `750` | Single cooperative deadline covering candidate collection, backend inference, and revalidation for one decision. Also the deadline HC05's judge asks (and HC08's batched ask) are bounded by. |
| `min_probability` | `0.90` | Legacy alias for `confidence_gates["read_shortcut"]` (HC09) -- still the default source when that key is absent. |
| `min_margin` | `0.20` | Minimum gap between the selected candidate's probability and the next-highest alternative. Independent of HC09's gates; always enforced alongside them. |
| `max_fast_streak` | `3` | Consecutive fast submissions allowed before forcing a slow route. |
| `max_fast_per_turn` | `12` | Total fast submissions allowed in one turn. |
| `max_candidates` | `12` | Candidates considered per decision (1..63). |
| `max_questions` | `8` | Contributed judgment questions considered per decision (0..64). |
| `max_task_chars` | `2000` | Most characters of the task message kept in the state (256..100000); a longer task keeps its head and tail (tail larger) joined by an omission marker, and injected `<system-reminder(s)>` envelopes are dropped first. |
| `max_state_chars` | `12000` | Canonical-JSON size budget for the state sent to the backend (512..100000). Also bounds HC05's judge state (`orchestrator._judge_state`). |
| `allow_external_state` | `False` (env override: `FAST_DECISIONS_ALLOW_EXTERNAL_STATE`) | Required, alongside an external backend (`backend.external == True`, e.g. Jev), before ANY external call is attempted -- read-shortcut, HC05 judge asks, and HC08 batched asks all honor this identical gate. |
| `allow_synthetic_active` | `False` | Whether an explicitly synthetic backend result (`synthetic=True`, e.g. `ScriptedBackend`) may be submitted in `active` mode. |
| `allowed_tools` | `("fast_workspace",)` | Tools a prepared candidate may target. |
| `shadow_max_messages` | `12` | Messages read for a shadow snapshot. |
| `shadow_snapshot_budget_ms` | `25` | Wall-clock budget for the shadow snapshot (1..5000). |
| `suppress_completed_reads` | `True` | HC02a: drop `fast_workspace` read/list candidates whose `(path, revision)` this turn already read. |
| `read_shortcut` | `True` (library); `false` in the shipped behavior | Judged read shortcut: ask the backend for a prepared read before slow requests. Off in the shipped behavior: it rarely fired in the studies and would put a scoring call in front of every slow request. |
| `effort_routing` | `None` | HC03/HC05, opt-in. See below. |
| `model_routing` | `None` | HC04/HC05, opt-in. See below. |
| `decision_batching` | `False` | HC08, opt-in. Combine the HC05 phase-judge and escalation-judge asks into one `ask_many()` call whenever both are due for the same request. No effect when fewer than two judge mechanisms are configured. |
| `confidence_gates` | `None` | HC09, opt-in. See below. |
| `tool_risk_shadow` | `False` | HC11, opt-in. Ask a batched destructive/touches_production/category classification BEFORE each tool call and record a `fast_decisions:tool_risk` receipt. Never blocks, modifies, or approves anything -- native approvals remain authoritative. |
| `delegation_routing` | `None` | Per-delegation model routing (opt-in). See below. |
| `version` | `"policy-v1"` | Recorded verbatim on every receipt (`policy_version`). Not validated against a known set. |

## `effort_routing` (HC03/HC05, opt-in; `None`/`{}` = off)

| Key | Default | Meaning |
|---|---|---|
| `orient` / `explore` / `implement` | unset (no override for that phase) | One of `low` / `medium` / `high` / `xhigh` / `max`. |
| `max_explore_requests` | unset | Positive int; escalates effort after this many explore-phase requests. |
| `escalate_after_provider_errors` | unset | Positive int. |
| `by_tier` | unset | `{cheap: <effort|null|"phase">, strong: <...>}`: one effort per start tier for the whole session/turn (requires `model_routing.start_policy`). `null` = provider default; `"phase"` = keep per-phase efforts. Shipped: `{cheap: medium, strong: null}`. `strong` is the **host-model effort** (see "Host effort" below). |
| `monotonic` | `False` | Never lower the effort within a turn once raised. |
| `phase_judge` | `False` | HC05: ask the configured `DecisionBackend` to classify the phase instead of trusting `effort.classify_phase` alone. A non-null, gate-passing answer overrides the deterministic phase for the rest of this request. Gated by `confidence_gates["phase"]` (HC09; default gate `0.0` -- byte-identical to pre-HC09 "any non-abstain answer applies"). |

### Host effort (opt-in)

`effort_routing.by_tier.strong` is the effort sent on every request that runs on the host model: sessions judged hard
(or kept on the host by the price gate), turns escalated to the host, and nothing for a model the user picked
(a picked model runs at its own effort). Shipped value: `null` (provider default). To opt in:

```yaml
effort_routing:
  by_tier:
    cheap: medium
    strong: medium     # host-model effort, opt-in
```

Evidence, by host:

- **Cheap tier (Sonnet 5):** `cheap: medium` is shipped. Plain Sonnet at medium cost 0.821x its default effort with
  non-inferior turn-pass ([effort-control](evidence/2026-10-05-effort-control/RESULT.md)).
- **Fable 5.1 host:** plain Fable at `medium` cost **0.860x** the default effort (95% CI 0.833-0.885), turn-pass
  **+0.033** (non-inferior), 23 test-split scenarios, 46 pairs, preregistered
  (`docs/evidence/2026-10-06-effort-control-fable/RESULT.md`, branch `eval/effort-control-fable`, PR #61). Medium alone
  did not reach the routing saving: medium Fable cost 1.546x the sticky-routed sessions on the same host (descriptive).
- **Opus 5.5 host:** unmeasured. Do not assume the Fable number transfers.

Why it is off by default: the sessions it would touch are the ones the judge called *hard* (16/140 Fable sessions, but
~32% of sticky spend), and the Fable test covered all 23 scenarios, not the judged-hard subset (it contains 2 explain,
2 review and 0 docs scenarios; the main campaign hints at a turn-pass loss at medium on docs/explain/review work, -0.066,
post hoc and confounded). The expected extra saving is about 4.5% of Fable session spend, next to the ~44% the
routing decision already delivers. Promote it after a preregistered test on judged-hard sessions.

## `model_routing` (HC04/HC05, opt-in; `None` = off; an explicit `{}` is invalid -- `start_model` is required)

| Key | Default | Meaning |
|---|---|---|
| `start_model` | required | The cheaper/faster model a turn starts pinned to. |
| `start_policy` | `"cheap"` (library); `judge` (shipped) | `cheap` (every turn starts on `start_model`, no judge), `rules` (prompt length), or `judge` (one typed simple/complex question to the configured backend; falls back to rules on abstain/error). |
| `complex_min_probability` | `0.5` | A judged turn with p(complex) at or above this starts on the host model. |
| `complex_min_prompt_chars` | `2000` | The `rules` policy (and the judge fallback) starts a prompt this long on the host model. |
| `cheap_max_workspace_files` | unset (library); `300` (shipped) | In a workspace with more files than this, the session starts on the host model whatever the judge says. |
| `decision_scope` | `"turn"` (library); `"session"` (shipped) | `turn`: decide the start tier at the first slow request of every turn. `session`: decide once, at the first slow request of the session's first turn (its prompt is the one judged), reuse for every later turn, persist across resumes (`<events_dir>/session-route/<session>.json`, no prompt text). A model the user picks always wins and never overwrites the stored decision; provider-error escalation stays per turn; the decision is re-made if the host model or routing config changes. Conflicts with `planner`. See "Decision scope". |
| `price_gate` | `None` (library: off); `{enabled: true}` (shipped) | Route only when the predicted session cost on `start_model` is lower than on the host. See "Price gate". |
| `keep_on_host` | `None` (off) | Opt-in: `{task_types: [...]}` keeps those task types on the host. Requires `start_policy: judge`. See "Task-type opt-out". |
| `start_effort` | unset | One of the `ALLOWED_EFFORTS` strings. |
| `max_requests_before_escalation` | unset | Positive int; escalates after this many slow requests in the turn. |
| `escalate_on_test_failure` | `False` | Escalate the first time `ObservedTool.execute` observes a failing test-tool result this turn. |
| `escalate_on_provider_error` | `False` | Escalate on any upstream provider exception. |
| `override_explicit_model` | `False` | Whether an explicit `request.model` set by the host is overridden by `start_model` anyway. |
| `escalation_judge` | `"rules"` | `"rules"` (deterministic triggers only), `"judge"` (HC05: ask the configured backend a single Choice question past the turn's first slow request, while not yet escalated by a deterministic trigger), or `"decomposed"` (HC10: ask five atomic yes/no signals in one batched call and combine them in code via a weighted sum -- see below). |
| `escalate_min_probability` | `0.7` | Legacy alias for `confidence_gates["escalation"]` (HC09) -- still the default source when that key is absent. Also the gate HC10's weighted score is compared against. |
| `escalation_weights` | `DEFAULT_ESCALATION_WEIGHTS` (see below) | HC10, opt-in. Per-signal weight override, merged over the defaults (a partial dict only overrides the signals it names). Unknown signal names or out-of-range values (`[0, 1]`) raise `ValueError`. |

### Decision scope

`decision_scope: session` (shipped) decides the start tier once and never switches: the provider's prompt cache is
never thrown away by a mid-session model change. In the paired campaign this cost **0.86x (Fable) and 0.92x (Opus)** of
deciding per turn (H3, `confirm/CONFIRM.md`); the sticky arm on Fable cost 0.558x plain Fable (CI 0.493-0.643) with
non-inferior turn-pass. `decision_scope: turn` restores per-turn decisions (the library default). Residual risk: a
session that starts easy and turns hard stays on the start model (the campaign's exploratory final-pass excess was 6
vs 1 on Fable sticky); a user model pick, provider-error escalation, `keep_on_host` and `decision_scope: turn` are the
mitigations.

### Price gate

Routing only saves money when the cheap model costs less *for the whole session*, and cheaper models make more requests
(measured: Sonnet 5 at medium made **1.38x** the requests of an Opus 5.5 host and **1.11x** those of a Fable 5.1 host,
paired). The gate predicts

```
predicted_ratio = request_multiplier(host) * usd_per_request(cheap) / usd_per_request(host)
usd_per_request = (in*3 + out*541 + cache_read*88,516 + cache_write*5,376 tokens) priced per model   # REFERENCE_MIX
route           = predicted_ratio < 1.0
```

and routes only when it is below 1. At the bundled prices (`savings.DEFAULT_RATES`, verified 2026-06-10):

| Host | multiplier | predicted ratio | gate | measured in the campaign (sticky-on-Sonnet / anchor) |
|---|---|---|---|---|
| `claude-opus-5-5` | 1.38 | 1.366 | **host** | 1.18 (CI 1.11-1.27); every routing arm cost 1.25-1.43x |
| `claude-fable-5-1` | 1.11 | 0.523 | **route** | 0.504 (CI 0.48-0.53); sticky 0.558 |
| `claude-opus-5`, `claude-opus-4-7` | 1.38 (default) | 0.828 | route | unmeasured |
| `claude-fable-5` | 1.38 (default) | 0.414 | route | unmeasured |
| `claude-sonnet-5` / dated ids | n/a | n/a | host (`same_model`) | n/a |
| `claude-haiku-4-5` | 1.38 (default) | 4.14 | host | n/a |
| unknown / unpriced model | n/a | n/a | host (`host_unknown` / `host_unpriced`) | n/a |

The gate is conservative: it over-predicts the cheap model's cost on both measured hosts (Opus 1.366 vs 1.20 measured,
Fable 0.523 vs 0.504). Break-even under the gate: Opus cache reads at **$0.429/M** (today $0.20/M); the paper's
break-even is $0.34-0.38. A priced-in sweep over the recorded sessions confirms the gate never routes where the data
say routing costs more ([replay](evidence/2026-10-05-defaults-replay/REPLAY.md)). Opus users give up the older
single-request study's ~20% speed gain at ~equal cost; `price_gate: {enabled: false}` restores routing.

`price_gate` keys (all optional; `{}` means on with defaults):

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns the gate off (legacy list-price guard only). |
| `request_multipliers` | `{}` | `{host_model: float in (0, 10]}`, merged over the built-in table (`claude-opus-5-5: 1.38`, `claude-fable-5-1: 1.11`); prefix match, so dated ids work. |
| `default_request_multiplier` | `1.38` | For a priced host with no table entry (the larger measured value: conservative). |
| `rates` | `{}` | `{model: [input, output, cache_read, cache_write]}` USD per million tokens, merged over `savings.DEFAULT_RATES`. Use it if a provider changes prices or for a model the table lacks. |

Hosts with no `default_model` or an unpriced model stay on the host (`host_unknown` / `host_unpriced`): add the model to
`price_gate.rates` to route. `afast doctor` prints the gate result for the configured host. The `session_routed`
event records every input and the predicted ratio ([EVENTS.md](EVENTS.md)). A tier chosen by a `profile` (e.g.
`frugal`'s Haiku) is re-checked against the gate. Evidence:
[campaign](evidence/2026-10-02-paired-campaign/README.md),
[CONFIRM.md](evidence/2026-10-02-paired-campaign/confirm/CONFIRM.md),
[paper](papers/2026-10-02-paired-measurement/README.md).

### Task-type opt-out

```yaml
model_routing:
  keep_on_host:
    task_types: [review, explain, feature]   # any of bugfix, feature, docs, explain, review, other
```

Adds one typed question (`task_type`) to the same batched judge call as `task_difficulty`, so there is no extra round
trip. A session the judge classifies as one of these starts on the host; **no answer fails closed to the host**
(`task_type_unknown_strong`). Requires `start_policy: judge`. **Exploratory:** on Fable the sticky-routed sessions lost
turn-pass on review (-0.155), explain (-0.143) and feature (-0.071) work (post hoc, 3-13 scenarios per type, no docs
scenario in the test split). The cost of using it: on the campaign mix it forfeits about **$676 of the $1,980 per 1,000
Fable sessions** that sticky routing saves. Off by default.

## `delegation_routing` (per-delegation model routing, opt-in; `None` or `{}` = off)

One decision per `delegate` tool call, before the child session exists. Unlike
`model_routing`, an explicit `{}` is valid and simply off (`mode` defaults to
`"off"`): there is no required key, because the shipped policy is the default.
Full design, evidence and limits: [DELEGATION-ROUTING.md](DELEGATION-ROUTING.md).

| Key | Default | Meaning |
|---|---|---|
| `mode` | `"off"` | `off` (inert: no facade, no judge call, no event) / `shadow` (decide and record, change nothing) / `enforce` (pin `provider_preferences` on the call). |
| `policy` | `"v3"` | A shipped policy name (`policies/delegation_<name>.json`) or a path to a JSON policy file. An unloadable policy disables the feature; it never breaks a turn. |
| `deadline_ms` | `750` | 10..60000. Bounds the WHOLE four-question `ask_many()` call. A backend with no `ask_many` of its own (laya, ollama, mlx, hosted) is fanned out into four CONCURRENT asks -- budget for the slowest of four, not one. |

## `confidence_gates` (HC09, opt-in; `None` = every kind uses its legacy default)

| Key | Default when present | Legacy fallback when the whole policy omits `confidence_gates`, or omits this key |
|---|---|---|
| `read_shortcut` | (no built-in default -- must be set explicitly to apply) | `min_probability` (`0.90`) |
| `phase` | (no built-in default -- must be set explicitly to apply) | `0.0` (no gate; any non-abstain judge answer applies -- the pre-HC09 behavior) |
| `escalation` | (no built-in default -- must be set explicitly to apply) | `model_routing.escalate_min_probability` (`0.7`) |

Each value must be a number in `(0, 1]`. A key present in `confidence_gates`
always overrides its legacy alias, even if the legacy alias is also
explicitly set. See `contracts.effective_gate(policy, kind)` -- the single
resolver every call site (`DecisionService.choose`, the HC05 phase/escalation
judges, whether asked sequentially or via HC08 batching) consults.

Recommended explicit configuration, once the head-to-head study in
`evals/STUDY-DESIGN.md` section 14 and `evals/DESIGN-BRIDGE.md` rule (d2)
confirms a stake-scaled floor beats the flat legacy defaults for a given
mechanism:

```yaml
confidence_gates:
  read_shortcut: 0.7
  phase: 0.6
  escalation: 0.9
```

These are illustrative, not a shipped default -- `confidence_gates`
defaults to `None`, and every kind's legacy fallback is unchanged until a
human ratifies otherwise (see `evals/DESIGN-BRIDGE.md`'s "for human
ratification" framing).

## `escalation_weights` default (HC10, `model_routing.escalation_judge: "decomposed"`)

Five atomic signals, each an independent yes/no probability, combined via
`score = sum(weight[signal] * probability[signal])`:

| Signal | Default weight | Question |
|---|---|---|
| `tests_failing` | `0.30` | Tests or checks are failing after edits. |
| `repeated_tool_errors` | `0.25` | The last tool results contain repeated errors or failures. |
| `plan_derailed` | `0.20` | The agent is repeating itself or has abandoned the stated plan. |
| `beyond_tier` | `0.15` | The task needs deeper reasoning than a fast model reliably provides. |
| `unfamiliar_code` | `0.10` | The task requires understanding code the agent has not read. |

`score >= gate + 0.1` escalates; `score <= gate - 0.1` continues on the
cheap model; the band in between (`gate - 0.1 < score < gate + 0.1`) is
deliberately left "uncertain" and not acted on -- the deterministic
triggers (`escalate_on_test_failure`, `max_requests_before_escalation`,
`escalate_on_provider_error`) remain a floor regardless. See
`docs/EVENTS.md`'s `escalation_signals` receipt and orchestrator.py's HC10
section for the full mechanism.
