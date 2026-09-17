"""Optional native-event bridge; observes but never grants permission."""
from __future__ import annotations
from .contracts import field_value
from .runtime import get_runtime

__amplifier_module_type__ = "hook"


async def mount(coordinator, config: dict):
    from amplifier_core.models import HookResult
    runtime, owner = get_runtime(coordinator, config)
    registrations = []

    async def observe(event: str, data: dict):
        # Allowlisted structural fields only. Never copy native event bodies.
        tool = data.get("tool_name") or data.get("tool")
        if not isinstance(tool, str):
            tool = field_value(tool, "name", None)
        await runtime.service.emit("health", {"native_event": event,
            "event_source": "native-hook-bridge", "tool": tool,
            "tool_call_id": data.get("tool_call_id"), "phase": data.get("phase"),
            "status": "observed"})
        return HookResult(action="continue")

    for event in ("tool:pre", "tool:post", "provider:error"):
        registrations.append(coordinator.hooks.register(event, observe, priority=999))

    async def cleanup():
        for unregister in registrations:
            if callable(unregister):
                unregister()
        if owner:
            await runtime.close()
    return cleanup
