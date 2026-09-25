Verdict: SIGN OFF WITH CHANGES

# Review: amplifier-bundle-preceptor `perf/session-footprint` (5 commits on origin/main a32309a)

Reviewer: independent. Every claim below was reproduced with commands. Output is excerpted
inline. Scratch worktrees were created under `/tmp/ampup/bundle-review/scratch-preceptor/`
and then removed. The branch worktree was never modified (`git status` clean at the end).

```
5aadfc0 perf(context): trim agent descriptions and cue-awareness; document footprint
e50b021 perf(tool-preceptor): advertise only the schema fields an instance's operations use
9475285 perf(injector): libyaml CSafeLoader, lazy yaml import, shared continue result
58d5bb2 perf(observer): take large-input hashing and mid-turn flushes off the critical path
ad5b461 bench: footprint.py measures per-request tokens and per-event hook latency
14 files changed, 1052 insertions(+), 144 deletions(-)
```

## Summary

The engineering is sound, and the headline numbers reproduce exactly: per-request tokens
2153 → 1076, and large-input hook latency drops from milliseconds to microseconds. I found
no failing tests and no removed tests. There are no config-key, default, composition or
public-API changes. Two things should change before merge:

1. It edits `context/cue-awareness.md` without the ablation this repo requires. That
   file's last reduction was gated by one.
2. It bundles a real behavior change (the `cue_ids_dosed` fix) inside a `perf:` commit.

Both are cheap to fix.

---

## 1. Tests: branch vs origin/main

Documented command: `make test`, which runs `uv run --no-project --with pytest
--with pytest-asyncio --with pyyaml pytest tests/` per module, plus a cross-module suite.

**Environment trap.** Plain `make test` on the branch passes (21/11/61/28). On a clean
`origin/main` worktree under `/tmp` the same command gives `1 error` (observer) and
`4 errors` (tool-preceptor): `ModuleNotFoundError: No module named 'amplifier_core'`. The
cause is that the branch worktree lives under `~/dev`, so uv silently discovers
`~/dev/.venv`, which has amplifier_core:

```
$ uv run --no-project ... python -c "import amplifier_core; print(amplifier_core.__file__)"
~/dev/.venv/lib/python3.12/site-packages/amplifier_core/__init__.py
```

This is pre-existing and not a regression. For a fair comparison I ran both trees with an
identical isolated environment:
`uv run --no-project --isolated --python 3.12 --with pytest --with pytest-asyncio
--with pyyaml --with amplifier-core` (amplifier-core 2.0.1).

| Suite | origin/main | branch |
|---|---|---|
| hooks-trajectory-observer | 16 passed | 21 passed |
| hooks-cue-injector | 10 passed | 11 passed |
| tool-preceptor | 58 passed | 61 passed |
| cross-module (`tests/`) | 28 passed | 28 passed |
| **total** | **112 passed, 0 failed** | **121 passed, 0 failed** |

- **Tests removed:** none. Test IDs were compared with `comm`: 0 only-on-main, 9 only-on-branch.
- **Regressions (pass on main, fail on branch):** none.
- **Stronger check.** I ran main's test files against the branch code (scratch worktree,
  `git checkout origin/main -- modules/*/tests tests`). The result was `1 failed, 15 passed`
  (observer), with injector and tool-preceptor all passing. The single failure is
  `test_buffer_flushes_on_flush_every_threshold`. It asserts that records are on disk
  synchronously when the `flush_every` threshold is hit. The branch made that flush
  fire-and-forget on purpose. The branch version of the test adds `_wait_for_writer()`
  and still pins that the threshold triggers the write. A new test,
  `test_threshold_flush_does_not_block_the_handler`, proves the handler no longer waits.
  This is an intended, documented semantic change, not a regression. See also Problem 6.
- `make check` (ruff lint and format) passes on both trees. `bench/footprint.py`, which
  `make check` doesn't cover, is also ruff-clean.

## 2. Claimed savings: re-measured

### Verified

**Per-request tokens (chars/4).** I ran `bench/footprint.py` against both trees
(`--repo <main worktree>`). I also measured the tool schema independently by
instantiating `PreceptorTool` and serializing name + description + input_schema.

