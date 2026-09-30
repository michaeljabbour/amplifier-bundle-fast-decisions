"""Transparency contract for the provider and tool facades.

Registry mode (registry.py) mounts ``RoutedProvider`` and ``ObservedTool`` in
the coordinator's registries for the whole session, so every piece of host
code that touches a provider or tool now touches a facade, not only the loop.
Host code does more than call ``complete()``/``execute()``. It copies, stamps,
monkeypatches and inspects them. Each rule below comes from a real consumer
(docs/FACADE-CONTRACT.md):

- ``copy.copy`` / ``copy.deepcopy`` produce a facade over a copy of the
  wrapped object, as copying the raw object would. hooks-session-naming
  copies the provider and sets ``coordinator`` on the copy. Before this
  contract the copy recursed forever and chats silently kept their fallback
  names.
- Private and dunder names never fall through to the wrapped object, so a
  half-built instance raises AttributeError instead of recursing.
- Assigning a public, non-callable value (``coordinator``, ``default_model``)
  reaches the wrapped object: that is state the wrapped object reads itself.
  Callables (method patches by hook-computer-use and Unified's telemetry),
  private names and names the facade class defines stay on the facade. A
  patch forwarded to the wrapped object would call back into the facade that
  calls the wrapped object, forever.
- ``vars(facade)`` / ``facade.__dict__`` show the wrapped object's instance
  state (loop-pipeline decides whether to clone a tool by looking for
  ``last_outcome`` there). The facade's own state lives in the real instance
  dictionary, reached through ``own_state``.
"""
from __future__ import annotations

import copy
from typing import Any


class _InstanceDict:
    """Base providing the real per-instance dictionary descriptor."""


_REAL_DICT = _InstanceDict.__dict__["__dict__"]


def own_state(facade: Any) -> dict[str, Any]:
    """The facade's own instance dictionary (``__dict__`` is the wrapped view)."""
    return _REAL_DICT.__get__(facade)


class TransparentFacade(_InstanceDict):
    """Mixin: forward attribute access to ``getattr(self, _target_attr)``."""

    _target_attr = "_target"

    def _target_object(self) -> Any:
        try:
            return own_state(self)[self._target_attr]
        except KeyError:
            # Half-built (copy protocol, unpickling): never recurse.
            raise AttributeError(self._target_attr) from None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._target_object(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if (name.startswith("_") or callable(value) or hasattr(type(self), name)
                or self._target_attr not in own_state(self)):
            object.__setattr__(self, name, value)
        else:
            setattr(self._target_object(), name, value)

    def __delattr__(self, name: str) -> None:
        if name in own_state(self):
            object.__delattr__(self, name)
        else:
            delattr(self._target_object(), name)

    @property
    def __dict__(self) -> dict[str, Any]:  # type: ignore[override]
        return vars(self._target_object())

    def _copy_with(self, target: Any) -> Any:
        clone = object.__new__(type(self))
        state = own_state(clone)
        state.update(own_state(self))
        state[self._target_attr] = target
        return clone

    def __copy__(self) -> Any:
        return self._copy_with(copy.copy(self._target_object()))

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        # The wrapped object is copied deeply; the facade's session wiring
        # (runtime, locks, telemetry) is shared, as one session owns it.
        clone = self._copy_with(copy.deepcopy(self._target_object(), memo))
        memo[id(self)] = clone
        return clone

    def __repr__(self) -> str:
        target = own_state(self).get(self._target_attr)
        return f"<{type(self).__name__} over {target!r}>"
