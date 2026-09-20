# Results -> design bridge

This is the point of the study: turn `results.json` into ratified defaults for
the bundle's `behaviors/fast-decisions.yaml`. Read `STUDY-DESIGN.md` first for
*why* these thresholds exist; this file is the *decision rule per knob*, the
*evidence required*, and the *current default*, so a human ratifying a change
can check the number against the rule in one place.

`evals/run.py` computes the numbers (via `build_cell_result`/`q3_comparison`
in `evals/run.py`, fed from `battery.py evaluate`'s `comparison.json`) and
writes `<out>/results.json`, `<out>/RESULTS.md` (the readable verdict table),
and `<out>/DESIGN-RECOMMENDATION.md` (this file's rules applied to that one
run, via `design_recommendation_text()`). **The recommendation is generated,
not authoritative** -- it is marked "for human ratification" and must not be
treated as having flipped any config on its own.

---

## (a) `mode`: shadow vs active (`behaviors/fast-decisions.yaml`)

**Decision rule:** flip from `shadow` to `active` only when the champion cell
`judge-local+effort` is `confirmed` (STUDY-DESIGN.md section 8) **on the S1
holdout split**, with quality non-inferior. `screen`-level results (dev split,
fewer than 3 reps, fewer than 8 paired passing tasks, or a CI that still
includes 1.0) are never sufficient -- they can direct the next experiment,
never a default.

**Evidence required:** `results.json["cells"]` entry for
`judge-local+effort` with `verdict == "confirmed"`, `split == "holdout"`,
`gate_passed == true`, `quality.non_inferior == true`, `exec_time_ratio.ci95_high < 1.0`.

**Current default:** `shadow` (unconfirmed as of this writing -- no holdout
pass has run yet).

---

## (b) Judge backend default (`ollama` / `jev` / `auto`)

**Decision rule:** default stays `ollama` (local, no external state) unless
`judge-jev+effort` is independently `confirmed` **and** its mechanism gate
shows `scored_by_backend["jev"] > 0` (i.e. Jev was actually called, not the
2026-09-18 "configured but never scored" defect) **and** decision latency
(p95, from the Jev receipts) is under 500 ms -- a judge slower than that
erodes the win it's there to buy. When all three hold, `auto` may default to
Jev *only* when `TYPESAFE_API_KEY` is present **and** `allow_external_state`
is explicitly set by the operator; external state is never default-on
(STUDY-DESIGN.md section 10).

**Evidence required:** `results.json["cells"]["judge-jev+effort"].verdict ==
"confirmed"`; its `gate_passed == true`; a p95 decision-latency figure under
500 ms (`comparison.json["mechanism"]["decision_latency_ms_p95"]`, emitted by
`battery.py`'s mechanism report).

**Current default:** `ollama`. `jev` is opt-in and unconfirmed.

---

## (c) `effort_routing` default map (`explore_only` incumbent vs `all_phase`)

**Decision rule:** the incumbent (`explore_only`: explore->low only) is the
shipped default. Promote to `all_phase` (orient/explore/implement) only when
`judge-local+effort`'s quality is non-inferior on the tasks that most stress
effort routing (`repair`, `bugfix` families in STUDY-DESIGN.md section 3) --
a quality regression on either family disqualifies `all_phase` regardless of
speed, because a routing decision that trades correctness for latency is not
the mechanism this benchmark is trying to validate.

**Evidence required:** `results.json["cells"]["judge-local+effort"].quality.non_inferior
== true` and (from `comparison["per_family"]`, read at report time, not
duplicated into results.json) no per-family success-rate drop for `repair`/
`bugfix` between the fd arm and its anchor.

**Current default:** `explore_only` (incumbent). `all_phase` is a candidate.

---

## (d) `model_routing` default (on / off)

**Decision rule:** default `off`. Flip to `on` only when
`judge-local+effort+route` beats **its own mandatory control**
`plain-sonnet` (R5) -- not merely `plain` -- with escalation actually firing
on a nonzero share of tasks (`mechanism_gate.flag_if_zero_escalations` must
not have fired). If the routing cell beats `plain` but does **not** beat
`plain-sonnet`, the honest recommendation is **"pin the cheaper model"**, not
routing: the measured gain is fully explained by using sonnet-5 directly, and
routing would add complexity (start-model selection, escalation triggers,
another mechanism to keep green) with no demonstrated payoff over just
changing `amplifier_model`.

**Evidence required:** `results.json["cells"]["judge-local+effort+route"]`:
`exec_time_ratio.geomean < 1.0` and `sign_test_p <= 0.05` **against its
`plain-sonnet` anchor**, `cost_ratio <= 1.0`, and the mechanism gate did not
flag `confounded_with_plain_sonnet`. The optional `vs_plain` field (from the
cell's `secondary_anchor: plain` in `cells.yaml`) distinguishes "beats
plain-sonnet" (routing pays) from "beats plain but not plain-sonnet" (pin the
model, don't route).

**Current default:** `off`. Both model-routing cells are candidates, never
assumed defaults (STUDY-DESIGN.md section 12, Decision 4).

---

## (d2) `escalation_judge` / `phase_judge` default (`rules` / `false` vs `judge` / `true`)

**Decision rule:** default stays `rules` (for `model_routing.escalation_judge`)
and `false` (for `effort_routing.phase_judge`) -- the deterministic HC03/HC04
behavior, unchanged -- unless the JEV twin of the relevant judged cell wins
the head-to-head defined in `STUDY-DESIGN.md` section 14: for escalation,
`judge-jev+effort+route-judged` must win-or-tie on time against its own
RULES-escalation twin `judge-jev+effort+route` (`secondary_anchor`) with
quality non-inferior, `mechanism_gate.judged_engaged == true` on every rep,
and jev decision-latency p95 under 500 ms; for phase classification,
`judge-jev+effort-phasejudged` must clear the same bar against its own
twin `judge-jev+effort`. Each knob is decided independently -- a win on one
does not imply a win on the other, and neither implies anything about rule
(b)'s read-shortcut judge default. If jev does not clear the bar, `local`
(`ollama qwen3:0.6b`) is evaluated the same way against ITS OWN rules twin
before either `escalation_judge: "judge"` or `phase_judge: true` can default
`on` for `ollama` either -- a judge mechanism is promoted only when it beats
the deterministic rules it would replace, independent of which backend runs
it.

**Evidence required:** `results.json["cells"]["judge-jev+effort+route-judged"]`
(and/or `"judge-local+effort+route-judged"`) with `verdict == "confirmed"`,
`gate_passed == true` (which must reflect `judged_engaged`, once
`evals/run.py::gate_eval` is extended to read it -- see STUDY-DESIGN.md
section 14's open item), `exec_time_ratio.geomean <= 1.0` measured against
the RULES twin (not `plain-sonnet`), quality non-inferior, and (for the jev
variant) `comparison.json["mechanism"]["decision_latency_ms_p95"] < 500`.
Symmetric evidence from `results.json["cells"]["judge-jev+effort-phasejudged"]`
/ `"judge-local+effort-phasejudged"]` for `phase_judge`.

**Current default:** `rules` / `false`. Both are opt-in candidates, evaluated
independently of rule (b)'s read-shortcut judge default and of rule (d)'s
`model_routing` on/off default -- `model_routing` must already be `on` (rule
(d)) before `escalation_judge` has anything to escalate.

---

## (e) External state (privacy)

**Decision rule:** external state (the `jev` judge backend) remains opt-in
**regardless of any result above**. No amount of evidence promotes it to a
default-on behavior; a human must set `allow_external_state: true` and
`TYPESAFE_API_KEY` explicitly, every time. See `docs/PRIVACY.md`.

**Evidence required:** none -- this is a policy invariant, not a result-driven
decision.

**Current default:** opt-in, unconditionally.

---

## How `DESIGN-RECOMMENDATION.md` is generated

`evals/run.py::design_recommendation_text(results, cells_doc)` applies rules
(a)-(e) above to one `results.json`, quoting the exact numbers that triggered
each recommendation and the evidence limits that qualify them. **Rule (d2)
is written above but not yet wired into `design_recommendation_text` or
`evals/run.py::gate_eval`** (both out of scope for the change that added
(d2) -- see STUDY-DESIGN.md section 14); until then, (d2) is checked by hand
against `results.json` and `comparison.json["mechanism"]["judged_engaged"]`.
It is written
to `<out>/DESIGN-RECOMMENDATION.md` at the end of every `run.py` invocation
that produces `results.json` (i.e. every invocation except `--dry-run`). It
never edits `behaviors/fast-decisions.yaml` itself -- "for human ratification"
means a person reads the recommendation, checks it against this file's rules
and the underlying `RESULTS.md`, and makes the edit by hand.

---

## Applying the recommendation

`evals/apply_recommendation.py` is the tool that turns a confirmed result
into an actual bundle change. It reads `<out>/results.json` (and, when
present, `<out>/gates.json` for mechanism-gate flags and
`latency_within_budget`) and `evals/cells.yaml` (the same fd/effort_profiles/
model_routing_profiles source `evals/run.py::cell_to_argv` reads), applies
ONLY the rules above whose evidence requirement is `verdict == "confirmed"`,
and writes/refreshes `behaviors/fast-decisions-active.yaml` -- an OPT-IN
`session.orchestrator` profile (the shape of `bundles/active.yaml`), never
the shadow default. `--promote-default` additionally flips
`behaviors/fast-decisions.yaml`'s hook `mode`/`backend` fields (never
`allow_external_state`) to the confirmed values.

**Confirmed-only, no exceptions.** A `screen`-level result never triggers a
file change, matching rule (a)'s "screen-level results ... are never
sufficient" language applied uniformly across (a)-(d): `--dry-run` and
`--apply` both exit `2` with no files touched when nothing is confirmed.

**Rule (b) stays a note, never a write.** Even when the `jev` twin of the
confirmed arm is independently confirmed with a passed mechanism gate and
`latency_within_budget: true`, `apply_recommendation.py` does not write
`backend: jev` anywhere -- it adds a note recommending `backend: auto`
semantics (jev when `TYPESAFE_API_KEY` is present AND
`allow_external_state` is explicitly set by the operator, else local) for a
human to apply by hand. Rule (e) (external state stays opt-in) is enforced
unconditionally: no evidence, confirmed or otherwise, ever sets
`allow_external_state: true` in a file this tool writes.

**Rule (d)'s two outcomes are both visible.** When the routing cell
(`judge-local+effort+route`) is confirmed against its `plain-sonnet` control
(R5) AND its mechanism gate's `flag_if_zero_escalations` did not fire (read
via `gates.json[cell]["flags"]`, never re-derived), `model_routing` is added
to the active profile. When it is confirmed but zero escalations fired, the
gain is explained by the model, not the routing, and the tool omits
`model_routing` and writes the "pin the cheaper model instead" comment in
its place -- exactly rule (d)'s own text.
