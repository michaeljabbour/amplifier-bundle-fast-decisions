Verdict: SIGN OFF WITH CHANGES

# Review: amplifier-bundle-memory `perf/startup-latency` (7 commits, origin/main bed0272 → HEAD 0096dc1)

Reviewer: independent, skeptical. Nothing committed or pushed. Worktree `git status` is clean. The scratch
`git worktree` of origin/main was removed (`git worktree list` shows only the two original worktrees).

## Safety of this review

- The live daemon was checked before and after: `pgrep -fl tool_memory.daemon` →
  `11847 …amplifier-runtime/bin/python -m amplifier_module_tool_memory.daemon --daemon --home ~/.amplifier/memory`
  both times. I never started, stopped, or talked to it.
- Every test and bench ran with `HOME=/tmp/ampup/bundle-review/scratch-memory/home-{main,branch}`,
  `AMPLIFIER_MEMORY_HOME=…/memhome-{main,branch}`, and `UV_PROJECT_ENVIRONMENT` set to scratch venvs.
  Nothing was installed into `~/.amplifier`.
- The only access under `~/.amplifier` was reading:
  - `~/.amplifier/memory/store.log` was copied with `cp` (sha256 prefix `7def09b16d1f934301a2` on both
    copies). All benches ran on the scratch copies, which have since been deleted.
  - The cached `loop-streaming` / `context-simple` module sources were read to check how delivery behaves.

## 1. Test suites (branch vs origin/main)

The repo documents two commands: `uv run pytest` at the root (CI runs an explicit subset of files) and each
module's own `pytest`.

- **amplifier-core:** the module venvs don't include it, because it is a peer dependency. I added it with
  `--with amplifier-core==1.3.3` (the version the root lock pins).
- **Root tests:** these ran with `--ignore=tests/integration` (see problem 8).

| Suite | origin/main | branch |
|---|---|---|
| root `tests/` (`--ignore=tests/integration`) | 116 passed, 1 deselected | 116 passed, 1 deselected |
| `modules/tool-memory` | 271 passed, 1 skipped | 296 passed, 1 skipped (+25 new) |
| `modules/hooks-memory-briefing` | 12 passed | 23 passed (+11 new) |
| `modules/hooks-memory-interject` | 24 passed | 27 passed (+3 new) |
| `modules/hooks-memory-capture` (`--with pytest`) | 24 passed | 24 passed |

- **Regressions:** none. No test that passes on main fails on the branch.
- **Existing tests:** the only ones touched are additions to the two `conftest.py` files and
  `test_client_ensure_daemon.py`. No assertions were weakened.
- **The one skip** is the same on both sides: `test_curate_dot.py:71`, attractor engine not available.
- **Race reproduction:** `test_unserialized_kernel_races` ran and passed, not skipped. So the Rust
  "Already borrowed" race does reproduce on this machine without the fix, and the fixed version is clean.

## 2. Verified claims (with evidence)

### Store read paths: re-measured in-process on a copy of the real store (403,089 events, 178 MB)

Both sides ran the same workload (`bench_store.py`), one after the other, not concurrently.

- The "branch, no reuse" column sets `SNAPSHOT_REUSE_S = 0`. It isolates each call from the 5 s snapshot
  sharing, so it is the honest per-call number.
- The "branch (reuse)" column is a burst of calls, where snapshot sharing applies.

| Op | main | branch, no reuse | branch (reuse, burst) | Claim | Holds? |
|---|---|---|---|---|---|
| wing search (vector), 1st call | 3.00 s | 1.78 s | 1.78 s | 3.25 → ~1.0–1.15 s | Partly. ~1.0–1.2 s once the ref cache is warm. The first search after daemon start is ~1.8 s. |
| wing search, repeat | 3.02 s | 1.04 s | 0.66 s | " | Yes |
| global search | 3.52 s | 1.74 s | 1.29 s | " | Roughly |
| room search | 3.13 s | 1.18 s | 0.76 s | – | – |
| degraded (no vector) wing search | **119.6 s** | 0.42 s | 0.05 s | minutes → 0.5–1.2 s | Yes |
| `read_diary` | 1.31 s | 0.37 s | 0.03 s | 1.36 → 0.37 s | Yes |
| `query_kg` | 0.37 s | 0.34 s | 0.00 s | – | – |
| `list_drawers(limit=6)` | 37.95 s | 0.38 s | 0.03 s | 39.3 → 1.2 s | Yes (better than claimed) |
| `list_drawers(wing, 20)` | 131.9 s | 0.38 s | 0.03 s | – | – |

