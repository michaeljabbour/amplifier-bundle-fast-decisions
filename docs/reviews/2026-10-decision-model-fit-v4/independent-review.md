# Independent review: "Where a Decision Model Fits in an Agent Harness" (v4)

Reviewed: `decision-model-fit-v4.pdf` (9 pp) and `decision-model-fit-v4-supplement.pdf` (21 pp), against the sources, `generated/numbers.tex`, the evidence JSON/READMEs under `docs/evidence/`, and `/tmp/v4-evidence-map.md`. Read-only; nothing in the repo was edited.

**Method note (how I looked at the pages).** I rendered every page at 150 dpi (plus 220 dpi crops of Figs 1-4 and Table 2) and read `pdftotext -layout` for every page. My tooling cannot display images directly, so visual inspection went through a vision model. I treated its output as a lead only, and kept a finding only when I could corroborate it from the PDF text layer (`pdftotext -bbox` geometry), pixel sampling, or the source. Where I could not corroborate a visual claim, it is not in the required list. Findings I rejected: a weaker vision model misread Fig 3's labels; the text layer shows 12.47 and 1.13. Supplement figures S2, S7, S9, S10 and S11 were only skimmed, so I made no required changes there.

---

## 1. Verdict

**Conditional pass: strong paper, not yet ready to send.**

What is good, and should be said louder in the paper:
- Every one of the ~45 numbers I traced matches the evidence files.
- Status labelling is unusually honest. Fig 1 separates preregistered from post hoc, the Decisions API result is reported even though it softens takeaway 1, and the corrected 0.83x -> 0.92x projection is stated openly.
- The structure (one section per takeaway: Claim / Evidence / For practitioners) is what the colleague asked for.
- Length is 9 pages including references, and no running header repeats the title.

What blocks it:
1. **Seven places where wording is stronger than the evidence.** The worst are the abstract's takeaway 3 (8-14 % "[preregistered]"), takeaway 4 (editable criteria), the 0.581x headline, and "a few more points of accuracy".
2. **Takeaways 1, 3 and 4 as the colleague phrased them are only partly supported.** The paper mostly says so in the body but not in the abstract or conclusion.
3. **The end of the paper does not say what is most important.**
4. **One real figure/text inconsistency (Fig 3) and several visible typesetting bugs.** Table 2 prints "0.116,4"; Fig 4 prints "26920"; the takeaway list is split across a page break by a table.

All fixes are text-level or small LaTeX changes. I estimate half a day.

---

## 2. Required changes (prioritised)

Page numbers are PDF pages of the main paper unless prefixed "Supp".

### P1: Claims stronger than the evidence (fix before anything else)

**R1. Abstract (p1) and Section 5 (p6): "deciding once was 8-14 % cheaper ... [preregistered]".**
- *Problem.*
  - The preregistered H3 criterion was only sticky/shipped <= 1.05 (`CONFIRM.md`: "H3 sticky/shipped (<=1.05) ... confirmed"). The size of the saving is descriptive.
  - The quoted 0.862 (0.764-0.994) and 0.917 (0.848-0.991) are the *pair reading*: quality-filtered, 35 and 33 triplets, with an estimator written after the data (Table 1 itself says so).
  - Both upper bounds are 0.994 and 0.991, so the CI lower end of the saving is about 0.6-0.9 %.
  - The unfiltered arm reading (all 46 triplets per host) is 0.869 (0.779-0.983) and 0.911 (0.854-0.970).
  - The "decide-once" (sticky) arm also ran the phase effort map in the sessions that kept the host (about 26 effort changes per session; A0 README), so "once" is not "no switching at all".
- *Fix, Section 5.* Replace the sentence "In the main campaign, deciding the model once ... a saving of 8-14 % [preregistered]" with:
  > "In the main campaign, deciding the model once per session cost 0.87x (0.78-0.98) of re-deciding it every turn on Fable and 0.91x (0.85-0.97) on Opus (all 46 paired triplets per host; the arm that decided once still applied a phase-based effort map on sessions that kept the host). The preregistered criterion was only that deciding once cost no more than 1.05x of re-deciding; the size of the saving is descriptive [preregistered criterion]."
- *Fix, abstract.* "deciding once cost 9-13 % less than re-deciding every turn".

