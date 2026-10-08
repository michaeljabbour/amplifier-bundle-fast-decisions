# Publication-conformance check: "Where a Decision Model Fits in an Agent Harness" (v5.1)

Independent, read-only check against `/tmp/pub-standards-checklist.md` (arXiv rules, plus the Stanford/SLAC-STI/OSTI conventions that still apply).
Checked 2026-10-08 against the uncommitted working tree in `~/dev/fd-v3/docs/papers/2026-10-08-decision-model-fit-v5/`.
Nothing in the repository was edited; the `git status` count (21 entries) is unchanged. All scratch output is in `/tmp` (renders in `/tmp/pub-conf-render/`).

Decision applied (as instructed): SLAC/DOE-specific items (DOE acknowledgment, SLAC report number or affiliation, DOE disclaimer, LDRD, S&T risk-matrix review) are **N/A**. A word-boundary scan of all three PDFs and the arXiv source found no DOE, SLAC, OSTI, LDRD, Stanford or DE-AC02 text, so nothing was added without a basis.

Status key: Pass, Partial, Fail, N-A. "Flagged" marks the item you asked me to record.

## Verdict

The arXiv edition is **technically ready to build and upload**.
- The tarball compiles clean from an empty directory.
- The abstract is compliant and identical everywhere.
- Fonts are clean.
- The source has no hidden files, comments or absolute paths.

It is **not yet ready to submit** because of four blockers:
1. The public-code statement points at a commit that does not contain this paper's build.
2. The license choice is still pending.
3. Two metadata facts are wrong or unconfirmed.
4. The review PDFs name "Amplifier" as an author.

## 1. Abstract

| # | Item | Level | Status | Evidence | Exact fix |
|---|---|---|---|---|---|
| A1 | Metadata abstract at most 1,920 characters | MUST | Pass | `arxiv/abstract.txt`: 1,513 characters stripped (1,514 bytes with the trailing newline). `check_abstract.py` reports "234 words, 1513 characters (limits 250 / 1920) ... abstract OK". `metadata.txt` states 1513. | None. |
| A2 | At most 250 words | SHOULD | Pass | 234 words (independent count, same result). | None. |
| A3 | Plain ASCII, no TeX characters | MUST | Pass | 0 non-ASCII or control characters. 0 occurrences of `\ { } ~ ^ _`. 0 internal newlines (one line, one paragraph). 0 double spaces. | None. |
| A4 | Does not start with "Abstract" | MUST | Pass | `abstract.txt` begins "AI coding agents make many small decisions...". The PDFs' run-in "Abstract." label is typeset, not in the metadata. | None. |
| A5 | No LaTeX, macros or citations | MUST/SHOULD | Pass | No `\cite`, no "[n]", no "et al". Bracket tags such as "[preregistered; challenger post hoc]" are plain text. There is exactly one `$` ("$18.41"), so MathJax cannot pair it into math today. | Optional hardening: write "USD 18.41" in `abstract.txt` so a later edit cannot accidentally create a `$...$` pair. |
| A6 | No undefined acronyms | SHOULD | Partial | The only acronym is "AI". "Jev" is defined in the abstract. "Fable" and "Opus" (host models) and "host" are used without a gloss, so a reader of the arXiv listing alone cannot tell what they are. | Add a few words in `sections/abstract-body.tex`, e.g. "on the Fable host model ... 1.255x on the Opus host model". Re-run `make arxiv` and `check_abstract.py`. |
| A7 | Identical across main PDF, supplement PDF, `abstract.txt` and arXiv PDF | SHOULD | Pass | Normalised text comparison (pdftotext p.1, Abstract. through Keywords:) is identical for all three PDFs vs `abstract.txt`. The only differences are by-design ASCII transliterations: x for ×, - for en dash, "%" without the thin space, straight apostrophes. | None. |
| A8 | No proprietary or sensitive content | SHOULD | Pass | Only third-party product names and aggregate numbers. No internal Microsoft model names or customer data. | None. |

## 2. Title, authors, affiliation, front matter

