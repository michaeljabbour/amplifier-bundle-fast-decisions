# v4 supplement restoration: independent completeness audit

Audited: `decision-model-fit-v4-supplement.pdf` (108 pp; 38 figures S1-S38, 66 tables S1-S66; Sections A-H) and `decision-model-fit-v4.pdf` (9 pp), uncommitted working tree on `v4/supplement-restore` (PDFs dated Oct 8 03:45). Earlier reports read from `origin/main` (JB 47 pp, v2 64 pp, v3 32 pp). Inventory: `/tmp/v4-restore-inventory.md` (218 rows, 198 unique; reproduces its own 49 / 65 / 84 count before the rebuild).

Method: `pdftotext -layout` of all five PDFs; every inventory row looked up by caption, heading or key phrase in the rebuilt PDFs; every restored table compared token-by-token with the earlier PDF; sentence-level containment scan of all three earlier PDFs against supplement + main text (to find prose that is in neither); page-image rendering and geometry checks for layout.

## 1. Verdict

**No inventory item is now MISSING.** 180 of 198 unique items are fully PRESENT, 18 are CONDENSED (each with a residual that can be named), 0 are MISSING. The 84 formerly-missing items: 81 are now PRESENT and 3 CONDENSED (JB-60, 61, 62). The 65 formerly-condensed items: 53 PRESENT, 12 still CONDENSED. Three formerly "present" items (P2-22, P2-84, V3-20) are re-graded CONDENSED because the earlier "present" judgement was lenient (named detail is in neither PDF).

The rebuild is a verbatim restoration, not a rewrite: every restored table matches its source numerically, every restored figure has a caption, a "How to read it" note and at least one text reference. The remaining problems are not missing figures. They are (a) internal contradictions created by pasting earlier-report text without reconciling it, (b) mechanical-scrub garbling, (c) leftover directory fragments, (d) main-paper numbers that have no supplement table.

## 2. Counts

| Scope | Unique items | PRESENT | CONDENSED | MISSING | Was (present / condensed / MISSING) |
|---|---|---|---|---|---|
| Judge benchmark | 62 | 56 | 6 | 0 | 4 / 26 / 32 |
| v2 companion | 89 | 83 | 6 | 0 | 8 / 30 / 51 |
| v3 | 47 | 41 | 6 | 0 | 37 / 9 / 1 |
| **Unique (duplicates and superseded removed)** | **198** | **180** | **18** | **0** | **49 / 65 / 84** |
| All rows | 218 | 198 | 20 | 0 | 53 / 72 / 93 |

Floats now in the supplement: 38 figures and 66 tables (was 12 and 6). Of the inventory's figures and tables, every one is present except as noted in the CONDENSED rows (JB-23 dev points; JB-59/60 survey table/footnote).

## 3. Author's intentional non-restorations: do the reasons hold?

**JB-57..63 ("superseded by v2's caching survey"): hold for 57, 58, 63; do not hold for 59, 60, 61, 62.** v2's version of the survey is itself a cut-down of the JB §10.4 text, and the rebuild restored v2's version. JB-58 -> Table S47 (identical), JB-63 -> Table S27, JB-57 -> D.1 prose: fine. What is lost relative to JB (and absent from v2): the same-configuration table with CIs and pair counts (Fable 0.49 [0.42-0.59] -> 0.62 [0.46-0.74]; 204/45/168/39 pairs); "How much the rebuilds cost" (138 switches, 110 at turn boundaries, turn-2 cost 1.93x/1.13x Opus, 1.59x/0.67x Fable); "Warm first requests" (83 % vs 67 %; re-normalised 1.16-1.27); the "42 %" footnote on Table S50 and the "593 anchors behind 903 pairs" caveat; the "84 of 90 Opus pairs from the 3 tuning scenarios" bullet. Priority Low-Medium (a superseded study), but "superseded" is not accurate for these four.

**Summary/recommendation boxes: hold for P2-21, P2-83, V3-01, V3-02, V3-41, V3-42, V3-47** (main paper carries them: §4 "Why we measured whole sessions", Table 3, abstract, §9). Caveat on V3-47: the "S2-S5 programme" list is now nowhere (it pointed at a repository design file; defensible). **Do not fully hold for P2-01, P2-02, P2-22, P2-84, P2-85:**
- P2-01: the spend-vs-geometric-mean statement (typical saving 44 %; spend -37.3 % over all scenarios, -42.4 % on the test split) survives only inside review response H.7 #2 (p106). $5.31 -> $3.33 is in C.3.2 without the percentages.
- P2-02: "a judge that never acts is useless; one that always acts is dangerous" is gone; safe/unsafe box (E.1.3) and usefulness rule (B.6.1) carry most of it.
- P2-22: the supplement's receipts text (F.1) is the telemetry claim; v2's own check is lost (35 same-model pairs: receipts claimed $2.22, measured -$2.80; "the policy grading its own homework"). D.2 (p70) still cites "the one DK had raised (Section 4 of the main paper)", which the main paper does not contain.
- P2-84: "the Opus result does not depend on effort: sticky-on-Sonnet at medium still 1.18x (1.11-1.27)" has no home (1.182 appears only inside the A.4 matched-effort arithmetic).
- P2-85: "Caching guidance (hypotheses)" (5 bullets), "How to use the numbers", "What to measure next" (longer sessions; live predictions; new-host price check; larger sample for final-test losses), "lowering host effort avoids the task-type quality losses" are in neither PDF. Main §4/§5 "For practitioners" cover the gist only.

## 4. Spot-checks

### (a) 22 restored numbers against the earlier PDFs (exact string match in both)

| # | Supplement location | Value | Source | Match |
|---|---|---|---|---|
| 1 | Table S18 (Sol row) | 62/63, 92-100 %, 0 wrong, cov 47, p50 2,131, p95 4,252, $889.37 | JB Table 8 | identical |
| 2 | Table S18 (Jev row) | 55/63, 77-93 %, 1 (0-8 %), 40, 160, 222, $18.41 | JB Table 8 | identical |
| 3 | Table S24 (Luna) | $121/month, 95,238 wrong auto, 81 %, p95 1,850 | JB Table 17 | identical |
| 4 | Table S21 (Jev) | 43/2, 36/1, 32/0, 17/0, 4/0 | JB Table 11 | identical |
| 5 | Table S20 | Jev vs tev1 4B accuracy +12.7, Holm 0.27 | JB Table 10 | identical |
| 6 | Table S25 (Jev) | 23/42, 40-69 %, 5 wrong, upper 25 %, 15 auto, 10 reads, 163/234 ms | JB Table 19 | identical |
| 7 | Table S17 (Qwen3 0.6B) | -35.6 (-45.6 to -25.6) <0.001; +17.8 (+8.9 to +26.7) 0.005 | JB Table 7 | identical |
| 8 | Table S28 (Clef holdout) | 57/63, 3 wrong, 46 auto, 391/722 ms, 0/378, $65.2 | v2 Table 3 | identical |
| 9 | Table S33 (Fable sticky) | 38/46, 0.558 (0.49-0.64); arm 0.537 (0.48-0.61) | v2 Table 22 | identical |
| 10 | Table S34 (H3 Fable) | 0.862 (0.76-0.99) | v2 Table 23 | identical |
| 11 | Table S37/S45 | Fable all tasks sticky 1,980; bugfix 1,346 (848 to 1,882) | v2 Tables 26, 41 | identical |
| 12 | Table S48 ($0.35 row) | 1.03, 1.15, 1.17 | 0.99, 1.10, 1.19 | v2 Table 11 | identical |
| 13 | Table S36 (Fable shipped) | 140, 3.56, 1.37, 0.97, 0.61, 0.49, 50.6, 4.68 M | v2 Table 25 | identical |
| 14 | Table S57 | Fable medium/default 0.860 (0.833-0.885) | v2 Table 35 | identical |
| 15 | Table S42 (Opus sticky) | 1.46, 1.11, 1.199 (1.11-1.30), 1.203 (1.09-1.33), 1.249 | v2 Table 38 | identical |
| 16 | Table S62 (H1, H7) | 0.581 (0.542-0.625), -0.013; 0.616 (0.565-0.672), -0.028, Holm 0.120 | v3 Table 4 | identical |
| 17 | Table S50 (4-turn Fable) | 75 pairs, 33 switches, 27 % | v2 Table 9 | identical |
| 18 | Table S10 (total) | 49 attempts, 176 sessions, $103.97 | v2 Table 21 | identical |
| 19 | Table S40 (sticky/Fable) | 46, 0.913, 0.935, $99.82 | v2 Table 36 | identical |
| 20 | Table S41 (Fable) | 28, 0.968, 0.94-1.00, 0.097, 0.069 | v2 Table 37 | identical |
| 21 | Table S54 (explain) | 3, 2,315, 1,912 to 2,804, -0.143 | v2 Table 32 | identical |
| 22 | Table S39 (Fable sticky) | 140, 0.943, 0.979, 6/1, p 0.13 | v2 Table 28 | identical |

