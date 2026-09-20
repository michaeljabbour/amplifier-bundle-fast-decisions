# Local scoring pilot

The `ollama` backend makes real one-token decisions on loopback without Jev,
an API key, or cloud compute. It is an experimental classifier, not a Jev
replica. Default model: `qwen3:0.6b` (Q4_K_M). The default app behavior remains
offline shadow; select a local profile explicitly to use this backend.

## Results, September 17, 2026

Measured on an Apple M5 Max with 128 GB memory, Ollama 0.34.1. Each model
handled 42 sequential requests: seven development cases, original/reversed
candidate order, three repetitions. These are seven distinct cases, not 42
independent examples. Inputs exclude the suite's answer-hint instruction field.
The final prompt uses typed operation/target descriptions, matching runtime
candidates. Wall times include Python, serialization, local HTTP and inference.
They do not measure a remote network, concurrent load, or full agent turns.

| Model | Warm p50 | Warm p95 | Maximum | Accepted at current policy | Wrong accepted | Order-stable pairs |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3 0.6B Q4_K_M | 20.8 ms | 23.9 ms | 25.3 ms | 15/42 | 0/15 | 18/21 |
| Llama 3.1 8B Q4_K_M | 65.6 ms | 67.9 ms | 68.1 ms | 3/42 | 0/3 | 15/21 |

Both met the 500 ms warm target on this small workload. Zero wrong accepted
cases is not a calibrated accuracy estimate. Option-order effects and low
coverage still prevent recommending general active routing. The policy remains
score >= 0.90 and margin >= 0.20. Unclear, oversized, unsupported, cold/timed-out
or malformed decisions fall back to the slow model.

First-ever Qwen load took about 14.8 seconds in an exploratory call. The saved
benchmark's `warmup_ms` can involve resident weights and is not a cold benchmark.
Keep the model resident before latency-sensitive runs.

Evidence: [Qwen](evidence/local-qwen3-06b.json),
[Llama](evidence/local-llama31-8b.json), and
[native approval smoke](evidence/local-kernel-two-targets-smoke.json).
The approval smoke uses the real local model, installed core/loop and workspace
tool, with mock coordinator/context and a fixture generative finalizer. For the
public two-target prompt, allowing the native hook caused one README.md read;
denying it caused zero executions and no `tool_start`. This is not complete
Foundation/provider host certification.

A separate [actual CLI run](evidence/local-cli-active.json) loaded the local
profile through Foundation, scored with Qwen in **70.8 ms**, executed the selected
read successfully, and used the existing Anthropic provider for the correct
one-sentence summary (exit 0). Session `b261eace-a41d-448e-8659-34d3616dfca0`
is in the normal Observatory event directory. This validates that bounded live
path; cancellation, steering and other lifecycle coverage remain the automated
integration lane, not a claim of exhaustive live-host certification.

The local pilot profiles are under `~/.amplifier/fast-decisions/local-pilot/`.
Its disposable `workspace/.amplifier/settings.local.yaml` isolates app composition.
Global settings were not edited. To reproduce from this checkout:

```bash
export AFAST_SOURCE="$PWD/src"
cd "$HOME/.amplifier/fast-decisions/local-pilot/workspace"
PYTHONPATH="$AFAST_SOURCE" amplifier run \
  --bundle "file://$HOME/.amplifier/fast-decisions/local-pilot/local-active.md" \
  --mode single "Read README.md, not LICENSE.md. Give a one-sentence summary."
```

## Run from an extracted checkout

Use Python 3.11+ with `.[local,test]` installed. Install the `local` extra in the
same environment as Amplifier for CLI sessions. Ollama must support native
generate token log probabilities.

```bash
ollama pull qwen3:0.6b
PYTHONPATH=src python3 scripts/bench_local.py --model qwen3:0.6b

# A disposable directory containing public README.md and LICENSE.md files:
export AFAST_PILOT_WORKSPACE=/absolute/path/to/public-fixture
PYTHONPATH=src python3 -m amplifier_fast_decisions configure \
  --bundle-root "$PWD" --workspace "$AFAST_PILOT_WORKSPACE" \
  --mode shadow --backend ollama --model qwen3:0.6b \
  --timeout-ms 500 --local-sources --output /tmp/afast-local-shadow.md
PYTHONPATH="$PWD/src" amplifier run \
  --bundle file:///tmp/afast-local-shadow.md --mode single \
  "Read README.md, not LICENSE.md. Give a one-sentence summary."
```

