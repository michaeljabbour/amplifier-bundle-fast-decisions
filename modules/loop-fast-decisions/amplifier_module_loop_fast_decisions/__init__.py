"""Thin Amplifier module entrypoint. Shared code is provided by the root bundle package."""
__amplifier_module_type__ = "orchestrator"
from amplifier_fast_decisions.orchestrator import mount
__all__ = ["mount"]
