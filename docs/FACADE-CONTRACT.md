# Facade contract: what host code may do to a routed provider or observed tool

In orchestrator mode, `RoutedProvider` and `ObservedTool` existed only inside one `execute()` call, and only the
upstream loop ever saw them. Registry mode (docs/REGISTRY-MODE.md) mounts them in the coordinator's provider and
tool registries for the whole session, so **every piece of host code that touches a provider or tool now touches a
facade**. Host code does more than call `complete()` and `execute()`. This document records what it does, which
patterns broke, and the contract that `src/amplifier_fast_decisions/facade.py` now guarantees.

## Incident (2026-09-30)

After registry mode shipped, chats in Amplifier Unified and the Amplifier CLI stopped getting automatic names and
kept the fallback title `Conversation <id>`.

- `hooks-session-naming` calls `copy.copy(provider)` and sets `coordinator` on the copy, so the naming call's own
  provider events are stamped as naming, not as conversation activity.
- `copy.copy` rebuilt a `RoutedProvider` without running `__init__` and then looked up `_provider`. The facade's
  `__getattr__` forwarded that lookup to `self._provider`, which recursed until Python raised `RecursionError`.
- The naming hook catches every exception and skips the call, so the model was never asked and nothing reported
  an error. Unified's "regenerate name" returned "No new name was returned".

Amplifier Unified's own session found the recursion and patched its naming code. The root cause is in the facade,
so the fix belongs here. The Unified patch becomes optional defense in depth.

## Audit: how hosts touch registry objects

Scanned: amplifier-app-cli, amplifier-runtime (TUI and Studio), Amplifier Unified (source and runtime), and every
module in `~/.amplifier/cache` and Unified's foundation cache. Third-party libraries were excluded.

| Consumer | Pattern | Before | Contract rule |
|---|---|---|---|
| `hooks-session-naming` (all hosts) | `copy.copy(provider)`, then `stamped.coordinator = view` | `RecursionError`, so no chat names | Copy wraps a copy of the provider; a public value reaches it |
| dot-runner `loop-pipeline` | Clones a tool per parallel branch when `"last_outcome" in tool.__dict__`, via `copy.copy(tool)` | Wrapper's `__dict__` hid the state, so branches shared one tool (race), and `copy.copy(ObservedTool)` raised `TypeError` | `vars()`/`__dict__` show the wrapped state; tools copy |
| hook-computer-use | `original = provider.complete; provider.complete = wrapper`; private flag attributes | Worked | Callables and private names stay on the facade |
| Unified telemetry (`execution_events.py`) | Patches `complete`, `compact_context`, `stream`; sets `_amplifier_web_observed` | Worked | Same. Forwarding a patch would make the wrapped provider call back into the facade forever |
| Mid-session model switch | `provider.default_model = …` | Would have set it on the facade only, so the provider kept its old model | Public non-callable values reach the provider |
| amplifier-runtime `model_routing.py` | Provider family from `name`, `module`, `config`, and `type(provider).__module__/__name__` | Worked; the type adds an extra, harmless identity | None needed |
| loop-streaming | `getattr(type(tool), "native_tool_spec", None)` | Handled (`_observed_class_for`) | Unchanged |
| Deep copies | `copy.deepcopy(provider)` | Failed on the facade's thread lock | Deep-copies the wrapped object; session wiring is shared. Fails exactly when the raw object would |

## Contract

1. `copy.copy(facade)` returns a facade over `copy.copy(wrapped)` with the same facade settings.
   `copy.deepcopy` deep-copies the wrapped object and shares the session runtime.
2. Private (`_x`) and dunder names never fall through to the wrapped object, so a half-built instance raises
   `AttributeError` instead of recursing.
3. Assigning a public non-callable value forwards it to the wrapped object. Callables, private names, and names
   the facade class defines stay on the facade.
4. `vars(facade)` and `facade.__dict__` return the wrapped object's instance dictionary. The facade's own state is
   reached through `own_state(facade)` in `facade.py`.
5. Transport is mirrored: `hasattr(facade, "stream")` matches the wrapped provider (docs/COMPATIBILITY.md).

`tests/test_facade_contract.py` checks each rule. It includes the dot-runner clone logic verbatim and, in the
real-kernel lane, the installed `hooks-session-naming` stamping a routed provider.

## Second failure class: a stale shared package

Every build of `amplifier-fast-decisions` is version `0.1.0`, pinned to `@main`. Each host environment installs
it separately, and an installer keeps an older copy because it appears to satisfy the requirement. On 2026-09-29
the CLI's environment still had a build from before registry mode, so the router hook failed to import and the
CLI dropped it with no visible error. Unified was unaffected because its runtime installs the package editable
from its bundle cache.

- The router entry point now raises an `ImportError` that names the stale file and the repair command.
- `afast doctor` probes every Amplifier host environment it finds (the CLI, amplifier-app-cli, amplifier-runtime,
  and Unified runtimes) when settings compose registry mode, and flags a stale package with the repair command.

## Rule for future facades

Any object this bundle puts into a host registry must satisfy this contract. Add the consumer pattern to the
audit table and a case to `tests/test_facade_contract.py` before relying on a new host behavior.
