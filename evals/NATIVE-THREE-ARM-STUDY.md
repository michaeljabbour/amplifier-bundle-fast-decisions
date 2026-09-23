# Does Fast Decisions help ordinary Codex and Amplifier work?

Design version: `native-three-arm/v1`, 2026-09-22 UTC.
Status: **qualified and frozen; collection started 2026-09-22 03:58:50 UTC**.

This is the replacement design for the September 21 Codex first-file-hook
experiments. The study is running; there is no completed performance result yet. This document is not executable input for `evals/run.py`.
The companion JSON is a machine-readable design record, not a runner manifest.
Existing campaign results and their protocols remain historical evidence.

## The question, in plain language

Does turning on the supported Fast Decisions decision helper let the assistant
finish the same real job sooner, or at lower measured cost, with a correct result?
Run this comparison separately in Codex and Amplifier:

1. The assistant without Fast Decisions.
2. The same assistant with Fast Decisions using the local model.
3. The same assistant with Fast Decisions using Jev.

The first comparison is about the supported read/list decision helper. Keep the
main model and its reasoning setting fixed. Effort changes and model switching
are other FD features and are outside this comparison. Do not describe these
results as testing every FD feature or the unmodified Amplifier default preset.

We are measuring the value of enabling the helper, including its integration
and overhead. Three conditions can answer that question. They cannot establish
that a learned chooser is better than every simpler way to choose a file. No
fourth condition or special prefetch system is required for the product question.

## What changes from the previous experiments

| Previous limitation | Replacement rule |
|---|---|
| A custom hook chose and read a file before Codex started. | Use the supported Smart Tool in Codex and the native decision integration in Amplifier. No experimental file injection or decision adapter. |
| Jev was connected through an experiment-only backend modification. | Use a public, documented Jev selection interface. Codex/Jev is unavailable until that interface exists and is qualified. |
| Tiny, previously exercised tasks all asked for README.md. | Use independently graded jobs from real repositories, new to this campaign, with their natural task descriptions. |
| Keeping the local model resident defined the confirmation. | Use ordinary documented startup and lifecycle behavior. Count startup, reload delays, abstentions, errors and fallbacks. |
| A few successful uses could be mistaken for everyday value. | Keep all assigned jobs, including jobs where the assistant never calls FD. |
| A slow baseline run strongly affected the average. | Keep it; show per-task results, medians, uncertainty and sensitivity to removing each task/project in turn. Never delete a run because it is slow. |
| Codex results could be read as evidence for Amplifier. | Two separate three-condition comparisons; no pooled score or cross-harness winner. |

## Verified interface audit and open requirements

Read-only audit at repository commit `a22b236f3c648a3d245849b652a8500722ce60f4`:

- **Codex/local:** the installed skill advertises the public
  `amplifier-fast-decisions select` command. The assistant supplies bounded
  read/list choices and receives advice. It still owns the action. The tool does
  not intercept Codex's model calls. Ordinary task use remains to be qualified.
- **Codex/Jev:** the installed public command exposes Ollama settings only.
  `smart_tool.select` constructs `OllamaBackend`; `_backend` is explicitly a
  private test seam, and result validation expects the local probability format.
  An environment variable or private backend replacement does not make this a
  supported Jev Smart Tool. A public backend option with consent, credentials,
  validation, failure behavior and accurate receipts is a product prerequisite.
- **Amplifier/local and Amplifier/Jev:** the source supports the native active
  integration and external-state consent. Their actual installed-host behavior
  must be qualified before performance collection; source support is not a pass.
- **Amplifier effort confound:** `bundles/active.yaml` includes
  `effort_routing.explore: low`. Explicitly set `effort_routing: null` and
  `model_routing: null` using supported configuration, and verify the resolved
  configuration and actual provider requests. Do not rely on a “judge-only” label.
- **Codex baseline isolation:** the previous runner supplied skill directory
  paths to disable skills and FD metadata remained visible. Official Codex
  documentation shows the path to `SKILL.md`. Use the documented mechanism in an
  isolated profile, then inspect actual discovery/context. Do not assume the path
  correction alone proves isolation, or edit the user's global configuration.

See [the audit record](native-three-arm-audit.json). These findings identify
requirements; this document does not silently implement or simulate them.

## The six conditions

