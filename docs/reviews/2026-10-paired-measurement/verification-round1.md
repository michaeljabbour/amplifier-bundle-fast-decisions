# Verification of the peer review: "Measured, not estimated" (paired-measurement report)

Read-only check, made 2026-10-05. Nothing was committed and no API calls were made. All computation ran under `nice -n 10`.

**Inputs.** The report is `docs/papers/2026-10-02-paired-measurement/paired-measurement.pdf` (48 pp, built 2026-10-04 21:57). The evidence is in `docs/evidence/2026-10-02-paired-campaign/`.

**Branch.** The checkout is on `eval/paired-measurement` @ `d0d205c`, not `main`. Local `main` is stale: it does not contain the paper. `origin/main` (`a7fcc9a`) has the paper, and `git diff HEAD origin/main` is empty for the paper, the evidence, `evals/paired*.py` and `evals/cells.yaml`. So these results apply to `main` too.

**Page numbers.** All page references are the printed page numbers. The printed number is the physical PDF page minus 1.

**Scripts.** The scripts are in `verification-scripts/` (originally run from a scratch directory):
- `common.py` loads the rows and uses `evals/paired_model.py`'s own `load_dataset` and `cluster_boot_mean`, so the bootstraps match the report's estimator.
- `c10.py` is the launch-offset regression.
- `c11.py` covers sticky versus the Sonnet control, and claim 7.
- The parsed request rows (a local pickle, not published) are rebuilt from `data/requests.jsonl.gz` in `c11.py`.

## Summary table

