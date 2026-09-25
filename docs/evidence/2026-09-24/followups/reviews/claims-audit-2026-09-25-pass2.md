Verdict: CORRECTIONS NEEDED

# Independent claims audit, second pass: fast-decisions README, report, results, design doc

Audited: `~/dev/amplifier-bundle-fast-decisions` @ `main` `caaf8a5`. The working tree was clean before and after; I changed nothing in the repo.
Recompute scripts: `/tmp/ampup/claims-audit2/work/s1.py` (S1 ratios, sign test, bootstrap) and `swe.py` (SWE counts and ratios). Judge AUCs, MANIFEST hashes, timestamps and code checks were run inline.

## Summary

The arithmetic mostly holds. I recomputed every S1 ratio (the 2026-09-24 and 2026-09-25 cells), every SWE resolved count and ratio, and every judge AUC and latency, and they match the published figures to the stated precision. There are four exceptions: one inverted ratio, one rounding error, one chart that doesn't match its stored per-step values, and one decision count taken from an evidence file that double-counts. Both `MANIFEST.json` files hash-verify in full (542 + 357 files, 0 mismatches, 0 missing). The test suite passes: `PYTHONPATH=src <amplifier python> -m unittest discover -s tests` ran 1067 tests, OK.

Where the documents go wrong:

1. **An inverted ratio.** RESULTS says "Opus 5.5 plain was ... 1.17x on the holdout" against plain Sonnet. The stored runs give 0.854x: Opus was *faster* than Sonnet on the holdout, and 1.17 is 1/0.854.
2. **Wrong run-order and timing wording.** "Two dev batches 1.5 h apart" is wrong. Batch 1 ran 02:53–03:16 UTC and batch 2 ran 03:17–03:28 UTC, so batch 2 started one minute after batch 1 ended. "We ran every decision-maker twice, a day apart" is also wrong: the first judge runs were 16:20–19:57 EDT on 24 Sep and the re-tests 22:53–00:05, roughly 4–7 hours later.
3. **The preregistration's own timestamp contradicts the runs.** `PREREGISTRATION.md` says "Written 2026-09-25 03:35 UTC, BEFORE the holdout pass is launched", but the first holdout run started at 03:29:22 UTC (stored `result.json`). The local original file's birth time is 03:29:08 UTC, 14 s before launch, and its modification time equals its birth time. So the order was probably right and the stated time is wrong. However, the birth time is local-only, and the prereg was committed together with the results (`c58c52f`). From the committed record alone, "written before the run" cannot be verified, and the one time it does state is contradicted.
4. **Figure 7's "Deciding once" per-step bars don't match the stored values** that the caption now cites. The stored values are 36.7/0.7/0.8/1.4/0.9/0.7/0.2 k tokens, 7 steps; the chart plots 36.7/0.3/1.7/1.5/1.1, 5 steps. The total (about 31k words) matches. "A single rebuild re-sent up to about 60,000 words" still has no stored record: the largest stored single write is 39,478 tokens, about 30k words.
5. **Claims still without stored evidence:**
   - RESULTS: "provider-reported cost of every routed call matched Sonnet 5 pricing (13 of 13), and every host call matched Opus 5.5 pricing (283 of 283)". No record of this anywhere.
   - RESULTS: "Jev routed an easy turn ... in ... the TUI". The TUI record has no judge field. This is the first audit's S6, which was not applied.
   - Report: the memory add-on "no longer hold[s] up the start of a session". `extras.json` itself says "session-start blocking ... NOT independently verified".
   - Report: "an independent Amplifier session re-computed every number here". The first audit ran on `52e0d29`, before the 2026-09-25 re-validation existed, and the new numbers had not been recomputed before publication. Item 1 above shows the gap.
6. **Rounding.** The Fable holdout CI upper bound is stored as 0.4984 and published as "0.49" (it should be 0.50) in README, RESULTS, ORCH and the report (twice).
7. **Smaller issues:**
   - "0.56× / 0.48× (Fable) ... in two batches" gives only batch 1. The two-batch range is 0.56–0.57× / 0.46–0.48×.
   - The Opus holdout failed two criteria (time *and* sign test), not only "the time criterion".
   - ORCH's "Measured trade-off" paragraph presents the earlier escalation build's 0.61×/0.50× as "Jev deciding".
   - The 2026-09-25 evidence README says home paths are shown as `~`, but three difficulty files carry `~/...`.
   - The report's "96 decisions, zero mid-request switches" comes from `mechanism-summary.json`, which counts every event twice. The per-rep `comparisons/*.json` give 48 decisions for the 48 runs (one per run); the zero-switch finding stands.

The behavioral claims match the code on `main`, including the scope-gate and savings fixes from the first audit (section 2).

---

## 1. Claims table

VERIFIED = recomputed or checked against a file or the code, and it matches. MISMATCH = the source says something different. UNSUPPORTED = no stored record. STALE = true for an earlier build or state. MISLEADING = the number is true but the framing is wrong or incomplete.

