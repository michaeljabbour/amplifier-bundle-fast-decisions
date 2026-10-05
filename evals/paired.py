"""Paired multi-turn cost-savings measurement driver (pilot build).

One scripted multi-turn session per ARM, all arms of a scenario-rep started together from the same frozen
workspace snapshot, compared against the anchor arm. Spec: docs/design/parallel-measurement-mode.md (v2).

Subcommands (exit codes as battery.py: 0 ok, 3 budget, 4 precondition):
  plan          arms x scenarios x reps x hosts, per-session cost estimate, budget check, schedule.json
                (--dry-run prints the plan and writes nothing, touches no network)
  run           launch waves (bounded by --parallel), per-session nonce, turn gaps, budget reservation and
                hard stop, resumable (adopts finished and live sessions)
  rows          extract sessions.jsonl / turns.jsonl / pairs.jsonl (+ cache-read audit, mechanism gates)
  grade         re-grade preserved per-turn workspace snapshots (no model call; P7 determinism)
  render-check  offline render of each profile's system prompt: nonce leads it, prompts match across arms

Reuses (adds, does not fork): scripts/forge_e2e.py (prepare / launch_run / wait_for_result / worker),
scripts/battery.py (_freeze_candidate_source), evals/run.py (cell_to_argv: cell -> side translation),
scripts/paired_scenarios.py (spec, snapshots, graders).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT / "scripts", REPO_ROOT / "evals"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import memguard  # noqa: E402
import paired_scenarios as ps  # noqa: E402

SCHEMA = "fast-decisions-paired/v1"
DEFAULT_DESIGN = REPO_ROOT / "evals" / "paired" / "pilot-v1.yaml"
EXIT_OK, EXIT_BUDGET, EXIT_PRECONDITION = 0, 3, 4
MAX_ENCODED_WORKSPACE_LEN = 240        # STUDY-DESIGN 17.1 (macOS NAME_MAX 255)
KEY_ENV_NAMES = ("ANTHROPIC_API_KEY", "ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY")  # names only, never values
FD_RECEIPT_EVENTS = ("difficulty_judged", "scored", "model_routed", "effort_routed", "efficiency", "turn_planned")


class PairedError(Exception):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


class BudgetExceeded(PairedError):
    def __init__(self, reason):
        super().__init__(EXIT_BUDGET, reason)


class ConfigError(PairedError):
    """A session failed BEFORE any model call and not for a transient reason: retrying cannot help, so the run
    stops (exit 4) with the error tail instead of burning 3 identical attempts."""

    def __init__(self, wave_id: str, tails: dict):
        self.wave_id, self.tails = wave_id, tails
        lines = [f"configuration error in wave {wave_id}: session(s) failed before any model call (no retry):"]
        for key, tail in tails.items():
            lines.append(f"  [{key}]")
            lines += [f"    {l}" for l in (tail or "(no output captured)").splitlines()]
        super().__init__(EXIT_PRECONDITION, "\n".join(lines))


# ----------------------------------------------------------------------------------------- failure classification

_NOISE = re.compile(r"FORGE_E2E_(STARTED|FINISHED)|^\s*$")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TRANSIENT_RE = re.compile(
    r"overloaded|rate.?limit|\b(429|500|502|503|504|529)\b|timed? ?out|connection (reset|refused|aborted|error)|"
    r"temporar(y|ily)|econn|forge launch failed|maximum sessions|posix_spawnp|cannot reach|empty response|"
    r"could not resolve host|name or service not known", re.I)


def clean_tail(text: str, lines: int = 14) -> str:
    kept = [l.rstrip() for l in _ANSI.sub("", (text or "").replace("\r", "")).splitlines() if not _NOISE.search(l)]
    return "\n".join(kept[-lines:])


# Positive evidence of a CONFIGURATION problem (the session cannot start for a reason retrying will not change).
CONFIG_RE = re.compile(
    r"Credential environment variable \S+ for provider|api_key_env \S+ is not set|Provider '[^']*' not configured|"
    r"Could not load configured provider source|No providers? configured|--model requires --provider|"
    r"(bundle|profile)[^\n]{0,60}(not found|failed to (load|resolve|prepare)|could not be (loaded|resolved))|"
    r"cannot determine base instruction|Failed to (load|resolve|prepare) bundle|ModuleNotFoundError: No module named 'amplifier",
    re.I)


def classify_failure(result: dict | None, diag: dict) -> str:
    """'config_error' | 'transient' for a session that failed infrastructure.

    A configuration error needs POSITIVE evidence, both of: (1) zero llm:request events in the session's events
    (``diag['model_calls']``; no session at all counts as zero) and (2) a recognised configuration marker in the
    error output (credential ValueError, unconfigured provider, bundle/profile resolution failure, ...). Everything
    else -- a worker that started running and vanished (Forge daemon restart, machine sleep, killed terminal), any
    model call having happened, transient markers (overload, rate limit, 5xx, timeouts, resets, Forge launch
    trouble), or simply no recognisable cause -- is transient and follows the normal whole-wave retry path. Absence of
    evidence is never a reason to halt a campaign."""
    tail = diag.get("error_tail") or ""
    if diag.get("model_calls", 0) > 0 or diag.get("worker_died"):
        return "transient"
    if TRANSIENT_RE.search(tail):
        return "transient"
    return "config_error" if CONFIG_RE.search(tail) else "transient"


# ----------------------------------------------------------------------------------------- config

def _abs(base: Path, value) -> Path:
    p = Path(str(value)).expanduser()
    return p if p.is_absolute() else base / p


def load_design(path=DEFAULT_DESIGN) -> dict:
    path = Path(path)
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    if d.get("schema") != "fast-decisions-paired/design/v1":
        raise PairedError(EXIT_PRECONDITION, f"{path}: unexpected design schema {d.get('schema')!r}")
    d["_path"] = str(path)
    return d


def scenario_dirs(design: dict):
    """The design's scenario directory (str) or directories (list) as absolute paths."""
    d = design["scenario_dir"]
    return [_abs(REPO_ROOT, x) for x in d] if isinstance(d, list) else _abs(REPO_ROOT, d)


def load_specs(design: dict) -> list:
    specs = ps.load_dir(scenario_dirs(design))
    flt = design.get("scenario_filter") or {}
    if flt.get("split"):                          # e.g. {split: test}: the preregistered confirmatory half only
        keep = set(flt["split"] if isinstance(flt["split"], list) else [flt["split"]])
        specs = [s for s in specs if s.split in keep]
    return specs


# ----------------------------------------------------------------------------------------- sessions

@dataclass
class Session:
    key: str                 # run name: <scenario>-r<rep>-<host>-<arm>   (short: path-length defect)
    wave_id: str
    scenario: str
    rep: int
    host: str                # opus | fable | any (host-independent control)
    arm: str
    kind: str                # plain | fd | sticky | control
    cell: str | None         # None for sticky until the decision is made
    model: str
    nonce: str | None = None
    attempt: int = 1
    est_usd: float = 0.0
    sticky_decision: str | None = None
    gate: dict = field(default_factory=dict)      # per-arm mechanism expectations from the design (served model, effort)


def _short(n: int, s: str) -> str:
    return s if len(s) <= n else s[:n]


def make_nonce(plan_id: str, key: str, attempt: int) -> str:
    """Per-session nonce: unique per (plan, session, attempt) and stable across that session's --resume turns
    (it is written once into the session's profile). A rerun attempt gets a NEW nonce so it can never read
    the failed attempt's cache."""
    raw = hashlib.sha256(f"{plan_id}|{key}|{attempt}".encode()).digest()[:16]
    return str(uuid.UUID(bytes=raw, version=4))


def subsample_keys(specs: list, reps: int, cfg: dict) -> set:
    """Seeded subsample of (scenario, rep) for an arm that only runs in a fraction of them (the A/A noise arm).
    Stratified by (split, has-long-gaps) so the noise estimate covers both halves of the preregistered split and both
    gap patterns; per stratum round(fraction * size) scenario-reps, chosen with random.Random(seed) over sorted keys."""
    rng = random.Random(cfg["seed"])
    strata = {}
    for spec in sorted(specs, key=lambda s: s.id):
        for rep in range(1, reps + 1):
            strata.setdefault((spec.split, spec.n_long_gaps > 0), []).append((spec.id, rep))
    chosen = set()
    for key in sorted(strata):
        keys = strata[key]
        chosen.update(rng.sample(keys, min(len(keys), round(cfg["fraction"] * len(keys)))))
    return chosen


def expand_sessions(design: dict, specs: list, *, reps: int, hosts: list, arms: list, scenarios=None) -> list:
    """Every session of the design, grouped into waves (scenario, rep, host-stratum). The host-independent
    control joins the first host's wave: one control session per scenario-rep, used for every stratum."""
    chosen = [s for s in specs if scenarios is None or s.id in scenarios]
    if not chosen:
        raise PairedError(EXIT_PRECONDITION, "no scenarios selected")
    sessions = []
    sub_keys = {arm: subsample_keys(chosen, reps, design["arms"][arm]["subsample"])
                for arm in arms if design["arms"][arm].get("subsample")}
    for spec in chosen:
        for rep in range(1, reps + 1):
            for hi, host in enumerate(hosts):
                wave_id = f"{spec.id}-r{rep}-{host}"
                for arm in arms:
                    a = design["arms"][arm]
                    if arm in sub_keys and (spec.id, rep) not in sub_keys[arm]:
                        continue                      # this arm only runs in a seeded subsample of scenario-reps
                    if a.get("host_independent"):
                        if hi != 0:
                            continue
                        shost, cell = "any", a["cells"]["any"]
                        model = None
                    else:
                        shost, cell = host, a["cells"][host]
                        model = design["hosts"][host]
                    if a["kind"] == "sticky":
                        cell = None
                    sessions.append(Session(key=f"{spec.id}-r{rep}-{shost}-{arm}", wave_id=wave_id, scenario=spec.id,
                                            rep=rep, host=shost, arm=arm, kind=a["kind"], cell=cell,
                                            model=model or "", gate=dict(a.get("gate") or {})))
    return sessions


def waves_of(sessions: list) -> dict:
    out = {}
    for s in sessions:
        out.setdefault(s.wave_id, []).append(s)
    return out


def seeded_wave_order(wave_ids: list, seed: int) -> list:
    ids = sorted(wave_ids)
    random.Random(seed).shuffle(ids)
    return ids


# ----------------------------------------------------------------------------------------- cost model