**R2. Section 5 (p6) and Fig 3 how-to-read: "added nothing" / "both bars are equally long".**
- *Problem.*
  - This is an equivalence claim from n = 24 per side, with no interval and no test: 66,235 vs 67,820 tokens, [exploratory].
  - It is the only direct evidence for "switch only when the cache has expired", and it covers effort changes, not model switches.
  - The caveat sits in the last paragraph of the section, not in the Claim.
- *Fix.* Replace "an effort change at that point added nothing (66,235 against 67,820 tokens; n = 24 each)" with:
  > "an effort change at that point added no detectable write cost (66,235 against 67,820 tokens; n = 24 each, small sample, no interval computed)".
  - Fig 3 how-to-read: "after a seven-minute pause the two bars are about the same length (n = 24 each), consistent with the expired cache being rewritten whatever the configuration."
  - Add to the Claim paragraph: "(measured for effort changes only, with five-minute caches)".

**R3. Fig 3 (p6) disagrees with its own text, and its labels are wrong in two ways.**
- *Baseline mismatch.*
  - Text: "11,650 against 900 when nothing changed (12.9x; n = 486 and 859)". The 900 is `sticky_host|unchanged|within_turn`.
  - Fig 3 caption and legend say "plain host, which never switches", and the bar is `anchor|unchanged|within_turn` = 1,133 tokens (label "1.13"). That gives 10.3x, not 12.9x.
- *Label overlap, corroborated by pixel sampling of the bbox.* The grey series' labels ("67.82", "12.47", "1.13") are drawn on top of the hatched orange bars, so they read as belonging to the wrong bar; "1.13" also collides with the axis.
- *Inconsistent decimals.* Orange labels have 1 dp (66.2, 18.0, 11.7), grey ones 2 dp (67.82, 12.47, 1.13).
- *Fix.*
  1. Use one baseline in text and figure. Easiest: make the text say "against 1,130 for the plain host (10.3x; n = 486 and 1,331)", i.e. use `anchor|unchanged|within_turn` in `AoEcUnchanged`, `AoEcX` and `CwWithinUnchangedN`.
  2. Print all labels at 1 dp in thousands (66.2, 67.8, 18.0, 12.5, 11.7, 1.1).
  3. Place the grey labels right of their own bar ends (`anchor=west`, white fill), or add `bar shift`/larger group spacing so a label cannot fall inside the other series' bar.

**R4. Section 4 (p4): the text and Fig 2 use different estimators, and the text's estimator is not labelled.**
- *Problem.*
  - Text: plain Sonnet vs plain Fable 0.577x (0.52-0.65) and vs plain Opus 1.433x (1.25-1.64). These are the pair reading (quality-filtered).
  - Fig 2, same campaign: the arm reading, 0.537 and 1.203, "unfiltered" per the caption.
  - Neither is tagged. The arm reading for the same two contrasts is 0.590 (0.529-0.663) and 1.457 (1.280-1.666).
  - CI precision is also mixed within one paragraph (0.52-0.65 vs 0.542-0.625).
- *Fix.* Use the unfiltered reading in the text, 0.59x (0.53-0.66) and 1.46x (1.28-1.67), with the tag "[preregistered hypotheses, all pairs]". Put the pair-reading numbers in Supp Fig S4 only. Use 3 dp for both ratio and CI throughout the section.
- *Also.* Tag the pilot and train rows in Fig 2 as "[exploratory]" in the caption, and soften the figure title "The same answer, study after study": the Opus pilot is 1.459 against about 1.2 elsewhere. Suggested title: "The same direction in every study".

**R5. Takeaway 1 (abstract p1, Section 3 p3, Fig 1 p4): five wording problems that make it look both overstated and understated.**
- (a) *"dearer models bought a few more points of accuracy" (abstract, Sec 3 Claim, Fig 1 how-to-read).*
  - The gaps are +7.9 and +11.1 points (5 and 7 of 63 cases).
  - In both cases the dearer model was never wrong where Jev was right: `candidate_only` 5 vs `baseline_only` 0, and 7 vs 0.
  - Holm is computed over a 13-candidate family, which includes local arms, so "did not reject" partly reflects family size.
  - Replace with: "dearer models were 8-11 points more accurate (5-7 of 63 cases, never wrong where Jev was right); the preregistered corrected tests could not confirm the gap."