| # | Item | Level | Status | Evidence | Exact fix |
|---|---|---|---|---|---|
| B1 | Title: not all caps, ASCII, no macros | MUST | Pass | "Where a Decision Model Fits in an Agent Harness" in `metadata.txt`, the arXiv PDF and the PDF `/Title`. | None. |
| B2 | Metadata authors as `Firstname Lastname`, all listed, affiliation in parentheses | MUST | Pass | `Michael J. Jabbour (1), David Koleczek (1) ((1) Microsoft, Office of the CTO, Redmond, WA, USA)`. | None. |
| B3 | Affiliation details are real and current | MUST | Partial | "Redmond, WA, USA" appears only in `make_arxiv.py` and `metadata.txt`. It is absent from every PDF front page and from the rest of the repository. Git author emails are gmail, so the submitter's arXiv account email also needs to support the Microsoft affiliation (arXiv: "physical presence, funding, e-mail address"). | Authors confirm the city, or drop it (arXiv allows city and country at most). Edit the `write_metadata()` template in `make_arxiv.py`. Register the arXiv account with an institutional email or confirmed endorsement. |
| B4a | No AI tool as author, arXiv edition | MUST | Pass | arXiv PDF byline lists two people. `pdfauthor` is "Michael J. Jabbour; David Koleczek". `metadata.txt` and README list the two humans only. | None. |
| B4b | **Flagged:** review PDFs list "Amplifier" as an author | MUST (if posted) | Fail (flagged, review PDFs only) | Byline on page 1 of `decision-model-fit-v5.pdf` and `-supplement.pdf` reads "Amplifier  Michael J. Jabbour  David Koleczek". `pdfauthor` is "Amplifier; Michael J. Jabbour; David Koleczek" in both (`pdfinfo`) and in `main.tex` and `supp.tex`. Compliant for review use only. If either PDF is posted to arXiv, OSTI or SLAC STI it breaks the arXiv rule. | Decide before any posting: remove "Amplifier" from the byline and `pdfauthor` in `main.tex` and `supp.tex` (the AI-use disclosure already credits it), or keep it only for internal review and never upload those PDFs. |
| B5 | Standard `\title`/`\author`/`abstract` block | SHOULD | Partial | The title block is hand-built (`\begin{center}` plus a `minipage` for the abstract, in `main.tex` and `sections/m0-abstract.tex`). arXiv's HTML conversion keys off `\title`/`\author`/`abstract`. | Use `\title`, `\author`, `\date`, `\maketitle` and `\begin{abstract}`, restyled in `preamble.tex` to keep the layout. Apply the same to the `HEADER` template in `make_arxiv.py`. |
| B6 | Fixed date, no `\today` | SHOULD | Pass | "October 8, 2026" (arXiv) and "Version 5.1 · October 8, 2026" (review). No `\today` in the source. | None. |
| B7 | Report number only if issued | COND | Pass | `Report-no: none`. | None. |
| B8 | ORCID iDs | SHOULD | Fail | No ORCID in the sources, PDFs or `metadata.txt`. | Both authors link an ORCID in their arXiv profiles. No LaTeX change is needed. |
| B9 | OSTI-style title elements (title, type, date, lead author and organisation) | OPTIONAL | Partial | Title, authors, organisation and date are present. There is no "Technical Report" type label (the arXiv byline carries no version line either). Sponsor and contract are N/A. | Optional: add "Technical report" above the date. |
| B10 | Keywords | OPTIONAL | Partial | Present on page 1 of all three PDFs ("decision models; model routing; ... paired measurement"). The review PDF metadata disagrees: `decision-model-fit-v5.pdf` `/Keywords` has "paired design", and the supplement PDF `/Keywords` is empty. The arXiv PDF matches page 1. | Align `pdfkeywords` in `main.tex` and `supp.tex` with the page-1 line. |
| B11 | Co-author consent and details checked | MUST | N-A (not checkable) | Process step, not an artifact property. | Submitter confirms. |
| B12 | Page-1 layout, rendered at 150 dpi | SHOULD | Pass | PNGs rendered to `/tmp/pub-conf-render/{main-01,supp-001,arxiv-001}.png` (1275 x 1650). I could not open images in this environment, so I verified the front matter geometrically from `pdftotext -bbox-layout`. The title, authors, affiliation and date lines are centred (centre x of 305.6 to 306.0 of 306 pt). The abstract box spans x 101.4 to 510.2 pt, inside the text block (86 to 527 pt). Nothing overflows, and the left 0.95-in strip is blank (no line numbers). | A human glance at the three PNGs is still worthwhile. |

