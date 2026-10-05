# Data dictionary (pointer)

The rows in this directory are written by the same extractor (`evals/paired.py rows`) as the main-v1 campaign and have the same schema
(`fast-decisions-paired/v1`). Field definitions, units and sign conventions are in
[`../../2026-10-02-paired-campaign/data/DATA-DICTIONARY.md`](../../2026-10-02-paired-campaign/data/DATA-DICTIONARY.md); only the differences are listed here.

| file | rows | meaning |
|---|---:|---|
| `sessions.jsonl` | 92 | one per session: 46 `sonnet` (provider-default effort, cell `plain-sonnet`) + 46 `sonnet_medium` (cell `plain-sonnet-medium`) |
| `turns.jsonl` | 1,032 | one per scripted turn |
| `pairs.jsonl` | 46 | one per scenario x rep; `arm` is always `sonnet_medium`, the anchor is `sonnet`; `delta_usd` / `log_cost_ratio` = medium minus default (negative: medium cheaper) |
| `requests.jsonl.gz` | 5,188 | one per main-loop LLM request |
| `summary.json` | - | row counts and audit lists (all empty: no cache-audit flags, mechanism failures, memory kills or cost mismatches) |
| `FILES.json` | - | row count, bytes and sha256 of each file above (published, content, and raw unsanitized source) |

Differences from main-v1:

* `host` is `any` on every row (Sonnet is host-independent), `split` is `test` on every row, `attempt` is 1 on every row (no retries), `sticky_decision` is null.
* The two arms differ only in provider reasoning effort: `sonnet_medium` sends `output_config.effort = medium` on main requests, `sonnet` sends none.
  The mechanism gate (`mechanism_engaged`) checks this and that every main request was served by Sonnet 5; it is true on every session.
* Cost basis is `cost_usd_tools_normalized`, as in main-v1.