**Composition caveat:** this CLI composes app bundles after the named bundle.
An installed fast-decisions app can override the shadow profile's hook config
back to `deterministic`; other app compositions can also replace the active
orchestrator. Always inspect the effective configuration event for `ollama-token`;
a successful CLI exit does not prove real scoring. For a newly created disposable
workspace only, use `.amplifier/settings.local.yaml` containing `bundle: {app: []}`
and run from that workspace. This isolates the pilot from global app composition
without changing global settings. Preserve existing local settings elsewhere.

Use `--mode active` in a separate generated profile for an isolated active
experiment. Do not register it app-wide. No external-state opt-in is required
for loopback scoring. Your normal generative provider still receives normal
agent context; local scoring does not make the whole agent local.

The profile uses the usual Observatory events directory unless `--events` is
given. Choose its session in the viewer. Scored events identify `ollama-token`
and the model. The UI labels the value **uncalibrated token score**. Shadow
proposals never authorize or execute a tool.

For the live native approval smoke, run
`PYTHONPATH=src python3 scripts/smoke_local_kernel.py` in the Amplifier environment.

## Host-agnostic scoring

The token-mass scoring in `score_tokens` (label normalization, abstention
residual, invalid-probability rejection) is shared verbatim by every local
one-token classifier host: `OllamaBackend` and `MlxBackend` both build their
prompt and label set from the same `_build_label_prompt` helper and both
adapt their host's response into the same `[{"token": ..., "logprob": ...}]`
shape before scoring, so switching hosts (`--backend ollama` vs
`--backend mlx`) changes only wire format and process, never the scoring
semantics, thresholds, or `DecisionResult` contract. See
[MODEL-SETUP.md's Apple MLX section](MODEL-SETUP.md#apple-mlx-host) for setup.

## Score semantics and limits

One `/api/generate` call requests one non-thinking token and its top-token
log probabilities. Recognized single-letter tokens carry their original mass;
all missing/unrecognized mass goes to abstention. Scores are never renormalized
over just the offered candidates or read from model-authored confidence JSON.
`probability_kind=token_mass_with_abstention_residual` records the distinction.

The scorer sees scrubbed observations and only prepared operation/target pairs.
It does not receive arbitrary argument fields, suite hints or private reasoning.
Combined prompt/system text is capped at 3500 UTF-8 bytes. Only 1–12 prepared
workspace read/list actions are supported; batched questions and Teamwork
judgments are not implemented. HTTP requires a literal loopback origin with
proxies/redirects disabled. Queue wait counts toward the deadline. The model
cannot generate arguments or permissions; revalidation and native approval apply.

## Hosted GPU judges and lower-bit models

Local latency already meets the target; quality is the next constraint.
Quantization reduces storage and can help inference, but does not teach
reliable task classification. Microsoft's native 1.58-bit BitNet model needs a
separate model/runtime evaluation. Abliterating refusal behavior has no
demonstrated benefit for this routing task.

If a better classifier needs a GPU service, use the **hosted** backend
(see [Hosted judge](MODEL-SETUP.md#hosted-judge)) against a modest GPU in a
nearby region: an always-warm load-balancing endpoint or dedicated pod, max one
worker, authentication and a teardown deadline. A planning allowance around
$1/hour and $5 for the first trial is reasonable; obtain an actual region and
instance quote before provisioning. Measure client p50/p95/p99 including network,
varied inputs and concurrency. Cold requests must fall back explicitly. The
local backends (Ollama, MLX) remain loopback-only; the hosted backend is the
supported path for a remote judge, and always requires the explicit
`--allow-external-state` opt-in.

Sources: [Ollama API](https://docs.ollama.com/api/generate),
[Qwen model](https://ollama.com/library/qwen3:0.6b),
[BitNet](https://huggingface.co/microsoft/bitnet-b1.58-2B-4T).
