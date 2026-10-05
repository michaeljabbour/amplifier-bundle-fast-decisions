# effort-control-v1 follow-up campaign (2026-10-05)

Evidence package for a completed, preregistered follow-up to the main-v1 paired campaign (`../2026-10-02-paired-campaign/`). Sanitized: no home paths, keys,
prompts or model responses. Nothing here was produced by a new model call.

**Question:** how much of main-v1's sticky-on-Sonnet saving is the reasoning-effort setting (`medium`) alone?
**Answer:** plain Sonnet at medium effort costs 0.821x plain Sonnet at default effort (95% CI 0.781-0.861; 23 test scenarios x 2 reps = 46 pairs; HE supported),
with turn-pass delta -0.003 (CI -0.026 to 0.021, non-inferior). Exploratory, non-concurrent: medium vs main-v1 sticky-on-Sonnet 0.958 (0.913-0.999, 22 scenarios).
Plain-language write-up: [`RESULT.md`](RESULT.md). Spend $250.13.

## Contents

| path | what |
|---|---|
| `summary.json` | machine-readable headline rows (`description`, `rows[{label, n_pairs, gm_ratio, ci95}]`) plus the quality endpoint |
| `RESULT.md` | result in plain language |
| `data/` | `sessions.jsonl` (92), `turns.jsonl` (1,032), `pairs.jsonl` (46), `requests.jsonl.gz` (5,188), `summary.json` (counts and audit lists), `FILES.json` (checksums), `DATA-DICTIONARY.md` (pointer to main-v1's) |
| `campaign/` | `schedule.json`, `plan.txt`, `state.json`, `ledger.json`, `preflight.json`, `run.log` |
| `result/effort-result.json` | the analysis output of `evals/paired_effort.py` (HE cost and quality endpoints, exploratory comparison) |
| `prereg/` | the preregistration and `PROVENANCE.md` (commit time vs first session, with caveats) |
| `reproduce/package_evidence.py` | rebuilds this directory from the raw campaign tree (only on the machine that ran it) |
| `SHA256SUMS` | sha256 of every file except `README.md` and itself |

## Reproducing the numbers

```
nice -n 10 python3 evals/paired_effort.py --rows <this>/data \
    --main-sessions docs/evidence/2026-10-02-paired-campaign/data/sessions.jsonl
```

`data/` holds `pairs.jsonl` and `sessions.jsonl`, the two inputs `paired_effort.py` reads. The output matches `result/effort-result.json`
(the exploratory ratio 0.9579543725453573 was re-derived from the published rows). No API calls.

## Honest notes

* Preregistration timing: the schedule was created 6 min 43 s before the preregistration commit, and the first analysed session started 16 s after it; see `prereg/PROVENANCE.md`.
* Exploratory comparison: sessions ran on different dates from main-v1; the CI upper bound 0.999 is essentially at 1.0.
* Sanitization: home prefix -> `~`, campaign root -> `<campaign>`; no failures occurred so no terminal tails exist; keys are never recorded
  (`tests/test_evidence_sanitized_effort.py` guards this).