def _turn_scale(table: dict, n: int) -> float:
    pts = sorted((int(k), float(v)) for k, v in table.items())
    if n <= pts[0][0]:
        return pts[0][1] * n / pts[0][0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if n <= x1:
            return y0 + (y1 - y0) * (n - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y1 + (y1 - y0) * (n - x1) / (x1 - x0)


def estimate_session_usd(design: dict, spec, arm: str, host: str, cell_hint: str | None = None, n_turns: int | None = None) -> float:
    cm = design["cost_model"]
    unit = cm["unit_usd_4turn"]
    a = design["arms"][arm]
    if a["kind"] == "sticky":
        anchor_cell = design["arms"]["anchor"]["cells"][host]
        base = unit[anchor_cell]["usd"] * cm["sticky_over_anchor"][host]
    elif a["kind"] == "control":
        base = unit[a["cells"]["any"]]["usd"]
    else:
        base = unit[a["cells"][host]]["usd"]
    n = len(spec.turns) if n_turns is None else n_turns
    est = base * _turn_scale(cm["turn_scaling"], n) * cm["type_factor"][spec.task_type]
    est *= 1.0 + cm["long_gap_extra_fraction"] * spec.n_long_gaps
    return round(est, 4)


def simulate_wall_hours(design: dict, waves: dict, order: list, specs_by_id: dict, parallel: int) -> float:
    """FIFO wave admission (a wave starts when ALL its sessions fit under --parallel), the same rule `run` applies.
    Session wall time = turns x minutes_per_turn + the scripted gaps; a wave lasts `wave_slowest_factor` x that (its
    slowest arm). Estimates only: wall_model in the design carries the assumptions."""
    wm = design.get("wall_model", {"minutes_per_turn": 1.0, "wave_slowest_factor": 1.4})
    free, t, running = parallel, 0.0, []             # running: heap of (end_time, size)
    import heapq
    for wid in order:
        sess = waves[wid]
        spec = specs_by_id[sess[0].scenario if hasattr(sess[0], "scenario") else sess[0]["scenario"]]
        dur = wm["wave_slowest_factor"] * (len(spec.turns) * wm["minutes_per_turn"] * 60 + sum(spec.gap_schedule))
        size = len(sess)
        while free < size:
            end, sz = heapq.heappop(running)
            t, free = max(t, end), free + sz
        heapq.heappush(running, (t + dur, size))
        free -= size
    return round((max([e for e, _ in running] + [t])) / 3600, 1)


def long_block_note(design: dict, specs_by_id: dict) -> dict | None:
    """The 40-turn long-session block needs authored follow-up turns (not written yet): reported, never scheduled."""
    lb = design.get("long_block")
    if not lb:
        return None
    note = {"status": lb.get("status", "TODO"), "scheduled": False, "turns": lb.get("turns"), "hosts": lb.get("hosts"),
            "scenarios": lb.get("candidates", [])}
    try:
        host = lb["hosts"][0]
        est = sum(estimate_session_usd(design, specs_by_id[sid], arm, host, n_turns=lb["turns"])
                  for sid in lb.get("candidates", []) for arm in lb.get("arms", []) if sid in specs_by_id)
        note["est_usd_if_authored"] = round(est * lb.get("reps", 1), 2)
    except (KeyError, IndexError):
        pass
    return note


def build_plan(design: dict, specs: list, *, reps: int, hosts: list, arms: list, scenarios=None, seed: int,
               budget_usd: float | None, parallel: int, plan_id: str | None = None) -> dict:
    by_id = {s.id: s for s in specs}
    sessions = expand_sessions(design, specs, reps=reps, hosts=hosts, arms=arms, scenarios=scenarios)
    plan_id = plan_id or uuid.uuid4().hex[:12]
    nonce_mode = design.get("nonce_mode", "per_session")
    for s in sessions:
        spec = by_id[s.scenario]
        s.est_usd = estimate_session_usd(design, spec, s.arm, s.host if s.host != "any" else hosts[0])
        if nonce_mode == "per_session":
            s.nonce = make_nonce(plan_id, s.key, s.attempt)
    waves = waves_of(sessions)
    split = False
    if any(len(v) > parallel for v in waves.values()):
        # the host-independent control does not need to co-start with a host stratum: give it its own wave rather than
        # forcing a larger --parallel (memory safety: default parallel is 4)
        for s in sessions:
            if s.host == "any":
                s.wave_id = f"{s.scenario}-r{s.rep}-any"
        waves, split = waves_of(sessions), True
    too_big = {w: len(v) for w, v in waves.items() if len(v) > parallel}
    if too_big:
        raise PairedError(EXIT_PRECONDITION, f"--parallel {parallel} is smaller than a wave (all arms of a wave must "
                                             f"co-start): {too_big}")
    order = seeded_wave_order(list(waves), seed)
    wall_h = simulate_wall_hours(design, waves, order, by_id, parallel)
    total = round(sum(s.est_usd for s in sessions), 2)
    reserve = round(total * design["cost_model"]["infra_retry_reserve_fraction"], 2)
    # R1: one prompt hash per scenario, shared by every arm of it (verified again after prepare, per session)
    prompt_hashes = {sid: ps.prompt_hash(by_id[sid]) for sid in {s.scenario for s in sessions}}
    plan = {
        "schema": SCHEMA, "plan_id": plan_id, "design": design["id"], "seed": seed, "reps": reps, "hosts": hosts,
        "arms": arms, "parallel": parallel, "nonce_mode": nonce_mode, "control_waves_split": split,
        "anchor_arm": design.get("anchor_arm", "anchor"),
        "scenarios": {sid: {"scenario_hash": ps.scenario_hash(by_id[sid]), "prompt_sha256": prompt_hashes[sid],
                            "turns": len(by_id[sid].turns), "gap_schedule": by_id[sid].gap_schedule,
                            "n_long_gaps": by_id[sid].n_long_gaps, "task_type": by_id[sid].task_type,
                            "language": by_id[sid].language, "split": by_id[sid].split}
                      for sid in sorted(prompt_hashes)},
        "wave_order": order,
        "waves": {w: [asdict(s) for s in waves[w]] for w in order},
        "n_sessions": len(sessions), "n_waves": len(waves), "est_total_usd": total,
        "est_infra_retry_reserve_usd": reserve, "est_with_reserve_usd": round(total + reserve, 2),
        "budget_usd": budget_usd, "est_wall_hours": wall_h, "long_block": long_block_note(design, by_id),
        "cost_model_source": design["cost_model"]["source"],
    }
    if budget_usd is not None and plan["est_with_reserve_usd"] > budget_usd:
        raise BudgetExceeded(f"estimated ${plan['est_with_reserve_usd']:.2f} (incl. "
                             f"{design['cost_model']['infra_retry_reserve_fraction']:.0%} retry reserve) exceeds "
                             f"--budget-usd {budget_usd:.2f}")
    return plan


def render_plan(plan: dict) -> str:
    lines = [f"plan {plan['plan_id']}  design={plan['design']}  seed={plan['seed']}  reps={plan['reps']}  "
             f"hosts={','.join(plan['hosts'])}  parallel={plan['parallel']}  nonce={plan['nonce_mode']}",
             f"arms: {', '.join(plan['arms'])}",
             f"{plan['n_sessions']} sessions in {plan['n_waves']} waves", ""]
    lines.append(f"{'scenario':16} {'type':8} {'lang':7} {'turns':5} {'gaps>=5m':8}")
    for sid, m in plan["scenarios"].items():
        lines.append(f"{sid:16} {m['task_type']:8} {m['language']:7} {m['turns']:5d} {m['n_long_gaps']:8d}")
    if plan.get("control_waves_split"):
        lines.append(f"(the plain-sonnet control runs in its own wave per scenario-rep: --parallel {plan['parallel']} < 5)")
    lines += ["", f"{'wave (seeded order)':34} {'sessions':>8} {'est $':>8}"]
    for w in plan["wave_order"]:
        v = plan["waves"][w]
        lines.append(f"{w:34} {len(v):8d} {sum(s['est_usd'] for s in v):8.2f}")
    per_arm = {}
    for w in plan["waves"].values():
        for s in w:
            k = (s["arm"], s["host"])
            c, u = per_arm.get(k, (0, 0.0))
            per_arm[k] = (c + 1, u + s["est_usd"])
    lines += ["", f"{'arm':10} {'host':6} {'n':>3} {'est $':>9}"]
    for (arm, host), (c, u) in sorted(per_arm.items()):
        lines.append(f"{arm:10} {host:6} {c:3d} {u:9.2f}")
    lines += ["", f"estimate (sessions)      ${plan['est_total_usd']:.2f}",
              f"infra retry reserve      ${plan['est_infra_retry_reserve_usd']:.2f}",
              f"estimate incl. reserve   ${plan['est_with_reserve_usd']:.2f}"
              + (f"   budget ${plan['budget_usd']:.2f}" if plan.get("budget_usd") is not None else ""),
              f"estimated wall time    {plan.get('est_wall_hours', '?')} h at --parallel {plan['parallel']} (FIFO waves; wall_model assumptions)",
              f"cost basis: {plan['cost_model_source']} (4-turn unit means, scaled to scenario turns/type; an estimate)"]
    lb = plan.get("long_block")
    if lb:
        lines.append(f"long-session block: {lb['status']} - NOT scheduled ({lb['turns']} turns, hosts {lb['hosts']}, "
                     f"{len(lb['scenarios'])} candidate scenarios"
                     + (f", ~${lb['est_usd_if_authored']:.0f} if authored" if 'est_usd_if_authored' in lb else "") + ")")
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------- ledger

class Ledger:
    """Budget reservation and hard stop (STUDY-DESIGN R6). Reserve before every wave launch; settle with the
    measured (recomputed) cost afterwards. Single-writer under a lock; persisted after every change."""

    def __init__(self, path: Path, budget_usd: float):
        self.path, self.lock = Path(path), threading.Lock()
        if self.path.exists():
            self.d = json.loads(self.path.read_text(encoding="utf-8"))
            self.d["budget_usd"] = budget_usd
        else:
            self.d = {"budget_usd": budget_usd, "reserved": {}, "spent": {}}
        self._save()

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def committed(self) -> float:
        return sum(self.d["spent"].values()) + sum(self.d["reserved"].values())

    def reserve(self, wave_key: str, usd: float):
        with self.lock:
            if self.committed() + usd > self.d["budget_usd"] + 1e-9:
                raise BudgetExceeded(f"reserving ${usd:.2f} for {wave_key} would exceed the hard stop "
                                     f"${self.d['budget_usd']:.2f} (committed ${self.committed():.2f})")
            self.d["reserved"][wave_key] = round(usd, 4)
            self._save()

    def settle(self, wave_key: str, spent_usd: float):
        with self.lock:
            self.d["reserved"].pop(wave_key, None)
            self.d["spent"][wave_key] = round(spent_usd, 4)
            self._save()

    def release(self, wave_key: str):
        with self.lock:
            self.d["reserved"].pop(wave_key, None)
            self._save()


# ----------------------------------------------------------------------------------------- events / rows

def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _rates():
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from amplifier_fast_decisions import savings
    return savings


def price_table_sha() -> str:
    return hashlib.sha256(json.dumps(_rates().DEFAULT_RATES, sort_keys=True).encode()).hexdigest()[:16]


def recompute_cost(model, uncached, read, write, output) -> float | None:
    sv = _rates()
    # savings.price: input_tokens INCLUDES cache reads (Amplifier convention); fresh = input - read
    return sv.price(model, {"input": uncached + read, "cache_read": read, "cache_write": write, "output": output},
                    sv.DEFAULT_RATES)


def parse_events(session_dir) -> dict:
    """Per-request records and fast_decisions receipt counts from one session's events.jsonl.
    Requests are paired by request_id (llm:request <-> llm:response); message bodies are never kept."""
    path = Path(session_dir) / "events.jsonl"
    out = {"requests": [], "fd_counts": {}, "efficiency": [], "error": None}
    if not path.exists():
        out["error"] = "no events.jsonl"
        return out
    pending, seen_eff = {}, set()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"llm:' not in line and '"fast_decisions:' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            name, d = ev.get("event"), ev.get("data") or {}
            if name == "llm:request":
                raw = d.get("raw") if isinstance(d.get("raw"), dict) else {}
                oc = raw.get("output_config")
                pending[ev.get("request_id") or f"anon{len(pending)}"] = {
                    "ts_req": _ts(ev.get("ts") or ev.get("timestamp")), "model": d.get("model"),
                    # `raw: true` on the provider puts the request payload in the event; with it, a main-loop request
                    # is the one carrying tools (background calls such as session naming have none). Without it the
                    # split is impossible, so every system-bearing request counts as main and has_raw is False.
                    "has_raw": bool(raw), "main": bool(d.get("has_system")) and ("tools" in raw if raw else True),
                    "effort": oc.get("effort") if isinstance(oc, dict) else None,
                    "thinking": bool(d.get("thinking_enabled"))}
            elif name == "llm:response":
                u = d.get("usage") or {}
                rid = ev.get("request_id")
                req = pending.pop(rid, None) or {"ts_req": None, "model": d.get("model"), "main": True,
                                                 "effort": None, "thinking": False, "has_raw": True}
                inp, rd, wr = _num(u.get("input_tokens")), _num(u.get("cache_read_tokens")), _num(u.get("cache_write_tokens"))
                out["requests"].append({
                    **req, "ts_resp": _ts(ev.get("ts") or ev.get("timestamp")), "model": d.get("model") or req["model"],
                    "uncached": max(inp - rd, 0.0), "read": rd, "write": wr, "output": _num(u.get("output_tokens")),
                    "cost": _num(u.get("cost_usd")), "has_cost": u.get("cost_usd") is not None,
                    "duration_ms": _num(ev.get("duration_ms")), "request_id": rid})
            elif isinstance(name, str) and name.startswith("fast_decisions:"):
                short = name.split(":", 1)[1]
                eid = ev.get("event_id")
                if eid is not None:
                    if (short, eid) in seen_eff:
                        continue
                    seen_eff.add((short, eid))
                out["fd_counts"][short] = out["fd_counts"].get(short, 0) + 1
                if short == "efficiency":
                    out["efficiency"].append(_num(d.get("usd_saved")))
    return out


def merge_run_receipts(parsed: dict, run_events_dir) -> dict:
    """Fold in fast_decisions receipts from the per-run events dir (STUDY-DESIGN 18.5). The session file and
    the run dir usually hold the same receipts, so per kind the LARGER count wins (never the sum); event ids
    are de-duplicated within the run dir."""
    d = Path(run_events_dir)
    if not d.is_dir():
        return parsed
    seen, counts, eff = set(), {}, []
    for f in sorted(d.glob("*.jsonl")):
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"fast_decisions:' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                name = ev.get("event", "")
                if not name.startswith("fast_decisions:"):
                    continue
                short, eid = name.split(":", 1)[1], ev.get("event_id")
                if eid is not None:
                    if (short, eid) in seen:
                        continue
                    seen.add((short, eid))
                counts[short] = counts.get(short, 0) + 1
                if short == "efficiency":
                    eff.append(_num((ev.get("data") or {}).get("usd_saved")))
    for short, n in counts.items():
        parsed["fd_counts"][short] = max(parsed["fd_counts"].get(short, 0), n)
    if len(eff) > len(parsed["efficiency"]):
        parsed["efficiency"] = eff
    return parsed


def cache_audit(requests: list, tools_prefix_tokens: float = 0.0) -> dict:
    """A cache read can only come from an entry written earlier by THIS session (same model, and on Sonnet the
    same effort level -- findings (e)/(f)). Any read beyond a session's own cumulative writes for that
    (model, effort) is foreign: it can only have been served from another session/arm. Main requests only
    (background calls, e.g. session naming, have their own prefix).

    ``tools_prefix_tokens``: the nonce leads the SYSTEM prompt, but the tools block precedes it in the provider's
    prefix order, so an entry covering only the tools is shared across sessions of the same model (the spec's residual
    risk; measured by `preflight`: ~32k tokens on every first request). Up to that many read tokens on a request that
    has no own earlier write for its (model, effort) are the shared tools prefix, not a leak: they are reported in
    ``cross_arm_read_tokens`` but not flagged. Anything beyond is flagged."""
    own, credit, flags, first_read, total_foreign = {}, {}, [], None, 0.0
    main = [r for r in requests if r["main"]]
    for i, r in enumerate(main):
        key = (r["model"], r["effort"] if r["model"] and "sonnet" in str(r["model"]) else None)
        written = own.get(key, 0.0)
        if key not in credit:
            # first request on this (model, effort): what it read was NOT written by this session; up to the
            # allowance it is the shared tools prefix, and that prefix stays readable on every later request
            credit[key] = min(r["read"], tools_prefix_tokens)
        foreign = max(0.0, r["read"] - written - credit[key])
        if i == 0:
            first_read = r["read"]
        if foreign > 0:
            flags.append({"request_index": i + 1, "model": r["model"], "cache_read": r["read"],
                          "own_written_before": written, "shared_prefix_credit": credit[key], "foreign_read_tokens": foreign})
            total_foreign += foreign
        own[key] = written + r["write"]
    return {"cross_arm_read_tokens": first_read or 0.0, "foreign_read_tokens_total": total_foreign,
            "foreign_read_requests": len(flags), "cache_audit_flags": flags, "cache_audit_clean": not flags}


def tools_normalize(requests: list, tools_prefix_tokens: float) -> dict:
    """Production-realistic repricing (primary cost basis): under one key the tools prefix is warm across sessions,
    so on the first main request of each (model, effort-on-Sonnet) the tools-prefix tokens are a cache READ, not a
    write. Per request: T = min(allowance, read + write); the part of T not already read (and actually written) moves
    from the write to the read rate. Returns {request_index: {"tokens": n, "delta_usd": d}} for repriced requests
    (delta_usd <= 0: normalized = recomputed + delta). Background requests are never touched."""
    seen, out = set(), {}
    sv = _rates()
    for i, r in enumerate(requests):
        if not r["main"]:
            continue
        key = (r["model"], r["effort"] if r["model"] and "sonnet" in str(r["model"]) else None)
        if key in seen:
            continue
        seen.add(key)
        rr = sv._rates_for(r["model"], sv.DEFAULT_RATES)
        if not rr or tools_prefix_tokens <= 0:
            continue
        tokens = min(r["write"], max(0.0, min(tools_prefix_tokens, r["read"] + r["write"]) - r["read"]))
        if tokens > 0:
            out[i] = {"tokens": tokens, "delta_usd": -tokens * (rr[3] - rr[2]) / 1e6}
    return out


def switch_metrics(main: list, windows: list) -> dict:
    """Model switches between consecutive main requests (survey definition): at a turn boundary vs mid-turn,
    plus the cache rebuild they cost (excess write tokens over the new-content expectation)."""
    def turn_of(r):
        return _turn_index(r, windows)

    sw = tb = mt = 0
    rb_write = rb_excess = rb_usd = 0.0
    for i in range(1, len(main)):
        prev, r = main[i - 1], main[i]
        if r["model"] == prev["model"]:
            continue
        sw += 1
        if turn_of(r) != turn_of(prev):
            tb += 1
        else:
            mt += 1
        expected_new = max((r["uncached"] + r["read"] + r["write"]) - (prev["uncached"] + prev["read"] + prev["write"]), 0.0)
        excess = max(r["write"] - expected_new, 0.0)
        rb_write += r["write"]
        rb_excess += excess
        rates = _rates()
        rr = rates._rates_for(r["model"], rates.DEFAULT_RATES)
        if rr:
            rb_usd += excess * (rr[3] - rr[2]) / 1e6
    return {"model_switches": sw, "switches_turn_boundary": tb, "switches_midturn": mt,
            "rebuild_write_tokens": rb_write, "rebuild_excess_write_tokens": rb_excess, "rebuild_usd": rb_usd}


def _turn_index(req: dict, windows: list) -> int:
    t = req.get("ts_req") or req.get("ts_resp")
    if t is None:
        return 0
    for i, w in enumerate(windows, start=1):
        if w[0] is not None and w[0] - 1.0 <= t <= (w[1] or w[0]) + 3.0:
            return i
    return 0


def turn_windows(result: dict) -> list:
    return [(_ts(t.get("started_at")), _ts(t.get("ended_at"))) for t in result.get("turns") or []]


COVARIATE_WHITELIST = (
    "scenario_id", "scenario_hash", "source", "task_type", "language", "split", "host_model", "host", "arm", "cell",
    "rep", "scripted_turns", "gap_schedule", "n_long_gaps", "turn1_prompt_chars", "total_prompt_chars",
    "workspace_files", "workspace_bytes", "swe_difficulty", "turn_index", "turn_prompt_chars", "gap_before_s")
ANCHOR_PROXY_PREFIX = "anchor_"
OUTCOME_FIELDS = ("cache_hit_share", "model_switches", "cost_usd_provider", "cost_usd_recomputed", "cost_usd_tools_normalized", "n_req", "tokens",
                  "wall_ms", "turn_pass_frac", "final_state_pass", "cross_arm_read_tokens")


def assert_covariates(columns) -> None:
    """Post-treatment outcomes may be described or mediated but never used as covariates; only the
    pre-session whitelist and anchor_* proxies (the A0 session's numbers) may enter a model."""
    bad = [c for c in columns if c not in COVARIATE_WHITELIST and not c.startswith(ANCHOR_PROXY_PREFIX)]
    if bad:
        raise ValueError(f"not allowed as covariates (post-treatment outcomes?): {bad}")


def mechanism_gate(session: dict, counts: dict, switches: int, main_models: list, main_efforts: list | None = None) -> dict:
    """STUDY-DESIGN R4 per arm kind. fd arms must show routing receipts; plain arms none; sticky must never
    switch, judge at most once, and keep every main request on the decided model."""
    kind = session["kind"]
    receipts = sum(counts.get(k, 0) for k in FD_RECEIPT_EVENTS)
    ok, why = True, []
    if kind in ("plain", "control"):
        if receipts:
            ok, why = False, [f"plain arm emitted {receipts} fast_decisions receipts (profile leaked)"]
    elif kind == "fd":
        if counts.get("difficulty_judged", 0) < 1:
            ok, why = False, ["no fast_decisions:difficulty_judged receipt"]
    elif kind == "sticky":
        if receipts < 1:
            ok = False
            why.append("no fast_decisions receipts (orchestrator not engaged)")
        if counts.get("difficulty_judged", 0) > 1:
            ok = False
            why.append("more than one difficulty_judged in a sticky session")
        if switches:
            ok = False
            why.append(f"sticky session switched models {switches}x")
        want = session.get("expected_main_model")
        if want and any(m != want for m in main_models):
            ok = False
            why.append(f"requested model {want} not on every main request (saw {sorted(set(main_models))})")
    g = session.get("gate") or {}
    if g.get("served_model_prefix") and main_models:
        bad = sorted({m for m in main_models if not str(m).startswith(g["served_model_prefix"])})
        if bad:
            ok = False
            why.append(f"served model(s) {bad} do not start with {g['served_model_prefix']}")
    if "effort" in g and main_efforts is not None:
        want = None if g["effort"] in (None, "absent", "default") else g["effort"]
        bad = sorted({str(e) for e in main_efforts if e != want})
        if bad:
            ok = False
            why.append(f"reasoning effort {bad} on main requests; expected {'absent (provider default)' if want is None else want}")
    return {"mechanism_engaged": ok, "mechanism_reasons": why, "fd_receipts": receipts}


def count_llm_requests(session_dir) -> int:
    """llm:request events in a session's events.jsonl (a request killed mid-flight counts: the call was made)."""
    path = Path(session_dir) / "events.jsonl"
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if '"llm:request"' in line)


def sessions_dir_for_workspace(workspace: Path) -> Path:
    slug = str(Path(workspace).resolve()).replace("/", "-").replace("\\", "-").replace(":", "")
    return Path.home() / ".amplifier" / "projects" / slug / "sessions"


def session_row(meta: dict, result: dict, parsed: dict, spec, snap_stats: dict, prov: dict, tools_prefix_tokens: float = 0.0) -> tuple:
    """(session_row, [turn_rows]) for one finished session. ``meta`` is the schedule entry of the session."""
    reqs = parsed["requests"]
    main = [r for r in reqs if r["main"]]
    windows = turn_windows(result)
    tokens = {}
    for r in main:
        t = tokens.setdefault(r["model"], {"input": 0.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0})
        t["input"] += r["uncached"]
        t["cache_read"] += r["read"]
        t["cache_write"] += r["write"]
        t["output"] += r["output"]
    cost_provider = sum(r["cost"] for r in reqs)
    recomputed = [recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"]) for r in reqs]
    cost_recomputed = sum(c for c in recomputed if c is not None)
    unpriced = sum(1 for c in recomputed if c is None)
    denom = sum(r["uncached"] + r["read"] + r["write"] for r in main)
    audit = cache_audit(reqs, tools_prefix_tokens)
    norm = tools_normalize(reqs, tools_prefix_tokens)
    for i, r in enumerate(reqs):
        r["_norm_tokens"] = norm.get(i, {}).get("tokens", 0.0)
        r["_norm_delta"] = norm.get(i, {}).get("delta_usd", 0.0)
    cost_normalized = cost_recomputed + sum(v["delta_usd"] for v in norm.values())
    sw = switch_metrics(main, windows)
    first = main[0] if main else None
    warm = None
    if first:
        rr = _rates()._rates_for(first["model"], _rates().DEFAULT_RATES)
        if rr:
            warm = cost_recomputed - first["write"] * (rr[3] - rr[2]) / 1e6
    turns_res = result.get("turns") or []
    passes = [bool(t.get("turn_passed")) for t in turns_res]
    labels = [l for t in turns_res for l in ((t.get("quality") or {}).get("failure_labels") or [])]
    last = turns_res[-1] if turns_res else {}
    last_q = last.get("quality") or {}
    final_pass = bool(turns_res) and not last.get("skipped") and last_q.get("failed", 1) == 0 and bool(last.get("turn_passed"))
    critical = (any(l.startswith("protected_modified") for l in labels)
                or any("evaluate_error" in l for l in labels))
    status = "infra_fail" if result.get("infrastructure_failure") else ("ok" if result.get("outcome_passed") else "agent_fail")
    gate = mechanism_gate({**meta, "expected_main_model": meta.get("expected_main_model")}, parsed["fd_counts"],
                          sw["model_switches"], [r["model"] for r in main], [r["effort"] for r in main])
    served = sorted({r["model"] for r in main if r["model"]})
    model_ids_ok = (not meta.get("model")) or all(m == meta["model"] or str(m).startswith(meta["model"]) or
                                                   meta["kind"] in ("fd", "sticky") for m in served)
    row = {
        "schema": SCHEMA, "session_key": meta["key"], "wave_id": meta["wave_id"], "attempt": meta.get("attempt", 1),
        "scenario_id": meta["scenario"], "scenario_hash": meta["scenario_hash"], "source": spec.source.get("desc"),
        "task_type": spec.task_type, "language": spec.language, "split": spec.split,
        "host": meta["host"], "host_model": meta["model"], "arm": meta["arm"], "kind": meta["kind"],
        "cell": meta.get("cell"), "rep": meta["rep"], "sticky_decision": meta.get("sticky_decision"),
        "scripted_turns": len(spec.turns), "gap_schedule": spec.gap_schedule, "n_long_gaps": spec.n_long_gaps,
        "turn1_prompt_chars": len(ps.turn_prompts(spec)[0]), "total_prompt_chars": sum(map(len, ps.turn_prompts(spec))),
        **snap_stats, "swe_difficulty": None,
        **prov,
        "nonce": result.get("nonce") or meta.get("nonce"), "key_fingerprint": result.get("key_fingerprint"),
        "model_ids": [meta["model"]] if meta.get("model") else [], "served_models": served,
        "served_model_check": model_ids_ok,
        "cost_usd_provider": round(cost_provider, 6), "cost_usd_recomputed": round(cost_recomputed, 6),
        # PRIMARY cost basis: tools prefix repriced as a cache read on each (model, effort) first request
        "cost_usd_tools_normalized": round(cost_normalized, 6),
        "tools_repriced_tokens": sum(v["tokens"] for v in norm.values()),
        "tools_normalized_delta_usd": round(sum(v["delta_usd"] for v in norm.values()), 6),
        "cost_mismatch": abs(cost_provider - cost_recomputed) > 1e-6 or unpriced > 0, "unpriced_requests": unpriced,
        "tokens": tokens, "n_req": len(main), "n_bg": len(reqs) - len(main),
        "wall_ms": sum(t.get("elapsed_ms") or 0 for t in turns_res),
        "exec_ms": sum(max(((r["ts_resp"] or 0) - (r["ts_req"] or 0)) * 1000, r["duration_ms"]) for r in main),
        **sw,
        "cache_hit_share": (sum(r["read"] for r in main) / denom) if denom else None,
        "first_req_write_static": first["write"] if first else None,
        "warm_start_cost_usd": warm,
        "tools_prefix_allowance_tokens": tools_prefix_tokens,
        **{k: audit[k] for k in ("cross_arm_read_tokens", "foreign_read_tokens_total", "foreign_read_requests",
                                 "cache_audit_flags", "cache_audit_clean")},
        "turn_pass_frac": (sum(passes) / len(passes)) if passes else 0.0, "final_state_pass": final_pass,
        "critical": critical, "failure_labels": labels, "receipt_usd_saved_sum": round(sum(parsed["efficiency"]), 6),
        "fd_receipt_counts": parsed["fd_counts"], **gate, "status": status,
        # a watchdog memory kill is a TASK outcome (the session is kept, the turn failed) but its cost is not comparable
        "killed_memory": bool(meta.get("killed_memory_info")), "killed_memory_info": meta.get("killed_memory_info"),
        "cost_valid": not meta.get("killed_memory_info"),
        "scheduled_start": meta.get("scheduled_start"), "actual_start": result.get("started_at"),
        "concurrent_sessions": meta.get("concurrent_sessions"), "wave_valid": meta.get("wave_valid", True),
    }
    trows = []
    prev_model = None
    for i, t in enumerate(turns_res, start=1):
        in_turn = [r for r in reqs if _turn_index(r, windows) == i]
        tmain = [r for r in in_turn if r["main"]]
        toks = {"input": sum(r["uncached"] for r in tmain), "cache_read": sum(r["read"] for r in tmain),
                "cache_write": sum(r["write"] for r in tmain), "output": sum(r["output"] for r in tmain)}
        starts = [r["ts_req"] for r in tmain if r["ts_req"]]
        ends = [r["ts_resp"] for r in tmain if r["ts_resp"]]
        switched = bool(tmain) and prev_model is not None and tmain[0]["model"] != prev_model
        if tmain:
            prev_model = tmain[-1]["model"]
        trows.append({
            "schema": SCHEMA, "session_key": meta["key"], "scenario_id": meta["scenario"], "arm": meta["arm"],
            "host": meta["host"], "rep": meta["rep"], "wave_id": meta["wave_id"], "turn_index": i,
            "turn_prompt_chars": len(ps.turn_prompts(spec)[i - 1]), "gap_before_s": t.get("gap_before_s", 0),
            "models_used": sorted({r["model"] for r in tmain if r["model"]}),
            "efforts_used": sorted({str(r["effort"]) for r in tmain}), "tokens": toks,
            "cost_usd": round(sum(r["cost"] for r in in_turn), 6),
            "cost_usd_recomputed": round(sum(c for c in (recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"])
                                                         for r in in_turn) if c is not None), 6),
            "cost_usd_tools_normalized": round(sum(c for c in (recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"])
                                                               for r in in_turn) if c is not None) + sum(r["_norm_delta"] for r in in_turn), 6),
            "tools_repriced_tokens": sum(r["_norm_tokens"] for r in in_turn),
            "tools_normalized_delta_usd": round(sum(r["_norm_delta"] for r in in_turn), 6),
            "calls": len(tmain), "bg_calls": len(in_turn) - len(tmain), "wall_ms": t.get("elapsed_ms"),
            "working_ms": ((max(ends) - min(starts)) * 1000) if starts and ends else None,
            "switched_in": switched, "pass": bool(t.get("turn_passed")), "skipped": bool(t.get("skipped")),
            "checks": (t.get("quality") or {}).get("checks"), "failure_labels": (t.get("quality") or {}).get("failure_labels"),
            "first_req_cache_read": tmain[0]["read"] if tmain else None,
            "first_req_cache_write": tmain[0]["write"] if tmain else None,
        })
    row["_request_rows"] = [{
        "schema": SCHEMA, "session_key": meta["key"], "scenario_id": meta["scenario"], "arm": meta["arm"], "host": meta["host"],
        "rep": meta["rep"], "request_index": i, "turn_index": _turn_index(r, windows), "main": r["main"], "model": r["model"],
        "effort": r["effort"], "tokens": {"input": r["uncached"], "cache_read": r["read"], "cache_write": r["write"], "output": r["output"]},
        "cost_usd_provider": r["cost"], "cost_usd_recomputed": recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"]),
        "cost_usd_tools_normalized": (recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"]) or 0.0) + r["_norm_delta"],
        "tools_repriced_tokens": r["_norm_tokens"], "tools_normalized_delta_usd": round(r["_norm_delta"], 6)}
        for i, r in enumerate(reqs, start=1)]
    return row, trows


def build_pairs(rows: list, turn_rows: list, anchor_arm: str = "anchor") -> list:
    """(scenario, rep, host, arm) vs the anchor (A0) of the same scenario/rep/host; the host-independent
    control is paired against each host's anchor. Also attaches anchor_* proxies to the session rows."""
    anchors = {(r["scenario_id"], r["rep"], r["host"]): r for r in rows if r["arm"] == anchor_arm}
    anchor_turns = {}
    for t in turn_rows:
        anchor_turns.setdefault((t["scenario_id"], t["rep"], t["host"]), {}).setdefault(t["arm"], []).append(t)
    pairs = []
    for r in rows:
        hosts = [r["host"]] if r["host"] != "any" else sorted({h for (_, _, h) in anchors})
        for host in hosts:
            a = anchors.get((r["scenario_id"], r["rep"], host))
            if a is None or r is a:
                continue
            norm = lambda x: x.get("cost_usd_tools_normalized", x["cost_usd_recomputed"])      # PRIMARY basis
            ac, ac_raw = norm(a), a["cost_usd_recomputed"]
            if r["host"] != "any":
                r["anchor_cost_usd"], r["anchor_cost_usd_raw"] = ac, ac_raw
                r["anchor_n_req"] = a["n_req"]
                r["anchor_turn_costs"] = [norm(t) for t in anchor_turns[(r["scenario_id"], r["rep"], host)][anchor_arm]]
            rc, rc_raw = norm(r), r["cost_usd_recomputed"]
            ratio = lambda x, y: round(__import__("math").log(x / y), 6) if x > 0 and y > 0 else None
            pairs.append({
                "schema": SCHEMA, "scenario_id": r["scenario_id"], "rep": r["rep"], "host": host, "arm": r["arm"],
                "task_type": r["task_type"], "n_long_gaps": r["n_long_gaps"],
                "cost_basis": "tools_normalized",
                "delta_usd": round(rc - ac, 6), "log_cost_ratio": ratio(rc, ac),
                "delta_usd_raw": round(rc_raw - ac_raw, 6), "log_cost_ratio_raw": ratio(rc_raw, ac_raw),
                "delta_s": round((r["wall_ms"] - a["wall_ms"]) / 1000, 3),
                "delta_turn_pass": round(r["turn_pass_frac"] - a["turn_pass_frac"], 4),
                "both_pass": bool(r["final_state_pass"] and a["final_state_pass"]),
                "arm_failed_what_anchor_passed": (not r["final_state_pass"]) and a["final_state_pass"],
                "anchor_cost_usd": ac, "arm_cost_usd": rc, "anchor_cost_usd_raw": ac_raw, "arm_cost_usd_raw": rc_raw,
                "mechanism_engaged": r["mechanism_engaged"], "cache_audit_clean": r["cache_audit_clean"],
                "cost_valid": bool(r.get("cost_valid", True) and a.get("cost_valid", True)),
                "valid": bool(r["wave_valid"] and a["wave_valid"] and r["status"] != "infra_fail" and a["status"] != "infra_fail"
                              and r.get("cost_valid", True) and a.get("cost_valid", True))})
    return pairs


# ----------------------------------------------------------------------------------------- sticky arm (A2)

def sticky_decision(turn1_prompt: str, policy_config: dict, *, workspace_dir, decide_fn=None) -> str:
    """Decide ONCE, at session start, in the harness: 'host' or 'cheap'. Reads the existing turn-start decision
    (orchestrator.decide_start_tier) with the frozen shipped policy and a stub service; the orchestrator is not
    touched and the result is only recorded + mapped to a pin cell. ``decide_fn(prompt, workspace, config)``
    returns the orchestrator's tier ('cheap' | 'strong') and is injectable for tests."""
    tier = (decide_fn or _decide_with_orchestrator)(turn1_prompt, str(workspace_dir), policy_config)
    if tier not in ("cheap", "strong"):
        raise PairedError(EXIT_PRECONDITION, f"unexpected start tier {tier!r}")
    return "cheap" if tier == "cheap" else "host"


def _decide_with_orchestrator(prompt: str, workspace_dir: str, config: dict) -> str:
    import asyncio
    from types import SimpleNamespace
    _rates()  # puts REPO/src on sys.path
    from amplifier_fast_decisions.demo import DemoCoordinator
    from amplifier_fast_decisions.orchestrator import decide_start_tier
    from amplifier_fast_decisions.runtime import get_runtime

    class Coordinator(DemoCoordinator):
        def get_capability(self, key):
            return workspace_dir if key == "session.working_dir" else super().get_capability(key)

    async def go():
        with tempfile.TemporaryDirectory() as events:
            cfg = {**config, "events_dir": events, "mode": "active"}
            runtime, _ = get_runtime(Coordinator(), cfg)
            try:
                request = SimpleNamespace(messages=[{"role": "user", "content": prompt}])
                return await decide_start_tier(runtime.service, request, cfg["model_routing"], None)
            finally:
                await runtime.close()
    return asyncio.run(go())


# ----------------------------------------------------------------------------------------- cell -> side

def _parse_argv_for_side(argv: list) -> dict:
    out = {"overrides": {}, "backend": None, "allow_external_state": False, "composition": "explicit"}
    import battery
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--fd-override":
            k, _, v = argv[i + 1].partition("=")
            out["overrides"][k] = battery._coerce(v)
            i += 1
        elif a == "--fd-backend":
            out["backend"] = argv[i + 1]
            i += 1
        elif a == "--fd-composition":
            out["composition"] = argv[i + 1]
            i += 1
        elif a == "--allow-external-state":
            out["allow_external_state"] = True
        i += 1
    return out


def cell_to_side(cell_id: str, cells_doc: dict, suites_doc: dict, *, baseline_source, candidate_source,
                 candidate_sha) -> tuple:
    """(side dict for forge_e2e, model, amplifier_bundle) for a cells.yaml cell. Reuses evals/run.cell_to_argv, so
    the arm is exactly what the existing campaigns run for that cell (add, don't fork)."""
    import run as evals_run
    cell = cells_doc["cells"][cell_id]
    model = cell.get("amplifier_model") or cells_doc.get("defaults", {}).get("amplifier_model")
    bundle = cell.get("amplifier_bundle") or "foundation"
    if "amplifier-fd" not in cell["harnesses"]:
        side = {"source_root": str(baseline_source), "mode": "off"}
        if cell.get("amplifier_effort"):               # plain cell with a pinned provider reasoning effort
            side["amplifier_effort"] = cell["amplifier_effort"]
        return side, model, bundle
    argv = evals_run.cell_to_argv(cell_id, cells_doc, suites_doc, "s1m", "m-dev", 1, out_root="/unused", base_seed=0,
                                  baseline_source=baseline_source, candidate_source=candidate_source,
                                  candidate_sha=candidate_sha)
    p = _parse_argv_for_side(argv)
    overrides = dict(p["overrides"])
    if p["backend"]:
        overrides["backend"] = p["backend"]
    if p["allow_external_state"]:
        overrides["allow_external_state"] = True
    return ({"source_root": str(candidate_source), "mode": "active", "decision_overrides": overrides,
             "composition": p["composition"]}, model, bundle)


# ----------------------------------------------------------------------------------------- run context

@dataclass
class Ctx:
    out: Path
    design: dict
    cells_doc: dict
    suites_doc: dict
    specs: dict                      # id -> ScenarioSpec
    snapshots: dict                  # id -> snapshot dir
    plan: dict
    campaign_root: Path
    candidate_source: str
    candidate_sha: str | None
    baseline_source: str
    seed: int
    key_env: dict = field(default_factory=dict)      # arm -> env var NAME holding that arm's key
    offsets: dict = field(default_factory=dict)      # arm -> start offset seconds (P2 contrast only)
    decide_fn: object = None
    now: object = time.time
    sleep: object = time.sleep
    deadline_s: int = 900
    max_spread_s: float = 60.0
    max_attempts: int = 3


def encoded_workspace_len(root: Path, name: str) -> int:
    import forge_e2e
    ws = Path(root) / forge_e2e._slug(name) / "workspace"
    return len(str(ws).replace("/", "-").replace("\\", "-").replace(":", ""))


def check_path_lengths(campaign_root: Path, sessions: list, wave_ids=None) -> int:
    """STUDY-DESIGN 17.1: fail BEFORE any launch if an encoded workspace path would exceed the limit."""
    worst = 0
    for s in sessions:
        n = encoded_workspace_len(campaign_root / "w000-a9", s["key"])
        worst = max(worst, n)
        if n > MAX_ENCODED_WORKSPACE_LEN:
            raise PairedError(EXIT_PRECONDITION, f"workspace path too long ({n} > {MAX_ENCODED_WORKSPACE_LEN}) for {s['key']}")
    return worst


class ForgeBackend:
    """The real launcher: forge_e2e.prepare / launch_run / wait_for_result (as battery.py does)."""

    def prepare_wave(self, ctx: Ctx, root: Path, sessions: list) -> None:
        import forge_e2e
        import forge_workloads
        spec_ids = sorted({s["scenario"] for s in sessions})
        sdirs = scenario_dirs(ctx.design)
        task_source = {"kind": "paired", "scenario_dir": [str(x) for x in sdirs] if isinstance(sdirs, list) else str(sdirs),
                       "snapshot_root": str(_abs(REPO_ROOT, ctx.design["snapshot_root"])), "ids": spec_ids}
        forge_workloads.register_source(**task_source)
        sides, runs = {}, []
        bundle = "foundation"
        for s in sessions:
            side, model, bundle = cell_to_side(s["cell"], ctx.cells_doc, ctx.suites_doc, baseline_source=ctx.baseline_source,
                                               candidate_source=ctx.candidate_source, candidate_sha=ctx.candidate_sha)
            side = {**side, "model": s["model"] or model}
            s["model"] = side["model"]
            if ctx.key_env.get(s["arm"]):
                side["api_key_env"] = ctx.key_env[s["arm"]]
            sides[s["arm"]] = side
            spec = ctx.specs[s["scenario"]]
            runs.append({"name": s["key"], "task": s["scenario"], "side": s["arm"], "rep": s["rep"],
                         "attempt": s["attempt"], "block": None, "seed": ctx.seed, "nonce": s.get("nonce"),
                         "prompt": ps.TURN_SEPARATOR.join(ps.turn_prompts(spec)), "deadline_seconds": ctx.deadline_s})
        config = {"runs": runs, "sides": sides, "provider": "anthropic", "model": sessions[0]["model"],
                  "amplifier_bundle": bundle, "limits": {"timeout_seconds": ctx.deadline_s, "max_iterations": 30,
                                                          "extended_thinking": True},
                  "events_dir": str(forge_e2e.EVENTS), "host_python": str(forge_e2e.HOST_PYTHON),
                  "forge_py": str(forge_e2e.FORGE), "prompt": forge_e2e.PROMPT, "task_source": task_source,
                  "turn_gap_seconds": 0, "campaign_provider": ctx.design.get("campaign_provider")}
        forge_e2e.prepare(root, config)

    def start(self, root: Path, name: str) -> None:
        import forge_e2e
        forge_e2e.launch_run(root, name)

    def wait(self, root: Path, name: str, timeout: float) -> bool:
        import forge_e2e
        return forge_e2e.wait_for_result(root, name, timeout)

    def status(self, root: Path, name: str) -> str:
        import forge_e2e
        run = Path(root) / forge_e2e._slug(name)
        if (run / "result.json").exists():
            return "done"
        running = run / "running.json"
        if running.exists():
            try:
                os.kill(json.loads(running.read_text()).get("controller_pid", 0), 0)
                return "live"
            except (ProcessLookupError, ValueError, TypeError):
                return "dead"
            except OSError:
                return "live"
        return "missing"

    def result(self, root: Path, name: str) -> dict | None:
        import forge_e2e
        p = Path(root) / forge_e2e._slug(name) / "result.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def close(self, root: Path, name: str) -> None:
        import forge_e2e
        try:
            forge_e2e.close_worker_terminal(root, name)
        except Exception:  # noqa: BLE001 -- terminal cleanup must never fail a wave
            pass

    def workspace(self, root: Path, name: str) -> Path:
        import forge_e2e
        return Path(root) / forge_e2e._slug(name) / "workspace"

    def _forge(self):
        import forge_e2e
        forge_py = Path(forge_e2e.FORGE).expanduser()
        if str(forge_py.parent) not in sys.path:
            sys.path.insert(0, str(forge_py.parent))
        import forge as forge_module
        return forge_module

    def forge_max_sessions(self) -> int:
        """Forge's own terminal cap (~/.forge/settings.json maxSessions, default 10): exited-but-unclosed terminals count."""
        try:
            return int(json.loads((Path.home() / ".forge" / "settings.json").read_text()).get("maxSessions", 10))
        except (OSError, ValueError, TypeError):
            return 10

    def forge_terminals(self, root: Path | None = None) -> dict:
        """{'total': n, 'ours_exited': n} from Forge's list_terminals ('ours' = name or cwd mentions the campaign root)."""
        sessions = self._forge().call("list_terminals", {})
        if isinstance(sessions, dict):
            sessions = sessions.get("sessions") or sessions.get("terminals") or []
        sessions = [s for s in sessions if isinstance(s, dict)]
        ours = [s for s in sessions if root is not None and str(root) in (s.get("name") or "") + " " + (s.get("cwd") or "")]
        return {"total": len(sessions), "ours": len(ours), "ours_exited": sum(1 for s in ours if s.get("status") == "exited")}

    def forge_reap(self, root: Path) -> bool:
        import forge_e2e
        return forge_e2e.reap_exited_worker_terminals(self._forge(), root)

    def diagnose(self, root: Path, name: str, result: dict | None) -> dict:
        """Evidence for failure classification: the error tail (forge-output.txt, else the first turn's stdout)
        and how many model calls the session made (llm:request events)."""
        run = self.run_dir(root, name)
        tail = ""
        for fname in ("forge-output.txt", "turn1-stdout.txt"):
            f = run / fname
            if f.exists():
                tail = clean_tail(f.read_text(errors="replace"))
                if tail:
                    break
        calls = sum(count_llm_requests(d) for d in self.session_dirs(root, name, result))
        died = False
        running, rfile = None, run / "running.json"
        if result is None and rfile.exists():
            try:
                os.kill(json.loads(rfile.read_text()).get("controller_pid", 0), 0)
            except (ProcessLookupError, ValueError, TypeError):
                died = True               # the worker started, then vanished without writing result.json
            except OSError:
                pass
        return {"error_tail": tail, "model_calls": calls, "worker_died": died}

    def session_dirs(self, root: Path, name: str, result: dict | None = None) -> list:
        """Every Amplifier session dir of this run's workspace, found on disk (a run that died has no result.json to
        name its session, but its events are still evidence and still cost money)."""
        base = sessions_dir_for_workspace(self.workspace(root, name))
        dirs = [d for d in (sorted(base.iterdir()) if base.is_dir() else []) if not d.name.startswith(".") and (d / "events.jsonl").exists()]
        sid = (result or {}).get("session_id")
        if sid and (base / sid).exists() and (base / sid) not in dirs:
            dirs.append(base / sid)
        return dirs

    def run_dir(self, root: Path, name: str) -> Path:
        import forge_e2e
        return Path(root) / forge_e2e._slug(name)


# ----------------------------------------------------------------------------------------- run

class Slots:
    """FIFO admission: a wave starts only when ALL its sessions fit under --parallel, so every arm of a wave
    co-starts and in-flight sessions never exceed the bound."""

    def __init__(self, n: int):
        self.n, self.cv = n, threading.Condition()

    def acquire(self, k: int):
        with self.cv:
            while self.n < k:
                self.cv.wait()
            self.n -= k

    def release(self, k: int):
        with self.cv:
            self.n += k
            self.cv.notify_all()


FORGE_RESERVE = 2             # terminals left free for the user / other tools when clamping --parallel to Forge's cap
MAX_EXCLUDED_PER_HOUR = 3
CAPACITY_WAIT_S = 15.0
MAX_CAPACITY_WAITS = 40


class BreakerOpen(PairedError):
    """Too many consecutive infrastructure failures: stop launching instead of burning through waves (exit 4)."""

    def __init__(self, reason: str):
        super().__init__(EXIT_PRECONDITION, reason)


class CircuitBreaker:
    """Trips when >= ``consecutive`` waves in a row have an infrastructure-failed attempt (no clean wave in between), or when
    more than ``max_excluded_per_hour`` waves were excluded within the last hour. Once open it stays open for the run."""

    def __init__(self, consecutive: int = 2, max_excluded_per_hour: int = MAX_EXCLUDED_PER_HOUR, now=time.time):
        self.consecutive, self.max_excluded, self.now = consecutive, max_excluded_per_hour, now
        self.lock, self.streak, self.excluded_at, self.tripped = threading.Lock(), [], [], None

    def note_infra(self, wid: str) -> str | None:
        with self.lock:
            if wid not in self.streak:
                self.streak.append(wid)
            if len(self.streak) >= self.consecutive and not self.tripped:
                self.tripped = (f"circuit breaker: {len(self.streak)} waves in a row failed infrastructure ({', '.join(self.streak)}); "
                                "stopping instead of burning through waves")
            return self.tripped

    def note_clean(self, wid: str) -> None:
        with self.lock:
            self.streak = []

    def note_excluded(self, wid: str) -> str | None:
        with self.lock:
            t = self.now()
            self.excluded_at = [x for x in self.excluded_at if t - x < 3600] + [t]
            if len(self.excluded_at) > self.max_excluded and not self.tripped:
                self.tripped = (f"circuit breaker: {len(self.excluded_at)} waves excluded within an hour (limit {self.max_excluded}); "
                                "stopping")
            return self.tripped


def _read_json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write_json(p: Path, value) -> None:
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(p)


class State:
    def __init__(self, path: Path):
        self.path, self.lock = Path(path), threading.Lock()
        self.d = _read_json(self.path, {"settings_sha256": None, "waves": {}})

    def save(self):
        with self.lock:
            _write_json(self.path, self.d)

    def wave(self, wid: str) -> dict:
        return self.d["waves"].setdefault(wid, {"status": "pending", "attempts": [], "accepted_attempt": None})


def settings_sha(path=None) -> str | None:
    """Hash of ~/.amplifier/settings.yaml with volatile bookkeeping removed.

    The CLI rewrites `updates.last_check` on its own schedule; that timestamp changes nothing a session loads, so it
    must not trip the STUDY-DESIGN 18.5 guard (it did on 2026-10-01, mid-campaign)."""
    p = Path(path or Path.home() / ".amplifier" / "settings.yaml")
    if not p.exists():
        return None
    try:
        import yaml
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict) and isinstance(doc.get("updates"), dict):
            doc = {**doc, "updates": {k: v for k, v in doc["updates"].items() if k != "last_check"}}
        blob = json.dumps(doc, sort_keys=True, default=str).encode()
    except Exception:
        blob = p.read_bytes()
    return "n1:" + hashlib.sha256(blob).hexdigest()[:16]


def decisions_path(out: Path) -> Path:
    return Path(out) / "decisions.jsonl"


def resolve_sticky(ctx: Ctx, sess: dict, policy_config: dict) -> None:
    """Make (or reuse, on a wave rerun/resume) the session's one-time sticky decision and pick its pin cell."""
    path = decisions_path(ctx.out)
    prior = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    hit = next((d for d in prior if d["scenario"] == sess["scenario"] and d["rep"] == sess["rep"] and d["host"] == sess["host"]), None)
    if hit is None:
        spec = ctx.specs[sess["scenario"]]
        decision = sticky_decision(ps.turn_prompts(spec)[0], policy_config,
                                   workspace_dir=Path(ctx.snapshots[sess["scenario"]]) / "workspace", decide_fn=ctx.decide_fn)
        hit = {"scenario": sess["scenario"], "rep": sess["rep"], "host": sess["host"], "decision": decision,
               "turn1_prompt_sha256": hashlib.sha256(ps.turn_prompts(spec)[0].encode()).hexdigest(),
               "policy_cell": ctx.design["sticky"]["policy_cell"], "decided_at": datetime.now(timezone.utc).isoformat()}
        with decisions_path(ctx.out).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(hit) + "\n")
    sess["sticky_decision"] = hit["decision"]
    sess["cell"] = ctx.design["arms"][sess["arm"]]["cells"][sess["host"]][hit["decision"]]
    sess["expected_main_model"] = ctx.design["hosts"][sess["host"]] if hit["decision"] == "host" else "claude-sonnet-5"


def wave_timeout_s(ctx: Ctx, sess: dict) -> float:
    spec = ctx.specs[sess["scenario"]]
    return len(spec.turns) * ctx.deadline_s + sum(spec.gap_schedule) + 900


def wave_cost(ctx: Ctx, backend, root: Path, sessions: list) -> float:
    """Measured (recomputed) cost of a wave's sessions, including sessions that died before writing result.json:
    their events are on disk and the provider billed them."""
    total = 0.0
    for s in sessions:
        res = backend.result(root, s["key"])
        dirs = backend.session_dirs(root, s["key"], res) if hasattr(backend, "session_dirs") else []
        if not dirs and res and res.get("session_id"):
            dirs = [sessions_dir_for_workspace(backend.workspace(root, s["key"])) / res["session_id"]]
        for sdir in dirs:
            total += sum(c for c in (recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"])
                                     for r in parse_events(sdir)["requests"]) if c is not None)
    return total


def failure_reason(infra: list, outcomes: dict, diag: dict) -> str:
    """Non-empty, human-readable reason for an infra-failed (or capacity-deferred) attempt: per failed session the launch /
    wait outcome plus the last lines of its error output."""
    parts = []
    for k in infra:
        out = str(outcomes.get(k, "?"))
        tail = clean_tail((diag.get(k) or {}).get("error_tail", ""), 3).replace("\n", " | ")
        died = " (worker vanished mid-run)" if (diag.get(k) or {}).get("worker_died") else ""
        parts.append(f"{k}: {out}{died}" + (f" -- {tail}" if tail else ""))
    return "; ".join(parts) or "no result.json and no output captured"


def run_wave(ctx: Ctx, backend, state: State, ledger: Ledger, wid: str, policy_config: dict, resume: bool, log=print,
             breaker=None) -> str:
    """All attempts of one wave. A TRANSIENT infrastructure failure reruns the whole wave (fresh nonces); a wave
    that fails ctx.max_attempts times is excluded and reported. A session that fails BEFORE any model call for a
    non-transient reason is a configuration error: no retry, the wave is marked ``config_error`` (re-runnable
    after the fix, not counted against the attempt limit) and ConfigError (exit 4, with the error tail) is raised.
    Returns 'done' | 'excluded'."""
    w = state.wave(wid)
    base = ctx.plan["waves"][wid]
    idx = ctx.plan["wave_order"].index(wid)

    def failures() -> int:
        return sum(1 for a in w["attempts"] if a["status"] == "infra_failed")

    while failures() < ctx.max_attempts:
        adopt = bool(resume and w["attempts"] and w["attempts"][-1]["status"] == "running")
        last = max([a["attempt"] for a in w["attempts"]] + [w.get("attempt_offset", 0)])
        attempt_no = last if adopt else last + 1
        if adopt:
            att = w["attempts"][-1]
            sessions, root = att["sessions"], Path(att["root"])
        else:
            sessions = [dict(s) for s in base]
            for s in sessions:
                s["attempt"] = attempt_no
                if ctx.plan["nonce_mode"] == "per_session":
                    s["nonce"] = make_nonce(ctx.plan["plan_id"], s["key"], attempt_no)
                if s["kind"] == "sticky":
                    resolve_sticky(ctx, s, policy_config)
            root = ctx.campaign_root / f"w{idx:03d}-a{attempt_no}"
            ledger.reserve(f"{wid}#a{attempt_no}", sum(s["est_usd"] for s in sessions))
            backend.prepare_wave(ctx, root, sessions)
            check_prompt_hashes(root, sessions, ctx.plan)
            att = {"attempt": attempt_no, "root": str(root), "status": "running", "sessions": sessions}
            w["attempts"].append(att)
            w["status"] = "running"
            state.save()
        launches, lock = {}, threading.Lock()

        def one(s, root=root, adopt=adopt):
            st = backend.status(root, s["key"]) if adopt else "missing"
            if st in ("done", "dead"):
                return st
            if st == "missing":
                off = ctx.offsets.get(s["arm"], 0)
                if off:
                    ctx.sleep(off)
                with lock:
                    launches[s["key"]] = ctx.now()
                try:
                    backend.start(root, s["key"])
                except Exception as exc:  # noqa: BLE001 -- a launcher hiccup is an infrastructure failure of this session
                    return f"launch_error:{exc}"
            ok = backend.wait(root, s["key"], wave_timeout_s(ctx, s))
            backend.close(root, s["key"])
            return "done" if ok else "timeout"

        with ThreadPoolExecutor(max_workers=max(1, len(sessions))) as ex:
            outcomes = dict(zip([s["key"] for s in sessions], ex.map(one, sessions)))
        results = {s["key"]: backend.result(root, s["key"]) for s in sessions}
        infra = [k for k, r in results.items() if r is None or r.get("infrastructure_failure")]
        spread = (max(launches.values()) - min(launches.values())) if len(launches) > 1 else 0.0
        att["launch_spread_s"] = round(spread, 2)
        att["wave_valid"] = bool(not ctx.offsets) and spread <= ctx.max_spread_s
        att["outcomes"] = outcomes
        spent = wave_cost(ctx, backend, root, sessions)
        ledger.settle(f"{wid}#a{attempt_no}", spent)
        if infra:
            diag = {k: backend.diagnose(root, k, results[k]) for k in infra}
            att["reason"] = failure_reason(infra, outcomes, diag)
            att["infra_failed_sessions"] = infra
            if all("Maximum sessions" in str(outcomes.get(k, "")) for k in infra):
                # Forge's terminal cap, not a failed run: wait for capacity and retry; never counts against the attempt limit
                att["status"] = "capacity_wait"
                w["capacity_waits"] = w.get("capacity_waits", 0) + 1
                state.save()
                log(f"[{wid}] Forge terminal cap reached ({w['capacity_waits']}/{MAX_CAPACITY_WAITS}); waiting {CAPACITY_WAIT_S:.0f}s for capacity")
                if w["capacity_waits"] > MAX_CAPACITY_WAITS:
                    raise BreakerOpen(f"[{wid}] Forge terminal cap still reached after {MAX_CAPACITY_WAITS} waits: {att['reason']}")
                if hasattr(backend, "forge_reap"):
                    try:
                        backend.forge_reap(ctx.campaign_root)
                    except Exception:  # noqa: BLE001 -- reaping is best effort
                        pass
                ctx.sleep(CAPACITY_WAIT_S)
                continue
            kinds = {k: classify_failure(results[k], diag[k]) for k in infra}
            att["failure_kinds"] = kinds
            cfg = {k: diag[k]["error_tail"] for k, v in kinds.items() if v == "config_error"}
            if cfg:
                att["status"], att["error_tail"] = "config_error", cfg
                w["status"] = "config_error"
                state.save()
                raise ConfigError(wid, cfg)
            att["status"] = "infra_failed"
            log(f"[{wid}] attempt {attempt_no}: transient infrastructure failure: {att['reason']}; rerunning the whole wave")
            trip = breaker.note_infra(wid) if breaker is not None else None
            if trip:
                w["status"] = "pending"            # not the scenario's fault: left runnable, never excluded by a breaker trip
                state.save()
                raise BreakerOpen(trip)
            if any(diag[k].get("worker_died") for k in infra):
                log(f"[{wid}] workers vanished mid-run (Forge daemon restart/shutdown, sleep, killed terminal?): "
                    "check ~/Library/Logs/forge/daemon.err.log for 'Shutting down daemon'")
            state.save()
            continue
        att["status"] = "done"
        w["status"], w["accepted_attempt"] = "done", attempt_no
        if breaker is not None and not any(a["status"] == "infra_failed" for a in w["attempts"]):
            breaker.note_clean(wid)
        state.save()
        if not att["wave_valid"]:
            log(f"[{wid}] WARNING launch spread {spread:.1f}s > {ctx.max_spread_s}s (or staggered): rows marked wave_valid=false")
        return "done"
    w["status"] = "excluded"
    w["excluded_reason"] = "; ".join(f"a{a['attempt']}: {a.get('reason', '?')}" for a in w["attempts"] if a["status"] == "infra_failed")
    state.save()
    trip = breaker.note_excluded(wid) if breaker is not None else None
    if trip:
        raise BreakerOpen(trip)
    return "excluded"


def reset_waves(state: State, ids: list, log=print) -> list:
    """Make waves runnable again (``run --reset-wave``): archive their attempts under ``history``, keep attempt
    numbering and the ledger (spend is never forgotten), clear the status. 'excluded' resets every excluded or
    config_error wave. Finished waves are refused: their data is accepted results."""
    wanted = [w for w, v in state.d["waves"].items() if v["status"] in ("excluded", "config_error")] if ids == ["excluded"] else ids
    done = []
    for wid in wanted:
        w = state.wave(wid)
        if w["status"] == "done":
            raise PairedError(EXIT_PRECONDITION, f"wave {wid} is done (accepted results); refusing to reset it")
        w.setdefault("history", []).append({"status": w["status"], "attempts": w["attempts"]})
        w["attempt_offset"] = max([a["attempt"] for a in w["attempts"]] + [w.get("attempt_offset", 0)])
        w.update(status="pending", attempts=[], accepted_attempt=None)
        done.append(wid)
        log(f"reset wave {wid} (attempt numbering continues after {w['attempt_offset']}; ledger kept)")
    state.save()
    return done


def check_prompt_hashes(root: Path, sessions: list, plan: dict) -> None:
    """R1 after prepare: every session's recorded prompt hash equals its scenario's hash, so all arms of a
    scenario got byte-identical prompts. A mismatch refuses the launch (nothing paid has run yet)."""
    man = _read_json(Path(root) / "manifest.json")
    for s in sessions:
        item = man["runs"][s["key"]]
        want = plan["scenarios"][s["scenario"]]["prompt_sha256"]
        if item["prompt_sha256"] != want:
            raise PairedError(EXIT_PRECONDITION, f"prompt hash mismatch for {s['key']}: {item['prompt_sha256']} != {want}")


def forge_clamp(backend, root: Path, parallel: int, log=print) -> int:
    """--parallel can never exceed what Forge can hold: its terminal cap (default 10, exited-but-unclosed terminals count)
    minus FORGE_RESERVE for the user, minus terminals that are not ours. Backends without Forge (tests) return as is."""
    if not hasattr(backend, "forge_max_sessions"):
        return parallel
    try:
        cap = backend.forge_max_sessions()
        try:
            backend.forge_reap(root)
        except Exception:  # noqa: BLE001
            pass
        info = backend.forge_terminals(root)
    except Exception as exc:  # noqa: BLE001 -- unreachable Forge: leave it to the launcher's own retry logic
        log(f"forge capacity check skipped: {exc!r}")
        return parallel
    external = max(0, info["total"] - info["ours"])
    allowed = max(1, cap - FORGE_RESERVE - external)
    if allowed < parallel:
        log(f"--parallel {parallel} clamped to {allowed}: Forge allows {cap} terminals, {external} belong to others, "
            f"{FORGE_RESERVE} kept free (raise maxSessions in ~/.forge/settings.json and restart the daemon for more)")
    return min(parallel, allowed)


def run_campaign(ctx: Ctx, backend, *, budget_usd: float, parallel: int, resume: bool, max_waves=None,
                 policy_config: dict | None = None, reset_waves_ids: list | None = None, watchdog=None, log=print,
                 breaker=None, stagger_per_session_s: float = 2.0) -> int:
    parallel = forge_clamp(backend, ctx.campaign_root, parallel, log)
    breaker = breaker if breaker is not None else CircuitBreaker()
    too_big = {w: len(v) for w, v in ctx.plan["waves"].items() if len(v) > parallel}
    if too_big:
        raise PairedError(EXIT_PRECONDITION, f"--parallel {parallel} is smaller than waves {too_big}: every arm of a wave must "
                                             "co-start. Pass --parallel N (N >= the largest wave) deliberately; the memory watchdog "
                                             "applies at any setting.")
    state, ledger = State(ctx.out / "state.json"), Ledger(ctx.out / "ledger.json", budget_usd)
    sha = settings_sha()
    prev = state.d.get("settings_sha256")
    if prev is not None and not str(prev).startswith("n1:"):
        # Recorded by the pre-normalization hash; it cannot be compared. Re-baseline, and keep the old value on record.
        state.d.setdefault("settings_rebaselined", []).append(
            {"from": prev, "to": sha, "at": datetime.now(timezone.utc).isoformat(),
             "why": "hash normalized to ignore updates.last_check; reviewed diff: only last_check and an unused provider"})
        prev = None
    if prev not in (None, sha):
        raise PairedError(EXIT_PRECONDITION, "~/.amplifier/settings.yaml changed since the campaign started (STUDY-DESIGN 18.5)")
    state.d["settings_sha256"] = sha
    state.save()
    if reset_waves_ids:
        reset_waves(state, reset_waves_ids, log)
    todo = [w for w in ctx.plan["wave_order"] if state.wave(w)["status"] not in ("done", "excluded")]
    if max_waves is not None:
        todo = todo[:max_waves]
    slots, futures, code = Slots(parallel), [], EXIT_OK
    stop, config_errors, breaker_errors = threading.Event(), [], []
    if watchdog is not None and not watchdog.is_alive():
        watchdog.start()
    last_admit = None                               # (time, size) of the previous wave admission
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        for wid in todo:
            size = len(ctx.plan["waves"][wid])
            if watchdog is not None:
                watchdog.gate(log)                  # no wave is admitted while system memory is short
            slots.acquire(size)
            if stop.is_set():
                slots.release(size)
                break
            if last_admit is not None:
                # stagger BETWEEN waves: the previous wave's launches (spaced by the launcher) must finish before the next
                # wave's start, so a wave's arms stay within the launch spread while many waves run at once
                wait = last_admit[0] + last_admit[1] * stagger_per_session_s + 2.0 - ctx.now()
                if wait > 0:
                    ctx.sleep(wait)
            if hasattr(backend, "forge_terminals"):
                # live terminal count must leave room for this wave (exited terminals of ours are reaped first)
                for _ in range(MAX_CAPACITY_WAITS):
                    try:
                        if backend.forge_terminals(ctx.campaign_root)["total"] + size <= backend.forge_max_sessions():
                            break
                        backend.forge_reap(ctx.campaign_root)
                    except Exception:  # noqa: BLE001
                        break
                    log(f"waiting for Forge terminal capacity before {wid} ({size} sessions)")
                    ctx.sleep(CAPACITY_WAIT_S)
            if stop.is_set():
                slots.release(size)
                break
            last_admit = (ctx.now(), size)
            try:
                need = sum(s["est_usd"] for s in ctx.plan["waves"][wid])
                if ledger.committed() + need > budget_usd + 1e-9:
                    raise BudgetExceeded(f"hard stop: ${ledger.committed():.2f} committed + ${need:.2f} for {wid} > ${budget_usd:.2f}")
            except BudgetExceeded as exc:
                slots.release(size)
                log(f"STOP: {exc.reason}")
                code = EXIT_BUDGET
                break

            def job(wid=wid, size=size):
                try:
                    return run_wave(ctx, backend, state, ledger, wid, policy_config or {}, resume, log, breaker=breaker)
                except ConfigError as exc:
                    config_errors.append(exc)
                    stop.set()           # a configuration error is the same for every wave: launch no further wave
                    return "config_error"
                except BreakerOpen as exc:
                    breaker_errors.append(exc)
                    stop.set()           # repeated infrastructure failures: stop launching, do not burn through the schedule
                    return "breaker_open"
                finally:
                    slots.release(size)
            futures.append(ex.submit(job))
        for f in futures:
            try:
                f.result()
            except BudgetExceeded as exc:
                log(f"STOP: {exc.reason}")
                code = EXIT_BUDGET
    if watchdog is not None:
        watchdog.stop()
    if breaker_errors:
        for exc in breaker_errors:
            log(exc.reason)
        log("STOPPED: infrastructure is unhealthy. No wave was excluded by this trip; fix the cause (see the attempt reasons "
            "in state.json) and re-run with --resume.")
        return EXIT_PRECONDITION
    if config_errors:
        for exc in config_errors:
            log(exc.reason)
        log("No further wave was launched. Fix the configuration, then re-run `preflight` and `run` (the wave is not "
            "counted as failed; add --reset-wave <id> only for waves that were excluded).")
        return EXIT_PRECONDITION
    return code


# ----------------------------------------------------------------------------------------- rows / grade

def accepted_sessions(out: Path):
    """(wave_id, attempt dict, session dict) for the accepted attempt of every done wave."""
    state = _read_json(Path(out) / "state.json", {"waves": {}})
    for wid, w in state["waves"].items():
        if w.get("accepted_attempt") is None:
            continue
        att = next(a for a in w["attempts"] if a["attempt"] == w["accepted_attempt"])
        for s in att["sessions"]:
            yield wid, att, s


def extract_rows(out: Path, backend=None, *, specs=None, snap_stats=None, tools_prefix_tokens: float = 0.0) -> dict:
    out = Path(out)
    backend = backend or ForgeBackend()
    plan = _read_json(out / "schedule.json")
    pf = _read_json(out / "preflight.json") or {}
    prov_base = {"price_table_sha": price_table_sha(), "nonce_mode": plan["nonce_mode"], "plan_id": plan["plan_id"],
                 "provider_module": pf.get("provider_module"), "campaign_provider": pf.get("campaign_provider"),
                 "preflight_ok": pf.get("ok")}
    rows, trows, skipped = [], [], []
    for wid, att, s in accepted_sessions(out):
        root = Path(att["root"])
        res = backend.result(root, s["key"])
        if res is None:
            skipped.append(s["key"])
            continue
        spec = specs[s["scenario"]]
        sdir = sessions_dir_for_workspace(backend.workspace(root, s["key"])) / (res.get("session_id") or "none")
        parsed = merge_run_receipts(parse_events(sdir), backend.run_dir(root, s["key"]) / "events")
        km = _read_json(backend.run_dir(root, s["key"]) / KILL_MARKER)
        meta = {**s, "scenario_hash": plan["scenarios"][s["scenario"]]["scenario_hash"],
                "wave_valid": att.get("wave_valid", True), "concurrent_sessions": len(att["sessions"]), "killed_memory_info": km}
        prov = {"build_sha": (res.get("source_expected") or {}).get("git_sha"),
                "bundle_tree_sha": (res.get("source_expected") or {}).get("tree_sha256"), **prov_base}
        row, tr = session_row(meta, res, parsed, spec, (snap_stats or {}).get(s["scenario"], {}), prov, tools_prefix_tokens)
        rows.append(row)
        trows.extend(tr)
    reqrows = [q for r in rows for q in r.pop("_request_rows")]
    pairs = build_pairs(rows, trows, plan.get("anchor_arm", "anchor"))
    d = out / "rows"
    d.mkdir(exist_ok=True)
    for name, data in (("sessions", rows), ("turns", trows), ("requests", reqrows), ("pairs", pairs)):
        (d / f"{name}.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in data), encoding="utf-8")
    flagged = [r["session_key"] for r in rows if not r["cache_audit_clean"]]
    summary = {"sessions": len(rows), "turns": len(trows), "requests": len(reqrows), "pairs": len(pairs),
               "tools_normalized_delta_usd_total": round(sum(r["tools_normalized_delta_usd"] for r in rows), 6), "skipped_no_result": skipped,
               "cache_audit_flagged_sessions": flagged,
               "mechanism_failed": [r["session_key"] for r in rows if not r["mechanism_engaged"]],
               "killed_memory": [r["session_key"] for r in rows if r["killed_memory"]],
               "cost_mismatch": [r["session_key"] for r in rows if r["cost_mismatch"]]}
    _write_json(d / "summary.json", summary)
    return summary


def regrade(out: Path, backend, specs, snapshots, *, passes: int = 1) -> dict:
    """Re-grade every preserved per-turn workspace tarball with no model call. ``passes`` > 1 grades repeatedly
    and reports whether all passes agree (P7: grader determinism)."""
    import tarfile
    results = []
    for _ in range(passes):
        one = {}
        for wid, att, s in accepted_sessions(out):
            root, spec = Path(att["root"]), specs[s["scenario"]]
            res = backend.result(root, s["key"]) or {}
            for t in res.get("turns") or []:
                tar = backend.run_dir(root, s["key"]) / "turn-snapshots" / f"t{t['index']}.tar.gz"
                if t.get("skipped") or not tar.exists():
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    with tarfile.open(tar) as tf:
                        tf.extractall(tmp)
                    one[f"{s['key']}#t{t['index']}"] = ps.grade_turn(spec, t["index"], Path(tmp) / "ws",
                                                                      t.get("final_message"), snapshots[s["scenario"]])
        results.append(one)
    stored = {}
    for wid, att, s in accepted_sessions(out):
        res = backend.result(Path(att["root"]), s["key"]) or {}
        for t in res.get("turns") or []:
            if t.get("quality"):
                stored[f"{s['key']}#t{t['index']}"] = t["quality"]
    deterministic = all(r == results[0] for r in results)
    mismatches = [k for k, v in results[0].items() if k in stored and stored[k] != v]
    summary = {"graded_turns": len(results[0]), "passes": passes, "deterministic": deterministic,
               "differs_from_recorded": mismatches}
    _write_json(Path(out) / "regrade.json", {"summary": summary, "grades": results[0]})
    return summary


_RENDER_SNIPPET = (
    "import asyncio,sys\nfrom pathlib import Path\nfrom amplifier_foundation import load_bundle\n"
    "async def main():\n"
    "    b=await load_bundle(sys.argv[1]); p=await b.prepare()\n"
    "    class S:\n        coordinator=None\n"
    "    f=p._create_system_prompt_factory(b,S(),Path(sys.argv[2]))\n"
    "    sys.stdout.write(await f())\nasyncio.run(main())\n")


def render_system_prompt(profile: Path, workspace: Path, python=None) -> str:
    import forge_e2e
    proc = subprocess.run([str(python or forge_e2e.HOST_PYTHON), "-c", _RENDER_SNIPPET, Path(profile).as_uri(), str(workspace)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise PairedError(EXIT_PRECONDITION, f"render failed for {profile}: {proc.stderr[-300:]}")
    return proc.stdout


def render_check(out: Path, backend=None, renderer=None) -> dict:
    """Offline (no model call): render every session's system prompt. The nonce must lead it; with the nonce
    masked, prompts must be byte-identical across sessions of the same cell kind (plain vs fd), proving the
    nonce is the ONLY per-session difference and every arm shares the same prompt otherwise."""
    backend, renderer = backend or ForgeBackend(), renderer or render_system_prompt
    groups, report = {}, {"ok": True, "problems": [], "groups": {}}
    for wid, att, s in accepted_sessions(out) if (Path(out) / "state.json").exists() else []:
        run = backend.run_dir(Path(att["root"]), s["key"])
        text = renderer(run / "profile.md", backend.workspace(Path(att["root"]), s["key"]))
        nonce = s.get("nonce")
        if nonce and not text.startswith(f"run-nonce: {nonce}"):
            report["ok"] = False
            report["problems"].append(f"{s['key']}: nonce is not the first line of the system prompt")
        masked = text.replace(nonce, "<NONCE>") if nonce else text
        groups.setdefault("fd" if s["kind"] in ("fd", "sticky") else "plain", {})[s["key"]] = hashlib.sha256(masked.encode()).hexdigest()
    for g, members in groups.items():
        distinct = set(members.values())
        report["groups"][g] = {"sessions": len(members), "distinct_prompt_hashes": len(distinct)}
        if len(distinct) != 1:
            report["ok"] = False
            report["problems"].append(f"group {g}: {len(distinct)} distinct masked system prompts")
    return report


# ----------------------------------------------------------------------------------------- memory safety

DEFAULT_PARALLEL = 4
SESSION_CAP_GB = 8.0          # hard per-session cap on the agent process tree (campaign watchdog)
HARD_FLOOR_GB = 16.0          # system available memory below this: kill the newest session trees until above the pause floor
KILL_MARKER = "killed_memory.json"


def pause_floor_bytes(total: int | None = None) -> int:
    """Launch gate: no new wave while system AVAILABLE memory is below max(32 GB, 25% of RAM)."""
    total = memguard.total_memory_bytes() if total is None else total
    return int(max(32 * memguard.GB, 0.25 * total))


class RealProbe:
    """What the watchdog looks at. Injectable so tests use fake process tables."""

    def table(self, root: Path) -> list:
        """Every process as {pid, ppid, rss, cwd, started} (cwd None when unreadable)."""
        rows = []
        if memguard.psutil is not None:
            ps_ = memguard.psutil
            for p in ps_.process_iter(["pid", "ppid", "memory_info", "create_time"]):
                try:
                    mi = p.info["memory_info"]
                    if mi is None:
                        continue
                    try:
                        cwd = p.cwd()
                    except (ps_.Error, OSError):
                        cwd = None
                    rows.append({"pid": p.info["pid"], "ppid": p.info["ppid"], "rss": int(mi.rss), "cwd": cwd,
                                 "started": p.info["create_time"]})
                except (ps_.Error, OSError):
                    continue
            return rows
        cwds = {}
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True, check=False).stdout
        pid = None
        for line in out.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and pid is not None:
                cwds[pid] = line[1:]
        out = subprocess.run(["ps", "-Ao", "pid=,ppid=,rss=,etime="], capture_output=True, text=True, check=False).stdout
        now = time.time()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0].isdigit():
                rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "rss": int(parts[2]) * 1024, "cwd": cwds.get(int(parts[0])),
                             "started": now - _etime_seconds(parts[3])})
        return rows

    def available(self) -> int:
        return memguard.available_memory_bytes()

    def total(self) -> int:
        return memguard.total_memory_bytes()