## 3. Statements

| # | Item | Level | Status | Evidence | Exact fix |
|---|---|---|---|---|---|
| C1 | Acknowledgments | OPTIONAL | Pass | "We thank the independent reviewers ..." (`sections/statements-body.tex`). The same text appears in the supplement as H.8 and once in the arXiv edition. | None. |
| C2 | Funding | OPTIONAL | Pass | "Microsoft funded this work. Model and service calls were paid at list price." | None. |
| C3 | Data and code availability with a public URL that resolves | MUST | **Partial** | URL and commit page both return HTTP 200 anonymously: `https://github.com/michaeljabbour/amplifier-bundle-fast-decisions` and `.../commit/3cd180b7523d`. All seven `docs/evidence/*` packages are at that commit. **But** the statement says the repository holds "the build that regenerates every number in this paper" at that commit. The v5 build does not exist there: `docs/papers/2026-10-08-decision-model-fit-v5/` is absent at `3cd180b7523d` (2026-10-07). It first appears in `4138f117`. The final sources are uncommitted: `refs.bib`, `check_abstract.py`, `make_arxiv.py`, `arxiv/`, `sections/abstract-body.tex`, `sections/m9b-statements.tex`, `sections/statements-body.tex`, plus 14 modified files. A reader following the stated commit cannot find this paper's build or arXiv builder. | Commit and push the working tree, then tag it (e.g. `report-v5.1`). Reword the statement: evidence packages at `3cd180b7523d`, paper source and build at tag `report-v5.1`. Add a tag macro in `build_assets.py` next to `PAPER_EVIDENCE_COMMIT` (line ~3070). Re-run `make arxiv`. |
| C4 | Competing interests | OPTIONAL | Pass | Present. It discloses Microsoft employment and Microsoft software, and the third-party services. | Authors must confirm the factual claim "no financial relationship with their providers beyond that use". I cannot verify it. |
| C5 | AI-use disclosure | MUST (if significant) | Partial | Present and well structured. "Amplifier ... orchestrated the experiments, wrote the analysis code, generated the figures and drafted the text ... authors ... take full responsibility". It separates the writing assistant from the systems under test. It does not name the underlying LLM(s) or version(s) that Amplifier used. | Add one sentence naming the model(s) and dates behind Amplifier's analysis and drafting. |
| C6 | No extraneous personal or political statements | MUST | Pass | None found in the full text. | None. |
| C7 | SLAC/DOE acknowledgment, report number, disclaimer, LDRD, S&T review | COND | N-A | Decision applied. Word-boundary scan found none present. | None. |
| C8 | Copyright line must not conflict with the arXiv license | MUST | Pass | No copyright statement in the paper or metadata. | None. |

## 4. Body conventions and format

