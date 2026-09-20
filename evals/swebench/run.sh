#!/usr/bin/env bash
# evals/swebench/run.sh
#
# S3 SWE-bench Verified slice (STUDY-DESIGN.md section 15). 30 pinned
# instances x 3 Amplifier variants (amplifier-plain, amplifier-fd-incumbent,
# amplifier-fd-candidate) = 90 trials by default, dispatched through the
# amplifier-evaluation harness (`python -m amplifier_evaluation run`) with a
# parallelism cap. SWE-bench grading is Docker-heavy and each task can take
# 10-40 minutes; this is run SERIALLY from a queue, never invoked directly by
# an automated agent -- see README.md.
#
# Usage:
#   ./run.sh                # dry-run preflight + task generation only
#   ./run.sh --check        # preflight only, no task generation, no harness
#   ./run.sh --run          # generate tasks (if absent) + invoke the harness
#
# Environment overrides:
#   ANTHROPIC_API_KEY     required; falls back to ~/.amplifier/keys.env
#   FD_SHA                required for --run; the pinned
#                         amplifier-bundle-fast-decisions commit sha used by
#                         the two amplifier-fd-* agents' bundle sources
#   MAX_PARALLEL          concurrent trials; default 1 (SWE-bench is
#                         Docker-heavy; see README.md "Why serial")
#   TRIALS_PER_PAIR        default 1
#   N_INSTANCES            default 30 (matches PINNED_INSTANCE_IDS)
#
# Prerequisites: amplifier-digital-twin, uv, python3, docker on PATH; Docker
# daemon running; amplifier_evaluation importable (activate the evaluation
# bundle's .venv, or run with PYTHONPATH pointed at its src/). See README.md
# "Preflight" for exactly what this script does and does not verify.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RESULTS_ROOT="${HERE}/results"
MAX_PARALLEL="${MAX_PARALLEL:-1}"
TRIALS_PER_PAIR="${TRIALS_PER_PAIR:-1}"
N_INSTANCES="${N_INSTANCES:-30}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

MODE="dry-run"
case "${1:-}" in
  --check) MODE="check" ;;
  --run) MODE="run" ;;
  "") MODE="dry-run" ;;
  *) die "unknown argument: $1 (expected --check, --run, or nothing)" ;;
esac

if [ -f "$HOME/.amplifier/keys.env" ]; then set -a; . "$HOME/.amplifier/keys.env"; set +a; fi

# ---- preflight (always runs; this is the ONLY thing --check does) --------
log "preflight checks"
python3 "$HERE/swebench_stage.py" check \
    --config "$HERE/candidate.config.json" \
    --pinned-ids "$HERE/PINNED_INSTANCE_IDS"
PREFLIGHT_EXIT=$?

if [ "$MODE" = "check" ]; then
    exit "$PREFLIGHT_EXIT"
fi

[ -n "${ANTHROPIC_API_KEY:-}" ] || die "ANTHROPIC_API_KEY not set and not in ~/.amplifier/keys.env"

if [ "$MODE" = "dry-run" ]; then
    log "dry-run: preflight ran above; not generating tasks or invoking the harness."
    log "re-run with --run to generate tasks (if absent) and dispatch the harness."
    exit "$PREFLIGHT_EXIT"
fi

# ---- --run from here on ---------------------------------------------------
[ -n "${FD_SHA:-}" ] || die "FD_SHA not set (pinned amplifier-bundle-fast-decisions commit sha, required for the two amplifier-fd-* agents)"

command -v amplifier-digital-twin >/dev/null || die "amplifier-digital-twin not on PATH"
command -v uv >/dev/null || die "uv not on PATH"
command -v python3 >/dev/null || die "python3 not on PATH"
command -v docker >/dev/null || die "docker not on PATH"
docker info >/dev/null 2>&1 || die "Docker is not running"
python3 -c "import amplifier_evaluation" 2>/dev/null \
    || die "amplifier_evaluation not importable; activate the evaluation bundle's .venv (see README.md 'Preflight')"

