#!/usr/bin/env python3
"""A1: the observatory week (docs/design/v3/PLAN.md, section A1; RQ1). Offline, $0.

Streams the local observatory event store (~/.amplifier/fast-decisions/events/, one JSONL file per session; and
events-eval/) line by line -- never a whole file in memory -- and writes privacy-safe aggregates only: counts, rates,
latency quantiles. No workspace names, labels, paths, prompts, responses, candidate ids or hashes leave this module.

What it answers:
  1. traffic: production vs eval/test per session (AFAST_TRAFFIC receipt tag after 09-25; Forge label; scratch/eval
     workspace basenames), with the unclassifiable share;
  2. the 1,642 `shadow_agreement` events decomposed by backend (local qwen3:0.6b, the scripted demo backend, ...),
     period (week 09-17..09-23 vs later), abstention, and whether the host's actual tool was the candidate tool at all;
  3. what "match" compares (the scorer's chosen prepared read == the host LLM's next tool call, tool AND argument digest);
  4. a census of decision kinds per session, judge latency p50/p95 per backend, and the event mix (heartbeats);
  5. efficiency receipts (keep-alive, loop_stop, cheaper_model, ...) next to what was later measured.
The relabelling step (6) is not possible: the store keeps no state text (privacy allow-list), so it is reported as
unidentifiable and costs $0.

Usage: nice -n 10 python3 -m evals.v3.a1_observatory [--events DIR] [--eval-events DIR] [--cutoff ISO] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from evals.v3.common import REPO_ROOT, mean, quantile, wilson, write_csv, write_json

STORE = Path.home() / ".amplifier" / "fast-decisions"
OUT = REPO_ROOT / "docs" / "evidence" / "2026-10-v3-offline" / "a1-observatory"
CUTOFF = "2026-10-05T17:00:00+00:00"          # snapshot taken before this analysis ran; later events are excluded
WEEK = ("2026-09-17", "2026-09-23")           # the observatory week (UTC dates, inclusive)
JEV_DEFAULT_DAY = "2026-09-24"                # Jev became the default judge (1f8bd4c)
CANDIDATE_TOOL = "fast_workspace"             # every prepared read candidate targets this tool (candidates.py)

DECISION_KINDS = ("difficulty_judged", "session_routed", "model_routed", "effort_routed", "scored", "routed",
                  "shadow_proposed", "role_proposed", "delegation_routed", "escalation_judged", "escalation_signals",
                  "phase_judged", "decided_batch", "tool_risk", "cua_decided", "turn_planned", "easy_turn_shaped",
                  "waste_guard", "cache_refresh", "efficiency", "judge_usage")
LATENCY_KINDS = ("scored", "shadow_proposed", "difficulty_judged", "judge_usage", "delegation_routed", "cua_decided")

# Eval/test markers on a workspace BASENAME (only the basename is recorded). Generic patterns only: scratch dirs,
# mktemp suffixes, harness/eval words. Anything else with a name is production; no name and no label = unclassified.
_TEST_EXACT = {"workspace", "tmp", "ws", "proj", "fdtest", "a", "b", "c", "d"}
_TEST_RE = re.compile(r"(^|[-_.])(afast|fd|forge|smoke|live|repro|trial|check|review|rereview|audit|e2e|test|tests|"
                      r"overhead|eval|bench|attr|agent|integration|release|hardening|study|p0|doctor|guards|facade|"
                      r"ledger|registry|naming|lazy)([-_.]|$)|\.[A-Za-z0-9]{4}$", re.IGNORECASE)

# Later measurements the receipts can be checked against (source paths in this repo).
MEASURED_LATER = {
    "cache_keepalive": {"measured": "one live A/B, 330 s wait: measured saving $0.160384 = receipt $0.160384",
                        "source": "evals/levers-2026-09-25/wait330-c-post-review-summary.json"},
    "loop_stop": {"measured": "waste-guards A/B (Opus, 3 reps), poll wait: measured $0.0558 vs receipt $0.0514",
                  "source": "docs/evidence/2026-09-25/waste-guards-ab/README.md"},
    "cheaper_model": {"measured": "real-workload replay: routing routine steps to Sonnet would ADD $17-46",
                      "source": "docs/evidence/2026-09-25/step-opportunity/summary.json; docs/GOAL.md"},
    "context_rightsize": {"measured": "none", "source": None},
}


def classify_name(workspace_name: str | None, session_label: str | None) -> tuple[str, str]:
    """(traffic class, basis) from the recorded basename and label alone."""
    if isinstance(session_label, str) and session_label.strip().lower().startswith("forge"):
        return "test", "forge_label"
    if not workspace_name:
        return "unclassified", "no_name"
    if workspace_name in _TEST_EXACT or _TEST_RE.search(workspace_name):
        return "test", "workspace_marker"
    return "production", "workspace_default"


def period(day: str) -> str:
    if day < WEEK[0]:
        return "before"
    return "week" if day <= WEEK[1] else "after"


def tool_class(actual_tool: str | None) -> str:
    if actual_tool is None:
        return "none"
    return "candidate_tool" if actual_tool == CANDIDATE_TOOL else "other_tool"


class Census:
    """Streaming aggregator. Feed every event with `add(event, store)`; call `finish()` once."""

    def __init__(self, cutoff: str = CUTOFF):
        self.cutoff = cutoff
        self.excluded_after_cutoff = 0
        self.bad_lines = 0
        self.counts = Counter()                       # (store, session, day, event) -> n
        self.health = Counter()                       # (store, session, day, health kind) -> n
        self.config = {}                              # (store, session) -> (workspace_name, label, harness)
        self.modes = defaultdict(set)                 # (store, session) -> {(mode, backend)}
        self.parent = {}                              # (store, session) -> parent session id
        self.receipt_traffic = defaultdict(set)       # (store, session) -> {production/test}
        self.proposals = {}                           # (store, session, decision) -> proposal facts
        self.agreements = []                          # agreement facts joined at finish()
        self.latency = []                             # (store, session, kind, backend, model, ms, day)
        self.receipts = []                            # (store, session, lever, decision, traffic, usd, s, day)
        self.routed = Counter()                       # (store, session, route, reason)
        self.difficulty = Counter()                   # (store, session, backend, choice, reason)
        self.slow_ms = []                             # (store, session, ms, day)
        self.slow_agg = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])   # (store, session, host_model) -> calls,$,ms,cr,cw
        self.first_start = {}                         # (store, session) -> first start-tier reason group
        self.effort = defaultdict(lambda: [None, 0, 0, Counter()])   # (store, session) -> last, requests, changes, efforts

    def add(self, e: dict, store: str = "events") -> bool:
        """Aggregate one event; False when it falls after the cutoff (excluded)."""
        ts = e.get("timestamp") or ""
        if ts > self.cutoff:
            self.excluded_after_cutoff += 1
            return False
        day, sid = ts[:10], e.get("session_id")
        name = str(e.get("event", "")).split(":")[-1]
        x = e.get("data") or {}
        sk = (store, sid)
        self.counts[(store, sid, day, name)] += 1
        if e.get("parent_session_id"):
            self.parent.setdefault(sk, e["parent_session_id"])
        if name == "health":
            kind = x.get("phase") or ("native_hook_metadata" if x.get("native_event") is not None else
                                      "recorder_status" if "queue_depth" in x else "other")
            self.health[(store, sid, day, kind)] += 1
            if x.get("phase") == "configuration":
                self.config.setdefault(sk, (x.get("workspace_name"), x.get("session_label"), x.get("harness")))
                self.modes[sk].add((x.get("mode"), x.get("backend")))
        elif name == "shadow_proposed":
            self.proposals[(store, sid, e.get("decision_id"))] = {
                "backend": x.get("backend") or "unknown", "model": x.get("model") or "unknown",
                "synthetic": bool(x.get("synthetic")), "candidate_count": x.get("candidate_count"), "day": day}
            self._lat(store, sid, name, x, day)
        elif name == "shadow_agreement":
            self.agreements.append({"store": store, "session": sid, "decision": e.get("decision_id"), "day": day,
                                    "agreement": x.get("agreement"), "tool_class": tool_class(x.get("actual_tool")),
                                    "would_have_avoided": bool(x.get("would_have_avoided_llm_turn"))})
        elif name in LATENCY_KINDS:
            self._lat(store, sid, name, x, day)
            if name == "difficulty_judged":
                self.difficulty[(store, sid, x.get("backend"), x.get("choice"), x.get("reason_code"))] += 1
                self.first_start.setdefault(sk, x.get("reason_code") or "unknown")
        elif name == "efficiency":
            t = x.get("traffic")
            if t:
                self.receipt_traffic[sk].add(t)
            self.receipts.append((store, sid, x.get("lever"), x.get("decision"), t, x.get("usd_saved") or 0.0,
                                  x.get("seconds_saved") or 0.0, day))
        elif name == "effort_routed":
            st = self.effort[sk]
            eff = x.get("requested_effort")
            if st[1] and eff != st[0]:
                st[2] += 1
            st[0] = eff
            st[1] += 1
            st[3][str(eff)] += 1
        elif name == "routed":
            self.routed[(store, sid, x.get("route"), x.get("reason_code"))] += 1
        elif name == "slow_end":
            ms = x.get("duration_ms")
            if isinstance(ms, (int, float)):
                self.slow_ms.append((store, sid, float(ms), day))
            a = self.slow_agg[(store, sid, x.get("host_model") or "unknown")]
            a[0] += 1
            for i, f in ((1, "cost_usd"), (2, "duration_ms"), (3, "cache_read_tokens"), (4, "cache_write_tokens")):
                v = x.get(f)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    a[i] += v
        return True

    def _lat(self, store, sid, kind, x, day):
        ms = x.get("duration_ms")
        if kind == "difficulty_judged":
            # only judge_* reasons call the backend; scope_/rules_/restored decisions record ~0 ms by construction
            rc = str(x.get("reason_code") or "")
            kind = "difficulty_judged:" + ("judge_call" if rc.startswith("judge_") else "no_judge_call")
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            self.latency.append((store, sid, kind, x.get("backend") or "unknown", x.get("model") or "unknown",
                                 float(ms), day))

    # ------------------------------------------------------------------------------------------------ classification
    def classify(self) -> dict:
        """(store, session) -> (class, basis). eval-store sessions are test; receipts' AFAST_TRAFFIC tag wins;
        children without their own config inherit the parent's class."""
        sessions = {(s, sid) for (s, sid, _, _) in self.counts}
        out = {}
        for sk in sessions:
            store, sid = sk
            if store == "events-eval":
                out[sk] = ("test", "eval_store")
            elif self.receipt_traffic.get(sk):
                out[sk] = ("test" if "test" in self.receipt_traffic[sk] else "production", "afast_traffic_tag")
            elif sk in self.config:
                out[sk] = classify_name(*self.config[sk][:2])
        for sk in sessions - set(out):
            par = self.parent.get(sk)
            cls = out.get((sk[0], par))
            out[sk] = (cls[0], "inherited_from_parent") if cls and cls[0] != "unclassified" else ("unclassified",
                                                                                                 "no_config")
        return out

    # ------------------------------------------------------------------------------------------------------- finish
    def finish(self) -> dict:
        cls = self.classify()
        tr = lambda store, sid: cls.get((store, sid), ("unclassified", "no_config"))[0]  # noqa: E731
        res = {}

        # 1. events, by store / period / traffic / type; and by day for the figure
        by_type, by_day = Counter(), Counter()
        for (store, sid, day, ev), n in self.counts.items():
            by_type[(store, period(day), tr(store, sid), ev)] += n
            by_day[(store, day, tr(store, sid), ev)] += n
        res["events_by_type"] = [{"store": a, "period": b, "traffic": c, "event": d, "n": n}
                                 for (a, b, c, d), n in sorted(by_type.items())]
        res["events_by_day"] = [{"store": a, "day": b, "traffic": c, "event": d, "n": n}
                                for (a, b, c, d), n in sorted(by_day.items())]
        totals = Counter()
        for (store, sid, day, ev), n in self.counts.items():
            totals[(store, "all")] += n
            totals[(store, period(day))] += n
        hk = Counter()
        for (store, sid, day, kind), n in self.health.items():
            hk[(store, kind)] += n
        res["health_mix"] = [{"store": s, "health_kind": k, "n": n, "share_of_store_events": n / totals[(s, "all")]}
                             for (s, k), n in sorted(hk.items())]

        # traffic table
        tt = Counter()
        ev_by_session = Counter()
        for (store, sid, day, ev), n in self.counts.items():
            ev_by_session[(store, sid)] += n
        for sk, (c, basis) in cls.items():
            tt[(sk[0], c, basis, "sessions")] += 1
            tt[(sk[0], c, basis, "events")] += ev_by_session[sk]
        res["traffic"] = [{"store": s, "traffic": c, "basis": b, "sessions": tt[(s, c, b, "sessions")],
                           "events": tt[(s, c, b, "events")]}
                          for (s, c, b, k) in sorted(tt) if k == "sessions"]

        # 2-3. shadow agreement decomposition
        rows = Counter()
        unjoined = 0
        for a in self.agreements:
            p = self.proposals.get((a["store"], a["session"], a["decision"]))
            if p is None:
                unjoined += 1
                p = {"backend": "unjoined", "model": "unjoined", "synthetic": None}
            rows[(a["store"], p["backend"], p["model"], p["synthetic"], period(a["day"]),
                  "jev_default_era" if a["day"] >= JEV_DEFAULT_DAY else "pre_jev_default", tr(a["store"], a["session"]),
                  a["tool_class"], a["agreement"])] += 1
        res["shadow_rows"] = [{"store": k[0], "backend": k[1], "model": k[2], "synthetic": k[3], "period": k[4],
                               "era": k[5], "traffic": k[6], "host_tool": k[7], "agreement": k[8], "n": n}
                              for k, n in sorted(rows.items(), key=str)]
        res["shadow_unjoined"] = unjoined

        def rate(filt, denom_filter=lambda r: True):
            sel = [(k, n) for k, n in rows.items() if filt(k) and denom_filter(k)]
            n = sum(v for _, v in sel)
            m = sum(v for k, v in sel if k[8] == "match")
            p, lo, hi = wilson(m, n)
            return {"match": m, "n": n, "rate": p, "wilson95": [lo, hi]}
        ev = lambda k: k[0] == "events"  # noqa: E731
        real = lambda k: k[1] not in ("scripted-demo",)  # noqa: E731
        res["shadow_rates"] = {
            "all (the 7.1% headline)": rate(ev),
            "scripted-demo backend (synthetic: always the first candidate)": rate(lambda k: ev(k) and k[1] == "scripted-demo"),
            "real scorer (non-synthetic)": rate(lambda k: ev(k) and real(k)),
            "real scorer, not abstained": rate(lambda k: ev(k) and real(k) and k[8] != "abstained"),
            "real scorer, host used the candidate tool": rate(lambda k: ev(k) and real(k) and k[7] == "candidate_tool"),
            "real scorer, host used the candidate tool, not abstained":
                rate(lambda k: ev(k) and real(k) and k[7] == "candidate_tool" and k[8] != "abstained"),
            "any scorer, host used another tool (unmatchable by construction)":
                rate(lambda k: ev(k) and k[7] == "other_tool"),
            "observatory week": rate(lambda k: ev(k) and k[4] == "week"),
            "after the week": rate(lambda k: ev(k) and k[4] == "after"),
            "jev-default era (>= 09-24)": rate(lambda k: ev(k) and k[5] == "jev_default_era"),
            "production traffic": rate(lambda k: ev(k) and k[6] == "production"),
            "test traffic": rate(lambda k: ev(k) and k[6] == "test"),
            "eval store (events-eval)": rate(lambda k: k[0] == "events-eval"),
        }
        res["shadow_backends_scored"] = dict(Counter(f"{p['backend']}|{p['model']}" for k, p in self.proposals.items()
                                                     if k[0] == "events"))

        # 4. decision census per session
        per = defaultdict(Counter)
        for (store, sid, day, evn), n in self.counts.items():
            if store == "events" and evn in DECISION_KINDS:
                per[(tr(store, sid), evn)][sid] += n
        n_sessions = Counter(tr(s, sid) for (s, sid) in cls if s == "events")
        cen = []
        for (traffic, kind), c in sorted(per.items()):
            vals = sorted(c.values())
            cen.append({"traffic": traffic, "kind": kind, "sessions_with_any": len(vals),
                        "share_of_sessions": len(vals) / n_sessions[traffic], "total": sum(vals),
                        "median_per_session_with_any": quantile(vals, 0.5), "p90_per_session_with_any": quantile(vals, 0.9),
                        "max_per_session": vals[-1]})
        res["census"] = cen
        res["sessions_by_traffic"] = dict(n_sessions)
        dif = Counter()
        for (store, sid, b, ch, rc), n in self.difficulty.items():
            if store == "events":
                dif[(tr(store, sid), b, ch, rc)] += n
        res["start_tier_decisions"] = [{"traffic": a, "backend": b, "choice": c, "reason_code": d, "n": n}
                                       for (a, b, c, d), n in sorted(dif.items(), key=str)]
        rt = Counter()
        for (store, sid, route, reason), n in self.routed.items():
            if store == "events":
                rt[(tr(store, sid), route, reason)] += n
        res["routed"] = [{"traffic": a, "route": b, "reason_code": c, "n": n} for (a, b, c), n in sorted(rt.items(), key=str)]

        # latency per (kind, backend, model)
        lat = defaultdict(list)
        for store, sid, kind, b, m, ms, day in self.latency:
            if store == "events":
                lat[(kind, b, m)].append(ms)
        res["latency"] = [{"kind": k, "backend": b, "model": m, "n": len(v), "p50_ms": quantile(v, .5),
                           "p95_ms": quantile(v, .95), "mean_ms": mean(v)} for (k, b, m), v in sorted(lat.items())]
        slow = [ms for store, sid, ms, day in self.slow_ms if store == "events"]
        res["slow_end_ms"] = {"n": len(slow), "p50": quantile(slow, .5), "p95": quantile(slow, .95), "mean": mean(slow)}

        # would-have-saved (ESTIMATE, the redesign doc's projection) for the real local scorer during the week
        wk = [k for k in rows if ev(k) and real(k) and k[4] == "week"]
        n_dec = sum(rows[k] for k in wk)
        n_match = sum(rows[k] for k in wk if k[8] == "match")
        week_slow = [ms for store, sid, ms, day in self.slow_ms if store == "events" and period(day) == "week"]
        week_score = [ms for store, sid, kind, b, m, ms, day in self.latency
                      if store == "events" and kind == "shadow_proposed" and b != "scripted-demo" and period(day) == "week"]
        res["would_have_saved_estimate"] = {
            "label": "ESTIMATED (never measured): decisions x (mean slow_end ms - mean scorer ms) x avoided-turn rate; "
                     "docs/design/redesign-2026-09-17.md `projected_task_latency_delta_ms`",
            "decisions": n_dec, "avoided_llm_turns_claimed": n_match,
            "avoided_rate": n_match / n_dec if n_dec else None,
            "mean_slow_end_ms_week": mean(week_slow), "mean_scorer_ms_week": mean(week_score),
            "projected_latency_saved_s": (n_dec * (mean(week_slow) - mean(week_score)) * (n_match / n_dec) / 1000)
            if n_dec else None,
        }

        # 5. receipts
        rc = defaultdict(lambda: [0, 0.0, 0.0])
        for store, sid, lever, dec, t, usd, s, day in self.receipts:
            if store == "events":
                r = rc[(lever, dec, t or "untagged", period(day))]
                r[0] += 1
                r[1] += usd
                r[2] += s
        res["receipts"] = [{"lever": lv, "decision": d, "traffic": t, "period": p, "n": v[0], "usd_saved_sum": v[1],
                            "seconds_saved_sum": v[2], "kind": "receipt-estimated (policy's own claim)",
                            "measured_later": MEASURED_LATER.get(lv, {}).get("measured"),
                            "measured_source": MEASURED_LATER.get(lv, {}).get("source")}
                           for (lv, d, t, p), v in sorted(rc.items(), key=str)]
        # A3 inputs: production workload as recorded by slow_end (host model mix, $, cache) and start-tier decisions
        wl = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0, set()])
        for (store, sid, hm), a in self.slow_agg.items():
            if store != "events":
                continue
            w = wl[(tr(store, sid), hm)]
            for i in range(5):
                w[i] += a[i]
            w[5].add(sid)
        res["workload"] = [{"traffic": t, "host_model": hm, "sessions": len(w[5]), "slow_calls": w[0],
                            "recorded_cost_usd": w[1], "provider_seconds": w[2] / 1000,
                            "cache_read_tokens": w[3], "cache_write_tokens": w[4]}
                           for (t, hm), w in sorted(wl.items(), key=str)]
        fs = Counter((tr(*sk), rc) for sk, rc in self.first_start.items() if sk[0] == "events")
        res["start_tier_first_per_session"] = [{"traffic": t, "reason_code": rc, "sessions": n}
                                               for (t, rc), n in sorted(fs.items(), key=str)]
        # the section-0.4 pattern in the wild: requested effort changing between consecutive requests of a session
        ec = defaultdict(lambda: [0, 0, 0, Counter()])
        for sk, (last, n, ch, effs) in self.effort.items():
            if sk[0] != "events":
                continue
            e = ec[tr(*sk)]
            e[0] += 1
            e[1] += n
            e[2] += ch
            e[3].update(effs)
        res["effort_switching"] = [{"traffic": t, "sessions": v[0], "requests": v[1], "effort_changes": v[2],
                                    "changes_per_request": v[2] / v[1] if v[1] else None,
                                    "sessions_with_a_change": sum(1 for sk, st in self.effort.items()
                                                                  if sk[0] == "events" and tr(*sk) == t and st[2]),
                                    "requested_efforts": dict(v[3])} for t, v in sorted(ec.items())]
        res["totals"] = {f"{s}|{p}": n for (s, p), n in sorted(totals.items())}
        res["excluded_after_cutoff"] = self.excluded_after_cutoff
        res["bad_lines"] = self.bad_lines
        res["session_files"] = {}
        return res


