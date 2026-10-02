# Data dictionary

Fields of the campaign rows written by `evals/paired.py rows` (`session_row`, `build_pairs`, `extract_rows`).
Costs are USD. Tokens are counts. `ms` are milliseconds; times are UTC ISO unless stated.
The primary cost basis is **tools-normalized** (`cost_usd_tools_normalized`, pairs `delta_usd`/`log_cost_ratio`); the
raw (recomputed, un-normalized) basis is kept next to it. Sign convention: `delta_usd` = arm - anchor, so negative is cheaper.

## Files, row counts, checksums

| file | rows | bytes | sha256 (as published) | sha256 of the uncompressed content | sha256 of the raw (unsanitized) source |
|---|---:|---:|---|---|---|
| `sessions.jsonl` | 1036 | 3609944 | `21dd0a6449c8aa4b6cf0ee43a93bc009cdf62645df9d2e54d910294785a13397` | `21dd0a6449c8aa4b6cf0ee43a93bc009cdf62645df9d2e54d910294785a13397` | `82b9bc7d2c68c5a67a95b29359072548e2e59a95cd0e2936d0541463a824e51e` |
| `turns.jsonl` | 11588 | 9531034 | `27c4699085a33d35046e398ef010b541c25f33ce43adce3f373d46bd5743e87d` | `27c4699085a33d35046e398ef010b541c25f33ce43adce3f373d46bd5743e87d` | `27c4699085a33d35046e398ef010b541c25f33ce43adce3f373d46bd5743e87d` |
| `pairs.jsonl` | 896 | 548041 | `af0410f5bc729a558a21ed765e95e3031140e7224c6966561d107ec01b2202db` | `af0410f5bc729a558a21ed765e95e3031140e7224c6966561d107ec01b2202db` | `af0410f5bc729a558a21ed765e95e3031140e7224c6966561d107ec01b2202db` |
| `requests.jsonl.gz` | 52437 | 1526534 | `ddf4f7882a16aada969cda0325ab63c43c11cdcce869e286f95202a0e52fcd6d` | `97b784182d1e58717d5120b5d036a6b0dd30a7bea3c55cd513567107b1f2eb12` | `97b784182d1e58717d5120b5d036a6b0dd30a7bea3c55cd513567107b1f2eb12` |
| `summary.json` | 1 object | 294 | `9e92f66ccf6998560be0a65c943a3f859ed0905eed1cb6f7e0a0259cdef3ee5f` | | `9e92f66ccf6998560be0a65c943a3f859ed0905eed1cb6f7e0a0259cdef3ee5f` |

The published files differ from the raw ones only where a path was rewritten (see `reproduce/package_evidence.py`):
`provider_module.path` and `provider_module.git_root` in sessions rows. Every other byte is unchanged;
`requests.jsonl.gz` is deterministic gzip (mtime 0, level 9).

## sessions (1036 rows)