def _etime_seconds(text: str) -> int:
    days, _, rest = text.partition("-") if "-" in text else ("0", "", text)
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def top_consumers(table: list, n: int = 8) -> list:
    return sorted(table, key=lambda r: -r["rss"])[:n]


def _worker_protected(run_dir: Path, rows_by_pid: dict) -> set:
    """The Forge worker (running.json controller_pid) and its ancestors: killing them would lose result.json and turn
    a task outcome into a fake infrastructure failure. Only the agent subtree below the worker is ever killed."""
    try:
        pid = json.loads((run_dir / "running.json").read_text()).get("controller_pid")
    except (OSError, ValueError):
        return set()
    out, depth = set(), 0
    while pid and pid in rows_by_pid and depth < 30:
        out.add(pid)
        pid, depth = rows_by_pid[pid]["ppid"], depth + 1
    return out


class Watchdog(threading.Thread):
    """Campaign memory watchdog. Every ``interval`` s: (a) find every process whose cwd is inside the campaign root,
    group them by session workspace (<root>/<wave>/<session>/...), children inherit their parent's session; kill a
    session's agent process tree above ``session_cap_gb`` and write ``killed_memory.json`` into its run dir (a task
    outcome: the worker survives, the turn fails, the session is kept but flagged invalid for cost); (b) pause launching
    new waves while system available memory < ``pause_floor``; below ``hard_floor`` (or when the campaign uses more
    than 115% of ``max_system_use_gb``) kill the most recently started session trees, one per tick, until above the
    floor. ``tick()`` is deterministic and testable; the thread just calls it."""

    def __init__(self, campaign_root, *, session_cap_gb: float = SESSION_CAP_GB, pause_floor_gb: float | None = None,
                 hard_floor_gb: float = HARD_FLOOR_GB, max_system_use_gb: float | None = None, probe=None, kill=None,
                 log=print, interval: float = 1.0, sleep=time.sleep, now=time.time):
        super().__init__(daemon=True, name="paired-watchdog")
        self.root = Path(campaign_root).resolve()
        self.session_cap = int(session_cap_gb * memguard.GB)
        self.probe = probe or RealProbe()
        self.pause_floor = int(pause_floor_gb * memguard.GB) if pause_floor_gb is not None else pause_floor_bytes(self.probe.total())
        self.hard_floor = int(hard_floor_gb * memguard.GB)
        self.max_use = int(max_system_use_gb * memguard.GB) if max_system_use_gb else None
        self.kill, self.log, self.interval, self.sleep, self.now = kill or memguard.kill_pids, log, interval, sleep, now
        self.stop_event, self.ok_to_launch = threading.Event(), threading.Event()
        self.ok_to_launch.set()
        self.killed, self.peak, self.paused_log = [], {}, []

    # -- one observation -------------------------------------------------------------------------------------------
    def sessions(self, rows: list) -> dict:
        """{'<wave>/<session>': {run_dir, rows, agent}} for processes in (or descended from processes in) the root."""
        by_pid = {r["pid"]: r for r in rows}
        owner = {}
        for r in rows:
            cwd = r.get("cwd")
            if not cwd:
                continue
            try:
                rel = Path(cwd).resolve().relative_to(self.root)
            except (ValueError, OSError):
                continue
            if len(rel.parts) >= 2:
                owner[r["pid"]] = f"{rel.parts[0]}/{rel.parts[1]}"
        for r in rows:
            if r["pid"] in owner:
                continue
            pid, depth = r["ppid"], 0
            while pid in by_pid and depth < 25:
                if pid in owner:
                    owner[r["pid"]] = owner[pid]
                    break
                pid, depth = by_pid[pid]["ppid"], depth + 1
        groups = {}
        for pid, key in owner.items():
            g = groups.setdefault(key, {"run_dir": self.root / key.split("/")[0] / key.split("/")[1], "rows": []})
            g["rows"].append(by_pid[pid])
        for key, g in groups.items():
            prot = _worker_protected(g["run_dir"], by_pid)
            g["agent"] = [r for r in g["rows"] if r["pid"] not in prot]
            g["rss"] = sum(r["rss"] for r in g["agent"])
            g["started"] = min((r["started"] for r in g["agent"]), default=0)
        return groups

    def _kill_session(self, key: str, g: dict, reason: str, avail: int) -> None:
        pids = [r["pid"] for r in g["agent"]]
        self.kill(pids)
        info = {"at": datetime.now(timezone.utc).isoformat(), "reason": reason, "rss_gb": round(g["rss"] / memguard.GB, 2),
                "session_cap_gb": round(self.session_cap / memguard.GB, 2), "available_gb": round(avail / memguard.GB, 1),
                "pids": pids}
        try:
            (g["run_dir"] / KILL_MARKER).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        self.killed.append({"session": key, **info})
        self.log(f"WATCHDOG killed {key} ({reason}): agent tree {info['rss_gb']} GB, system available {info['available_gb']} GB")

    def tick(self) -> dict:
        rows = self.probe.table(self.root)
        groups = self.sessions(rows)
        avail = self.probe.available()
        for key, g in groups.items():
            self.peak[key] = max(self.peak.get(key, 0), g["rss"])
        for key, g in list(groups.items()):
            if g["rss"] > self.session_cap and g["agent"]:
                self._kill_session(key, g, "session_cap", avail)
                groups.pop(key)
        used = sum(g["rss"] for g in groups.values())
        low = avail < self.pause_floor
        busy = self.max_use is not None and used > self.max_use
        was_paused = not self.ok_to_launch.is_set()
        if low or busy:
            self.ok_to_launch.clear()
            if not was_paused:
                msg = (f"WATCHDOG pausing wave launches: available {avail / memguard.GB:.1f} GB (floor {self.pause_floor / memguard.GB:.0f}), "
                       f"campaign uses {used / memguard.GB:.1f} GB")
                self.paused_log.append(msg)
                self.log(msg)
        else:
            if was_paused:
                self.log("WATCHDOG resuming wave launches")
            self.ok_to_launch.set()
        hard = avail < self.hard_floor or (self.max_use is not None and used > 1.15 * self.max_use)
        if hard and groups:
            newest = max(groups.items(), key=lambda kv: kv[1]["started"])
            self._kill_session(newest[0], newest[1], "system_floor", avail)
        return {"available": avail, "used": used, "paused": not self.ok_to_launch.is_set(),
                "sessions": {k: g["rss"] for k, g in groups.items()}}

    def gate(self, log=None, poll_s: float = 1.0) -> None:
        """Block while launches are paused (called before each wave is admitted)."""
        announced = False
        while not self.ok_to_launch.is_set() and not self.stop_event.is_set():
            if not announced and log:
                log("waiting for system memory before launching the next wave ...")
                announced = True
            self.sleep(poll_s)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 -- the watchdog must never die silently, nor crash the campaign
                self.log(f"WATCHDOG tick failed: {exc!r}")
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()
        self.ok_to_launch.set()


