#!/usr/bin/env python3
"""Judge-quality benchmark runner.

    PYTHONPATH=src:. python3 evals/judges.py --split dev --dry-run
    PYTHONPATH=src:. python3 evals/judges.py --split dev --arms jev-1.13 gpt-6-luna --reps 3
    PYTHONPATH=src:. python3 evals/judges.py --replay <dir>/requests.jsonl --out /tmp/replay

Arms, prices, policies and contrasts live in evals/judges.yaml. Keys come only from
the environment (TYPESAFE_API_KEY, OPENAI_API_KEY) and are never written anywhere.
The request log holds raw answers only; every score is recomputed at summary time,
so --replay needs no network and reproduces summary.json exactly.
The holdout split refuses to run until evals/judge_bench/holdout/PREREGISTRATION.md
and cases.json are committed, unmodified, and the cases hash matches the one in
the preregistration.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from evals.judge_bench import cases as case_lib  # noqa: E402
from evals.judge_bench.arms import ArmUnavailable, OpenAIDecisionsArm, build_arm  # noqa: E402
from evals.judge_bench.scoring import resolve_policy, validate_answer  # noqa: E402
from evals.judge_bench.summarize import summarize  # noqa: E402

CONFIG = Path(__file__).resolve().parent / "judges.yaml"
HOLDOUT_DIR = ROOT / "evals" / "judge_bench" / "holdout"
SCHEMA = "fast-decisions-evals/judges/v1"
SECRET_ENV = ("TYPESAFE_API_KEY", "OPENAI_API_KEY")


class GuardError(RuntimeError):
    pass


# --------------------------------------------------------------------- config

def load_config(path: Path = CONFIG) -> dict:
    import yaml
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != SCHEMA:
        raise ValueError(f"{path}: expected schema {SCHEMA}")
    for name, spec in cfg["arms"].items():
        spec["name"] = name
        if spec["adapter"] == "instruction_clause" and spec["base"] not in cfg["arms"]:
            raise ValueError(f"arm {name}: unknown base {spec['base']}")
    for a, b in cfg["contrasts"]:
        if a not in cfg["arms"] or b not in cfg["arms"]:
            raise ValueError(f"contrast {a} vs {b}: unknown arm")
    return cfg


def _price_spec(name: str, specs: dict):
    spec = specs.get(name)
    while spec:
        if spec.get("price_in") is not None or spec.get("price_out") is not None:
            return spec
        spec = specs.get(spec.get("base"))
    return None


def _multiplier(name: str, specs: dict) -> float:
    spec = specs.get(name)
    while spec:
        if spec.get("adapter") == "chat":
            return float(spec.get("priority_multiplier") or 1.0) if spec.get("service_tier") == "priority" else 1.0
        spec = specs.get(spec.get("base"))
    return 1.0


def request_cost(name: str, specs: dict, tokens_in, tokens_out) -> float:
    price = _price_spec(name, specs)
    if not price:
        return 0.0
    usd = ((tokens_in or 0) * (price.get("price_in") or 0.0) + (tokens_out or 0) * (price.get("price_out") or 0.0)) / 1e6
    return usd * _multiplier(name, specs)


def make_plan(cfg: dict, arm_names: list[str], n_cases: int, reps: int) -> dict:
    d, specs = cfg["defaults"], cfg["arms"]
    per_arm = []
    for name in arm_names:
        spec = specs[name]
        requests = n_cases * d["order_passes"] * reps + d["warmups"] * reps
        est_in, est_out = spec.get("est_tokens_in", 0), spec.get("est_tokens_out", 0)
        usd = requests * request_cost(name, specs, est_in, est_out)
        per_arm.append({"arm": name, "requests": requests, "est_tokens_in": est_in, "est_tokens_out": est_out,
                        "est_usd": usd, "priced": _price_spec(name, specs) is not None})
    return {"arms": per_arm, "requests": sum(a["requests"] for a in per_arm),
            "est_usd": sum(a["est_usd"] for a in per_arm)}


# ---------------------------------------------------------------- holdout guard

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def check_holdout_guard(root: Path = ROOT, holdout_dir: Path | None = None) -> str:
    """Refuse unless the preregistration and cases are committed, unmodified, and
    the preregistered cases_sha256 matches the cases on disk. Returns the sha."""
    holdout_dir = Path(holdout_dir) if holdout_dir else HOLDOUT_DIR
    prereg, cases_file = holdout_dir / "PREREGISTRATION.md", holdout_dir / "cases.json"
    for f in (prereg, cases_file):
        if not f.exists():
            raise GuardError(f"holdout guard: {f} does not exist; write and commit the preregistration first")
    for f in (prereg, cases_file):
        rel = str(f.resolve().relative_to(Path(root).resolve()))
        if _git(root, "ls-files", "--error-unmatch", rel).returncode != 0:
            raise GuardError(f"holdout guard: {rel} is not tracked by git; commit it first")
        if _git(root, "diff", "--quiet", "HEAD", "--", rel).returncode != 0:
            raise GuardError(f"holdout guard: {rel} differs from HEAD; commit it (or restore it) first")
    match = re.search(r"^cases_sha256:\s*([0-9a-f]{64})\s*$", prereg.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise GuardError("holdout guard: PREREGISTRATION.md has no 'cases_sha256: <64 hex>' line")
    actual = case_lib.cases_sha256(case_lib.holdout_cases(cases_file))
    if actual != match.group(1):
        raise GuardError(f"holdout guard: cases hash {actual} does not match preregistered {match.group(1)}")
    return actual


# ----------------------------------------------------------------- summarizing

def build_summary(rows, cases, tags, meta: dict) -> dict:
    policies = [resolve_policy(n) for n in meta["policies"]]
    return summarize(rows, cases, tags, policies, specs=meta["specs"], contrasts=meta["contrasts"],
                     primary=meta["primary_policy"], timeout_ms=meta["timeout_ms"])


def dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _meta_from_cfg(cfg: dict) -> dict:
    d = cfg["defaults"]
    return {"policies": d["policies"], "primary_policy": d["primary_policy"], "timeout_ms": d["timeout_ms"],
            "contrasts": cfg["contrasts"], "specs": cfg["arms"]}


def _print_table(summary: dict) -> None:
    primary = summary["primary_policy"]
    print(f"primary policy: {primary}")
    for arm, out in summary["arms"].items():
        block = out["policies"][primary]["reps"]
        rep = sorted(block, key=int)[0]
        b, lat = block[rep], out["reps"][rep]["latency"]
        print(f"{arm:32} acc {b['correct']:>3}/{b['n']:<3} auto {b['automatic']:>3} "
              f"wrong-auto {b['automatic_errors']:>2} p50 {lat['p50_ms']} p95 {lat['p95_ms']} ms  (rep {rep})")


# ---------------------------------------------------------------------- replay

def default_out(split: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / ".amplifier" / "evaluation" / "fast-decisions" / f"{stamp}-judges-{split}"


def do_replay(args, cfg) -> int:
    requests = Path(args.replay)
    manifest_path, run_path = requests.parent / "manifest.json", requests.parent / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if manifest.get("tags"):
        tags = manifest["tags"]
    elif any(c.get("screen") == "holdout" for c in cases):
        tags = {c["id"]: c.get("tags") or {} for c in cases}
    else:
        tags = case_lib.load_tags("dev")  # first-pass manifests carry no tags
    meta = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else _meta_from_cfg(cfg)
    summary = build_summary(_read_rows(requests), cases, tags, meta)
    out = Path(args.out) if args.out else default_out("replay")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(dump(summary), encoding="utf-8")
    print(json.dumps({"replayed": str(requests), "summary": str(out / "summary.json")}))
    return 0


# ------------------------------------------------------------------------- run

class Spend:
    def __init__(self, limit: float):
        self.limit, self.total, self.stopped = limit, 0.0, False

    def exceeded(self) -> bool:
        if self.total >= self.limit:
            self.stopped = True
        return self.stopped


def _scrub(text: str) -> str:
    for var in SECRET_ENV:
        value = os.environ.get(var)
        if value:
            text = text.replace(value, "[redacted]")
    return text


async def _one(arm, name, case, order, rep, client, log, spend, specs, sem):
    async with sem:
        if spend.exceeded():
            return
        row = {"arm": name, "rep": rep, "id": case["id"], "screen": case["screen"], "kind": case["kind"],
               "expected": case["expected"], "order": order, "valid": False}
        start = time.perf_counter()
        try:
            result = await arm.decide(client, case_lib.reorder(case["payload"], order))
            row.update(elapsed_ms=(time.perf_counter() - start) * 1000, model=result["model"],
                       answer=result["answer"], input_tokens=result["input_tokens"],
                       output_tokens=result["output_tokens"], timing=result["timing"],
                       http_status=result["http_status"])
            if result.get("reasoning_tokens") is not None:
                row["reasoning_tokens"] = result["reasoning_tokens"]
            spend.total += request_cost(name, specs, result["input_tokens"], result["output_tokens"])
            validate_answer(case, result["answer"])
            row["valid"] = True
        except Exception as exc:
            row.setdefault("elapsed_ms", (time.perf_counter() - start) * 1000)
            row["error"] = _scrub(f"{type(exc).__name__}: {str(exc)[:200]}")
        log.write(json.dumps(row, default=str) + "\n")
        log.flush()


async def _block(arm, name, cases, rep, client, log, spend, specs, cfg, concurrency):
    d = cfg["defaults"]
    for _ in range(d["warmups"]):  # excluded from results, but charged to the budget
        if spend.exceeded():
            return
        try:
            result = await arm.decide(client, case_lib.reorder(cases[0]["payload"], 0))
            spend.total += request_cost(name, specs, result["input_tokens"], result["output_tokens"])
        except Exception as exc:
            print(json.dumps({"warmup_failed": name, "error": _scrub(repr(exc)[:200])}), flush=True)
    sem = asyncio.Semaphore(concurrency)
    await asyncio.gather(*(_one(arm, name, case, order, rep, client, log, spend, specs, sem)
                           for order in range(d["order_passes"]) for case in cases))


def _git_state() -> dict:
    sha = _git(ROOT, "rev-parse", "HEAD")
    dirty = _git(ROOT, "status", "--porcelain", "--untracked-files=no")
    return {"sha": sha.stdout.strip() or None, "dirty": bool(dirty.stdout.strip())}


def _ollama_version() -> str | None:
    try:
        done = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)
        return (done.stdout or done.stderr).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


async def run(args, cfg, cases, tags, split, arm_names, probe_decisions) -> int:
    import httpx
    specs = cfg["arms"]
    out = Path(args.out) if args.out else default_out(split)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path, requests_path, run_path = out / "manifest.json", out / "requests.jsonl", out / "run.json"
    sha = case_lib.cases_sha256(cases)
    if manifest_path.exists():
        if not args.append:
            print(f"refusing: {manifest_path} exists; use --append to add arms to this run", file=sys.stderr)
            return 2
        if json.loads(manifest_path.read_text(encoding="utf-8")).get("cases_sha256") != sha:
            print("refusing: cases_sha256 differs from the existing manifest (manifest is never rewritten)",
                  file=sys.stderr)
            return 2
    else:
        if args.append and requests_path.exists():
            print("refusing: --append but manifest.json is missing", file=sys.stderr)
            return 2
        manifest = {"schema": "fast-decisions-evals/judge-manifest/v1", "split": split, "cases": cases,
                    "cases_sha256": sha, "tags": tags}
        manifest_path.write_text(dump(manifest), encoding="utf-8")
    if requests_path.exists() and not args.append:
        print(f"refusing: {requests_path} exists; use --append", file=sys.stderr)
        return 2

    try:
        arms = {n: build_arm(specs[n], specs) for n in arm_names}
        decisions_arm = None
        if probe_decisions:
            decisions_arm = OpenAIDecisionsArm("openai-decisions", os.environ.get("OPENAI_API_KEY"),
                                               specs["openai-decisions"].get("model"))
    except ArmUnavailable as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2

    previous = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
    invocation = {"argv": sys.argv, "started_utc": datetime.now(timezone.utc).isoformat(),
                  "git": _git_state(), "ollama_version": _ollama_version(), "split": split,
                  "reps": args.reps, "concurrency": args.concurrency, "arms": list(arm_names),
                  "cases": len(cases), "openai_decisions_probe": None,
                  "arm_determinism": {n: arms[n].determinism for n in arms}}
    spend = Spend(args.budget_usd)
    rows = []
    if args.append and requests_path.exists():
        rows = [r for r in _read_rows(requests_path) if r["arm"] not in set(arm_names) | {"openai-decisions"}]
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        if decisions_arm is not None:
            if os.environ.get("OPENAI_API_KEY"):
                status, body = await decisions_arm.probe(client)
            else:
                status, body = None, "OPENAI_API_KEY not set; probe not sent"
            invocation["openai_decisions_probe"] = {"arm": "openai-decisions", "status": status,
                                                    "body": _scrub(body or "")}
            print(json.dumps(invocation["openai_decisions_probe"]), flush=True)
            if decisions_arm.usable:
                arms["openai-decisions"] = decisions_arm
                invocation["arms"].append("openai-decisions")
                invocation["arm_determinism"]["openai-decisions"] = decisions_arm.determinism
        with requests_path.open("w", encoding="utf-8") as log:
            for row in rows:
                log.write(json.dumps(row, default=str) + "\n")
            for rep in range(1, args.reps + 1):  # rep 1 over all arms, then rep 2 ...
                for name, arm in arms.items():
                    if spend.exceeded():
                        break
                    await _block(arm, name, cases, rep, client, log, spend, specs, cfg, args.concurrency)
                    print(json.dumps({"rep": rep, "arm_complete": name, "spent_usd": round(spend.total, 6)}),
                          flush=True)
    invocation.update(ended_utc=datetime.now(timezone.utc).isoformat(),
                      budget={"limit_usd": args.budget_usd, "realized_usd": spend.total,
                              "stopped_early": spend.stopped})
    meta = _meta_from_cfg(cfg)
    kept_specs = dict(previous.get("specs", {}))
    for name in invocation["arms"]:
        s = specs[name]
        while s:
            kept_specs[s["name"]] = s
            s = specs.get(s.get("base"))
    meta["specs"] = kept_specs
    run_doc = dict(meta, schema="fast-decisions-evals/judge-run/v1", split=split, cases_sha256=sha,
                   invocations=previous.get("invocations", []) + [invocation])
    run_path.write_text(dump(run_doc), encoding="utf-8")
    summary = build_summary(_read_rows(requests_path), cases, tags, meta)
    (out / "summary.json").write_text(dump(summary), encoding="utf-8")
    _print_table(summary)
    print(json.dumps({"out": str(out), "spent_usd": round(spend.total, 6), "stopped_early": spend.stopped}))
    return 3 if spend.stopped else 0


# ------------------------------------------------------------------------ main

def print_plan(plan: dict, split: str, n_cases: int, args, extra: list[str]) -> None:
    print(f"judge benchmark plan: split={split} cases={n_cases} reps={args.reps} concurrency={args.concurrency}")
    print(f"{'arm':34}{'requests':>9}{'tok_in':>8}{'tok_out':>8}{'est_usd':>10}")
    for a in plan["arms"]:
        note = "" if a["priced"] else "  (no API charge)"
        print(f"{a['arm']:34}{a['requests']:>9}{a['est_tokens_in']:>8}{a['est_tokens_out']:>8}"
              f"{a['est_usd']:>10.4f}{note}")
    print(f"{'TOTAL':34}{plan['requests']:>9}{'':>16}{plan['est_usd']:>10.4f}   budget ${args.budget_usd:.2f}")
    for line in extra:
        print(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--arms", nargs="+")
    parser.add_argument("--reps", type=int)
    parser.add_argument("--append", action="store_true", help="add or replace the selected arms in an existing run")
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--limit", type=int, default=0, help="evenly spaced subset of cases")
    parser.add_argument("--concurrency", type=int, default=1, help="in-flight requests per arm (latency tests)")
    parser.add_argument("--replay", type=Path, help="recompute summary.json from a requests.jsonl, offline")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config()
    specs = cfg["arms"]
    if args.replay:
        return do_replay(args, cfg)
    if args.budget_usd is None:
        args.budget_usd = float(cfg["budget"]["default_usd"])
    if args.reps is None:
        args.reps = cfg["defaults"]["reps"][args.split]
    if args.concurrency < 1 or args.reps < 1:
        parser.error("--reps and --concurrency must be >= 1")
    unknown = [a for a in args.arms or [] if a not in specs]
    if unknown:
        parser.error(f"unknown arms: {unknown}")
    try:
        if args.split == "holdout":
            check_holdout_guard()
            cases = case_lib.holdout_cases()
        else:
            cases = case_lib.dev_cases()
    except (GuardError, FileNotFoundError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    if args.limit:
        cases = cases[::max(1, len(cases) // args.limit)][:args.limit]
    tags = case_lib.load_tags(args.split, cases)

    selected = args.arms or list(specs)
    probe_decisions = "openai-decisions" in selected and specs["openai-decisions"].get("auto_enable") == "probe_200"
    arm_names = [a for a in selected if specs[a].get("enabled", True)]
    plan = make_plan(cfg, arm_names, len(cases), args.reps)
    over = plan["est_usd"] > args.budget_usd
    if args.dry_run:
        extra = []
        if probe_decisions:
            extra.append("openai-decisions: probed at run start (POST /v1/decisions); runs only on HTTP 200, "
                         "otherwise recorded as unavailable; not in this estimate (unpriced)")
        if args.split == "holdout":
            extra.append("holdout guard: passed")
        print_plan(plan, args.split, len(cases), args, extra)
    if over:
        print(f"refusing: estimate ${plan['est_usd']:.4f} exceeds budget ${args.budget_usd:.2f}", file=sys.stderr)
        return 2
    if args.dry_run:
        return 0
    return asyncio.run(run(args, cfg, cases, tags, args.split, arm_names, probe_decisions))


if __name__ == "__main__":
    sys.exit(main())
