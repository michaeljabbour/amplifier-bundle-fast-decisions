# Teamwork as a portable Smart Tool

Target: `amplifier-bundle-teamwork` capabilities become usable from ordinary
Python, a CLI, or an agent harness on supported operating systems. Its existing
Amplifier bundle becomes an adapter. This maps the current checkout, not a
completed migration or cross-platform validation.

## Boundary

```text
CLI / optional MCP / Amplifier hooks / other harness adapters
                         |
               typed Teamwork library API
        consent + attribution + deterministic operations
                         |
            service client / journal / transport
                         |
                optional decision backend
         cheap classifier -> abstain -> generative judge
```

The library owns capabilities with no Amplifier core/Foundation imports.
Adapters supply identity, consent, bounded context, credentials, cancellation
and event sinks. No adapter silently enrolls projects, changes providers,
starts a UI, or grants the model permission to write.

| Existing implementation | Destination |
|---|---|
| `hooks-teamwork/.../__init__.py`: HTTPClient, Journal, WorkTools | Extract service/journal/operations into the library. Keep HookResult/ToolResult envelopes and lifecycle in the adapter. |
| `service_url.py`, `git_remote.py`, `queue_name.py`, reports | Portable helpers with explicit configuration/pathlib; report git/subprocess dependencies. |
| `decision_judge.py`: child session and RECORD/SKIP | Typed JudgeRequest/JudgeResult plus injected backend; child-session creation in the Amplifier adapter. Preserve `no_verdict` versus legitimate SKIP. |
| Enrollment, sharing consent, parent attribution | Caller-supplied authority/context, checked before mutations. |
| Hook observation and record emission | Adapter collects bounded observations; library suggests; authorized caller writes with provenance. |

The current judge also generates claims and lessons. A small classifier should
initially decide “consider recording, skip, or escalate.” Generation still needs
a generative backend. Preserve background queueing and cancellation. The local
scorer here currently supports workspace read/list only; it cannot yet replace
the Teamwork judge.

## Jev architecture implications

[Archer Hume's article](https://archerhume.com/posts/jevs-architecture-unmasked/)
is black-box architectural inference. Shared state encoding, separate question
readouts and numerical probabilities are useful experimental directions; the
article does not establish exact implementation or supply trained weights.
[TypeSafe's description](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
describes typed probabilistic decisions. Our one-token classifier approximates
a narrow interface, not Jev's training, calibration or parallel question heads.

After extraction, collect consented scrubbed Teamwork decisions with human
labels. Split by project/session before training. Compare a small encoder head,
a constrained one-token model, and the existing judge. Evaluate accepted-error
rate, coverage, calibration, option-order stability, injection resistance and
p95/p99 latency. Then choose quantization, distillation or cloud hosting.

## Deliverable sequence

1. Extract one deterministic slice: project status and record listing. Typed
   library API, thin JSON CLI, explicit errors, cancellation and caller-supplied
   state/config paths. Test without Amplifier installed.
2. Move enrollment/consent, journal and writes behind that API. Require credentials
   explicitly for service operations; prove retry behavior and attribution parity.
3. Adapt the bundle to the library. Compare adapted and baseline behavior on the
   same fixtures before replacing hook implementations.
4. Add optional judge interfaces. Missing provider is explicit unavailability,
   not an undisclosed deterministic substitute. Evaluate local scoring in shadow.
5. Ship `smart-tool.json`, canonical `SMART_TOOL.md`, its library metadata accessor,
   entrypoint and discovery information. Run Smart Tool conformance and actual
   installation/execution on macOS, Linux and Windows. Advertise only verified
   platforms. Add MCP after library/CLI parity.

Acceptance: the same operation works through plain Python, CLI and Amplifier
with equivalent typed results, authority and provenance. Imports/manifest checks
alone do not prove harness independence; Unix-only setup is not OS independence.

Sources: [Smart Tools](https://github.com/microsoft/amplifier-smart-tools),
[structure](https://github.com/microsoft/amplifier-smart-tools/blob/main/spec/structure.md),
[manifest](https://github.com/microsoft/amplifier-smart-tools/blob/main/spec/manifest.md),
[invocation](https://github.com/microsoft/amplifier-smart-tools/blob/main/spec/invocation.md).
