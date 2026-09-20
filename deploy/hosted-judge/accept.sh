#!/usr/bin/env bash
# accept.sh -- gateway owner runs this AFTER deploying the hosted tiny-Qwen
# (0.6B) judge (see runpod-pod.json + litellm-model.yaml). Nothing here is
# run automatically by this repository -- this file only executes when the
# gateway owner invokes it against their own deployed endpoint.
#
# Usage:
#   JUDGE_API_BASE=https://your-litellm.example.internal \
#   JUDGE_API_KEY=sk-... \
#   ./accept.sh
#
# Pass:
#   - p95 < 300 ms over N one-token probes at the endpoint
#   - top_logprobs length == 10 on every probe
#   - returned model id matches "fast-decisions-judge" on every probe
#   - afast bench suite agreement >= the local judge's 0.75-0.80, on both runs
set -euo pipefail

: "${JUDGE_API_BASE:?set JUDGE_API_BASE to the LiteLLM base URL}"
: "${JUDGE_API_KEY:?set JUDGE_API_KEY to a scoped inference key}"
MODEL="${JUDGE_MODEL:-fast-decisions-judge}"
N="${ACCEPT_PROBES:-200}"

echo "== Phase 1: ${N} sequential 1-token probes against ${JUDGE_API_BASE} =="
tmp_latencies="$(mktemp)"
trap 'rm -f "$tmp_latencies"' EXIT
bad_logprobs=0
bad_model=0

for i in $(seq 1 "$N"); do
  body='{"model":"'"$MODEL"'","messages":[{"role":"user","content":"ok"}],"max_tokens":1,"temperature":0,"logprobs":true,"top_logprobs":10,"chat_template_kwargs":{"enable_thinking":false}}'
  start=$(python3 -c 'import time; print(time.time())')
  response=$(curl -fsS --max-time 5 -X POST "${JUDGE_API_BASE%/}/chat/completions" \
    -H "Authorization: Bearer ${JUDGE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$body") || { echo "probe $i: request failed" >&2; exit 1; }
  end=$(python3 -c 'import time; print(time.time())')
  echo "$(python3 -c "print(($end-$start)*1000)")" >> "$tmp_latencies"

  top_logprobs_len=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
try:
    tl = d['choices'][0]['logprobs']['content'][0]['top_logprobs']
    print(len(tl))
except Exception:
    print(0)
" "$response")
  [ "$top_logprobs_len" = "10" ] || bad_logprobs=$((bad_logprobs + 1))

  returned_model=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
print(d.get('model', ''))
" "$response")
  case "$returned_model" in *"$MODEL"*) ;; *) bad_model=$((bad_model + 1));; esac
done

python3 -c "
import sys

path, n, bad_logprobs, bad_model = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
with open(path) as f:
    latencies = sorted(float(line) for line in f if line.strip())

def pctile(data, p):
    if not data:
        return float('nan')
    idx = min(len(data) - 1, int(round(p / 100 * (len(data) - 1))))
    return data[idx]

p50 = pctile(latencies, 50)
p95 = pctile(latencies, 95)
print(f'p50={p50:.1f}ms p95={p95:.1f}ms n={len(latencies)}')
print(f'top_logprobs!=10 on {bad_logprobs}/{n} probes')
print(f'model id mismatch on {bad_model}/{n} probes')

ok = p95 < 300 and bad_logprobs == 0 and bad_model == 0
print('PHASE 1: ' + ('PASS' if ok else 'FAIL'))
if not ok:
    sys.exit(1)
" "$tmp_latencies" "$N" "$bad_logprobs" "$bad_model"

echo "== Phase 2: afast bench suite --live --backend hosted, twice =="
afast bench suite --live --backend hosted --hosted-url "$JUDGE_API_BASE" --model "$MODEL" --json > run1.json
afast bench suite --live --backend hosted --hosted-url "$JUDGE_API_BASE" --model "$MODEL" --json > run2.json
echo "wrote run1.json and run2.json"
echo "Compare each run's agreement against the local judge's measured 0.75-0.80"
echo "(docs/proposals/hosted-judge-deployment-example.md). PASS requires"
echo "agreement >= 0.75-0.80 on both runs -- inspect the JSON and confirm by hand."