| # | Item | Level | Status | Evidence | Exact fix |
|---|---|---|---|---|---|
| D1 | Single column, single spacing, 10 to 12 pt body | MUST | Pass | `\documentclass[11pt,letterpaper]{article}`, article class (one column by default), `parskip`, no double-spacing or `referee` options. pypdf font-size scan: body is 10.8 to 11.0 bp (11 pt). | None. |
| D2 | Margins at least 1 in | MUST | Pass | `geometry`: textwidth 6.1 in, top and bottom 1 in. Measured ink on all 262 rendered pages: min left 1.17 in, min right 1.15 in, min top 0.99 in. Body bottom is at least 0.97 in on 3 arXiv pages (13, 104, 120; supplement 4, 95, 111): descenders about 2 pt below the text block (verified at 300 dpi). The folio sits 0.56 in from the page bottom, which is normal. | None needed. |
| D3 | No line numbers, watermarks, highlights, margin notes | MUST | Pass | No `lineno`. Left-margin ink is 0 on page 1 and the margin scan shows nothing outside the text block on any page. Searches for DRAFT, CONFIDENTIAL, TODO, FIXME and watermark found nothing in any PDF. The tinted callout boxes (Key idea, Claim) are structural (6 to 8 percent tint plus a rule), not text highlighting. | None. |
| D4 | Type size inside floats | SHOULD | Partial | Captions, abstract and references are 10 pt. Table text is 9 pt and figure labels or footnotes 8 pt. Share of characters below 10 pt is about 7.5 percent (main PDF) and 6.9 percent (arXiv PDF). Below 8 pt is 0.6 percent: code listings on arXiv pp. 117 to 118 in 7.6 bp Bera Mono (scaled 0.85). | Optional: use `\small` for tables if page budget allows. |
| D5 | Fonts embedded, no Type 3 | MUST | Pass | `pdffonts`: main 10 fonts, supplement 14, arXiv 14, plus the fresh compile 14. All Type 1 (Libertinus, Bera Mono, Dingbats, MSBM10). Every font is emb=yes, sub=yes, uni=yes. **0 Type 3.** No JavaScript (`pdfinfo`). | None. |
| D6 | Caption placement | (no rule; consistency) | Pass | Source scan: 75 `table` environments have the caption above, 4 `xltabular` have it inside, 42 `figure` environments have it below. | None. |
| D7 | Numbering | (no rule; consistency) | Pass | Main: sections 1 to 9, Tables 1 to 4, Figures 1 to 4. Appendices A to I use `X.n` floats. 42 unique figure and 80 unique table captions. | None. |
| D8 | Float order | SHOULD | Partial | Table A.4 is typeset before Table A.3 (supplement p.6 and arXiv p.15). | Fix the float placement or order of the two A.3/A.4 tables in `supp/a-methods.tex`. |
| D9 | Consistent number formats and units | SHOULD | Partial | Percent uses a thin space 475 times vs 31 glued occurrences. "×" is used consistently (180, 0 "x"). Thousands separators are mostly commas, but a few 4-digit values lack one: Appendix A cost table ("1036", "1121") and "1135 ms", against "1,036 sessions" in the main text. "7-minute" is used 5 times and "seven-minute" twice. | Format those values through `siunitx` (`\num{}`). Pick one of "7-minute" or "seven-minute". |
| D10 | Consistent spelling variant | SHOULD | Partial | Mixed UK and US: organise (3), judgement (6), behaviour (3), analyse (6), centre (2), favour (4), colour (4), labelled (19) and labelling (4), against labeled (5), labeling (1), normaliz- (31), summariz- (2). | Pick one house variant and normalise the prose. |
| D11 | Alt text on figures for HTML | SHOULD | N-A | All 42 figures are TikZ or pgfplots with zero `\includegraphics`, so `alt=` does not apply. arXiv HTML will have no alt text. | Optional only. |
| D12 | Semantic sectioning | SHOULD | Pass | `\section`, `\subsection`, `\emph`. `titlesec` only styles them. | None. |

## 5. References

| # | Item | Level | Status | Evidence | Exact fix |
|---|---|---|---|---|---|
| E1 | Complete references | MUST | Partial | 4 entries, all resolve (HTTP 200: both arXiv abs pages and DOI links, and all five URLs in the source: Cloudflare docs for Clef and Clef-Flash, two Hugging Face model pages, the GitHub repo). The two arXiv IDs return the right titles from the arXiv API. **Gap:** the systems the paper evaluates and prices (Jev, GPT-6 Luna and Sol, the OpenAI Decisions API, Fable 5.1, Opus 5.5, Sonnet 5, Qwen3 models) have no reference. Prices come from "the bundle's own table (price list on 2026-06-10)", which is not cited. | Add `@misc` entries (provider doc or pricing URL plus "Accessed ..." date) for these systems and the price list, or add one dated model-and-endpoint table in an appendix. |
| E2 | arXiv IDs and DOIs, clean format | SHOULD | Pass | [1] and [2] carry `arXiv:2406.18665` and `arXiv:2305.05176` plus `10.48550/arXiv.*` DOIs. No braces, tildes or font commands inside the IDs. | Optional: check whether RouteLLM and FrugalGPT have published venue versions, and cite those if so. I did not verify this. |
| E3 | One consistent style, single bib | SHOULD | Partial | `unsrturl` numbering, one `refs.bib`. BibTeX lower-cased the product name in the titles ("clef-flash") for [3] and [4]. Entry [3] reads awkwardly ("Clef-Flash: URL. Accessed ... URL: ..."). | In `refs.bib` write `{Clef} and {Clef-Flash}` (and `Workers {AI} models: {Clef} and {Clef-Flash}`). Split [3] into two entries, one per URL. |
| E4 | `.bbl` shipped, name matches main file | MUST | Pass | `main.bbl` with `main.tex`. arXiv: "will use the .bbl file if it is present". | Optional safety: also ship `refs.bib`. |

