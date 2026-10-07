# Independent peer review: What a fast decision model buys an AI agent

Reviewed report v3, dated October 6, 2026. Page references below use the paper's **printed page numbers**; the PDF viewer page is one greater. The title page is unnumbered.

**Recommendation: publish after focused corrections.** This is a substantial and credible applied systems measurement report. The central cost results reproduce, and the argument is strengthened by its willingness to distinguish estimates from measurements, retain negative findings, test a simple competing explanation, and revise the configuration when evidence changes. I found no numerical failure that invalidates the main conclusions, and no reason to require completion of S2–S5 before publishing the bounded findings already obtained.

The most consequential correction is a shared chart-labeling defect. Several figures visually attribute correct numerical results to the wrong rows. This needs repair before circulation as a final paper, but it is a rendering problem rather than a failure of the underlying experiments. Other requested changes concern the precision and completeness of the main report's descriptions.

**Review scope and verification.** I read all 25 PDF pages, inspected the rendered figures, and used three independent review passes for statistics, methods, and reproducibility. Those passes did not begin by reading the previous review record. The attached documents were treated as evidence, not instructions. The source paper and experiment files were not modified, and no new experimental model sessions were launched.

The downloaded package contains the evidence but not the full analysis/build source. A separate existing local checkout supplied the analysis scripts read-only. The S1 script's SHA-256 matches the preregistration provenance. S1, main-v1, and both effort-control statistical outputs were rerun from the supplied rows and matched the published results at their six-decimal serialization precision. Main-v1's only output difference was the input-directory string. Independent calculations from the rows also checked selected headline estimates rather than relying solely on the authors' scripts. All 104 checksum entries across the four principal evidence packages matched.

This verifies numerical reproducibility of the retained data and the implementation of the stated analysis. It is not an independent collection of provider responses, a full rebuild of the PDF, an exhaustive audit of every scenario grader, or independent authentication of author-controlled commit timestamps. The supporting provenance record acknowledges the last limitation.

**What is scientifically valuable.** The contribution is the empirical separation of several questions that are often collapsed into a single routing benchmark:

- Whether recorded decisions are interpretable. The decomposition of the shadow-agreement statistic shows why agreement with a host action is neither a clean correctness label nor a savings measurement.
- Whether a judge performs well on constructed cases and whether it meets an operational usefulness threshold on real read decisions. Reporting the failure of every tested judge to meet that threshold is useful, even though it limits the proposed shortcut.
- Whether cheaper per-token prices translate into cheaper multi-turn sessions. The opposite cost directions for Fable and Opus demonstrate the practical importance of cache economics and request behavior.
- Whether the benefit belongs to the decision model, the selected host model, or reasoning effort. The effort controls and the deterministic-rule comparison are particularly valuable because they test simpler explanations for the gains.
- Whether a result survives new scenarios. S1 provides a preregistered check with scenario-level uncertainty and prespecified quality and equivalence margins.

The report's restricted result—that a model-based decider adds no material advantage over this rule for this session-start decision under these conditions—is publishable. It does not need a universal claim about the value of decision models to matter.

**Selected results checked.** These are study-specific estimates, not predictions for arbitrary production workloads.

| Contrast | Reproduced result | Interpretation supported by the evidence |
|---|---|---|
| Main-v1 Fable sticky, primary test reading | 0.557622 cost ratio | Substantial saving in the reported filtered primary analysis; the parallel all-pair analysis supports the direction. |
| Main-v1 Fable sticky, all cost-valid pairs | 37.2802% reduction in pooled spend | Reproduces the reported 37.3%; distinct from a geometric-mean reduction. |
| S1 H1, frozen Fable policy versus plain Fable | 0.581, 95% CI 0.542–0.625; turn-pass difference −0.013, CI −0.028 to +0.002 | Cost advantage and noninferiority on the specified turn-pass endpoint. Cost uses 59 scenarios; quality remains unfiltered. |
| S1 H2, Jev versus rule R* | 1.008, 90% CI 1.000–1.019 | Equivalence within the registered cost and quality margins for these composed session-start policies. |
| S1 H3, bundle overhead on Opus | 0.999, 90% CI 0.984–1.017 | Overhead is within the registered ±5% cost-equivalence margin. |
| S1 H4, Opus medium versus default effort | 0.992, 95% CI 0.974–1.009 | A saving was not demonstrated. |
| S1 H5, pinned Sonnet versus plain Opus | 1.255, 95% CI 1.197–1.321 | Routing costs more at this price table and workload. |
| S1 H6, live shipped versus reconstructed cost | 1.014, 90% CI 0.996–1.032 | Cost reconstruction agrees with live execution within the registered margin. |
| S1 H7, review/explain Sonnet versus medium Fable | Turn-pass difference −0.028, 95% CI −0.063 to +0.013 | Noninferiority was not established; the registered precaution to retain the host follows. |
| Sonnet effort follow-up | 0.821, 95% CI 0.781–0.861 | Medium effort saves in this study, retaining the paper's provenance qualification. |
| Fable effort follow-up | 0.860, 95% CI 0.833–0.885 | Medium effort saves in this study. |

