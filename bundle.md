---
bundle:
  name: fast-decisions
  version: 0.1.0
  description: >-
    Fast-decision telemetry hook plus the read-only fast_workspace tool, on top
    of foundation. The orchestrator is untouched here: the hook observes
    provider and tool metadata only. The shadow/active decision orchestrator
    (a fast decision model choosing among prepared read-only actions) is
    opt-in via bundles/shadow.yaml and bundles/active.yaml.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: fast-decisions:behaviors/fast-decisions
---
