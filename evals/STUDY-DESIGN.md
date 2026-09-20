# fast-decisions evaluation: study design

Status: design, not yet run. Version `study-design/v1`.
Supersedes the ad-hoc campaigns of 2026-09-12..19 (`docs/BATTERY-2026-09-18.md`,
`docs/CAMPAIGN-2026-09-18.md`), which produced one real result and six lessons.
Those lessons are rules here, not advice.

---

## 1. What this benchmark is for

fast-decisions is an **opt-in layer inside Amplifier**. It tries to make the
routine decisions cheaply so the expensive model is used only when it is
actually needed. Three mechanisms, independently switchable:

- **judge** -- a small scorer decides whether a prepared read/list action can be
  taken directly instead of asking the big model. Backends: `unavailable` (off),
  `ollama` (local Qwen 0.6b), `jev` (typesafe.ai, a network call).
- **effort routing** -- per phase (orient / explore / implement), ask the big
  model for less reasoning effort where less is enough.
- **model routing** -- start a turn on a cheaper model and escalate to the
  expensive one on a trigger (request count, test failure, provider error).

The benchmark exists to answer four questions in a form a hostile reader
accepts:

- **Q1 -- Does it pay?** Is Amplifier with fast-decisions faster and cheaper than
  plain Amplifier at unchanged quality, on the same tasks, same model, same
  machine, same hour?
- **Q2 -- What part pays?** Which mechanism contributes what, isolated one change
  at a time, each with the control that keeps its result from being explained
  away?
- **Q3 -- Does it matter?** How does Amplifier in its best configuration compare
  with Claude Code, Codex, and OpenCode on identical tasks under identical
  rules?
- **Q4 -- Does it hold?** Does any gain survive harder public tasks (aider
  polyglot), a held-out split, and repetition?

Q1 and Q2 are the product questions. Q3 is the reality check -- the 2026-09-18
campaign found Amplifier 2-4x slower than Claude Code for reasons *outside* the
decision loop (~14 s startup, ~50k-token system prompt), and a benchmark that
cannot see that is not worth running.

---

## 2. Rules that came from being wrong

Each of these cost a day. They are preconditions, not preferences; the runner
refuses to launch when one is unmet (section 7 and `SPEC-for-builder.md`).

**R1 -- Identical prompts, verified by hash before launch.** Amplifier once
received the generic fallback prompt while every other harness received the real
task prompt, and the comparison ran to completion looking fine. Before any paid
launch, the exact prompt string each run will use is resolved and hashed, and
every harness's hash for a given task must match. A run whose prompt cannot be
resolved pre-launch is not launched.

