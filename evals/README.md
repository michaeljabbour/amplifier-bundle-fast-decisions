# evals/ -- how to run the fast-decisions benchmark

Read `STUDY-DESIGN.md` first: it says what is being measured and which rules are
non-negotiable. This file is the operating manual. `SPEC-for-builder.md` is the
implementation spec for `evals/run.py`, which now exists (see `cells.yaml`,
`suites.yaml`). Decision (2026-09-20): the old S1 external-harness columns from
the 2026-09-18 campaign (run under `acceptEdits`) are retired -- not comparable
to anything `run.py` produces, which is `bypassPermissions` everywhere (R2). See
`STUDY-DESIGN.md` section 12 "Decisions" for the rest.

`run.py` composes existing tools. It adds no measurement logic of its own:

```
evals/run.py  ->  scripts/battery.py prepare|run|reevaluate|evaluate
              ->  scripts/battery_report.py --series ...
```

---

## Before the first run

```bash
# 1. toolchains for the languages you will grade (S2 only)
python3 -c "import sys; sys.path.insert(0,'scripts'); import polyglot_tasks; print(polyglot_tasks.toolchains())"

# 2. the polyglot corpus, pinned
python3 scripts/fetch_polyglot.py --dest ~/dev/polyglot --ref main
jq -r .sha ~/dev/polyglot/polyglot-manifest.json      # must be 7e0611e...

# 3. forge is healthy (the runner checks this too, and refuses without it)
python3 scripts/forge_e2e.py doctor 2>/dev/null || python3 "$(python3 -c "import sys;sys.path.insert(0,'scripts');import forge_e2e;print(forge_e2e.FORGE)")" doctor

# 4. warm the local judge -- a cold ollama inflates the first runs of a cell
ollama pull qwen3:0.6b && ollama run qwen3:0.6b "ok" >/dev/null

# 5. keys in the environment only, never in a file under the run directory
: "${ANTHROPIC_API_KEY:?set it}"
```

---

## Where results live

```
.amplifier/evaluation/fast-decisions/<UTC-sortable-datetime>/
```

for example `.amplifier/evaluation/fast-decisions/20260919T140355Z/`. This
follows the evaluation bundle's harness-automation convention (sortable
per-project directory in the workspace root).

**Never commit run output.** It contains full prompts and responses, absolute
host paths, workspace contents, and session traces. `.amplifier/` is already in
this repo's `.gitignore`; confirm with `git status` before any commit -- captured
run output must never appear there.

Layout inside a run directory:

```
<out>/
  manifest.json              suite shas, cells, reps, seeds, budget, exclusions
  cells.resolved.json        the exact battery.py argv per cell (what actually ran)
  prompt-verification.json   per-task prompt hashes, per harness (the R1 receipt)
  campaign/                  battery.py campaign root
    protocol.json  ledger.jsonl
    experiments/<cell>-<suite>-<split>-r<N>/
      proposal.json  comparison.json  REPORT.md  runs/...
  report/report.md report.json        cross-cell comparison
  results.json                        verdict per cell (see evals/DESIGN-BRIDGE.md)
  RESULTS.md                          the readable verdict table + Q3/Q4 + evidence limits
  DESIGN-RECOMMENDATION.md            results.json -> evals/DESIGN-BRIDGE.md rules, for human ratification
```

Read `evals/DESIGN-BRIDGE.md` for how `results.json` turns into a recommended
change to `behaviors/fast-decisions.yaml` -- the decision rule, the evidence
required, and the current default, per knob (`mode`, judge backend,
`effort_routing`, `model_routing`, external state).

---

## Run one cell

```bash
python3 evals/run.py \
  --suite s1 --split dev --cells judge-local+effort --reps 1 \
  --out .amplifier/evaluation/fast-decisions/$(date -u +%Y%m%dT%H%M%SZ)
```

One rep, dev split: this is a **screen**. It cannot produce a finding
(`STUDY-DESIGN.md` section 8).

## Run a pair (a mechanism and its control)

```bash
python3 evals/run.py \
  --suite s1 --split dev --cells judge-local+effort+route,plain-sonnet --reps 3 \
  --out .amplifier/evaluation/fast-decisions/$(date -u +%Y%m%dT%H%M%SZ)
```

`run.py` refuses to run `judge-local+effort+route` without `plain-sonnet` in the
same invocation -- the routing number is uninterpretable alone (R5).

## Run the full matrix

