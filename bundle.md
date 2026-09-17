---
bundle:
  name: fast-decisions
  version: 0.1.0
  description: >-
    Experimental hybrid orchestration with bounded Jev decisions and read-only
    local telemetry. Defaults to shadow mode with external state disabled.
    Shared runtime code and the standalone viewer live in the root package.
includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: fast-decisions:behaviors/hybrid.yaml
---
