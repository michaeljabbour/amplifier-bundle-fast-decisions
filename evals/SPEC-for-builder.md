# Implementation spec: `evals/run.py`, `evals/cells.yaml`, `evals/suites.yaml`

Read `STUDY-DESIGN.md` for *why*. This is *what to build*.

## Overview

A thin driver that turns declarative cell/suite definitions into the
`scripts/battery.py` invocations they already describe, verifies the
preconditions that have burned us before, runs them serially, re-scores, and
emits one cross-cell report plus a manifest.

**Hard constraint: no new runner logic.** `run.py` must not time a run, parse a
harness, score a task, compute a statistic, or decide an outcome. Every number
in its output comes from `battery.py` or `battery_report.py`. If a behavior
seems to need new measurement code, it belongs in `battery.py` instead and this
spec is wrong -- stop and say so.

Stdlib only, consistent with `battery.py`/`battery_report.py`. YAML is the one
exception: parse `cells.yaml`/`suites.yaml` with `pyyaml` if importable, else
fail with a clear message naming the missing dependency (do not hand-roll a YAML
parser, and do not silently fall back to JSON).

---

## 1. `evals/suites.yaml`

```yaml
schema: fast-decisions-evals/suites/v1

suites:
  s1:
    label: "S1 synthetic battery (20 tasks, 4 families)"
    task_source: battery           # battery.py --task-source battery
    deadline_seconds: 600
    splits:
      dev:     { tasks_flag: dev,     expected_task_count: 12 }
      holdout: { tasks_flag: holdout, expected_task_count: 8 }
    required_toolchains: [python3]

  s2:
    label: "S2 aider polyglot slice (40 tasks: python/rust/go/cpp)"
    task_source: polyglot          # battery.py --task-source polyglot
    deadline_seconds: 900
    polyglot:
      root_env: AFAST_POLYGLOT_ROOT      # or --polyglot-root on the CLI
      pinned_corpus_sha: "7e0611e"       # prefix-matched against polyglot-manifest.json .sha
      languages: [python, rust, go, cpp]
      slice: 40
      seed: 20260919                     # fixed: changing it changes the split
    splits:
      dev:     { split_flag: dev,     expected_task_count: 24 }
      holdout: { split_flag: holdout, expected_task_count: 16 }
    required_toolchains: [python3, cargo, go, cmake]
    excluded_languages:
      java: "corpus ships no junit-platform-console-standalone jar; polyglot_tasks.load() skips java"
      javascript: "grading needs `npx --no-install jest` with node_modules present; corpus is not vendored offline"
```

`expected_task_count` is asserted against `proposal.json["tasks"]` after prepare.
A mismatch is a precondition failure (exit 4) -- it means the split moved.

---

## 2. `evals/cells.yaml`

