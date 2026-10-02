"""Build the sanitized evidence package from the RAW paired-campaign directories (read-only).

    CAMPAIGNS=~/dev/afast-paired python3 package_evidence.py

Reads  <CAMPAIGNS>/main-v1, <CAMPAIGNS>/pilot-2, <CAMPAIGNS>/dashboard-main-v1.html, the Forge daemon log.
Writes data/, campaign/, pilot/, dashboard/, prereg/, model/, data/DATA-DICTIONARY.md, campaign/FAILURES.md and
SHA256SUMS next to this script's parent directory.  Never touches the raw tree.  README.md files are hand-written.

Sanitization (the only transformations applied; rows are otherwise byte-for-byte what `evals/paired.py rows` wrote):
  * the home directory prefix becomes ~ ; the campaign / pilot / snapshot roots become <campaign> / <pilot-2> /
    <snapshots>; the repo checkout becomes <repo>
  * free-text failure reasons (tails of agent terminal output captured by the harness) are cut at " -- " and replaced
    by a length + sha256 prefix, so no model response text survives
  * any key that could hold prompt/response text aborts the build instead of being silently kept
"""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = str(Path.home())
RAW = Path(os.environ.get("CAMPAIGNS", Path.home() / "dev" / "afast-paired")).expanduser()
MAIN, PILOT = RAW / "main-v1", RAW / "pilot-2"
OUT = Path(__file__).resolve().parent.parent
REPO = OUT.parents[2]
FORGE_LOG = Path.home() / "Library" / "Logs" / "forge" / "daemon.err.log"

REPLACEMENTS = [(str(MAIN), "<campaign>"), (str(PILOT), "<pilot-2>"), (str(RAW / "snapshots"), "<snapshots>"),
                (str(RAW), "<campaigns>"), (str(Path.home() / "dev" / "fd-paired"), "<repo>"), (str(REPO), "<repo>"),
                (HOME, "~")]
FORBIDDEN_KEYS = {"prompt", "prompts", "response", "responses", "text", "content", "message", "messages", "stdout",
                  "stderr", "output_text", "tail", "transcript", "completion", "body"}
ITEM_SPLIT = re.compile(r"; (?=[A-Za-z0-9._-]+-r\d+-[a-z0-9]+-(?:anchor|aa|shipped|sticky|sonnet): )")


def san_str(s: str) -> str:
    for a, b in REPLACEMENTS:
        s = s.replace(a, b)
    return s


def scrub_reason(s: str) -> str:
    """Keep '<session>: <cause>' of each item, replace the captured terminal tail by its length and hash."""
    out = []
    for item in ITEM_SPLIT.split(s):
        head, sep, tail = item.partition(" -- ")
        out.append(f"{head} -- [terminal tail omitted: {len(tail)} chars, sha256:{hashlib.sha256(tail.encode()).hexdigest()[:8]}]"
                   if sep else item[:300])
    return "; ".join(out)


def walk(v, key=None, strict=True):
    if isinstance(v, dict):
        bad = FORBIDDEN_KEYS & set(v)
        if strict and bad:
            raise SystemExit(f"refusing to package: field(s) {sorted(bad)} may hold prompt/response text")
        return {san_str(k): walk(x, k, strict) for k, x in v.items()}
    if isinstance(v, list):
        return [walk(x, key, strict) for x in v]
    if isinstance(v, str):
        return san_str(scrub_reason(v) if key == "reason" else v)
    return v


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def jsonl_rows(p: Path):
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def dump_row(o) -> str:
    return json.dumps(o, default=str) + "\n"


def copy_rows(src: Path, dst: Path, name: str, gz: bool) -> dict:
    """Sanitize one rows/*.jsonl. Returns {rows, raw_sha256, sha256 (file written), content_sha256, fields}."""
    n, fields = 0, {}
    body = hashlib.sha256()
    target = dst / (name + ".jsonl" + (".gz" if gz else ""))
    dst.mkdir(parents=True, exist_ok=True)
    fh = open(target, "wb")
    out = gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) if gz else fh
    for o in jsonl_rows(src / f"{name}.jsonl"):
        o = walk(o)
        for k, v in o.items():
            fields.setdefault(k, set()).add(type(v).__name__)
        b = dump_row(o).encode("utf-8")
        body.update(b)
        out.write(b)
        n += 1
    if gz:
        out.close()
    fh.close()
    return {"rows": n, "raw_sha256": sha(src / f"{name}.jsonl"), "sha256": sha(target), "content_sha256": body.hexdigest(),
            "bytes": target.stat().st_size, "fields": fields, "file": target.name}


def copy_text(src: Path, dst: Path, per_line=None) -> None:
    text = src.read_text(encoding="utf-8", errors="replace")
    lines = []
    for line in text.splitlines(keepends=True):
        if per_line:
            line = per_line(line)
        lines.append(san_str(line))
    w(dst, "".join(lines))


def copy_json(src: Path, dst: Path, strict=False) -> None:
    obj = walk(json.loads(src.read_text(encoding="utf-8")), strict=strict)
    w(dst, json.dumps(obj, indent=2, default=str) + "\n")


def dashboard_html(text: str) -> str:
    """The dashboard's infrastructure-failure table embeds the same terminal tails as state.json: scrub them, escape the
    path placeholders for HTML, and drop the 60 s auto-refresh (this is a frozen snapshot)."""
    text = re.sub(r"(<td>)([^<]*worker vanished[^<]*)(</td>)", lambda m: m.group(1) + scrub_reason(m.group(2)) + m.group(3), text)
    text = re.sub(r"(transient infrastructure failure: )((?:(?!</pre>)[^\n])*)", lambda m: m.group(1) + scrub_reason(m.group(2)), text)   # run.log excerpt
    text = san_str(text)
    for token in ("campaign", "pilot-2", "snapshots", "campaigns", "repo"):
        text = text.replace(f"<{token}>", f"&lt;{token}&gt;")
    text = re.sub(r'<meta http-equiv="refresh"[^>]*>', "<!-- snapshot: auto-refresh removed -->", text)
    return text