**R2 -- Identical ability to run commands.** Claude Code under
`--permission-mode acceptEdits` refuses build/test commands ("build command was
not approved") while codex / opencode / amplifier run them freely. Every harness
in every cell gets `bypassPermissions`, on both suites. The permission mode of
each harness is recorded per run and printed in the report. Consequence to state
plainly: **S1 external-harness numbers are not comparable to the 2026-09-18
campaign**, which ran Claude under `acceptEdits`.

**R3 -- Grading is independent of the agent.** Candidate code runs
out-of-process with a timeout, never imported into the evaluator. Test discovery
is pytest-first -- `unittest` exit 5 ("no tests collected") is a failure signal,
not a pass, and mis-reading it once silently failed seven passing runs. Answer
parsing tolerates markdown wrapping (`**ANSWER: 8765**`, `> answer: 4.`).
Protected files are byte-compared against the shipped original; any edit fails
the run.

**R4 -- Mechanism gates: configured is not engaged.** One "Jev" cell never called
Jev -- `allow_external_state` was dropped on the way into the profile, the
service refused every request, and the cell's numbers were pure plain-Amplifier
wearing a Jev label. A cell counts only when its own receipts prove its
mechanism fired: the judge actually scored on the configured backend, effort
routing actually emitted `effort_routed` for the phases it claims, model routing
actually emitted `model_routed` for its start model. The cell declares what it
expects; the runner asserts it against receipts; a cell that fails its gate is
reported and **excluded from every claim**.

**R5 -- Every cell has the control that could explain it away.** The
model-routing cell sent 100% of its calls to sonnet-5 and escalated zero times --
so its speed is indistinguishable from "just use sonnet-5". Two consequences:
(a) a **plain-Amplifier-on-sonnet-5 control is mandatory** whenever a routing
cell runs; (b) **every series label names judge / effort / routing / model** -- a
bare "amplifier-fd" label in a report is a defect.

**R6 -- Frozen everything, preregistered, resumable, never re-run to fix.**
The candidate source is snapshotted into a detached worktree at a named sha for
the lifetime of an experiment, so a mid-run edit cannot change what is being
measured. Task splits are frozen at prepare. Hypotheses and decision rules are
written before the confirm split runs. Budget is reserved before every paid
launch. A restarted runner adopts finished and live workers rather than
duplicating them. A Forge deadline is not a completion -- retries and deadline
failures are counted and reported. **Numbers are never improved by re-running a
run**; when the evaluator is wrong, results are re-scored from the preserved
workspaces (`battery.py reevaluate`), which touches no model.

**R7 -- Timing and cost are defined, with provenance.** Working time = first
model call -> last response. Startup is excluded from the headline number and
**reported separately**, because startup is where Amplifier actually loses to
Claude Code and hiding it would be flattering and useless. Every cost carries its
source: `harness_reported`, `computed_from_tokens_estimate`, or
`gateway_internal_not_metered` (OpenCode: not billed here, so it is not "free").
Codex has no native first-call marker, so external harnesses' working time may
still include their own startup -- stated in every report that contains them.

**R8 -- Statistics sized to the evidence.** Comparisons are paired per task
(same task, same workspace hash, same hour). Aggregate is the geometric mean of
per-task ratios; significance is the exact two-sided sign test. No claim before
3 repetitions. Selection happens on dev, confirmation on holdout, and holdout is
never tuned on. The evidence-limits section is generated from the run, not
written by hand. Anything below the bar is labelled **screen**, never "result".

**R9 -- Infrastructure hygiene.** One fixed profile name per cell (a per-run name
pollutes the registry). `forge doctor` before every launch batch. The external
judge (`jev`) requires explicit external-state consent -- it sends bounded task
state off-machine (docs/PRIVACY.md) and is never default-on. Keys live in the
environment, never in a config file, never in run output.

---

## 3. Task suites

### S1 -- synthetic battery (`scripts/battery_tasks.py`)

20 tasks, 4 families x 5, **12 dev / 8 holdout** (3 dev + 2 holdout per family):

| family | what it tests | grading |
|---|---|---|
| `repair` | rebuild a function to a written contract | randomized + boundary + invalid-input + immutability cases against an **independent oracle** implemented in the evaluator, never against the candidate's own helpers |
| `answer` | trace a small codebase with deliberate decoys | single unambiguous token matched by regex against the final `ANSWER:` line, markdown-tolerant |
| `edit` | one precise described change | new behavior **plus** regression checks on untouched behavior |
| `bugfix` | one planted bug with a failing public test | the public case, more cases exposing the same bug, and regression cases |

Why keep it: it is fast (30 s - 2 min/run), cheap, hermetic (stdlib only, no
network, no toolchain), and its hidden checks cannot be gamed by editing tests.
It is the workhorse for Q1/Q2.

Why it is not enough: the tasks are small and synthetic, so a mechanism that
only helps on long tasks is invisible here. That is what S2 is for.

### S2 -- aider polyglot slice (`scripts/polyglot_tasks.py`)

Public corpus `Aider-AI/polyglot-benchmark`, **pinned to sha `7e0611e`**
(recorded in `polyglot-manifest.json`; the runner refuses a mismatch). **40
tasks**, stratified evenly across **python, rust, go, cpp** (10 each), split
60/40 by `select_slice(n=40, seed=...)` into **24 dev / 16 holdout**. Grading
runs the exercise's own shipped test suite on a private temp copy: pytest for
python, `cargo test --offline` with `#[ignore]` stripped for rust,
`go test -json` with leaf-test counting for go, CMake + Catch2 for cpp. Shipped
test files are protected and byte-compared.

**Why Java and JavaScript are excluded (for now).** Not a judgment about the
languages -- both are currently *ungradeable here*, and an ungradeable task
scores zero for every harness equally while costing full budget.

- *Java*: the corpus ships no JUnit Platform Console Standalone jar and the
  exercises assume a Gradle + Maven Central toolchain. `polyglot_tasks.load()`
  already skips Java unless such a jar is found under the corpus root. Including
  Java means either a network fetch inside a no-network task, or 10 guaranteed
  zeros. Re-include the moment a jar is vendored -- the loader picks it up
  automatically.
- *JavaScript*: grading uses `npx --no-install jest`, which requires
  `node_modules` already present in the exercise. The corpus is not
  pre-installed, and the task rules forbid installing packages, so the result
  depends on machine state: a populated cache grades, a clean machine returns
  `toolchain_missing:jest`. A check that varies by machine is not a check.
  Re-include once the corpus is vendored with dependencies installed offline.

Both exclusions are recorded in the run manifest so a reader sees what was left
out rather than inferring it from a task list.

### Split discipline

`dev` is where configurations are chosen. `holdout` confirms a configuration
already chosen, exactly once per claim, with the decision rule written down
first. If a holdout run disappoints and the configuration is then changed, the
next holdout run is a *new* holdout claim on a *new* split -- not a retry.

---

## 4. Cells

A **cell** is one configuration under test. One cell = one `battery.py`
experiment = one `proposal.json`. Every cell that has a fast-decisions arm
carries **its own contemporaneous `amplifier-plain` anchor at the same
generative model, inside the same experiment**, on the same workspaces, in a
randomly interleaved order. Cross-cell comparison is therefore always
ratio-to-own-anchor, never raw time -- machine drift, provider weather, and
time-of-day cannot masquerade as a mechanism effect.

Generative model default: `claude-fable-5-1` (pinned identically on both arms by
`--amplifier-model`, so a paired comparison can never silently compare two
models). Judge model default: `qwen3:0.6b` on `ollama`.

| id | harnesses in the experiment | model | judge | effort routing | model routing | purpose / control role |
|---|---|---|---|---|---|---|
| `plain` | amplifier-plain | fable-5-1 | -- | -- | -- | Reference series; run-to-run drift check across reps. No fd arm. |
| `judge-local` | plain + fd | fable-5-1 | ollama qwen3:0.6b | off | off | **Judge alone.** Isolates skip-the-model reads from every other mechanism. |
| `effort-only` | plain + fd | fable-5-1 | `unavailable` (off) | orient=medium, explore=low, implement=high | off | **Effort routing alone.** The control that stops "fd is faster" from being credited to the judge. |
| `judge-local+effort` | plain + fd | fable-5-1 | ollama qwen3:0.6b | all-phase | off | **Champion candidate.** Reproduces BASE+TUNE1 with controls. Minus `effort-only` = the judge's marginal contribution; minus `judge-local` = effort routing's. |
| `judge-jev+effort` | plain + fd | fable-5-1 | jev (external, opt-in) | all-phase | off | **Judge swap.** Differs from `judge-local+effort` in exactly one axis. Requires explicit external-state consent (section 10). |
| `judge-local+effort+route` | plain + fd | fable-5-1 | ollama qwen3:0.6b | all-phase | start `claude-sonnet-5`, escalate on request-count / test failure / provider error | **Model routing.** Confounded by construction unless read against `plain-sonnet`. |
| `plain-sonnet` | amplifier-plain | sonnet-5 | -- | -- | -- | **Mandatory control for the routing cell.** Answers "is this routing, or is it just sonnet-5?" Without it, no routing claim is admissible. |
| `externals` | claude + codex + opencode + plain + fd(champion) | fable-5-1 | champion config | champion | champion | **Q3.** All five harnesses, identical hashed workspaces, one interleaved schedule, `bypassPermissions` everywhere. |

Series labels in every report are built as
`<harness> [judge=<backend> <model>; effort <phase>-><effort>,...; model routing: on/off; model=<generative model>]`.
A label missing any of the four axes is a defect (R5).

**Cell ordering.** `plain`, `judge-local+effort`, and `externals` first -- they
carry Q1 and Q3. The isolation cells (`judge-local`, `effort-only`) next. The
routing pair (`judge-local+effort+route` + `plain-sonnet`) last and only
together; running the routing cell without its control produces an
uninterpretable number, so the runner treats them as one unit.

---

## 5. Run protocol

Per cell, per suite, per split, per repetition:

1. **prepare** -- freeze the candidate source into a detached worktree at the
   named sha; build one identical, content-hashed workspace per task per
   harness (prepare asserts the per-task workspace hashes match across
   harnesses); freeze the randomized schedule (tasks shuffled by seed, harness
   order independently shuffled within each task -- paired blocks); write
   `proposal.json` with the prompt hash, commands, permission mode, models,
   splits, and the frozen sha.
2. **verify** -- before any paid launch: prompt hashes identical across harnesses
   per task (R1); permission mode is `bypassPermissions` for every harness (R2);
   corpus sha matches the pin for S2; candidate sha matches the frozen sha;
   `forge doctor` green; required toolchains present for the languages in the
   split; budget reservation available. Any failure aborts **before spending**.
3. **run** -- serial. Exactly one timed run at a time
   (`max_parallel_timed_runs: 1`): a timed measurement that shares CPU, disk, or
   a provider rate limit with another timed measurement is not a measurement.
   Budget is reserved before each launch and settled after. Infrastructure
   failures get at most one retry, recorded as a retry.
4. **re-score** -- `battery.py reevaluate` recomputes quality and outcome
   deterministically from the preserved workspaces. Runs nothing, calls no
   model, costs nothing. This is the only sanctioned way to change a number
   after the fact (R6).
5. **evaluate** -- per-harness summary, per-task table, per-family table, paired
   fd-vs-plain comparison, mechanism report, evidence limits.
6. **report** -- `battery_report.py` across all cells and reps as labelled series.

**Repetitions.** 3 per cell per split, as three separate experiments with three
different seeds (`...-r1/-r2/-r3`). Different seeds mean different task order and
different within-task harness order, so an ordering artifact cannot survive all
three. Per-task time is aggregated across reps by **median** before the paired
comparison, so one pathological run cannot carry a cell.

---

## 6. Metrics and definitions

| metric | definition | notes |
|---|---|---|
| **working time** | first `llm:request` -> last `llm:response`, from native session events (amplifier); `duration_ms` (claude); first `step_start` -> last `step_finish` (opencode); wall time otherwise | the headline time metric; each result records which source was used |
| **startup time** | wall time - working time | reported separately, never folded into the headline (R7) |
| **penalized time** | working time when the run passed; the full deadline when it did not | prevents "fast because it gave up" |
| **cost** | provider/harness-reported USD where available; token x published-rate estimate for codex; not-billed-here for opencode | every figure carries `cost_source`; unknowns are counted, never zeroed |
| **cost per success** | total known cost / successful runs | `None` when any cost is unknown |
| **outcome_passed** | exit 0 **and** not timed out **and** zero failed hidden checks **and** every protected file byte-identical **and** workspace suite not failing **and** no infrastructure failure | one boolean, all-or-nothing |
| **provider requests** | count of `llm:request` events | the mechanism's most direct footprint |
| **deadline failures / retries** | counted and reported per harness | a deadline is not a completion (R6) |

Deadlines: 600 s (S1), 900 s (S2).

---

## 7. Mechanism gates

Each cell declares what its receipts must show. The runner asserts the
declaration against the aggregated `fast_decisions:*` receipts and fails the
cell when it does not hold.

| cell | gate |
|---|---|
| `judge-local` | `scored_by_backend["ollama"] > 0`; fallbacks not the majority of decisions |
| `effort-only` | total scored == 0 (judge genuinely off) **and** `effort_routed` present for `implement:high`. Blocked until the `battery.py` gate stops treating `backend: unavailable` as a refusing external backend -- see `SPEC-for-builder.md` section 6a |
| `judge-local+effort` | both of the above's positive halves |
| `judge-jev+effort` | `scored_by_backend["jev"] > 0` (the exact defect that shipped a fake Jev cell) |
| `...+route` | `model_routed_requested_models["claude-sonnet-5"] > 0`; **if escalations == 0**, the cell is flagged `confounded_with_plain_sonnet` and its claim is admissible only as a comparison against the `plain-sonnet` control |
| `plain`, `plain-sonnet` | no fast-decisions receipts at all (a plain arm emitting them means the profile leaked) |

A failed gate does not delete the run -- the numbers stay, marked
`mechanism_engaged: false` with the reason, excluded from claims, and visible in
the report. Silent exclusion would reproduce the original bug at the reporting
layer.

---

## 8. Statistics and decision rules

**Unit of comparison.** One task, one split, one cell -- fd arm against its own
in-experiment plain anchor, per-task time = median across reps.

**Aggregate.** Geometric mean of per-task ratios (time and cost). Significance:
exact two-sided binomial sign test over per-task win/loss, ties excluded.

**Quality.** Non-inferiority, not superiority: the fd arm's successes must be
at least (plain's successes - 1) on the split, **and** zero critical failures. A
critical failure is a protected file modified, an evaluator crash, or an
independent check the fd arm failed that plain passed on the same task and rep.
One critical failure disqualifies a cell regardless of its speed.

**A win (Q1/Q2) requires all of:**
1. mechanism gate green on **every** rep;
2. geometric-mean time ratio <= 0.90;
3. sign-test p <= 0.05;
4. cost ratio <= 1.00;
5. quality non-inferior as defined above;
6. at least 3 reps and at least 8 paired passing task pairs.

**Labels.**
- **screen** -- fewer than 3 reps, or dev-split only, or fewer than 8 paired
  passing pairs, or any gate amber. Screens may direct the next experiment.
  Screens are never reported as findings.
- **confirmed** -- the full bar above, on the **holdout** split, with the
  decision rule preregistered before the holdout ran.

**Q3 (vs external harnesses)** is reported descriptively -- per-task working
time, cost with provenance, success counts, and per-task speed rank -- with an
explicit statement of what is *not* matched: models differ by harness, external
working time may include their own startup, and OpenCode cost is not metered
here. No significance claim is made across harnesses on a single rep.

**Q4** is `confirmed` on S2 holdout, or it is not claimed.

---

## 9. Evidence limits

Generated from the run, appended to every report, never hand-written. At
minimum: task count per split; repetitions; which harnesses' cost is estimated
vs reported vs unmetered; which harnesses' working time may include startup;
whether models are matched across harnesses; which cells failed a mechanism
gate; which runs were re-scored and why; infrastructure retries and deadline
failures; and the suites' frozen shas.

Known limits of the design itself, stated up front:

- One machine, one account, one provider region. Nothing here generalizes to a
  different host without re-running.
- S1 tasks are small; a mechanism whose benefit scales with task length is
  under-measured by S1 and over-weighted in any S1-only conclusion.
- The judge's local backend requires a warm ollama; a cold model inflates the
  first runs of a cell. Warm before the batch, and keep the warm-up out of the
  measured window.
- External harness models are their configured defaults -- this benchmark
  measures *the harnesses as they are used*, not the models in isolation.

---

## 10. Budget and privacy policy

Reserve before every paid launch; settle after; refuse to launch when the
reservation would exceed the cap (`battery.py run` exits 3 rather than spending).
Per-launch reservation and total cap live in the campaign protocol. A cell that
exhausts budget mid-run stops cleanly and resumes later by adopting finished and
live workers -- never by relaunching completed work.

Preregister the budget for a claim *before* starting it. The 2026-09-18 campaign
ran out of budget before its holdout, leaving a selected configuration with no
selection-free confirmation -- that is a failed claim, not a partial one.

**External state.** The `judge-jev+effort` cell sends bounded task state to
typesafe.ai. It requires `--fd-backend jev --allow-external-state` together;
`battery.py prepare` refuses jev without the consent flag, by design. Run it only
against the synthetic S1 suite and the public S2 corpus -- never against private
workspaces. See docs/PRIVACY.md.

---

## 11. Out of scope

- Startup-time and system-prompt-size optimization. The 2026-09-18 data says
  these dominate the Amplifier-vs-Claude-Code gap, but they are not
  fast-decisions mechanisms. This benchmark **measures and reports** them
  (startup is a first-class separate metric) and does not attempt to fix them.
- Judge-quality evaluation in isolation (precision/recall of the scorer against
  labelled decisions). That belongs in `afast bench` (docs/BENCH.md), which is
  offline and free; this benchmark measures end-to-end task outcomes.
- Multi-machine, multi-account, or cross-region reproducibility.
- Java and JavaScript polyglot tasks, until gradeable offline (section 3).
- Any claim about a configuration that was not run under a green mechanism gate.


---

## 12. Decisions (2026-09-20)

Resolved open questions from the architect, applied in `cells.yaml`/`suites.yaml`/`run.py`:

1. **Contemporaneous anchor is per-batch, not per-cell.** A **repetition batch**
   is the selected cells for one (suite, split, rep), run back-to-back in a
   seeded random cell order, `plain` (or `plain-sonnet` for the routing pair)
   included as a cell. Each cell is still its own `battery.py` experiment,
   named `<cell>-<suite>-<split>-r<N>`; all experiments in a batch share
   `--candidate-sha` and the batch seed derives each experiment's seed
   (`base_seed + rep`) deterministically. A judge/effort/routing cell no
   longer carries its own embedded `amplifier-plain` harness -- it declares
   `anchor_cell` in `cells.yaml` and `run.py` compares it against that anchor
   cell's same-batch experiment via `battery.py evaluate --baseline-root
   --baseline-experiment` (an existing capability; no new measurement logic).
   `externals` is the one exception: it keeps its own embedded
   `amplifier-plain` harness because Q3 is a five-harness, single-interleaved
   comparison, not a batch-anchor comparison. The report compares within-batch
   by default; a report spanning more than one batch (multiple reps or splits)
   marks the cross-batch comparisons non-contemporaneous in its evidence
   limits.
2. **`bypassPermissions` for Claude Code on both suites (R2).** The old S1
   external-harness columns from the 2026-09-18 campaign (run under
   `acceptEdits`) are retired -- not comparable to anything produced under
   this design. `cells.yaml`'s external entries record `bypassPermissions`
   explicitly, never relying on `battery.py prepare`'s own per-task-source
   default.
3. **Repetitions are separate experiments, aggregated by the report.** Each
   rep is its own `battery.py` experiment with its own seed
   (`base_seed + rep`). `battery_report.py` runs once across every produced
   series (one call, `--series` per (cell, rep, harness)); it does its own
   per-task aggregation across the series it's given. `run.py` does not
   compute a median itself -- that would be new measurement logic banned by
   section 0's hard constraint. If per-rep aggregation into a single number
   per task is needed beyond what one `battery_report.py` invocation already
   produces, that aggregation belongs in `battery_report.py`, not `run.py`.
4. **The incumbent vs. the candidates.** `judge-local+effort-incumbent`
   (`explore_only`: explore->low only) represents Amplifier's already-shipped
   fast-decisions default and is a reference series, not a candidate under
   evaluation. `judge-local+effort` (`all_phase`: orient/explore/implement)
   is the champion **candidate**. Both model-routing cells
   (`judge-local+effort+route`, `plain-sonnet`) are candidates, not defaults.

---

## 13. Decisions (2026-09-20b) -- results verdict layer, cross-rep aggregation, design bridge

Resolved as part of completing `evals/run.py` end to end and adding
`evals/DESIGN-BRIDGE.md`. Applied in `battery_report.py`, `evals/run.py`,
`evals/cells.yaml`, `evals/suites.yaml`.

1. **Cross-repetition aggregation lives in `battery_report.py`, not `run.py`.**
   `--aggregate-reps "<label>=<root>:<exp1>,<exp2>,...:<harness>"` loads the
   same task set across the listed experiments and combines them into one
   series: per task, median exec time / median cost across reps where the
   task passed, and pass = majority vote (a tie counts as not-passed). Feeds
   `report.json["reps_summary"]`: per-task per-rep pass/exec, median,
   dispersion (IQR), and per-series consistency (share of tasks with an
   identical pass/fail outcome across every rep). This is a report-time
   convenience for humans reading `report.md`; it does **not** replace the
   verdict layer below, which operates on `battery.py`'s own per-rep
   `comparison.json` cross-campaign data, not on `battery_report.py`'s
   aggregated series.

2. **A results -> verdict layer in `evals/run.py`, superseding the simpler
   `RESULTS.md` described in `SPEC-for-builder.md` section 8.** After the
   report step, `run.py` writes `<out>/results.json` and `<out>/RESULTS.md`:
   per candidate cell (every cell with an `anchor_cell`), a verdict row with
   passed/total, an exec-time geometric-mean ratio with a bootstrap 95% CI
   (stdlib `random.Random`, fixed seed, 2000 resamples of per-task log-ratios,
   median-aggregated across reps first per section 5's rule), the exact
   sign-test p (reusing `battery._sign_test`, not re-derived), cost ratio
   (billable only, unknowns annotated), quality delta, mechanism gate result,
   and a verdict in `{confirmed, screen, gate-failed, quality-regressed,
   no-effect}` per section 8's bar, now made explicit and code-implemented
   (see `evals/run.py::classify_verdict`). A Q3 table (the champion cell vs
   every external harness in the `externals` cell) and a Q4 section (rows
   whose split is `holdout`) are included when present. This is new
   computation in `run.py` beyond section 0's original "no new runner logic"
   constraint -- justified because every input number is still read from
   `battery.py`'s own `comparison.json` (the cross-campaign anchor comparison
   or the same-experiment paired comparison), and the bootstrap/verdict code
   is itself pure and unit-tested, not a new *measurement*.

3. **A results -> design-bridge recommendation.** `evals/DESIGN-BRIDGE.md`
   states, per bundle knob (`mode`, judge backend default, `effort_routing`
   default, `model_routing` default, external-state policy), the decision
   rule, the evidence required, and the current default. `run.py` writes
   `<out>/DESIGN-RECOMMENDATION.md` by applying those rules to one
   `results.json`, marked "for human ratification" -- it recommends, it does
   not flip any config.

4. **The routing cell gets an optional `secondary_anchor`.**
   `judge-local+effort+route` now also declares `secondary_anchor: plain` in
   `cells.yaml`. `run.py` performs one extra, read-only `battery.py evaluate
   --baseline-experiment <plain's same-batch experiment>` call per rep (no new
   paid launch: `evaluate` is a pure recompute from already-collected result
   files), then re-runs the primary `evaluate` against `anchor_cell`
   (`plain-sonnet`) so the persisted `comparison.json` on disk is left exactly
   as the primary flow set it. This lets the recommendation distinguish
   "beats plain-sonnet" (routing pays; recommend `on`) from "beats plain but
   not plain-sonnet" (the gain is just the cheaper model; recommend pinning
   it, not routing) -- the literal case `SPEC-for-builder.md` section 14
   calls out.

