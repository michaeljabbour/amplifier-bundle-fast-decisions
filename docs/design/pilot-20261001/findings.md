# Pilot de-risking, 2026-10-01: prompt-cache semantics (Step 1), plus Step 0 pointer

Raw data: `step1_cache_probe.json` (111 requests, per-request usage, 0 errors). Scripts:
`step1_cache_probe.py`, `step1b_effort_replicate.py`, `step1c_effort_pairs.py`. Logs: `step1*_run.log`.

**Setup.** Calls went straight to `POST https://api.anthropic.com/v1/messages`. They used the same key
the `provider-anthropic` module uses (`ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY`), the same model ids the
campaigns used (`claude-opus-5-5`, `claude-sonnet-5`, `claude-fable-5-1`, all available), and the
same thinking/effort shapes the campaign `llm:request` events show:
- Opus and Sonnet: `thinking={"type":"adaptive","display":"summarized"}`.
- Routed Sonnet: adds `output_config.effort=medium`.
- Fable: no thinking parameter.

Cache markers were `{"type":"ephemeral"}`, the 5-minute TTL that the provider uses by default. Every
test started with a unique nonce at the front of the system prompt, so no test could read another
test's cache. The shared prompt was P (≈10.9k tokens, a Python file) followed by X (≈4.5k tokens,
a second file); a full request was ≈15.5k tokens.

**Spend: $4.76** at list prices computed from usage. By model: Sonnet $3.54, Fable $0.79, Opus $0.43.
$1.54 of that was the extra effort replication (e4).

## Answers

**(a) After writing P+X (marker at the end of X), does a request for P alone (marker at P) read P?
No. It misses completely and writes P.** This held on all three models. Sonnet wrote 10,948 tokens
and read 0; repeating the P-alone request then read 10,948.

A cache entry exists only at a block boundary where some request placed a marker. A longer entry
does not serve its own prefixes. Related checks on Sonnet:
- **a2, extending the conversation** (P+X+Y, marker at Y): read 15,455 (P+X) and wrote 2,272 (Y).
  The automatic lookback finds the earlier entry.
- **a3, a diverging branch** (P+X′, where the write had no marker at P): read 0 and wrote 14,777.
- **a4, the same branch when the write also had a marker at P:** read 10,938 (P) and wrote 3,839.
- **The lookback window is about 20 blocks.** With 10 extra blocks after the last entry (g4), it
  read 15,455. With 30 extra blocks (g3), it fell back to the system-prompt entry: read 10,938,
  wrote 6,340.

**(b) Do two API keys in the same org share a cache? No.** `ANTHROPIC_API_KEY` and the provider key
are different keys, and both return the same `anthropic-organization-id` (hash `defee167d1`).
- A write with key 1, then the identical request with key 2: key 2 wrote 15,455 and read 0.
- Key 1 again: read 15,455.
- The reverse direction (write with key 2, then key 1): key 1 wrote 15,455, read 0.

Sharing is narrower than the org. I can't tell from here whether it's per workspace or per key,
because workspace ids aren't visible in the response.

**(c) Do two simultaneous identical first requests both pay a write? Yes, 3 of 3 trials.** Both
wrote 15,455 and read 0. A follow-up about 1 s later read 15,455.

**(d) Does a read at about 240 s refresh the 5-minute TTL? Yes.**

| Entry | Write | Read(s) | Result at ~420 s |
|---|---|---|---|
| A | t=0 | t=240 read 15,455 | read 15,455 (alive at 7 min, so the read refreshed it) |
| B (control, never read) | t=0 | — | wrote 15,455, read 0 (expired) |
| C (control) | t=0 | t=280 read 15,455 | — |

All writes were billed as `ephemeral_5m`.

**(e) Does changing thinking or effort between otherwise identical requests invalidate the cache?**
- **Thinking on or off: no, on any of the three models.** For example, Sonnet adaptive → no
  thinking read 15,464, and Opus did the same.
- **Effort on Opus 5.5 and Fable 5.1: no.** Absent → low, medium or high all read 15,464, in both
  orders.
- **Effort on Sonnet 5: yes, and it misses the whole prompt, system prompt included.** The cache is
  split by effort level, and leaving effort out behaves the same as `high`.
  - In fresh-cache pairs (2 replicates each, every one consistent): absent→high **hit**;
    absent→low, absent→medium, low→medium, low→high and medium→high all **missed** (write 15.46k,
    read 0). Same→same hit.
  - With only a system-prompt marker (e3), absent→medium still rewrote the whole system prompt
    (10,937 tokens).

  Caveat: these requests had no thinking blocks in earlier assistant turns. Real multi-turn
  histories that contain them weren't tested.

**(f) Are caches per model? Confirmed.** Sonnet wrote 15,454; the same request then wrote 15,454 on
Opus and 15,454 on Fable (0 read on each). Repeating it on Sonnet and on Opus read 15,454.

## What this means for a "fork the session and run the other path" design

1. **A fork under the same key will read the live run's cache** for any prefix the live run marked,
   on the same model, and on Sonnet only at the same effort level. That entry must be alive: within
   5 minutes of the live run's last request touching it, since every read refreshes the TTL (d).
   A fork taken at a turn start sends exactly the live run's turn-k first request, so it gets a
   full warm read. That is faithful for a same-model counterfactual, because a real session on that
   path would also have had that history warm.
2. **A fork on a different model starts cold no matter what** (f). That cold start is the real
   switch cost. Since it doesn't depend on timing, no deferral is needed for that comparison.
3. **To isolate a fork from the live run, use the second key rather than a delay** (b). Using the
   same key with a delay only works if the fork starts more than 5 minutes after the live run last
   touched the shared prefix. The live run keeps refreshing that prefix while it's active, so in
   practice that means waiting until the live run is finished and then another 5+ minutes.
   - If you want the realistic warm state, run the fork on the live key right after the fork point.
     Don't start it at the same instant as the live request: simultaneous identical requests both
     pay the write (c), which would overstate the fork's cost by one write (≈$0.058 per 15k tokens
     on Sonnet).
4. **A skipped call (a fast-row decision) leaves no cache entry, but that costs nothing extra.** The
   next call's lookback reaches the last entry that was written and writes the combined delta:
   - Skipped (g2): turn 3 read 15,455 and wrote 4,479.
   - Not skipped (g1): turn 2 wrote 2,272 and turn 3 wrote 2,207. That's the same 4,479 total.

   So the skip saves the skipped call's own read, uncached input and output, and the cache
   accounting is otherwise neutral. Two exceptions:
   - The gap since the last written entry grows past about 20 content blocks. Tool-heavy turns add
     many `tool_use`/`tool_result` blocks. The provider's secondary rolling marker normally sits on
     the previous turn's primary one, but if that request was skipped, the marker points at a
     boundary nobody wrote. The read then falls back to an earlier marker (in g3, the system
     prompt), and much more gets rewritten.
   - The skip makes the next touch land more than 5 minutes after the last one, so the entry
     expires.

   A "skipped call saved $X" receipt should check both conditions.
5. **Sonnet effort is part of the cache key.** Routed Sonnet requests send `effort=medium`, so they
   never share cache with a plain-sonnet run (effort absent = high), or with another effort lever's
   Sonnet calls. Any switch of Sonnet's effort level within a session is a full rewrite, about
   $0.058 per 15k tokens. Opus and Fable effort levers don't pay this.

Step 0 (variance and power) is in `step0_variance.json` / `step0_table.md`. The final reply has a
summary.