class MemorySafetyError(PairedError):
    pass


def memory_safety_check(probe=None, floor_bytes: int | None = None) -> dict:
    """Refuse to start a campaign when the machine is already short of memory; print what is using it."""
    probe = probe or RealProbe()
    floor = pause_floor_bytes(probe.total()) if floor_bytes is None else floor_bytes
    avail = probe.available()
    if avail >= floor:
        return {"ok": True, "available_gb": round(avail / memguard.GB, 1), "floor_gb": round(floor / memguard.GB, 1)}
    top = top_consumers(probe.table(Path("/nonexistent-root")), 8)
    lines = [f"  {r['rss'] / memguard.GB:6.2f} GB  pid {r['pid']}  cwd {r.get('cwd') or '?'}" for r in top]
    raise MemorySafetyError(EXIT_PRECONDITION, f"refusing to start: system available memory {avail / memguard.GB:.1f} GB is below the "
                                               f"floor {floor / memguard.GB:.0f} GB. Top memory consumers:\n" + "\n".join(lines))


# ----------------------------------------------------------------------------------------- preflight

_PROVIDER_SNIPPET = (
    "import importlib, importlib.metadata as md, json, pathlib, subprocess\n"
    "out = {'module': 'provider-anthropic'}\n"
    "try:\n"
    "    m = importlib.import_module('amplifier_module_provider_anthropic')\n"
    "    p = pathlib.Path(m.__file__).resolve()\n"
    "    out['path'] = str(p.parent)\n"
    "    try:\n        out['version'] = md.version('amplifier-module-provider-anthropic')\n    except Exception:\n        out['version'] = None\n"
    "    for par in p.parents:\n"
    "        r = subprocess.run(['git', '-C', str(par), 'rev-parse', 'HEAD'], capture_output=True, text=True)\n"
    "        if r.returncode == 0:\n            out['git_sha'] = r.stdout.strip(); out['git_root'] = str(par); break\n"
    "except Exception as exc:\n    out['error'] = repr(exc)\n"
    "print(json.dumps(out))\n")


