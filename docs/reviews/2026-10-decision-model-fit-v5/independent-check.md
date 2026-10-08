# v5 independent check: decision-model-fit-v5 (main, 11 pp) + supplement (121 pp)

Read-only check of the uncommitted working tree in
`docs/papers/2026-10-08-decision-model-fit-v5/`. Nothing in that directory was edited.
Fixes were trial-compiled in a scratch copy (`/tmp/v5work`) only.

Method. `pdftotext -layout` and `-bbox` on both PDFs; 150 dpi renders of main p1-11 and supplement
p1-6, p116-121 (I cannot view images, so layout was judged from word-box geometry and pixel extents,
not by eye); text of the hypothesis-table pages (supp p56-58, p94-96); a macro-by-macro comparison
of `generated/numbers.tex` against the PDF text; a rebuild of both PDFs in the scratch copy.
`check_alignment.py` and `check_figures.py` both pass (run with `-B`; they write nothing). They do
not catch most of the defects below.

## Verdicts

| # | Requirement | Verdict | One-line reason |
|---|---|---|---|
| 1 | Figures/tables list moved to an appendix at the end of the supplement; short front matter | **Pass** (1 defect) | Section I is the last section (p116-121). It lists 38 figures + 74 tables, matching the body captions one-for-one, and all page numbers are correct. Front matter is a half-page summary + TOC, but 6 TOC entries (H.3-I) spill onto an otherwise empty p3. |
| 2a | Main paper 8-12 pp | **Pass** | 11 pp (10 achievable, see L2). |
| 2b | Main paper clean | **Partly** | Takeaway list is split around Table 1 (p1-2); p6, p7, p8 end with 2.9, 1.9 and 1.6 in of blank space; conclusion items 3 and 5 start lowercase after a full stop; undefined jargon. No orphan headings, split boxes, overflow or file paths. |
| 2c | Abstracts aligned (abstract, summary, list, conclusion, findings table: same five takeaways, order, numbers, labels) | **Pass** at headline level, **Partly** overall | All 5 titles, 11 headline numbers and 5 labels are byte-identical in all six places and in the same order. The main abstract alone carries four extra secondary numbers (8-11 points, 1.3-1.7x, about 0.75x, rule-matched-model). Table S2 uses a different label vocabulary. |
| 3 | Claims and evidence crisp | **Partly** | Table 1 is a good claims-and-evidence table. Each takeaway section has 3-4 bullets. But "claim" boxes are 2-3 sentences, not one. Plain-words hypothesis tables exist only for C (S36) and G (S69). Several labels are stronger than the supplement's own wording (H1-H3 below). |
| 4 | Numbers match `numbers.tex` | **Pass** | Every macro-fed number matches. Hard-coded literals ("8-11 points" in abstract and Section 3) agree with +7.9 / +11.1 but are not macro-driven. |
| 5 | No file paths in either PDF | **Pass** | Only the GitHub URL, CLI flags/config keys and one JS snippet (`r.json()`). The checker's 9 path patterns: 0 hits. |

## Defects, by severity (page = PDF page; "Main" / "Supp")

### A. Claims stronger than their evidence labels, and wrong references

**A1. Main p5, Section 4, bullet 2 (and Supp p5, Table S2).**
- Main labels the main-campaign figures 0.590x (0.529-0.663) / 1.457x [preregistered].
- Supp C.4 (p58) says that section "is labelled confirmatory but not preregistered" because the estimator was fixed after the data. Main Table 2 (p3) agrees ("estimator written after the data").
- Table S2 (Supp p5) labels the row "Routing on Fable saves 0.56x (0.49-0.64), main-v1, preregistered". That number is the pair reading, which Supp C.4 says "is not reported alone", and it appears nowhere in the main paper (which uses the arm reading: 0.537 / 0.590).
- Fix: relabel as "[confirmatory; estimator post hoc]" (new label, define it once in Section 2) in `sections/m4-routing.tex` bullet 2. In `build_assets.py` ~line 2708 change the row to the arm reading (`0.537x (0.48-0.61)`, sticky) with the same label.