| # | Claim (short) | Verdict | Key evidence | Fix |
|---|---|---|---|---|
| 1 | "Preregistered" overstates; estimator 56 min after; 4/4 depends on scoping; Opus sticky excused post hoc | **Partly correct** | Campaign ended 17:39:07 EDT (`campaign/supervisor.log`); `paired_confirm.py` was first committed in `c3ea41a` at 18:34:57 EDT, 55 min 50 s later. The script docstring (`evals/paired_confirm.py:4-7`) says it fixed the filter, the savings-claim scoping and the verdict rule. Opus sticky ΔTP −0.0102 [−0.0582, 0.0329] is "not confirmed", which is not the same as failed. **But** the rule "each savings claim requires non-inferior turn-pass" is verbatim in the preregistration (`prereg/PREREGISTRATION-main-v1.md`, Hypotheses). Only the *definition* of a savings claim (a cell whose cost CI upper bound is below 1; `paired_confirm.py:202-207`) is post hoc. The paper already discloses all of this in §7.6, the §9 intro, §13 and App. B (p. 42). | Drop or qualify "[preregistered]" on §9 and "All 4 preregistered hypotheses were confirmed" (`01-summary.tex:41`). Say: "hypotheses and thresholds preregistered; estimator and savings-claim scope fixed after data collection." Add one sentence: if quality is required of every routed cell, Quality is "not confirmed" (3 of 4). |
| 2 | "44 %" is a GM of per-pair ratios; the spend reduction is 37.3 %; only one is labelled | **Correct**, with a nuance | 44 % = 1 − 0.5576 (test, pair-filtered GM; `build_assets.py:372`). All-70 spend: $5.3114 → $3.3313, a 37.3 % reduction (ratio of means 0.6272). Table 21's $1,980 = 1000 × (5.3114 − 3.3313) = 1,980.1 (mean of 140 pair deltas). The gap is almost entirely the estimator: GM all-70 = 0.5596 (44.0 %) against a ratio of means of 0.6272 on the same sessions. Split and filter barely matter (GM 0.5576 / 0.5372 / 0.5596). 37.3 % appears nowhere in the paper. "44 %" at `01-summary.tex:19` and `08-recommendations.tex:5` is not labelled as a geometric mean. | Label the 44 % as "typical per-session (geometric-mean) saving". Report the spend reduction (37.3 % all-70; 42.4 % test) next to it. State that per-1,000 figures are mean-$ (spend) based. |
| 3 | Test split has zero docs; split stratified by family and pause pattern, not task type; docs is the largest Fable saving; one of only two task types with positive Opus savings | **Mostly correct; one sub-claim wrong** | All 4 docs scenarios are train (`commander-`, `fatihcolor-`, `fd-cli-`, `kac-docs`). The strata are (family, gap pattern) (`prereg/SPLIT.md`). Test task mix: bugfix 6, mixed 10, feature 3, explain 2, review 2, docs 0. **Wrong part:** docs is *not* the largest Fable saving. For sticky, review is larger ($3,007 vs $2,615); for shipped, review is $3,011; for sonnet, feature is $2,895 (Table 21). **Right part:** docs and explain are the only task types with positive Opus sticky and shipped savings (264/162 and 341/235). | State that docs has no held-out scenario and that the Opus "docs/explain exception" (§10.2, Fig 17 caption) is train-only for docs. Show task-type × split counts in Table 14 or 30. |
| 4 | Primary filter conditions on a post-treatment outcome; Fable sticky clears −0.05 by 0.0035; the point estimate flips sign | **Correct, and already disclosed**; one conflation | Pair filter = ΔTP ≥ 0. For Fable sticky it drops 8 of 46 (`confirm.json`). The filter is on the **cost** endpoint (Table 17). The quality test (Table 19) uses all 46 pairs, so the 0.0035 margin is not affected by it. Lower bound −0.0465 → margin 0.0035. Mean +0.0015 test, −0.0209 all-70 [−0.058, 0.012], −0.0319 train [−0.081, 0.008]. A different RNG stream gives −0.0451, so the margin is about the size of bootstrap Monte-Carlo noise. Disclosed at §9.2, §12, §13 ×2 and App B dev. 3. | Make the arm reading primary, or co-primary, for cost. In the Summary key-idea box, say "non-inferior on test only; not shown on all 70 or on train". Note the bound is within MC noise. |
| 5 | Largest savings coincide with largest quality losses (knowledge); not cross-referenced | **Correct at family level; not a general pattern** | Knowledge, Fable sticky: saving $2,973/1k (the largest family; GM 0.447) and ΔTP −0.083 [−0.140, −0.028] (the worst). Opus sticky knowledge ΔTP −0.060 [−0.115, −0.006] (the worst). The same holds for shipped. It does **not** hold for Fable sonnet (polyglot −0.041 is worse than knowledge −0.029; polyglot saves more). Inside knowledge, the losses are in explain (−0.143) and review (−0.155); docs is −0.033. Scenario-level Spearman(saving, ΔTP) = −0.02 (Fable sticky), so this is a family/task effect, not "more saving → more loss". Table 23 (§11.6) and Table 21 (§10.2) never reference each other. | Add a joint savings × ΔTP table by family/task, or cross-reference. Flag that knowledge (and review/explain) fails the −0.05 margin on Fable sticky. |
| 6 | Tools normalization $15.37 should be ~$260.70; Sonnet component $15.50 means an asymmetric adjustment | **Wrong arithmetic premise; asymmetry is real but removes a bias** | $260.70 reproduces exactly if *every* session wrote the full 32,100-token prefix: 448 × Fable + 448 × Opus + 140 × Sonnet at 32,100 × (write − read) = 176.17 + 69.03 + 15.50. The $15.50 is the reviewer's own Sonnet term; the measured Sonnet-arm adjustment is $2.13. Of 1,195 repriced first-per-(model, effort) requests, 1,121 were already warm: they read 32,029 or 32,033 tokens and got about 67–71 tokens repriced each, $0.44 in total. 74 were cold (read < 20k) and got the full 32,100: $14.93 of the $15.37. The cold ones are concentrated on anchors: Fable 16/140, Opus 22/140, Sonnet 19/140, against sticky 2–3/140. The adjustment *lowers anchor cost more*, so it **raises** routed ratios: test, pair reading, Fable sticky 0.552 raw → 0.558 normalized; Opus shipped 1.358 → 1.380. That is conservative for the Fable claims and slightly favourable to H2. | Publish the cold/warm table by arm. Say the 32,100 allowance overshoots the measured prefix (32,029/32,033) by about 70 tokens. Keep the raw-basis verdicts visible (App B already has them). |
| 7 | Sticky makes 10.5–11.8 % fewer requests than composition weighting predicts and costs 15.7 % less on Opus | **Correct** | Weights 124/140 Sonnet + 16/140 host from Table 20 means. Requests: Fable predicted 56.07 vs actual 50.19 (−10.5 %); Opus 54.97 vs 48.50 (−11.8 %). Cost on Opus: 3.096 vs 2.615 (−15.6 %; −15.7 % with Table 20's rounded values). On Fable it is only −3.7 %. Matched to the same scenario-rep partner: requests 0.894× / 0.895×, cost 0.941× (Fable) / 0.870× (Opus). | See claim 11 for the cause. Correct §12's "the sticky arm is mostly plain Sonnet" (`08-recommendations.tex:14`, `04-design.tex:70-72`). |
| 8 | Turn rows 11,576 (§11) vs 11,588 (§14) | **Correct; cause found** | 11,588 − 10 (all turns of the memory-killed `py-forth-r2-opus-aa`) − 2 (skipped last turns in two cost-valid `agent_fail` sessions: `mistune-escape-r1-any-sonnet` turn 8 and `go-dominoes-r1-fable-sticky` turn 13) = 11,576. Filter at `build_assets.py:1141` (cost_valid and not skipped). Those two skips are not mentioned in `FAILURES.md` or the paper. "11576" is also printed without a thousands separator (`07b-more.tex:4`). | One line in §11: "11,576 = 11,588 minus the 10 turns of the killed session minus 2 skipped turns", and name the two skips. Format with `\num`. |
| 9 | §§11.4, 11.5, 11.7 are empty headings | **Correct as rendered** | `07b-more.tex:68,81,103`: each subsection holds only a float. On p. 33 the headings 11.4, 11.5 and 11.6 are stacked with no text. Figs 23 and 24 land on pp. 34–35. The 11.7 heading falls at the bottom of p. 36, *after* its own Fig 25 (p. 35) and Fig 26 (p. 36), directly before Part IV. Fig 26 (session length) is not about requests. | Add 1–3 sentences of findings to each subsection, use `[H]` or `\FloatBarrier`, and move Fig 26 under §10.2 or its own heading. |
| 10 | §10.4 attributes Opus A/A 1.049 to fixed launch order, but Fable A/A is 0.968 with the same order; regress on offset | **Correct; regression does not support the launch-order explanation** | `scheduled_start` is null on all 1,036 rows, so the offset is `actual_start` minus the wave's first start. The start order is not actually fixed: the anchor started first in only 64 % (Fable) / 59 % (Opus) of waves, and aa started before the anchor in 36 % / 30 %. A/A slope of log ratio on Δoffset (aa − anchor), scenario-cluster bootstrap B = 4,000: **Fable −0.0014/s [−0.0114, +0.0071], n = 28; Opus −0.0064/s [−0.0181, +0.0083], n = 27.** The intercept at Δ = 0 is still 0.970 (Fable) and 1.054 (Opus). The Opus A/A is +0.064 when aa started first against +0.041 when the anchor did, the wrong sign for an order effect. The A/A log ratio tracks the request-count ratio (r = 0.49 Opus, 0.68 Fable). | Replace "plausibly because the launch order was fixed" (`07-exploratory.tex:109`, `09-limitations.tex:34-35`, `04-design.tex:31-34`) with "unexplained; not associated with start offset (slope …)". Note that 1 of 2 A/A intervals excluding 1 is unremarkable. |
| 11 | Missing analysis: sticky (when it chose Sonnet) vs plain Sonnet | **Computed: the sticky-Sonnet arm is materially cheaper than plain Sonnet** | GM cost ratio sticky/control: **Fable 0.861 [0.830, 0.893] all (124 sessions / 62 scenarios); 0.872 [0.828, 0.920] test (44 / 22). Opus 0.826 [0.795, 0.856] all (124 / 63); 0.824 [0.768, 0.878] test (43 / 22).** Requests per session: 48.8 vs 55.3 and 48.4 vs 55.2 (GM 0.89). Output tokens −31 %; execution time −27 %. ΔTP −0.012 (CI includes 0). Cause: sticky-cheap runs Sonnet at **effort = medium** on all 12,062 main requests (`evals/cells.yaml:781-799`, inherited `start_effort`). The control has effort unset (`cells.yaml:104-110`), described as "no effort set, which means high" in `docs/design/parallel-measurement-mode.md:30`. It is not a read shortcut: the cell is `backend: none` and there are no judge or shortcut receipts. | The "use Sonnet" comparison in §12 is confounded by effort. Add this analysis. Re-state the §12 conclusion. Recommend a "Sonnet at medium" control in the next campaign. |

Two related findings are not among the reviewer's claims. Both matter for claims 6, 10 and 11:
- **The Sonnet control runs only in the Opus wave.** All 140 sonnet sessions have `wave_id …-opus`. The 140 Fable–sonnet pairs therefore compare sessions started a median 5.7 h apart (max 23.6 h), not "within seconds" as §7.2 says. Table 13 says only that one run serves both hosts.
- **When sticky kept the host model (16 per host), it cost more than the plain host.** GM 1.255× (Fable) and 1.357× (Opus), n = 16 each. Those sessions ran the composed bundle with effort routing (high/medium/low). On Fable, "sticky ≈ plain Sonnet" (0.558 vs 0.577) is two effects cancelling: the medium-effort Sonnet saving (0.504 vs the control's 0.586 on the same scenarios) and the dearer host-kept sessions.

---

## Details and computations

### Claim 1: preregistration record

- **Timeline.** The preregistration commit `3aa2d1e` is at 2026-10-01 10:18:42 EDT, and the first session started 10:24:54 EDT (`prereg/PROVENANCE.md`). The campaign completed at 17:39:07 EDT on Oct 2 (`campaign/supervisor.log`, last line). `evals/paired_confirm.py` was first added in `c3ea41a` at 2026-10-02 18:34:57 −0400 (`git log --follow`). The gap is 55 min 50 s.
- **Exploratory summaries already existed.** The paper itself says so (§7.6 at p. 20; §13 "The estimator was written after the data"; App B "Three further points" item 1, p. 42). So does the script docstring (`evals/paired_confirm.py:4-7`): "…which cells count as savings claims, and the verdict rule … written after the campaign's data were collected … when exploratory all-split summaries … already existed."
- **What the preregistration text actually says.** It says "Primary endpoint: … among pairs where quality is non-inferior (turn-pass fraction margin -0.05)" and "**Quality:** each savings claim requires non-inferior turn-pass fraction (bootstrap lower bound > -0.05)." The *scoping to savings claims is preregistered*. What was decided post hoc is the operational definition: a cell is a savings claim if its cost CI upper bound is below 1 (`paired_confirm.py:202-207`; App B point 2). The reviewer's "excused by a post-hoc rule" is therefore an overstatement. The scope rule is in the preregistration; its operationalization is not, though it is the natural one.
- **Table 19, Opus sticky.** The mean is −0.0102 with 95 % CI [−0.0582, 0.0329] and verdict "not confirmed" (`confirm.json`). The reading is "non-inferiority not shown", not "inferior": the CI straddles −0.05.
- **Does 4/4 depend on the scoping?** Yes. If Quality were required of every routed cell, Opus sticky would make Quality "not confirmed", giving 3 of 4. It does **not** depend on the pair-vs-arm filter: Table 18 and `confirm.json` give identical verdicts under both readings. The 20 alternative seeds also change no verdict (`seed_robustness.all_stable = true`).
- **Problem is labelling, not concealment.** The `[preregistered]` tag on §9 and "All 4 preregistered hypotheses were confirmed" (`01-summary.tex:41`, `NHypConfirmed` at `build_assets.py:393`) read stronger than the record supports.

### Claim 2: 44 % vs 37.3 %

Fable sticky, tools-normalized basis (from `pairs.jsonl` via `paired_model.load_dataset`):

| sample | n pairs | GM ratio | ratio of mean $ |
|---|---:|---:|---:|
| test, pair-filtered (primary) | 38 | **0.5576** → 44.2 % | 0.6009 |
| test, all cost-valid | 46 | 0.5372 | 0.5763 |
| all 70 | 140 | 0.5596 → 44.0 % | **0.6272** → 37.3 % |

- Mean $/session over all 70: anchor 5.3114, sticky 3.3313. So 1 − 3.3313/5.3114 = 37.28 %.
- `per_1000_empirical` = −1000 × mean(delta) = 1,980.1 (`paired_confirm.py:334-346`). Every Fable sticky pair is valid, so this equals 1000 × (5.3114 − 3.3313).
- `CfFableStickySaving = pct(1 − gm_ratio)` (`build_assets.py:372`) gives 44.
- The 44 % appears at `01-summary.tex:19` (p. 2) and `08-recommendations.tex:5` (p. 36) with no "geometric mean" label. The GM is defined in §7.6 (p. 20) and named in the Table 17 caption.
- The other Fable arms show the same pattern: shipped GM 0.6325 vs ratio of means 0.6697; sonnet 0.5867 vs 0.6065.

### Claim 3: docs in the split

- Task type × split (`sessions.jsonl`): bugfix 12 train / 6 test; feature 10/3; mixed 18/10; **docs 4/0**; explain 1/2; review 2/2.
- The strata are (family, gap pattern) and the unit is the upstream project (`prereg/SPLIT.md` Method 1–3).
- Table 21 maxima on Fable:
  - sticky: review 3,007 > docs 2,615 > explain 2,315;
  - shipped: review 3,011 > docs 2,263;
  - sonnet: feature 2,895 > review 2,389 > mixed 2,405 (docs 2,246).
- Positive Opus savings: sticky docs 264, explain 341; shipped docs 162, explain 235; sonnet explain only (242).
- Consequence: the Opus "short read-heavy" exception (Fig 17 caption, p. 29) rests, for docs, entirely on training data. The confirmatory Fable ratio has no docs scenarios in it. Because docs saves more than average, its absence probably makes the confirmatory Fable ratio slightly conservative rather than optimistic.

### Claim 4: quality filter and margin

- The pair filter is `dtp > −0.05`, which is equivalent to `dtp ≥ 0` (`paired_confirm.py:97-98`, docstring lines 15-18). It is applied to the **cost** endpoint only.
- The quality test (`quality_endpoints`, `paired_confirm.py:177-189`) uses all 46 quality-valid test pairs per cell.
- Effect of the filter on the cost ratio (arm → pair reading, test):

  | | sticky | shipped | sonnet |
  |---|---|---|---|
  | Fable | 0.537 → 0.558 | 0.618 → 0.629 | 0.590 → 0.577 |
  | Opus | 1.203 → 1.249 | 1.321 → 1.380 | 1.457 → 1.433 |

  So the filter raises the sticky and shipped ratios (the paper says "0.01 to 0.06", which is correct for those arms) and *lowers* sonnet's.
- On Opus the filter makes H2 easier to confirm, but the arm reading confirms it anyway.
- Fable sticky ΔTP, using the same estimator with my own RNG key:

  | sample | mean | 95 % CI |
  |---|---:|---|
  | test (`confirm.json`) | +0.0015 | [−0.0465, 0.0547] |
  | test (my key) | +0.0015 | [−0.0451, 0.0555] |
  | train | −0.0319 | [−0.0806, 0.0081] |
  | all 70 | −0.0209 | [−0.0556, 0.0119] (paper: −0.058, 0.012) |

  The 0.0035 margin is about the same size as the run-to-run Monte-Carlo noise in the bound (0.0014 between two RNG streams).
- Already disclosed: §9.2 (p. 26), Key idea §12 (p. 36), §13 bullets "primary filter selects on an outcome" and "Quality is near the margin" (p. 38), App B deviation 3 (p. 42).

### Claim 5: knowledge family

All 70 scenarios, cost-valid pairs. "Saving" is mean −Δ$ × 1000; ΔTP is the mean turn-pass difference.

| host/arm | knowledge | mixed | polyglot | repos |
|---|---|---|---|---|
| Fable sticky saving/1k (GM) | **2,973 (0.447)** | 1,783 (0.506) | 2,229 (0.597) | 1,047 (0.713) |
| Fable sticky ΔTP | **−0.083** | +0.009 | −0.044 | +0.025 |
| Fable shipped saving/1k / ΔTP | **2,727 / −0.061** | 1,517 / +0.001 | 2,106 / −0.025 | 761 / +0.026 |
| Fable sonnet saving/1k / ΔTP | 2,576 / −0.029 | 2,024 / +0.015 | **2,897 / −0.041** | 739 / +0.023 |
| Opus sticky saving/1k / ΔTP | **+31 / −0.060** | −126 / +0.010 | −751 / −0.007 | −1,070 / +0.005 |

- Knowledge ΔTP with scenario-cluster CI: Fable sticky −0.083 [−0.140, −0.028] and Opus sticky −0.060 [−0.115, −0.006]. Both exclude 0, and both lower bounds are below −0.05.
- Within knowledge, Fable sticky ΔTP is: docs −0.033, explain −0.143, review −0.155, mixed +0.007.
- Scenario-level Spearman(saving, ΔTP) for Fable sticky is −0.020 (Opus −0.028), so there is no general trade-off.
- Cross-references: none. "Knowledge" appears in the PDF text only in §7.4, Table 14, Table 23 and Table 30.

### Claim 6: tools normalization

**Mechanism** (`evals/paired.py:597-616`). On the first **main** request of each (model, effort-if-Sonnet) key, `tokens = min(write, max(0, min(32100, read+write) − read))` moves from the write rate to the read rate. A session that already read ≥ 32,100 gets 0.

- Shipped sessions get two repriced requests when they used both models (80/140 Fable, 79/140 Opus). Every other session gets one.
- In practice no first request read ≥ 32,100. Warm first requests read exactly 32,029 (Fable/Opus) or 32,033 (Sonnet), so about 71 or 67 tokens are repriced on *every* warm session. This is the allowance overshooting the actual prefix (measured by preflight at "~32k").

**Reviewer's $260.70.** 32,100 × (12.50 − 0.25) / 1e6 × 448 Fable-host sessions = 176.165; 32,100 × 4.80 / 1e6 × 448 Opus-host = 69.028; 32,100 × 3.45 / 1e6 × 140 Sonnet = 15.504. The sum is **260.70**. It assumes every session wrote the whole prefix, which is not what happened. Note that the reviewer prices sticky and shipped at the host rate, although most of their first requests were Sonnet.

**Actual distribution** (`sessions.jsonl`, `requests.jsonl.gz`):

| host/arm | sessions | cold first-requests (read < 20k, 32,100 repriced) | $ cold | warm reqs | $ warm | total $ |
|---|---:|---:|---:|---:|---:|---:|
| Fable anchor | 140 | **16** | 6.292 | 124 | 0.108 | 6.399 |
| Fable aa | 28 | 1 | 0.393 | 27 | 0.023 | 0.417 |
| Fable shipped | 140 | 7 | 1.623 | 213 | 0.101 | 1.724 |
| Fable sticky | 140 | 2 | 0.221 | 138 | 0.042 | 0.264 |
| Opus anchor | 140 | **22** | 3.390 | 118 | 0.040 | 3.430 |
| Opus aa | 28 | 1 | 0.154 | 27 | 0.009 | 0.163 |
| Opus shipped | 140 | 3 | 0.376 | 216 | 0.059 | 0.434 |
| Opus sticky | 140 | 3 | 0.376 | 137 | 0.033 | 0.409 |
| Sonnet control | 140 | **19** | 2.104 | 121 | 0.028 | 2.132 |
| **total** | 1,036 | 74 | 14.93 | 1,121 | 0.44 | **15.372** (= `summary.json`) |

**Reading.**
- The adjustment is arm-asymmetric because cold prefix writes fell mostly on anchors (and on Sonnet in the Opus wave). That is consistent with the anchor usually starting first in its wave, so it found the shared tools entry cold more often.
- Normalization removes that start-order penalty. Its effect on ratios is upward, i.e. against routing.
  - Test, pair reading, raw → normalized: Fable sticky 0.5523 → 0.5576, shipped 0.6252 → 0.6289, sonnet 0.5737 → 0.5772; Opus sticky 1.2338 → 1.2492, shipped 1.3582 → 1.3796, sonnet 1.4209 → 1.4332.
  - All-70 A/A: Fable 0.9667 → 0.9681, Opus 1.0468 → 1.0492.
- It cannot create the Fable savings. It slightly strengthens H2, but H2 holds on the raw basis too (App B "Raw cost basis", p. 42).

### Claim 7: composition weighting

Computed from Table 20 means, with p = 124/140 sticky sessions on Sonnet per host:

| | predicted | actual | difference |
|---|---:|---:|---:|
| Fable requests | 0.8857 × 57.37 + 0.1143 × 46.02 = 56.07 | 50.19 | −10.5 % |
| Opus requests | 0.8857 × 57.37 + 0.1143 × 36.39 = 54.97 | 48.50 | −11.8 % |
| Opus cost | 0.8857 × 3.2214 + 0.1143 × 2.1254 = 3.096 | 2.615 | −15.6 % (−15.7 % from rounded table values) |
| Fable cost | 3.460 | 3.331 | −3.7 % |

The Fable cost gap is smaller because sticky's background requests are billed on the **host** model: $0.158 per session on Fable vs $0.051 for the control (see claim 11).

Matched to the scenario-rep partner (the control if the sticky judge chose Sonnet, the anchor if it chose the host): requests 0.894× (Fable) / 0.895× (Opus), cost 0.941× / 0.870×.

### Claim 8: turn rows

- `turns.jsonl` has 11,588 rows.
- The killed session `py-forth-r2-opus-aa` contributes 10 rows (cost_valid = false).
- Skipped turns: `mistune-escape-r1-any-sonnet` turn 8, `py-forth-r2-opus-aa` turn 10, and `go-dominoes-r1-fable-sticky` turn 13.
- `build_assets.py:1141` keeps cost-valid, non-skipped turns: 11,588 − 10 − 2 = **11,576** (`\PerTurnN`, `generated/numbers.tex:555`).
- The two extra skips are both `agent_fail` sessions that stayed cost-valid. Each was billed for one fewer turn than its partner, which is a negligible pair bias but undocumented: `FAILURES.md` covers only the kill.

### Claim 9: empty headings

Physical PDF page 34 (printed p. 33) has, in order: "11.3 … 11.4 Scenario by scenario / 11.5 The noise floor in detail / 11.6 Quality by scenario family / Table 23". Fig 22 and Fig 23 are on printed p. 34, Fig 24 and Fig 25 on p. 35, and on p. 36 Fig 26 comes *before* "11.7 Requests per session and session length", followed directly by "Part IV". The tex for those subsections contains a figure only (`07b-more.tex:68-79`, `81-91`, `103-123`).

### Claim 10: launch-offset regression

- `scheduled_start` is null on all 1,036 rows (DATA-DICTIONARY: "Reserved for offset-start experiments"). The offset is therefore `actual_start − min(actual_start in wave)`.
- Mean offsets: Fable anchor 1.02 s, aa 2.57 s, shipped 2.59 s, sticky 3.39 s. Opus anchor 1.32 s, aa 2.22 s, shipped 2.71 s, sticky 4.26 s, sonnet 5.06 s.
- The intended launch order is anchor, aa, shipped, sticky, sonnet (`campaign/run.log`), but the observed start order varies. The most common orders are A-Sh-St (51) and A-Sh-St-Son (22); Sh-A-St appears 20 times.
- OLS of y = ln(cost_arm / cost_anchor) on Δ = offset_arm − offset_anchor, with a scenario-cluster bootstrap (B = 4,000 for A/A, 2,000 otherwise):

| model | host | n | slope per second | 95 % CI | intercept → ratio at Δ = 0 |
|---|---|---:|---:|---|---|
| A/A only | Fable | 28 | −0.0014 | [−0.0114, +0.0071] | 0.970 |
| A/A only | Opus | 27 | −0.0064 | [−0.0181, +0.0083] | 1.054 |
| all same-wave arms + arm FE | Fable | 308 | +0.0115 | [−0.0027, +0.0221] | — |
| all same-wave arms + arm FE | Opus | 447 | −0.0123 | [−0.0260, +0.0009] | — |
| sticky only | Fable / Opus | 140 / 140 | +0.0192 / −0.0150 | [−0.0004, +0.0389] / [−0.0315, +0.0016] | — |

- No slope is distinguishable from 0, and the signs disagree across hosts.
- The Opus A/A bias stays put at Δ = 0, and it is larger when aa started *first* (+0.064, n = 8) than when the anchor did (+0.041, n = 19).
- Opus aa made 3.8 % more requests than its anchor (GM), and the A/A log ratio correlates with the log request ratio (r = 0.49; Fable 0.68). That points to behavioural run-to-run variation, not start order.

### Claim 11: sticky (chose Sonnet) vs plain Sonnet control

Setup:
- The sticky session is paired with the Sonnet control on the same scenario and rep (the control is host-independent and runs once per scenario-rep, in the Opus wave).
- The statistic is the GM of ln(cost_sticky / cost_control), tools-normalized.
- CIs use `paired_model.cluster_boot_mean` (scenarios, then reps), B = 10,000, seed 20261002.
- All 248 sticky-cheap sessions and their controls are cost-valid.

| | Fable all | Fable test | Opus all | Opus test |
|---|---|---|---|---|
| sessions / scenarios | 124 / 62 | 44 / 22 | 124 / 63 | 43 / 22 |
| **cost ratio sticky/control (GM)** | **0.861 [0.830, 0.893]** | **0.872 [0.828, 0.920]** | **0.826 [0.795, 0.856]** | **0.824 [0.768, 0.878]** |
| main-loop only (background excluded) | 0.820 [0.789, 0.851] | 0.830 [0.783, 0.879] | 0.820 [0.788, 0.851] | 0.818 [0.761, 0.873] |
| ratio of mean $ | 0.839 | 0.851 | 0.812 | 0.812 |
| mean $ sticky / control | 2.545 / 3.035 | 2.516 / 2.956 | 2.466 / 3.037 | 2.372 / 2.921 |
| background $ per session sticky / control | 0.158 / 0.051 | 0.155 / 0.049 | 0.060 / 0.051 | 0.057 / 0.049 |
| requests per session sticky / control | 48.8 / 55.3 | 50.3 / 55.4 | 48.4 / 55.2 | 48.5 / 54.9 |
| requests GM ratio | 0.894 [0.863, 0.926] | 0.916 [0.863, 0.974] | 0.885 [0.854, 0.917] | 0.891 [0.837, 0.949] |
| sticky had fewer requests | 92/124 | 33/44 | 93/124 | 31/43 |
| output tokens per session | 18.3k / 26.8k | 17.2k / 26.2k | 18.8k / 26.9k | 17.4k / 25.9k |
| cache-read tokens per session | 4.45M / 5.53M | 4.49M / 5.39M | 4.44M / 5.52M | 4.32M / 5.32M |
| execution time GM ratio | 0.730 | 0.734 | 0.736 | 0.718 |
| ΔTP sticky − control | −0.012 [−0.033, +0.008] | −0.008 [−0.050, +0.040] | −0.012 [−0.037, +0.016] | −0.018 [−0.071, +0.034] |
| final pass sticky / control | 0.935 / 0.944 | 1.000 / 0.977 | 0.952 / 0.944 | 0.977 / 0.977 |

**Interpretation.** When sticky chose Sonnet it was **14–18 % cheaper than plain Sonnet** on the same scenario and rep. It made about 11 % fewer main-loop requests, about 31 % fewer output tokens, about 20 % fewer cache reads, and finished about 27 % faster. There is no detectable quality difference.

The request rows show why. All 12,062 sticky-cheap main requests carry `effort = "medium"`. All 8,032 control main requests carry `effort = null`. The control cell `plain-sonnet` sets no effort (`cells.yaml:104-110`), which the design doc describes as "no effort set, which means high" (`docs/design/parallel-measurement-mode.md:30`). `orch-pin-cheap(-opus)` (`cells.yaml:781-799`) uses the composed bundle with `effort_profile: all_phase` and the shipped default start effort. Shipped's Sonnet requests are medium as well (5,904 and 5,994 requests).

It is **not** the read shortcut. The pin cells use `backend: none` (no judge), and the sticky-cheap receipts contain no difficulty-judged or scored events, only routed / effort_routed / model_routed, one per request. The bundle's composed context may contribute, but this data cannot separate it from effort.

On Fable a cross-wave timing confound is also present: the control ran in the Opus wave, a median 5.7 h away from the Fable sessions. The Opus-host result (same wave) is about the same size, so timing is not the driver.

**Implication for §12** ("the sticky arm is mostly plain Sonnet"; "plain Sonnet … cost about the same"). The sticky arm is mostly *medium-effort Sonnet inside the bundle*, which is cheaper than the plain-Sonnet control. On Fable the near-equality 0.558 vs 0.577 comes from two effects cancelling:
- sticky-cheap 0.504 vs the control's 0.586 on the same scenarios;
- sticky-host sessions at 1.255× anchor (n = 16; Opus 1.357×), which are dearer than plain host.

A fair "just use Sonnet" control would set the same effort.
