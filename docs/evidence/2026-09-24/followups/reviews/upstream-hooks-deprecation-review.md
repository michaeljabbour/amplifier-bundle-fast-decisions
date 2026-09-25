# Independent review: hooks-deprecation "authored config only" fix

**Verdict: ACCEPT WITH CHANGES.** The core idea is sound and the speed-up is real. Before this goes upstream, fix one new crash on Python 3.11/3.12 (a symlink loop). Also correct the PR description: its main claimed consequence, "the injection landed in every session", did not happen on this machine.

Reviewed: branch `fix/deprecation-scan-allowlist` @ `ff56431` against `origin/main` @ `ce876d5`. The patch file matches `git diff origin/main` apart from its `format-patch` header and footer. Machine: macOS arm64. The Amplifier CLI here runs on Python 3.12.11 with amplifier-core 2.0.1 (RustSession). Tests were also run on 3.11, 3.12 and 3.13.

All scratch work lives under `/tmp/ampup/review/scratch/`. I removed the leftover scratch git worktree (`wt-main`) and `.ruff_cache`, and `git status` is clean. I did not modify anything under `~/.amplifier`.

---

## 1. Verified claims

### 1.1 Tests: VERIFIED, with one caveat
```
$ PYTHONPATH=modules/hooks-deprecation /tmp/ampup/fvenv/bin/python -m pytest -q modules/hooks-deprecation/tests
76 passed in 0.11s                                  # py3.13
$ uv run --python 3.11 / 3.12 ... pytest ...        # 76 passed on each
```
- **"72 existing tests pass unchanged": true.** I ran `origin/main`'s test file against the HEAD module and got `72 passed`.
- **The new tests do catch the change.** Running them against the `origin/main` module gives `4 failed, 72 passed`: all 4 `TestFindSourceFilesAuthoredOnly` tests fail.
- **Useful side evidence for the PR.** On `origin/main`, four existing tests scan the *real* home directory and are very slow on this machine:
  ```
  12.31s TestMultiTombstoneMount::test_list_form_both_fire
  12.11s ...::test_single_flat_config_is_pass_through_identical_to_direct_hook
  11.94s ...::test_union_of_flat_and_list_both_fire
   5.74s ...::test_single_flat_config_fires_once_per_session_through_mount
  ```
  The whole suite takes 41.9 s on main and 0.11 s on HEAD.
- **Caveat: CI does not run these tests.** `.github/workflows/ci.yml` runs `uv run pytest tests/`. That explicit path overrides `testpaths`, which lists only `tests` and `modules/tool-delegate/tests` anyway. The PR's test evidence is local only, and the Windows CI legs never exercise this code.

### 1.2 Performance: VERIFIED on this machine
I benchmarked `origin/main`'s function against HEAD's, loaded from files (`scratch/bench.py`), with cwd set to the repo:
```
dirs [cwd, home]:              origin/main 7.389s / 6.406s   HEAD 0.002s / 0.003s
dirs [wd, cwd, home] (real):   origin/main 7.246s / 5.884s   HEAD 0.003s / 0.002s
```
The size of `~/.amplifier` right now:
- `projects/`: 323 YAML files, **21,407 directories**, 170.4 GB
- `team-knowledge/`: 5,075 YAML files
- `cache/`: 1,074
- `resolve/`: 430
- `evaluation/`: 279
- `recipe-runner/`: 181
- The whole of `.amplifier`: 36,412 directories

The PR says "~35k directories" inside `projects/`. That is wrong: 35k is the total for all of `.amplifier`, and `projects/` has about 21k (see §3).

The cost also shows up in real sessions. Across 60 recent sessions, the median gap between the `routing:matrix-loaded` event and the `deprecation:warning` event was **6.52 s** (range 0–32.9 s). That gap is consistent with the benchmark, but it is not isolated: other `session:start` work sits inside it. I could not reproduce the author's cProfile figure ("5.5–7.7 s") from the materials provided.

Two more structural points check out:
- **It blocks the event loop.** `find_source_files` is synchronous and is called from `async on_session_start` (`__init__.py:315`).
- **Sub-sessions pay the cost too.** All 23 delegated sub-sessions among the 468 sessions from the last 2 days emitted `deprecation:warning`.

### 1.3 False-positive evidence: VERIFIED
`origin/main` returns 15 paths and HEAD returns 0. All 15 are under `~/.amplifier/team-knowledge/made-team-knowledge-data/`:
- 9 are live knowledge-base files (`manifest.yaml`, `people/*/profile.yaml`, `capabilities/**/…hooks-redaction….yaml`)
- 6 are under `.kb-backup/`

