# Savings model

Saving = anchor cost - arm cost (positive = money saved). Ratios are arm / anchor, so 0.80 is a 20% saving. Intervals are 95% for estimates and 90% for predictions. Confidence intervals resample scenarios first, then reps.

Cost basis: normalized. 896 pairs, 895 valid for cost; by split {'test': 294, 'train': 602}; 0 pairs could not be joined to their sessions.

## A/A noise (anchor vs a second, identical anchor)

The mean log ratio should be about 0. Its SD is the run-to-run noise floor for one session.

| host | pairs | mean log ratio | 95% CI | SD log ratio | SD per session | centred on 0 |
|---|---|---|---|---|---|---|
| all | 55 | 0.007078 | -0.028 to 0.040 | 0.107067 | 0.075708 | True |
| fable | 28 | -0.03243 | -0.067 to 0.004 | 0.096974 | 0.068571 | True |
| opus | 27 | 0.048049 | 0.005 to 0.089 | 0.103048 | 0.072866 | False |

## Savings by arm and host

| arm | host | slice | valid pairs | scenarios | mean saving/session | median | cost ratio | 95% CI | saving | ratio (both pass) | d turn-pass | non-inferior | claim allowed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aa | all | all | 55 | 26 | $0.00 | -$0.02 | 1.007103 | 0.973 to 1.043 | -0.7% | 1.007401 | -0.0015 | True | True |
| aa | fable | all | 28 | 26 | $0.12 | $0.13 | 0.96809 | 0.935 to 1.004 | 3.2% | 0.966439 | 0.0042 | True | True |
| aa | opus | all | 27 | 25 | -$0.12 | -$0.10 | 1.049222 | 1.006 to 1.094 | -4.9% | 1.051777 | -0.0072 | True | True |
| shipped | all | all | 280 | 70 | $0.58 | $0.17 | 0.890957 | 0.826 to 0.961 | 10.9% | 0.895784 | -0.013 | True | True |
| shipped | fable | all | 140 | 70 | $1.75 | $1.75 | 0.632513 | 0.588 to 0.683 | 36.7% | 0.634675 | -0.0129 | True | True |
| shipped | opus | all | 140 | 70 | -$0.59 | -$0.44 | 1.255002 | 1.173 to 1.337 | -25.5% | 1.264317 | -0.0131 | True | True |
| sonnet | all | all | 280 | 70 | $0.50 | $0.13 | 0.922449 | 0.843 to 1.006 | 7.8% | 0.91894 | -0.0013 | True | True |
| sonnet | fable | all | 140 | 70 | $2.09 | $2.09 | 0.586681 | 0.550 to 0.625 | 41.3% | 0.586381 | -0.008 | True | True |
| sonnet | opus | all | 140 | 70 | -$1.10 | -$0.89 | 1.450385 | 1.345 to 1.569 | -45.0% | 1.450095 | 0.0054 | True | True |
| sticky | all | all | 280 | 70 | $0.75 | $0.25 | 0.819612 | 0.759 to 0.892 | 18.0% | 0.825952 | -0.0155 | True | True |
| sticky | fable | all | 140 | 70 | $1.98 | $2.03 | 0.559639 | 0.517 to 0.613 | 44.0% | 0.56679 | -0.0209 | False | False |
| sticky | opus | all | 140 | 70 | -$0.49 | -$0.32 | 1.200351 | 1.129 to 1.280 | -20.0% | 1.210663 | -0.0101 | True | True |

## By task type

