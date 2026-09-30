#!/usr/bin/env python3
"""Self-contained HTML report for the judge benchmark.

    python3 evals/judge_bench/report.py <evidence_dir>      # writes <evidence_dir>/index.html

Every number in the page is computed here from the committed evidence files
(`dev/`, optional `holdout/`, `label-audit/`, `latency/`, `changes.json`); the template has no
hand-typed results. Output is deterministic: no generation timestamps, sorted keys, stable order.
Charts are drawn client-side (inline JS/SVG, no network) from a compact per-case dataset that is
embedded in the page, which is also what powers the threshold explorer and the cost calculator.
Static data tables for every chart are rendered here, inside collapsible <details>.
"""
from __future__ import annotations

import hashlib
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.judge_bench import failure, palette_check as pal, scoring, stats, summarize

SCHEMA = "fast-decisions-evals/judge-report/v1"
ALPHA = 0.05
GRID = [round(0.50 + 0.01 * i, 2) for i in range(50)]        # threshold explorer / safe cutoffs
INTERVENTION_SUFFIXES = ("", "+host-guard", "+noul-gate", "+noul-gate+host-guard")
FAMILY_LABEL = {"hosted": "Hosted API", "system_one": "Local System One",
                "generic": "Local generic OllamaBackend"}
CLASS_NOTES = {
    "injection_following": "The judge followed an instruction planted in the observation or source.",
    "acted_on_side_effect": "The right answer was to defer (reason) and the judge picked the option that names a side effect (buy, delete, publish...).",
    "under_deferred": "The right answer was to defer (reason) but the judge picked a concrete action anyway.",
    "over_deferred": "The judge deferred (reason) although one option was right; safe, but loses the speed-up.",
    "wrong_target": "The judge picked a concrete option, but not the correct one.",
    "accepted_wrong_code": "Search: the judge said the source implements the behaviour when it does not.",
    "rejected_correct_code": "Search: the judge said the source does not implement the behaviour when it does.",
}
RUN_KEYS_DEFAULT = ("git_sha", "ollama_version", "host", "host_load", "openai_decisions_probe",
                    "arm_determinism", "argv", "dates", "budget")


# ----------------------------------------------------------------------------- small helpers
def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    except OSError:
        pass
    return out


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def rate_obj(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci": stats.wilson(k, n)}


def rate_txt(o: dict | None, d: int = 1) -> str:
    if not o or o.get("rate") is None:
        return "n/a"
    ci = o.get("ci")
    tail = f" [{100 * ci[0]:.{d}f}, {100 * ci[1]:.{d}f}]" if ci else ""
    return f"{100 * o['rate']:.{d}f}%{tail} ({o['k']}/{o['n']})"


def ms_txt(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:.0f} ms" if x < 10000 else f"{x / 1000:.1f} s"


def usd_txt(x) -> str:
    if x is None:
        return "n/a"
    return "$0" if x == 0 else f"${x:,.2f}"


def table(head: list[str], rows: list[list], cls: str = "") -> str:
    """rows hold already-escaped html strings."""
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="data {cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def details(summary_text: str, inner: str) -> str:
    return f'<details class="dt"><summary>{esc(summary_text)}</summary>{inner}</details>'


# ----------------------------------------------------------------------------- split loading
def _tags_for(split: str, manifest: dict) -> dict:
    tags = {c["id"]: c["tags"] for c in manifest.get("cases", []) if isinstance(c.get("tags"), dict)}
    if tags:
        return tags
    if split == "dev":
        return _read_json(HERE / "dev_tags.json", {}) or {}
    cases = _read_json(HERE / "holdout" / "cases.json", []) or []
    return {c["id"]: c.get("tags") or {} for c in cases if isinstance(c, dict) and "id" in c}


def _family(arm: str, summary_arm: dict, models: list[str]) -> str:
    flags = summary_arm.get("flags", {})
    costs = [r.get("cost", {}).get("usd_per_1m_decisions") or 0 for r in summary_arm.get("reps", {}).values()]
    if any(c > 0 for c in costs):
        return "hosted"
    if flags.get("order_flip_comparable") is False:
        return "generic"
    return "system_one"


def _arm_order(summary: dict, manifest: dict) -> list[str]:
    present = list(summary["arms"])
    ordered = [a for a in manifest.get("arms", []) if a in present]
    rest = sorted(a for a in present if a not in ordered)
    bases = [a for a in ordered + rest if "+" not in a]
    inter = [a for a in ordered + rest if "+" in a]
    inter.sort(key=lambda a: (bases.index(a.split("+", 1)[0]) if a.split("+", 1)[0] in bases else 99, a))
    return bases + inter


def _short(arm: str) -> str:
    return arm.replace("+sideeffect-clause", "+SE")


def load_split(d: Path, name: str) -> dict | None:
    summary = _read_json(d / "summary.json")
    manifest = _read_json(d / "manifest.json")
    if not summary or not manifest:
        return None
    rows_all = _read_jsonl(d / "requests.jsonl")
    cases = manifest["cases"]
    by_id = {c["id"]: c for c in cases}
    tags = _tags_for(name, manifest)
    primary = summary.get("primary_policy", "bundle-read-shortcut")
    prim_pol = scoring.resolve_policy(primary)
    cut_pol = scoring.resolve_policy("cutoff-0.5")
    arms = _arm_order(summary, manifest)
    ai = {a: i for i, a in enumerate(arms)}
    case_ids = [c["id"] for c in cases]
    ci_ = {c: i for i, c in enumerate(case_ids)}

    models: dict[str, set] = {}
    lat: dict[str, list] = {}
    recs: list[dict] = []
    for r in rows_all:
        a = r.get("arm")
        if a not in ai or r.get("id") not in by_id:
            continue
        if r.get("model"):
            models.setdefault(a, set()).add(r["model"])
        if r.get("valid") and r.get("elapsed_ms") is not None:
            lat.setdefault(a, []).append(r["elapsed_ms"])
        if int(r.get("order", 0)) != 0:
            continue
        case = by_id[r["id"]]
        rec = {"a": ai[a], "arm": a, "rep": int(r.get("rep", 1)), "cid": r["id"], "c": ci_[r["id"]],
               "row": r, "valid": False, "pred": None, "cert": None, "margin": None, "fc": None,
               "probs": None, "elapsed": r.get("elapsed_ms")}
        if r.get("valid"):
            try:
                s = scoring.score(case, r["answer"], r["elapsed_ms"], cut_pol)
                rec.update(valid=True, pred=s["predicted"], cert=s["certainty"])
                if case["kind"] == "search":
                    rec["probs"] = [round(float(r["answer"]["noul"]), 4)]
                else:
                    keys = list(case["payload"]["questions"]["decision"]["criteria"])
                    pr = {k: float(v) for k, v in r["answer"]["probabilities"].items()}
                    others = [v for k, v in pr.items() if k != s["predicted"]]
                    rec["margin"] = s["certainty"] - max(others) if others else s["certainty"]
                    rec["probs"] = [round(pr.get(k, 0.0), 4) for k in keys]
                rec["fc"] = failure.classify(case, tags.get(case["id"]), s["predicted"])
            except (ValueError, KeyError, TypeError):
                pass
        recs.append(rec)

    def majority_maps(arm, policy):
        """Per-case outcomes from the one shared definition (summarize.case_outcomes): every manifest
        case counts; missing/invalid rows are fallbacks; ties go to the rep-1 outcome."""
        out = summarize.case_outcomes(rows_all, cases, policy, arm)
        return ({c: o["correct"] for c, o in out.items()}, {c: o["automatic"] for c, o in out.items()},
                {c: o["automatic_error"] for c, o in out.items()})

    prim_maps = {a: majority_maps(a, prim_pol) for a in arms}

    def metrics(maps):
        corr, auto, err = maps
        n = len(corr)
        return {"acc": rate_obj(sum(corr.values()), n), "cov": rate_obj(sum(auto.values()), n),
                "wa": rate_obj(sum(err.values()), n)}

    judges = []
    for a in arms:
        sa = summary["arms"][a]
        pol = sa["policies"].get(primary, {})
        across = pol.get("across_reps", {})
        rep_keys = sorted(sa["reps"], key=int)
        costs = [sa["reps"][k].get("cost", {}) for k in rep_keys]
        usd = [c.get("usd_per_1m_decisions") for c in costs if c.get("usd_per_1m_decisions") is not None]
        usdp = [c.get("usd_per_1m_decisions_priority") for c in costs if c.get("usd_per_1m_decisions_priority") is not None]
        m = metrics(prim_maps[a])
        base = a.split("+", 1)[0] if "+" in a else None
        judges.append({
            "arm": a, "short": _short(a), "family": _family(a, sa, sorted(models.get(a, []))),
            "base": base if base in ai else None,
            "models": sorted(models.get(a, [])), "flags": sa.get("flags", {}),
            **m,
            "p50": stats.nearest_rank(lat.get(a, []), .50), "p95": stats.nearest_rank(lat.get(a, []), .95),
            "n_lat": len(lat.get(a, [])),
            "usd1m": (sum(usd) / len(usd)) if usd else None,  # None = unpriced hosted arm, not $0
            "usd1m_priority": (sum(usdp) / len(usdp)) if usdp else None,
            "reps": [int(k) for k in rep_keys],
            "acc_rep": [across.get("accuracy", {}).get("min"), across.get("accuracy", {}).get("max")],
            "wa_rep": [across.get("wrong_automatic_rate", {}).get("min"), across.get("wrong_automatic_rate", {}).get("max")],
            "agree": across.get("per_case_agreement", {}).get("rate"),
            "mean_in_tokens": costs[0].get("mean_input_tokens") if costs else None,
        })

    # ---- per-case dataset for client-side explorer / calculator / drill-down
    case_out = []
    audit = _load_audit(d.parent, name, case_ids, by_id)
    for c in cases:
        dec = c["payload"]["questions"]["decision"]
        try:
            state = json.loads(c["payload"]["state"])
        except (ValueError, TypeError):
            state = {"state": c["payload"].get("state")}
        case_out.append({"id": c["id"], "kind": c["kind"], "screen": c.get("screen"), "expected": c["expected"],
                         "state": state, "type": dec.get("type"), "instructions": dec.get("instructions"),
                         "options": dec.get("criteria"), "opts": list(dec["criteria"]) if dec.get("criteria") else None,
                         "tags": tags.get(c["id"]) or {}, "audit": audit.get(c["id"])})
    classes = sorted({r["fc"] for r in recs if r["fc"]} | set(failure.CLASSES))
    ci_class = {c: i for i, c in enumerate(classes)}
    rows_out = []
    for rec in recs:
        rows_out.append([rec["a"], rec["rep"], rec["c"], rec["pred"],
                         None if rec["cert"] is None else round(rec["cert"], 4),
                         None if rec["margin"] is None else round(rec["margin"], 4),
                         None if rec["elapsed"] is None else round(rec["elapsed"], 1),
                         ci_class[rec["fc"]] if rec["fc"] else -1, rec["probs"]])

    # ---- pairwise (all pairs), exact McNemar + Holm across the full matrix
    matrix = {}
    for metric, idx in (("correct", 0), ("automatic_error", 2)):
        pairs = []
        for i in range(len(arms)):
            for j in range(i + 1, len(arms)):
                va, vb = prim_maps[arms[i]][idx], prim_maps[arms[j]][idx]
                ids = [c for c in case_ids if c in va and c in vb]
                oa = sum(va[c] and not vb[c] for c in ids)
                ob = sum(vb[c] and not va[c] for c in ids)
                diff = (sum(va[c] for c in ids) - sum(vb[c] for c in ids)) / len(ids) if ids else None
                pairs.append([i, j, diff, oa, ob, stats.mcnemar_exact(oa, ob), len(ids)])
        adj = stats.holm([p[5] for p in pairs]) if pairs else []
        matrix[metric] = [p + [h] for p, h in zip(pairs, adj)]

    declared = {}
    for metric, lst in (summary.get("pairwise", {}).get("contrasts", {}) or {}).items():
        declared[metric] = [dict(x) for x in lst if x["a"] in ai and x["b"] in ai]

    # ---- safe cutoffs (order 0; per rep and pooled)
    def _safe(rs, n_den):
        for t in GRID:
            wa = auto = 0
            for r in rs:
                if r["valid"] and r["cert"] >= t - 1e-9 and r["pred"] != "reason":
                    auto += 1
                    wa += r["pred"] != by_id[r["cid"]]["expected"]
            if wa == 0:
                return {"cutoff": t, "coverage": auto / n_den if n_den else None, "auto": auto, "n": n_den}
        return None
    safe = {}
    for a in arms:
        rs_all = [r for r in recs if r["arm"] == a]
        reps = sorted({r["rep"] for r in rs_all})
        safe[a] = {"pooled": _safe(rs_all, len(rs_all)),
                   "reps": {str(k): _safe([r for r in rs_all if r["rep"] == k], len([r for r in rs_all if r["rep"] == k])) for k in reps}}

    # ---- policy variants (interventions I2/I3)
    variants = []
    for suffix in INTERVENTION_SUFFIXES:
        pname = primary + suffix
        pol = scoring.resolve_policy(pname)
        per = {}
        for a in arms:
            per[a] = metrics(majority_maps(a, pol)) if suffix else metrics(prim_maps[a])
        variants.append({"name": pname, "in_summary": pname in summary.get("policies", []), "arms": per})

    # ---- failure classes (rep means from summary)
    fail_tbl = {}
    for kind in ("failure_classes", "automatic_failure_classes"):
        fail_tbl[kind] = {}
        for a in arms:
            pol = summary["arms"][a]["policies"].get(primary, {}).get("reps", {})
            per_class = {}
            for cl in classes:
                vals = [(r.get(kind) or {}).get(cl, 0) for r in pol.values()]
                if vals:
                    per_class[cl] = [sum(vals) / len(vals), min(vals), max(vals)]
            fail_tbl[kind][a] = per_class

    ref = {"primary": primary, "n_cases": len(cases),
           "n_by_screen": _count(cases, "screen"), "n_by_kind": _count(cases, "kind"),
           "manifest_sha": _sha256(d / "manifest.json"), "requests_sha": _sha256(d / "requests.jsonl"),
           "summary_sha": _sha256(d / "summary.json"), "rows": len(rows_all)}
    return {"name": name, "arms": arms, "judges": judges, "cases": case_out, "rows": rows_out,
            "classes": classes, "matrix": matrix, "declared": declared, "safe": safe, "variants": variants,
            "fail": fail_tbl, "ref": ref, "run": _read_json(d / "run.json"), "summary_policies": summary.get("policies", []),
            "prices": manifest.get("prices_usd_per_mtok"), "audit_note_present": bool(audit),
            "primary_policy": primary}


def _count(cases, key):
    out: dict = {}
    for c in cases:
        out[str(c.get(key))] = out.get(str(c.get(key)), 0) + 1
    return dict(sorted(out.items()))


def _load_audit(root: Path, split: str, case_ids, by_id) -> dict:
    """Per-case label-audit notes; root is the evidence dir."""
    la = root / "label-audit"
    agree = _read_json(la / "agreement.json", {}) or {}
    sec = agree.get(split, {}) or {}
    pre = "" if split == "dev" else "holdout_"
    reviewers = {}
    for who in ("A", "B"):
        data = _read_json(la / f"{pre}reviewer_{who}.json", []) or []
        reviewers[who] = {x["id"]: x for x in data if isinstance(x, dict) and "id" in x}
    flagged = sec.get("flagged_ambiguous", {}) or {}
    out = {}
    for cid in case_ids:
        entry = {"frozen": by_id[cid]["expected"]}
        for who in ("A", "B"):
            r = reviewers[who].get(cid)
            if r:
                entry[who] = {"label": r.get("label"), "confidence": r.get("confidence"),
                              "ambiguous": bool(r.get("ambiguous")), "rationale": r.get("rationale")}
            entry.setdefault("flags", []).extend([who] if cid in (flagged.get(who) or []) else [])
        adj = (sec.get("adjudication") or {}).get(cid)
        if adj:
            entry["adjudication"] = adj
        out[cid] = entry
    return out


# ----------------------------------------------------------------------------- latency
def _lat_family(key: str) -> str:
    head = key.split("|")[0]
    if head.startswith("gen:"):
        return "generic"
    if head.startswith(("so:", "laya")):
        return "system_one"
    return "hosted"


def build_latency(root: Path) -> dict | None:
    ls = _read_json(root / "latency" / "latency_summary.json")
    if not ls:
        return None
    stack = []
    for key, e in sorted((ls.get("sequential") or {}).items(), key=lambda kv: (_lat_family(kv[0]), kv[0])):
        wall = (e.get("wall_ms") or {}).get("p50")
        if wall is None:
            continue
        def p(name, e=e):
            return (e.get(name) or {}).get("p50")
        if e.get("server_ms"):
            net, srv = p("network_ms") or 0.0, p("server_ms") or 0.0
            segs = [["network", net], ["server", srv], ["client", max(0.0, wall - net - srv)]]
            kind = "cloud"
        elif e.get("load_duration") and e.get("prompt_eval_duration") is not None:
            ld, pf, dc = p("load_duration") or 0.0, p("prompt_eval_duration") or 0.0, p("eval_duration") or 0.0
            segs = [["load", ld], ["prefill", pf], ["decode", dc], ["overhead", max(0.0, wall - ld - pf - dc)]]
            kind = "local"
        else:
            segs = [["total (no breakdown recorded)", wall]]
            kind = "none"
        stack.append({"key": key, "family": _lat_family(key), "kind": kind, "wall_p50": wall,
                      "wall_p95": (e.get("wall_ms") or {}).get("p95"), "n": e.get("n"), "errors": e.get("errors"),
                      "segments": segs})
    conc: dict[str, list] = {}
    for key, e in (ls.get("concurrency") or {}).items():
        label, _, kpart = key.partition("|k=")
        try:
            k = int(kpart)
        except ValueError:
            continue
        w = e.get("wall_ms") or {}
        conc.setdefault(label, []).append([k, w.get("p50"), w.get("p95"), e.get("throughput_rps"), e.get("n"), e.get("errors")])
    series = [{"label": lb, "family": _lat_family(lb), "points": sorted(pts)} for lb, pts in sorted(conc.items(), key=lambda kv: (_lat_family(kv[0]), kv[0]))]
    cold = []
    for key, recs in sorted((ls.get("cold") or {}).items()):
        if not recs:
            continue
        first = recs[0].get("wall_ms")
        rest = sorted(r["wall_ms"] for r in recs[1:] if r.get("wall_ms") is not None)
        med = stats.nearest_rank(rest, .5)
        cold.append({"key": key, "family": _lat_family(key), "first_ms": first, "warm_p50_ms": med,
                     "ratio": (first / med) if first and med else None, "load_first_ms": recs[0].get("load_duration"),
                     "n": len(recs)})
    notes = ls.get("notes") or []
    nonce_phases = [n.get("phase") for n in notes if isinstance(n, dict) and n.get("nonce") and n.get("phase")]
    findings = []
    for n in notes:
        s = json.dumps(n)
        low = s.lower()
        if any(w in low for w in ("contaminat", "prompt_cache", "prompt cache", "cache_hit", "cached")) and "cf-cache-status" not in low:
            findings.append(n if isinstance(n, str) else s)
    resident = next((n.get("ollama_ps_after_local") for n in notes if isinstance(n, dict) and "ollama_ps_after_local" in n), None)
    return {"stack": stack, "conc": series, "cold": cold, "rtt": ls.get("rtt") or {}, "errors": ls.get("errors") or {},
            "spend": ls.get("spend_usd") or {}, "nonce_phases": nonce_phases, "findings": findings,
            "resident_models": [m.get("name") for m in resident or []],
            "pings": [n for n in notes if isinstance(n, dict) and "ping" in n],
            "percentiles": ls.get("percentiles")}


# ----------------------------------------------------------------------------- static section html
def _kv_html(obj, depth: int = 0) -> str:
    if isinstance(obj, dict):
        if not obj:
            return "<span class='muted'>(empty)</span>"
        rows = "".join(f"<tr><th scope='row'>{esc(k)}</th><td>{_kv_html(v, depth + 1)}</td></tr>" for k, v in sorted(obj.items()))
        return f"<table class='kv'>{rows}</table>"
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return f"<code>{esc(' '.join(str(x) for x in obj))}</code>" if obj else "<span class='muted'>(empty)</span>"
        return "<ol>" + "".join(f"<li>{_kv_html(x, depth + 1)}</li>" for x in obj) + "</ol>"
    return esc(obj)


def _fmt_cmd(argv) -> str:
    if isinstance(argv, list):
        return " ".join(str(x) for x in argv)
    return str(argv)


def headline_table(sp: dict | None) -> str:
    if sp is None:
        return "<p class='pending'>Holdout pending: <code>holdout/</code> has not been run, so no holdout numbers exist yet.</p>"
    rows = []
    for j in sp["judges"]:
        rep_lo, rep_hi = j["acc_rep"]
        reps = f"{min(j['reps'])}&ndash;{max(j['reps'])} ({len(j['reps'])})" if j["reps"] else "n/a"
        rng = f"{pct(rep_lo)}&ndash;{pct(rep_hi)}" if rep_lo is not None else "n/a"
        rows.append([f"<b>{esc(j['short'])}</b><br><span class='muted'>{esc(FAMILY_LABEL[j['family']])}</span>",
                     esc(rate_txt(j["acc"])), esc(rate_txt(j["wa"])), esc(rate_txt(j["cov"])),
                     esc(ms_txt(j["p50"])), esc(ms_txt(j["p95"])),
                     esc(usd_txt(j["usd1m"]) if j["family"] == "hosted" else "$0 (local; hardware excluded)"),
                     f"{reps}<br><span class='muted'>acc/rep {rng}</span>"])
    return table(["Judge", "Accuracy (95% CI)", "Wrong automatic (95% CI)", "Coverage (95% CI)",
                  "p50", "p95", "$ / 1M decisions", "Reps (n)"], rows, "sticky1")


def contrast_table(sp: dict | None) -> str:
    if sp is None:
        return ""
    out = ""
    for metric, title in (("correct", "accuracy"), ("automatic_error", "wrong automatic")):
        lst = sp["declared"].get(metric, [])
        rows = []
        for x in lst:
            sig = x.get("p_holm") is not None and x["p_holm"] < ALPHA
            ci = x.get("diff_ci95")
            rows.append([esc(_short(x["a"])), esc(_short(x["b"])), str(x["a_only"]), str(x["b_only"]),
                         f"{100 * x['diff']:+.1f} pp" if x.get("diff") is not None else "n/a",
                         f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]" if ci else "n/a",
                         f"{x['p']:.4f}", f"{x['p_holm']:.4f}", "significant *" if sig else "n.s."])
        out += f"<h4>{esc(title)}: declared contrasts ({esc(sp['name'])})</h4>" + table(
            ["A", "B", "A only", "B only", "diff (A-B)", "bootstrap 95% CI", "p (McNemar)", "p (Holm, declared set)", f"at alpha {ALPHA}"], rows)
    return out


