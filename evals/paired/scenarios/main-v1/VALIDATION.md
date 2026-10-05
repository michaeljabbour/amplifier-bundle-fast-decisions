# main-v1 scenario validation

- Date: 2026-10-01
- Commit: `4caf4639ec58dd9cf85140b90ddd25d0634d3293` (branch `eval/paired-measurement`)
- Guard: every validator run with `--cap-gb 4 --grader-timeout 300` (and `--jobs 1` where supported), `MEMGUARD_MAX_CONCURRENT=1`, one validator invocation per scenario, strictly serial; system memory free % checked >= 50 before each (observed 94-96 %).
- Peaks: memguard whole-tree RSS sampled every 0.25 s via a wrapper around `memguard.run_guarded` (no repo code changed); sub-sample runs record ~0.
- Machine-readable: `validation.json`.

## Result: 65 valid / 5 defective (minor, non-blocking) / 0 unvalidatable (of 70)

All 70 pass their validator (loads, start state fails, reference passes every turn). 1015 guarded runs: **0 resource_limit kills, 0 timeouts**, max sampled peak 0.334 GB (rust-gradeschool). The 5 defects are file_regex sub-checks that already match the pristine upstream file (the turn still discriminates through a sibling check, but that requirement is unenforced).

## Systemic (blocking for the stock loader)

scripts/paired_scenarios.py SPLITS=('train','test','pilot') and TASK_TYPES lack 'main', 'docs', 'explain'. All 70 main-v1 files carry split: main (rejected by the stock loader); 7 knowledge files also use task_type docs (4) / explain (3). Every validator monkeypatches the tuples in-process, so validators pass while the unpatched loader rejects 70/70.

**Fix:** Either add 'main' to SPLITS and 'docs','explain' to TASK_TYPES in scripts/paired_scenarios.py:51-52, or (as the polyglot validator comment intends) assign the seeded train/test split to each file and map docs/explain to 'knowledge' before the campaign loads main-v1.

pilot-v1 (5 files) loads with the stock loader.

## Defects and exact fixes (do not edit until reviewed; each replacement checked: 0 matches on pristine, >= min_count on the reference at that turn)

| scenario | turn | path | current pattern | replace with |
|---|---|---|---|---|
| jmespath-strcmp | 7 | `CHANGELOG.rst` | `(?i)string` | `^Next Release\s*\n=+\n(?:(?!\d+\.\d+\.\d+\s*\n=).*\n)*?.*(?i:string)` |
| pathspec-matchfile | 5 | `CHANGES.rst` | `match_file` | `^0\.12\.1 \(TBD\)\n-+\n(?:(?!\d+\.\d+\.\d+ \().*\n)*?.*match_file` |
| pathspec-matchfile | 7 | `pathspec/pathspec.py` | `\*separators\*` | `def partition\([^)]*\)[^\n]*:\n\s+"""(?:(?!""")[\s\S])*?\*separators\*` |
| schema-wrongkey | 6 | `CHANGELOG.md` | `Optional` | `^## Unreleased\n(?:(?!## v).*\n)*?.*Optional` |
| schema-wrongkey | 7 | `schema/__init__.py` | `wrong_keys min_count: 4` | `wrong_keys min_count: 8` |
| sortedc-update | 6 | `HISTORY.rst` | `__rmul__\|rmul` | `^2\.2\.3 \(unreleased\)\n-{10,}\n(?:(?!\d+\.\d+\.\d+ \().*\n)*?.*(?:__rmul__\|rmul)` |
| sortedc-update | 6 | `HISTORY.rst` | `update` | `^2\.2\.3 \(unreleased\)\n-{10,}\n(?:(?!\d+\.\d+\.\d+ \().*\n)*?.*update` |
| sqlparse-realname | 5 | `CHANGELOG` | `Development Version\n(?:.*\n)+?\* .*get_real_name` | `Development Version\n-+\n(?:(?!Release ).*\n)*?\* .*get_real_name` |
| sqlparse-realname | 5 (hardening only: 0 hits on pristine today, same unbounded span) | `CHANGELOG` | `Development Version\n(?:.*\n)+?\* .*(spaced\|spaces\|whitespace).*\n?.*(dot\|alias)` | `Development Version\n-+\n(?:(?!Release ).*\n)*?\* .*(spaced\|spaces\|whitespace).*\n?.*(dot\|alias)` |

