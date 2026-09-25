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

---

## 16. Decomposed escalation signals and tool-risk shadow classification (2026-09-22)

**HC10 -- decomposed escalation signals.** `judge-local+effort+route-decomposed`
(local judge, routing, `escalation_judge: decomposed`; anchor `plain-sonnet`,
secondary_anchor `judge-local+effort+route-judged`) and its jev twin
`judge-jev+effort+route-decomposed`. **Hypothesis:** combining five atomic
yes/no signals (`plan_derailed`, `repeated_tool_errors`, `tests_failing`,
`unfamiliar_code`, `beyond_tier`) in code via a weighted sum keeps or
improves completed-task quality while reducing false escalations, compared
to trusting a single judged "should we escalate?" verdict (HC05's
`escalation_judge: judge`) -- the same rationale independent Jev audits
report for atomic signal decomposition generally (section 14's framing
extended to escalation itself, not just the read-shortcut). **Mechanism
gate:** `fast_decisions:escalation_signals` receipts present
(`require_judged: true`, reusing the same `judged_engaged` computation
section 14 defines for `escalation_judged`/`phase_judged` -- an
`escalation_signals` receipt satisfies it identically). **Kill criterion:**
quality drop on the dev split, or a false-escalation rate (escalations
where the eventual outcome did not need the stronger model) that is not
strictly better than the `-judged` twin's.

**Decisive comparison.** `judge-local+effort+route-decomposed` vs
`judge-local+effort+route-judged` (and the jev pair identically) answers
"does decomposing the verdict into signals combined in code beat trusting
the model's own combined judgment?" -- both hand the escalate-or-not call
away from pure deterministic rules, differing only in HOW the judge's
signal is used (one combined choice vs five independent probabilities
weighted in code). This is a plain re-use of `battery.py evaluate`'s
existing anchor-comparison machinery pointed at the `-judged` twin's
same-batch experiment, per section 12 Decision 1's pattern -- no new
measurement logic.

