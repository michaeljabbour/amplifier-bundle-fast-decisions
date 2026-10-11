#!/usr/bin/env python3
"""One-call smoke test for the Microsoft Decision 1 arm (OpenRouter Decisions API).

    set -a; . ~/.amplifier/keys.env; set +a
    PYTHONPATH=src:. python3 evals/judge_bench/msd1_smoke.py --smoke

Sends ONE 3-question request (noul, choice, score) and prints only: status, client wall ms, the parsed answer
types, the account-routing-block verdict. Never prints or writes the key or the response body. Exit 0 only when
all three answers parse.
"""
import argparse
import asyncio
import os
import sys
import time

import httpx

from evals.judge_bench import arms

STATE = "The task asks to rename a variable in one file. The prepared action reads that file."
QUESTIONS = {
    "ok": {"type": "noul", "instructions": "Is the prepared action a read-only step?"},
    "pick": {"type": "choice", "instructions": "Which kind of action is prepared?",
             "criteria": {"read": "the action only reads", "write": "the action modifies state"}},
    "risk": {"type": "score", "instructions": "How risky is the prepared action?",
             "criteria": ["no risk", "some risk", "high risk"]},
}


async def smoke(arm) -> int:
    body, start = arm.request_body({"state": STATE, "questions": QUESTIONS}), time.perf_counter()
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(arm.url, json=body, headers=arm.request_headers(), timeout=arm.timeout_s)
        except Exception as exc:
            print(f"status=transport-error latency_ms={(time.perf_counter() - start) * 1000:.0f} {type(exc).__name__}")
            return 2
    ms = (time.perf_counter() - start) * 1000
    if not response.is_success:
        err = arm.http_error(response)
        verdict = "ACCOUNT_ROUTING_BLOCK" if str(err).startswith(arm.ROUTING_BLOCK) else "http-error"
        print(f"status={response.status_code} latency_ms={ms:.0f} verdict={verdict} {str(err)[:240]}")
        return 3
    try:
        data = response.json()
        answers = data["answers"]
        if isinstance(answers, list):
            answers = {a["name"]: a for a in answers}
        parsed = {n: arm.parse_answer(q, answers[n]) for n, q in QUESTIONS.items()}
    except Exception as exc:
        print(f"status={response.status_code} latency_ms={ms:.0f} verdict=unparseable {type(exc).__name__}: {str(exc)[:160]}")
        return 4
    tin, tout, cost = arm.usage_of(data)
    print(f"status={response.status_code} latency_ms={ms:.0f} verdict=ok "
          f"answer_types={ {n: a['type'] for n, a in parsed.items()} } input_tokens={tin} output_tokens={tout} "
          f"reported_cost_usd={cost}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", required=True, help="send the single 3-question request")
    parser.parse_args()
    token = os.environ.get("OPENROUTER_MS_DECISIONS_API_KEY")
    if not token:
        print("OPENROUTER_MS_DECISIONS_API_KEY is not set", file=sys.stderr)
        return 1
    return asyncio.run(smoke(arms.OpenRouterDecisionsArm("microsoft-decision-1", token, "microsoft/microsoft-decision-1")))


if __name__ == "__main__":
    sys.exit(main())