| Harness | Without FD | FD-local | FD-Jev |
|---|---|---|---|
| Codex | FD skill unavailable in the session; no FD calls or file injection. | Stock published skill and public CLI available for ordinary, voluntary use. | Same skill and public CLI, with public Jev selection qualified in the frozen development build. |
| Amplifier | Ordinary upstream loop, with FD decision machinery and FD skill disabled. | Native active decision integration, local backend, fixed main-model effort. | Same native integration and policy, Jev backend with explicit external-state consent. |

Within each harness, match the main model, reasoning setting, tool permissions,
context/iteration limits, non-FD skills, dependencies and starting files. Between
harnesses, use each harness's qualified normal model/provider and report its exact
identity; do not substitute a model to make FD look better. The causal comparisons
are within a harness, not Codex against Amplifier.

No main-model delegation in measured jobs. This holds for every condition and
bounds the result to a single assistant. Ordinary shell tools and tests remain
available under the same native permission rules; no blanket approval bypass is
introduced to get an integration working.

FD-local and FD-Jev use their supported, unmodified backend prompts, the same
selection policy and public input contract within a harness. Record any native
backend differences; do not align prompts with a monkeypatch during the study.
Freeze thresholds, deadlines, limits, source versions and configurations before
collecting performance results. No tuning against confirmation tasks.

For Codex, only the shipped discovery instructions introduce FD. Do not add
“you must use FD,” prescribe a minimum number of calls, supply ready-made
candidates, rewrite task context for the tool, or preload file contents. Building
the candidates, reading help, calling the tool, considering its advice, and doing
the action all count as the assistant's work. Non-use is a result, not a reason to
retry a task. Ordinary abstention is also a result.

## Qualification before a scored job

Use separate disposable public examples, never the scored tasks. Limit this
stage to at most 24 assistant sessions across both harnesses; retain every attempt.
It is installation/function checking, not evidence of speed or usefulness.

For each harness, prove all three intended conditions work before starting its
performance study. The Amplifier study need not wait for Codex/Jev development,
but neither study may silently become a two-condition comparison.

1. Capture executable and dependency versions, resolved profiles, source hashes,
   main-model/effort identity and the effective skill/tool inventory. Confirm the
   baseline has no FD discovery metadata, FD calls, active hook or scoring process
   acting on its behalf. Match unrelated context after normalizing workspace paths.
2. In an explicitly requested, excluded capability check, demonstrate a real
   local selection and a real authenticated Jev selection through the intended
   public/native entry point. Verify the returned backend/model and corresponding
   host trace. A configured backend, synthetic result, or bare manifest call is
   insufficient. Do not force use in the scored jobs afterward.
3. Verify ordinary refusal/abstention, unavailable-scorer fallback, cancellation,
   and native action validation/permission behavior. Where the host supports
   permission modification, verify it remains effective. Do not bypass failures.
4. In Amplifier, link a real prepared action to native execution and check tool
   result pairing, usage/context accounting, and unchanged main-model settings.
   Streaming paths which cannot use FD must be reported honestly, not swapped
   for a different transport by the benchmark.
5. Qualify the independent graders: the untouched broken checkout must fail the
   intended check; a known correct reference must pass; zero collected tests,
   broken toolchains and test tampering must not count as success.

If an interface or isolation check fails, record the requirement and stop that
harness before performance collection. Product fixes create a new version to
qualify and freeze; they are not hidden changes to an ongoing experiment.

## Work to be tested

The bounded first study uses **24 distinct real-repository jobs, three
repetitions, three conditions: 216 sessions per harness, 432 total**. This is a
fixed precision-limited study, not a promise that 24 jobs can prove a small speed
gain or unchanged quality. The number is a work limit, not a power calculation.
If the result is uncertain, report uncertainty; do not keep adding jobs until a
positive result appears.

Select six public repositories, four independent jobs per repository. Target
12 bug fixes, six small feature changes, and six maintenance/refactoring jobs
across the full set. Each must require working in a real project and have
independent behavioral/regression checks. Use original issue/change descriptions
where available, not new instructions engineered to trigger FD. Keep legitimate
jobs that do not offer useful read/list shortcuts.

Before selecting the sample, inventory task IDs, commits and content hashes used
in prior local campaigns. Exclude all previously used jobs, the eight hook-pilot
tasks, and qualification tasks. Public jobs may be familiar to a model from
training: “new” means not used to develop or select this campaign, not guaranteed
absent from training.

