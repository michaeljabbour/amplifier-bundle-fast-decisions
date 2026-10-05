# holdout-v3 batch A scenario validation (20 scenarios: 10 bugfix + 10 feature)

- Branch / worktree: `v3/scenarios-a` (`/Users/michaeljabbour/dev/fd-v3-scen-a`), based on `origin/v3/program` c1ebafa.
- Validator: `validate_holdout.py` in this directory (serial, `--jobs 1 --cap-gb 4 --grader-timeout 300`, `MEMGUARD_MAX_CONCURRENT=1`, `memory_pressure` free % checked >= 50 before each scenario; observed 85-87 %). Machine-readable: `validation.json`.
- References (outside the repo): `~/dev/afast-paired-refs/holdout-v3/<id>/turnN/` (cumulative full-file overlays, `MESSAGE.txt` = reference final message, `_DELETE`), authoring tools `~/dev/afast-paired-refs/holdout-v3/_tools/` (`hb.py`, `dbg.py`, `scenarios/<module>.py`), frozen snapshots `_snapshots/`.
- Result: **20/20 valid**. 262 guarded grader runs, **0 memguard kills**, max sampled peak 0.134 GB (whole-tree RSS sampled every 0.25 s; most runs finish between two samples and report 0.0).
- Real-repo families: 12 (10 bugfix, 2 feature), 9 of them with > 300 workspace files; polyglot: 8 (all feature). Turn counts: [8, 9, 9, 9, 9, 9, 9, 10, 10, 10, 10, 10, 10, 11, 11, 11, 12, 14, 14, 16]. Scenarios with two 420 s idle gaps: go-cryptosquare, falcon-regexconv, pyg-rawtoken.

## What each validated row means

1. loader: `paired_scenarios.parse` accepts the file (`split: holdout` is appended to `SPLITS` in-process, see Caveats).
2. snapshot builds twice with the same tree hash; second `materialize` verifies the stored hash.
3. start: turn 1's checks FAIL on the pristine workspace (label shown).
4. reference: every turn's checks PASS on the cumulative reference state.
5. discriminating: every turn's checks FAIL on the state before that turn with a content-free final message (`DONE: ok`), so no turn passes for free; `weak` counts sub-checks (file_regex/doc_sections/keyed_facts) that already pass before their turn while a sibling check still discriminates.
6. guarded: every scenario/hidden-test run went through `memguard.run` (4 GB cap, 300 s, system floor).

## Table

