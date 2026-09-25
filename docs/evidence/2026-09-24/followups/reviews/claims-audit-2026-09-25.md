Verdict: CORRECTIONS NEEDED

# Independent claims audit: fast-decisions README, report, results, design doc

Audited: `~/dev/amplifier-bundle-fast-decisions` @ `main` `52e0d29` (working tree clean; nothing modified).
Scripts I used to recompute are in `/tmp/ampup/claims-audit/work/` (`s1.py`, `swe.py`; the judge-AUC and
MANIFEST checks were run inline).

## Summary

The arithmetic holds up. Every S1 ratio, SWE resolved count, SWE ratio and judge AUC I recomputed from the
committed evidence matches the published figure to the stated precision. The one exception is a single
rounding (GLM 0.755 is really 0.7546). All 533 files in `MANIFEST.json` hash-verify: 0 mismatches, 0 missing.

The problems are about what the numbers are attributed to, and about text that went stale:

1. **The headline "everyday tasks" numbers (0.55–0.61× time, 0.38–0.40× cost) were measured with the built-in
   length rule.** The shipped default is now Jev. On the same S1 tasks Jev measured 0.61× time and **0.50×** cost.
   The README headline table, the report's hero text, the "At a glance" table and the report's Figure 2/3 data all
   present the rule's numbers as what you get from the default.
2. **The measured builds are not the shipped build.** Commit `3d2c4e0` ("decide once for real") came after the
   evidence. It removed the 6-request and test-failure escalation. The measured S1 default escalated mid-request 2
   times in 145 routed calls (`router-rules-s1-dev` comparison: `model_routed_escalations_by_reason: {max_requests: 2}`).
   The corrected default (`orch-default` cell, commit `52e0d29`) has no stored results.
