# PR draft: microsoft/amplifier-foundation. `hooks-deprecation` scans only authored config

**Status: drafted, not opened.** The patch is `amplifier-foundation-hooks-deprecation-authored-only.patch`,
against `origin/main` `ce876d5` (2026-09-24). Local branch: `/tmp/ampup/amplifier-foundation` @
`fix/deprecation-scan-allowlist`.

## Title

fix(hooks-deprecation): scan only authored `.amplifier` config for evidence (5.8 s → 2 ms per session start)

## Problem

`find_source_files()` looks for "evidence" that a user's configuration references a deprecated bundle.
It runs `rglob("*.yaml")` over each search directory's `.amplifier/` (the working dir, cwd and home)
and skips `cache/` paths only *after* enumerating them. It is called on every `session:start`, once
per tombstone. Foundation ships one tombstone today, in `behaviors/redaction.yaml`, for
`hooks-redaction` with `require_evidence: true`. Every delegated sub-session pays the same cost again.

On a well-used machine `~/.amplifier` is dominated by tool-managed state:

| Directory | YAML files |
|---|---|
| `projects/` (session transcripts) | 323, inside ~35k directories and 169 GB |
| `team-knowledge/` (a bundle's data store) | 2,000+ |
| `cache/` (resolved modules) | 1,074 |
| `resolve/`, `evaluation/`, `recipe-runner/` (bundle state) | 430 / 279 / 181 |

Measured on that machine:
- **Time.** `find_source_files` takes **5.81 s**, synchronously, inside an async hook handler, so it
  blocks the event loop. A cProfile of a real session attributes 5.5–7.7 s of session start to it.
  That is the largest single item before the first prompt.
- **Correctness.** It returned **15 false "evidence" files**, all inside a team knowledge base whose
  YAML *describes* the `hooks-redaction` capability. Because `require_evidence` was satisfied, the
  deprecation warning fired and its system-context injection landed in **every session** for a user
  who never configured `hooks-redaction`.

## Change

Scan only where users author configuration that can reference a bundle:
- top-level `*.yaml` in `.amplifier/`: `settings.yaml`, `settings.local.yaml`, and the like
- `*.yaml` under `.amplifier/bundles/`, depth-capped at 4, skipping hidden and `cache` directories

Files seen twice, e.g. when cwd is home, are reported once. Nothing else changes: firing logic,
severity, the `self.composed` signal from #277, and the message format are all untouched.

## Why an allow-list and not a longer deny-list

A deny-list (`cache`, `projects`, `team-knowledge`, …) would have to name other bundles' private
directories, and it can never be complete: a new bundle's data store reintroduces both the slowdown
and the false positives. The two authored locations above are exactly what the existing tests already
treat as evidence (`test_scans_nested_yaml_files` uses `.amplifier/bundles/`), and they are what a
user edits by hand.

## Behavior change and risk

- **Not scanned any more:** YAML in *other* `.amplifier/` subdirectories (e.g. a hand-made
  `.amplifier/profiles/x.yaml`) and `bundles/` files deeper than 4 levels. Such a reference would no
  longer count as evidence.
- **Why the risk is low:**
  - Since #277 the primary firing signal is the *composed* session (`self.composed`): if the
    deprecated bundle is actually in the session, the warning fires regardless of files. The file
    scan is documented as a best-effort fallback.
  - Previously-scanned locations produced false positives on real machines, which is worse than a
    rare miss.
- **No new dependencies, no config surface, no public API change.**

## Tests

- All 72 existing tests pass **unchanged**.
- 4 new tests pin the contract:
  - tool-managed state is ignored: cache, sessions, bundle data stores, subdir top level, hidden dirs
  - nested authored bundles are found within the depth cap
  - `cache` and hidden dirs under `bundles/` are skipped
  - cwd == home de-duplicates

```
PYTHONPATH=modules/hooks-deprecation python -m pytest -q modules/hooks-deprecation/tests
76 passed
```

## Measurements (macOS, Apple Silicon, same machine)

| | Before | After |
|---|---|---|
| `find_source_files("hooks-redaction", [cwd, home])` | 5.81 s | 0.002 s |
| False-positive evidence files | 15 | 0 |
| Deprecation injection in sessions that never configured `hooks-redaction` | yes | no |

## Reviewer notes and open questions

1. Should any other `.amplifier/` subdirectory count as authored config? If maintainers know one,
   it is a one-line addition to the allow-list.
2. The scan still runs synchronously in the async handler. At 2 ms that no longer matters, so moving
   it to a thread was deliberately left out of this PR.
3. The `hooks-redaction` tombstone's `sunset_date` is 2026-10-01. This fix matters until the
   tombstone is removed, and for every future tombstone.

## How it was found

The fast-decisions benchmarking work (`amplifier-bundle-fast-decisions`, `evals/STUDY-DESIGN.md`
§18) profiled Amplifier startup. A trivial prompt took 59 s on a real configuration, and 13 s of
that was hooks and composition before the prompt was sent.