| arm | host | slice | valid pairs | scenarios | mean saving/session | median | cost ratio | 95% CI | saving | ratio (both pass) | d turn-pass | non-inferior | claim allowed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aa | all | bugfix | 17 | 9 | $0.20 | $0.06 | 0.963654 | 0.912 to 1.021 | 3.6% | 0.960608 | -0.0118 | True | True |
| aa | all | docs | 2 | 1 | -$0.90 | -$0.90 | 1.18122 | n/a | -18.1% | 1.18122 | -0.0312 |  |  |
| aa | all | explain | 6 | 2 | $0.00 | -$0.04 | 1.017089 | 0.941 to 1.097 | -1.7% | 1.023643 | -0.0167 | False | False |
| aa | all | feature | 10 | 5 | $0.01 | -$0.01 | 0.985753 | 0.922 to 1.051 | 1.4% | 0.985753 | -0.0083 | True | True |
| aa | all | mixed | 18 | 8 | -$0.10 | -$0.07 | 1.039608 | 0.984 to 1.098 | -4.0% | 1.039608 | 0.0208 | True | True |
| aa | all | review | 2 | 1 | $0.08 | $0.08 | 1.014201 | n/a | -1.4% | 1.014201 | 0.0 |  |  |
| aa | fable | bugfix | 9 | 9 | $0.43 | $0.44 | 0.916525 | 0.871 to 0.965 | 8.3% | 0.905049 | -0.0007 | True | True |
| aa | fable | docs | 1 | 1 | -$1.09 | -$1.09 | 1.159465 | n/a | -15.9% | 1.159465 | 0.0 |  |  |
| aa | fable | explain | 3 | 2 | $0.14 | $0.27 | 0.96759 | 0.910 to 1.035 | 3.2% | 0.96759 | 0.0 | True | True |
| aa | fable | feature | 5 | 5 | $0.01 | -$0.07 | 0.981792 | 0.906 to 1.064 | 1.8% | 0.981792 | 0.0 | True | True |
| aa | fable | mixed | 9 | 8 | -$0.04 | $0.06 | 0.997571 | 0.950 to 1.063 | 0.2% | 0.997571 | 0.0139 | True | True |
| aa | fable | review | 1 | 1 | $0.38 | $0.38 | 0.942786 | n/a | 5.7% | 0.942786 | 0.0 |  |  |
| aa | opus | bugfix | 8 | 8 | -$0.07 | -$0.07 | 1.019577 | 0.949 to 1.090 | -2.0% | 1.019577 | -0.0229 | False | False |
| aa | opus | docs | 1 | 1 | -$0.70 | -$0.70 | 1.203382 | n/a | -20.3% | 1.203382 | -0.0625 |  |  |
| aa | opus | explain | 3 | 2 | -$0.13 | -$0.10 | 1.06912 | 0.985 to 1.147 | -6.9% | 1.113871 | -0.0333 | False | False |
| aa | opus | feature | 5 | 5 | $0.01 | $0.02 | 0.98973 | 0.943 to 1.040 | 1.0% | 0.98973 | -0.0167 | True | True |
| aa | opus | mixed | 9 | 8 | -$0.16 | -$0.19 | 1.083417 | 0.995 to 1.167 | -8.3% | 1.083417 | 0.0278 | True | True |
| aa | opus | review | 1 | 1 | -$0.22 | -$0.22 | 1.091025 | n/a | -9.1% | 1.091025 | 0.0 |  |  |
| shipped | all | bugfix | 72 | 18 | -$0.22 | -$0.44 | 1.178646 | 1.045 to 1.340 | -17.9% | 1.178646 | 0.0212 | True | True |
| shipped | all | docs | 16 | 4 | $1.21 | $1.16 | 0.697248 | 0.594 to 0.811 | 30.3% | 0.71815 | 0.0066 | True | True |
| shipped | all | explain | 12 | 3 | $1.24 | $0.78 | 0.596923 | 0.459 to 0.766 | 40.3% | 0.596923 | -0.1259 | False | False |
| shipped | all | feature | 52 | 13 | $0.76 | $0.03 | 0.900865 | 0.784 to 1.022 | 9.9% | 0.909633 | -0.0385 | False | False |
| shipped | all | mixed | 112 | 28 | $0.77 | $0.27 | 0.814234 | 0.726 to 0.899 | 18.6% | 0.810941 | -0.0015 | True | True |
| shipped | all | review | 16 | 4 | $1.18 | $0.80 | 0.790779 | 0.611 to 1.017 | 20.9% | 0.745068 | -0.0995 | False | False |
| shipped | fable | bugfix | 36 | 18 | $0.80 | $0.79 | 0.809676 | 0.726 to 0.899 | 19.0% | 0.809676 | 0.0253 | True | True |
| shipped | fable | docs | 8 | 4 | $2.26 | $2.10 | 0.523585 | 0.482 to 0.568 | 47.6% | 0.509861 | -0.0096 | False | False |
| shipped | fable | explain | 6 | 3 | $2.24 | $2.35 | 0.415624 | 0.332 to 0.551 | 58.4% | 0.415624 | -0.1611 | False | False |
| shipped | fable | feature | 26 | 13 | $2.02 | $1.74 | 0.657769 | 0.564 to 0.777 | 34.2% | 0.670521 | -0.0329 | False | False |
| shipped | fable | mixed | 56 | 28 | $1.94 | $1.87 | 0.590729 | 0.532 to 0.660 | 40.9% | 0.584059 | -0.0014 | True | True |
| shipped | fable | review | 8 | 4 | $3.01 | $3.15 | 0.48961 | 0.432 to 0.554 | 51.0% | 0.48961 | -0.0927 | False | False |
| shipped | opus | bugfix | 36 | 18 | -$1.24 | -$1.22 | 1.715757 | 1.545 to 1.899 | -71.6% | 1.715757 | 0.0172 | True | True |
| shipped | opus | docs | 8 | 4 | $0.16 | $0.18 | 0.928513 | 0.865 to 0.998 | 7.1% | 0.928513 | 0.0227 | True | True |
| shipped | opus | explain | 6 | 3 | $0.23 | $0.29 | 0.857307 | 0.758 to 0.987 | 14.3% | 0.857307 | -0.0907 | False | False |
| shipped | opus | feature | 26 | 13 | -$0.49 | -$0.43 | 1.233802 | 1.128 to 1.361 | -23.4% | 1.234013 | -0.0441 | False | False |
| shipped | opus | mixed | 56 | 28 | -$0.40 | -$0.26 | 1.122305 | 1.044 to 1.204 | -12.2% | 1.125959 | -0.0017 | True | True |
| shipped | opus | review | 8 | 4 | -$0.64 | -$0.57 | 1.277202 | 1.163 to 1.439 | -27.7% | 1.304136 | -0.1063 | False | False |
| sonnet | all | bugfix | 72 | 18 | -$0.54 | -$0.62 | 1.31254 | 1.130 to 1.541 | -31.3% | 1.301717 | 0.023 | True | True |
| sonnet | all | docs | 16 | 4 | $1.06 | $1.01 | 0.763803 | 0.632 to 0.941 | 23.6% | 0.780752 | 0.0217 | True | True |
| sonnet | all | explain | 12 | 3 | $1.30 | $1.07 | 0.581444 | 0.453 to 0.745 | 41.9% | 0.581444 | 0.0 | True | True |
| sonnet | all | feature | 52 | 13 | $0.90 | $0.25 | 0.895208 | 0.762 to 1.056 | 10.5% | 0.897933 | -0.0377 | False | False |
| sonnet | all | mixed | 112 | 28 | $0.80 | $0.28 | 0.802911 | 0.719 to 0.902 | 19.7% | 0.786801 | 0.008 | True | True |
| sonnet | all | review | 16 | 4 | $0.60 | $0.13 | 0.937993 | 0.727 to 1.225 | 6.2% | 0.937993 | -0.0812 | False | False |
| sonnet | fable | bugfix | 36 | 18 | $0.87 | $0.77 | 0.814064 | 0.728 to 0.905 | 18.6% | 0.807782 | 0.0264 | True | True |
| sonnet | fable | docs | 8 | 4 | $2.25 | $1.90 | 0.543043 | 0.506 to 0.577 | 45.7% | 0.541517 | 0.0085 | True | True |
| sonnet | fable | explain | 6 | 3 | $2.37 | $2.40 | 0.394997 | 0.355 to 0.436 | 60.5% | 0.394997 | -0.0167 | False | False |
| sonnet | fable | feature | 26 | 13 | $2.90 | $2.69 | 0.530733 | 0.493 to 0.569 | 46.9% | 0.533261 | -0.0562 | False | False |
| sonnet | fable | mixed | 56 | 28 | $2.41 | $2.19 | 0.525268 | 0.488 to 0.570 | 47.5% | 0.522769 | 0.0013 | True | True |
| sonnet | fable | review | 8 | 4 | $2.39 | $2.50 | 0.586509 | 0.512 to 0.684 | 41.3% | 0.586509 | -0.0812 | False | False |
| sonnet | opus | bugfix | 36 | 18 | -$1.95 | -$1.89 | 2.116248 | 1.887 to 2.347 | -111.6% | 2.097679 | 0.0195 | True | True |
| sonnet | opus | docs | 8 | 4 | -$0.13 | -$0.04 | 1.074307 | 0.934 to 1.243 | -7.4% | 1.125679 | 0.0348 | True | True |
| sonnet | opus | explain | 6 | 3 | $0.24 | $0.26 | 0.855898 | 0.749 to 0.986 | 14.4% | 0.855898 | 0.0167 | True | True |
| sonnet | opus | feature | 26 | 13 | -$1.10 | -$0.93 | 1.509983 | 1.392 to 1.651 | -51.0% | 1.511988 | -0.0193 | False | False |
| sonnet | opus | mixed | 56 | 28 | -$0.81 | -$0.33 | 1.22731 | 1.121 to 1.349 | -22.7% | 1.203324 | 0.0147 | True | True |
| sonnet | opus | review | 8 | 4 | -$1.19 | -$1.10 | 1.500116 | 1.341 to 1.697 | -50.0% | 1.500116 | -0.0812 | False | False |
| sticky | all | bugfix | 72 | 18 | $0.15 | -$0.23 | 1.035755 | 0.895 to 1.186 | -3.6% | 1.04655 | 0.0185 | True | True |
| sticky | all | docs | 16 | 4 | $1.44 | $1.38 | 0.648686 | 0.547 to 0.773 | 35.1% | 0.647258 | -0.0073 | True | True |
| sticky | all | explain | 12 | 3 | $1.33 | $1.01 | 0.575965 | 0.474 to 0.707 | 42.4% | 0.575965 | -0.1167 | False | False |
| sticky | all | feature | 52 | 13 | $0.80 | -$0.25 | 0.859921 | 0.719 to 1.024 | 14.0% | 0.865523 | -0.0511 | False | False |
| sticky | all | mixed | 112 | 28 | $0.86 | $0.35 | 0.750394 | 0.671 to 0.851 | 25.0% | 0.743808 | 0.0075 | True | True |
| sticky | all | review | 16 | 4 | $1.29 | $0.89 | 0.746684 | 0.574 to 0.968 | 25.3% | 0.805485 | -0.1464 | False | False |
| sticky | fable | bugfix | 36 | 18 | $1.35 | $1.21 | 0.680725 | 0.597 to 0.777 | 31.9% | 0.686906 | 0.0268 | True | True |
| sticky | fable | docs | 8 | 4 | $2.62 | $2.54 | 0.463938 | 0.432 to 0.503 | 53.6% | 0.463628 | -0.033 | False | False |
| sticky | fable | explain | 6 | 3 | $2.31 | $2.23 | 0.410938 | 0.373 to 0.459 | 58.9% | 0.410938 | -0.1426 | False | False |
| sticky | fable | feature | 26 | 13 | $2.18 | $2.32 | 0.581564 | 0.474 to 0.753 | 41.8% | 0.597339 | -0.0714 | False | False |
| sticky | fable | mixed | 56 | 28 | $2.02 | $2.23 | 0.525555 | 0.466 to 0.608 | 47.4% | 0.525424 | 0.0057 | True | True |
| sticky | fable | review | 8 | 4 | $3.01 | $2.90 | 0.483007 | 0.417 to 0.574 | 51.7% | 0.509856 | -0.1552 | False | False |
| sticky | opus | bugfix | 36 | 18 | -$1.04 | -$0.83 | 1.575952 | 1.407 to 1.762 | -57.6% | 1.575952 | 0.0102 | True | True |
| sticky | opus | docs | 8 | 4 | $0.26 | $0.21 | 0.907004 | 0.846 to 0.961 | 9.3% | 0.903619 | 0.0185 | True | True |
| sticky | opus | explain | 6 | 3 | $0.34 | $0.41 | 0.807263 | 0.749 to 0.880 | 19.3% | 0.807263 | -0.0907 | False | False |
| sticky | opus | feature | 26 | 13 | -$0.57 | -$0.52 | 1.271508 | 1.172 to 1.381 | -27.2% | 1.297112 | -0.0308 | False | False |
| sticky | opus | mixed | 56 | 28 | -$0.30 | -$0.11 | 1.071423 | 0.995 to 1.154 | -7.1% | 1.067411 | 0.0093 | True | True |
| sticky | opus | review | 8 | 4 | -$0.43 | -$0.37 | 1.154306 | 0.970 to 1.375 | -15.4% | 1.19205 | -0.1375 | False | False |