sales-orders turn 15 warning (passes with half-truncated reference files) is informational, not a defect: the turn only grades the new Executive summary at the top of report.md, and the start state still fails.

## Coverage notes

- validate_knowledge.py does not grade the empty/start state; it proves discrimination with a per-turn plausible-wrong variant (all passed). Start-state failure for knowledge is therefore not verified.
- validate_polyglot.py's start check covers turn 1 on the starter; later turns' discrimination is the `weak` check (all empty).
- polyglot was run with `--ref-root ~/dev/afast-paired-refs/polyglot`; the validator's default root has only 8/20 (those 8 are byte-identical).

## References not under ~/dev/afast-paired-refs

18 scenarios: boltons-tableutils, cachetools-params, jmespath-strcmp, markdown-tocclass, commander-docs, debug-triage, fastrand-explain, fatihcolor-docs, fd-cli-docs, filelock-explain, gohumanize-review, humanize-review, kac-docs, ms-review, nanoid-explain, pflag-mixed, semver-review, yamllint-mixed. All 18 exist under `~/dev/afast-paired-src/reference/{repos,knowledge}` and were validated from there. Missing everywhere: none.

## Per-scenario

| family | id | turns | stock loader | validator | start fails | ref passes | weak | kills | peak GB | runtime s | ref root |
|---|---|---|---|---|---|---|---|---|---|---|---|
| polyglot | go-dominoes | 13 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.032 | 11.8 | refs |
| polyglot | go-linkedlist | 16 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.062 | 24.5 | refs |
| polyglot | go-protein | 8 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.032 | 8.4 | refs |
| polyglot | go-say | 11 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.032 | 9.2 | refs |
| polyglot | go-vlq | 12 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.032 | 11.8 | refs |
| polyglot | js-listops | 8 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.0 | 5.5 | refs |
| polyglot | js-phone | 8 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.0 | 5.5 | refs |
| polyglot | js-rationals | 12 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.0 | 7.6 | refs |
| polyglot | js-tournament | 16 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.0 | 11.3 | refs |
| polyglot | py-book-store | 8 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.044 | 20.0 | refs |
| polyglot | py-forth | 10 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.054 | 13.4 | refs |
| polyglot | py-go-counting | 14 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.078 | 12.7 | refs |
| polyglot | py-poker | 12 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.047 | 10.4 | refs |
| polyglot | py-rest-api | 9 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.0 | 5.6 | refs |
| polyglot | py-sgf-parsing | 15 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.042 | 9.2 | refs |
| polyglot | rust-gradeschool | 12 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.334 | 25.4 | refs |
| polyglot | rust-luhn | 8 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.116 | 11.5 | refs |
| polyglot | rust-ocr | 16 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.265 | 32.0 | refs |
| polyglot | rust-twobucket | 12 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.243 | 22.1 | refs |
| polyglot | rust-wordy | 16 | rejects (split: main) | OK | yes (turn 1) | all turns | 0 | 0 | 0.26 | 34.2 | refs |
| repos | boltons-tableutils | 8 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.094 | 12.9 | src |
| repos | cachetools-params | 10 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.0 | 3.3 | src |
| repos | jmespath-strcmp | 9 | rejects (split: main) | OK | yes | all turns | 1 | 0 | 0.0 | 3.6 | src |
| repos | lark-discard | 12 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.094 | 25.2 | refs |
| repos | lark-template | 8 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.094 | 21.1 | refs |
| repos | markdown-tocclass | 10 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.0 | 7.3 | src |
| repos | mistune-escape | 8 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.074 | 10.2 | refs |
| repos | moreit-chunked | 8 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.098 | 32.2 | refs |
| repos | pathspec-matchfile | 8 | rejects (split: main) | OK | yes | all turns | 2 | 0 | 0.0 | 4.8 | refs |
| repos | schema-wrongkey | 12 | rejects (split: main) | OK | yes | all turns | 2 | 0 | 0.0 | 5.2 | refs |
| repos | sortedc-update | 12 | rejects (split: main) | OK | yes | all turns | 2 | 0 | 0.074 | 17.6 | refs |
| repos | sqlparse-realname | 8 | rejects (split: main) | OK | yes | all turns | 1 | 0 | 0.063 | 9.6 | refs |
| repos | tabulate-github | 12 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.098 | 12.4 | refs |
| repos | toolz-interpose | 8 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.078 | 7.8 | refs |
| repos | voluptuous-number | 12 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.059 | 7.5 | refs |
| repos | xmltodict-none | 8 | rejects (split: main) | OK | yes | all turns | 0 | 0 | 0.048 | 6.0 | refs |
| mixed | api-docs | 16 | rejects (split: main) | OK | 16/16 | all turns | 0 | 0 | 0.0 | 9.9 | refs |
| mixed | arch-explain | 16 | rejects (split: main) | OK | 16/16 | all turns | 0 | 0 | 0.042 | 9.5 | refs |
| mixed | changelog-gen | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 8.1 | refs |
| mixed | config-matrix | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 6.8 | refs |
| mixed | deps-audit | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 5.8 | refs |
| mixed | discrepancy-docs | 16 | rejects (split: main) | OK | 16/16 | all turns | 0 | 0 | 0.017 | 7.9 | refs |
| mixed | docstring-audit | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 7.8 | refs |
| mixed | expense-anomaly | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 7.8 | refs |
| mixed | hr-salary-qa | 16 | rejects (split: main) | OK | 16/16 | all turns | 0 | 0 | 0.0 | 9.7 | refs |
| mixed | log-incident | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 4.7 | refs |
| mixed | meeting-notes | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 3.4 | refs |
| mixed | migration-plan | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 9.0 | refs |
| mixed | okr-status | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 7.9 | refs |
| mixed | pr-review-cart | 12 | rejects (split: main) | OK | 12/12 | all turns | 0 | 0 | 0.0 | 5.4 | refs |
| mixed | pr-review-retry | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 4.8 | refs |
| mixed | readme-rewrite | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 4.8 | refs |
| mixed | sales-orders | 16 | rejects (split: main) | OK | 16/16 | all turns | 1 | 0 | 0.0 | 8.6 | refs |
| mixed | support-workload | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 4.4 | refs |
| mixed | survey-analysis | 16 | rejects (split: main) | OK | 16/16 | all turns | 0 | 0 | 0.0 | 8.4 | refs |
| mixed | timesheet-invoice | 8 | rejects (split: main) | OK | 8/8 | all turns | 0 | 0 | 0.0 | 7.1 | refs |
| knowledge | commander-docs | 13 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.002 | 3.3 | src |
| knowledge | debug-triage | 11 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.0 | 1.6 | src |
| knowledge | fastrand-explain | 9 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.002 | 1.8 | src |
| knowledge | fatihcolor-docs | 8 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.035 | 2.3 | src |
| knowledge | fd-cli-docs | 16 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.0 | 1.3 | src |
| knowledge | filelock-explain | 9 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.0 | 1.4 | src |
| knowledge | gohumanize-review | 12 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.034 | 4.5 | src |
| knowledge | humanize-review | 12 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.034 | 2.2 | src |
| knowledge | kac-docs | 14 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.0 | 3.1 | src |
| knowledge | ms-review | 8 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.046 | 2.3 | src |
| knowledge | nanoid-explain | 10 | rejects (split: main, task_type) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.0 | 1.1 | src |
| knowledge | pflag-mixed | 15 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.161 | 7.2 | src |
| knowledge | semver-review | 10 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.199 | 4.3 | src |
| knowledge | yamllint-mixed | 14 | rejects (split: main) | OK | n/a (wrong variant fails) | all turns | 0 | 0 | 0.045 | 4.5 | src |