```bash
# selection pass, dev split
python3 evals/run.py --suite s1 --split dev --cells all --reps 3 --out <dir>

# confirmation pass, holdout split, champion + its controls only
python3 evals/run.py --suite s1 --split holdout \
  --cells plain,judge-local+effort,externals --reps 3 --out <dir>

# harder tasks
python3 evals/run.py --suite s2 --split dev     --cells plain,judge-local+effort --reps 3 --out <dir>
python3 evals/run.py --suite s2 --split holdout --cells plain,judge-local+effort --reps 3 --out <dir>
```

Preregister before the holdout pass: write the decision rule and the expected
result into `<out>/PREREGISTRATION.md` **before** launching. A holdout run whose
rule was written afterwards is a dev run with a misleading name.

## Resume

```bash
python3 evals/run.py --resume --out <existing-dir>
```

Re-reads the manifest, skips experiments that already have results, adopts live
workers, and continues. Resume never re-prepares an existing experiment and
never relaunches a finished run.

## Report only (free, no model calls)

```bash
python3 evals/run.py --report-only --out <existing-dir>
```

Re-scores from preserved workspaces (`battery.py reevaluate`), re-evaluates, and
regenerates the report. This is the **only** sanctioned way to change a number
after the fact.

## Where the campaign actually lives (`--campaign-root`)

`--out` keeps only `manifest.json`, `gates.json`, `preflight.json`/
`prompt-verification.json`, `campaign-proposal.json`, and a
`campaign-root.txt` pointer. The campaign itself (experiments, runs,
workspaces, receipts) lives elsewhere by default:

```
~/dev/afast-ev/<basename of --out>
```

so its deeply nested run-dir paths don't count against `--out`'s own path
budget (see `STUDY-DESIGN.md` section 17 -- a workspace path over macOS's
255-byte `NAME_MAX` silently kills the run before it launches). Override with:

```bash
python3 evals/run.py --campaign-root /some/other/place ...
```

Set once per `--out` directory; `--campaign-root` on a later `--resume`/
`--report-only` call must agree with the value already recorded in
`campaign-root.txt`, or `run.py` refuses (exit 2) rather than silently
splitting one campaign across two locations. A new preflight check,
`workspace_path_length`, fails loudly (exit 4) before any worker launches if
the plan would still exceed the limit; `preflight.json`'s `max_encoded_len`
reports the margin on every run, pass or fail.

## Running runs in parallel (`--parallel`)

```bash
python3 evals/run.py --parallel 3 --suite s1 --split dev --cells all --reps 3 --out <dir>
```

Keeps up to `N` timed runs in flight at once (default `1`, unchanged
sequential behavior), plumbed through to every `battery.py run` invocation.
Refused if `N` exceeds `cells.yaml`'s `budget.max_parallel_timed_runs` (`3`
by default -- see `STUDY-DESIGN.md` section 17 for the validity conditions
that make sharing the machine sound: measured wall time is 93-95% remote
provider spans, not local compute). Every result gains
`concurrency_at_launch`/`concurrency_max`; relative comparisons within a
wave stay valid, absolute times collected under `--parallel > 1` carry a
load caveat.

---

## Sanity-check protocol -- do this for every cell, every time

The numbers have been wrong three times in ways the numbers themselves could not
show. Twenty minutes here is cheaper than a day of interpreting a fake result.

1. **Read 3 transcripts per cell** (one pass, one fail, one slowest). Look for:
   the agent doing the actual task rather than something adjacent; no prompt that
   reads generic or truncated; no "command not approved" refusals; no evidence of
   the agent editing a protected file and the check missing it.
2. **Check the mechanism section** of `experiments/<cell>.../REPORT.md`:
   `mechanism_engaged` is true, `scored_by_backend` names the backend the cell
   claims, `effort_routed_by_phase_effort` is non-empty for a cell claiming
   effort routing, `model_routed_requested_models` names the start model for a
   routing cell. `configured_backend: jev` with `scored_by_backend: {}` is the
   known failure -- it means Jev was never called.
3. **Check prompt provenance** in `prompt-verification.json`: every task has one
   hash shared by all harnesses. Then spot-check one run's recorded prompt
   against `forge_workloads.task_prompt(task)` by eye.
4. **Check the series labels** in `report/report.md`: each names judge, effort,
   routing, and model. A bare `amplifier-fd` means the label pipeline broke and
   the report cannot be read.