## 6. arXiv packaging

| # | Item | Level | Status | Evidence | Exact fix |
|---|---|---|---|---|---|
| F1 | TeX source, pdflatex | MUST | Pass | `main.tex` (16,193 lines, 838,522 bytes) built with pdfTeX 1.40.27, TeX Live 2025. | None. |
| F2 | Supplement embedded, not separate | MUST | Pass | Appendices A to I follow the main text in one `main.tex`. Appendix A starts on p.12 of 130. Cross-references resolve. | None. |
| F3 | Builds from the tarball alone, 3 passes | MUST | Pass | Extracted `arxiv-source.tar.gz` into a fresh temp dir and ran `pdflatex -interaction=nonstopmode -halt-on-error main.tex` three times. All exit 0. Pages 123, then 130, then 130. A 4th pass gives identical text. 0 "LaTeX Warning", 0 Overfull/Underfull boxes, 0 undefined citations or references, 0 "??" in the output text. No bibtex run was needed. | None. |
| F4 | `.bbl` matches main file name | MUST | Pass | `main.bbl` and `main.tex`. | None. |
| F5 | No hidden files, minted, absolute paths, comments | MUST | Pass | 78 members: 70 `.dat`, 6 `.tex`, 1 `.yaml`, 1 `.bbl`. No dotfiles, `._*`, `__MACOSX` or `_minted`. All filenames match `[A-Za-z0-9_+.,=-]`. 0 comment lines in `main.tex` (the 21 lines containing a bare `%` are all pure end-of-line continuation guards, verified). No `/Users`, `/tmp` or `../` paths. No `\write18`, `minted`, `lineno` or `\today`. A `-recorder` run shows all 77 shipped data/label/yaml files are read, with none missing and none unused. | None. |
| F6 | Nothing arXiv would reject | MUST | Pass | No JavaScript, EPS, `psfig` or `.aux`/`.log`/`.pdf` members. 220,764-byte archive (884,928 bytes unpacked). Hyperref is loaded with no driver option. `xr-hyper` is loaded but harmless. | None. |
| F7 | Shipped preview PDF matches a clean compile | SHOULD | Partial | The clean tarball compile and `arxiv/decision-model-fit-v5-arxiv.pdf` both have 130 pages, but float placement differs on 28 pages (60 to 84, 126, 128, 129). The word streams differ by 13 words from reordering. `arxiv-test` discards its compile output. | Have `make_arxiv.py` or `make arxiv-test` copy the clean-compile `main.pdf` over `arxiv/decision-model-fit-v5-arxiv.pdf`, so the preview is exactly what arXiv will build. |
| F8 | Single-document wording in the arXiv edition | SHOULD | Partial | The arXiv PDF still says "supplement" 4 times (Table 1 caption on p.2, the Data availability statement, appendix A "moved to the supplement", TOC) and "main paper" 8 times in the appendices (e.g. "the main paper states them", "the main paper quotes"). | Extend `MAIN_REWRITES` and `SUPP_REWRITES` in `make_arxiv.py`: "where the supplement gives the details" to "where the appendices give the details"; "this paper and its supplement" to "this paper and its appendices"; "moved to the supplement" to "moved to the appendices"; remaining "the main paper" to "the main text". |
| F9 | Flattener inlines a TeX Live file | SHOULD | Partial | `main.tex` lines ~8 to 5513 are TeX Live's `glyphtounicode.tex` (5,505 `\pdfglyphtounicode` lines) inlined by the flattener. Harmless, but 5,500 lines of noise. | In `make_arxiv.py` keep `\input{glyphtounicode}` and `\pdfgentounicode=1` as written instead of inlining the system file. |
| F10 | Metadata: title, authors, abstract | MUST | Pass | See A1 to A7, B1 and B2. | None. |
| F11 | Metadata: Comments | SHOULD | Partial | "11 pages main text + 119-page appendix; 42 figures, 79 tables." Pages are right (11 + 119 = 130). Figures are right (42). **Tables: the PDF has 80 table captions, so "79" is wrong.** `make_arxiv.py` counts `\begin{table}` substrings (75) plus `xltabular` (4), which misses one table produced by a macro instantiated twice. | Count from `main.lot` and `main.lof` or the compiled captions in `make_arxiv.py`, then update the Comments to "80 tables". |
| F12 | Categories and ACM class | SHOULD | Pass | Primary cs.SE with cross-lists cs.AI and cs.LG (two, within the "one or two" guidance). ACM-class `D.2.8; I.2.11` are valid 1998 CCS codes (Metrics; Distributed AI). | None. |
| F13 | License | MUST (choose) | Partial | `metadata.txt`: "CC BY 4.0 (recommended; pending Microsoft legal review)". The choice is irrevocable and not yet made. | Obtain the Microsoft legal answer, record the license, and set it in `metadata.txt`. If not cleared, use the "arXiv non-exclusive license 1.0". |
| F14 | Journal-ref, DOI, Report-no blank | MUST | Pass | All "none" in `metadata.txt`. | None. |
| F15 | Upload instructions | SHOULD | Partial | README step 4 says "arXiv compiles main.tex with pdflatex". Current arXiv (Submission 1.5) asks the submitter to pick the processor. | In `make_arxiv.py`'s README template, add "select PDFLaTeX as the processor and `main.tex` as the main file". |
| F16 | Tarball header hygiene | SHOULD | Partial | Member headers carry local owner "michaeljabbour" (uid 501). No xattr or AppleDouble entries. | Optional: pack with `--owner=0 --group=0 --numeric-owner`. |
| F17 | Endorsement, rate limit, submit-time actions | MUST | N-A (not checkable) | Process steps, not artifact properties. | Submitter needs cs.SE endorsement (README covers this) and at most 2 new submissions per month. |