**A2. Supp p5, Table S2, rows 1-2** ("Decision calls are fast...", "Shadow agreement...").
- Evidence column says "measured". Takeaway 5 says [exploratory, one owner] and Table S68 says [exploratory].
- Fix: `build_assets.py` lines 2704-2705, replace `"measured"` with `"exploratory, one owner"`.

**A3. Main p8, Section 6, bullet 1.** "every judge, Jev included, clicked 'buy'" is unlabelled and overstated.
- Supp E.1.4 (p86-87, Table S64): one development-split case (cua-18, [screen]). All 10 judges ranked "Buy now" first, but only 7 of 10 would have clicked it in repetition 1. Sol timed out in 2 of 3 reps. Three judges fell back.
- Fix (`sections/m6-gate.tex`): "In one development case (cua-18, [screen]) all 10 judges, Jev included, ranked 'Buy now' first because the task said 'purchase' and no policy said otherwise; 7 of 10 would have clicked it automatically."

**A4. Takeaway 2 headline scope, in 4 of 5 places.**
- 0.581x is the preregistered configuration, which the paper does not ship: H7 failed, so a keyword proxy keeps review/explain on the host.
- The shipped configuration costs about 0.75x of plain Fable (replayed, exploratory; Supp Table S2 last row, Section 8 footnote).
- Only the abstract says "about 0.75x ... (replayed)". Claims table row 2 (p2), conclusion item 2 (p10), Supp summary (p1) and Table S1 (p4) show only 0.581x.
- Fix: add one clause to Table 1 row 2: "shipped config about 0.75x (replayed)". Alternatively remove it from the abstract and state the scope in the Section 4 claim only; but then say so in all places. The point is that all six places say the same thing.

**A5. Supp p55, C.1, first sentence.** "Table S33 repeats ... the main paper's Table 2". The per-request price table is main **Table 3** (Table 2 is the data-sources table). Stale cross-reference.
- Fix: `supp/c-trace.tex` line 3. Replace the literal `Table~2` with `Table~\ref{M-tab:perrequest}` so it cannot drift again. `supp/d-trace.tex` and `supp/f-trace.tex` hard-code "Figure~3", "Section~7" and "Figure~4"; these are correct today but should use `\ref{M-...}` too.

### B. Weaker or imprecise claims

- **B1. Takeaway 1 title** ("best price-quality") and the Section 3 claim ("cheapest and fastest accurate judge"). The post hoc Decisions API run sits above Jev on accuracy (59 vs 55 holdout; 30 vs 23 on real reads) at 1.3-1.7x the price. Its server p95 (136-179 ms) is below Jev's client p95 (216-222 ms) (Supp Table S16). "Fastest" is not established against it.
  - Fix: title "Jev is the cheapest accurate decision model we tested", or keep the title and drop "and fastest". It needs to change in `build_assets.py` TAKEAWAYS so all six places move together.
- **B2. Section 5 title and practitioner box (p7-8).** "switch only when the cache has expired" / "that is the cheap moment to change configuration". The evidence is n = 24 per arm, no interval, exploratory, effort changes only. Section 5 itself says a model switch at expiry "was not isolated".
  - Fix: title "Configure once per session; avoid switching while the cache is warm". Box: "After an idle gap past the cache lifetime a switch looked no dearer (effort changes only, n = 24, exploratory); how much cheaper the new configuration must be is untested."
- **B3. Takeaway 3 "9-13 % cheaper".** The label covers only the preregistered criterion (<= 1.05x). The size of the saving is "descriptive" (Supp S36), and the Fable CI is 0.78-0.98 (2-22 %).
  - Fix: Head macro in `build_assets.py`: "deciding once about 9-13 % cheaper than per turn (descriptive; CI 2-22 %)". Same in all six places.