5. **Check `unknown_cost_count`** per harness. A non-zero count is fine; a
   non-zero count silently averaged into a cost ratio is not -- the ratio is
   reported as `None` when any input is unknown.
6. **Check deadline failures and retries.** A cell with deadline failures is not
   comparable to one without until the penalization is read explicitly.

---

## Cost and time expectations

From the 2026-09-12..19 campaigns. These are planning figures, not guarantees;
`--dry-run` prints the estimate for the exact matrix you asked for.

| | per run | notes |
|---|---|---|
| S1 task, amplifier (either arm) | $0.65 - $1.90, 40 s - 4 min | fd arm runs cheaper and faster than plain in the measured data |
| S1 task, claude | ~$0.16, 20 - 40 s | harness-reported cost |
| S1 task, codex | ~$1.10, 12 - 30 s | token-estimated cost |
| S1 task, opencode | not billed here, 25 - 60 s | team gateway; cost is unknown, not zero |
| S2 polyglot task | $1 - $4, 2 - 15 min | 900 s deadline; cpp/rust builds dominate the tail |

Matrix-level, at 3 reps:

| pass | runs | rough cost | rough wall time |
|---|---|---|---|
| S1 dev, one paired cell (12 tasks x 2 arms x 3 reps) | 72 | $50 - $75 | 2 - 4 h |
| S1 dev, `--cells all` | ~400 | $250 - $400 | 12 - 20 h |
| S1 holdout, champion + externals (8 tasks) | ~120 | $60 - $100 | 3 - 5 h |
| S2 dev, one paired cell (24 tasks x 2 arms x 3 reps) | 144 | $200 - $450 | 10 - 20 h |

Runs are serial by design (one timed run at a time), so wall time does not
shrink with more cores. Budget the matrix before starting it; a matrix that
stops halfway leaves a selected configuration with no confirmation, which is a
failed claim rather than a partial one.

---

## When something is wrong

| symptom | what it means | what to do |
|---|---|---|
| `run.py` exits 4 before any launch | a precondition failed (prompt hash, corpus sha, permission mode, forge doctor, toolchain) | fix the precondition; nothing was spent |
| `run.py` exits 3 | budget or launch cap refused | raise the cap deliberately, or finish in a later session with `--resume` |
| `run.py` exits 5 | runs finished but a mechanism gate failed | the cell's numbers exist and are excluded from claims; read the mechanism section, fix the config, re-run **that cell** |
| `run.py` exits 6 | `--resume` finished its loop but a run is still incomplete (no `result.json`, no live worker) | `--resume` again once the missing runs have a chance to finish or restart |
| a cell's numbers look too good | check the gate first, then the transcripts | a mechanism that never engaged produces plain-Amplifier numbers under a fancy label |
| the evaluator was wrong | re-score, never re-run | `--report-only` re-derives outcomes from preserved workspaces at zero cost |

---

## Applying the recommendation

`run.py` never edits `behaviors/*.yaml` itself -- it only writes
`DESIGN-RECOMMENDATION.md` "for human ratification" (see DESIGN-BRIDGE.md).
`evals/apply_recommendation.py` is the tool that actually applies a
confirmed recommendation to the bundle, and it applies ONLY what
DESIGN-BRIDGE.md's rules say is confirmed -- never a `screen`-level result.

```bash
python3 evals/apply_recommendation.py \
  --results <out-dir> [--holdout-results <out-dir>] \
  --repo <bundle-repo-worktree> \
  --dry-run   # or --apply
```

- Default output is opt-in: it writes/refreshes
  `behaviors/fast-decisions-active.yaml` (a `session.orchestrator` profile,
  in the shape of `bundles/active.yaml`), and leaves the shadow default
  (`behaviors/fast-decisions.yaml`) untouched.
- Pass `--promote-default` to also flip the default behavior's hook
  `mode`/`backend` fields to the confirmed values -- it never sets
  `allow_external_state: true` there, regardless of what was confirmed
  (DESIGN-BRIDGE.md rule (e) is a policy invariant, not a result-driven
  decision).
- Exit codes: `0` applied (or would be, under `--dry-run`); `2` nothing was
  confirmed, no files touched; `4` malformed inputs (missing/unparseable
  `results.json` or `cells.yaml`).
- `--dry-run` prints the unified diff for each file it would touch plus a
  changelog-style summary of exactly which rule fired and the numbers that
  triggered it -- read that before ever passing `--apply`.
