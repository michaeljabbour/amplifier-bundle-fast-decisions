#!/usr/bin/env python3
"""Offline replay of the recorded main-v1 paired campaign through the REAL routing decision code.

No model calls, no network, no scenario code: only the recorded session/request/decision rows are read, and the
shipped behavior YAML's policy drives `RoutedProvider` over a `DemoProvider` (a local stub).

  derive  recompute the price-gate constants (request multipliers, reference request mix) from the recorded data and
          fail if they disagree with src/amplifier_fast_decisions/price_gate.py.
  replay  for each of the 280 recorded waves build the shipped policy, a stub judge that returns the wave's recorded
          sticky decision, and run 3 scripted turns; Opus hosts must never route (140/140), Fable hosts must match the
          recorded decision (140/140).
  sweep   re-price the recorded Opus sessions at several cache-read prices and check the gate never routes where the
          recorded data say routing costs more.

Usage: python3 evals/price_gate_replay.py {derive|replay|sweep|all} [--evidence DIR] [--behavior YAML] [--json OUT]
Evidence: docs/evidence/2026-10-02-paired-campaign (data/sessions.jsonl, data/requests.jsonl.gz, campaign/decisions.jsonl).
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amplifier_fast_decisions import orchestrator, price_gate  # noqa: E402
from amplifier_fast_decisions.contracts import (  # noqa: E402
    Answer, Decision, DecisionResult, Policy, SLOW, TurnState,
)
from amplifier_fast_decisions.demo import DemoCoordinator, DemoProvider, demo_response  # noqa: E402
from amplifier_fast_decisions.runtime import Runtime  # noqa: E402
from amplifier_fast_decisions.savings import DEFAULT_RATES  # noqa: E402
from amplifier_fast_decisions.service import DecisionService  # noqa: E402
from amplifier_fast_decisions.telemetry import Emitter  # noqa: E402

DEFAULT_EVIDENCE = ROOT / "docs" / "evidence" / "2026-10-02-paired-campaign"
DEFAULT_BEHAVIOR = ROOT / "behaviors" / "fast-decisions.yaml"
HOSTS = {"opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}
SWEEP_PRICES = (0.20, 0.25, 0.30, 0.35, 0.38, 0.40, 0.43, 0.45, 0.50)
CHEAP = "claude-sonnet-5"


def _jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load(evidence: Path) -> dict:
    sessions = _jsonl(evidence / "data" / "sessions.jsonl")
    return {
        "sessions": sessions,
        "index": {(s["scenario_id"], s["rep"], s["host"], s["arm"]): s for s in sessions},
        "requests": _jsonl(evidence / "data" / "requests.jsonl.gz"),
        "decisions": _jsonl(evidence / "campaign" / "decisions.jsonl"),
    }


# ---- derive ---------------------------------------------------------------------------------------------------------

def derive(data: dict) -> dict:
    sessions, index = data["sessions"], data["index"]
    out: dict = {"multipliers": {}, "ok": True}
    for host, model in HOSTS.items():
        pairs = []
        for s in sessions:
            if s["host"] == host and s["arm"] == "sticky" and s["sticky_decision"] == "cheap" and s["cost_valid"]:
                anchor = index[(s["scenario_id"], s["rep"], host, "anchor")]
                if anchor["cost_valid"]:
                    pairs.append((s, anchor))
        multiplier = sum(s["n_req"] for s, _ in pairs) / sum(a["n_req"] for _, a in pairs)
        shipped = price_gate.REQUEST_MULTIPLIERS[model]
        ok = round(multiplier, 2) == shipped
        out["multipliers"][model] = {"pairs": len(pairs), "derived": round(multiplier, 4), "constant": shipped, "ok": ok}
        out["ok"] &= ok
    # Reference mix: pooled plain-host anchors, per main request. Sessions (token sums) and the request rows agree.
    anchors = [s for s in sessions if s["arm"] == "anchor" and s["cost_valid"]]
    n_req, totals = sum(s["n_req"] for s in anchors), defaultdict(float)
    for s in anchors:
        for tokens in s["tokens"].values():
            for key, value in tokens.items():
                totals[key] += value
    from_sessions = {k: totals[k] / n_req for k in ("input", "cache_read", "cache_write", "output")}
    valid = {(s["scenario_id"], s["rep"], s["host"]) for s in anchors}
    rtot, rn = defaultdict(float), 0
    for r in data["requests"]:
        if r.get("main") and r["arm"] == "anchor" and (r["scenario_id"], r["rep"], r["host"]) in valid:
            rn += 1
            for key, value in r["tokens"].items():
                rtot[key] += value
    from_requests = {k: rtot[k] / rn for k in from_sessions} if rn else None
    mix_ok = all(abs(from_sessions[k] - price_gate.REFERENCE_MIX[k]) <= 1.0 for k in from_sessions)
    out["reference_mix"] = {"anchor_sessions": len(anchors), "main_requests": n_req, "from_sessions": from_sessions,
                            "request_rows": rn, "from_request_rows": from_requests,
                            "constant": dict(price_gate.REFERENCE_MIX), "ok": mix_ok}
    out["ok"] &= mix_ok
    default_ok = price_gate.DEFAULT_REQUEST_MULTIPLIER == max(price_gate.REQUEST_MULTIPLIERS.values())
    out["default_multiplier_ok"] = default_ok
    out["ok"] &= default_ok
    return out


# ---- replay ---------------------------------------------------------------------------------------------------------

class _RecordedJudge:
    """Answers task_difficulty with the wave's recorded decision. No model behind it."""
    name = "recorded-judge"
    external = False

    def __init__(self, decision: str):
        self.p_complex = 0.1 if decision == "cheap" else 0.9
        self.calls = 0

    async def ask(self, request):
        self.calls += 1
        probs = {"simple": 1 - self.p_complex, "complex": self.p_complex}
        return DecisionResult(action=Decision(choice=SLOW, probabilities={SLOW: 1.0}),
                              answers={"task_difficulty": Answer(probabilities=probs)})

    async def ask_many(self, request):
        return await self.ask(request)

    async def close(self):
        pass


