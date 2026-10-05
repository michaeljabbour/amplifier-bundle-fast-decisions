# holdout-v3 scenarios (S1 of the v3 program)

60 scenarios that no agent had run before S1: `polyglot/` 12, `repos/` 20, `mixed/` 16, `knowledge/` 12 (10 per task type:
bugfix, feature, mixed, review, explain, docs). All carry `split: holdout`; there is no train/test division (every scenario
is confirmatory). Authored in three batches (`validate_holdout.py` batch A: repos + polyglot bugfix/feature; `validate_b.py`
batch B: mixed + polyglot docs/mixed, generators in `gen_b/`; `validate_c.py` batch C: knowledge + repos review/explain).
Reports of the three batches: `VALIDATION.md`, `VALIDATION-B.md`, `VALIDATION-C.md`.

| file | what it is |
|---|---|
| `SPLIT.md` | the panel table, the PLAN S1 constraint check and the overlap report against main-v1 / pilot-v1 (`panel.py` writes it) |
| `scenario-hashes.json` | the frozen contract: sha256 of every scenario file, `scenario_hash`, `prompt_sha256`, the snapshot tree hash, the hidden-grader hash and a panel hash. The preregistration quotes the panel hash |
| `validation-combined.json` | the one combined, serial, memguarded validator run over all 60 (`validate_all.py`) |
| `panel.py` | constraints + overlaps + hashes (`--write` regenerates `SPLIT.md` and `scenario-hashes.json`) |
| `validate_all.py` | dispatches each scenario to the validator that matches how its reference was authored |

## Re-validate, re-check, re-freeze

```bash
export PYTHONPATH=src:.:scripts:evals
memory_pressure | tail -1                      # need >= 50% free; the scripts refuse to run a scenario below that
python3 evals/paired/scenarios/holdout-v3/validate_all.py       # serial, nice 10, memguard 4 GB / 300 s per grader run
python3 evals/paired/scenarios/holdout-v3/panel.py              # prints problems/overlaps; exit 1 on any problem
python3 evals/paired/scenarios/holdout-v3/panel.py --write      # only BEFORE the preregistration commit
```

Every grader, hidden test and `go test` of a scenario runs through `scripts/memguard.py` (4 GB cap, 300 s timeout, system-memory
floor); never run scenario code outside it. References (never shown to agents) live outside the repository under
`~/dev/afast-paired-refs/holdout-v3/<id>/turnN/`; frozen snapshots under `~/dev/afast-paired/snapshots/<id>-<hash10>/` are
verified by tree hash on every use.

## Rules

* Never run by any agent before S1 (the smoke design `evals/paired/holdout-v3-smoke.yaml` is the single, disclosed exception:
  one plain-Sonnet session per scenario to confirm solvability; it is not analysed).
* After the S1 preregistration commit nothing in this directory that enters a hash may change. A change is a deviation and is
  recorded in the preregistration's provenance file with its reason.
* The same upstream repository must not appear in two scenarios at one commit; `panel.py` fails on an identical id,
  repo@sha/subdir, inline tree, or exercise slug in the same language across holdout-v3, main-v1 and pilot-v1. The same exercise
  slug in another language is reported (4 cases, listed in `SPLIT.md`: go-bowling vs pilot py-bowling, and three more) and kept: a
  different language is a different task for the model, with different files, tests and prompts.