## By gap pattern

| arm | host | slice | valid pairs | scenarios | mean saving/session | median | cost ratio | 95% CI | saving | ratio (both pass) | d turn-pass | non-inferior | claim allowed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aa | all | 2+ long gaps | 17 | 9 | $0.06 | $0.06 | 1.002165 | 0.940 to 1.073 | -0.2% | 1.002165 | 0.0078 | True | True |
| aa | all | no long gap | 38 | 17 | -$0.03 | -$0.03 | 1.00932 | 0.968 to 1.049 | -0.9% | 1.009883 | -0.0059 | True | True |
| aa | fable | 2+ long gaps | 9 | 9 | $0.29 | $0.36 | 0.95229 | 0.903 to 1.011 | 4.8% | 0.95229 | 0.0224 | True | True |
| aa | fable | no long gap | 19 | 17 | $0.04 | $0.06 | 0.975665 | 0.936 to 1.021 | 2.4% | 0.973592 | -0.0044 | True | True |
| aa | opus | 2+ long gaps | 8 | 8 | -$0.20 | -$0.28 | 1.061403 | 0.981 to 1.146 | -6.1% | 1.061403 | -0.0067 | False | False |
| aa | opus | no long gap | 19 | 17 | -$0.09 | -$0.05 | 1.044135 | 0.994 to 1.096 | -4.4% | 1.047526 | -0.0075 | True | True |
| shipped | all | 2+ long gaps | 92 | 23 | $0.78 | $0.21 | 0.868478 | 0.777 to 0.968 | 13.2% | 0.876913 | -0.0183 | False | False |
| shipped | all | no long gap | 188 | 47 | $0.49 | $0.14 | 0.902169 | 0.814 to 0.992 | 9.8% | 0.905097 | -0.0104 | True | True |
| shipped | fable | 2+ long gaps | 46 | 23 | $2.04 | $2.03 | 0.642903 | 0.569 to 0.728 | 35.7% | 0.646951 | -0.0199 | False | False |
| shipped | fable | no long gap | 94 | 47 | $1.61 | $1.60 | 0.62749 | 0.574 to 0.690 | 37.3% | 0.628898 | -0.0095 | True | True |
| shipped | opus | 2+ long gaps | 46 | 23 | -$0.48 | -$0.45 | 1.173201 | 1.077 to 1.277 | -17.3% | 1.180239 | -0.0168 | False | False |
| shipped | opus | no long gap | 94 | 47 | -$0.64 | -$0.43 | 1.297086 | 1.189 to 1.419 | -29.7% | 1.308058 | -0.0113 | True | True |
| sonnet | all | 2+ long gaps | 92 | 23 | $0.73 | $0.46 | 0.896862 | 0.793 to 1.015 | 10.3% | 0.897619 | -0.0155 | False | False |
| sonnet | all | no long gap | 188 | 47 | $0.38 | $0.10 | 0.935236 | 0.832 to 1.050 | 6.5% | 0.930106 | 0.0056 | True | True |
| sonnet | fable | 2+ long gaps | 46 | 23 | $2.57 | $2.24 | 0.572283 | 0.528 to 0.618 | 42.8% | 0.573762 | -0.0263 | False | False |
| sonnet | fable | no long gap | 94 | 47 | $1.85 | $1.74 | 0.593858 | 0.545 to 0.650 | 40.6% | 0.593016 | 0.0009 | True | True |
| sonnet | opus | 2+ long gaps | 46 | 23 | -$1.11 | -$0.95 | 1.405531 | 1.273 to 1.558 | -40.6% | 1.418631 | -0.0047 | False | False |
| sonnet | opus | no long gap | 94 | 47 | -$1.09 | -$0.88 | 1.472854 | 1.330 to 1.631 | -47.3% | 1.466462 | 0.0103 | True | True |
| sticky | all | 2+ long gaps | 92 | 23 | $0.98 | $0.27 | 0.805282 | 0.708 to 0.918 | 19.5% | 0.808572 | -0.0104 | False | False |
| sticky | all | no long gap | 188 | 47 | $0.63 | $0.25 | 0.826717 | 0.747 to 0.917 | 17.3% | 0.834989 | -0.018 | True | True |
| sticky | fable | 2+ long gaps | 46 | 23 | $2.45 | $2.66 | 0.550178 | 0.483 to 0.642 | 45.0% | 0.553556 | -0.0228 | False | False |
| sticky | fable | no long gap | 94 | 47 | $1.75 | $1.74 | 0.564328 | 0.513 to 0.627 | 43.6% | 0.573603 | -0.02 | False | False |
| sticky | opus | 2+ long gaps | 46 | 23 | -$0.48 | -$0.41 | 1.178671 | 1.068 to 1.296 | -17.9% | 1.18107 | 0.0021 | False | False |
| sticky | opus | no long gap | 94 | 47 | -$0.49 | -$0.29 | 1.211106 | 1.111 to 1.319 | -21.1% | 1.226272 | -0.016 | True | True |

