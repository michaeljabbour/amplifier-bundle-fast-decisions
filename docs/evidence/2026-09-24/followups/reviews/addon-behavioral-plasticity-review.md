Verdict: SIGN OFF WITH CHANGES

# Review: amplifier-bundle-behavioral-plasticity `perf/startup-footprint` (464ba71)

Reviewed: `~/dev/amplifier-bundle-behavioral-plasticity-perf`, one commit on top of
origin/main (7053120), 14 files, +525/-115. origin/main was checked out as a scratch
worktree at `/tmp/ampup/bundle-review/scratch-behavioral-plasticity`. All measurements
used a scratch venv (`/tmp/ampup/bundle-review/venv-bp`: py3.12, pytest, pytest-asyncio,
pyyaml, tiktoken, amplifier-core 2.0.1). Nothing under `~/.amplifier` was modified. The
branch worktree's `git status` is still clean.

Bottom line: the savings are real and measured correctly. The substrate removal is
justified by memory@main. No test regresses. Two small correctness problems need fixing
before the PR:
- the retry-on-failed-spawn guarantee for autofire isn't real;
- the new "read on demand" pointer can't be opened as written.

The rest is optional doc and hygiene cleanup.

---

## 1. Test suites (branch vs origin/main)

The documented command is in `bundle.md` ("Run it"): `cd modules/tool-falsification-harness && python -m pytest -q`.
I also ran the `dep-amplifier-data` module's tests. Command used:
`PYTHONDONTWRITEBYTECODE=1 AMPLIFIER_MEMORY_REPO=~/dev/amplifier-bundle-memory python -m pytest -q -p no:cacheprovider`

| Suite | origin/main | branch |
|---|---|---|
| tool-falsification-harness | **90 passed** | **132 passed** |
| dep-amplifier-data | **1 FAILED** (`TypeError: 'function' object is not subscriptable`, test_mount.py:28) | **1 passed** |

- **No regressions.** I diffed the collected test IDs. Every test on main is still on
  the branch. The branch adds 15 new test functions (42 cases once parametrised), all in
  `test_startup_footprint.py`.
- The dep-amplifier-data test was already failing on main. That test was stale: since
  c4f47cc, `mount()` returns a cleanup callable instead of a metadata dict. The branch
  fixes the test correctly.
- On main, 3 `test_memory_backend` tests skip unless `AMPLIFIER_MEMORY_REPO` is set,
  because the scratch worktree has no sibling memory repo. With the variable set, all 90
  pass. The branch finds the memory repo on its own.

## 2. Claimed savings, re-measured

Scripts: `/tmp/ampup/bundle-review/measure.py` and `imp.py`. Tokenizer: tiktoken cl100k_base.

| Claim | Measured main -> branch | Holds? |
|---|---|---|
| `context/harness-awareness.md` ~600 -> ~134 tokens | 2522 chars / **601 tok -> 566 chars / 134 tok** | **Yes, exactly** |
| Tool schema 223 -> 186 tokens | name+description+input_schema as compact JSON: **223 -> 186** (indent=2 gives 260 -> 223) | **Yes, exactly** (compact-JSON basis) |
| Lean adapter: "~490 tokens/request lighter" | 467 (context) + 37 (schema) = **504** | Yes (roughly) |
| Import+mount ~6.7 ms -> ~1.7 ms median | 30 runs each, warm bytecode, mock coordinator: **6.61 -> 1.36 ms** median (min 5.82 -> 1.21) | **Yes** |
| "10 -> 2 submodules" loaded | **9 -> 1**. Main loads ablation, autofire, benchmarks, cohort, fixtures, outcomes, probes, storage, verdict. Branch loads only autofire. | Direction holds; the counts are off by one (see P6) |
| Autofire: one spawn per session instead of one per turn | New tests show it: 5 fires -> 1 spawn. The `once_per_session: false` opt-out works. | Yes, with the failure-path caveat in P1 |
| memory >= 2.0 hard-depends on amplifier-data at the same pin | memory origin/main (bed0272) is v2.0.1. `tool-memory` plus the hooks-behavioral-write, memory-briefing, memory-capture, memory-interject and project-context pyprojects all list `amplifier-data @ ...@09482f1fa569...` as a hard dependency. The `[substrate]` extra is marked "DELETED". memory's `behaviors/memory.yaml` composes tool-memory. `bundle.md` pins memory `@main`. | **Yes** |
| Lean adapter keeps CI's hook without the top-level `hooks:` entry | Upstream `behaviors/context-intelligence.yaml` includes `context-intelligence-logging`, which declares `hook-context-intelligence` with full config. Foundation's registry (registry.py:492-520) registers the root namespace for `#subdirectory=` includes, so the `context-intelligence:behaviors/...` include resolves. | Plausible from code. Not checked end-to-end; HANDOFF says so too. |
| Per-tool-call cost of `verdict_meaning` | About 15 tokens, and only in tool results | Negligible, as stated |

