# main-v1 train/test split (preregistered)

- Seed: **20261002** (python `random.Random`); written into every scenario file's `split:` line and `split.json`.
- Reproduce / verify: `python3 evals/paired/scenarios/main-v1/assign_split.py --check` (a pure function of the files).
- Target: 2/3 train, 1/3 test (23 of 70 test).

## Method

1. **Stratum** = (family, gap pattern). Family is the directory (polyglot / repos / mixed / knowledge); gap pattern is *long-gaps* (any 7-minute gap in the script) vs *no-gaps*.
2. **Unit** = one upstream project, so scenarios from the same upstream repository share a split: repos and knowledge scenarios are grouped by repository URL (only `lark-discard` + `lark-template` share one); each polyglot exercise and each authored (inline) fixture is its own unit (the polyglot-benchmark repo is a corpus, not a project). A unit takes the stratum of its first member by id.
3. **Quota**: floor(n/3) test slots per stratum, the rest of the 23 go to the strata with the largest fractional remainders (ties by the seeded RNG). Within a stratum, units are sorted by key, shuffled with the seeded RNG and filled into *test* until the quota is met; the rest are *train*.

## Counts

| family | gap pattern | train | test |
|---|---|---:|---:|
| knowledge | long-gaps | 3 | 1 |
| knowledge | no-gaps | 6 | 4 |
| knowledge | ALL | 9 | 5 |
| mixed | long-gaps | 5 | 2 |
| mixed | no-gaps | 9 | 4 |
| mixed | ALL | 14 | 6 |
| polyglot | long-gaps | 4 | 3 |
| polyglot | no-gaps | 9 | 4 |
| polyglot | ALL | 13 | 7 |
| repos | long-gaps | 3 | 2 |
| repos | no-gaps | 8 | 3 |
| repos | ALL | 11 | 5 |
| ALL | ALL | 47 | 23 |

pilot-v1 (5 scenarios) keeps `split: pilot` and is outside this split.

## Assignment

### test (23)

- **polyglot** (7): go-linkedlist [gaps], go-protein, js-listops, js-phone, py-go-counting [gaps], py-rest-api, rust-ocr [gaps]
- **repos** (5): lark-discard, lark-template [gaps], mistune-escape, toolz-interpose [gaps], xmltodict-none
- **mixed** (6): api-docs [gaps], discrepancy-docs [gaps], docstring-audit, readme-rewrite, sales-orders, survey-analysis
- **knowledge** (5): debug-triage, fastrand-explain, filelock-explain, humanize-review [gaps], semver-review

### train (47)

- **polyglot** (13): go-dominoes [gaps], go-say, go-vlq, js-rationals [gaps], js-tournament, py-book-store, py-forth [gaps], py-poker, py-sgf-parsing, rust-gradeschool [gaps], rust-luhn, rust-twobucket, rust-wordy
- **repos** (11): boltons-tableutils, cachetools-params [gaps], jmespath-strcmp, markdown-tocclass [gaps], moreit-chunked, pathspec-matchfile, schema-wrongkey, sortedc-update, sqlparse-realname, tabulate-github, voluptuous-number [gaps]
- **mixed** (14): arch-explain, changelog-gen, config-matrix, deps-audit, expense-anomaly [gaps], hr-salary-qa, log-incident [gaps], meeting-notes [gaps], migration-plan [gaps], okr-status, pr-review-cart [gaps], pr-review-retry, support-workload, timesheet-invoice
- **knowledge** (9): commander-docs [gaps], fatihcolor-docs, fd-cli-docs [gaps], gohumanize-review, kac-docs, ms-review, nanoid-explain, pflag-mixed, yamllint-mixed [gaps]

