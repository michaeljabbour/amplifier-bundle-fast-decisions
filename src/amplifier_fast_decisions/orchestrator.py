"""Hybrid orchestrator composed with the upstream streaming loop.

The upstream loop owns context, tools, approvals, steering and cancellation.
This module supplies contract-compatible provider/tool facades per execute().
It never patches a class, a global provider dictionary or amplifier-core.
"""
from __future__ import annotations
import asyncio
import re
import time
from typing import Any
from uuid import uuid4

from .contracts import (
    Candidate,
    TurnState,
    field_value,
    digest,
    candidate_read_identity,
)
from . import effort
from .runtime import Runtime, get_runtime
from . import provenance

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


# HC04 ("opt-in model routing with escalation"): test-failure detection.
# Conservative and text-pattern based -- never raises, never inspects
# arguments, only the already-observed tool result text (capped at 20k
# chars before matching). See docs/ARCHITECTURE.md.
_TEST_TOOL_NAMES = frozenset({"bash", "python_check", "run_tests"})
_TEST_FAILURE_PATTERNS = (
    re.compile(r"FAILED \("),
    re.compile(r"FAIL:"),
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"(?m)^Error:"),
    re.compile(r"\b\d+\s+failed\b"),
)


def _is_test_tool(tool_key: str) -> bool:
    return tool_key in _TEST_TOOL_NAMES or "test" in tool_key


def _tool_result_text(result: Any) -> str:
    """Best-effort, defensive stringification of a tool result, capped at 20k chars.

    Never raises: an object with none of the common output fields falls
    back to ``str(result)``, and any exception there yields an empty string.
    """
    for attr in ("output", "result", "stdout", "content"):
        value = field_value(result, attr, None)
        if isinstance(value, str):
            return value[:20000]
    try:
        return str(result)[:20000]
    except Exception:
        return ""


def _test_failure_observed(text: str) -> bool:
    return any(pattern.search(text) for pattern in _TEST_FAILURE_PATTERNS)


