# v4 restore inventory: what v2, v3 and the judge-benchmark report had that v4 dropped

Repo: `michaeljabbour/fd-v3`, `origin/main` @ `a2102af`. Read-only diff. Sources: the `.tex` sources (recursive `\input` expansion: `figure`/`table`/`xltabular` envs, `keyidea`/`caution`/`casecard`/`processnote` boxes, `description`/`lstlisting`, `\section`/`\subsection`) checked against `pdftotext` of all five PDFs (figure and table counts match: JB 8 F/22 T, v2 26/43, v3 16/7, v4 main 4/3, v4 supp 12/6).

**Status legend.** `present` = same or equivalent object in v4 (main or supplement). `condensed` = the content survives but smaller (the Notes column says what was lost). `MISSING` = nothing equivalent in v4.

**Path legend.** Source paths are relative to each report dir `docs/papers/<report>/`. Evidence: EV-jb = `docs/evidence/2026-09-30-judge-benchmark/`; EV-trace = `docs/evidence/2026-10-01-trace-judge-benchmark/`; EV-caching = `docs/evidence/2026-10-01-caching/results.json`; EV-paired = `docs/evidence/2026-10-02-paired-campaign/`; EV-clef = `docs/evidence/2026-10-04-clef-judges/`; EV-effort = `docs/evidence/2026-10-05-effort-control/`; EV-effort-fable = `docs/evidence/2026-10-06-effort-control-fable/`; EV-defaults-replay = `docs/evidence/2026-10-05-defaults-replay/`; EV-v3offline = `docs/evidence/2026-10-v3-offline/` (a1-observatory, a0-counterfactual); EV-holdout-v3 = `docs/evidence/2026-10-06-holdout-v3/`; EV-openai = `docs/evidence/2026-10-06-openai-decisions/`. `data/…`, `labels/…`, `tables/…` = `generated/data|labels|tables/` written by that report's `build_assets.py`.

**"In v4 tree?"** = whether the generated table/figure file already exists under `docs/papers/2026-10-07-decision-model-fit-v4/`. v4's `build_assets.py` still regenerates every v2 table and `.dat` file (42 generated tables sit in `generated/tables/` and are never `\input`), and the judge-benchmark figures and tables sit under `generated/jb/`. What v4 lacks is the v2 figure sources: 19 `figures/fig-*.tex` files are not in v4 (aahist, band, cache, gapwrites, interim, model, perturn, ph-acclat, ph-wacov, pilot, power, probe, progress, requests, savings, scenario, survey, switch, turncomp). Copy them from v2. v2 `fig-composition.tex` is not the same file as v3/v4 `fig-composition.tex`: the names match, but the v2 file plots main-campaign data and the v3/v4 file plots S1 data.

## Counts

| Scope | Items | present | condensed | MISSING |
|---|---|---|---|---|
| Judge benchmark | 68 | 5 | 28 | 35 |
| v2 companion | 99 | 8 | 34 | 57 |
| v3 | 51 | 40 | 10 | 1 |
| **All rows** | **218** | **53** | **72** | **93** |
| **Unique (duplicates and superseded versions removed)** | **198** | **49** | **65** | **84** |

Figures and tables only (all rows): MISSING: 67, condensed: 31, present: 24.
Duplicates removed: 14 exact re-uses plus 6 judge-benchmark originals superseded by a v2 extended version. "How to read it" notes are not counted as separate rows. They belong to their figure or table: JB 13, v2 26, v3 15, v4 13. Each restored figure should bring its note back with it.


## judge benchmark report (47 pp): `docs/papers/2026-09-30-judge-benchmark/`

