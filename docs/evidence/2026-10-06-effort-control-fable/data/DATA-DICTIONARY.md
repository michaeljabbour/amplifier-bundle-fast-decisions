# Data dictionary (pointer)

The rows in this directory are written by the same extractor (`evals/paired.py rows`) as the main-v1 campaign and have the same schema
(`fast-decisions-paired/v1`). Field definitions, units and sign conventions are in
[`../../2026-10-02-paired-campaign/data/DATA-DICTIONARY.md`](../../2026-10-02-paired-campaign/data/DATA-DICTIONARY.md); only the differences are listed here.

| file | rows | meaning |
|---|---:|---|
| `sessions.jsonl` | 92 | one per session: 46 `fable` (provider-default effort, cell `plain`) + 46 `fable_medium` (cell `plain-medium`) |
| `turns.jsonl` | 1,032 | one per scripted turn |
| `pairs.jsonl` | 46 | one per scenario x rep; `arm` is always `fable_medium`, the anchor is `fable`; `delta_usd` / `log_cost_ratio` = medium minus default (negative: medium cheaper) |
| `requests.jsonl.gz` | 4,032 | one per main-loop LLM request |
| `summary.json` | - | row counts and audit lists: `cache_audit_flagged_sessions` = [go-linkedlist-r1-any-fable], `killed_memory` = [py-go-counting-r2-any-fable]; `mechanism_failed` and `cost_mismatch` are empty (see `../FLAGS.md`) |
| `FILES.json` | - | row count, bytes and sha256 of each file above (published, content, and raw unsanitized source) |

Differences from main-v1:

* `host` is `any` on every row (Fable is the single host), `split` is `test` on every row, `attempt` is 1 on every row (no retries), `sticky_decision` is null.
* The two arms differ only in provider reasoning effort: `fable_medium` sends `output_config.effort = medium` on main requests, `fable` sends none.
  The mechanism gate (`mechanism_engaged`) checks this and that every main request was served by Fable 5.1; it is true on every session.
* `killed_memory` / `killed_memory_info` / `cost_valid` on `sessions.jsonl`: one session (py-go-counting-r2-any-fable, the default-effort arm) was stopped by the
  memory watchdog; it is kept, flagged, and `cost_valid` is false, which makes its pair cost-invalid (`pairs.jsonl`: `cost_valid` false, `valid` false).
* `pairs.jsonl` `cache_audit_clean` reflects the ARM session only for this campaign (the extractor was later fixed to require both sessions and to add
  `arm_cache_audit_clean` / `anchor_cache_audit_clean`); the anchor flag is in `sessions.jsonl`. See `../FLAGS.md`.
* Cost basis is `cost_usd_tools_normalized`, as in main-v1.