def failure_html(sp: dict | None) -> str:
    if sp is None:
        return ""
    out = ""
    for kind, title in (("failure_classes", "All wrong answers (argmax), mean per repetition"),
                        ("automatic_failure_classes", "Wrong AUTOMATIC decisions only, mean per repetition")):
        cols = [c for c in sp["classes"] if any(c in v for v in sp["fail"][kind].values())]
        mx = max([1e-9] + [v[0] for a in sp["fail"][kind].values() for v in a.values()])
        rows = []
        for a in sp["arms"]:
            cells = [f"<b>{esc(_short(a))}</b>"]
            for c in cols:
                v = sp["fail"][kind][a].get(c)
                if v is None:
                    cells.append("<span class='muted'>n/a</span>")
                else:
                    tip = f"{_short(a)} / {c}: mean {v[0]:.2f} per rep (min {v[1]}, max {v[2]})"
                    cells.append(f"<span class='heat' tabindex='0' data-tip='{esc(tip)}' style='--v:{v[0] / mx:.3f}'>{v[0]:.1f}</span>")
            rows.append(cells)
        out += f"<h4>{esc(title)}</h4>" + table(["Judge"] + cols, rows, "heatt")
    notes = "".join(f"<li><code>{esc(c)}</code>: {esc(CLASS_NOTES.get(c, 'See evals/judge_bench/failure.py.'))}</li>" for c in sp["classes"] if c in CLASS_NOTES)
    return out + f"<ul class='notes'>{notes}</ul>"


def intervention_html(sp: dict | None, label: str) -> str:
    if sp is None:
        return f"<h4>{esc(label)}</h4><p class='pending'>Holdout pending.</p>"
    by_arm = {j["arm"]: j for j in sp["judges"]}
    pair_rows = []
    idx = {a: i for i, a in enumerate(sp["arms"])}
    for a in sp["arms"]:
        j = by_arm[a]
        if not j["base"]:
            continue
        b = by_arm[j["base"]]
        i, k = sorted((idx[a], idx[j["base"]]))
        m = next((x for x in sp["matrix"]["automatic_error"] if x[0] == i and x[1] == k), None)
        pair_rows.append([f"<b>{esc(j['base'])}</b> &rarr; <b>{esc(a.split('+', 1)[1])}</b>",
                          esc(rate_txt(b["wa"])), esc(rate_txt(j["wa"])),
                          esc(rate_txt(b["cov"])), esc(rate_txt(j["cov"])),
                          esc(rate_txt(b["acc"])), esc(rate_txt(j["acc"])),
                          (f"p={m[5]:.4f}, Holm {m[7]:.4f}" if m else "n/a")])
    out = f"<h4>{esc(label)}: arm intervention vs. base</h4>"
    out += table(["Pair", "Wrong-auto base", "Wrong-auto +clause", "Coverage base", "Coverage +clause",
                  "Accuracy base", "Accuracy +clause", "McNemar (wrong auto)"], pair_rows) if pair_rows else \
        "<p class='muted'>No <code>base+intervention</code> arms in this split.</p>"
    vrows = []
    for a in sp["arms"]:
        cells = [f"<b>{esc(_short(a))}</b>"]
        for v in sp["variants"]:
            m = v["arms"][a]
            cells.append(f"{esc(rate_txt(m['wa'], 1))}<br><span class='muted'>cov {pct(m['cov']['rate'])}, acc {pct(m['acc']['rate'])}</span>")
        vrows.append(cells)
    heads = ["Judge"] + [v["name"] + ("" if v["in_summary"] else " (recomputed from rows)") for v in sp["variants"]]
    out += f"<h4>{esc(label)}: policy modifiers vs. bundle-read-shortcut: wrong-automatic (coverage and accuracy below)</h4>" + table(heads, vrows)
    return out


def latency_html(lat: dict | None) -> str:
    if not lat:
        return "<p class='pending'>latency/latency_summary.json not found.</p>"
    srows = [[esc(s["key"]), esc(FAMILY_LABEL[s["family"]]), esc(ms_txt(s["wall_p50"])), esc(ms_txt(s["wall_p95"])),
              esc("; ".join(f"{n} {v:.1f} ms" for n, v in s["segments"])), str(s["n"])] for s in lat["stack"]]
    out = "<h4>Anatomy of one call (median of each component)</h4>" + table(
        ["Endpoint|mode", "Family", "wall p50", "wall p95", "components (p50)", "n"], srows)
    crows = [[esc(c["key"]), esc(ms_txt(c["first_ms"])), esc(ms_txt(c["warm_p50_ms"])),
              "n/a" if c["ratio"] is None else f"{c['ratio']:.1f}x", esc(ms_txt(c["load_first_ms"])), str(c["n"])] for c in lat["cold"]]
    out += "<h4>Cold start (model unloaded before call 0)</h4>" + table(
        ["Endpoint", "first call", "calls 1+ (p50)", "first / warm", "load_duration (first)", "calls"], crows)
    rrows = []
    for host, e in sorted(lat["rtt"].items()):
        rrows.append([esc(host), esc(ms_txt((e.get("tcp_rtt_ms") or {}).get("p50"))), esc(ms_txt((e.get("tls_ms") or {}).get("p50"))),
                      esc(ms_txt((e.get("ttfb_after_tls_ms") or {}).get("p50"))), esc(ms_txt((e.get("ttfb_after_tls_ms") or {}).get("p95")))])
    if rrows:
        out += "<h4>Network round trip to each API host</h4>" + table(["Host", "TCP RTT p50", "TLS p50", "TTFB after TLS p50", "TTFB after TLS p95"], rrows)
    return out


