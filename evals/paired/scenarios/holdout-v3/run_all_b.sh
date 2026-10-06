#!/bin/bash
# Serial, memory-guarded validation of holdout-v3 batch B. One validator invocation per scenario; refuses to start a
# run unless system memory is >= 50% free. Usage: run_all_b.sh [id ...]  (default: every scenario in mixed/ polyglot/)
cd "$(dirname "$0")/../../../.." || exit 1
export MEMGUARD_MAX_CONCURRENT=1
D=evals/paired/scenarios/holdout-v3
ids="$*"; [ -z "$ids" ] && ids=$(ls $D/mixed/*.yaml $D/polyglot/*.yaml | xargs -n1 basename | sed 's/\.yaml$//')
mkdir -p "${B_OUT:-/tmp/holdout-b}"
for id in $ids; do
  free=$(memory_pressure | awk '/free percentage/ {gsub("%","",$5); print $5}')
  if [ "${free:-0}" -lt 50 ]; then echo "SKIP $id: only ${free}% memory free"; continue; fi
  echo "== $id (free ${free}%)"
  python3 $D/validate_b.py --ids "$id" --cap-gb 4 --grader-timeout 300 --json "${B_OUT:-/tmp/holdout-b}/$id.json" 2>&1 | grep -v "^$"
done