| field | type | meaning |
|---|---|---|
| `schema` | str | Row schema id, always `fast-decisions-paired/v1`. |
| `session_key` | str | Unique session id `<scenario>-r<rep>-<host|any>-<arm>`; also the run directory name in the raw tree. |
| `wave_id` | str | `<scenario>-r<rep>-<host>`. All sessions of one wave start together from the same frozen workspace; the unit that is retried when infrastructure fails. |
| `attempt` | int | Number of the wave attempt that was accepted. 1 for 941 sessions; 2, 3 and 4 mean earlier attempts of the wave failed on infrastructure and were rerun (see campaign/FAILURES.md). Failed attempts are not in the data. |
| `scenario_id` | str | Scenario (task script) id. |
| `scenario_hash` | str | sha256 of the scenario spec (task, turns, checks); checked against schedule.json at launch. |
| `source` | str | Human-readable provenance of the task (upstream repo / benchmark), not prompt text. |
| `task_type` | str | Scenario family: bugfix, feature, docs, explain, review, mixed. |
| `language` | str | Main language of the workspace. |
| `split` | str | Preregistered split, `train` or `test` (prereg/SPLIT.md). |
| `host` | str | Host model stratum of the pair: `opus` or `fable`; `any` for the Sonnet control, which is host-independent and is paired against both hosts' anchors. |
| `host_model` | str | Model id the session requested (anchor/aa: the host; shipped/sticky: the host, which the policy may override per request; sonnet: Sonnet). |
| `arm` | str | `anchor` (plain host model, A0), `aa` (second anchor on a 20% subsample, noise floor), `shipped` (orch-default fast-decisions profile), `sticky` (model chosen once at session start, never switched), `sonnet` (plain Sonnet control). |
| `kind` | str | Mechanism class used by the mechanism gate: `plain`, `fd`, `sticky`, `control`. |
| `cell` | str | Profile cell id (evals/paired/main-v1.yaml), e.g. `plain-opus`, `orch-default-opus`. |
| `rep` | int | Repetition 1 or 2 of the scenario/host cell. |
| `sticky_decision` | NoneType/str | Sticky arm only: `cheap` or `host`, decided once from the turn-1 prompt (campaign/decisions.jsonl); null for other arms. |
| `scripted_turns` | int | Number of scripted user turns in the scenario. |
| `gap_schedule` | list | Seconds of idle time before each turn (0, 10 s steps, 420 s long gaps that outlast the 5-minute cache TTL). |
| `n_long_gaps` | int | Number of gaps of 5 minutes or more in gap_schedule. |
| `turn1_prompt_chars` | int | Length in characters of the first user prompt (the text itself is not published). |
| `total_prompt_chars` | int | Total characters over all scripted prompts. |
| `workspace_files` | int | File count of the frozen starting workspace. |
| `workspace_bytes` | int | Total bytes of the frozen starting workspace. |
| `swe_difficulty` | NoneType | Reserved for SWE-bench difficulty; always null in this campaign. |
| `build_sha` | str | Git sha of the candidate source frozen at plan time (the preregistration commit). |
| `bundle_tree_sha` | str | sha256 over the frozen candidate source tree. |
| `price_table_sha` | str | First 16 hex of sha256 of the price table (`savings.DEFAULT_RATES`, JSON, sorted keys) used to recompute costs. |
| `nonce_mode` | str | `per_session`: every session carries its own cache-isolation nonce at the start of the system prompt. |
| `plan_id` | str | Id of the plan in campaign/schedule.json. |
| `provider_module` | dict | Provider module actually imported: module name, version, git sha (paths sanitized). |
| `campaign_provider` | dict | Provider entry injected for the campaign: id, source, and the NAMES of its config keys (no values). |
| `preflight_ok` | bool | Whether the freshest preflight (campaign/preflight.json) passed. |
| `nonce` | str | The session's UUID cache nonce. |
| `key_fingerprint` | str | 10-hex sha prefix of the API key used; identical on every session (one shared key). |
| `model_ids` | list | Model id list requested for the session (host model). |
| `served_models` | list | Distinct model ids that served main-loop requests; two entries mean the policy routed some requests elsewhere. |
| `served_model_check` | bool | True when every served model matches the requested one (always true for fd/sticky arms, which route on purpose). |
| `cost_usd_provider` | float | USD summed from the provider-reported per-request cost over ALL requests (main and background). |
| `cost_usd_recomputed` | float | USD recomputed from token counts and the price table over all requests. |
| `cost_usd_tools_normalized` | float | PRIMARY cost basis: recomputed cost with the shared tools prefix on the first request of each (model, effort) repriced from cache write to cache read (production-realistic warm tools). |
| `tools_repriced_tokens` | float | Tokens moved from the write rate to the read rate by the tools normalization. |
| `tools_normalized_delta_usd` | float | USD change from normalization (<= 0); cost_usd_tools_normalized = cost_usd_recomputed + this. |
| `cost_mismatch` | bool | True when |provider - recomputed| > 1e-6 USD or any request was unpriced. False on every session. |
| `unpriced_requests` | int | Requests whose model is missing from the price table. |
| `tokens` | dict | Main-loop token totals per served model: `input` (uncached input), `cache_read`, `cache_write`, `output`. |
| `n_req` | int | Main-loop LLM requests (requests carrying tools). |
| `n_bg` | int | Background LLM requests (no tools, e.g. session naming); billed in cost fields, excluded from `tokens`. |
| `wall_ms` | float | Sum of the per-turn elapsed milliseconds (includes the scripted gaps). |
| `exec_ms` | float | Sum over main requests of request-to-response time (milliseconds). |
| `model_switches` | int | Changes of model between consecutive main requests. |
| `switches_turn_boundary` | int | Switches that fall between two turns. |
| `switches_midturn` | int | Switches inside a turn. |
| `rebuild_write_tokens` | float | Cache-write tokens on requests that followed a switch. |
| `rebuild_excess_write_tokens` | float | Of those, write tokens above what the new content explains (pure cache rebuild). |
| `rebuild_usd` | float | USD premium of the excess rebuild writes over the read rate. |
| `cache_hit_share` | float | cache_read / (uncached + cache_read + cache_write) over main requests; null with no requests. |
| `first_req_write_static` | float | Cache-write tokens on the session's first main request (the static prefix). |
| `warm_start_cost_usd` | float | Recomputed cost with the first request's write tokens billed at the read rate (what a fully warm start would cost). |
| `tools_prefix_allowance_tokens` | int | Shared tools-prefix allowance used by the audit and the normalization (32,100 tokens, measured by preflight). |
| `cross_arm_read_tokens` | float | Cache-read tokens on the first main request (shared tools prefix; reported, not flagged within the allowance). |
| `foreign_read_tokens_total` | float | Cache-read tokens beyond the session's own earlier writes plus the allowance (would indicate cross-arm leakage). |
| `foreign_read_requests` | int | Number of requests with foreign reads. |
| `cache_audit_flags` | list | Per-request detail of foreign reads; empty on every session. |
| `cache_audit_clean` | bool | True when no foreign reads were found. True on every session. |
| `turn_pass_frac` | float | Fraction of scripted turns whose checks passed. |
| `final_state_pass` | bool | True when the last turn ran and all its checks passed (final workspace state correct). |
| `critical` | bool | True when a protected file was modified or a check errored while evaluating. |
| `failure_labels` | list | Failed-check labels over all turns (check names such as `pytest_failures`; no output text). |
| `receipt_usd_saved_sum` | float/int | Sum of USD reported by the fast_decisions efficiency receipts (the policy's own claim; not used as evidence). |
| `fd_receipt_counts` | dict | Count of fast_decisions receipt events by kind. |
| `mechanism_engaged` | bool | Mechanism gate: fd arms show routing receipts, plain arms none, sticky never switches and judges once. True on every session. |
| `mechanism_reasons` | list | Reasons the gate failed; empty on every session. |
| `fd_receipts` | int | Total routing receipts (difficulty_judged, scored, model_routed, effort_routed, efficiency, turn_planned). |
| `status` | str | `ok` (passed), `agent_fail` (ran, outcome failed), `infra_fail` (infrastructure; none in accepted rows). |
| `killed_memory` | bool | True when the memory watchdog killed the session's agent tree (one session; see campaign/FAILURES.md). |
| `killed_memory_info` | NoneType/dict | Watchdog marker: time, reason, RSS and cap in GB, process ids; null otherwise. |
| `cost_valid` | bool | False when the session was memory-killed: its cost is not comparable and its pairs are excluded from cost analyses. |
| `scheduled_start` | NoneType | Reserved for offset-start experiments; always null here. |
| `actual_start` | str | UTC ISO time the session actually started. |
| `concurrent_sessions` | int | Sessions in the same wave attempt (started together). |
| `wave_valid` | bool | False when the wave's launch spread exceeded the limit; always true here. |
| `anchor_cost_usd` | float | Non-anchor rows only: the paired anchor's tools-normalized cost (added by pair building). |
| `anchor_cost_usd_raw` | float | The paired anchor's recomputed (un-normalized) cost. |
| `anchor_n_req` | int | The paired anchor's main request count. |
| `anchor_turn_costs` | list | The paired anchor's per-turn tools-normalized costs. |

## turns (11588 rows)

| field | type | meaning |
|---|---|---|
| `schema` | str | Row schema id. |
| `session_key` | str | Session id (joins sessions.jsonl). |
| `scenario_id` | str | Scenario id. |
| `arm` | str | Arm. |
| `host` | str | Host stratum. |
| `rep` | int | Repetition. |
| `wave_id` | str | Wave id. |
| `turn_index` | int | 1-based scripted turn number. |
| `turn_prompt_chars` | int | Characters in this turn's scripted prompt (text not published). |
| `gap_before_s` | int | Idle seconds before the turn. |
| `models_used` | list | Distinct models serving this turn's main requests. |
| `efforts_used` | list | Distinct reasoning-effort values as strings (`None` when not set). |
| `tokens` | dict | Main-request tokens in the turn: input (uncached), cache_read, cache_write, output. |
| `cost_usd` | float/int | Provider-reported USD of every request (main + background) inside the turn window. |
| `cost_usd_recomputed` | float/int | Same requests, recomputed from tokens and the price table. |
| `cost_usd_tools_normalized` | float/int | Same requests on the primary tools-normalized basis. |
| `tools_repriced_tokens` | float/int | Tokens repriced by the tools normalization in this turn. |
| `tools_normalized_delta_usd` | float/int | USD effect of that repricing (<= 0). |
| `calls` | int | Main-loop requests in the turn. |
| `bg_calls` | int | Background requests in the turn. |
| `wall_ms` | NoneType/float | Turn elapsed milliseconds as recorded by the runner (null for a turn that never ran). |
| `working_ms` | NoneType/float | First main request start to last main response end (milliseconds); null with no main request. |
| `switched_in` | bool | True when the turn's first main request used a different model than the previous turn's last. |
| `pass` | bool | All of the turn's checks passed. |
| `skipped` | bool | Turn not run (an earlier turn ended the session, e.g. a kill). |
| `checks` | NoneType/int | Number of checks evaluated after the turn. |
| `failure_labels` | NoneType/list | Labels of failed checks (null when skipped). |
| `first_req_cache_read` | NoneType/float | Cache-read tokens of the turn's first main request. |
| `first_req_cache_write` | NoneType/float | Cache-write tokens of the turn's first main request. |

## pairs (896 rows)

| field | type | meaning |
|---|---|---|
| `schema` | str | Row schema id. |
| `scenario_id` | str | Scenario id. |
| `rep` | int | Repetition. |
| `host` | str | Host stratum of the pair (the Sonnet control yields one pair per host). |
| `arm` | str | The non-anchor arm: aa, shipped, sticky or sonnet. |
| `task_type` | str | Scenario family. |
| `n_long_gaps` | int | Long gaps (>= 5 min) in the scenario. |
| `cost_basis` | str | `tools_normalized` (the primary basis for delta_usd / log_cost_ratio / anchor_cost_usd / arm_cost_usd). |
| `delta_usd` | float | arm - anchor in USD (negative = the arm was cheaper), primary basis. The model code's `saving` is the negative of this. |
| `log_cost_ratio` | float | ln(arm cost / anchor cost), primary basis; null if either cost is 0. |
| `delta_usd_raw` | float | arm - anchor in USD on the recomputed, un-normalized basis. |
| `log_cost_ratio_raw` | float | ln ratio on the raw basis. |
| `delta_s` | float | Wall-clock seconds, arm - anchor. |
| `delta_turn_pass` | float | turn_pass_frac arm - anchor. |
| `both_pass` | bool | Both final states passed. |
| `arm_failed_what_anchor_passed` | bool | The arm's final state failed while the anchor's passed. |
| `anchor_cost_usd` | float | Anchor cost, primary basis. |
| `arm_cost_usd` | float | Arm cost, primary basis. |
| `anchor_cost_usd_raw` | float | Anchor cost, raw basis. |
| `arm_cost_usd_raw` | float | Arm cost, raw basis. |
| `mechanism_engaged` | bool | Mechanism gate of the arm session. |
| `cache_audit_clean` | bool | Cache audit of the arm session. |
| `cost_valid` | bool | False if either session was memory-killed. |
| `valid` | bool | Usable for analysis: both waves valid, neither session infra_fail, both cost_valid. |

## requests (52437 rows)

| field | type | meaning |
|---|---|---|
| `schema` | str | Row schema id. |
| `session_key` | str | Session id. |
| `scenario_id` | str | Scenario id. |
| `arm` | str | Arm. |
| `host` | str | Host stratum. |
| `rep` | int | Repetition. |
| `request_index` | int | 1-based order among all of the session's LLM requests (main + background). |
| `turn_index` | int | Turn the request falls in; 0 when its timestamp is outside every turn window. |
| `main` | bool | True for main-loop requests (carry tools), false for background requests. |
| `model` | str | Model id the response came from. |
| `effort` | NoneType/str | Reasoning effort requested (null when unset). |
| `tokens` | dict | input (uncached), cache_read, cache_write, output tokens of the request. |
| `cost_usd_provider` | float | Provider-reported USD. |
| `cost_usd_recomputed` | float | Recomputed USD from the price table (null if unpriced). |
| `cost_usd_tools_normalized` | float | Primary basis for this request. |
| `tools_repriced_tokens` | float | Tokens repriced on this request (first request per model/effort only). |
| `tools_normalized_delta_usd` | float | USD effect of the repricing (<= 0). |

## summary.json

| field | meaning |
|---|---|
| `sessions` | Accepted sessions in rows. (value: `1036`) |
| `turns` | Turn rows. (value: `11588`) |
| `requests` | Request rows. (value: `52437`) |
| `pairs` | Arm-vs-anchor pairs. (value: `896`) |
| `tools_normalized_delta_usd_total` | Sum of the normalization deltas over all sessions (USD). (value: `-15.371928`) |
| `skipped_no_result` | Sessions with no result.json (none). (value: `[]`) |
| `cache_audit_flagged_sessions` | Sessions with foreign cache reads (none). (value: `[]`) |
| `mechanism_failed` | Sessions that failed the mechanism gate (none). (value: `[]`) |
| `killed_memory` | Session keys killed by the memory watchdog. (value: `["py-forth-r2-opus-aa"]`) |
| `cost_mismatch` | Sessions whose provider and recomputed costs disagree (none). (value: `[]`) |

## Notes

* `sessions` carries `anchor_*` fields only on non-anchor rows with a host-specific pair (not on `anchor`, and not on `sonnet` rows, whose host is `any`).
* Turn cost fields sum every request inside the turn window, background requests included; session totals also count requests that fall outside every turn window (`turn_index` 0 in requests), so the sum of a session's turn costs can be slightly below its session cost.
* One session, `py-forth-r2-opus-aa`, was killed by the memory watchdog: `cost_valid` false, its pair `valid` false; its task outcome (turn 9 failed, turn 10 skipped) is kept for quality analyses.
* `sessions` has 1,036 rows = 280 waves; 896 pairs = 280 shipped + 280 sticky + 280 sonnet (140 sessions x 2 hosts) + 56 aa.