```yaml
schema: fast-decisions-evals/cells/v1

defaults:
  amplifier_model: claude-fable-5-1
  judge_model: qwen3:0.6b
  claude_permission_mode: bypassPermissions     # R2: never acceptEdits, either suite
  claude_max_budget_usd: 3.0
  external_models:
    claude: null            # null = the harness's configured default; recorded either way
    codex: null
    opencode: null

effort_profiles:
  all_phase: { orient: medium, explore: low, implement: high }
  explore_only: { explore: low }

model_routing_profiles:
  sonnet_start:
    start_model: claude-sonnet-5
    max_requests_before_escalation: 6
    escalate_on_test_failure: true
    escalate_on_provider_error: true

cells:
  plain:
    label_suffix: "plain [model=claude-fable-5-1]"
    harnesses: [amplifier-plain]
    amplifier_model: claude-fable-5-1
    fd: null
    role: "reference series / drift check"
    mechanism_gate: { no_fd_receipts: true }

  plain-sonnet:
    label_suffix: "plain [model=claude-sonnet-5]"
    harnesses: [amplifier-plain]
    amplifier_model: claude-sonnet-5
    fd: null
    role: "mandatory control for judge-local+effort+route"
    mechanism_gate: { no_fd_receipts: true }

  judge-local:
    harnesses: [amplifier-plain, amplifier-fd]
    fd: { backend: ollama, model: qwen3:0.6b }
    role: "judge alone"
    mechanism_gate: { scored_backend: ollama, min_scored: 1, max_fallback_fraction: 0.5 }

  effort-only:
    harnesses: [amplifier-plain, amplifier-fd]
    fd: { backend: unavailable, effort_profile: all_phase }
    role: "effort routing alone (judge off)"
    mechanism_gate: { max_scored: 0, require_effort_phases: ["implement:high"] }

  judge-local+effort:
    harnesses: [amplifier-plain, amplifier-fd]
    fd: { backend: ollama, model: qwen3:0.6b, effort_profile: all_phase }
    role: "champion candidate"
    champion: true
    mechanism_gate: { scored_backend: ollama, min_scored: 1, require_effort_phases: ["implement:high"] }

  judge-jev+effort:
    harnesses: [amplifier-plain, amplifier-fd]
    fd: { backend: jev, allow_external_state: true, effort_profile: all_phase }
    role: "judge swap (external; opt-in state)"
    mechanism_gate: { scored_backend: jev, min_scored: 1, require_effort_phases: ["implement:high"] }

  judge-local+effort+route:
    harnesses: [amplifier-plain, amplifier-fd]
    fd: { backend: ollama, model: qwen3:0.6b, effort_profile: all_phase,
          model_routing_profile: sonnet_start }
    role: "model routing"
    requires_cells: [plain-sonnet]          # refuse to run without its control
    mechanism_gate:
      model_routed_model: claude-sonnet-5
      min_model_routed: 1
      flag_if_zero_escalations: confounded_with_plain_sonnet

  externals:
    harnesses: [claude, codex, opencode, amplifier-plain, amplifier-fd]
    fd: { backend: ollama, model: qwen3:0.6b, effort_profile: all_phase }   # = champion
    role: "Q3 cross-harness comparison"
    mechanism_gate: { scored_backend: ollama, min_scored: 1 }

budget:
  per_launch_usd: 12.0
  estimated_total_usd: 400.0
  max_benchmark_worker_launches: 600
  max_infrastructure_retries_per_run: 1
  max_parallel_timed_runs: 1        # never raise this: timed runs must not share resources
  wall_hours: 24
```

---

## 3. Cell -> `battery.py prepare` flag mapping

Every cell becomes one experiment per (suite, split, rep), named
`<cell>-<suite>-<split>-r<N>`. Flags below are exhaustive: nothing else is
passed, and every flag here comes from `battery.py`'s existing `prepare` parser.

**Always:**

| flag | value |
|---|---|
| `--root` | `<out>/campaign` |
| `--experiment` | `<cell>-<suite>-<split>-r<N>` |
| `--harnesses` | comma-joined `cells[cell].harnesses` |
| `--seed` | `base_seed + N` (recorded in the manifest) |
| `--deadline-seconds` | `suites[suite].deadline_seconds` |
| `--baseline-source` | `--baseline-source` CLI value |
| `--candidate-source` | `--candidate-source` CLI value (this worktree) |
| `--candidate-sha` | `--candidate-sha` CLI value (required; freezes the snapshot) |
| `--amplifier-model` | cell's `amplifier_model` or `defaults.amplifier_model` |
| `--claude-permission-mode` | `bypassPermissions` (always explicit; never rely on the default) |

Note: `prepare` requires `--baseline-source` and `--candidate-source` whenever
any amplifier harness is present -- including `amplifier-plain`-only cells. Pass
both; the candidate snapshot is created and simply unused by a plain-only cell.

**Suite s1:** `--tasks dev` or `--tasks holdout`.

**Suite s2:** `--task-source polyglot --polyglot-root <root> --languages python,rust,go,cpp --slice 40 --split dev|holdout`.
(`--tasks` is not passed for polyglot.)

**Externals cell only:** `--claude-model`, `--codex-model`, `--opencode-model`
when non-null, and `--claude-max-budget-usd <defaults.claude_max_budget_usd>`.

**fd configuration** (only for cells with an `amplifier-fd` harness):

| cell `fd` field | flags emitted |
|---|---|
| `backend: ollama` | `--fd-backend ollama` |
| `backend: jev` + `allow_external_state: true` | `--fd-backend jev --allow-external-state` (both, always together -- prepare refuses jev alone) |
| `backend: unavailable` | `--fd-override backend=unavailable` (not a `--fd-backend` choice) |
| `model: qwen3:0.6b` | `--fd-override model=qwen3:0.6b` |
| `effort_profile: X` | `--fd-override effort_routing=<compact JSON of effort_profiles[X]>` |
| `model_routing_profile: Y` | `--fd-override model_routing=<compact JSON of model_routing_profiles[Y]>` |

