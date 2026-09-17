"""Hybrid orchestrator composed with the upstream streaming loop.

The upstream loop owns context, tools, approvals, steering and cancellation.
This module supplies contract-compatible provider/tool facades per execute().
It never patches a class, a global provider dictionary or amplifier-core.
"""
from __future__ import annotations
import asyncio
import time
from typing import Any
from uuid import uuid4

from .contracts import Candidate, TurnState, field_value, digest
from .runtime import Runtime, get_runtime

__amplifier_module_type__ = "orchestrator"


def action_response(candidate: Candidate, tool_call_id: str):
    """Create real Amplifier envelopes; fail at mount/doctor on schema drift."""
    from amplifier_core.message_models import ChatResponse, ToolCall, Usage
    return ChatResponse(
        content=[],
        tool_calls=[ToolCall(id=tool_call_id, name=candidate.tool, arguments=candidate.arguments)],
        usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
    )


def usage_fields(response: Any) -> dict:
    usage = field_value(response, "usage", {}) or {}
    return {k: field_value(usage, k) for k in ("input_tokens", "output_tokens", "total_tokens")}


class RoutedProvider:
    """Preserve the Provider protocol while intercepting complete() boundaries.

The nonstandard .stream path is deliberately hidden. The upstream loop's
complete() path retains normal tool handling. A provider may still stream
internally via complete(). See docs/COMPATIBILITY.md.
"""
    def __init__(self, provider: Any, runtime: Runtime, tools: dict[str, Any],
                 response_factory=action_response, provider_key: str | None = None):
        self._provider = provider
        self._runtime = runtime
        self._tools = tools
        self._response_factory = response_factory
        self._provider_key = provider_key or getattr(provider, "name", "unknown")
        self._synthetic_responses: dict[int, Any] = {}

    def __getattr__(self, name: str):
        if name in {"stream", "__wrapped__"}:
            raise AttributeError(name)
        return getattr(self._provider, name)

    @property
    def name(self):
        return self._provider.name

    def get_info(self):
        return self._provider.get_info()

    async def list_models(self):
        return await self._provider.list_models()

    def parse_tool_calls(self, response):
        # Provider-specific parsing must not attempt to decode a Jev envelope.
        if id(response) in self._synthetic_responses:
            return response.tool_calls or []
        return self._provider.parse_tool_calls(response)

    async def complete(self, request, **kwargs):
        service = self._runtime.service
        candidate = await service.choose(request, self._tools)
        turn = service.turn
        assert turn is not None
        if candidate:
            tool_call_id = "fd_" + uuid4().hex[:24]
            # Build the envelope BEFORE committing an execution mapping. If the
            # core schema has drifted, make the failure visible, then use slow.
            try:
                response = self._response_factory(candidate, tool_call_id)
            except Exception as exc:
                await service.emit("fallback", {"reason_code": "envelope_incompatible",
                                                 "exception_type": type(exc).__name__})
                await service.emit("routed", {"route": "slow", "destination": self._provider_key,
                                              "reason_code": "envelope_incompatible"})
            else:
                turn.used.add(candidate.fingerprint)
                turn.fast_streak += 1
                turn.fast_total += 1
                await service.emit("routed", {"mode": service.policy.mode,
                    "backend": service.backend.name, "policy_version": service.policy.version,
                    "route": "fast", "destination": candidate.tool,
                    "selected_candidate": candidate.id, "reason_code": "prepared_action_selected",
                    "status": "submitted_to_upstream"})
                turn.tool_decisions[tool_call_id] = {
                    "decision_id": service.last_decision_id, "tool": candidate.tool,
                    "arguments_hash": digest(candidate.arguments), "claimed": False,
                }
                self._synthetic_responses[id(response)] = response
                return response
        turn.fast_streak = 0
        service.slow_total += 1
        model = field_value(request, "model") or "provider-default"
        decision_id = service.last_decision_id
        await service.emit("slow_start", {"provider": self._provider_key, "model": model,
            "route": "slow", "destination": self._provider_key, "status": "running"}, decision_id)
        start = time.perf_counter()
        try:
            # Preserve the actual request, model override, kwargs, and response identity.
            response = await self._provider.complete(request, **kwargs)
        except asyncio.CancelledError:
            await service.emit("slow_end", {"provider": self._provider_key, "model": model,
                "status": "cancelled", "duration_ms": (time.perf_counter() - start) * 1000}, decision_id)
            raise
        except Exception as exc:
            await service.emit("slow_end", {"provider": self._provider_key, "model": model,
                "status": "error", "exception_type": type(exc).__name__,
                "duration_ms": (time.perf_counter() - start) * 1000}, decision_id)
            raise
        await service.emit("slow_end", {"provider": self._provider_key, "model": model,
            "status": "ok", "duration_ms": (time.perf_counter() - start) * 1000,
            **usage_fields(response), "latency_kind": "provider_complete_wall_time"}, decision_id)
        return response


