# Policy configuration reference

Every key `Policy.from_config(config: dict)` accepts (`amplifier_fast_decisions/contracts.py::Policy`),
in one place. `from_config` silently ignores unrecognized keys (it filters
by `cls.__dataclass_fields__`); a typo in a key name here is a silent
no-op, not an error -- double-check spelling against this table. Keys
inside a nested dict (`effort_routing`, `model_routing`, `confidence_gates`)
ARE validated and DO raise `ValueError` on an unknown sub-key or an
out-of-range value (see `contracts.validate_effort_routing`,
`validate_model_routing`, `validate_confidence_gates`).

## Top-level keys

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
| `max_state_chars` | `12000` | Canonical-JSON size budget for the state sent to the backend (512..100000). Also bounds HC05's judge state (`orchestrator._judge_state`). |
| `allow_external_state` | `False` (env override: `FAST_DECISIONS_ALLOW_EXTERNAL_STATE`) | Required, alongside an external backend (`backend.external == True`, e.g. Jev), before ANY external call is attempted -- read-shortcut, HC05 judge asks, and HC08 batched asks all honor this identical gate. |
| `allow_synthetic_active` | `False` | Whether an explicitly synthetic backend result (`synthetic=True`, e.g. `ScriptedBackend`) may be submitted in `active` mode. |
| `allowed_tools` | `("fast_workspace",)` | Tools a prepared candidate may target. |
| `shadow_max_messages` | `12` | Messages read for a shadow snapshot. |
| `shadow_snapshot_budget_ms` | `25` | Wall-clock budget for the shadow snapshot (1..5000). |
| `suppress_completed_reads` | `True` | HC02a: drop `fast_workspace` read/list candidates whose `(path, revision)` this turn already read. |
| `effort_routing` | `None` | HC03/HC05, opt-in. See below. |
| `model_routing` | `None` | HC04/HC05, opt-in. See below. |
| `decision_batching` | `False` | HC08, opt-in. Combine the HC05 phase-judge and escalation-judge asks into one `ask_many()` call whenever both are due for the same request. No effect when fewer than two judge mechanisms are configured. |
| `confidence_gates` | `None` | HC09, opt-in. See below. |
| `version` | `"policy-v1"` | Recorded verbatim on every receipt (`policy_version`). Not validated against a known set. |

## `effort_routing` (HC03/HC05, opt-in; `None`/`{}` = off)

| Key | Default | Meaning |
|---|---|---|
| `orient` / `explore` / `implement` | unset (no override for that phase) | One of `low` / `medium` / `high` / `xhigh` / `max`. |
| `max_explore_requests` | unset | Positive int; escalates effort after this many explore-phase requests. |
| `escalate_after_provider_errors` | unset | Positive int. |
| `phase_judge` | `False` | HC05: ask the configured `DecisionBackend` to classify the phase instead of trusting `effort.classify_phase` alone. A non-null, gate-passing answer overrides the deterministic phase for the rest of this request. Gated by `confidence_gates["phase"]` (HC09; default gate `0.0` -- byte-identical to pre-HC09 "any non-abstain answer applies"). |

## `model_routing` (HC04/HC05, opt-in; `None` = off; an explicit `{}` is invalid -- `start_model` is required)

| Key | Default | Meaning |
|---|---|---|
| `start_model` | required | The cheaper/faster model a turn starts pinned to. |
| `start_effort` | unset | One of the `ALLOWED_EFFORTS` strings. |
| `max_requests_before_escalation` | unset | Positive int; escalates after this many slow requests in the turn. |
| `escalate_on_test_failure` | `False` | Escalate the first time `ObservedTool.execute` observes a failing test-tool result this turn. |
| `escalate_on_provider_error` | `False` | Escalate on any upstream provider exception. |
| `override_explicit_model` | `False` | Whether an explicit `request.model` set by the host is overridden by `start_model` anyway. |
| `escalation_judge` | `"rules"` | `"rules"` (deterministic triggers only) or `"judge"` (HC05: also ask the configured backend past the turn's first slow request, while not yet escalated by a deterministic trigger). |
| `escalate_min_probability` | `0.7` | Legacy alias for `confidence_gates["escalation"]` (HC09) -- still the default source when that key is absent. |

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