5. **Reps defaults, made explicit and declarative.** `evals/suites.yaml` gets
   a top-level `reps_defaults: {dev: 3, holdout: 5}` (applies to both S1 and
   S2). `--reps` on the CLI always overrides it. `run.py`'s `--reps` CLI
   default changes from a hardcoded `1` to `None`, resolved against
   `reps_defaults` at invocation time. Rationale: cost is not the constraint
   here, study quality is (section 8's bar already requires >= 3 reps for any
   claim; holdout confirmation gets 5 for a tighter CI given it is the
   one-shot, never-tuned-on pass).

6. **Exit 3 and exit 6, made concrete.** Exit 3 (budget/launch-cap refused,
   propagated from `battery.py`) now also writes a **partial** manifest and
   gates file before returning, with placeholder entries for cells not yet
   reached, specifically so `--resume` has something to read; the reason
   string is normalized to `budget_refused: <detail>`. Exit 6 (new): on
   `--resume`, after the run step, every planned experiment is scanned
   (`scan_incomplete_runs`) for a run with no `result.json` and no live
   `running.json` worker (checked via `os.kill(pid, 0)`); if any remain, `run.py`
   exits 6 with the list rather than reporting success on an incomplete batch.

---

## 14. Judge head-to-head (2026-09-20c)