def scrub_log_line(line: str) -> str:
    m = re.match(r"^(\[[^\]]+\] attempt \d+: transient infrastructure failure: )(.*)$", line.rstrip("\n"))
    return (m.group(1) + scrub_reason(m.group(2)) + "\n") if m else line


# ----------------------------------------------------------------------------------------------- field docs
S_DOC = {
 "schema": "Row schema id, always `fast-decisions-paired/v1`.",
 "session_key": "Unique session id `<scenario>-r<rep>-<host|any>-<arm>`; also the run directory name in the raw tree.",
 "wave_id": "`<scenario>-r<rep>-<host>`. All sessions of one wave start together from the same frozen workspace; the unit that is retried when infrastructure fails.",
 "attempt": "Number of the wave attempt that was accepted. 1 for 941 sessions; 2, 3 and 4 mean earlier attempts of the wave failed on infrastructure and were rerun (see campaign/FAILURES.md). Failed attempts are not in the data.",
 "scenario_id": "Scenario (task script) id.",
 "scenario_hash": "sha256 of the scenario spec (task, turns, checks); checked against schedule.json at launch.",
 "source": "Human-readable provenance of the task (upstream repo / benchmark), not prompt text.",
 "task_type": "Scenario family: bugfix, feature, docs, explain, review, mixed.",
 "language": "Main language of the workspace.",
 "split": "Preregistered split, `train` or `test` (prereg/SPLIT.md).",
 "host": "Host model stratum of the pair: `opus` or `fable`; `any` for the Sonnet control, which is host-independent and is paired against both hosts' anchors.",
 "host_model": "Model id the session requested (anchor/aa: the host; shipped/sticky: the host, which the policy may override per request; sonnet: Sonnet).",
 "arm": "`anchor` (plain host model, A0), `aa` (second anchor on a 20% subsample, noise floor), `shipped` (orch-default fast-decisions profile), `sticky` (model chosen once at session start, never switched), `sonnet` (plain Sonnet control).",
 "kind": "Mechanism class used by the mechanism gate: `plain`, `fd`, `sticky`, `control`.",
 "cell": "Profile cell id (evals/paired/main-v1.yaml), e.g. `plain-opus`, `orch-default-opus`.",
 "rep": "Repetition 1 or 2 of the scenario/host cell.",
 "sticky_decision": "Sticky arm only: `cheap` or `host`, decided once from the turn-1 prompt (campaign/decisions.jsonl); null for other arms.",
 "scripted_turns": "Number of scripted user turns in the scenario.",
 "gap_schedule": "Seconds of idle time before each turn (0, 10 s steps, 420 s long gaps that outlast the 5-minute cache TTL).",
 "n_long_gaps": "Number of gaps of 5 minutes or more in gap_schedule.",
 "turn1_prompt_chars": "Length in characters of the first user prompt (the text itself is not published).",
 "total_prompt_chars": "Total characters over all scripted prompts.",
 "workspace_files": "File count of the frozen starting workspace.",
 "workspace_bytes": "Total bytes of the frozen starting workspace.",
 "swe_difficulty": "Reserved for SWE-bench difficulty; always null in this campaign.",
 "build_sha": "Git sha of the candidate source frozen at plan time (the preregistration commit).",
 "bundle_tree_sha": "sha256 over the frozen candidate source tree.",
 "price_table_sha": "First 16 hex of sha256 of the price table (`savings.DEFAULT_RATES`, JSON, sorted keys) used to recompute costs.",
 "nonce_mode": "`per_session`: every session carries its own cache-isolation nonce at the start of the system prompt.",
 "plan_id": "Id of the plan in campaign/schedule.json.",
 "provider_module": "Provider module actually imported: module name, version, git sha (paths sanitized).",
 "campaign_provider": "Provider entry injected for the campaign: id, source, and the NAMES of its config keys (no values).",
 "preflight_ok": "Whether the freshest preflight (campaign/preflight.json) passed.",
 "nonce": "The session's UUID cache nonce.",
 "key_fingerprint": "10-hex sha prefix of the API key used; identical on every session (one shared key).",
 "model_ids": "Model id list requested for the session (host model).",
 "served_models": "Distinct model ids that served main-loop requests; two entries mean the policy routed some requests elsewhere.",
 "served_model_check": "True when every served model matches the requested one (always true for fd/sticky arms, which route on purpose).",
 "cost_usd_provider": "USD summed from the provider-reported per-request cost over ALL requests (main and background).",
 "cost_usd_recomputed": "USD recomputed from token counts and the price table over all requests.",
 "cost_usd_tools_normalized": "PRIMARY cost basis: recomputed cost with the shared tools prefix on the first request of each (model, effort) repriced from cache write to cache read (production-realistic warm tools).",
 "tools_repriced_tokens": "Tokens moved from the write rate to the read rate by the tools normalization.",
 "tools_normalized_delta_usd": "USD change from normalization (<= 0); cost_usd_tools_normalized = cost_usd_recomputed + this.",
 "cost_mismatch": "True when |provider - recomputed| > 1e-6 USD or any request was unpriced. False on every session.",
 "unpriced_requests": "Requests whose model is missing from the price table.",
 "tokens": "Main-loop token totals per served model: `input` (uncached input), `cache_read`, `cache_write`, `output`.",
 "n_req": "Main-loop LLM requests (requests carrying tools).",
 "n_bg": "Background LLM requests (no tools, e.g. session naming); billed in cost fields, excluded from `tokens`.",
 "wall_ms": "Sum of the per-turn elapsed milliseconds (includes the scripted gaps).",
 "exec_ms": "Sum over main requests of request-to-response time (milliseconds).",
 "model_switches": "Changes of model between consecutive main requests.",
 "switches_turn_boundary": "Switches that fall between two turns.",
 "switches_midturn": "Switches inside a turn.",
 "rebuild_write_tokens": "Cache-write tokens on requests that followed a switch.",
 "rebuild_excess_write_tokens": "Of those, write tokens above what the new content explains (pure cache rebuild).",
 "rebuild_usd": "USD premium of the excess rebuild writes over the read rate.",
 "cache_hit_share": "cache_read / (uncached + cache_read + cache_write) over main requests; null with no requests.",
 "first_req_write_static": "Cache-write tokens on the session's first main request (the static prefix).",
 "warm_start_cost_usd": "Recomputed cost with the first request's write tokens billed at the read rate (what a fully warm start would cost).",
 "tools_prefix_allowance_tokens": "Shared tools-prefix allowance used by the audit and the normalization (32,100 tokens, measured by preflight).",
 "cross_arm_read_tokens": "Cache-read tokens on the first main request (shared tools prefix; reported, not flagged within the allowance).",
 "foreign_read_tokens_total": "Cache-read tokens beyond the session's own earlier writes plus the allowance (would indicate cross-arm leakage).",
 "foreign_read_requests": "Number of requests with foreign reads.",
 "cache_audit_flags": "Per-request detail of foreign reads; empty on every session.",
 "cache_audit_clean": "True when no foreign reads were found. True on every session.",
 "turn_pass_frac": "Fraction of scripted turns whose checks passed.",
 "final_state_pass": "True when the last turn ran and all its checks passed (final workspace state correct).",
 "critical": "True when a protected file was modified or a check errored while evaluating.",
 "failure_labels": "Failed-check labels over all turns (check names such as `pytest_failures`; no output text).",
 "receipt_usd_saved_sum": "Sum of USD reported by the fast_decisions efficiency receipts (the policy's own claim; not used as evidence).",
 "fd_receipt_counts": "Count of fast_decisions receipt events by kind.",
 "fd_receipts": "Total routing receipts (difficulty_judged, scored, model_routed, effort_routed, efficiency, turn_planned).",
 "mechanism_engaged": "Mechanism gate: fd arms show routing receipts, plain arms none, sticky never switches and judges once. True on every session.",
 "mechanism_reasons": "Reasons the gate failed; empty on every session.",
 "status": "`ok` (passed), `agent_fail` (ran, outcome failed), `infra_fail` (infrastructure; none in accepted rows).",
 "killed_memory": "True when the memory watchdog killed the session's agent tree (one session; see campaign/FAILURES.md).",
 "killed_memory_info": "Watchdog marker: time, reason, RSS and cap in GB, process ids; null otherwise.",
 "cost_valid": "False when the session was memory-killed: its cost is not comparable and its pairs are excluded from cost analyses.",
 "scheduled_start": "Reserved for offset-start experiments; always null here.",
 "actual_start": "UTC ISO time the session actually started.",
 "concurrent_sessions": "Sessions in the same wave attempt (started together).",
 "wave_valid": "False when the wave's launch spread exceeded the limit; always true here.",
 "anchor_cost_usd": "Non-anchor rows only: the paired anchor's tools-normalized cost (added by pair building).",
 "anchor_cost_usd_raw": "The paired anchor's recomputed (un-normalized) cost.",
 "anchor_n_req": "The paired anchor's main request count.",
 "anchor_turn_costs": "The paired anchor's per-turn tools-normalized costs.",
}
T_DOC = {
 "schema": "Row schema id.", "session_key": "Session id (joins sessions.jsonl).", "scenario_id": "Scenario id.", "arm": "Arm.",
 "host": "Host stratum.", "rep": "Repetition.", "wave_id": "Wave id.", "turn_index": "1-based scripted turn number.",
 "turn_prompt_chars": "Characters in this turn's scripted prompt (text not published).",
 "gap_before_s": "Idle seconds before the turn.",
 "models_used": "Distinct models serving this turn's main requests.",
 "efforts_used": "Distinct reasoning-effort values as strings (`None` when not set).",
 "tokens": "Main-request tokens in the turn: input (uncached), cache_read, cache_write, output.",
 "cost_usd": "Provider-reported USD of every request (main + background) inside the turn window.",
 "cost_usd_recomputed": "Same requests, recomputed from tokens and the price table.",
 "cost_usd_tools_normalized": "Same requests on the primary tools-normalized basis.",
 "tools_repriced_tokens": "Tokens repriced by the tools normalization in this turn.",
 "tools_normalized_delta_usd": "USD effect of that repricing (<= 0).",
 "calls": "Main-loop requests in the turn.", "bg_calls": "Background requests in the turn.",
 "wall_ms": "Turn elapsed milliseconds as recorded by the runner (null for a turn that never ran).",
 "working_ms": "First main request start to last main response end (milliseconds); null with no main request.",
 "switched_in": "True when the turn's first main request used a different model than the previous turn's last.",
 "pass": "All of the turn's checks passed.", "skipped": "Turn not run (an earlier turn ended the session, e.g. a kill).",
 "checks": "Number of checks evaluated after the turn.", "failure_labels": "Labels of failed checks (null when skipped).",
 "first_req_cache_read": "Cache-read tokens of the turn's first main request.",
 "first_req_cache_write": "Cache-write tokens of the turn's first main request.",
}
P_DOC = {
 "schema": "Row schema id.", "scenario_id": "Scenario id.", "rep": "Repetition.",
 "host": "Host stratum of the pair (the Sonnet control yields one pair per host).", "arm": "The non-anchor arm: aa, shipped, sticky or sonnet.",
 "task_type": "Scenario family.", "n_long_gaps": "Long gaps (>= 5 min) in the scenario.",
 "cost_basis": "`tools_normalized` (the primary basis for delta_usd / log_cost_ratio / anchor_cost_usd / arm_cost_usd).",
 "delta_usd": "arm - anchor in USD (negative = the arm was cheaper), primary basis. The model code's `saving` is the negative of this.",
 "log_cost_ratio": "ln(arm cost / anchor cost), primary basis; null if either cost is 0.",
 "delta_usd_raw": "arm - anchor in USD on the recomputed, un-normalized basis.",
 "log_cost_ratio_raw": "ln ratio on the raw basis.",
 "delta_s": "Wall-clock seconds, arm - anchor.",
 "delta_turn_pass": "turn_pass_frac arm - anchor.",
 "both_pass": "Both final states passed.",
 "arm_failed_what_anchor_passed": "The arm's final state failed while the anchor's passed.",
 "anchor_cost_usd": "Anchor cost, primary basis.", "arm_cost_usd": "Arm cost, primary basis.",
 "anchor_cost_usd_raw": "Anchor cost, raw basis.", "arm_cost_usd_raw": "Arm cost, raw basis.",
 "mechanism_engaged": "Mechanism gate of the arm session.", "cache_audit_clean": "Cache audit of the arm session.",
 "cost_valid": "False if either session was memory-killed.",
 "valid": "Usable for analysis: both waves valid, neither session infra_fail, both cost_valid.",
}
R_DOC = {
 "schema": "Row schema id.", "session_key": "Session id.", "scenario_id": "Scenario id.", "arm": "Arm.", "host": "Host stratum.",
 "rep": "Repetition.", "request_index": "1-based order among all of the session's LLM requests (main + background).",
 "turn_index": "Turn the request falls in; 0 when its timestamp is outside every turn window.",
 "main": "True for main-loop requests (carry tools), false for background requests.",
 "model": "Model id the response came from.", "effort": "Reasoning effort requested (null when unset).",
 "tokens": "input (uncached), cache_read, cache_write, output tokens of the request.",
 "cost_usd_provider": "Provider-reported USD.", "cost_usd_recomputed": "Recomputed USD from the price table (null if unpriced).",
 "cost_usd_tools_normalized": "Primary basis for this request.", "tools_repriced_tokens": "Tokens repriced on this request (first request per model/effort only).",
 "tools_normalized_delta_usd": "USD effect of the repricing (<= 0).",
}
SUM_DOC = {
 "sessions": "Accepted sessions in rows.", "turns": "Turn rows.", "requests": "Request rows.", "pairs": "Arm-vs-anchor pairs.",
 "tools_normalized_delta_usd_total": "Sum of the normalization deltas over all sessions (USD).",
 "skipped_no_result": "Sessions with no result.json (none).", "cache_audit_flagged_sessions": "Sessions with foreign cache reads (none).",
 "mechanism_failed": "Sessions that failed the mechanism gate (none).", "killed_memory": "Session keys killed by the memory watchdog.",
 "cost_mismatch": "Sessions whose provider and recomputed costs disagree (none).",
}