| | main | branch | claimed | holds? |
|---|---|---|---|---|
| context files | 542 | 472 | 542 → 472 | yes |
| agent descriptions | 1044 | 345 | ~1044 → ~345 | yes |
| tool schema, read-only instance | 566 (2267 ch) | 258 (1035 ch) | ~567 → ~259 | yes |
| tool schema, consent instance | 521 (2086 ch) | 171 (687 ch) | (not claimed) | bonus |
| tool schema, writable instance | 577 | 555 | "unchanged fields" | yes, all 18 props kept |
| **total** | **2153** | **1076** | 2153 → 1076 | yes |

Caveat: chars/4 is an estimate, not a real tokenizer count. The relative saving (~50%)
is robust. Absolute counts will differ on the actual provider tokenizer.

**Per-event observer latency.** Observer enabled, `footprint.py`, mean µs:

| event | main | branch | claimed |
|---|---|---|---|
| tool:pre small | 15.8 (p99 313) | 4.2 (p99 6) | ~11 → ~3–5 |
| tool:pre 1 MB | 1762 | 5.8 | ~1700 → ~4–6 |
| tool:post 1 MB | 1852 | 3.9 | ~1700 → ~4–6 |
| tool:pre 10 MB | 17097 | 4.7 | ~16000 → ~3 |
| provider:request | 11.6 | 1.6 | ~9 → ~2 |
| total CPU, 1 MB pre+post (drained) | 3434 | 1824 | ~3300 → ~1700 |

All hold within noise.

**"Off the critical path" holds under the GIL.** I tested independently whether handing
json.dumps + sha256 to a thread merely moves the stall. The test times a fixed chunk of
pure-Python "next step" work right after the handler returns:

```
1MB   next_step alone 2650us | inline hash+step  4566us | bg submit+step 2669us
10MB  next_step alone 2616us | inline hash+step 19785us | bg submit+step 2661us
```

The background path does not stall the following work.

**Injector.**

| | main | branch | claimed |
|---|---|---|---|
| first provider:request, 8 active of 60 cues | 3896 µs | 720 µs | ~3.7 ms → ~0.66 ms |
| each later provider:request | 0.8 µs | 0.2 µs | 0.7 → 0.2 µs |

libyaml is present in the real CLI install
(`~/.local/share/uv/tools/amplifier`: `libyaml: True CSafeLoader: True`), so the
CSafeLoader speedup is realized in production.

**Schema narrowing doesn't hide fields any operation needs.** `_dispatch` reads exactly
`_REQUIRED_FIELDS ∪ _OPTIONAL_FIELDS` for every operation (checked by grepping every
`data[...]` / `data.get(...)` in `_dispatch`). `execute()` reads no other input keys.
I first suspected the new coverage test was circular, so I probed the drift risk in a
scratch copy: I added a new property to `_INPUT_SCHEMA` without listing it in the field
tables. The suite does catch that:
`test_readonly_and_consent_schemas_drop_write_only_fields` asserts writable props ==
full `_INPUT_SCHEMA` → `1 failed`. That suspicion is retracted.

**Structural claim in 5aadfc0 is correct.** `context/cue-awareness.md` is loaded only by
`behaviors/preceptor.yaml`, which also includes all four agents. Dropping the "Deeper:"
agent list therefore duplicates nothing the delegate listing doesn't already carry.