Also zero numeric differences (token-diff) for Tables S13, S15, S16, S19, S25, S31, S49, S61, S63 and for the data labels of all 38 figures against their source figures (residual diffs are page headers/axis ticks). Only formatting differs: v3 "(-0.063-0.013)" is now "(-0.063 to 0.013)"; H2 CI 1.000-1.022 (95 %) became 1.000-1.019 (90 %, equivalence test, footnoted).

### (b) Figures: caption, "How to read it", text reference

All 38 figures: exactly one caption each, a "How to read it" note within the float, and at least one in-text reference. **Tables:** 8 of 66 are never cited in prose: S39, S42, S50, S55, S56, S57, S60, S61 (see gap G10). No figure is duplicated (main Fig 1 is a redraw of Fig S12 with the Decisions API point; main Fig 3 and Fig 4 have no supplement counterpart).

### (c) File paths

Literal greps for `~/`, `/Users/`, `docs/`, `evals/`, `.json`, `.jsonl`, `.py`, `.tex` (also `.yaml`, `.csv`, `generated/`, `PYTHONPATH`): **0 hits in either PDF** (one `r.json()` inside the restored hold-search-15 code listing is JavaScript). The main PDF is clean (its GitHub URL is intentional). **Soft leaks remain in the supplement:** 13 directory-style fragments (`model/` x3 on p9, p64, p103; `data/` x2; `firstpass-repro/`, `label-audit/`, `latency/`, `confirm/`, `campaign/`, `prereg/`, `pilot/`, `reproduce/`, all in H.3/H.4 p103-104), plus the Table S56 and S57 captions "(evidence in the 2026-10-05-effort-control directory)" / "...-fable directory" (p78-79, verbatim from v2), "the eval/judge-realistic branch" and "benchmark folder of the repository" (p103-104). Commit hashes and PR numbers are present (not paths). `savings.DEFAULT_RATES` (p68) is a code identifier.

### (d) "??" and duplicates

No `??` in either PDF; no broken `\ref`. Duplicated *content* (not figures): B.6 (p43-46, from JB §10) and B.7 (p47, from v2 §3) tell the real-decision study twice, with two near-identical "Read this before generalizing" boxes (p46 and p47). Dangling cross-references: "Part III is that experiment" (p71), "the one DK had raised (Section 4 of the main paper)" (p70), "This chapter reports both" (p43; the caching study is in D.2), "S2 replicates" (p89; undefined study label that collides with Figure/Table S2).

### (e) Organization A-H against the main paper

Mirrors correctly. Main §2 -> A (setting, methods, judge-benchmark design, A.8 labelling guide, A.9 case cards); §3 -> B; §4 -> C; §5 -> D; §6 -> E; §7 -> F; §8 -> H.2 (recipes) and G.2 (proxy replay); §9 -> Table S66 (H.5); G is the S1 study that §4 and §5 both cite. Every "Details:" pointer in the main PDF resolves (B, C+G, D+G, E, F, H.2, G.2, Table S66); the only main-paper change in the working tree is these pointers. Two weak spots: Takeaway 3's headline numbers are split between C.2 (H3) and G (H2); and the TOC stops at depth 1 (8 entries for 108 pages).

### (f) Rendering (10 random pages at 150 dpi)

Pages 6, 12, 20, 28, 31, 36, 38, 40, 57, 92 (seeded sample) rendered to `/tmp/render/p<N>-<NNN>.png` (e.g. `p12-012.png`). **I could not look at the images** (no image viewer in this environment; the file tool refuses binaries), so I did not make a visual judgement. Substitute checks, run on all 108 pages: word-box overlaps = 0 (threshold 1 pt x 2 pt); words within 36 pt of any page edge = 0; ink extent 14 %-86 % of page width on every page; no page with a >20 % internal blank band; only p1 (title/TOC) ends above 55 % height. From text order and spacing: p6 one justified line stretched ("kind:        tests, runner:"); p67 Table S47 floats into the middle of the continued Table S46, and p96 Table S65 into the middle of continued Table S64; Tables S59/S60 (p83) use rotated column headers; Fig S19 (p62) x labels are rotated. 65 run-in headings print a doubled period ("Provenance.. The"; the preamble adds "." and the ported sources already contain one; 71 `\paragraph{...\.}` in `supp/ported/*.tex`).

## 5. Reconciliation table (all 218 rows)

Legend: *Was* = status in the inventory; *Now* = this audit. `dup:` marks the 20 rows removed from the unique count (twin shown). `INT` = author listed this row as an intentional non-restoration. Locations are supplement sections and PDF pages unless "Main".