def provider_module_info(python=None) -> dict:
    """Which provider-anthropic the host interpreter will import (module path, package version, git sha)."""
    import forge_e2e
    try:
        proc = subprocess.run([str(python or forge_e2e.HOST_PYTHON), "-c", _PROVIDER_SNIPPET], capture_output=True,
                              text=True, timeout=60, check=False)
        info = json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
        info = {"module": "provider-anthropic", "error": repr(exc)}
    return info


def preflight_targets(ctx: Ctx) -> list:
    """Distinct (cell, model, key) the planned waves will use. A sticky arm expands to BOTH of its pin cells (the
    decision is only made at launch). Each target carries the set of models its first response may come from."""
    cheap = "claude-sonnet-5"
    seen, out = set(), []
    for wave in ctx.plan["waves"].values():
        for s in wave:
            arm = ctx.design["arms"][s["arm"]]
            if s["kind"] == "sticky":
                variants = [(arm["cells"][s["host"]]["host"], "pin-host"), (arm["cells"][s["host"]]["cheap"], "pin-cheap")]
            else:
                variants = [(s["cell"], s["kind"])]
            for cell, kind in variants:
                _, cell_model, _ = cell_to_side(cell, ctx.cells_doc, ctx.suites_doc, baseline_source=ctx.baseline_source,
                                                candidate_source=ctx.candidate_source, candidate_sha=ctx.candidate_sha)
                model = s["model"] or cell_model
                key_env = ctx.key_env.get(s["arm"])
                ident = (cell, model, key_env)
                if ident in seen:
                    continue
                seen.add(ident)
                expected = {"pin-cheap": {cheap}, "fd": {model, cheap}}.get(kind, {model})
                out.append({"cell": cell, "model": model, "key_env": key_env, "kind": "fd" if kind in ("fd", "pin-host", "pin-cheap") else kind,
                            "variant": kind, "expected_models": sorted(expected), "arm": s["arm"], "host": s["host"]})
    return out


