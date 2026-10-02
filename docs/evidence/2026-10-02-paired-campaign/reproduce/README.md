# Reproducing the rows and the fit

Two levels, with different requirements:

1. **Re-extract the rows from the raw campaign tree** (only on the machine that ran it: the raw tree and the per-session event files are not in the repo).
2. **Re-fit the savings model from the published rows** (anyone with this repo; no raw tree, no API calls).

Nothing here calls a model API. Run heavy steps with `nice -n 10`.

## Build and environment recorded in the data

| item | value | where recorded |
|---|---|---|
| candidate build (`build_sha`) | `3aa2d1e0065d99f68dd6393097d988397515e2bf` (the preregistration commit) | every session row, `campaign/schedule.json` |
| candidate tree sha256 (`bundle_tree_sha`) | `e6ae68f57132c8ffcb953a4ea9c1b51ce1a4d9b87e3b4a598c14cc9f0280bd2b` | every session row |
| plan | `4f1a9b5bb7ec`, design `main-v1`, seed 20261002, 2 reps, 280 waves, 1,036 sessions | `campaign/schedule.json` |
| model ids | `claude-opus-5-5` (host), `claude-fable-5-1` (host), `claude-sonnet-5` (cheap model / control) | `host_model`, `served_models` |
| price table sha | `9cb9b9134ab7fa08` (first 16 hex of sha256 of `savings.DEFAULT_RATES`); equals the hash of the table in this checkout, verified 2026-10-02 | `price_table_sha` |
| provider module | `provider-anthropic` 1.0.0, git `9e2f20c9342253666d0bdb3dcf593a58456e72f9`, configured as `git+https://github.com/microsoft/amplifier-module-provider-anthropic@main` with `raw: true` | `provider_module`, `campaign_provider` |
| tools-prefix allowance | 32,100 tokens (`evals/paired/main-v1.yaml`, measured by preflight: 32,029-32,033) | `tools_prefix_allowance_tokens` |
| runtime (preflight manifests) | Amplifier `installed_commit` `62061032277869e7ec6b98c2f6d0b9aaa7799294`, amplifier-core 1.0.0, amplifier-foundation 1.0.0, Python 3.14.7, macOS-26.7-arm64 | raw `pf-*/manifest.json` (not published) |
| API key | one shared key for every session and arm; fingerprint `a375910513` (10-hex sha prefix); no per-arm keys (`key_env` is empty in the schedule) | `key_fingerprint` |
| nonce | one UUID per session at the start of the system prompt (`nonce_mode: per_session`) | `nonce` |
| harness | `evals/paired.py` at `dc1aa4e` or later; the code that ran the campaign was in the working tree and was committed as `dc1aa4e` after the campaign (see `../prereg/PROVENANCE.md`) | |

## Spend

| bucket | USD | source |
|---|---:|---|
| main-v1 ledger total | 3,527.2936 | `campaign/ledger.json` (hard stop $6,500) |
| of which accepted sessions (the 1,036 rows) | 3,418.1496 | sum of `cost_usd_provider` over `data/sessions.jsonl` = 3,418.1493 (rounding) |
| of which failed attempts, retried or reset | 103.9716 | `campaign/FAILURES.md` |
| of which preflights (2 runs: Oct 1 10:24 EDT $2.8389; Oct 2 09:21 EDT $2.3335) | 5.1724 | ledger keys `preflight#...` |
| pilot-2 | 119.5476 | `pilot/ledger.json` (116.7088 sessions + 2.8388 preflight; budget $150) |
| pilot-1 (not packaged) | 43.7159 | raw tree only |
| all pilots | 163.2635 | |
| **everything spent on this study that the tree records** | **3,690.5571** | |

Tools-normalized cost over the 1,036 sessions is $3,402.7774 (the normalization repricing the shared tools prefix is $15.37 in total, `data/summary.json`).

Wall clock: first session started 2026-10-01 10:24:54 EDT, last 2026-10-02 17:17:23 EDT, `campaign complete` 17:39:07 EDT (about 31 h).

## 1. Replay the rows from the raw tree

