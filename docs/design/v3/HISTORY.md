# fast-decisions: reconstructed history and evidence (for the v3 technical report)

Sources (all read-only): `git -C ~/dev/fd-paired` at `origin/main` (head `8e7faf3`, 2026-10-05, 388 commits, first commit `1bac342` 2026-09-16); `~/.amplifier/fast-decisions/` (live observatory event store); `~/dev/amplifier-unified` (no fast-decisions docs; only the registry-mode commit `37f400d` in fd-paired references Unified). Repo is `amplifier-bundle-fast-decisions`; Python package `amplifier_fast_decisions`, CLI `afast` / `amplifier-fast-decisions`.

Notation: "prereg" = preregistered confirmatory; "screen" = exploratory/dev. All $ are provider-reported or price-table estimates, not billing.

## 0. Findings the narrative must absorb up front (where the lead's story needs adjustment)

1. **The observatory was real, and it is the first thing built (2026-09-17)**, but the ~1-week observation window is not a clean "ran it, then measured" phase. The events dir holds 4,482 session files, 464,883 `fast_decisions:*` events, 2026-09-17 .. 2026-10-05 (counted by me; 71% are 15 s `health` heartbeats). 2026-09-17..23 carries 171,609 events, so "about a week" matches the heavy window, but the observatory kept running to Oct 5 and was fed by eval traffic too (separate `events-eval/` has 311 files; `AFAST_TRAFFIC=test` tagging only arrived 2026-09-25, `2dbe1d2`).
2. **The observatory's honest finding was negative.** Of 1,642 `shadow_agreement` events: 117 match, 1,132 mismatch, 393 abstained (7.1% match; my count over `events/`). Its first real-host validation (`docs/OBSERVATORY-VALIDATION.md`, 2026-09-17) showed one local-judge call that timed out and fell back ("evidence of fallback, not acceleration") and one completed fast path at 126 ms.
3. **The system-1 model is not what saves the money.** The measured savings come mainly from (a) choosing a cheaper model once per session, (b) the effort setting, (c) deterministic guards. The paper itself says: "no judge met the usefulness rule on real decisions" (trace study) and "this campaign shows no benefit of this router beyond the decision to use Sonnet" (paired campaign). Jev is "the best of the judges tested", not proven necessary. Plain Sonnet at medium effort alone cost 0.821x default (prereg).
4. **The headline savings are host- and price-dependent.** Fable 5.1 host: sticky routing 0.558x cost (CI 0.493-0.643). Opus 5.5 host: every routing arm 1.25-1.43x (costs MORE). The shipped default therefore has a price gate that refuses to route on an Opus 5.5 host.
5. **Stale doc banners contradict the current default.** `docs/GOAL.md` "Status", `docs/JEV-CUA.md` and `docs/JEVGREP.md` headers still say Laya is the default; `987453c`/PR #49 (2026-09-29) restored Jev (`behaviors/fast-decisions.yaml`, `jevgrep.yaml`, `jev-cua.yaml` all `backend: jev`, `allow_external_state: true`). `docs/SMART-TOOL.md` banner is correct (Jev 1.13.0).
6. **The 2,000-run SWE-bench Verified four-arm campaign (`evals/swebench/COMPLETE-CAMPAIGN.md`) has no results in `origin/main`**: `docs/SWEBENCH-RECOVERY.md` records it stopped after 29 finished runs and was patched to resume; no final tally is committed. Do not cite a complete-Verified result.

## 1. Dated timeline (origin/main)