- **B4. Takeaway 5 "34 % routed in production".** The denominator is "of the sessions Jev judged" (Section 7; Table S68). The workspace-size gate kept 49 % of sessions on the host first. Table 1 compares it with "89 % in the lab", which is the main campaign (97 % is test traffic).
  - Fix: Head "34 % of judged sessions routed in production"; Table 1: "89 % in the main campaign".
- **B5. Main p5, Section 4 bullet 4.** Break-even "about $0.38" is the pair reading. The all-pairs reading used in the rest of that list gives $0.34 (Supp p72, Table S52). Write "about $0.34-0.38".
- **B6. Scenario count.** Main Table 1 (p2) says "Holdout study, 59 scenarios". Abstract, Table 2 and Section 4 say 60. Supp index S34 says 59 (Fable) and 60 (Opus).
  - Fix: Table 1: "60 scenarios (59 usable for Fable)".
- **B7. Claim boxes.** The brief asks for a one-sentence claim. Sections 3, 4, 6 and 7 have 2 sentences, Section 5 has 3. Each box = title + one extra sentence at most; move caveats into bullets. Section 5's "The start-of-session choice needs no decision model" is already a bold run-in paragraph below.
- **B8. Hypothesis tables.** S36 (C.3, p57) and S69 (G.1, p94) are crisp. Takeaways 1, 3 and 4 are also labelled [preregistered] but have no plain-words table: Rule 1 and Rule 2 (B.4, p37-42), the I1-I3 interventions (E.2.3, p90) and the effort/cache items (D). Add 3-5 row tables in the same Question / Threshold / Result / Meaning form.
- **B9. Undefined jargon in main.** "sticky" (Figure 2 labels and caption), "triplets" (Section 5, Table 1), "main-v1", "H1"/"H5" (Figure 2 rows), "frozen configuration", "scenario-reps", "Holm". Define in one sentence in Section 2, or relabel Figure 2 rows (e.g. "main test, decide once").
- **B10. Naming collision.** "S1" means the holdout study, and also Table S1 / Figure S1 in the supplement. Rename the study (e.g. "holdout study H").
- **B11. Table S1 Details column (Supp p4).** Lists "C" and "D"; Table 1 (main) and the supplement summary list "C, G" and "D, G". In `build_assets.py` the TAKEAWAYS tuple has one section key per takeaway; add the second.

### C. Layout (verified fixes in scratch copy)

- **L1. Main p1-2: takeaway list split around Table 1.** Items 1-3 are on p1; Table 1 sits at the top of p2; items 4-5 follow the table.
  - Fix (`sections/m1-intro.tex`):
    1. `\begin{enumerate}[leftmargin=1.6em, itemsep=0pt, topsep=2pt]`;
    2. delete the sentence "We asked where it earns its place in a harness, and where something simpler does as well.";
    3. drop the five "(\cref{sec:...})" pointers and put the section numbers in Table 1's Details column ("Section 3; Supp. B").
  - Result: all five items on p1.
- **L2. Main p6, p7, p8: blank space of 2.9, 1.9 and 1.6 in at the bottom.**
  - Cause: `preamble.tex` line 20, `\preto\section{\needspace{10\baselineskip}}`. With a float-only page top it forces each new section to the next page.
  - Fix: change 10 to 6. Result: main = **10 pages**, bottom gaps <= 1.0 in (except the last page), no new orphan headings; supplement stays 121 pp.
- **L3. Main p10, conclusion items 3 and 5.** "3. Configure model and effort once per session. deciding once ...", "5. ... accuracy. decisions 30x ...".
  - Fix: `sections/m9-limits.tex`: write `\TkTitle{X}:} \TkHead{X}` (colon, as in the abstract) instead of `\TkTitle{X}.} \TkHead{X}`, all five items.