Build and hash an eligible pool using only provenance, scope, license, dependency
availability and grader validity—not measured FD use or performance. Record all
exclusions. Draw the repository/task sample by the frozen seed within the stated
categories. If the pool cannot satisfy the quotas, revise and version the design
before any scored launch; do not fill missing slots with favorable toy tasks.

For every job, freeze repository URL and commit, original task text, starting
file hashes, dependency environment, protected files, grader source/hash,
positive/negative grader checks and the complete expected test inventory. Keep
the grading environment and reference solution outside the assistant workspace.
Do not impose artificial ANSWER:/DONE: requirements; grade the requested work.
Tests/grading run independently of the assistant. A grader repair may re-score
preserved outputs for every condition; it must not regenerate solutions.

## Execution, ordering and ordinary startup

- A fresh session and isolated checkout for each attempt. The identical task
  prompt and starting-file hashes go to all three conditions and both harnesses.
  Do not transfer answers, summaries, caches of task-specific tool output or
  modified workspaces between attempts. Ordinary provider caching remains on
  and its usage is recorded; do not claim it has been reset.
- Run the three conditions for a task/repetition close together, one measured
  assistant session at a time. Randomize task order with seed `20260922`.
  Balance condition position so each condition appears first, second and third
  once per task over three repetitions; balance forward/reverse order across
  tasks. Randomize which harness's block is first. Save the complete schedule
  before launch. Do not compare all baselines from one day with FD from another.
- Use an isolated standard local-model service to protect the user's service.
  Use ordinary documented settings and lifecycle, not a residency watchdog or
  extended keep-alive invented for the study. Record competing host work and
  scorer readiness; do not condition inclusion on staying warm.
- Each repetition is a work batch. Start timing its first local-FD job before
  any documented service startup/warmup needed for that batch. Count that work
  in that job and in the batch total. Later jobs reuse only what the normal
  product keeps alive. Record first-job versus later-job timing. Reloads,
  timeouts and reconnects during the batch remain measured outcomes.
- Dependency installation and one-time product installation happen before
  collection and are reported separately. Runtime tool/help discovery, CLI
  startup, scoring, assistant tests, retries, fallback and final response are
  inside task timing. Independent grading happens afterward and is timed
  separately. Setup or authentication failure after a job starts still counts.
- Use the documented CLI process lifetime in Codex. Do not add a persistent
  decision service just for its measured conditions. Amplifier may reuse clients
  as its native integration ordinarily does. Report that product difference.

## Measurements and rules for conclusions

**Correctness first:** record independent acceptance and all regression results
for every assigned attempt, including unfinished ones. Also report new failures
where baseline succeeded, permission/protected-file violations and incomplete
test coverage. A tool that is faster because it stopped early has not helped.

**Time:** record actual elapsed time from task submission, including any assigned
runtime startup above, to final response/process completion. Use a fixed
1,200-second per-attempt limit. The primary time score is elapsed time for an
independently accepted result; an unsuccessful or timed-out attempt gets the full
1,200-second limit. This is a failure-penalized completion score, not a claim that
an early failure literally took 20 minutes. Show raw elapsed time and acceptance
next to it. Never present success-only timing as the main result.

**Work and cost:** count actual main-model requests/responses, input/cached/output
tokens, FD calls by backend, actual actions, repeated reads, tests, failures and
recoveries. Keep usage by provider/model. Report real billed cost when available;
otherwise mark dollar cost unknown. Fewer tokens or a local model do not prove a
lower total bill. Include scorer charges in any cost comparison.

**Use and effect:** distinguish availability, invocation, valid suggestion,
accepted/executed suggestion, completed work, and actual model work avoided.
Link native host events and FD receipts using session/decision IDs; reconcile
usage with host totals. A selection is not an execution or a saved model call.
Summarize jobs where FD was not used, abstained, repeated a read, failed, or added
work. These are retained in the main enabled-versus-baseline comparison. A
used-only subset is descriptive and cannot replace that comparison.

For each harness separately:

1. Average the three attempt scores for each task/condition. Form the FD/baseline
   ratio per task and take the geometric mean across the 24 tasks. Report the
   acceptance difference, per-task data, arithmetic means, medians and raw tails
   alongside this predeclared primary score.
2. Estimate uncertainty with 50,000 paired task-resampling draws, seed `20260923`,
   keeping all repetitions and conditions together. Resample tasks within each
   of the six fixed repositories. These intervals describe uncertainty for the
   chosen projects; six projects do not establish all-project generalization.