These are honest numbers. PROVENANCE also states plainly that about 5 ms and about 0.5k
tokens is all this repo owns out of the measured +4.5 s and ~6.5k tokens, and that the
rest is inherited from memory and CI. That framing is accurate.

## 3. Problems, most severe first

### P1 — MUST-FIX: after a failed spawn, autofire no longer retries in the same session, and the new test hides this
`autofire.py:104-117` adds the session to `spawned` "only after a spawn that didn't raise".
But `runner.spawn_worker` never raises when `Popen` fails. It catches the exception, logs
a traceback, and returns `None` (runner.py, the `try: subprocess.Popen(...) except
Exception:` block). `tests/test_runner.py:95-110` confirms this.

So on the most likely failure (Popen itself fails), the session is still marked as spawned
and no later turn retries. Before this change, the next turn's spawn gave that session
another chance. After it, the session produces zero falsification records. The same
applies if the worker starts and then crashes. PROVENANCE records five such silent
ImportError crashes in the past.

`test_autofire_retries_after_a_failed_spawn` only passes because it monkeypatches
`spawn_worker` to raise, which the real function never does. The only real exception path
left is the unguarded `log_dir.mkdir` / `open` at the top of `spawn_worker`.

**Fix:**
- Make `spawn_worker` return `True` on a successful `Popen` and `False` in the `except`
  branch.
- In autofire, only call `spawned.add(session_id)` when the return is truthy.
- Change the test to monkeypatch `subprocess.Popen` to raise once, so it goes through the
  real `spawn_worker`.
- Optionally, note in the spec that a worker that crashes after spawning is not retried
  (accepted trade-off).

### P2 — MUST-FIX: the "read on demand" pointer in the injected context can't be opened as written
The new `context/harness-awareness.md` tells the model to read
`` `behavioral-plasticity:docs/tier2-harness/harness-reference.md` `` with no `@`. The
filesystem tools only resolve bundle paths when the string starts with `@`
(`amplifier_module_tool_filesystem/read.py:115`). Anything else is treated as a literal
path. I checked this: `read_file("behavioral-plasticity:docs/tier2-harness/harness-reference.md")`
returns `Path not found`. The content moved out of the always-on context is therefore
effectively unreachable unless the model guesses the `@`.

The author left out `@` to avoid eager expansion. But foundation's `parse_mentions`
already skips mentions inside inline code. I verified it: for
`` `@behavioral-plasticity:docs/tier2-harness/harness-reference.md` `` it returns `[]`,
while the same text without backticks does get expanded.