`Policy.model_routing.escalation_judge` and `Policy.effort_routing.phase_judge`
(HC05, `orchestrator._ask_judge_choice` -- see `docs/ARCHITECTURE.md`) let the
CONFIGURED judge backend, not just deterministic rules, make a decision. This
section adds the cells needed to compare the two judges -- local `ollama
qwen3:0.6b` vs `jev` (typesafe.ai) -- across every mechanism arm where the
judge participates, and specifically on the ONE decision that actually
carries speed: whether to escalate off the cheap model.

**The factorial.** `judge ∈ {local, jev}` × `arm ∈ {read-shortcut only,
+effort incumbent, +effort all-phase, +effort all-phase phase-judged,
+route rules-escalation, +route judge-escalation}`. Each `arm` for `judge=jev`
is a twin of its `judge=local` cell, identical in every axis except the
backend (and, for the two `+route*` pairs, `allow_external_state: true`,
required for `jev`):

| local cell | jev twin | arm |
|---|---|---|
| `judge-local` | `judge-jev` | read-shortcut alone |
| `judge-local+effort-incumbent` | `judge-jev+effort-incumbent` | today's shipped default (explore:low) |
| `judge-local+effort` | `judge-jev+effort` | all-phase effort routing (already existed) |
| `judge-local+effort-phasejudged` | `judge-jev+effort-phasejudged` | all-phase, judge classifies the phase |
| `judge-local+effort+route` | `judge-jev+effort+route` | model routing, rules escalation |
| `judge-local+effort+route-judged` | `judge-jev+effort+route-judged` | model routing, JUDGE escalation |

