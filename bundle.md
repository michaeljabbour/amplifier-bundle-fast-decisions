---
bundle:
  name: fast-decisions
  version: 0.2.0
  description: >-
    Foundation plus orchestrator-primary fast-decisions: loop-fast-decisions
    replaces foundation's loop-streaming (and wraps it, so every upstream
    behavior is preserved) and decides once per session whether the session
    is easy (cheaper start model, only when it is cheaper on this host) or
    hard (the host model, unchanged), routing provider calls by phase and
    failure signals; the telemetry hook, the read-only fast_workspace tool
    and the observatory dashboard come with it. Observer-only (no
    orchestrator swap): behaviors/fast-decisions-shadow.yaml. The judged
    read shortcut rungs remain in bundles/active*.yaml.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: fast-decisions:behaviors/fast-decisions
---
