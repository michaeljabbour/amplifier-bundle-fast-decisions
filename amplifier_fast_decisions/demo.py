"""Transparent synthetic fixture using the REAL routing service and facades.

The upstream loop, envelopes, decision backend, tool and generative model are
contract doubles here. This is a visual/functionality demo, not a Jev benchmark.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from .backends import ScriptedBackend
from .contracts import Candidate, Policy, VALIDATOR_CAPABILITY
from .service import DecisionService
from .runtime import Runtime
from .orchestrator import HybridOrchestrator
from .telemetry import Emitter, JsonlRecorder


@dataclass
class DemoCall:
    id: str
    name: str
    arguments: dict


@dataclass
class DemoResponse:
    content: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    usage: Any = field(default_factory=lambda: SimpleNamespace(input_tokens=180, output_tokens=65, total_tokens=245))


def demo_response(candidate, call_id):
    return DemoResponse(tool_calls=[DemoCall(call_id, candidate.tool, candidate.arguments)])


class DemoHooks:
    def __init__(self):
        self.handlers: dict[str, list] = {}
        self.events = []
    def register(self, event, handler, priority=0, name=None):
        pair = (priority, handler)
        self.handlers.setdefault(event, []).append(pair)
        return lambda: self.handlers[event].remove(pair)
    async def emit(self, event, data):
        self.events.append((event, data))
        results = []
        for _, handler in sorted(self.handlers.get(event, []), key=lambda x: x[0]):
            result = await handler(event, data)
            results.append(result)
            if getattr(result, "action", None) == "deny":
                return result
        return SimpleNamespace(action="continue")


class DemoCoordinator:
    def __init__(self):
        self.session_id = "demo-" + uuid4().hex[:8]
        self.hooks = DemoHooks()
        self.capabilities = {VALIDATOR_CAPABILITY: lambda c: c.tool == "demo_inspect"}
        self.mounts = {}
        self.contributors = {}
    def register_capability(self, key, value):
        self.capabilities[key] = value
    def get_capability(self, key):
        return self.capabilities.get(key)
    def register_contributor(self, channel, name, callback):
        self.contributors.setdefault(channel, []).append(callback)
    async def collect_contributions(self, channel):
        return [cb() for cb in self.contributors.get(channel, [])]
    async def mount(self, category, value, name=None):
        self.mounts.setdefault(category, {})[name] = value


class DemoContext:
    def __init__(self):
        self.messages = []
    async def add_message(self, message):
        self.messages.append(message)
    async def get_messages(self):
        return self.messages


class DemoTool:
    name = "demo_inspect"
    description = "Synthetic, side-effect-free inspection action"
    input_schema = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}
    def __init__(self):
        self.executions = []
    async def execute(self, input, **kwargs):
        self.executions.append(input)
        await asyncio.sleep(0.025)
        return SimpleNamespace(success=True, output={"synthetic": True, "status": "inspected"})


class DemoProvider:
    name = "demo-reasoner"
    def __init__(self, delay_ms=360):
        self.calls = 0
        self.delay_ms = delay_ms
        self.requests = []
    def get_info(self):
        return SimpleNamespace(id=self.name, display_name=self.name, context_window=32000)
    async def list_models(self):
        return []
    def parse_tool_calls(self, response):
        return response.tool_calls
    async def complete(self, request, **kwargs):
        self.calls += 1
        self.requests.append(request)
        await asyncio.sleep(self.delay_ms / 1000)
        return DemoResponse(content=[{"type": "text", "text": "Synthetic task completed."}])


class DemoLoop:
    """Small contract double, not vendored or represented as upstream source."""
    async def execute(self, prompt, context, providers, tools, hooks, **kwargs):
        await context.add_message({"role": "user", "content": prompt})
        provider = next(iter(providers.values()))
        for _ in range(20):
            request = SimpleNamespace(messages=list(context.messages),
                tools=[{"name": key, "parameters": tool.input_schema} for key, tool in tools.items()],
                model="synthetic-reasoner", tool_choice="auto")
            pre = await hooks.emit("provider:request", {"provider": provider.name})
            if getattr(pre, "action", "continue") == "deny":
                return "Provider denied by demo gate"
            response = await provider.complete(request)
            await hooks.emit("provider:response", {"provider": provider.name})
            calls = provider.parse_tool_calls(response)
            await context.add_message({"role": "assistant", "content": response.content})
            if not calls:
                return "Synthetic task completed."
            for call in calls:
                data = {"tool_name": call.name, "tool_call_id": call.id, "tool_input": call.arguments}
                result = await hooks.emit("tool:pre", data)
                if getattr(result, "action", "continue") == "deny":
                    await context.add_message({"role": "tool", "content": "Denied", "tool_call_id": call.id})
                    continue
                output = await tools[call.name].execute(call.arguments)
                await hooks.emit("tool:post", {**data, "tool_result": output})
                await context.add_message({"role": "tool", "content": json.dumps(output.output), "tool_call_id": call.id})
        raise RuntimeError("Demo loop exceeded iteration budget")


SCENARIOS = [
    ("Prepared read-only actions", "active", [{"choice": "first"}] , 3),
    ("Ambiguity escalates to reasoning", "active", [{"choice": "first", "probability": .56}], 2),
    ("Jev abstains", "active", [{"choice": "reason"}], 2),
    ("Shadow suggestion, slow execution", "shadow", [{"choice": "first"}], 2),
    ("Timeout returns to baseline", "active", [{"choice": "first", "delay_ms": 500}], 2),
    ("Fast-path budget returns to reasoning", "active", [{"choice": "first"}], 5),
]


async def run_demo(directory: str | Path, *, stop: threading.Event | None = None,
                   repeat: bool = False, callback=None, delay_ms=35):
    coordinator = DemoCoordinator()
    recorder = JsonlRecorder(directory, coordinator.session_id)
    emitter = Emitter(coordinator.session_id, recorder=recorder, callback=callback, synthetic=True)
    try:
        while True:
            for title, mode, script, count in SCENARIOS:
                if stop and stop.is_set():
                    return
                backend = ScriptedBackend(script, delay_ms=delay_ms)
                policy = Policy(mode=mode, timeout_ms=180, allowed_tools=("demo_inspect",),
                                allow_synthetic_active=True, max_fast_streak=3)
                candidates = [Candidate(f"inspect_{i}", f"Inspect artifact {i + 1}", "demo_inspect",
                              {"target": f"artifact-{i}"}, rationale="Synthetic prepared inspection").__dict__
                              for i in range(count)]
                service = DecisionService(policy, backend, emitter, coordinator, candidates)
                runtime = Runtime(service)
                orchestrator = HybridOrchestrator({}, coordinator, runtime,
                    upstream=DemoLoop(), response_factory=demo_response)
                await emitter.emit("health", {"session_label": title, "synthetic": True})
                await orchestrator.execute(title, DemoContext(), {"demo-reasoner": DemoProvider()},
                                           {"demo_inspect": DemoTool()}, coordinator.hooks)
                await backend.close()
                if repeat:
                    await asyncio.sleep(.5)
            if not repeat:
                return
    finally:
        await asyncio.to_thread(recorder.close)