3. The four planned speed comparisons are local versus baseline and Jev versus
   baseline in each harness. Use 98.75% intervals for the four primary ratios to
   account approximately for making four comparisons; 95% intervals on secondary
   measures are descriptive. Do not infer Jev beats local just because one
   comparison with baseline looks stronger.
4. Show leave-one-task-out and leave-one-repository-out point estimates for every
   omission, not just the inconvenient outlier. The all-attempt result remains
   primary. Do not delete or winsorize slow runs. Report whether the conclusion
   depends on one task or project.
5. A supported speed signal requires the primary interval entirely below 1,
   no observed decrease in acceptance, and no new protected-file/permission
   violations. Call it a result on this workload, not proof of equal quality.
   Report the paired acceptance-difference interval even when every task passes.
   This study does not establish a powered “no quality loss” or equivalence claim.
6. Report at least three possible outcomes honestly: useful on this workload;
   no demonstrated benefit; or integration unavailable/unusable. If the tool is
   available but not called, say that—it is a normal-use result, not a missing
   observation. Confidence interval overlap with no improvement means uncertain,
   not proof the tool has no value.

## Failure handling, resource limits and the launch gate

Retain every assigned attempt, backend failure, abstention, non-use and native
retry. Never re-run an attempt to replace its score. If the assistant naturally
retries within the fixed deadline, its time and usage remain part of that attempt.
Do not exclude a run because its FD backend never scored or its fallback rate was
high. This differs deliberately from older mechanism-only campaign filters.

Pause collection only for a broken measurement/credential system, changed model
or configuration, baseline contamination, safety violation, or a predeclared
resource limit. Preserve all observations and the scheduled denominator. An
outage is not automatically a free replacement. Record missed scheduled jobs,
where collection stopped, and whether inference is still valid. A version change
requires a separate experiment. A partially completed schedule is not a completed
three-condition result.

Before any scored launch, create a separate locked execution manifest containing:

- All three qualified entry points for that harness and their evidence paths.
- Immutable package/host versions, effective profiles, approved permission scope,
  main-model/effort and scorer identities, and allowed configuration differences.
- The complete new-task inventory, grader checks, exact prompts/hashes and schedule.
- A task-clock implementation and independent verifier that include the declared
  startup and failure treatment, plus receipt and token reconciliation checks.
- A finite currency ceiling with a metering or conservative reservation source,
  a finite aggregate output-token ceiling, and a collection wall-time ceiling.
  Reserve the remaining allowance before each launch. The design's maximum is
  432 scored sessions and 24 qualification sessions; a smaller resource ceiling
  must be reported if it prevents completion. No silent budget increase or
  unmetered “free” claim.
- A source/configuration digest and recorded freeze timestamp before any scored
  task is dispatched. The analysis must also be frozen before results are read.

The installed Codex/Jev interface, actual host qualification, new-task manifest,
runner verification and numeric collection budgets are **not yet supplied**.
This is why the corrected design is complete but the study is not marked ready
to launch. Do not fill these gaps with a custom integration or call this document
a completed preregistration.

## Evidence boundary and references

Retain the original pilot and isolated-runtime confirmation as experimental-hook
evidence only. Do not pool their 144 sessions into the native-use study, use them
as new-task evidence, or silently revise their historical numbers.

- [Portable interface and limits](../docs/SMART-TOOL.md)
- [Public selection implementation](../src/amplifier_fast_decisions/smart_tool.py)
- [Supported policy settings](../docs/CONFIGURATION.md)
- [Active bundle defaults](../bundles/active.yaml)
- [Host checks](../docs/AGENT-HANDOFF.md), [compatibility](../docs/COMPATIBILITY.md),
  [privacy](../docs/PRIVACY.md)