None of them is authored config. The only authored locations here are `~/.amplifier/settings*.yaml`, which do not mention `redaction`, and `~/.amplifier/bundles/`, which contains no YAML.

### 1.4 "The injection landed in every session": REFUTED as written
Tracing the code path:
- `behaviors/redaction.yaml` is included by `bundle.md:36` and `bundles/anchors/bundle.md:17`, so every foundation or anchors session mounts this tombstone.
- The `composed` signal from #277 is **False** for this tombstone. The replacement bundle's module ID is `hook-redaction` (singular; `amplifier-bundle-redaction/behaviors/redaction.yaml`), so `"hooks-redaction" in declared_ids` is false. With `require_evidence: true`, the file scan is therefore the **only** thing that decides firing.
- End to end with the real `amplifier_core.HookRegistry` (`scratch/e2e/e2e.py`, team-knowledge-style fixture): `origin/main` produces `emit -> inject_context`, HEAD produces `emit -> continue`. **At the hook level, the claimed consequence is real.**

But on this host the injection never reaches the model:
- **The event fires everywhere.** 468/468 recent sessions emitted `deprecation:warning`. In this review session it fired with `n_source_files=15`.
- **The text never reaches the model.** 0/468 sessions have the warning text in their first `llm:request`. 0/467 other sessions contain `DEPRECATION WARNING: hooks-redaction` anywhere in `events.jsonl`.
- **The logs do capture injections.** The same `llm:request` payloads *do* contain other hooks' injections (`hooks-status-context`, `hooks-skills-visibility`, `routing-matrix`, …).

So on amplifier-core 2.0.1 / RustSession, the result of `session:start` is not applied to the model's context. For comparison, the pure-Python `session.py` `execute()` calls `await self.coordinator.hooks.emit(event_base, payload)` and discards the result.

What is actually observable on this machine is narrower: a false `deprecation:warning` event, carrying 15 unrelated file paths, recorded in every session's `events.jsonl` and in anything that captures events. That is still a real bug, but it is a different claim from "system-context injection landed in every session". (Separately, the hook's `session:start` injection looks undeliverable on this kernel version. That deserves its own issue and is not in scope here.)

### 1.5 "Firing logic, severity, `composed` and message format untouched": TRUE for the code, imprecise for the output
Only `find_source_files` changed. Its *output* does change in three ways:
- results are de-duplicated
- results are sorted
- the set of files differs

Those results feed both the "Found in:" list and the event's `source_files` payload.

---

## 2. Problems found, most severe first

### P1 (must fix): new crash on Python 3.11 and 3.12 when a symlink loop ends in `.yaml` under `bundles/`
`key = str(yaml_file.resolve())` (`__init__.py:195`) runs **outside** the `try`. Before 3.13, `Path.resolve()` raises `RuntimeError` on a symlink loop, even in non-strict mode. `os.walk` still lists a looping file symlink in `filenames`.

Reproduced with `scratch/edge.py`:
```
py3.12  bundles/loop.yaml self-symlink   old=['…/bundles/ok.yaml'] | new=RAISES RuntimeError: Symlink loop from …
py3.13  same                             old=[…ok.yaml]             | new=[…ok.yaml]
py3.11  Path.resolve: RuntimeError       py3.12 Path.resolve: RuntimeError       py3.13: ok
```
End to end on 3.12 with the real HookRegistry:
```
LOG ERROR amplifier_core.hooks: Hook handler error for event 'session:start' (handler 'deprecation'):
  … RuntimeError: Symlink loop from '…/.amplifier/bundles/loop.yaml'   [loop] emit -> continue
```
In that fixture `settings.yaml` really does reference `hooks-redaction`. HEAD logs an ERROR in every session and suppresses a **genuine** warning; main warns correctly. The module declares `requires-python >=3.11`, CI tests 3.11–3.13, and the installed CLI runs 3.12. The trigger is rare, but it breaks the documented "best-effort, silently skips unreadable files" contract.

**Fix.** Use `os.path.realpath(yaml_file)`, which never raises on loops (verified on 3.11, 3.12 and 3.13), or compute the key inside the `try` and catch `RuntimeError` as well. Add a test. (`os.symlink` needs to be skipped on Windows when it lacks privileges.)

### P2: the PR description's headline consequence is overclaimed (§1.4)
"Its system-context injection landed in **every session**" and the table row "Deprecation injection in sessions … yes → no" are not what this machine shows. **Fix:** see §3.

