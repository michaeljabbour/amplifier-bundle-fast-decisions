# `make` regenerates every number from the committed evidence, then builds the supplement and the main paper
# (each twice, so cross-document references resolve). `make FINAL=1` requires every evidence package.
PYTHON ?= python3
LATEXMK ?= latexmk
NICE ?= nice -n 10
MAIN := decision-model-fit-v4
SUPP := decision-model-fit-v4-supplement
EVIDENCE := ../../evidence/2026-10-02-paired-campaign ../../evidence/2026-10-05-effort-control ../../evidence/2026-10-06-effort-control-fable \
	../../evidence/2026-10-v3-offline ../../evidence/2026-10-05-defaults-replay ../../evidence/2026-10-06-holdout-v3 \
	../../evidence/2026-10-06-openai-decisions
FINAL ?= 0
ifeq ($(FINAL),1)
.PHONY: generated/numbers.tex
endif
LTX = $(NICE) $(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error

.PHONY: all assets pdf check clean distclean

all: $(MAIN).pdf

# Figure geometry, row identity, page budget (main body <= 10 pages) and no file paths in either PDF.
check: $(MAIN).pdf
	$(NICE) $(PYTHON) check_figures.py

assets: generated/numbers.tex

generated/numbers.tex: build_assets.py labelplacer.py jb_import.py $(shell find $(EVIDENCE) -type f) \
		../../design/parallel-measurement-mode.md ../../design/pilot-20261001/step1_cache_probe.json
	FINAL=$(FINAL) $(NICE) $(PYTHON) build_assets.py

pdf: $(MAIN).pdf

$(MAIN).pdf: generated/numbers.tex main.tex supp.tex preamble.tex $(wildcard sections/*.tex) $(wildcard supp/*.tex) $(wildcard figures/*.tex)
	$(LTX) -jobname=$(SUPP) supp.tex
	$(LTX) -jobname=$(MAIN) main.tex
	$(LTX) -g -jobname=$(SUPP) supp.tex
	$(LTX) -g -jobname=$(MAIN) main.tex

# Remove build intermediates; keep both PDFs.
clean:
	$(LATEXMK) -c -jobname=$(MAIN) main.tex
	$(LATEXMK) -c -jobname=$(SUPP) supp.tex
	rm -f *.bbl *.run.xml *.xdv
	rm -rf __pycache__ generated/src

distclean: clean
	rm -rf generated $(MAIN).pdf $(SUPP).pdf