`--fd-override k=v` values are coerced by `battery.py::_coerce`, which json-parses
anything that is not an int/float/bool -- so a compact JSON object passes through
intact. Emit it with `json.dumps(obj, separators=(",", ":"))` and pass it as one
argv element (never shell-quoted into a string).

**Sequence per experiment:**

```
battery.py prepare  --root <campaign> --experiment <exp> ...      # see above
<verification: see section 5>
battery.py run       --root <campaign> --experiment <exp>
battery.py reevaluate --root <campaign> --experiment <exp> --reason "post-run rescore"
battery.py evaluate  --root <campaign> --experiment <exp>
```

`backfill-exec` is only needed for experiments that predate `exec_time_ms`;
`run.py` does not call it for experiments it created. Expose it as
`--backfill-exec` for adopting an older campaign root, and skip it otherwise.

---

## 4. Campaign root

`battery.py` requires a campaign root with `protocol.json` and `ledger.jsonl`
(budget, launch cap, reservation policy). On first use of an `--out` directory,
`run.py` writes `<out>/campaign-proposal.json` from `cells.yaml::budget` and
calls:

```
campaign.py init --root <out>/campaign \
  --proposal <out>/campaign-proposal.json \
  --baseline-source <baseline> --candidate-worktree <candidate> \
  --installed-cache <installed-cache> --history-index <history-index> \
  --host-python <host-python> --events-dir <events-dir>
```

Paths come from CLI flags of the same names. If `<out>/campaign/protocol.json`
already exists, skip init (idempotent; `campaign.py init` refuses an existing
root and that refusal must not surface as an error on resume).

---

## 5. Verification (runs after prepare, before `battery.py run`)

All checks run before any paid launch. Any failure -> exit 4, nothing spent.
Write every check's outcome to `<out>/prompt-verification.json` and
`<out>/preflight.json` even on success -- these files are the receipt.

1. **Prompt identity (R1).** For each task in `proposal.json["tasks"]`:
   - resolve the task via `forge_workloads.get_task(name)` (register the polyglot
     source first from `proposal["task_source"]`, exactly as `battery.py`'s
     `_register_task_source_from_proposal` does);
   - `expected = forge_workloads.task_prompt(task) or task.prompt`; require it
     non-empty; `expected_sha = sha256(expected)`;
   - for each amplifier run of that task, read the stored `prompt` from
     `runs/amplifier/manifest.json` and require `sha256(stored) == expected_sha`;
   - for each external run of that task, require `runs/manifest.json["runs"][name]`
     has **no** `prompt` key (so `_dispatch` falls back to `task.prompt`, which is
     `expected`) -- and record that this is a static guarantee, not an observed
     hash.
   Record per task: `expected_sha`, per-harness `{matched: bool, source:
   "recorded"|"static-fallback"}`. Any mismatch or unresolvable prompt: exit 4.
2. **Permission mode (R2).** `proposal.json["claude_permission_mode"] ==
   "bypassPermissions"`. Also assert `proposal["commands"]["claude"]` contains
   `--permission-mode bypassPermissions` when the cell includes claude.
3. **Command templates.** For each external harness in the cell, compare
   `proposal["commands"][h]` against the expected argv shape from `cells.yaml`
   (binary name, model flag present iff a model was requested). Mismatch: exit 4.
4. **Task count.** `len(proposal["tasks"]) == suites[suite].splits[split].expected_task_count`.
5. **Corpus sha (s2).** `polyglot-manifest.json`'s `sha` starts with
   `pinned_corpus_sha`. Mismatch: exit 4.
6. **Frozen candidate.** `proposal["candidate_source_snapshot"]["git_sha"]`
   starts with `--candidate-sha`. Also require the snapshot exists on disk.
7. **Workspace identity.** `prepare` already asserts per-task workspace hashes
   match across harnesses; re-assert it here by hashing and comparing, and record
   the per-task hash in `preflight.json` (cheap, and it is the artifact a
   skeptic asks for).
8. **Toolchains.** Every entry in `suites[suite].required_toolchains` resolves on
   PATH (use `polyglot_tasks.toolchains()` for the s2 set).
9. **Forge doctor.** Run it; non-zero exit -> exit 4.
10. **Budget headroom.** `campaign.py budget status` remaining >= estimated cost
    of this invocation (`runs x per_launch_usd`). Insufficient -> exit 3.
11. **Cell dependencies.** Every `requires_cells` entry of a requested cell is
    also in the requested set. Missing -> exit 2.
