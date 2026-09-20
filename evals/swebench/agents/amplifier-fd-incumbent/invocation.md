# Driving amplifier-fd-incumbent

This agent is the Amplifier CLI with amplifier-foundation plus the
fast-decisions orchestrator in ACTIVE mode (incumbent config: local judge +
`explore: low` effort routing). The eval is a SINGLE, non-interactive turn:
hand the task message to `amplifier run` and let it work to completion.

## IMPORTANT: the turn can take many minutes

Identical caution as amplifier-plain: launch in the BACKGROUND with a
completion sentinel and POLL. Do NOT run `amplifier run` as a single blocking
command.

## Step 1 -- launch in the background

```
cd /workspace && rm -f eval-run.out eval-run.done && \
nohup bash -lc 'PATH=/root/.local/bin:$PATH amplifier run "<the user's message>" > /workspace/eval-run.out 2>&1; echo "EXIT:$?" > /workspace/eval-run.done' >/dev/null 2>&1 &
echo launched
```

If the user's message contains a double quote, first write it to
`/workspace/eval-prompt.txt` and use `amplifier run "$(cat /workspace/eval-prompt.txt)"`.

## Step 2 -- poll until the sentinel appears

```
if [ -f /workspace/eval-run.done ]; then echo "COMPLETE $(cat /workspace/eval-run.done)"; else echo RUNNING; tail -c 200 /workspace/eval-run.out 2>/dev/null; fi
```

Sleep ~30s between checks; be patient (up to ~40 minutes). Do NOT conclude
while it still prints `RUNNING`.

## Step 3 -- confirm the deliverable and conclude

```
cat /workspace/eval-run.out
cd /workspace/repo && git add -N . && git --no-pager diff --stat
```

- verdict `success` -- sentinel shows `EXIT:0` and the diff is non-empty
- verdict `failure` -- non-zero exit, or an empty diff

Do NOT judge correctness yourself -- the grader (the official SWE-bench
Docker harness) does that. If you observe `fallback` events referencing
`hook_cannot_own_active` in the session transcript, note it explicitly in
your summary: it means the orchestrator swap did not take and this trial
degraded to shadow-only (a defect in the DTU's bundle composition, not a
model failure).