- [Official Codex skill documentation](https://developers.openai.com/codex/skills),
  retrieved through the OpenAI developer documentation MCP on 2026-09-22 UTC.

Keys remain in the environment and never enter task manifests, profiles or logs.
Only public, disposable task data may go to Jev under the user's existing test
authorization and explicit external-state configuration. Do not change default
user installations, global skills, production workspaces or running services to
enforce experiment isolation.


## Execution record (2026-09-22 UTC)

The study directory is `/Users/michaeljabbour/dev/afast-native-study-20260922`.
`freeze.json` hashes the execution scripts, task prompts, grading inputs, product
snapshots, installed public CLI and runtime sources. `schedule.json` contains all
432 assignments. `state.json` and append-only `results.jsonl` record progress.
The earlier interface audit above remains a historical description of the
starting commit; `qualification-audit.json` records the resolved requirements.

The tested development build adds public Jev selection with explicit external
consent and includes candidate filenames in the model-facing choices. It preserves
native backend scores and actual model identity, and never switches backends on
failure. The installed distribution still reports version 0.1.0; its wheel and
source hashes, rather than that version string, identify the tested build.

An isolated product patch to `amplifier-bundle-skills` adds the documented
`exclude_skills` setting. Amplifier's CLI otherwise restores user discovery paths
regardless of configured skill sources. All Amplifier conditions use the same
patched skills module and exclude the FD advisory skill and FD catalog; the two
active conditions use the native orchestrator. User skill files and global
settings remain in place. The patch is in
`/Users/michaeljabbour/dev/amplifier-bundle-skills-native-isolation` and the study
uses a frozen byte-identical copy.

The fixed main models are Codex `gpt-6-astra`, high effort, Fast tier, and Amplifier
`claude-fable-5-1`, max effort, using the user's normal Anchors base. Actual request
traces verify model/effort and baseline discovery isolation. The local judge is
`qwen3:0.6b`; Jev requests `jev-latest`, qualified as `jev-1.13.0`. The original
500 ms decision deadline remains unchanged. One excluded Codex/Jev capability
check timed out; its failure remains in the record.

The task pool covers Click, Jinja, Werkzeug, packaging, attrs, and Babel. It was
screened using seeded ordering and grader validity before any scored assistant
attempt. A 254-record prior-campaign inventory found no overlap with these
repositories; this audit occurred after task setup and before the execution
freeze, rather than before all pool preparation as originally planned. Task text
is a frozen, behavior-focused adaptation of original issues/change descriptions,
with explicit acceptance contracts for newly requested APIs and refactoring
interfaces. No reference patches are supplied to experimental assistants.

Initial setup failures are retained. Werkzeug required an additional test
dependency; Babel required its official checksum-verified CLDR build. Initial
Babel data are now generated from base sources, and independent grading rebuilds
data from submitted sources using a frozen official archive. Two maintenance
jobs have additional independent iterator/cold-import checks. The ETag feature's
base cannot collect tests importing its absent new API; a separate executed API
check fails on base and passes on reference. All 24 tasks also pass their complete
frozen reference test inventory. Grading runs outside the assistant workspace
and replaces task tests and pytest configuration with the frozen grader copy.
Public task tests may be edited; study instructions and configuration are protected.

Category labels follow the fixed title rules and some maintenance changes also
correct behavior. Python 3.13/macOS skips remain visible, including Python 3.14-
and Windows-specific checks. Results establish acceptance against the stated
checks, not comprehensive validation on those other platforms.

Verification: the 884-test package suite completed successfully (41 host-dependent skips), followed by 22
checks against the installed Amplifier core/loop, 48 skills-discovery regression
checks, 18 focused public-tool checks, and all six end-to-end runner checks.
The installed upstream does not apply `tool:pre` modification data; the fast path
preserves that native behavior. Denial, timeout, stale candidates and cancellation
were checked separately. Qualification sessions are excluded from performance.

Resource limits: $1,000 initial, automatic continuation within the user-authorized
$2,500 range; 40,000 reported output tokens per job, 12 million aggregate, and
seven days maximum collection wall time. Each job retains the original 1,200 s
limit. Budget tracking uses conservative Codex API-equivalent valuations and
Amplifier's provider estimates, with a $50 Jev planning reserve. Actual invoices
and Jev dollar prices are unknown; no exact billed-cost claim is supported.
Unknown main-model usage reserves $40 for that job. Spending or token limits can
leave an incomplete study; they never trigger selective replacement runs.

After the first three scored runs, Git rejected an explicit `.venv` exclusion
while preparing the next repository. That fourth assignment had no task
submission or model process. The preparation attempt is retained, and amendment
`001-pre-submission-git-setup` changes only Git staging to use `.git/info/exclude`.
All completed outputs, prompts, treatments, graders, analysis and schedule remain
unchanged. The old freeze is retained; collection resumed under the documented
runner amendment without regenerating any assistant solution.
