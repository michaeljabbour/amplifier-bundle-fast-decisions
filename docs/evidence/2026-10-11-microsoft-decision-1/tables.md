### dev (90 cases, 3 reps x 2 option orders, label: screen)

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| microsoft-decision-1 | 3 s deadline | 84/90 = 0.933 | 5/90 = 0.056 (Wilson upper 0.124) | 73/90 = 0.811 | 0/540 | 292 | 392 | 4.4 |
| microsoft-decision-1 | no deadline | 84/90 = 0.933 | 5/90 = 0.056 (Wilson upper 0.124) | 73/90 = 0.811 | 0/540 | 292 | 392 | 4.4 |
| jev-1.13 | 3 s deadline | 85/90 = 0.944 | 3/90 = 0.033 (Wilson upper 0.093) | 69/90 = 0.767 | 0/540 | 232 | 284 | 15.9 |
| jev-1.13 | no deadline | 85/90 = 0.944 | 3/90 = 0.033 (Wilson upper 0.093) | 69/90 = 0.767 | 0/540 | 232 | 284 | 15.9 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = microsoft-decision-1 minus jev-1.13):

| metric | microsoft-decision-1 | jev-1.13 | diff [95% CI] | msd1 only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.933 | 0.944 | -0.011 [-0.067, +0.044] | 3 / 4 | 1.000 | 1.000 |
| wrong automatic | 0.056 | 0.033 | +0.022 [-0.022, +0.067] | 3 / 1 | 0.625 | 0.625 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| False | False | none | True (392) | True ($4 vs $16) | True | False |

### holdout (63 cases, 3 reps x 2 option orders, label: post-hoc (arms added after the preregistration; cases and scorer unchanged))

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| microsoft-decision-1 | 3 s deadline | 57/63 = 0.905 | 5/63 = 0.079 (Wilson upper 0.173) | 49/63 = 0.778 | 0/378 | 292 | 356 | 6.9 |
| microsoft-decision-1 | no deadline | 57/63 = 0.905 | 5/63 = 0.079 (Wilson upper 0.173) | 49/63 = 0.778 | 0/378 | 292 | 356 | 6.9 |
| jev-1.13 | 3 s deadline | 55/63 = 0.873 | 1/63 = 0.016 (Wilson upper 0.085) | 40/63 = 0.635 | 0/378 | 234 | 347 | 18.4 |
| jev-1.13 | no deadline | 55/63 = 0.873 | 1/63 = 0.016 (Wilson upper 0.085) | 40/63 = 0.635 | 0/378 | 234 | 347 | 18.4 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = microsoft-decision-1 minus jev-1.13):

| metric | microsoft-decision-1 | jev-1.13 | diff [95% CI] | msd1 only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.905 | 0.873 | +0.032 [-0.048, +0.111] | 4 / 2 | 0.688 | 0.688 |
| wrong automatic | 0.079 | 0.016 | +0.063 [+0.000, +0.143] | 5 / 1 | 0.219 | 0.219 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| True | False | none | True (355) | True ($7 vs $18) | True | False |

### trace-dev (21 cases, 3 reps x 2 option orders, label: screen)

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| microsoft-decision-1 | 3 s deadline | 16/21 = 0.762 | 4/21 = 0.190 (Wilson upper 0.400) | 15/21 = 0.714 | 0/126 | 316 | 551 | 29.8 |
| microsoft-decision-1 | no deadline | 16/21 = 0.762 | 4/21 = 0.190 (Wilson upper 0.400) | 15/21 = 0.714 | 0/126 | 316 | 551 | 29.8 |
| jev-1.13 | 3 s deadline | 16/21 = 0.762 | 3/21 = 0.143 (Wilson upper 0.346) | 14/21 = 0.667 | 0/126 | 239 | 523 | 43.2 |
| jev-1.13 | no deadline | 16/21 = 0.762 | 3/21 = 0.143 (Wilson upper 0.346) | 14/21 = 0.667 | 0/126 | 239 | 523 | 43.2 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = microsoft-decision-1 minus jev-1.13):

| metric | microsoft-decision-1 | jev-1.13 | diff [95% CI] | msd1 only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.762 | 0.762 | +0.000 [+0.000, +0.000] | 0 / 0 | 1.000 | 1.000 |
| wrong automatic | 0.190 | 0.143 | +0.048 [+0.000, +0.143] | 1 / 0 | 1.000 | 1.000 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| True | False | none | False (551) | True ($30 vs $43) | True | False |

### trace-holdout (42 cases, 3 reps x 2 option orders, label: post-hoc (arms added after the preregistration; cases and scorer unchanged))

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| microsoft-decision-1 | 3 s deadline | 25/42 = 0.595 | 8/42 = 0.190 (Wilson upper 0.333) | 18/42 = 0.429 | 0/252 | 312 | 378 | 31.8 |
| microsoft-decision-1 | no deadline | 25/42 = 0.595 | 8/42 = 0.190 (Wilson upper 0.333) | 18/42 = 0.429 | 0/252 | 312 | 378 | 31.8 |
| jev-1.13 | 3 s deadline | 23/42 = 0.548 | 5/42 = 0.119 (Wilson upper 0.250) | 15/42 = 0.357 | 0/252 | 239 | 326 | 46.1 |
| jev-1.13 | no deadline | 23/42 = 0.548 | 5/42 = 0.119 (Wilson upper 0.250) | 15/42 = 0.357 | 0/252 | 239 | 326 | 46.1 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = microsoft-decision-1 minus jev-1.13):

| metric | microsoft-decision-1 | jev-1.13 | diff [95% CI] | msd1 only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.595 | 0.548 | +0.048 [-0.071, +0.167] | 4 / 2 | 0.688 | 0.688 |
| wrong automatic | 0.190 | 0.119 | +0.071 [+0.000, +0.167] | 3 / 0 | 0.250 | 0.250 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| False | False | none | True (378) | True ($32 vs $46) | True | False |