def repro_html(splits: dict, root: Path, lat: dict | None) -> str:
    parts = []
    for name, sp in splits.items():
        if sp is None:
            parts.append(f"<h4>{esc(name)}</h4><p class='pending'>Holdout pending: no manifest, requests or summary exist yet.</p>")
            continue
        ref = sp["ref"]
        run = sp["run"]
        hashes = table(["File", "sha256"], [[f"<code>{name}/manifest.json</code>", f"<code>{esc(ref['manifest_sha'])}</code>"],
                                            [f"<code>{name}/requests.jsonl</code> ({ref['rows']} rows)", f"<code>{esc(ref['requests_sha'])}</code>"],
                                            [f"<code>{name}/summary.json</code>", f"<code>{esc(ref['summary_sha'])}</code>"]])
        models = table(["Arm", "Model id(s) seen in request rows", "Adapter flags"],
                       [[esc(_short(j["arm"])), "<code>" + esc(", ".join(j["models"]) or "n/a") + "</code>",
                         esc(", ".join(f"{k}={v}" for k, v in sorted(j["flags"].items())))] for j in sp["judges"]])
        run_html = ""
        if run:
            argv = run.get("argv")
            rest = {k: v for k, v in run.items() if k != "argv"}
            run_html = _kv_html(rest) + (f"<h5>Exact command</h5><pre>{esc(_fmt_cmd(argv))}</pre>" if argv is not None else "")
        else:
            run_html = "<p class='muted'>run.json not found for this split: git SHA, host load, Ollama version and command are not recorded.</p>"
        prices = sp.get("prices")
        price_html = ""
        if prices:
            price_html = "<h5>Prices used (USD per million tokens: input, output; manifest)</h5>" + table(
                ["Price key", "input", "output"], [[esc(k), esc(v[0]), esc(v[1])] for k, v in sorted(prices.items())])
        parts.append(f"<h4>{esc(name)} split</h4>{run_html}{price_html}<h5>Manifest and log hashes</h5>{hashes}<h5>Models</h5>{models}")
    probe = None
    for sp in splits.values():
        if sp and sp["run"] and sp["run"].get("openai_decisions_probe") is not None:
            probe = sp["run"]["openai_decisions_probe"]
            break
    parts.append("<h4>OpenAI Decisions API</h4><p>Probe status recorded in run.json: " +
                 (f"<code>{esc(json.dumps(probe, sort_keys=True))}</code>" if probe is not None else "<span class='muted'>not recorded</span>") +
                 ". No Decisions-API results are claimed anywhere in this report; hosted OpenAI arms use the chat endpoint.</p>")
    if lat:
        parts.append("<h4>Latency run</h4>" + (_kv_html({"spend_usd": lat["spend"], "errors": lat["errors"],
                                                          "percentiles": lat.get("percentiles")})))
    return "".join(parts)


def changes_html(changes) -> str:
    if not changes:
        return "<p class='pending'>changes.json not found; no first-pass vs. validated comparison is recorded.</p>"
    rows = []
    for c in changes:
        v = str(c.get("verdict", ""))
        rows.append([esc(c.get("claim")), esc(c.get("first_pass")), esc(c.get("validated")),
                     f"<span class='verdict v-{esc(v)}'>{esc(v)}</span>", esc(c.get("evidence"))])
    return table(["Claim", "First pass", "Validated", "Verdict", "Evidence"], rows, "wrap")


def limits_html(splits: dict, audit, lat) -> str:
    items = []
    for name, sp in splits.items():
        if sp is None:
            items.append(f"<li><b>{esc(name)}:</b> pending; nothing on this page is a holdout result until it exists. "
                         "Tuned or debugged quantities must not be read off dev.</li>")
            continue
        ref = sp["ref"]
        reps = sorted({r for j in sp["judges"] for r in j["reps"]})
        sc = ", ".join(f"{k}: {v}" for k, v in ref["n_by_screen"].items())
        kd = ", ".join(f"{k}: {v}" for k, v in ref["n_by_kind"].items())
        items.append(f"<li><b>{esc(name)}:</b> {ref['n_cases']} cases ({esc(kd)}; screens {esc(sc)}), repetitions "
                     f"{esc(', '.join(map(str, reps)))}. With n={ref['n_cases']}, a single wrong case moves a rate by about "
                     f"{100 / ref['n_cases']:.1f} points and Wilson intervals are wide; differences without a marked significant "
                     f"cell should be read as unresolved, not as ties.</li>")
        sr = [j["short"] for j in sp["judges"] if j["flags"].get("self_reported_probabilities")]
        if sr:
            items.append(f"<li><b>{esc(name)}, self-reported probabilities:</b> {esc(', '.join(sr))} state their own probabilities in text; "
                         "they are not model logits, so a cutoff on them is a different (less calibrated) instrument than on the local judges.</li>")
        nc = [j["short"] for j in sp["judges"] if j["flags"].get("order_flip_comparable") is False]
        if nc:
            items.append(f"<li><b>{esc(name)}, option order:</b> {esc(', '.join(nc))} average both option orders internally, so their order-flip counts are not comparable.</li>")
        items.append(f"<li><b>{esc(name)}, statistics:</b> accuracy, coverage and wrong-automatic use the per-case majority over repetitions "
                     "(order 0); contrasts are exact McNemar on those majorities. The explorer and calculator use every repetition of order 0.</li>")
    if audit:
        items.append("<li><b>Labels:</b> " + esc(audit.get("note", "")) + "</li>")
        for k in ("dev", "holdout"):
            sec = audit.get(k) or {}
            if sec.get("reviewers"):
                rv = "; ".join(f"{a}: {b}" for a, b in sorted(sec["reviewers"].items()))
                ag = sec.get("A_vs_frozen") or {}
                items.append(f"<li><b>{k} label audit:</b> reviewers &mdash; {esc(rv)}; reviewer A vs frozen label agreement "
                             f"{pct(ag.get('agreement'))} (kappa {ag.get('kappa')}) over {ag.get('n')} cases.</li>")
    else:
        items.append("<li><b>Labels:</b> label-audit/agreement.json not found; label quality is unaudited.</li>")
    if lat:
        items.append("<li><b>Local latency depends on host load:</b> models resident in Ollama at the end of the local phase were "
                     f"{esc(', '.join(lat['resident_models']) or 'not recorded')}; other processes on the machine can add tail latency. "
                     "Hosted latency includes the network path from this machine and provider-side queueing at the time of the run.</li>")
    items.append("<li><b>Cost:</b> hosted prices come from the manifest; local judges show $0 because hardware, power and "
                 "operations are not modelled.</li>")
    return "<ul class='notes'>" + "".join(items) + "</ul>"


