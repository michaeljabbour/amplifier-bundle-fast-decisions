# Data dictionary (pointer)

The rows are written by the same extractor (`evals/paired.py rows`) as the main-v1 campaign and have the same schema (`fast-decisions-paired/v1`). Field definitions, units and sign conventions:
[`../../2026-10-02-paired-campaign/data/DATA-DICTIONARY.md`](../../2026-10-02-paired-campaign/data/DATA-DICTIONARY.md). Differences for this campaign:

| file | rows | meaning |
|---|---:|---|
| `sessions.jsonl` | 1,224 | one per session; `arm` in anchor, anchor_m, ph, ph_m, shipped, shipped_m, pc, aa; `host` fable / opus / any (Pc); `rep` 1-2 |
| `turns.jsonl` | 12,856 | one per scripted turn |
| `pairs.jsonl` | 1,104 | arm vs the same-host anchor per scenario-rep; carries `arm_cache_audit_clean` and `anchor_cache_audit_clean` (the harness fix from the effort-control study) |
| `requests.jsonl.gz` | 49,254 | one per LLM request (`main` false = background request); the `model` field is the model that served it |
| `summary.json` | - | row counts and the audit lists (`cache_audit_flagged_sessions` 4, `mechanism_failed` 8, `cost_mismatch` 2, `killed_memory` 0); see `../FLAGS.md` |
| `FILES.json` | - | rows, bytes and sha256 of each file (published, content and raw unsanitized source) |

* `mechanism_engaged` / `mechanism_reasons` hold the per-session preregistered gate result; `wave_valid`, `cost_valid`, `cache_audit_clean` are the other validity inputs. The analysis reads `sessions.jsonl` only.
* `attempt` is the accepted wave attempt (1-4); earlier infrastructure-failed attempts are in `../campaign/state.json`, not in the rows.
* `cost_usd_tools_normalized` is the cost basis; the decider charge (`judge_usage` receipts x $1.8e-5) is added by the analysis. `scheduled_start`, `actual_start`, `concurrent_sessions` record the schedule.
* Sanitization: home prefix -> `~`, campaign root -> `<campaign>`; free-text failure tails replaced by length + hash; key fingerprints are short sha prefixes; there are no prompt or response fields.