**The paired comparison rule.** Each `judge=jev` cell is read against its
`judge=local` twin on the SAME tasks/reps (both cells run in the same
repetition batch, same seeds, same task order -- section 12 Decision 1): a
time ratio (geometric mean, with the bootstrap 95% CI already computed by
`evals/run.py`'s verdict layer) and its CI, a quality delta (non-inferiority,
section 8's definition), the mechanism gate (`mechanism_engaged` for both,
`judged_engaged` for the two judged cells -- see below), and decision latency
p95 from `comparison.json["mechanism"]["decision_latency_ms_p95"]`,
per-backend via `decision_latency_ms_by_backend`. This is a plain re-use of
`battery.py evaluate`'s existing anchor-comparison machinery pointed at a
NEW baseline (the twin cell's same-batch experiment, not just the shared
`plain`/`plain-sonnet` anchor) -- no new measurement logic, matching section
12 Decision 1's `--baseline-root`/`--baseline-experiment` pattern.

**The decisive pair.** `judge-local+effort+route-judged` vs
`judge-jev+effort+route-judged` is what actually answers "which judge should
decide escalation": both hand the escalate-or-not call (the mechanism that
determines whether a turn stays cheap or moves to sonnet-5, i.e. the one
thing in this whole benchmark that visibly trades speed for capability) to
the judge, via `model_routing.escalation_judge: "judge"`
(`model_routing_profiles.sonnet_start_judged` in `cells.yaml`). Each also
carries a `secondary_anchor` at its own RULES-escalation twin
(`judge-local+effort+route` / `judge-jev+effort+route` respectively), so a
report can show, per judge, whether letting it decide escalation beat that
same judge's own deterministic-rules configuration -- not just whether it
beat `plain-sonnet`.