- (b) *"a real but small accuracy premium" (Sec 3).* This asserts "real" from an unadjusted bootstrap CI right after reporting a non-significant corrected test, and "small" for 8-11 points. Replace with: "an apparent accuracy premium of 8-11 points that the corrected preregistered tests could not confirm".
- (c) *"Clef ... matched Jev's accuracy (57 against 56)" and "Decisions API matched or exceeded Jev" (abstract has no [post hoc] tag).* Point estimates are not equivalence. Replace with "scored 57 against an in-run Jev's 56 [post hoc, no test]". Abstract: "in a post hoc run, OpenAI's Decisions API scored the same or higher on all four splits (59 vs 55 on the holdout) at 1.3-1.7x the price".
- (d) *Coverage omitted.* On the real-read splits the Decisions API automated about half as many decisions as Jev: trace-holdout coverage 16.7 % vs 35.7 %, trace-dev 47.6 % vs 66.7 %. Part of its accuracy lead there is more fallbacks. Add to the Section 3 Decisions API paragraph: "On real read decisions it automated fewer (7 against 15 of 42), so part of its accuracy gain is more fallbacks to the host."
- (e) *Price and reliability wording.*
  - "similar price" appears in Fig 1 how-to-read (p4), the Sec 3 practitioner box (p3), and Supp S2.1 Key idea (Supp p5). It contradicts "1.3-1.7x" in the same paper. Say "at 1.3-1.7x the price" everywhere.
  - "9 of 1,296 requests failed in transport" is reported for the Decisions API only. Jev had 4 transport failures in the same run (summary.json `invalid`). Report "9 for the Decisions API and 4 for Jev", also in Supp Table S2.
  - Fig 1 how-to-read says moving right "buys a few points of accuracy at two to fifty times the price", but Clef-Flash (to the right, less accurate) and Luna-D (1.4x) are exceptions.
- *Suggested takeaway-1 sentence (abstract and Section 3 Claim), to meet the colleague's wording without over-claiming:*
  > "Among the system-1 models we tested, Jev is the best price-quality tradeoff when cost and latency matter: it is the cheapest and fastest accurate judge, and no dearer model was shown more accurate in the preregistered test. OpenAI's Decisions API is the main challenger (post hoc: same or higher accuracy at 1.3-1.7x the price, fewer automated real reads)."

**R6. Takeaway 4 is overstated in the abstract (p1) and the Section 6 title (p7).**
- *Problem.*
  - "pair the model's editable natural-language criteria with a deterministic guard: the guard removed every side-effect error we measured". The 38 -> 0 result is across the 9 judges that had such errors.
  - Jev made 0 targeted errors on the 21 holdout computer-use cases at the shipped gate (I1 and I2 both report "applicable: False" for Jev), so Jev-plus-guard is unproven on the holdout. On dev, Jev made 1-2 per repetition.
  - The natural-language clause was not confirmed pooled (22 -> 20; 1 of 3 judges).
  - Editability, customization and comparison with a classifier were never tested. The body says so; the abstract and the heading "an editable gate" do not.
- *Replace the abstract sentence with:*
  > "Fourth, for risky actions a deterministic guard on irreversible verbs removed all 38 side-effect errors made by nine judges on the holdout [preregistered]; a plain-text risk rule in the prompt helped only some judges (not confirmed overall), so the decision model's potential edge over a fixed classifier, criteria a user can rewrite, remains untested."
- *Section 6 title:* "Risky actions: a deterministic guard works; editable criteria are untested".
- *Add one sentence to Section 6 Evidence:* "Jev itself made no such error on the 21 holdout computer-use cases at the shipped gate; the guard matters for the other nine judges and for Jev on the development cases (1-2 per repetition)."

**R7. The 0.581x headline is not what the paper recommends (abstract p1, Sec 4 Claim p4, vs Section 8 p8).**
- *Problem.* 0.581x is the frozen package "route + medium effort" with no review/explain safeguard. Section 8 recommends keeping review/explain on the host, with a replayed (not rerun) ratio of 0.749x (0.699-0.799). A reader following Table 3 should expect about 0.75x, not 0.58x.
- *Fix, abstract.* "it cost 0.58x the plain host on Fable 5.1 (about 0.75x with the review/explain safeguard we recommend, replayed rather than rerun) and 1.26x on Opus 5.5, both replicated on fresh scenarios".
- *Fix, Section 4 Claim.* "On Fable, routing alone cost 0.59x and the full package 0.58x; on Opus it cost 1.26-1.46x."

**R8. Abstract last sentence is wrong as written (p1).** "All results come from one model provider" is false: Section 3 compares Jev, OpenAI, Cloudflare and local models. Replace with: "All session results use one provider's models (two hosts, one routing target), scripted tasks and list prices; the judge benchmarks use model-written labels."