class ObservedTool:
    """Measure actual execute(), not merely a tool:pre hook which may be denied."""
    def __init__(self, tool: Any, runtime: Runtime, tool_key: str):
        self._tool, self._runtime, self._tool_key = tool, runtime, tool_key

    def __getattr__(self, name):
        return getattr(self._tool, name)

    async def execute(self, input: dict[str, Any], **kwargs):
        service = self._runtime.service
        turn = service.turn
        decision_id = service.last_decision_id
        tool_call_id = "observed_" + uuid4().hex[:20]
        if turn:
            fingerprint = digest(input)
            for call_id, info in turn.tool_decisions.items():
                if not info["claimed"] and info["tool"] == self._tool_key and info["arguments_hash"] == fingerprint:
                    info["claimed"] = True
                    tool_call_id = call_id
                    decision_id = info["decision_id"]
                    break
            turn.revision += 1
        fields = {"tool": self._tool_key, "tool_call_id": tool_call_id, "status": "running"}
        await service.emit("tool_start", fields, decision_id)
        start = time.perf_counter()
        try:
            result = await self._tool.execute(input, **kwargs)
        except asyncio.CancelledError:
            await service.emit("tool_end", {**fields, "status": "cancelled", "success": False,
                "duration_ms": (time.perf_counter() - start) * 1000}, decision_id)
            raise
        except Exception as exc:
            await service.emit("tool_end", {**fields, "status": "error", "success": False,
                "exception_type": type(exc).__name__, "duration_ms": (time.perf_counter() - start) * 1000}, decision_id)
            raise
        else:
            success = field_value(result, "success", None)
            await service.emit("tool_end", {**fields, "status": "ok" if success is not False else "error",
                "success": success, "duration_ms": (time.perf_counter() - start) * 1000}, decision_id)
            return result
        finally:
            if turn:
                turn.revision += 1


class HybridOrchestrator:
    def __init__(self, config: dict[str, Any], coordinator: Any, runtime: Runtime,
                 *, upstream: Any = None, response_factory=action_response):
        self.config = config
        self.coordinator = coordinator
        self.runtime = runtime
        self.response_factory = response_factory
        if upstream is None:
            try:
                from amplifier_module_loop_streaming import StreamingOrchestrator
            except ImportError as exc:
                raise RuntimeError("Install the amplifier extra in the SAME environment as Amplifier") from exc
            # Upstream configuration is explicit; no accidental forwarding of Jev settings.
            upstream = StreamingOrchestrator(dict(config.get("upstream", {})))
        self.upstream = upstream

    async def execute(self, prompt, context, providers, tools, hooks, **kwargs) -> str:
        async with self.runtime.lock:
            service = self.runtime.service
            service.turn = TurnState(uuid4().hex)
            service.last_decision_id = None
            service.slow_total = 0
            service.emitter.hooks = hooks
            await service.emit("turn_start", {"mode": service.policy.mode,
                "backend": service.backend.name, "engine": "upstream-loop-streaming",
                "transport": "provider-complete", "policy_version": service.policy.version})
            # Provider keys and defaults are unchanged. Upstream pins and selections apply.
            wrapped_tools = {key: ObservedTool(tool, self.runtime, key) for key, tool in tools.items()}
            wrapped_providers = {key: RoutedProvider(provider, self.runtime, tools,
                self.response_factory, key) for key, provider in providers.items()}
            kwargs.setdefault("coordinator", self.coordinator)
            try:
                return await self.upstream.execute(prompt, context, wrapped_providers, wrapped_tools, hooks, **kwargs)
            except asyncio.CancelledError:
                await service.emit("cancelled", {"reason_code": "turn_cancelled"})
                raise
            finally:
                await service.emit("turn_end", {"fast_total": service.turn.fast_total,
                    "slow_total": service.slow_total,
                    **(self.runtime.recorder.health if self.runtime.recorder else {})})
                service.turn = None
                service.last_decision_id = None

    async def cleanup(self):
        await self.runtime.close()


async def mount(coordinator, config: dict):
    # Validate envelope construction before entering any user turn.
    action_response(Candidate("compat_check", "Schema check", "fast_workspace", {"operation": "list", "path": "."}), "compat_check")
    # The orchestrator owns decision policy; win regardless of module mount order.
    runtime, _ = get_runtime(coordinator, config, owner=True)
    try:
        orchestrator = HybridOrchestrator(config, coordinator, runtime)
        await coordinator.mount("session", orchestrator, name="orchestrator")
    except Exception:
        await runtime.close()
        raise
    return orchestrator.cleanup
