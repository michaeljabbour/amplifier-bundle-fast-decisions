#!/bin/bash
# Serial, memguard-capped validation of every batch-C scenario (one validator invocation per scenario).
# usage: run_all_c.sh <out.jsonl>
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/validation-c.jsonl}"; : > "$OUT"
export MEMGUARD_MAX_CONCURRENT=1
for f in "$HERE"/knowledge/*.yaml "$HERE"/repos/*.yaml; do
  id="$(basename "$f" .yaml)"
  free=$(memory_pressure | awk '/free percentage/ {gsub("%","",$5); print $5}')
  if [ "${free:-0}" -lt 50 ]; then echo "SKIP $id: only ${free}% free" >&2; echo "{\"id\": \"$id\", \"errors\": [\"memory below 50% free\"]}" >> "$OUT"; continue; fi
  echo "== $id (free ${free}%)" >&2
  python3 "$HERE/validate_c.py" --ids "$id" --cap-gb 4 --grader-timeout 300 --json "$OUT" >/dev/null 2>"$HERE/.val-$id.err" || echo "FAILED $id" >&2
done
