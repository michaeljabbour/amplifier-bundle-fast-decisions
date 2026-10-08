# Publication-Standards Checklist: SLAC STI + arXiv

**Target:** 10-page technical report plus a 121-page supplement, written in LaTeX. Topic: applied ML systems measurement (decision models in AI agent harnesses). Authors are at Microsoft. Destination: arXiv, following Stanford/SLAC conventions.
**Researched:** 2026-10-08. Every rule below is quoted from or linked to the page it came from. Items labeled *derived* or *recommendation* are my inferences and are marked as such. Policies change, so re-check arXiv pages on the day you submit. The arXiv rate-limit and endorsement pages cite blog posts from 2026.

Labels: **MUST** = hard requirement (or a rejection/hold risk). **SHOULD** = stated preference or strong recommendation. **OPTIONAL** = allowed or useful. **COND** = applies only if the condition is met.

---

## 0. Fetch log and coverage

| Page | Status |
|---|---|
| https://sti.slac.stanford.edu/author-guides-resources | Fetched |
| https://sti.slac.stanford.edu/publishing-guide | Fetched. **The page body is empty** (only a heading and nav). |
| https://sti.slac.stanford.edu/publishing-guide/open-researcher-contributor-id-orcid | Fetched |
| https://sti.slac.stanford.edu/about, /sti/faqs, /sti-publication-services-0 | Fetched |
| `www-internal.slac.stanford.edu/SciDoc/SciDoc_About_Resources_AuthorResp.asp` and `..._Pub_Matrix.asp` (linked from the author guide) | **Could not fetch.** These are on the SLAC intranet and timed out. The "matrix of business rules" for SLAC publications is behind this wall. |
| Closest official linked pages (OSTI, which SLAC's FAQ links to): https://www.osti.gov/stip/about/supporting-documentation/2411C, https://www.osti.gov/stip/submit/lab-submissions, https://www.osti.gov/stip/submit/submission-basics/sti-copyright, https://www.osti.gov/stip/submit/submission-basics/marking-requirements, https://www.osti.gov/stip/submit/financial-awardee-submissions/doe-reporting-requirements/sample-cover-pages | Fetched. https://www.osti.gov/elink timed out. |
| arXiv: submit/index, prep (metadata), submit_tex, submit_pdf, ancillary_files, license, sizes, endorsement, cross, moderation, policies/content-types, policies/format_requirements, 00README, tar, submit_latex_best_practices, faq/freefonts, faq/whytex, orcid, category_taxonomy, CS review/position-paper blog post | All fetched (arXiv docs read from the site and the `arXiv/arxiv-docs` GitHub repo) |

**Main coverage gap.** The public SLAC STI pages have **no guidance** on any of the following: abstract length or structure, title style, author-list format, keywords, citation style, figures and tables, document-type formatting, accessibility for authors, or arXiv specifically. They mention preprint archives only as places SLAC work must still be tracked. Nothing in this checklist on those topics comes from SLAC. Where a topic has no rule in either source, the checklist says so instead of making one up.

**Applicability gate (decide this first).** SLAC requirements apply only if the paper is a *SLAC document*. The test is: "Did you conduct the research for or write this scientific or technical paper: while being paid by SLAC, while working at SLAC, or while using SLAC-funded equipment? If the answer is YES, then it's a SLAC document!" (https://sti.slac.stanford.edu/author-guides-resources). If every author is at Microsoft with no SLAC pay, presence, or equipment, the SLAC/DOE items below marked COND do **not** apply. In that case, "following Stanford/SLAC conventions" means voluntarily adopting the OSTI title-page elements (§d), not adding DOE statements. Adding a DOE acknowledgment or SLAC affiliation without a real basis would breach arXiv's affiliation policy (§b).

---

## 1. SLAC STI: concrete rules found

Source: https://sti.slac.stanford.edu/author-guides-resources unless noted.

1. **Tracking duty (COND: SLAC document).** "All written results of SLAC work must be properly tracked, collected, and made publicly accessible as mandated by SLAC's DOE contract." This covers work "regardless of where such research may eventually appear (e.g., a journal article, conference proceedings, preprint archive, or server elsewhere)." **An arXiv posting is covered.**
2. **Registration and upload (COND).** "It is each SLAC author's responsibility to register and upload their SLAC documents to Scientific Publishing Services." For LDRD documents, this means "obtaining a SLAC document number, and submitting a PDF version of the preprinted version (not copyrighted by a journal or publishing house)."
3. **DOE contract acknowledgment (COND).** "Put the DOE contract acknowledgment on your paper (i.e., 'Work supported by the U.S. Department of Energy, Office of Science under contract number DE-AC02-76SF00515.')"
4. **LDRD variant (COND: LDRD-funded).** This text "must always appear on your LDRD document, either on the title page or in the acknowledgement section": "This work is supported by the U.S. Department of Energy, Laboratory Directed Research and Development funding, under contract DE-AC02-76SF00515." Also: "This affiliation should be made apart from and in addition to your other affiliations." The primary subject must be "exclusively funded by LDRD" (no commingling).
5. **Registration metadata (COND: LDRD).** Program affiliation, funding source, LDRD proposal number, PI/scientific lead name and email, "the complete name of the journal or conference," and a document abstract.
6. **Abstract content.** The abstract is a "brief overview." "These documents are publicly accessible online, therefore no proprietary, sensitive, or competitively disadvantageous (to the Laboratory or lead scientist) information should be included." No length is given.
7. **Document types** (https://sti.slac.stanford.edu/about). STI products are listed as "Technical Reports/Workshop Reports," "Journal Articles – Accepted Manuscripts," "Conference Presentations and Proceedings," "Scientific Research Datasets," "Software…," "Patents," "Theses and Dissertations," and "Books/Monographs." This paper is a **Technical Report** (it is not an accepted journal manuscript).
8. **ORCID** (SLAC ORCID page). "ORCID iDs are increasingly required by funders and publishers." OSTI adds (COND: DOE federal or contractor employees): employees "must obtain a persistent identifier (PID)… (e.g., ORCID iD). The PID must be used by these employees in published research outputs" (https://www.osti.gov/stip/about/supporting-documentation/2411C).
9. **Report PIDs (OSTI).** "Technical Reports with no distribution limitations – If the report has a PID, it must be provided to OSTI… If a PID is not provided, OSTI will assign one" (2411C page). For an arXiv posting, the arXiv DOI (10.48550/arXiv.…) is the PID to report.
10. **Data (OSTI, COND: DOE-funded R&D).** R&D "must provide a Data Management Plan (DMP) or Data Management and Sharing Plan (DMSP)." "Scientific data that are shared publicly… must be reported as STI to DOE" (2411C).
11. **Pre-publication security review (OSTI, COND: National Lab work).** "Review processes must include appropriate review and approval steps for restricted Science and Technology topic areas as identified in the… S&T Risk Matrix" (2411C). Whether AI work is on the matrix is not stated on the fetched pages. Ask SLAC STI.
12. **Copyright notice for contractor-authored manuscripts (OSTI, COND).** "Notice: This manuscript has been authored by [Contractor] under Contract No. [number] with the U.S. Department of Energy. The United States Government retains… a non-exclusive, paid-up, irrevocable, world-wide license…" For technical reports specifically: "permission from DOE is required to establish and claim copyright" (https://www.osti.gov/stip/submit/submission-basics/sti-copyright).
13. **Title/cover page elements (OSTI sample pages; written for DOE financial-assistance reports, used here only as a convention).** These are: "Unique product number/report number – at top right corner," "Product/report title – centered," "Type of product/report," "Date of issuance or publication date," "Lead author's/principal investigator's name and organization," "Sponsoring DOE organization," and "Contract/financial number." (https://www.osti.gov/stip/submit/financial-awardee-submissions/doe-reporting-requirements/sample-cover-pages)
14. **Markings.** Documents with classified or CUI content "should be marked according to their respective guidance" (marking-requirements page). This is not expected for this paper, but confirm that nothing is CUI.
15. **Contact:** sti@slac.stanford.edu / scipubs@slac.stanford.edu.

## 2. arXiv: concrete rules found

**Submission overview** (https://info.arxiv.org/help/submit/index.html)
- Content must be "topical and refereeable scientific contributions." Submitters must be registered authors, and new users or categories may need endorsement.
- Format preference order: "(La)TeX, AMS(La)TeX, PDFLaTeX" > PDF > HTML. "We do not accept… PDF created from TeX/LaTeX source."
- Figures: "PDFLaTeX processing" → "JPEG, GIF, PNG or PDF." "We do not accept submissions with omitted figures."
- Filenames may use only "a-z A-Z 0-9 _ + - . , =" and are case sensitive ("Figure1.PDF and figure1.pdf are not the same").
- "You may choose multiple Top-Level files and the resulting article will contain the TeX output of all the selected files, concatenated together, in order."
- The four most common compile failures: mixed figure formats, misreading "Option clash for package hyperref" (it "is not a reason to report a failure"), missing style files, and wrong-case or absolute figure paths.
- Fix errors by replacing the submission. "DO NOT make a new submission for a corrected article."

**Metadata** (https://info.arxiv.org/help/prep.html)
- "Our metadata fields only accept ASCII input." Curly quotes, en/em dashes, and fi/ff ligatures pasted from a PDF are the "most common culprits."
- **Title:** "Do not use all uppercase letters." "Do not use unicode characters." Expand opaque macros. "Check your spelling."
- **Authors:** "Firstname Lastname." "Include the names of all authors instead of truncating the list with 'et al.'" No honorifics and no degree suffixes. "Affiliations must be placed within parentheses," for example `Author One (1), Author Two (1 and 2) ((1) Institution One, (2) Institution Two)`. "Do not enter full mailing address." "It is a violation of our policies to misrepresent your identity or organizational affiliation. Claimed affiliation should be current in the conventional sense: e.g., physical presence, funding, e-mail address." "Generative AI language tools should not be listed as an author."
- **Abstract:** "abstracts longer than 1920 characters will not be accepted." "Do not include the word 'Abstract'." Omit TeX-isms such as `~`, `\,`, `\ `, and font commands like `\em`/`\it`. "Carriage returns will be stripped unless they are followed by leading white spaces." "Avoid unnecessary blank lines." Some TeX math is rendered through MathJax. Refer to other papers as `arXiv:YYMM.NNNNN`.
- **Comments:** "Indicate number of pages and number of figures." This is the field for URLs and for "submitted to" information (frozen per version). "Do not put copyright statements in the comments."
- **Report-no:** "required only when supplied by author's institution… Do not put any other information in this field."
- **Journal-ref / DOI:** only for already-published versions. "Do not add the arXiv assigned DOI to this field."
- **ACM-class (cs only):** e.g., `F.2.2; I.2.7`.

**TeX processing** (https://info.arxiv.org/help/submit_tex.html)
- Do not include `.aux .log .toc .lot .lof .dvi .pdf`. **Exceptions:** `.bbl` and `.ind`.
- "Do not include extraneous files (including unused figure files)… Do not include journal templates, referee letters."
- "arXiv recommends against using the `\today` macro."
- There is no on-the-fly figure conversion (`-eps-converted-to.pdf` is not allowed), so use one figure format throughout. `psfig` is not supported.
- "Do not include embedded JavaScript… Submissions with embedded JavaScript are automatically rejected."
- With hyperref or graphics, "you do not have to make this explicit [driver] choice and should not do so." From the 00README page: "We no longer add hyperref by default." Load `hyperref` yourself.
- "We don't provide any further packages besides what is provided by the TeX Live system." Include any custom `.sty`/`.cls` files.
- "Do not submit in double-spaced 'referee' mode."
- References: "strongly encourage you to include arXiv's YYMM.NNNNN identifiers… Do not include extraneous font commands, spaces, tildes, braces, or line-breaks within the e-print identifier."
- `.bbl`: "the name of the .bbl file must match the name of the main .tex file." Otherwise include every `.bib` file, or "the submission system will block you." For biblatex, the `.bbl` must be compatible: "TeX Live 2025… uses bbl format 3.3… For TeX Live 2025, only bbl format 3.3 is supported." Biber vs BibTeX `.bbl` files must match the backend you used.
- Provide `.ind` (makeindex), `.gls`/`.nls` (glossaries) yourself.
- `xr` across separately compiled PDFs: links "will not function… We concatenate the single PDFs." Use `subfiles` + `xr` with `\externaldocument[M-]{main}[]`.
- "Hidden files will be deleted upon announcement." Packages that rely on hidden files, "e.g. minted.sty," "may function on your machine, but will fail once announced."
- TeX comments ship in the public source. "potentially embarrassing self-comments… you should probably take them out" (https://info.arxiv.org/help/faq/whytex.html).
- "arXiv's TeX installation does not have any proprietary fonts" (https://info.arxiv.org/help/faq/freefonts.html).

**Format requirements** (https://info.arxiv.org/help/policies/format_requirements.html)
- Must have: "Title and authorship," "Complete references," "Links to code or data sets must resolve to a publicly available repository," "Machine readability," "Single spaced text," "10 to 14 point type," "Minimum 1" page margin."
- Must not have: "Line numbers," "Watermarks that obstruct the text," "Highlighted text," "Margin notes," "Referee remarks," or "Copyright statements which prohibit or impair arXiv's redistribution license."
- "Papers with long sections that are not article text, like code, images, or tables we encourage authors to use ancillary files… rather than append them to the end of the document."

**Content types / moderation** (https://info.arxiv.org/help/policies/content-types.html, https://info.arxiv.org/help/moderation/index.html)
- Typically NOT accepted: "Supplemental material that is not embedded in the full article." **A standalone supplement cannot be its own arXiv submission.**
- Required: "appropriate and carefully prepared sections, figures, tables, references." "Submissions should focus entirely on the scientific research and avoid extraneous personal or political statements."
- **Generative AI:** arXiv requires "authors to report in their work any significant use of sophisticated tools… we now include in particular text-to-text generative AI among those that should be reported consistent with subject standards for methodology." Authors "take full responsibility for all its contents, irrespective of how the contents were generated."
- **Rate limit:** "up to two new submissions per calendar month with a limit of three active submissions" per author.
- **CS review/position papers** (https://blog.arxiv.org/2025/10/31/attention-authors-updated-practice-for-review-articles-and-position-papers-in-arxiv-cs-category/): these "must now be accepted at a journal or a conference and complete successful peer review." Without documentation they are "likely to be rejected." **A measurement study is original research, so frame it as one.**

**Ancillary files** (https://info.arxiv.org/help/ancillary_files.html)
- Put them in "a directory `anc` at the root of your .tar.gz or .zip." Use it for raw data, code, extra images, and spreadsheets.
- "TeX files should not be included in the ancillary file directory." "Full text placed in the ancillary directory will not be indexed in searches." Ancillary files are "not supported with PDF submissions." They are frozen per version.

**Size** (https://info.arxiv.org/help/sizes.html)
- **No numeric size cap is stated** in the current docs (I searched the arxiv-docs repo). Oversized uploads are auto-rejected. For a legitimately long paper, "contact the arXiv administrators… quote the automatic rejection identifier."
- "Starting with February 2026, we will issue a warning… if images larger than 34 Megapixel." Use "JPEG" for photos and "PDF, PNG" for diagrams. Full-resolution figures may go in `anc/`.

**PDF/fonts** (https://info.arxiv.org/help/submit_pdf.html). This page applies to PDF-only submissions but is relevant to included PDF figures.
- "outline (TrueType/Type1) rather than bitmap (Type3) fonts." Type 3 fonts break machine readability. "arXiv may reject PDF submissions because of non-standard, non-embedded fonts."

**Licenses** (https://info.arxiv.org/help/license/index.html)
- Options: CC BY 4.0, CC BY-SA 4.0, CC BY-NC-SA 4.0, CC BY-NC-ND 4.0, the arXiv non-exclusive license 1.0, or CC0. "The license chosen is irrevocable." "Funders may require specific licenses." For a license not on the list: "select the arXiv license and then indicate the desired license in the first page." Special copyright statements go "on the first page… Copyright notices should not be included in the separate metadata."

**Endorsement / cross-listing / accessibility**
- "arXiv requires that users be endorsed before submitting their first paper to arXiv or a new category." An institutional email plus claimed papers can qualify (https://info.arxiv.org/help/endorsement.html).
- "It is rarely appropriate to add more than one or two cross-lists. … Bad cross-lists will be removed" (https://info.arxiv.org/help/cross.html).
- For HTML conversion: use a standard `\title`/`\author`/`abstract` block, add alt text with `\includegraphics[alt={...}]{...}`, and use semantic macros (`\emph`, `\section`) instead of visual ones (https://info.arxiv.org/help/submit_latex_best_practices.html).

**Categories** (https://arxiv.org/category_taxonomy)
- cs.SE: "design tools, software metrics, testing and debugging, programming environments."
- cs.AI: "all areas of AI except Vision, Robotics, Machine Learning, Multiagent Systems, and Computation and Language… includes… Planning, and Uncertainty in AI."
- cs.LG: "also an appropriate primary category for applications of machine learning methods."
- cs.PF: "performance measurement and evaluation."
- cs.MA: "multiagent systems… intelligent agents."
- cs.CL: "natural language processing… work on artificial languages… that does not explicitly address natural-language issues… is not appropriate."

---

## 3. Merged checklist

### (a) Abstract

| # | Item | Level | Source |
|---|---|---|---|
| a1 | ≤ **1920 characters** in the arXiv metadata abstract (spaces count). Check with: `detex abstract.tex \| tr -s ' \n' ' ' \| wc -c` | MUST | arXiv prep |
| a2 | **Word count: no word limit exists in either source.** *Derived:* 1920 characters is roughly 270–320 words of technical English. Aim for **≤ 250 words** to leave margin for expanded macros. | SHOULD (derived) | (none) |
| a3 | ASCII only. Retype straight quotes, `--` for dashes, and plain "fi"/"ff"; do not paste from the PDF. | MUST | arXiv prep |
| a4 | Do not start with the word "Abstract." | MUST | arXiv prep |
| a5 | No `~`, `\,`, `\ `, `\em`, `\it`, `\textbf`, or custom macros. Expand acronym macros to plain text. Simple `$...$` math is OK through MathJax, but use it sparingly. | MUST/SHOULD | arXiv prep |
| a6 | `\cite{}` will not resolve in metadata (*derived*). If you must reference a paper, write `arXiv:YYMM.NNNNN`. Neither source forbids references, but they are rarely needed. | SHOULD | arXiv prep |
| a7 | One paragraph, or indent continuation lines to force breaks. No blank lines. | SHOULD | arXiv prep |
| a8 | No proprietary, sensitive, or competitively disadvantageous information. This matters here: no internal Microsoft model names, customer data, or unreleased product details. | SHOULD (SLAC wording; MUST if a SLAC document) | SLAC author guide |
| a9 | Structure: **neither source prescribes one.** SLAC says only "brief overview." | (no rule) | (none) |
| a10 | Keep the metadata abstract and the `\begin{abstract}` text identical, so arXiv, SciDoc/OSTI, and the PDF all match. | SHOULD (recommendation) | (none) |

### (b) Title, authors, affiliations, front matter

| # | Item | Level | Source |
|---|---|---|---|
| b1 | Title not in all caps, no Unicode, no opaque macros, spell-checked. | MUST | arXiv prep |
| b2 | Metadata authors as `Firstname Lastname`; list **all** authors (no "et al."); no "Dr." or "PhD"; no commas inside names. | MUST | arXiv prep |
| b3 | Affiliations in numbered parentheses, e.g. `A. One (1), B. Two (1 and 2) ((1) Microsoft, Redmond, WA, USA, (2) ...)`. City and country at most. | MUST (format) | arXiv prep |
| b4 | Affiliations must be real and current ("physical presence, funding, e-mail address"). **Only list SLAC/Stanford/DOE if that is true.** | MUST | arXiv prep |
| b5 | No AI tool as an author. | MUST | arXiv prep, moderation |
| b6 | Use a standard `\title{}` / `\author{}` / `\begin{abstract}` block (needed for HTML and accessibility). | SHOULD | arXiv best practices |
| b7 | Use a fixed date on the title page, not `\today`. | SHOULD | arXiv submit_tex |
| b8 | Report number: put it at the **top right** of the title page *and* in the arXiv `Report-no` field **only if your institution assigned one** (a SLAC document number if it is a SLAC document; a Microsoft technical-report number only if one was actually issued). Never invent one. | COND MUST | arXiv prep; SLAC author guide; OSTI sample pages |
| b9 | OSTI-style title-page elements: title, "Technical Report," date of issuance, lead author and organization, and sponsoring organization plus contract number (if DOE). | OPTIONAL (convention); COND if a SLAC document | OSTI sample pages |
| b10 | ORCID iDs for all authors, linked to their arXiv accounts. Required for DOE/contractor employees. | SHOULD; COND MUST (DOE) | arXiv orcid; OSTI 2411C; SLAC ORCID page |
| b11 | Submitter has every co-author's consent and has checked their details. | MUST | arXiv prep |
| b12 | Keywords: neither source requires them. arXiv has no keyword field; use ACM-class instead (f12). | OPTIONAL | (none) |

### (c) Required statements

| # | Item | Level | Source |
|---|---|---|---|
| c1 | **DOE contract acknowledgment**, verbatim: "Work supported by the U.S. Department of Energy, Office of Science under contract number DE-AC02-76SF00515." | COND MUST (SLAC document) | SLAC author guide |
| c2 | **LDRD acknowledgment**, verbatim, on the title page or in the acknowledgments, "apart from and in addition to your other affiliations." | COND MUST (LDRD) | SLAC author guide |
| c3 | **DOE copyright/license notice** ("This manuscript has been authored by … under Contract No. … The United States Government retains … non-exclusive … license"). Put it on the **first page**, not in the arXiv Comments. | COND MUST (DOE contractor-authored) | OSTI sti-copyright; arXiv license |
| c4 | Any copyright line must not contradict the arXiv license you select. | MUST | arXiv license, format_requirements |
| c5 | **Generative-AI and tool-use disclosure.** Report "any significant use of sophisticated tools… text-to-text generative AI," following methodology norms. In an agent-harness paper, also state which LLMs and agents produced data or analysis (the systems under test) separately from any AI help with writing. | MUST (if significant use) | arXiv moderation |
| c6 | **Data and code availability:** every code or data link must "resolve to a publicly available repository." No internal Microsoft URLs, private repos, or links that require a login. | MUST | arXiv format_requirements |
| c7 | DOE-funded work: data shared publicly must also be reported to OSTI, with a DMP/DMSP in place. | COND MUST | OSTI 2411C |
| c8 | Funding statement in general: only the DOE/SLAC wording is mandated. For Microsoft-funded work, no source requires a statement (*recommendation:* state "funded by Microsoft"). | COND MUST / OPTIONAL | SLAC; (none) |
| c9 | Competing interests: **no requirement in either source.** *Recommendation:* if you measure Microsoft or competitor products, add a one-line conflict-of-interest note. | OPTIONAL | (none) |
| c10 | DOE "disclaimer" boilerplate: **not found on any page I could fetch.** The SciDoc rules matrix that may contain it is intranet-only. Ask sti@slac.stanford.edu if this is a SLAC document. Do not copy text from memory. | COND (unverified) | (unreachable) |
| c11 | No extraneous personal or political statements. | MUST | arXiv moderation |
| c12 | S&T Risk Matrix pre-publication review and notification to the DOE program office if the topic is restricted. | COND MUST (National Lab work) | OSTI 2411C |

### (d) Body structure conventions

| # | Item | Level | Source |
|---|---|---|---|
| d1 | Single spacing, **10–14 pt**, **≥1 inch margins**, no line numbers, no highlights or margin notes, no review or "DRAFT/CONFIDENTIAL" watermark over text. Turn off `[review]`/`lineno` options from venue templates. | MUST | arXiv format_requirements, submit_tex |
| d2 | "Appropriate and carefully prepared sections, figures, tables, references." | MUST | arXiv moderation |
| d3 | Use semantic sectioning (`\section`, `\subsection`, `\emph`), not manual font sizing. This gives navigation in the HTML version. | SHOULD | arXiv best practices |
| d4 | Alt text on every figure: `\includegraphics[alt={...}]{...}`. | SHOULD | arXiv best practices |
| d5 | No slides or posters in the body. Put them in `anc/`. | MUST | arXiv format_requirements |
| d6 | Section order, numbering scheme, caption placement, equation numbering, and units: **neither source prescribes any of these.** The SLAC "Publishing Guide" page is empty, and the business-rules matrix is intranet-only. Pick one consistent house style (for example, the venue template you will later target). | (no rule) | (none) |
| d7 | Prefer TeX source over a pre-built PDF, because the HTML version and its accessibility depend on it. | SHOULD (MUST in practice: PDF built from TeX is rejected) | arXiv submit, whytex |

### (e) References

| # | Item | Level | Source |
|---|---|---|---|
| e1 | "Complete references." Every cited item must be fully resolvable. | MUST | arXiv format_requirements |
| e2 | Include arXiv IDs as `arXiv:YYMM.NNNNN`, with no braces, tildes, font commands, or line breaks inside the ID. With BibTeX, use `eprint` + `archivePrefix={arXiv}` or put the plain string in `note`. | SHOULD ("strongly encourage") | arXiv submit_tex |
| e3 | Include DOIs for published works. Neither source requires this for references. OSTI requires PIDs for DOE STI *records*, not reference lists. | SHOULD (recommendation) | OSTI 2411C (by analogy) |
| e4 | Citation style: **no style is mandated by either source.** | (no rule) | (none) |
| e5 | Prefer a single bibliography file. arXiv says reference extraction "will be more accurate and faster if your references are all in one file." | SHOULD | arXiv submit_tex |
| e6 | Persistent links for software and datasets that you cite as evidence (they must be public; see c6). | MUST | arXiv format_requirements |

### (f) arXiv packaging

| # | Item | Level | Source |
|---|---|---|---|
| f1 | **Submit TeX source**, compiled by pdflatex (or xelatex), not a PDF. | MUST | arXiv submit, submit_pdf |
| f2 | **Supplement: embed it.** A separate supplement-only submission is "typically NOT accepted." **Recommended:** `\appendix` + `\input{supplement/...}` in the same main `.tex` file, so there is one PDF with working cross-references. Alternative: two top-level `.tex` files that arXiv concatenates, using `subfiles` + `xr` with `\externaldocument[M-]{main}[]`. **Do not** cross-link two independently compiled PDFs with plain `xr`. | MUST (embed) / SHOULD (single main file) | arXiv content-types, submit, submit_tex |
| f3 | Move bulky non-prose parts of the 121 pages (raw run logs, per-trial tables, prompt dumps, code) into `anc/` (CSV, JSON, `.py`, high-res figures). Keep the narrative appendix in the PDF. Remember that `anc/` text is **not indexed**. | SHOULD | arXiv format_requirements, ancillary_files |
| f4 | No `.tex` files in `anc/`. Do not reference `anc/` paths from the TeX source. | MUST | arXiv ancillary_files |
| f5 | Layout: `main.tex`, `main.bbl` (same basename) or all `.bib` files, `figures/*.pdf\|png\|jpg`, `sections/*.tex`, `supplement/*.tex`, custom `*.sty`/`*.cls`, `anc/...`. Package as `.tar.gz` or `.zip` (not rar or bz2). Compilation runs from the root, so `\input` paths must be relative to the root. | MUST | arXiv submit_tex, tar, ancillary_files |
| f6 | `.bbl`: if you ship one, its name must match the main `.tex` file, and a biblatex `.bbl` must be format 3.3 (TeX Live 2025) and built with the same backend you used. A mismatched `.bbl` breaks the build. | MUST | arXiv submit_tex |
| f7 | Remove `.aux .log .out .toc .pdf .synctex.gz`, unused figures, templates, response letters, hidden files and folders (`.git`, `.DS_Store`, `_minted`/`.cache`), and **TeX comments** containing internal notes. Check with `latexpand --empty-comments` or the third-party `arxiv_latex_cleaner` (made by Google, not arXiv). | MUST (hidden files and extras) / SHOULD (comments) | arXiv submit_tex, whytex |
| f8 | Filenames may use only `a-z A-Z 0-9 _ + - . , =`, and case must match `\includegraphics`. | MUST | arXiv submit |
| f9 | Figures all in one family (PDF/PNG/JPG for pdflatex). Convert EPS yourself. No `psfig`. No JavaScript or animations in PDFs (put movies in `anc/`). Images under 34 MP. Avoid Type 3 fonts in matplotlib PDFs (`pdf.fonttype: 42`). | MUST / SHOULD | arXiv submit_tex, sizes, submit_pdf |
| f10 | `\usepackage{hyperref}` yourself, with no `[pdftex]` driver option. Do not use proprietary fonts (only TeX Live fonts are available). Do not use `minted` unless the code is pre-rendered (use `listings` instead). Provide `.ind`/`.gls` if used. | MUST / SHOULD | arXiv submit_tex, 00README, freefonts |
| f11 | Size: no numeric cap is published. Compress figures. If auto-rejected, write to arXiv admins with the rejection identifier and explain "10 pp + 121 pp supplement." | SHOULD | arXiv sizes |
| f12 | **Metadata to fill:** Title, Authors (b2–b3), Abstract (a). **Comments:** `10 pages main text + 121-page supplementary appendix; N figures, M tables. Code and data: https://github.com/... ` (put a space before any trailing period after the URL). **Report-no:** only if assigned. **Journal-ref/DOI:** leave blank. **ACM-class (optional):** e.g. `I.2.11; D.2.8` (my suggestion; check the codes against ACM CCS 1998 before use). | MUST (title, authors, abstract) / SHOULD (comments) / OPTIONAL (ACM) | arXiv prep |
| f13 | **Category (recommendation).** **Primary cs.SE** if the main contribution is measuring the harness, i.e. how agent software routes and decides, with metrics and instrumentation ("software metrics… programming environments"). **Primary cs.AI** if the main contribution is about the decision models' reasoning or uncertainty behavior. **Cross-list** the other of the two, plus **at most one** of cs.LG (applications of ML), cs.PF (if latency, cost, or throughput measurement is central), or cs.MA (if multi-agent). **Avoid cs.CL** unless NLP itself is the subject. Keep to 1–2 cross-lists; moderators may reclassify. | SHOULD | arXiv taxonomy, cross, moderation |
| f14 | **License (recommendation): CC BY 4.0**, if Microsoft's legal/open-source office and any target venue allow it. It is arXiv's stated preference ("encourages… a liberal license"), and the DOE non-exclusive government license (c3) does not conflict with it. If a future venue's copyright transfer is a concern, choose the **arXiv non-exclusive license 1.0**. Avoid CC0 (it "conflicts with many publishers' requirements"). The choice is **irrevocable**. | MUST (choose) / SHOULD (CC BY) | arXiv license |
| f15 | Endorsement: the submitter needs an endorsement for the chosen cs category. A Microsoft institutional email plus claimed prior papers can qualify; otherwise ask a cs-area endorser. Do this early. | MUST | arXiv endorsement |
| f16 | Frame the work as **original research** (measurement methodology and results), not a survey or position paper. A CS survey or position paper needs proof of prior peer review. | MUST (avoid rejection) | arXiv CS blog post |
| f17 | Rate limit: ≤2 new submissions per author per month, ≤3 active. Coordinate if co-authors are posting other papers. | MUST | arXiv moderation |
| f18 | Before clicking Submit: open the compiled preview, check all 131+ pages, the references, and the figure count, then **check the HTML rendering** after announcement. Submit before 14:00 US Eastern to be announced at 20:00 the same day. | SHOULD | arXiv submit, submit_tex |

### (g) Conflicts between the sources and how to resolve them

| # | Tension | Resolution |
|---|---|---|
| g1 | **Applicability.** "Follow SLAC conventions" vs Microsoft-only authorship. SLAC rules attach only to SLAC documents, and arXiv forbids misrepresenting affiliation or funding. | Apply the §0 test. If it is not a SLAC document, **omit** the DOE contract text, the SLAC affiliation, and any SLAC report number. Use only the neutral OSTI title-page layout (b9) as a style convention. |
| g2 | **Report number.** SLAC requires "obtaining a SLAC document number." arXiv's Report-no is "required only when supplied by author's institution." | No conflict if SLAC-registered: put the number on the title page top right **and** in Report-no, with nothing else in that field. Otherwise leave it blank. |
| g3 | **Supplement format.** SLAC wants "a PDF version of the preprinted version." arXiv rejects TeX-built PDFs and unembedded supplements. | Build **one** TeX source (main + appendix supplement) for arXiv, then give SLAC/OSTI the **arXiv-compiled PDF** (and its arXiv DOI as the PID). |
| g4 | **Abstract.** SLAC gives no length and bans proprietary content. arXiv sets 1920 characters, ASCII, no "Abstract" label. | Write one abstract that satisfies both: ≤1920 characters (≈≤250 words), ASCII, no proprietary details. Reuse it verbatim in SciDoc/E-Link. |
| g5 | **Copyright and license notices.** The DOE notice must be on the manuscript. arXiv bans copyright text in Comments and any notice that impairs its license. | Put the DOE notice on page 1 only. It grants a *non-exclusive* government license, so it is compatible with CC BY 4.0 or the arXiv license. Never put it in metadata. For technical reports, DOE says asserting copyright needs DOE permission, so confirm with SLAC STI before choosing a CC license. |
| g6 | **Date.** The OSTI cover page shows the "date of issuance." arXiv advises against `\today`. | Hard-code the issuance date. |
| g7 | **Long non-text content.** SLAC/OSTI treat the report as one STI product. arXiv encourages moving long code, image, or table sections into `anc/`, but `anc/` is unindexed and must not hold TeX. | Keep the explanatory supplement in the PDF so it stays one indexed record. Move raw data and code to `anc/` and mirror them in a public repository (also needed for c6 and, if DOE-funded, c7). |
| g8 | **Timing.** SLAC tracks preprints "regardless of where" they appear, but the fetched pages give no deadline. | *Recommendation:* if it is a SLAC document, register in SciDoc and get the number **before** posting, so the number appears on arXiv v1 (metadata is frozen per version). |
| g9 | **Gaps in both sources** (structure, citation style, competing interests, units, captions). | No rule exists. Use a consistent venue-style template and record it as an author choice, not a requirement. |