**R9. Supp S2 (Supp p2): "Two blind reviewers ... kappa = 1.00" reads as human review.** The evidence README says "All reviewers are Anthropic models" (separate agents). Replace with: "Two blind reviewer agents (language models, not people) checked the labels against a written guide; their agreement with the final labels was kappa = 1.00, which shows the labels follow the guide, not that they match operator preference." Do the same for the real-decision reviewers (kappa 0.84 / 0.51-0.57).

**R10. Supp Fig S8 (Supp p12) caption misstates which subgroups breach the margin.** Computing d - dm from `s1-subgroups.dat` gives lower bounds below -0.05 for:

| Subgroup | Lower bound |
|---|---|
| task: mixed | -0.071 |
| task: docs | -0.069 |
| task: explain | -0.078 |
| family: mixed | -0.067 |
| family: knowledge | -0.056 |
| task: review | -0.050 |

The caption and title name only "explain and mixed work", and write "review touches it (-0.050)" as if it were the estimate (the estimate is -0.019). Replace with: "Lower bounds fall below the -0.05 margin for the explain (-0.078), mixed (-0.071) and docs (-0.069) tasks and the mixed and knowledge families; review's lower bound is -0.050. Subgroups hold 9-20 scenarios; treat as hypothesis-generating." Retitle: "Every subgroup saves money; quality intervals for several subgroups are too wide to rule out a loss."

### P2: Structure and the colleague's criteria

**R11. The five-takeaway list is split across p1/p2 by Table 1 (p1-p2).** Items 1-3 end p1 (0.29 in left); Table 1 floats to the top of p2, before the "2 Setting, data and measures" heading, and items 4-5 follow it. The most important list in the paper is cut in half, and the "Data" paragraph on p3 refers back to a table one page earlier.
- *Fix.*
  1. Move the Table 1 float to after the "Data" paragraph (`[H]`, or place the environment after that paragraph and `\FloatBarrier`).
  2. Trim the abstract (~230 -> ~190 words) and intro paragraph 2 by ~4 lines so all five items sit on p1.
  3. Add a strength tag to each item. Suggested replacement for the five lines:
     > 1. Jev is the best price-quality decision model we tested; OpenAI's Decisions API is the challenger (§3; preregistered + post hoc).
     > 2. Route to a cheaper model only when the host is much more expensive once caching and request volume are counted (§4; preregistered, two hosts).
     > 3. Configure model and effort once per session; change only after the cache has expired (§5; once = preregistered, expiry = exploratory, effort only).
     > 4. Guard risky actions with a deterministic rule plus the model's plain-text policy; editability is untested (§6).
     > 5. Real telemetry measures latency and usage mix, not accuracy, and showed routing applies far less often than in the lab (§7; exploratory, one owner).

**R12. The paper does not end by saying what is most important (Conclusion, p9).**
- *Problem.* The conclusion is one paragraph of positioning. It does not restate the five takeaways, rank them, or say which is the most robust. Section 8 ends on a side result (the keyword proxy, 0.749x).
- *Fix.* Replace the Conclusion body with a ranked list, and move the keyword-proxy paragraph into the supplement or into the Table 3 footnote:
  > "What matters most, in order of how well it is supported. (1) Routing pays only when the host's price, weighted by cache reads and writes and the cheaper model's extra requests, is far above the target's: it saved 42 % on Fable and cost 25 % more on Opus, on two independent scenario sets [preregistered]. (2) Pick model and effort once per session; deciding once cost no more than re-deciding every turn and avoided cache rewrites [preregistered criterion, exploratory mechanism]. (3) Jev is the best price-quality decision model we tested; the Decisions API is the one to re-test [preregistered + post hoc]. (4) Use a deterministic guard for risky actions; editable policy is promising but untested. (5) Use telemetry for latency and usage mix, never for accuracy or savings."

**R13. Data section is one sentence plus a table; data caveats recur in §§3-9 (colleague: "no relitigating after Section 3 until the conclusion").**
- *Problem.*
  - §2 "Data." is one sentence plus Table 1.
  - The same weaknesses reappear in Section 7 ("321 classified as production because they carried no test tag"), Section 6 ("We ran no live risky actions ..."), Section 8 ("not replicated live"), and Section 9, which nearly duplicates Table 1's weakness column (one provider, scripted, list prices, small and rebuilt, one owner, LM labels).
