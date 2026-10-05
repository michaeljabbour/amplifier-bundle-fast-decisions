# holdout-v3: the S1 scenario panel (all `split: holdout`)

No train/test division: all 60 scenarios are confirmatory for S1 (docs/design/v3/PLAN.md, S1). Dev-only data stays main-v1 (its test split already carried three confirmations). The frozen contract is `scenario-hashes.json` (panel sha256 `7c76addbe215a9fbab9d18a84520a6d125b7ddba3f4e74d510598521eec5ce31`); `panel.py` re-checks every constraint below from the files.

## Constraints (PLAN S1) and the observed panel

| constraint | required | observed |
|---|---|---|
| scenarios | 60 | 60 |
| per task type | 10 each | bugfix 10, feature 10, mixed 10, review 10, explain 10, docs 10 |
| families | polyglot 12, repos 20, mixed 16, knowledge 12 | polyglot 12, repos 20, mixed 16, knowledge 12 |
| workspace files > 300 | >= 12 | 16 (every file) / 16 (scope-gate count) |
| >= 2 idle gaps (>= 300 s) | >= 6 | 21 |
| turns | 8-16 | 8-16 |
| overlap with main-v1 / pilot-v1 | none | 0 identical; see below |

## Family x task type

| family | bugfix | feature | mixed | review | explain | docs | total |
|---|---|---|---|---|---|---|---|
| polyglot | 0 | 8 | 2 | 0 | 0 | 2 | 12 |
| repos | 10 | 2 | 0 | 4 | 4 | 0 | 20 |
| mixed | 0 | 0 | 8 | 0 | 0 | 8 | 16 |
| knowledge | 0 | 0 | 0 | 6 | 6 | 0 | 12 |

## Overlap report (against main-v1: 70 scenarios, pilot-v1: 5)

- **Identical (id, repo@sha/subdir, inline tree): FAILS the check:** none
- **Same exercise slug and language: FAILS the check:** none
- **Same exercise slug, other language (reported, kept: a different task in a different language):** 
  - go-bowling (go/bowling) vs pilot-v1/py-bowling (python/bowling)
  - js-linkedlist (javascript/simple-linked-list) vs main-v1/go-linkedlist (go/simple-linked-list)
  - py-gradeschool (python/grade-school) vs main-v1/rust-gradeschool (rust/grade-school)
  - py-linked-list-docs (python/simple-linked-list) vs main-v1/go-linkedlist (go/simple-linked-list)
- **Same upstream repository, other commit/files (reported, kept: a different bug/feature and a different snapshot):** none
- **Turn-1 task text (the shared Rules boilerplate stripped) resembles an existing scenario's, ratio > 0.8 (reported):** 
  - go-crypto-docs turn 1 resembles pilot-v1/go-wordsearch (ratio 0.92)

## Scenarios

