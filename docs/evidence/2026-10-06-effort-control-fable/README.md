# effort-control-fable-v1 follow-up campaign (2026-10-06)

Evidence package for a completed, preregistered follow-up to the main-v1 paired campaign (`../2026-10-02-paired-campaign/`) and the Sonnet effort follow-up
(`../2026-10-05-effort-control/`). Sanitized: no home paths, keys, prompts or model responses. Nothing here was produced by a new model call.

**Question (round-2 peer review):** does plain Fable 5.1 at reasoning effort `medium` cost less than at the provider default?
**Answer:** 0.860x (95% CI 0.833-0.885; 23 test scenarios x 2 reps = 46 pairs, 45 cost-valid; HF supported), turn-pass delta +0.033 (CI -0.002 to +0.080, non-inferior);
final pass 45 both / 1 medium-only / 0 default-only. Exploratory, non-concurrent: vs main-v1 Fable-host sticky 1.546 (1.343-1.759), vs main-v1 Fable anchor 0.829 (0.790-0.866).
Plain-language write-up: [`RESULT.md`](RESULT.md); the two flagged sessions: [`FLAGS.md`](FLAGS.md). Spend $421.71.

## Contents

| path | what |
|---|---|
| `summary.json` | machine-readable headline rows (`description`, `rows[{label, n_pairs, gm_ratio, ci95}]`), the quality endpoint and `HF_supported` |
| `RESULT.md` / `FLAGS.md` | result in plain language / the cache-audit flag and the memory kill, with sensitivities |
| `data/` | `sessions.jsonl` (92), `turns.jsonl` (1,032), `pairs.jsonl` (46), `requests.jsonl.gz` (4,032), `summary.json` (counts and audit lists), `FILES.json`, `DATA-DICTIONARY.md` |
| `campaign/` | `schedule.json`, `plan.txt`, `state.json`, `ledger.json`, `preflight.json`, `run.log`, the memory-kill marker |
| `result/` | `effort-fable-result.json` (analysis output of `evals/paired_effort.py --design fable`) and `sensitivity.json` (as-run vs strict variants, recomputed from `data/pairs.jsonl`) |
| `prereg/` | the preregistration and `PROVENANCE.md` (commit 249941c at 08:33:19 -04:00 precedes schedule creation 12:33:29Z and the first session; the disclosed scratch preflight) |
| `reproduce/package_evidence.py` | rebuilds this directory from the raw campaign tree (only on the machine that ran it) |
| `SHA256SUMS` | sha256 of every file except `README.md` and itself |

## Reproducing the numbers

```
nice -n 10 python3 evals/paired_effort.py --design fable --rows <this>/data \
    --main-sessions docs/evidence/2026-10-02-paired-campaign/data/sessions.jsonl
```

`data/` holds `pairs.jsonl` and `sessions.jsonl`, the two inputs the script reads; the output matches `result/effort-fable-result.json`. No API calls.

## Honest notes

* Preregistration timing: the preregistration commit precedes the schedule (by 10 s) and the first session (by 7 min 29 s). The analysis-script commit followed the preregistration commit by 7 s,
  also before the schedule. A scratch feasibility preflight ($1.73, mechanism only) ran before the commit and is disclosed in `prereg/PROVENANCE.md`.
* The pair rows copied only the arm's cache-audit flag; the flagged session was the anchor, so its pair stayed in the as-run result. `FLAGS.md` gives both results; the harness is fixed for future runs.
* The exploratory main-v1 comparisons are not concurrent; sessions ran on different dates.
* Sanitization: home prefix -> `~`, campaign root -> `<campaign>`; free-text failure tails (none occurred) would be replaced by length + hash; keys are never recorded
  (`tests/test_evidence_sanitized_effort_fable.py` guards this).