def dictionary(infos: dict, sums: dict) -> str:
    docs = {"sessions": S_DOC, "turns": T_DOC, "pairs": P_DOC, "requests": R_DOC}
    lines = ["# Data dictionary", "",
             "Fields of the campaign rows written by `evals/paired.py rows` (`session_row`, `build_pairs`, `extract_rows`).",
             "Costs are USD. Tokens are counts. `ms` are milliseconds; times are UTC ISO unless stated.",
             "The primary cost basis is **tools-normalized** (`cost_usd_tools_normalized`, pairs `delta_usd`/`log_cost_ratio`); the",
             "raw (recomputed, un-normalized) basis is kept next to it. Sign convention: `delta_usd` = arm - anchor, so negative is cheaper.", "",
             "## Files, row counts, checksums", "",
             "| file | rows | bytes | sha256 (as published) | sha256 of the uncompressed content | sha256 of the raw (unsanitized) source |",
             "|---|---:|---:|---|---|---|"]
    for name in ("sessions", "turns", "pairs", "requests"):
        i = infos[name]
        lines.append(f"| `{i['file']}` | {i['rows']} | {i['bytes']} | `{i['sha256']}` | `{i['content_sha256']}` | `{i['raw_sha256']}` |")
    sj = sums["summary_sha"]
    lines += [f"| `summary.json` | 1 object | {sums['summary_bytes']} | `{sj}` | | `{sums['summary_raw_sha']}` |", "",
              "The published files differ from the raw ones only where a path was rewritten (see `reproduce/package_evidence.py`):",
              "`provider_module.path` and `provider_module.git_root` in sessions rows. Every other byte is unchanged;",
              "`requests.jsonl.gz` is deterministic gzip (mtime 0, level 9).", ""]
    for name, doc in docs.items():
        lines += [f"## {name} ({infos[name]['rows']} rows)", "", "| field | type | meaning |", "|---|---|---|"]
        missing = [k for k in infos[name]["fields"] if k not in doc]
        if missing:
            raise SystemExit(f"undocumented {name} fields: {missing}")
        for k, types in infos[name]["fields"].items():
            lines.append(f"| `{k}` | {'/'.join(sorted(types))} | {doc[k]} |")
        lines.append("")
    lines += ["## summary.json", "", "| field | meaning |", "|---|---|"]
    for k, v in sums["summary"].items():
        lines.append(f"| `{k}` | {SUM_DOC[k]} (value: `{json.dumps(v)}`) |")
    lines += ["", "## Notes", "",
              "* `sessions` carries `anchor_*` fields only on non-anchor rows with a host-specific pair (not on `anchor`, and not on `sonnet` rows, whose host is `any`).",
              "* Turn cost fields sum every request inside the turn window, background requests included; session totals also count requests that fall outside every turn window (`turn_index` 0 in requests), so the sum of a session's turn costs can be slightly below its session cost.",
              "* One session, `py-forth-r2-opus-aa`, was killed by the memory watchdog: `cost_valid` false, its pair `valid` false; its task outcome (turn 9 failed, turn 10 skipped) is kept for quality analyses.",
              "* `sessions` has 1,036 rows = 280 waves; 896 pairs = 280 shipped + 280 sticky + 280 sonnet (140 sessions x 2 hosts) + 56 aa."]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------- failures
