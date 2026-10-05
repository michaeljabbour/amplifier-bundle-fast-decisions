# Judge-benchmark technical report (LaTeX)

*Which Fast Model Should Make an Agent's Small Decisions? A Validated, Preregistered Benchmark of
Decision Judges.* Amplifier and Michael J. Jabbour, Microsoft, Office of the CTO. September 30, 2026.

This directory turns the judge-benchmark evidence
([`docs/evidence/2026-09-30-judge-benchmark/`](../../evidence/2026-09-30-judge-benchmark/README.md))
and its interactive report into a pedagogical technical report: [`judge-benchmark.pdf`](judge-benchmark.pdf).

## Build

```bash
make            # regenerate generated/ from the evidence, then latexmk -pdf -> judge-benchmark.pdf
make check      # geometry check of the built figures (check_figures.py, uses pdftotext -bbox)
make clean      # remove LaTeX intermediates, keep the PDF
make distclean  # also remove generated/ and the PDF
```

Needs Python 3 (standard library only) and TeX Live 2025 (`latexmk`, `pdflatex`, pgfplots, tcolorbox,
booktabs, xltabular, libertinus). No network access and no model calls.

## Where the numbers come from

Every number in the text, tables and figures is produced by `build_assets.py`, which reads **only** the
committed evidence files:

| Evidence file | Used for |
|---|---|
| `dev/summary.json`, `holdout/summary.json` | per-judge metrics (majority over repetitions), per-repetition ranges, latency, cost, calibration, failure classes, pairwise contrasts, decision rules 1-4, threshold sweep |
| `dev/requests.jsonl`, `holdout/requests.jsonl` | pooled p50/p95 (nearest rank), per-case answer cards, the worked example `cua-18` |
| `dev/run.json`, `holdout/run.json` | commits, spend, host load, arm specs and prices, Decisions API probe (HTTP 403) |
| `dev/manifest.json`, `holdout/manifest.json` | case text, labels and tags |
| `firstpass-repro/summary.json`, `requests.jsonl`, `run.json` | first-pass replay and seven-run repeatability |
| `label-audit/agreement.json` | blind label audit (kappa, adjudications) |
| `latency/latency_summary.json` | latency anatomy, cold starts, concurrency, round trips |
| `changes.json` | the claim-by-claim first-pass comparison (rendered verbatim) |
| `../2026-10-01-trace-judge-benchmark/{dev,holdout}/*.json[l]`, `holdout/rule2_useful.json`, `holdout/trace_analysis.json` | follow-up on real decisions (Section 10): table, figure, caveats |
| `evals/judge_bench/traces/{PREREGISTRATION.md,labels_final.json,pool.json,FINDING-*.md}` | trace-case design, labels and kappa (recomputed), usefulness rule, state-budget numbers |
| `../2026-10-01-caching/results.json`, `README.md` | follow-up on caching (Section 10): same-cell contrast, price x volume, rebuild shares, warm/cold ranges; the proposal's figures |

It writes:

- `generated/numbers.tex`: one `\newcommand` per number used in prose (for example `\JevHoldAccK`,
  `\LunaHoldRAccPHolm`, `\ITwoHoldBefore`). Naming: `<Judge><Split><Metric>`, split `Dev` or `Hold`.
- `generated/tables/*.tex`: booktabs tables `\input` by the sections.
- `generated/data/*.dat`: data files read by the pgfplots figures in `figures/`.

The output is deterministic (no clock, randomness or network). The script re-scores every stored
answer with its own copy of the bundle's read-shortcut gate and asserts that the result matches
`summary.json` for every arm and repetition before it writes anything. Scatter-plot label positions come
from a deterministic backtracking placer in the script, using the text font's TFM metrics. Every
label must keep clear of every marker and every other label, stay inside the axis, and be strictly
nearer its own marker than any other (a displaced label gets a leader line); if any label cannot be
placed this way the script exits non-zero and the build stops. Placements are written to
`generated/labels/*.tex` and recorded in `generated/data/labels-*.tsv`. `check_figures.py` then
re-checks the same rules on the built PDF from the text positions pdftotext reports, and checks that
the Fig. 7 legends sit above their axes.

The PR number and commit of the post-study changes (PR #56, `180f919`) are named constants at the top
of `build_assets.py` (`SINCE_PR`, `SINCE_COMMIT`); they are not in the evidence JSON.

A few follow-up facts exist only as prose in committed Markdown (the state-budget numbers, the smoke-run
erratum, the proposed caching experiment). `build_assets.py` reads them with anchored patterns and stops
the build if the text no longer matches. Ratios from the caching study are rounded half-up from the
values stored in `results.json` (1.305 -> 1.31), as that study's README reports them.

Policy constants that are not stored in the evidence JSON (the gate's 0.90 probability, 0.20 margin and
0.75 computer-use bar, from `evals/judge_bench/scoring.py`) and the illustrative traffic volume for the
cost projection (100,000 decisions per day) are named constants at the top of `build_assets.py`.

## Layout

```
main.tex                 preamble, title page, \input of sections
sections/                00-abstract ... 11-reproducibility, appendix-a/b/c
figures/                 pgfplots figures reading generated/data
generated/               numbers.tex, tables/, data/, labels/  (written by build_assets.py)
build_assets.py          evidence -> generated/ (numbers, tables, data, scatter labels)
check_figures.py         post-build geometry check of labels and legends
Makefile                 make = assets + pdf; make clean
judge-benchmark.pdf      the built report
```