### Results are identical

- **Real-store copy:** all 9 workload results are equal, main vs branch. The only difference is the new
  `importance` key on search hits.
- **Diary/KG on the real store proves nothing.** The live store has no diary entries and no KG facts, so the
  commit's claim that diary and KG are "byte-equal on the real store" is technically true but only because
  both sides return nothing.
- **Synthetic store, to cover that gap:** 600 drawers across 4 wings and 7 rooms, with mixed importance,
  categories and embeddings. It also has 40 diary entries for 2 agents, 60 KG asserts plus invalidations and
  re-asserts, and 12 `update_importance` calls.
  - All 22 read results are equal: search (vector and lexical, wing/room/global), diary, `query_kg`
    (subject, predicate, None, unknown subject), `kg_timeline`, `list_drawers` (all/wing/room) and
    `kg_stats`.
  - The new `importance` field matches main's old per-hit `has_importance` lookup on **56/56** hits.

### Reads no longer append to the log

The same workload appended 8 events to the log on main and 0 on the branch. On the synthetic store it was
18 on main and 0 on the branch.

`_read_ref` computes `CellWriteEvent(payload=…).cell_ref()`. That is exactly what
`AmplifierStore.write_cell(payload)` returns when `interpreters=()`, which I checked in the amplifier-data
source.

### No stale reads within the 5 s snapshot reuse window (branch, durable Rust kernel, kernel lock applied)

- **Sequential check:** 20 rounds of write-then-immediately-read, covering `file_diary`, `assert_kg`,
  `invalidate_kg`, `file` + `search`, `list_drawers`, `update_importance` and `rollback`. **0 stale results.**
- **Concurrent check:** 4 reader threads (`read_diary` + `search`) ran alongside a writer doing 150 diary
  writes. Each reader checked that every write *completed before its call started* was visible.
  286 reads, **0 stale, 0 errors.**
- **Why this holds:**
  - The generation counter is read before `all_events()`.
  - The kernel observer bumps it synchronously inside `append_batch`.
  - `_snapshot_lock` is never held across a kernel call, so the lock order (kernel RLock, then
    snapshot lock) can't deadlock.

### Daemon locking change

- `DurableKernel._lock` is a `threading.RLock`. `append_batch` holds it and then calls the wrapped
  `_fk.append`, so taking the same lock again is safe.
- `all_events()` returns a fully built list, so holding the lock around the call covers the whole Rust
  borrow.
- `/health` doesn't touch the kernel, so long reads can't make the daemon look wedged.

### Briefing delivery mechanics

