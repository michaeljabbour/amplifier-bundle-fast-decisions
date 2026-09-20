# Proposal: host the fast-decisions judge on the team RunPod gateway

*Status: draft for the gateway owner (2026-09-20). Nothing here is deployed; all mutations are the owner's call.*

## What we need
A hosted "decision judge": one chat completion per agent step, `max_tokens: 1`, `temperature: 0`,
`logprobs: true`, `top_logprobs: 10`, ~300 prompt tokens, answer scored from the first token's
top-k log-probabilities. Hard budget: 500 ms end to end from a developer machine. Today the judge
runs locally (qwen3:0.6b via Ollama, ~25 ms/decision, agreement 0.75-0.80 on our decision suites);
Jev (typesafe.ai) scores 1.00 at ~350 ms but is a paid external service. A team-hosted judge gives
every member the same decisions with no local model and keeps state inside team infrastructure.

## What we verified on the gateway (read-only probes, 2026-09-20)
- `https://llm.amplifier.run/v1` answers with the scoped inference key; `logprobs`/`top_logprobs`
  pass through LiteLLM to vLLM on `Qwen/Qwen3.8-27B-FP8` (response shape
  `choices[0].logprobs.content[0].top_logprobs`).
- One-token latency from a Mac on the team network: p50 ~106 ms (min 95 ms; one cold outlier 3.4 s).
  500 ms is realistic with a 750 ms client timeout and abstain-on-timeout.
- Qwen3 emits a thinking block first; the client must send
  `chat_template_kwargs: {"enable_thinking": false}` (vLLM honours it). The fast-decisions
  `gateway` backend now does this by default.
- Suite runs through the CLI hit intermittent timeouts and one HTTP 401 within a minute of calls
  (rate/budget limits on the scoped key?) -- to be clarified with the owner.

## Ask
1. **Interim (no new infra):** allow the inference key a small sustained rate for 1-token requests
   (~5-20 req/s burst per user) against `Qwen/Qwen3.8-27B-FP8`; confirm no per-minute budget that
   returns 401.
2. **Dedicated judge (new deployment):** `Qwen/Qwen3-0.6B` (or `Qwen3-1.7B`) instruct weights,
   vLLM with `--max-logprobs 10`, single small GPU (a 24 GB class card is ample; 0.6B fits with
   headroom), 1 replica to start, autoscale 0-2; expose as model id `fast-decisions-judge` in the
   routing matrix with a read-only inference key scope; expected QPS 5-20 sustained team-wide.
   Rough cost: one small on-demand GPU ~US$0.3-0.5/h when warm; scale-to-zero when idle.
3. **Rollout:** stage behind a non-default model id; we run the decision suites and the harness
   battery cell `judge-gateway+effort-incumbent` against it; promote only if agreement >= local judge
   and p95 < 500 ms; rollback = remove the model id (clients fall back to the local judge).

## Client side (already in the repo)
`backend: gateway`, `model: <id>`, `gateway_url`, `gateway_key_env` (default `LITELLM_INFERENCE_KEY`),
`allow_external_state: true` (state leaves the machine -> explicit consent, see docs/PRIVACY.md).
Compare hosts with `afast bench suite --live --backend gateway --model <id>`.