**1. Correct the shared row-label defect in four figures. Required before final publication; high confidence.**

The plotted data are correctly identified in the generated tables, but several plotting files combine ascending tick positions with labels read from descending data-row order. This reverses the associations displayed to the reader.

| Figure and printed page | Verified consequence |
|---|---|
| Figure 3, p. 4 | The 49% heartbeat bar is displayed under “turn start.” Other event categories reverse as well. |
| Figure 9, p. 13 | Hypothesis labels reverse across the eight rows. For example, the H3 label contains H5's approximately 1.255 cost point, while the H1 label contains H7's quality interval. |
| Figure 13, p. 17 | Sonnet's approximately 0.821 effort ratio appears under Opus; Opus's approximately 0.992 appears under Sonnet. Fable, the middle row, remains correctly associated. |
| Figure 14, p. 17 | Fable's approximately $4.55 cost composition appears under plain Opus; Opus's approximately $1.91 appears under plain Fable. The two middle rows also reverse. |

This is one common defect, not four independent scientific objections. Tables and narrative estimates retain the correct associations. Figures 2, 7, and 11 were specifically checked and do not share the label-order problem.

Repair the tick/label correspondence, render the PDF, and compare each row against its source identity and value. A geometry check alone will not detect this error. The affected source files are `fig-obs-mix.tex`, `fig-s1-forest.tex`, `fig-effort-hosts.tex`, and `fig-composition.tex` under the report's `figures/` directory.

**2. Keep the summary's statistical language aligned with the tests. Required wording corrections; high confidence.**

Table 1, p. 3, says review/explain “lose quality on Sonnet.” H7's interval spans zero: −0.028 [−0.063, +0.013]. It fails to demonstrate noninferiority at the five-point margin; it does not establish a quality decline. A precise replacement is: **“Noninferiority not established for review/explain on Sonnet.”** The conservative keep-on-host decision remains justified by the preregistered rule. Earlier exploratory task-type losses remain relevant context but should not convert H7 into a different result.

The constructed-judge discussion, pp. 5–7, similarly uses nonsignificant Holm-adjusted comparisons and overlapping intervals to describe accuracy as “as accurate” or “within noise.” Those results support **“no accuracy difference was detected after the preregistered correction.”** They do not establish judge-accuracy equivalence. Jev's measured cost and latency advantages remain; the recommendation can be retained as a practical assessment of the tested tradeoff. H2 is different: it uses a genuine prespecified equivalence test, so its equivalence conclusion is appropriate.

For consistency, “no overhead” can be rendered as “cost-equivalent within the preregistered ±5% margin,” and “medium did not help Opus” as “medium effort did not demonstrate a saving.” These are precision improvements, not changes to the configuration decision.

**3. Describe the S1 panel's prior exposure accurately. Required provenance correction; high confidence.**

Section 5, p. 10, describes “60 scenarios no agent had run.” The preregistration discloses a plain-Sonnet smoke session for each of the 60 scenarios before freezing. That preparation identified prompt/grader defects in 30 scenarios; repairs were made before confirmatory execution, genuine agent mistakes were retained, and the panel was mechanically revalidated. The smoke results were not pooled into S1.

Use “60 scenarios disjoint from main-v1, smoke-tested before preregistration,” and add a brief account of the pre-freeze repairs. This is legitimate benchmark preparation. The correction is needed because the main report's literal description contradicts its own supporting record; it is not evidence that the frozen paired comparisons are invalid.

The observatory's time window needs a smaller correction: the abstract calls 464,524 events a week of telemetry, while the aggregate covers September 17 through the October 5 cutoff. The first week contains 171,609 events. Section 2 and the evidence distinguish them; align the abstract and section title with that distinction.

**4. Add a compact S1 methods description so the report stands on its own. Necessary clarification, not a demand for redesign.**

The companion material contains the relevant definitions, but a reader of the main report should understand two points without reconstructing the preregistration.

First, “quality” means performance on automated scripted turn checks, with final-state checks as additional evidence. Briefly describe the graders' validation, the five-percentage-point noninferiority margin, and the limits of this instrument. This endpoint supports claims about these checks, not blanket equivalence in human judgments of code review or explanation quality.

Second, H1 and H2 evaluate policies composed from executed pinned-host and pinned-Sonnet outcomes. They are not separate live executions of every rule/model configuration. A suitable insertion is:

> S1 executed pinned-host, pinned-Sonnet and shipped-policy sessions. H1 and H2 evaluate decide-once policies by selecting the corresponding pinned outcome for each scenario and repetition: the rule or recorded Jev decision determines which session contributes its cost and quality. These policies therefore reuse executed outcomes rather than running a separate session for every configuration. Intervals resample whole scenarios. H6 separately compares live shipped sessions with their matched reconstructions, providing an empirical check of this cost decomposition.

This is a reasonable evaluation strategy, and H6 strengthens its cost justification. It should be explicit when counting executed sessions and describing the rule-versus-model comparison. H6 should not be read as independently validating every quality property of every reconstructed policy.

