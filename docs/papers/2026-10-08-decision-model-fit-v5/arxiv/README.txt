arXiv edition of "Where a Decision Model Fits in an Agent Harness" (technical report v5.1, October 8, 2026)

Contents of this directory
  arxiv-source.tar.gz              upload this file (flat TeX source: main.tex, main.bbl, plotted data and label files)
  decision-model-fit-v5-arxiv.pdf  the PDF this source compiles to (130 pages: main text, then appendices A-I)
  abstract.txt                     ASCII abstract for the metadata form (no "Abstract" prefix)
  metadata.txt                     title, authors, comments, categories, license
  source/                          the unpacked tarball, for inspection

Upload steps
  1. Rebuild from the paper directory: `make arxiv` (regenerates the source, then test-compiles the tarball alone
     with pdflatex three times, as arXiv does, and fails on any error or undefined reference).
  2. Log in to arxiv.org with an account endorsed for cs.SE (request endorsement first if needed).
  3. Start a new submission; choose the license in metadata.txt only after Microsoft legal has confirmed it
     (the choice is irrevocable).
  4. Upload arxiv-source.tar.gz and select PDFLaTeX as the processor. arXiv compiles main.tex using main.bbl
     (no .bib is needed); the shipped PDF here is exactly that clean compile.
  5. Paste the metadata from metadata.txt and abstract.txt. Authors: Michael J. Jabbour and David Koleczek only;
     arXiv does not allow AI tools as authors. The paper's Statements section carries the AI-use disclosure.
  6. Check the compiled preview: page count, figures, references, appendix cross-references.
  7. Submit before 14:00 US Eastern for same-day announcement; check the HTML rendering after announcement.

Before submitting (decisions for the lead; not changed by the build)
  - License: CC BY 4.0 is recommended but pending Microsoft legal review; the arXiv choice is irrevocable.
  - ORCID iDs: link each author's ORCID to their arXiv profile (no source change needed).
  - Author consent: both authors must confirm the author list, affiliation and the competing-interests statement.
  - Endorsement: the submitting account needs cs.SE endorsement (institutional email or an endorser).
  - Authorship: the two review PDFs list Amplifier as an author; arXiv forbids AI authors, so this edition lists
    only Michael J. Jabbour and David Koleczek and discloses Amplifier's role in the AI-use statement.
  - Data and code: the statement cites git tag report-v5.1; create and push that tag before submitting.

Notes
  - Figures are pgfplots drawn at compile time from the shipped data files; there are no image files.
  - All fonts are Type 1 (Libertinus, Bera Mono) from TeX Live 2025; no Type 3 fonts.
  - The review editions (main paper + separate supplement PDF) are built by `make FINAL=1`; arXiv does not
    accept a separate supplement, so this edition appends it as appendices.
