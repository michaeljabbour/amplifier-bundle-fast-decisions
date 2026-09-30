# `make` regenerates every number from the evidence files, then builds the PDF.
PYTHON ?= python3
LATEXMK ?= latexmk
PDF := judge-benchmark.pdf
EVIDENCE := ../../evidence/2026-09-30-judge-benchmark

.PHONY: all assets pdf clean distclean

all: $(PDF)

assets: generated/numbers.tex

generated/numbers.tex: build_assets.py $(shell find $(EVIDENCE) -name '*.json' -o -name '*.jsonl')
	$(PYTHON) build_assets.py

pdf: $(PDF)

$(PDF): generated/numbers.tex main.tex $(wildcard sections/*.tex) $(wildcard figures/*.tex)
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -jobname=judge-benchmark main.tex

# Remove build intermediates; keep the PDF.
clean:
	$(LATEXMK) -c -jobname=judge-benchmark main.tex
	rm -f judge-benchmark.bbl judge-benchmark.run.xml judge-benchmark.xdv

# Also remove generated assets and the PDF.
distclean: clean
	rm -rf generated $(PDF)
