Verdict: SIGN OFF WITH CHANGES

# Review: `perf/session-footprint` (amplifier-bundle-design-loop)

Branch under review: `perf/session-footprint` @ `510b680`, worktree
`~/dev/amplifier-bundle-design-loop-perf`, 1 commit ahead of `origin/main` @ `8cfb80f`
(`git log --oneline origin/main..HEAD` confirms exactly one commit).

Method: fetched `origin/main`, added a detached scratch worktree at
`/tmp/ampup/bundle-review/scratch-design-loop/main-worktree`, built two fully isolated
`uv venv`s (`venv-branch`, `venv-main`, PyPI `amplifier-core`/`pytest`/`pytest-asyncio`/
`playwright`/`filelock`/`fastapi`/`uvicorn`/`python-multipart` + `amplifier-foundation`
from GitHub + `-e` installs of each worktree's own `modules/*`), and ran the repo's
documented deterministic command (`python -m pytest modules tests -v`, per README
"Develop" section) against both. No installs into `~/.amplifier`; both scratch venvs
and the scratch worktree were removed after review; the branch worktree's `git status`
is unchanged (clean, matches pre-review state — its own `.venv`/`.pytest_cache` are
gitignored and untouched by this review).

## Verified claims (with evidence)

**1. Test suite: zero regressions.**
```
branch (perf/session-footprint): 259 passed, 3 skipped, 28 warnings
main   (origin/main, 8cfb80f):   250 passed, 3 skipped, 28 warnings
```
The 9-test delta is entirely new coverage the branch adds (`tests/test_footprint.py`
×6, `test_mount_does_no_filesystem_io_until_first_append` in
`tool-design-ledger/tests`, plus 2 new cases in `test_bundle_structure.py` for
`behaviors/design-loop-full.yaml`). Every test that passes on main also passes on
the branch. The 3 skips are the same `manual`-marked integration tests on both
sides (require a paid provider key; correctly gated out of the deterministic run).

**2. Per-request footprint: ~2.9k → ~1.35k tokens (own components).**
Ran `scripts/measure_footprint.py` (added by this branch) against the branch, and
a copy of the same script against the main worktree's `behaviors/design-loop.yaml`
(same tools/agents/context, pre-slimming text):
```
main:   TOTAL (own components) 11524 chars ~2881 tok
branch: TOTAL (own components)  5393 chars ~1348 tok
```
Matches the commit message ("~2.9k -> ~1.35k tokens") almost exactly. The
`tests/test_footprint.py` budget (`TOTAL_BUDGET_CHARS = 6500`) is set with
reasonable headroom above the measured 5393, not gamed to just-barely-pass.

**3. `design-intelligence` is genuinely unused by this bundle's own runtime, and foundation already ships it.**
`grep` across all YAML/recipes/agents in the repo found no runtime reference to a
`design-intelligence:*` namespace outside of docs/plans and the new opt-in
`behaviors/design-loop-full.yaml`. Cloned `microsoft/amplifier-foundation` fresh
and confirmed its `bundle.md` directly includes
`git+https://github.com/microsoft/amplifier-bundle-design-intelligence@main#subdirectory=behaviors/design-intelligence.yaml`
(byte-identical URL to the one removed from `design-loop.yaml`) — so any host that
composes `foundation` still gets design-intelligence, unchanged.

**4. `recipes` include still resolves once (dedup), not duplicated cost.**
Read `amplifier_foundation/registry.py`: `BundleRegistry` caches loaded bundles in
`self._loaded_bundles: dict[str, Bundle]` keyed by URI and checks it first (`if not
refresh and uri in self._loaded_bundles: return self._loaded_bundles[uri]`) before
any load. Since `design-loop.yaml` and `foundation`'s `bundle.md` reference the
identical `amplifier-bundle-recipes@main#subdirectory=behaviors/recipes.yaml` URI,
the "deduplicated on foundation" claim in `PROVENANCE.md` holds structurally.

**5. Lazy playwright import removes real mount-time cost.**
`tests/test_footprint.py::test_mounting_tools_does_not_import_playwright` passes on
the branch (fails the underlying premise on main, where `tool-render`'s
`render.py` imports `playwright.async_api` at module scope). Independently timed a
cold-process playwright import in the branch's venv:
```
import_s 0.10284029100148473   (first/cold run)
import_s 0.03552866700920276   (warm FS cache)
import_s 0.03392479100148193
```
~100ms cold, consistent with the commit's "~0.1-0.2 s" figure; not a precise
benchmark (single machine, no host-runtime harness), but the order of magnitude
and the "moved off mount()" mechanism are both confirmed by code + test.

**6. Ledger directory creation is deferred to first append, without introducing a race.**
`mount()` and `DesignLedgerTool.__init__` no longer call `mkdir`; `_op_append`
still does `path.parent.mkdir(parents=True, exist_ok=True)` immediately before
writing (unchanged from main), which is idempotent under concurrent calls.
`_read_records`/`_count_lines` already handled a missing directory/file
(`if not path.exists(): return []` / `return 0`) before this branch, so `query`/
`best`/`dead_fixes` against a not-yet-created ledger dir were always safe. New
regression test `test_mount_does_no_filesystem_io_until_first_append` covers this
end-to-end and passes.

**7. Tool input contracts are functionally unchanged despite terser schemas.**
The only schema shape change is `design_controller`'s `candidate_scores`, from 8
enumerated `properties` to `additionalProperties: {int 0-4}`. Confirmed the
*previous* schema had no nested `required` list either (so it never actually
enforced "all 8 keys present" at the schema level — only in prose), and the
runtime (`_evaluate`, `_gate`) still keys everything off the module-level `DIMS`
constant, unchanged by this diff. Net effect: no real strictness lost, and
`test_tool_input_contracts_preserved` (checks top-level property/required sets for
all 6 tools) passes on the branch.

**8. Agent "firewall contract" semantics were relocated, not deleted.**
`agents/design-critic.md`, `-maker.md`, `-planner.md`, `-judge.md`: only the
YAML-frontmatter `meta.description` (used for the always-sent delegate catalog)
was trimmed; `git diff` shows zero changes below the second `---` (the actual
agent body/system-prompt used when the agent is invoked). Confirmed by line counts
(`design-critic.md`: 133→121 lines, all removed lines inside the frontmatter block)
and by `tests/test_harness_agents_structure.py` (checks the body for the firewall
"never" clause, rubric, JSON contract, etc.) passing unchanged on both sides.

## Problems

### 1. [MUST-FIX] `bundle.md`'s "Division of labour" section is now actively misleading
`bundle.md` (untouched by this PR) still reads: *"`design-intelligence` agents do
the design work; this bundle adds the measurement and governance layer."* This was
already imprecise pre-branch (design-loop's own `design-critic`/`-maker`/`-planner`
agents, not design-intelligence's, do the scored/governed work — confirmed both
existed on `origin/main` already). The PR's entire point is that
`behaviors/design-loop.yaml` no longer includes design-intelligence by default, so
this sentence — sitting in the file a user reads first — now describes a
dependency that is not present unless the host bundle happens to include
`foundation` or the reviewer explicitly opts into `design-loop-full.yaml`. Given
this PR touched `README.md`, `PROVENANCE.md`, `HANDOFF.md`, and `STRUCTURE.md` to
describe exactly this composition change, leaving `bundle.md` stale is a real gap.
**Fix:** reword the "Division of labour" paragraph to state that
`design-critic`/`design-maker`/`design-planner` (this bundle's own agents) do the
design work, and that `design-intelligence` is an optional, separate agent team
available via `foundation` or `behaviors/design-loop-full.yaml`, not a dependency
of the judge/harness described above it.

### 2. [OPTIONAL] `docs/DEV_SETUP.md`'s offline-`prepare()` constraint section is now imprecise
It says *"`bundle.md` includes `amplifier-bundle-design-intelligence@main`"* — true
before this branch (direct include in `design-loop.yaml`), no longer true as a
direct statement (now only transitive, via `foundation`, or via the new opt-in
`behaviors/design-loop-full.yaml`). The underlying constraint this section
documents (design-intelligence pulls in the unpublished `amplifier-foundation`
dependency chain during `prepare()`) still applies whenever a host composes
`foundation`, so this is not functionally wrong, just no longer precisely sourced.
**Fix:** reword to "`bundle.md` includes `foundation`, which in turn includes
`amplifier-bundle-design-intelligence@main`..." (or drop the specific attribution
and describe the constraint generically).

### 3. [OPTIONAL] Cosmetic lint regression in `tool-design-lints/lints.py`
Removing the top-of-file `from playwright.async_api import async_playwright`
import left two consecutive blank lines before `logger = logging.getLogger(...)`.
`ruff` flags this file with `I001` ("import block is un-sorted or un-formatted")
on the branch; the same rule does **not** fire on `origin/main`'s version of the
file (verified by running `python_check` against both). Not a functional issue,
one blank line to delete.

### 4. [OPTIONAL — recommend a smoke check before merge] Trimmed recipe-invocation guidance in `context/design-loop-awareness.md`
The old awareness file carried a fully worked YAML example of invoking
`design-loop:recipes/design-converge.yaml` (`recipe_path:` + a `context:` block
listing every key: `source`, `brief`, `task_class`, `signature`, `run_id`,
`rubric_version`, `bar`, `floors`, `budget`, `epsilon`, `k`, `tau`, `output`,
`work_dir`, `bundle_ref`). The new version only says to supply `source`, optional
`brief`, and an absolute `work_dir`, and states "other keys ... have defaults
documented in the recipe's `context:` block" — which I confirmed is true
(`recipes/design-converge.yaml`'s `context:` section does inline-comment every
default: `bar: 24`, `floors: 2`, `budget: 12`, `epsilon: 1`, `k: 3`, `tau: 0`,
`output: "all"`, etc.), and it's a reasonable place to avoid duplicating text that
is sent on every turn regardless of whether a convergence run happens. However,
this is a genuine reduction in in-context, worked guidance for a
recipe-invocation shape the model must still get right (the `recipes` tool's own
schema teaches the generic `recipe_path`/`context` shape, but not this recipe's
specific required/optional split). The branch's own `HANDOFF.md` states *"No live
`amplifier run` was done"* — i.e., this specific behavior change has not been
exercised end-to-end with a real model. I could not verify it either (out of
scope: no live provider run was performed for this review). **Recommendation:**
before merge, do the one live smoke test `HANDOFF.md` itself proposes next
("compose the behavior... run design-judge once and a 1-budget design-converge
with `bundle_ref` set") to confirm the terser awareness text is still sufficient
for the model to invoke the recipe correctly.

### 5. [OPTIONAL — pre-existing, not introduced by this branch] Lint/type baseline is unchanged but not clean
`python_check` reports the same 4 pyright errors (`amplifier_core`/`playwright`
`reportMissingImports` from running outside the real host runtime type-stubs;
`ViewportSize` dict-vs-TypedDict mismatches) and the same `ruff-format`/`BLE001`
warnings on both `origin/main` and the branch. Not this PR's responsibility to
fix, flagged only so it isn't mistaken for something the branch caused.

## Not found (explicitly checked, no issue)
- No renamed config keys or changed defaults in any tool's runtime behavior
  (`design_controller`'s `DIMS`-driven logic, `design_ledger`'s ledger-path/
  read/append logic, `render`/`render_report`/`target_state`/`design_lints` I/O
  contracts are all byte-for-byte unchanged in this diff outside of
  description/schema text and import placement).
- No composition changes that break a host bundle: `behaviors/design-loop.yaml`
  still declares the same `tools:`/`agents:`/`context:` blocks; only the
  `includes:` list lost `design-intelligence` (verified unused, see claim 3) and
  kept `recipes` (verified required — `recipes/design-pass.yaml` and
  `recipes/design-converge.yaml` both run as `recipes` bundle recipes).
- No concurrency/background-work/once-per-session logic touched at all by this
  diff — the only stateful component (`design_ledger`) still does synchronous,
  idempotent file I/O per call.
- No unrelated changes in the diff; every touched file maps to the commit
  message's five bullet points.
- Commit message is accurate against the diff and against my own measurements.