S1 method (as specified in the brief): geometric mean over tasks of (median candidate / median anchor) on `exec_time_ms` and `cost_usd`, excluding `infrastructure_failure` runs. Sign test: two-sided binomial. CI: bootstrap over tasks (mine: 5000 resamples, seed 0; the pipeline's is stored in `results.json`).

### 1a. 2026-09-25 re-validation (new claims)

| # | Claim | Location | Source | Recomputed | Verdict |
|---|---|---|---|---|---|
| 1 | Fable holdout 0.42× time, 0.50× cost | README table; report hero, At a glance, Fit, Rigor; RESULTS; ORCH | prereg2-s1-holdout | 0.419 / 0.499 | VERIFIED |
| 2 | 95% interval 0.35–0.49 | README; report ×2; RESULTS; ORCH | results.json ci95 [0.3539, 0.4984]; my bootstrap [0.35, 0.50] | upper bound rounds to 0.50 | **MISMATCH** (rounding) |
| 3 | Faster on 8/8, sign test p = 0.008 / 0.0078 | README; report; RESULTS | per-task ratios | 8/8, p = 0.0078 | VERIFIED |
| 4 | "met all 6 criteria"; "confirmed" | README; report; RESULTS; ORCH | PREREGISTRATION.md criteria; gates.json (all green, 3 reps); results.json verdict `confirmed`; 24/24 vs 24/24 | 6/6 pass | VERIFIED |
| 5 | Criteria "written down before the run" / "Before starting it" | README; report Rigor; PREREGISTRATION.md ("03:35 UTC, BEFORE the holdout pass is launched") | first holdout `started_at` 03:29:22 UTC; local file birth time 03:29:08 UTC (not committed); prereg committed with results in `c58c52f` | stated time is 6 min *after* launch; local birth time is 14 s *before* | **MISMATCH** (stated timestamp) / **UNSUPPORTED** from the committed record |
| 6 | Pipeline cost 0.54× | RESULTS; evidence README | results.json `cost_ratio` 0.5412 | 0.54 | VERIFIED |
| 7 | Opus holdout 1.01× [0.86–1.17], 0.98×, 2/8, p = 0.29, no effect | README; report; RESULTS; ORCH | prereg2 | 1.007 [0.861, 1.173]; 0.978; 2/8; p = 0.289; verdict `no-effect` | VERIFIED |
| 8 | "the Opus result failed the time criterion" / "the time criterion failed" | README; report Rigor | criteria 2 and 3 | time 1.01 > 0.90 **and** p 0.29 > 0.05 | MISLEADING (incomplete: two criteria failed) |
| 9 | Dev batch 1: Fable 0.559×/0.484×, 11/12; Opus 0.825×/0.895×, 10/12 | RESULTS; report; evidence README | reval-s1-dev | 0.559/0.484, 11/12; 0.825/0.895, 10/12 | VERIFIED |
| 10 | Dev batch 2: Fable 0.574×/0.460×, 10/12; Opus 0.757×/0.822×, 9/12 | RESULTS; report; NOTE.md | reval-s1-dev-batch2 | 0.574/0.460, 10/12; 0.757/0.822, 9/12 | VERIFIED |
| 11 | "On the 12 tuning tasks the default measured 0.56× / 0.48× (Fable) and 0.76–0.83× / 0.82–0.90× (Opus) in two batches" | README; report At-a-glance note | #9, #10 | Fable two-batch range is 0.56–0.57× / 0.46–0.48× | MISLEADING (Fable gives batch 1 only; the Fit table has it right) |
| 12 | "Opus setup looked 17–24% faster" on tuning tasks | report Fit | #9, #10 | 17.5% / 24.3% | VERIFIED |
| 13 | vs plain-sonnet on holdout: 0.91× [0.77–1.08] time, 1.29× cost | README; report; RESULTS | prereg2 | 0.907 (pipeline [0.765, 1.075]); cost 1.285 (pipeline estimator 1.39) | VERIFIED (the brief's method; the pipeline cost is 1.39×, not disclosed) |
| 14 | "Opus 5.5 plain was as fast as plain Sonnet on dev (1.00x) and **1.17x on the holdout**" | RESULTS update | plain-opus vs plain-sonnet | dev 0.997; batch 2 1.179; **holdout 0.854** (Opus faster on 5/8) | **MISMATCH** (inverted: 1/0.854 = 1.17) |
| 15 | "Claude Opus 5.5 was about as fast and as cheap as Sonnet on these tasks" | README; report Fit | plain-opus vs plain-sonnet | time 1.00 / 1.18 / 0.85; cost 1.06 / 1.14 / 1.03 | VERIFIED (loosely) |
| 16 | "Every run passed in every cell" | RESULTS update | outcome_passed | 300/300 scored runs passed; 1 infrastructure failure (plain-opus dev r2, retried as a2) excluded | VERIFIED (retry not mentioned) |
| 17 | "Jev judged every turn (no rule fallback) and no turn escalated" | RESULTS update | comparisons/orch-default*.json in all three batches: `runs_evaluated` = decisions (one per run), reasons only `judge_cheap` / `judge_strong`, `fallback_count: 0`, `model_routed_escalations_by_reason: {}` | as stated | VERIFIED |
| 18 | "96 decisions, zero mid-request switches" in the first re-test batch | report "Deciding once" | comparisons/orch-default*-r{1,2}.json `mechanism`: 12 runs and 12 decisions per rep (Fable 18 cheap + 6 strong, Opus 19 + 5), 0 fallbacks, 97 + 92 slow calls; mechanism-summary.json reports exactly double (36+12, 38+10; 194 and 184 calls) for the same 48 runs | **48** decisions, 0 switches | **MISMATCH** (96 comes from mechanism-summary.json, which double-counts every event; that evidence file is itself wrong) |
| 19 | "Jev sent about three in four requests to the faster model" | report Results | comparisons `mechanism` | Fable dev 18/24 turns cheap (75%), 27/36 over both batches; holdout 18/24 | VERIFIED (ratio unaffected by the double count) |
| 20 | Candidate commit `52e0d29` for all S1 runs | RESULTS; evidence README | three manifest.json `requested_sha` | 52e0d29… in all three | VERIFIED |
| 21 | Batch 2 "launched as a reversed-order check ... ran in declared order" | NOTE.md; evidence README | batch-2 argv reversed; `started_at` order plain → plain-sonnet → orch-default → plain-opus → orch-default-opus | as stated | VERIFIED |
| 22 | "the two dev batches **1.5 h apart**" / "Two batches **an hour and a half apart**" / "a replicate one and a half hours later" | RESULTS update; report Rigor; NOTE.md | `started_at` batch 1 02:53:30–03:16:45; batch 2 03:17:44–03:28:36 UTC | batch 2 started 1 min after batch 1 ended, 24 min after it started | **MISMATCH** |
| 23 | Cells ran "back to back (~10 min apart)", "about ten minutes apart" | RESULTS; report Rigor; evidence README | cell start gaps: dev b1 ~10.5 min, b2 ~5 min, holdout ~7.5 min | 5–11 min | VERIFIED (approximate) |
| 24 | "ran back to back within about fifteen minutes" | report At a glance | anchor start → candidate end: dev 15 min, holdout Fable 17 min, Opus 8–9 min | ≈15 min | VERIFIED (approximate) |
| 25 | Prereg prediction "time ~0.57, cost ~0.47" from two dev batches | PREREGISTRATION.md | #9, #10 | 0.559/0.574; 0.484/0.460 | VERIFIED |
| 26 | "About 660 recorded coding runs" | report hero | 192 S1 (09-24) + 165 SWE + 301 S1 (09-25, incl. 1 infra) | 658 | VERIFIED |
| 27 | "3 test courses · 9 decision-makers" | report hero | S1, SWE, judge probe; 9 judges | as stated | VERIFIED |

### 1b. 2026-09-24 S1 (built-in rule, earlier builds)

| # | Claim | Location | Recomputed | Verdict |
|---|---|---|---|---|
| 28 | Rule 0.55× / 0.38× on 12 tuning tasks | README; RESULTS; report DATA | 0.545 / 0.381 | VERIFIED |
| 29 | Rule holdout 0.61× [0.47–0.78] / 0.40×; 7/8; p = 0.07; 5 of 6 | README; RESULTS; report | 0.610 / 0.395; 7/8; p = 0.070; stored CI [0.47, 0.78] | VERIFIED |
| 30 | One task marginally slower (8.79 s vs 8.73 s) | RESULTS | answer_default_port 1.01 | VERIFIED |
| 31 | Earlier Jev build 0.61× / 0.50×, 3 of 12 to the host | README; RESULTS; ORCH; report DATA | 0.608 / 0.500; 3 of 12 runs served on Fable | VERIFIED; **STALE** framing in ORCH (#80) |
| 32 | plain-sonnet 0.59× / 0.42× (screen batch) | RESULTS | 0.589 / 0.420 | VERIFIED |
| 33 | "Standard Amplifier, cheaper model" 0.58× / 0.38×, "same batch as the current default" | report DATA | reval-s1-dev: 0.579 / 0.382 | VERIFIED |
| 34 | First version 0.48× / 0.77× | RESULTS; report DATA | 0.479 / 0.767 | VERIFIED |
| 35 | Effort by phase, same model: 0.77× / 1.09× | RESULTS; report DATA | 0.773 / 1.090 | VERIFIED (label fixed after the first audit) |
| 36 | Fig 2 "rows come from four separate batches" | report | reval-s1-dev, screen, router, router-rules | 4 | VERIFIED |
| 37 | "Jev judges difficulty better; the rule was cheaper on a set of all-easy tasks because it kept fewer requests on the usual model" | README; ORCH | rule 12/12 on Sonnet vs Jev 3/12 on host (different batches) | VERIFIED (cross-batch) |

### 1c. SWE-bench Verified (`grading/*.json` `resolved_instances`; ratios matched on arm + instance + rep against plain)

| # | Claim | Location | Recomputed | Verdict |
|---|---|---|---|---|
| 38 | Shipped default 13/20 vs 14/20; 1.00× / 0.98× | README; report; RESULTS; ORCH | 7+6 vs 7+7; 1.000 / 0.985; 263/263 calls served on Fable | VERIFIED. Measured on candidate `7445966` (rule backend, 6-request escalation, cwd scope gate); the gate returns before judge and escalation, so the routing is identical on this data |
| 39 | "same setup as standard" / "Same model and settings" / "exactly the standard setup" | README; report | same model and effort; the fd arm still mounts the wrapper, hook and `fast_workspace` tool | MISLEADING (minor; first audit #19, not addressed) |
| 40 | Jev router 3 reps 19/30 vs 23/30; 0.86× / 0.91× | README; RESULTS; ORCH; report | 7+6+6 vs 7+8+8; 30 pairs 0.855 / 0.912 | VERIFIED |
| 41 | django-11532 3/3 → 1/3 | RESULTS; report | plain 3, Jev 1 | VERIFIED |
| 42 | Local qwen:latest router 6/10 vs 7/10; 0.75× / 0.89× | RESULTS | 6 vs 7; 0.751 / 0.885 | VERIFIED |
| 43 | plain-sonnet 5/10; 1.66×; 0.93× per task; 1.42× total spend | RESULTS; report | 1.663 / 0.926 / 1.42 | VERIFIED |
| 44 | First version 8/10 vs 7/10; 1.21× / 1.40× | RESULTS; report; ORCH | 1.205 / 1.395 | VERIFIED |
| 45 | Strong + phase effort 12/20; 0.81× / 0.87×; "saved 19%" | RESULTS; report | 6+6; 0.811 / 0.869 | VERIFIED |
| 46 | pylint-7080: lower effort 0/2, plain 2/2, default 1/2 | RESULTS; report | 0 / 2 / 1 | VERIFIED |
| 47 | Plain fixed 77% (Jev batch) / 70%; DATA 70/65/60/63/80/50 | report | 23/30, 7/10; 14/20, 13/20, 12/20, 19/30, 8/10, 5/10 | VERIFIED |
| 48 | Provider wait 80–84% (RESULTS) / 80–85% (report), median 84% over 165 runs | RESULTS; report | median 0.836; IQR 0.78–0.87; n = 165 | VERIFIED |
| 49 | ~12 s start-up and exit per run (median 12.5 s) | RESULTS; report | 12.53 s | VERIFIED |
| 50 | "one task paid for about 175,000 words of rebuilds" | report | xarray-4687 first version: 235,461 cache-write tokens × 0.75 = 176k | VERIFIED as a total of all cache writes (includes the first write and ordinary increments: minor MISLEADING) |

### 1d. Judges (AUC over `source == swe-verified` rows, 45 complex / 45 simple)

| # | Claim | Location | Recomputed (09-24 / 09-25) | Verdict |
|---|---|---|---|---|
| 51 | Jev 83%, ~0.14–0.16 s | README; report; RESULTS; ORCH | 0.827 / 0.829; p50 155 / 138 ms | VERIFIED |
| 52 | Rule 60%; "no rule based on wording beat 60%"; 410 held-out | all | 0.599 / 0.599; surface-feature-auc.json (first audit) | VERIFIED |
| 53 | qwen:latest 85%, ~2.2–2.5 s | README; report; RESULTS | 0.848 / 0.847; p50 (all) 2.45 / 2.22 s | VERIFIED |
| 54 | qwen:latest "27.4B parameters, 29 GB" / "27 billion" / "27B" | README; RESULTS; report text + DATA | extras.json `qwen_latest_ollama_show` (27.4B), `qwen_latest_size_gb_from_ollama_list: 29` | VERIFIED (the first audit's R8/S4/H7 gap is now backed) |
| 55 | Qwen3 8B 72%, ~0.36 s | README; RESULTS; report DATA | 0.721 / 0.721; 364 / 316 ms | VERIFIED |
| 56 | Qwen3 4B 74% / 0.26 s | RESULTS; report DATA | 0.737 / 0.737; 259 / 221 ms | VERIFIED |
| 57 | GLM 0.75 (RESULTS) / 76, "75% and 76% in two runs" (report) | RESULTS; report | 0.7546 / 0.7570 | VERIFIED |
| 58 | Llama 3.1 8B 0.70, "70% and 69%" | RESULTS; report | 0.696 / 0.694 | VERIFIED |
| 59 | "Mid-size local models land around 69–76%" | report | 0.694–0.757 | VERIFIED |
| 60 | qwen3:0.6b 0.50, 0.072 s | RESULTS; ORCH; report | 0.503 / 0.503; 72 / 66 ms | VERIFIED |
| 61 | Hosted Qwen3.8-27B 85%; median ~0.6 s (0.59–0.63); 18–25% took 5–24 s "in two runs" | README; report HOSTED | 09-24 keepalive 0.848, p50 634 ms, 28/110 (25%) >5 s, max 21.6 s; 09-25 0.847, 590 ms, 20/110 (18%), max 24.0 s | VERIFIED. A third run (09-24 non-keepalive: p50 1.22 s, 20%) is not mentioned: minor |
| 62 | RESULTS hosted row: median 0.63 s; 40–90 ms cached; 1 in 4 took 5–22 s | RESULTS | 09-24 keepalive: 8 calls 41–90 ms; 28/110 | VERIFIED |
| 63 | "Re-run on 2026-09-25; figures reproduced" / "each landed within a point or two" | README; report; evidence README | all 9 judges within 0.4 points (AUC) | VERIFIED |
| 64 | "We ran every decision-maker twice, **a day apart**" | report | first runs: local file times 16:20–19:57 EDT 24 Sep; re-tests (`reval-judges/`) 22:53–00:05 EDT | **MISMATCH** (about 4–7 h apart) |
| 65 | "Picks the harder issue" framing now states that the middle band is excluded | README; report | as stated | VERIFIED (first audit R6/H7 applied) |

### 1e. Follow-ups, start-up, add-ons, upstream

| # | Claim | Location | Source | Verdict |
|---|---|---|---|---|
| 66 | Sonnet about 1.3× faster than Opus (113 vs 88 tok/s, 4 calls each) | RESULTS | followups.json | VERIFIED (n = 4) |
| 67 | Prices vs Sonnet: Fable 3.3/3.3/0.8, Opus 1.3/1.3/0.7 | report Fit; RESULTS | followups.json + `savings.DEFAULT_RATES` | VERIFIED |
| 68 | Four add-ons merged: memory #9, behavioral-plasticity #2, design-loop #3, preceptor #7 | RESULTS; report | extras.json `addon_prs` (merge SHAs, times); `gh pr view` today: all 4 MERGED | VERIFIED |
| 69 | Each reviewed by a separate Amplifier session before merging | report; RESULTS | reviews/addon-*-review.md review pre-merge branches; all "SIGN OFF WITH CHANGES" | VERIFIED (whether the requested changes landed is not recorded) |
| 70 | 2,153 → 1,146 tokens; ~2,900 → 1,350; search 3.0 → 1.0 s | report | extras.json `addon_pr_numbers_quoted` | VERIFIED (author's figures, review-checked) |
| 71 | Memory add-on "no longer hold[s] up the start of a session" | report Start-up | extras.json: "session-start blocking of 7.8-9.2 s NOT independently verified" | **UNSUPPORTED** |
| 72 | Trivial request 18.5 s with vs 17.5 s without (2 runs each) | report; RESULTS | followups.json [18.6, 18.4] / [18.3, 16.6] | VERIFIED (n = 2) |
| 73 | Fig 8: 8.3 s (2 calls), 5.3 s, 2.9 s; unprofiled launch 2.6–3.2 s; 24 add-ons | report DATA + caption | startup/startup-profile.json | VERIFIED. The 2.9 s bar is the mean of two *unprofiled* runs inside a chart titled "one profiled request" (disclosed in the caption) |
| 74 | "A 2026-09-25 profile ... still shows 8.3 s in two calls" | RESULTS | startup-profile.json 8.25 | VERIFIED |
| 75 | 59 s / 114k tokens / 13 s app-free / model call ~2 s | RESULTS | install-measurements-2026-09-24.md: 59.3 s, 114k, 12.9 s, ~2 s | VERIFIED (one run each) |
| 76 | hooks-deprecation 5.8 s → 0.002 s; "4–7 s ... becomes 2 ms"; 72 + 6 tests; independent review stored | RESULTS; report Flavors | review: main 5.88–7.39 s → 0.002–0.003 s; review verified **72 + 4 new** (76 passed) at `ff56431`; "72 + 6" is the PR body / patch doc (78 passed) | VERIFIED (timings); tests MISLEADING (minor: the stored review checked an earlier revision) |
| 77 | PR #413 open, optional suggestion | RESULTS; report | `gh pr view 413`: OPEN, "Optional: …" | VERIFIED |
| 78 | Surfaces: "Jev routed an easy turn to Sonnet in the CLI, `amplifier-runtime serve` and the TUI (core 1.6.0)" | RESULTS | followups.json: CLI and runtime record `judge: jev`; TUI record has **no judge field** | **UNSUPPORTED** for "Jev" in the TUI (first audit S6 not applied) |
| 79 | "provider-reported cost of every routed call matched Sonnet 5 pricing (13 of 13), and every host call matched Opus 5.5 pricing (283 of 283)" | RESULTS | no stored record anywhere in docs/evidence | **UNSUPPORTED** (new claim) |
| 80 | ORCH "Measured trade-off": "Jev deciding ran at 0.61x / 0.50x against 0.55x / 0.38x ... because Jev sent 3 of 12 tasks to the host" | ORCH Who judges | router-s1-dev (escalation build) | **STALE**: the current decide-once default measured 0.56×/0.48× and 0.57×/0.46× (sent 6 of 24 and 3 of 12 Fable turns to the host) |
| 81 | In-session model pick wins (`user_model_strong`), verified in the terminal app | README; report | followups `tui_after_model_pick`; code `_user_selected_model` | VERIFIED (n = 1) |
| 82 | Fig 7 "Switching" lane 36.8/37.1/0.9/39.5/1.1 → ≈87k words | report | extras.json `fig7_per_request_cache_write_tokens` 36753/37100/938/39478/1060 | VERIFIED |
| 83 | Fig 7 "Deciding once" lane 36.7/0.3/1.7/1.5/1.1 (5 steps) "Per-step values are stored with the evidence" | report | stored: 36697/721/816/1438/895/676/211 (7 steps) | **MISMATCH** (bars; the ≈31k total matches) |
| 84 | "a single rebuild re-sent up to about 60,000 words" | report | largest stored single write 39,478 tokens (≈30k words) | **UNSUPPORTED** (first audit #58, still open) |
| 85 | "an independent Amplifier session re-computed every number here from the stored records" | report Rigor | first audit ran on `52e0d29`, before the 09-25 evidence existed; #14 shows the new numbers were not all recomputed | **UNSUPPORTED** as written (true only once this report is stored) |
| 86 | Evidence checksums | both evidence READMEs | 542/542 and 357/357 sha256 match; only `.DS_Store` (untracked) and MANIFEST itself unlisted | VERIFIED (full set) |
| 87 | 2026-09-25 evidence: "home paths shown as `~`" | evidence README | `difficulty-report-{hosted,jev-rules,local}.json` contain `"~/dev/afast-ev/difficulty-dataset.jsonl"` | **MISMATCH** |
| 88 | RouteLLM (LMSYS, ICLR 2025) | report | STUDY-DESIGN cites arXiv:2406.18665 | not re-checked online |

## 2. Behavioral claims vs code and config on `main`

| Behavior | Claim | Code / config | Verdict |
|---|---|---|---|
| Default judge | Jev | `behaviors/fast-decisions.yaml`: `backend: jev`, `allow_external_state: true`, `start_policy: judge`, `timeout_ms: 3000` | VERIFIED; no stale "rule is the default" text remains (report Fig 1 and DATA fixed) |
| Fallback | No key, or any Jev error or timeout → length rule; nothing leaves | `backends.py:313` raises `BackendUnavailable` before any request when `TYPESAFE_API_KEY` is missing; `_ask_judge_choice` catches every exception and the `asyncio.timeout_at` deadline → `None` → `decide_start_tier` keeps the rule tier (`complex_min_prompt_chars` 2000) | VERIFIED |
| Scope gate (300 files) | "When the session's folder holds more than 300 files (not counting .git, dependency, virtualenv and build folders) ... whatever the decision-maker says" | `orchestrator.py:224-237` `session_working_dir` = `session.working_dir` capability, else `os.getcwd()`; `:260-270` checks the gate **before** the judge; skip set `.git node_modules .venv venv __pycache__ .tox .mypy_cache .pytest_cache dist build .amplifier .swe`; counts stop at limit+1; memoized per process by `root\|limit` | VERIFIED (the first audit's cwd caveat is fixed). Unstated nuances: the count is cached for the process lifetime, so a folder that grows past 300 during a long `serve` process is not recounted; the gate is skipped when the user picked a model; firing through `session.working_dir` in runtime/Studio is covered by a unit test only, with no stored end-to-end record |
| Decide once | No mid-request switch except a provider error | config `max_requests_before_escalation: null`, `escalate_on_test_failure: false`, `escalate_on_provider_error: true`; `escalation_judge` defaults to `rules`, no `phase_judge`; tier is decided before effort (`orchestrator.py:721-725`); `by_tier.cheap: medium`, `strong: null` → provider default; host-pinned effort is respected (`effort.py:217`) | VERIFIED. On a provider error the failed call re-raises (`:1012-1021`); later calls in the turn go to the host, as README item 1 states |
| 2,500-character limit | First 2,500 chars of the latest message (helper instructions in sub-sessions) | `_DIFFICULTY_STATE_CHARS = 2500` applied to `_turn_user_text` (latest user message, `<system-reminder>` stripped) | VERIFIED |
| User model pick respected | An in-session pick keeps every request on it; a pre-session model is still routable | `_user_selected_model`: `ui.model_override` marker or a `default_model` change after first sight → `user_model_strong` for the turn | VERIFIED (evaluated once per turn, so a pick made mid-turn takes effect from the next turn) |
| Savings method | Cheap-turn tokens at host rates; provider `cost_usd` is the actual; after the first turn a cheap turn's cache writes are priced as host reads; a host turn right after a cheap turn is charged its rebuild; time scaled after 20+ samples (≥200 output tokens); negative allowed | `savings.py:131-186, 292` (`saved = counterfactual − actual − switch_penalty`), `MIN_RATE_SAMPLES = 20`, `MIN_RATE_OUTPUT = 200`; host from the recorded `host_model`, else `claude-fable-5-1` | VERIFIED (the first audit's over-statement is fixed in code and docs). Edge case: with no recorded `host_model`, Fable rates are assumed |
| What leaves the machine | Jev: first 2,500 chars; rule and local: nothing; log has no prompts or file contents | only `_ask_judge_choice` / Jev backends send, gated by `allow_external_state`; the hook uses `backend: deterministic`, `allow_external_state: false`; `afast rubric` and the smart tool send their inputs to Jev when invoked (the docs say so) | VERIFIED |
| Provider restriction | Faster model sent only to Anthropic providers | `provider_match: anthropic` → reason `provider_not_matched` otherwise | VERIFIED |
| Bundle description | — | now "decides once per turn whether it is easy ... or hard" | VERIFIED (first audit recommendation applied) |
| Test suite | README Development | 1067 tests, OK (with `PYTHONPATH=src` on the Amplifier tool Python; system Python 3.14 lacks the deps: 41 import errors, an environment issue, not a regression) | VERIFIED |

## 3. First-audit corrections: applied or superseded?

| ID | Status |
|---|---|
| R1–R3 | Superseded by the 09-25 re-validation (the headline is now the measured current default) |
| R4 | Applied, and the code was fixed to use the session folder |
| R5, R6, R7 | Applied |
| R8 | Applied; "27.4B, 29 GB" now backed by extras.json |
| R9 | Superseded: the savings code now accounts for cache state and the README describes it |
| H1, H2, H4, H5 | Superseded by new text and DATA (checked in 1a/1b) |
| H3, H8, H9 | Applied |
| H6 | Superseded by the re-test (0.757 → "75% and 76%") |
| H7 | Applied |
| H10 | **Not satisfied**: the caption now claims per-step values are stored, but the "Deciding once" bars don't match them (#83); the 60k single rebuild is still unsupported (#84) |
| H11 | Applied (startup-profile.json, reviews stored), except the new unsupported memory start-up claim (#71) |
| S1–S5, S7, S8 | Applied |
| S6 | **Half applied**: the add-on part is done; the surface bullet still says Jev routed in the TUI (#78) |
| O1–O6 | Applied or superseded. O3/O-"Who judges" trade-off paragraph left stale (#80) |
| Code: scope gate / bundle description | Applied |
| #19 "same setup as standard" | Not addressed (minor, #39) |

## 4. Required corrections (exact replacement text)

### docs/RESULTS-2026-09-24.md

**C1 (inverted ratio).** Replace
`Opus 5.5 plain was as fast as plain Sonnet on dev (1.00x) and 1.17x on the holdout.`
with
`Opus 5.5 plain took 1.00x plain Sonnet's time on dev (1.18x in the replicate batch) and 0.85x on the holdout.`

**C2 (batch timing).** Replace
`Cells ran in cells.yaml order, back to back (~10 min apart); the two dev batches 1.5 h apart agree, but within-batch order was not randomized.`
with
`Cells ran in cells.yaml order, back to back (5–11 min apart); the second dev batch started one minute after the first ended, and the two agree, but within-batch order was not randomized.`

**C3 (preregistration timestamp).** Replace `The preregistration is stored with the holdout.` with
`The preregistration is stored with the holdout. Its header says 03:35 UTC, which is wrong: the first holdout run started at 03:29:22 UTC, and the local original file was created at 03:29:08 UTC (filesystem time, not in the evidence). The document and the results were committed together, so the stored record alone does not prove the order.`

**C4 (CI rounding).** In the update table replace `**0.42x [0.35-0.49]**` with `**0.42x [0.35-0.50]**`.

**C5 (surfaces).** Replace
`Verified end to end, one prompt each: Jev routed an easy
  turn to Sonnet in the CLI, `amplifier-runtime serve` and the TUI (core 1.6.0); the provider-reported cost of
  every routed call matched Sonnet 5 pricing (13 of 13), and every host call matched Opus 5.5 pricing (283 of 283).`
with
`Verified end to end, one prompt each: Jev routed an easy turn to Sonnet in the CLI and `amplifier-runtime serve`; in the TUI (core 1.6.0) an easy turn went to Sonnet (the judge was not recorded).`
(Or keep the pricing sentence and first store its record, the per-call model and cost comparison, in `docs/evidence/`.)

**C6 (hooks-deprecation tests, minor).** Replace `(72 existing + 6 new tests passing on Python 3.11–3.13; independent review stored in` with
`(72 existing + 6 new tests passing on Python 3.11–3.13 per the PR; the stored independent review checked an earlier revision, 72 + 4, in`.

### README.md

**C7.** Replace `(faster on 8 of 8 tasks, sign test p = 0.008, 95% interval 0.35–0.49); the Opus result failed the time
criterion.` with `(faster on 8 of 8 tasks, sign test p = 0.008, 95% interval 0.35–0.50); the Opus result failed the time
and sign-test criteria.`

**C8.** Replace `On the 12 tuning tasks the default measured 0.56× / 0.48× (Fable) and 0.76–0.83× / 0.82–0.90× (Opus) in
two batches.` with `On the 12 tuning tasks the default measured 0.56–0.57× / 0.46–0.48× (Fable) and 0.76–0.83× / 0.82–0.90× (Opus) in
two batches.`

**C9.** Replace `Everyday setups ran back to back in the same batch;` with `Everyday setups ran back to back in the same batch, always in the same order;` (the run order is a stated limit in RESULTS and the evidence but missing here).

### docs/report/fast-decisions-report.html

**C10 (At a glance note).** Replace `on the twelve tuning tasks it measured 0.56× / 0.48×
  (Fable) and 0.76–0.83× / 0.82–0.90× (Opus) across two batches.` with `on the twelve tuning tasks it measured 0.56–0.57× / 0.46–0.48×
  (Fable) and 0.76–0.83× / 0.82–0.90× (Opus) across two batches.`

**C11 (Rigor).** Replace `Two batches an hour and a half apart gave the same result, but within-batch drift was not tested
  directly.` with `Two batches run back to back (the second started a minute after the first ended) gave the same result, but within-batch drift was not tested directly.`

**C12 (Rigor).** Replace `and an independent Amplifier session re-computed every number here from the stored
  records.` with `and independent Amplifier sessions re-computed the numbers from the stored records (audit records in docs/evidence/2026-09-24/followups/reviews/).`
(Store this report there, e.g. as `claims-audit-2026-09-25-pass2.md`, and regenerate the manifest.)

**C13 (confirmation paragraph).** Replace `time 0.42× (95% interval 0.35–0.49)` with `time 0.42× (95% interval 0.35–0.50)`, and `With Claude Opus
    5.5 the time criterion failed:` with `With Claude Opus
    5.5 the time and sign-test criteria failed:`. Replace `Before starting it, we wrote down six pass criteria` with
`Before starting it, we wrote down six pass criteria (the file's own timestamp, 03:35 UTC, is wrong; the file was created at 03:29:08 UTC, 14 seconds before the first run)`.

**C14 (judges).** Replace `We ran
  every decision-maker twice, a day apart; each landed within a point or two of its first result.` with `We ran
  every decision-maker twice, several hours apart; each landed within a point or two of its first result.`

**C15 (Fig 7 data).** In the Figure 7 script replace
`{ name: 'Deciding once', rows: [36.7, 0.3, 1.7, 1.5, 1.1], switches: [] } ];`
with
`{ name: 'Deciding once', rows: [36.7, 0.7, 0.8, 1.4, 0.9, 0.7, 0.2], switches: [] } ];`
and `colW = 128` with `colW = 100` (7 columns: 270 + 6×100 + 54 = 924 < 980). The computed total stays ≈31k words.

**C16 (single rebuild).** Replace `In our runs a single rebuild re-sent up to about 60,000 words, and one task paid for about 175,000 words
  of rebuilds in total.` with `In the SymPy run below a single rebuild re-sent about 30,000 words, and one task paid for about 175,000 words
  of memory writes in total.`

**C16b (decision count).** Replace `In the current default's
    first re-test batch: 96 decisions, zero mid-request switches.` with `In the current default's
    first re-test batch: 48 decisions, zero mid-request switches.`

**C17 (memory add-on).** Replace `and the memory add-on's look-ups got about three times faster (a search went
  from 3.0 to 1.0 seconds on a copy of a real memory store) and no longer hold up the start of a session.` with
`and the memory add-on's look-ups got about three times faster (a search went
  from 3.0 to 1.0 seconds on a copy of a real memory store); its change to stop holding up the start of a session was not independently measured.`

### docs/ORCHESTRATOR-PRIMARY.md

**C18 (stale trade-off).** Replace
`Measured trade-off to keep in mind: on the 12-task everyday screen (1 rep) Jev deciding ran at 0.61x
time / 0.50x cost against 0.55x / 0.38x for the length rule, because Jev sent 3 of 12 tasks to the host
model.`
with
`Measured trade-off to keep in mind: on the 12 everyday tuning tasks the current Jev default ran at 0.56–0.57x
time / 0.46–0.48x cost (two batches), against 0.55x / 0.38x for the length rule in an earlier batch, because Jev sent about one
turn in four to the host model while the rule kept all of them on Sonnet.`

**C19.** In the Evidence table replace `| 0.42x [0.35-0.49] |` with `| 0.42x [0.35-0.50] |`.

### Evidence (outside the four documents; they cite it)

**C20.** `docs/evidence/2026-09-25/s1/reval-s1-dev-batch2/NOTE.md`: replace `It is therefore a replicate one and a half hours later, not an
order check.` with `It is therefore a replicate run immediately after batch 1 (started 03:17:44 UTC, one minute after batch 1 ended), not an
order check.`

**C20b.** `docs/evidence/2026-09-25/s1/reval-s1-dev/mechanism-summary.json` counts every `difficulty_judged` / `model_routed` event twice: 48 judged turns and 194 / 184 calls for 24 runs per cell, against `comparisons/*.json` `mechanism` (12 decisions and 52 / 45 slow calls per rep). Regenerate it with each event counted once (expected: orch-default judge_cheap 18, judge_strong 6, start_model 80 + start_strong 17 = 97 calls; orch-default-opus 19 / 5, 92 calls), or delete it and point the evidence README at the comparisons. Then regenerate `MANIFEST.json`.

**C21.** `docs/evidence/2026-09-25/README.md`: add under Limits
`- PREREGISTRATION.md states 03:35 UTC; the first holdout run started at 03:29:22 UTC. The local original was created at 03:29:08 UTC (filesystem birth time, unchanged since); it was committed together with the results.`
Do not edit PREREGISTRATION.md itself.
Also either replace `home paths shown as `~`` with `home paths shown as `~` except the `dataset` field of the three difficulty reports`, or redact that field to `~/dev/afast-ev/difficulty-dataset.jsonl` and regenerate `MANIFEST.json`.

## 5. What I could not check

- The local raw archives and session logs behind the 09-24 exec times were not opened. The prereg birth time (03:29:08 UTC) and the judge re-test times come from local files outside the repo.
- Whether the add-on reviewers' requested changes were applied before merge.
- Studio's window (not driven by anyone, as the README states). The scope gate via `session.working_dir` in `amplifier-runtime serve` has unit-test coverage only.
- The RouteLLM/ICLR citation was not re-checked online.
