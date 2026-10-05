# Frozen for the S1 preregistration: R* and the candidate configs

Frozen at commit **`658f22810b508dd353d411a3bc1aacde06ae3dd9`**, committed **2026-10-05T13:47:42-04:00
(2026-10-05T17:47:42Z)** on `v3/program`, before any S1 session or holdout-v3 scenario exists.

| file | sha256 |
|---|---|
| `evals/v3/frozen_rule.json` | `fa01f97b26273a354f888f29cd21c43d92e91961eefbe8ebf46596a7673b8258` |
| `evals/v3/rules.py` (feature + intent classifier `intent-kw-v1`) | `9ff0e82c58d11c94d64997330b883ca42ac3758563fb228bee4b95d9c5997c5a` |

**R\*** (session-start decider, decided once): route the whole session to the cheap model (Sonnet 5, `medium`) unless
the starting workspace has more than 300 files (the shipped scope gate), in which case keep the host. No external call,
no consent needed. Fitted on the main-v1 train split only (47 scenarios x 2 reps, Fable host); the fitting floor was
chosen by 5-fold grouped cross-validation on train, which selected no floor because no fitted rule improved turn-pass
out of fold. An a-priori objective that was run first (`host if turn1_prompt_chars > 243`) is reported in
`docs/evidence/2026-10-v3-offline/a0-counterfactual/README.md` and is not used.

**C\*_F** (Fable 5.1 host): bundle, decide-once, decider R\*, price gate on, `cheap_max_workspace_files: 300`,
`effort_routing.by_tier: {cheap: medium, strong: medium}`, `keep_on_host` off. H2 comparator: Jev 1.13.0.
Predicted vs plain Fable (estimate from main-v1 potential outcomes): 0.508x [0.483, 0.536], turn-pass -0.019
[-0.052, +0.010].

**C\*_O** (Opus 5.5 host): shipped defaults (price gate closed, never routes) + `strong: medium`. Unmeasured; prior
band 0.821-0.860x.

d(Jev, R\*) on main-v1 = 0.10 (both hosts). Any change to these files after this commit is a deviation and must be
recorded in `prereg/PROVENANCE.md` with its reason.
