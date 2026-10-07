### dev (90 cases, 3 reps x 2 option orders, label: screen)

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| luna-decisions | 3 s deadline | 88/90 = 0.978 | 0/90 = 0.000 (Wilson upper 0.041) | 64/90 = 0.711 | 4/540 | 1798 | 4796 | 20.3 |
| luna-decisions | no deadline | 88/90 = 0.978 | 0/90 = 0.000 (Wilson upper 0.041) | 65/90 = 0.722 | 4/540 | 1798 | 4796 | 20.3 |
| jev-1.13 | 3 s deadline | 86/90 = 0.956 | 3/90 = 0.033 (Wilson upper 0.093) | 68/90 = 0.756 | 0/540 | 1460 | 4462 | 15.9 |
| jev-1.13 | no deadline | 86/90 = 0.956 | 3/90 = 0.033 (Wilson upper 0.093) | 69/90 = 0.767 | 0/540 | 1460 | 4462 | 15.9 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = luna-decisions minus jev-1.13):

| metric | luna-decisions | jev-1.13 | diff [95% CI] | luna only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.978 | 0.956 | +0.022 [-0.022, +0.067] | 3 / 1 | 0.625 | 0.625 |
| wrong automatic | 0.000 | 0.033 | -0.033 [-0.078, +0.000] | 0 / 3 | 0.250 | 0.250 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| True | True | none | False (4796) | True ($20 vs $16) | False | False |

### holdout (63 cases, 3 reps x 2 option orders, label: post-hoc (arms added after the preregistration; cases and scorer unchanged))

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| luna-decisions | 3 s deadline | 59/63 = 0.937 | 1/63 = 0.016 (Wilson upper 0.085) | 43/63 = 0.683 | 5/378 | 1473 | 3439 | 25.6 |
| luna-decisions | no deadline | 59/63 = 0.937 | 1/63 = 0.016 (Wilson upper 0.085) | 44/63 = 0.698 | 5/378 | 1473 | 3439 | 25.6 |
| jev-1.13 | 3 s deadline | 55/63 = 0.873 | 1/63 = 0.016 (Wilson upper 0.085) | 40/63 = 0.635 | 1/378 | 1569 | 3730 | 18.4 |
| jev-1.13 | no deadline | 55/63 = 0.873 | 1/63 = 0.016 (Wilson upper 0.085) | 40/63 = 0.635 | 1/378 | 1569 | 3730 | 18.4 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = luna-decisions minus jev-1.13):

| metric | luna-decisions | jev-1.13 | diff [95% CI] | luna only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.937 | 0.873 | +0.063 [-0.016, +0.159] | 6 / 2 | 0.289 | 0.289 |
| wrong automatic | 0.016 | 0.016 | +0.000 [-0.048, +0.048] | 1 / 1 | 1.000 | 1.000 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| True | False | none | False (3439) | True ($26 vs $18) | False | False |

### trace-dev (21 cases, 3 reps x 2 option orders, label: screen)

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| luna-decisions | 3 s deadline | 16/21 = 0.762 | 2/21 = 0.095 (Wilson upper 0.289) | 10/21 = 0.476 | 0/126 | 1679 | 3235 | 71.8 |
| luna-decisions | no deadline | 16/21 = 0.762 | 2/21 = 0.095 (Wilson upper 0.289) | 10/21 = 0.476 | 0/126 | 1679 | 3235 | 71.8 |
| jev-1.13 | 3 s deadline | 16/21 = 0.762 | 3/21 = 0.143 (Wilson upper 0.346) | 14/21 = 0.667 | 1/126 | 1404 | 4067 | 43.2 |
| jev-1.13 | no deadline | 16/21 = 0.762 | 3/21 = 0.143 (Wilson upper 0.346) | 14/21 = 0.667 | 1/126 | 1404 | 4067 | 43.2 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = luna-decisions minus jev-1.13):

| metric | luna-decisions | jev-1.13 | diff [95% CI] | luna only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.762 | 0.762 | +0.000 [-0.143, +0.143] | 1 / 1 | 1.000 | 1.000 |
| wrong automatic | 0.095 | 0.143 | -0.048 [-0.143, +0.000] | 0 / 1 | 1.000 | 1.000 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| False | True | none | False (3235) | True ($72 vs $43) | True | False |

### trace-holdout (42 cases, 3 reps x 2 option orders, label: post-hoc (arms added after the preregistration; cases and scorer unchanged))

| arm | view | accuracy | wrong automatic | coverage | invalid | p50 ms | p95 ms | $/1M decisions |
|---|---|---|---|---|---|---|---|---|
| luna-decisions | 3 s deadline | 30/42 = 0.714 | 1/42 = 0.024 (Wilson upper 0.123) | 7/42 = 0.167 | 0/252 | 1414 | 3002 | 76.3 |
| luna-decisions | no deadline | 30/42 = 0.714 | 1/42 = 0.024 (Wilson upper 0.123) | 7/42 = 0.167 | 0/252 | 1414 | 3002 | 76.3 |
| jev-1.13 | 3 s deadline | 23/42 = 0.548 | 5/42 = 0.119 (Wilson upper 0.250) | 15/42 = 0.357 | 2/252 | 1387 | 3436 | 46.1 |
| jev-1.13 | no deadline | 23/42 = 0.548 | 5/42 = 0.119 (Wilson upper 0.250) | 15/42 = 0.357 | 2/252 | 1387 | 3436 | 46.1 |

Paired contrast (McNemar exact on per-case majority; rule-1 family, Holm over its tests; diff = luna-decisions minus jev-1.13):

| metric | luna-decisions | jev-1.13 | diff [95% CI] | luna only / jev only | p | Holm p |
|---|---|---|---|---|---|---|
| accuracy | 0.714 | 0.548 | +0.167 [+0.048, +0.310] | 8 / 1 | 0.039 | 0.039 |
| wrong automatic | 0.024 | 0.119 | -0.095 [-0.190, -0.024] | 0 / 4 | 0.125 | 0.125 |

Rule-1 (replace Jev as default) checks against the preregistered thresholds:

| non-inferior accuracy (lower CI > -0.05) | non-inferior wrong-auto (upper CI < 0.03) | superior on | p95 <= 500 ms | cost <= 2x Jev | valid >= 98% | replaces default |
|---|---|---|---|---|---|---|
| True | True | accuracy | False (3002) | True ($76 vs $46) | True | False |