CAP_WINDOW = ("2026-10-01T20:30:00-04:00", "2026-10-01T20:36:00-04:00")
PMSET = [("2026-10-01T12:24:40-04:00", "2026-10-01T14:05:04-04:00", "on battery (97%)"),
         ("2026-10-01T15:30:49-04:00", "2026-10-01T19:28:28-04:00", "on battery (100%)")]


def birth(p: Path) -> dt.datetime:
    p = Path(str(p).replace("<campaign>", str(MAIN)))      # state.json is read back after sanitization
    return dt.datetime.fromtimestamp(p.stat().st_birthtime).astimezone()


def forge_events() -> dict:
    shut, idle = [], []
    for line in FORGE_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"Shutting down daemon' in line or '"Session idle timeout"' in line or '"Starting forge daemon"' in line:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = dt.datetime.fromisoformat(o["ts"].replace("Z", "+00:00"))
            (idle if "idle" in o["msg"] else shut).append((t, o["msg"], {k: v for k, v in o.items() if k in ("maxSessions",)}))
    return {"shut": shut, "idle": idle}


def failures_md(state: dict, ledger: dict, mem: dict, spend: dict) -> tuple[str, dict]:
    fe = forge_events()
    starts = [t for t, m, _ in fe["shut"] if m.startswith("Shutting")]
    rows = []

    def add(wid, att, wave_note, history):
        if att["status"] == "done":
            return
        k = att.get("failure_kinds") or {}
        n_sess = len(k) or len([1 for v in (att.get("outcomes") or {}).values() if v != "done"])
        t0 = birth(Path(att["root"]))
        reason, note = att.get("reason"), (wave_note or "")
        if "maxSessions" in note:
            cause, ev = "forge_session_cap", "recorded (wave reset_note)"
        elif "Mac slept" in note:
            cause, ev = "mac_sleep", "recorded (wave reset_note)"
        elif reason and "worker vanished" in reason:
            nxt = next((s for s in starts if s > t0.astimezone(dt.timezone.utc)), None)
            cause, ev = "forge_daemon_restart", "recorded reason + daemon log shutdown " + (nxt.astimezone(t0.tzinfo).strftime("%m-%d %H:%M:%S") if nxt else "?")
        elif CAP_WINDOW[0] <= t0.isoformat(timespec="seconds") <= CAP_WINDOW[1]:
            cause, ev = "forge_session_cap", "INFERRED from start time (inside the 20:31-20:35 burst, same cadence as the recorded cap waves)"
        else:
            cause, ev = "mac_sleep", "INFERRED from start time (Oct 1 clamshell-sleep window, Forge idle timeouts)"
        rows.append({"wave": wid, "attempt": att["attempt"], "status": "excluded->reset" if history else "infra_failed->retried",
                     "sessions_failed": n_sess, "started": t0.isoformat(timespec="seconds"), "cause": cause, "evidence": ev,
                     "usd": ledger["spent"].get(f"{wid}#a{att['attempt']}", 0.0), "sess": [s["key"] for s in att["sessions"]][:0]})

    for wid, w_ in state["waves"].items():
        for h in w_.get("history", []):
            for a in h["attempts"]:
                add(wid, a, w_.get("reset_note"), True)
        for a in w_["attempts"]:
            add(wid, a, None, False)
    rows.sort(key=lambda r: r["started"])
    by = collections.defaultdict(list)
    for r in rows:
        by[r["cause"]].append(r)
    cnt = {c: len(v) for c, v in by.items()}
    usd = {c: round(sum(r["usd"] for r in v), 4) for c, v in by.items()}
    sess = {c: sum(r["sessions_failed"] for r in v) for c, v in by.items()}
    reset_waves = sorted(wid for wid, w_ in state["waves"].items() if w_.get("history"))
    cap_waves = [wid for wid in reset_waves if "maxSessions" in state["waves"][wid]["reset_note"]]
    sleep_waves = [wid for wid in reset_waves if "Mac slept" in state["waves"][wid]["reset_note"]]
    n_acc = sum(1 for w_ in state["waves"].values() if w_.get("accepted_attempt") is not None)
    shutdowns = [t.astimezone().strftime("%m-%d %H:%M:%S") for t in starts if t >= dt.datetime(2026, 10, 1, 14, 24, 54, tzinfo=dt.timezone.utc)]
    L = ["# Failed, excluded and retried attempts", "",
         "Source of truth: `campaign/state.json` (every wave keeps its attempts; waves that were reset keep the earlier attempts in `history`),",
         "`campaign/ledger.json` (spend per `<wave>#a<attempt>`), `campaign/run.log` and `campaign/supervisor.log`, the Forge daemon log",
         "`~/Library/Logs/forge/daemon.err.log` (timestamps only; its other content is not published) and the macOS power log (`pmset -g log`).",
         "Times are America/New_York (EDT, -04:00) and are the **start** of the attempt (creation time of its run directory); a failure time is only",
         "given where an external event pins it.", "",
         "## Summary", "",
         f"* {len(rows) + n_acc} wave attempts in total: **{n_acc} accepted** (one per wave, 280 waves) and **{len(rows)} failed**.",
         "* Every failed attempt was an *infrastructure* failure (`transient`), none an agent or scenario failure; every wave was rerun until it completed. No wave is missing from the data.",
         f"* {len(reset_waves)} waves were *excluded* by the harness after 3 failed attempts and then *reset* (`--reset-wave`) and rerun from attempt 4 "
         f"({len(cap_waves)} for the Forge session cap, {len(sleep_waves)} for the Mac sleeping); their 30 earlier attempts are the `history` entries in state.json. "
         "(Earlier notes counted all 10 as cap waves; state.json attributes 9 to the cap and 1, `markdown-tocclass-r1-opus`, to sleep.)",
         "* The other 19 failed attempts were retried automatically by the harness and succeeded within 4 attempts.",
         f"* Spend on failed attempts: ${sum(r['usd'] for r in rows):.4f} of ${sum(ledger['spent'].values()):.2f} total ledger spend; most failed attempts died before spending anything.",
         "* Failed-attempt rows are not in `data/` (only the accepted attempt of a wave is extracted). The failed attempts' raw run directories exist in the raw tree.", "",
         "| cause | failed attempts | sessions failed | ledger USD on them | how well established |", "|---|---:|---:|---:|---|",
         f"| forge_session_cap | {cnt.get('forge_session_cap', 0)} | {sess.get('forge_session_cap', 0)} | {usd.get('forge_session_cap', 0)} | 27 recorded in reset notes; 4 inferred from timing |",
         f"| forge_daemon_restart | {cnt.get('forge_daemon_restart', 0)} | {sess.get('forge_daemon_restart', 0)} | {usd.get('forge_daemon_restart', 0)} | recorded reason, each matches a `Shutting down daemon` entry in the Forge log |",
         f"| mac_sleep | {cnt.get('mac_sleep', 0)} | {sess.get('mac_sleep', 0)} | {usd.get('mac_sleep', 0)} | 3 recorded in a reset note; 4 inferred from timing |",
         f"| **total** | **{len(rows)}** | **{sum(sess.values())}** | **{round(sum(usd.values()), 4)}** | |", ""]

    L += ["## 1. Forge session cap (maxSessions 10) at `--parallel 32`", "",
          "The Forge daemon allows `maxSessions` terminals (10 until Oct 2 09:20, then 26, then 30). At ~20:31 on Oct 1 the run was relaunched at `--parallel 32`; launches "
          "beyond the cap failed with `launch_error \"Maximum sessions (10) reached\"`, three times per wave, so the harness excluded the waves. This was a harness bug "
          "(it did not wait for capacity), fixed that evening (backup `state.json.bak-before-capacity-fix` is dated 20:40) but only committed as `dc1aa4e` on Oct 2 at 18:18, after the campaign ended (\"Forge capacity waits, failure reasons, circuit breaker, launch stagger\"); the run log of the later runs shows "
          "`waiting for Forge terminal capacity` and `--parallel 28 clamped to 23`. The excluded waves were reset and rerun as attempt 4. "
          "state.json before the fix is kept in the raw tree (`state.json.bak-before-capacity-fix`, not published).", "",
          f"Waves excluded for the cap ({len(cap_waves)}): " + ", ".join(f"`{x}`" for x in cap_waves) + ".", "",
          "Four more attempts (`toolz-interpose-r2-fable` a1-a2, `config-matrix-r1-opus` a1-a2) have no recorded reason but started at 20:33-20:34, inside the same burst and "
          "on the same ~40 s cadence as the recorded cap waves; they are classified as cap **by inference** and were retried successfully (not reset).", ""]
    L += ["## 2. Forge daemon restarts", "",
          "Attempts whose workers 'vanished mid-run' (Forge terminals closed under them). Each such attempt has a recorded `reason`, and each started shortly before a "
          "`Shutting down daemon...` entry in the Forge daemon log. Shutdowns in the campaign window (EDT): " + ", ".join(shutdowns) + ". "
          "No shutdown appears between the campaign start (Oct 1 10:24) and Oct 2 05:05. The first two Oct 2 shutdowns are exactly 6 h 00 m 00 s apart; the third is 4 h 50 m "
          "after the second. A ~6-hour period is therefore only evidenced twice, not as a steady cycle. The cause of the restarts is not recorded in any file I could read.", "",
          "The harness response: `circuit breaker` (2 consecutive waves with infrastructure failure stop the run with exit 4 and no exclusion; `supervisor.log` shows an "
          "automatic resume 60 s later, 'breaker caused by Forge daemon restart at 2026-10-02T19:55:28.395Z'), and the next run adopted live sessions with `--resume`.", ""]
    L += ["## 3. Mac clamshell sleep on battery", "",
          "`pmset -g log` shows lid-closed sleeps while on battery, with periodic maintenance DarkWakes (the harness runs `caffeinate`, which cannot prevent clamshell sleep on battery):", ""]
    for a, b, c in PMSET:
        L.append(f"* sleep {a[11:19]} -> full wake {b[11:19]} (EDT, {c})")
    L += ["", "Running sessions then logged `Connection error` retries and the Forge idle timeout (30 min in the Oct 2 config reload) closed them: the Forge log has 20 `Session idle timeout` "
          "entries between 12:57 and 19:22 on Oct 1. The recorded reset note for `markdown-tocclass-r1-opus` cites 'pmset 15:30-16:07'; the power log shows the second sleep lasting "
          "until 19:28 (with DarkWake maintenance windows), and that wave's third attempt started at 17:31, i.e. inside the sleep, so the note's window is the first interruption, not the whole outage.", "",
          "Four attempts with no recorded reason (`rust-gradeschool-r2-fable` a1 12:14, `mistune-escape-r1-fable` a1 12:19, `pr-review-cart-r2-fable` a1 15:10 and a2 17:23) are "
          "classified as sleep **by inference**: each was running when a clamshell sleep began or was launched inside one, and all precede the harness gaining failure reasons.", ""]
    L += ["## 4. Attempts with no recorded reason (honest accounting)", "",
          "A preliminary tally spoke of 18 early attempts without a recorded reason. That number cannot be reproduced from the files; what they show:", "",
          "* 38 failed attempts carry no per-attempt `reason` field: the 30 `history` attempts of the reset waves (explained only by a human-written, retrospective wave-level "
          "`reset_note`) and 8 attempts of waves that were retried automatically (the 4 cap-burst and 4 sleep attempts above). The reason field was added during Oct 2 (committed afterwards in `dc1aa4e`); "
          "only the 11 attempts from Oct 2 04:59 on have one.",
          "* 18 = the 8 unannotated attempts + the 10 reset waves is the most plausible reading of that tally; if it meant something else it is not recoverable from these files.",
          "* For none of the 38 is the cause *recorded at the time*. The classification above rests on the reset notes (30), start-time coincidence with the cap burst (4) and with "
          "clamshell-sleep windows (4). Treat those 8 as probable, not proven.", ""]
    L += ["## 5. Process-level interruptions (`run.log`, `supervisor.log`)", "",
          "* Oct 1, first lines of `run.log`, before the first session (timing inferred from the fix commit): `KeyError: 'api-docs'` (exit 1) because `run` fell back to the pilot design; fixed in `4c9ce44` (10:24:19), first session started 10:24:54.",
          "* Oct 1 ~20:30: `settings.yaml changed since the campaign started` (exit 4): the CLI's `updates.last_check` timestamp changed the guarded hash. Re-baselined 20:31 with a recorded reason (`settings_rebaselined` in state.json); fixed in `20fd152`.",
          "* Several `EXIT 143` (SIGTERM): the run was stopped by a signal. One is the 14:54 supervisor restart at `PARALLEL=28` (logged in `supervisor.log`); the cause of the others is not logged.",
          "* Oct 2: `run.log` shows two circuit-breaker stops (exit 4), after the 11:05 and 15:55 Forge restarts. `supervisor.log` records run starts at 12:32:25, 14:54:19 (restart at `PARALLEL=28`) and 16:21:00 (automatic resume 60 s after the second stop was noticed), then `EXIT 0` and `campaign complete` at 17:39:07. `run.log` only holds the later runs; earlier output was overwritten.", ""]
    L += ["## 6. Memory kill: `py-forth-r2-opus-aa`", "",
          f"The watchdog killed the agent tree of this A/A session at {mem['at']} UTC (reason `{mem['reason']}`: RSS {mem['rss_gb']} GB > per-session cap {mem['session_cap_gb']} GB, "
          f"{mem['available_gb']} GB available system-wide). The kill landed in turn 9 (failed), turn 10 was skipped; turns 1-8 passed. Handling (`session_row` in `evals/paired.py`: a watchdog kill is a *task outcome*, the session is kept, "
          "but its cost is not comparable; memory safety limits are identical across arms per the preregistration):", "",
          "* the session is **kept**: `status` `agent_fail`, `turn_pass_frac` 0.8, `final_state_pass` false, so it counts for quality analyses;",
          "* its **cost is invalid**: `cost_valid` false and `killed_memory` true in sessions.jsonl; the single pair it forms (`py-forth` rep 2, host opus, arm aa) has `cost_valid` false and `valid` false and must be excluded from every cost estimate;",
          "* the wave was not rerun (a rerun would not be comparable with the other 4 sessions of the same wave), and no other session was killed (`summary.json` -> `killed_memory`).", ""]
    L += ["## 7. Every failed attempt", "",
          "| wave | attempt | outcome | sessions failed | started (EDT) | cause | evidence | USD spent |", "|---|---:|---|---:|---|---|---|---:|"]
    for r in rows:
        L.append(f"| {r['wave']} | {r['attempt']} | {r['status']} | {r['sessions_failed']} | {r['started']} | {r['cause']} | {r['evidence']} | {r['usd']:.4f} |")
    L.append("")
    return "\n".join(L), {"rows": len(rows), "by_cause": cnt, "usd": usd, "sessions": sess, "accepted": n_acc, "reset_waves": len(reset_waves),
                           "cap_waves": len(cap_waves), "sleep_waves": len(sleep_waves)}


