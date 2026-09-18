# Privacy, security and operating boundary

## Three different data paths

1. **TypeSafe:** external requests are disabled by default. Opt-in sends the bounded current task snapshot, prepared candidate descriptions, and any contributed judgment questions (`fast_decisions.questions`) -- all batched into a single request. The state projection excludes system/developer messages, private thinking blocks, images and executable argument objects. Public user/tool/assistant text can contain confidential information. Labels, rationales and question instructions can also contain sensitive details. This applies identically to shadow measurement running in `hooks-fast-decisions`: with `allow_external_state: false` (the shipped default) no TypeSafe/Jev client is ever constructed for shadow scoring; the snapshot it reads comes from the mounted context manager, bounded by `shadow_max_messages` and `max_state_chars`, same bounds and same opt-in gate as the active path. The shadow-only model-role router (`role_router`, on by default in `behaviors/fast-decisions.yaml`) sends no additional state to TypeSafe -- it reads the `model_role_resolver` capability locally to enumerate live roles and never contacts an external backend itself.
2. **Local observatory:** stores allowlisted metadata, probability distributions, model/tool names, hashes, IDs and timing. It excludes raw prompts, arguments, tool outputs, exception messages and private reasoning. Metadata can still be sensitive. Review it before exporting.
3. **Other Amplifier modules:** their existing tracing/logging policies are unchanged. This bundle cannot promise that unrelated native loggers redact all content.

Scrubbing masks common key, bearer, secret-assignment and private-key patterns. **It is not a DLP system, prompt-injection defense or guarantee of anonymization.** Test only public/disposable workspaces initially. Review TypeSafe's data handling separately before using private company material. The SDK documents header redaction but not body redaction; do not enable HTTP/SDK debug body logging with private state.

## Actions and authority

The bundled workspace tool supports read/list only, resolves paths under an explicit root, rejects symlink components, traversal, absolute paths, hidden/sensitive filenames, binary data and unsupported file types, bounds output and rechecks revisions. It is a convenience guard, not an OS-level sandbox against an adversary racing filesystem changes. Use a disposable checkout or container with appropriate file permissions.

Other tools require explicit allowlisting and a trusted validator. Those controls restrict routing eligibility, but native permission hooks are still required for actions that need them. Do not base mandatory authorization on an optional observer hook or a model confidence score. Do not treat the read-only default as authorization to enable writes globally.

## Viewer

The server binds only to 127.0.0.1, requires a random bearer token on data endpoints, checks Host/Origin, applies a content-security policy and serves a fixed static asset allowlist. It has no execution, approval, configuration or write API. The token is delivered in the URL fragment, moved to session storage and removed from the visible location. Do not publish the printed token-bearing URL. Loopback plus a token does not defend against compromised local processes.

**Auto-observatory state file:** when the hook auto-starts the viewer (`observatory.enabled: true`, the default), it writes `~/.amplifier/fast-decisions/serve.json` (`--state-file` to override) containing the viewer's pid, port, the token-bearing URL, events directory, start time and version. This file is written mode `0600` (owner read/write only) via atomic tmp-file-plus-rename, and is removed on clean shutdown (`afast serve --stop`, or the server's own exit handler). Treat it like the token itself: local-only, not for sharing, and readable only by the invoking user's account. `afast serve --stop` reads it, signals the pid and removes it regardless of whether the process was still alive.

The configuration event carries `workspace_name`, the basename of the session's working directory (for example `my-repo`), so the viewer can name sessions; parent directories, home paths and full paths are never recorded. Set `workspace_name` in the hook config to override it.

The original logs use private file permissions where supported. The queue is bounded and best-effort, not a regulatory-grade audit ledger. Offline HTML and JSONL exports are deliberately shareable files and are not encrypted. Protect or delete them according to your organization's retention policy.