**Decision rule (fed to `DESIGN-BRIDGE.md`).** Decomposed escalation
becomes the recommended `escalation_judge` mode ONLY if it wins-or-ties on
time against its `-judged` twin, quality is non-inferior, its mechanism
gate is green on every rep, AND its false-escalation rate is strictly
lower than the `-judged` twin's on the dev split. Otherwise `"judge"`
(HC05's single verdict) remains the recommended judged mode, independent
of whatever `escalation_weights` tuning might separately be explored.

**HC11 -- tool-risk shadow classification.** `judge-local+effort-incumbent-riskshadow`
(`tool_risk_shadow: true`, otherwise identical to the incumbent
`judge-local+effort-incumbent`; anchor `plain`, secondary_anchor
`judge-local+effort-incumbent`). **Purpose:** measure the wall-clock cost
of asking a batched `destructive` / `touches_production` / `category`
classification before every tool call (extra backend round-trips on the
tool-execution critical path), and collect `fast_decisions:tool_risk`
receipts as labeled data for a future deny/ask evaluation -- this cell
does NOT itself evaluate whether tool-risk classification should ever gate
execution; it only measures overhead and gathers labels. **Mechanism
gate:** identical to the incumbent's (`scored_backend: ollama, min_scored:
1, require_effort_phases: ["explore:low"]`) -- `tool_risk_shadow` never
changes what gets scored or how effort routes, only whether an additional,
non-authoritative classification receipt is also emitted. **Kill
criterion:** none -- this is a cost-measurement and label-collection cell,
not a candidate under evaluation; it is reported alongside the incumbent's
own numbers, never compared for a win/loss verdict.

**Budget.** `cells.yaml`'s `budget.estimated_total_usd` is raised to `1800`
and `max_benchmark_worker_launches` to `2400` to cover the 3 new cells (2
`*-decomposed` twins plus the 1 `*-riskshadow` reference cell) across S1
and S2, dev and holdout, at the existing 3/5-rep schedule (section 13
Decision 5).


## 17. Runner throughput: campaign-root split and bounded parallel timed runs (2026-09-22)

Two operational fixes to `scripts/battery.py` / `evals/run.py` so the
remaining formal-stage runs finish faster and stop crashing. Neither changes
any measurement: no new number in `results.json`/`comparison.json` originates
here, only how fast and how reliably the existing numbers get collected.

### 17.1 Path-length defect (the six-hour outage)

Amplifier names its per-project session dir by encoding the resolved
workspace path 1:1 (`/` -> `-`) under `~/.amplifier/projects/`. The formal
driver nests a run's workspace at
`<out>/campaign/experiments/<cell>-<suite>-<split>-r<N>/runs/amplifier/
<cell>-<suite>-<split>-r<N>-<task>-<harness>-a<N>/workspace`, and `<out>`
itself is a long, timestamped path
(`<repo>/.amplifier/evaluation/fast-decisions/<ts>-s1-dev`). For
fast-decisions cells this encoded to 282 characters -- over macOS's 255-byte
`NAME_MAX` -- and every such run died before it ever launched
(`OSError: [Errno 63] File name too long`, surfaced by the receipts collector
as `no_result_json`). Plain cells encoded to 239 and ran; this made the
defect invisible until a fast-decisions-heavy stretch of the batch hit it,
six hours in.

**Fix.** `evals/run.py` gained `--campaign-root DIR` (default
`~/dev/afast-ev/<basename of --out>`, created on first use): the campaign
(experiments/runs/workspaces/receipts) now lives there instead of nested
under `--out`. `--out` keeps only `manifest.json`, `gates.json`,
`preflight.json`/`prompt-verification.json`, `campaign-proposal.json`, and a
`campaign-root.txt` pointer recording where the campaign actually lives
(`resolve_campaign_root`, `default_campaign_root`). The split is idempotent
across `--resume`/`--report-only`: the pointer file is authoritative once
written, and a campaign that already exists directly under
`<out>/campaign` (pre-dating this change) is adopted in place rather than
orphaned.

A new preflight check, `workspace_path_length` (`check_workspace_path_length`
in `evals/run.py`, reusing `battery.run_dir_for` rather than re-deriving the
path so the check can never drift from what `battery.py` actually builds),
computes the exact workspace path for every planned run in the frozen
schedule and fails loudly (precondition failure, the existing exit-4 path)
if any encoded length exceeds 240 bytes -- naming the offending run and its
length. `preflight.json` records `max_encoded_len` (both at the top level and
inside the check) on every invocation, pass or fail, so the margin is always
visible, not just at the moment it's finally exceeded.

**Measured margin under the new default.** For suite s1 (the 20-task
battery), the specific worst case named when this fix was scoped --
`judge-jev+effort+route-judged-batched`, longest task name
(`bugfix_average_score_truncation`), harness `amplifier-fd`, attempt 1 --
encodes to 238 characters: under the 240 limit. A broader scan across every
cell in `cells.yaml` finds one cell with a longer id,
`judge-local+effort+route-judged-batched` (39 vs. 37 characters), which
pushes the same task/harness/attempt combination to 242 -- 2 over. Closing
that residual 2 characters would mean shortening the on-disk directory name
independently of the manifest run key (e.g. dropping the redundant
`<experiment>-` prefix `_run_dir_for` currently repeats even though the run
already lives under `experiments/<experiment>/...`), which requires the
amplifier-side run id and the outer manifest key to diverge -- a coupled
change against `forge_e2e.py`'s own sub-manifest that deserves its own
dedicated, separately-tested change rather than a rushed addition here. Until
that lands, the `workspace_path_length` preflight check is the backstop: a
plan that would exceed the limit is refused in under a second, before any
worker launches -- not discovered six hours into a run.

### 17.2 Bounded parallel timed runs

`scripts/battery.py run` launched every run strictly one at a time. It now
accepts `--parallel N` (default 1, byte-identical to the prior sequential
behavior): a bounded scheduler keeps up to `N` dispatches in flight through a
thread pool, launching the next run as soon as a slot frees. Every ledger
append and manifest write still happens on the main thread alone
(single-writer), so the reservation/budget/launch-cap/retry bookkeeping is
exactly as correct as it was before parallelism existed -- only the blocking
wait on Forge or an external harness process overlaps. `--parallel` is
refused outright if it exceeds `protocol.limits.max_parallel_timed_runs`
(itself sourced from `cells.yaml`'s `budget.max_parallel_timed_runs`, plumbed
through `campaign.py init` since HC's original wiring). `evals/run.py` gained
a matching `--parallel N` flag, plumbed to every `battery.py run` invocation.

Because the frozen schedule already groups every harness for a given task
consecutively in `run_order` (`cmd_prepare`'s own construction: outer loop
over shuffled tasks, inner loop over shuffled harnesses), the scheduler
never needs to reorder anything to keep a task's paired runs (e.g.
`amplifier-plain` and `amplifier-fd`, or a candidate and its anchor) launching
in the same wave -- preserving that adjacency is what "matched scheduling"
means here, and it falls out of not skipping ahead in `run_order`.

Every result now carries two additional integer fields:
`concurrency_at_launch` (how many runs, including itself, were in flight the
instant it launched) and `concurrency_max` (the peak in-flight count observed
at any point during its life -- updated as later runs join the same window,
not just at launch). At `--parallel 1` both are always `1`.

**Validity conditions for shared-machine timing (why raising
`max_parallel_timed_runs` from 1 to 3 is sound, not just convenient).**
Measured wall time for a timed run is 93-95% remote provider round-trip
spans, not local compute -- so up to 3 runs may share the machine without the
measurement becoming noise:

- Judge decision latency p95 (from `fast_decisions:*` receipts) must stay
  under 200ms under load; this is measured and reported per cell, not
  assumed.
- Absolute times (e.g. an isolated cell's mean wall-clock) carry a load
  caveat when collected under `--parallel > 1` -- they are not a clean
  cross-run comparison point.
- Relative comparisons *within a wave* (the pairs that actually launched
  together, sharing the same load) remain valid: the release gate always
  uses quality plus matched relative time from the same wave, never an
  absolute time compared across waves collected under different load.

`cells.yaml`'s `budget.max_parallel_timed_runs` is raised to `3` on this
basis (previously pinned at `1` with a "never raise this" comment written
before this section's validity conditions existed to justify raising it).

## 18. Orchestrator-primary: factorial design, harder suites, power (2026-09-24)

Context: [docs/ORCHESTRATOR-PRIMARY.md](../docs/ORCHESTRATOR-PRIMARY.md). The
bundle now replaces the host orchestrator by composition, and its default is
routing-only (no judge). The first screen (S1 dev, 1 rep,
`~/dev/afast-orch-primary-20260924/screen-s1-dev`) showed:

| Cell | vs | Time ratio (95% CI) | Cost ratio | Quality |
|---|---|---|---|---|
| orch-primary | plain | 0.48 [0.40, 0.57] | 0.79 | 12/12 vs 12/12 |
| orch-primary | plain-sonnet | 0.81 [0.57, 1.03] | 1.83 | 12/12 vs 12/12 |
| orch-primary-effort-only | plain | 0.77 [0.66, 0.89] | 1.11 | 12/12 vs 12/12 |

These are screens (section 8), not findings. They surfaced three design
problems that this section fixes.

### 18.1 The start model is a confound, so the design is factorial

Most of orch-primary's gain over `plain` belongs to the start model
(`claude-sonnet-5`). `plain-sonnet` alone is 0.59x `plain`. On S1 the routed
runs never escalated (`flag: confounded_with_plain_sonnet`), which makes
orch-primary there equal to "plain-sonnet + effort routing". The question the
product has to answer is not "faster than plain?" but **which component buys
what**. Every orchestrator-primary study is therefore run as a factorial over
the three mechanisms. The model is held fixed within each contrast.

| Factor | Levels | Cells that isolate it |
|---|---|---|
| start model | fable, sonnet | `plain` vs `plain-sonnet` |
| phase effort routing | off, on | `plain` vs `orch-primary-effort-only` (fable) |
| escalation (sonnet start -> host model) | off, on | `plain-sonnet` vs `orch-primary` |

The claims map onto the contrasts as follows. A "routing makes Amplifier
faster" claim needs the effort contrast. A "cheap-first with escalation keeps
quality" claim needs the escalation contrast **on a suite where quality
varies**. Only the model contrast justifies saying "switching models is
faster", and that is not a claim about this bundle.

### 18.2 A ceiling suite cannot test quality, so SWE-bench is required

On S1 every cell passed 12/12. Non-inferiority on S1 is vacuous: it cannot
detect a quality cost from starting on a cheaper model. Quality claims for
orchestrator-primary require S3 (SWE-bench Verified) with the official Docker
grader: `evals/swebench/forge_swebench.py`. That script is a Forge-driven
runner. Agents work in real checkouts and run tests through `.swe/run`
inside the same instance image the grader uses, and the patch is graded by
`swebench.harness.run_evaluation` (swebench 4.x). The quality endpoint is the
resolved rate, with McNemar's exact test on paired resolved/unresolved
outcomes per instance. It replaces the S1/S2 "successes - 1" margin there.

### 18.3 Power: size the study for the contrast that matters

Per-task log-ratio SDs measured in the screen give the pairs needed for 80%
power (alpha 0.05, two-sided, paired):

| Contrast | SD(log ratio) | To detect the observed effect | To detect 0.90x |
|---|---|---|---|
| orch-primary vs plain-sonnet | 0.54 | ~55 pairs (effect 0.81x) | ~210 pairs |
| effort-only vs plain | 0.28 | ~10 pairs (effect 0.77x) | ~55 pairs |
| orch-primary vs plain | 0.33 | ~2 pairs (effect 0.48x) | ~76 pairs |

So:
- The effort-routing effect on a fixed model is cheap to confirm: 12 tasks
  x 3 reps on the S1 holdout, preregistered.
- orch-primary vs plain-sonnet needs roughly 20 tasks x 3 reps. It is
  underpowered on the 12-task dev split at 1 rep, and its CI (0.57-1.03)
  crosses 1.
- A 1-rep screen is never reported as a finding (section 8, unchanged).

### 18.4 Cost accounting must include the cache

The one SWE-bench check that escalated (django__django-13741) was the fastest
arm but the most expensive: $1.33, against $0.98 for plain and $0.63 for
plain-sonnet. A likely cause is that switching models mid-turn discards the
prompt-cache prefix and writes it again on the new model. Reports therefore
break cost into cache-write, cache-read, input and output tokens per model.
Any escalation design change (e.g. escalating only at turn boundaries) is its
own cell, measured against this one.

### 18.5 Isolation invariants (each learned from a failed run)

- **Per-run events dir.** Receipts are read from `run/events`, never from the
  shared `~/.amplifier/fast-decisions/events`. The shared dir's 100k-record
  window silently dropped whole sessions.
- **No user app bundles in the workspace** (`settings.local.yaml: bundle.app: []`).
  Record a hash of `~/.amplifier/settings.yaml` at campaign start and refuse
  to continue if it changes. The native three-arm study died from a
  mid-run settings change.
- **Composition proof.** Composed cells never name the orchestrator module.
  A `model_routed` or `effort_routed` receipt is the proof that composition
  performed the swap, and `effective-loop-config.json` records the config.
- **Completion is `result.json`, never a Forge observation.** Forge's
  `run_command` returns after about 60 s while the process keeps running.
- **Patches are captured through a private git index.** An agent-left
  `.git/index.lock` once turned a real edit into an empty patch.

### 18.6 Next runs, in order

1. **S3 screen**: 10 instances x {plain, plain-sonnet, orch-primary} x 1 rep
   (running). It tells us whether escalation preserves the resolved rate and
   what it costs.
2. **S1 holdout, preregistered**: {plain, orch-primary-effort-only} x 8
   tasks x 5 reps. Confirms or kills the effort-routing effect on a fixed
   model.
3. **S3 dev, 3 reps, 20 instances**: {plain-sonnet, orch-primary, plus a
   turn-boundary-escalation cell}. This is the escalation contrast at the
   power 18.3 requires.
4. **S3 holdout, preregistered**: the survivor of step 3 against its controls.

### 18.7 Turn-start difficulty router (2026-09-24)

**Finding that motivated it.** On the S3 screen (10 SWE-bench Verified instances, 1 rep, official
grader), cheap-first routing reversed its S1 advantage:

| Arm | Resolved | Median exec | Total cost |
|---|---|---|---|
| plain (fable) | 7/10 | 122 s | $12.58 |
| plain-sonnet | 5/10 | 163 s | $17.86 |
| orch-primary (sonnet first, escalate after 6 requests) | 8/10 | 179 s | $18.51 |

Every complex instance followed the same pattern: 6 sonnet requests, then `max_requests` escalation.
Each model switch, and each effort change, re-wrote the ~37k-token conversation cache (Anthropic
invalidates the message cache when thinking or model parameters change). Escalation preserved quality
but cost 1.2x plain's time and 1.4x its cost.

**Design.** Decide model and effort once per turn, before the first provider call. This is
RouteLLM-style routing by query difficulty (Ong et al., ICLR 2025, arXiv:2406.18665), adapted to an
agent loop:
- `model_routing.start_policy: judge` asks one typed simple/complex question.
- A simple turn gets the cheap model at a single effort (`effort_routing.by_tier.cheap`).
- A complex turn gets the host model at provider-default effort, i.e. exactly plain, with no mid-turn
  switch.
- Judge failure falls back to a prompt-length rule.

The configuration unit is the turn, not the query, because the cache must stay stable across the
turn's requests.

**Offline judge evidence** (`evals/difficulty/probe.py`): SWE-bench Verified human difficulty labels,
45 "<15 min" vs 45 ">=1 h", plus 20 S1 prompts.

| Judge | AUC (SWE difficulty) | Latency p50 |
|---|---|---|
| Jev jev-1.13.0 | 0.83 | 156 ms |
| local qwen:latest (29 GB), typed question, permutation-debiased | 0.85 | ~1–2.5 s |
| local glm-4.7-flash | 0.76 | 0.5 s |
| local llama3.1:8b | 0.70 | 0.46 s |
| prompt-length rule | 0.60 | 0 |
| local qwen3:0.6b | 0.54 (chance) | 60 ms |

This required new capability: the local one-token backends previously refused typed questions
outright. They now answer choice and noul questions from first-token option-letter mass, averaged over
forward and reversed option order.

**Live test (running):** `swe-router10` runs {plain, orch-router-jev, orch-router-local} on the same 10
instances, with a contemporaneous plain anchor. S1 dev with `orch-router-jev` follows. The hypothesis to
confirm at >=3 reps:
- Router quality >= plain on S3.
- Router time <= plain on S3 and ~= plain-sonnet on S1.
- Router cost <= orch-primary everywhere.

### 18.8 Three-rep S3 result and the scope gate (2026-09-24)

S3, 10 instances x 3 reps, router judged by Jev vs a contemporaneous plain anchor:

| | plain (fable) | orch-router-jev |
|---|---|---|
| resolved | **23/30** | **19/30** |
| time vs plain (geomean, 30 pairs) | 1.00 | 0.86 (cheap-routed turns 0.75, strong-routed 0.98) |
| cost vs plain | 1.00 | 0.91 |

There were 4 discordant pairs, all favouring plain (McNemar exact p = 0.125). That is not significant,
but it **fails the non-inferiority bar** (section 8: successes >= plain - 1). Two instances account
for all four:
- **django-11532** (human label "15 min - 1 hour"). Jev judged it simple (p = 0.05) in every rep.
  Sonnet started, escalated to fable after 6 requests, and the run still failed 2 of 3. The cheap
  model's early trajectory misdirected the fix, and escalation did not recover it.
- **pytest-10356.** Routed strong, so the config is identical to plain, yet it failed 0/3 vs 2/3.
  That is run-to-run variance under identical configuration.

Meanwhile S1 (small scope) showed no measurable quality cost, though it is a ceiling suite (every
config passes every task). The rule-only router (pre-scope-gate build 43ed54e) ran at 0.55x plain's
time and 0.38x its cost, 12/12, as did plain-sonnet. On the preregistered 8-task holdout (3 reps) it
ran at 0.61x [0.47–0.78] time and 0.40x cost, 24/24; the sign test gave 7 faster, 1 marginally slower
(median 8.79 s vs 8.73 s), p = 0.07, so 5 of 6 criteria passed and the result is not confirmed.

**Conclusion.** For repository-scale bugs, "difficulty" is not "the cheap model can solve it". The
quality-safe shape gates the cheap tier on task scope. `model_routing.cheap_max_workspace_files: 300`
(shipped) starts any turn in a larger workspace on the host model, whatever the judge says. It uses a
bounded, memoized walk that skips VCS, dependency and cache directories.

Expected effect, to be measured:
- On S3 every instance runs strong: quality = plain, time ~ 0.98x.
- On S1 nothing changes: 0.55x time, 0.38x cost.

Repository-scale speedups must therefore come from Amplifier's overhead, not the model choice (section
18.9, next): startup hooks, a 68–114k-token system prompt, and cache stability.

### 18.9 Complex-task speed without a model swap (2026-09-24)

S3, 10 instances x 2 reps, same wave:

| Arm | Resolved | Time vs plain | Cost vs plain | Discordant pairs |
|---|---|---|---|---|
| plain | 14/20 | 1.00 | 1.00 | — |
| shipped default (scope gate → strong, provider-default effort) | 13/20 | 1.00 | 0.98 | 1 plain-only (pylint r2); config identical to plain, so this is noise |
| strong tier + phase effort (orient medium / explore low→held medium / implement high) | 12/20 | 0.81 (faster 14/20) | 0.87 | 2 plain-only (pylint-7080, both reps) |

**The shipped default passes non-inferiority** on S3. Lower effort on repository-scale tasks trades
~19% time for a quality risk: pylint-7080 was 0/2 with lower effort, against 2/2 for plain and 1/2 for
the shipped default in the same batch. It is
shipped as an opt-in knob (`by_tier.strong: phase`), not a default. Beyond this, repository-scale
speed must come from Amplifier's own overhead, not from the model or effort choice:
- 5.8 s per session start in foundation `hooks-deprecation`, sub-sessions included (upstream patch
  ready)
- per-prompt hooks in heavy app compositions (up to 5 s)
- a 68–114k-token prompt