# ---- 1. generate the 30 pinned SWE-bench Verified task dirs (idempotent) --
if [ ! -d "$HERE/tasks/swebench-1" ]; then
    log "generating $N_INSTANCES SWE-bench Verified task dirs"
    uv run --quiet --with huggingface_hub --with pyarrow python3 "$HERE/sample_swebench.py" \
        --n "$N_INSTANCES" --seed 42 --split verified \
        --out "$HERE/tasks" --pinned-file "$HERE/PINNED_INSTANCE_IDS"
else
    log "tasks/ already populated; skipping generation (delete tasks/swebench-* to re-sample)"
fi

# ---- 2. render amplifier-fd-candidate's install.yaml from candidate.config.json --
RENDERED_AGENTS_DIR="$(mktemp -d)"
cp -r "$HERE/agents/amplifier-plain" "$RENDERED_AGENTS_DIR/"
cp -r "$HERE/agents/amplifier-fd-incumbent" "$RENDERED_AGENTS_DIR/"
# The two static agents carry a literal {{FD_SHA}} placeholder inside their
# embedded bundle-YAML heredocs (their bundle module `source:` lines) even
# though they have no other candidate.config.json template placeholders;
# substitute it the same way render-candidate does for the third agent.
python3 "$HERE/swebench_stage.py" substitute-fd-sha \
    --agents-dir "$RENDERED_AGENTS_DIR" --fd-sha "$FD_SHA"

log "rendering amplifier-fd-candidate from candidate.config.json"
python3 "$HERE/swebench_stage.py" render-candidate \
    --config "$HERE/candidate.config.json" \
    --template "$HERE/agents/amplifier-fd-candidate" \
    --out "$RENDERED_AGENTS_DIR/amplifier-fd-candidate" \
    --fd-sha "$FD_SHA" \
    || die "rendering amplifier-fd-candidate failed -- likely candidate.config.json is not yet 'confirmed' (see README.md 'Preflight' and STUDY-DESIGN.md section 8's decision rule)"

# ---- 3. build the 90 (agent, task) pairs ----------------------------------
PAIRS=()
for agent in amplifier-plain amplifier-fd-incumbent amplifier-fd-candidate; do
    for n in $(seq 1 "$N_INSTANCES"); do
        PAIRS+=(--pair "$agent:swebench-$n")
    done
done

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-s3"
OUTPUT_DIR="$RESULTS_ROOT/$RUN_ID"
mkdir -p "$OUTPUT_DIR"

log "running harness over ${#PAIRS[@]} pair-flags (max_parallel=$MAX_PARALLEL, trials_per_pair=$TRIALS_PER_PAIR), output=$OUTPUT_DIR"
cd "$HERE"
python3 -m amplifier_evaluation run \
    --agents-dir "$RENDERED_AGENTS_DIR" \
    --tasks-dir "$HERE/tasks" \
    "${PAIRS[@]}" \
    --output-dir "$RESULTS_ROOT" \
    --run-id "$RUN_ID" \
    --max-parallel "$MAX_PARALLEL" \
    --trials-per-pair "$TRIALS_PER_PAIR" \
    --launch-var "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" \
    ${TYPESAFE_API_KEY:+--launch-var "TYPESAFE_API_KEY=$TYPESAFE_API_KEY"} \
    --verbose
HARNESS_EXIT=$?

log "harness exit: $HARNESS_EXIT"
log "results: $OUTPUT_DIR (summary.json, trials/, harness.log)"

# ---- 4. summarize into battery-style result rows --------------------------
python3 "$HERE/summarize.py" --output-dir "$OUTPUT_DIR" --out "$OUTPUT_DIR/battery_rows.json"
log "battery-style rows: $OUTPUT_DIR/battery_rows.json"

rm -rf "$RENDERED_AGENTS_DIR"
exit "$HARNESS_EXIT"