def preflight_fingerprint(ctx: Ctx, targets: list) -> str:
    body = {"targets": sorted((t["cell"], t["model"], t["key_env"] or "") for t in targets),
            "candidate": ctx.candidate_sha, "provider": ctx.design.get("campaign_provider")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def run_preflight(ctx: Ctx, backend, ledger: Ledger, *, parallel: int, log=print, provider_info=None) -> dict:
    """One minimal session ("Reply with OK.") per distinct (cell, model, key), in the SAME isolated provider
    environment the campaign uses, concurrently. Passes only if every session completes and has an llm:response
    from an expected model. Costs cents; the measured cost is recorded in the ledger. Writes preflight.json."""
    targets = preflight_targets(ctx)
    pdir = _abs(REPO_ROOT, ctx.design["preflight"]["scenario_dir"])
    specs = {s.id: s for s in ps.load_dir(pdir)}
    snap_root = _abs(REPO_ROOT, ctx.design["snapshot_root"])
    pf_ctx = replace(ctx, design={**ctx.design, "scenario_dir": str(pdir)}, specs=specs,
                     snapshots={"preflight": str(ps.materialize(specs["preflight"], snap_root))})
    stamp = int(time.time() * 1000)
    ledger_key = f"preflight#{stamp}"
    ledger.reserve(ledger_key, round(ctx.design["preflight"]["est_usd_per_session"] * len(targets), 4))
    sessions, key_env = [], {}
    for i, t in enumerate(targets):
        key = f"pf{i}"
        key_env[key] = t["key_env"]
        sessions.append({"key": key, "wave_id": "preflight", "scenario": "preflight", "rep": 1, "host": t["host"], "arm": key,
                         "kind": t["kind"], "cell": t["cell"], "model": t["model"], "attempt": 1, "est_usd": 0.0,
                         "nonce": make_nonce(ctx.plan["plan_id"], key, stamp) if ctx.plan["nonce_mode"] == "per_session" else None})
    pf_ctx.key_env = {k: v for k, v in key_env.items() if v}
    root = ctx.campaign_root / f"pf-{stamp}"
    report = {"ok": False, "run_at": datetime.now(timezone.utc).isoformat(), "root": str(root), "sessions": [], "total_cost_usd": 0.0}
    try:
        backend.prepare_wave(pf_ctx, root, sessions)

        def one(s):
            try:
                backend.start(root, s["key"])
            except Exception as exc:  # noqa: BLE001
                return f"launch_error:{exc}"
            ok = backend.wait(root, s["key"], 900)
            backend.close(root, s["key"])
            return "done" if ok else "timeout"
        with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(sessions)))) as ex:
            outcomes = dict(zip([s["key"] for s in sessions], ex.map(one, sessions)))
        total = 0.0
        for s, t in zip(sessions, targets):
            res = backend.result(root, s["key"])
            entry = {"cell": t["cell"], "model": t["model"], "key_env": t["key_env"], "variant": t["variant"], "outcome": outcomes[s["key"]]}
            models, cost, raw_flags = [], 0.0, []
            if res and res.get("session_id") and not res.get("infrastructure_failure"):
                sdir = sessions_dir_for_workspace(backend.workspace(root, s["key"])) / res["session_id"]
                parsed = parse_events(sdir)
                models = sorted({r["model"] for r in parsed["requests"] if r["main"] and r["model"]})
                raw_flags = [r["has_raw"] for r in parsed["requests"] if r["main"]]
                cost = sum(c for c in (recompute_cost(r["model"], r["uncached"], r["read"], r["write"], r["output"])
                                       for r in parsed["requests"]) if c is not None)
            raw_ok = bool(raw_flags) and all(raw_flags)
            entry.update(models_seen=models, cost_usd=round(cost, 6), raw_events=raw_ok,
                         passed=bool(models) and set(models) <= set(t["expected_models"]) and raw_ok)
            if not entry["passed"]:
                diag = backend.diagnose(root, s["key"], res)
                entry["error_tail"] = diag["error_tail"] or ("session produced no response from "
                                                              f"{t['expected_models']} (models seen: {models})")
                if models and not raw_ok:
                    entry["error_tail"] = ("llm:request events carry no raw payload: the campaign provider needs `raw: true` "
                                           "(background calls cannot be told from main-loop calls without it)")
                    entry["failure_kind"] = "raw_events_missing"
                else:
                    entry["failure_kind"] = classify_failure(res, diag) if (res is None or res.get("infrastructure_failure")) else "unexpected_model"
            total += cost
            report["sessions"].append(entry)
        report["total_cost_usd"] = round(total, 6)
        report["ok"] = all(e["passed"] for e in report["sessions"])
    finally:
        ledger.settle(ledger_key, report["total_cost_usd"])
    report["fingerprint"] = preflight_fingerprint(ctx, targets)
    report["provider_module"] = provider_info() if callable(provider_info) else provider_module_info()
    report["campaign_provider"] = {k: v for k, v in (ctx.design.get("campaign_provider") or {}).items() if k != "config"}
    report["campaign_provider"]["config_keys"] = sorted((ctx.design.get("campaign_provider") or {}).get("config", {}))
    _write_json(ctx.out / "preflight.json", report)
    for e in report["sessions"]:
        log(f"preflight {'PASS' if e['passed'] else 'FAIL'}  {e['cell']:22} {e['model']:20} key={e['key_env'] or 'default'}  "
            f"models={','.join(e['models_seen']) or '-'}  ${e['cost_usd']:.4f}")
        if not e["passed"]:
            log("    " + "\n    ".join(e["error_tail"].splitlines()))
    log(f"preflight {'PASSED' if report['ok'] else 'FAILED'}: {len(report['sessions'])} sessions, ${report['total_cost_usd']:.4f}")
    return report