- *Fix.*
  1. Expand "Data" to 4-5 sentences covering how each source was generated and its main strength and weakness. Content is in the supplement: model-written labels checked by model reviewers; real-decision cases fingerprint-matched and clipped to 2,048 characters; the 60-scenario S1 panel smoke-tested before preregistration, which found prompt or grader defects in 30 scenarios that were then repaired; telemetry production class is 321 of 398 by default.
  2. Delete Section 9 and add two sentences to the Conclusion ("Scope: ...").
  3. Cut per-section caveats to one clause that points to Table 1.
  4. Keep claim-specific limits that change what the claim means (e.g. "effort only" in §5), because the colleague's "no relitigating" is about data, not about the scope of a claim.

**R14. Undefined terms an outside reader will hit.**
- "Jev" is used in the abstract before it is defined (first defined in §2 p2). Write "Jev, a hosted typed-decision service".
- "test sessions/test traffic" in Section 7 is undefined (it is sessions tagged test or evaluation, including the authors' own benchmark runs). Define it once in Table 1, in the telemetry row.
- The supplement uses "S1" for both the holdout study and Section S1 (Supp p9: "it must replicate in S2 before it ships" while Section S2 is the judge benchmarks). Rename the study (e.g. "the holdout study, HS") or number supplement sections A1-A8.

**R15. Strengths of the work are not stated.** For readers who work with system-1 models, the strong points are scattered: paired same-start sessions, a fresh 60-scenario preregistered holdout (1,224 sessions), replication of both routing directions, regenerate-from-evidence numbers, and honest reporting of a result that cut against the incumbent. Add after Table 1:
> "What makes this evidence strong: sessions are paired and start together from one frozen workspace; the central routing result was preregistered and replicated on 60 fresh scenarios (1,224 sessions); every number is regenerated from committed evidence; and results that cut against our default (the Decisions API, the corrected projection) are reported in the body."

### P3: Typesetting and consistency bugs

**R16. Table 2 (p5): "0.116,4 / 0.055,4 / 0.054,8".** siunitx groups the decimals ("group-digits=all" with `group-minimum-digits=4`). Fix in the preamble: `\sisetup{group-separator={,}, group-digits=integer, group-minimum-digits=4}`; or print 4 dp "0.1164". Check every `S[...]` column.

**R17. Fig 4 (p8): data label "26920" has no separator** while the axis reads "10,000". Print "26,920". The same applies to any other label above 999 in other figures.

**R18. Fig 2 (p5) and similar figures: data labels collide with the frame and gridlines.** "0.529" sits on the top frame line (the frame is at y = 246.4 pt and the label spans 244.8-252.3 pt); "1.199", "1.203" and "1.459" are struck by the 1.2 and 1.5 gridlines. Same pattern in Supp Figs S3, S5, S6, S8 and S12 ("1.000" and "0.991" struck by the x = 1 line; "49.0" on the frame). Fix: add `ymin/ymax` padding of half a row; give `nodes near coords` a white fill (`fill=white, fill opacity=0.85`); or move labels to a fixed right-hand column.

**R19. Cross-document links render cyan (p9 "Supplement Table S1"; Supp p9 "main paper, Section 8").** hyperref's default `filecolor=cyan` applies to xr-hyper links. Add `filecolor=okblue!65!black` to `\hypersetup` in both documents.

**R20. Label hyphenation (p8 "[prereg-/istered]"; p3 "equiva-/lence"; p3 "prereg-/istered").** Wrap the label macros in `\mbox{...}` and add `\hyphenation{pre-reg-is-tered equi-va-lence}` for the body.

**R21. Mixed numeral fonts.** Math-mode numerals are Computer Modern (CMR10/CMMI10 in `pdffonts`) while body text is Libertinus ("p = 0.16", "-0.05", "-0.063", all pgfplots tick labels). Fix: load `\usepackage{libertinust1math}` after `libertinus`, or stop setting numbers in math mode.

**R22. Supp Fig S1 caption (Supp p3):** "the preregistered run, then (below the gap) the post-hoc run". In the figure the post hoc rows (Clef, Clef-Flash, Jev in-run) are *above* the gap. Fix the caption: "(above the gap)". Also drop "(companion report, Part I)" from the how-to-read, because that report is not cited or available.

**R23. Supp S7 and "Changes in this version" (Supp p19-20) are internal process, not value for outside readers.** They refer to a v3 and a "companion technical report" outsiders never saw ("Jev is described as the low-cost point ... rather than as the most accurate per dollar"). Cut both, or move them to a repository CHANGELOG. Also: Table S1 lists evidence packages by repo folder name (e.g. `2026-10-06-holdout-v3`). Give each a human title and date and keep the folder name only in the repo; folder names are close to the "no local paths" rule. Scenario ids (click-flow-explain, go-bowling, peewee-filterfk, bleach-sanitize-review) and freeze strings in code font (`always_route | strong default | scope off | keep none`, Supp p9, which break across lines mid-expression) should be replaced by prose or put in a display block.

**R24. Smaller consistency items (batch fix).**
- Supp p2: "kappa between 0.51-0.57" -> "kappa 0.51-0.57".
- Supp p17: "($-1.80)" -> "-$1.80".
- Supp Table S4: signed CIs "(-0.028-0.002)" -> "(-0.028 to 0.002)" (the main paper already uses "to").
- "post hoc" vs "post-hoc" (main p4 caption and Supp captions use the hyphenated form; labels and body use the unhyphenated form). Pick "post hoc".
- Fig 3/Fig 4 and others carry in-figure titles that duplicate the caption, and the legend sits above the title. Remove in-figure titles.
- Table 3 "Evidence" column says "S1", which a reader will take as a section. Use "holdout study".

---

## 3. Optional improvements

1. **Add a "what it took" sentence per section.** The paper has a few ("Per-token list prices misled", "A corrected projection", "post hoc"), and more are available in the evidence:
   - The cache-aware per-turn planner (3 scenarios, exploratory) predicted +$1.35/+$0.31 savings on Opus and measured -$1.54/-$0.80, the wrong sign (caching survey); this motivates "configure once".
   - The first frozen rule (shorter prompt -> host) did not generalise (0.628x vs 0.513x on test).
   - 30 of 60 S1 scenarios needed prompt or grader repair before preregistration (Supp S4).
   - The 7.1 % "agreement" headline was mostly unmatchable decisions. Put this in §7 in one line, framed as what telemetry cannot measure, rather than relegating it to the supplement.
2. **State the equivalence margin where H2 is cited (p6):** "equivalent within +-5 % (90 % CI 1.000-1.019)". Right now the reader must go to the supplement.
3. **Add pointers to the supplement** at the end of each section ("Details: Supp S2, Figs S1-S3"). The main text currently has one hyperlinked supplement reference (the availability paragraph), and "the supplement" otherwise.
4. **Fig 2 and S-figures:** the labels are small relative to the axis text; consider 8 pt data labels and thicker whiskers.
5. **Page 5 has 1.85 in blank at the bottom** because Fig 3 floats to p6. Moving Fig 3 after the Section 5 Claim paragraph, or shrinking Fig 2, closes it. The last page (p9) is 60 % full; there is room for R12's conclusion.
6. **Author block.** "Amplifier" (an AI system) is listed first with a Microsoft affiliation. Confirm this against the venue and Microsoft authorship policy, or move it to an acknowledgement.
7. **Sec 3 "For practitioners" box:** "fast enough for interactive use" depends on the network. Jev's client p95 was 216-222 ms on the clean path but 3.4-4.5 s on the slow-network run, with up to about 9 % of Jev calls over the 3 s deadline (dev split). Add "on a clean network path".
8. **Table 3 wraps heavily** ("Any harness" cell is six lines; "Medium (0.821x the default)" breaks inside the parenthetical). Set the last column narrower and the second wider, or drop the "Evidence" column.
9. **Supp pp17-19:** the YAML listing splits across pages after "effort_routing:" and leaves one line of the next listing at a page bottom. Wrap listings in `\begin{minipage}` or use `\Needspace`.
10. **Supp S4.4/S4.5 are stub sections** whose figures float pages later; fold each into the section of its figure.
11. **References.** Two references is thin for "others working with system-1 models"; consider adding public references on prompt caching and on cascade/routing work beyond RouteLLM and FrugalGPT.

---

## 4. Criteria checklist

| # | Colleague's criterion | Verdict | Justification |
|---|---|---|---|
| 1a | 8-10 pages main, rest in supplement | **Met** | Main body is 9 pp including references; supplement is 21 pp. |
| 1b | "At the end it should be clear what is most important" | **Not met** | Conclusion does not restate or rank the takeaways; §8 ends on a side result (keyword proxy). See R12. |
| 2a | Exact title | **Met** | "Where a Decision Model Fits in an Agent Harness"; PDF metadata matches. |
| 2b | Header below the title fixed | **Met** | No running header repeats the title (v3 bug gone). Byline, affiliation and date are clean. Confirm the AI "author" (optional #6). |
| 3 | Abstract clear on takeaways, does not undermine confidence | **Partly** | Five numbered findings, and the "labelling artefact" no longer leads. But takeaway 1 is immediately undercut by the Decisions API clause, takeaway 4 is overstated, "one model provider" is wrong, and there are no status tags. See R5-R8. |
| 4a | Structured around takeaways, not a story | **Met** | One section per takeaway with Claim / Evidence / For practitioners. |
| 4b | "What it took to get there" sprinkled in | **Partly** | A few instances ("list prices misled", "corrected projection", "post hoc"); several strong ones are left out (optional #1). |
| 5 | Data compartmentalised in one section; no relitigating after §3 | **Partly** | §2 + Table 1 exist, but "Data" is one sentence, Table 1 sits before its section, and caveats recur in §§6-9 (Section 9 duplicates Table 1). See R11, R13. |
| T1 | Jev best price/quality among major system-1 models | **Partly** | Paper deliberately downgrades to "low-cost point" because post hoc Decisions API matched or exceeded it at 1.3-1.7x. Honest, but wording is muddled and a few phrasings mislead. See R5. |
| T2 | Routing saves money only when the host is much more expensive, caching included | **Met** | Both directions replicated on fresh scenarios, price gate predicts both, and the "threshold is modelled, not measured" caveat is stated. Fix the estimator mismatch (R4) and the headline (R7). |
| T3 | Configure once; switch only after cache expiry unless substantially cheaper | **Partly** | "Once" is supported (preregistered criterion <= 1.05). "After expiry" rests on n = 24, effort only, exploratory. "Substantially cheaper" was never measured; the paper says so but only at the end of §5. See R1, R2. |
| T4 | Usable as a customisable risk filter (unlike a specialised classifier) | **Partly** | The deterministic guard is solid (38 -> 0). The editability and the classifier comparison are explicitly untested, honestly in the body, not in the abstract. See R6. |
| T5 | Takeaways from real-usage telemetry | **Partly** | §7 contains real findings (30x faster, routing applies to one third of production sessions, no production Fable use, estimates vs measurements). It is framed as "how to use telemetry", and the abstract lists no numbers. |
| 6a | No local file paths | **Met** (main) / **Partly** (supp) | Main has a GitHub URL and commit only. Supp Table S1 lists repo folder names, and scenario ids and config strings appear in code font. See R23. |
| 6b | No small formatting bugs | **Not met** | Table 2 "0.116,4"; Fig 4 "26920"; Fig 3 label overlap and mixed decimals; label hyphenation; cyan links; mixed numeral fonts; Supp Fig S1 "below the gap". See R16-R24. |
| 7 | Value for others working with system-1 models; highlight strengths | **Partly** | Practitioner boxes are good. The strengths are not stated (R15), "Jev" is undefined in the abstract (R14), and the supplement carries version-history process material (R23). |
| S | Statistical language and labels | **Partly** | Very good where it exists (Fig S1, S2, the H7 wording, the "not confirmed" I1). Gaps: R1, R2, R4, R5, R9, R10. No false equivalences except R2. |

---

## 5. Numbers verified

All match, unless marked.

**Judge benchmark** (`2026-09-30-judge-benchmark/holdout/summary.json`):
- Jev 55/63 correct, $18.41 per M decisions (`cost_usd_per_1m_jev` = 18.409). Matches the text and Fig 1.
- Luna 60/63 (0.9524), $40.46 -> 2.2x. Sol 62/63 (0.9841), $889.37 -> 48.3x, printed "48x". (The evidence map's $894/49x is a different run; the paper's figure matches this summary.)
- Luna-Jev +7.9 points, CI [+1.6, +15.9], Holm p = 0.156 (printed 0.16). Sol-Jev +11.1, CI [+3.2, +19.0], Holm p = 0.094 (printed 0.09).
- Discordant cases: Luna 5 vs 0, Sol 7 vs 0.
- Wrong-auto Jev 1/63 (1.6 %). Rule-1 margins (0.98 valid, 500 ms, 2x cost) confirmed.

**Decisions API** (`2026-10-06-openai-decisions/summary.json`):
- Accuracy 88/90 vs 86/90; 59/63 vs 55/63; 16/21 vs 16/21; 30/42 vs 23/42.
- Price ratios computed from `usd_per_1m`: 1.27x, 1.39x, 1.66x, 1.65x, i.e. 1.3-1.7x.
- Server p95 136-179 ms. Requests 1,296. Invalid 9 (Luna) and 4 (Jev), so the paper reports 9 only (R5e).
- Coverage 71.1/75.6, 68.2/63.5, 47.6/66.7, 16.7/35.7 (R5d).

**S1 holdout** (`s1_result.json`):
- H1 0.581 (0.542-0.625), turn-pass -0.013 (-0.028 to 0.002).
- H2 1.008 (90 % CI 1.000-1.019); 4 of 120 discordant. H3 0.999 (0.984-1.017). H4 0.992 (0.974-1.009).
- H5 1.255 (1.197-1.321). H6 1.014 (0.996-1.032 at 90 %).
- H7 0.616 (0.565-0.672), turn-pass lower bound -0.063.
- Freeze tables have 23 rows per host (22 Fable candidates), as in Supp Fig S9. `RESULT.md`'s "24 rows" is stale; the paper is right.

**Main campaign:**
- `CONFIRM.md` pair reading: Fable sonnet 0.577 (0.516-0.654); Opus sonnet 1.433 (1.253-1.640); H3 0.862 (0.764-0.994) and 0.917 (0.848-0.991). The arm values differ (R1, R4).
- Fig 2 data: pilot 0.529/1.459; train 0.571/1.199; test 0.537/1.203; S1 0.581/1.255.
- Effort follow-ups 0.821 (0.781-0.861) and 0.860 (0.833-0.885).

**Table 2:** recomputed from list prices and the quoted token mix.
- Fable $0.11641, Opus $0.05541, Sonnet $0.05484.
- Shares match (Fable 58/19/23, Opus 49/32/20, Sonnet 37/48/15).
- Sonnet/Fable 0.471 and Sonnet/Opus 0.990; predicted 0.524 and 1.365.

**Cache:**
- A0 `summary.json`: 11,650.4 (n = 486) vs 899.9 (n = 859) = 12.95x (the 12.9x in the text is the *sticky* unchanged baseline; see R3).
- Plain-host within-turn baseline is 1,132.6 (n = 1,331), which is what Fig 3 plots.
- Long gap 66,235.0 vs 67,819.5, n = 24 each. Short gap 17,959.6 vs 12,467.2. Gap-write ratios 5.8x and 6.2x (from `gapwrites.dat`: 65.062/11.296).

**Telemetry** (`a1-observatory`):
- 398 production, 77 tagged, 321 default; 464,524 events; 19-day window.
- Host p50 4,828 ms, p95 26,920 ms; Jev p50 159 ms, p95 311 ms (n = 248) -> 30x and 87x. Qwen 48/93 ms.
- First start-tier decisions: 105/214 = 49 % scope gate; 35/103 = 34 % cheap; test 113/117 = 97 %.
- Shadow agreement 117/1,642 = 7.1 %; 117/151 = 77.5 %; production 1/633 (0.2 %); test 113/991 (11.4 %).
- 12 effort changes in 12,094 production requests, vs 828 in 3,752 test requests (README).

**Risky actions:**
- I2: 38 -> 0 across 9 judges, coverage cost 1.6-7.9 points, accuracy change 0 (Jev "applicable: False").
- I1: 22 -> 20, confirmed 1 of 3.

**Other:**
- Prices (10/50/0.25/12.50; 4/20/0.20/5; 3/15/0.30/3.75).
- Spend $3,527.29 (main), $4,975.51 (S1).
- Evidence-map items I could not re-derive from files and left unverified: 0.92x recompute (derived in `build_assets`), $222.66 receipts, and the Fig S12 shares.

**Corroborated visual findings** (geometry or pixel evidence):
- Fig 3 grey labels sit on the orange bars (R3).
- Fig 2 "0.529" under the frame line (R18).
- Table 2 comma-decimals (R16).
- Fig 4 "26920" (R17).
- Cyan cross-document links on p9 (R19).
- `pdffonts` shows CM math fonts alongside Libertinus (R21).
- No text-on-text overlaps in either PDF; no lines beyond the margin; the 9-page budget is held.
