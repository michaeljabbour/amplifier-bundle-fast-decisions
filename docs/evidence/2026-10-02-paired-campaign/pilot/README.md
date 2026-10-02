# Pilot-2 (screening pilot, not part of the analysis)

`pilot-2` is the second screening run (design `evals/paired/pilot-v1.yaml`) that preceded the preregistration. The preregistration
(`../prereg/PREREGISTRATION-main-v1.md`) uses it only to choose the design and states that it is "not part of the analysis"; anything
read off these rows is exploratory.

| | |
|---|---|
| plan | `pilot-v1`, plan id `2e5229198b34`, created 2026-10-01T12:13:21Z (08:13 EDT), seed 20261002 |
| design | 5 scenarios x 1 rep x hosts opus + fable x arms anchor, aa, shipped, sticky, sonnet = 45 sessions in 10 waves, `--parallel 5` |
| scenarios | go-wordsearch, py-bowling, rust-wordcount, slugify-bugfix, slugify-review |
| rows | 45 sessions, 360 turns, 1,634 requests, 40 pairs (`sessions.jsonl`, `turns.jsonl`, `requests.jsonl.gz`, `pairs.jsonl`, `summary.json`; same schema as `../data/`, see `../data/DATA-DICTIONARY.md`) |
| candidate build | `4caf463` (an earlier commit than the main campaign's `3aa2d1e`); same price table sha `9cb9b9134ab7fa08` |
| failures | none: every wave was accepted on attempt 1; no memory kill, cache audit clean, mechanism gates green (`summary.json`) |
| spend | $119.5476 ledger = $116.7088 sessions + $2.8388 preflight, against a $150 budget (`ledger.json`) |

Also here: `schedule.json`, `state.json`, `ledger.json`, `preflight.json`, `decisions.jsonl`, `plan.txt` (sanitized exactly like the main campaign files).

Not packaged: `pilot-1`, an earlier first screening run (directory created 2026-10-01 00:30 EDT, ledger $43.7159 over 9 entries, budget $150) that was superseded by pilot-2.
It exists only in the raw tree. Total pilot spend, both runs: $163.2635.

The preregistration quotes pilot figures (A/A noise SD, geometric-mean ratios per host). Which pilot run those came from is not stated there, so they are not re-derived here.
