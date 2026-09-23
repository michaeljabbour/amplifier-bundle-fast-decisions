# Fast Decisions dashboard

The working dashboard is served at **http://127.0.0.1:8794/**.
Its source is `src/amplifier_fast_decisions/static/`; the Python viewer serves
live, sanitized telemetry at the root. Do not use `python -m http.server` here.

Launch from the repository (stop an existing viewer with `afast serve --stop` first):

```sh
PYTHONPATH=src python3 -m amplifier_fast_decisions serve --port 8794 --no-fallback --open \
  --study /Users/michaeljabbour/dev/afast-native-study-20260922
```

The viewer is loopback-only and the root URL works in any local browser tab,
including Incognito. Runtime telemetry and study receipts
are read only. Study unit-test logs are excluded. The study progress table includes
baseline runs even though they do not emit Fast Decisions telemetry.

The decision circuit and compact ledger share one dashboard. Inspect a ledger
row to pin its circuit and reveal its stages; collapse the circuit for more room.
The same session filters, event stream, and evidence inspector serve both.
Decisions, submitted
actions, confirmed executions, bypassed provider calls, fallbacks and scoring
latency are recorded separately. Poor tool calls prevented and net time saved
remain explicitly unmeasured; counts are not proof of task quality or savings.

Previous HTML mockups, generated demo exports and screenshots are consolidated
under `archive/`. They are historical visual references, not live dashboards,
and are not served by the viewer. The archive generator creates synthetic demo
content only: `PYTHONPATH=src python3 docs/visuals/archive/build_preview.py`.
