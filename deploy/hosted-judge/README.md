# Hosted tiny-Qwen judge (0.6B) -- gateway owner deployment package

*Nothing in this repository deploys anything. The gateway owner runs these
steps against their own infrastructure and account.*

**What:** hosts the same 0.6B decision judge every teammate's local Ollama
already runs (`qwen3:0.6b`) behind the team's own LiteLLM gateway, so nobody
needs a local model to get fast-decisions judging.

**Why:** one dedicated pod serves the whole team; state stays inside team
infrastructure (never a third-party judge); the client already fails open to
the local judge if the hosted endpoint is unreachable or unaccepted.

**Expected cost:** ~US$0.27-0.49/h for a 24 GB-class GPU pod (RunPod
community/secure tier, unconfirmed which), i.e. roughly $200/mo always-on
(see `docs/proposals/hosted-judge-deployment-example.md` for the full
hosting-option comparison this package implements).

**Expected latency:** the floor is the network, not the model -- about
100 ms round-trip from a developer laptop to the pod on a one-token judge
call; local Ollama is faster (~25 ms) because there is no network hop.

**Files:**
- `runpod-pod.json` -- RunPod pod-create payload (image tag is a
  placeholder -- pin before use).
- `litellm-model.yaml` -- the `model_list` entry to add to your LiteLLM
  config.
- `accept.sh` -- acceptance script the owner runs after deploy.
- `rollback.md` -- one-step rollback.

**Acceptance criteria (see `accept.sh`):** p95 latency < 300 ms at the
endpoint over >=200 sequential one-token probes; `top_logprobs` length of 10
on every response; the returned model id matches on every response; suite
agreement >= the local judge's measured 0.75-0.80.
