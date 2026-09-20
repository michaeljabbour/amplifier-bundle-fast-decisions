# Model setup: local first, hosting optional

Start with **Ollama + [`qwen3:0.6b` (Q4_K_M)](https://ollama.com/library/qwen3:0.6b)** for the bundle's bounded read/list
decisions. This is the model we have exercised in an actual Amplifier CLI
session. In the seven-case development suite its warm p95 was 23.9 ms on an
Apple M5 Max, versus 67.9 ms for Llama 3.1 8B. Qwen accepted 15 of 42 requests
at the current thresholds; Llama accepted 3. Those requests repeat the same
seven cases in two candidate orders. Neither result establishes general
accuracy or a guarantee for other hardware, larger inputs, or concurrent sessions.
See [the evidence and limitations](LOCAL-SCORER.md).

The model is a small autoregressive classifier requesting one token. It does
not reproduce Jev's architecture, calibration, or broader decision primitives.
The current adapter supports prepared `fast_workspace` read/list candidates;
it does not support batched questions, model-role scoring, or context compaction.

## Simple local setup

You need an existing working Amplifier installation and generative provider,
Python 3.11+, `uv`, and an extracted checkout of this repository. Install and
start Ollama using the [macOS/Windows download](https://ollama.com/download) or
[Linux instructions](https://docs.ollama.com/linux). The tested runtime was
Ollama 0.34.1; use a version supporting native `/api/generate` token log
probabilities. The backend rejects responses without them.

From the repository directory, pull and warm the model. The empty generation
request preloads the weights; `num_ctx` matches the scorer's request. This
warmup may take seconds and is outside the 500 ms decision budget.

```bash
export AFAST_REPO="$PWD"
ollama pull qwen3:0.6b
curl --fail --silent --show-error http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:0.6b","stream":false,"keep_alive":"10m","options":{"num_ctx":4096}}'
ollama ps
```

Install the `local` extra and the profile generator's YAML dependency in the
**Python environment that runs Amplifier**. For the usual `uv tool` installation
named `amplifier`, use the following. If your installation differs, set
`AFAST_HOST_PYTHON` to its actual Python executable instead; a separate venv will
not install these dependencies into the host.

```bash
export AFAST_HOST_PYTHON="$(uv tool dir)/amplifier/bin/python"
uv pip install --python "$AFAST_HOST_PYTHON" -e "${AFAST_REPO}[local]" pyyaml
"$AFAST_HOST_PYTHON" -m amplifier_fast_decisions doctor --require-amplifier
```

Create a fresh public fixture workspace and its local profile. The project-local
`app: []` prevents installed app bundles from overriding this test's selected
backend or orchestrator. These commands write only into a new temporary
directory; they do not edit global Amplifier settings or an existing project.

```bash
export AFAST_PILOT="$(mktemp -d "${TMPDIR:-/tmp}/afast-pilot.XXXXXX")"
mkdir -p "$AFAST_PILOT/workspace/.amplifier"
cp "$AFAST_REPO/README.md" "$AFAST_PILOT/workspace/README.md"
cp "$AFAST_REPO/LICENSE" "$AFAST_PILOT/workspace/LICENSE.md"
printf 'bundle:\n  app: []\n' > "$AFAST_PILOT/workspace/.amplifier/settings.local.yaml"

"$AFAST_HOST_PYTHON" -m amplifier_fast_decisions configure \
  --bundle-root "$AFAST_REPO" --workspace "$AFAST_PILOT/workspace" \
  --mode shadow --backend ollama --model qwen3:0.6b \
  --timeout-ms 500 --local-sources --output "$AFAST_PILOT/shadow.md"

cd "$AFAST_PILOT/workspace"
PYTHONPATH="$AFAST_REPO/src" amplifier run \
  --bundle "file://$AFAST_PILOT/shadow.md" --mode single \
  "Read README.md, not LICENSE.md. Give a one-sentence summary."
```

In the Observatory, inspect this session's configuration: backend should be
`ollama-token` and mode `shadow`. A real score identifies `qwen3:0.6b` and
`probability_kind: token_mass_with_abstention_residual`. The configuration proves
which backend was selected; only a scored event proves it responded. Shadow
proposals leave the ordinary provider/tool path in charge. A successful CLI
exit by itself does not establish that any decision was scored.

To exercise the active path in the same isolated workspace:

```bash
"$AFAST_HOST_PYTHON" -m amplifier_fast_decisions configure \
  --bundle-root "$AFAST_REPO" --workspace "$AFAST_PILOT/workspace" \
  --mode active --backend ollama --model qwen3:0.6b \
  --timeout-ms 500 --local-sources --output "$AFAST_PILOT/active.md"
PYTHONPATH="$AFAST_REPO/src" amplifier run \
  --bundle "file://$AFAST_PILOT/active.md" --mode single \
  "Read README.md, not LICENSE.md. Give a one-sentence summary."
```

An accepted selection emits a fast submission. Native approvals still apply;
a matching successful `tool_end` establishes execution. A low score, unsupported
request, or timeout falls back to the existing provider. No TypeSafe key or
`--allow-external-state` flag is needed for this loopback scorer. Your usual
provider still handles its normal agent context and may incur usage charges.

The viewer normally opens for interactive TTY sessions. If needed, run
`"$AFAST_HOST_PYTHON" -m amplifier_fast_decisions serve --open` in another
terminal and open the full token-bearing link. If an auto-viewer already owns
that events directory, reuse it or stop it with `serve --stop` before starting
another. Keep the temporary workspace until you finish inspecting the pilot.

## Configuration and tuning

`configure` writes a profile; it does not change the default app. Use
`configure --help` for its supported flags. For settings without a flag, edit
the generated profile's `hooks` entry for `hooks-fast-decisions` in shadow mode,
or `session.orchestrator.config` in active mode.

| Setting | Starting value | What to change, and why |
|---|---|---|
| `backend`, `model` | `ollama`, `qwen3:0.6b` | Set through `--backend` / `--model`; benchmark every model change before active use. |
| `ollama_url` | `http://127.0.0.1:11434` | `--ollama-url` accepts a literal loopback HTTP origin, including another local port. No remote hostname, path, credentials, or HTTPS endpoint. |
| `timeout_ms` | `500` | Set `--timeout-ms 500` explicitly; the general CLI default is 750. This bounds scoring and queue wait, not the whole agent turn. Measure warm p95 below 500 ms with headroom. |
| `min_probability`, `min_margin` | `0.90`, `0.20` | Keep these initially. Raising them reduces accepted actions. Lowering them can accept wrong actions; evaluate held-out cases and candidate-order changes first. |
| `max_state_chars` | `2048` for generated Ollama profiles | Limits the snapshot. A separate backend input-byte guard can still reject a request; increasing this does not expand the model contract. |
| `max_candidates` | `12` | The local backend supports 1–12 candidates. Reduce the set through precise eligibility; do not omit legitimate choices just to inflate confidence. |
| `max_fast_streak`, `max_fast_per_turn` | `3`, `12` | Active-path budgets. Start here; faster scoring does not justify unbounded tool runs. |

The adapter itself fixes `think: false`, `temperature: 0`, `num_predict: 1`,
`num_ctx: 4096`, `top_logprobs: 20`, and `keep_alive: "10m"`. These are **not**
exposed as bundle tuning settings. Unknown extra config fields will not change
them. Changing one-token or non-thinking behavior would violate the adapter's
response validation. Recognized action tokens retain their original probability
mass; everything else becomes abstention. These scores are not calibrated
probabilities of correctness.

For latency, warm the model before a run, check residency with `ollama ps`, and
avoid sharing its inference queue with long generations. Each score requests
another ten minutes of residency; after a longer idle period, rewarm before
testing. Ollama's [API](https://docs.ollama.com/api/generate) documents the
request fields, and its [FAQ](https://docs.ollama.com/faq) explains residency
and how `ollama ps` reports GPU/CPU placement. Larger models, more parallel
sessions, and larger inputs need fresh measurements.

Run the development benchmark from the repository:

```bash
cd "$AFAST_REPO"
PYTHONPATH=src "$AFAST_HOST_PYTHON" scripts/bench_local.py \
  --model qwen3:0.6b --timeout-ms 500 --repeats 3 \
  --output "$AFAST_PILOT/qwen-benchmark.json"
```

Check `errors`, `wrong_accepted`, acceptance coverage, `order_stable_pairs`, and
warm p95 together. The benchmark warms once with a longer timeout, then measures
sequential requests; it is not a load test or a held-out accuracy evaluation.
It currently uses the default local port 11434 and has no `--ollama-url` flag.
Compare complete, equivalent tasks with and without acceleration before claiming
time or money saved; a short decision call alone does not prove either.

## Apple MLX host

On Apple Silicon, `mlx_lm.server` is a second local judge host, an alternative
to Ollama, not a replacement for it -- pick one. It runs the same bounded,
loopback-only, one-token classifier contract as the Ollama adapter (same
`DecisionResult` shape, same abstention semantics, same 1-12 prepared
`fast_workspace` read/list candidates); only the wire format and host differ.
Intel Macs and Rosetta Python are not supported: MLX requires an actual
Apple Silicon (arm64) process, not just Apple hardware.

Detect Apple Silicon before choosing this path:

```bash
[ "$(uname -m)" = "arm64" ] && case "$(sysctl -n machdep.cpu.brand_string)" in *Apple*) echo "Apple Silicon";; esac
```

Install `mlx-lm` (a separate optional dependency, not the `local` extra used
for Ollama) and start its OpenAI-compatible server. `--chat-template-args`
disables Qwen3's `<think>` blocks -- the adapter scores a single non-thinking
token, exactly like the Ollama path, and a thinking preamble would consume
the one generated token on something other than a label:

```bash
uv tool install mlx-lm
mlx_lm.server --model mlx-community/Qwen3-0.6B-4bit --host 127.0.0.1 --port 8080 \
  --chat-template-args '{"enable_thinking": false}'
curl -fsS http://127.0.0.1:8080/health
```

Default port `8080`. Recommended weights: `mlx-community/Qwen3-0.6B-4bit`
(matching the Ollama-side default model size), or `mlx-community/Qwen3-1.7B-4bit`
if 0.6B's acceptance coverage is too low for a workload. `-8bit` and `-bf16`
variants trade memory for potential quality; benchmark before switching.
Unlike Ollama's `keep_alive` eviction, mlx-lm keeps the model resident for the
server process's entire lifetime -- there is no idle-eviction timer to rewarm
against.

Configure the bundle to use it:

```bash
"$AFAST_HOST_PYTHON" -m amplifier_fast_decisions configure \
  --bundle-root "$AFAST_REPO" --workspace "$AFAST_PILOT/workspace" \
  --mode shadow --backend mlx --model mlx-community/Qwen3-0.6B-4bit \
  --timeout-ms 500 --local-sources --output "$AFAST_PILOT/shadow-mlx.md"
```

`mlx_lm.server`'s exact `logprobs` request shape has varied across released
versions: some accept an integer count (`{"logprobs": N}`), others the
OpenAI-style pair (`{"logprobs": true, "top_logprobs": N}`). The adapter tries
both and caches whichever the running server accepts; re-verify against your
installed version rather than assuming either shape is guaranteed going
forward.

Compare the two hosts on the same suite before choosing one for a workload:

```bash
afast bench suite --live --backend ollama --model qwen3:0.6b
afast bench suite --live --backend mlx --model mlx-community/Qwen3-0.6B-4bit
```

`afast doctor` reports an `mlx_server` check (`GET /health` against
`FAST_DECISIONS_MLX_URL`, default `http://127.0.0.1:8080`) alongside its other
checks; absence is not an error unless you intend to use `--backend mlx`.

## Hosting without RunPod

No RunPod account or deployment is required. Use an existing private workstation,
server, or rented Linux host and run **both Amplifier and Ollama on that machine**.
Install Ollama using its [Linux guide](https://docs.ollama.com/linux), keep its
listener on loopback, and repeat the setup above in that host's shell. Start with
the same Qwen model and measure the host before upgrading hardware. The recorded
Mac timings do not predict CPU-only or rented GPU performance.

Connect to the host by SSH to run Amplifier. Keep the raw inference service
private. Observatory records stay on that host; they are not automatically
aggregated with sessions on your laptop. Its loopback viewer can be inspected
through an SSH local port forward, using the viewer's actual port and temporary
token. This is a viewer-access option, not distributed telemetry ingestion.

The current scorer intentionally rejects a remote model URL. Forwarding a remote
scorer into a local port would still transmit the snapshot to another machine,
while today's adapter labels it local (`external=False`). Do not treat that as
supported hosted scoring. Keeping Amplifier and Ollama together honors the
current boundary; a future remote adapter needs explicit external-state opt-in,
authentication, and end-to-end network measurements.

Do not start with a bigger or more aggressively quantized model just to imitate
Jev. The tested 4-bit model is the practical baseline; new quantization, BitNet,
fine-tuning, and different runtimes require their own compatibility and quality
evaluation. No cloud resource was provisioned for this guide.

## If it does not score

| Symptom | Check |
|---|---|
| Viewer says disconnected | Open its complete printed URL, including the temporary token; a bare localhost address cannot access events. |
| Backend is `scripted-demo` | An app bundle likely overrode your selected profile. Run from the fresh isolated workspace above and inspect the new configuration event. |
| No eligible candidates | Use an explicit readable text-file path under the configured workspace root. Generic questions and edits are outside this pilot. |
| Cold or timed-out decisions | Warm the model, check `ollama ps`, and inspect queue/load pressure. Keep the 500 ms target while diagnosing. |
| Backend unavailable / no probabilities | Check Ollama's version and native log-probability support, exact model name, HTTP availability, and `httpx` in the actual Amplifier Python environment. |
| Scores exist but no fast execution | Shadow mode only proposes. In active mode, inspect abstention, thresholds, budgets, and native approval outcomes. |
| The normal provider retries or fails | Diagnose the generative provider separately; the local scorer does not replace its authentication, network access, or final-answer generation. |

## Hosted judge (team gateway)

The above hosts (Ollama, MLX) keep the judge model on the same machine as
Amplifier, so no snapshot state leaves it. A **hosted gateway** instead runs
the judge on shared infrastructure the team controls (for example a
RunPod-backed OpenAI-compatible endpoint), reached over HTTPS with an API
key. This is a real network call, so it always requires explicit opt-in:
`--backend gateway --allow-external-state` (`battery.py prepare
--fd-backend gateway --allow-external-state`; the bundle's own
`allow_external_state: true` config for direct runtime use). It is gated by
the same `allow_external_state` consent check as the `jev` backend in
`DecisionService.choose` -- omit the flag and the route silently falls back
to the existing provider (`external_state_not_enabled`).

**What leaves the machine:** the same bounded decision state every backend
sees -- the compact task snapshot (`state`), the prepared candidate
descriptions, and (if contributed) judgment questions -- never raw file
contents beyond the prepared excerpt already built for the local backends,
and never anything from outside the `fast_workspace` boundary. See
[Privacy](PRIVACY.md) for the full data-path accounting.

**Configuration**

| Setting | Default | Notes |
|---|---|---|
| `gateway_url` (config) / `FAST_DECISIONS_GATEWAY_URL` (env) | `https://llm.amplifier.run/v1` | Must be `https://` unless the host is literal loopback (`127.0.0.1`/`::1`), which may use `http://` for local gateway development. No credentials, query string or fragment in the URL -- the key travels only in the `Authorization` header. |
| `model` (config) | none -- **required** | Unlike the local backends, there is no default judge model for a hosted gateway; a missing `model` is a startup error, not a silent fallback. |
| `gateway_key_env` (config) | `LITELLM_INFERENCE_KEY` | Names the environment variable holding the API key. The key value itself is never a config field, never logged, and never appears in receipts, profiles or the doctor check -- only the outbound `Authorization: Bearer <key>` header carries it, for that one request. |

**Doctor:** `afast doctor` reports a `gateway_server` check (`GET
{base}/models` using the configured key) alongside its other checks, with
state `reachable`, `auth_failed`, or `unreachable` -- never the key itself.
Absence is not an error unless you intend to use `--backend gateway`.

**Comparing against the local judge:** run the same suite through both
backends and compare:

```bash
afast bench suite --live --backend ollama --model qwen3:0.6b
afast bench suite --live --backend gateway --model <hosted-model-id> \
  --gateway-url https://llm.amplifier.run/v1
```

(`--gateway-url` is optional; it overrides `FAST_DECISIONS_GATEWAY_URL` and
the built-in default.) This isolates the question a hosted judge actually
answers: does it reach the same decisions as the local judge, and at what
added network latency cost? It does not by itself establish accuracy,
reliability, or a cost advantage over Ollama/MLX -- benchmark before
switching a workload over, exactly as with any other backend change.

A hosted server cannot be assumed to honor a server-side "disable thinking"
flag the way a self-hosted mlx-lm process can (`--chat-template-args
'{"enable_thinking": false}'`), so the gateway backend's system prompt
explicitly forbids a `<think>` preamble. If the model emits one anyway, the
adapter does not need to detect it specially: a `<think>`-style token simply
fails to match any recognized action label, and its probability mass is
absorbed into the abstention residual like any other unrecognized token
(see `score_tokens` in `local_backend.py`) -- the decision routes to the
existing provider rather than acting on a leaked thinking token.

## Use it as a Smart Tool

The [portable Smart Tool](SMART-TOOL.md) packages the same local model capability
as a library and thin CLI. Deterministic help/manifest/schema commands need no
model; `select` owns model invocation and returns typed advisory selection or
abstention. It can be discovered through a skill in Claude Code, Codex, and
Amplifier. It never asserts that a suggestion executed or saved a provider call.

Automatic provider bypass remains the Amplifier adapter described above. The
[Teamwork portability design](design/teamwork-portable-tool.md) discusses deeper
harness integration; universal call interception and context retention are not
implemented by installing a discovery skill.
