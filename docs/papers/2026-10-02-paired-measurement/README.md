# Measured, not estimated: what routing an agent to a cheaper model actually costs

Technical report on the preregistered paired multi-turn measurement campaign main-v1 (2026-10-01 to 2026-10-02).
Amplifier and Michael J. Jabbour, Microsoft, Office of the CTO. Output: [`paired-measurement.pdf`](paired-measurement.pdf).

The bundle's shipped defaults (price gate, one decision per session) implement these recommendations; see [docs/CONFIGURATION.md](../../CONFIGURATION.md) and the [offline replay](../../evidence/2026-10-05-defaults-replay/REPLAY.md).

## Build

```bash
make            # build_assets.py (generated/), then latexmk -pdf; both under nice -n 10
make check      # geometry checks on the built PDF (check_figures.py; needs poppler)
make clean      # remove LaTeX intermediates, keep the PDF
make distclean  # also remove generated/ and the PDF
```

Needs Python 3 with numpy (build_assets.py reuses the committed estimator in evals/paired_confirm.py and evals/paired_model.py), TeX Live 2025 (latexmk, pdflatex, pgfplots, tcolorbox, libertinus) and
`git` with the `origin/main` ref fetched (the earlier caching survey and the trace judge benchmark's Jev cost are read from it). No network
access beyond that ref, and no model calls.

## Where the numbers come from

`build_assets.py` reads only committed files and writes every number in the text (`generated/numbers.tex`), every
table (`generated/tables/`), every plotted datum (`generated/data/`) and every scatter-label position
(`generated/labels/`). No number is typed by hand.

| Source | Used for |
|---|---|
| `docs/evidence/2026-10-02-paired-campaign/confirm/confirm.json` | all confirmatory results (H1-H3, quality, model check, decision) and the exploratory tables it carries (pass rates, A/A, interim vs final, savings per 1,000, raw basis, deviations) |
| `.../data/{sessions,pairs}.jsonl`, `requests.jsonl.gz`, `summary.json` | counts, scenario list, cost composition (per-class prices recovered from the request rows by exact least squares and checked against the probe's price table), sticky decisions, memory kill |
| `.../model/{summary,predictions}.json` | slices by gap pattern and length, switching and rebuild shares, predicted totals for the model figure |
| `.../campaign/{state,ledger}.json`, `decisions.jsonl`, `FAILURES.md`, `supervisor.log`, `plan.txt` | attempts, failures by cause (FAILURES.md section 7 table, cross-checked against state.json), spend, timing |
| `.../prereg/*`, `reproduce/README.md`, `pilot/` | split, thresholds, provenance, pilot facts, pilot-1 spend |
| `docs/design/parallel-measurement-mode.md` | power table |
| `docs/design/pilot-20261001/step1_cache_probe.json` | the cache-semantics probe table and price table |
| `evals/paired/README.md`, `evals/paired/main-v1.yaml`, `evals/paired/scenarios/main-v1/` | memory-guard facts, A/A subsample fraction, scenario families |
| `git show origin/main:docs/evidence/2026-10-01-caching/results.json` | the earlier survey's same-cell contrast (motivation) |

Facts that exist only as prose in committed Markdown are read with anchored patterns; the build stops if the text
no longer matches. Ratios are rounded half-up from the stored values.

## Checks

* `labelplacer.py` places the scatter labels deterministically from the font's TFM metrics; the build stops if a
  label cannot be placed inside the axis, clear of every marker and label, and strictly nearest its own marker.
* `check_figures.py` re-checks on the built PDF: no overlapping text on any page; every scatter label nearest its own
  marker; every legend above its plot.

## Layout

```
main.tex            preamble, title page, \input of sections
sections/           00-abstract ... 10-reproducibility, appendix-a-glossary, appendix-b-tables
figures/            pgfplots/TikZ figures reading generated/data
build_assets.py     evidence -> generated/
labelplacer.py      scatter label placer (shared design with the judge-benchmark report)
check_figures.py    post-build geometry checks
Makefile
paired-measurement.pdf
```

Two evidence files are matched by a global `*.log` ignore rule and must be committed with `git add -f`:
`campaign/run.log` and `campaign/supervisor.log` (build_assets.py reads `supervisor.log`).

## Part I sources (judge studies) and optional Clef data

`jb_import.py` (called by `build_assets.py`) runs `git archive origin/main` for the judge-benchmark,
trace-benchmark and caching-survey evidence, `evals/judge_bench/` and that branch's judge-benchmark paper code, extracts
them into `generated/src/` (gitignored, removed by `make clean`), runs that paper's own `build_assets.py` on the
extracted evidence, and copies its numbers, tables, data, labels and path-rewritten figure sources into `generated/jb/`.
The build therefore needs the `origin/main` ref. The four bundle fixes are read from commits `a15c439`
and `1f3b0e4` (history of this branch).

Cloudflare Clef and Clef-Flash (post-hoc arms) are read with `git show origin/main:docs/evidence/2026-10-04-clef-judges/...`
(summary, run, requests and rule-2 files for dev, holdout, trace-dev and trace-holdout) plus `evals/judges.yaml` for their prices,
so a clean clone builds without any sibling checkout.

## Review record

The external reviews (reconstructed from the authors' response), the verification of the round-1 points and its
scripts are in [`docs/reviews/2026-10-paired-measurement/`](../../reviews/2026-10-paired-measurement/). The responses
are Appendix C of the report.
