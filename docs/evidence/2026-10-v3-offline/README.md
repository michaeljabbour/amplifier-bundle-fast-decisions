# v3 offline analyses (2026-10): A0, A1, A3 inputs

| dir | plan section | what | spend |
|---|---|---|---|
| `a0-counterfactual/` | A0 | potential-outcome pricing of every session-start decider on main-v1; R\* and the S1 candidate configs frozen (`evals/v3/frozen_rule.json`, `evals/v3/FROZEN.md`); the effort-switch cache finding | $0 |
| `a1-observatory/` | A1 (RQ1) | the observatory week and the whole store: traffic, event mix, decision census, shadow agreement decomposed, latency, receipts vs measured | $0 |
| `a3-projection-inputs/` | A3 (RQ11) | provisional projection inputs (pre-S1) | $0 |

Code: `evals/v3/` (stdlib only). Tests: `tests/test_v3_offline.py` (also guards this directory's sanitization).
Reproduce from the repository root:

    nice -n 10 python3 -m evals.v3.a0_counterfactual     # needs PyYAML (test extra) for scenario prompts
    nice -n 10 python3 -m evals.v3.a1_observatory        # needs the local store ~/.amplifier/fast-decisions/
    python3 -m evals.v3.a3_projection
    PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_v3_offline.py'

Sanitized: `~` for the home directory, no keys, no prompt or response text, no workspace names or labels.
`SHA256SUMS` covers every file here.
