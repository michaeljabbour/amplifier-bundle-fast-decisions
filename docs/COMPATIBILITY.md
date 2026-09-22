# Compatibility and verification boundary

## Public contracts used

- Orchestrator execute signature and mount semantics.
- Provider `complete(ChatRequest, **kwargs)` and `parse_tool_calls`.
- Typed `ChatResponse`, `ToolCall` and `Usage` envelopes.
- Tool `execute(input)` and metadata forwarding.
- Hook registration/unregister and `HookResult(action="continue")`.
- Coordinator capabilities and contribution channels.
- Foundation bundle includes, local module sources, root-package activation.

See [SOURCES.md](SOURCES.md) for source documents and pinned indexed snapshots. Full GitHub connector file fetches were blocked by organization SSO during this build. Public docs and indexed code excerpts were available. The sandbox could not install or run the actual core or streaming package. Source alignment is not a passed real-runtime integration test.

## Transport tradeoff

The provider facade is transport-transparent: `.stream` is mirrored exactly when the wrapped
provider has it, and proxied verbatim, so `callable(getattr(provider, "stream", None))` --
loop-streaming's own transport-selection expression -- returns the same answer wrapped or
unwrapped. No shipped provider currently implements `.stream` (verified by probing all nine
installed provider modules), so today this changes nothing about which transport runs; it removes a
latent, silent regression for any conforming third-party or future provider that does add one.

The fast path (a synthesized response standing in for an LLM turn) is attempted **only** inside
`complete()`. It is never attempted on the `stream` transport, because loop-streaming's streaming
branch cannot dispatch tool calls at all: `_has_pending_tools` is hard-coded to return `False`, and
`_process_tools` has no body on that path (see `docs/UPSTREAM_CONTRACT.md`). A prepared action
submitted through `stream()` would be silently dropped -- failing *open*. We fail *closed* instead:
the stream transport always defers to the real provider, with reason code
`fast_path_unavailable_on_transport`.

The next upstream-facing improvement would be a vendor-neutral decision boundary directly inside `loop-streaming`, tested in both transports. That would let the fast path reach the stream transport as well. It is not included as a speculative patch to unverified source in this release.

## Required host checks

Verify actual mounting, ChatRequest/ChatResponse schema, native approval-deny and approval-modify behavior, provider pins, model overrides, steering, cancellation during Jev/slow/tools, multi-tool turns, context compaction, tool-result pairing, child-session isolation, nested bundles, cleanup, actual TypeSafe models/quotas and the SDK version your host resolves.

A synthetic response has zero generative token usage. Depending on the host's usage-meter behavior, this may influence context-meter bookkeeping. Validate compaction/meters in the real loop before prolonged sessions. Jev usage is separately recorded in observatory events.

The shared capability is a Python object in the Python host. It is not a JSON-callable cross-language capability for Node or Rust consumers. The Rust core remains untouched. A Rust-only host would need a separate adapter.

## Dependencies

Core reference snapshot: `6d4cd217f83bb29b671b5c9d854aaa08be14db1b`.

Streaming reference snapshot: `20aac7a9eb26034d230357f6aa6805f27c86df52`.

The active loop module installs its wrapped `loop-streaming` at the pinned SHA above as a required dependency. Replacing the orchestrator means Foundation does not necessarily activate the displaced loop; relying on an optional extra or a warm module cache can fail on a fresh host. The former `upstream` extra remains accepted for compatibility. The root package's `amplifier` extra remains a local development convenience; do not independently upgrade core inside an existing app merely to try this bundle. Foundation is included from `main`; its transitive bundles and TypeSafe SDK are not locked here. Capture your resolved installation and core/loop commits after your first successful test before comparing performance.

`doctor` is environment-local. An import failure in system Python does not mean the same module is missing from a uv-managed CLI, and a passed check in an isolated venv does not verify the CLI host.

## Rollback

Run your prior primary bundle without `--bundle fast-decisions-*`. The recommended commands do not change your default or register a global app bundle. Stop the viewer with Ctrl+C. Local JSONL remains until you remove it. No cloud server, account mutation or kernel patch is installed by the demo.
