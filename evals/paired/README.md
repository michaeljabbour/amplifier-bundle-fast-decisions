# Paired multi-turn measurement harness (pilot build)

Spec: `docs/design/parallel-measurement-mode.md` (v2). Driver: `evals/paired.py`. Scenarios: `scenarios/pilot-v1/*.yaml`.
Design (arms, hosts, cost model): `pilot-v1.yaml`.

## Reproduce the scenario snapshots

Every scenario pins its workspace to a full git sha (`workspace.repo` + `workspace.sha`); `local_hint` is only a speed-up.
`paired.py plan` (non `--dry-run`) runs `paired_scenarios.materialize`, which fetches that sha (`git fetch --depth 1`),
extracts the subdir with `git archive`, applies `remove` / `add_files`, vendors `pip_vendor` pins (`text-unidecode==1.3`),
and pulls hidden tests (`from_git`). Snapshots live outside the repo in `~/dev/afast-paired/snapshots/<id>-<hash10>/`
and are verified by tree hash on every use (frozen; never edited). The python-slugify scenarios use
https://github.com/un33k/python-slugify.git at `c442cd4cb61763c85b078d6ea83b5959c3ff364a` (parent of upstream fix
`8f9a550a906701412c8fc93e731582098f2caee2`); rebuilding from the network alone gives an identical tree hash.

## Provider isolation (why sessions do not use your global provider list)

The Amplifier CLI validates every provider in `~/.amplifier/settings.yaml` at session start (`GOOGLE_API_KEY` for
`provider-gemini` killed the first pilot wave), and settings scopes merge provider lists by identity, so a project/local
scope can add or tweak providers but never remove one. A separate `AMPLIFIER_HOME` would isolate settings but also the
cache/registry/sessions and trips the shared-venv guard (editable `.pth` files get repointed), so it is not used.

Mechanism (reuses the profile every campaign already generates): the generated `profile.md` declares its own
`providers:` list with ONE entry, `campaign-anthropic` (design `campaign_provider`: module `provider-anthropic`, source
`...@main`, `api_key: ${ANTHROPIC_API_KEY}`, `base_url: https://api.anthropic.com`, `enable_1m_context`, `raw: true`).
When a bundle declares providers, settings providers are only applied as overrides to entries with a matching id/module,
and nothing else is mounted or credential-checked. The entry has its own id so no global entry can merge config into it
(an id-less global `provider-anthropic` entry would otherwise inject its `reasoning_effort: max`). The key reaches the
provider only through the session env (`ANTHROPIC_API_KEY`; per-arm `--key-env` overrides it for that session).
`preflight` records the resolved provider module (version, git sha, path) in `preflight.json`; every `sessions.jsonl`
row carries it as `provider_module`. `~/.amplifier/settings.yaml` is never modified.

## Preflight and failure handling

`paired.py preflight` runs one "Reply with OK." session per distinct (cell, model, key) in the isolated environment and
requires an `llm:response` from the expected model plus raw payload events. `run` does this first (unless a passing
preflight for the same targets is < 12 h old, or `--skip-preflight`) and aborts with exit 4 before any wave on failure.
A session that fails before any model call without a transient marker (overload, 429/5xx, timeout, connection reset,
Forge launch trouble) is a configuration error: no retry, the run stops with exit 4 and the error tail, and the wave is
marked `config_error` (re-runnable, not counted against the 3-attempt limit). `run --reset-wave <id>|excluded` makes an
excluded wave runnable again; attempt numbering and the ledger (including preflight spend) are kept.

## Pilot commands

    python3 evals/paired.py plan --dry-run --reps 2 --budget-usd 400        # plan + estimate, writes nothing
    python3 evals/paired.py plan --out ~/dev/afast-paired/pilot-1 --reps 1 --budget-usd 150   # freeze schedule, snapshots, candidate worktree
    python3 evals/paired.py run  --out ~/dev/afast-paired/pilot-1 --parallel 6 --budget-usd 150 [--resume]
    python3 evals/paired.py rows --out ~/dev/afast-paired/pilot-1          # rows/{sessions,turns,pairs}.jsonl + summary.json
    python3 evals/paired.py grade --out ... --passes 2                     # P7: re-grade preserved turn snapshots, no model
    python3 evals/paired.py render-check --out ...                         # offline: nonce leads the system prompt, prompts match

P2 contrast (no nonce, same key vs second key): `plan --nonce-mode none --arms anchor,aa --scenarios py-bowling
--key-env aa=ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY --offset aa=60`.

## Nonce

`run-nonce: <uuid>` is the first line of each session's bundle instruction (the body of the generated `profile.md`,
written by `forge_e2e._build_run`), followed by the instruction the profile would otherwise have. A root-bundle body
REPLACES an included instruction, so the original is read offline from the composed bundle and kept.
