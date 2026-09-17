# Build and verification report

Release: 0.1.0 experimental. Built September 17, 2026 UTC (September 16 in San Francisco).

## Delivered

Foundation bundle, three independently packaged module entrypoints, reusable decision service, real TypeSafe async SDK adapter, metadata emitters, JSONL recorder, read-only local viewer, offline replay/export, configuration generator, doctor command, synthetic demo, test suites, source references and human/agent handoff documentation.

## Executed in the build sandbox

| Check | Actual result |
|---|---|
| `python -m unittest discover -s tests -v` | **89 discovered: 86 passed, 3 skipped**, 4.976 seconds on the recorded final run |
| Skipped tests | Real `amplifier_core` envelope, real `HookResult`, real streaming-loop execute signature; upstream packages are absent |
| SDK adapter | Tested against a mock of the documented request/response shape; no live request |
| Demo | 74 schema-valid events, all explicitly synthetic |
| Python compile check | Passed for runtime, modules, scripts and example Python |
| Frontend syntax | `node --check` passed |
| Standalone browser | Rendered in Chromium; event selection, distribution display, replay/pause/step and filtering passed |
| Responsive browser | 390px viewport checked without page-wide overflow |
| Browser JavaScript errors | None observed in the executed standalone checks |
| Local HTTP server | Authentication, Host/Origin validation, read-only behavior, static allowlist and security headers passed in local Python HTTP tests |
| Live browser-to-localhost navigation | Blocked by the sandbox browser administrator policy; not a passed live browser test |
| Root wheel | Built successfully without fetching dependencies |
| Three module wheels | All built successfully without fetching dependencies |

Exact recorded test output is in `docs/evidence/unit-tests.txt`. Browser and packaging evidence are in the same directory. These checks concern different layers and must not be combined into a claim that real Amplifier integration passed.

## Not executed or established here

Real Foundation module loading; a Rust-backed Amplifier session; actual upstream tool-loop/approval/steering/compaction behavior with the facades; installed provider-specific streaming behavior; live Jev model availability, accuracy, calibration, latency, billing or end-to-end task speedup. The sandbox has no installed Amplifier/TypeSafe packages or API key, and GitHub full-file access was SSO-restricted. Offline fixture tests are not substitutes for these checks.

The CI workflow is supplied but was not run on GitHub in this session. The local interpreter was Python 3.13. The configured 3.11/3.12/3.13 CI matrix has not yet been executed.

## First host acceptance test

Use the README shadow profile on a disposable public checkout. Verify an actual TypeSafe model appears in scored events, with only slow execution in shadow. Then enable active mode for one explicit read-only file candidate. Confirm a native denial prevents actual execute(), and verify timeout/cancellation fall back or cancel without unauthorized work. Preserve your installed commits and export an allowlisted trace before expanding the fast-path tool set.

No source files were pushed to GitHub and no existing Amplifier repository, default bundle, account or installed runtime was modified by this build.
