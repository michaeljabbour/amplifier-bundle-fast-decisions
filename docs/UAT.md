# UAT walkthrough: is shadow measurement telling the truth?

This is the step-by-step a human runs in a real Amplifier session before
ever considering `--mode active`. See also `docs/BENCH.md` for what each
number means, and `docs/PRIVACY.md` before enabling `--allow-external-state`.

## 1. Confirm the environment

```bash
python3 -m amplifier_fast_decisions doctor --require-amplifier
```

All required checks green. `TYPESAFE_API_KEY_present` should be `true` if
you intend to exercise real Jev (its value is never displayed).

## 2. Generate a local shadow profile

```bash
export WORKSPACE="$(pwd)"
python3 -m amplifier_fast_decisions configure \
  --bundle-root "$PWD" \
  --workspace "$WORKSPACE" \
  --mode shadow \
  --allow-external-state \
  --output "$PWD/local-shadow.md"

amplifier bundle add "file://$PWD/local-shadow.md" --app
```

`--allow-external-state` is what makes this shadow rung "real Jev, zero
behaviour change" rather than deterministic-only shadow (see
`docs/design/redesign-2026-09-17.md` P3, rung ladder). Do not add `--app`
during this test; select the profile per-run instead:

```bash
amplifier run --bundle fast-decisions-shadow \
  "A normal working task, not a synthetic prompt."
```

## 3. Run a normal working session

30-60 minutes, ordinary tasks -- not synthetic prompts designed to trigger
the fast path. **Nothing should feel different.** That is the acceptance
criterion for this rung: shadow scoring runs entirely off the critical path
(P3), so a session with shadow mounted should be indistinguishable, from the
user's seat, from the same session without it.

## 4. Replay the recorded telemetry

```bash
afast bench replay ~/.amplifier/fast-decisions/events --md uat.md
```

## 5. Read `uat.md` and answer one question per mismatch

For a sample of roughly 20 mismatches (`shadow_agreement.agreement ==
"mismatch"`), the owner reads the proposed vs. actual action and asks:
**would I have let it act?**

The viewer's decision list (`afast serve`) makes this concrete: sort
"mismatch first", open each row, and check the reason code and probability
against your own judgment of the task. The reliability plot answers a
related but different question -- is the *stated* probability trustworthy
at all, independent of any single decision.

## 6. Only then consider `--mode active`

And only for `fast_workspace` (the only rung this bundle ships as active --
see the design doc's "Decisions taken", #1). Promotion criteria:

- `agreement_rate` and `calibration_ece` hold up across the sampled
  mismatches you actually read, not just the aggregate number.
- `shadow_snapshot_budget_exceeded` and `dropped_shadow_jobs` are near zero
  -- if shadow itself is quietly failing to snapshot or score, its
  measurement is not trustworthy regardless of what it reports.
- `unsafe_autonomous_actions` is `0` (it is a release blocker, not a metric,
  if it is not).
- `order_agreement_stability` from `afast bench suite` is high and
  `max_probability_swing` is under the 0.15 warning threshold -- otherwise
  the thresholds you are about to trust are measuring candidate
  serialisation, not the task.

```bash
python3 -m amplifier_fast_decisions configure \
  --bundle-root "$PWD" --workspace "$WORKSPACE" \
  --mode active --allow-external-state --output "$PWD/local-active.md"
amplifier bundle add "file://$PWD/local-active.md" --app
amplifier run --bundle fast-decisions-active \
  "The same kind of task you shadow-tested."
```

## What the observatory shows during this walkthrough

`afast serve --open` (or `afast export` for a static HTML snapshot) renders,
on top of the existing routing graph and timeline, four bench-specific
views (see `docs/BENCH.md` "The viewer's four bench additions" for detail):
a decision list sortable mismatch-first, the reliability plot, a rung banner
(mode / backend / policy version / inferred external-state), and a "what
would have changed" counter that keeps avoided-LLM-turns and
different-action mismatches visually distinct -- they are different risks.

No control endpoint exists in the viewer, before or after this rung. It
cannot authorize anything; it can only show you what already happened.