def preflight_is_fresh(ctx: Ctx) -> bool:
    rep = _read_json(ctx.out / "preflight.json")
    if not rep or not rep.get("ok"):
        return False
    if rep.get("fingerprint") != preflight_fingerprint(ctx, preflight_targets(ctx)):
        return False
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(rep["run_at"])).total_seconds() / 3600
    except (KeyError, ValueError):
        return False
    return age_h <= ctx.design["preflight"].get("max_age_hours", 12)


# ----------------------------------------------------------------------------------------- CLI

def key_env_names_available() -> set:
    """NAMES of key variables available (process env + ~/.amplifier/keys.env). Values are never read or printed."""
    names = {k for k in os.environ if k.endswith("API_KEY")}
    kp = Path.home() / ".amplifier" / "keys.env"
    if kp.exists():
        for line in kp.read_text(errors="replace").splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if m:
                names.add(m.group(1))
    return names


def _kv(items, cast=str) -> dict:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        if not k or not v:
            raise PairedError(EXIT_PRECONDITION, f"expected ARM=VALUE, got {it!r}")
        out[k] = cast(v)
    return out


def _common(args):
    design = load_design(args.design)
    if getattr(args, "nonce_mode", None):
        design["nonce_mode"] = args.nonce_mode
    return design, load_specs(design)


