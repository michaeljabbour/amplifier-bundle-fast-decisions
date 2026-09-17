#!/usr/bin/env python3
"""Explicitly opt-in, one billed request, public fixed content, no tool execution."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amplifier_fast_decisions.backends import JevBackend
from amplifier_fast_decisions.contracts import Candidate, DecisionRequest


async def main():
    if os.getenv("AFAST_RUN_LIVE") != "1" or not os.getenv("TYPESAFE_API_KEY"):
        raise SystemExit(
            "Set AFAST_RUN_LIVE=1 and TYPESAFE_API_KEY to authorize the public live probe."
        )
    backend = JevBackend(timeout_ms=5000)
    try:
        request = DecisionRequest(
            state={"task": "Read README.md before explaining the project."},
            candidates=(
                Candidate(
                    "read_readme",
                    "Read the project's README.md",
                    "fast_workspace",
                    {"operation": "read", "path": "README.md"},
                ),
            ),
        )
        result = await backend.ask(request)
        result.action.validate({"read_readme", "reason"})
        print(
            json.dumps(
                {
                    "live_api": True,
                    "tool_execution": False,
                    "model": result.model,
                    "choice": result.action.choice,
                    "probabilities": result.action.probabilities,
                    "input_tokens": result.input_tokens,
                },
                indent=2,
            )
        )
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
