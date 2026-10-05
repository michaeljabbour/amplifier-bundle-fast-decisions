---
name: "amplifier-fast-decisions"
description: "Decide once at session start which model and effort a coding session should run on (the same price-gated, scope-gated decision the Amplifier orchestrator makes), and use Jev for bounded read/list decisions, source relevance search, and proposals on observed UI controls. The host keeps execution and approval authority; uncertain decisions abstain."
---

Install the CLI if needed:

```bash
uv tool install 'amplifier-fast-decisions[local] @ git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main'
```

Run `amplifier-fast-decisions --help` and follow its guidance. Confirm capability
arguments with `amplifier-fast-decisions <capability> --help` before use.