| Date | Commits / PRs | What |
|---|---|---|
| 09-16 | `1bac342` | baseline snapshot before restructure |
| 09-17 | `406c8b7` (#1), `cf77185` (#2), `3793541` (#3) | Amplifier-native bundle layout; real-kernel CI lane; orchestrator mounted at kernel's `orchestrator` point |
| 09-17 | `e3dd674` (#6), `c34728c` (#7), `a486e85` (#8), `docs/design/redesign-2026-09-17.md` | shadow scoring in the hook (no orchestrator swap); batched `DecisionRequest`; shadow-only role router; `afast bench` offline replay + labelled suite (CLASSic-shaped) |
| 09-17 | `b3d4d3e` (#14), `8a4dae2` (#15), `3e2e985` (#16), `88462b9` (#17) | **Observatory**: auto-start on session start, port fallback, local scorer (Qwen3:0.6B via Ollama), session-first view with presence + execution evidence |
| 09-17/18 | `881fdfa`, `2dcc289`, `docs/design/teamwork-portable-tool.md` | **Portable Smart Tool** (library + CLI, no Amplifier needed) |
| 09-18 | `675a4b3` (#18/#19), `cc1fbf5`, `e7dafe1` (#20) | Observatory redesigned as a decision ledger; paired host-execution measurement; `docs/OBSERVATORY-VALIDATION.md` |
| 09-18 | `46ffc47`, `de1700e`, `1c8d8de`.. `92c9ff9` (#21), `docs/CAMPAIGN-2026-09-18.md` | Forge matched baseline/fast runner; hill-climb campaign HC00-HC03b; $45.39 settled worker spend |
| 09-18 | `b569153`, `b42b0e3`, `1dfeae3`, `docs/BATTERY-2026-09-18.md` | 20-prompt x 5-harness battery (Claude Code, Codex, OpenCode, Amplifier plain, Amplifier+FD); effort routing; HC04 model routing + escalation `19512a8` |
| 09-19 | `512adb2`, `422e64d`, `a6edd99`, `001c702`, `1218824`, `3e711fc` | `evals/STUDY-DESIGN.md` written; verdict layer (bootstrap CI); aider-polyglot adapter (225 exercises); multidimensional report |
| 09-20 | `5a1505a`, `cd5da87`, `39fd0b9`, `361d01a`, `15b1beb`, `98cbb35`, `eef3360`, `fef638e`, `441286f`, `22f8658`, `33b4e5c` (#22-#32) | judge-driven escalation; evidence-gated reconfiguration; S3 SWE-bench stage; "make my amplifier faster" recipe; MLX/Ollama local judges; hosted judge (RunPod); Laya backend; HC08 batching + HC09 stake-scaled gates; four-harness smoke of the Smart Tool |
| 09-21 | `40f7a93`..`ff00b28` (#33) | active-loop install fixes |
| 09-22 | `3a15bb1`, `661f380` (HC10 decomposed escalation, HC11 tool-risk shadow), `be9e41b`, `11b6b8b` | calibration/gate curves; Jev pinned `jev-1.13.0` (probabilities only); bounded parallel runs; path-length outage (STUDY-DESIGN 17.1). `evals/NATIVE-THREE-ARM-STUDY.md` frozen 09-22 (collection started; **no completed result in repo**) |
| 09-23 | `0f03032` | "unify live observatory" |
| 09-24 | `4960914` | **orchestrator-primary composition** (`loop-fast-decisions` replaces root orchestrator, wraps upstream loop-streaming); `5deded5` start-tier difficulty router; `8245a2f` router as default; `1f8bd4c` Jev default judge + savings estimate; `1902d0d` scope gate (`cheap_max_workspace_files: 300`); `5ba2714` SWE-bench Forge runner; `docs/RESULTS-2026-09-24.md`; HTML plain-language report; upstream hooks-deprecation PR #413 |
| 09-25 | `2dbe1d2` efficiency receipts + ledger (`docs/GOAL.md`), `4309e4b` routing levers, `30dd665` per-step action set, `723e515`/`46a7673` cache keep-alive, `664d270` waste guards + Claude Code hook, `4ab5da8` continuous eval harness, `05d4f3e` multi-turn suite s1m, `b1012e2` holdout2 | goal reframed to per-step decisions; holdout2 confirmed; Haiku preset disqualified; waste census; turn planner opt-in |
| 09-27 | `54c7e09` (#39), `5a0b7be` (#40) | AnyJev (opt-in) + native jevgrep retrieval; merge of all branches ("integrate/all-work-20260927"); eight matched Amplifier runs |
| 09-28 | `d6db404` (#41), `8481ec5`/`4c9ce44` (#42), `2e206f3`, `f7c2738` (#43) | default Jevgrep; full-Verified 4-arm campaign launched (stopped, see 0.6); project-scoped Jev advice for Codex; Jev CUA selector + bounded host driver |
| 09-29 | `b063072` (#44), `5efd599` (#45), `027bf0a` (#46), `af4f694`/#48, `987453c`/#49, `3a4e57e` (#50), `37f400d` (#51), `219bb82` (#52), `a451fdd` (#53) | Forge-validated live features; Laya default then **reverted to Jev**; delegation routing; **registry mode** for Unified; facade transparency |
| 09-30 | #54 (`62ebe49`, `45d5f8e`), #55 (`1de101a`..`9708864`), #56 (`180f919`), `1fe1d1b`..`7481132`, `4e71244` | nine-judge comparison (Luna, Sol added); preregistered judge benchmark (63 holdout cases); four bundle defects fixed (`a15c439`); trace-derived real-decision benchmark; caching survey; design of paired measurement v2 |
| 10-01 | `6865bbc`, `6d34805`, `4caf463`, `c1481d5`, `c2c287e`, `3aa2d1e` | paired multi-turn harness; memguard; main-v1 scenarios (70, 47 train/23 test, preregistered) |
| 10-02 | `7e69a1d`, `dc1aa4e`, `c3ea41a`, `f46e5b2` (technical report) | live dashboard for paired campaigns; main-v1 evidence + confirmatory analysis; technical report |
| 10-04 | `c62a39c`, `ee13ca9`, `310f044`, #57-#59 | Clef / Clef-Flash post-hoc judge arms; paper covers four parts |
| 10-05 | `b92a4dc`, `7f79eb3`, `249941c`, `733a6fc`, `d5602cf`, `9e4865e`, `672164c`, `182b354`, `c029d50`, #60-#63 | effort-control (Sonnet medium 0.821x; Fable medium 0.860x); two peer-review rounds; **price gate + decide once per session shipped**; offline replay of campaign through shipped code |

## 2. Phases: question, build, numbers, lesson, open

### Phase A: Observatory (09-17 .. ~09-23; kept running after)
- **Question:** what do the small decisions in real agent sessions look like, and could a fast judge take them? Is it observable?
- **Built:** `observatory.py`, `observer.py`, `telemetry.py`, `static/app.js|index.html|style.css`, `afast serve`; session-first -> decision-ledger view; shadow scoring (`shadow.py`), role router (`router.py`), `afast bench replay/suite`; privacy allow-list (`privacy.py`); `docs/EVENTS.md`, `docs/PRIVACY.md`, `docs/OBSERVATORY-VALIDATION.md`. Auto-launches on session start (`behaviors/fast-decisions.yaml` `observatory:`; stop with `afast serve --stop`).
- **Numbers:** local store 464,883 events, 4,482 session files (see section 0.1). Shadow agreement 117/1,642 match (my count). Local backends on the checked suite (`docs/EVIDENCE.md`): Ollama qwen3:0.6b agreement 0.75-0.80 at ~23 ms; Laya 0.60-0.63 at ~10 ms; MLX 0.70-0.88 at ~105 ms; Jev 1.00 at ~190 ms (one run, constructed suite; agreement is not correctness). Validation host: real timeout fallback 496.4 ms; one fast path 126.0 ms (`docs/OBSERVATORY-VALIDATION.md`).
- **Taught:** observation alone cannot show savings; a "bypass" needs host receipts; shadow agreement is not correctness. Also showed hook `modify` is not honored at `tool:pre` (`docs/UPSTREAM_CONTRACT.md`), which forced the orchestrator-level design.
- **Open:** the observatory's raw store is local and unpublished; no committed summary of the week exists apart from the numbers above. It is not in `~/dev/amplifier-unified`.

### Phase B: Evaluation/benchmark tooling (09-18 .. 09-22)
- **Question:** is Amplifier+FD faster/cheaper than plain at equal quality, and how does it compare with Claude Code, Codex, OpenCode?
- **Built:** Forge-driven battery (`scripts/battery*.py`), hill-climb campaign runner, S1 synthetic battery, S2 aider-polyglot (225 exercises), S3 SWE-bench Verified slice, `evals/STUDY-DESIGN.md` (sections 1-17), verdict layer, mechanism gates, receipts.
- **Numbers:** Battery (`docs/BATTERY-2026-09-18.md`): FD vs plain Amplifier same model, 20 tasks: time 0.68x (15 wins/5 losses, sign test p=0.041), cost 0.76x, 20/20 both; but Amplifier still 2-4x slower than Claude Code/Codex (about 14 s startup, about 50k-token system prompt). Hill-climb: HC03b effort routing 0.42x time / 0.59x cost on 2 tasks (screen; variance 39% between identical baselines). Polyglot screen (`docs/EVIDENCE.md`): plain 40/40 at 100 s; FD local judge 40/40 at 51 s; FD+routing 40/40 at 26 s; plain-on-Sonnet control 39/40 at 128 s (1 rep, screen).
- **Taught:** run-to-run variance dominates at 1 rep; controls (plain-on-Sonnet) are needed to separate model swap from mechanism; many "wins" were instrumentation bugs (HC03 gain was a classifier that never saw an explore phase; "three benchmark-validity defects" `ce05436`).
- **Open:** native three-arm Codex/Amplifier study (frozen 09-22) has no committed result.

### Phase C: Orchestrator-primary and levers (09-24 .. 09-25)
- **Question:** can a start-tier difficulty router + effort control save cost/time at equal quality? Do the per-step levers meet the goal (<=0.50x cost, <=0.60x full-model calls, <=0.70x time)?
- **Built:** `loop-fast-decisions`, `orchestrator.py`, `routing_levers.py`, `effort.py`, `levers.py` (keep-alive), `step_actions.py`, `planner.py`, `guards.py`/`waste.py`, `efficiency.py`, `savings.py`.
- **Numbers (`docs/RESULTS-2026-09-24.md`, `docs/evidence/2026-09-25/`):** holdout2 (12 fresh tasks, 3 reps, prereg, confirmed): Fable host 0.52x time [0.42-0.65], 0.49x cost, 11/12 faster, 36/36 pass; Opus host 0.80x time, 0.97x cost. S3 SWE-bench 10x3: plain 23/30 vs router 19/30 (fails non-inferiority) -> scope gate (`cheap_max_workspace_files: 300`); strong tier + phase effort 12/20 vs 14/20 (opt-in only). Haiku preset disqualified (failed `repair_roman_to_int` 4/6). Multi-turn dev screen: Opus cost 1.34-1.41x. Real-workload measurement 09-25 (`step-opportunity/summary.json`): 2,884 calls, $363.09, 61% cache read, 30% cache write, helpers 67% of spend; routing routine steps to Sonnet would ADD $17-46. Waste census (30 days, $13,924): deterministic waste ~6%. Waste-guards A/B (Opus, 3 reps): poll-wait saved $0.0558 (receipt $0.0514), quality 9/9 both arms. Keep-alive A/B: 330 s wait saved $0.16 (receipt 0.160384 = measured 0.160384).
- **Taught:** "decide once" beats switching (cache is per model); Opus cache reads ($0.20/M) are cheaper than Sonnet ($0.30/M). GOAL targets **not met** as of 09-25 (`docs/GOAL.md`).
- **Open:** holdout3 only preregistered (`docs/evidence/2026-09-25/holdout3/PREREGISTRATION.md`), no result committed; planner and step-actions remain opt-in.

### Phase D: Retrieval, CUA, delegation, Laya, harnesses (09-27 .. 09-29)
- **Built:** jevgrep (`jevgrep.py`, `modules/tool-jevgrep`), `jev_cua.py`/`cua_host.py`, `delegation.py` + `policies/delegation_v3.json`, `laya_*.py`, `anyjev_*.py`, `registry.py`.
- **Numbers:** Matched Amplifier example (`docs/evidence/2026-09-27-integration/REPORT.md`): 46.1% faster, 63.3% lower est. cost, 128/128 checks both arms, ONE small task x4 reps. Decision alternatives (`2026-09-28-decisions/REPORT.md`): prepared read 39% faster/45% cheaper on one task, 8% SLOWER on a repair task; jevgrep 38% faster, cost incomplete (retrieval charge unknown). Laya (`2026-09-29-laya-hosted/README.md`): Jev 56/60 vs Laya base 35/60 vs typed 34/60; fresh 30: 29 / 19 / 22. Four-harness Laya acceptance: all three capabilities ran, but select and cua abstained in every harness; "no avoided reasoning calls, dollar savings or end-to-end speedup demonstrated". Delegation routing (`docs/evidence/DELEGATION-ROUTING-STUDY.md`, 10,816 recorded delegations, $120.17 spend): v3 policy n=21 cost per accepted task -57%, wall 0.36x, depth-sufficiency preserved; generic preference rule FAILED (4/3/14); read-only agents only; Jev only. Live check: 2 sessions (shadow/enforce), pin appears; effort of child undetermined.
- **Taught:** local classifiers (Laya) are fast (10-84 ms) but not accurate enough; Jev restored as default. Retrieval helps latency but cost isn't measured.

### Phase E: Judge benchmark (09-30)
- **Question:** which fast model should make small decisions (Jev, Luna, Sol, Clef, local)?
- **Built:** `evals/judge_bench/`, `evals/judges.yaml`, STUDY-DESIGN 19, paper `docs/papers/2026-09-30-judge-benchmark/`.
- **Numbers (`docs/evidence/2026-09-30-judge-benchmark/README.md`):** holdout 63 cases, prereg `aec2457`: Jev 55/63, one wrong automatic, p50 about 155 ms / p95 about 220 ms, $18 per 1M decisions; Luna 60/63 (p95 1.8-1.9 s, 2.2x cost); Sol 62/63 (p95 3.6-4.7 s, 49x cost); neither difference survives Holm (p 0.16, 0.09). Host side-effect guard (I2) removed every side-effect wrong-automatic decision in 9/9 judges. No local judge qualified (best tev1-4B: 3 wrong automatic at 44% coverage). First-pass claims partly wrong (Luna 90/90 did not reproduce). Clef (post-hoc, `2026-10-04-clef-judges`): matched Jev accuracy at 3.2-4.4x cost, ~3x slower; Clef-Flash cheaper, less accurate.
- **Real traces (`2026-10-01-trace-judge-benchmark`):** 42 real read-shortcut decisions; **no judge met the usefulness bar**; Jev took 10/13 sufficient reads, 5 wrong (12%); state-budget clipped the task out of the judge's view (`FINDING-state-budget-clips-task.md`).
- **Four bundle defects fixed** (`a15c439`, `1f3b0e4`, #56 `180f919`).

### Phase F: Paired multi-turn campaign + effort controls (10-01 .. 10-05)
- **Question:** what does routing cost over realistic multi-turn sessions, with prompt cache accounted for?
- **Built:** `evals/paired*.py`, `evals/paired/` (70 scenarios), memguard, dashboard, paper `docs/papers/2026-10-02-paired-measurement/`.
- **Numbers (`docs/evidence/2026-10-02-paired-campaign/README.md`, `confirm/CONFIRM.md`):** 280 waves, 1,036 sessions, 52,437 requests, ledger $3,527.29; test split 23 scenarios, prereg. Fable: sticky 0.558x (0.493-0.643), shipped 0.629x, plain Sonnet 0.58x. Opus: sticky 1.249x, shipped 1.380x, Sonnet 1.433x. H3 sticky vs shipped: 0.862 (Fable), 0.917 (Opus). All 4 hypotheses confirmed; quality close to margin (Fable sticky lower bound -0.047 vs -0.05; final hidden tests 3.6-4.3 points worse, exploratory). Effort: Sonnet medium 0.821x (0.781-0.861), turn-pass -0.003 (`2026-10-05-effort-control/RESULT.md`, $250.13); Fable medium 0.860x (0.833-0.885), +0.033 turn-pass (`2026-10-06-effort-control-fable`, $421.71). Opus break-even cache-read about $0.34-0.38/M vs $0.20 today.
- **Taught:** most of the routed saving is the effort setting + model choice; router machinery added nothing on Sonnet sessions; peer reviews (rounds 1-2) forced withdrawal of an earlier "router adds little" claim and addition of the effort confound.
- **Shipped as a result (`d5602cf`, `9e4865e`, `672164c`):** price gate, decide once per session, `cheap: medium`. Offline replay (`182b354`, `docs/evidence/2026-10-05-defaults-replay/REPLAY.md`): Opus 140/140 not routed, Fable 140/140 equal recorded decision; gate sound across price sweep. Unmeasured: end-to-end cost of the shipped unrouted-Opus path.

### Phase G (now): the plateau
Open design question: what configuration should a general "system 1" decision smart tool have inside Amplifier and other harnesses. Evidence says: keep deterministic guards and effort/price-aware model choice; the judged read-shortcut and per-step prepared actions have weak or negative evidence; value of Jev beyond a simple rule is not established (rules-only router `orch-router-rules` was 0.55x time / 0.38x cost on S1 pre-scope-gate, 5 of 6 criteria, not confirmed; STUDY-DESIGN 18.8).

## 3. Lever inventory (current shipped default in `behaviors/fast-decisions.yaml` unless noted)

| Lever | Default | Evidence |
|---|---|---|
| `backend` | `jev` (1.13.0), `allow_external_state: true` | Judge benchmark holdout 55/63, p95 about 220 ms; Luna/Sol not significantly better; Clef not better (cost/latency). Laya rejected (35/60). |
| `read_shortcut` (judged prepared read) | `false` (library default True) | Rarely fired; trace study: no judge useful; 8% slower on repair task (`2026-09-28-decisions`); one task 39% faster. Weak/negative. |
| `suppress_completed_reads` | True | HC02a screen: no gain (1.03x/0.98x), not confirmed. |
| `min_probability`/`min_margin` gates | 0.90 / 0.20 | Not fitted; "accuracy flat across 0.50-0.95" per audits (`docs/EVIDENCE.md`); calibration tool exists (`afast bench calibrate`). |
| Start-tier routing `model_routing.start_policy` | `judge`, start model `claude-sonnet-5`, provider_match anthropic | Paired prereg: Fable sticky 0.558x; Opus 1.25x. holdout2 confirmed on single-turn. |
| `decision_scope` | `session` (library `turn`) | Paired H3: 0.862x Fable, 0.917x Opus vs per-turn. |
| `price_gate` | enabled | Replay PASS; Opus 140/140 not routed. Break-even Opus cache read $0.429/M (gate) vs $0.34-0.38 (paper). Constants 1.38 / 1.11 derived from 124 pairs each. |
| `cheap_max_workspace_files` scope gate | 300 | S3 19/30 vs 23/30 without it; with it config = plain on S3 (13/20 vs 14/20, 1 plain-only, noise). |
| Escalation (`max_requests_before_escalation`, `escalate_on_test_failure`, `escalate_on_provider_error`, `escalation_judge`, HC10 decomposed) | null / false / true / `rules` / off | Mid-turn escalation rebuilt cache (1.2x slower, 1.4x costlier); only provider-error escalation kept. HC10/HC11 no confirmed result. |
| `effort_routing.by_tier.cheap` | `medium` | Prereg 0.821x Sonnet, non-inferior. |
| `effort_routing.by_tier.strong` | `null` (opt-in `medium`; `phase`) | Fable medium 0.860x prereg; Opus unmeasured; `phase` on S3 12/20 vs 14/20 (opt-in). |
| `effort_routing` phases (orient medium/explore low/implement high, `monotonic`) | configured but tier overrides | HC03b screen 0.42x/0.59x (2 tasks); battery TUNE1 ~0.64x time (4 tasks); no holdout. |
| `phase_judge` (HC05) | off | no evidence of benefit |
| `decision_batching` HC08, `confidence_gates` HC09 | off | S3 screen candidate only; no confirmation |
| `keep_on_host.task_types` | off (example `[review, explain, feature]`) | Post hoc: Fable review -0.155, explain -0.143, feature -0.071 turn-pass; forfeits about $676 of $1,980 per 1,000 sessions; exploratory. |
| `profile` frugal/balanced/careful, `tiers`, `large_repo`, `strong_effort` (`routing_levers.py`) | balanced; others off | large-repo-v0 screen (n=30/arm; L2 read-only 0.70x exec, 0.86x cost 20/20; frugal ~0.3x cost with Haiku risk; L3 `strong_effort`: drop); prereg confirmation not run. |
| Easy-turn shaping (`easy_turn_guidance`, `easy_turn_hide_tools`) | off | Cut Haiku round trips 1.11x, not enough; Haiku preset disqualified. |
| `cache_keepalive` | on (270 s, <=6 refreshes, >=20k tokens) | Live A/B 330 s wait: $0.16 saved, receipt exact. Local ledger shows 194 receipts / $222.66 receipt-estimated (my aggregation; not measured). |
| Waste guards (repeat stop, retry stop, poll wait, identical-result pointer) | on, `poll_max_wait_s` 240 | A/B 9/9 quality; poll wait $0.056 saved; flaky never fired. Census: about 6% of spend addressable (2/3 one runaway loop). Local ledger: only 3 `loop_stop` receipts, $0.70. |
| Loop-stop nudges (`Policy.loop_stop`) | off | Receipts did not reconcile with A/B. |
| `step_actions.prepared` / `cheaper_model` (per-step) | off | Price/cache-aware math: Sonnet routine steps ADD $17-46 on Opus; local ledger `cheaper_model` net -$1.80, +417 s (238 prod receipts). |
| `planner` (turn planner, `model_routing.planner`) | off (opt-in) | Planner value cells: Opus 1.05x time, 1.17x cost; Fable 0.37x/0.61x (dev, 3 scenarios); no confirmation. |
| `delegation_routing` | off (`mode: off\|shadow\|enforce`, policy v3, deadline 750 ms) | -57% cost per accepted task (n=21), preference rule failed, read-only agents, Jev only. |
| `tool_risk_shadow` HC11 | off | record-only; no result |
| CUA (`jev_cua` tool, behavior `jev-cua`) | opt-in; Jev, gate 0.75, never executes | Live browser integration (1 call, 194-ish ms); "no avoided calls" in Laya cross-harness. Judge bench `cua-18` case. No savings. |
| Jevgrep (`behaviors/jevgrep`) | included by default, `jev` | one task 38% faster; retrieval charge unknown; exact-symbol task did not invoke it. |
| `decision_scope`/`keep_on_host` etc. persistence | `<events_dir>/session-route/` | tests only |
| Observatory | on, port 8765, opens browser | validation docs; no savings claim itself |
| `AFAST_TRAFFIC` test tagging | env | needed for ledger hygiene |

## 4. Harness inventory

| Harness | How exposed | Status / evidence |
|---|---|---|
| **Amplifier CLI (orchestrator mode)** | `bundle.md` / `behaviors/fast-decisions.yaml`: replaces orchestrator with `loop-fast-decisions` wrapping loop-streaming; hook module `hooks-fast-decisions`, tools `fast_workspace`, `jevgrep` | Most evidence: all studies above; real-kernel CI lane (`cf77185`); Forge live feature check #44; Laya/Jev native acceptance. |
| **Amplifier registry mode** (Unified, `loop-live`) | `behaviors/fast-decisions-registry.yaml`, hook `hooks-fast-decisions-router` (`registry.py`); `docs/REGISTRY-MODE.md` | Added #51-#53; tests + docs only found; no measured savings on Unified. In `~/dev/amplifier-unified` I found no fast-decisions code or docs. |
| **Amplifier shadow** (observer only) | `behaviors/fast-decisions-shadow.yaml`, `bundles/shadow.yaml` | Observatory data. |
| **Active read-shortcut rungs** | `bundles/active.yaml`, `active-routing.yaml`, `active-mlx.yaml` | Polyglot screen only (1 rep). |
| **Claude Code** | Smart Tool skill via `install-skill --host claude`; waste-guard PreToolUse/PostToolUse hook (`claude_hook.py`, `hooks_install.py`) | CLI invocation verified live 09-20 (commit `56799fb`) and 09-29 (Laya, Jev); hook exercised with `claude -p` on Haiku (retry stop denied, receipt `harness: "Claude Code"`). No end-to-end savings. |
| **Codex** | skill + `scripts/jev-route` (`docs/CODEX-JEV.md`), project `AGENTS.md`; shadow advice only | CLI verified; instruction-driven, not interception; native three-arm study has no result. |
| **OpenCode** | skill (`--host opencode`) + CLI | CLI verified only (4-harness smoke, `docs/SMART-TOOL.md`). |
| **Python library / CLI** | `amplifier_fast_decisions.smart_tool` (`manifest`, `describe`, `select`, `search`, `cua`); `smart-tool.json`; `src/amplifier_fast_decisions/SMART_TOOL.md` | Conformance tests (`tests/test_smart_tool.py`); real calls with Jev 09-29 (`2026-09-29-jev-default`: select 253 ms, search 1,818 ms, cua 194 ms). |
| **MCP** | not shipped ("MCP is not required or currently shipped", `docs/SMART-TOOL.md`; backlog B11) | none |
| **Rust/Node hosts** | Python object capability only (`docs/COMPATIBILITY.md`) | none |
| Backends | Jev (default), Laya (local/hosted/RunPod), Ollama qwen3:0.6b, MLX, AnyJev (opt-in, L2), hosted Qwen (AUC 0.85, median 0.63 s shared gateway), Luna/Sol/Clef as bench arms only | see phase E |

## 5. Open questions

1. Does any judge add value beyond a deterministic rule/`prompt length` router? Rules-only router (`orch-router-rules`) was 0.55x time / 0.38x cost on S1 (5 of 6 criteria) and the paired campaign found no router benefit beyond "use Sonnet"; the ablation "sticky/rules vs judge" at equal effort on a preregistered holdout is not run.
2. Opus 5.5 host: shipped path (no routing) is "expected, not measured" to cost the anchor; host effort medium on Opus unmeasured; the price table is dated 2026-06-10.
3. Quality: Fable sticky margin barely passes; routed arms lose 3.6-4.3 points on final hidden tests; keep_on_host task-type opt-out is post hoc.
4. Real-workload replay: goal of <=0.50x cost, <=0.60x calls, <=0.70x time at equal quality on the owner's real sessions is **not demonstrated** (GOAL.md status 09-25); holdout3 (preregistered, no result); large-repo L2 read-only routing confirmation not run.
5. Per-step levers (prepared actions, cheaper-step, planner) have no confirmatory evidence; ledger receipts vs measured only reconcile for keep-alive and poll-wait.
6. Judge costs are not in the paired session costs (about 0.05 cents per shipped session estimated); Jev/Jevgrep charges unmeasured in several studies.
7. External-state consent and privacy: default sends bounded state to TypeSafe (`allow_external_state: true`); offline tier "none qualifies" per judge bench; Laya hosted vs local quality.
8. Delegation routing: n=21, read-only, Jev-only, not pooled across policy rounds; live check only a mechanism check.
9. Cross-harness: automatic interception exists only in Amplifier; for Claude Code/Codex/OpenCode the tool is advisory and cannot remove a model turn; MCP surface absent. What is the "general smart tool" contract (select/search/cua/guards)?
10. Full SWE-bench Verified 4-arm comparison (2,000 runs) incomplete in repo; native Codex/Amplifier three-arm study has no result; Clef re-test if hosted nearby.
11. Observatory: no committed, privacy-safe summary of its week; mixing production and eval traffic before 09-25.
12. Stale doc banners (GOAL.md status, JEV-CUA.md, JEVGREP.md) still say Laya is default.
