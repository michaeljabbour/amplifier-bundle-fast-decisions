# holdout-v3 batch B validation

- Date: 2026-10-05. Branch `v3/scenarios-b` (base origin/v3/program c1ebafa).
- Guard: `run_all_b.sh` (one `validate_b.py --ids <id> --cap-gb 4 --grader-timeout 300` per scenario, strictly serial, `MEMGUARD_MAX_CONCURRENT=1`, `memory_pressure` >= 50% free required before each; observed 86-87%). Every grader / hidden test / `go test` / pytest / doctest ran through scripts/memguard.py (via `paired_scenarios.grade_turn`). 0 resource_limit kills, 0 timeouts; max sampled whole-tree peak 0.055 GB.
- No model or network calls. Polyglot snapshots come from the pinned Aider corpus clone (sha 7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f) via `local_hint`.
- Loader: `scripts/paired_scenarios.py` SPLITS gains `holdout` (identical one-line change to batch C, so the merges are conflict-free); `validate_b.py` additionally parses every file with split=test.
- Checks per scenario: stock loader parses; 8-16 turns; gaps none or exactly two 420 s (never before turn 2); snapshot tree hash stable across two materialisations; no hidden-file name in a prompt; no keyed_facts satisfied by the prompt; at every turn the checks FAIL on the pre-turn state and PASS on the reference output; per-turn explicit wrong variant, `empty` mutation and (numeric turns) `bump` mutation all FAIL; tamper of a protected file fails the last turn; half-truncation probe (warning only).
- References live outside the repo: `~/dev/afast-paired-refs/holdout-v3/<id>/turnN/`. Regenerate everything with `gen_b/gen_all.py <module[:fn]> ...` (deterministic; expected values are computed by the generators).
- Machine-readable: `validation-b.json`; frozen scenario hashes: `scenario-hashes-b.json`.
- Polyglot exercises (outside main-v1, pilot-v1 and the S2 slice): python/zipper, python/simple-linked-list, go/crypto-square, go/sublist.

20/20 valid.

| family | id | task type | lang | turns | 420 s gaps | files | start fails | ref passes | wrong variants rejected | mutations rejected | guarded runs | kills | peak GB | s | result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mixed | access-log-stats | mixed | python | 8 | 0  | 4 | 8/8 | all turns | 8/8 | 13/13 | 22 | 0 | 0.055 | 26.0 | OK |
| mixed | adr-records | docs | markdown | 10 | 0  | 13 | 10/10 | all turns | 10/10 | 11/11 | 35 | 0 | 0.0 | 44.4 | OK |
| mixed | alert-runbooks | docs | markdown | 10 | 0  | 4 | 10/10 | all turns | 10/10 | 13/13 | 31 | 0 | 0.0 | 27.5 | OK |
| mixed | bank-recon | mixed | python | 10 | 0  | 3 | 10/10 | all turns | 10/10 | 15/15 | 33 | 0 | 0.0 | 32.4 | OK |
| mixed | cli-manual | docs | python | 10 | 2 [4, 8] | 4 | 10/10 | all turns | 10/10 | 10/10 | 30 | 0 | 0.019 | 27.1 | OK |
| mixed | config-reference | docs | json | 11 | 0  | 4 | 11/11 | all turns | 11/11 | 12/12 | 40 | 0 | 0.0 | 32.0 | OK |
| mixed | data-dictionary | docs | markdown | 10 | 0  | 3 | 10/10 | all turns | 10/10 | 17/17 | 34 | 0 | 0.0 | 29.7 | OK |
| mixed | db-evolution | mixed | sql | 13 | 0  | 14 | 13/13 | all turns | 13/13 | 14/14 | 35 | 0 | 0.0 | 31.9 | OK |
| mixed | docs-corpus | docs | markdown | 10 | 2 [4, 9] | 323 | 10/10 | all turns | 10/10 | 13/13 | 30 | 0 | 0.0 | 40.4 | OK |
| mixed | fleet-fuel | mixed | python | 9 | 0  | 3 | 9/9 | all turns | 9/9 | 16/16 | 23 | 0 | 0.0 | 21.7 | OK |
| mixed | gradebook | mixed | python | 9 | 0  | 5 | 9/9 | all turns | 9/9 | 15/15 | 28 | 0 | 0.0 | 28.3 | OK |
| mixed | inventory-recon | mixed | python | 11 | 2 [5, 9] | 5 | 11/11 | all turns | 11/11 | 18/18 | 40 | 0 | 0.0 | 33.3 | OK |
| mixed | lib-reference | docs | python | 10 | 0  | 5 | 10/10 | all turns | 10/10 | 11/11 | 35 | 0 | 0.0 | 30.2 | OK |
| mixed | onboarding-guide | docs | markdown | 10 | 2 [3, 7] | 14 | 10/10 | all turns | 10/10 | 11/11 | 35 | 0 | 0.0 | 36.1 | OK |
| mixed | release-fragments | mixed | python | 9 | 2 [4, 7] | 41 | 9/9 | all turns | 9/9 | 14/14 | 23 | 0 | 0.0 | 22.1 | OK |
| mixed | svc-config-audit | mixed | python | 15 | 2 [5, 10] | 323 | 15/15 | all turns | 15/15 | 23/23 | 43 | 0 | 0.0 | 68.8 | OK |
| polyglot | go-crypto-docs | mixed | go | 8 | 0  | 4 | 8/8 | all turns | 8/8 | 8/8 | 31 | 0 | 0.032 | 29.3 | OK |
| polyglot | go-sublist-docs | docs | go | 9 | 2 [4, 8] | 6 | 9/9 | all turns | 9/9 | 9/9 | 25 | 0 | 0.032 | 22.0 | OK |
| polyglot | py-linked-list-docs | docs | python | 9 | 2 [4, 8] | 6 | 9/9 | all turns | 9/9 | 9/9 | 45 | 0 | 0.0 | 44.2 | OK |
| polyglot | py-zipper-docs | mixed | python | 10 | 2 [5, 9] | 3 | 10/10 | all turns | 10/10 | 10/10 | 35 | 0 | 0.0 | 34.6 | OK |

warnings (informational): 1
- cli-manual turn8: still passes with half-truncated reference files