- **L4. Supp p3: TOC spill.** 6 TOC entries (H.3-I) on an otherwise empty page.
  - Fix: `supp.tex` line 32: replace `\clearpage` after `\input{supp/summary}` with `\medskip`. Result: summary + TOC fit pp 1-2, Section A starts p3, supplement = 120 pp (the index updates automatically).
- **L5. Supp p94: Table S69 (the G.1 hypothesis table) sits above the "G The preregistered holdout study" heading.** The `[tbp]` float rises to the page top. Trial fix: `supp/g-hyptable.tex` `[tbp]`->`[H]` plus `\clearpage` before `\section` in `supp/g-s1.tex`. Order is restored (G, G.1, intro, S69) at the cost of +1 page and a 3.4 in blank under Table S68. Without `\clearpage`, `[H]` alone strands the "G" heading at the foot of the previous page. Needs a layout decision.
- **L6. Supp p4: Figure S1 + Table S1 above the "A Setting, data and methods" heading.** Same float-ahead-of-heading pattern. Minor. If L4 is applied the heading moves to p3 anyway; use `[!ht]` on both.
- **L7. Supp near-orphan headings.** p36 "B.3.4 Interventions on dev" with a dangling "On dev:"; p58 "C.4.1 The hypotheses" + one line; p93 "F.2 ..." + one line, table on p94. Minor.
- **L8. Supp blank bottoms (not required, noting).** p27 (3.4 in), p28 (3.6 in), p48 (2.6 in), p87 (2.5 in), presumably unsplittable case boxes (fdbox has `breakable=false`).
- No horizontal overflow on any page of either PDF; claim and practitioner boxes are never split.

## The 10 worst sentences in the main paper (with rewrites)

1. **p5, Section 4 claim** (broken grammar): "Route to a cheaper model only when the host is much dearer once caching is counted, and the extra requests the cheaper model makes."
   -> "Route to a cheaper model only when the host is much dearer once caching and the cheaper model's extra requests are counted; it paid on Fable and lost on Opus in two independent scenario sets."
2. **p4, Section 3 bullet 2** (6 facts in 2 sentences): "Luna (60/63) and Sol (62/63) were +7.9 and +11.1 points more accurate (paired bootstrap +1.6 to +15.9; +3.2 to +19.0), never wrong where Jev was right, at 2.2x and 48x the cost and p95 of 1.8-1.9 and 3.6-4.7 s. The corrected tests could not confirm the gap (Holm p = 0.16 and 0.09) [preregistered]."
   -> "Luna (60/63) and Sol (62/63) scored 7.9 and 11.1 points higher than Jev (95 % CI +1.6 to +15.9 and +3.2 to +19.0), at 2.2x and 48x the cost and with p95 latencies of 1.8-1.9 s and 3.6-4.7 s. After Holm correction the gaps were not confirmed (p = 0.16 and 0.09) [preregistered]."
3. **p7, Section 5 bullet 3**: "After a pause past the five-minute cache lifetime, the first request rewrote the history whatever the configuration (5.8x the writes after a short pause on Fable, 6.2x on Opus); an effort change there added no detectable write cost (66,235 against 67,820 tokens; n = 24 each, no interval computed) [exploratory]."
   -> "After a pause longer than the five-minute cache lifetime, the first request rewrote the whole history in every configuration (5.8x the writes of a request after a short pause on Fable, 6.2x on Opus). An effort change then added no visible cost (66,235 tokens against 67,820 on the plain host; 24 requests each, no interval) [exploratory]."
4. **p5, Section 4** (obscure): "Because two hosts and one cheap model were measured, 'much more expensive' is a modelled threshold: no host lay between Opus's one-to-one and Fable's two-to-one per-request price against Sonnet."
   -> "'Much dearer' is a modelled threshold, not a measured one: we tested two hosts against one cheap model, and none fell between Opus (about Sonnet's price per request) and Fable (about twice Sonnet's)."