## By scripted turn count

| arm | host | slice | valid pairs | scenarios | mean saving/session | median | cost ratio | 95% CI | saving | ratio (both pass) | d turn-pass | non-inferior | claim allowed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aa | all | 9-12 | 23 | 11 | $0.06 | -$0.02 | 0.993087 | 0.945 to 1.038 | 0.7% | 0.992503 | -0.0229 | False | False |
| aa | all | <=8 | 22 | 10 | $0.05 | $0.03 | 0.99716 | 0.945 to 1.053 | 0.3% | 0.99716 | 0.017 | True | True |
| aa | all | >=13 | 10 | 5 | -$0.24 | -$0.30 | 1.063048 | 0.979 to 1.149 | -6.3% | 1.063048 | 0.0091 | True | True |
| aa | fable | 9-12 | 12 | 11 | $0.18 | $0.32 | 0.957059 | 0.905 to 1.010 | 4.3% | 0.952066 | -0.0069 | True | True |
| aa | fable | <=8 | 11 | 10 | $0.17 | $0.10 | 0.954112 | 0.921 to 0.991 | 4.6% | 0.954112 | 0.0114 | True | True |
| aa | fable | >=13 | 5 | 5 | -$0.13 | -$0.08 | 1.02744 | 0.922 to 1.144 | -2.7% | 1.02744 | 0.0154 | True | True |
| aa | opus | 9-12 | 11 | 10 | -$0.07 | -$0.10 | 1.033939 | 0.985 to 1.078 | -3.4% | 1.038971 | -0.0389 | False | False |
| aa | opus | <=8 | 11 | 10 | -$0.07 | -$0.03 | 1.04215 | 0.961 to 1.132 | -4.2% | 1.04215 | 0.0227 | True | True |
| aa | opus | >=13 | 5 | 5 | -$0.35 | -$0.31 | 1.099891 | 1.054 to 1.157 | -10.0% | 1.099891 | 0.0029 | True | True |
| shipped | all | 9-12 | 120 | 30 | $0.54 | $0.11 | 0.896954 | 0.798 to 1.010 | 10.3% | 0.912174 | -0.035 | False | False |
| shipped | all | <=8 | 88 | 22 | $0.28 | $0.12 | 0.929436 | 0.787 to 1.089 | 7.1% | 0.923624 | 0.0199 | True | True |
| shipped | all | >=13 | 72 | 18 | $1.03 | $0.44 | 0.836678 | 0.747 to 0.942 | 16.3% | 0.831055 | -0.0165 | False | False |
| shipped | fable | 9-12 | 60 | 30 | $1.72 | $1.62 | 0.638896 | 0.563 to 0.729 | 36.1% | 0.652775 | -0.0391 | False | False |
| shipped | fable | <=8 | 44 | 22 | $1.13 | $1.22 | 0.637405 | 0.556 to 0.730 | 36.3% | 0.637405 | 0.0199 | True | True |
| shipped | fable | >=13 | 36 | 18 | $2.57 | $2.47 | 0.616187 | 0.557 to 0.695 | 38.4% | 0.598439 | -0.0093 | True | True |
| shipped | opus | 9-12 | 60 | 30 | -$0.64 | -$0.57 | 1.259245 | 1.148 to 1.379 | -25.9% | 1.267192 | -0.0309 | False | False |
| shipped | opus | <=8 | 44 | 22 | -$0.57 | -$0.43 | 1.355263 | 1.183 to 1.549 | -35.5% | 1.375185 | 0.0199 | True | True |
| shipped | opus | >=13 | 36 | 18 | -$0.52 | -$0.27 | 1.136068 | 1.041 to 1.243 | -13.6% | 1.130646 | -0.0237 | False | False |
| sonnet | all | 9-12 | 120 | 30 | $0.57 | $0.26 | 0.908801 | 0.795 to 1.035 | 9.1% | 0.915745 | -0.0161 | False | False |
| sonnet | all | <=8 | 88 | 22 | $0.12 | $0.04 | 0.989848 | 0.830 to 1.197 | 1.0% | 0.976768 | 0.0312 | True | True |
| sonnet | all | >=13 | 72 | 18 | $0.84 | $0.35 | 0.867562 | 0.756 to 1.002 | 13.2% | 0.849777 | -0.0164 | False | False |
| sonnet | fable | 9-12 | 60 | 30 | $2.21 | $2.23 | 0.572475 | 0.521 to 0.634 | 42.8% | 0.577873 | -0.024 | False | False |
| sonnet | fable | <=8 | 44 | 22 | $1.17 | $1.34 | 0.625572 | 0.540 to 0.728 | 37.4% | 0.617843 | 0.0284 | True | True |
| sonnet | fable | >=13 | 36 | 18 | $3.02 | $2.99 | 0.565033 | 0.526 to 0.612 | 43.5% | 0.561026 | -0.0259 | False | False |
| sonnet | opus | 9-12 | 60 | 30 | -$1.08 | -$0.99 | 1.442718 | 1.293 to 1.610 | -44.3% | 1.451163 | -0.0083 | False | False |
| sonnet | opus | <=8 | 44 | 22 | -$0.93 | -$0.66 | 1.566245 | 1.341 to 1.853 | -56.6% | 1.544204 | 0.0341 | True | True |
| sonnet | opus | >=13 | 36 | 18 | -$1.33 | -$0.69 | 1.332069 | 1.180 to 1.505 | -33.2% | 1.323267 | -0.0069 | False | False |
| sticky | all | 9-12 | 120 | 30 | $0.70 | $0.12 | 0.837029 | 0.737 to 0.946 | 16.3% | 0.846399 | -0.0466 | False | False |
| sticky | all | <=8 | 88 | 22 | $0.57 | $0.28 | 0.823087 | 0.717 to 0.956 | 17.7% | 0.835553 | 0.0185 | True | True |
| sticky | all | >=13 | 72 | 18 | $1.04 | $0.32 | 0.787303 | 0.674 to 0.933 | 21.3% | 0.780582 | -0.0052 | True | True |
| sticky | fable | 9-12 | 60 | 30 | $1.95 | $2.21 | 0.576507 | 0.504 to 0.666 | 42.3% | 0.588906 | -0.0473 | False | False |
| sticky | fable | <=8 | 44 | 22 | $1.55 | $1.50 | 0.540141 | 0.487 to 0.597 | 46.0% | 0.547238 | 0.0199 | True | True |
| sticky | fable | >=13 | 36 | 18 | $2.55 | $3.55 | 0.556207 | 0.466 to 0.687 | 44.4% | 0.555412 | -0.027 | False | False |
| sticky | opus | 9-12 | 60 | 30 | -$0.55 | -$0.44 | 1.21528 | 1.113 to 1.336 | -21.5% | 1.23293 | -0.0459 | False | False |
| sticky | opus | <=8 | 44 | 22 | -$0.42 | -$0.30 | 1.25425 | 1.108 to 1.436 | -25.4% | 1.263274 | 0.017 | True | True |
| sticky | opus | >=13 | 36 | 18 | -$0.48 | -$0.22 | 1.114414 | 1.006 to 1.236 | -11.4% | 1.108769 | 0.0165 | True | True |

