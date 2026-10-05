# Review record: paired-measurement report

| File | What it is |
|---|---|
| `round1-review.md` | Round-1 external review points (reconstructed from the authors' response) |
| `round2-review.md` | Round-2 external review items (reconstructed from the authors' response) |
| `verification-round1.md` | The authors' check of every round-1 point against the committed evidence |
| `verification-scripts/` | The scripts behind that check (`common.py`, `c10.py` launch-offset regression, `c11.py` sticky vs Sonnet control). Run from the repository root: `cd docs/reviews/2026-10-paired-measurement/verification-scripts && FD_PAIRED_REPO=../../../.. python3 c11.py` |

The responses are Appendix C of `docs/papers/2026-10-02-paired-measurement/paired-measurement.pdf`. The scripts were
adapted only to read paths relative to the repository and to rebuild the request rows from `requests.jsonl.gz`.