12. **External state consent.** A cell with `backend: jev` requires
    `allow_external_state: true` in its own definition **and** the CLI flag
    `--allow-external-state` on this invocation. Missing -> exit 2. (Two gates on
    purpose: config alone must not send state off-machine.)

---

## 6. Mechanism gate evaluation (after `evaluate`)

Read `experiments/<exp>/comparison.json["mechanism"]` -- do not re-derive it.
Evaluate the cell's `mechanism_gate` against it:

| gate key | assertion against `comparison["mechanism"]` |
|---|---|
| `scored_backend: X`, `min_scored: N` | `scored_by_backend.get(X, 0) >= N` |
| `max_scored: N` | `sum(scored_by_backend.values()) <= N` |
| `max_fallback_fraction: F` | `fallback_count / (fallback_count + total_scored) <= F` when the denominator is non-zero |
| `require_effort_phases: [..]` | each key present in `effort_routed_by_phase_effort` with count > 0 |
| `model_routed_model: M`, `min_model_routed: N` | `model_routed_requested_models.get(M, 0) >= N` |
| `flag_if_zero_escalations: TAG` | when `sum(model_routed_escalations_by_reason.values()) == 0`, attach `TAG` to the cell (a flag, not a failure) |
| `no_fd_receipts: true` | `mechanism` is `None`, or all counters are zero |

Also honor `mechanism["mechanism_engaged"]`: false fails the gate regardless of
the cell's own keys.

### 6a. Required upstream fix before the `effort-only` cell can run

`battery.py::_mechanism_report` currently treats **any** configured backend other
than `'ollama'` as an external backend that must have scored, so a deliberate
judge-off cell (`backend: unavailable`) will always report
`mechanism_engaged: false` with reason `external backend 'unavailable'
refused/never scored`. That is the gate misfiring on a legitimate configuration.

Fix it in `battery.py`, not in `run.py` -- a `run.py` exemption would be exactly
the "special-case the gate" move that let the fake Jev cell through. One change:

```python
# _mechanism_report, the external-backend branch
if configured_backend and configured_backend not in ('ollama', 'unavailable'):
    ...
```

plus, in the same function, an explicit positive check so the off-switch is
verified rather than merely tolerated: when `configured_backend` is
`'unavailable'`, `engaged` is false if anything was scored at all (the judge was
supposed to be off and was not). Ship this with a unit test for both directions
before running `effort-only`; until then that cell is blocked and `run.py`
refuses it with exit 2, naming this spec section.

Write `<out>/gates.json`: per (cell, rep) `{passed, flags, reason, counters}`.
A failed gate marks the cell `excluded_from_claims: true` in the manifest and
report, keeps its numbers, and makes `run.py` exit 5 **after** the report is
written. Never delete or hide a failed cell.

---

## 7. `run.py` CLI

```
python3 evals/run.py
  --suite {s1,s2}
  --split {dev,holdout}
  --cells <comma-list>|all
  --reps N                        (default 1)
  --out DIR                       (required)
  --baseline-source PATH
  --candidate-source PATH         (default: this repo's worktree root)
  --candidate-sha SHA             (required unless --resume/--report-only)
  --polyglot-root PATH            (s2; default $AFAST_POLYGLOT_ROOT)
  --installed-cache PATH --history-index PATH --host-python PATH --events-dir PATH
  --base-seed N                   (default 20260919)
  --allow-external-state          (required by any jev cell)
  --dry-run                       print resolved argv + cost/time estimate, touch nothing
  --resume                        continue an existing --out
  --report-only                   reevaluate + evaluate + report, no launches
  --backfill-exec                 run battery.py backfill-exec before evaluate (adopted roots)
  --cells-file / --suites-file    (default evals/cells.yaml, evals/suites.yaml)
```

**Order of work:** resolve config -> validate cell set (dependencies, consent) ->
init/adopt campaign root -> for each (cell, rep) in declared cell order, then rep
order: prepare (skip if `proposal.json` exists) -> verify -> run -> reevaluate ->
evaluate -> gate. **Serial throughout.** Only after every experiment: report.