5. **p9, Section 7 bullet 4** ("headline 7.1 %" is never defined in the main paper): "Proposal-host agreement is a usage signal, not a correctness label: 0.2 % in production against 11.4 % in test traffic; the headline 7.1 % was mostly decisions that could not match by construction."
   -> "Agreement between Jev's proposal and the host's next action is a usage signal, not a correctness label: 0.2 % in production against 11.4 % in test traffic. An earlier all-traffic figure of 7.1 % was mostly decisions that could not match by construction (1,491 of 1,642)."
6. **p10, Table 4 footnote**: "Without a decision model the shipped configuration identifies them with a keyword classifier; replayed on the holdout sessions this gives about 0.75x of plain Fable, against 0.58x without the safeguard (replayed, not run live; Supplement Section G.3)."
   -> "The shipped configuration finds review and explain tasks with a keyword classifier. Replayed on the holdout sessions (not run live; Supplement Section G.3), it costs about 0.75x of plain Fable, against 0.58x without the safeguard."
7. **p9, Section 7 "A corrected projection"** (3 clauses in 2 sentences): "Recomputed on the same mix (53 % Opus, 46 % Sonnet spend), with Opus at default effort and Sonnet hosts at medium (0.821x), the projection is 0.92x (0.90-0.94) [exploratory]; the correction is documented in the supplement."
   -> "With Opus left at default effort and Sonnet at medium (0.821x), the same spend mix (53 % Opus, 46 % Sonnet) projects 0.92x (0.90-0.94) [exploratory]. The supplement documents the correction."
8. **p2, Section 2** (three ideas in one sentence): "The session-start decision chooses the session's model and reasoning effort once; the shipped default can also use a one-line rule instead of a model (route to the cheaper model unless the workspace has more than 300 files) and a price gate that keeps the host whenever routing cannot pay at current prices."
   -> "The session-start decision chooses the session's model and reasoning effort once. The shipped default can replace the model with a one-line rule: route to the cheaper model unless the workspace has more than 300 files. It also applies a price gate that keeps the host whenever routing cannot pay at current prices."
9. **p5, Section 3 Decisions API paragraph** (string of unlabelled pairs): "It scored 88 against 86 development cases, 59 against 55 holdout cases, 16 against 16 and 30 against 23 real read decisions; only the last difference survived Holm correction (p = 0.039, exploratory)."
   -> "Against the in-run Jev reference it scored 88 vs 86 on development cases, 59 vs 55 on the holdout, and 16 vs 16 and 30 vs 23 on the two splits of real read decisions. Only the last gap survived Holm correction (p = 0.039; exploratory)."
10. **p8, Section 6 bullet 1** (overstated and unlabelled; see A3): "In a purchase case, every judge, Jev included, clicked 'buy' when the task asked and no policy said otherwise."
    -> "In one development case (cua-18, [screen]) all 10 judges, Jev included, ranked 'Buy now' first because the task said 'purchase' and no policy said otherwise; 7 of 10 would have clicked it automatically."

Also worth fixing: the Section 2 paragraph "What makes this evidence strong" is self-congratulatory and runs 50 words; split into three short factual sentences and drop "every number is regenerated from committed evidence" (it is in the code-availability statement).

## What passes cleanly (for the record)

- Five takeaways: same titles, headline numbers, labels and order in the main abstract, Table 1, intro list, conclusion, Supp summary and Table S1. Verified on the rendered text, not only at macro level.
- All macro-fed numbers match `generated/numbers.tex`; spot-checked derived numbers: 9-13 % = 1-0.869 / 1-0.911; 30x = 4.8 s / 159 ms; 87x = 26.9 s / 311 ms; Table 3 per-request prices and shares recompute from the token mix and list prices; Decisions API pairs match Table S16.
- Index of figures and tables: 38 + 74 entries, none missing or extra, every page number correct. Table S74 (cited by the main paper) is on p111.
- Main-to-supplement cross-references for sections (B-H) and "main paper's Section 3/4/5/6/7/8" are correct; the only wrong one is A5.