def cmd_plan(args) -> int:
    design, specs = _common(args)
    hosts = [h.strip() for h in args.hosts.split(",")] if args.hosts else list(design["hosts"])
    arms = [a.strip() for a in args.arms.split(",")] if args.arms else list(design["arms"])
    for h in hosts:
        if h not in design["hosts"]:
            raise PairedError(EXIT_PRECONDITION, f"unknown host {h!r}")
    for a in arms:
        if a not in design["arms"]:
            raise PairedError(EXIT_PRECONDITION, f"unknown arm {a!r}")
    reps = args.reps or design["default_reps"]
    parallel = args.parallel or design.get("default_parallel", DEFAULT_PARALLEL)
    scenarios = set(args.scenarios.split(",")) if args.scenarios else None
    budget = args.budget_usd if args.budget_usd is not None else design.get("budget_usd")
    plan = build_plan(design, specs, reps=reps, hosts=hosts, arms=arms, scenarios=scenarios, seed=args.seed,
                      budget_usd=budget, parallel=parallel)
    key_env, offsets = _kv(args.key_env), _kv(args.offset, int)
    if key_env:
        missing = {v for v in key_env.values()} - key_env_names_available()
        if missing:
            raise PairedError(EXIT_PRECONDITION, f"key env var(s) not found (names checked only): {sorted(missing)}")
    print(render_plan(plan))
    if args.dry_run:
        return EXIT_OK
    if not args.out:
        raise PairedError(EXIT_PRECONDITION, "--out is required unless --dry-run")
    out = Path(args.out).expanduser().resolve()
    if (out / "schedule.json").exists():
        raise PairedError(EXIT_PRECONDITION, f"{out} already has a schedule.json (plans are frozen; use a new --out)")
    out.mkdir(parents=True, exist_ok=True)
    camp_root = _abs(Path.cwd(), args.campaign_root) if args.campaign_root else _abs(REPO_ROOT, design["campaign_root_base"]) / out.name
    camp_root.mkdir(parents=True, exist_ok=True)
    flat = [s for w in plan["waves"].values() for s in w]
    plan["max_encoded_workspace_len"] = check_path_lengths(camp_root, flat)
    snap_root = _abs(REPO_ROOT, design["snapshot_root"])
    snaps = {}
    for spec in specs:
        if spec.id in plan["scenarios"]:
            snaps[spec.id] = str(ps.materialize(spec, snap_root))
    import battery
    cand = Path(args.candidate_source or REPO_ROOT).expanduser().resolve()
    frozen, info = battery._freeze_candidate_source(str(cand), camp_root, candidate_sha=args.candidate_sha)
    plan.update({"candidate": {"requested": str(cand), "frozen_source": frozen, "info": info},
                 "baseline_source": str(Path(args.baseline_source).expanduser().resolve()) if args.baseline_source else frozen,
                 "campaign_root": str(camp_root), "snapshots": snaps,
                 "key_env": key_env, "offsets": offsets, "settings_sha256": settings_sha(),
                 "created_at": datetime.now(timezone.utc).isoformat()})
    _write_json(out / "schedule.json", plan)
    (out / "plan.txt").write_text(render_plan(plan) + "\n", encoding="utf-8")
    print(f"\nwrote {out/'schedule.json'} (campaign root {camp_root}, widest encoded workspace path {plan['max_encoded_workspace_len']} bytes)")
    return EXIT_OK


def _ctx_from_schedule(out: Path, args=None) -> Ctx:
    plan = _read_json(Path(out) / "schedule.json")
    if plan is None:
        raise PairedError(EXIT_PRECONDITION, f"{out}/schedule.json not found (run `plan` first)")
    if args is not None and getattr(args, "design", None):
        design_path = args.design
    else:
        # The schedule names its design; use it so `run`/`rows` never silently fall back to the pilot design.
        candidate = REPO_ROOT / "evals" / "paired" / f"{plan.get('design', '')}.yaml"
        design_path = candidate if plan.get("design") and candidate.exists() else DEFAULT_DESIGN
    design = load_design(design_path)
    if plan.get("design") and design.get("id") != plan["design"]:
        raise PairedError(EXIT_PRECONDITION, f"design {design.get('id')!r} does not match the schedule's {plan['design']!r}")
    import run as evals_run
    specs = {s.id: s for s in load_specs(design)}
    for sid, m in plan["scenarios"].items():
        if ps.scenario_hash(specs[sid]) != m["scenario_hash"]:
            raise PairedError(EXIT_PRECONDITION, f"scenario {sid} changed since the plan was frozen (hash mismatch)")
    return Ctx(out=Path(out), design=design, cells_doc=evals_run.load_cells(_abs(REPO_ROOT, design["cells_file"])),
               suites_doc=evals_run.load_suites(), specs=specs, snapshots=plan["snapshots"], plan=plan,
               campaign_root=Path(plan["campaign_root"]), candidate_source=plan["candidate"]["frozen_source"],
               candidate_sha=plan["candidate"]["info"]["git_sha"] if plan["candidate"].get("info") else None,
               baseline_source=plan["baseline_source"], seed=plan["seed"], key_env=plan.get("key_env") or {},
               offsets=plan.get("offsets") or {}, deadline_s=design.get("deadline_seconds_per_turn", 900),
               max_spread_s=design.get("max_wave_launch_spread_s", 60), max_attempts=design.get("max_wave_attempts", 3))


def cmd_run(args) -> int:
    out = Path(args.out).expanduser().resolve()
    ctx = _ctx_from_schedule(out, args)
    budget = args.budget_usd if args.budget_usd is not None else ctx.plan.get("budget_usd")
    if budget is None:
        raise PairedError(EXIT_PRECONDITION, "--budget-usd is required (the hard stop)")
    parallel = args.parallel or DEFAULT_PARALLEL
    if args.dry_run:
        print(f"would run {len(ctx.plan['wave_order'])} waves (parallel {parallel}, budget ${budget:.2f}); first waves:")
        for w in ctx.plan["wave_order"][:5]:
            print(f"  {w}: " + ", ".join(s['arm'] for s in ctx.plan['waves'][w]))
        return EXIT_OK
    import forge_e2e
    safety = memory_safety_check(floor_bytes=int(args.pause_floor_gb * memguard.GB) if args.pause_floor_gb else None)
    print(f"memory check ok: {safety['available_gb']} GB available (floor {safety['floor_gb']} GB)")
    backend = ForgeBackend()
    try:    # keep the Mac awake while the campaign runs (idle/system sleep killed sessions: markdown-tocclass-r1-opus)
        subprocess.Popen(["caffeinate", "-i", "-m", "-s", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("caffeinate attached (idle/system sleep prevented; clamshell sleep on battery cannot be prevented: keep the lid open or on AC)")
    except OSError:
        pass
    if not args.skip_preflight and not preflight_is_fresh(ctx):
        rep = run_preflight(ctx, backend, Ledger(out / "ledger.json", budget), parallel=parallel)
        if not rep["ok"]:
            print("paired.py: preflight FAILED; no wave was launched (exit 4). Fix the cause above and re-run.", file=sys.stderr)
            return EXIT_PRECONDITION
    policy = forge_e2e.composed_effective_config(ctx.candidate_source, {}) or {}
    reset = (args.reset_wave or None)
    wd = Watchdog(ctx.campaign_root, session_cap_gb=args.session_cap_gb, pause_floor_gb=args.pause_floor_gb,
                  hard_floor_gb=args.hard_floor_gb, max_system_use_gb=args.max_system_use_gb)
    code = run_campaign(ctx, backend, budget_usd=budget, parallel=parallel, resume=args.resume,
                        max_waves=args.waves, policy_config=policy, reset_waves_ids=reset, watchdog=wd)
    print(json.dumps({"exit": code, "state": str(out / "state.json"), "ledger": str(out / "ledger.json")}))
    return code


def cmd_preflight(args) -> int:
    out = Path(args.out).expanduser().resolve()
    ctx = _ctx_from_schedule(out, args)
    budget = args.budget_usd if args.budget_usd is not None else ctx.plan.get("budget_usd")
    if budget is None:
        raise PairedError(EXIT_PRECONDITION, "--budget-usd is required (the ledger hard stop)")
    targets = preflight_targets(ctx)
    if args.dry_run:
        for t in targets:
            print(f"{t['cell']:22} {t['model']:20} key={t['key_env'] or 'default':38} expects {','.join(t['expected_models'])}")
        print(f"{len(targets)} preflight sessions (est ${ctx.design['preflight']['est_usd_per_session'] * len(targets):.2f})")
        return EXIT_OK
    rep = run_preflight(ctx, ForgeBackend(), Ledger(out / "ledger.json", budget), parallel=args.parallel or DEFAULT_PARALLEL)
    pm = rep.get("provider_module") or {}
    print(json.dumps({"ok": rep["ok"], "total_cost_usd": rep["total_cost_usd"], "sessions": len(rep["sessions"]),
                      "provider_module": {k: pm.get(k) for k in ("version", "git_sha", "path", "error")}}, indent=2))
    return EXIT_OK if rep["ok"] else EXIT_PRECONDITION


def _specs_and_stats(out: Path, args):
    ctx = _ctx_from_schedule(out, args)
    stats = {sid: ps.workspace_stats(Path(p)) for sid, p in ctx.snapshots.items()}
    return ctx, stats


def cmd_rows(args) -> int:
    out = Path(args.out).expanduser().resolve()
    ctx, stats = _specs_and_stats(out, args)
    summary = extract_rows(out, specs=ctx.specs, snap_stats=stats,
                           tools_prefix_tokens=ctx.design.get("cache_audit", {}).get("tools_prefix_tokens", 0))
    print(json.dumps(summary, indent=2))
    return EXIT_OK


def cmd_grade(args) -> int:
    out = Path(args.out).expanduser().resolve()
    ctx, _ = _specs_and_stats(out, args)
    summary = regrade(out, ForgeBackend(), ctx.specs, {k: Path(v) for k, v in ctx.snapshots.items()}, passes=args.passes)
    print(json.dumps(summary, indent=2))
    return EXIT_OK if summary["deterministic"] else EXIT_PRECONDITION


def cmd_render_check(args) -> int:
    out = Path(args.out).expanduser().resolve()
    rep = render_check(out)
    print(json.dumps(rep, indent=2))
    return EXIT_OK if rep["ok"] else EXIT_PRECONDITION


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="schedule + cost estimate (+ budget refusal); --dry-run touches nothing")
    pl.add_argument("--design", default=str(DEFAULT_DESIGN))
    pl.add_argument("--out")
    pl.add_argument("--seed", type=int, default=20261002)
    pl.add_argument("--reps", type=int)
    pl.add_argument("--hosts", help="comma list from the design (default: all)")
    pl.add_argument("--arms", help="comma list from the design (default: all)")
    pl.add_argument("--scenarios", help="comma list of scenario ids")
    pl.add_argument("--budget-usd", type=float)
    pl.add_argument("--parallel", type=int, help=f"default {DEFAULT_PARALLEL} (memory safety)")
    pl.add_argument("--nonce-mode", choices=["per_session", "none"])
    pl.add_argument("--candidate-source")
    pl.add_argument("--candidate-sha")
    pl.add_argument("--baseline-source")
    pl.add_argument("--campaign-root")
    pl.add_argument("--key-env", action="append", metavar="ARM=ENVVAR", help="per-arm API key: env var NAME")
    pl.add_argument("--offset", action="append", metavar="ARM=SECONDS", help="delay an arm's start (P2 contrast only)")
    pl.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run", help="launch waves (bounded concurrency, budget hard stop, resumable)")
    r.add_argument("--out", required=True)
    r.add_argument("--design")
    r.add_argument("--parallel", type=int)
    r.add_argument("--budget-usd", type=float)
    r.add_argument("--waves", type=int, help="run only the first N unfinished waves")
    r.add_argument("--resume", action="store_true", help="adopt finished and live sessions")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--skip-preflight", action="store_true", help="do not run the preflight (not recommended)")
    r.add_argument("--session-cap-gb", type=float, default=SESSION_CAP_GB, help="watchdog: kill a session's agent tree above this RSS")
    r.add_argument("--pause-floor-gb", type=float, help="no new wave while system available memory is below this (default max(32, 25%% of RAM))")
    r.add_argument("--hard-floor-gb", type=float, default=HARD_FLOOR_GB, help="below this, kill the newest session trees until above the pause floor")
    r.add_argument("--max-system-use-gb", type=float, help="cap on total RSS of all campaign session processes (pause above, kill newest at 115%%)")
    r.add_argument("--reset-wave", action="append", metavar="WAVE_ID",
                   help="make an excluded / config_error wave runnable again ('excluded' = all of them); attempt "
                        "numbering and the ledger are kept")
    pf = sub.add_parser("preflight", help="one minimal session per distinct (cell, model, key); aborts (exit 4) on failure")
    pf.add_argument("--out", required=True)
    pf.add_argument("--design")
    pf.add_argument("--parallel", type=int)
    pf.add_argument("--budget-usd", type=float)
    pf.add_argument("--dry-run", action="store_true", help="list what would run; no session, no spend")
    for name, help_ in (("rows", "extract sessions/turns/pairs datasets"), ("grade", "re-grade preserved turn snapshots (no model)"),
                        ("render-check", "offline system-prompt render + nonce check")):
        c = sub.add_parser(name, help=help_)
        c.add_argument("--out", required=True)
        c.add_argument("--design")
        if name == "grade":
            c.add_argument("--passes", type=int, default=2)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"plan": cmd_plan, "run": cmd_run, "rows": cmd_rows, "grade": cmd_grade,
                "render-check": cmd_render_check, "preflight": cmd_preflight}[args.cmd](args)
    except PairedError as exc:
        print(f"paired.py: {exc.reason}", file=sys.stderr)
        return exc.code
    except ps.ScenarioError as exc:
        print(f"paired.py: scenario error: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION


if __name__ == "__main__":
    sys.exit(main())