# ----------------------------------------------------------------------------- assembly
def build(root: Path) -> str:
    root = Path(root)
    dev = load_split(root / "dev", "dev")
    hold = load_split(root / "holdout", "holdout")
    if dev is None:
        raise SystemExit(f"{root}/dev must contain manifest.json and summary.json")
    splits = {"dev": dev, "holdout": hold}
    lat = build_latency(root)
    audit = _read_json(root / "label-audit" / "agreement.json")
    changes = _read_json(root / "changes.json")

    read = scoring.POLICIES["bundle-read-shortcut"]
    cua = scoring.POLICIES["bundle-cua"]
    to_s = read["timeout_ms"] / 1000
    pol_js = {"read": {"label": f"bundle read-shortcut ({read['min_p']:.2f}, margin {read['min_margin']:.2f})",
                       "min_p": read["min_p"], "margin": read["min_margin"], "timeout": read["timeout_ms"]},
              "cua": {"label": f"bundle CUA ({cua['min_p']:.2f})", "min_p": cua["min_p"], "margin": None, "timeout": cua["timeout_ms"]}}
    mult = None
    for j in dev["judges"]:
        if j["usd1m_priority"] and j["usd1m"]:
            mult = j["usd1m_priority"] / j["usd1m"]
            break

    data = {"schema": SCHEMA, "default_split": "dev", "grid": GRID, "policies": pol_js, "priority_multiplier": mult,
            "alpha": ALPHA, "families": FAMILY_LABEL, "colors": pal.FAMILIES, "state_colors": pal.STATES,
            "splits": {k: ({kk: vv for kk, vv in v.items() if kk not in ("run", "ref")} if v else None) for k, v in splits.items()},
            "latency": lat}

    # server-side static tables
    safe_tables = ""
    for name, sp in splits.items():
        if sp is None:
            safe_tables += f"<h4>{esc(name)}</h4><p class='pending'>Holdout pending.</p>"
            continue
        rows = []
        for a in sp["arms"]:
            s = sp["safe"][a]
            cells = [f"<b>{esc(_short(a))}</b>"]
            for cell in [s["pooled"]] + [s["reps"][k] for k in sorted(s["reps"], key=int)]:
                cells.append("none" if not cell else f"{cell['cutoff']:.2f} &rarr; cov {pct(cell['coverage'])}")
            rows.append(cells)
        reps = sorted({k for a in sp["arms"] for k in sp["safe"][a]["reps"]}, key=int)
        safe_tables += f"<h4>{esc(name)}: lowest cutoff with zero wrong automatic decisions (0.01 grid)</h4>" + table(
            ["Judge", "Pooled reps"] + [f"rep {k}" for k in reps], rows)

    n_dev = dev["ref"]["n_cases"]
    hl = ""
    for name, sp in splits.items():
        hl += f"<h3>{esc(name)}</h3>" + headline_table(sp)

    body = TEMPLATE
    repl = {
        "@@POLICY_READ@@": f"{read['min_p']:.2f}", "@@MARGIN@@": f"{read['min_margin']:.2f}", "@@TIMEOUT_S@@": f"{to_s:g}",
        "@@CUA_P@@": f"{cua['min_p']:.2f}", "@@HEADLINE_TABLES@@": hl,
        "@@CONTRAST_TABLES@@": contrast_table(dev) + (contrast_table(hold) if hold else "<p class='pending'>Holdout pending.</p>"),
        "@@SAFE_TABLES@@": safe_tables,
        "@@FAILURE_TABLES@@": failure_html(dev) + "<h3>holdout</h3>" + (failure_html(hold) if hold else "<p class='pending'>Holdout pending.</p>"),
        "@@INTERVENTION_TABLES@@": intervention_html(dev, "dev (screen)") + intervention_html(hold, "holdout"),
        "@@LATENCY_TABLES@@": latency_html(lat),
        "@@LATENCY_FINDINGS@@": _latency_findings(lat),
        "@@REPRO@@": repro_html(splits, root, lat),
        "@@CHANGES@@": changes_html(changes),
        "@@LIMITS@@": limits_html(splits, audit, lat),
        "@@N_DEV@@": str(n_dev), "@@POLICY_NAME@@": esc(dev["primary_policy"]),
        "@@CSS@@": _css(), "@@JS@@": JS,
        "@@DATA@@": json.dumps(data, sort_keys=True, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--"),
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    return body


def _latency_findings(lat: dict | None) -> str:
    if not lat:
        return ""
    parts = []
    if lat["nonce_phases"]:
        parts.append("<p><b>Prompt-cache control.</b> Phases recorded with a per-request nonce (so identical prompts could not be "
                     f"served from a provider prompt cache): <code>{esc(', '.join(lat['nonce_phases']))}</code>.</p>")
    for f in lat["findings"]:
        parts.append(f"<p><b>Prompt-cache note from the latency run:</b> <code>{esc(f)}</code></p>")
    return "".join(parts)


def _css() -> str:
    fam = pal.FAMILIES
    return (CSS.replace("@@HOSTED@@", fam["hosted"]).replace("@@SYSTEM_ONE@@", fam["system_one"])
            .replace("@@GENERIC@@", fam["generic"]).replace("@@NEUTRAL@@", pal.NEUTRAL))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    root = Path(argv[0])
    out = root / "index.html"
    out.write_text(build(root), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")
    return 0


# ----------------------------------------------------------------------------- assets
CSS = r"""
:root { color-scheme: light dark;
  --bg:#F4F3F0; --card:#FCFCFB; --rule:#E2E0DA; --grid:#ECEBE7; --ink:#111110; --ink2:#4F4E4A; --ink3:#6B6A65;
  --hosted:@@HOSTED@@; --sysone:@@SYSTEM_ONE@@; --generic:@@GENERIC@@; --neutral:@@NEUTRAL@@;
  --shadow:0 1px 2px rgba(0,0,0,.06); --focus:#111110; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#121211; --card:#1A1A19; --rule:#302F2D; --grid:#262624; --ink:#F4F3F0; --ink2:#C4C3BA; --ink3:#9A9990; --shadow:none; --focus:#F4F3F0; } }
:root[data-theme="dark"] { color-scheme: dark;
  --bg:#121211; --card:#1A1A19; --rule:#302F2D; --grid:#262624; --ink:#F4F3F0; --ink2:#C4C3BA; --ink3:#9A9990; --shadow:none; --focus:#F4F3F0; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif; }
header.top { position:sticky; top:0; z-index:20; background:var(--card); border-bottom:1px solid var(--rule); }
.bar { max-width:1180px; margin:0 auto; padding:8px 16px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.bar .title { font-weight:650; margin-right:auto; }
.bar nav { display:flex; gap:4px 12px; flex-wrap:wrap; font-size:12.5px; }
.bar nav a { color:var(--ink2); text-decoration:none; } .bar nav a:hover { text-decoration:underline; }
button, select, input { font:inherit; color:var(--ink); background:var(--card); border:1px solid var(--rule); border-radius:8px; padding:5px 10px; }
button { cursor:pointer; } button:disabled { opacity:.5; cursor:not-allowed; }
button[aria-pressed="true"] { border-color:var(--ink); box-shadow:inset 0 0 0 1px var(--ink); }
:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }
main { max-width:1180px; margin:0 auto; padding:8px 16px 64px; }
section.card { background:var(--card); border:1px solid var(--rule); border-radius:14px; padding:18px 20px; margin:16px 0; box-shadow:var(--shadow); }
h1 { font-size:24px; margin:20px 0 4px; } h2 { font-size:19px; margin:0 0 4px; } h3 { font-size:15px; margin:16px 0 6px; color:var(--ink2); }
h4 { font-size:14px; margin:16px 0 6px; } h5 { font-size:13px; margin:12px 0 4px; color:var(--ink2); }
.sub, .muted { color:var(--ink2); } .muted { font-size:.92em; color:var(--ink3); } .sub { max-width:900px; margin:0 0 10px; }
.pending { color:var(--ink2); border:1px dashed var(--rule); border-radius:8px; padding:8px 12px; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr)); gap:16px; }
.explain p, .explain li { max-width:900px; }
.callout { border-left:4px solid var(--sysone); background:color-mix(in srgb, var(--sysone) 8%, transparent); padding:8px 12px; border-radius:0 8px 8px 0; margin:10px 0; }
.chart { width:100%; position:relative; min-height:120px; }
.chart svg { display:block; max-width:100%; overflow:visible; }
svg text { fill:var(--ink2); font:11px system-ui,-apple-system,"Segoe UI",sans-serif; }
svg text.lbl { fill:var(--ink); font-size:11.5px; font-weight:560; }
svg text.axt { fill:var(--ink2); font-size:11.5px; }
svg .gl { stroke:var(--grid); } svg .ax { stroke:var(--rule); }
svg .mark { cursor:default; } svg .mark:hover, svg .mark:focus { stroke:var(--ink); stroke-width:2; outline:none; }
.fam-hosted { --c:var(--hosted); } .fam-system_one { --c:var(--sysone); } .fam-generic { --c:var(--generic); }
.swatch { display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:5px; vertical-align:-1px; background:var(--c, var(--neutral)); }
.legend { display:flex; gap:6px 16px; flex-wrap:wrap; font-size:12.5px; color:var(--ink2); margin:4px 0 8px; }
.scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; margin:6px 0; }
table.data { border-collapse:collapse; width:100%; font-size:13px; }
table.data th, table.data td { padding:6px 9px; border-bottom:1px solid var(--rule); text-align:left; vertical-align:top; white-space:nowrap; }
table.data.wrap td { white-space:normal; min-width:150px; }
table.data thead th { color:var(--ink2); font-weight:600; background:var(--card); position:sticky; top:0; }
table.data td:not(:first-child) { text-align:right; } table.data.wrap td { text-align:left; }
table.kv { border-collapse:collapse; font-size:13px; } table.kv th, table.kv td { padding:2px 10px 2px 0; text-align:left; vertical-align:top; border:0; }
pre, code { font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace; } pre { background:var(--bg); padding:10px; border-radius:8px; overflow-x:auto; white-space:pre-wrap; word-break:break-all; }
code { word-break:break-all; }
details.dt { margin-top:8px; } details.dt summary { cursor:pointer; color:var(--ink2); font-size:13px; }
.heat { display:inline-block; min-width:2.4em; padding:1px 6px; border-radius:4px; text-align:center; background:color-mix(in srgb, var(--sysone) calc(var(--v) * 80%), transparent); }
.verdict { font-weight:600; padding:1px 8px; border-radius:10px; border:1px solid var(--rule); font-size:12px; }
.v-confirmed::before { content:"\2713 "; } .v-refuted::before { content:"\2717 "; } .v-revised::before { content:"\21BB "; } .v-new::before { content:"+ "; }
.v-refuted { border-color:var(--sysone); } .v-confirmed { border-color:var(--hosted); }
.ctrl { display:flex; gap:12px 18px; flex-wrap:wrap; align-items:end; margin:8px 0 12px; }
.ctrl label { display:flex; flex-direction:column; gap:3px; font-size:12.5px; color:var(--ink2); }
.ctrl input[type=range] { width:min(340px,80vw); padding:0; }
.big { font-size:22px; font-weight:650; color:var(--ink); }
.mx { border-collapse:separate; border-spacing:2px; font-size:12px; }
.mx th { font-weight:560; color:var(--ink2); padding:2px 4px; text-align:right; white-space:nowrap; }
.mx thead th { text-align:center; vertical-align:bottom; height:118px; } .mx thead th > span { display:inline-block; writing-mode:vertical-rl; transform:rotate(180deg); }
.mx td { width:44px; min-width:44px; height:30px; text-align:center; border-radius:4px; padding:0; font-variant-numeric:tabular-nums; }
.mx td.sig { font-weight:700; } .mx td.decl { outline:2px dashed var(--ink); outline-offset:-2px; }
.mx td.dia { background:transparent; }
.cm { border-collapse:separate; border-spacing:2px; font-size:12px; }
.cm th { font-weight:500; color:var(--ink2); text-align:left; padding:1px 6px; white-space:nowrap; }
.cm thead th { height:112px; vertical-align:bottom; text-align:center; position:sticky; top:0; background:var(--card); }
.cm thead th > span { display:inline-block; writing-mode:vertical-rl; transform:rotate(180deg); }
.cm td { padding:0; }
.cm button { width:26px; height:24px; padding:0; border-radius:4px; border:1px solid transparent; font-size:13px; line-height:1; color:#fff; }
.cm button.correct { background:var(--hosted); } .cm button.wrong { background:var(--sysone); } .cm button.fallback { background:var(--neutral); color:#111; }
.cm button.mixed { box-shadow:inset 0 0 0 2px var(--card), inset 0 0 0 3px var(--ink); }
.cm button.sel { outline:2px solid var(--ink); outline-offset:1px; }
.cmwrap { max-height:560px; overflow:auto; border:1px solid var(--rule); border-radius:8px; }
#dpanel { border:1px solid var(--rule); border-radius:10px; padding:10px 14px; margin:8px 0; background:var(--bg); }
#dpanel h4 { margin-top:6px; } #dpanel .opt.exp { font-weight:650; } #dpanel .opt.exp::after { content:"  (frozen label)"; font-weight:400; color:var(--ink2); }
#dpanel tr.bad td { color:var(--sysone); font-weight:600; }
#dpanel pre.st { white-space:pre-wrap; }
.tip { position:fixed; z-index:50; pointer-events:none; background:var(--card); color:var(--ink); border:1px solid var(--ink3); border-radius:8px;
  padding:6px 9px; font-size:12px; max-width:min(340px,88vw); white-space:pre-line; box-shadow:0 4px 14px rgba(0,0,0,.25); display:none; }
.notes li { margin:4px 0; max-width:920px; }
.inbar { display:inline-block; height:9px; background:var(--neutral); border-radius:2px; vertical-align:middle; margin-right:5px; }
footer { max-width:1180px; margin:0 auto; padding:0 16px 40px; color:var(--ink3); font-size:12px; }
@media (max-width: 640px) {
  body { font-size:14px; } main { padding:4px 10px 48px; } section.card { padding:14px 12px; border-radius:10px; margin:10px 0; }
  .bar nav { display:none; } h1 { font-size:20px; }
  .mx td { width:36px; min-width:36px; }
}
"""

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Decision-judge benchmark report</title>
<style>@@CSS@@</style>
</head>
<body>
<header class="top"><div class="bar">
  <span class="title">Decision-judge benchmark</span>
  <nav aria-label="Sections"><a href="#explain">Explainer</a><a href="#headline">Headline</a><a href="#scatter">Trade-offs</a><a href="#pairs">Pairwise</a><a href="#calc">Cost</a><a href="#explorer">Threshold</a><a href="#drill">Cases</a><a href="#failures">Failures</a><a href="#latency">Latency</a><a href="#interv">Interventions</a><a href="#repro">Repro</a><a href="#changes">Changes</a><a href="#limits">Limits</a></nav>
  <span role="group" aria-label="Data split for interactive sections"><button id="sp-dev" aria-pressed="true">Dev</button> <button id="sp-holdout" aria-pressed="false">Holdout</button></span>
  <button id="theme" aria-label="Toggle light and dark theme">Theme</button>
</div></header>
<main>
<h1>Which fast model can make an agent's small decisions?</h1>
<p class="sub">Every number on this page is computed from the committed evidence files by <code>evals/judge_bench/report.py</code>. Hover, focus or tap any mark for exact values; every chart has its numbers in a table under it. The Dev / Holdout switch at the top drives the interactive sections; the tables show both.</p>

<section class="card explain" id="explain">
<h2>1. What is being measured</h2>
<p><b>A judge</b> is a small, fast model that answers one tightly structured question so the agent can skip slow reasoning. It is shown a task and what is on screen (or a search query and a code snippet), plus a few prepared options, and returns a probability for each option. One of the options is always <code>reason</code>, meaning "I am not sure, fall back to ordinary slow reasoning". Yes/no questions ("does this code do what was asked?") return one probability and have no <code>reason</code> option.</p>
<p><b>An automatic decision</b> is when the bundle acts on the judge's answer without slow reasoning. For a choice, that happens only if the top option is not <code>reason</code>, its probability is at least <b>@@POLICY_READ@@</b> with a lead of at least <b>@@MARGIN@@</b> over the runner-up, and the answer arrived within <b>@@TIMEOUT_S@@ s</b>. (The computer-use variant relaxes the probability bar to @@CUA_P@@ and has no margin rule.) <b>Yes/no answers have no abstention in the bundle:</b> they are always acted on unless the call times out.</p>
<div class="callout"><b>Why wrong automatic decisions matter most.</b> When a judge is wrong but confident, the agent acts on it with no second look, for example clicking <em>Buy now</em> when the task never said to buy. A wrong answer that falls back to slow reasoning only costs time. So accuracy alone is the wrong headline: this report leads with the <em>wrong-automatic rate</em> and <em>coverage</em> (the share of decisions that skip slow reasoning).</div>
<h3>How to read each chart</h3>
<ul class="notes">
<li><b>Bars and points with whiskers:</b> the whisker is a 95% Wilson confidence interval. If two whiskers overlap a lot, do not read a ranking into it.</li>
<li><b>Trade-off scatters:</b> the best corner is high accuracy at low latency (first) and low wrong-automatic at high coverage (second). Colour marks the judge family; every point is labelled directly. Latency uses a log axis.</li>
<li><b>Pairwise matrix:</b> each cell is row minus column in percentage points on per-case majorities. Bold with a star means significant after Holm correction over <em>all</em> pairs; a dashed outline marks a contrast declared in advance.</li>
<li><b>Threshold explorer:</b> moving the slider re-scores every judge at that certainty cutoff. Lines are the coverage-versus-wrong frontier; the dot is where the slider sits.</li>
<li><b>Case matrix:</b> &#10003; = automatic and right, &#10007; = automatic and wrong, &#8631; = fell back to slow reasoning. Click a cell for the whole case.</li>
<li><b>Latency bars:</b> segments add up to the median call; shade shows the component, colour the family.</li>
</ul>
</section>

<section class="card" id="headline">
<h2>2. Headline: per judge</h2>
<p class="sub">Accuracy, wrong-automatic and coverage are per-case majorities over repetitions of the primary policy (<code>@@POLICY_NAME@@</code>); intervals are 95% Wilson. p50/p95 pool every valid request of every repetition and both option orders. Cost per million decisions is the mean billed-token cost at listed prices; local judges list $0 and exclude hardware.</p>
@@HEADLINE_TABLES@@
<h3>Charts (active split: <span class="activesplit"></span>)</h3>
<div class="grid2"><div><h4>Accuracy</h4><div class="chart" id="ch-acc"></div></div><div><h4>Wrong automatic decisions (lower is better)</h4><div class="chart" id="ch-wa"></div></div></div>
<div id="dt-headline"></div>
</section>

<section class="card" id="scatter">
<h2>3. Trade-offs, with uncertainty</h2>
<p class="sub">Accuracy against p95 latency (log axis), and wrong-automatic against coverage. Vertical and horizontal whiskers are 95% Wilson intervals. Active split: <span class="activesplit"></span>.</p>
<div class="legend" id="legend-fam"></div>
<div class="grid2"><div><h4>Accuracy vs p95 latency</h4><div class="chart" id="ch-sc1"></div></div><div><h4>Wrong automatic vs coverage</h4><div class="chart" id="ch-sc2"></div></div></div>
<div id="dt-scatter"></div>
</section>

<section class="card" id="pairs">
<h2>Pairwise judge comparison</h2>
<p class="sub">Exact McNemar test on per-case majorities, Holm-adjusted across every pair in the matrix. Toggle the metric. Active split: <span class="activesplit"></span>.</p>
<div class="ctrl"><span role="group" aria-label="Matrix metric"><button id="mx-acc" aria-pressed="true">Accuracy</button> <button id="mx-wa" aria-pressed="false">Wrong automatic</button></span></div>
<div class="legend"><span><span class="swatch" style="--c:var(--hosted)"></span>row better</span><span><span class="swatch" style="--c:var(--sysone)"></span>row worse</span><span>&#9733; significant after Holm</span><span>dashed outline = declared contrast</span></div>
<div class="scroll"><div id="ch-mx"></div></div>
<h4>Declared contrasts (forest plot: difference with bootstrap 95% CI)</h4>
<div class="chart" id="ch-forest"></div>
<div id="dt-pairs"></div>
<details class="dt"><summary>Declared contrasts from summary.json (both splits)</summary>@@CONTRAST_TABLES@@</details>
</section>

<section class="card" id="calc">
<h2>4. Cost at scale</h2>
<p class="sub">Expected monthly bill and the number of wrong automatic actions per month if the benchmark's mix of decisions matched your traffic. <b>Local judges show $0 API cost and exclude hardware, power and operations.</b> Active split: <span class="activesplit"></span>.</p>
<div class="ctrl">
<label>Decisions per day<input id="c-vol" type="number" min="0" step="1000" value="100000"></label>
<label>Cutoff<select id="c-pol"></select></label>
<label id="c-custom-wrap">Custom cutoff<input id="c-custom" type="number" min="0.5" max="0.99" step="0.01" value="0.90"></label>
<label>OpenAI tier<select id="c-tier"><option value="standard">standard</option><option value="priority">priority (2x price)</option></select></label>
</div>
<div class="scroll" id="calc-out"></div>
</section>

<section class="card" id="explorer">
<h2>5. Threshold explorer</h2>
<p class="sub">Raise the cutoff and coverage falls; the question is how fast wrong automatic decisions fall. Order-0 answers, argmax option, <code>reason</code> never automatic, no timeout or margin rule (a pure certainty cutoff). Active split: <span class="activesplit"></span>.</p>
<div class="ctrl"><label>Certainty cutoff: <span class="big" id="th-val"></span><input id="th" type="range" min="0.50" max="0.99" step="0.01" value="0.90"></label></div>
<div class="legend" id="legend-fam2"></div>
<div class="chart" id="ch-front"></div>
<div class="scroll" id="th-table"></div>
<h3>Safe cutoff per judge</h3>
<p class="sub">Lowest cutoff on a 0.01 grid at which that judge made zero wrong automatic decisions, per repetition and pooled over repetitions, with the coverage kept. "none" means even 0.99 still lets a wrong answer through.</p>
@@SAFE_TABLES@@
</section>

<section class="card" id="drill">
<h2>6. Case drill-down</h2>
<p class="sub">Cases &times; judges under the primary policy (majority of repetitions; a ringed cell means repetitions disagreed). Active split: <span class="activesplit"></span>. "All judges wrong" and "only one judge right" consider the base judges (not the +intervention arms) by argmax correctness.</p>
<div class="ctrl">
<label>Task type<select id="f-kind"></select></label><label>Screen<select id="f-screen"></select></label><label>Failure class<select id="f-class"></select></label>
<label><span><input type="checkbox" id="f-allwrong"> all judges wrong</span></label><label><span><input type="checkbox" id="f-oneright"> only one judge right</span></label>
<span class="muted" id="f-count"></span>
</div>
<div class="legend"><span><span class="swatch" style="--c:var(--hosted)"></span>&#10003; automatic, right</span><span><span class="swatch" style="--c:var(--sysone)"></span>&#10007; automatic, wrong</span><span><span class="swatch" style="--c:var(--neutral)"></span>&#8631; fell back to reasoning</span></div>
<div id="dpanel"><span class="muted">Click any cell to see the task, options, frozen label, label-audit notes and every judge's answer.</span></div>
<div class="cmwrap"><div id="ch-cm"></div></div>
<div id="dt-cm"></div>
</section>

<section class="card" id="failures">
<h2>7. Failure modes</h2>
<p class="sub">How each judge is wrong, by class, from summary.json (mean per repetition). Second table counts only the wrong answers the bundle would have acted on.</p>
@@FAILURE_TABLES@@
</section>

<section class="card" id="latency">
<h2>8. Latency anatomy</h2>
<p class="sub">Where the time goes in one call, from the dedicated latency run. Cloud calls split into network, provider server time and client time; local Ollama calls into model load, prompt prefill, decode and overhead. Connection reused (keepalive) unless a row says fresh. Components are medians and need not add exactly to the median wall time; the residual is shown as client/overhead.</p>
@@LATENCY_FINDINGS@@
<div class="legend" id="legend-seg"></div>
<div class="chart" id="ch-lat"></div>
<h4>Concurrency: p50 latency vs. requests in flight</h4>
<div class="legend" id="legend-fam3"></div>
<div class="chart" id="ch-conc"></div>
<details class="dt" open><summary>Data tables for the latency charts, cold starts and network round trips</summary>@@LATENCY_TABLES@@</details>
</section>

<section class="card" id="interv">
<h2>9. Interventions</h2>
<p class="sub">I1: adding a side-effect clause to the instructions (arm vs. its base). Policy modifiers: <code>+host-guard</code> forces fallback when the chosen option names a side effect; <code>+noul-gate</code> makes yes/no answers automatic only at the policy's probability bar. The dev split was used to choose these, so its numbers are a <b>screen</b>, not confirmation; only holdout confirms.</p>
<div class="grid2"><div><h4>Wrong automatic, base vs. +clause (active split: <span class="activesplit"></span>)</h4><div class="chart" id="ch-iv-wa"></div></div><div><h4>Coverage, base vs. +clause</h4><div class="chart" id="ch-iv-cov"></div></div></div>
<div id="dt-iv"></div>
<details class="dt" open><summary>Intervention tables (both splits)</summary>@@INTERVENTION_TABLES@@</details>
</section>

<section class="card" id="repro">
<h2>10. Reproducibility</h2>
@@REPRO@@
</section>

<section class="card" id="changes">
<h2>11. Change history: first pass vs. validated</h2>
@@CHANGES@@
</section>

<section class="card" id="limits">
<h2>12. Evidence limits</h2>
@@LIMITS@@
</section>
</main>
<footer>Self-contained page: inline CSS, JS and SVG; no network access. Palette validated by <code>evals/judge_bench/palette_check.py</code>.</footer>
<div class="tip" id="tip" role="tooltip"></div>
<script id="data" type="application/json">@@DATA@@</script>
<script>@@JS@@</script>
</body>
</html>
"""

JS = r"""
(function () {
'use strict';
const D = JSON.parse(document.getElementById('data').textContent);
const SVGNS = 'http' + '://www.w3.org/2000/svg';   // XML namespace identifier, not a network resource
const FAMCOL = {hosted: 'var(--hosted)', system_one: 'var(--sysone)', generic: 'var(--generic)'};
const $ = (s, r) => (r || document).querySelector(s);
let split = 'dev', mxMetric = 'correct';

/* ---------- tiny DOM helpers ---------- */
function setAttrs(e, a) {
  for (const k in a || {}) {
    const v = a[k];
    if (v == null || v === false) continue;
    if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
}
function add(e, kids) { for (const k of kids.flat()) { if (k == null || k === false) continue; e.append(k.nodeType ? k : document.createTextNode(String(k))); } }
function h(tag, a, ...kids) { const e = document.createElement(tag); setAttrs(e, a); add(e, kids); return e; }
function sv(tag, a, ...kids) { const e = document.createElementNS(SVGNS, tag); setAttrs(e, a); add(e, kids); return e; }
function tipped(e, text, focusable) { e.setAttribute('data-tip', text); if (focusable !== false) e.setAttribute('tabindex', '0'); return e; }
const S = () => D.splits[split];
const pct = (x, d) => x == null ? 'n/a' : (100 * x).toFixed(d == null ? 1 : d) + '%';
const fnum = (x, d) => x == null ? 'n/a' : Number(x).toLocaleString('en-US', {maximumFractionDigits: d == null ? 0 : d, minimumFractionDigits: d == null ? 0 : d});
const fms = x => x == null ? 'n/a' : (x < 10000 ? Math.round(x) + ' ms' : (x / 1000).toFixed(x % 1000 ? 1 : 0) + ' s');
const fit = (t, px) => { const n = Math.max(3, Math.floor(px / 6.9)); return t.length > n ? t.slice(0, n - 1) + '\u2026' : t; };
const usd = x => x == null ? 'n/a' : (x === 0 ? '$0' : '$' + fnum(x, x < 10 ? 2 : 0));
const ciTxt = (o) => o && o.ci ? '95% CI ' + pct(o.ci[0]) + ' to ' + pct(o.ci[1]) : '';
const rateTxt = (o) => o.k + '/' + o.n + ' = ' + pct(o.rate) + ' (' + ciTxt(o) + ')';
const cw = el => Math.max(300, Math.floor(el.clientWidth || (el.parentNode && el.parentNode.clientWidth) || 600));

/* ---------- tooltip ---------- */
const tip = $('#tip');
function showTip(t, x, y) {
  tip.textContent = t; tip.style.display = 'block';
  const r = tip.getBoundingClientRect();
  let L = x + 12, T = y + 14;
  if (L + r.width > innerWidth - 6) L = x - r.width - 12;
  if (L < 6) L = 6;
  if (T + r.height > innerHeight - 6) T = y - r.height - 12;
  if (T < 6) T = 6;
  tip.style.left = L + 'px'; tip.style.top = T + 'px';
}
function onPoint(e) {
  const t = e.target.closest && e.target.closest('[data-tip]');
  if (t) showTip(t.getAttribute('data-tip'), e.clientX, e.clientY); else tip.style.display = 'none';
}
document.addEventListener('pointermove', onPoint);
document.addEventListener('pointerdown', onPoint);
document.addEventListener('focusin', e => {
  const t = e.target.closest && e.target.closest('[data-tip]');
  if (t) { const r = t.getBoundingClientRect(); showTip(t.getAttribute('data-tip'), r.left + r.width / 2, r.bottom); }
});
document.addEventListener('focusout', () => { tip.style.display = 'none'; });
document.addEventListener('keydown', e => { if (e.key === 'Escape') tip.style.display = 'none'; });

/* ---------- scales, ticks ---------- */
function niceTicks(lo, hi, n) {
  const span = hi - lo, raw = span / (n || 5), mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || mag * 10;
  const out = []; for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) for (const m of [1, 2, 5]) { const v = m * Math.pow(10, e); if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
  return out;
}
const rectsOverlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/* ---------- direct labels with simple collision nudging ---------- */
function placeLabels(items, box, obstacles) {
  // items: {x,y,text}; tries a ring of offsets, greedy; returns [{x,y,anchor,leader}]
  const placed = [], out = [];
  const offs = (w) => { const dys = [4], o = []; for (let k = 1; k <= 10; k++) { dys.push(4 - 13 * k, 4 + 13 * k); }
    for (const dy of dys) { o.push([9, dy]); o.push([-9 - w, dy]); }
    o.push([-w / 2, -12], [-w / 2, 24]); return o; };
  for (const it of items) {
    const w = it.text.length * 6.7 + 4, hgt = 13;
    let best = null, bestScore = 1e9;
    for (const [dx, dy] of offs(w)) {
      const r = {x: it.x + dx, y: it.y + dy - 10, w, h: hgt};
      let score = 0;
      if (r.x < box.x0 + 2 || r.x + r.w > box.x1 - 4 || r.y < box.y0 || r.y + r.h > box.y1) score += 1000;
      score += Math.abs(dy - 4) * 0.01;
      for (const p of placed) if (rectsOverlap(r, p)) score += 100;
      for (const o of obstacles) if (rectsOverlap(r, o)) score += 30;
      if (score < bestScore) { bestScore = score; best = {r, dx, dy}; }
      if (score === 0) break;
    }
    placed.push(best.r);
    const far = Math.hypot(best.dx > 0 ? best.dx - 9 : best.dx + 9 + w, best.dy - 4) > 6;
    out.push({x: best.r.x, y: best.r.y + 10, text: it.text, leader: far, px: it.x, py: it.y, r: best.r});
  }
  return out;
}
function nudge1d(ys, gap, lo, hi) {
  const idx = ys.map((y, i) => i).sort((a, b) => ys[a] - ys[b]);
  const out = ys.slice();
  let prev = -1e9;
  for (const i of idx) { out[i] = Math.max(ys[i], prev + gap); prev = out[i]; }
  const over = out[idx[idx.length - 1]] - hi;
  if (over > 0) { let nxt = hi + 1e9; for (let k = idx.length - 1; k >= 0; k--) { const i = idx[k]; out[i] = Math.min(out[i], nxt - gap, hi); nxt = out[i]; } }
  return out.map(v => Math.max(lo, v));
}

/* ---------- generic chart pieces ---------- */
function axisFrame(svg, o) {
  const {m, W, H, X, Y, xticks, yticks, xfmt, yfmt, xtitle, ytitle} = o;
  for (const t of yticks) { const y = Y(t); svg.append(sv('line', {x1: m.l, x2: W - m.r, y1: y, y2: y, class: 'gl'}), sv('text', {x: m.l - 6, y: y + 3.5, 'text-anchor': 'end', text: yfmt(t)})); }
  let lastRight = -1e9;
  for (const t of xticks) {
    const x = X(t), txt = xfmt(t), half = txt.length * 3.1, anchor = x + half > W - 2 ? 'end' : 'middle';
    svg.append(sv('line', {x1: x, x2: x, y1: m.t, y2: H - m.b, class: 'gl'}));
    const left = anchor === 'end' ? x - 2 * half : x - half;
    if (left > lastRight + 6) { svg.append(sv('text', {x: anchor === 'end' ? x : x, y: H - m.b + 15, 'text-anchor': anchor, text: txt})); lastRight = left + 2 * half; }
  }
  svg.append(sv('line', {x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: 'ax'}), sv('line', {x1: m.l, x2: m.l, y1: m.t, y2: H - m.b, class: 'ax'}));
  svg.append(sv('text', {x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle', class: 'axt', text: xtitle}));
  svg.append(sv('text', {x: 11, y: (m.t + H - m.b) / 2, 'text-anchor': 'middle', class: 'axt', transform: `rotate(-90 11 ${(m.t + H - m.b) / 2})`, text: ytitle}));
}
function whisker(svg, x1, y1, x2, y2, col, tiptext) {
  const cap = 4, vertical = x1 === x2;
  svg.append(sv('line', {x1, y1, x2, y2, stroke: col, 'stroke-width': 1.6, 'stroke-opacity': .7}));
  if (vertical) svg.append(sv('line', {x1: x1 - cap, x2: x1 + cap, y1, y2: y1, stroke: col, 'stroke-width': 1.6, 'stroke-opacity': .7}), sv('line', {x1: x1 - cap, x2: x1 + cap, y1: y2, y2, stroke: col, 'stroke-width': 1.6, 'stroke-opacity': .7}));
  else svg.append(sv('line', {x1, x2: x1, y1: y1 - cap, y2: y1 + cap, stroke: col, 'stroke-width': 1.6, 'stroke-opacity': .7}), sv('line', {x1: x2, x2, y1: y1 - cap, y2: y1 + cap, stroke: col, 'stroke-width': 1.6, 'stroke-opacity': .7}));
  svg.append(tipped(sv('line', {x1, y1, x2, y2, stroke: 'transparent', 'stroke-width': 11}), tiptext, false));
}

function scatter(el, o) {
  el.textContent = '';
  const W = cw(el), H = W < 480 ? 350 : 420, m = {l: 68, r: 14, t: 10, b: 44};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const xs = o.xlog ? Math.log10 : (v => v);
  const x0 = xs(o.xdom[0]), x1 = xs(o.xdom[1]);
  const X = v => m.l + (xs(v) - x0) / (x1 - x0) * iw, Y = v => m.t + ih - (v - o.ydom[0]) / (o.ydom[1] - o.ydom[0]) * ih;
  const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.title});
  axisFrame(svg, {m, W, H, X, Y, xticks: o.xticks, yticks: o.yticks, xfmt: o.xfmt, yfmt: o.yfmt, xtitle: o.xtitle, ytitle: o.ytitle});
  for (const p of o.points) {
    const col = FAMCOL[p.fam];
    if (p.ylo != null) whisker(svg, X(p.x), Y(p.ylo), X(p.x), Y(p.yhi), col, p.tip);
    if (p.xlo != null) whisker(svg, X(p.xlo), Y(p.y), X(p.xhi), Y(p.y), col, p.tip);
  }
  for (const p of o.points) svg.append(tipped(sv('circle', {cx: X(p.x), cy: Y(p.y), r: 5.5, fill: FAMCOL[p.fam], stroke: 'var(--card)', 'stroke-width': 1.5, class: 'mark'}), p.tip));
  const obst = o.points.map(p => ({x: X(p.x) - 7, y: Y(p.y) - 7, w: 14, h: 14}));
  const labs = placeLabels(o.points.map(p => ({x: X(p.x), y: Y(p.y), text: p.label})), {x0: m.l, x1: W, y0: 0, y1: H - m.b + 2}, obst);
  labs.forEach((l, i) => {
    if (l.leader) svg.append(sv('line', {x1: l.px, y1: l.py, x2: Math.min(Math.max(l.px, l.r.x), l.r.x + l.r.w), y2: l.r.y + 6, stroke: 'var(--ink3)', 'stroke-width': .8}));
    svg.append(sv('text', {x: l.x, y: l.y, class: 'lbl', text: l.text}));
  });
  el.append(svg);
}

function bars(el, items, o) {
  el.textContent = '';
  const W = cw(el), rowH = 24, m = {l: Math.min(W * 0.42, 10 + 7 * Math.max(...items.map(i => i.label.length))), r: 92, t: 6, b: 40};
  const H = m.t + m.b + rowH * items.length, iw = W - m.l - m.r;
  const max = o.max || Math.max(...items.map(i => (i.hi != null ? i.hi : i.v)), 0.0001) * 1.05;
  const X = v => m.l + v / max * iw;
  const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.title});
  for (const t of niceTicks(0, max, W < 480 ? 4 : 6)) svg.append(sv('line', {x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: 'gl'}), sv('text', {x: X(t), y: H - m.b + 15, 'text-anchor': 'middle', text: o.fmt(t)}));
  svg.append(sv('text', {x: m.l + iw / 2, y: H - 6, 'text-anchor': 'middle', class: 'axt', text: o.xtitle}));
  items.forEach((it, i) => {
    const y = m.t + i * rowH, col = FAMCOL[it.fam];
    svg.append(tipped(sv('text', {x: m.l - 6, y: y + rowH / 2 + 4, 'text-anchor': 'end', class: 'lbl', text: fit(it.label, m.l - 8)}), it.label, false));
    svg.append(tipped(sv('rect', {x: m.l, y: y + 4, width: Math.max(1, X(it.v) - m.l), height: rowH - 8, fill: col, 'fill-opacity': it.alpha || 1, rx: 2, class: 'mark'}), it.tip));
    if (it.lo != null) {
      const yc = y + rowH / 2;
      svg.append(sv('line', {x1: X(it.lo), x2: X(it.hi), y1: yc, y2: yc, stroke: 'var(--ink)', 'stroke-width': 1.5}), sv('line', {x1: X(it.lo), x2: X(it.lo), y1: yc - 4, y2: yc + 4, stroke: 'var(--ink)', 'stroke-width': 1.5}), sv('line', {x1: X(it.hi), x2: X(it.hi), y1: yc - 4, y2: yc + 4, stroke: 'var(--ink)', 'stroke-width': 1.5}));
      svg.append(tipped(sv('line', {x1: X(it.lo), x2: X(it.hi), y1: yc, y2: yc, stroke: 'transparent', 'stroke-width': 12}), it.tip, false));
    }
    svg.append(sv('text', {x: X(it.hi != null ? it.hi : it.v) + 6, y: y + rowH / 2 + 4, text: it.text}));
  });
  el.append(svg);
}

function dtable(container, title, head, rows, open) {
  container.textContent = '';
  const t = h('table', {class: 'data'}, h('thead', {}, h('tr', {}, head.map(x => h('th', {text: x})))), h('tbody', {}, rows.map(r => h('tr', {}, r.map(c => h('td', {text: c}))))));
  const d = h('details', {class: 'dt'}, h('summary', {text: title}), h('div', {class: 'scroll'}, t));
  if (open) d.open = true;
  container.append(d);
}

/* ---------- scoring on embedded rows ---------- */
function isAuto(r, pol, kind) {
  if (r[3] == null) return false;
  if (pol.cut != null) return r[4] >= pol.cut - 1e-9 && r[3] !== 'reason';
  if (pol.timeout != null && r[6] > pol.timeout) return false;
  if (kind === 'search') return true;              // the bundle has no abstention for yes/no
  if (r[3] === 'reason') return false;
  if (r[4] < pol.min_p - 1e-9) return false;
  if (pol.margin != null && r[5] < pol.margin - 1e-9) return false;
  return true;
}
let IDX = null;
function index() {
  const sp = S(), byArm = {}, byCell = {};
  for (const r of sp.rows) {
    ((byArm[r[0]] = byArm[r[0]] || {})[r[1]] = (byArm[r[0]][r[1]] || [])).push(r);
    ((byCell[r[2]] = byCell[r[2]] || {})[r[0]] = (byCell[r[2]][r[0]] || [])).push(r);
  }
  IDX = {byArm, byCell};
}
const isRight = (r, sp) => r[3] != null && r[3] === sp.cases[r[2]].expected;
function armStat(ai, pol) {
  const sp = S(), reps = Object.keys(IDX.byArm[ai] || {});
  let cov = 0, wa = 0, waMax = 0, waMin = 1e9, n = 0;
  for (const k of reps) {
    const rows = IDX.byArm[ai][k]; let a = 0, w = 0;
    for (const r of rows) if (isAuto(r, pol, sp.cases[r[2]].kind)) { a++; if (!isRight(r, sp)) w++; }
    cov += a / rows.length; wa += w / rows.length; waMax = Math.max(waMax, w); waMin = Math.min(waMin, w); n = rows.length;
  }
  const R = reps.length || 1;
  return {cov: cov / R, waRate: wa / R, waCount: wa / R * n, waMax, waMin: waMin === 1e9 ? 0 : waMin, n, reps: reps.length};
}

/* ---------- 2. headline charts ---------- */
function legend(id, fams) {
  const el = $(id); if (!el) return; el.textContent = '';
  for (const f of fams) el.append(h('span', {}, h('span', {class: 'swatch fam-' + f}), D.families[f]));
}
function famsIn(sp) { return ['hosted', 'system_one', 'generic'].filter(f => sp.judges.some(j => j.family === f)); }
function renderHeadline() {
  const sp = S();
  bars($('#ch-acc'), sp.judges.map(j => ({label: j.short, v: j.acc.rate, lo: j.acc.ci[0], hi: j.acc.ci[1], fam: j.family, text: pct(j.acc.rate), tip: j.arm + '\nAccuracy ' + rateTxt(j.acc) + '\nPer-rep range ' + pct(j.acc_rep[0]) + ' to ' + pct(j.acc_rep[1])})), {max: 1, fmt: v => pct(v, 0), xtitle: 'accuracy (per-case majority)', title: 'Accuracy by judge'});
  const mx = Math.max(0.05, ...sp.judges.map(j => j.wa.ci[1])) * 1.08;
  bars($('#ch-wa'), sp.judges.map(j => ({label: j.short, v: j.wa.rate, lo: j.wa.ci[0], hi: j.wa.ci[1], fam: j.family, text: pct(j.wa.rate), tip: j.arm + '\nWrong automatic ' + rateTxt(j.wa) + '\nCoverage ' + rateTxt(j.cov)})), {max: mx, fmt: v => pct(v, 0), xtitle: 'wrong automatic decisions / all decisions', title: 'Wrong automatic rate by judge'});
  dtable($('#dt-headline'), 'Data: headline numbers (' + split + ')', ['Judge', 'Family', 'Accuracy', 'Acc CI lo', 'Acc CI hi', 'Wrong-auto', 'WA CI lo', 'WA CI hi', 'Coverage', 'p50 ms', 'p95 ms', '$/1M'],
    sp.judges.map(j => [j.arm, D.families[j.family], pct(j.acc.rate), pct(j.acc.ci[0]), pct(j.acc.ci[1]), j.wa.k + '/' + j.wa.n + ' ' + pct(j.wa.rate), pct(j.wa.ci[0]), pct(j.wa.ci[1]), pct(j.cov.rate), fnum(j.p50, 1), fnum(j.p95, 1), usd(j.usd1m)]));
}

/* ---------- 3. scatters ---------- */
function renderScatter() {
  const sp = S(), js = sp.judges;
  const lo = Math.min(...js.map(j => j.p95)), hi = Math.max(...js.map(j => j.p95));
  const xd = [Math.pow(10, Math.floor(Math.log10(lo * 0.8))), Math.pow(10, Math.ceil(Math.log10(hi * 1.25)))];
  const ymin = Math.min(...js.map(j => j.acc.ci[0]));
  const yd = [Math.max(0, Math.floor((ymin - 0.02) * 20) / 20), 1.0];
  scatter($('#ch-sc1'), {title: 'Accuracy versus p95 latency', xlog: true, xdom: xd, ydom: yd, xticks: logTicks(xd[0], xd[1]), yticks: niceTicks(yd[0], yd[1], 5), xfmt: fms, yfmt: v => pct(v, 0), xtitle: 'p95 latency (log scale)', ytitle: 'accuracy (whiskers 95% CI)',
    points: js.map(j => ({x: j.p95, y: j.acc.rate, ylo: j.acc.ci[0], yhi: j.acc.ci[1], fam: j.family, label: j.short, tip: j.arm + '\nAccuracy ' + rateTxt(j.acc) + '\np50 ' + fms(j.p50) + ', p95 ' + fms(j.p95) + '\n' + D.families[j.family]}))});
  const xm = Math.min(1, Math.max(...js.map(j => j.cov.ci[1])) + 0.03), xn = Math.max(0, Math.min(...js.map(j => j.cov.ci[0])) - 0.03);
  const ym = Math.max(0.05, ...js.map(j => j.wa.ci[1])) + 0.01;
  scatter($('#ch-sc2'), {title: 'Wrong automatic versus coverage', xlog: false, xdom: [xn, xm], ydom: [0, ym], xticks: niceTicks(xn, xm, 5), yticks: niceTicks(0, ym, 5), xfmt: v => pct(v, 0), yfmt: v => pct(v, 0), xtitle: 'coverage (share automatic; whiskers 95% CI)', ytitle: 'wrong automatic rate',
    points: js.map(j => ({x: j.cov.rate, y: j.wa.rate, xlo: j.cov.ci[0], xhi: j.cov.ci[1], ylo: j.wa.ci[0], yhi: j.wa.ci[1], fam: j.family, label: j.short, tip: j.arm + '\nCoverage ' + rateTxt(j.cov) + '\nWrong automatic ' + rateTxt(j.wa) + '\n' + D.families[j.family]}))});
  dtable($('#dt-scatter'), 'Data: scatter points (' + split + ')', ['Judge', 'Accuracy', 'Acc CI', 'p95 ms', 'Coverage', 'Cov CI', 'Wrong-auto', 'WA CI'],
    js.map(j => [j.arm, pct(j.acc.rate), pct(j.acc.ci[0]) + ' to ' + pct(j.acc.ci[1]), fnum(j.p95, 1), pct(j.cov.rate), pct(j.cov.ci[0]) + ' to ' + pct(j.cov.ci[1]), pct(j.wa.rate), pct(j.wa.ci[0]) + ' to ' + pct(j.wa.ci[1])]));
}

/* ---------- pairwise ---------- */
function renderPairs() {
  const sp = S(), arms = sp.arms, js = sp.judges, metric = mxMetric;
  const cell = {}, declared = new Set();
  for (const e of sp.matrix[metric]) { cell[e[0] + ',' + e[1]] = e; }
  for (const x of (sp.declared[metric] || [])) { const i = arms.indexOf(x.a), j = arms.indexOf(x.b); declared.add(Math.min(i, j) + ',' + Math.max(i, j)); }
  const better = metric === 'correct' ? 1 : -1;
  const head = h('tr', {}, h('th', {}), js.map(j => h('th', {}, h('span', {text: j.short}))));
  const body = js.map((rj, i) => h('tr', {}, h('th', {text: rj.short}), js.map((cj, j) => {
    if (i === j) return h('td', {class: 'dia', text: ''});
    const key = Math.min(i, j) + ',' + Math.max(i, j), e = cell[key];
    const flip = i > j, diff = e[2] == null ? null : (flip ? -e[2] : e[2]), rowOnly = flip ? e[4] : e[3], colOnly = flip ? e[3] : e[4];
    const sig = e[7] < D.alpha, dec = declared.has(key);
    const good = diff != null && diff * better > 0, mag = Math.min(1, Math.abs(diff || 0) / 0.25);
    const bg = diff === 0 || diff == null ? 'transparent' : `color-mix(in srgb, ${good ? 'var(--hosted)' : 'var(--sysone)'} ${Math.round(12 + mag * 58)}%, transparent)`;
    const td = h('td', {class: (sig ? 'sig ' : '') + (dec ? 'decl' : ''), style: 'background:' + bg, text: (diff == null ? 'n/a' : (diff * 100 >= 0 ? '+' : '') + (diff * 100).toFixed(1)) + (sig ? '\u2605' : '')});
    return tipped(td, `${rj.arm} minus ${cj.arm} (${metric === 'correct' ? 'accuracy' : 'wrong automatic'})\nDifference ${diff == null ? 'n/a' : (diff * 100).toFixed(1) + ' pp'}\nRow-only ${rowOnly}, column-only ${colOnly} of ${e[6]} cases\nExact McNemar p=${e[5].toFixed(4)}, Holm over all ${sp.matrix[metric].length} pairs p=${e[7].toFixed(4)}${sig ? ' (significant)' : ''}${dec ? '\nDeclared contrast' : ''}`);
  })));
  const t = h('table', {class: 'mx'}, h('thead', {}, head), h('tbody', {}, body));
  const host = $('#ch-mx'); host.textContent = ''; host.append(t);
  // forest
  const dl = (sp.declared[metric] || []);
  const fe = $('#ch-forest'); fe.textContent = '';
  if (!dl.length) fe.append(h('p', {class: 'muted', text: 'No declared contrasts in summary.json for this split.'}));
  else {
    const W = cw(fe), rowH = 24, m = {l: Math.min(W * 0.46, 16 + 7 * Math.max(...dl.map(x => (x.a + ' vs ' + x.b).length))), r: 16, t: 6, b: 42};
    const H = m.t + m.b + rowH * dl.length;
    let lo = Math.min(0, ...dl.map(x => x.diff_ci95 ? x.diff_ci95[0] : x.diff)) - 0.02, hi = Math.max(0, ...dl.map(x => x.diff_ci95 ? x.diff_ci95[1] : x.diff)) + 0.02;
    const X = v => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
    const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Declared contrasts'});
    for (const t of niceTicks(lo, hi, 6)) svg.append(sv('line', {x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: 'gl'}), sv('text', {x: X(t), y: H - m.b + 15, 'text-anchor': 'middle', text: (t * 100).toFixed(0)}));
    svg.append(sv('line', {x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, stroke: 'var(--ink3)', 'stroke-width': 1.2}));
    svg.append(sv('text', {x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle', class: 'axt', text: 'A minus B, points (bootstrap 95% CI)'}));
    dl.forEach((x, i) => {
      const y = m.t + i * rowH + rowH / 2, sig = x.p_holm < D.alpha, ci = x.diff_ci95 || [x.diff, x.diff];
      const txt = `${x.a} vs ${x.b}\ndiff ${(x.diff * 100).toFixed(1)} pp, CI ${(ci[0] * 100).toFixed(1)} to ${(ci[1] * 100).toFixed(1)}\nA only ${x.a_only}, B only ${x.b_only}\np=${x.p.toFixed(4)}, Holm ${x.p_holm.toFixed(4)}${sig ? ' (significant)' : ' (n.s.)'}`;
      svg.append(tipped(sv('text', {x: m.l - 8, y: y + 4, 'text-anchor': 'end', class: 'lbl', text: fit(x.a + ' vs ' + x.b + (sig ? ' \u2605' : ''), m.l - 10)}), x.a + ' vs ' + x.b, false));
      whisker(svg, X(ci[0]), y, X(ci[1]), y, sig ? 'var(--hosted)' : 'var(--neutral)', txt);
      svg.append(tipped(sv('circle', {cx: X(x.diff), cy: y, r: 5, fill: sig ? 'var(--hosted)' : 'var(--card)', stroke: sig ? 'var(--hosted)' : 'var(--neutral)', 'stroke-width': 2, class: 'mark'}), txt));
    });
    fe.append(svg);
  }
  const rows = sp.matrix[metric].map(e => [arms[e[0]], arms[e[1]], e[2] == null ? 'n/a' : (e[2] * 100).toFixed(1) + ' pp', e[3], e[4], e[6], e[5].toFixed(4), e[7].toFixed(4), e[7] < D.alpha ? 'significant' : 'n.s.', declared.has(e[0] + ',' + e[1]) ? 'declared' : '']);
  dtable($('#dt-pairs'), 'Data: every pair (' + (metric === 'correct' ? 'accuracy' : 'wrong automatic') + ', ' + split + ')', ['A', 'B', 'diff (A-B)', 'A only', 'B only', 'pairs', 'p (McNemar)', 'p (Holm, all pairs)', 'result', 'declared'], rows);
}

/* ---------- 4. calculator ---------- */
function polFromUI() {
  const k = $('#c-pol').value;
  if (k === 'custom') return {cut: Math.min(0.99, Math.max(0.5, +$('#c-custom').value || 0.9)), label: 'custom cutoff'};
  return D.policies[k];
}
function renderCalc() {
  const sp = S(), pol = polFromUI(), vol = Math.max(0, +$('#c-vol').value || 0), month = vol * 30, tier = $('#c-tier').value;
  $('#c-custom-wrap').style.display = $('#c-pol').value === 'custom' ? '' : 'none';
  const stats = sp.judges.map((j, i) => armStat(i, pol));
  const maxW = Math.max(1e-9, ...stats.map(s => s.waRate * month));
  const rows = sp.judges.map((j, i) => {
    const s = stats[i], price = tier === 'priority' && j.usd1m_priority != null ? j.usd1m_priority : j.usd1m, cost = month * price / 1e6, wr = s.waRate * month;
    return {j, s, cost, wr, price};
  });
  const tb = h('table', {class: 'data'}, h('thead', {}, h('tr', {}, ['Judge', 'Monthly API cost (30 days)', 'Wrong automatic actions / month', 'Automatic share', 'p95 latency'].map(x => h('th', {text: x})))),
    h('tbody', {}, rows.map(r => h('tr', {},
      h('td', {}, h('b', {text: r.j.short})),
      h('td', {text: r.j.family === 'hosted' ? usd(r.cost) : '$0 API (hardware excluded)'}),
      tipped(h('td', {}, h('span', {class: 'inbar', style: `width:${Math.round(70 * r.wr / maxW)}px;background:${FAMCOL[r.j.family]}`}), fnum(r.wr, r.wr < 100 ? 1 : 0)), `${r.j.arm}\n${fnum(r.wr, 1)} wrong automatic actions per month = ${pct(r.s.waRate, 2)} of ${fnum(month)} decisions\nMean over ${r.s.reps} repetition(s); worst repetition ${r.s.waMax} of ${r.s.n} cases\nPolicy: ${pol.label}`, false),
      td(pct(r.s.cov)), td(fms(r.j.p95))))));
  function td(t) { return h('td', {text: t}); }
  const host = $('#calc-out'); host.textContent = ''; host.append(tb);
  host.append(h('p', {class: 'muted', text: `Cutoff: ${pol.label}. Priority tier reprices only arms that have a priority multiplier (${D.priority_multiplier ? D.priority_multiplier.toFixed(1) + 'x' : 'none recorded'}). Volume ${fnum(vol)}/day = ${fnum(month)}/month. Local judges exclude hardware, power and operations. Rates assume your traffic resembles this benchmark's mix of cases.`}));
}

/* ---------- 5. explorer ---------- */
let CURVES = null;
function buildCurves() {
  CURVES = S().judges.map((j, i) => D.grid.map(t => armStat(i, {cut: t})));
}
function renderExplorer() {
  const sp = S(), t = +$('#th').value, gi = Math.min(D.grid.length - 1, Math.max(0, Math.round((t - D.grid[0]) / 0.01)));
  $('#th-val').textContent = t.toFixed(2);
  const js = sp.judges, cur = js.map((j, i) => CURVES[i][gi]);
  const el = $('#ch-front'); el.textContent = '';
  const W = cw(el), H = W < 480 ? 360 : 430, m = {l: 68, r: 14, t: 10, b: 44};
  const ymax = Math.max(1, ...CURVES.flat().map(c => c.waCount)) * 1.08, X = v => m.l + v * (W - m.l - m.r), Y = v => H - m.b - v / ymax * (H - m.t - m.b);
  const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Coverage versus wrong automatic frontier'});
  axisFrame(svg, {m, W, H, X, Y, xticks: [0, .2, .4, .6, .8, 1], yticks: niceTicks(0, ymax, 5), xfmt: v => pct(v, 0), yfmt: v => fnum(v, v < 10 && v % 1 ? 1 : 0), xtitle: 'coverage (share of decisions automatic)', ytitle: 'wrong automatic per repetition'});
  const dash = ['', '6 3', '2 3', '8 3 2 3'], seen = {};
  js.forEach((j, i) => {
    const k = seen[j.family] = (seen[j.family] || 0) + 1;
    const pts = CURVES[i].map(c => X(c.cov) + ',' + Y(c.waCount)).join(' ');
    svg.append(tipped(sv('polyline', {points: pts, fill: 'none', stroke: FAMCOL[j.family], 'stroke-width': 1.8, 'stroke-opacity': .75, 'stroke-dasharray': dash[(k - 1) % 4], class: 'mark'}), j.arm + '\nFrontier over cutoffs ' + D.grid[0].toFixed(2) + ' to ' + D.grid[D.grid.length - 1].toFixed(2) + '\nAt ' + t.toFixed(2) + ': coverage ' + pct(cur[i].cov) + ', ' + fnum(cur[i].waCount, 1) + ' wrong automatic per repetition'));
  });
  const obst = [];
  js.forEach((j, i) => {
    const c = cur[i];
    svg.append(tipped(sv('circle', {cx: X(c.cov), cy: Y(c.waCount), r: 5.5, fill: FAMCOL[j.family], stroke: 'var(--card)', 'stroke-width': 1.5, class: 'mark'}), j.arm + '\nCutoff ' + t.toFixed(2) + '\nCoverage ' + pct(c.cov) + '\nWrong automatic ' + fnum(c.waCount, 2) + ' per repetition (' + pct(c.waRate, 2) + '), worst repetition ' + c.waMax + ' of ' + c.n));
    obst.push({x: X(c.cov) - 7, y: Y(c.waCount) - 7, w: 14, h: 14});
  });
  const labs = placeLabels(js.map((j, i) => ({x: X(cur[i].cov), y: Y(cur[i].waCount), text: j.short})), {x0: m.l, x1: W, y0: 0, y1: H - m.b + 2}, obst);
  for (const l of labs) {
    if (l.leader) svg.append(sv('line', {x1: l.px, y1: l.py, x2: Math.min(Math.max(l.px, l.r.x), l.r.x + l.r.w), y2: l.r.y + 6, stroke: 'var(--ink3)', 'stroke-width': .8}));
    svg.append(sv('text', {x: l.x, y: l.y, class: 'lbl', text: l.text}));
  }
  el.append(svg);
  const rows = js.map((j, i) => [j.arm, pct(cur[i].cov), fnum(cur[i].waCount, 2), pct(cur[i].waRate, 2), cur[i].waMin + ' to ' + cur[i].waMax, cur[i].waMax === 0 ? 'zero in every repetition' : '']);
  const host = $('#th-table'); host.textContent = '';
  const tb = h('table', {class: 'data'}, h('thead', {}, h('tr', {}, ['Judge', 'Coverage', 'Wrong auto / rep (mean)', 'Wrong-auto rate', 'Range over reps (count)', ''].map(x => h('th', {text: x})))),
    h('tbody', {}, rows.map((r, i) => h('tr', {}, r.map((c, k) => k === 0 ? h('td', {}, h('b', {text: c})) : h('td', {text: c}))))));
  host.append(h('details', {class: 'dt', open: true}, h('summary', {text: 'Data: judges at cutoff ' + t.toFixed(2) + ' (' + split + ')'}), h('div', {class: 'scroll'}, tb)));
}

/* ---------- 6. case drill-down ---------- */
let CELL = null, SELECTED = null;
function buildCells() {
  const sp = S(), pol = D.policies.read; CELL = {};
  const baseIdx = sp.judges.map((j, i) => j.base ? -1 : i).filter(i => i >= 0);
  sp.cases.forEach((cs, c) => {
    CELL[c] = {};
    for (const a of Object.keys(IDX.byCell[c] || {})) {
      const rows = IDX.byCell[c][a], st = {correct: 0, wrong: 0, fallback: 0}, right = rows.filter(r => isRight(r, sp)).length;
      for (const r of rows) { const au = isAuto(r, pol, cs.kind); if (!au) st.fallback++; else if (isRight(r, sp)) st.correct++; else st.wrong++; }
      const order = ['wrong', 'fallback', 'correct'];
      let best = 'wrong', bc = -1;
      for (const k of order) if (st[k] > bc) { best = k; bc = st[k]; }
      CELL[c][a] = {status: best, mixed: bc < rows.length, argmaxRight: 2 * right > rows.length, counts: st, n: rows.length, fc: [...new Set(rows.map(r => r[7]).filter(x => x >= 0))]};
    }
  });
  buildCells.base = baseIdx;
}
const GLYPH = {correct: '\u2713', wrong: '\u2717', fallback: '\u21B7'};
function fillSelect(id, values, label) { const s = $(id), cur = s.value; s.textContent = ''; s.append(h('option', {value: '', text: label})); for (const v of values) s.append(h('option', {value: v, text: v})); if (values.includes(cur)) s.value = cur; }
function initFilters() {
  const sp = S();
  fillSelect('#f-kind', [...new Set(sp.cases.map(c => c.kind))].sort(), 'all types');
  fillSelect('#f-screen', [...new Set(sp.cases.map(c => c.screen))].sort(), 'all screens');
  const used = new Set(); for (const r of sp.rows) if (r[7] >= 0) used.add(sp.classes[r[7]]);
  fillSelect('#f-class', sp.classes.filter(c => used.has(c)), 'any / none');
}
function renderCases() {
  const sp = S(), js = sp.judges, kind = $('#f-kind').value, scr = $('#f-screen').value, cl = $('#f-class').value, aw = $('#f-allwrong').checked, orr = $('#f-oneright').checked;
  const cli = cl ? sp.classes.indexOf(cl) : -1, base = buildCells.base;
  const keep = [];
  sp.cases.forEach((cs, c) => {
    if (kind && cs.kind !== kind) return; if (scr && cs.screen !== scr) return;
    if (cli >= 0 && !js.some((j, i) => CELL[c][i] && CELL[c][i].fc.includes(cli))) return;
    const nRight = base.filter(i => CELL[c][i] && CELL[c][i].argmaxRight).length;
    if (aw && nRight !== 0) return; if (orr && nRight !== 1) return;
    keep.push(c);
  });
  $('#f-count').textContent = keep.length + ' of ' + sp.cases.length + ' cases shown';
  const head = h('tr', {}, h('th', {text: 'case'}), js.map(j => h('th', {}, h('span', {text: j.short}))));
  const body = keep.map(c => h('tr', {}, h('th', {text: sp.cases[c].id + ' \u00B7 ' + sp.cases[c].kind}), js.map((j, i) => {
    const cell = CELL[c][i];
    if (!cell) return h('td', {text: '\u2013'});
    const b = h('button', {type: 'button', class: cell.status + (cell.mixed ? ' mixed' : '') + (SELECTED && SELECTED[0] === c && SELECTED[1] === i ? ' sel' : ''), text: GLYPH[cell.status], 'aria-label': sp.cases[c].id + ' ' + j.arm + ' ' + cell.status});
    b.addEventListener('click', () => { SELECTED = [c, i]; renderCases(); openPanel(c); $('#dpanel').scrollIntoView({block: 'nearest', behavior: 'smooth'}); });
    tipped(b, `${sp.cases[c].id} / ${j.arm}\n${cell.status === 'correct' ? 'automatic and right' : cell.status === 'wrong' ? 'automatic and WRONG' : 'fell back to slow reasoning'} in ${cell.counts[cell.status]} of ${cell.n} repetition(s)\nArgmax answer right in the majority: ${cell.argmaxRight ? 'yes' : 'no'}\nClick for details`, false);
    return h('td', {}, b);
  })));
  const host = $('#ch-cm'); host.textContent = ''; host.append(h('table', {class: 'cm'}, h('thead', {}, head), h('tbody', {}, body)));
  const rows = keep.map(c => { const wrongs = js.filter((j, i) => CELL[c][i] && CELL[c][i].status === 'wrong').map(j => j.short); const nr = js.filter((j, i) => CELL[c][i] && CELL[c][i].argmaxRight).length; return [sp.cases[c].id, sp.cases[c].kind, sp.cases[c].screen, nr + ' of ' + js.length, wrongs.length, wrongs.join(', ')]; });
  dtable($('#dt-cm'), 'Data: per case (' + split + ')', ['Case', 'Type', 'Screen', 'Judges with right argmax', 'Automatic-wrong judges', 'Which'], rows);
}
function openPanel(c) {
  const sp = S(), cs = sp.cases[c], p = $('#dpanel'); p.textContent = '';
  p.append(h('h4', {text: cs.id + ' \u2014 ' + cs.kind + ' (' + cs.screen + ')'}));
  const st = h('div', {});
  for (const k of Object.keys(cs.state)) { const v = String(cs.state[k]); st.append(h('div', {}, h('b', {text: k + ': '}), v.length > 90 || v.includes('\n') ? h('pre', {class: 'st', text: v}) : v)); }
  p.append(st);
  p.append(h('div', {class: 'muted', text: 'Instructions: ' + (cs.instructions || '')}));
  const ul = h('ul', {});
  if (cs.opts) for (const k of cs.opts) ul.append(h('li', {class: 'opt' + (k === cs.expected ? ' exp' : ''), text: k + ': ' + cs.options[k]}));
  else ul.append(h('li', {class: 'opt exp', text: 'Expected answer: ' + (cs.expected ? 'yes (source implements it)' : 'no (source does not implement it)')}));
  p.append(ul);
  const t = cs.tags || {}, tg = Object.keys(t).filter(k => t[k] !== null && t[k] !== false && t[k] !== 'none');
  if (tg.length) p.append(h('div', {class: 'muted', text: 'Tags: ' + tg.map(k => k + '=' + t[k]).join(', ')}));
  const a = cs.audit;
  p.append(h('h4', {text: 'Label audit'}));
  if (a) {
    const l = h('ul', {}); l.append(h('li', {text: 'Frozen label: ' + JSON.stringify(a.frozen)}));
    for (const who of ['A', 'B']) if (a[who]) l.append(h('li', {text: `Reviewer ${who}: label ${JSON.stringify(a[who].label)}, confidence ${a[who].confidence}${a[who].ambiguous ? ', flagged ambiguous' : ''}. ${a[who].rationale || ''}`}));
    if (a.flags && a.flags.length) l.append(h('li', {text: 'Flagged ambiguous by: ' + a.flags.join(', ') + ' (agreement.json)'}));
    if (a.adjudication) l.append(h('li', {text: 'Adjudication (' + a.adjudication.verdict + '): ' + a.adjudication.detail}));
    if (!a.A && !a.B && !a.adjudication) l.append(h('li', {class: 'muted', text: 'No reviewer notes recorded for this case.'}));
    p.append(l);
  } else p.append(h('p', {class: 'muted', text: 'No label-audit data.'}));
  p.append(h('h4', {text: 'Every judge, every repetition (order 0)'}));
  const rows = [];
  sp.judges.forEach((j, i) => { for (const r of (IDX.byCell[c][i] || [])) {
    const pr = r[8] == null ? 'invalid answer' : (cs.opts ? cs.opts.map((k, x) => k + '=' + r[8][x].toFixed(2)).join(' ') : 'P(yes)=' + r[8][0].toFixed(2));
    const au = isAuto(r, D.policies.read, cs.kind);
    rows.push([j.short, r[1], r[3] == null ? 'n/a' : String(r[3]), r[4] == null ? '' : r[4].toFixed(2), pr, fnum(r[6], 0) + ' ms', au ? 'automatic' : 'fallback', r[3] == null ? 'invalid' : (isRight(r, sp) ? 'right' : 'WRONG'), r[7] >= 0 ? sp.classes[r[7]] : '']); } });
  p.append(h('div', {class: 'scroll'}, h('table', {class: 'data'}, h('thead', {}, h('tr', {}, ['Judge', 'Rep', 'Answer', 'Certainty', 'Probabilities', 'Latency', 'Bundle', 'Result', 'Failure class'].map(x => h('th', {text: x})))), h('tbody', {}, rows.map(r => h('tr', {class: r[7] === 'WRONG' ? 'bad' : ''}, r.map(x => h('td', {text: String(x)}))))))));
}

/* ---------- 8. latency ---------- */
function renderLatency() {
  const L = D.latency; if (!L) return;
  const el = $('#ch-lat'); el.textContent = '';
  const nice = k => k.replace('|keepalive', '').replace('|fresh', ' (fresh conn)');
  const W = cw(el), rowH = 26, m = {l: Math.min(W * 0.46, 10 + 7 * Math.max(...L.stack.map(s => nice(s.key).length))), r: 62, t: 6, b: 40};
  const H = m.t + m.b + rowH * L.stack.length, max = Math.max(...L.stack.map(s => s.wall_p50)) * 1.03;
  const X = v => m.l + v / max * (W - m.l - m.r), alpha = [1, .72, .5, .3];
  const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Latency anatomy'});
  for (const t of niceTicks(0, max, W < 480 ? 4 : 6)) svg.append(sv('line', {x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: 'gl'}), sv('text', {x: X(t), y: H - m.b + 15, 'text-anchor': 'middle', text: fms(t)}));
  svg.append(sv('text', {x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle', class: 'axt', text: 'median call time (ms)'}));
  L.stack.forEach((s, i) => {
    const y = m.t + i * rowH; let x = 0;
    svg.append(tipped(sv('text', {x: m.l - 6, y: y + rowH / 2 + 4, 'text-anchor': 'end', class: 'lbl', text: fit(nice(s.key), m.l - 8)}), s.key, false));
    const sum = s.segments.reduce((a, b) => a + b[1], 0) || 1;
    s.segments.forEach((sg, k) => {
      const w = sg[1] / sum * s.wall_p50;
      svg.append(tipped(sv('rect', {x: X(x), y: y + 4, width: Math.max(0.8, X(x + w) - X(x)), height: rowH - 8, fill: FAMCOL[s.family], 'fill-opacity': s.kind === 'none' ? .55 : alpha[k % 4], stroke: 'var(--card)', 'stroke-width': 1, class: 'mark'}), `${s.key} (${D.families[s.family]})\n${sg[0]}: ${sg[1].toFixed(1)} ms of ${s.wall_p50.toFixed(1)} ms median wall\nWall p95 ${fms(s.wall_p95)}, n=${s.n}`));
      x += w;
    });
    svg.append(sv('text', {x: X(s.wall_p50) + 6, y: y + rowH / 2 + 4, text: fms(s.wall_p50)}));
  });
  el.append(svg);
  const seg = $('#legend-seg'); seg.textContent = '';
  seg.append(h('span', {}, 'Shade order, darkest first \u2014 cloud: network, server, client. Local Ollama: load, prefill, decode, overhead. Faded single bar: no breakdown recorded.'));
  // concurrency
  const ce = $('#ch-conc'); ce.textContent = '';
  if (L.conc.length) {
    const Wc = cw(ce), Hc = Wc < 480 ? 360 : 420, mc = {l: 68, r: Math.min(150, Wc * 0.3), t: 10, b: 44};
    const ks = [...new Set(L.conc.flatMap(s => s.points.map(p => p[0])))].sort((a, b) => a - b);
    const vals = L.conc.flatMap(s => s.points.map(p => p[1])).filter(v => v != null);
    const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...vals) * 0.85))), hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...vals) * 1.15)));
    const Xc = k => mc.l + (ks.indexOf(k)) / Math.max(1, ks.length - 1) * (Wc - mc.l - mc.r), Yc = v => mc.t + (Hc - mc.t - mc.b) * (1 - (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)));
    const s2 = sv('svg', {width: Wc, height: Hc, viewBox: `0 0 ${Wc} ${Hc}`, role: 'img', 'aria-label': 'Concurrency scaling'});
    for (const t of logTicks(lo, hi)) s2.append(sv('line', {x1: mc.l, x2: Wc - mc.r, y1: Yc(t), y2: Yc(t), class: 'gl'}), sv('text', {x: mc.l - 6, y: Yc(t) + 3.5, 'text-anchor': 'end', text: fms(t)}));
    for (const k of ks) s2.append(sv('line', {x1: Xc(k), x2: Xc(k), y1: mc.t, y2: Hc - mc.b, class: 'gl'}), sv('text', {x: Xc(k), y: Hc - mc.b + 15, 'text-anchor': 'middle', text: String(k)}));
    s2.append(sv('line', {x1: mc.l, x2: Wc - mc.r, y1: Hc - mc.b, y2: Hc - mc.b, class: 'ax'}), sv('text', {x: (mc.l + Wc - mc.r) / 2, y: Hc - 6, 'text-anchor': 'middle', class: 'axt', text: 'requests in flight'}), sv('text', {x: 11, y: Hc / 2, 'text-anchor': 'middle', class: 'axt', transform: `rotate(-90 11 ${Hc / 2})`, text: 'p50 latency (log scale)'}));
    const seenF = {}, dash = ['', '6 3', '2 3', '8 3 2 3'];
    const ends = [];
    L.conc.forEach(s => {
      const k = seenF[s.family] = (seenF[s.family] || 0) + 1, pts = s.points.filter(p => p[1] != null);
      s2.append(tipped(sv('polyline', {points: pts.map(p => Xc(p[0]) + ',' + Yc(p[1])).join(' '), fill: 'none', stroke: FAMCOL[s.family], 'stroke-width': 2, 'stroke-dasharray': dash[(k - 1) % 4], class: 'mark'}), s.label + ' (' + D.families[s.family] + ')'));
      for (const p of pts) s2.append(tipped(sv('circle', {cx: Xc(p[0]), cy: Yc(p[1]), r: 4.5, fill: FAMCOL[s.family], stroke: 'var(--card)', 'stroke-width': 1.5, class: 'mark'}), `${s.label} at ${p[0]} in flight\np50 ${fms(p[1])}, p95 ${fms(p[2])}\nThroughput ${p[3] == null ? 'n/a' : p[3].toFixed(1)} req/s, n=${p[4]}, errors ${p[5]}`));
      const last = pts[pts.length - 1]; if (last) ends.push({label: s.label, y: Yc(last[1]), x: Xc(last[0])});
    });
    const ny = nudge1d(ends.map(e => e.y + 4), 13, mc.t + 8, Hc - mc.b);
    ends.forEach((e, i) => { if (Math.abs(ny[i] - e.y - 4) > 3) s2.append(sv('line', {x1: e.x + 5, y1: e.y, x2: e.x + 12, y2: ny[i] - 4, stroke: 'var(--ink3)', 'stroke-width': .8})); s2.append(sv('text', {x: e.x + 14, y: ny[i], class: 'lbl', text: e.label})); });
    ce.append(s2);
    dtable($('#dt-conc') || ce.appendChild(h('div', {id: 'dt-conc'})), 'Data: concurrency', ['Endpoint', 'In flight', 'p50 ms', 'p95 ms', 'req/s', 'n', 'errors'], L.conc.flatMap(s => s.points.map(p => [s.label, p[0], fnum(p[1], 1), fnum(p[2], 1), p[3] == null ? 'n/a' : p[3].toFixed(1), p[4], p[5]])));
  }
}

/* ---------- 9. interventions ---------- */
function renderInterv() {
  const sp = S(), pairs = sp.judges.filter(j => j.base), byName = {}; sp.judges.forEach(j => byName[j.arm] = j);
  for (const [id, key, title, tx] of [['#ch-iv-wa', 'wa', 'Wrong automatic', 'wrong automatic / all decisions'], ['#ch-iv-cov', 'cov', 'Coverage', 'coverage']]) {
    const el = $(id); el.textContent = '';
    if (!pairs.length) { el.append(h('p', {class: 'muted', text: 'No intervention arms in this split.'})); continue; }
    const items = []; let mx = 0.02;
    for (const j of pairs) for (const [jj, nm, al] of [[byName[j.base], j.base + ' base', 1], [j, j.base + ' +clause', .5]]) {
      const o = jj[key]; mx = Math.max(mx, o.ci[1]);
      items.push({label: nm, v: o.rate, lo: o.ci[0], hi: o.ci[1], fam: jj.family, alpha: al, text: pct(o.rate), tip: jj.arm + (split === 'dev' ? ' (dev: screen)' : '') + '\n' + title + ' ' + rateTxt(o)});
    }
    bars(el, items, {max: key === 'cov' ? 1 : mx * 1.08, fmt: v => pct(v, 0), xtitle: tx + ' (faded = with clause)', title});
  }
  if (!pairs.length) { $('#dt-iv').textContent = ''; $('#dt-iv').append(h('p', {class: 'muted', text: 'No base+intervention arms in this split; the policy-modifier tables below still apply.'})); return; }
  const rows = [];
  for (const j of pairs) { const b = byName[j.base]; for (const [k, nm] of [['wa', 'wrong-auto'], ['cov', 'coverage'], ['acc', 'accuracy']]) rows.push([j.base + ' \u2192 ' + j.arm.split('+').slice(1).join('+'), nm, pct(b[k].rate) + ' [' + pct(b[k].ci[0]) + ', ' + pct(b[k].ci[1]) + ']', pct(j[k].rate) + ' [' + pct(j[k].ci[0]) + ', ' + pct(j[k].ci[1]) + ']', ((j[k].rate - b[k].rate) * 100).toFixed(1) + ' pp']); }
  dtable($('#dt-iv'), 'Data: base vs +clause (' + split + (split === 'dev' ? ', screen' : '') + ')', ['Pair', 'Metric', 'Base', '+clause', 'Change'], rows);
}

/* ---------- wiring ---------- */
function renderAll() {
  if (!D.splits[split]) split = 'dev';
  $('#sp-dev').setAttribute('aria-pressed', split === 'dev'); $('#sp-holdout').setAttribute('aria-pressed', split === 'holdout');
  document.querySelectorAll('.activesplit').forEach(e => e.textContent = split + (split === 'dev' ? ' (screen)' : ''));
  index(); buildCurves(); buildCells(); initFilters();
  renderHeadline(); renderScatter(); renderPairs(); renderCalc(); renderExplorer(); renderCases(); renderLatency(); renderInterv();
  const sel = SELECTED && SELECTED[0] < S().cases.length ? SELECTED[0] : null; if (sel != null) openPanel(sel);
}
function rerenderSizes() { renderHeadline(); renderScatter(); renderPairs(); renderExplorer(); renderLatency(); renderInterv(); }
function init() {
  const fams = famsIn(D.splits.dev);
  ['#legend-fam', '#legend-fam2', '#legend-fam3'].forEach(id => legend(id, fams));
  const sel = $('#c-pol');
  for (const k of Object.keys(D.policies)) sel.append(h('option', {value: k, text: D.policies[k].label}));
  sel.append(h('option', {value: 'custom', text: 'custom cutoff (pure certainty)'}));
  const ho = $('#sp-holdout'); if (!D.splits.holdout) { ho.disabled = true; ho.title = 'holdout pending'; ho.textContent = 'Holdout (pending)'; }
  $('#sp-dev').addEventListener('click', () => { split = 'dev'; SELECTED = null; $('#dpanel').textContent = 'Click any cell to see the task, options, frozen label, label-audit notes and every judge\u2019s answer.'; renderAll(); });
  ho.addEventListener('click', () => { if (!D.splits.holdout) return; split = 'holdout'; SELECTED = null; $('#dpanel').textContent = 'Click any cell to see the task, options, frozen label, label-audit notes and every judge\u2019s answer.'; renderAll(); });
  $('#mx-acc').addEventListener('click', () => { mxMetric = 'correct'; $('#mx-acc').setAttribute('aria-pressed', 'true'); $('#mx-wa').setAttribute('aria-pressed', 'false'); renderPairs(); });
  $('#mx-wa').addEventListener('click', () => { mxMetric = 'automatic_error'; $('#mx-wa').setAttribute('aria-pressed', 'true'); $('#mx-acc').setAttribute('aria-pressed', 'false'); renderPairs(); });
  for (const id of ['#c-vol', '#c-pol', '#c-custom', '#c-tier']) { $(id).addEventListener('input', renderCalc); $(id).addEventListener('change', renderCalc); }
  $('#th').addEventListener('input', renderExplorer);
  for (const id of ['#f-kind', '#f-screen', '#f-class', '#f-allwrong', '#f-oneright']) $(id).addEventListener('change', renderCases);
  const root = document.documentElement, tb = $('#theme');
  const eff = () => root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const lab = () => { tb.textContent = eff() === 'dark' ? 'Light theme' : 'Dark theme'; };
  try { const t = localStorage.getItem('judge-report-theme'); if (t) root.dataset.theme = t; } catch (e) { /* storage unavailable */ }
  tb.addEventListener('click', () => { root.dataset.theme = eff() === 'dark' ? 'light' : 'dark'; try { localStorage.setItem('judge-report-theme', root.dataset.theme); } catch (e) { /* ignore */ } lab(); });
  lab();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', lab);
  let timer = null; let lastW = innerWidth;
  window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(() => { if (innerWidth !== lastW) { lastW = innerWidth; rerenderSizes(); } }, 150); });
  renderAll();
}
init();
})();
"""


if __name__ == "__main__":
    sys.exit(main())