**Fix:** write it as `` `@behavioral-plasticity:docs/tier2-harness/harness-reference.md` ``
(inside backticks). The existing guard test `test_awareness_context_has_no_eager_mentions`
already allows an `@` directly after a backtick (`(?<![\w`])@`), so it still passes. Also
fix the matching sentence in the HANDOFF "Non-Obvious Context" line: `@` inside backticks
is safe.

### P3 — OPTIONAL: the model no longer knows that `proxy` is the expected result
The old context said "the predicted and acceptable verdict is `proxy`". The new context and
`VERDICT_MEANINGS["proxy"]` ("the gain lived in retrieval") drop that. The README's own
smoke test treats `proxy` as a pass, but a model with no other context may now report it as
a failure or regression. **Fix:** add about 10 tokens, either to the context ("`proxy` is
the expected result for the built-in fixtures") or to `VERDICT_MEANINGS["proxy"]`.

### P4 — OPTIONAL: stale or contradictory docs about the substrate and the autofire timing
- `modules/dep-amplifier-data/pyproject.toml:12-19` still says "Base memory never composes
  this module, so amplifier-data stays OPTIONAL for memory". It also says the pin is
  mirrored in memory's `[project.optional-dependencies].substrate`, which memory 2.x has
  deleted. Update both, or say the carrier is legacy (pre-2.0 only).
- `docs/tier2-harness/falsification-harness-spec.md:139-145`: the same paragraph now says
  both "verdicts accrue hands-free at session end" and "spawns at most once per session"
  on the first `orchestrator:complete`, which is the end of turn 1. Reword to "after the
  first turn".
- `docs/overview/why-separate-bundle.md:193-195` says the D6 "Known limitations" note lives
  in `context/harness-awareness.md`. It now lives in `docs/tier2-harness/harness-reference.md`.

### P5 — OPTIONAL: side effects of the lazy public API
- **Type erasure.** Under pyright, `from amplifier_module_tool_falsification_harness import Thresholds`
  is now typed `Any` (on main it is `type[Thresholds]`). A bad assignment that main catches
  passes silently on the branch; I checked both. **Fix:** add an
  `if TYPE_CHECKING: from .verdict import Thresholds, ...` block that mirrors
  `_LAZY_EXPORTS`. It costs nothing at runtime.
- **Monkeypatch target moved.** `execute()` now imports `run_memory_ablation` and
  `write_falsification_result` locally, so patching `pkg.run_memory_ablation` no longer
  affects the tool. No test in this repo depends on that. It is a quiet change to a test
  seam; mention it in the commit, or patch `.ablation.run_memory_ablation`.
- What I verified works: `from pkg import *`, `from pkg import X`, `pkg.X`, `dir()`,
  `AttributeError` for unknown names, and the worker via `python -m ...worker`. No lazy
  name is used bare inside `__init__.py`, which PEP 562 would not cover; I checked with
  an AST scan.

### P6 — OPTIONAL: small inaccuracies in the commit message and docs
- "loads 2 submodules instead of 10": I measure 1 vs 9.
- The autofire comment says "same guard the survey capture hook uses". The survey hook
  does use a per-session set, but it spawns at teardown (`cleanup()` / `session:end`), not
  on the first `orchestrator:complete`.
- The measure-only adapter says cohort labels "now reflect whatever the rest of the config
  actually composes". As HANDOFF itself notes, CI is never detected: the harness keys on
  `context_intelligence.config_resolver`, but upstream CI registers
  `context_intelligence.hook_config_resolver`. I confirmed this in upstream
  `hook-context-intelligence/__init__.py:322`. So `ci` and `ci+memory` labels cannot occur
  today. This bug predates the branch and is not introduced here. Say so in the adapter
  comment.

### P7 — OPTIONAL: test and hygiene nits
- `test_tool_result_carries_verdict_meaning_but_record_does_not` calls `persist=True`.
  `write_falsification_result` prefers the survey's writer when
  `amplifier_module_hooks_survey_capture` is importable. In that case the record goes to
  the survey's real storage instead of `tmp_path`, and the `.json` check is skipped, so
  the test passes without checking anything. In my venv the survey module wasn't
  importable, so the check did run. **Fix:** `monkeypatch.setattr(storage, "_try_survey_write", lambda *a, **k: None)`
  and assert unconditionally.
- `adapters/` holds suggested configs for a separate local setup
  (`~/dev/amplifier-startup-fixes`), and they point at this repo's `@main`. That is fine
  as documentation, but it is scope creep for a perf PR. Consider moving them to their own
  PR, or at least list them in the README "Layout" section.
- Ruff, using the same parent-directory config for both trees: the new test file adds 3
  findings (2× I001, 1× UP032; 44 on the branch vs 41 on main) and is not
  `ruff format`-clean (5 files would be reformatted vs 4 on main). The repo has no lint
  gate, so this doesn't block.
- No CHANGELOG exists in the repo, so there is nothing to update. HANDOFF and PROVENANCE
  entries were added and are accurate, apart from the P2 note.
- No debug code left in. The one `print` is inside the subprocess probe script in the test,
  where it is needed.

## 4. Verified with no problem found

- **Substrate removal leaves behavior unchanged for this bundle's users.** The carrier's
  only runtime effect was a no-op `session:start` hook. amplifier-data still gets installed
  by memory 2.x's own pinned dependencies. `behaviors/substrate.yaml` and the module are
  kept, so existing adapters that include `behaviors/substrate.yaml` (for example
  `~/dev/amplifier-startup-fixes/behavioral-plasticity-app.yaml`) keep working.
- **No config keys renamed and no defaults changed** except the new `once_per_session`,
  which defaults to `True` and is documented in the docstring and spec. `autofire`,
  `ablation_mode`, `benchmark_id` and `results_dir` are unchanged.
- **The tool schema shrinks without changing meaning.** The fields, types and defaults
  (`benchmark_id`, `cohort`, `session_id`, `persist`) are identical. "(needs session_id)"
  is accurate: `execute` only persists when both `persist` and `session_id` are set.
- **`verdict_meaning` stays out of the stored record.** `write_falsification_result`
  serialises `result.to_record()` again from the `VerdictResult`, not from the enriched
  output dict. The test confirms this for the local-file path.
- **Running the benchmark once per session is sound.** All registered benchmarks
  (synthetic, frozen `behavioral-v1` corpus, `memory-recall-v1` against memory's static
  recall fixtures, and the probe fixtures) are deterministic. None of them read the live
  session. Cohort detection comes from tools and capabilities that are mounted and stable,
  so measuring at the end of turn 1 gives the same record per session and benchmark. The
  `spawned` set belongs to one coordinator, so child sessions and resumed sessions each
  still spawn. Dropping the per-turn spawns also removes concurrent workers overwriting
  the same file.
- **The `mount()` return value is fine.** The tool module still returns a metadata dict,
  which is acceptable because it mounts a real Tool. Only a module that mounts no tool must
  return a callable, which is the c4f47cc case.

## 5. Required before opening the PR
1. P1: fix the spawn-success signal and the misleading retry test.
2. P2: add the `@` (inside backticks) to the reference-doc pointer.

Everything else is optional polish. P3 and P4 are quick and worth doing in the same PR.

---
Scratch artefacts left for reproduction: `/tmp/ampup/bundle-review/{measure.py,imp.py,full.diff,venv-bp}`.
The origin/main scratch worktree was removed after the review.