# ----------------------------------------------------------------------------------------------- prereg
def git(*a) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], check=True, capture_output=True, text=True).stdout.strip()


def prereg_md(first_start: str, schedule_created: str) -> str:
    items = [("evals/paired/PREREGISTRATION-main-v1.md", "preregistration"), ("evals/paired/scenarios/main-v1/SPLIT.md", "train/test split"),
             ("evals/paired/scenarios/main-v1/split.json", "split (machine readable)"), ("evals/paired/main-v1.yaml", "campaign design")]
    L = ["# Preregistration provenance", "", "| file | what | commit | commit time | subject | blob sha |", "|---|---|---|---|---|---|"]
    t_pre = None
    for f, what in items:
        h, ct, subj = git("log", "--format=%H|%cI|%s", "-1", "--", f).split("|", 2)
        L.append(f"| `{f}` | {what} | `{h[:12]}` | {ct} | {subj} | `{git('rev-parse', f'{h}:{f}')[:12]}` |")
        if "PREREGISTRATION" in f:
            t_pre = ct
    t0 = dt.datetime.fromisoformat(first_start.replace("Z", "+00:00"))
    tp = dt.datetime.fromisoformat(t_pre)
    ok = tp < t0
    L += ["", "## Preregistration precedes the data", "",
          f"* preregistration commit time: {t_pre} ({tp.astimezone(dt.timezone.utc).isoformat()})",
          f"* schedule (`campaign/schedule.json`) created: {schedule_created}",
          f"* first session `actual_start` in `data/sessions.jsonl`: {first_start}",
          f"* gap: preregistration is {(t0 - tp)} before the first session started; **{'PASS' if ok else 'FAIL'}**",
          f"* the split commit is earlier still ({git('log', '--format=%cI', '-1', '--', 'evals/paired/scenarios/main-v1/SPLIT.md')}).",
          f"* the files are unchanged since: `git diff 3aa2d1e HEAD -- <prereg, SPLIT, split.json>` is empty ({'yes' if not git('diff', '3aa2d1e', 'HEAD', '--', 'evals/paired/PREREGISTRATION-main-v1.md', 'evals/paired/scenarios/main-v1/SPLIT.md', 'evals/paired/scenarios/main-v1/split.json') else 'NO'}).",
          "* `build_sha` in every session is `3aa2d1e0065d99f68dd6393097d988397515e2bf`, the preregistration commit itself: the candidate bundle under test was frozen at that commit.",
          "", "Caveat: git commit times are author-controlled. The commit was pushed to `origin/eval/paired-measurement`; the push time is not recorded in the repo, "
          "so the ordering rests on commit timestamps plus the consistency of schedule creation (+52 s) and first session (+6 m 12 s) with them.",
          "", "Harness changes after the preregistration (none edits the prereg, split or design). Note that the harness code which ran the campaign was not a commit: "
          "the Forge capacity wait (state backup dated Oct 1 20:40) and the failure-reason capture (present in state.json from Oct 2 04:59) were live in the working tree and were only committed as `dc1aa4e` on Oct 2 at 18:18, after the campaign ended. "
          "The candidate under test (`build_sha`) is a separate frozen copy, unaffected. Re-extracting rows with the committed harness reproduces the raw rows byte for byte (reproduce/README.md).", ""]
    L += ["```", git("log", "--format=%h %cI %s", "3aa2d1e..HEAD", "--", "evals/paired.py", "evals/paired_dashboard.py", "evals/paired_model.py", "scripts"), "```", ""]
    if not ok:
        raise SystemExit("preregistration does NOT precede first session")
    return "\n".join(L)


