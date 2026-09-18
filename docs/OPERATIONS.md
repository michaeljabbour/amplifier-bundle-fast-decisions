# Diagnose, measure and compare

These are deterministic Smart Tool capabilities. They do not make model calls,
change host configuration, launch a viewer, or execute a proposed action.
`diagnose` probes only local health endpoints unless `--offline` is supplied.

## Installation to live execution

```bash
amplifier-fast-decisions diagnose
amplifier-fast-decisions diagnose --session PARENT_SESSION_ID
amplifier-fast-decisions measure --session PARENT_SESSION_ID
```

Both commands accept `--events DIRECTORY_OR_JSONL`. Descendants are included by
default. `diagnose` also accepts `--state-file FILE`, `--model NAME`,
`--ollama-url LITERAL_LOOPBACK_ORIGIN`, and `--offline`. Its JSON reports:

- Package metadata in the invoking Python environment; not the state of every host.
- Local model presence, installed digest and whether Ollama reports it loaded.
  This does not prove inference or token-log-probability support.
- Authenticated viewer health and whether it reads the same event directory.
  The viewer token is never included in diagnostic output or sent to redirects.
- Effective session mode/backend from configuration receipts, observer presence,
  working/idle state, actual scores, bypasses, executions and fallback reasons.
- Remediation for absent receipts, scripted shadow, missing model, viewer mismatch,
  no eligible scoring and recorded provider failures.

No receipts means **not observed**, not “bundle absent.” A missing installation in
system Python does not establish that a uv-managed host lacks the package.
A loaded model does not establish that the session selected it. A healthy viewer
connection does not establish that a session is running.

