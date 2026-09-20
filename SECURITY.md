# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately via
[GitHub Security Advisories](https://github.com/michaeljabbour/amplifier-bundle-fast-decisions/security/advisories/new)
for this repository. Do not open a public issue for a suspected
vulnerability.

Include what you found, how to reproduce it, and its potential impact. We'll
acknowledge the report and follow up with next steps.

## Scope

In its default configuration, this project sends nothing off the machine.
Decisions run against a local, deterministic scorer or a local model host;
no state leaves the process unless you explicitly opt in.

External backends -- a paid judge service, or a hosted OpenAI-compatible
endpoint (`--backend hosted`, alias `gateway`) -- are opt-in only, gated by an explicit
`allow_external_state` flag, and documented in [docs/PRIVACY.md](docs/PRIVACY.md),
which is the authoritative accounting of what data can leave the machine and
under which conditions.
