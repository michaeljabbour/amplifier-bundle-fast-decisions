# PR draft: microsoft/amplifier-foundation. `hooks-deprecation` scans only authored config

**Status: opened 2026-09-24 as an optional suggestion: https://github.com/microsoft/amplifier-foundation/pull/413 (independently reviewed; all changes applied).**
The patch is `amplifier-foundation-hooks-deprecation-authored-only.patch`, against `origin/main` `ce876d5`
(2026-09-24). Local branch: `/tmp/ampup/amplifier-foundation` @ `fix/deprecation-scan-allowlist` (`028e99e`).

## Title

fix(hooks-deprecation): scan only authored .amplifier config for evidence

## Problem

`find_source_files()` looks for "evidence" that a user's configuration references a deprecated bundle.
It runs `rglob("*.yaml")` over each search directory's `.amplifier/` (the working dir, cwd and home)
and skips `cache/` paths only *after* enumerating them. It is called on every `session:start`, once
per tombstone, synchronously inside an async handler, so it blocks the event loop. Every delegated
sub-session pays the cost again. Foundation ships one `require_evidence` tombstone today, in
`behaviors/redaction.yaml`, for `hooks-redaction`.

The durable issue is the contract for this and every future tombstone: a scan whose cost and
false-positive rate grow with tool-managed state under `~/.amplifier`.

On a heavily used machine (point-in-time snapshot, one machine), `~/.amplifier` is dominated by
tool-managed state:

| Directory | YAML files |
|---|---|
| `projects/` (session storage) | 323, inside ~21k directories (about 36k across all of `.amplifier`) |
| `team-knowledge/` (a bundle's data store) | ~5,000 |
| `cache/` (resolved modules) | 1,074 |
| `resolve/`, `evaluation/`, `recipe-runner/` (bundle state) | 430 / 279 / 181 |

Measured on that machine (macOS arm64, Python 3.12):
- **Time.** `find_source_files` takes about **6–7 s** (5.9–7.4 s across runs).
- **Correctness.** It returned **15 false "evidence" files**, all inside a team knowledge base whose
  YAML *describes* the `hooks-redaction` capability. Because `require_evidence` was satisfied (and
  `composed` is false: the replacement module is `hook-redaction`), the hook returned
  `inject_context` and emitted `deprecation:warning`, listing 15 unrelated files, in every session
  and sub-session (468/468 sessions over two days on that machine). *(On amplifier-core 2.0.1 the
  `session:start` injection did not appear in the model request; that is a separate delivery issue.)*

## Change

Scan the locations where users author configuration, plus whatever else sits at the top level:
- top-level `*.yaml` in `.amplifier/`: `settings.yaml`, `settings.local.yaml`, and any other
  top-level YAML (some of it tool-written, e.g. `distro.yaml`; these are few and small)
- `*.yaml` under `.amplifier/bundles/`, depth-capped at 4, skipping `.git` and `cache` directories

Results are de-duplicated by real path (`os.path.realpath`, which does not raise on symlink loops
before Python 3.13) and returned in scan order. Firing logic, severity, the `self.composed` signal
from #277, and the message format are unchanged; the *contents* of the "Found in:" list and the
event's `source_files` payload change as described below.

## Why an allow-list and not a longer deny-list

A deny-list (`cache`, `projects`, `team-knowledge`, …) would have to name other bundles' private
directories, and it can never be complete: a new bundle's data store reintroduces both the slowdown
and the false positives. Skipping the scan when `composed` decides would not help here, because for
this tombstone `composed` is false, so the scan is the deciding signal.

The old `test_scans_nested_yaml_files` docstring promised "nested .amplifier/ subdirectories" in
general. This PR narrows that contract to `.amplifier/bundles/` and updates the docstring.

## Behavior change and risk

| Case | Before | After |
|---|---|---|
| `.amplifier/profiles/*.yaml`, `.amplifier/recipes/*.yaml`, other subdirectories | found | not found |
| `bundles/` files more than 4 directories deep | found | not found |
| `bundles/.git/**`, `bundles/cache/**` | found | not found |
| other hidden directories under `bundles/` | found | found |
| `.amplifier/bundles` itself a symlink | not found | found (widens the scan) |
| symlinked bundle directories inside `bundles/` (e.g. a dev checkout) | not followed | not followed (known gap) |
| the same file reached twice (working_dir == cwd, cwd == home) | reported twice | reported once |
| `.yml`, `bundle.md` | not scanned | not scanned (unchanged) |
| unreadable dirs, dangling symlinks, non-UTF-8 files | skipped | skipped |
| file symlink loop ending in `.yaml` under `bundles/` | skipped | skipped (regression test added) |

- **Known residual (pre-existing):** a copy of a bundle that *carries* a tombstone, placed under
  `.amplifier/bundles/`, still matches itself (the #344 class of bug is narrowed, not closed). A
  structural fix (ignoring files that are themselves `hooks-deprecation` carriers) belongs in a follow-up.
- **Why the risk is low:** since #277 a deprecated bundle that is actually composed fires regardless
  of files; the scan is a best-effort fallback, and the previously scanned locations produced false
  positives on real machines.
- **No new dependencies, no config surface, no public API change.**

## Tests

- All 72 existing tests pass unchanged (`origin/main`'s test file run against the new module).
- 6 new tests pin the contract:
  - tool-managed state is ignored
  - nested authored bundles are found within the depth cap
  - `.git` and `cache` under `bundles/` are skipped
  - other hidden directories under `bundles/` are still scanned
  - a file symlink loop under `bundles/` is skipped (skipped where symlinks are unavailable)
  - cwd == home de-duplicates
- The 4 original new tests fail against `origin/main`'s module, as intended.
- **These module tests are not part of CI** (`ci.yml` runs `uv run pytest tests/`). Run locally:

```
PYTHONPATH=modules/hooks-deprecation python -m pytest -q modules/hooks-deprecation/tests
78 passed        # Python 3.11, 3.12 and 3.13
```

Supporting evidence: on `origin/main`, four existing tests scan the real home directory; on the same
machine the module suite takes 41.9 s on `main` and 0.1 s with this change.

`ruff check` and `ruff format --check` (default settings) report no new findings relative to `main`.

## Measurements (one machine: macOS arm64, Python 3.12)

| | Before | After |
|---|---|---|
| `find_source_files("hooks-redaction", [wd, cwd, home])` | 5.9–7.4 s | 0.002–0.003 s |
| False-positive evidence files | 15 | 0 |
| `deprecation:warning` emitted with false evidence | every session | none (the hook returns `continue`) |

## Reviewer notes and open questions

1. Should the filesystem fallback exist at all now that `composed` (#277) exists, or be limited to
   top-level `settings*.yaml`? That is a policy change and deliberately not part of this PR.
2. Should any other `.amplifier/` subdirectory count as authored config? It is a one-line addition.
3. The scan still runs synchronously in the async handler. At ~2 ms that no longer matters, so moving
   it to a thread was left out.
4. The `hooks-redaction` tombstone's `sunset_date` is 2026-10-01. After that this fix matters for
   every future `require_evidence` tombstone.
5. Separate issue worth filing: on amplifier-core 2.0.1 (RustSession), `session:start`
   `inject_context` results did not reach the model request on the reporting machine.
