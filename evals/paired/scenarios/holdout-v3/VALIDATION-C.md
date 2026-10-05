# holdout-v3 batch C validation (20 scenarios: 12 knowledge + 8 repos; 10 review + 10 explain)

- Result: **20/20 valid** (loader parses with the stock loader, start state fails every turn, reference passes every turn, plausible-wrong variant fails every turn)
- Guard: `run_all_c.sh`: one `validate_c.py` invocation per scenario, strictly serial, `--cap-gb 4 --grader-timeout 300`, `MEMGUARD_MAX_CONCURRENT=1`, free memory >= 50% checked before each; all grading through scripts/memguard.py
- Kills: 0 memory kills, 0 timeouts; max sampled peak 0.067 GB
- Workspaces > 300 files: 5; scenarios with two 420 s gaps: 9; turns min/max: 8/16

| family | id | type | repo@sha | files | turns | gaps | check kinds | start fails | wrong fails | ref passes | kills | peak GB | valid |
|---|---|---|---|---:|---:|---|---|---|---|---|---:|---:|---|
| knowledge | black-pipeline-explain | explain | psf/black@77c0cae | 504 | 14 | 6,10 | doc_sections,file_regex,keyed_facts,tests | 14/14 | 14/14 | 14/14 | 0 | 0.0 | yes |
| knowledge | bleach-sanitize-review | review | mozilla/bleach@f0355a7 | 125 | 10 | 5,9 | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.002 | yes |
| knowledge | click-flow-explain | explain | pallets/click@06b2a67 | 178 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.0 | yes |
| knowledge | dateutil-calendar-review | review | dateutil/dateutil@2642afa | 104 | 10 | 4,8 | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.002 | yes |
| knowledge | honcho-process-review | review | nickstenning/honcho@2f47b72 | 72 | 8 | - | doc_sections,file_regex,keyed_facts,tests | 8/8 | 8/8 | 8/8 | 0 | 0.066 | yes |
| knowledge | itsdang-signer-review | review | pallets/itsdangerous@672971d | 53 | 13 | - | doc_sections,file_regex,keyed_facts,tests | 13/13 | 13/13 | 13/13 | 0 | 0.043 | yes |
| knowledge | jsch-planted-review | review | python-jsonschema/jsonschema@51cd75e | 631 | 16 | 5,9 | doc_sections,file_regex,keyed_facts,tests | 16/16 | 16/16 | 16/16 | 0 | 0.067 | yes |
| knowledge | marsh-load-explain | explain | marshmallow-code/marshmallow@1c63bda | 103 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.0 | yes |
| knowledge | mkdocs-events-explain | explain | mkdocs/mkdocs@2862536 | 280 | 11 | 5,9 | doc_sections,file_regex,keyed_facts,tests | 11/11 | 11/11 | 11/11 | 0 | 0.0 | yes |
| knowledge | pluggy-calls-explain | explain | pytest-dev/pluggy@1ca1d52 | 98 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.0 | yes |
| knowledge | schedule-semantics-review | review | dbader/schedule@82a43db | 35 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.041 | yes |
| knowledge | xmlschema-arch-explain | explain | sissaschool/xmlschema@627c179 | 523 | 12 | 6,10 | doc_sections,file_regex,keyed_facts,tests | 12/12 | 12/12 | 12/12 | 0 | 0.0 | yes |
| repos | cssselect-xpath-explain | explain | scrapy/cssselect@663d908 | 27 | 10 | 4,8 | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.0 | yes |
| repos | isodate-regress-review | review | gweis/isodate@17cb25e | 31 | 10 | 4,8 | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.002 | yes |
| repos | jpointer-regress-review | review | stefankoegl/python-json-pointer@5998f95 | 23 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.002 | yes |
| repos | jsonpatch-ops-explain | explain | stefankoegl/python-json-patch@d8e1a6e | 26 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.0 | yes |
| repos | pyg-util-regress-review | review | pygments/pygments@156d85f | 2797 | 12 | - | doc_sections,file_regex,keyed_facts,tests | 12/12 | 12/12 | 12/12 | 0 | 0.043 | yes |
| repos | rich-text-split-explain | explain | Textualize/rich@9d8f9a3 | 553 | 11 | 5,9 | doc_sections,file_regex,keyed_facts,tests | 11/11 | 11/11 | 11/11 | 0 | 0.0 | yes |
| repos | tomlkit-roundtrip-explain | explain | python-poetry/tomlkit@0518af2 | 80 | 10 | - | doc_sections,file_regex,keyed_facts,tests | 10/10 | 10/10 | 10/10 | 0 | 0.0 | yes |
| repos | validators-regress-review | review | python-validators/validators@70de324 | 133 | 11 | - | doc_sections,file_regex,keyed_facts,tests | 11/11 | 11/11 | 11/11 | 0 | 0.041 | yes |

## Disclosures

- scripts/paired_scenarios.py: `SPLITS` gains `"holdout"` (one word; the stock loader rejected `split: holdout`). Sibling batches A/B will carry the same edit.
- One validator for both families (`validate_c.py`, adapted from validate_knowledge.py): stock loader, double materialize with identical tree hash, start state fails every turn, per-turn reference passes, per-turn plausible-wrong variant fails, keyed_facts not satisfied by the prompt or by `DONE: ok`, notes when a check already passes before its turn. All grading goes through scripts/memguard.py.
- Reference messages/files are hand-authored from the pinned source and from real runs of the pinned code; no model call was made, so the PLAN's per-scenario plain-Sonnet smoke session is still to be done.
- Authoring-time fact checks used a few ad-hoc `python3 -c` snippets and one direct pytest of a two-test file outside memguard (tiny, not the validator); every validator/grader run was guarded.
- Network check: every snapshot was rebuilt from git by sha with `local_hint` ignored and the tree hash equals the cached one (honcho needed `.git_archival.txt` removed: its export-subst content differs between a tagged clone and a shallow fetch).
- Same upstream repos as batch A (different tasks): jsonschema, pygments, rich.
- References and generators: ~/dev/afast-paired-refs/holdout-v3/<id>/turnN/ and ~/dev/afast-paired-refs/holdout-v3/_tools/{lib.py,sc/*.py}.