**Mechanism gate: `require_judged`.** A cell with `escalation_judge: "judge"`
or `effort_routing.phase_judge: true` declares `mechanism_gate: {..., 
require_judged: true}`. `scripts/battery.py`'s `_mechanism_report` now
computes `judged_engaged` (`true`/`false`/`null`) and `judged_reason`: `null`
when the cell's own config configures neither mechanism (not applicable);
`false` when the configured judge mechanism produced zero
`escalation_judged`/`phase_judged` receipts, OR when any of those receipts
were answered by a backend OTHER than the cell's `configured_backend` (the
same class of defect R4 already guards for `scored`/`model_routed` -- a
judged cell whose judge silently never fired, or fired against the wrong
backend, must not be credited); `true` otherwise. This is the DATA half of
the gate. **The wiring of `require_judged` into `evals/run.py::gate_eval` is
NOT yet done** -- `run.py` was out of scope for this change; `gate_eval`
should read `mechanism.get("judged_engaged")` the same way it already reads
`mechanism.get("mechanism_engaged")`, once that file is in scope.

**The decision rule (fed to `DESIGN-BRIDGE.md` rule (d2)).** Jev becomes the
default judge for `escalation_judge`/`phase_judge` ONLY if, across the arms
where the judge's OWN decision determines behavior (`+route-judged`,
`+effort*-phasejudged`), the jev cell wins-or-ties on time against its local
twin, quality is non-inferior, its mechanism gate (including
`judged_engaged`) is green on every rep, AND `jev`'s decision-latency p95 is
under 500 ms (the same bar `DESIGN-BRIDGE.md` rule (b) already sets for the
read-shortcut judge) -- a judge slow enough to erode the time it was meant to
buy is not a win merely because its answer was "better". Otherwise `local`
(`ollama qwen3:0.6b`) remains the default for both HC05 knobs, independent of
whatever rule (b) concludes for the read-shortcut judge alone -- the two are
evaluated separately because a judge that reads well for a cheap read/list
choice is not automatically the right judge for a decision that changes
which model serves the rest of the turn.