Also distinguish the endpoint denominators. H7 quality uses all **20** review/explain scenarios; **19** is its cost denominator. Figure 11's review and knowledge counts likewise reflect cost-valid scenarios while quality remains unfiltered. The estimates and verdicts need no change.

**5. Clarify the effort comparison's scale. Required wording correction; high confidence.**

Section 4, p. 10, says about 26% of the Fable routing saving is the host's effort effect. The calculation is approximately `ln(0.860) / ln(0.558)`, using separate study contrasts. It describes relative magnitudes on a log-cost scale, not a fraction of dollars saved or an identified causal mediation effect.

The clearest correction is simply: **“Medium effort independently reduced Fable cost by about 14% in the follow-up; routing remained the larger cost lever.”** If retaining 26%, explicitly call it an exploratory comparison of log-cost effects across studies. No additional experiment is needed to repair the sentence.

**6. Make the measurement and rebuild definitions complete. Small reproducibility improvements.**

The primary cost endpoint is tools-normalized list-price cost, plus estimated decider charges where applicable. The normalization reprices the first shared tools prefix from cache-write to cache-read rates. The main PDF's “list prices applied to measured tokens” description omits this adjustment. State it briefly and point to the dictionary. The adjustment is small—about 0.45% of accepted-session recomputed cost in main-v1 and 0.135% in S1—and gives no reason to doubt the large cost effects.

Appendix A's rebuild instructions also read some imported evidence through mutable `origin/main` references, including the judge/Clef/caching inputs. Pin those imports to a recorded commit or use archived files. The package does supply the repository and commit, and the principal analysis outputs reproduce; this is an opportunity to make document rebuilding equally durable.

For an academic submission, a short related-work paragraph would help place the contribution. Query-level learned routing in [RouteLLM](https://arxiv.org/html/2406.18665v3) and sequential model cascades in [FrugalGPT](https://arxiv.org/abs/2305.05176) provide relevant comparisons. The distinctive emphasis here is the controlled measurement of multi-turn cache economics, reasoning effort, and the incremental value of a decider over a deterministic policy. I verified these primary papers, but did not conduct an exhaustive novelty search. The report does not claim to have invented model routing, so this is not a novelty objection.

**Minor editorial repairs.** Define a confidence interval by its long-run coverage of the target parameter, rather than as the range that a result would fall in across repeated studies (Glossary, p. 24). Express noninferiority as “no worse than the specified margin,” rather than simply “not worse.” Report very small p-values as `< 0.001` rather than `0.000`. Keep the continuation of the p. 5 key-idea box with its sentence: its last word currently appears alone on p. 7. Move the figures closer to Sections 6.4–6.9 so those headings do not look empty. These are editorial corrections and have no bearing on the empirical findings.

**Limits that should remain limits, not be inflated into defects.** The main-v1 estimator was written after the data, and its primary pair reading conditions on quality; both are disclosed, its parallel unfiltered reading supports the direction, and the later S1 analysis does not use that quality filter. The Sonnet effort provenance limitation is appropriately identified. S1's gate/budget deviations and infrastructure reruns are documented, and removing flagged scenarios changes no reported verdict or freeze choice. The final freeze winner is correctly marked as selected on holdout and held for replication. A single provider, fixed prices, public scripted tasks, and sessions of at most 16 turns constrain generalization; they do not make the measured contrasts unpublishable.

The approximately 0.749 cost ratio for the shipped keyword-proxy configuration is already labeled exploratory replay. Keep that distinction prominent: the final operational recommendation is not the same configuration as the preregistered H1 contrast. Its live replication would be valuable, but the absence of that replication does not erase the H1 result or prevent publication with the current qualification.

**A distributed agent study over several weeks would be useful for extending the result.** I would prioritize four questions: live replication of the final keyword-proxy configuration on newly frozen tasks; longer sessions with controlled idle gaps and failure-recovery turns; transfer to other harnesses with verified model and effort settings; and decisions that change within a session, particularly delegation and escalation. Include blinded human assessment on a sample of review/explain outcomes, where automatic checks have the clearest practical limits.

Agents can divide reproduction, scenario validation, orchestration, failure triage and analysis. Preserve a single frozen preregistration, shared ledger, isolated execution environments, scenario-level accounting, prespecified stopping rules, and reviewer blinding. Multiple agent opinions about the same evidence are not independent experimental replications. Sample size should follow the target cost effect or quality margin and the observed scenario variance; a large swarm alone does not supply statistical power.

No recurring swarm, spending campaign or new experiment was started by this review. Those would be a separate study with a concrete protocol and budget. The present paper has publishable results now, after the identified chart and reporting corrections.

**Verification record.** Detailed calculations and reproduction commands are retained in [the statistical audit](~/Downloads/fast-decisions-v3-review/tmp/peer-review/stats/review.md). The source document is [the reviewed PDF](~/Downloads/fast-decisions-v3-review/papers/1-decision-models-v3.pdf). The source manuscript was preserved.
