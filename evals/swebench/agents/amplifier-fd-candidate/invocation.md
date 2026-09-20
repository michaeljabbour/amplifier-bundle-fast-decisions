# Driving amplifier-fd-candidate

This agent is the Amplifier CLI with amplifier-foundation plus the
fast-decisions orchestrator in ACTIVE mode, configured from the S1/S2
confirmed champion cell (`evals/swebench/candidate.config.json`, rendered
into this agent's `install.yaml` before the harness runs -- see that file's
header comment and README.md "Preflight"). Behavior otherwise identical to
amplifier-fd-incumbent's invocation flow.

## IMPORTANT: the turn can take many minutes

Identical caution as the other two S3 variants: launch in the BACKGROUND
with a completion sentinel and POLL. Do NOT run `amplifier run` as a single
blocking command.

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

Do NOT judge correctness yourself. Note any `hook_cannot_own_active` fallback
event the same way amplifier-fd-incumbent's invocation.md describes.