### P3: the contract narrows more than the "Behavior change" section says
`scratch/edge.py` results, old vs new, on both 3.12 and 3.13:

| Case | origin/main | HEAD | In the PR? |
|---|---|---|---|
| `.amplifier/profiles/dev.yaml`, `.amplifier/recipes/r.yaml` | found | not found | yes (profiles) |
| `bundles/a/b/c/d/e/x.yaml` (5 directories deep) | found | not found | yes |
| `bundles/.hidden/x.yaml` | found | **not found** | **no** |
| `.amplifier/bundles` itself a symlink | **not found** | **found** | **no** (widens the scan) |
| Duplicates when working_dir == cwd, or cwd == home | reported twice | once | partly (only cwd == home is mentioned; working_dir == cwd is the common case, since `on_session_ready` always appends both) |
| `bundles/x -> ~/dev/x` (symlinked dev checkout) | not found | not found | no change, but worth stating as a known gap |
| `.yml`, `bundle.md`, `Settings.YAML` | not found | not found | no change (pre-existing gap) |
| unreadable `.amplifier` or `bundles/`, dangling symlink, directory symlink loop, non-UTF-8 file | skipped | skipped | no change |

Also note the existing `test_scans_nested_yaml_files` docstring: *"Finds bundle references in nested .amplifier/ subdirectories."* That states the broader, old contract. The test passes only because it happens to use `bundles/`. So the PR's line "exactly what the existing tests already treat as evidence" is a stretch.

**Fix:**
- List every row above in the PR.
- Update that docstring to "…under `.amplifier/bundles/`".
- Decide deliberately whether hidden directories under `bundles/` should really be skipped. Skipping `.git` is the useful part; a plain `d != ".git"` would be the narrower change.

### P4: "top-level `*.yaml` = authored settings" is not accurate
This machine's `~/.amplifier/` top level includes tool-written YAML: `distro.yaml`, `hosts.yaml`, `tui-preferences.yaml`, `fable-overrides.stash.yaml`. They are scanned before and after the change. None mentions `redaction` today, so there is no false positive now. But the code comment's claim ("authored configuration … lives in exactly two places") and the PR's "Change" section overstate it.

**Fix:** soften the comment to "the locations where users author configuration, plus whatever else sits at the top level". Optionally restrict the top level to `settings*.yaml`. That would be stricter, but the maintainers should make that call.

### P5: the carrier config can still match itself under `bundles/` (pre-existing, not a regression)
With a copy of amplifier-foundation (without `.git`) at `~/.amplifier/bundles/amplifier-foundation/`, both versions report `amplifier-foundation/behaviors/redaction.yaml` as evidence (main in 33 ms, HEAD in 7 ms). The #344 class of bug is narrowed, not closed. **Fix:** mention it as a known residual. A structural fix (for example, ignoring files that are themselves `hooks-deprecation` carriers) belongs in a follow-up.

### P6: lint and format regress relative to main (default ruff; the repo has no ruff config)
- `ruff check`: one **new** `I001` (`import os` placed after `from datetime import date`). Main has 9 findings, HEAD has 10.
- `ruff format --check`: main reports "3 files already formatted"; HEAD reports "**2 files would be reformatted**" (the `dirnames[:] = … if … else sorted(…)` expression, and the aligned comments and long asserts in the new tests).

**Fix:** run `ruff check --fix` and `ruff format` on the module. Optionally add `-> Iterator[Path]` to `_authored_yaml_files`.

### P7: commit trailer does not follow repo convention
The commit ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Recent upstream commits use `Generated with Amplifier` + `Co-Authored-By: Amplifier <240397093+microsoft-amplifier@users.noreply.github.com>` (13 of the last 40). **Fix:** amend the trailer.

### P8 (minor): residual hygiene worth mentioning
- **Tests still read the real home directory.** `TestMultiTombstoneMount` tests call `on_session_ready`, which scans the reviewer's real `Path.home()` and `cwd`. After this PR that is fast, but it is still non-hermetic. It could be a follow-up that monkeypatches `HOME` and `cwd`.
- **Whole-file reads are unchanged.** Files under `bundles/` are still read whole with no size cap. The depth cap bounds this in practice; a cap is optional.

---

## 3. Upstream acceptability and alternatives

