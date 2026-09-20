# Rollback

The hosted tiny-Qwen (0.6B) judge has one integration point: the
`fast-decisions-judge` entry in the LiteLLM `model_list`
(`litellm-model.yaml`). To roll back:

1. Remove the `fast-decisions-judge` entry from your LiteLLM `model_list`
   (or revert the config change that added it) and reload/restart LiteLLM
   per your normal config-reload process.
2. No client-side change is required. Every fast-decisions client already
   fails open to its local judge (Ollama/MLX) at the existing 500 ms budget
   when the hosted backend is unreachable or not configured -- see
   `DecisionService.choose` and docs/MODEL-SETUP.md.
3. Tear down the RunPod pod (or leave it running idle; it costs the same
   either way since it is billed per-hour while up).

There is no data migration and no schema to unwind: the hosted judge never
holds state, it only answers one-token classification requests.