## Quality against the anchor, and where the cost comes from

Non-inferior means the 95% lower bound of the mean turn-pass difference is at least -0.05. McNemar compares the final hidden-test result: anchor-only passes vs arm-only passes.

| arm | host | arm pass | anchor pass | anchor-only / arm-only | McNemar p | d turn-pass 95% CI | cache-rebuild share of cost | switches/session | sessions with a switch | receipt saving/session |
|---|---|---|---|---|---|---|---|---|---|---|
| aa | all | 0.9464 | 1.0 | 3 / 0 | 0.25 | -0.018 to 0.015 | 0.0 | 0.0 | 0.0 | $0.00 |
| aa | fable | 0.9643 | 1.0 | 1 / 0 | 1.0 | -0.006 to 0.018 | 0.0 | 0.0 | 0.0 | $0.00 |
| aa | opus | 0.9286 | 1.0 | 2 / 0 | 0.5 | -0.030 to 0.014 | 0.0 | 0.0 | 0.0 | $0.00 |
| shipped | all | 0.9357 | 0.9679 | 11 / 2 | 0.0225 | -0.043 to 0.011 | 0.142487 | 1.507 | 0.568 | $0.00 |
| shipped | fable | 0.9357 | 0.9786 | 7 / 1 | 0.0703 | -0.045 to 0.017 | 0.170789 | 1.507 | 0.571 | $0.00 |
| shipped | opus | 0.9357 | 0.9571 | 4 / 1 | 0.375 | -0.046 to 0.017 | 0.105378 | 1.507 | 0.564 | $0.00 |
| sonnet | all | 0.9429 | 0.9679 | 9 / 2 | 0.0654 | -0.033 to 0.023 | 0.0 | 0.0 | 0.0 | $0.00 |
| sonnet | fable | 0.9429 | 0.9786 | 5 / 0 | 0.0625 | -0.042 to 0.022 | 0.0 | 0.0 | 0.0 | $0.00 |
| sonnet | opus | 0.9429 | 0.9571 | 4 / 2 | 0.6875 | -0.024 to 0.033 | 0.0 | 0.0 | 0.0 | $0.00 |
| sticky | all | 0.9393 | 0.9679 | 11 / 3 | 0.0574 | -0.045 to 0.010 | 0.0 | 0.0 | 0.0 | $0.00 |
| sticky | fable | 0.9429 | 0.9786 | 6 / 1 | 0.125 | -0.058 to 0.011 | 0.0 | 0.0 | 0.0 | $0.00 |
| sticky | opus | 0.9357 | 0.9571 | 5 / 2 | 0.4531 | -0.037 to 0.015 | 0.0 | 0.0 | 0.0 | $0.00 |