`evals/paired.py rows` reads `state.json` (accepted attempt of every wave), `schedule.json`, `preflight.json`, each session's `result.json` and
`events/` in the campaign tree, and the Amplifier session `events.jsonl` under `~/.amplifier/projects/<encoded workspace path>/sessions/`.
It writes `<out>/rows/`. To avoid overwriting the original rows, point it at a scratch directory that links the three input files
(the absolute run paths inside `state.json` resolve to the raw tree):

```bash
RAW=~/dev/afast-paired/main-v1
SCRATCH=$(mktemp -d)
for f in schedule.json state.json preflight.json ledger.json; do ln -s "$RAW/$f" "$SCRATCH/$f"; done
cd <repo checkout at dc1aa4e or later>
nice -n 10 python3 evals/paired.py rows --out "$SCRATCH"
for f in sessions turns pairs requests; do cmp "$SCRATCH/rows/$f.jsonl" "$RAW/rows/$f.jsonl" && echo "$f identical"; done
diff "$SCRATCH/rows/summary.json" "$RAW/rows/summary.json" && echo "summary identical"
```

Verified on 2026-10-02 with the committed harness: all four `.jsonl` files and `summary.json` are **byte-identical** to the rows produced during the
campaign (raw sha256 are in `../data/DATA-DICTIONARY.md`, last column). `package_evidence.py` then rewrites only path strings, so the published files
equal the raw ones except for `provider_module.path` / `git_root` in sessions rows.

To rebuild this directory from the raw tree: `CAMPAIGNS=~/dev/afast-paired python3 reproduce/package_evidence.py`, then
`python3 -m pytest tests/test_evidence_sanitized.py` (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` if a global pytest plugin fails to import).

## 2. Re-fit the model from the published rows

`evals/paired_model.py` needs only `<root>/rows/sessions.jsonl` and `pairs.jsonl`. Link the published files; the original run used the defaults
(seed 0, basis `normalized`, 2,000 summary bootstraps, 400 fit bootstraps, 4,000 prediction draws) and the numpy fallback engine:

```bash
E=docs/evidence/2026-10-02-paired-campaign
S=$(mktemp -d); mkdir "$S/rows"
ln -s "$PWD/$E/data/sessions.jsonl" "$PWD/$E/data/pairs.jsonl" "$S/rows/"
nice -n 10 python3 evals/paired_model.py all "$S" --engine fallback     # about 2 s; writes $S/model/
for f in summary.json model.json predictions.json MODEL.md; do cmp "$S/model/$f" "$E/model/$f" && echo "$f identical"; done
```

Verified on 2026-10-02: `summary.json`, `model.json`, `predictions.json` and `MODEL.md` regenerated from the **published** rows are byte-identical to the
files in `../model/` (which are byte-identical to the ones produced from the raw rows). With `statsmodels` installed the default `--engine auto` would pick
the MixedLM engine instead; pass `--engine fallback` to match.

Descriptive summaries only: `python3 evals/paired_model.py summarize "$S"`. Workload calculator: `... workload "$S" --mix mix.json --sessions 1000`.

## 3. Confirmatory analysis

`evals/paired_confirm.py` implements the confirmatory analysis and reads `<root>/rows/{sessions,pairs}.jsonl` plus
`<root>/model/{model,predictions}.json`, writing `<root>/confirm/`. The hypotheses, thresholds, split and decision
rule are the preregistered ones; the estimator (10,000 bootstrap resamples, seed 20261002, the pair-level quality
filter, which cells count as savings claims, and the verdict rule) is fixed in the script, which was written after
the data were collected (first committed in `c3ea41a`).

```bash
mkdir -p "$S/model"; cp "$E/model/model.json" "$E/model/predictions.json" "$S/model/"
nice -n 10 python3 evals/paired_confirm.py "$S"      # about 4 s; see `--help` for --out, --boot, --seed
cmp "$S/confirm/CONFIRM.md" "$E/confirm/CONFIRM.md" && echo "CONFIRM.md identical"
```

Verified on 2026-10-02: run on the **published** rows and model files, `paired_confirm.py` reproduces `confirm/CONFIRM.md`
byte for byte, and `confirm/confirm.json` is identical except for the `campaign` path field.