class RoutedProvider:
    """Preserve the Provider protocol while intercepting complete() boundaries.

The facade is transport-transparent: `stream` is mirrored iff the wrapped
provider actually has it, and proxied verbatim -- the fast path is attempted
only in complete(). loop-streaming's streaming branch cannot dispatch tool
calls (_has_pending_tools is hard-coded False), so synthesizing a response
on that transport would fail open (drop the action silently) instead of
failing closed (defer to the LLM). See docs/COMPATIBILITY.md and
docs/UPSTREAM_CONTRACT.md.
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
        if name == "stream":
            inner = getattr(self._provider, "stream", None)
            if not callable(inner):
                raise AttributeError(name)  # mirror absence exactly
            return self._stream_proxy
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
                                              "reason_code": "envelope_incompatible",
                                              "transport_measured": "provider-complete"})
            else:
                turn.used.add(candidate.fingerprint)
                turn.fast_streak += 1
                turn.fast_total += 1
                # HC02a: a fast submission is a completed read too -- record
                # it so a second proposal of the same unchanged file is
                # suppressed on the next decision in this turn.
                if service.policy.suppress_completed_reads:
                    identity = candidate_read_identity(candidate, self._tools)
                    if identity is not None:
                        turn.completed_reads[identity[0]] = identity[1]
                await service.emit("routed", {"mode": service.policy.mode,
                    "backend": service.backend.name, "policy_version": service.policy.version,
                    "route": "fast", "destination": candidate.tool,
                    "tool_call_id": tool_call_id,
                    "selected_candidate": candidate.id, "reason_code": "prepared_action_selected",
                    "status": "submitted_to_upstream", "transport_measured": "provider-complete"})
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
        provider_call_id = "provider_" + uuid4().hex
        # HC03 ("phase-specific effort routing", opt-in): entirely skipped
        # -- no attribute touched, no event emitted -- when the policy has
        # no effort_routing configured. See effort.py and docs/EVENTS.md.
        effort_routing = service.policy.effort_routing
        effort_applied_this_request = False
        phase = None
        if effort_routing:
            phase = effort.classify_phase(request)
            explore_requests = (
                turn.explore_requests + 1 if phase == effort.PHASE_EXPLORE else turn.explore_requests
            )
            host_pinned = field_value(request, "reasoning_effort", None) is not None
            applied_effort, reason_code = effort.decide_effort(
                phase,
                effort_routing,
                explore_requests=explore_requests,
                provider_errors_seen=turn.provider_errors_seen,
                host_pinned=host_pinned,
            )
            if phase == effort.PHASE_EXPLORE:
                turn.explore_requests = explore_requests
            if applied_effort is not None:
                if isinstance(request, dict):
                    request["reasoning_effort"] = applied_effort
                else:
                    setattr(request, "reasoning_effort", applied_effort)
                turn.effort_routed_requests += 1
                effort_applied_this_request = True
            await service.emit("effort_routed", {
                "phase": phase, "requested_effort": applied_effort,
                "default_effort": "provider_default", "reason_code": reason_code,
                "explore_requests": turn.explore_requests,
                "provider_call_id": provider_call_id, "mode": service.policy.mode,
            }, decision_id)
        # HC04 ("opt-in model routing with escalation", opt-in): entirely
        # skipped -- no attribute touched, no event emitted -- when the
        # policy has no model_routing configured. See docs/ARCHITECTURE.md.
        model_routing = service.policy.model_routing
        if model_routing:
            start_model = model_routing["start_model"]
            start_effort = model_routing.get("start_effort")
            max_requests = model_routing.get("max_requests_before_escalation")
            override_explicit = model_routing.get("override_explicit_model", False)
            escalate_on_test_failure = model_routing.get("escalate_on_test_failure", False)

            turn.slow_requests_seen += 1
            if not turn.escalated:
                if escalate_on_test_failure and turn.test_failure_seen:
                    turn.escalated, turn.escalation_reason = True, "test_failure"
                elif max_requests is not None and turn.slow_requests_seen > max_requests:
                    turn.escalated, turn.escalation_reason = True, "max_requests"

            routing_phase = phase if phase is not None else effort.classify_phase(request)
            requested_model = None
            requested_effort = None
            if turn.escalated:
                reason_code = f"escalated_{turn.escalation_reason}"
            else:
                explicit_model = field_value(request, "model", None)
                if explicit_model and not override_explicit:
                    reason_code = "host_pinned"
                else:
                    requested_model = start_model
                    if isinstance(request, dict):
                        request["model"] = start_model
                    else:
                        setattr(request, "model", start_model)
                    # The verified installed Anthropic provider reads the
                    # per-request model from kwargs (`kwargs.get("model", ...)`),
                    # never from request.model -- see docs/ARCHITECTURE.md.
                    # Setting request.model alone would be a receipt that
                    # lies about what was actually served.
                    kwargs["model"] = start_model
                    if (
                        start_effort is not None
                        and not effort_applied_this_request
                        and field_value(request, "reasoning_effort", None) is None
                    ):
                        requested_effort = start_effort
                        if isinstance(request, dict):
                            request["reasoning_effort"] = start_effort
                        else:
                            setattr(request, "reasoning_effort", start_effort)
                    turn.model_routed_requests += 1
                    reason_code = "start_model"
            await service.emit("model_routed", {
                "phase": routing_phase, "requested_model": requested_model,
                "requested_effort": requested_effort, "reason_code": reason_code,
                "escalated": turn.escalated, "escalation_reason": turn.escalation_reason,
                "model_routed_requests": turn.model_routed_requests,
                "provider_call_id": provider_call_id, "mode": service.policy.mode,
            }, decision_id)
            # Reflect any routing-applied model in the slow_start/slow_end
            # receipts below -- otherwise they'd keep showing the
            # pre-routing value even though a different model was requested.
            model = field_value(request, "model") or model
        await service.emit("slow_start", {"provider": self._provider_key, "model": model,
            "provider_call_id": provider_call_id,
            "route": "slow", "destination": self._provider_key, "status": "running",
            "transport_measured": "provider-complete"}, decision_id)
        start = time.perf_counter()
        try:
            # Preserve the actual request, model override, kwargs, and response identity.
            response = await self._provider.complete(request, **kwargs)
        except asyncio.CancelledError:
            await service.emit("slow_end", {"provider": self._provider_key, "model": model,
                "provider_call_id": provider_call_id,
                "status": "cancelled", "duration_ms": (time.perf_counter() - start) * 1000,
                "transport_measured": "provider-complete"}, decision_id)
            raise
        except Exception as exc:
            turn.provider_errors_seen += 1
            if model_routing and not turn.escalated and model_routing.get("escalate_on_provider_error"):
                turn.escalated, turn.escalation_reason = True, "provider_error"
            await service.emit("slow_end", {"provider": self._provider_key, "model": model,
                "provider_call_id": provider_call_id,
                "status": "error", "exception_type": type(exc).__name__,
                "duration_ms": (time.perf_counter() - start) * 1000,
                "transport_measured": "provider-complete"}, decision_id)
            raise
        await service.emit("slow_end", {"provider": self._provider_key, "model": model,
            "provider_call_id": provider_call_id,
            "status": "ok", "duration_ms": (time.perf_counter() - start) * 1000,
            **usage_fields(response), "latency_kind": "provider_complete_wall_time",
            "transport_measured": "provider-complete"}, decision_id)
        return response

    async def _stream_proxy(self, request, **kwargs):
        """Verbatim proxy of the provider's stream transport.

        The fast path is structurally unavailable here: loop-streaming's
        streaming branch cannot dispatch tool calls (`_has_pending_tools`
        always returns False, see docs/UPSTREAM_CONTRACT.md). We therefore
        never ask the service and never synthesize a response on this
        transport -- fail closed (defer to the real provider) rather than
        fail open (drop a prepared action silently).
        """
        service = self._runtime.service
        await service.emit("routed", {"route": "slow", "destination": self._provider_key,
            "reason_code": "fast_path_unavailable_on_transport",
            "transport_measured": "provider-stream"})
        start = time.perf_counter()
        provider_call_id = "provider_" + uuid4().hex
        await service.emit("slow_start", {"provider": self._provider_key,
            "provider_call_id": provider_call_id,
            "route": "slow", "destination": self._provider_key, "status": "running",
            "transport_measured": "provider-stream"})
        status = "error"
        try:
            async for chunk in self._provider.stream(request, **kwargs):
                yield chunk
            status = "ok"
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            await service.emit("slow_end", {"provider": self._provider_key,
                "provider_call_id": provider_call_id, "status": status,
                "duration_ms": (time.perf_counter() - start) * 1000,
                "transport_measured": "provider-stream"})


class ObservedTool:
    """Measure actual execute(), not merely a tool:pre hook which may be denied."""
    def __init__(
        self, tool: Any, runtime: Runtime, tool_key: str, *, workspace: Any = None
    ):
        self._tool, self._runtime, self._tool_key = tool, runtime, tool_key
        # HC02a: the raw fast_workspace tool (never wrapped, never executed
        # from here) used only to normalize a native read_file's file_path
        # into the same (path, revision) identity space as candidates.
        self._workspace = workspace

    def __getattr__(self, name):
        return getattr(self._tool, name)

    def _completed_read_identity(self, input: dict[str, Any]) -> tuple[str, str] | None:
        """HC02a: ``(normalized path, revision)`` for a successful read/list
        this tool call just performed, or ``None`` when this tool/shape is
        not part of the ledger (or the path cannot be normalized).

        Covers ``fast_workspace`` read/list (via its own ``read_identity``)
        and the native ``read_file`` tool's ``file_path`` (resolved against
        the fast_workspace tool's configured root, if one is mounted).
        """
        if not isinstance(input, dict):
            return None
        if self._tool_key == "fast_workspace":
            operation = input.get("operation")
            path = input.get("path")
            identity_fn = getattr(self._tool, "read_identity", None)
        elif self._tool_key == "read_file":
            operation, path = "read", input.get("file_path")
            identity_fn = (
                getattr(self._workspace, "read_identity", None)
                if self._workspace
                else None
            )
        else:
            return None
        if (
            not callable(identity_fn)
            or not isinstance(path, str)
            or operation not in ("read", "list")
        ):
            return None
        try:
            result = identity_fn(path, operation)
        except Exception:
            return None
        if not isinstance(result, tuple) or len(result) != 2:
            return None
        key, revision = result
        return str(key), str(revision)

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
            if (
                turn
                and success is not False
                and service.policy.suppress_completed_reads
            ):
                identity = self._completed_read_identity(input)
                if identity is not None:
                    turn.completed_reads[identity[0]] = identity[1]
            # HC04 ("opt-in model routing with escalation"): observe a
            # successful test-tool execution's own result text for a
            # failure signature. Only tracked once per turn (subsequent
            # detections are redundant) and only while model_routing is
            # configured -- inert otherwise, matching every other HC04 seam.
            if (
                turn
                and not turn.test_failure_seen
                and service.policy.model_routing
                and _is_test_tool(self._tool_key)
            ):
                if _test_failure_observed(_tool_result_text(result)):
                    turn.test_failure_seen = True
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
            # No self-authored "transport" claim here: a turn may enter the
            # facade through complete() and/or stream() multiple times, each
            # measured independently at the point of entry (transport_measured
            # on routed/slow_start/slow_end). See docs/UPSTREAM_CONTRACT.md.
            await service.emit("turn_start", {"mode": service.policy.mode,
                "backend": service.backend.name, "engine": "upstream-loop-streaming",
                "policy_version": service.policy.version,
                "allow_external_state": service.policy.allow_external_state,
                "effort_routing_enabled": bool(service.policy.effort_routing),
                "model_routing_enabled": bool(service.policy.model_routing)})
            # Provider keys and defaults are unchanged. Upstream pins and selections apply.
            workspace_tool = tools.get("fast_workspace")
            wrapped_tools = {
                key: ObservedTool(tool, self.runtime, key, workspace=workspace_tool)
                for key, tool in tools.items()
            }
            wrapped_providers = {key: RoutedProvider(provider, self.runtime, tools,
                self.response_factory, key) for key, provider in providers.items()}
            kwargs.setdefault("coordinator", self.coordinator)
            started = time.perf_counter()
            status = "error"
            try:
                response = await self.upstream.execute(prompt, context, wrapped_providers, wrapped_tools, hooks, **kwargs)
                status = "ok"
                return response
            except asyncio.CancelledError:
                status = "cancelled"
                await service.emit("cancelled", {"reason_code": "turn_cancelled"})
                raise
            finally:
                await service.emit("turn_end", {"fast_total": service.turn.fast_total,
                    "status": status, "duration_ms": (time.perf_counter() - started) * 1000,
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
    # HC00 ("freeze source"): the same receipt hooks-fast-decisions emits,
    # from the orchestrator side too -- best-effort, never fatal to mount.
    try:
        await runtime.service.emit(
            "source",
            provenance.source_event_data(
                mode=runtime.service.policy.mode, module="loop-fast-decisions"
            ),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    try:
        orchestrator = HybridOrchestrator(config, coordinator, runtime)
        await coordinator.mount("orchestrator", orchestrator)
    except Exception:
        await runtime.close()
        raise
    return orchestrator.cleanup