## Fitted model

Engine: **fallback** (numpy method-of-moments variance components + feasible GLS); 564 train pairs (splits ['train']); interactions with arm: False. Fixed effects use only information known before the session. Coefficient CIs are scenario-cluster bootstrap percentiles.

### Log cost ratio (arm term = log ratio at the reference host and task type, average size)

564 rows, 47 scenarios. Variance: scenario 0.01936073, scenario:rep 0.00828263, residual 0.03831304.

| term | estimate | model SE | bootstrap 95% CI |
|---|---|---|---|
| arm=shipped | -0.52557 | 0.050002 | -0.6584 to -0.3835 |
| arm=sonnet | -0.486493 | 0.050002 | -0.6129 to -0.3502 |
| arm=sticky | -0.592694 | 0.050002 | -0.7114 to -0.4477 |
| host=opus | 0.765499 | 0.021165 | 0.7117 to 0.8149 |
| task_type=bugfix | 0.237047 | 0.091047 | -0.0266 to 0.4707 |
| task_type=docs | -0.116242 | 0.087578 | -0.2662 to 0.0159 |
| task_type=explain | -0.378682 | 0.162949 | -0.4814 to 0.0000 |
| task_type=feature | 0.040059 | 0.070806 | -0.1139 to 0.1750 |
| task_type=review | -0.066037 | 0.119361 | -0.1955 to 0.0422 |
| turns | 0.044692 | 0.024432 | -0.0106 to 0.1002 |
| long_gap | -0.086868 | 0.050573 | -0.2052 to 0.0296 |
| log_turn1 | 0.10123 | 0.03626 | 0.0231 to 0.1923 |

