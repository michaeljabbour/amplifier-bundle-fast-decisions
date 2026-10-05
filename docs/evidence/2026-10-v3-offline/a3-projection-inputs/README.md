# A3 inputs: provisional real-workload projection (offline, $0)

Code: `evals/v3/a3_projection.py`. **Provisional, pre-S1: not the A3 result.** It combines the production workload A1
recorded with per-host ratios from A0 and the effort studies, each labelled measured / estimated / prior.

* Recorded production spend share: Opus 5.5 53%, Sonnet 5 46%, other 1%; no Fable-hosted production sessions.
* Shipped defaults on that mix: **1.00x** (the price gate never routes Opus; nothing applies to a Sonnet host).
* Candidate configs (Opus `strong: medium` prior 0.821-0.860, unmeasured; Sonnet medium 0.821 measured):
  **0.83x [0.80, 0.86]**, about $2.3k a month at the 30-day waste-census scale ($13,924). The GOAL cost target
  (<= 0.50x) is not met under any frozen candidate on this workload.
* Fable-host what-if (estimate): 49% of production sessions hit the scope gate, so with R\* the routable half would
  run at main-v1's 0.50x: 0.75x overall with `strong` default, 0.68x with `strong: medium`.

Reproduce: `python3 -m evals.v3.a3_projection` (reads the A0 and A1 outputs).