3. **Stale text contradicts the code.** The report's Figure 1 and chart labels say the built-in rule is the default.
   RESULTS says "No judge (length rule) by default", names branch `feat/orchestrator-primary`, and says the upstream
   PR still needs approval (PR #413 is open). ORCHESTRATOR-PRIMARY's tier table still lists escalation "on test
   failure, provider error or after 6 requests". Its "Evidence so far" table is superseded and has a wrong cost (0.55× vs 0.50×).
4. **Several claims have no committed evidence:** the start-up profile (26 s breakdown, 151 modules, 59 s / 114k-token
   trivial prompt), the add-on token and latency cuts, "independently reviewed" merges, the per-step values behind
   Figure 7, and qwen:latest being "27B / 29 GB".
5. **Behavioral caveats the docs don't state:**
   - The scope gate counts files in the **process cwd** (`os.getcwd()`), memoized per process. It is not the session's
     working directory, so it is unverified for `amplifier-runtime serve` / Studio.
   - The savings estimate overstates savings when easy and hard turns alternate, because cross-turn cache rebuilds are
     priced as if the host had paid them.
   - "Always wins" for a user model pick is only true for an in-session pick.

## 1. Claims table

Legend: VERIFIED = recomputed or checked against file/code and matches. MISMATCH = the source says something
different. UNSUPPORTED = no committed record (it may exist in a terminal or a local archive). STALE = was true for an
earlier build or state, not now. MISLEADING = true number, wrong or incomplete framing.

### 1a. S1 everyday tasks (recomputed: geometric mean over tasks of median candidate / median plain, `exec_time_ms`, `cost_usd`)

| # | Claim | Location | Source | Recomputed | Verdict |
|---|---|---|---|---|---|
| 1 | Shipped default, 12 dev tasks: 0.55× time / 0.38× cost | README table+text; report hero, At-a-glance, Fig 2/3, DATA; RESULTS; ORCH | s1/router-rules-s1-dev | 0.545 / 0.381 | VERIFIED numerically; **MISLEADING/STALE** as "default": the cell is `orch-router-rules` (length rule), PREREGISTRATION says "no judge", and the default is now Jev |
| 2 | Holdout, 8 unseen tasks × 3 reps: 0.61× / 0.40× | README; report; RESULTS | s1/prereg-s1-holdout | 0.610 / 0.3952 | VERIFIED (the harness's own `RESULTS.md` prints the cost as 0.39); same "rule, not Jev" caveat as #1 |
| 3 | 95% CI 0.47–0.78 | report; RESULTS | prereg RESULTS.md (bootstrap 2000, seed 20260919) | [0.47, 0.78] as stored (not re-bootstrapped) | VERIFIED against stored output |
| 4 | Sign test 7/8, p = 0.07; not confirmed; 5 of 6 criteria | README; report; RESULTS | per-task ratios; PREREGISTRATION.md; gates.json | 7 of 8 faster; two-sided binomial 18/256 = 0.0703; gates green; criteria 1,2,4,5,6 pass | VERIFIED |
| 5 | One task marginally slower, median 8.79 s vs 8.73 s | report; RESULTS | answer_default_port | 8.789 s vs 8.731 s | VERIFIED |
| 6 | "With only eight tasks, that test passes only if all eight are faster" | report; RESULTS Open | binomial | 8/8 → p = 0.0078; 7/8 → 0.070 | VERIFIED |
| 7 | Every task passed; 24/24; 12/12 | all | outcome_passed | all runs of all cells passed | VERIFIED |
| 8 | Router + Jev: 0.61× / 0.50×, Jev sent 3 of 12 to the full model | README; RESULTS; ORCH "Who judges"; report DATA | s1/router-s1-dev; comparison `judge_strong: 3` | 0.608 / 0.500; 3 tasks served on fable | VERIFIED |
| 9 | ORCH "Evidence so far": S1 Jev 0.61× / **0.55×** cost | ORCH | s1/router-s1-dev | cost 0.500 | **MISMATCH** |
| 10 | plain-sonnet 0.59× / 0.42× | RESULTS; report DATA | s1/screen-s1-dev | 0.589 / 0.420 | VERIFIED |
| 11 | Same-run cheaper-model control 0.57× / 0.37× | report Fig 2 caption | router-rules-s1-dev plain-sonnet | 0.574 / 0.374 | VERIFIED; note it is **equal to or better than** the shipped rule in that batch (0.545 / 0.381) |
| 12 | orch-primary v0: 0.48× / 0.77× | RESULTS; report DATA | screen-s1-dev | 0.479 / 0.767 | VERIFIED |
| 13 | Effort routing alone (fable): 0.77× / 1.09× | RESULTS; report DATA ("Full model, lower thinking level") | screen-s1-dev effort-only | 0.773 / 1.090 | VERIFIED numerically; label **MISLEADING**: the cell uses phase effort orient=medium / explore=low / implement=**high**, not uniformly lower thinking |
| 14 | vs the cheaper-model control on holdout: "cost the same and was not reliably faster (four tasks faster, four slower)" | report Results | holdout per task | cost 0.395 vs 0.401 ✓; 4 faster / 4 slower ✓; but the stored secondary ratio is **0.81× [0.64, 0.99]** | **MISLEADING**: omits the stored geomean, whose CI excludes 1.0 |
| 15 | "Dev 0.95" vs plain-sonnet (prereg prediction) | PREREG (context) | router-rules-s1-dev | 0.545/0.574 = 0.95 | VERIFIED (context only) |
| 16 | S1 dev screens of the default ran on build 43ed54e (pre-scope-gate) | RESULTS; evidence README | manifests hold only tool SHAs | no candidate SHA in committed manifests | UNSUPPORTED (committed) |
| 17 | "The decision is made once per request" as a property of the measured results | README intro; report "Deciding once"; Fig 7 | router-rules-s1-dev comparison | 2 `max_requests` mid-request escalations in the measured default | **STALE**: true of current code, not of the measured build |

### 1b. SWE-bench Verified (resolved from `grading/*.json`; ratios = geomean of candidate/plain matched on instance + rep)

| # | Claim | Location | Recomputed | Verdict |
|---|---|---|---|---|
| 18 | Shipped default 13/20 vs plain 14/20; 1.00× time, 0.98× cost | README; report; RESULTS | 7+6 vs 7+7; 1.000 / 0.985 (per-instance medians: 1.014 / 0.989); all 20 served fable | VERIFIED |
| 19 | "Same setup as standard" / "exactly the standard setup" | README; report | served model = fable in 20/20; the fd arm still mounts the `fast_workspace` tool, the hook and the orchestrator wrapper | MISLEADING (minor): same model and effort, not byte-identical setup |
| 20 | Router+Jev 3 reps 19/30 vs 23/30; 0.86× / 0.91× | RESULTS; README ("19 of 30 vs 23 of 30"); report | 7+6+6 vs 7+8+8; 30 pairs → 0.855 / 0.912 | VERIFIED |
| 21 | django-11532: 3/3 → 1/3, Jev judged it simple every time | RESULTS; report | plain 3/3, Jev 1/3; each Jev run started with 6 sonnet requests | VERIFIED |
| 22 | Router + local qwen:latest 6/10 (plain 7/10), 0.75× / 0.89× | RESULTS | 6 vs 7; 0.751 / 0.885 | VERIFIED |
| 23 | plain-sonnet 5/10 (plain 7/10), 1.66×, 0.93× per task, 1.42× total spend | RESULTS; report DATA | 1.663 / 0.926 / 1.42 | VERIFIED |
| 24 | orch-primary v0 8/10 vs 7/10, 1.21× / 1.40× ("1.2× slower, 1.4× more expensive") | RESULTS; report; ORCH | 1.205 / 1.395 | VERIFIED |
| 25 | Strong tier + phase effort 12/20, 0.81× / 0.87×; "saved 19%" | RESULTS; report Fig 5 | 6+6; 0.811 / 0.869 | VERIFIED |
| 26 | pylint-7080: lower effort 0/2, plain 2/2, shipped default 1/2 | RESULTS; report | as stated | VERIFIED |
| 27 | Plain fixed 77% (Jev batch), 70% (first-version batch) | report Fig 4 | 23/30 = 76.7%, 7/10 | VERIFIED |
| 28 | complexSolved DATA 70/65/60/63/80/50 % | report DATA | 14/20, 13/20, 12/20, 19/30, 8/10, 5/10 | VERIFIED |
| 29 | ORCH "Evidence so far": S3 Jev 0.90× / 0.94×, 7/10 vs 7/10; "confirmation at 3 reps running" | ORCH | router10 alone: 0.897 / 0.940, 7 vs 7; the 3-rep result is 19/30 vs 23/30, 0.86× / 0.91× | **STALE** |
| 30 | Provider wait ≈ 80–84% (RESULTS) / 80–85% (report) of the turn | RESULTS; report | provider_response_duration / exec_time over 165 SWE runs: median 0.836, IQR 0.78–0.87 | VERIFIED |
| 31 | ~12 s start-up and exit per run | RESULTS; report | wall − exec: median 12.5 s | VERIFIED |
| 32 | "About 360 recorded coding runs" | report | 192 S1 + 165 SWE result files = 357 | VERIFIED |

### 1c. Judges (AUC recomputed over `difficulty-report*.json` rows with `source == swe-verified`, 45 complex / 45 simple)

| # | Claim | Location | Recomputed | Verdict |
|---|---|---|---|---|
| 33 | Jev AUC 0.83 / "83%", ~0.16 s | README; RESULTS; ORCH; report | 0.827; p50 155 ms | VERIFIED |
| 34 | Built-in rule 0.60; "no rule based on wording beat 60%"; "no surface feature beats length (410 held-out)" | all | 0.599; surface-feature-auc.json: best is chars 0.595, n = 410 | VERIFIED |
| 35 | qwen:latest 0.85, ~2.45 s | README; RESULTS; report | 0.848; p50 2.45 s (all rows) / 2.47 s (reported) | VERIFIED |
| 36 | qwen:latest is "27B-class", "29 GB", "27 billion parameters" | README; RESULTS; report text + DATA note | not in any committed file; `ollama list` shows 29 GB on this machine; no parameter count anywhere | **UNSUPPORTED** (terminal-only size; the parameter count is unverified) |
| 37 | Hosted Qwen3.8-27B-FP8 0.85; median 0.63 s; 40–90 ms cached; 1 in 4 took 5–22 s | README; RESULTS; report HOSTED | keepalive: 0.848, p50 634 ms, 8 calls 41–90 ms, 28/110 > 5 s (25%), max 21.6 s | VERIFIED (the 1-in-4 is over all 110 items; on the 90 SWE items it is 28/90 = 31%) |
| 38 | qwen3:4b / qwen3:8b 0.74 / 0.72, 0.26 / 0.36 s | README (8b); RESULTS; report | prefill: 0.737 / 0.721; p50 259 / 364 ms | VERIFIED |
| 39 | glm-4.7-flash **0.76** / "76%" | RESULTS; report DATA | 0.7546 (the report file rounds it to 0.755) | **MISMATCH** (rounding: should be 0.75 / 75%) |
| 40 | llama3.1:8b 0.70, ~0.5 s (DATA 0.46 s) | RESULTS; report | 0.696; p50 457 ms | VERIFIED |
| 41 | qwen3:0.6b 0.50, 0.072 s, "coin flip" | RESULTS; ORCH; report | prefill 0.503, 72 ms | VERIFIED |
| 42 | "Mid-size local models 70–76%" | report | 0.696–0.755 | VERIFIED (upper end 75%) |
| 43 | 90 human-rated issues, balanced 45/45, plus 20 everyday tasks; 9 decision-makers | README; RESULTS; report | 110 rows = 90 SWE + 20 S1; 9 judges | VERIFIED |
| 44 | "Picks the harder of two issues" | README; report | AUC over pairs of **extremes** (<15 min vs ≥1 h); the 15 min–1 h middle band is excluded | MISLEADING (minor): the pairs are extremes, which flatters every judge; say so |

### 1d. Follow-ups, overhead, upstream

| # | Claim | Location | Source | Verdict |
|---|---|---|---|---|
| 45 | Sonnet about 1.3× faster than Opus 5.5 (113 vs 88 tok/s, 4 calls each) | README; RESULTS; report | followups.json: 113 / 88 = 1.28 | VERIFIED (n = 4, measured once) |
| 46 | Opus 5.5 price vs Sonnet 1.3× / 1.3× / 0.7×; Fable 3.3× / 3.3× / 0.8× | RESULTS; report | followups prices + savings.py DEFAULT_RATES: 4/3, 20/15, 0.2/0.3; 10/3, 50/15, 0.25/0.3 | VERIFIED |
| 47 | Opus default: "short requests save a little, long ones can cost slightly more" | README; report; RESULTS | price arithmetic only; no Opus-host run stored (`orch-default-opus` cell has no results) | UNSUPPORTED as a measurement; RESULTS and the report label it an estimate, **the README does not** |
| 48 | Trivial prompt 17.5 s without / 18.5 s with the four add-ons ("about one second") | RESULTS; report | followups: [18.3, 16.6] vs [18.6, 18.4] | VERIFIED as means; thin (n = 2, the without-runs spread 1.7 s) |
| 49 | Four add-ons "optimized and merged", each "independently reviewed" (memory #9, behavioral-plasticity #2, design-loop #3, preceptor #7) | RESULTS; report | names only in followups.json; no PR URLs, merge records or reviews | UNSUPPORTED |
| 50 | Add-on text cut 2,153 → 1,146 tokens; memory first-reply wait 12 s → under 3 s | report | nothing committed | UNSUPPORTED |
| 51 | Start-up breakdown 26 s (7.7 / 5.1 / 4.8 / 4.6 / 2.0 / 2.2), "151 modules", 5.5–7.7 s in profiled sessions | report Fig 8 + DATA | nothing committed (bars sum to 26.4) | UNSUPPORTED |
| 52 | Trivial prompt on the real config 59 s, 114k-token prompt; 13 s with app bundles disabled; model call ~2 s | RESULTS | nothing committed (points to a local BUNDLE-CLEANUP.md) | UNSUPPORTED |
| 53 | hooks-deprecation 5.8 s → 0.002 s; 72 existing + 6 new tests, Py 3.11–3.13; independently reviewed | RESULTS; report ("6–7 s → 2 ms") | PR #413 body states "6–7 s → 0.002 s" and "72 + 6 tests" (author's own statement); 5.8 s is STUDY-DESIGN prose; no stored review | Partly SUPPORTED (by PR text only); "independently reviewed" UNSUPPORTED; 5.8 s vs 6–7 s vs 7.7 s (Fig 8) inconsistent across docs |
| 54 | Upstream PR open as an optional suggestion, #413 | RESULTS; report | `gh pr view 413`: OPEN, "Optional: hooks-deprecation only scans…" | VERIFIED |
| 55 | RESULTS "Open: Apply the foundation fix upstream (needs approval to open the PR)" | RESULTS | the PR is open | **STALE** |
| 56 | Surface checks: Jev routed an easy turn to Sonnet in the CLI, runtime serve **and the TUI** | RESULTS; README; report | followups: CLI and runtime record judge=jev; the TUI record has **no judge field** (choice cheap, served sonnet) | Partly SUPPORTED (TUI routing yes, "Jev" in the TUI not recorded); n = 1 per surface |
| 57 | In-session model pick wins (user_model_strong), verified in the TUI | README; RESULTS | followups `tui_after_model_pick`; code `decide_start_tier` | VERIFIED (n = 1) |
| 58 | Fig 7: 87,000 vs 31,000 words rebuilt; one task ~175,000 words; a single rebuild up to ~60,000 words | report | totals match run aggregates: sympy v0 115.3k tokens × 0.75 = 86.5k; decide-once lane 41.3k → 31k; xarray v0 235,461 tokens → 176k. Per-step values and the 60k single rebuild are **not** in committed files | Totals VERIFIED; per-step bars UNSUPPORTED; "rebuilds" also counts the first-step cache write and ordinary incremental writes (MISLEADING, minor) |
| 59 | ORCH "re-wrote a 37k–235k-token cache on every escalation" | ORCH | 235k is a whole-run cache-write total (xarray), not a cache size; STUDY-DESIGN says "~37k-token" | **MISMATCH** |
| 60 | Branch `feat/orchestrator-primary` | RESULTS header | not a local branch; docs are on `main` | **STALE** |
| 61 | "Local judges … now answer choice and **noul** questions" | RESULTS | typo | MISMATCH (typo) |
| 62 | ORCH "Measuring it: adds **three** cells" (table lists five) | ORCH | — | MISMATCH (outside the audited sections; minor) |
| 63 | RouteLLM (LMSYS, ICLR 2025) | report | cited in STUDY-DESIGN as arXiv:2406.18665 | Consistent with the cited source; not re-checked online |
| 64 | Evidence checksums | evidence README | MANIFEST.json: 533 files, all sha256 match, none missing | VERIFIED (full set, not a sample) |

## 2. Behavioral claims vs code and config

| Behavior | Claim | Code / config | Verdict |
|---|---|---|---|
| Default judge | Jev (README, ORCH, report "Flavors") | `behaviors/fast-decisions.yaml`: `backend: jev`, `allow_external_state: true`, `start_policy: judge` | VERIFIED. **Contradicted** by report Fig 1 caption ("simple built-in rule (the default…)"), report DATA labels "Recommended · built-in rule — The new default", and RESULTS "No judge (length rule) by default" → STALE |
| Fallback | Without a key or on Jev error/timeout, the length rule decides and nothing leaves | `backends.py:313` raises `BackendUnavailable` when `TYPESAFE_API_KEY` is missing; `_ask_judge_choice` catches any exception or timeout (`timeout_ms: 3000`) → None → `decide_start_tier` keeps the rule tier (`complex_min_prompt_chars` 2000) | VERIFIED |
| Scope gate | >300 files → host model regardless of the judge | `orchestrator.py:244-253`: `workspace_file_count(os.getcwd(), 300)`, checked **before** the judge (no Jev call), skips .git/node_modules/.venv/build/dist/.amplifier etc., memoized per process by `root\|limit` | VERIFIED for the CLI. **Caveat not stated:** uses the process cwd, not the session working dir, and caches the count for the life of the process. In `amplifier-runtime serve` (Studio) the gate evaluates the server's cwd, so "work inside a large project always gets the full model" is unverified there |
| Decide once | One decision per request; only a provider error moves up | config: `max_requests_before_escalation: null`, `escalate_on_test_failure: false`, `escalate_on_provider_error: true`; `escalation_judge` defaults to `rules`; `phase_judge` not set; `by_tier.cheap: medium` fixes effort | VERIFIED for current code. Nuance: on a provider error the failed call **raises** (no retry in the wrapper, `orchestrator.py:996-1004`); only later calls in the same request go to the host. The measured builds used `max_requests: 6` and `escalate_on_test_failure: true` (see #17) |
| 2,500-character limit | "first 2,500 characters of the request" | `_DIFFICULTY_STATE_CHARS = 2500` applied to `_turn_user_text` = the **latest real user message**, with `<system-reminder>` blocks stripped; sent with fixed question text and criteria to `/v1/systemone` | VERIFIED; wording imprecise. In delegated sub-sessions (which inherit the orchestrator) the "user message" is the delegation instruction, so up to 2,500 characters of that also go to Jev on every sub-session request. Not stated |
| User model pick respected | README: in-session pick keeps every request on it; report: "picking a model yourself always wins" | `_user_selected_model`: `ui.model_override` marker, or `default_model` changed after first sight → `user_model_strong`; a pre-session `--model` or settings model is routable | README VERIFIED (states the limit). Report "**always** wins" is MISLEADING |
| Savings method | Cheap-turn tokens priced at host rates; provider cost_usd is the actual; time scaled by host/start rate ratio after 20+ samples each; negative allowed | `savings.py`: matches (`MIN_RATE_SAMPLES = 20`, samples need ≥200 output tokens, `saved = counterfactual − actual`) | VERIFIED. **Misleading by omission:** (a) a cheap turn after a host turn pays a cold-cache write, and the counterfactual prices those same cache-write tokens at host write rates as if the host would also have rebuilt (it would have read the cache); (b) the host turn after a cheap turn pays a rebuild that is counted as "saves nothing". Mixed sessions therefore overstate savings. Also `DEFAULT_HOST_MODEL = claude-fable-5-1` is used when `host_model` is not recorded, which inflates savings for non-Fable users in that edge case |
| What leaves the machine | Jev: first 2,500 chars; rule/local: nothing; log has no prompts or file contents | Only `_ask_judge_choice` / HostedBackend send data (gated by `allow_external_state`); telemetry uses an allowlist (`privacy.SAFE_FIELDS`); `afast rubric` and the smart tool send their inputs to Jev when invoked | VERIFIED for routing; see the sub-session nuance above. The dashboard records repo name, branch and harness (metadata, not contents) |
| Provider restriction | Easy requests go to Sonnet 5 | `provider_match: anthropic`, start model only sent to Anthropic providers | VERIFIED; the README does not say routing only happens on Anthropic providers |

## 3. True but misleading, or without stored evidence (consolidated)

- **The headline S1 numbers belong to a non-default judge** (#1, #2). The shipped Jev default measured 0.61× / 0.50× on
  dev. It was never run on the holdout, and the corrected decide-once default (`orch-default`) was never run at all.
- **On S1 the whole gain is the model swap.** In the same batch, "standard Amplifier on Sonnet" was 0.57× / 0.37×, versus
  0.55× / 0.38× for the shipped rule. The report says this; the README does not.
- **The report's holdout comparison against the cheaper model** omits the stored 0.81× [0.64, 0.99] (#14).
- **"Lower thinking level" label** on the S1 effort-only cell (#13).
- **"Picks the harder of two issues"** hides that the pairs are extremes (#44).
- **Fig 7 per-step values, start-up profile, add-on cuts, "independently reviewed", 59 s / 114k prompt, qwen:latest 27B / 29 GB**
  have no committed record (#36, #49–53, #58).
- **The Opus 5.5 cost expectation** in the README reads as a finding; it is a price-table estimate (#47).
- **The scope gate and the Studio claim:** the gate reads the process cwd.
- **Savings overstatement** in sessions that alternate tiers (§2).

## 4. Required corrections (exact replacement text)

### README.md

**R1. Headline table, first row.** Replace
```
| Everyday coding tasks | 0.55–0.61× | 0.38–0.40× | Every task passed |
```
with
```
| Everyday coding tasks, Jev deciding (default) | 0.61× | 0.50× | Every task passed (12 tasks, one run each) |
| Everyday coding tasks, built-in rule (no key) | 0.55–0.61× | 0.38–0.40× | Every task passed |
```

**R2. Paragraph under the table.** Replace
```
Compared with standard Amplifier on the same tasks, run at the same time. Ratios are geometric means of per-task
ratios. Everyday tasks: 12 tuning tasks (0.55× / 0.38×, one run each) and 8 unseen tasks run three times each
(0.61× / 0.40×). The unseen-task result met 5 of its 6 preregistered criteria; the significance test fell short
(p = 0.07), so it is not yet confirmed.
```
with
```
Compared with standard Amplifier on the same tasks, run at the same time. Ratios are geometric means of per-task
ratios. Built-in rule: 12 tuning tasks (0.55× / 0.38×, one run each) and 8 unseen tasks run three times each
(0.61× / 0.40×); the unseen-task result met 5 of its 6 preregistered criteria, but the significance test fell short
(p = 0.07), so it is not yet confirmed. Jev deciding was measured only on the 12 tuning tasks. On these small tasks
nearly all of the gain comes from using Sonnet: standard Amplifier switched to Sonnet ran at 0.57× / 0.37× in the
same batch. These runs predate the current "decide once" build: the measured build could still switch an easy
request up after 6 model calls, which happened 2 times in 145 calls. The current build has not been re-measured yet.
```

**R3. Opus paragraph.** Replace `so expect mostly a speed gain:` with
`so expect mostly a speed gain (an estimate from list prices and a 4-call speed check, not a measured comparison):`

**R4. "How it works" item 2.** Replace
```
2. **Large projects always get your usual model.** In a folder with more than 300 files, the request runs exactly
   as standard Amplifier would, whatever the decision-maker says.
```
with
```
2. **Large projects always get your usual model.** When the folder Amplifier was started in holds more than 300
   files (not counting .git, node_modules, virtualenvs and build folders), the request runs on your usual model and
   thinking level, whatever the decision-maker says. The count is taken from the process's working folder and cached
   for the life of the process; it was verified in the command line, not in Studio.
```

**R5. "How it works" item 1.** Replace `(only a provider error on the faster model moves the request to your usual model)` with
`(only a provider error on the faster model moves the rest of the request to your usual model; the failed call itself is not retried by Fast Decisions)`

**R6. "Who decides" intro.** Replace
```
Measured on 90 real issues rated by human experts (SWE-bench Verified): how often each decision-maker picks the
harder of two issues, and how long it takes. 50% is a coin flip.
```
with
```
Measured on 90 real issues rated by human experts (SWE-bench Verified): how often each decision-maker ranks an issue
rated an hour or more of work above one rated under 15 minutes, and how long it takes. 50% is a coin flip. Issues in
between were not included, so real-world accuracy will be lower.
```

**R7. "Who decides" table, Jev row, last cell.** Replace `The first 2,500 characters of the request` with
`The first 2,500 characters of your latest message (for helper sessions, of the helper's instructions)`

**R8. "Who decides" table, Qwen row.** Replace `| Qwen 27B-class model on your Mac (Ollama `qwen:latest`) |` with
`| A large local Qwen model (Ollama `qwen:latest`, 29 GB on the test machine) |`

**R9. Savings bullet.** Replace `Estimates, labeled as such; a negative number means routing cost more.` with
`Estimates, labeled as such; a negative number means routing cost more. Sessions that alternate between easy and hard requests pay extra cache rebuilds that this estimate does not subtract, so it overstates savings there.`

### docs/report/fast-decisions-report.html

**H1. Hero paragraph.** Replace `On everyday tasks, Amplifier now finishes in
      roughly half to three-fifths of the time for about 40% of the cost, with every task still
      passing its hidden checks.` with `On everyday tasks, Amplifier finished in roughly three-fifths
      of the time for half the cost with Jev deciding (the default), and in half to three-fifths of the time for about
      40% of the cost with the built-in rule, with every task still passing its hidden checks.`

**H2. At-a-glance table, everyday row.** Replace the cells `0.55–0.61×` / `0.38–0.40×` with
`0.61× (Jev, default) · 0.55–0.61× (built-in rule)` / `0.50× (Jev) · 0.38–0.40× (built-in rule)`. Also replace
`The everyday-task range spans tuning tasks (0.55×) and a separate set of eight tasks never used for tuning (0.61×).` with
`The built-in-rule range spans tuning tasks (0.55×) and eight tasks never used for tuning (0.61×); Jev was measured on the tuning tasks only. All everyday runs predate the current decide-once build.`

**H3. Figure 1 caption.** Replace `The call can be made by a simple built-in rule (the default; nothing leaves
    your machine), by Jev, TypeSafe's hosted decision model, or by a model you run yourself.` with
`The call is made by Jev, TypeSafe's hosted decision model (the default), by a simple built-in rule (used without a Jev key or when Jev fails; nothing leaves your machine), or by a model you run yourself.`

**H4. Results, everyday paragraph.** Replace `Against standard Amplifier simply switched to the cheaper
  model it cost the same and was not reliably faster (four tasks faster, four slower), which is what we expected: on
  small jobs the dispatcher mostly just picks the cheaper model.` with
`Against standard Amplifier simply switched to the cheaper model it cost the same (0.40×); on the unseen tasks it was 0.81× the time (95% interval 0.64–0.99) but faster on only four of eight tasks, and on the tuning tasks the cheaper-model control was as fast (0.57×). On small jobs the dispatcher mostly just picks the cheaper model.`

**H5. DATA.simpleTime / DATA.simpleCost, row "Recommended · built-in rule".** Replace the note
`'The new default; 0.61× on eight unseen tasks'` with `'Used without a Jev key; 0.61× on eight unseen tasks'` and
`'The new default; 0.40× on eight unseen tasks'` with `'Used without a Jev key; 0.40× on eight unseen tasks'`. In the
"Recommended · Jev decides" rows, set the notes to `'The default; sent 3 of 12 tasks to the full model'` and `'The default'`.
Rename both `'Full model, lower thinking level'` rows to `'Full model, thinking level by phase'`.

**H6. DATA.judges GLM row.** Replace `['GLM 4.7 Flash, this Mac', 76, 0.5, '']` with `['GLM 4.7 Flash, this Mac', 75, 0.5, '']`,
and `Mid-size local models land around 70–76%` with `Mid-size local models land around 70–75%`.

**H7. Judges prose and DATA.** Replace `A 27-billion-parameter open model
  does slightly better (85%): on this Mac it takes about two and a half seconds;` with
`A large open model does slightly better (85%): run locally (Ollama qwen:latest, 29 GB) it takes about two and a half seconds;`.
Replace the DATA note `'27B parameters, runs locally'` with `'Ollama qwen:latest, 29 GB'`. Replace
`we showed each one pairs of real issues: one rated a quick fix by human experts and
  one rated an hour or more of work.` with `we showed each one pairs of real issues: one rated a quick fix (under 15 minutes) by human experts and one rated an hour or more of work; issues in between were left out, so everyday accuracy will be lower.`

**H8. "Deciding once" bullet.** Replace `The dispatcher picks the model and thinking level before the first
    step and never changes them mid-request.` with `The dispatcher picks the model and thinking level before the first step and changes them mid-request only if the faster model's service returns an error. (The build measured here could also switch up after six steps; that happened twice in 145 calls on everyday tasks.)`

**H9. "Choose who makes the call" card.** Replace `One setting switches between them, and picking a model yourself
      always wins.` with `One setting switches between them, and picking a model yourself during a session always wins (a model set before the session starts can still be routed).`

**H10. Figure 7 caption.** Append: `Per-step values come from the local raw-record archive, not the committed evidence folder; the totals match the committed per-run cache-write counts. Rebuild totals include the first step's initial cache write.`

**H11. Figure 8 caption and start-up/add-on paragraphs.** Append: `These timings, the token counts and the first-reply latency are from profiled terminal runs and are not in the committed evidence folder.`
Replace `each change independently reviewed before merging` with `each change reviewed before merging (review records not included here)`.

### docs/RESULTS-2026-09-24.md

**S1.** Replace `Branch `feat/orchestrator-primary`.` with `Measured on branch `feat/orchestrator-primary` (since merged to `main`); the default changed after measurement (Jev judge, decide-once), see Follow-ups.`

**S2.** Replace `4. **Pluggable judge.** No judge (length rule) by default. Jev, or a local model, via the` with
`4. **Pluggable judge.** At measurement time, no judge (length rule) by default; Jev is now the default (see Follow-ups). Jev, or a local model, via the`

**S3.** In the S1 table, replace `| **router, shipped default (length rule; pre-scope-gate build 43ed54e)** |` with
`| **router, length rule (the default when measured; pre-scope-gate build 43ed54e)** |`, and
`| **shipped default, preregistered holdout (8 unseen tasks, 3 reps)** |` with
`| **length rule, preregistered holdout (8 unseen tasks, 3 reps)** |`. Replace `| router + Jev |` with `| router + Jev (current default judge) |`.
Append below the table: `The measured builds could escalate an easy turn after 6 requests (2 of 145 routed calls did); the current decide-once default has not been re-measured.`

**S4.** Judges table: replace `| local glm-4.7-flash / llama3.1:8b | 0.76 / 0.70 | ~0.5 s |` with `| local glm-4.7-flash / llama3.1:8b | 0.75 / 0.70 | ~0.5 s |`.
Replace `| local qwen:latest (29 GB) |` with `| local qwen:latest (29 GB per local `ollama list`; not in evidence) |`.

**S5.** Amplifier overhead section, first bullet: append ` (terminal measurement; not in the committed evidence folder)`.
Second bullet: replace `(72 existing + 6 new tests passing on Python 3.11–3.13; independently reviewed)` with `(72 existing + 6 new tests passing on Python 3.11–3.13, as stated in PR #413; review record not stored)`.

**S6.** Follow-ups, add-ons bullet: replace `each
  after an independent Amplifier review.` with `(PR records and reviews not stored in the evidence folder).`
Surface bullet: replace `Verified end to end: Jev routed an easy turn to
  Sonnet in the CLI, `amplifier-runtime serve` and the TUI (core 1.6.0).` with `Verified end to end, one prompt each: Jev routed an easy turn to Sonnet in the CLI and `amplifier-runtime serve`; in the TUI (core 1.6.0) an easy turn went to Sonnet (the judge was not recorded).`

**S7.** Open section: replace `- Apply the foundation fix upstream (needs approval to open the PR) and the local bundle cleanup
  (needs approval).` with `- The foundation fix is open upstream as an optional suggestion (amplifier-foundation #413); the local bundle cleanup still needs approval.`

**S8.** Bugs section: replace `They now answer choice and noul questions.` with `They now answer choice and yes/no questions.`
(The intended word is unknown; confirm with the author.)

### docs/ORCHESTRATOR-PRIMARY.md

**O1. Tier table, simple row, last cell.** Replace `escalation on test failure, provider error or after 6 requests` with
`only on a provider error (subsequent calls move to the host model)`.

**O2.** Replace `The previous cheap-first policy re-wrote a 37k–235k-token cache on
every escalation and every effort flip.` with `The previous cheap-first policy re-wrote the ~37k-token conversation cache on every escalation and every effort flip (up to 235k cache-write tokens over one SWE-bench run).`

**O3. "Evidence so far".** Replace the heading line and table with:
```
**Evidence so far** (S1: screen, 1 rep; S3: 3 reps, no scope gate):

| Suite | Router (Jev) vs plain: time | cost | quality |
|---|---|---|---|
| S1 simple (12 tasks) | 0.61x | 0.50x | 12/12 vs 12/12 |
| S3 SWE-bench Verified (10 × 3 reps, before the scope gate) | 0.86x | 0.91x | 19/30 vs 23/30 |

With the scope gate (the shipped default), S3 runs on the host model: 13/20 vs 14/20, 1.00x time, 0.98x cost.
```

**O4. "Who judges".** Replace `the first 2,500 characters of the turn's request go to the Jev endpoint.` with
`the first 2,500 characters of the turn's latest user message (system reminders removed; in delegated sub-sessions, the delegation instruction) go to the Jev endpoint.`

**O5. "Savings".** Append after `These are estimates, not matched comparisons;`:
` in particular, a cheaper-model turn that follows a host-model turn pays a cold-cache write that the counterfactual prices at host rates as if the host would also have paid it, and the rebuild on the next host turn is not charged to routing, so sessions that alternate tiers overstate savings. Rate samples need at least 200 output tokens.`

**O6. "Measuring it".** Replace `adds three cells` with `adds these cells`.

### Code/config (not a doc claim, but it bears on a documented promise; recommend, do not block on)

- `orchestrator.py:246` scope gate: use the session's working directory, e.g. the coordinator's `session.working_dir`
  capability, falling back to `os.getcwd()`. Include it in the memo key, or re-document the limit as in R4.
- `behaviors/fast-decisions.yaml` `bundle.description` still says "a cheaper start model that escalates on failure
  signals", which contradicts decide-once. Update it to "a cheaper start model for turns judged easy, decided once per turn".

## 5. What I could not check

- Bootstrap CIs were read from stored output, not re-sampled.
- The local raw archive and session logs (`~/dev/afast-orch-primary-20260924/archive/*`) were not opened. Their stated
  SHA-256 values were not re-hashed (604 MB).
- The RouteLLM/ICLR citation was not re-checked online.
- Studio's own window was not driven by anyone, as the README itself states.