| ID | § | Type | Label | Caption / first sentence | Source files | Data read | v4 status | v4 location | In v4 tree? | Prio | Takeaway | Notes / duplicate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| JB-01 | 1 | key idea | `—` | Accuracy alone is the wrong headline for a judge. | `sections/01-introduction.tex` | — | condensed | main §2 Measures (prose) | — | Low | 1 | Box gone; accuracy/wrong-automatic/coverage defined in one sentence each. |
| JB-02 | 2.3 | key idea | `—` | A judge's mistakes come in two kinds: safe mistakes (fall back) and unsafe mistakes (acted on). | `sections/02-background.tex` | — | condensed | main §2 (gate + fallback prose) | — | Low | 1 | Safe/unsafe framing gone. |
| JB-03 | 2.4 | worked example (casecard) | `sec:worked` | The question the judge sees: Task 'Purchase the subscription'... | `sections/02-background.tex` | numbers.tex (Ex* macros) <- EV-jb dev logs | condensed | main §6 (one sentence: every judge clicked 'buy') | — | Med | 4 | Step-by-step Jev walkthrough (ms, probabilities, gate checks) gone. |
| JB-04 | 2.4 | table (T1) | `tab:cua18` | Every base judge's answer to cua-18 under the bundle's gate. | `sections/02-background.tex + generated/tables/case-cua-18.tex` | EV-jb dev request logs | **MISSING** | — | yes | High | 4 | Per-judge x rep outcome grid for the purchase case. |
| JB-05 | 3.1 | description list | `—` | Dev split (90 cases, screen) / holdout (63, preregistered) / case kinds. | `sections/03-method.tex` | EV-jb | condensed | main Table 1 (tab:data) rows | — | Low | M | Case-kind breakdown (read/search/select/cua counts) gone. |
| JB-06 | 3.1 | key idea | `—` | A holdout is a set of cases kept aside until the analysis is fixed. | `sections/03-method.tex` | — | condensed | supp A8 glossary 'Preregistered' | — | Low | M | No 'holdout' explanation box. |
| JB-07 | 3.2 | table (T2) | `tab:labelaudit` | Blind label audit. | `generated/tables/label-audit.tex` | EV-jb label-audit files | condensed | supp A2 prose (kappa only) | yes | Med | 1 | Per-split agreement table gone; only kappa quoted. [= v2 T1 tab:jblabel] |
| JB-08 | 3.2 | description list | `—` | Adjudication notes per flagged case (cua-18: label defensible, task under-specified...). | `generated/tables/adjudication.tex` | EV-jb audit | **MISSING** | — | yes | Low | 1 |  |
| JB-09 | 3.2 | caveat | `—` | The holdout author and both reviewers are Anthropic models (Claude Opus and Claude Sonnet). | `sections/03-method.tex` | — | condensed | main §2, supp A2 ('labels written by language models') | — | Med | 1 | Same-vendor caveat (labeller = model family under test) lost. |
| JB-10 | 3.3 | table (T3) | `tab:arms` | The 10 base judges. | `generated/tables/arms.tex` | EV-jb run config | condensed | main §2 'Models and prices' (names only) | yes | Med | 1 | Backend, size, probability source per judge lost. |
| JB-11 | 3.4 | description list | `—` | Scoring policies: bundle-read-shortcut (primary), alternatives. | `sections/03-method.tex` | — | condensed | main §2 gate definition | — | Low | 1 | Alternative policies gone. |
| JB-12 | 3.5 | key idea | `—` | For each case we take the majority outcome over the three repetitions. | `sections/03-method.tex` | — | **MISSING** | — | — | Med | M | Aggregation rule not stated in v4. |
| JB-13 | 3.6 | analysis (text) | `—` | Statistics, explained plainly: CI, McNemar, Holm, non-inferiority, calibration, latency, cost. | `sections/03-method.tex` | — | condensed | main §2 Measures; supp A8 (4 terms) | — | Med | M | Plain-language stats primer gone. |
| JB-14 | 3.7 | analysis (text) | `—` | The preregistered decision rules (Rule 1: replace Jev; Rule 2: offline tier). | `sections/03-method.tex` | EV-jb prereg | condensed | main §3 (one sentence on replacement rule) | — | Low | 1 | Rule 2 definition gone. |
| JB-15 | 4.1 | table (T4) | `tab:variance` | Repeatability over seven runs on the 90 dev cases. | `sections/04-validating-first-pass.tex (inline)` | numbers.tex <- EV-jb dev runs | **MISSING** | — | — | Med | M | Run-to-run variance. |
| JB-16 | 4.2 | analysis (text) | `—` | Harness audit (defects found in the first-pass harness). | `sections/04-validating-first-pass.tex` | EV-jb | **MISSING** | — | — | Med | M |  |
| JB-17 | 4.3 | table (T5, xltabular) | `tab:changes` | All 20 first-pass claims, what the first pass said, and what the validation found. | `generated/tables/changes.tex` | EV-jb + git history | **MISSING** | — | yes | Med | REF | [= v2 T43] |
| JB-18 | 5.1 | table (T6) | `tab:headline-dev` | Dev split [screen], 90 cases, 3 repetitions, policy bundle-read-shortcut. | `generated/tables/headline-dev.tex` | EV-jb dev summary | **MISSING** | — | yes | Med | 1 | Dev split only appears for the Decisions API table. |
| JB-19 | 5.2 | figure (F1) | `fig:wacov-dev` | Wrong automatic rate against coverage on the dev split [screen]. | `figures/fig-wa-coverage.tex (dev)` | data/scatter-dev-{cloud,local,jev}.dat; labels/wacov-dev.tex | **MISSING** | — | yes | Med | 1 | Safety-usefulness trade-off plot. |
| JB-20 | 5.3 | table (T7) | `tab:rule1-dev` | Rule 1 on the dev split [screen]: each candidate minus Jev. | `generated/tables/rule1-dev.tex` | EV-jb dev | **MISSING** | — | yes | Med | 1 |  |
| JB-21 | 5.4 | analysis (text) | `—` | Interventions on dev. | `sections/05-results-dev.tex` | EV-jb dev | condensed | supp A2 (Jev dev I1 count) | — | Med | 4 | Per-judge dev intervention results gone. |
| JB-22 | 6.1 | table (T8) | `tab:headline-hold` | Holdout [preregistered], 63 cases, 3 repetitions, policy bundle-read-shortcut. | `generated/tables/headline-holdout.tex` | EV-jb holdout summary | condensed | supp Fig S1 + main §3 prose | yes | High | 1 | Accuracy/cost/p95 quoted for 3 judges; wrong-auto, coverage, ECE, p50 columns for all 10 arms lost. [= v2 T2 tab:jbheadline] |
| JB-23 | 6.1 | figure (F2) | `fig:accuracy` | Accuracy of every arm on both splits, with 95% Wilson intervals. | `figures/fig-accuracy.tex` | data/accuracy.dat | condensed | supp Fig S1 (v2 fig-ph-accuracy) | yes | Low | 1 | Dev-split points dropped (holdout only); Clef added. [superseded by v2 F1] |
| JB-24 | 6.2 | table (T9) | `tab:rule1-hold` | Rule 1 on the holdout: each candidate minus Jev, paired-bootstrap CIs, Holm-adjusted McNemar p. | `generated/tables/rule1-holdout.tex` | EV-jb holdout | condensed | main §3 prose (Luna/Sol diffs, CIs, Holm p) | yes | Med | 1 | Local-judge rows and wrong-auto contrasts lost. |
| JB-25 | 6.2 | caveat | `—` | The bootstrap intervals for Luna and Sol exclude zero, but Holm-adjusted McNemar tests do not reach 0.05. | `sections/06-results-holdout.tex` | — | present | main §3 + supp A2 (prose) | — |  | 1 | Same content, not boxed. |
| JB-26 | 6.3 | table (T10) | `tab:pairwise` | The 13 contrasts declared in the run configuration, both splits, accuracy and wrong-automatic rate. | `generated/tables/pairwise.tex` | EV-jb | **MISSING** | — | yes | Med | 1 |  |
| JB-27 | 6.4 | figure (F3) | `fig:wacov-hold` | Wrong automatic rate against coverage on the holdout, 95% Wilson intervals. | `figures/fig-wa-coverage.tex (holdout)` | data/scatter-holdout-*.dat; labels/wacov-holdout.tex | **MISSING** | — | yes | Low | 1 | [superseded by v2 F2] |
| JB-28 | 6.4 | figure (F4) | `fig:acclat` | Accuracy against p95 latency (log scale) on the holdout. | `figures/fig-acc-latency.tex` | data/scatter-holdout-*.dat; labels/acclat-holdout.tex | **MISSING** | — | yes | Low | 1 | Latency only as prose numbers in v4. [superseded by v2 F3] |
| JB-29 | 6.5 | figure (F5) | `fig:sweep` | Threshold sweep (coverage and wrong-automatic rate vs certainty cutoff). | `figures/fig-sweep.tex` | data/sweep-dev.dat, sweep-holdout.dat | **MISSING** | — | yes | High | 1 | Gate-cutoff sensitivity analysis. |
| JB-30 | 6.5 | table (T11) | `tab:threshold` | Automatic / wrong automatic decisions at selected cutoffs, holdout. | `generated/tables/threshold-holdout.tex` | EV-jb holdout | **MISSING** | — | yes | High | 1 |  |
| JB-31 | 7 | description list | `—` | Failure-mode classes (acted on side effect, under-deferred, accepted wrong code, injection...). | `sections/07-failure-modes.tex` | — | **MISSING** | — | — | Low | 1 |  |
| JB-32 | 7.1 | table (T12) | `tab:fail-all` | Holdout: all wrong answers by class (mean per repetition). | `generated/tables/failure-holdout.tex` | EV-jb holdout | **MISSING** | — | yes | Med | 1 |  |
| JB-33 | 7.1 | table (T13) | `tab:fail-auto` | Holdout: only the wrong answers the bundle would have acted on. | `generated/tables/failure-auto-holdout.tex` | EV-jb holdout | **MISSING** | — | yes | High | 4 |  |
| JB-34 | 7.2 | analysis (text) | `—` | Root causes: side effects (instruction), accepted wrong code, injection following, confident cloud mistakes. | `sections/07-failure-modes.tex` | EV-jb | condensed | main §6 (one clause: models follow the task unless the risk rule is stated) | — | Med | 4 | Injection and calibration findings gone. |
| JB-35 | 7.3 | description list | `—` | Interventions I1 (side-effect clause), I2 (host guard), I3 (yes/no gate). | `sections/07-failure-modes.tex` | — | condensed | supp A2 (I1, I2 only) | — | Med | 4 | I3 dropped. |
| JB-36 | 7.3 | table (T14) | `tab:interventions` | Interventions on both splits. | `generated/tables/interventions.tex` | EV-jb | condensed | main §6 + supp A2 prose (holdout totals) | yes | High | 4 | Per-judge, per-split, coverage-cost rows gone. |
| JB-37 | 7.3 | figure (F6) | `fig:i2` | The host guard (I2) on the holdout: side-effect wrong automatic decisions per judge, without and with the guard. | `figures/fig-i2.tex` | data/i2-holdout.dat | condensed | main §6 prose ('38 to 0') | yes | High | 4 | Per-judge bars gone. [= v2 F6 fig:jbi2] |
| JB-38 | 7.3 | key idea | `—` | The most effective safety measure is not a better model but a dumb, deterministic rule in the host. | `sections/07-failure-modes.tex` | — | present | main §6 claim + For practitioners | — |  | 4 |  |
| JB-39 | 8.1 | figure (F7) | `fig:anatomy` | Where the time goes in one call (medians of each component). | `figures/fig-latency-anatomy.tex` | data/latency-cloud.dat, latency-local.dat | **MISSING** | — | yes | High | 1 | [= v2 F5 fig:jblatency] |
| JB-40 | 8.1 | table (T15) | `tab:anatomy` | The numbers behind the latency anatomy figure. | `generated/tables/latency-anatomy.tex` | EV-jb latency | **MISSING** | — | yes | Med | 1 |  |
| JB-41 | 8.1 | table (T16) | `tab:concurrency` | Latency and throughput as requests in flight rise. | `generated/tables/latency-concurrency.tex` | EV-jb latency | **MISSING** | — | yes | Med | 1 | Concurrency study. |
| JB-42 | 8.1 | caveat | `—` | Local latency is a property of this host at that time, not of the model. | `sections/08-latency-and-cost.tex` | — | **MISSING** | — | — | Med | 1 |  |
| JB-43 | 8.2 | table (T17) | `tab:cost` | Projected monthly API cost and wrong automatic actions at 100,000 decisions per day. | `generated/tables/cost.tex` | EV-jb holdout rates + prices | **MISSING** | — | yes | Med | 1 | Cost-at-scale projection. |
| JB-44 | 8.2 | caveat | `—` | The wrong-action column assumes real traffic has the benchmark's decision mix. | `sections/08-latency-and-cost.tex` | — | **MISSING** | — | — | Med | 1 |  |
| JB-45 | 9.1 | key idea | `—` | Keep Jev 1.13 as the default judge. | `sections/09-recommendations.tex` | — | present | main §3 For practitioners | — |  | 1 |  |
| JB-46 | 9.2 | key idea | `—` | Adopt intervention I2: never act automatically on an option naming an irreversible side effect. | `sections/09-recommendations.tex` | — | present | main §6 | — |  | 4 |  |
| JB-47 | 9.3 | analysis (text) | `—` | Cloud fallback when Jev is unreachable: GPT-6 Luna, behind the guard. | `sections/09-recommendations.tex` | EV-jb | **MISSING** | — | — | Med | 1 | No fallback-judge recommendation in v4. |
| JB-48 | 9.4 | table (T18) | `tab:rule2` | Rule 2, the offline tier: local judges under the strictest policy. | `generated/tables/rule2.tex` | EV-jb | condensed | main §3 (one sentence: no local model met the safety bar) | yes | Med | 1 |  |
| JB-49 | 9.5-9.7 | analysis (text) | `—` | What is within noise; what the follow-ups add; what would change these recommendations. | `sections/09-recommendations.tex` | — | condensed | main §3, §9 | — | Low | 1 | 'What would change the recommendation' list gone. |
| JB-50 | 9.8 | caveat | `—` | Measured before these changes: every result was measured before the listed changes were merged. | `sections/09-recommendations.tex` | — | **MISSING** | — | — | Med | REF |  |
| JB-51 | 10 | key idea | `—` | Two new questions, two new kinds of evidence. | `sections/09a-follow-up.tex` | — | **MISSING** | — | — | Low | 1 | Framing box. |
| JB-52 | 10.1 | key idea + text | `—` | 'What the host did next' is not the same as 'what was enough'; how trace cases were rebuilt, labelled, replayed, preregistered. | `sections/09a-follow-up.tex` | EV-trace | condensed | main §2 Data; supp A2 (kappa vs host) | — | Low | 1 | Fingerprinting/replay method gone. |
| JB-53 | 10.2 | table (T19) | `tab:trace` | Real read-shortcut decisions, holdout: 42 cases, 3 repetitions. | `generated/tables/trace-holdout.tex` | EV-trace holdout/summary.json | condensed | supp Fig S2 + main §3 prose | yes | Low | 1 | Per-judge counts table gone. [= v2 T6 tab:jbtrace] |
| JB-54 | 10.2 | figure (F8) | `fig:reads` | Real decisions: correct automatic reads against wrong automatic reads, holdout. | `figures/fig-reads.tex` | data/reads-{cloud,jev,local}.dat; labels/reads-holdout.tex | present | supp Fig S2 (v2 fig-ph-reads, + Clef) | — |  | 1 | [superseded by v2 F7 = v3 F6] |
| JB-55 | 10.2 | analysis (text) | `—` | Why accuracy misleads here (always-fallback scores highest); cost of a wrong read; scoring against the host's next read. | `sections/09a-follow-up.tex` | EV-trace | **MISSING** | — | — | Med | 1 |  |
| JB-56 | 10.3 | caveat | `—` | Read this before generalizing (scope and selection of the trace cases). | `sections/09a-follow-up.tex` | — | **MISSING** | — | — | Med | 1 | [= v2 caveat §3] |
| JB-57 | 10.4 | key idea | `—` | Three prices matter (input, cache read, cache write). | `sections/09a-follow-up.tex` | — | condensed | main §4 claim | — | Low | 2 |  |
| JB-58 | 10.4 | table (T20) | `tab:prices` | Price table behind every cost in this section (USD per million tokens). | `sections/09a-follow-up.tex (inline)` | numbers.tex | condensed | main §2 prose | — | Low | 2 | Table -> one sentence. [superseded by v2 T10] |
| JB-59 | 10.4 | table (T21) | `tab:samecell` | Cost ratio for the same cell in single-turn and 4-turn sessions. | `sections/09a-follow-up.tex (inline)` | EV-caching results.json | **MISSING** | — | — | Low | 3 | [superseded by v2 F8] |
| JB-60 | 10.4 | table (T22) | `tab:rebuild` | Rebuild cost after model switches, by stratum. | `sections/09a-follow-up.tex (inline)` | EV-caching | **MISSING** | — | — | Low | 3 | [= v2 T9] |
| JB-61 | 10.4 | analysis (text) | `—` | Caching survey: price vs volume (about half each), rebuild cost, warm first requests, proposed experiment. | `sections/09a-follow-up.tex` | EV-caching | **MISSING** | — | — | Low | 2 |  |
| JB-62 | 10.4 | caveat | `—` | What the caching study did not show (longer and real chats...). | `sections/09a-follow-up.tex` | — | **MISSING** | — | — | Med | 3 |  |
| JB-63 | 10.5 | analysis (text) | `—` | New findings for the bundle (defects found by the trace study). | `sections/09a-follow-up.tex` | EV-trace | **MISSING** | — | — | Low | M | [~ v2 T8 tab:prfixes] |
| JB-64 | 11 | analysis (text) | `—` | Limitations. | `sections/10-limitations.tex` | — | condensed | main §2 'common limits', §9 scope | — | Low | M |  |
| JB-65 | 12 | code listing + text | `—` | Reproducibility: evidence, runs, replaying the numbers (PYTHONPATH=... commands). | `sections/11-reproducibility.tex` | — | condensed | main §9 data availability + supp Table S1 | — | Med | REF | Replay commands, run commits gone. |
| JB-66 | App A | glossary (37 terms) | `—` | Argmax ... Wrong-automatic rate. | `sections/appendix-a-glossary.tex` | — | condensed | supp A8 (17 terms) | — | High | REF | Judge-side terms gone: coverage, wrong-automatic rate, gate, host guard, McNemar, kappa, ECE, p50/p95, screen, holdout, injection... |
| JB-67 | App B | analysis (text) | `—` | The holdout labeling guide (principle, case kinds, choice/search cases, untrusted data, tags). | `sections/appendix-b-labeling-guide.tex` | — | **MISSING** | — | — | High | REF |  |
| JB-68 | App C | worked examples (6 casecards + 2 listings) | `—` | Case examples: fresh-cua-09, search-11, hold-cua-00, hold-cua-12, hold-select-06, hold-search-15. | `generated/tables/case-examples.tex` | EV-jb cases + logs | **MISSING** | — | yes | High | REF |  |

## v2 companion technical report (64 pp): `docs/papers/2026-10-02-paired-measurement/`