- **An allow-list is the right shape.** A deny-list has to name other bundles' private directories and goes stale. Pruning only `cache/` would fix neither the `team-knowledge/` false positives nor most of the walk.
- **"Skip the scan when `composed` decides" would not help here.** For this tombstone `composed` is False, because the replacement module ID is `hook-redaction`. The scan is the deciding signal, so that alternative removes nothing in the case that motivated the PR. It also changes the "Found in:" content for `require_evidence: false` tombstones.
- **Running the scan in a thread (`asyncio.to_thread`)** fixes blocking but not the cost or the false positives. At about 2 ms it isn't needed; omitting it is fine.
- **A simpler option for maintainers to consider:** drop the filesystem fallback entirely now that #277 exists, or keep only top-level `settings*.yaml`. That is more Occam, but it is a policy change. Raise it as a question; don't bundle it into this PR.
- **Timing matters.** The only `require_evidence` tombstone sunsets on 2026-10-01, one week from today. Once it is removed, the scan costs nothing. The durable value is the performance and correctness contract for *future* tombstones, and the PR should lead with that.
- **Likely maintainer reception:** accepted once P1 is fixed and the description is honest about delivery (§1.4) and the full list of behavior changes (P3).

---

## 4. Required wording changes in the PR description

1. **Title.** Drop the unqualified "(5.8 s → 2 ms per session start)". Suggested:
   `fix(hooks-deprecation): scan only authored .amplifier config for evidence`
   Put the numbers in the body, labelled "on a heavily used machine".
2. **Correctness bullet.** Replace "the deprecation warning fired and its system-context injection landed in every session" with:
   > Because `require_evidence` was satisfied (and `composed` is false: the replacement module is `hook-redaction`), the hook returned `inject_context` and emitted `deprecation:warning`, listing 15 unrelated files, in every session and sub-session (468/468 sessions over two days on that machine). *(On amplifier-core 2.0.1 the `session:start` injection did not appear in the model request; that is a separate delivery issue.)*
3. **Measurements table.**
   - Change the "Deprecation injection … yes → no" row to "`deprecation:warning` emitted with false evidence: every session → none (and the hook returns `continue`)".
   - Add the Python version.
   - Say it is one machine.
4. **Machine-profile table.**
   - `projects/`: "~35k directories" → "~21k directories (about 36k across all of `.amplifier`)".
   - `team-knowledge/`: "2,000+" → "~5,000".
   - Say the numbers are a point-in-time snapshot of one machine.
5. **"Why an allow-list".** Delete "exactly what the existing tests already treat as evidence". Say instead that the old docstring promised all nested subdirectories and that this PR narrows it (and updates the docstring).
6. **"Behavior change and risk".** Add:
   - hidden directories under `bundles/` are now skipped
   - a symlinked `.amplifier/bundles` is now scanned (previously it was not)
   - symlinked bundle directories inside `bundles/` are still not followed
   - results are de-duplicated (this also covers working_dir == cwd) and sorted
   - `.yml` and `bundle.md` are still not scanned (unchanged)
7. **"Change" section and code comment.** Replace "exactly two places" / "top-level `*.yaml` … settings files" with wording that admits tool-written top-level YAML is scanned too (P4).
8. **"Tests" section.**
   - Say the module tests are **not** part of CI (`ci.yml` runs `pytest tests/`) and give the local command.
   - List the Python versions actually run (3.11, 3.12, 3.13).
   - Update the counts once the P1 test is added.
   - Optionally cite the 41.9 s → 0.1 s suite time as supporting evidence.
9. **"How it was found".** Drop the fast-decisions / "59 s trivial prompt" anecdote, or mark it as context the maintainers can't verify. The PR should stand on reproducible numbers alone.
10. **Open questions.** Add: "Should the filesystem fallback exist at all now that `composed` (#277) exists, or be limited to `settings*.yaml`?"

---

## Evidence index (scratch, not committed)
- `scratch/bench.py`: before/after timing and hit counts. I fixed a module-loading bug (`sys.modules` registration) so it runs.
- `scratch/edge.py`: the edge-case matrix, old vs new, on 3.12 and 3.13.
- `scratch/e2e/e2e.py`: `on_session_ready` → real `HookRegistry.emit("session:start")`, old vs new, false-positive and symlink-loop scenarios.
- `scratch/maintests_run/`: main's tests against the HEAD module, and the new tests against the main module.
- `scratch/ruff_main.txt`, `scratch/ruff_head.txt`: lint diff.
- `scratch/recent_events.txt`: the 468 session event logs used in §1.2 and §1.4 (read-only greps and `jq`-style field extraction; no large lines were printed).