For an explicit local model profile, follow [MODEL-SETUP.md](MODEL-SETUP.md#simple-local-setup).
The existing `afast configure --backend ollama --mode shadow|active --local-sources`
command writes a named profile. It does not alter global app/default configuration.
Use a fresh session and re-run diagnostics against its actual session ID. `off`
disables both active and background shadow scoring; it retains observation.

## What the measurements mean

`measure` reads metadata-only JSONL, including kernel-wrapped receipts. Records are
deduplicated by session/event identity, with parent/child/grandchild membership
resolved independently of file order. Invalid records and bounded-history truncation
are reported. Incomplete trailing writes are retried on the next invocation.

- `provider_calls_started/finished`: instrumented provider entry/exit, joined by
  `provider_call_id`; stream calls are included, with missing usage left unknown.
- `provider_calls_bypassed`: recorded prepared-envelope submission at a real provider
  boundary. Native denial can still prevent the proposed tool from executing.
- `tool_executions_*`: actual instrumented `execute()`, joined by `tool_call_id`.
  `success: true` is required for a successful execution count.
- Native provider requests, tool pre/post hooks and retries are separate observation
  counters. Do not add native hook counts to instrumented calls.
- Provider token totals remain null if any recorded call lacks a complete successful
  usage receipt. Known-call coverage is included beside each token field.
- Decision scoring total/p95 covers recorded backend scoring durations, including
  shadow work. It is not total scheduler overhead or end-to-end task latency.
- `instrumented_coverage_complete` requires matched turn, provider and tool entry/exit
  identities. Observer-only and legacy traces cannot establish complete coverage.
- Successful turn completion means the orchestrator returned; it does not certify
  answer correctness. Tool calls eliminated, net cost saved and quality parity are
  null until a suitable explicit comparison or execution receipt supports them.

The viewer also exposes the same read-only report at authenticated
`GET /api/measure?session=PARENT_SESSION_ID`. Its source reports retained-history
limits; a browser API report has no authority to alter policy or execute tools.

## Matched task comparisons

```bash
amplifier-fast-decisions compare --input runs.json
```

Relative event paths resolve beside `runs.json`. The comparator retains negative
regressions and rejects efficiency claims when inputs/revisions/hardware differ,
receipts are incomplete, or either run fails its explicit outcome checks.
Its exit code means a report was produced, not that the enabled run improved.
Read `all_pairs_eligible` and each pair's `baseline_minus_enabled` values.

```json
{
  "schema_version": "paired-runs-v1",
  "pairs": [{
    "task_id": "public-task-01",
    "split": "development",
    "baseline": {
      "events": "baseline/events",
      "session_id": "actual-baseline-session",
      "wall_time_ms": 1200,
      "task_fingerprint": "hash-of-identical-task-input",
      "workspace_fingerprint": "hash-of-identical-starting-workspace",
      "provider_model": "exact-model-id",
      "provider_revision": "verified-revision",
      "hardware": "same-host-identity",
      "outcome": {
        "passed": true,
        "evaluator": "checked-output-v1",
        "checks": {"expected_output": true}
      }
    },
    "enabled": {
      "events": "enabled/events",
      "session_id": "actual-enabled-session",
      "wall_time_ms": 950,
      "task_fingerprint": "hash-of-identical-task-input",
      "workspace_fingerprint": "hash-of-identical-starting-workspace",
      "provider_model": "exact-model-id",
      "provider_revision": "verified-revision",
      "hardware": "same-host-identity",
      "outcome": {
        "passed": true,
        "evaluator": "checked-output-v1",
        "checks": {"expected_output": true}
      }
    }
  }]
}
```

These numbers are a schema example, not measured savings. Timing, fingerprints and
outcome assertions are supplied by the caller; the comparator checks consistency
and receipts, not the truth of an arbitrary evaluator. Use `unknown` for an
unverified serving revision. It prevents a comparability claim rather than silently
pretending a mutable model name pins weights. Costs remain unknown without verified
billing evidence; token differences are not priced as Jev or another provider.

## Explicit live development runner

Run from this checkout with the local dependencies in the Amplifier host environment:

```bash
PYTHONPATH=src python scripts/bench_compare_host.py \
  --output-dir /tmp/afast-new-comparison \
  --provider YOUR_PROVIDER --model YOUR_MODEL
```

The output directory must not exist. This **does call the configured generative
provider**, using two tiny public extraction tasks in separate equivalent workspaces.
Baseline uses the same instrumented upstream wrapper with decisions off; enabled
uses the local scorer. The runner counterbalances order, warms the local model,
measures full CLI elapsed time, and checks exact final answers. Startup/composition
is included; warmup is separate. It writes profiles and an isolated project-local
`app: []`, never global settings. The model revision is unknown unless explicitly
verified and passed as `--provider-revision`.

Outputs are `runs.json`, `comparison.json` and metadata receipts. The runner does not
retain provider output in its reports. Other host loggers retain their normal policy.
These are development fixtures. Held-out workflow outcomes, larger samples, matching
serving revisions and cold/warm/concurrency tests remain necessary before broader
quality parity or savings claims.

## Public development pilot — 2026-09-18

Four real Amplifier runs, counterbalanced baseline/enabled order, used the public
README extraction fixtures above. All four final answers passed exact checks.
Baseline had decisions off, including shadow scoring; enabled allowed one fast
submission per turn. Global configuration was unchanged.

| Task | Baseline elapsed | Enabled elapsed | Provider calls | Tool executions |
|---|---:|---:|---|---|
| extract-a | 26.565 s | 19.551 s | 2 → 1 | 1 → 1 |
| extract-b | 24.660 s | 16.160 s | 2 → 1 | 1 → 1 |

Both enabled runs recorded one actual bypass and successful execution. Their four
recorded active/shadow scoring calls were below 40 ms; those durations are backend
scoring, not full task latency. No provider retries or execution failures were
recorded. These numbers establish the behavior of these four development runs.
They do not establish held-out quality parity, general speedup or dollars saved.
The provider name was `claude-fable-5-1`; its immutable serving revision was not
available, so the comparator correctly marked both pairs ineligible for a strict
matched-revision efficiency claim. Provider usage is recorded but local scorer
cost and provider billing are not independently priced.

Environment: macOS arm64, Amplifier CLI `14dc68e`, core 1.6.1, Python 3.12.11,
loop-streaming `20aac7a9eb26034d230357f6aa6805f27c86df52`; local Ollama 0.34.1,
Qwen3:0.6b digest
`7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435`.
The runner records isolated session IDs, elapsed time, receipt coverage and exact
checks. An earlier pilot exposed shadow inference still running in `off` mode;
that defect was fixed and those earlier timings were discarded.

A separate real delegation test created parent
`8e6d12db-47a3-4c49-bd02-2fdbcab5d1f3` and child
`0000000000000000-0a5fe972c1f24f03_foundation-explorer`.
The parent called `delegate`; its child used the fast read path. Parent-scoped
measurement includes both sessions once: three actual provider calls, two
successful tool executions, one bypass in the child, and complete matched
instrumentation. The final `Cedar|violet` answer passed an exact check.
