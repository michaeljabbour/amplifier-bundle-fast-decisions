# Amplifier install cleanup: measured proposal (2026-09-24)

This is a proposal. Nothing has been changed yet. Apply it only after approval, and only once no
benchmark is running, since the runners refuse to launch if `~/.amplifier/settings.yaml` changes.

## What your current setup costs (trivial prompt "Reply with just: ok", single mode)

| Config | Wall time | Session start → prompt | Prompt size (cache write) | Cost |
|---|---|---|---|---|
| Real (24 app bundles) | **59.3 s** | 26.5 s | **114k tokens** | $0.43 |
| Same, app bundles off (workspace override) | **12.9 s** | 6.1 s | ~20k tokens | ~$0.15 |

The model call itself took about 2 s in both.

## Where the time goes (cProfile of a real-config run)

| Cost | Where | Fix |
|---|---|---|
| 7.7 s per session start | foundation `hooks-deprecation`: `rglob` over all of `~/.amplifier` (169 GB and ~35k dirs under `projects/`), then filtering | **Upstream patch ready**: `docs/upstream-patches/amplifier-foundation-hooks-deprecation-prune.patch` (5.8 s → 0.07 s, 75 tests pass). Also stops false "evidence" matches in team-knowledge data. |
| 5.1 s per prompt | `team-knowledge-base`: `hooks-team-knowledge-context` runs `git pull --rebase` and rebuilds the index on every prompt | Remove the app bundle, or ask the owner to sync in the background or on a TTL |
| 4.6 s per session | `memory`: `hooks-memory-briefing` makes three daemon round-trips (search, diary read, KG query) | Keep if you use memory; see the duplication below |
| duplicate | `behavioral-plasticity-app.yaml` mounts the same five memory hooks as `memory.yaml`, plus context-intelligence and survey capture | Keep only one of the two |
| 4.4 s | YAML parsing of about 3,600 documents while composing 24 app bundles and their agents | Fewer bundles |
| 4.8 s | module load and validation (151 loads) | Fewer bundles; an upstream validation cache would help |
| ~94k tokens per request | roughly 120 agent descriptions and ~90 tool schemas | Fewer bundles with many agents |

## Per-app-bundle footprint (hooks / tools / agents added)

| App bundle | Hooks | Tools | Agents | Notes |
|---|---|---|---|---|
| foundation-capabilities.yaml (startup-fixes) | 14 | 15 | 42 | the foundation stack itself |
| active-routing.yaml (fast-decisions) | 15 | 16 | 42 | also brings foundation; supersede with the v0.2 bundle |
| made-support | 3 | 4 | **14** | large agent roster |
| design-loop | 0 | 7 | **13** | large agent roster |
| behavioral-plasticity-app.yaml | **10** | 7 | 7 | **duplicates the memory stack** |
| product-management (tech-bro-idealist) | 0 | 4 | 9 | |
| memory | 5 | 1 | 2 | 4.6 s briefing |
| converge | 2 | 4 | 5 | |
| attractor-app.yaml | 3 | 2 | 5 | |
| preceptor, mj, ux-ergonomist | 2 / 3 / 0 | 1 / 3 / 1 | 4 each | |
| impeccable, the-usual, unknowns, runpod, team-pulse, conformance | 1–2 | 1–3 | 0–3 | small |
| **team-knowledge** | 1 | 1 | 0 | **5.1 s on every prompt** |
| digital-twin-universe, evaluation, llm-wiki, amplifier-online, teamwork | 0–1 | 0–2 | 0–1 | small; keep what you use |

## Proposed changes, in order of payoff

1. **Remove `team-knowledge`**, or keep it only in a dedicated profile. Saves about 5 s on every prompt.
2. **Remove `behavioral-plasticity-app.yaml`** (or `memory`), whichever you use less. Ends the duplicated memory hooks.
3. **Replace `active-routing.yaml`** with the v0.2 orchestrator-primary bundle once confirmed. One fast-decisions entry, not two foundation stacks.
4. **Move rarely used agent-heavy bundles** (design-loop, made-support, product-management, attractor, converge) to named bundles you activate when needed (`amplifier bundle use …` / `--bundle`), rather than composing them into every session.
5. **Apply the upstream `hooks-deprecation` fix** once merged (or as a local override meanwhile). Saves about 5.8 s per session start for every user.

Expected result, to re-measure after applying: a trivial prompt should drop from about 59 s toward the ~13 s app-free figure, and the prompt from 114k toward about 20–40k tokens, depending on what stays.

## Also found

Benchmark runs register bundles into your global `~/.amplifier/registry.json`, and `file://` module
activation installs `amplifier_fast_decisions` editable into the shared Amplifier tool env (last one
wins). Your everyday sessions currently import it from an experiment worktree
(`smoke1/source`). After the running benchmarks finish, re-point it:
`uv pip install --python ~/.local/share/uv/tools/amplifier/bin/python -e ~/dev/amplifier-bundle-fast-decisions`.
