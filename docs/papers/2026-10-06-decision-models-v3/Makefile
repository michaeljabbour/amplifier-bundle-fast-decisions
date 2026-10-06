# `make` regenerates every number from the evidence files, then builds the PDF (both under nice).
# `make FINAL=1` requires the S1 result (docs/evidence/2026-10-06-holdout-v3/) and fails without it.
PYTHON ?= python3
LATEXMK ?= latexmk
NICE ?= nice -n 10
JOB := decision-models-v3
PDF := $(JOB).pdf
EVIDENCE := ../../evidence/2026-10-02-paired-campaign ../../evidence/2026-10-05-effort-control ../../evidence/2026-10-06-effort-control-fable \
	../../evidence/2026-10-v3-offline ../../evidence/2026-10-05-defaults-replay $(wildcard ../../evidence/2026-10-06-holdout-v3)
FINAL ?= 0
ifeq ($(FINAL),1)
.PHONY: generated/numbers.tex
endif

.PHONY: all assets pdf check clean distclean

all: $(PDF)

# Geometry check of the built figures (labels vs markers, legends vs plot areas, overlapping text).
check: $(PDF)
	$(NICE) $(PYTHON) check_figures.py

assets: generated/numbers.tex

generated/numbers.tex: build_assets.py labelplacer.py jb_import.py $(shell find $(EVIDENCE) -type f) \
		../../design/parallel-measurement-mode.md ../../design/pilot-20261001/step1_cache_probe.json
	FINAL=$(FINAL) $(NICE) $(PYTHON) build_assets.py

pdf: $(PDF)

$(PDF): generated/numbers.tex main.tex $(wildcard sections/*.tex) $(wildcard figures/*.tex)
	$(NICE) $(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -jobname=$(JOB) main.tex

# Remove build intermediates; keep the PDF.
clean:
	$(LATEXMK) -c -jobname=$(JOB) main.tex
	rm -f $(JOB).bbl $(JOB).run.xml $(JOB).xdv
	rm -rf __pycache__ generated/src

# Also remove generated assets and the PDF.
distclean: clean
	rm -rf generated $(PDF)