**Budget.** `cells.yaml`'s `budget.estimated_total_usd` is raised to `1500`
and `max_benchmark_worker_launches` to `2000` to cover the 8 new cells (7 new
`judge-jev*`/`*-judged`/`*-phasejudged` cells plus their batch-anchor
overhead) across S1 and S2, dev and holdout, at the existing 3/5-rep
schedule (section 13 Decision 5) -- cost is not the constraint here, study
quality is.


---

## 15. S3 -- SWE-bench Verified slice

**What.** A third task suite, alongside S1 and S2 (section 3), built on the
Amplifier evaluation bundle's own DTU harness (`amplifier-evaluation` /
`amplifier_evaluation.harness`) rather than this repo's in-process battery
runner -- SWE-bench Verified needs a real repo checkout, a real Docker-based
grader (the official `swebench` harness), and a real Amplifier CLI install
inside a Digital Twin Universe, none of which S1/S2's synthetic/polyglot
task shape requires. Lives entirely under `evals/swebench/` (see that
directory's README.md for the full preflight/run/sanity-check protocol; this
section records the study-design decisions, not the operational detail).

**Slice.** 30 pinned `princeton-nlp/SWE-bench_Verified` (test split)
instances, sampled with `--seed 42` (reproducible; `sample_swebench.py`
re-samples deterministically if a pinned id ever fails to resolve against
the live dataset -- see that script's `select_batch()`). No dev/holdout
split for S3 at this stage: S1/S2 already carry the dev-vs-holdout
discipline (section 3 "Split discipline") for choosing and confirming a
configuration; S3's role is a single confirmatory slice on a held-out
benchmark family, not a second place configurations get chosen.

**Three variants, not S1/S2's two-arm (fd vs plain) shape:**

| variant | composition | role |
|---|---|---|
| `amplifier-plain` | amplifier-foundation @ main, no fast-decisions bundle | baseline |
| `amplifier-fd-incumbent` | foundation + fast-decisions ACTIVE, configured as `evals/cells.yaml`'s `judge-local+effort-incumbent` (local judge + `explore: low` effort routing only) | today's shipped default -- reference series, not a candidate under evaluation (same framing `cells.yaml` already gives that cell for S1/S2) |
| `amplifier-fd-candidate` | foundation + fast-decisions ACTIVE, configured from `evals/swebench/candidate.config.json` -- the S1/S2 **confirmed** champion cell (section 8's decision rule) | the configuration actually under evaluation for S3 |

`amplifier-fd-candidate`'s configuration is never hand-picked while building
the S3 harness: `candidate.config.json` ships as a placeholder
(`status: "unconfirmed"`, all of `backend`/`model`/`effort_routing`/
`allow_external_state` null) and `swebench_stage.py::render_candidate_install_yaml`
refuses to render its agent definition until that file is filled in from a
`confirmed` S1/S2 result and `status` is flipped to `"confirmed"`. This
keeps S3 a confirmatory run of a decision already made on S1/S2, not a venue
for choosing one.

**Grading.** The official SWE-bench Docker harness (`swebench.harness.run_evaluation`),
via `evals/swebench/grade.py` (copied from the evaluation bundle's example 04
helper, attribution preserved, default `--dataset` switched to `verified`).
`resolved` is binary per instance -- every `FAIL_TO_PASS` test passes and
every `PASS_TO_PASS` test still passes, or it does not -- matching this
document's own `outcome_passed` philosophy (section 6: "one boolean,
all-or-nothing") rather than partial credit.

**Result rows.** `evals/swebench/summarize.py` converts one harness run's
`summary.json` + trial directories into rows using this repo's own battery
vocabulary (`task`, `harness`, `outcome_passed`, `exec_time_ms`,
`exec_time_source`, `cost_usd`, `cost_source`) so an S3 row is recognizable
next to an S1/S2 row. `scripts/battery_report.py` is out of scope for this
change (it reads a campaign/manifest.json layout this harness does not
produce) -- `summarize.py` produces a compatible row shape for a future
bridge, not a drop-in feed into that report today. `exec_time_ms` for S3
currently equals the trial's whole-lifecycle `elapsed_s` (launch through
cleanup): the harness's `summary.json` does not separately timestamp
`running_agent` alone today, only `state.json`'s per-stage `history` does --
see `summarize.py`'s module docstring for the exact caveat and where a
future narrower figure would come from. `cost_usd` is `null` with
`cost_source: "unknown"` unless a `"cost_usd"` figure is recoverable from a
trial's `ai_user.json` artifact -- most AI User backends do not surface one
today, matching this document's own "unknowns are counted, never zeroed"
principle (section 6) rather than estimating from tokens the way S1's codex
cost figure does (that estimate is codex-specific pricing; nothing
equivalent exists for an Amplifire-CLI-driven turn here).

**Why serial, not parallel.** SWE-bench tasks take 10-40 minutes each
(agent turn + the official harness's per-instance Docker test run,
including a per-instance image pull). S3 runs are dispatched later, one
batch at a time, from a queue -- never launched directly by whatever agent
built this stage, and never run concurrently with another S3 batch on the
same host (shared Docker daemon). `evals/swebench/run.sh` defaults
`MAX_PARALLEL=1` for this reason; raising it is an explicit operator
decision made at dispatch time, informed by the host's actual Docker
capacity, not a default this stage sets for them.

**Decision rule for S3.** S3 does not itself decide whether
`amplifier-fd-candidate`'s configuration "wins" -- that decision is S1/S2's
(section 8), already made before `candidate.config.json` is filled in. S3
answers a narrower question: does the S1/S2-confirmed configuration hold up
on a held-out, real-world, Docker-graded benchmark family neither S1 nor S2
can exercise (a live repository, a live test suite, no independent oracle
written for this study)? A confirmed S1/S2 win that regresses on S3 --
strictly fewer `swebench-resolved` passes than `amplifier-fd-incumbent` on
the same 30 instances, or fewer than `amplifier-plain` -- is reported as a
regression on this specific slice, not silently absorbed into the S1/S2
confirmed claim.
