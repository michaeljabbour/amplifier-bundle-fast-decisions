"""Thin Amplifier module entrypoint. Shared code is provided by the root bundle package."""
__amplifier_module_type__ = "tool"
from amplifier_fast_decisions.workspace import mount
__all__ = ["mount"]
