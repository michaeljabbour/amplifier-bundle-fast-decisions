#!/bin/bash
# Reproduction driver: committed harness at 45d5f8e, unchanged. 3 reps. Local arms sequential (Ollama residency),
# cloud arms in a separate sequential process.
set -u
cd "$(dirname "$0")/../../../.."
R="$1"; GROUP="$2"
set -a; . ~/.amplifier/keys.env; set +a
if [ "$GROUP" = local ]; then ARMS="laya-base tev1-0.8b tev1-4b nimble-9b qwen3-0.6b qwen3-4b qwen3-8b"; else ARMS="jev-1.13 gpt-6-luna gpt-6.1-sol"; fi
for rep in 1 2 3; do
  for arm in $ARMS; do
    out="$R/rep$rep"
    if [ -f "$out/requests.jsonl" ] && grep -q "\"arm\": \"$arm\"" "$out/requests.jsonl"; then APP=--append; elif [ -f "$out/requests.jsonl" ]; then APP=--append; else APP=; fi
    # separate dir per group to avoid concurrent writers
    out="$R/rep$rep-$GROUP"
    APP=; [ -f "$out/requests.jsonl" ] && APP=--append
    echo "$(date -u +%FT%TZ) start rep$rep $arm" 
    PYTHONPATH=src:. python3 evals/judge_comparison.py --output "$out" --arms $arm $APP 2>&1 | tail -2
  done
done
echo DONE
