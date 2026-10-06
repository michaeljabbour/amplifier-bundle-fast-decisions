# holdout-v3 runbook: smoke, then S1

Order of events (the preregistration precedes the S1 schedule and every S1 session; the smoke precedes the preregistration):
validated panel -> smoke -> (repair or swap a scenario only now, re-run `panel.py --write`) -> commit the preregistration and its
provenance -> S1 `plan` -> `run` -> `rows` -> `s1_analysis.py` (complete data only).

Always: `export PYTHONPATH=src:.:scripts:evals`; `memory_pressure | tail -1` must show >= 50% free before any run (the harness
also refuses below max(32 GB, 25% of RAM) available); scenario code only through `scripts/memguard.py` (4 GB, 300 s, built into
the graders); nothing else heavy on the machine. `CAND` is the frozen candidate commit: the commit that contains the product
code the sessions will run (`git rev-parse HEAD` after the last commit; every plan records it and freezes a detached worktree).

## 1. Smoke: one plain Sonnet 5 session per scenario (60 sessions, cap $250, est. $206 with reserve, ~4.6 h at --parallel 8)

```bash
CAND=$(git rev-parse HEAD)
python3 evals/paired.py plan --design evals/paired/holdout-v3-smoke.yaml --out ~/dev/afast-paired/holdout-v3-smoke \
  --seed 20261005 --parallel 8 --candidate-sha "$CAND" --budget-usd 250
nice -n 10 python3 evals/paired.py run --out ~/dev/afast-paired/holdout-v3-smoke --parallel 8 --budget-usd 250
python3 evals/paired.py rows --out ~/dev/afast-paired/holdout-v3-smoke        # per-scenario pass table only; NOT analysed
```

Read `rows/sessions.jsonl` only for: did the session finish, did each turn grade without `evaluate_error` / `resource_limit` /
timeouts, was any scenario unsolvable in every turn. A failing scenario is repaired or swapped before the preregistration commit.
No cost or pass-rate number from the smoke enters any hypothesis.

## 2. S1 (1,224 sessions, 240 waves, cap $5,000, est. $4,292 with reserve)

```bash
CAND=$(git rev-parse HEAD)                    # after the preregistration commit; record it in prereg-holdout-v3/PROVENANCE.md
python3 evals/paired.py plan --design evals/paired/holdout-v3.yaml --out ~/dev/afast-paired/holdout-v3 \
  --seed 20261005 --parallel 12 --candidate-sha "$CAND" --budget-usd 5000
python3 evals/paired.py preflight --out ~/dev/afast-paired/holdout-v3 --budget-usd 5000 --parallel 10     # 10 cells, ~$5
nice -n 10 python3 evals/paired.py run --out ~/dev/afast-paired/holdout-v3 --parallel 12 --budget-usd 5000 \
  --session-cap-gb 8 --max-system-use-gb 80
# resume after a stop:  ... run --out ... --parallel 12 --budget-usd 5000 --resume
# spend/health only (the holdout split is blinded):  python3 evals/paired_dashboard.py serve --out ~/dev/afast-paired/holdout-v3
python3 evals/paired.py rows --out ~/dev/afast-paired/holdout-v3
python3 evals/v3/s1_analysis.py --sessions ~/dev/afast-paired/holdout-v3/rows/sessions.jsonl --out <result dir>
```

`--parallel` must be >= 7 (a Fable wave with the A/A has 7 sessions; the design refuses less). Wall-time estimates (FIFO waves):
8 -> 133 h, 10 -> 73 h, 12 -> 67 h, 20 -> 36 h, 24 -> 34 h, 30 -> 24 h; the memory watchdog and Forge's terminal cap (`maxSessions`
30) bind first, so measure the first 20 waves' concurrency before raising it. The first waves are also the multi-turn test of the
ShF gate ("decided once, restored on resume"); any mechanism-gate failure stops the run (preregistration, Stop rules).

## Offline checks that need no model

```bash
python3 evals/paired.py plan --dry-run --design evals/paired/holdout-v3.yaml --parallel 12 --seed 20261005
python3 evals/v3/s1_render_cells.py --out /tmp/render.json      # every cell differs from its comparator only where intended
python3 evals/paired/scenarios/holdout-v3/panel.py              # panel constraints + overlaps (exit 1 on a problem)
python3 evals/paired.py preflight --out <scratch> --budget-usd 10 --reevaluate    # re-read the last preflight sessions, no spend
```