| ID | § | Type | Label | Caption / first sentence | Source files | Data read | v4 status | v4 location | In v4 tree? | Prio | Takeaway | Notes / duplicate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P2-01 | 1 | key idea | `—` | What we found (test split; hypotheses preregistered, estimator after the data). | `sections/01-summary.tex` | numbers.tex | condensed | main abstract, §9 | — | Low | 2 |  |
| P2-02 | 2 | key idea | `—` | A judge is useful when it is right when it acts and acts often enough to matter. | `sections/p1-01-judges.tex` | — | condensed | main §2 Measures | — | Low | 1 |  |
| P2-03 | 2.1 | table (T1) | `tab:jblabel` | Blind label audit of the judge benchmark. | `generated/jb/tables/label-audit.tex` | EV-jb | condensed | supp A2 (kappa) | yes | Low | 1 | [dup of JB-07] |
| P2-04 | 2.2 | table (T2) | `tab:jbheadline` | Judge benchmark holdout: accuracy, wrong automatic, coverage, latency, cost. | `generated/jb/tables/headline-holdout.tex` | EV-jb | condensed | supp Fig S1 + main §3 | yes | Low | 1 | [dup of JB-22] |
| P2-05 | 2.2 | figure (F1) | `fig:jbaccuracy` | Holdout accuracy with 95% Wilson intervals: preregistered run, then post hoc Clef run. | `figures/fig-ph-accuracy.tex` | data/ph-acc-pre.dat, ph-acc-post.dat | present | supp Fig S1 | — |  | 1 | [= v3 F4] |
| P2-06 | 2.2 | figure (F2) | `fig:jbwacov` | Wrong-automatic rate against coverage on the holdout, with the post hoc Clef arms. | `figures/fig-ph-wacov.tex` | jb/data/scatter-holdout-*.dat, data/ph-hold-{clef,jev}.dat; labels/wacov-holdout-ph.tex | **MISSING** | — | no (copy from source report) | High | 1 | Only safety-vs-usefulness view of the judges. [supersedes JB-27] |
| P2-07 | 2.2 | figure (F3) | `fig:jbacclat` | Accuracy against p95 latency (log scale) on the holdout, with the post hoc Clef arms. | `figures/fig-ph-acclat.tex` | jb/data/scatter-holdout-*.dat, ph-hold-*.dat; labels/acclat-holdout-ph.tex | **MISSING** | — | no (copy from source report) | High | 1 | [supersedes JB-28] |
| P2-08 | 2.2 | figure (F4) | `fig:jbcost` | Cost per million decisions (log) against holdout accuracy, for priced judges. | `figures/fig-ph-costacc.tex` | data/ph-cost-pre.dat, ph-cost-post.dat; labels/costacc-holdout.tex | condensed | main Fig 1 fig:frontier (redrawn) | yes | High | 1 | Wilson error bars dropped; Decisions API point added. fig-ph-costacc.tex still in v4 tree, unused. [= v3 F5] |
| P2-09 | 2.3 | figure (F5) | `fig:jblatency` | Where the time goes in one judge call: cloud (top) and local (bottom). | `generated/jb/figures/fig-latency-anatomy.tex` | jb/data/latency-*.dat | **MISSING** | — | yes | Low | 1 | [dup of JB-39] |
| P2-10 | 2.3 | figure (F6) | `fig:jbi2` | The side-effect guard (I2) on the holdout: targeted wrong automatic decisions before and after. | `generated/jb/figures/fig-i2.tex` | jb/data/i2-holdout.dat | condensed | main §6 prose | yes | Low | 4 | [dup of JB-37] |
| P2-11 | 2.3 | analysis (text) | `—` | Validating an earlier first pass. | `sections/p1-01-judges.tex` | EV-jb | **MISSING** | — | — | Low | M | [dup of JB-15/16] |
| P2-12 | 2.4 | table (T3) | `tab:clefresults` | Post hoc run: Clef, Clef-Flash and in-run Jev on all four splits. | `generated/tables/clef-results.tex` | EV-clef (2026-10-04-clef-judges) | condensed | supp Fig S1/S2, main Fig 1, §3 prose | yes | High | 1 | Four-split table with latency and cost gone. |
| P2-13 | 2.4 | table (T4) | `tab:clefcontrasts` | Post hoc paired contrasts (McNemar exact on per-case majority). | `generated/tables/clef-contrasts.tex` | EV-clef | **MISSING** | — | yes | Med | 1 |  |
| P2-14 | 2.4 | table (T5) | `tab:clefrule1` | Preregistered default-judge rule applied descriptively to the post hoc arms. | `generated/tables/clef-rule1.tex` | EV-clef | condensed | main §3 ('no challenger met the rule') | yes | Low | 1 |  |
| P2-15 | 2.4 | key idea | `—` | Clef matches Jev's accuracy but costs several times more and answers ~3x slower. | `sections/p1-clef.tex` | — | condensed | main §3 prose | — | Low | 1 |  |
| P2-16 | 3 | table (T6) | `tab:jbtrace` | Real decisions, holdout: 42 cases. | `generated/jb/tables/trace-holdout.tex` | EV-trace | condensed | supp Fig S2 | yes | Low | 1 | [dup of JB-53] |
| P2-17 | 3 | table (T7) | `tab:clefrule2` | Rule 2 ('useful' read shortcut) on both trace splits for the post hoc run. | `generated/tables/clef-rule2.tex` | EV-clef | condensed | supp Fig S2 (Clef points) | yes | Med | 1 | Trace-dev split gone. |
| P2-18 | 3 | figure (F7) | `fig:jbreads` | Real decisions: correct vs wrong automatic reads on trace-holdout, + post hoc Clef. | `figures/fig-ph-reads.tex` | data/ph-reads-{clef,jev}.dat, jb/data/reads-*.dat; labels/reads-holdout-ph.tex | present | supp Fig S2 | — |  | 1 | [= v3 F6; supersedes JB-54] |
| P2-19 | 3 | caveat | `—` | Read this before generalizing (selection...). | `sections/p1-02-traces.tex` | — | **MISSING** | — | — | Low | 1 | [dup of JB-56] |
| P2-20 | 3.1 | table (T8) | `tab:prfixes` | The four defects found by the real-decision study and their fixes (PR #58). | `sections/p1-02-traces.tex (inline)` | numbers.tex | **MISSING** | — | — | Low | M | [~ JB-63] |
| P2-21 | 4 | key idea | `—` | The only way to know what routing costs is to run the same work twice and compare. | `sections/02-why.tex` | — | present | main §4 'Why we measured whole sessions' | — |  | 2 |  |
| P2-22 | 4 | analysis (text) | `—` | Receipts are claims, not measurements; caching makes cost depend on history; DK's question. | `sections/02-why.tex` | telemetry receipts | present | supp A5 'Claimed savings were estimates'; main §4 | — |  | 5 |  |
| P2-23 | 5 | figure (F8) | `fig:survey` | Earlier caching survey: same configuration in single-turn and 4-turn sessions, 95% bootstrap. | `figures/fig-survey.tex` | data/survey-samecell.dat <- EV-caching results.json | **MISSING** | — | no (copy from source report) | High | 3 | [supersedes JB-59] |
| P2-24 | 5 | table (T9) | `tab:surveyrebuild` | Earlier survey: share of routed runs' cost spent re-writing caches after a switch. | `sections/p2-survey.tex (inline)` | EV-caching | **MISSING** | — | — | Med | 3 | [dup of JB-60] |
| P2-25 | 5 | caveat | `—` | Why a new experiment was needed (<=4 turns, few synthetic scenarios, caches never expired). | `sections/p2-survey.tex` | — | **MISSING** | — | — | Med | 3 |  |
| P2-26 | 5 | analysis (text) | `—` | Price and volume, about half each (survey-pricevolume.dat built but not plotted). | `sections/p2-survey.tex` | data/survey-pricevolume.dat | **MISSING** | — | — | Low | 2 | [dup of JB-61] |
| P2-27 | 6 | table (T10) | `tab:prices` | Price per million tokens (USD), by model and token class. | `sections/03-caching.tex (inline)` | numbers.tex | condensed | main §2 prose | — | High | 2 | [supersedes JB-58] |
| P2-28 | 6 | table (T11) | `tab:breakeven` | Opus-host cost ratios if Opus cache reads cost more than list (price sensitivity sweep). | `generated/tables/breakeven.tex` | EV-paired rows repriced | condensed | main §4 (one break-even number) | yes | High | 2 | Sweep over read prices, both readings, gone. |
| P2-29 | 6 | figure (F9) | `fig:cache` | How the prompt cache behaves over a conversation (schematic). | `figures/fig-cache.tex` | none (schematic) | **MISSING** | — | no (copy from source report) | High | 3 | Conceptual figure that explains takeaway 3. |
| P2-30 | 6 | table (T12) | `tab:probe` | The cache-semantics probe. | `generated/tables/probe.tex` | docs/design/pilot-20261001/step1_cache_probe.json | **MISSING** | — | yes | High | 3 |  |
| P2-31 | 6 | figure (F10) | `fig:probe` | The probe requests drawn: tokens written and read by each. | `figures/fig-probe.tex` | data/probe.dat; tables/probe-key.tex, probe-ticks.tex | **MISSING** | — | no (copy from source report) | High | 3 |  |
| P2-32 | 6 | key idea | `—` | Six facts from the probe shaped the experiment. | `sections/03-caching.tex` | probe json | condensed | main §5 (switch invalidates prefix; 5-min lifetime) | — | Med | 3 |  |
| P2-33 | 7.1 | analysis (text) | `—` | How the design evolved. | `sections/04-design.tex` | docs/design/parallel-measurement-mode.md | **MISSING** | — | — | Med | M |  |
| P2-34 | 7.2 | key idea | `—` | Pairing removes most of the noise. | `sections/04-design.tex` | — | present | main §2 'What makes this evidence strong' | — |  | M |  |
| P2-35 | 7.3 | table (T13) | `tab:arms` | The five arms. | `sections/04-design.tex (inline)` | — | **MISSING** | — | — | High | M | Arms (plain, sticky, shipped, sonnet...) never defined in v4. |
| P2-36 | 7.3 | table (T14) | `tab:effortmix` | Main-loop requests by host, arm, model and reasoning effort. | `generated/tables/effort-mix.tex` | EV-paired requests | **MISSING** | — | yes | High | 3 | Evidence for the effort confound. |
| P2-37 | 7.4 | table (T15) | `tab:families` | Scenarios by family and preregistered split. | `sections/04-design.tex (inline)` | evals/paired scenarios | **MISSING** | — | — | Med | M |  |
| P2-38 | 7.6 | table (T16) | `tab:tpfinal` | Correlation between turn-pass fraction and final hidden tests (point-biserial). | `generated/tables/tp-final-corr.tex` | EV-paired sessions | **MISSING** | — | yes | Med | M | Quality-instrument validity. |
| P2-39 | 7.6 | examples list | `—` | Quality-instrument examples (turn checks). | `generated/tables/quality-examples.tex` | EV-paired transcripts | **MISSING** | — | yes | Med | M |  |
| P2-40 | 7.7 | table (T17) | `tab:staticresid` | Un-normalized static-write cost per session. | `generated/tables/static-residual.tex` | EV-paired | **MISSING** | — | yes | Med | M |  |
| P2-41 | 7.7 | table (T18) | `tab:toolsnorm` | Tools normalization by host and arm. | `generated/tables/tools-norm.tex` | EV-paired | condensed | main §2 Measures, supp A4 (one % figure) | yes | Med | M |  |
| P2-42 | 7.7 | table (T19) | `tab:toolsratios` | Confirmatory ratios on raw vs tools-normalized basis. | `generated/tables/tools-ratios.tex` | EV-paired | **MISSING** | — | yes | Med | M | Sensitivity of headline to normalization. |
| P2-43 | 7.8 | analysis (text) | `—` | Hypotheses and the decision rule; what was fixed later; ratios and intervals. | `sections/04-design.tex` | prereg | condensed | supp A3 Design | — | Low | M |  |
| P2-44 | 7.9 | table (T20) | `tab:power` | Projected precision of the routing ratio (power analysis). | `generated/tables/power.tex` | docs/design/parallel-measurement-mode.md | **MISSING** | — | yes | High | M |  |
| P2-45 | 7.9 | figure (F11) | `fig:power` | Projected 95% CI half-width vs number of scenarios. | `figures/fig-power.tex` | data/power-curve.dat; tables/power-legend.tex | **MISSING** | — | no (copy from source report) | High | M |  |
| P2-46 | 7.10 | figure (F12) | `fig:pilot` | Second screening pilot (40 pairs, 5 scenarios) against the full campaign. | `figures/fig-pilot.tex` | data/pilot.dat <- EV-paired/pilot/pairs.jsonl | condensed | main Fig 2 (pilot rows, sticky only) | no (copy from source report) | Med | 2 | Per-arm pilot-vs-final comparison gone. |
| P2-47 | 8.1 | key idea | `—` | A guard that kills runaway sessions is only fair if its kills are counted. | `sections/05-running.tex` | evals/paired README | **MISSING** | — | — | Med | M | Memory guard. |
| P2-48 | 8.2 | table (T21) | `tab:failures` | Failed wave attempts by cause. | `generated/tables/failures.tex` | EV-paired | **MISSING** | — | yes | High | M | Main-campaign flags/failures (S1 only in v4 process note). |
| P2-49 | 8.3 | figure (F13) | `fig:progress` | Campaign progress: sessions completed and spend over time. | `figures/fig-progress.tex` | data/progress.dat, failures-time.dat, throughput.dat | **MISSING** | — | no (copy from source report) | High | M | Timeline of the run. |
| P2-50 | 8.4 | analysis (text) | `—` | Spend and time; provenance (prereg commit/time). | `sections/05-running.tex` | EV-paired ledger | condensed | supp A1 Spend | — | Low | M | Prereg timestamps/commit gone. |
| P2-51 | 9 | table (T22) | `tab:primary` | Primary endpoint: geometric-mean cost ratio, arm over plain host, test split. | `generated/tables/primary.tex` | EV-paired | condensed | supp Fig S4 (same ratios as dots) | yes | Med | 2 | n, both readings in tabular form gone. |
| P2-52 | 9 | figure (F14) | `fig:forest` | Confirmatory cost ratios on the test split. | `figures/fig-forest.tex` | data/forest.dat, forest-h3.dat | present | supp Fig S4 | — |  | 2 | [= v3 F8] |
| P2-53 | 9.1 | table (T23) | `tab:hyp` | The preregistered hypotheses, test split, pair reading. | `generated/tables/hypotheses.tex` | EV-paired | **MISSING** | — | yes | High | 2 | Main-campaign verdict table; only H3 (0.87/0.91) quoted in main §5. |
| P2-54 | 9.2 | table (T24) | `tab:quality` | Quality: mean turn-pass difference, arm minus plain host, test split. | `generated/tables/quality.tex` | EV-paired | **MISSING** | — | yes | High | 2 | Main-campaign quality result absent. |
| P2-55 | 9.3 | figure (F15) | `fig:model` | The savings model: predicted vs observed total saving per arm/host. | `figures/fig-model.tex` | data/model-check-{fable,opus}.dat; labels/model-check.tex | **MISSING** | — | no (copy from source report) | High | M | Model fitting & validation. |
| P2-56 | 9.4 | analysis (text) | `—` | Decision (what the confirmatory results decide). | `sections/06-confirmatory.tex` | — | condensed | main §4 | — | Low | 2 |  |
| P2-57 | 10.1 | figure (F16) | `fig:composition` | Mean cost per session split by what was paid for (main campaign, incl. rebuild). | `figures/fig-composition.tex (v2 version)` | data/composition.dat | condensed | supp Fig S11 is the S1 analogue (s1-composition.dat) | no (copy from source report) | High | 2 | Main-campaign arms and 'rebuild' class gone. Same filename, different data in v3/v4. |
| P2-58 | 10.1 | table (T25) | `tab:composition` | The numbers behind the composition figure: $/session by token class, requests, cache reads. | `generated/tables/composition.tex` | EV-paired | **MISSING** | — | yes | High | 2 |  |
| P2-59 | 10.2 | figure (F17) | `fig:savings` | Dollars saved per 1,000 sessions by task type and arm, 90% ranges. | `figures/fig-savings.tex` | data/savings-{fable,opus}.dat | **MISSING** | — | no (copy from source report) | High | 2 | S1 subgroup fig is a partial analogue. |
| P2-60 | 10.2 | table (T26) | `tab:per1000` | Measured saving per 1,000 sessions by task type, host and arm. | `generated/tables/per1000.tex` | EV-paired | **MISSING** | — | yes | High | 2 |  |
| P2-61 | 10.2 | table (T27) | `tab:tasksplit` | Scenarios by task type and preregistered split. | `generated/tables/task-split.tex` | evals/paired | **MISSING** | — | yes | Med | M |  |
| P2-62 | 10.3 | table (T28) | `tab:passrates` | Final hidden-test pass rate by arm vs plain host (McNemar). | `generated/tables/passrates.tex` | EV-paired | **MISSING** | — | yes | Med | 2 |  |
| P2-63 | 10.4 | analysis (text) | `—` | The noise floor (A/A). | `sections/07-exploratory.tex` | EV-paired A/A pairs | condensed | supp A4 process note (S1 A/A turn-pass only) | — | Med | M |  |
| P2-64 | 10.5 | figure (F18) | `fig:interim` | Cost ratio of each routed arm as evidence accumulated: pilot, interim, final train/test. | `figures/fig-interim.tex` | data/interim-{fable,opus}.dat | condensed | main Fig 2 replication (pilot/train/test/S1, sticky only) | no (copy from source report) | Med | 2 | Interim-dashboard stage, shipped/sonnet arms gone. |
| P2-65 | 10.6 | analysis (text) | `—` | Limits of the savings model. | `sections/07-exploratory.tex` | — | **MISSING** | — | — | Med | M |  |
| P2-66 | 11.1 | figure (F19) | `fig:perturn` | Mean cost of each turn by turn index, per arm and host. | `figures/fig-perturn.tex` | data/perturn-{fable,opus}.dat | **MISSING** | — | no (copy from source report) | Med | 3 |  |
| P2-67 | 11.1 | figure (F20) | `fig:turncomp` | What each turn of a plain-host session paid for, by turn index. | `figures/fig-turncomp.tex` | data/turncomp-{fable,opus}.dat | **MISSING** | — | no (copy from source report) | Med | 3 |  |
| P2-68 | 11.2 | figure (F21) | `fig:gapwrites` | Cache-write tokens on first request of a turn, after short vs long pause, per arm and host. | `figures/fig-gapwrites.tex` | data/gapwrites.dat | condensed | main Fig 3 fig:cachewrites (new re-analysis) | no (copy from source report) | High | 3 | Per-arm/per-host breakdown gone; v4 contrasts plain vs effort-change. |
| P2-69 | 11.3 | figure (F22) | `fig:switch` | Shipped arm: number of model switches leading into each turn. | `figures/fig-switch.tex` | data/switch-timing.dat | **MISSING** | — | no (copy from source report) | Med | 3 |  |
| P2-70 | 11.4 | figure (F23) | `fig:scenario` | Scenario by scenario: plain Fable cost vs sticky saving. | `figures/fig-scenario.tex` | data/scenario-scatter.dat; labels/scenario-scatter.tex | **MISSING** | — | no (copy from source report) | Med | 2 | S1 per-scenario Fig S7 is a partial analogue. |
| P2-71 | 11.5 | figure (F24) | `fig:aahist` | Distribution of log cost ratio between two identical plain-host sessions (A/A). | `figures/fig-aahist.tex` | data/aa-hist.dat | **MISSING** | — | no (copy from source report) | High | M |  |
| P2-72 | 11.6 | table (T29) | `tab:qualityfamily` | Mean turn-pass difference by scenario family. | `generated/tables/quality-family.tex` | EV-paired | **MISSING** | — | yes | Med | 2 |  |
| P2-73 | 11.6 | table (T30) | `tab:jointfamily` | Savings and quality together, by family. | `generated/tables/joint-family.tex` | EV-paired | **MISSING** | — | yes | Med | 2 |  |
| P2-74 | 11.6 | table (T31) | `tab:jointtask` | Savings and quality together, by task type. | `generated/tables/joint-task.tex` | EV-paired | **MISSING** | — | yes | Med | 2 |  |
| P2-75 | 11.6 | table (T32) | `tab:taskfable` | Fable sticky by task type with 95% CIs on saving per 1,000 sessions. | `generated/tables/task-fable-sticky.tex` | EV-paired | **MISSING** | — | yes | High | 2 | Origin of keep_on_host review/explain. |
| P2-76 | 11.7 | figure (F25) | `fig:requests` | Main-loop requests per session by kind of session (box plot). | `figures/fig-requests.tex` | tables/requests-box.tex | condensed | main Table 2 (request multiplier 1.11/1.38 only) | no (copy from source report) | Med | 2 | Distribution gone. |
| P2-77 | 11.8 | figure (F26) | `fig:band` | Cost ratio by scripted session length. | `figures/fig-band.tex` | data/band-{fable,opus}-{shipped,sticky}.dat | **MISSING** | — | no (copy from source report) | Med | 3 |  |
| P2-78 | 12 | table (T33) | `tab:effort` | Sticky sessions that chose Sonnet vs plain-Sonnet control (effort confound). | `sections/07c-effort.tex (inline)` | EV-paired | **MISSING** | — | — | High | 3 |  |
| P2-79 | 12 | analysis (text) | `—` | The effort confound: what medium-effort sessions did differently; two corrections. | `sections/07c-effort.tex` | EV-paired | condensed | supp A3 effort follow-ups, A7 review | — | Med | 3 |  |
| P2-80 | 12.1 | table (T34) | `tab:effortfollow` | Effort-control follow-up (plain Sonnet medium vs default). | `generated/tables/effort-control.tex` | EV-effort (2026-10-05-effort-control) | condensed | supp Fig S10 row + A3 prose | yes | High | 3 | Cross-study 0.958 row, turn-pass row, provenance caveat gone. |
| P2-81 | 12.1 | key idea | `—` | The effort setting alone explains most of the sticky-vs-plain-Sonnet gap. | `sections/07c-effort.tex` | — | condensed | supp A3 | — | Low | 3 |  |
| P2-82 | 12.2 | table (T35) | `tab:effortfable` | Fable effort follow-up (plain Fable medium vs default). | `generated/tables/effort-fable.tex` | EV-effort-fable (2026-10-06-effort-control-fable) | condensed | supp Fig S10 row | yes | High | 3 |  |
| P2-83 | 13 | key idea | `—` | Fable 5.1: move the session to Sonnet, and decide once. | `sections/08-recommendations.tex` | — | present | main Table 3 | — |  | 2 |  |
| P2-84 | 13 | key idea | `—` | Opus 5.5: do not route to Sonnet. | `sections/08-recommendations.tex` | — | present | main Table 3 | — |  | 2 |  |
| P2-85 | 13 | analysis (text) | `—` | How much of the saving is the router vs effort; quality by task type; caching guidance; how to use the numbers; what to measure next. | `sections/08-recommendations.tex` | — | condensed | main §4 (plain Sonnet vs plain Fable), §5, §9 | — | Low | 2 |  |
| P2-86 | 14 | analysis (text) | `—` | Limitations and threats to validity. | `sections/09-limitations.tex` | — | condensed | main §2, §9 | — | Low | M |  |
| P2-87 | 15 | code listing + text | `—` | Reproducibility (re-running the analysis from published rows). | `sections/10-reproducibility.tex` | — | condensed | main §9 + supp Table S1 | — | Med | REF | Commands gone. |
| P2-88 | App A | glossary (23 terms) | `—` | A/A ... Wave. | `sections/appendix-a-glossary.tex` | — | condensed | supp A8 | — | High | REF | Anchor, arm, confirmatory/exploratory, nonce, prediction interval, shipped, sticky, tools-normalized cost, wave gone. |
| P2-89 | App B | table (T36) | `tab:modelcheck` | Savings-model check: PI coverage and observed vs predicted. | `generated/tables/model-check.tex` | EV-paired | **MISSING** | — | yes | High | M |  |
| P2-90 | App B | table (T37) | `tab:aa` | A/A noise floor: second plain-host session vs first. | `generated/tables/aa.tex` | EV-paired | **MISSING** | — | yes | High | M |  |
| P2-91 | App B | table (T38) | `tab:interim` | Interim and final cost ratios. | `generated/tables/interim.tex` | EV-paired | **MISSING** | — | yes | Med | 2 |  |
| P2-92 | App B | table (T39) | `tab:slicegap` | Cost ratio by pause pattern. | `generated/tables/slice-gap.tex` | EV-paired | **MISSING** | — | yes | Med | 3 |  |
| P2-93 | App B | table (T40) | `tab:sliceturns` | Cost ratio by scripted session length. | `generated/tables/slice-turns.tex` | EV-paired | **MISSING** | — | yes | Med | 3 | Numbers behind F26. |
| P2-94 | App B | table (T41, xltabular) | `tab:per1000full` | Savings per 1,000 sessions by host, task type and arm, measured and predicted. | `generated/tables/per1000-full.tex` | EV-paired | **MISSING** | — | yes | Med | 2 |  |
| P2-95 | App B | table (T42, xltabular) | `tab:scenarios` | The 70 scenarios: family, task type, language, turns, long gaps, split. | `generated/tables/scenarios.tex` | evals/paired/scenarios/main-v1 | **MISSING** | — | yes | Med | M |  |
| P2-96 | App B | analysis (text) | `—` | Raw cost basis. | `sections/appendix-b-tables.tex` | — | **MISSING** | — | — | Low | M |  |
| P2-97 | App B | enumerated list | `—` | Deviations from the preregistration. | `generated/tables/deviations.tex` | EV-paired prereg | **MISSING** | — | yes | High | M | Only S1 deviations survive (A4 process note). |
| P2-98 | App C | analysis (text) | `—` | Response to review, rounds 1-2 and re-review. | `sections/appendix-c-review.tex` | — | condensed | supp A7 (one sentence for rounds 1-2) | — | Med | REF | Point-by-point responses gone. |
| P2-99 | App C | table (T43, xltabular) | `tab:changes` | All 20 first-pass claims (judge benchmark). | `generated/jb/tables/changes.tex` | EV-jb | **MISSING** | — | yes | Low | REF | [dup of JB-17] |

## v3 (32 pp): `docs/papers/2026-10-06-decision-models-v3/`

| ID | § | Type | Label | Caption / first sentence | Source files | Data read | v4 status | v4 location | In v4 tree? | Prio | Takeaway | Notes / duplicate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V3-01 | * | key idea | `—` | The one-sentence answer: a fast decision model is worth what its decisions change... | `sections/00b-short.tex` | — | condensed | main abstract | — | Low | REF | 'Short version' page gone. |
| V3-02 | 1 | key idea | `—` | A decision model is only worth what its decisions change. | `sections/01-intro.tex` | — | condensed | main §9 last paragraph | — | Low | REF |  |
| V3-03 | 1 | figure (F1) | `fig:timeline` | Each stage answered the question the previous one left open (study timeline). | `figures/fig-timeline.tex` | none (schematic) | **MISSING** | — | yes | High | REF | File still in v4 figures/, unused. |
| V3-04 | 1 | table (T1) | `tab:findings` | Findings at a glance. | `generated/tables/findings.tex` | build_assets (findings rows) | condensed | main §1 five takeaways + §9 ranked list | yes | High | REF | Per-finding value/source/evidence-label columns gone. |
| V3-05 | 1 | analysis (text) | `—` | Related work (RouteLLM, FrugalGPT) and how to read evidence labels. | `sections/01-intro.tex` | — | present | main §1 + references | — |  | REF |  |
| V3-06 | 2 | figure (F2) | `fig:obslatency` | A decision call is two orders of magnitude faster than a host model call. | `figures/fig-obs-latency.tex` | data/obs-latency.dat <- EV-v3offline/a1-observatory | present | main Fig 4 fig:latency | — |  | 5 | Caption now '~30x at the median'. |
| V3-07 | 2 | figure (F3) | `fig:obsmix` | Most recorded events are bookkeeping; decision-bearing events are a thin slice. | `figures/fig-obs-mix.tex` | data/obs-mix.dat <- a1-observatory/health_mix.csv | present | supp Fig S12 | — |  | 5 |  |
| V3-08 | 2 | key idea | `—` | Telemetry told us decisions are cheap and fast, and that savings claims were estimates. | `sections/02-observatory.tex` | — | present | main §7 claim/For practitioners | — |  | 5 |  |
| V3-09 | 2 | analysis (text) | `—` | The 7.1% that was not what it seemed; claimed savings were estimates. | `sections/02-observatory.tex` | EV-v3offline/a1-observatory | present | supp A5 | — |  | 5 |  |
| V3-10 | 3 | figure (F4) | `fig:accuracy` | No accuracy difference between the top judges was detected after the preregistered correction. | `figures/fig-ph-accuracy.tex` | data/ph-acc-*.dat | present | supp Fig S1 | — |  | 1 | [dup of P2-05] |
| V3-11 | 3 | figure (F5) | `fig:costacc` | Jev is the cheapest judge near the top of the measured accuracy range. | `figures/fig-ph-costacc.tex` | data/ph-cost-*.dat | condensed | main Fig 1 fig:frontier | yes | Low | 1 | CIs dropped. [dup of P2-08] |
| V3-12 | 3 | figure (F6) | `fig:reads` | On real read decisions, no judge reached the usefulness zone. | `figures/fig-ph-reads.tex` | data/ph-reads-*.dat | present | supp Fig S2 | — |  | 1 | [dup of P2-18] |
| V3-13 | 3.1 | figure (F7) | `fig:openai` | The Decisions API was at or above Jev on every split (post hoc). | `figures/fig-openai.tex (via generated/openai-section.tex)` | data/openai-acc.dat <- EV-openai/summary.json | present | supp Fig S3 | — |  | 1 |  |
| V3-14 | 3.1 | table (T2) | `tab:openai` | OpenAI Decisions API (post hoc) vs in-run Jev. | `generated/tables/openai-decisions.tex` | EV-openai | present | supp Table S2 | — |  | 1 |  |
| V3-15 | 3.1 | key idea | `—` | A native typed-decision endpoint matched or exceeded Jev's accuracy... | `generated/openai-section.tex` | — | present | supp A2.1 | — |  | 1 | Price wording corrected in v4. |
| V3-16 | 3 | key idea | `—` | Jev is the best value among the decision models we tested. | `sections/03-judges.tex` | — | present | main §3 For practitioners | — |  | 1 |  |
| V3-17 | 4 | figure (F8) | `fig:forest` | On main-v1 test split, every Fable routing arm saved money and every Opus arm cost more. | `figures/fig-forest.tex` | data/forest*.dat | present | supp Fig S4 | — |  | 2 | [dup of P2-52] |
| V3-18 | 4 | analysis (text) | `—` | Why caching made this necessary; what it found; the effort confound. | `sections/04-paired.tex` | EV-paired | condensed | main §4, supp A3/A7 | — | Low | 2 | Effort-confound narrative reduced to one paragraph. |
| V3-19 | 4 | key idea | `—` | Measured, not estimated: on Fable, deciding once to run on Sonnet saved about half. | `sections/04-paired.tex` | — | present | main §4 claim | — |  | 2 |  |
| V3-20 | 5 | analysis (text) | `—` | A counterfactual on existing sessions (A0 decide-once pricing). | `sections/05-plateau.tex` | EV-v3offline/a0-counterfactual/summary.json | present | supp A3 | — |  | 3 |  |
| V3-21 | 5 | figure (F9) | `fig:a0` | On Fable the rule R* is at least as cheap as Jev; on Opus every routing policy costs more. | `figures/fig-a0.tex` | data/a0-policies.dat | present | supp Fig S5 | — |  | 3 |  |
| V3-22 | 5 | table (T3) | `tab:a0` | Decide-once policies on main-v1 (exploratory). | `generated/tables/a0-policies.tex` | EV-v3offline/a0-counterfactual | present | supp Table S3 | — |  | 3 |  |
| V3-23 | 5 | analysis (text) | `—` | An artefact to avoid: effort switches rewrite the prompt cache. | `sections/05-plateau.tex` | EV-paired requests | present | main §5 + Fig 3 (expanded) | — |  | 3 |  |
| V3-24 | 5 | analysis (text) | `—` | How the S1 panel was prepared (smoke test, repairs). | `sections/05-plateau.tex` | EV-holdout-v3 | present | supp A4, main §2 | — |  | S |  |
| V3-25 | 5 | worked example (casecard) | `—` | S1 methods in brief (quality, cost, composed policies). | `sections/05-plateau.tex` | — | present | supp A4 | — |  | S |  |
| V3-26 | 5 | table (T4) | `tab:s1hyp` | S1 (holdout-v3) preregistered hypotheses. | `generated/s1-section.tex + tables/s1-hypotheses.tex` | EV-holdout-v3 (2026-10-06-holdout-v3) | present | supp Table S4 | — |  | S |  |
| V3-27 | 5 | analysis (text) | `—` | H1-H7 in plain words; what the freeze rule chose. | `sections/05-plateau.tex` | EV-holdout-v3 | present | supp A4 | — |  | S |  |
| V3-28 | 5 | key idea | `—` | The start-of-session choice was matched by a one-line rule. | `sections/05-plateau.tex` | — | present | supp A4, main §5 | — |  | 3 |  |
| V3-29 | 5 | process note | `—` | Process note: how the S1 run went (spend, gate failures, outage, budget). | `sections/05-plateau.tex` | EV-holdout-v3 | present | supp A4 | — |  | S |  |
| V3-30 | 6.1 | figure (F10) | `fig:s1forest` | Two hypotheses carry money (H1, H5); the rest are guards. | `figures/fig-s1-forest.tex` | data/s1-forest.dat | present | supp Fig S6 | — |  | S |  |
| V3-31 | 6.1 | key idea | `—` | Two of the eight rows carry money. | `sections/05b-s1-detail.tex` | — | present | supp A4.1 | — |  | S |  |
| V3-32 | 6.2 | worked example (casecard) | `—` | Worked example: one scenario, one paired cost ratio. | `sections/05b-s1-detail.tex` | numbers.tex Wx* <- EV-holdout-v3 | present | supp A4.2 | — |  | S | Scenario name anonymized. |
| V3-33 | 6.3 | figure (F11) | `fig:perscen` | The direction is consistent across scenarios; the size varies widely. | `figures/fig-perscen.tex` | data/perscen-{fable,opus}.dat | present | supp Fig S7 | — |  | S |  |
| V3-34 | 6.4 | figure (F12) | `fig:subgroups` | Every subgroup saves money; quality risk concentrates in explain and mixed work. | `figures/fig-subgroups.tex` | data/s1-subgroups.dat | present | supp Fig S8 | — |  | S | Caption softened. |
| V3-35 | 6.5 | figure (F13) | `fig:fz` | On Fable many configurations qualify; on Opus none does. | `figures/fig-fz.tex (preamble) + generated/fz-*-plots.tex` | data/fz-{fable,opus}-{cand,chosen,non,prereg}.dat; labels/fz-*.tex | present | supp Fig S9 | — |  | S |  |
| V3-36 | 6.6 | table (T5) | `tab:discordant` | The 4 S1 scenario-reps where Jev and rule R* chose different session models. | `generated/tables/discordant.tex` | EV-holdout-v3 | present | supp Table S5 | — |  | 3 |  |
| V3-37 | 6.6 | worked example (casecard) | `—` | Why the two deciders differ only where they disagree. | `sections/05b-s1-detail.tex` | — | present | supp A4.6 | — |  | 3 |  |
| V3-38 | 6.7 | figure (F14) | `fig:effort` | Medium effort saved money on Sonnet and Fable but not on Opus. | `figures/fig-effort-hosts.tex` | data/effort-hosts.dat | present | supp Fig S10 | — |  | 3 |  |
| V3-39 | 6.8 | figure (F15) | `fig:composition` | Plain Fable spends most of its money writing to the cache (S1). | `figures/fig-composition.tex + generated/composition-totals.tex` | data/s1-composition.dat | present | supp Fig S11 | — |  | 2 |  |
| V3-40 | 6.9 | figure (F16) | `fig:cumulative` | Four independent sets of scenarios give the same answer for each host. | `figures/fig-cumulative.tex` | data/cumulative.dat | present | main Fig 2 fig:replication (promoted) | — |  | 2 |  |
| V3-41 | 6 | analysis (text) | `—` | What this taught us, and what it left open (S1). | `sections/05b-s1-detail.tex` | — | condensed | main §9 | — | Low | S |  |
| V3-42 | 7 | key idea | `—` | What gets the most out of a decision model: decide once; price gate; rule; effort; keep review/explain on host. | `sections/06-recommendation.tex` | — | condensed | main §8/§9 | — | Low | 3 |  |
| V3-43 | 7 | table (T6) | `tab:config` | Recommended settings per host model, after S1. | `sections/06-recommendation.tex (inline)` | numbers.tex | present | main Table 3 tab:recs | — |  | REF |  |
| V3-44 | 7 | analysis (text) | `—` | What a user should set, incl. keyword-proxy replay (R* alone / true-label keep_on_host / shipped proxy; classifier precision and recall). | `sections/06-recommendation.tex` | EV-defaults-replay/replay.json; EV-holdout-v3 | condensed | main Table 3 footnote (0.75x vs 0.58x) | — | Med | 2 | Oracle variant, CIs, turn-pass, precision/recall gone. |
| V3-45 | 7 | analysis (text) | `—` | Per harness: Amplifier install/update instructions. | `sections/06-recommendation.tex` | — | condensed | supp A6 (Claude Code/Codex/Copilot only) | — | Low | REF | Amplifier bundle add/update lines gone. |
| V3-46 | 8 | code listings (4) + text | `—` | Configuration recipes (shipped default, accept review/explain risk, Sonnet medium, use decision model, smart tool). | `sections/06b-recipes.tex + generated/recipe-shipped.yaml` | — | present | supp A6 | — |  | REF |  |
| V3-47 | 9 | key idea + text | `—` | The takeaway; what remains open; honest limits; where a decision model might still matter. | `sections/07-limits.tex` | — | condensed | main §9 | — | Low | REF |  |
| V3-48 | App A | analysis (text) | `—` | Companion material: companion report pointer, evidence used, reproducing. | `sections/appendix-a-companion.tex` | — | present | supp A1 Table S1 | — |  | REF | Pointer to v2 companion dropped (v2 not cited). |
| V3-49 | App B | table (T7, xltabular) | `tab:fzkey` | Every configuration the S1 freeze rule considered. | `generated/tables/fz-key-long.tex` | EV-holdout-v3 | present | supp Table S6 | — |  | S |  |
| V3-50 | App C | glossary (17 terms) | `—` | A/A pair ... Turn-pass fraction. | `sections/appendix-b-glossary.tex` | — | present | supp A8 (identical) | — |  | REF |  |
| V3-51 | App D | analysis (text) | `—` | Response to the independent review (round 3). | `sections/appendix-c-review3.tex` | — | present | supp A7 | — |  | REF |  |

## Items in v4 that did not exist before

| ID | Where | Type | Label | Caption / content | Source | Data | Kind | Notes |
|---|---|---|---|---|---|---|---|---|
| N-01 | main §2 | table (T1) | `tab:data` | Data sources, what each shows, and its main weakness. | `sections/m2-setting.tex (inline)` | numbers.tex | new | Replaces scattered method sections. |
| N-02 | main §2 | analysis (text) | `—` | What makes this evidence strong / common limits stated once. | `sections/m2-setting.tex` | — | new |  |
| N-03 | main §3 | figure (F1) | `fig:frontier` | Jev is the low-cost point on the accuracy-cost frontier. | `figures/fig-v4-frontier.tex; labels/v4-frontier.tex` | data/v4-frontier-{pre,post}.dat | new (redraw) | Redraw of fig-ph-costacc + Decisions API point (Luna-D); no CIs. |
| N-04 | main §4 | table (T2) | `tab:perrequest` | Sonnet is half Fable's price per request but Opus's equal (per-request cost, composition, predicted routing ratio). | `generated/tables/v4-perrequest.tex` | EV-paired requests (RqMix*, RpMult*) | new | New per-request price model. |
| N-05 | main §5 | figure (F3) | `fig:cachewrites` | A switch rewrites the cache unless the cache has already expired. | `figures/fig-v4-cachewrites.tex` | data/v4-cachewrites.dat | new | New re-analysis: effort change vs plain, within turn / short / 7-min pause. |
| N-06 | main §5 | analysis (text) | `—` | Decide once vs re-decide every turn: 0.87x Fable, 0.91x Opus (preregistered criterion <=1.05). | `sections/m5-once.tex` | EV-paired (forest-h3) | reframed | Was v2 forest bottom panel / H3. |
| N-07 | main §3-§7 | key idea x5 | `—` | 'For practitioners' boxes, one per takeaway. | `sections/m3..m7` | — | new |  |
| N-08 | main §7 / supp A5 | analysis (text) | `—` | Production vs test routing rates (scope gate 49%, Jev routed 34% vs 89%/97%), effort switches 12/12,094; corrected spend-mix projection 0.83x -> 0.92x. | `sections/m7-telemetry.tex, supp/s5-telemetry.tex` | EV-v3offline | new |  |
| N-09 | main §4 | analysis (text) | `—` | Plain Sonnet vs plain Fable/Opus model-only contrast (CfFableSonnetArm). | `sections/m4-routing.tex` | EV-paired | new (promoted) |  |
| N-10 | supp A1 | table (S1) | `tab:evidence` | Evidence packages used in this report, by package ID. | `supp/s1-evidence.tex (inline)` | — | new | Replaces v3 App A. |
| N-11 | main §10 | bibliography | `—` | References (RouteLLM, FrugalGPT). | `sections/m10-references.tex` | — | new |  |
| N-12 | supp A2 | analysis (text) | `—` | Risky actions: the side-effect interventions (I1/I2 holdout summary). | `supp/s2-judges.tex` | EV-jb | new (condensed from JB §7) |  |

## Prioritized restore list (MISSING and condensed only, duplicates collapsed)

Ordering: High, then Med, then Low; MISSING before condensed within each level. Each row is the version to restore. When an item exists in two reports, the newest extended version is listed, and the other IDs appear in "also in".


### Takeaway 1: choosing the judge (Jev is best price-quality)

- **[High] JB-29: figure (F5) `fig:sweep`**: Threshold sweep (coverage and wrong-automatic rate vs certainty cutoff). *MISSING*. Gate-cutoff sensitivity analysis. Assets in v4 tree: yes.
- **[High] JB-30: table (T11) `tab:threshold`**: Automatic / wrong automatic decisions at selected cutoffs, holdout. *MISSING*. Assets in v4 tree: yes.
- **[High] JB-39: figure (F7) `fig:anatomy`**: Where the time goes in one call (medians of each component). *MISSING*. Assets in v4 tree: yes. Also in: P2-09.
- **[High] P2-06: figure (F2) `fig:jbwacov`**: Wrong-automatic rate against coverage on the holdout, with the post hoc Clef arms. *MISSING*. Only safety-vs-usefulness view of the judges. Assets in v4 tree: no (copy from source report). Also in: JB-27.
- **[High] P2-07: figure (F3) `fig:jbacclat`**: Accuracy against p95 latency (log scale) on the holdout, with the post hoc Clef arms. *MISSING*. Assets in v4 tree: no (copy from source report). Also in: JB-28.
- **[High] JB-22: table (T8) `tab:headline-hold`**: Holdout [preregistered], 63 cases, 3 repetitions, policy bundle-read-shortcut. *condensed* (v4 has: supp Fig S1 + main §3 prose). Lost: Accuracy/cost/p95 quoted for 3 judges; wrong-auto, coverage, ECE, p50 columns for all 10 arms lost. Assets in v4 tree: yes. Also in: P2-04.
- **[High] P2-08: figure (F4) `fig:jbcost`**: Cost per million decisions (log) against holdout accuracy, for priced judges. *condensed* (v4 has: main Fig 1 fig:frontier (redrawn)). Lost: Wilson error bars dropped; Decisions API point added. fig-ph-costacc.tex still in v4 tree, unused. Assets in v4 tree: yes. Also in: V3-11.
- **[High] P2-12: table (T3) `tab:clefresults`**: Post hoc run: Clef, Clef-Flash and in-run Jev on all four splits. *condensed* (v4 has: supp Fig S1/S2, main Fig 1, §3 prose). Lost: Four-split table with latency and cost gone. Assets in v4 tree: yes.
- **[Med] JB-18: table (T6) `tab:headline-dev`**: Dev split [screen], 90 cases, 3 repetitions, policy bundle-read-shortcut. *MISSING*. Dev split only appears for the Decisions API table. Assets in v4 tree: yes.
- **[Med] JB-19: figure (F1) `fig:wacov-dev`**: Wrong automatic rate against coverage on the dev split [screen]. *MISSING*. Safety-usefulness trade-off plot. Assets in v4 tree: yes.
- **[Med] JB-20: table (T7) `tab:rule1-dev`**: Rule 1 on the dev split [screen]: each candidate minus Jev. *MISSING*. Assets in v4 tree: yes.
- **[Med] JB-26: table (T10) `tab:pairwise`**: The 13 contrasts declared in the run configuration, both splits, accuracy and wrong-automatic rate. *MISSING*. Assets in v4 tree: yes.
- **[Med] JB-32: table (T12) `tab:fail-all`**: Holdout: all wrong answers by class (mean per repetition). *MISSING*. Assets in v4 tree: yes.
- **[Med] JB-40: table (T15) `tab:anatomy`**: The numbers behind the latency anatomy figure. *MISSING*. Assets in v4 tree: yes.
- **[Med] JB-41: table (T16) `tab:concurrency`**: Latency and throughput as requests in flight rise. *MISSING*. Concurrency study. Assets in v4 tree: yes.
- **[Med] JB-42: caveat `—`**: Local latency is a property of this host at that time, not of the model. *MISSING*. Assets in v4 tree: —.
- **[Med] JB-43: table (T17) `tab:cost`**: Projected monthly API cost and wrong automatic actions at 100,000 decisions per day. *MISSING*. Cost-at-scale projection. Assets in v4 tree: yes.
- **[Med] JB-44: caveat `—`**: The wrong-action column assumes real traffic has the benchmark's decision mix. *MISSING*. Assets in v4 tree: —.
- **[Med] JB-47: analysis (text) `—`**: Cloud fallback when Jev is unreachable: GPT-6 Luna, behind the guard. *MISSING*. No fallback-judge recommendation in v4. Assets in v4 tree: —.
- **[Med] JB-55: analysis (text) `—`**: Why accuracy misleads here (always-fallback scores highest); cost of a wrong read; scoring against the host's next read. *MISSING*. Assets in v4 tree: —.
- **[Med] JB-56: caveat `—`**: Read this before generalizing (scope and selection of the trace cases). *MISSING*. Assets in v4 tree: —. Also in: P2-19.
- **[Med] P2-13: table (T4) `tab:clefcontrasts`**: Post hoc paired contrasts (McNemar exact on per-case majority). *MISSING*. Assets in v4 tree: yes.
- **[Med] JB-07: table (T2) `tab:labelaudit`**: Blind label audit. *condensed* (v4 has: supp A2 prose (kappa only)). Lost: Per-split agreement table gone; only kappa quoted. Assets in v4 tree: yes. Also in: P2-03.
- **[Med] JB-09: caveat `—`**: The holdout author and both reviewers are Anthropic models (Claude Opus and Claude Sonnet). *condensed* (v4 has: main §2, supp A2 ('labels written by language models')). Lost: Same-vendor caveat (labeller = model family under test) lost. Assets in v4 tree: —.
- **[Med] JB-10: table (T3) `tab:arms`**: The 10 base judges. *condensed* (v4 has: main §2 'Models and prices' (names only)). Lost: Backend, size, probability source per judge lost. Assets in v4 tree: yes.
- **[Med] JB-24: table (T9) `tab:rule1-hold`**: Rule 1 on the holdout: each candidate minus Jev, paired-bootstrap CIs, Holm-adjusted McNemar p. *condensed* (v4 has: main §3 prose (Luna/Sol diffs, CIs, Holm p)). Lost: Local-judge rows and wrong-auto contrasts lost. Assets in v4 tree: yes.
- **[Med] JB-48: table (T18) `tab:rule2`**: Rule 2, the offline tier: local judges under the strictest policy. *condensed* (v4 has: main §3 (one sentence: no local model met the safety bar)). Assets in v4 tree: yes.
- **[Med] P2-17: table (T7) `tab:clefrule2`**: Rule 2 ('useful' read shortcut) on both trace splits for the post hoc run. *condensed* (v4 has: supp Fig S2 (Clef points)). Lost: Trace-dev split gone. Assets in v4 tree: yes.
- **[Low] JB-08: description list `—`**: Adjudication notes per flagged case (cua-18: label defensible, task under-specified...). *MISSING*. Assets in v4 tree: yes.
- **[Low] JB-31: description list `—`**: Failure-mode classes (acted on side effect, under-deferred, accepted wrong code, injection...). *MISSING*. Assets in v4 tree: —.
- **[Low] JB-51: key idea `—`**: Two new questions, two new kinds of evidence. *MISSING*. Framing box. Assets in v4 tree: —.
- **[Low] JB-01: key idea `—`**: Accuracy alone is the wrong headline for a judge. *condensed* (v4 has: main §2 Measures (prose)). Lost: Box gone; accuracy/wrong-automatic/coverage defined in one sentence each. Assets in v4 tree: —.
- **[Low] JB-02: key idea `—`**: A judge's mistakes come in two kinds: safe mistakes (fall back) and unsafe mistakes (acted on). *condensed* (v4 has: main §2 (gate + fallback prose)). Lost: Safe/unsafe framing gone. Assets in v4 tree: —.
- **[Low] JB-11: description list `—`**: Scoring policies: bundle-read-shortcut (primary), alternatives. *condensed* (v4 has: main §2 gate definition). Lost: Alternative policies gone. Assets in v4 tree: —.
- **[Low] JB-14: analysis (text) `—`**: The preregistered decision rules (Rule 1: replace Jev; Rule 2: offline tier). *condensed* (v4 has: main §3 (one sentence on replacement rule)). Lost: Rule 2 definition gone. Assets in v4 tree: —.
- **[Low] JB-49: analysis (text) `—`**: What is within noise; what the follow-ups add; what would change these recommendations. *condensed* (v4 has: main §3, §9). Lost: 'What would change the recommendation' list gone. Assets in v4 tree: —.
- **[Low] JB-52: key idea + text `—`**: 'What the host did next' is not the same as 'what was enough'; how trace cases were rebuilt, labelled, replayed, preregistered. *condensed* (v4 has: main §2 Data; supp A2 (kappa vs host)). Lost: Fingerprinting/replay method gone. Assets in v4 tree: —.
- **[Low] JB-53: table (T19) `tab:trace`**: Real read-shortcut decisions, holdout: 42 cases, 3 repetitions. *condensed* (v4 has: supp Fig S2 + main §3 prose). Lost: Per-judge counts table gone. Assets in v4 tree: yes. Also in: P2-16.
- **[Low] P2-02: key idea `—`**: A judge is useful when it is right when it acts and acts often enough to matter. *condensed* (v4 has: main §2 Measures). Assets in v4 tree: —.
- **[Low] P2-14: table (T5) `tab:clefrule1`**: Preregistered default-judge rule applied descriptively to the post hoc arms. *condensed* (v4 has: main §3 ('no challenger met the rule')). Assets in v4 tree: yes.
- **[Low] P2-15: key idea `—`**: Clef matches Jev's accuracy but costs several times more and answers ~3x slower. *condensed* (v4 has: main §3 prose). Assets in v4 tree: —.

### Takeaway 2: routing economics (route only when the host is much dearer)

- **[High] P2-53: table (T23) `tab:hyp`**: The preregistered hypotheses, test split, pair reading. *MISSING*. Main-campaign verdict table; only H3 (0.87/0.91) quoted in main §5. Assets in v4 tree: yes.
- **[High] P2-54: table (T24) `tab:quality`**: Quality: mean turn-pass difference, arm minus plain host, test split. *MISSING*. Main-campaign quality result absent. Assets in v4 tree: yes.
- **[High] P2-58: table (T25) `tab:composition`**: The numbers behind the composition figure: $/session by token class, requests, cache reads. *MISSING*. Assets in v4 tree: yes.
- **[High] P2-59: figure (F17) `fig:savings`**: Dollars saved per 1,000 sessions by task type and arm, 90% ranges. *MISSING*. S1 subgroup fig is a partial analogue. Assets in v4 tree: no (copy from source report).
- **[High] P2-60: table (T26) `tab:per1000`**: Measured saving per 1,000 sessions by task type, host and arm. *MISSING*. Assets in v4 tree: yes.
- **[High] P2-75: table (T32) `tab:taskfable`**: Fable sticky by task type with 95% CIs on saving per 1,000 sessions. *MISSING*. Origin of keep_on_host review/explain. Assets in v4 tree: yes.
- **[High] P2-27: table (T10) `tab:prices`**: Price per million tokens (USD), by model and token class. *condensed* (v4 has: main §2 prose). Assets in v4 tree: —. Also in: JB-58.
- **[High] P2-28: table (T11) `tab:breakeven`**: Opus-host cost ratios if Opus cache reads cost more than list (price sensitivity sweep). *condensed* (v4 has: main §4 (one break-even number)). Lost: Sweep over read prices, both readings, gone. Assets in v4 tree: yes.
- **[High] P2-57: figure (F16) `fig:composition`**: Mean cost per session split by what was paid for (main campaign, incl. rebuild). *condensed* (v4 has: supp Fig S11 is the S1 analogue (s1-composition.dat)). Lost: Main-campaign arms and 'rebuild' class gone. Same filename, different data in v3/v4. Assets in v4 tree: no (copy from source report).
- **[Med] P2-62: table (T28) `tab:passrates`**: Final hidden-test pass rate by arm vs plain host (McNemar). *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-70: figure (F23) `fig:scenario`**: Scenario by scenario: plain Fable cost vs sticky saving. *MISSING*. S1 per-scenario Fig S7 is a partial analogue. Assets in v4 tree: no (copy from source report).
- **[Med] P2-72: table (T29) `tab:qualityfamily`**: Mean turn-pass difference by scenario family. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-73: table (T30) `tab:jointfamily`**: Savings and quality together, by family. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-74: table (T31) `tab:jointtask`**: Savings and quality together, by task type. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-91: table (T38) `tab:interim`**: Interim and final cost ratios. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-94: table (T41, xltabular) `tab:per1000full`**: Savings per 1,000 sessions by host, task type and arm, measured and predicted. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-46: figure (F12) `fig:pilot`**: Second screening pilot (40 pairs, 5 scenarios) against the full campaign. *condensed* (v4 has: main Fig 2 (pilot rows, sticky only)). Lost: Per-arm pilot-vs-final comparison gone. Assets in v4 tree: no (copy from source report).
- **[Med] P2-51: table (T22) `tab:primary`**: Primary endpoint: geometric-mean cost ratio, arm over plain host, test split. *condensed* (v4 has: supp Fig S4 (same ratios as dots)). Lost: n, both readings in tabular form gone. Assets in v4 tree: yes.
- **[Med] P2-64: figure (F18) `fig:interim`**: Cost ratio of each routed arm as evidence accumulated: pilot, interim, final train/test. *condensed* (v4 has: main Fig 2 replication (pilot/train/test/S1, sticky only)). Lost: Interim-dashboard stage, shipped/sonnet arms gone. Assets in v4 tree: no (copy from source report).
- **[Med] P2-76: figure (F25) `fig:requests`**: Main-loop requests per session by kind of session (box plot). *condensed* (v4 has: main Table 2 (request multiplier 1.11/1.38 only)). Lost: Distribution gone. Assets in v4 tree: no (copy from source report).
- **[Med] V3-44: analysis (text) `—`**: What a user should set, incl. keyword-proxy replay (R* alone / true-label keep_on_host / shipped proxy; classifier precision and recall). *condensed* (v4 has: main Table 3 footnote (0.75x vs 0.58x)). Lost: Oracle variant, CIs, turn-pass, precision/recall gone. Assets in v4 tree: —.
- **[Low] JB-61: analysis (text) `—`**: Caching survey: price vs volume (about half each), rebuild cost, warm first requests, proposed experiment. *MISSING*. Assets in v4 tree: —. Also in: P2-26.
- **[Low] JB-57: key idea `—`**: Three prices matter (input, cache read, cache write). *condensed* (v4 has: main §4 claim). Assets in v4 tree: —.
- **[Low] P2-01: key idea `—`**: What we found (test split; hypotheses preregistered, estimator after the data). *condensed* (v4 has: main abstract, §9). Assets in v4 tree: —.
- **[Low] P2-56: analysis (text) `—`**: Decision (what the confirmatory results decide). *condensed* (v4 has: main §4). Assets in v4 tree: —.
- **[Low] P2-85: analysis (text) `—`**: How much of the saving is the router vs effort; quality by task type; caching guidance; how to use the numbers; what to measure next. *condensed* (v4 has: main §4 (plain Sonnet vs plain Fable), §5, §9). Assets in v4 tree: —.
- **[Low] V3-18: analysis (text) `—`**: Why caching made this necessary; what it found; the effort confound. *condensed* (v4 has: main §4, supp A3/A7). Lost: Effort-confound narrative reduced to one paragraph. Assets in v4 tree: —.

### Takeaway 3: configure once, caching, effort

- **[High] P2-23: figure (F8) `fig:survey`**: Earlier caching survey: same configuration in single-turn and 4-turn sessions, 95% bootstrap. *MISSING*. Assets in v4 tree: no (copy from source report). Also in: JB-59.
- **[High] P2-29: figure (F9) `fig:cache`**: How the prompt cache behaves over a conversation (schematic). *MISSING*. Conceptual figure that explains takeaway 3. Assets in v4 tree: no (copy from source report).
- **[High] P2-30: table (T12) `tab:probe`**: The cache-semantics probe. *MISSING*. Assets in v4 tree: yes.
- **[High] P2-31: figure (F10) `fig:probe`**: The probe requests drawn: tokens written and read by each. *MISSING*. Assets in v4 tree: no (copy from source report).
- **[High] P2-36: table (T14) `tab:effortmix`**: Main-loop requests by host, arm, model and reasoning effort. *MISSING*. Evidence for the effort confound. Assets in v4 tree: yes.
- **[High] P2-78: table (T33) `tab:effort`**: Sticky sessions that chose Sonnet vs plain-Sonnet control (effort confound). *MISSING*. Assets in v4 tree: —.
- **[High] P2-68: figure (F21) `fig:gapwrites`**: Cache-write tokens on first request of a turn, after short vs long pause, per arm and host. *condensed* (v4 has: main Fig 3 fig:cachewrites (new re-analysis)). Lost: Per-arm/per-host breakdown gone; v4 contrasts plain vs effort-change. Assets in v4 tree: no (copy from source report).
- **[High] P2-80: table (T34) `tab:effortfollow`**: Effort-control follow-up (plain Sonnet medium vs default). *condensed* (v4 has: supp Fig S10 row + A3 prose). Lost: Cross-study 0.958 row, turn-pass row, provenance caveat gone. Assets in v4 tree: yes.
- **[High] P2-82: table (T35) `tab:effortfable`**: Fable effort follow-up (plain Fable medium vs default). *condensed* (v4 has: supp Fig S10 row). Assets in v4 tree: yes.
- **[Med] JB-62: caveat `—`**: What the caching study did not show (longer and real chats...). *MISSING*. Assets in v4 tree: —.
- **[Med] P2-25: caveat `—`**: Why a new experiment was needed (<=4 turns, few synthetic scenarios, caches never expired). *MISSING*. Assets in v4 tree: —.
- **[Med] P2-66: figure (F19) `fig:perturn`**: Mean cost of each turn by turn index, per arm and host. *MISSING*. Assets in v4 tree: no (copy from source report).
- **[Med] P2-67: figure (F20) `fig:turncomp`**: What each turn of a plain-host session paid for, by turn index. *MISSING*. Assets in v4 tree: no (copy from source report).
- **[Med] P2-69: figure (F22) `fig:switch`**: Shipped arm: number of model switches leading into each turn. *MISSING*. Assets in v4 tree: no (copy from source report).
- **[Med] P2-77: figure (F26) `fig:band`**: Cost ratio by scripted session length. *MISSING*. Assets in v4 tree: no (copy from source report).
- **[Med] P2-92: table (T39) `tab:slicegap`**: Cost ratio by pause pattern. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-93: table (T40) `tab:sliceturns`**: Cost ratio by scripted session length. *MISSING*. Numbers behind F26. Assets in v4 tree: yes.
- **[Med] P2-32: key idea `—`**: Six facts from the probe shaped the experiment. *condensed* (v4 has: main §5 (switch invalidates prefix; 5-min lifetime)). Assets in v4 tree: —.
- **[Med] P2-79: analysis (text) `—`**: The effort confound: what medium-effort sessions did differently; two corrections. *condensed* (v4 has: supp A3 effort follow-ups, A7 review). Assets in v4 tree: —.
- **[Low] JB-60: table (T22) `tab:rebuild`**: Rebuild cost after model switches, by stratum. *MISSING*. Assets in v4 tree: —. Also in: P2-24.
- **[Low] P2-81: key idea `—`**: The effort setting alone explains most of the sticky-vs-plain-Sonnet gap. *condensed* (v4 has: supp A3). Assets in v4 tree: —.
- **[Low] V3-42: key idea `—`**: What gets the most out of a decision model: decide once; price gate; rule; effort; keep review/explain on host. *condensed* (v4 has: main §8/§9). Assets in v4 tree: —.

### Takeaway 4: risky actions (deterministic guard)

- **[High] JB-04: table (T1) `tab:cua18`**: Every base judge's answer to cua-18 under the bundle's gate. *MISSING*. Per-judge x rep outcome grid for the purchase case. Assets in v4 tree: yes.
- **[High] JB-33: table (T13) `tab:fail-auto`**: Holdout: only the wrong answers the bundle would have acted on. *MISSING*. Assets in v4 tree: yes.
- **[High] JB-36: table (T14) `tab:interventions`**: Interventions on both splits. *condensed* (v4 has: main §6 + supp A2 prose (holdout totals)). Lost: Per-judge, per-split, coverage-cost rows gone. Assets in v4 tree: yes.
- **[High] JB-37: figure (F6) `fig:i2`**: The host guard (I2) on the holdout: side-effect wrong automatic decisions per judge, without and with the guard. *condensed* (v4 has: main §6 prose ('38 to 0')). Lost: Per-judge bars gone. Assets in v4 tree: yes. Also in: P2-10.
- **[Med] JB-03: worked example (casecard) `sec:worked`**: The question the judge sees: Task 'Purchase the subscription'... *condensed* (v4 has: main §6 (one sentence: every judge clicked 'buy')). Lost: Step-by-step Jev walkthrough (ms, probabilities, gate checks) gone. Assets in v4 tree: —.
- **[Med] JB-21: analysis (text) `—`**: Interventions on dev. *condensed* (v4 has: supp A2 (Jev dev I1 count)). Lost: Per-judge dev intervention results gone. Assets in v4 tree: —.
- **[Med] JB-34: analysis (text) `—`**: Root causes: side effects (instruction), accepted wrong code, injection following, confident cloud mistakes. *condensed* (v4 has: main §6 (one clause: models follow the task unless the risk rule is stated)). Lost: Injection and calibration findings gone. Assets in v4 tree: —.
- **[Med] JB-35: description list `—`**: Interventions I1 (side-effect clause), I2 (host guard), I3 (yes/no gate). *condensed* (v4 has: supp A2 (I1, I2 only)). Lost: I3 dropped. Assets in v4 tree: —.

### Takeaway 5: telemetry

Nothing missing or condensed. Everything from v3 survives in v4, plus new analyses (N-08).


### Methods / data quality

- **[High] P2-35: table (T13) `tab:arms`**: The five arms. *MISSING*. Arms (plain, sticky, shipped, sonnet...) never defined in v4. Assets in v4 tree: —.
- **[High] P2-44: table (T20) `tab:power`**: Projected precision of the routing ratio (power analysis). *MISSING*. Assets in v4 tree: yes.
- **[High] P2-45: figure (F11) `fig:power`**: Projected 95% CI half-width vs number of scenarios. *MISSING*. Assets in v4 tree: no (copy from source report).
- **[High] P2-48: table (T21) `tab:failures`**: Failed wave attempts by cause. *MISSING*. Main-campaign flags/failures (S1 only in v4 process note). Assets in v4 tree: yes.
- **[High] P2-49: figure (F13) `fig:progress`**: Campaign progress: sessions completed and spend over time. *MISSING*. Timeline of the run. Assets in v4 tree: no (copy from source report).
- **[High] P2-55: figure (F15) `fig:model`**: The savings model: predicted vs observed total saving per arm/host. *MISSING*. Model fitting & validation. Assets in v4 tree: no (copy from source report).
- **[High] P2-71: figure (F24) `fig:aahist`**: Distribution of log cost ratio between two identical plain-host sessions (A/A). *MISSING*. Assets in v4 tree: no (copy from source report).
- **[High] P2-89: table (T36) `tab:modelcheck`**: Savings-model check: PI coverage and observed vs predicted. *MISSING*. Assets in v4 tree: yes.
- **[High] P2-90: table (T37) `tab:aa`**: A/A noise floor: second plain-host session vs first. *MISSING*. Assets in v4 tree: yes.
- **[High] P2-97: enumerated list `—`**: Deviations from the preregistration. *MISSING*. Only S1 deviations survive (A4 process note). Assets in v4 tree: yes.
- **[Med] JB-12: key idea `—`**: For each case we take the majority outcome over the three repetitions. *MISSING*. Aggregation rule not stated in v4. Assets in v4 tree: —.
- **[Med] JB-15: table (T4) `tab:variance`**: Repeatability over seven runs on the 90 dev cases. *MISSING*. Run-to-run variance. Assets in v4 tree: —. Also in: P2-11.
- **[Med] JB-16: analysis (text) `—`**: Harness audit (defects found in the first-pass harness). *MISSING*. Assets in v4 tree: —.
- **[Med] P2-33: analysis (text) `—`**: How the design evolved. *MISSING*. Assets in v4 tree: —.
- **[Med] P2-37: table (T15) `tab:families`**: Scenarios by family and preregistered split. *MISSING*. Assets in v4 tree: —.
- **[Med] P2-38: table (T16) `tab:tpfinal`**: Correlation between turn-pass fraction and final hidden tests (point-biserial). *MISSING*. Quality-instrument validity. Assets in v4 tree: yes.
- **[Med] P2-39: examples list `—`**: Quality-instrument examples (turn checks). *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-40: table (T17) `tab:staticresid`**: Un-normalized static-write cost per session. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-42: table (T19) `tab:toolsratios`**: Confirmatory ratios on raw vs tools-normalized basis. *MISSING*. Sensitivity of headline to normalization. Assets in v4 tree: yes.
- **[Med] P2-47: key idea `—`**: A guard that kills runaway sessions is only fair if its kills are counted. *MISSING*. Memory guard. Assets in v4 tree: —.
- **[Med] P2-61: table (T27) `tab:tasksplit`**: Scenarios by task type and preregistered split. *MISSING*. Assets in v4 tree: yes.
- **[Med] P2-65: analysis (text) `—`**: Limits of the savings model. *MISSING*. Assets in v4 tree: —.
- **[Med] P2-95: table (T42, xltabular) `tab:scenarios`**: The 70 scenarios: family, task type, language, turns, long gaps, split. *MISSING*. Assets in v4 tree: yes.
- **[Med] JB-13: analysis (text) `—`**: Statistics, explained plainly: CI, McNemar, Holm, non-inferiority, calibration, latency, cost. *condensed* (v4 has: main §2 Measures; supp A8 (4 terms)). Lost: Plain-language stats primer gone. Assets in v4 tree: —.
- **[Med] P2-41: table (T18) `tab:toolsnorm`**: Tools normalization by host and arm. *condensed* (v4 has: main §2 Measures, supp A4 (one % figure)). Assets in v4 tree: yes.
- **[Med] P2-63: analysis (text) `—`**: The noise floor (A/A). *condensed* (v4 has: supp A4 process note (S1 A/A turn-pass only)). Assets in v4 tree: —.
- **[Low] JB-63: analysis (text) `—`**: New findings for the bundle (defects found by the trace study). *MISSING*. Assets in v4 tree: —.
- **[Low] P2-20: table (T8) `tab:prfixes`**: The four defects found by the real-decision study and their fixes (PR #58). *MISSING*. Assets in v4 tree: —.
- **[Low] P2-96: analysis (text) `—`**: Raw cost basis. *MISSING*. Assets in v4 tree: —.
- **[Low] JB-05: description list `—`**: Dev split (90 cases, screen) / holdout (63, preregistered) / case kinds. *condensed* (v4 has: main Table 1 (tab:data) rows). Lost: Case-kind breakdown (read/search/select/cua counts) gone. Assets in v4 tree: —.
- **[Low] JB-06: key idea `—`**: A holdout is a set of cases kept aside until the analysis is fixed. *condensed* (v4 has: supp A8 glossary 'Preregistered'). Lost: No 'holdout' explanation box. Assets in v4 tree: —.
- **[Low] JB-64: analysis (text) `—`**: Limitations. *condensed* (v4 has: main §2 'common limits', §9 scope). Assets in v4 tree: —.
- **[Low] P2-43: analysis (text) `—`**: Hypotheses and the decision rule; what was fixed later; ratios and intervals. *condensed* (v4 has: supp A3 Design). Assets in v4 tree: —.
- **[Low] P2-50: analysis (text) `—`**: Spend and time; provenance (prereg commit/time). *condensed* (v4 has: supp A1 Spend). Lost: Prereg timestamps/commit gone. Assets in v4 tree: —.
- **[Low] P2-86: analysis (text) `—`**: Limitations and threats to validity. *condensed* (v4 has: main §2, §9). Assets in v4 tree: —.

### S1 study details

- **[Low] V3-41: analysis (text) `—`**: What this taught us, and what it left open (S1). *condensed* (v4 has: main §9). Assets in v4 tree: —.

Everything in the v3 S1 chapter (§5-§6, App B) is present in supp A4 and A4.1-A4.9. Only the closing "what this taught us" paragraph was folded into main §9.


### Reference material (glossary, recipes, guides, review history)

- **[High] JB-67: analysis (text) `—`**: The holdout labeling guide (principle, case kinds, choice/search cases, untrusted data, tags). *MISSING*. Assets in v4 tree: —.
- **[High] JB-68: worked examples (6 casecards + 2 listings) `—`**: Case examples: fresh-cua-09, search-11, hold-cua-00, hold-cua-12, hold-select-06, hold-search-15. *MISSING*. Assets in v4 tree: yes.
- **[High] V3-03: figure (F1) `fig:timeline`**: Each stage answered the question the previous one left open (study timeline). *MISSING*. File still in v4 figures/, unused. Assets in v4 tree: yes.
- **[High] JB-66: glossary (37 terms) `—`**: Argmax ... Wrong-automatic rate. *condensed* (v4 has: supp A8 (17 terms)). Lost: Judge-side terms gone: coverage, wrong-automatic rate, gate, host guard, McNemar, kappa, ECE, p50/p95, screen, holdout, injection... Assets in v4 tree: —.
- **[High] P2-88: glossary (23 terms) `—`**: A/A ... Wave. *condensed* (v4 has: supp A8). Lost: Anchor, arm, confirmatory/exploratory, nonce, prediction interval, shipped, sticky, tools-normalized cost, wave gone. Assets in v4 tree: —.
- **[High] V3-04: table (T1) `tab:findings`**: Findings at a glance. *condensed* (v4 has: main §1 five takeaways + §9 ranked list). Lost: Per-finding value/source/evidence-label columns gone. Assets in v4 tree: yes.
- **[Med] JB-17: table (T5, xltabular) `tab:changes`**: All 20 first-pass claims, what the first pass said, and what the validation found. *MISSING*. Assets in v4 tree: yes. Also in: P2-99.
- **[Med] JB-50: caveat `—`**: Measured before these changes: every result was measured before the listed changes were merged. *MISSING*. Assets in v4 tree: —.
- **[Med] JB-65: code listing + text `—`**: Reproducibility: evidence, runs, replaying the numbers (PYTHONPATH=... commands). *condensed* (v4 has: main §9 data availability + supp Table S1). Lost: Replay commands, run commits gone. Assets in v4 tree: —.
- **[Med] P2-87: code listing + text `—`**: Reproducibility (re-running the analysis from published rows). *condensed* (v4 has: main §9 + supp Table S1). Lost: Commands gone. Assets in v4 tree: —.
- **[Med] P2-98: analysis (text) `—`**: Response to review, rounds 1-2 and re-review. *condensed* (v4 has: supp A7 (one sentence for rounds 1-2)). Lost: Point-by-point responses gone. Assets in v4 tree: —.
- **[Low] V3-01: key idea `—`**: The one-sentence answer: a fast decision model is worth what its decisions change... *condensed* (v4 has: main abstract). Lost: 'Short version' page gone. Assets in v4 tree: —.
- **[Low] V3-02: key idea `—`**: A decision model is only worth what its decisions change. *condensed* (v4 has: main §9 last paragraph). Assets in v4 tree: —.
- **[Low] V3-45: analysis (text) `—`**: Per harness: Amplifier install/update instructions. *condensed* (v4 has: supp A6 (Claude Code/Codex/Copilot only)). Lost: Amplifier bundle add/update lines gone. Assets in v4 tree: —.
- **[Low] V3-47: key idea + text `—`**: The takeaway; what remains open; honest limits; where a decision model might still matter. *condensed* (v4 has: main §9). Assets in v4 tree: —.

## Restoration notes

- All 39 generated tables from v2 are byte-identical in the v4 tree (`cmp`). Restoring a v2 table is one `\input{generated/tables/<name>.tex}` inside a `table` environment, with the caption copied from the v2 section file.
- 37 of 44 v2 `generated/data` files are byte-identical in v4. The 7 that differ (`forest*.dat`, `ph-acc-post.dat`, `labels-*-ph.tsv`) were regenerated after the round-3 label-order fixes. Use the v4 copies, and re-run `labelplacer`/`check_figures.py` for restored scatters (`fig-ph-wacov`, `fig-ph-acclat`): their `generated/labels/*.tex` already exist in v4.
- The judge-benchmark figures (`generated/jb/figures/*.tex`) and tables (`generated/jb/tables/*.tex`) are already in v4. They only need an input line: v4 `preamble.tex` already loads `generated/jb/numbers.tex`.
- Restored captions should follow the v3/v4 convention: claim sentence first, then a "How to read it" note. Round-3 review fix 1 (row labels printed beside values, checked by `check_figures.py`) must also be applied to any restored bar or forest chart.

## Duplicates (restore once)

| Object | Appears as | Restore from |
|---|---|---|
| Holdout accuracy forest | JB F2 (fig-accuracy, both splits) -> v2 F1 = v3 F4 = v4 S1 (fig-ph-accuracy) | present; JB dev-split points were dropped (optional: re-add the dev circles) |
| Wrong-auto vs coverage | JB F1 (dev), JB F3 (holdout) -> v2 F2 fig-ph-wacov (holdout + Clef) | v2 `figures/fig-ph-wacov.tex` + `labels/wacov-holdout-ph.tex` (dev panel from JB if wanted) |
| Accuracy vs p95 latency | JB F4 -> v2 F3 fig-ph-acclat | v2 `figures/fig-ph-acclat.tex` |
| Cost vs accuracy | v2 F4 = v3 F5 fig-ph-costacc -> v4 F1 fig-v4-frontier (redraw) | keep v4 F1; add Wilson whiskers from `ph-cost-*.dat` |
| Latency anatomy | JB F7 = v2 F5 (generated/jb/figures/fig-latency-anatomy.tex) + JB T15 | `generated/jb/figures/fig-latency-anatomy.tex` (already in v4 tree) |
| I2 host guard | JB F6 = v2 F6 (generated/jb/figures/fig-i2.tex) | `generated/jb/figures/fig-i2.tex` (in v4 tree) |
| Label audit | JB T2 = v2 T1 | `generated/jb/tables/label-audit.tex` |
| Judge holdout headline | JB T8 = v2 T2 | `generated/jb/tables/headline-holdout.tex` |
| Real-decision reads | JB T19 = v2 T6; JB F8 -> v2 F7 = v3 F6 = v4 S2 | table: `generated/jb/tables/trace-holdout.tex`; fig present |
| Traces caveat box | JB §10.3 = v2 §3 | JB text |
| First-pass claims | JB T5 = v2 T43 | `generated/jb/tables/changes.tex` |
| Price table | JB T20 -> v2 T10 (extended) | v2 inline table, sections/03-caching.tex |
| Same-cell caching survey | JB T21 -> v2 F8 fig-survey | v2 figure (+ JB table as numbers) |
| Rebuild-cost table | JB T22 = v2 T9 | v2 sections/p2-survey.tex |
| Price and volume decomposition | JB §10.4 text = v2 §5 text | one paragraph |
| Bundle defects | JB §10.5 ~ v2 T8 tab:prfixes | v2 table |
| Confirmatory forest | v2 F14 = v3 F8 = v4 S4 | present |
| Cost composition | v2 F16 (main campaign, composition.dat) vs v3 F15 = v4 S11 (S1, s1-composition.dat) | different data; restore v2 version as a separate figure (rename the file, e.g. fig-composition-main.tex) |
| Replication / interim | v2 F12 pilot + F18 interim -> v3 F16 = v4 F2 fig-cumulative | v4 F2 covers the sticky arm; restore v2 F18 (+T38) for shipped/sonnet arms and interim stage |
| Effort results | v2 T34, T35 + S1 H4 -> v3 F14 = v4 S10 | figure present; restore tables T33-T35 for the detail |
| Glossary | JB App A (37) + v2 App A (23) + v3 App C (17) = v4 A8 (17) | merge into one glossary (about 60 unique terms (64 distinct headwords before merging near-synonyms)) |