- **Hook order:** on amplifier-core 1.3.3 (test pin) and 2.0.1 (the user's installed CLI), a priority-10
  handler runs before a priority-20 one, and the two `inject_context` results are merged
  (`'[briefing10]\n\n[interject20]'`). So the briefing doesn't suppress interject, and
  `memory:briefing_assembled` fires before interject searches.
- **Side calls:** `loop-streaming` emits `provider:request` with `iteration: 0` only for its side calls
  (goal judge/evaluator). The main loop uses `iteration >= 1`, so skipping iteration 0 is correct.
- **First-prompt injection:** `loop-streaming` stores an ephemeral `prompt:submit` injection and applies it
  to the first iteration, so the briefing does reach the model.

### `max_inject_chars` fix

I fuzzed 12,000 memory sets against caps of 100/300/800/2000:
- **Branch:** the largest output was cap + 10–15 chars.
- **main:** the largest output was ~7,000–9,000 chars, whatever the cap (e.g. 7,802 chars under 800).

The claimed bug is real and the fix is correct.

### Version / shutdown rule (`client.py`)

- The version-mismatch shutdown now runs only if `_should_retire(theirs, mine)`: never for `0.0.0-dev`,
  never for unparsable versions, only when the daemon's version is numerically strictly lower.
  - This is what now protects the live 2.0.1 daemon from test/dev venvs.
  - The branch's root `tests/conftest.py` also points `AMPLIFIER_MEMORY_HOME` at a tmp dir for every test.
- **Edge case (harmless):** `(2,0) < (2,0,0)` in Python tuple comparison, so a daemon reporting "2.0" would
  be retired by a "2.0.0" client. Not realistic.

### Token, schema and import-time costs

- **Tool schemas:** unchanged. The only change in `tool-memory/__init__.py` is the version string.
  `context/`, `agents/` and `skills/` are unchanged.
- **Import time:** `amplifier_module_hooks_memory_briefing` imports in about the same time on both sides
  (`-X importtime`, cumulative, warm: main 75–90 ms, branch 80–91 ms). No measurable change.
- **Injected tokens go UP by design.** The briefing is now actually delivered: 300–1,500 tokens
  (`token_budget: 1500`). See problem 2 for why this is more than a turn-one cost.

### Not re-verified

- "9.2 s blocked at session:start, 0 chars delivered" in a real session. This would need a real host
  session against the real store. The code confirms delivery moved off `session:start`, but I didn't run it.
- "1,449 briefing lookups lost to HTTP 400". I didn't mine the live events directory.
- "30 s+ with a cold daemon".

## 3. Problems, most severe first

### 1. MUST-FIX: snapshot expiry timers pin every fold for 5 s, multiplying daemon memory

**Where:** `store.py`, `_fold_snapshot`:
`threading.Timer(self.SNAPSHOT_REUSE_S, self._expire_snapshot, (fold,))`.

**What goes wrong:**
- Every new snapshot starts its own timer thread, and that thread holds a strong reference to the fold for
  5 s.
- On the real store a fold is ~300–500 MB of Python objects.
- `_on_append` clears the snapshot slot, but it can't release folds still held by earlier timers.
- So any interleaving of writes and reads keeps several folds alive at once. That interleaving is normal
  daemon traffic: capture-hook `remember` calls mixed with interject/briefing searches across sessions.

**Measured on the real-store copy (8 write+read pairs within 5 s):**

| | Peak RSS | Timer threads alive |
|---|---|---|
| main | 809 MB (681 MB steady) | – |
| **branch** | **3,240 MB** | 10 |
| branch, still ~1.96 GB after the timers expired | 1,959 MB | – |
| branch with the fix below (monkeypatched Timer holding a `weakref`) | **847 MB** | – |

The synthetic concurrency run also left 256 live timer threads.

**Fix:**
- Give the timer a `weakref.ref(fold)` (or just a generation/identity token) instead of the fold. The
  measurement above confirms this restores main-level memory.
- Or drop the timer entirely and do an age check on access (the slot is already cleared on append).
- Add a regression test asserting that only one fold stays reachable after N write/read pairs, e.g. with
  `weakref` plus `gc.collect()`.

### 2. MUST-FIX: the intended behavior changes are under-disclosed, and one claim is wrong under the default orchestrator

**How the CHANGELOG presents it:** the change appears under **"Fixed"**, framed as "now actually reaches
the model". Missing from the CHANGELOG:

- **Token cost.** Nothing says this adds a new per-session token cost of up to ~1,500 tokens
  (`token_budget`).
- **Persisted, not ephemeral.** Under the current `loop-streaming` default, `ephemeral_injection_mode:
  "persist"` (both cached copies, line 1255):
  - The "ephemeral" injection is **added to the conversation as a persisted user message**
    (`_persist_reminder` → `context.add_message(... metadata: {ephemeral: True, persisted: True})`).
  - `context-simple` then protects that message during retention/compaction (`_protected_sequences`).
  - So the briefing rides along on **every later request in the session**, cached but still counted
    against the context window. It is not a turn-one-only cost.
  - The briefing's own footer, "*This briefing is ephemeral and will not appear in conversation history.*",
    is false in that mode.
- **Sub-agents.** "sub-agent sessions are skipped" is a half-sentence. It should say sub-agents now get no
  briefing by default. (On main they got nothing either, because `session:start` results were discarded,
  but the intended behavior did change.)
- **Cross-session staleness.** The `cache_ttl_s: 300` reuse means a second session in the same process
  within 5 minutes gets the first session's memory sections, missing writes made in between.
- **Automatic daemon replacement.** Upgrading to 2.0.2 automatically retires a running 2.0.1 daemon on
  first contact. This is in the release commit message but not the CHANGELOG.

**Fix:**
- Add a `### Changed` (behavior) section stating: the delivery point, the token cost, sub-session default
  off (`brief_subsessions`), the 300 s per-process cache, and the automatic 2.0.1 → 2.0.2 daemon
  replacement.
- Either reword the footer, or state that under `ephemeral_injection_mode: persist` the briefing is
  retained in history.
- Mirror this in `behaviors/memory.yaml` comments and the briefing README.

### 3. OPTIONAL (should fix): process exit waits for an unfinished prefetch

**What goes wrong:**
- The prefetch runs on a `concurrent.futures.ThreadPoolExecutor`, which uses non-daemon threads that the
  interpreter joins at exit. The nested pool in `_fetch_memory_part` is the same.
- A session that ends before delivery (quit right after start, or a one-shot `amplifier run` whose turn
  finishes before a cold prefetch) holds the process open until the prefetch finishes. With a cold spawn
  plus 15 s HTTP client timeouts, that can be tens of seconds.
- Measured: mount with an `ensure_daemon` stub that sleeps 6 s → `mount returned after 0.00s`, process
  `real 6.39s`.
- This is not worse than main (which blocked ~9 s at start), but it contradicts "never blocks".

**Fix:** run the job on a `threading.Thread(daemon=True)` feeding a `Future`, and/or abandon the job on
`session:end`. Document it either way.

### 4. OPTIONAL: partially failed prefetches get cached

**What goes wrong:**
- `_call_client` turns any error (timeout, HTTP 400, …) into `None`.
- `_prefetch_job` still returns `kind=_OK`, with the failed section simply missing.
- That result is then reused for 300 s by sibling sessions. So "A failed or daemon-unavailable result is
  never reused" only holds for total failure.
- Separately, the prefetch runs at `mount()` even for sub-sessions that will never be briefed. Usually a
  cache hit, so cheap, but not free on first mount.

**Fix:** mark the result not cacheable if any `_call_client` returned `None` because of an exception.

### 5. OPTIONAL: `_CellRefCache` throws away its whole memo when an older snapshot arrives late

**What goes wrong:** when a thread that materialized an older (shorter) event list calls `refs_for` after a
newer one, the check `n > len(events)` wipes the memo. It then re-hashes ~220k cell writes (~1.5 s). This is
correct but can thrash under concurrent read/write.

**Fix:** when `n > len(events)`, check that `events[-1][0]` matches the memoized position at that index and
return `self._refs[:len(events)]` without resetting.

### 6. OPTIONAL: the kernel-lock fix depends on amplifier-data private attributes

**What goes wrong:** `_serialize_kernel_access` silently does nothing if a future amplifier-data renames
`_fk`/`_lock`. The pinned-commit test would catch that on a pin bump, but the daemon itself would not warn.

**Fix:**
- Log a warning when the store is durable but can't be wrapped.
- File the upstream fix (`DurableKernel.all_events` and `resolve` should take `_lock`), as the commit
  message already suggests.

### 7. OPTIONAL: interject cap is soft by up to ~15 chars

**What goes wrong:**
- `total` doesn't count the `"\n---\n"` separators or the join newlines, so output can exceed the cap by up
  to ~15 chars (fuzz: cap 800 → max 810, cap 2000 → max 2015).
- With `max_chars` below ~55, the result is a header-only injection with no memory in it.

**Fix:** count separator lengths, and return `""` when no snippet fits.

### 8. OPTIONAL (pre-existing, not introduced here): root `uv run pytest` silently skips the whole root suite

`tests/integration/conftest.py`'s `pytest_collection_modifyitems` marks **every** collected item as skipped
off-DTU: 124 skipped on both main and branch. Only CI's explicit file list avoids this.

**Fix (separate PR):** scope the skip to items under `tests/integration/`.

### 9. OPTIONAL hygiene

- **Ruff:** findings on the touched source files went from 76 on main to 80 on the branch; I didn't
  enumerate the four new ones. The baseline isn't clean, so this is not a gate, but worth a `ruff check`
  pass before the PR.
- **`bench_startup.py` prints:** these are intentional CLI output, not leftover debugging.
- **Scope:** no unrelated file changes.
- **Commit messages:** accurate, except that the store-perf commit's claim of byte-equal diary/KG on the
  real store proves nothing (both sides are empty). Say so, or cite the synthetic check.

## Bottom line

- **Correctness is good:** read-path results are identical, there are no stale reads, the Rust race is
  genuinely fixed, and the `max_inject_chars` and version-rule fixes are right.
- **Perf claims hold or beat the claims.** The one exception is the first search after daemon start
  (~1.8 s, not ~1.0 s).
- **Merge after:**
  - (1) fixing the timer holding each fold, a small but real daemon memory regression (~4× peak RSS);
  - (2) disclosing the token/persistence/sub-session/auto-retire behavior changes as behavior changes, and
    correcting the "ephemeral" footer claim under the default `persist` mode.
