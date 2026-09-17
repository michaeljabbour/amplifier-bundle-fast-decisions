---
bundle:
  name: fast-decisions
  version: 0.1.0
  description: >-
    Fast-decision telemetry hook plus the read-only fast_workspace tool, on top
    of foundation. The orchestrator is untouched here: the hook runs shadow
    measurement (what it would have chosen, never enacted) on top of whatever
    orchestrator you already run. The active decision orchestrator (a fast
    decision model actually substituting a prepared read-only action for an
    LLM turn) remains opt-in via bundles/active.yaml.
    bundles/shadow.yaml is retained only as a DEPRECATED forwarding alias --
    this root bundle already is the shadow rung.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: fast-decisions:behaviors/fast-decisions
---