| id | family | type | lang | turns | idle gaps | files | scope-gate files | source | scenario hash |
|---|---|---|---|---|---|---|---|---|---|
| black-pipeline-explain | knowledge | explain | python | 14 | 2 | 504 | 505 | psf/black@77c0cae1 | `86a526f0bfb5` |
| click-flow-explain | knowledge | explain | python | 10 | 0 | 178 | 179 | pallets/click@06b2a678 | `5348ecc1ed17` |
| marsh-load-explain | knowledge | explain | python | 10 | 0 | 103 | 104 | marshmallow-code/marshmallow@1c63bdaf | `ca0908190457` |
| mkdocs-events-explain | knowledge | explain | python | 11 | 2 | 280 | 281 | mkdocs/mkdocs@28625367 | `5df3ece7f552` |
| pluggy-calls-explain | knowledge | explain | python | 10 | 0 | 98 | 99 | pytest-dev/pluggy@1ca1d527 | `c45ef1aa05e0` |
| xmlschema-arch-explain | knowledge | explain | python | 12 | 2 | 523 | 524 | sissaschool/xmlschema@627c1795 | `956c8c6daab3` |
| bleach-sanitize-review | knowledge | review | python | 10 | 2 | 125 | 126 | mozilla/bleach@f0355a7a | `22dd5fb52c77` |
| dateutil-calendar-review | knowledge | review | python | 10 | 2 | 104 | 105 | dateutil/dateutil@2642afac | `3d671ee33858` |
| honcho-process-review | knowledge | review | python | 8 | 0 | 72 | 73 | nickstenning/honcho@2f47b723 | `75dfa0b8f7a1` |
| itsdang-signer-review | knowledge | review | python | 13 | 0 | 53 | 54 | pallets/itsdangerous@672971d6 | `d9b0a09e2608` |
| jsch-planted-review | knowledge | review | python | 16 | 2 | 631 | 632 | python-jsonschema/jsonschema@51cd75e3 | `4852f0225d5b` |
| schedule-semantics-review | knowledge | review | python | 10 | 0 | 35 | 36 | dbader/schedule@82a43db1 | `9fa904139c5c` |
| adr-records | mixed | docs | markdown | 10 | 0 | 13 | 14 | inline (self-authored) | `f836c91666ae` |
| alert-runbooks | mixed | docs | markdown | 10 | 0 | 4 | 5 | inline (self-authored) | `1c609552bc79` |
| cli-manual | mixed | docs | python | 10 | 2 | 4 | 5 | inline (self-authored) | `1adbdc0ea6c2` |
| config-reference | mixed | docs | json | 11 | 0 | 4 | 5 | inline (self-authored) | `de13abb8272c` |
| data-dictionary | mixed | docs | markdown | 10 | 0 | 3 | 4 | inline (self-authored) | `9e55de09f49f` |
| docs-corpus | mixed | docs | markdown | 10 | 2 | 323 | 324 | inline (self-authored) | `3a621b10f2a4` |
| lib-reference | mixed | docs | python | 10 | 0 | 5 | 6 | inline (self-authored) | `719236c1f43b` |
| onboarding-guide | mixed | docs | markdown | 10 | 2 | 14 | 15 | inline (self-authored) | `6a55b2fc6092` |
| access-log-stats | mixed | mixed | python | 8 | 0 | 4 | 5 | inline (self-authored) | `b589867a5518` |
| bank-recon | mixed | mixed | python | 10 | 0 | 3 | 4 | inline (self-authored) | `0d6cfeb54565` |
| db-evolution | mixed | mixed | sql | 13 | 0 | 14 | 15 | inline (self-authored) | `a00afa28a3e1` |
| fleet-fuel | mixed | mixed | python | 9 | 0 | 3 | 4 | inline (self-authored) | `843e2b87113b` |
| gradebook | mixed | mixed | python | 9 | 0 | 5 | 6 | inline (self-authored) | `4db08848b927` |
| inventory-recon | mixed | mixed | python | 11 | 2 | 5 | 6 | inline (self-authored) | `8d8dc42c5660` |
| release-fragments | mixed | mixed | python | 9 | 2 | 41 | 42 | inline (self-authored) | `a8dc499cecbe` |
| svc-config-audit | mixed | mixed | python | 15 | 2 | 323 | 324 | inline (self-authored) | `9b538866a145` |
| go-sublist-docs | polyglot | docs | go | 9 | 2 | 6 | 7 | aider-ai/polyglot-benchmark@7e0611e7 `go/exercises/practice/sublist` | `c18c7daea72e` |
| py-linked-list-docs | polyglot | docs | python | 9 | 2 | 6 | 7 | aider-ai/polyglot-benchmark@7e0611e7 `python/exercises/practice/simple-linked-list` | `aa579cb184c2` |
| go-bowling | polyglot | feature | go | 14 | 0 | 5 | 6 | aider-ai/polyglot-benchmark@7e0611e7 `go/exercises/practice/bowling` | `fc2108bef582` |
| go-cryptosquare | polyglot | feature | go | 11 | 2 | 4 | 5 | aider-ai/polyglot-benchmark@7e0611e7 `go/exercises/practice/crypto-square` | `5fd6129a96a5` |
| js-linkedlist | polyglot | feature | javascript | 14 | 0 | 9 | 10 | aider-ai/polyglot-benchmark@7e0611e7 `javascript/exercises/practice/simple-linked-list` | `f46e4a141cf7` |
| js-queenattack | polyglot | feature | javascript | 11 | 0 | 9 | 10 | aider-ai/polyglot-benchmark@7e0611e7 `javascript/exercises/practice/queen-attack` | `75e31aa866f9` |
| py-dotdsl | polyglot | feature | python | 12 | 0 | 4 | 5 | aider-ai/polyglot-benchmark@7e0611e7 `python/exercises/practice/dot-dsl` | `fff22ad1fd2a` |
| py-gradeschool | polyglot | feature | python | 10 | 0 | 4 | 5 | aider-ai/polyglot-benchmark@7e0611e7 `python/exercises/practice/grade-school` | `fbbc006fc99e` |
| py-grep | polyglot | feature | python | 16 | 0 | 3 | 4 | aider-ai/polyglot-benchmark@7e0611e7 `python/exercises/practice/grep` | `5c4eff311ac8` |
| py-zipper | polyglot | feature | python | 11 | 0 | 3 | 4 | aider-ai/polyglot-benchmark@7e0611e7 `python/exercises/practice/zipper` | `964436bf69ac` |
| go-crypto-docs | polyglot | mixed | go | 8 | 0 | 4 | 5 | aider-ai/polyglot-benchmark@7e0611e7 `go/exercises/practice/crypto-square` | `45fc8f28cd76` |
| py-zipper-docs | polyglot | mixed | python | 10 | 2 | 3 | 4 | aider-ai/polyglot-benchmark@7e0611e7 `python/exercises/practice/zipper` | `e18399ad5d28` |
| bottle-etag | repos | bugfix | python | 10 | 0 | 219 | 220 | bottlepy/bottle@2a743a30 | `cf4c7af9f3d0` |
| faker-nonutf-cli | repos | bugfix | python | 9 | 0 | 818 | 819 | joke2k/faker@5b56bd72 | `d422004e3d20` |
| fpdf2-booldict | repos | bugfix | python | 9 | 0 | 1615 | 1616 | py-pdf/fpdf2@a78182be | `14a52a67ea89` |
| jsonschema-jsonpath | repos | bugfix | python | 10 | 0 | 628 | 629 | python-jsonschema/jsonschema@11455212 | `e46db57e4082` |
| peewee-filterfk | repos | bugfix | python | 9 | 0 | 194 | 195 | coleifer/peewee@1f7c96db | `4a5145b92bc6` |
| pyg-rawtoken | repos | bugfix | python | 10 | 2 | 2783 | 2784 | pygments/pygments@6a7aa837 | `d5b07eab6bca` |
| pyparsing-quotedws | repos | bugfix | python | 10 | 0 | 293 | 294 | pyparsing/pyparsing@d3388aaf | `cc20fc0d97ea` |
| rich-softwrap | repos | bugfix | python | 9 | 0 | 550 | 551 | textualize/rich@05ff9709 | `99e4799a8610` |
| tornado-zerotimeout | repos | bugfix | python | 9 | 0 | 320 | 321 | tornadoweb/tornado@4d892393 | `c8fa702348ca` |
| xlsxwriter-filter | repos | bugfix | python | 9 | 0 | 2839 | 2840 | jmcnamara/xlsxwriter@efd07187 | `7785438c4071` |
| cssselect-xpath-explain | repos | explain | python | 10 | 2 | 27 | 28 | scrapy/cssselect@663d9089 | `59366f6de3f4` |
| jsonpatch-ops-explain | repos | explain | python | 10 | 0 | 26 | 27 | stefankoegl/python-json-patch@d8e1a6e2 | `d4e88c5684cf` |
| rich-text-split-explain | repos | explain | python | 11 | 2 | 553 | 554 | textualize/rich@9d8f9a37 | `5aede06ef513` |
| tomlkit-roundtrip-explain | repos | explain | python | 10 | 0 | 80 | 81 | python-poetry/tomlkit@0518af25 | `56fa4981675d` |
| falcon-regexconv | repos | feature | python | 10 | 2 | 436 | 437 | falconry/falcon@e45dd08e | `0ea317ae4776` |
| ytdlp-fps | repos | feature | python | 8 | 0 | 1238 | 1239 | yt-dlp/yt-dlp@7a569456 | `9cb1b8403269` |
| isodate-regress-review | repos | review | python | 10 | 2 | 31 | 32 | gweis/isodate@17cb25eb | `46b762076345` |
| jpointer-regress-review | repos | review | python | 10 | 0 | 23 | 24 | stefankoegl/python-json-pointer@5998f951 | `f0cf619ac1fb` |
| pyg-util-regress-review | repos | review | python | 12 | 0 | 2797 | 2798 | pygments/pygments@156d85fd | `bd06a4192813` |
| validators-regress-review | repos | review | python | 11 | 0 | 133 | 134 | python-validators/validators@70de3243 | `72543b2cb2be` |
