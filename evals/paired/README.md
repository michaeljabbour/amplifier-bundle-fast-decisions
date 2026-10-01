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

## main-v1 scenarios, references, split

* 70 validated scenarios under `evals/paired/scenarios/main-v1/{polyglot,repos,mixed,knowledge}`; design `evals/paired/main-v1.yaml`
  (`paired.py plan --dry-run --design evals/paired/main-v1.yaml`). Task types include `docs` and `explain`.
* Split: `split: train|test` is written into every file by `assign_split.py` (seed 20261002, stratified by family and gap
  pattern, same upstream repo => same split); see `SPLIT.md` / `split.json`; `assign_split.py --check` verifies the files.
* **Reference solutions** (outside the repo, never given to agents) live ONLY under `~/dev/afast-paired-refs/<family>/<id>/`
  (`polyglot`, `repos`, `mixed`, `knowledge`). All four validators default to that root (`--ref-root` overrides).
  `~/dev/afast-paired-src/reference/` is no longer read.
* Validators (`validate_polyglot.py`, `repos/validate_repos.py`, `validate_mixed.py`, `validate_knowledge.py`) run scenario
  code only through memguard; run them serially: `--jobs 1 --cap-gb 4`, and only with `memory_pressure` >= 50% free.
  `validate_knowledge.py` also checks that the untouched starting workspace fails every turn's checks.
* `aa` runs in a seeded 20% subsample of scenario-reps (stratified by split and gap pattern, both hosts). The 40-turn
  long-session block is a TODO in the design (needs authored follow-up turns) and is never scheduled.

## Memory safety (read before running anything)

On 2026-10-01 an unguarded Go test binary (`dominoes.test`) grew to 120-470 GB and drove a 128 GB Mac out of memory four
times (it also killed the Forge daemon mid-pilot). Nothing that executes scenario code may run unguarded now.

* `scripts/memguard.py`: library + CLI (`python3 scripts/memguard.py run --cap-gb N --timeout S [--cwd D] -- cmd ...`).
  Own process group; whole-tree RSS (group + descendants, setsid escapees included) polled every 0.25 s; SIGTERM, then
  SIGKILL after 2 s, on cap / timeout / system-available-memory floor (default min(24 GB, 20% RAM)). Prints one JSON line
  `{killed: memory|timeout|system_floor|null, peak_rss_gb, wall_s, returncode}`; exit 137 (memory/floor), 124 (timeout).
  Also sets GOMEMLIMIT, GOFLAGS=-p=2, CARGO_BUILD_JOBS=2, NODE_OPTIONS=--max-old-space-size (and Linux RLIMIT_AS, loose).
* Graders and hidden tests (`paired_scenarios._check_tests`, every `polyglot_tasks` runner, hence all four `validate_*.py`
  validators) run under it: 4 GB, 300 s (env `PAIRED_GRADER_CAP_GB`, `PAIRED_GRADER_TIMEOUT_S`; validators take
  `--cap-gb` / `--grader-timeout`). A memory kill is a failed check labelled `resource_limit`, never an infra failure.
  At most 3 guarded runs execute at once per process (`MEMGUARD_MAX_CONCURRENT`).
* `paired.py run`: refuses to start when system available memory < max(32 GB, 25% RAM) and prints the top consumers;
  a watchdog thread (1 s) finds every process whose cwd is inside the campaign root, groups them per session workspace,
  and (a) kills a session's agent tree above 8 GB (`--session-cap-gb`) - never the Forge worker, so the turn fails and the
  session is kept with `killed_memory.json` -> rows get `killed_memory=true`, `cost_valid=false`; (b) pauses launching
  waves below the pause floor (`--pause-floor-gb`); (c) below 16 GB (`--hard-floor-gb`) kills the newest session trees,
  one per second, until above the floor. `--max-system-use-gb N` caps the campaign's total RSS the same way.
  Default `--parallel` is 4 (the plain-sonnet control gets its own wave when a wave would not fit); a wave larger than
  `--parallel` is refused, not deadlocked.
* Agent sessions run with GOMEMLIMIT=4GiB, GOFLAGS=-p=2, CARGO_BUILD_JOBS=2, NODE_OPTIONS=--max-old-space-size=4096, the
  same for every arm (no bias). Limits cannot see processes that leave the campaign root AND the parent chain.

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
