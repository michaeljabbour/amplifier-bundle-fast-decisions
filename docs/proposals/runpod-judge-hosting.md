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
- Your team's OpenAI-compatible gateway URL (e.g. `https://llm.example.internal/v1`) answers with
  the scoped inference key; `logprobs`/`top_logprobs` pass through LiteLLM to vLLM on
  `Qwen/Qwen3.8-27B-FP8` (response shape `choices[0].logprobs.content[0].top_logprobs`) --
  verified live against a LiteLLM+vLLM deployment.
- One-token latency from a Mac on the team network: p50 ~106 ms (min 95 ms; one cold outlier 3.4 s).
  500 ms is realistic with a 750 ms client timeout and abstain-on-timeout.
- Qwen3 emits a thinking block first; the client must send
  `chat_template_kwargs: {"enable_thinking": false}` (vLLM honours it). The fast-decisions
  `gateway` backend now does this by default.
- Suite runs through the CLI hit intermittent timeouts and one HTTP 401 within a minute of calls
  (rate/budget limits on the scoped key?) -- to be clarified with the owner.

## Hosting comparison and recommendation (2026-09-20)

| Option | Cost | Latency | Notes |
|---|---|---|---|
| **Dedicated always-on pod** (24 GB-class, recommended) | ~US$197/mo + ~$2/mo disk (assumed $0.27/h for an A5000-class GPU; community vs. secure tier pricing unconfirmed) | p50/p95 ~= 110-140 / 180-260 ms | No cold start. Single-host risk is covered by the client's existing fail-open to the local judge. |
| Serverless, `min-workers=1` | ~US$423-504/mo (2-2.5x the dedicated pod for the same warmth) | Comparable to dedicated, plus an extra queue hop | Pays for standby capacity at a premium over a dedicated pod; no cold-start benefit since a worker is always warm. |
| Serverless, `min-workers=0` | ~US$128-150/mo | 20-60 s cold starts | Unusable against the 500 ms budget; cheapest only when latency does not matter. |

**Recommendation:** the dedicated always-on 24 GB-class pod. It is the only option that meets the
500 ms budget without paying a premium for serverless standby capacity, and single-host risk is
already mitigated by the existing client fail-open to the local judge.

### Deployment shape
- Pinned vLLM worker image.
- Environment: `MODEL_NAME=Qwen/Qwen3-0.6B`, `MAX_MODEL_LEN=4096`, `MAX_LOGPROBS=10`,
  `ENABLE_PREFIX_CACHING=true`, `DTYPE=bfloat16`, `GPU_MEMORY_UTILIZATION=0.60`,
  `MAX_NUM_SEQS=64`, `DISABLE_LOG_REQUESTS=true`.
- Port 8000/http; disk 20 GB.
- Liveness: `/health` every 30 s, plus one 1-token canary request every 60 s.

### LiteLLM `model_list` entry
```yaml
- model_name: fast-decisions-judge
  litellm_params:
    model: openai/Qwen/Qwen3-0.6B
    api_base: os.environ/JUDGE_API_BASE
    api_key: os.environ/JUDGE_API_KEY
    drop_params: false
    timeout: 2
    num_retries: 0
```
No fallbacks configured. Key scope: an inference-only, model-restricted key -- self-check with
`GET /v1/models` (expect 200) and `GET /key/list` (expect 403).

### Rollout
1. Stage as `fast-decisions-judge-staging` first.
2. **Acceptance:** decision-suite agreement >= the local judge; >=200 sequential 1-token probes
   against the endpoint with p95 < 300 ms; `top_logprobs` length of 10 on 100% of responses; the
   returned model id identity-checked on every response.
3. Promote to `fast-decisions-judge`; keep the staging deployment running for 7 days after
   promotion.
4. **Rollback:** delete the model entry from the LiteLLM `model_list` -- clients fail open to the
   local judge with no further action required.

### Assumptions to confirm
- RunPod community vs. secure tier pricing for the A5000-class GPU (cost table above assumes
  $0.27/h; secure tier may differ).
- Whether the scoped inference key used during the initial read-only probes carries a per-minute
  rate/budget limit (observed intermittent timeouts and one HTTP 401 within a minute of calls).
- Sustained team-wide QPS for the dedicated pod under real usage, to confirm `MAX_NUM_SEQS=64` and
  `GPU_MEMORY_UTILIZATION=0.60` are sized correctly.

## Client side (already in the repo)
`backend: gateway`, `model: <id>`, `gateway_url`, `gateway_key_env` (default `LITELLM_INFERENCE_KEY`),
`allow_external_state: true` (state leaves the machine -> explicit consent, see docs/PRIVACY.md).
Compare hosts with `afast bench suite --live --backend gateway --model <id>`.
