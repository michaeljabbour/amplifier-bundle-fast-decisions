# Human / coding-agent handoff

Goal: verify the experimental bundle in the user's real Amplifier environment without changing the Rust kernel or default app configuration.

1. Read README, COMPATIBILITY and PRIVACY. Do not reinterpret offline fixture tests as upstream tests.
2. Run `python3 -m unittest discover -s tests -v` and the no-key demo. Capture failures before editing.
3. In the actual Amplifier host, record Python, core, loop, Foundation, provider and SDK versions/commits. Run the appropriate import/schema checks in that same environment.
4. Generate the local shadow profile using the configure command. Set a key via the environment and explicitly authorize external public state. Register as an ordinary named bundle, not `--app`; run once on a disposable public checkout.
5. Confirm requested/scored/slow_start with real model identity. No fast tool execution should occur because of shadow suggestions. Confirm no raw text/arguments/outputs appear in observatory logs.
6. Generate an active profile. Run the explicit README.md prompt. Confirm native approval denies a fast submission when configured to deny, and no actual tool_start is emitted for that denied call. Test allowed, modified, stale, timeout and cancelled paths separately.
7. Test the actual installed loop's cancellation, steering, usage meter/compaction and provider pin behaviors. Compare ordinary baseline vs hybrid correctness before measuring speed.
8. If envelope/provider/SDK shape has drifted, fix the adapter and add a regression. Never bypass approval hooks or silently execute tools directly to get a demo passing.
9. Export an allowlisted trace and annotate the test outcome. Do not ship API keys, private prompts, private tool outputs or blanket performance claims.

Definition of host-validated: actual Foundation loads all modules, actual core envelopes are accepted, native approvals are preserved, actual tools and slow model produce a correct task result, cancellation/errors are handled, and the trace corresponds to real execution.