def shipped_orchestrator_config(behavior: Path) -> dict:
    import yaml

    config = yaml.safe_load(behavior.read_text(encoding="utf-8"))["session"]["orchestrator"]["config"]
    # main-v1 recorded Jev decisions: replay them through the judge path, which the shipped rule decider (R*) no longer
    # takes by default (S1 H2). The task-type opt-out is a judge question the recorded campaign never asked.
    return {**config, "model_routing": {**config["model_routing"], "start_policy": "judge", "keep_on_host": None}}


async def _wave(config: dict, host_model: str, decision: str, workspace_files: int, turns: int = 3) -> dict:
    events: list[dict] = []
    coordinator = DemoCoordinator()
    emitter = Emitter(coordinator.session_id, callback=events.append)
    policy = Policy.from_config({**config, "mode": "off", "read_shortcut": False})
    judge = _RecordedJudge(decision)
    service = DecisionService(policy, judge, emitter, coordinator, [])
    provider = DemoProvider(delay_ms=0)
    provider.default_model = host_model
    facade = orchestrator.RoutedProvider(provider, Runtime(service), {}, demo_response, "anthropic-primary")
    requests = []
    with mock.patch.object(orchestrator, "workspace_file_count", lambda root, limit: workspace_files):
        for i in range(turns):
            service.turn = TurnState(f"t{i + 1}")
            for _ in range(2):
                req = NS(messages=[{"role": "user", "content": "scripted turn"}], tools=[], tool_choice="auto")
                await facade.complete(req)
                requests.append(req)
    judged = [e["data"] for e in events if e["event"].endswith("difficulty_judged")]
    return {
        "tiers": [j["choice"] for j in judged], "reasons": [j["reason_code"] for j in judged],
        "judge_calls": judge.calls,
        "models": sorted({getattr(r, "model", None) or "host" for r in requests}),
        "efforts": sorted({getattr(r, "reasoning_effort", None) or "none" for r in requests}),
        "carries_model": any(getattr(r, "model", None) for r in requests),
        "carries_effort": any(getattr(r, "reasoning_effort", None) for r in requests),
    }