**Resume semantics.** An experiment directory with `proposal.json` is never
re-prepared; instead its proposal is re-verified against the requested cell
definition (a differing fd override, model, or split is exit 2 -- "the cell
changed under an existing run"). `battery.py run` is re-invoked regardless: it
skips runs with a `result.json`, adopts `running.json` workers, and relaunches
nothing finished.

---

## 8. Report

One `battery_report.py` invocation across every produced series:

```
battery_report.py --out <out>/report \
  --title "fast-decisions <suite> <split> (reps=N)" \
  --series "<label>=<out>/campaign:<exp>:<harness>" ...
```

One series per (cell, rep, harness). The label **must** name all four axes
(R5). Build it as:

```
<cell-id> r<N> <harness> [judge=<backend> <model>; effort <phases>; model routing: on|off; model=<amplifier_model>]
```

taking judge/effort/routing from the cell definition and cross-checking against
`comparison.json["amplifier_fd_series_label"]`; a disagreement between the
declared config and the recorded profile is a defect -> exit 4 before reporting
(it means the config did not reach the profile, which is the R4 failure mode
appearing at a different layer).

Then write `<out>/RESULTS.md`: the per-cell verdict table
(`confirmed` / `screen` / `excluded`), each cell's geomean time ratio, cost
ratio, sign-test p, quality counts, gate status and flags -- all read from
`comparison.json` and `gates.json`, none recomputed -- followed by the
auto-generated evidence limits (union of every experiment's
`comparison["evidence_limits"]`, plus reps, splits, suite shas, excluded
languages, and unknown-cost counts).

---

## 9. `<out>/manifest.json`

```json
{
  "schema": "fast-decisions-evals/manifest/v1",
  "created_at_utc": "...",
  "invocation": { "argv": ["..."], "suite": "s1", "split": "dev", "reps": 3 },
  "suite": { "id": "s1", "task_source": "battery", "deadline_seconds": 600,
             "expected_task_count": 12, "tasks": ["..."],
             "polyglot": { "pinned_corpus_sha": "7e0611e", "actual_corpus_sha": "...",
                           "languages": ["python","rust","go","cpp"], "slice": 40, "seed": 20260919,
                           "excluded_languages": { "java": "...", "javascript": "..." } } },
  "candidate": { "source": "...", "requested_sha": "...", "frozen_git_sha": "...", "tree_sha256": "..." },
  "baseline":  { "source": "...", "git_sha": "..." },
  "cells": [ { "id": "judge-local+effort", "experiments": ["judge-local+effort-s1-dev-r1", "..."],
               "seeds": [20260920, 20260921, 20260922], "argv": ["..."],
               "gate": { "passed": true, "flags": [] }, "excluded_from_claims": false } ],
  "budget": { "per_launch_usd": 12.0, "estimated_total_usd": 400.0,
              "estimated_for_this_invocation_usd": 68.0, "spent_usd": 71.4, "unknown_cost_runs": 3 },
  "verification": { "prompt_hashes": "prompt-verification.json", "preflight": "preflight.json" },
  "tool_shas": { "battery.py": "...", "battery_tasks.py": "...", "polyglot_tasks.py": "...",
                 "battery_report.py": "...", "forge_workloads.py": "..." }
}
```

`tool_shas` matters: a report whose evaluator changed mid-campaign is not one
campaign. Re-verify them on resume and refuse (exit 4) on a change.

---

## 10. Exit codes

| code | meaning | spent? |
|---|---|---|
| 0 | everything ran, every gate green | yes |
| 2 | usage/config error (unknown cell, missing required control cell, missing consent flag, cell definition changed under an existing run) | no |
| 3 | budget or launch cap refused (propagated from `battery.py` exit 3) | possibly partially |
| 4 | precondition failed (prompt hash, corpus sha, permission mode, command template, task count, frozen sha, toolchain, forge doctor, tool sha drift, label/profile disagreement) | no, if pre-launch |
| 5 | runs completed but at least one mechanism gate failed; report written, cells excluded from claims | yes |
| 6 | runs incomplete after resume (missing `result.json` with no live worker) | yes |

Print exactly one JSON line on exit, matching `battery.py`'s convention:
`{"out": "...", "cells": [...], "exit": N, "reason": "..."}`.

---

## 11. File layout produced

```
<out>/
  manifest.json
  cells.resolved.json
  campaign-proposal.json
  preflight.json
  prompt-verification.json
  gates.json
  campaign/                      # campaign.py root
  report/report.md report.json
  RESULTS.md
  PREREGISTRATION.md             # written by a human before a holdout pass; run.py only checks it exists
```

`run.py` requires `PREREGISTRATION.md` to exist before launching any
`--split holdout` pass (exit 2 otherwise). It does not read or validate the
contents -- the point is that the rule was written down first.

---

## 12. Tests required

Under `tests/`, matching the repo's existing style (`python3 -m unittest discover
-s tests -v`). **No test may invoke a real harness, a provider, forge, or the
network.** Substitute fakes for `battery.py`/`campaign.py`/`battery_report.py`
subprocess calls, exactly as the existing battery tests substitute fakes for
forge and the amplifier launcher.

Pure-function tests (the majority):

1. `cell_to_argv` -- each cell in `cells.yaml` produces the exact expected argv,
   including: `--fd-override backend=unavailable` for the judge-off cell; jev
   emitting both `--fd-backend jev` and `--allow-external-state`; compact-JSON
   `effort_routing` / `model_routing` as single argv elements; explicit
   `--claude-permission-mode bypassPermissions` on every cell; `--tasks` for s1
   and `--task-source polyglot ... --split` (and no `--tasks`) for s2.
2. `series_label` -- names judge, effort, routing, and model; a label missing an
   axis is rejected.
3. `verify_prompts` -- passes on matched hashes; fails on a mismatched amplifier
   prompt; fails on an external run carrying a `prompt` override; fails on an
   empty/unresolvable prompt. Fixtures are small hand-written manifests.
4. `gate_eval` -- each `mechanism_gate` key against synthetic `mechanism` dicts:
   jev-configured-but-never-scored fails; judge-off-with-scores fails;
   effort-phase-missing fails; zero escalations flags but does not fail;
   `mechanism_engaged: false` fails regardless of other keys.
5. `resume_detection` -- an experiment with `proposal.json` is not re-prepared; a
   changed cell definition exits 2; a matching one proceeds.
6. `exit_codes` -- each failure path returns its documented code, and every
   pre-launch failure path provably issues zero `battery.py run` calls (assert on
   the fake's call log).
7. `cost_estimate` -- `--dry-run` produces a deterministic estimate from
   `runs x per_launch_usd` and touches no filesystem state outside `<out>`.
8. `manifest_shape` -- required keys present; `tool_shas` recorded; a changed
   tool sha on resume exits 4.

One end-to-end test with fakes: a two-cell, one-rep, two-task invocation drives
the full sequence (init -> prepare -> verify -> run -> reevaluate -> evaluate ->
gate -> report), asserting call order, serialization (no overlapping run calls),
and the produced file layout.

---

## 13. Explicit non-goals

- No parallelism, no work-stealing, no scheduler. One timed run at a time.
- No retry logic beyond what `battery.py` already does.
- No statistics: geomean, sign test, and ratios come from `battery.py evaluate`
  and `battery_report.py`.
- No cost model: costs come from result files with their `cost_source` intact.
- No new task definitions. Tasks live in `battery_tasks.py` / `polyglot_tasks.py`.
- No mutation of an existing experiment's `proposal.json`, ever.


---

## 14. Decision (2026-09-20) -- amendments to this spec

`evals/run.py`, `evals/cells.yaml`, and `evals/suites.yaml` are implemented
against this spec with the following resolved-open-question amendments (see
`STUDY-DESIGN.md` section 12 "Decisions" for the full rationale):

- **Section 2 `cells.yaml`, section 3 harness lists:** every judge/effort/
  routing cell (`judge-local`, `effort-only`, `judge-local+effort`,
  `judge-local+effort-incumbent` [new], `judge-jev+effort`,
  `judge-local+effort+route`) now declares `harnesses: [amplifier-fd]` only
  (no embedded `amplifier-plain`) plus a new `anchor_cell` field naming the
  batch's shared plain anchor. `externals` is unchanged (keeps its own
  `amplifier-plain`). `run.py` validates `anchor_cell` exactly like
  `requires_cells` (section 5 #11) and wires it into `battery.py evaluate`
  via `--baseline-root`/`--baseline-experiment` pointing at the anchor's
  same-(suite,split,rep) experiment.
- **Section 3 experiment naming:** canonical naming stays
  `<cell>-<suite>-<split>-r<N>` (matches the section 9 manifest example); the
  decision text's shorthand `<suite>-<cell>-r<rep>` was informal, not a
  second naming scheme.
- **New cell `judge-local+effort-incumbent`:** `fd: {backend: ollama, model:
  qwen3:0.6b, effort_profile: explore_only}`, `anchor_cell: plain`,
  representing Amplifier's already-shipped default (reference series, not a
  candidate).