### Delta $ as a share of predicted anchor cost (arm term negative = saves)

564 rows, 47 scenarios. Variance: scenario 0.01484351, scenario:rep 0.03917823, residual 0.05855303.

| term | estimate | model SE | bootstrap 95% CI |
|---|---|---|---|
| arm=shipped | -0.355823 | 0.056743 | -0.4742 to -0.2136 |
| arm=sonnet | -0.253974 | 0.056743 | -0.3916 to -0.1157 |
| arm=sticky | -0.394285 | 0.056743 | -0.5221 to -0.2353 |
| host=opus | 0.719733 | 0.035339 | 0.6178 to 0.8313 |
| task_type=bugfix | 0.177044 | 0.099684 | -0.0828 to 0.4559 |
| task_type=docs | -0.14906 | 0.095885 | -0.2916 to 0.0187 |
| task_type=explain | -0.319131 | 0.178407 | -0.4089 to 0.0000 |
| task_type=feature | -0.073065 | 0.077523 | -0.2236 to 0.0817 |
| task_type=review | -0.111065 | 0.130683 | -0.2283 to 0.0000 |
| turns | 0.052408 | 0.02675 | -0.0089 to 0.1172 |
| long_gap | -0.118298 | 0.05537 | -0.2348 to -0.0148 |
| log_turn1 | 0.132649 | 0.039699 | 0.0260 to 0.2470 |