| family | id | task_type | repo@sha / exercise | files | turns | 420 s gaps before turns | start fails | ref passes | discriminating | weak | guarded runs | kills | peak GB | runtime s | scenario hash |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| repos | bottle-etag | bugfix | bottlepy/bottle@2a743a302a71 (fix b73bd1db) | 219 | 10 | - | yes (pytest_failures) | all (10/10) | all | 0 | 11 | 0 | 0.0 | 10.9 | cf4c7af9f3d0 |
| repos | faker-nonutf-cli | bugfix | joke2k/faker@5b56bd720b92 (fix 7b41840a) | 818 | 9 | - | yes (pytest_failures) | all (9/9) | all | 0 | 9 | 0 | 0.134 | 27.6 | d422004e3d20 |
| repos | falcon-regexconv | feature | falconry/falcon@e45dd08ea161 (fix eb27592b) | 436 | 10 | 5,9 | yes (pytest_failures) | all (10/10) | all | 0 | 11 | 0 | 0.053 | 14.3 | 0ea317ae4776 |
| repos | fpdf2-booldict | bugfix | py-pdf/fpdf2@a78182be9331 (fix dd0d4517) | 1615 | 9 | - | yes (pytest_failures) | all (9/9) | all | 0 | 9 | 0 | 0.094 | 24.8 | 14a52a67ea89 |
| repos | jsonschema-jsonpath | bugfix | python-jsonschema/jsonschema@11455212a0ee (fix 9a957d77) | 628 | 10 | - | yes (pytest_failures) | all (10/10) | all | 0 | 9 | 0 | 0.0 | 12.1 | e46db57e4082 |
| repos | peewee-filterfk | bugfix | coleifer/peewee@1f7c96dbe3d8 (fix c7f0cd45) | 194 | 9 | - | yes (pytest_failures) | all (9/9) | all | 0 | 9 | 0 | 0.116 | 14.2 | 4a5145b92bc6 |
| repos | pyg-rawtoken | bugfix | pygments/pygments@6a7aa837d500 (fix 2f0d713b) | 2783 | 10 | 5,8 | yes (pytest_failures) | all (10/10) | all | 0 | 11 | 0 | 0.0 | 38.7 | d5b07eab6bca |
| repos | pyparsing-quotedws | bugfix | pyparsing/pyparsing@d3388aaf5c60 (fix 59b167db) | 293 | 10 | - | yes (pytest_failures) | all (10/10) | all | 0 | 11 | 0 | 0.107 | 16.0 | cc20fc0d97ea |
| repos | rich-softwrap | bugfix | Textualize/rich@05ff970926cb (fix 39ee57df) | 550 | 9 | - | yes (pytest_failures) | all (9/9) | all | 0 | 9 | 0 | 0.063 | 11.6 | 99e4799a8610 |
| repos | tornado-zerotimeout | bugfix | tornadoweb/tornado@4d892393adb0 (fix aac84855) | 320 | 9 | - | yes (pytest_failures) | all (9/9) | all | 0 | 11 | 0 | 0.058 | 47.4 | c8fa702348ca |
| repos | xlsxwriter-filter | bugfix | jmcnamara/XlsxWriter@efd07187f174 (fix 6b698c2d) | 2839 | 9 | - | yes (pytest_failures) | all (9/9) | all | 0 | 11 | 0 | 0.0 | 31.6 | 7785438c4071 |
| repos | ytdlp-fps | feature | yt-dlp/yt-dlp@7a569456f24f (fix 1249676e) | 1238 | 8 | - | yes (pytest_failures) | all (8/8) | all | 0 | 11 | 0 | 0.074 | 20.3 | 9cb1b8403269 |
| polyglot | go-bowling | feature | Aider polyglot go/exercises/practice/bowling@7e0611e77b54 | 5 | 14 | - | yes (build_failed) | all (14/14) | all | 0 | 17 | 0 | 0.0 | 13.4 | fc2108bef582 |
| polyglot | go-cryptosquare | feature | Aider polyglot go/exercises/practice/crypto-square@7e0611e77b54 | 4 | 11 | 5,9 | yes (go_test_failures) | all (11/11) | all | 0 | 17 | 0 | 0.032 | 13.8 | 5fd6129a96a5 |
| polyglot | js-linkedlist | feature | Aider polyglot javascript/exercises/practice/simple-linked-list@7e0611e77b54 | 9 | 14 | - | yes (cmd_failed) | all (14/14) | all | 0 | 19 | 0 | 0.0 | 15.3 | f46e4a141cf7 |
| polyglot | js-queenattack | feature | Aider polyglot javascript/exercises/practice/queen-attack@7e0611e77b54 | 9 | 11 | - | yes (cmd_failed) | all (11/11) | all | 0 | 17 | 0 | 0.0 | 13.2 | 75e31aa866f9 |
| polyglot | py-dotdsl | feature | Aider polyglot python/exercises/practice/dot-dsl@7e0611e77b54 | 4 | 12 | - | yes (pytest_failures) | all (12/12) | all | 0 | 19 | 0 | 0.0 | 16.9 | fff22ad1fd2a |
| polyglot | py-gradeschool | feature | Aider polyglot python/exercises/practice/grade-school@7e0611e77b54 | 4 | 10 | - | yes (pytest_failures) | all (10/10) | all | 0 | 15 | 0 | 0.0 | 12.0 | fbbc006fc99e |
| polyglot | py-grep | feature | Aider polyglot python/exercises/practice/grep@7e0611e77b54 | 3 | 16 | - | yes (pytest_failures) | all (16/16) | all | 0 | 19 | 0 | 0.0 | 13.9 | 5c4eff311ac8 |
| polyglot | py-zipper | feature | Aider polyglot python/exercises/practice/zipper@7e0611e77b54 | 3 | 11 | - | yes (pytest_failures) | all (11/11) | all | 0 | 17 | 0 | 0.0 | 13.4 | 964436bf69ac |

## Caveats

- **Stock loader rejects `split: holdout`.** `scripts/paired_scenarios.py` has `SPLITS = ('train','test','pilot')` (the same defect main-v1 had for `main`); every validator here appends `holdout` in-process. One-line fix before S1 loads the panel: add `'holdout'` to `SPLITS`. No loader change was made on this branch.
- `go-bowling` is the Go port of an exercise whose Python version (`python/bowling`) was a pilot-v1 scenario. It is a different corpus directory, language, test file and scenario (precedent: main-v1 `py-book-store` vs Go `book-store` in the S2 slice), but the program owner may prefer to drop or swap it.
- Real-repo scenarios run pytest with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (the grader's setting); `fpdf2-booldict` passes `-o addopts=` (its pyproject adds `--cov` options that need the disabled plugin) and `pyparsing-quotedws`/`ytdlp-fps` pass `-k` filters to keep turns in seconds.
- `rich-softwrap`: `tests/test_console.py::test_brokenpipeerror` fails on the pristine parent in this environment (it shells out to `python -m rich`), so that file is not used in any check.
- `tornado-zerotimeout` turn 1 fails on the parent through an async test timeout (about 8 s of wall time per grading of that turn).
- Hidden tests for turns >= 2 are scenario-authored (`hidden_files`, inline); turn 1 of every real-repo scenario uses the upstream commit's own test files via `from_git`. Workspace = parent of the upstream commit; nothing from the fix leaks into the workspace.
- The workspace snapshot of `networkx` was evaluated and dropped (needs an installed package for its backend entry points).