## Required fixes, in priority order

**Blockers before submitting**
1. **C3: code-and-data statement.** Commit and push the working tree (including `refs.bib`, `check_abstract.py`, `make_arxiv.py`, `arxiv/`, `sections/abstract-body.tex`, `sections/*statements*.tex`), tag it, and reword the statement to cite the evidence commit `3cd180b7523d` plus the tag that holds the paper and build. Rebuild with `make arxiv`.
2. **F13: license.** Get the Microsoft legal decision and record it in `metadata.txt`. Also have the authors confirm the competing-interests claim (C4).
3. **F11 and B3: wrong or unconfirmed metadata.** Change "79 tables" to 80 (count from `.lot`). Confirm or remove "Redmond, WA, USA".
4. **B4b: AI-author flag.** Decide on "Amplifier" in the review PDFs' bylines and `pdfauthor` before any posting beyond internal review. The arXiv edition is already clean.

**Should fix, low effort**
5. F8: remove stale "supplement" and "main paper" wording from the arXiv edition (12 occurrences, `make_arxiv.py` rewrites).
6. F7: ship the clean-compile PDF as the preview (28 pages differ in float placement).
7. E1 and E3: brace "Clef-Flash" in `refs.bib`, tidy [3], and add references for the evaluated systems and the price list.
8. C5: name the LLM(s) behind Amplifier in the AI-use disclosure.
9. B5: switch to `\title`, `\author`, `\maketitle` and `abstract` for the HTML build.
10. B8: add ORCID iDs to the authors' arXiv profiles.
11. F9: stop inlining `glyphtounicode.tex` (5,505 lines).
12. A6: add a few words in the abstract saying Fable and Opus are host models.

**Polish**
- D8 (Table A.4 before A.3).
- D9 and D10 (4-digit commas, "7-minute" vs "seven-minute", spelling variant).
- B10 (keyword metadata mismatch).
- F15 and F16 (README processor note, tar owner).
- A5 (replace the lone `$` with "USD").

## What I could not verify
- Co-author consent, cs.SE endorsement, the account email, the "no financial relationship" claim, and Microsoft legal or publication review.
- The review PDFs were inspected, not rebuilt. They depend on `../../evidence/*` and my task was read-only. They are newer than every source (16:10:46 and 16:10:48 vs the last source edit at 16:01:47), and their text matches the arXiv edition apart from the expected supplement-to-appendix rewrites.
- I rendered the three page-1 PNGs but had no image viewer here. The front-matter layout check above is geometric (text boxes and pixel bounds).
- Whether RouteLLM and FrugalGPT have published-venue versions that should be cited instead of or alongside the arXiv versions.
