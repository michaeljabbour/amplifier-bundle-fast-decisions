# Source references

Reviewed September 16-17, 2026 (UTC). These links document contracts; they do not certify this implementation.

- Orchestrator: https://github.com/microsoft/amplifier-core/blob/main/docs/contracts/ORCHESTRATOR_CONTRACT.md
- Provider: https://github.com/microsoft/amplifier-core/blob/main/docs/contracts/PROVIDER_CONTRACT.md
- Hook: https://github.com/microsoft/amplifier-core/blob/main/docs/contracts/HOOK_CONTRACT.md
- Hook registration: https://github.com/microsoft/amplifier-core/blob/main/docs/HOOKS_API.md
- Contributions: https://github.com/microsoft/amplifier-core/blob/main/docs/specs/CONTRIBUTION_CHANNELS.md
- Foundation bundle guide: https://github.com/microsoft/amplifier-foundation/blob/main/docs/BUNDLE_GUIDE.md
- Streaming indexed snapshot: https://github.com/microsoft/amplifier-module-loop-streaming/tree/20aac7a9eb26034d230357f6aa6805f27c86df52
- Core indexed snapshot: https://github.com/microsoft/amplifier-core/tree/6d4cd217f83bb29b671b5c9d854aaa08be14db1b
- CLI indexed snapshot, named bundle usage and global --app semantics: https://github.com/microsoft/amplifier-app-cli/tree/4d168ed822314dced895c8cf7fdbb24233cbe31b
- TypeSafe async API: https://docs.typesafe.ai/sdk/python/api/clients/async/client
- TypeSafe question dictionaries: https://docs.typesafe.ai/sdk/python/api/types/questions
- TypeSafe response shape: https://docs.typesafe.ai/sdk/python/api/types/responses

Architectural decisions in this package are original implementation choices, not claims that Microsoft recommends this particular facade approach. Most importantly, hiding a provider's separate .stream entrypoint is an explicit prototype compatibility tradeoff.
