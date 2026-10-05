# Paired cost-measurement campaign main-v1 (2026-10-01 to 2026-10-02)

Evidence package for a completed, preregistered campaign that measured what fast-decisions routing policies cost against a plain host-model
anchor. Everything here is sanitized (no home paths, keys, prompts or model responses; see "Sanitization"). Nothing in this directory was
produced by a new model call.

## What the campaign measured

* **Question:** the measured (not estimated) cost, and the quality, of each fast-decisions policy compared with a plain host model, on the same scripted
  multi-turn coding/knowledge session started from the same frozen workspace.
* **Design** (`prereg/PREREGISTRATION-main-v1.md`, `campaign/plan.txt`): 70 scenarios (polyglot 20, repos 16, mixed 20, knowledge 14), preregistered
  47 train / 23 test split, 2 repetitions, two host models (Opus 5.5, Fable 5.1), 280 waves, 1,036 sessions. Every arm of a scenario/rep/host starts
  together, in its own terminal, from one frozen workspace, with its own cache nonce so arms cannot warm each other's prompt cache.
* **Arms:** `anchor` (plain host, A0), `aa` (a second anchor on a seeded 20% subsample: the run-to-run noise floor), `shipped` (orch-default profile,
  per-request routing), `sticky` (model chosen once from the first prompt, never switched), `sonnet` (plain Sonnet, host-independent control).
* **Cost basis:** provider-priced tokens recomputed from a fixed price table, with the shared tools prefix repriced as a cache read ("tools-normalized",
  primary); the raw basis is stored alongside. Cache audit and mechanism gates are recorded per session.
* **Endpoints** (test split only): H1 (Fable: routing is cheaper), H2 (Opus: routing to Sonnet does not save), H3 (sticky costs no more than shipped),
  non-inferior quality; plus a prediction model fitted on train and validated on test. Decision rules are in the preregistration.
* **Status of the run:** all 280 waves completed; 1,036 sessions, 11,588 turns, 52,437 requests, 896 pairs (895 cost-valid). 49 wave attempts
  failed on infrastructure and were rerun; one session was killed by the memory watchdog and is cost-invalid (`campaign/FAILURES.md`).

## Results

Confirmatory numbers come from `confirm/CONFIRM.md` (`evals/paired_confirm.py`, test split, 23 scenarios, 10,000 scenario-cluster
bootstrap resamples, seed 20261002). Everything else is exploratory and labeled so.

**All four preregistered hypotheses are confirmed, under both readings of "non-inferior".**

| host | arm | cost ratio vs plain host (test) | 95% CI | verdict |
|---|---|---|---|---|
| Fable 5.1 | sticky (choose once, never switch) | 0.558 | 0.493 to 0.643 | H1 confirmed: 44% cheaper |
| Fable 5.1 | shipped (orch-default) | 0.629 | 0.555 to 0.715 | H1 confirmed: 37% cheaper |
| Opus 5.5 | sticky | 1.249 | 1.125 to 1.389 | H2 confirmed: no saving (25% dearer) |
| Opus 5.5 | shipped | 1.380 | 1.250 to 1.529 | H2 confirmed: no saving |
| Opus 5.5 | sonnet (control) | 1.433 | 1.253 to 1.640 | H2 confirmed: no saving |
| both | sticky / shipped | 0.862 (Fable), 0.917 (Opus) | upper 0.994, 0.991 | H3 confirmed: never switching is cheaper |

- **Quality:** turn-pass is non-inferior for every Fable savings claim (Fable sticky is closest to the -0.05 margin: lower bound -0.047).
  Exploratory caution: on the final hidden tests, routed Fable arms lost more scenarios the anchor passed than they won
  (shipped 7/1, sticky 6/1, sonnet 5/0; McNemar p 0.06-0.13, not significant).
- **Decision (preregistered rule):** on a Fable-class host, route to Sonnet with the choice made once at session start (`sticky`); on an
  Opus-class host, do not route to Sonnet.
- **Prediction model:** passes its preregistered check (90% PI coverage 0.960 log ratio, 0.935 dollars; test total $180.35 inside $63-$251).
  But its arm and task effects are shared across hosts, so do not use its per-host or per-task figures; use the empirical tables.