| ID | Item | Was | Now | Supplement location | Notes |
|---|---|---|---|---|---|
| JB-01 | key idea: Accuracy alone is the wrong headline for a judge. | CONDENSED | **CONDENSED** | E.1.3 p80-81 (prose) | Box "Accuracy alone is the wrong headline" gone; idea survives as "leads with wrong-automatic rate and coverage, treats accuracy as supporting". |
| JB-02 | key idea: A judge's mistakes come in two kinds: safe mistakes (fall back) and un... | CONDENSED | **PRESENT** | E.1.3 key idea, p81 | Verbatim safe/unsafe mistakes box. |
| JB-03 | worked example (casecard): The question the judge sees: Task 'Purchase the subscription'... | CONDENSED | **PRESENT** | E.1.4, p81-82 | Step-by-step Jev walkthrough restored; 142 ms, a=0.91/reason=0.08/b=0.01, margin 0.83 match JB. |
| JB-04 | table (T1): Every base judge's answer to cua-18 under the bundle's gate. | MISSING | **PRESENT** | Table S58, p82 | Full 10 judges x 3 reps grid. |
| JB-05 | description list: Dev split (90 cases, screen) / holdout (63, preregistered) / case kind... | CONDENSED | **PRESENT** | A.5.1, p14-15 | Dev (60+30; 30 select/30 cua/30 search), holdout (21/21/21; 29 tagged) and case kinds. |
| JB-06 | key idea: A holdout is a set of cases kept aside until the analysis is fixed. | CONDENSED | **PRESENT** | A.5.1 key idea, p15 | Holdout/preregistration box incl. SHA-256 prefix. |
| JB-07 | table (T2): Blind label audit. | CONDENSED | **PRESENT** | Table S11, p15 | Identical to JB Table 2. |
| JB-08 | description list: Adjudication notes per flagged case (cua-18: label defensible, task un... | MISSING | **PRESENT** | A.5.2, p15-16 | cua-18, cua-19, fresh-cua-09, search-11 adjudications. |
| JB-09 | caveat: The holdout author and both reviewers are Anthropic models (Claude Opu... | CONDENSED | **PRESENT** | A.5.2 "Read with care" p16; A.7 p23 | Same-vendor caveat restored as boxed note. |
| JB-10 | table (T3): The 10 base judges. | CONDENSED | **PRESENT** | Table S12, p16 | Identical (where it runs, call path, probability source, $/1M). |
| JB-11 | description list: Scoring policies: bundle-read-shortcut (primary), alternatives. | CONDENSED | **PRESENT** | A.5.4, p17 | 5 policies listed (bundle-read-shortcut, +host-guard, +noul-gate, cutoff-t, study-0.75). |
| JB-12 | key idea: For each case we take the majority outcome over the three repetitions. | MISSING | **PRESENT** | A.5.5 key idea, p17 | Majority-over-three-repetitions rule restored. |
| JB-13 | analysis (text): Statistics, explained plainly: CI, McNemar, Holm, non-inferiority, cal... | CONDENSED | **PRESENT** | A.5.6, p17-18 | Plain-language CI, McNemar, Holm, non-inferiority, calibration, latency, cost. |
| JB-14 | analysis (text): The preregistered decision rules (Rule 1: replace Jev; Rule 2: offline... | CONDENSED | **PRESENT** | A.5.7, p18-19 | All four preregistered rules. |
| JB-15 | table (T4): Repeatability over seven runs on the 90 dev cases. | MISSING | **PRESENT** | Table S13, p19 + A.6.1 | Seven-run repeatability table. |
| JB-16 | analysis (text): Harness audit (defects found in the first-pass harness). | MISSING | **PRESENT** | A.6.2, p19-20 | Six audit findings + two code-review bugs. |
| JB-17 | table (T5, xltabular): All 20 first-pass claims, what the first pass said, and what the valid... | MISSING | **PRESENT** | Table S14, p21-23 | 20 claims + 1 change-log entry. Caption says "verbatim from a JSON record"; one row says "logged in a JSON record and a JSON record" (scrub artefact). |
| JB-18 | table (T6): Dev split [screen], 90 cases, 3 repetitions, policy bundle-read-shortc... | MISSING | **PRESENT** | Table S16, p32 | 14 arms; identical to JB Table 6. |
| JB-19 | figure (F1): Wrong automatic rate against coverage on the dev split [screen]. | MISSING | **PRESENT** | Fig S8, p33 | Dev wrong-auto vs coverage with Wilson whiskers. |
| JB-20 | table (T7): Rule 1 on the dev split [screen]: each candidate minus Jev. | MISSING | **PRESENT** | Table S17, p34 | Identical to JB Table 7. |
| JB-21 | analysis (text): Interventions on dev. | CONDENSED | **PRESENT** | B.3.4 p33-34; Table S61 dev columns p85 | Three I1/I2/I3 bullets with dev counts. |
| JB-22 | table (T8): Holdout [preregistered], 63 cases, 3 repetitions, policy bundle-read-s... | CONDENSED | **PRESENT** | Table S18, p35 | All 14 arms, accuracy, wrong-auto, coverage, p50, p95, $/1M; identical to JB Table 8 (JB table had no ECE column). |
| JB-23 `dup:v2 F1` | figure (F2): Accuracy of every arm on both splits, with 95% Wilson intervals. | CONDENSED | **CONDENSED** | Fig S5, p29 | Holdout-only plus Clef (v2 version). Dev-split circles of JB Fig 2 are still not drawn; dev accuracy/CI survive only in Table S16. Superseded original. |
| JB-24 | table (T9): Rule 1 on the holdout: each candidate minus Jev, paired-bootstrap CIs,... | CONDENSED | **PRESENT** | Table S19, p35 | All 13 candidates incl. local judges and wrong-auto contrasts. |
| JB-25 | caveat: The bootstrap intervals for Luna and Sol exclude zero, but Holm-adjust... | PRESENT | **PRESENT** | B.4.2 "Read with care", p36 | Now boxed. |
| JB-26 | table (T10): The 13 contrasts declared in the run configuration, both splits, accur... | MISSING | **PRESENT** | Table S20, p37 | 13 declared contrasts, both splits. |
| JB-27 `dup:v2 F2` | figure (F3): Wrong automatic rate against coverage on the holdout, 95% Wilson inter... | MISSING | **PRESENT** | Fig S10, p39 | v2 version (with Clef arms). Superseded original. |
| JB-28 `dup:v2 F3` | figure (F4): Accuracy against p95 latency (log scale) on the holdout. | MISSING | **PRESENT** | Fig S11, p40 | v2 version (with Clef arms). Superseded original. |
| JB-29 | figure (F5): Threshold sweep (coverage and wrong-automatic rate vs certainty cutoff... | MISSING | **PRESENT** | Fig S9, p38 | 4-panel sweep, dev + holdout. |
| JB-30 | table (T11): Automatic / wrong automatic decisions at selected cutoffs, holdout. | MISSING | **PRESENT** | Table S21, p37 | Identical. |
| JB-31 | description list: Failure-mode classes (acted on side effect, under-deferred, accepted w... | MISSING | **PRESENT** | E.2 class list, p82-83 | Seven classes incl. Over-deferred. |
| JB-32 | table (T12): Holdout: all wrong answers by class (mean per repetition). | MISSING | **PRESENT** | Table S59, p83 | Heat-table of all wrong answers by class. |
| JB-33 | table (T13): Holdout: only the wrong answers the bundle would have acted on. | MISSING | **PRESENT** | Table S60, p83 | Unsafe subset. |
| JB-34 | analysis (text): Root causes: side effects (instruction), accepted wrong code, injectio... | CONDENSED | **PRESENT** | E.2.2, p84 | Side effects / accepted wrong code / injection / confident cloud mistakes. |
| JB-35 | description list: Interventions I1 (side-effect clause), I2 (host guard), I3 (yes/no gat... | CONDENSED | **PRESENT** | E.2.3, p84 and p86 | I1, I2, I3 all present (I3 now back). |
| JB-36 | table (T14): Interventions on both splits. | CONDENSED | **PRESENT** | Table S61, p85 | Every per-judge, per-split row incl. I2+I3; identical to JB Table 14. |
| JB-37 | figure (F6): The host guard (I2) on the holdout: side-effect wrong automatic decisi... | CONDENSED | **PRESENT** | Fig S31, p86 | Per-judge before/after bars. |
| JB-38 | key idea: The most effective safety measure is not a better model but a dumb, de... | PRESENT | **PRESENT** | E.2.3 key idea, p86 |  |
| JB-39 | figure (F7): Where the time goes in one call (medians of each component). | MISSING | **PRESENT** | Fig S13, p42 | Cloud + local anatomy bars. |
| JB-40 | table (T15): The numbers behind the latency anatomy figure. | MISSING | **PRESENT** | Table S22, p40 | Identical to JB Table 15. |
| JB-41 | table (T16): Latency and throughput as requests in flight rise. | MISSING | **PRESENT** | Table S23, p41 | Concurrency study. |
| JB-42 | caveat: Local latency is a property of this host at that time, not of the mode... | MISSING | **PRESENT** | B.5 "Read with care", p41 |  |
| JB-43 | table (T17): Projected monthly API cost and wrong automatic actions at 100,000 deci... | MISSING | **PRESENT** | Table S24, p43 |  |
| JB-44 | caveat: The wrong-action column assumes real traffic has the benchmark's decis... | MISSING | **PRESENT** | B.5.2 "Read with care", p42 |  |
| JB-45 | key idea: Keep Jev 1.13 as the default judge. | PRESENT | **PRESENT** | B.8.1 key idea, p50 |  |
| JB-46 | key idea: Adopt intervention I2: never act automatically on an option naming an ... | PRESENT | **PRESENT** | B.8.2 key idea, p50 |  |
| JB-47 | analysis (text): Cloud fallback when Jev is unreachable: GPT-6 Luna, behind the guard. | MISSING | **PRESENT** | B.8.3, p50 | GPT-6 Luna behind the guard. |
| JB-48 | table (T18): Rule 2, the offline tier: local judges under the strictest policy. | CONDENSED | **PRESENT** | Table S31, p51 + B.8.4, p50 | Both splits, all 7 local judges. |
| JB-49 | analysis (text): What is within noise; what the follow-ups add; what would change these... | CONDENSED | **PRESENT** | B.8.5-B.8.7, p51-52 | "What would change the recommendation" list back. B.8.6/B.8.7 still call the caching experiment "not been run" (stale; see gap G2). |
| JB-50 | caveat: Measured before these changes: every result was measured before the li... | MISSING | **PRESENT** | B.8.8 box, p52 | "Measured before these changes". |
| JB-51 | key idea: Two new questions, two new kinds of evidence. | MISSING | **PRESENT** | B.6 key idea, p43 |  |
| JB-52 | key idea + text: 'What the host did next' is not the same as 'what was enough'; how tra... | CONDENSED | **PRESENT** | B.6.1, p43-44 | Fingerprint rebuild, 926 eligible, 70 drawn, seed. |
| JB-53 | table (T19): Real read-shortcut decisions, holdout: 42 cases, 3 repetitions. | CONDENSED | **PRESENT** | Table S25, p44 | Identical to JB Table 19 incl. "form" column. |
| JB-54 `dup:v2 F7` | figure (F8): Real decisions: correct automatic reads against wrong automatic reads,... | PRESENT | **PRESENT** | Fig S6, p30 | v2 version (with Clef). Superseded original. |
| JB-55 | analysis (text): Why accuracy misleads here (always-fallback scores highest); cost of a... | MISSING | **PRESENT** | B.6.2, p45-46 | Why accuracy misleads (29/42), cost of a wrong read, host-next-read scoring. |
| JB-56 | caveat: Read this before generalizing (scope and selection of the trace cases)... | MISSING | **PRESENT** | B.6.3 p46 (boxed) | Duplicated by a second box in B.7 (p47). |
| JB-57 `INT` | key idea: Three prices matter (input, cache read, cache write). | CONDENSED | **CONDENSED** | D.1, p67 (prose) | Author: intentionally not restored. Box not present; the three prices are in D.1 prose and Table S47. Content is covered. |
| JB-58 `dup:v2 T10` `INT` | table (T20): Price table behind every cost in this section (USD per million tokens)... | CONDENSED | **PRESENT** | Table S47, p67 | v2 version restored. Superseded original. |
| JB-59 `dup:v2 F8` `INT` | table (T21): Cost ratio for the same cell in single-turn and 4-turn sessions. | MISSING | **CONDENSED** | Fig S22, p70 | Author: superseded by v2 F8. Figure restored, but JB Table 21 values are gone: Fable 0.49 [0.42-0.59] -> 0.62 [0.46-0.74], pair counts 204/45/168/39, CIs. Only the Opus 0.95->1.31 and 0.97->1.35 appear (in the note). Superseded original. |
| JB-60 `INT` | table (T22): Rebuild cost after model switches, by stratum. | MISSING | **CONDENSED** | Table S50, p71 | v2 version. JB footnote lost: mid-turn escalation row "27 % (42 % incl. effort-setting rewrites)" and the caveat that pooled rebuild shares mislead (593 anchors behind 903 pairs). |
| JB-61 `INT` | analysis (text): Caching survey: price vs volume (about half each), rebuild cost, warm ... | MISSING | **CONDENSED** | D.2, p70-71 | Price-vs-volume (46 %/54 %) is back. Still lost: "How much the rebuilds cost" (138 switches, 110/28, turn 2 = 1.93x/1.13x Opus, 1.59x/0.67x Fable, SWE-bench 0.98x), "Warm first requests" re-normalisation (83 % vs 67 %; 1.16-1.27), 1.44x cache-read tokens, 3,000 resamples. |
| JB-62 `INT` | caveat: What the caching study did not show (longer and real chats...). | MISSING | **CONDENSED** | D.2 "Why a new experiment was needed", p71 | Lists <=4 turns, 6 scenarios, no expiry, no decide-once arm, 0/903 receipts. Lost: 84 of 90 Opus pairs come from the 3 tuning scenarios; routed cells also change effort. (JB proposed-experiment paragraph deliberately dropped: stale.) |
| JB-63 `INT` | analysis (text): New findings for the bundle (defects found by the trace study). | MISSING | **PRESENT** | Table S27, p48 + B.7.1 | v2 version (PR #58 fixes). Minor JB extras (escalation/phase/tool-risk decisions could not be rebuilt) not carried. |
| JB-64 | analysis (text): Limitations. | CONDENSED | **PRESENT** | A.7, p23-24 | Plus A.4 for the campaigns. |
| JB-65 | code listing + text: Reproducibility: evidence, runs, replaying the numbers (PYTHONPATH=...... | CONDENSED | **CONDENSED** | H.3, p103 | Replay commands intentionally dropped (paths), but remaining prose is garbled by path scrubbing: "recomputes every committed the summary record from its the request log", "the post-hoc the trace analysis record"; also lists firstpass-repro/, label-audit/, latency/. |
| JB-66 | glossary (37 terms): Argmax ... Wrong-automatic rate. | CONDENSED | **PRESENT** | H.1, p97-101 | 60 merged terms; every one of JB 37 / v2 23 / v3 17 present ("Within noise" -> "No difference detected"; "Cache read, cache write" -> "Cache read / cache write"). |
| JB-67 | analysis (text): The holdout labeling guide (principle, case kinds, choice/search cases... | MISSING | **PRESENT** | A.8, p24-25 | Full labelling guide. |
| JB-68 | worked examples (6 casecards + 2 listings): Case examples: fresh-cua-09, search-11, hold-cua-00, hold-cua-12, hold... | MISSING | **PRESENT** | A.9, p25-28 | 6 casecards + 2 code listings. |
| P2-01 `INT` | key idea: What we found (test split; hypotheses preregistered, estimator after t... | CONDENSED | **CONDENSED** | Main abstract/Section 9; Table S1 p3 | Author: main-paper content (reason holds). Residual: spend-vs-geometric-mean statement (44 % typical; spend -37.3 % all scenarios, -42.4 % test) now appears only inside review response H.7 #2 (p106); $5.31 -> $3.33 is in C.3.2 without the percentages. |
| P2-02 `INT` | key idea: A judge is useful when it is right when it acts and acts often enough ... | CONDENSED | **CONDENSED** | E.1.3 p81; B.6.1 p44 | Author: main-paper content (partly holds). "Never acts = useless, always acts = dangerous" framing gone; safe/unsafe box and usefulness rule remain. |
| P2-03 `dup:JB-07` | table (T1): Blind label audit of the judge benchmark. | CONDENSED | **PRESENT** | Table S11 | Duplicate of JB-07. |
| P2-04 `dup:JB-22` | table (T2): Judge benchmark holdout: accuracy, wrong automatic, coverage, latency,... | CONDENSED | **PRESENT** | Table S18 | Duplicate of JB-22. |
| P2-05 | figure (F1): Holdout accuracy with 95% Wilson intervals: preregistered run, then po... | PRESENT | **PRESENT** | Fig S5, p29 |  |
| P2-06 | figure (F2): Wrong-automatic rate against coverage on the holdout, with the post ho... | MISSING | **PRESENT** | Fig S10, p39 |  |
| P2-07 | figure (F3): Accuracy against p95 latency (log scale) on the holdout, with the post... | MISSING | **PRESENT** | Fig S11, p40 |  |
| P2-08 | figure (F4): Cost per million decisions (log) against holdout accuracy, for priced ... | CONDENSED | **PRESENT** | Fig S12, p41 | Wilson whiskers present; main Fig 1 is the redraw. |
| P2-09 `dup:JB-39` | figure (F5): Where the time goes in one judge call: cloud (top) and local (bottom). | MISSING | **PRESENT** | Fig S13 | Duplicate of JB-39. |
| P2-10 `dup:JB-37` | figure (F6): The side-effect guard (I2) on the holdout: targeted wrong automatic de... | CONDENSED | **PRESENT** | Fig S31 | Duplicate of JB-37. |
| P2-11 `dup:JB-15/16` | analysis (text): Validating an earlier first pass. | MISSING | **PRESENT** | A.6, p19-20 | Duplicate of JB-15/16. |
| P2-12 | table (T3): Post hoc run: Clef, Clef-Flash and in-run Jev on all four splits. | CONDENSED | **PRESENT** | Table S28, p48 | Four splits, latency, >3 s, cost; identical to v2 Table 3. |
| P2-13 | table (T4): Post hoc paired contrasts (McNemar exact on per-case majority). | MISSING | **PRESENT** | Table S29, p49 |  |
| P2-14 | table (T5): Preregistered default-judge rule applied descriptively to the post hoc... | CONDENSED | **PRESENT** | Table S30, p49 |  |
| P2-15 | key idea: Clef matches Jev's accuracy but costs several times more and answers ~... | CONDENSED | **PRESENT** | B.7.2 key idea, p49 |  |
| P2-16 `dup:JB-53` | table (T6): Real decisions, holdout: 42 cases. | CONDENSED | **PRESENT** | Table S25 | Duplicate of JB-53. |
| P2-17 | table (T7): Rule 2 ('useful' read shortcut) on both trace splits for the post hoc ... | CONDENSED | **PRESENT** | Table S26, p47 | Both trace splits. |
| P2-18 | figure (F7): Real decisions: correct vs wrong automatic reads on trace-holdout, + p... | PRESENT | **PRESENT** | Fig S6, p30 |  |
| P2-19 `dup:JB-56` | caveat: Read this before generalizing (selection...). | MISSING | **PRESENT** | B.7 box, p47 | Duplicate of JB-56 (two near-identical boxes, p46 and p47). |
| P2-20 | table (T8): The four defects found by the real-decision study and their fixes (PR ... | MISSING | **PRESENT** | Table S27, p48 |  |
| P2-21 `INT` | key idea: The only way to know what routing costs is to run the same work twice ... | PRESENT | **PRESENT** | Main Section 4 "Why we measured whole sessions" | Author: main-paper content. Reason holds (sentence is in the main paper). |
| P2-22 `INT` | analysis (text): Receipts are claims, not measurements; caching makes cost depend on hi... | PRESENT | **CONDENSED** | F.1 "Claimed savings were estimates" p87; main Section 4 | Author: present. Only partly. Lost: v2's own receipt-vs-measurement check (35 same-model pairs: receipts claimed $2.22, measured -$2.80), "a receipt is the policy grading its own homework", and the DK quote. D.2 (p70) still says "the one DK had raised (Section 4 of the main paper)" - dangling. |
| P2-23 | figure (F8): Earlier caching survey: same configuration in single-turn and 4-turn s... | MISSING | **PRESENT** | Fig S22, p70 |  |
| P2-24 `dup:JB-60` | table (T9): Earlier survey: share of routed runs' cost spent re-writing caches aft... | MISSING | **PRESENT** | Table S50, p71 | Duplicate of JB-60 (v2 version; see JB-60 for the lost footnote). |
| P2-25 | caveat: Why a new experiment was needed (<=4 turns, few synthetic scenarios, c... | MISSING | **PRESENT** | D.2, p71 | Contains stale "Part III is that experiment". |
| P2-26 `dup:JB-61` | analysis (text): Price and volume, about half each (survey-pricevolume.dat built but no... | MISSING | **PRESENT** | D.2 "Price and volume", p71 | Text only, as in v2 (pricevolume.dat still not plotted). |
| P2-27 | table (T10): Price per million tokens (USD), by model and token class. | CONDENSED | **PRESENT** | Table S47, p67 |  |
| P2-28 | table (T11): Opus-host cost ratios if Opus cache reads cost more than list (price s... | CONDENSED | **PRESENT** | Table S48, p68 | 5 prices x pair/arm readings; plus the 1.90x and $0.38/$0.34/$0.49/$0.50 note. |
| P2-29 | figure (F9): How the prompt cache behaves over a conversation (schematic). | MISSING | **PRESENT** | Fig S20, p68 |  |
| P2-30 | table (T12): The cache-semantics probe. | MISSING | **PRESENT** | Table S49, p69 |  |
| P2-31 | figure (F10): The probe requests drawn: tokens written and read by each. | MISSING | **PRESENT** | Fig S21, p69 |  |
| P2-32 | key idea: Six facts from the probe shaped the experiment. | CONDENSED | **PRESENT** | D.1 key idea, p70 | Six probe facts. |
| P2-33 | analysis (text): How the design evolved. | MISSING | **PRESENT** | A.2.1, p2 | Why v1 forks were rejected. |
| P2-34 | key idea: Pairing removes most of the noise. | PRESENT | **PRESENT** | A.2.2 key idea, p4 |  |
| P2-35 | table (T13): The five arms. | MISSING | **PRESENT** | Table S2, p4 | All five arms defined. |
| P2-36 | table (T14): Main-loop requests by host, arm, model and reasoning effort. | MISSING | **PRESENT** | Table S3, p5 |  |
| P2-37 | table (T15): Scenarios by family and preregistered split. | MISSING | **PRESENT** | Table S4, p6 |  |
| P2-38 | table (T16): Correlation between turn-pass fraction and final hidden tests (point-b... | MISSING | **PRESENT** | Table S5, p7 |  |
| P2-39 | examples list: Quality-instrument examples (turn checks). | MISSING | **PRESENT** | A.2.6, p6 | Three examples (paths scrubbed to "a Markdown file"/"a Python file"). |
| P2-40 | table (T17): Un-normalized static-write cost per session. | MISSING | **PRESENT** | Table S6, p8 |  |
| P2-41 | table (T18): Tools normalization by host and arm. | CONDENSED | **PRESENT** | Table S7, p8 |  |
| P2-42 | table (T19): Confirmatory ratios on raw vs tools-normalized basis. | MISSING | **PRESENT** | Table S8, p8 |  |
| P2-43 | analysis (text): Hypotheses and the decision rule; what was fixed later; ratios and int... | CONDENSED | **PRESENT** | A.2.8, p7-9 |  |
| P2-44 | table (T20): Projected precision of the routing ratio (power analysis). | MISSING | **PRESENT** | Table S9, p9 |  |
| P2-45 | figure (F11): Projected 95% CI half-width vs number of scenarios. | MISSING | **PRESENT** | Fig S2, p10 |  |
| P2-46 | figure (F12): Second screening pilot (40 pairs, 5 scenarios) against the full campai... | CONDENSED | **PRESENT** | Fig S3, p10 | Per-arm pilot-vs-final (8 rows). |
| P2-47 | key idea: A guard that kills runaway sessions is only fair if its kills are coun... | MISSING | **PRESENT** | A.3.1 key idea, p11 |  |
| P2-48 | table (T21): Failed wave attempts by cause. | MISSING | **PRESENT** | Table S10, p11 |  |
| P2-49 | figure (F13): Campaign progress: sessions completed and spend over time. | MISSING | **PRESENT** | Fig S4, p12 |  |
| P2-50 | analysis (text): Spend and time; provenance (prereg commit/time). | CONDENSED | **PRESENT** | A.3.4, p12-13 | Prereg commit/time and provenance back. |
| P2-51 | table (T22): Primary endpoint: geometric-mean cost ratio, arm over plain host, test... | CONDENSED | **PRESENT** | Table S33, p55 | Pairs kept, both readings. |
| P2-52 | figure (F14): Confirmatory cost ratios on the test split. | PRESENT | **PRESENT** | Fig S14, p53 |  |
| P2-53 | table (T23): The preregistered hypotheses, test split, pair reading. | MISSING | **PRESENT** | Table S34, p55 | Pair reading only (see gap G6 for main-paper 0.87x/0.91x all-pairs). |
| P2-54 | table (T24): Quality: mean turn-pass difference, arm minus plain host, test split. | MISSING | **PRESENT** | Table S35, p56 |  |
| P2-55 | figure (F15): The savings model: predicted vs observed total saving per arm/host. | MISSING | **PRESENT** | Fig S16, p57 |  |
| P2-56 | analysis (text): Decision (what the confirmatory results decide). | CONDENSED | **PRESENT** | C.2.4, p57 |  |
| P2-57 | figure (F16): Mean cost per session split by what was paid for (main campaign, incl.... | CONDENSED | **PRESENT** | Fig S17, p58 | Main-campaign arms incl. rebuild class; v2 figure restored under a renamed file. |
| P2-58 | table (T25): The numbers behind the composition figure: $/session by token class, r... | MISSING | **PRESENT** | Table S36, p58 |  |
| P2-59 | figure (F17): Dollars saved per 1,000 sessions by task type and arm, 90% ranges. | MISSING | **PRESENT** | Fig S18, p60 |  |
| P2-60 | table (T26): Measured saving per 1,000 sessions by task type, host and arm. | MISSING | **PRESENT** | Table S37, p59 |  |
| P2-61 | table (T27): Scenarios by task type and preregistered split. | MISSING | **PRESENT** | Table S38, p61 |  |
| P2-62 | table (T28): Final hidden-test pass rate by arm vs plain host (McNemar). | MISSING | **PRESENT** | Table S39, p61 |  |
| P2-63 | analysis (text): The noise floor (A/A). | CONDENSED | **PRESENT** | C.3.4 p61; D.3.5 p74; Table S41 p63 |  |
| P2-64 | figure (F18): Cost ratio of each routed arm as evidence accumulated: pilot, interim,... | CONDENSED | **PRESENT** | Fig S19, p62 | Pilot/interim/train/test/confirmatory; Table S42 beside it. |
| P2-65 | analysis (text): Limits of the savings model. | MISSING | **PRESENT** | C.3.6, p62 |  |
| P2-66 | figure (F19): Mean cost of each turn by turn index, per arm and host. | MISSING | **PRESENT** | Fig S23, p72 |  |
| P2-67 | figure (F20): What each turn of a plain-host session paid for, by turn index. | MISSING | **PRESENT** | Fig S24, p72 |  |
| P2-68 | figure (F21): Cache-write tokens on first request of a turn, after short vs long pau... | CONDENSED | **PRESENT** | Fig S25, p73 | Per-arm, per-host. |
| P2-69 | figure (F22): Shipped arm: number of model switches leading into each turn. | MISSING | **PRESENT** | Fig S26, p73 |  |
| P2-70 | figure (F23): Scenario by scenario: plain Fable cost vs sticky saving. | MISSING | **PRESENT** | Fig S27, p74 |  |
| P2-71 | figure (F24): Distribution of log cost ratio between two identical plain-host sessio... | MISSING | **PRESENT** | Fig S28, p75 |  |
| P2-72 | table (T29): Mean turn-pass difference by scenario family. | MISSING | **PRESENT** | Table S51, p75 |  |
| P2-73 | table (T30): Savings and quality together, by family. | MISSING | **PRESENT** | Table S52, p75 |  |
| P2-74 | table (T31): Savings and quality together, by task type. | MISSING | **PRESENT** | Table S53, p75 |  |
| P2-75 | table (T32): Fable sticky by task type with 95% CIs on saving per 1,000 sessions. | MISSING | **PRESENT** | Table S54, p76 |  |
| P2-76 | figure (F25): Main-loop requests per session by kind of session (box plot). | CONDENSED | **PRESENT** | Fig S29, p76 | Box plot restored. |
| P2-77 | figure (F26): Cost ratio by scripted session length. | MISSING | **PRESENT** | Fig S30, p77 |  |
| P2-78 | table (T33): Sticky sessions that chose Sonnet vs plain-Sonnet control (effort conf... | MISSING | **PRESENT** | Table S55, p77 |  |
| P2-79 | analysis (text): The effort confound: what medium-effort sessions did differently; two ... | CONDENSED | **PRESENT** | D.4, p76-77 | Both corrections included. |
| P2-80 | table (T34): Effort-control follow-up (plain Sonnet medium vs default). | CONDENSED | **PRESENT** | Table S56, p78 | 0.958 row, turn-pass row and provenance caveat back. Caption carries a repository directory name. |
| P2-81 | key idea: The effort setting alone explains most of the sticky-vs-plain-Sonnet g... | CONDENSED | **PRESENT** | D.4.1 key idea, p79 |  |
| P2-82 | table (T35): Fable effort follow-up (plain Fable medium vs default). | CONDENSED | **PRESENT** | Table S57, p79 | Caption carries a repository directory name. |
| P2-83 `INT` | key idea: Fable 5.1: move the session to Sonnet, and decide once. | PRESENT | **PRESENT** | Main Table 3; C.1 p53; G p89; D.4 key idea p79 | Author: main-paper content. Reason holds. |
| P2-84 `INT` | key idea: Opus 5.5: do not route to Sonnet. | PRESENT | **CONDENSED** | Main Table 3; C.2.1 p56; Table S48 note p68 | Author: main-paper content. Recommendation holds; residual: "Opus result does not depend on the effort setting: sticky-on-Sonnet at medium still 1.18x (95 % CI 1.11-1.27)" is gone (only "1.182" appears inside the A.4 matched-effort arithmetic). |
| P2-85 `INT` | analysis (text): How much of the saving is the router vs effort; quality by task type; ... | CONDENSED | **CONDENSED** | D.4 (router vs effort); Table S54; C.3.6 | Author: main-paper content (partly holds). Lost with no home in either PDF: "Caching guidance (hypotheses)" (5 bullets), "How to use the numbers", "What to measure next" (longer sessions, live predictions, new-host price check, larger sample for final-test losses), "lowering the host's own effort avoids the task-type quality losses", "route only task types that hold quality = hypothesis". |
| P2-86 | analysis (text): Limitations and threats to validity. | CONDENSED | **PRESENT** | A.4, p13-14 | All 17 limitation bullets. |
| P2-87 | code listing + text: Reproducibility (re-running the analysis from published rows). | CONDENSED | **CONDENSED** | H.4, p103-104 | Commands intentionally dropped; text garbled by scrubbing ("Its evidence directory is: its evidence package (Table S66)", "its the data dictionary"); lists data/, confirm/, model/, campaign/, prereg/, pilot/, reproduce/ and "the eval/judge-realistic branch". |
| P2-88 | glossary (23 terms): A/A ... Wave. | CONDENSED | **PRESENT** | H.1, p97-101 |  |
| P2-89 | table (T36): Savings-model check: PI coverage and observed vs predicted. | MISSING | **PRESENT** | Table S40, p63 |  |
| P2-90 | table (T37): A/A noise floor: second plain-host session vs first. | MISSING | **PRESENT** | Table S41, p63 |  |
| P2-91 | table (T38): Interim and final cost ratios. | MISSING | **PRESENT** | Table S42, p63 |  |
| P2-92 | table (T39): Cost ratio by pause pattern. | MISSING | **PRESENT** | Table S43, p63 |  |
| P2-93 | table (T40): Cost ratio by scripted session length. | MISSING | **PRESENT** | Table S44, p64 |  |
| P2-94 | table (T41, xltabular): Savings per 1,000 sessions by host, task type and arm, measured and pr... | MISSING | **PRESENT** | Table S45, p65 | Full 42 cells with 90 % range and model column. |
| P2-95 | table (T42, xltabular): The 70 scenarios: family, task type, language, turns, long gaps, split... | MISSING | **PRESENT** | Table S46, p66-67 | All 70 scenarios (split across 2 pages; Table S47 floats into the continuation). |
| P2-96 | analysis (text): Raw cost basis. | MISSING | **PRESENT** | C.4 "Raw cost basis", p63 |  |
| P2-97 | enumerated list: Deviations from the preregistration. | MISSING | **PRESENT** | C.4, p64-65 | 10 deviations + 3 extra points. Numbering collision: the three "further points" are numbered 5, 6, 7 (were 1-3 in v2). Garbled: "The model is the existing a JSON record", "a Python file (PREREG constant) and a Markdown file". |
| P2-98 | analysis (text): Response to review, rounds 1-2 and re-review. | CONDENSED | **PRESENT** | H.7, p106-108 | Round 1 (11), re-review, round 2 (8). Several pointers to "Section 8 of the main paper" refer to v2 Section 8, not v4. |
| P2-99 `dup:JB-17` | table (T43, xltabular): All 20 first-pass claims (judge benchmark). | MISSING | **PRESENT** | Table S14 | Duplicate of JB-17. |
| V3-01 `INT` | key idea: The one-sentence answer: a fast decision model is worth what its decis... | CONDENSED | **CONDENSED** | Main abstract; Table S1 p3 | Author: main-paper content. Reason holds. |
| V3-02 `INT` | key idea: A decision model is only worth what its decisions change. | CONDENSED | **CONDENSED** | Main Section 9 last paragraph; G key idea p89 | Author: main-paper content. Reason holds. |
| V3-03 | figure (F1): Each stage answered the question the previous one left open (study tim... | MISSING | **PRESENT** | Fig S1, p2 | Timeline restored with its "How to read it". |
| V3-04 | table (T1): Findings at a glance. | CONDENSED | **PRESENT** | Table S1, p3 | 16 rows incl. keyword proxy. Row "Effort switches rewrite the cache - 12.9x cache writes" disagrees with main Section 5 (10.3x; 11,650 vs 1,133 tokens). |
| V3-05 | analysis (text): Related work (RouteLLM, FrugalGPT) and how to read evidence labels. | PRESENT | **PRESENT** | Main Section 1 + references |  |
| V3-06 | figure (F2): A decision call is two orders of magnitude faster than a host model ca... | PRESENT | **PRESENT** | Main Fig 4 | Not repeated in supplement (not needed). |
| V3-07 | figure (F3): Most recorded events are bookkeeping; decision-bearing events are a th... | PRESENT | **PRESENT** | Fig S32, p87 |  |
| V3-08 | key idea: Telemetry told us decisions are cheap and fast, and that savings claim... | PRESENT | **PRESENT** | Main Section 7; F.1 p86-87 |  |
| V3-09 | analysis (text): The 7.1% that was not what it seemed; claimed savings were estimates. | PRESENT | **PRESENT** | F.1, p86-87 | Small details dropped (171,609 events in week 1; 4,470 session files). |
| V3-10 `dup:P2-05` | figure (F4): No accuracy difference between the top judges was detected after the p... | PRESENT | **PRESENT** | Fig S5 | Duplicate of P2-05. |
| V3-11 `dup:P2-08` | figure (F5): Jev is the cheapest judge near the top of the measured accuracy range. | CONDENSED | **PRESENT** | Fig S12 | Duplicate of P2-08; CIs present. |
| V3-12 `dup:P2-18` | figure (F6): On real read decisions, no judge reached the usefulness zone. | PRESENT | **PRESENT** | Fig S6 | Duplicate of P2-18. |
| V3-13 | figure (F7): The Decisions API was at or above Jev on every split (post hoc). | PRESENT | **PRESENT** | Fig S7, p31 |  |
| V3-14 | table (T2): OpenAI Decisions API (post hoc) vs in-run Jev. | PRESENT | **PRESENT** | Table S15, p31 | Identical to v3 Table 2. |
| V3-15 | key idea: A native typed-decision endpoint matched or exceeded Jev's accuracy... | PRESENT | **PRESENT** | B.2 key idea, p31 |  |
| V3-16 | key idea: Jev is the best value among the decision models we tested. | PRESENT | **PRESENT** | Main Section 3; B.8.1 p50 |  |
| V3-17 `dup:P2-52` | figure (F8): On main-v1 test split, every Fable routing arm saved money and every O... | PRESENT | **PRESENT** | Fig S14 | Duplicate of P2-52. |
| V3-18 | analysis (text): Why caching made this necessary; what it found; the effort confound. | CONDENSED | **PRESENT** | D.4, p76-79 | Effort-confound narrative now full length. |
| V3-19 | key idea: Measured, not estimated: on Fable, deciding once to run on Sonnet save... | PRESENT | **PRESENT** | Main Section 4 claim |  |
| V3-20 | analysis (text): A counterfactual on existing sessions (A0 decide-once pricing). | PRESENT | **CONDENSED** | C.1 p54; Fig S15; Table S32 | Figure and table restored. Lost narrative: Jev and R* disagree on 14 of 140 main-v1 scenario-reps; Jev "keep on host" calls bought nothing; Opus price gate sits at the oracle (regret $1 per 1,000 sessions). |
| V3-21 | figure (F9): On Fable the rule R* is at least as cheap as Jev; on Opus every routin... | PRESENT | **PRESENT** | Fig S15, p54 |  |
| V3-22 | table (T3): Decide-once policies on main-v1 (exploratory). | PRESENT | **PRESENT** | Table S32, p54 |  |
| V3-23 | analysis (text): An artefact to avoid: effort switches rewrite the prompt cache. | PRESENT | **PRESENT** | Main Section 5 + Fig 3; C.1 p54 (one sentence) | Supplement has no table for the 11,650 vs 1,133 and 66,235 vs 67,820 numbers; Table S1 gives a different multiple (12.9x). |
| V3-24 | analysis (text): How the S1 panel was prepared (smoke test, repairs). | PRESENT | **PRESENT** | G.1 "How the panel was prepared", p88 |  |
| V3-25 | worked example (casecard): S1 methods in brief (quality, cost, composed policies). | PRESENT | **PRESENT** | G.1 "S1 methods in brief", p88 |  |
| V3-26 | table (T4): S1 (holdout-v3) preregistered hypotheses. | PRESENT | **PRESENT** | Table S62, p88 |  |
| V3-27 | analysis (text): H1-H7 in plain words; what the freeze rule chose. | PRESENT | **PRESENT** | G.1 bullets, p89 |  |
| V3-28 | key idea: The start-of-session choice was matched by a one-line rule. | PRESENT | **PRESENT** | G.1 key idea, p89 |  |
| V3-29 | process note: Process note: how the S1 run went (spend, gate failures, outage, budge... | PRESENT | **PRESENT** | G.1 process note, p90 |  |
| V3-30 | figure (F10): Two hypotheses carry money (H1, H5); the rest are guards. | PRESENT | **PRESENT** | Fig S33, p90 |  |
| V3-31 | key idea: Two of the eight rows carry money. | PRESENT | **PRESENT** | G.1.1 key idea, p90 |  |
| V3-32 | worked example (casecard): Worked example: one scenario, one paired cost ratio. | PRESENT | **PRESENT** | G.1.2, p91 | Scenario name anonymised. |
| V3-33 | figure (F11): The direction is consistent across scenarios; the size varies widely. | PRESENT | **PRESENT** | Fig S34, p91 |  |
| V3-34 | figure (F12): Every subgroup saves money; quality risk concentrates in explain and m... | PRESENT | **PRESENT** | Fig S35, p92 | Caption lists every subgroup crossing the margin. |
| V3-35 | figure (F13): On Fable many configurations qualify; on Opus none does. | PRESENT | **PRESENT** | Fig S36, p93 |  |
| V3-36 | table (T5): The 4 S1 scenario-reps where Jev and rule R* chose different session m... | PRESENT | **PRESENT** | Table S63, p93 |  |
| V3-37 | worked example (casecard): Why the two deciders differ only where they disagree. | PRESENT | **PRESENT** | G.1.6, p92 |  |
| V3-38 | figure (F14): Medium effort saved money on Sonnet and Fable but not on Opus. | PRESENT | **PRESENT** | Fig S37, p94 |  |
| V3-39 | figure (F15): Plain Fable spends most of its money writing to the cache (S1). | PRESENT | **PRESENT** | Fig S38, p94 |  |
| V3-40 | figure (F16): Four independent sets of scenarios give the same answer for each host. | PRESENT | **PRESENT** | Main Fig 2 | Promoted to main paper. |
| V3-41 `INT` | analysis (text): What this taught us, and what it left open (S1). | CONDENSED | **CONDENSED** | G.1.5 p92; G key idea p89; main Section 9 | Author: main-paper content. Reason holds. |
| V3-42 `INT` | key idea: What gets the most out of a decision model: decide once; price gate; r... | CONDENSED | **CONDENSED** | Main Table 3 + Section 9 ranked list | Author: main-paper content. Reason holds. |
| V3-43 | table (T6): Recommended settings per host model, after S1. | PRESENT | **PRESENT** | Main Table 3 |  |
| V3-44 | analysis (text): What a user should set, incl. keyword-proxy replay (R* alone / true-la... | CONDENSED | **PRESENT** | G.2 p97; Table S65 p96 | True-label variant, shipped proxy, CIs, turn-pass, precision 38 %, 26 of 28 recall all present. |
| V3-45 | analysis (text): Per harness: Amplifier install/update instructions. | CONDENSED | **PRESENT** | H.2, p103 |  |
| V3-46 | code listings (4) + text: Configuration recipes (shipped default, accept review/explain risk, So... | PRESENT | **PRESENT** | H.2, p101-103 | Shipped YAML + 3 recipes + smart tool. |
| V3-47 `INT` | key idea + text: The takeaway; what remains open; honest limits; where a decision model... | CONDENSED | **CONDENSED** | Main Section 9; G.1 process note p90 | Author: main-paper content. Reason holds; the "S2-S5 programme" list is nowhere (it pointed at a repository design doc). |
| V3-48 | analysis (text): Companion material: companion report pointer, evidence used, reproduci... | PRESENT | **PRESENT** | H.5 Table S66, p105 |  |
| V3-49 | table (T7, xltabular): Every configuration the S1 freeze rule considered. | PRESENT | **PRESENT** | Table S64, p95-96 | All 23+23 configurations. Table S65 floats into the continuation. |
| V3-50 | glossary (17 terms): A/A pair ... Turn-pass fraction. | PRESENT | **PRESENT** | H.1 |  |
| V3-51 | analysis (text): Response to the independent review (round 3). | PRESENT | **PRESENT** | H.6, p105 | Seven round-3 points. |
## 6. Remaining gaps, prioritized, with exact fixes

Paths below are relative to `docs/papers/2026-10-07-decision-model-fit-v4/` (this file is not part of either PDF). Page numbers are supplement PDF pages.

### HIGH: the supplement contradicts itself or the main paper

**G1. Decisions API "not measured / HTTP 403" vs. the post hoc run (five places).** A.5.3 p16 ("Nothing in this report is a claim about the OpenAI Decisions API"), Table S14 p22 (row "could not be measured"), A.7 p23 ("Decisions API not measured... no claim is made about it"), B.4.6 p36 ("returned HTTP 403, so nothing is claimed for it"), B.8.7 p52 ("Today it returns 403"). Section B.2 (p30-31, Table S15, Fig S7) and main Takeaway 1 report it as measured post hoc and the main challenger. No sentence links the two.
Fix: append "in the preregistered runs; a later post hoc run is in Section B.2" to each. Files: `supp/ported/jb-03-method.tex` (A.5.3), `generated/jb/tables/changes.tex:44` (row "The OpenAI Decisions API could not be measured"; imported by `jb_import.py`, so patch the import step, not the generated file), `supp/ported/jb-10-limitations.tex`, `supp/ported/vt-p1-01-judges.tex:12`, `supp/ported/jb-09-recommendations.tex:111` (replace "Today it returns 403" with "It answered in the post hoc run (Section B.2); a preregistered holdout of it has not been run").

**G2. "The proposed caching experiment... has not been run" (and "Part III").** B.8.6 p51-52 ("pending the proposed caching experiment (Section D.2), which has not been run"), B.8.7 p52 (last bullet), D.2 p71 ("Part III is that experiment"). The paired campaign in Sections C-D *is* that experiment.
Fix: B.8.6: "...This was then measured: sticky routing cost 0.558x on Fable and 1.249x on Opus (Section C.2)". B.8.7: delete the bullet. D.2: "Section C is that experiment, larger than proposed." Files: `supp/ported/jb-09-recommendations.tex`, `supp/ported/vt-p2-survey.tex:47`.

**G3. Table S1 disagrees with main Section 5.** Table S1 (p3) row "Effort switches rewrite the cache: 12.9x cache writes"; main Section 5 and Fig 3 say 10.3x (11,650 vs 1,133 tokens, n = 486 and 1,331). 12.9 is the old baseline (sticky-host sessions with unchanged effort, 900 tokens). Review point H.7.1 #3 says the baseline was unified.
Fix: `build_assets.py:2704` replace `\\AoEcX` with `\\CwWithinX` (and drop `AoEcX` at :2286 if unused elsewhere).

**G4. Scrub garbling (visible nonsense).** `nopath()` (`build_assets.py:131-139`) swaps file names for "a JSON record" etc. without regard for the surrounding article. Instances: p9 "The confirmatory script, the confirmatory script (commit c3ea41a)"; p22 "(logged in a JSON record and a JSON record)"; p64 "The model is the existing a JSON record"; p64 "a Python file (PREREG constant) and a Markdown file use 0.83-0.97"; p103 "recomputes every committed the summary record from its the request log", "the post-hoc the trace analysis record", "in the directory its evidence package (Table S66)"; p104 "Its evidence directory is: its evidence package (Table S66)" (orphan line), "data/ and its the data dictionary". Also p64: the "Three further points" are numbered 5, 6, 7 (collide with items 5-7 above; were 1-3 in v2).
Fix: make `nopath()` consume a preceding determiner (`(?:\b(?:the|its|an?)\s+)?`) and emit a noun phrase without an article; then re-read H.3, H.4, C.4 (deviations) once; renumber the three points 11-13 (`generated/tables/deviations.tex` / `supp/ported/vt-appendix-b-tables.tex`).

**G5. Directory fragments still in the supplement (strict path greps are clean).** Table S56/S57 captions p78-79 "(evidence in the 2026-10-05-effort-control directory)" / "...-fable directory"; p103-104 `firstpass-repro/`, `label-audit/`, `latency/`, `data/`, `confirm/`, `model/`, `campaign/`, `prereg/`, `pilot/`, `reproduce/`, "the eval/judge-realistic branch", "benchmark folder of the repository"; `model/` p9 and p64.
Fix: caption -> "(evidence package in Table S66)"; rewrite H.3/H.4 bullets as prose ("the case manifests, run records, request logs and summary records for each split") and delete the branch name. Files: `supp/ported/vt-07c-effort.tex`, `supp/ported/jb-11-reproducibility.tex`, `supp/ported/vt-10-reproducibility.tex`, `supp/ported/vt-04-design.tex`.

### MEDIUM

**G6. Main-paper numbers with no supplement source (traceability).** Present only in the main PDF: (i) Section 5 decide-once 0.87x (0.78-0.98) Fable, 0.91x (0.85-0.97) Opus, all 46 triplets; Table S34 and Fig S14 give only the pair reading 0.862/0.917. (ii) Fig 3 and Section 5: 11,650 vs 1,133 (n = 486/1,331), 66,235 vs 67,820 (n = 24), and the bar values. (iii) Table 2: 0.0548/0.0554/0.1164 per request, 88,516/5,376/541 tokens, predicted 0.524/1.365, multipliers 1.11/1.38. (iv) Section 7 and Fig 4: 311 ms, 26,920 ms, 93 ms; effort switches 12 of 12,094 production vs 828 of 3,752 test requests; 0.2 % vs 11.4 % match rate; Jev routed 34 % vs 89 % / 97 %. (v) Section 3: Jev p95 "216-222 ms" and Sol "3.6-4.7 s"; Table S18 gives only the pooled 222 and 4,252 ms, and 216, 3.6 and 4.7 appear nowhere in the supplement.
Fix: add one table each: C.2 "H3, all-pairs and pair reading" (arm-reading row for Table S34 / Fig S14), D.3.2 "Cache writes by position, plain vs after an effort change", C.1 "Per-request price model behind main Table 2", F.1 "Production vs test routing and effort switches", and per-repetition min-max p95 columns in Table S18. Each is a few lines of `build_assets.py` output already computed for the main paper.

**G7. Caching-survey residue (JB-59, 60, 61, 62).** See Section 3. Restore from `origin/main:docs/papers/2026-09-30-judge-benchmark/sections/09a-follow-up.tex`: (a) Table 21 (same configuration, single-turn vs 4-turn: ratio, CI, pairs) beside Fig S22; (b) Table S50 footnote "27 % (42 % incl. effort-setting rewrites)" and the "593 anchors behind 903 pairs" sentence; (c) paragraphs "How much the rebuilds cost" and "Warm first requests" in D.2; (d) bullet "84 of the 90 Opus 4-turn pairs come from the 3 tuning scenarios" in the "Why a new experiment was needed" box (`supp/ported/vt-p2-survey.tex`).

**G8. Receipts evidence (P2-22) and the dangling DK reference.** Restore from v2 `sections/02-why.tex`: "A receipt is the policy grading its own homework... where the same survey could compare receipts with measurements (35 pairs), receipts claimed $2.22 saved while the measured saving was -$2.80." Put it at the head of D.2 and replace "the one DK had raised (Section 4 of the main paper)" with "the question the main paper's Section 4 opens with" (`supp/ported/vt-p2-survey.tex`).

**G9. P2-84 / P2-85 content with no home.** Add a short "C.5 Guidance and open measurements" (`supp/c-routing.tex`): the five caching-guidance hypotheses; "How to use the numbers" (measured tables for per-host/task figures, model only for pooled forecasts: partly in C.3.6); "What to measure next" (longer sessions; live predictions with intervals; new-host price check against Sonnet; larger sample for the final-test losses); the sentence that lowering the host's own effort avoids the task-type quality losses; and the Opus effort-independence result 1.18x (1.11-1.27). Source: v2 `sections/08-recommendations.tex`.

**G10. Eight tables never cited in prose:** S39 (C.3.3), S42 (C.3.5), S50 (D.2), S55 (D.4), S56 (D.4.1), S57 (D.4.2), S60 and S61 (E.2.1, E.2.3). Add one `\cref` sentence in each named subsection.

**G11. Stale "Section 8 of the main paper" in the review responses** (H.7 p106 #2, p107 #11, round-2 #2 and #8). v4 main Section 8 is Table 3 only; it does not contain the 44 %/37.3 % labelling, the "3 of 6 task types miss the margin" sentence or the "evidence does not establish the judge machinery's value" sentence. Re-point to C.3.2, D.4, A.4, or write "Section 8 of the companion report" (`supp/ported/vt-appendix-c-review.tex:18,47,83,100`).

**G12. Spend-vs-geometric-mean figures (P2-01).** Add to C.3.2 (p59), next to "$5.31 to $3.33": "a 37.3 % reduction in spend over all 70 scenarios, 42.4 % on the test split; the 44 % in earlier drafts is the geometric-mean per-session saving".

### LOW

- **G13. Duplicate real-decision text.** B.6 (p43-46) and B.7 (p47) tell the same study with two "Read this before generalizing" boxes. Keep B.6.3, replace B.7 by one sentence plus a pointer (saves about a page); fix B.6 intro "This chapter reports both" (`supp/ported/jb-09a-traces.tex:7`).
- **G14. Overclaim in the review history.** `supp/h-v4review.tex:20` ends "This version restores every figure, table and analysis of the earlier reports to this supplement." It is a process note, and 18 items are still CONDENSED. Delete it.
- **G15. Doubled periods after 65 run-in headings.** Preamble line 14 (`\titleformat{\paragraph}...[.]`) adds the period; remove the trailing "." from the 71 `\paragraph{...}` arguments in `supp/ported/*.tex` (`sed -i -E 's/\\paragraph\{([^}]*)\.\}/\\paragraph{\1}/'`).
- **G16. Navigation.** `supp.tex:30` sets `tocdepth{1}`; for a 108-page document use 2, and add `\listoffigures`/`\listoftables` or a one-page "main-paper claim -> supplement item" map.
- **G17. Float placement.** p67 Table S47 inside the S46 continuation; p96 Table S65 inside the S64 continuation. Move S47 into D.1 text (`[H]` or `\FloatBarrier` before the scenario table) and S65 to after S64.
- **G18. Optional.** JB-23: add dev-split circles to Fig S5 (data already in `generated/jb/data/accuracy.dat`). The undefined study label "S2" (G p89) collides with Figure/Table S2: write "a replication study". Duplicate headings "G" / "G.1" carry the same title. p6 has one over-stretched line in the check-example bullets.
