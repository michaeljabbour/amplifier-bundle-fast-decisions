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
