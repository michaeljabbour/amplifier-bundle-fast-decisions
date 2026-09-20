# Driving amplifier-plain

This agent is the Amplifier CLI with amplifier-foundation composed and NO
fast-decisions bundle. The eval is a SINGLE, non-interactive turn: hand the
task message to `amplifier run` and let it work to completion.

## IMPORTANT: the turn can take many minutes

A real SWE-bench turn takes several minutes and may run for the task's full
timeout (2700s per `meta.yaml`). Do NOT run `amplifier run` as a single
blocking command -- it will hit a command timeout and you will wrongly
conclude failure. Instead launch it in the BACKGROUND with a completion
sentinel and POLL until it finishes.

## Step 1 -- launch in the background

Run the user's message verbatim as the quoted argument. Redirect output to a
file and write a sentinel when it exits:

```
cd /workspace && rm -f eval-run.out eval-run.done && \
nohup bash -lc 'PATH=/root/.local/bin:$PATH amplifier run "<the user's message>" > /workspace/eval-run.out 2>&1; echo "EXIT:$?" > /workspace/eval-run.done' >/dev/null 2>&1 &
echo launched
```

If the user's message contains a double quote, first write it to
`/workspace/eval-prompt.txt` and use `amplifier run "$(cat /workspace/eval-prompt.txt)"`.

## Step 2 -- poll until the sentinel appears

Repeat this check, sleeping ~30s between checks, for as long as it takes (be
patient -- up to ~40 minutes; SWE-bench turns are slow):

```
if [ -f /workspace/eval-run.done ]; then echo "COMPLETE $(cat /workspace/eval-run.done)"; else echo RUNNING; tail -c 200 /workspace/eval-run.out 2>/dev/null; fi
```

Do NOT conclude while it still prints `RUNNING`. Keep polling. The run
spawning a sub-session is expected, not an error.

## Step 3 -- confirm the deliverable and conclude

Once you see `COMPLETE`, confirm the agent edited the repository (it should
NOT commit -- the grader extracts the patch via `git diff`):

```
cat /workspace/eval-run.out
cd /workspace/repo && git add -N . && git --no-pager diff --stat
```

Then conclude:

- verdict `success` -- the sentinel shows `EXIT:0` and `git diff --stat`
  shows at least one changed file in `/workspace/repo`
- verdict `failure` -- the sentinel shows a non-zero exit, or the diff is
  empty (the agent made no changes)

Put a short note about what was changed in your summary. Do NOT judge
correctness yourself -- the grader (the official SWE-bench Docker harness)
does that.
