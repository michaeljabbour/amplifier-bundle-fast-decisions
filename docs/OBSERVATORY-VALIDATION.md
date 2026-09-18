# Observatory validation — 2026-09-17

The redesigned viewer projects recorded events across local Amplifier sessions.
Parent sessions are the default scope; child activity is included by default. The mechanics
view correlates only by both session and decision ID, keeps missing stages absent,
and defaults to an actual decision attempt before a shadow proposal.

## Actual host observations

Host: Amplifier CLI `14dc68e`, Python 3.12.11, core 1.6.1, installed loop-streaming
`20aac7a9eb26034d230357f6aa6805f27c86df52`. Profiles used local module sources and
`PYTHONPATH=src`, Qwen3:0.6b through local Ollama, and a disposable public README.
Only the pilot workspace excluded app bundles; global configuration was unchanged.

- Session `7a981275-f194-4e17-87a1-1a89f00f1c4f`: real interactive host emitted
  configuration and seven observed 15-second heartbeats before being closed.
  Its decision attempt timed out (recorded 496.4 ms); the ordinary provider
  selected `read_file`, which succeeded and produced the correct summary.
  This is evidence of fallback, not acceleration. No cold-start cause was proven.
- After an explicit model warmup, fresh session
  `867edefd-4d09-4a1c-9b51-dbe3c996dd60` recorded a real Qwen score at 126.0 ms,
  a fast submission, matching successful `fast_workspace` execution, and a
  normal Anthropic final answer. Cleanup emitted `session_closed`. This proves
  one completed fast path; it is not a workload latency guarantee.
- The two host sessions overlapped while the first remained idle. Both used
  the shared local event directory and were independently visible to the viewer.
  No comparison of whole-task speed or spend was controlled in this check.

## Automated and visual checks

- Actual Amplifier Python: 244 discovered tests passed at the full-suite check
  (including dependency-based skips where applicable). New checks cover observer
  heartbeat ownership, retry metadata privacy, and stopping emissions on cleanup.
- Thirteen Node projection tests cover provenance, parent identity, stale presence,
  submission versus execution, and cross-session correlation isolation.
- Optional Chromium integration test uses only temporary fixture JSONL. It
  checks two parents plus a child, live appended events, mechanics, pause/resume,
  keyboard focus across polling, import/return-to-live, token reconnect, and
  mobile overflow. These fixture tests are not host execution evidence.
- Real recorded host traces were rendered at desktop and mobile sizes with no
  browser errors or horizontal document overflow. The feed and side panels have
  bounded scrolling. Candidate probabilities remain explicitly uncalibrated.

The neutral live-flow view highlights newly arrived recorded stages, supports
child aggregation by default, and explicitly separates generative-call bypass
from unmeasured tool pruning, net savings, and task-quality parity. Browser
integration checks newly appended stages receive arrival highlighting.

Portable Smart Tool validation is documented in [SMART-TOOL.md](SMART-TOOL.md):
installed conformance, deterministic skill installation, real local model calls,
and strict separation of advisory scores from runtime actions. No RunPod
resource, Jev API invocation, or context-retention optimizer is part of this
change.

## Ledger redesign — 2026-09-18

The live view is now a decision ledger (one row per session + decision id) with the
stage chain under each row, instead of one card per decision. What changed and how it
was checked:

- Sessions are named by `workspace_name` (the working-directory basename the hook now
  records at mount; `session_label` still wins when configured) with the short id as a
  secondary line. The hook never records a full path; `privacy.SAFE_FIELDS` allowlists
  the single component and `tests/test_observer_presence.py` covers basename-only,
  config override, and allowlist behaviour.
- A native `tool:pre` / `tool:post` pair joins the shadow decision that recorded the
  same `tool_call_id`, so "model proposed X → LLM called Y → match/mismatch" reads on
  one row. `shadow_observed` is rendered as a stage. Rows with no decision remain
  hook-observation rows, dimmed and labelled "Not scored".
- Verdicts are labelled chips with a tone (fast executed / submitted / failed, reasoning
  model, match / mismatch / abstained, no candidate, fallback, advisory, scripted,
  in flight, not scored); the label carries the meaning, never the colour alone.
- Session state treats `provider:request`, `tool:pre`, `tool:post` and `llm:response`
  as work signals, so a single retry no longer leaves "Provider issue reported" showing
  after the session has resumed.
- Verification: the 13 Node projection tests and the optional Chromium integration test
  (`tests/test_viewer_browser.py`) pass unchanged against the new markup; the Python
  suite passes on 3.12 apart from repo-layout tests that need the full checkout. A
  synthetic local fixture (not host telemetry) was rendered at 390, 768, 1150, 1280 and
  1440 px with no page errors or horizontal document overflow, and with events dripped
  in live to confirm arrival highlighting, the pinned in-flight row and working/idle
  state changes. These fixture renders are not host execution evidence.