**The agent-description trim is ecosystem-conformant.** Foundation's
`docs/AGENT_AUTHORING.md` now rejects `<example>` blocks outright ("banned entirely, not
just capped"), and "Authoritative on" is optional. Only `meta.description` blocks changed.
Agent bodies, `model_role` and tools are unchanged.

**The `cue_ids_dosed` bug fix is real.** I reproduced it with a scratch probe:
`execution:start`, then the manifest lands, then `provider:request`, `tool:pre`, and
`execution:end`:

```
MAIN   : execution:start [] | provider:request [] | tool:pre [] | execution:end []
BRANCH : execution:start [] | provider:request ['cue-001'] | tool:pre ['cue-001'] | execution:end ['cue-001']
```

### Off or unrealizable

**The lazy imports save nothing in a real host.** 9475285 advertises a "lazy yaml
import". 58d5bb2 says "concurrent.futures imported lazily: disabled sessions pay
nothing". `footprint.py` reports injector import time 7.5 → 1.8 ms. That is a
fresh-interpreter artifact:

```
$ python3 -c "import sys, asyncio; print('concurrent.futures' in sys.modules)"
True
$ <amplifier CLI python> -c "import sys, amplifier_foundation, amplifier_app_cli; print('yaml' in sys.modules)"
True
```

Every Amplifier session already has both modules loaded before this bundle mounts. The
code is harmless; only the claims are off. See Problem 4.

**"Digests are byte-identical"** holds only when `tool_input` is not mutated in place.
See Problem 3.

### Unverifiable here

Real-session end-to-end effect: a DTU run with an actual provider and tokenizer. The
branch does not claim one.

---

## 3–4. Problems, most severe first

### P1. MUST-FIX: `context/cue-awareness.md` edited without the evidence this repo requires, and the commit message misstates it

- `AGENTS.md` lists this as non-negotiable: *"Removal carries the burden of proof…
  Applies to cues, to context files… show that removing it changes nothing."*
- `bench/README.md` ("The definitive ablation") records that this file's previous
  reduction was applied only after a 3-arm `bench/probe_context.py` run returned ACCEPT:
  *"Authorized by the verdict above, not by taste — which is what `cue-awareness.md`
  demands."*
- 5aadfc0 trims the same file again (1399 → 1121 chars, ~70 tokens) with no ablation. It
  also says *"every instruction and command kept"*, but it deletes the sentence
  **"A cue never overrides what the user actually asked for."** (see
  `git show 5aadfc0 -- context/cue-awareness.md`).
- The related `cue-conflict` probe was classified over-determined in the last run, so the
  change is probably safe. "Probably" is exactly what this repo refuses to ship on,
  inside the file that states the rule.
- **Fix (pick one):**
  - **(a)** Revert only the `context/cue-awareness.md` hunk. This forfeits ~70 of the
    ~1077 tokens saved (~6.5%) and keeps everything else. This is the recommendation.
  - **(b)** Run `bench/probe_context.py` (3-arm, no-context / full / reduced) on the new
    text, record the ACCEPT in `bench/README.md` like the previous one, and correct the
    commit message.

  The agent-description trims don't need this treatment: foundation policy now bans the
  removed `<example>` blocks.

### P2. MUST-FIX: behavior change hidden inside a `perf:` commit (58d5bb2)

- The stated goal is to cut cost *without changing what the bundle does*. 58d5bb2 also
  fixes `cue_ids_dosed`, which was always `[]` on main for newly dosed sessions (proved
  above). That changes recorded observation data on disk. It also changes user-visible
  output: `tool-preceptor`'s `observations` summary aggregates `cue_ids_dosed`
  (`ledger.py:834-843`), and downstream form-analyst attribution depends on it
  (`context/methodology/ledger-format.md:50`: "the correlation key").
- It's a good fix, and the commit body does mention it ("Fix: …"). But a reviewer
  skimming `perf(...)` subjects will miss it, and it can't be reverted independently of
  the perf work.
- **Fix:** split it into its own commit
  (`fix(observer): re-read dosing manifest on first provider:request`). Include the
  `cue_ids()` / `_cue_ids_final` change and its two tests
  (`test_cue_ids_seen_when_manifest_lands_on_first_provider_request`,
  `test_resumed_session_manifest_read_on_first_event`). Call it out in the PR
  description as the one intentional behavior change.

### P3. OPTIONAL: deferred hashing changes the digest when `tool_input` is mutated in place; the commit message overstates identity

I reproduced this deterministically with a scratch probe: a busy writer, then `tool:pre`
with a 100 KB dict, then an in-place mutation, then `tool:post` with the same object.

```
MAIN   : tool:pre digest = ORIGINAL   tool:post digest = MUTATED
BRANCH : tool:pre digest = MUTATED    tool:post digest = MUTATED
```

- The `tool:pre` record can hash content the input didn't have at `tool:pre` time.
  `tool:post` reuses that digest by object identity. A concurrent mutation during
  json.dumps on the worker would instead raise, and the digest would be recorded as
  `None` (fail-open).
- Realistic risk is low: grepping the module cache found no tool that mutates its input
  dict in place. The observer README does disclose the trade-off. However, it says
  *"milliseconds after the event"*, and the window is really unbounded while the single
  writer is busy (e.g. a slow disk during a prior flush).
- **Fix:** change 58d5bb2's *"Digests are byte-identical"* to "…identical unless
  tool_input is mutated in place before the background hash runs". In the README, replace
  "milliseconds" with "after any queued writer work".

### P4. OPTIONAL: lazy-import claims are unrealizable in real hosts

`yaml` and `concurrent.futures` are already in `sys.modules` in every Amplifier session
(evidence in §2). The `IMPORT ms` row in `footprint.py` measures a cold interpreter.

- **Fix:** drop "lazy yaml import" from 9475285's subject. Drop the "disabled sessions
  pay nothing" bullet from 58d5bb2. Label `footprint.py`'s import timing as
  cold-interpreter only.
- Optionally remove the lazy-import indirection itself: one fewer moving part, zero
  measured cost.

### P5. OPTIONAL: observer README misdescribes the inline/background threshold

The README says large means *"over ~4 KB of top-level string content"*. `_estimated_chars`
actually counts **any** nested dict/list/tuple value as 4096, so every small nested input
takes the thread hop:

```
small nested todo input -> 4096 (>=4096 => background thread)
flat 1KB string input   -> 1002
```

This is correctness-neutral, since the digest is identical. It costs a thread hop plus a
Future on many common small tool inputs (todo lists, edit arrays).

- **Fix:** document it accurately, or estimate nested containers by `len()` of their
  immediate string members instead of assuming large.

### P6. OPTIONAL: durability window for mid-turn records (accept, but state it in the PR)

With the `flush_every` flush now fire-and-forget, records past the threshold are
in flight rather than on disk when the handler returns. A SIGKILL in that window loses
them. On main, they were durable. Eager points (`execution:end`, `cancel:requested`) and
cleanup still block, with a 10 s cap (`_DRAIN_TIMEOUT_S`). On normal exit, the executor's
non-daemon worker drains its queue. This is a deliberate trade and is documented in the
module README. Mention it in the PR body.

### P7. OPTIONAL: commit trailer convention

The branch commits carry `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
main's Amplifier-authored commits (e8a0f0a, 5482d1a, …) use
`Co-Authored-By: Amplifier <240397093+microsoft-amplifier@users.noreply.github.com>`.
Align the trailers when re-committing for P1/P2.

### P8. OPTIONAL, pre-existing and not caused by this branch: test-harness fragility and a stale count

- `make test` module suites run without `--with amplifier-core`. They pass only when uv
  happens to discover a venv containing it: here `~/dev/.venv`, because the worktree sits
  under `~/dev`. A clean checkout elsewhere errors on collection (§1). Consider adding
  `--with amplifier-core` to the module loop in `Makefile`, as the cross-module line
  already has.
- The root `README.md` header says "71 tests". Actual counts are 112 (main) and 121
  (branch).

---

## Non-issues checked

- **Config keys and defaults:** no `config.get(...)` line added or removed in the diff.
- **Composition:** `bundle.md`, `behaviors/`, `bundles/` untouched.
- **Public API:** no module-level `def`/`class`/constant removed from any module `__init__.py`.
- **Shared `_CONTINUE` HookResult singleton.** `HookResult` is a mutable pydantic model
  (assignment allowed). Hook dispatch is the Rust `RustHookRegistry` (`hooks.py` is a
  5-line re-export), no Python code in amplifier_core assigns to result fields, and the
  observer already shared a `_CONTINUE` on main. Low risk.
- **Single shared writer thread across sessions.** FIFO ordering guarantees each hash job
  completes before the flush job that serializes its record. `drain()` waits on the last
  submitted future, which covers all earlier ones. Inline fallbacks exist for executor
  shutdown (`RuntimeError` in `digest()`, `Exception` in `flush()`). `_pending_digests`
  is bounded at 256.
- **CSafeLoader safety.** The new test confirms `!!python/object/apply` is rejected, and
  output equals `yaml.safe_load`.
- **Debug leftovers:** the only `print(` additions are in `bench/footprint.py`'s CLI
  output, which is legitimate.
