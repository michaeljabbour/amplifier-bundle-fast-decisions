# Judge-benchmark technical report (LaTeX)

*Which Fast Model Should Make an Agent's Small Decisions? A Validated, Preregistered Benchmark of
Decision Judges.* Amplifier and Michael J. Jabbour, Microsoft, Office of the CTO. September 30, 2026.

This directory turns the judge-benchmark evidence
([`docs/evidence/2026-09-30-judge-benchmark/`](../../evidence/2026-09-30-judge-benchmark/README.md))
and its interactive report into a pedagogical technical report: [`judge-benchmark.pdf`](judge-benchmark.pdf).

## Build

```bash
make            # regenerate generated/ from the evidence, then latexmk -pdf -> judge-benchmark.pdf
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

It writes:

- `generated/numbers.tex`: one `\newcommand` per number used in prose (for example `\JevHoldAccK`,
  `\LunaHoldRAccPHolm`, `\ITwoHoldBefore`). Naming: `<Judge><Split><Metric>`, split `Dev` or `Hold`.
- `generated/tables/*.tex`: booktabs tables `\input` by the sections.
- `generated/data/*.dat`: data files read by the pgfplots figures in `figures/`.

The output is deterministic (no clock, randomness or network). The script re-scores every stored
answer with its own copy of the bundle's read-shortcut gate and asserts that the result matches
`summary.json` for every arm and repetition before it writes anything. Scatter-plot label positions come
from a small deterministic placer in the script; they never change a plotted value.

Policy constants that are not stored in the evidence JSON (the gate's 0.90 probability, 0.20 margin and
0.75 computer-use bar, from `evals/judge_bench/scoring.py`) and the illustrative traffic volume for the
cost projection (100,000 decisions per day) are named constants at the top of `build_assets.py`.

## Layout

```
main.tex                 preamble, title page, \input of sections
sections/                00-abstract ... 11-reproducibility, appendix-a/b/c
figures/                 pgfplots figures reading generated/data
generated/               numbers.tex, tables/, data/  (written by build_assets.py)
build_assets.py          evidence -> generated/
Makefile                 make = assets + pdf; make clean
judge-benchmark.pdf      the built report
```
