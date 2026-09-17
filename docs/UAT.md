# UAT walkthrough: is shadow measurement telling the truth?

This is the step-by-step a human runs in a real Amplifier session before
ever considering `--mode active`. See also `docs/BENCH.md` for what each
number means, and `docs/PRIVACY.md` before enabling `--allow-external-state`.

## 1. Confirm the environment

```bash
afast doctor --require-amplifier
```

Run this from the Amplifier tool venv's interpreter (or via the `afast`
entry point it installs) -- `--require-amplifier` checks for
`amplifier_core`/`amplifier_module_loop_streaming`, which live only there,
not in a bare source checkout. All required checks green.
`TYPESAFE_API_KEY_present` should be `true` if you intend to exercise real
Jev (its value is never displayed).

## 2. The default: shadow is already on, no configure step needed

The simplest UAT is the already-installed behavior. Shadow measurement
lives on the hook (`hooks-fast-decisions`), not the orchestrator (P3), so
it composes onto whatever orchestrator you already run -- no bundle profile
required for the deterministic rung:

```bash
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=behaviors/fast-decisions.yaml" --app
```

Shadow is on by default with the deterministic (in-process, offline)
backend. Run a normal session; `shadow_*` events appear in
`~/.amplifier/fast-decisions/events` with no API key involved.

The first top-level session also auto-opens the local observatory
(`http://127.0.0.1:8765`, token-protected, loopback-only) so `shadow_*`
telemetry is visible live -- no separate `afast serve` step needed. It
reuses an already-running viewer rather than spawning a second one, stays
off for child sessions and non-TTY runs, and can be disabled with
`observatory.open_browser: never` or `AFAST_OBSERVATORY=off`. If 8765 is
busy, the viewer picks a free port instead; the state file and printed URL
tell you which (`--no-fallback` fails loud instead, for a deliberate fixed
port). Stop it any time with `afast serve --stop`. See `docs/PRIVACY.md`
("Viewer") for what the state file holds.

### For real Jev in shadow

Real Jev scoring (still shadow -- never enacted) needs
`TYPESAFE_API_KEY` and an explicit opt-in to external state:

```bash
export TYPESAFE_API_KEY=...
export WORKSPACE="$(pwd)"
afast configure \
  --bundle-root "$PWD" \
  --workspace "$WORKSPACE" \
  --mode shadow \
  --allow-external-state \
  --output "$PWD/local-shadow.md"
```

`--allow-external-state` is what makes this shadow rung "real Jev, zero
behaviour change" rather than deterministic-only shadow (see
`docs/design/redesign-2026-09-17.md` P3, rung ladder). Add it with `--app`
to keep it mounted, or select it per-run instead:

```bash
amplifier bundle add "file://$PWD/local-shadow.md" --app
# or, without --app:
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
afast bench replay ~/.amplifier/projects/<project>/sessions/<id>/ --md uat.md
```

`bench replay` accepts a real Amplifier session directory directly (it reads
the kernel's `events.jsonl`), or the recorder's own events directory:

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

Either the profile `configure` generates, or the checked-in
`bundles/active.yaml` via `amplifier bundle use`, will do:

```bash
afast configure \
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
