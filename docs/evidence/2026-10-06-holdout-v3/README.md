# holdout-v3 (S1), the v3 core study (2026-10-05/06)

Evidence package for the completed, preregistered S1 campaign: 60 never-run scenarios x 2 reps x Fable 5.1 / Opus 5.5, 1,224 sessions in 240 waves. Sanitized: no home paths, keys, prompts or model
responses. Nothing here was produced by a new model call. Spend $4,975.51 (ledger).

**Headline:** the shipped-bundle routing (rule R*, strong medium) costs 0.581x plain Fable (95% CI 0.542-0.625) at turn-pass -0.013 (-0.028 to +0.002): H1 supported. The decision model is equivalent to the rule (H2: ship R*).
No overhead on Opus (H3 0.999). Medium effort on Opus is not shown to save (H4, 0.992, upper bound 1.009). Routing Opus work to Sonnet costs 1.255x (H5). Live = predicted (H6, 1.014). Review + explain are not shown
non-inferior (H7, lower bound -0.063): ship `keep_on_host: [review, explain]`. Plain-language write-up: [`RESULT.md`](RESULT.md); flags: [`FLAGS.md`](FLAGS.md); operations: [`FAILURES.md`](FAILURES.md).

## Contents

| path | what |
|---|---|
| `s1_result.json` | the preregistered analysis output (schema `fast-decisions-v3-s1-result/v1`): `hypotheses.{H1..H7,H3b}` (`estimate`, `p_holm`, `supported`; `hypotheses.H2.decision`), `freeze.{fable,opus}` (`chosen`, `selected_on_holdout`, `table[]`), `health`, `regret`, `noise_floor`. Same file as `result/s1_result.json` |
| `RESULT.md` / `FLAGS.md` / `FAILURES.md` | result in plain language / the three flag groups and how each was handled / operational failures and deviations |
| `data/` | `sessions.jsonl` (1,224), `turns.jsonl` (12,856), `pairs.jsonl` (1,104), `requests.jsonl.gz` (49,254), `summary.json`, `FILES.json`, `DATA-DICTIONARY.md` |
| `campaign/` | `schedule.json`, `plan.txt`, `state.json`, `ledger.json`, `preflight.json`, `run.log`, `supervisor.log` (the logs are force-added: `*.log` is git-ignored) |
| `prereg/` | the preregistration, `PROVENANCE.md` (commit 6ea0fd3 at 2026-10-05T21:28:41-04:00 precedes the schedule by 19.7 s and the first session by 58.9 s; frozen inputs unchanged), the freeze checklist |
| `result/` | `s1_result.json` and two exploratory robustness reruns (`robustness-drop_bleach`, `robustness-drop_bleach_and_black_pipeline`) |
| `reproduce/package_evidence.py` | rebuilds this directory from the raw campaign tree (only on the machine that ran it) |
| `SHA256SUMS` | sha256 of every file except `README.md` and itself |

## Reproducing the numbers

```
nice -n 10 python3 evals/v3/s1_analysis.py --sessions docs/evidence/2026-10-06-holdout-v3/data/sessions.jsonl \
    --out /tmp/s1 --resamples 10000 --seed 20261005
cmp /tmp/s1/s1_result.json docs/evidence/2026-10-06-holdout-v3/s1_result.json
```

## Honest notes

* The preregistered stop rules were not met in the letter: the budget cap was raised 5,000 -> 6,300 mid-run, mechanism-gate failures are detected at row extraction and so did not stop the run, and 36% of wave attempts
  failed on infrastructure (a Forge outage). See `FAILURES.md` and `FLAGS.md`; the preregistered analysis was applied as written and a robustness rerun without the affected scenarios changes no verdict.
* The Fable frozen configuration was selected on the holdout and must replicate in S2 before it ships. The Opus host keeps its current default.
* Preregistration timing rests on git commit timestamps.