def stream_dir(census: Census, path: Path, store: str) -> int:
    """Feed every JSONL line of every file under `path` into the census, one line at a time. Returns the number of
    files holding at least one event at or before the cutoff (so the count does not grow with the live store)."""
    files = 0
    if not path.is_dir():
        return 0
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(".jsonl"):
            continue
        kept = False
        with open(path / fn, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    kept = census.add(json.loads(line), store) or kept
                except (json.JSONDecodeError, TypeError, AttributeError):
                    census.bad_lines += 1
        files += kept
    return files


def run(events: Path = STORE / "events", eval_events: Path = STORE / "events-eval", cutoff: str = CUTOFF,
        out: Path = OUT) -> dict:
    c = Census(cutoff)
    nf = stream_dir(c, events, "events")
    ne = stream_dir(c, eval_events, "events-eval")
    res = c.finish()
    res["session_files"] = {"events": nf, "events-eval": ne}
    week_total = sum(r["n"] for r in res["events_by_type"] if r["store"] == "events" and r["period"] == "week")
    summary = {
        "schema": "fast-decisions-observatory-summary/v1",
        "label": "privacy-safe aggregates of the local observatory store; counts are MEASURED event counts; "
                 "receipt dollars and projected savings are ESTIMATES",
        "store": {"events_dir": "~/.amplifier/fast-decisions/events", "eval_dir": "~/.amplifier/fast-decisions/events-eval",
                  "cutoff_utc": cutoff, "excluded_after_cutoff": res["excluded_after_cutoff"],
                  "session_files": res["session_files"], "bad_lines": res["bad_lines"], "totals": res["totals"],
                  "week": list(WEEK), "week_events": week_total},
        "traffic": res["traffic"], "sessions_by_traffic": res["sessions_by_traffic"],
        "health_mix": res["health_mix"],
        "shadow": {"what_match_means": (
            "match = the scorer's chosen prepared read candidate (always a `fast_workspace` read) has the same tool AND "
            "argument digest as the host LLM's next actual tool call. It measures agreement with the host, not "
            "correctness; a host call to any other tool (read_file, bash, grep, ...) is a mismatch by construction, "
            "even when it reads the same file. abstained = the scorer chose the slow path."),
            "rates": res["shadow_rates"], "backends_scored": res["shadow_backends_scored"],
            "unjoined_agreements": res["shadow_unjoined"],
            "relabel_step": "not run ($0): the store keeps no state text (privacy allow-list: hashes, counts, ids only), "
                            "so a strong model cannot judge whether a mismatch was defensible; the correctness of the "
                            "shadow choices is unidentifiable from this store"},
        "start_tier_decisions": res["start_tier_decisions"], "routed": res["routed"],
        "latency": res["latency"], "slow_end_ms": res["slow_end_ms"],
        "would_have_saved_estimate": res["would_have_saved_estimate"],
        "receipts": res["receipts"],
        "a3_inputs": {"label": "MEASURED recorded workload (slow_end cost_usd is the recorder's own price-table "
                               "estimate per call); start-tier = first difficulty_judged per session",
                      "workload": res["workload"], "start_tier_first_per_session": res["start_tier_first_per_session"],
                      "effort_switching": res["effort_switching"]},
    }
    write_json(out / "observatory-summary.json", summary)
    write_csv(out / "events_by_day.csv", res["events_by_day"])
    write_csv(out / "events_by_type.csv", res["events_by_type"])
    write_csv(out / "shadow_agreement_decomposition.csv", res["shadow_rows"])
    write_csv(out / "shadow_agreement_rates.csv", [{"slice": k, **v} for k, v in res["shadow_rates"].items()])
    write_csv(out / "latency_by_backend.csv", res["latency"])
    write_csv(out / "decision_census.csv", res["census"])
    write_csv(out / "receipts_reconciliation.csv", res["receipts"])
    write_csv(out / "traffic_classification.csv", res["traffic"])
    write_csv(out / "health_mix.csv", res["health_mix"])
    write_csv(out / "a3_workload.csv", res["workload"])
    write_csv(out / "a3_start_tier_first_per_session.csv", res["start_tier_first_per_session"])
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", type=Path, default=STORE / "events")
    ap.add_argument("--eval-events", type=Path, default=STORE / "events-eval")
    ap.add_argument("--cutoff", default=CUTOFF)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    s = run(a.events, a.eval_events, a.cutoff, a.out)
    print(json.dumps({"store": s["store"], "shadow": s["shadow"]["rates"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