- **Savings per 1,000 sessions** (empirical, all splits, 90% range): Fable sticky $1,980 (1,577-2,368), shipped $1,754 (1,481-2,032),
  sonnet $2,090 (1,834-2,340); Opus sticky -$489, shipped -$588, sonnet -$1,096 (cost increases). By task type: `confirm/CONFIRM.md`.
- **Interim vs final:** Fable ratios were stable from pilot to final; the pilot overstated the Opus penalty (sticky 1.46 vs 1.25 final test) and
  the interim partial-train read understated it (1.11).
- **Noise floor:** A/A per-session SD of the log ratio about 0.07; Opus A/A 1.049 (1.007-1.093), small next to the effects.
- **Spend:** $3,527.29 main campaign (ledger), pilots $163.26.

## Contents

| path | what |
|---|---|
| `data/` | `sessions.jsonl` (1,036), `turns.jsonl` (11,588), `pairs.jsonl` (896), `requests.jsonl.gz` (52,437), `summary.json`; **`DATA-DICTIONARY.md`** documents every field and carries row counts and sha256 of each file |
| `campaign/` | `schedule.json`, `plan.txt`, `state.json`, `ledger.json`, `decisions.jsonl` (sticky decisions), `preflight.json`, `run.log`, `supervisor.log`; **`FAILURES.md`**: every failed/excluded/retried attempt grouped by cause, and the memory kill |
| `pilot/` | pilot-2 rows and run files (screening only, not analysed) and a note |
| `dashboard/index.html` | static snapshot of the campaign dashboard taken at completion (open in a browser; auto-refresh removed) |
| `prereg/` | the preregistration, the train/test split (`SPLIT.md`, `split.json`) and `PROVENANCE.md`: commits and the check that the preregistration precedes the first session |
| `model/` | derived: output of `evals/paired_model.py all` on `data/` (summaries, mixed-model fit, test predictions, `MODEL.md`) |
| `reproduce/` | `README.md` (commands, versions, price table, provider version, spend) and `package_evidence.py` (how this directory was built) |
| `SHA256SUMS` | sha256 of every file except this README |

## Key facts

* Preregistration commit `3aa2d1e` at 2026-10-01 10:18:42 EDT; the first session started 6 min 12 s later (10:24:54 EDT). The split was committed at 08:42:47 EDT the same day.
* Spend: main-v1 $3,527.29 (sessions $3,418.15, failed attempts $103.97, preflights $5.17); pilots $163.26. Details in `reproduce/README.md`.
* Rows are reproducible: re-extracting them with the committed harness gives byte-identical files, and the model re-fits byte-identically from the published rows.

## Sanitization

Rows are exactly what `evals/paired.py rows` wrote, except that the home directory prefix is replaced by `~` and campaign/pilot/repo roots by
`<campaign>`, `<pilot-2>`, `<repo>`. Message bodies were never stored in rows (only character counts). The harness's free-text failure reasons contained the
tail of agent terminal output; those tails are replaced by their length and a hash. The Forge daemon log and macOS power log were read for timestamps only and are not published.
`api_key` appears in `sessions.jsonl` only as the *name* of a provider config key; no key value is present, and sessions carry a 10-hex sha prefix fingerprint.
`tests/test_evidence_sanitized.py` fails if the home path, an API-key or bearer-token pattern, an api-key assignment with a value, prompt/response-text fields or unscrubbed terminal tails appear anywhere here.

## Known limits (stated up front)

* The harness that ran the campaign was uncommitted working-tree code, committed afterwards as `dc1aa4e` (`prereg/PROVENANCE.md`).
* The cause of 8 failed attempts was not recorded at the time and is inferred from timing (`campaign/FAILURES.md` section 4).
* One shared API key served every arm; cache isolation relies on per-session nonces plus the audit recorded in each row (no flagged sessions).
* Prompt text, scenario workspaces, per-session transcripts and event files are not published; scenario definitions live in `evals/paired/scenarios/main-v1/` in this repository.