# ----------------------------------------------------------------------------------------------- main
def main() -> None:
    data, camp = OUT / "data", OUT / "campaign"
    infos = {n: copy_rows(MAIN / "rows", data, n, gz=(n == "requests")) for n in ("sessions", "turns", "pairs", "requests")}
    summary_raw = MAIN / "rows" / "summary.json"
    copy_json(summary_raw, data / "summary.json", strict=False)
    summary = json.loads(summary_raw.read_text(encoding="utf-8"))
    sums = {"summary": summary, "summary_sha": sha(data / "summary.json"), "summary_raw_sha": sha(summary_raw),
            "summary_bytes": (data / "summary.json").stat().st_size}
    w(data / "DATA-DICTIONARY.md", dictionary(infos, sums))

    copy_json(MAIN / "schedule.json", camp / "schedule.json")
    copy_text(MAIN / "plan.txt", camp / "plan.txt")
    copy_json(MAIN / "state.json", camp / "state.json")
    copy_json(MAIN / "ledger.json", camp / "ledger.json")
    copy_text(MAIN / "decisions.jsonl", camp / "decisions.jsonl")
    copy_json(MAIN / "preflight.json", camp / "preflight.json")
    copy_text(MAIN / "run.log", camp / "run.log", scrub_log_line)
    copy_text(MAIN / "supervisor.log", camp / "supervisor.log")
    state, ledger = json.loads((camp / "state.json").read_text(encoding="utf-8")), json.loads((camp / "ledger.json").read_text(encoding="utf-8"))
    sess = list(jsonl_rows(data / "sessions.jsonl"))
    mem = next(s for s in sess if s["killed_memory"])["killed_memory_info"]
    md, fsum = failures_md(state, ledger, mem, {})
    w(camp / "FAILURES.md", md)

    pil = OUT / "pilot"
    for n in ("sessions", "turns", "pairs", "requests"):
        copy_rows(PILOT / "rows", pil, n, gz=(n == "requests"))
    copy_json(PILOT / "rows" / "summary.json", pil / "summary.json")
    for f in ("schedule.json", "state.json", "ledger.json", "preflight.json"):
        copy_json(PILOT / f, pil / f)
    copy_text(PILOT / "decisions.jsonl", pil / "decisions.jsonl")
    copy_text(PILOT / "plan.txt", pil / "plan.txt")

    w(OUT / "dashboard" / "index.html", dashboard_html((RAW / "dashboard-main-v1.html").read_text(encoding="utf-8")))

    first_start = min(s["actual_start"] for s in sess if s["actual_start"])
    pre = OUT / "prereg"
    for src in ("evals/paired/PREREGISTRATION-main-v1.md", "evals/paired/scenarios/main-v1/SPLIT.md", "evals/paired/scenarios/main-v1/split.json"):
        w(pre / Path(src).name, (REPO / src).read_text(encoding="utf-8"))
    w(pre / "PROVENANCE.md", prereg_md(first_start, json.loads((camp / "schedule.json").read_text(encoding="utf-8"))["created_at"]))
    for f in ("model.json", "summary.json", "predictions.json"):
        copy_text(MAIN / "model" / f, OUT / "model" / f)      # no paths inside: kept byte-identical to the raw files
    copy_text(MAIN / "model" / "MODEL.md", OUT / "model" / "MODEL.md")

    sums_lines = []
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and p.name not in ("SHA256SUMS", "README.md", "__pycache__") and "__pycache__" not in p.parts:
            sums_lines.append(f"{sha(p)}  {p.relative_to(OUT).as_posix()}")
    w(OUT / "SHA256SUMS", "\n".join(sums_lines) + "\n")
    json.dump({"failures": fsum, "infos": {k: {x: y for x, y in v.items() if x != "fields"} for k, v in infos.items()}, "first_start": first_start},
              sys.stdout, indent=1, default=str)
    print()


if __name__ == "__main__":
    main()