### Anchor cost submodel (log $ per session, anchor + aa sessions)

225 rows, 47 scenarios. Variance: scenario 0.03476785, scenario:rep 0.0, residual 0.02153495.

| term | estimate | model SE | bootstrap 95% CI |
|---|---|---|---|
| intercept | 1.325818 | 0.061434 | 1.1594 to 1.4994 |
| host=opus | -0.89498 | 0.019574 | -0.9364 to -0.8527 |
| task_type=bugfix | 0.434937 | 0.114979 | 0.1360 to 0.6759 |
| task_type=docs | -0.033524 | 0.111265 | -0.3059 to 0.3093 |
| task_type=explain | 0.063753 | 0.203569 | -0.0546 to 0.1884 |
| task_type=feature | 0.359371 | 0.089695 | 0.1416 to 0.6035 |
| task_type=review | 0.445982 | 0.150627 | -0.0000 to 0.6559 |
| turns | 0.322701 | 0.030726 | 0.2544 to 0.4155 |
| long_gap | 0.159134 | 0.064044 | 0.0081 to 0.3130 |
| log_turn1 | -0.141474 | 0.046514 | -0.2373 to -0.0280 |

## Prediction on the test split

276 test pairs from 23 scenarios; 90% prediction intervals from 4000 draws. Checks follow the design doc (coverage 0.83-0.97, total inside the interval, slope 0.7-1.3).

| check | value | pass |
|---|---|---|
| 90% PI coverage, log ratio | 0.9601 | True |
| 90% PI coverage, saving $ (delta model) | 0.9348 | True |
| 90% PI coverage, saving $ (ratio model, c_hat fixed) | 0.8732 |  |
| measured total inside predicted total PI | $180.35 in 63 to 251 | True |
| calibration slope (measured on predicted saving) | 0.829 | True |
| mean error, saving $/session (pred - measured) | -0.0663 |  |
| mean error, log ratio (pred - measured) | 0.005509 |  |

### Per arm and host, and per 1,000 sessions with this test mix

| arm / host | pairs | PI coverage (log) | PI coverage ($) | measured total | predicted total | total PI90 | inside | per 1,000 sessions | PI90 (1,000 sessions) |
|---|---|---|---|---|---|---|---|---|---|
| shipped / fable | 46 | 0.9565 | 0.9783 | $85.01 | $93.57 | 65 to 121 | True | $2,081.64 | 1,594 to 2,447 |
| shipped / opus | 46 | 1.0 | 0.9783 | -$31.48 | -$32.64 | -45 to -20 | True | -$687.74 | -909 to -528 |
| sonnet / fable | 46 | 0.9348 | 0.9348 | $94.95 | $69.18 | 40 to 95 | True | $1,548.89 | 1,072 to 1,903 |
| sonnet / opus | 46 | 0.9565 | 0.8261 | -$46.80 | -$42.51 | -57 to -29 | True | -$905.43 | -1,193 to -698 |
| sticky / fable | 46 | 0.913 | 0.9348 | $99.82 | $103.13 | 71 to 132 | True | $2,282.82 | 1,720 to 2,730 |
| sticky / opus | 46 | 1.0 | 0.9565 | -$21.15 | -$28.69 | -42 to -17 | True | -$605.53 | -829 to -436 |

