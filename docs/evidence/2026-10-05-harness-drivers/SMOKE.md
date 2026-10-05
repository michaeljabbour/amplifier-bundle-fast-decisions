# Harness-driver and launch smoke (offline suite + 12 one-sentence live calls)

Date 2026-10-05. Purpose: confirm that the interfaces `evals/harness_drivers.py` and `launch` rely on exist and behave as
documented in each CLI's `--help`, and learn what the unit tests could not. Not a performance, cost or quality result.

**Spend (logged in `smoke-log.jsonl`):** about $0.41 in total, under the $5 allowance. Claude Code about $0.31 (provider-reported
`total_cost_usd`); Codex at most about $0.10 at *illustrative* token rates (the ChatGPT-account billing is not per token, so
the true figure is unknown); Copilot 0 premium requests (`gpt-5-mini`, multiplier 0); Jev under $0.0001.

Installed locally and exercised: Claude Code 2.1.289, Codex 0.160.0, Copilot CLI 0.0.412. OpenCode is installed but has no driver.

## What was confirmed

| Interface | Result |
|---|---|
| `claude -p PROMPT --output-format json [--model M] [--effort E] [--resume SID]` | JSON carries `session_id`, `result`, `total_cost_usd`, `usage`, `modelUsage`. `--resume` kept context (turn 2 recalled the word from turn 1). Full model ids are honored exactly; the alias `haiku` resolved to `claude-sonnet-5-5` in this version, so S4 must pass full ids. |
| `codex exec --json [-c model=...] [-c model_reasoning_effort=...]`, `codex exec resume SID PROMPT` | Events `thread.started` (thread id), `item.completed` (agent_message), `turn.completed` (usage). **`turn.completed.usage` is the thread's cumulative total**, not the turn's (73,053 vs the rollout's `last_token_usage` of 41,940 on turn 2): the driver subtracts the previous total. **`exec resume` rejects `-s/--sandbox`**: the driver passes such flags on the first turn only. `-c model="..."` reached Codex (an unsupported model was refused by name). |
| `copilot -p PROMPT -s --allow-all-tools --resume UUID --model M` | The caller can choose the session UUID; turn 2 resumed it and recalled the word. No token usage is printed: cost is premium requests x multiplier x $0.04, so Copilot stays a portability screen. No effort flag exists. |
| `amplifier-fast-decisions decide --decider jev --allow-external-state` (live Jev) | easy task on a Fable host: `route: true`, `claude-sonnet-5`, `medium`, `judge_cheap`, 195 ms, p(complex) 0.0. hard task: `route: false`, host model, `judge_strong`, p(complex) 1.0. Estimated judge cost $0.00002 per call. |
| `launch --harness claude|codex|copilot` | The flags are applied: Claude ran `--model haiku --effort medium`, Copilot ran `--model gpt-5-mini`, Codex received `-c model="gpt-5.2-codex"`. |

## What was NOT done

- Clef / Clef-Flash against the live Workers AI endpoint: no Cloudflare credentials in this environment. The backend is tested against a
  local fake server only (`tests/test_backend_table.py`).
- Long or tool-heavy sessions through any driver; error paths other than a non-zero exit and a timeout.
- Wiring driver results into `evals/paired.py`'s row extraction (`session_row` parses Amplifier events). The drivers return per-turn
  usage and cost in a normalized `TurnResult`; the paired harness still needs an `ExternalHarnessBackend` and a row builder.
- The Codex per-token rates used above are placeholders; S4 must fix real rates in its preregistration.
- Copilot model multipliers in `COPILOT_MULTIPLIERS` are from memory of GitHub's published table and must be verified against the
  account's plan before S4.
- A model-backed `select` per harness inside each harness's own agent loop (plan E5) has no committed evidence yet.