def replay(data: dict, behavior: Path) -> dict:
    config = shipped_orchestrator_config(behavior)
    stickies = {(s["scenario_id"], s["rep"], s["host"]): s for s in data["sessions"] if s["arm"] == "sticky"}
    rows = []
    for d in data["decisions"]:
        key = (d["scenario"], d["rep"], d["host"])
        files = stickies[key]["workspace_files"]
        rows.append({"wave": "-".join(map(str, key)), "host": d["host"], "recorded": d["decision"], "files": files,
                     **asyncio.run(_wave(config, HOSTS[d["host"]], d["decision"], files))})
    out: dict = {"waves": len(rows), "by_host": {}}
    for host in HOSTS:
        mine = [r for r in rows if r["host"] == host]
        if host == "opus":
            ok = sum(1 for r in mine if set(r["tiers"]) == {"strong"} and r["reasons"][0] == "price_gate_strong"
                     and set(r["reasons"][1:]) <= {"session_strong"}
                     and r["judge_calls"] == 0 and not r["carries_model"] and not r["carries_effort"])
            out["by_host"][host] = {"waves": len(mine), "no_routing": ok, "pass": ok == len(mine)}
        else:
            want = lambda r: "cheap" if r["recorded"] == "cheap" else "strong"  # noqa: E731
            match = sum(1 for r in mine if set(r["tiers"]) == {want(r)})
            asked = sum(1 for r in mine if r["judge_calls"] == 1 or r["reasons"][0] == "scope_strong")
            session_reuse = sum(1 for r in mine if all(x.startswith("session_") for x in r["reasons"][1:]))
            cheap_ok = sum(1 for r in mine if r["recorded"] != "cheap"
                           or (r["models"] == [CHEAP] and r["efforts"] == ["medium"]))
            out["by_host"][host] = {
                "waves": len(mine), "decision_matches_recorded": match,
                "recorded_cheap": sum(1 for r in mine if r["recorded"] == "cheap"),
                "recorded_host": sum(1 for r in mine if r["recorded"] != "cheap"),
                "judged_once": asked, "turns_2_3_reuse_session": session_reuse, "cheap_requests_sonnet_medium": cheap_ok,
                "pass": match == asked == session_reuse == cheap_ok == len(mine)}
    out["pass"] = all(v["pass"] for v in out["by_host"].values())
    out["mismatches"] = [r for r in rows if r["host"] == "fable" and set(r["tiers"]) != {"cheap" if r["recorded"] == "cheap" else "strong"}][:10]
    out["spend"] = _spend(data)
    return out


def _spend(data: dict) -> dict:
    """Mean tools-normalized session cost per arm (descriptive; not a pass criterion)."""
    cost: dict = defaultdict(list)
    for s in data["sessions"]:
        if s["cost_valid"] and s["arm"] in ("anchor", "shipped", "sticky"):
            cost[(s["host"], s["arm"])].append(s["cost_usd_tools_normalized"])
    return {f"{h}/{a}": round(sum(v) / len(v), 3) for (h, a), v in sorted(cost.items())}


# ---- sweep ----------------------------------------------------------------------------------------------------------

def _session_cost(session: dict, read_price: float) -> float:
    total = 0.0
    for model, t in session["tokens"].items():
        rates = list(DEFAULT_RATES[model])
        if model == HOSTS["opus"]:
            rates[2] = read_price
        total += (t["input"] * rates[0] + t["output"] * rates[1] + t["cache_read"] * rates[2] + t["cache_write"] * rates[3]) / 1e6
    return total


def sweep(data: dict) -> dict:
    index = data["index"]
    rows, ok = [], True
    for price in SWEEP_PRICES:
        logs = []
        for s in data["sessions"]:
            if s["host"] == "opus" and s["arm"] == "sticky" and s["split"] == "test" and s["cost_valid"]:
                anchor = index[(s["scenario_id"], s["rep"], "opus", "anchor")]
                if anchor["cost_valid"]:
                    logs.append(math.log(_session_cost(s, price) / _session_cost(anchor, price)))
        measured = math.exp(sum(logs) / len(logs))
        opus = DEFAULT_RATES[HOSTS["opus"]]
        gate = price_gate.evaluate(HOSTS["opus"], CHEAP, {"rates": {HOSTS["opus"]: [opus[0], opus[1], price, opus[3]]}})
        sound = (not gate.route) or measured < 1.0
        ok &= sound
        rows.append({"opus_cache_read_usd_per_m": price, "gate_predicted": round(gate.predicted_ratio, 3),
                     "gate": "route" if gate.route else "host", "measured_sticky_over_anchor": round(measured, 3),
                     "pairs": len(logs), "sound": sound})
    return {"rows": rows, "pass": ok,
            "gate_break_even_cache_read": round(price_gate.break_even_cache_read(HOSTS["opus"], CHEAP), 3)}


# ---- cli ------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["derive", "replay", "sweep", "all"])
    ap.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    ap.add_argument("--behavior", type=Path, default=DEFAULT_BEHAVIOR)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)
    data = load(args.evidence)
    result: dict = {}
    if args.command in ("derive", "all"):
        result["derive"] = derive(data)
    if args.command in ("replay", "all"):
        result["replay"] = replay(data, args.behavior)
    if args.command in ("sweep", "all"):
        result["sweep"] = sweep(data)
    passed = all(v.get("pass", v.get("ok")) for v in result.values())
    result["pass"] = passed
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
