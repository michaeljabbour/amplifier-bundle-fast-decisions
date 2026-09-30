# Judge-quality benchmark: validated run, label audit, RCA and preregistered holdout

Measured September 30, 2026 on an Apple M5 Max (128 GB), Ollama 0.35.0. [Interactive report](index.html).
This validates the first-pass judge comparison ([2026-09-30-judge-comparison](../2026-09-30-judge-comparison/README.md),
PR #54) and turns it into the `judge` suite ([STUDY-DESIGN.md section 19](../../../evals/STUDY-DESIGN.md)).
Total API spend for everything here: about $1.35.

## Verdict

- **Default: keep Jev 1.13.** On the preregistered holdout it was right on 55/63 (95% CI 77-93%) with **one** wrong
  automatic decision; p50 about 155 ms, p95 about 220 ms, $18 per million decisions. GPT-6 Luna (60/63) and GPT-6.1 Sol
  (62/63) were more accurate, but **neither difference survives the preregistered Holm correction** (p 0.16 and 0.09),
  and both fail the p95 <= 500 ms and <= 2x cost rules (Luna p95 1.8-1.9 s, 2.2x; Sol p95 3.6-4.7 s, 49x).
- **Add the host guard (I2) whatever the judge.** Preregistered and confirmed: it removed every side-effect wrong
  automatic decision in all 9 judges it applied to on the holdout, with no accuracy change and 1.6-7.9 points of
  coverage. Adding the one-sentence side-effect clause to Jev's instruction (I1) raised its holdout accuracy from 55
  to 59/63; that gain is within noise (Holm p 0.16).
- **Cloud fallback when Jev is unreachable (descriptive, rule 3): GPT-6 Luna, only behind the host guard.** It is
  the more accurate judge, but its mistakes are confident: on the holdout it issued a full refund at p 0.98-0.99 and
  followed an injected "submit for approval" at 0.97-0.99. Jev's mistakes mostly fell back at low certainty.
- **Offline tier: none qualifies.** No local judge met the preregistered rule (wrong automatic upper bound < 10% at
  >= 30% coverage with guards). The best, tev1 4B, made 3 wrong automatic decisions at 44% coverage (upper bound 13%).
  The first pass's tev1 0.8B recommendation does not hold: 35/63 and 14 wrong automatic on the holdout.
- **Within noise at these sample sizes:** Jev vs Luna vs Sol on accuracy (dev and holdout); Jev vs Luna vs Sol on
  wrong automatic decisions; every intervention's effect on accuracy; Luna vs Sol. **Not within noise:** Jev is more
  accurate than every local judge on dev (Holm p <= 0.03); on the holdout Jev beats every local judge on wrong automatic
  decisions except nimble (p 0.08) and on accuracy except nimble and tev1 4B (p 0.16).
- **What would change this:** an OpenAI Decisions API that returns HTTP 200 and passes rule 1 (the arm probes on every
  run; today it returns 403 "not enabled for this user"); a Jev release whose p95 or accuracy moves; a larger holdout
  (at 63 cases only differences above about 8 points are detectable); or live-traffic receipts that disagree.

## What the first pass got right and wrong

The full table is [changes.json](changes.json) (20 claims, each with its evidence), rendered in the report. In short:

- **Right:** Jev's accuracy (85-86/90 in all seven runs), Sol's (88 in all seven), every local judge's (identical in all
  seven runs), Laya's 35/60, costs to the cent, and that Luna's latency is OpenAI server time (95% of the gap to Jev).
- **Wrong:** "Luna was right on all 90" (the first pass scored Luna's *stated* choice; on its own probabilities, which
  the bundle uses, it was 89/90, then 85-89 across six more runs, 86/90 in the validated run, the same as Jev);
  "Luna made no wrong automatic decisions" (it clicked Buy now at 0.96-0.99 in all three validated repetitions);
  "tev1 0.8B has zero wrong automatic decisions from 0.85" (true only under the study rule, which lets a confident "no"
  abstain; the bundle acts on every yes/no answer, giving 12/90); and the automatic rule itself (0.75 on the stated
  choice is not the bundle's 0.90 / 0.20-margin / 3 s gate).
- **Revised:** local latency (host load moved the same answers' medians from -33% to +95% across reruns); priority
  tier (-32%, not -14%); side-effect failures are an instruction-wording problem shared by every judge, Luna included.

## Dev split (90 cases, 3 repetitions; screen, not a finding)

Primary policy `bundle-read-shortcut`. Accuracy is the per-case majority over repetitions; wrong automatic and coverage are per repetition. Latency ranges are per-repetition medians / p95s.

| Judge | Accuracy (majority, 95% CI) | Rep range | Wrong automatic (95% CI) | Coverage | p50 / p95 | $ / 1M decisions |
|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | 86/90 (89–98%) | 85–86 | 2–2 per rep | 69–72 | 1049–1144 / 1936–2446 ms | $34.95 |
| gpt-6-luna+sideeffect-clause | 88/90 (92–99%) | 87–88 | 1–2 per rep | 70–72 | 1024–1086 / 1816–2347 ms | $37.86 |
| gpt-6.1-sol | 88/90 (92–99%) | 88–88 | 1–1 per rep | 52–66 | 2239–2453 / 3590–4299 ms | $750.88 |
| jev-1.13 | 86/90 (89–98%) | 85–86 | 2–3 per rep | 69–69 | 152–163 / 213–231 ms | $15.91 |
| jev-1.13+sideeffect-clause | 89/90 (94–100%) | 88–89 | 1–1 per rep | 66–67 | 148–159 / 215–221 ms | $17.14 |
| laya-base | 54/90 (50–70%) | 54–54 | 13–13 per rep | 31–31 | 23–29 / 27–34 ms | $0 |
| nimble-9b | 74/90 (73–89%) | 74–74 | 11–11 per rep | 69–69 | 171–252 / 204–425 ms | $0 |
| qwen3-0.6b | 54/90 (50–70%) | 54–54 | 19–19 per rep | 47–47 | 42–52 / 47–67 ms | $0 |
| qwen3-4b | 76/90 (76–91%) | 76–76 | 8–8 per rep | 58–58 | 141–183 / 152–207 ms | $0 |
| qwen3-8b | 77/90 (77–91%) | 77–77 | 11–11 per rep | 74–74 | 160–190 / 189–207 ms | $0 |
| qwen3-8b+sideeffect-clause | 79/90 (79–93%) | 79–79 | 10–10 per rep | 73–73 | 140–184 / 190–260 ms | $0 |
| tev1-0.8b | 67/90 (65–82%) | 67–67 | 12–12 per rep | 38–38 | 39–46 / 45–64 ms | $0 |
| tev1-0.8b+sideeffect-clause | 66/90 (63–81%) | 66–66 | 12–12 per rep | 37–37 | 36–42 / 41–81 ms | $0 |
| tev1-4b | 71/90 (69–86%) | 71–71 | 11–11 per rep | 62–62 | 119–147 / 153–158 ms | $0 |

## Holdout (63 fresh cases, preregistered, 3 repetitions)

Preregistered in [evals/judge_bench/holdout/PREREGISTRATION.md](../../../evals/judge_bench/holdout/PREREGISTRATION.md) (commit `aec2457`, pushed before any judge saw a case); run from clean commit `2ff4b15`. Every arm answered every case in every repetition.

| Judge | Accuracy (majority, 95% CI) | Rep range | Wrong automatic (95% CI) | Coverage | p50 / p95 | $ / 1M decisions |
|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | 60/63 (87–98%) | 60–61 | 2–3 per rep | 51–51 | 987–1048 / 1758–1898 ms | $40.46 |
| gpt-6-luna+sideeffect-clause | 61/63 (89–99%) | 60–62 | 0–1 per rep | 48–49 | 1006–1028 / 1570–1681 ms | $43.36 |
| gpt-6.1-sol | 62/63 (92–100%) | 61–62 | 0–1 per rep | 41–45 | 2011–2263 / 3603–4664 ms | $894.37 |
| jev-1.13 | 55/63 (77–93%) | 55–56 | 1–1 per rep | 40–41 | 152–166 / 216–222 ms | $18.41 |
| jev-1.13+sideeffect-clause | 59/63 (85–98%) | 58–60 | 1–1 per rep | 37–39 | 148–158 / 213–294 ms | $19.64 |
| laya-base | 28/63 (33–57%) | 28–28 | 12–12 per rep | 23–23 | 25–36 / 31–45 ms | $0 |
| nimble-9b | 49/63 (66–86%) | 49–49 | 8–8 per rep | 49–49 | 193–293 / 208–313 ms | $0 |
| qwen3-0.6b | 27/63 (31–55%) | 27–27 | 16–16 per rep | 28–28 | 41–48 / 46–55 ms | $0 |
| qwen3-4b | 38/63 (48–71%) | 38–38 | 16–16 per rep | 38–38 | 142–185 / 166–219 ms | $0 |
| qwen3-8b | 45/63 (59–81%) | 45–45 | 14–14 per rep | 50–50 | 129–194 / 142–297 ms | $0 |
| qwen3-8b+sideeffect-clause | 43/63 (56–78%) | 43–43 | 14–14 per rep | 48–48 | 128–173 / 152–245 ms | $0 |
| tev1-0.8b | 35/63 (43–67%) | 35–35 | 14–14 per rep | 29–29 | 36–48 / 42–55 ms | $0 |
| tev1-0.8b+sideeffect-clause | 33/63 (40–64%) | 33–33 | 14–14 per rep | 27–27 | 41–155 / 44–761 ms | $0 |
| tev1-4b | 47/63 (63–84%) | 47–47 | 11–11 per rep | 43–43 | 103–149 / 124–190 ms | $0 |

## Part 1 findings

**Reproduction and variance.** The unchanged first-pass harness was rerun three times from a clean worktree
(`firstpass-repro/`), then the new runner ran three more repetitions (`dev/`). Local judges (temperature 0 through the
bundle's OllamaBackend; no temperature sent to Ollama's System One endpoint or Laya) returned identical answers in all
seven runs. Jev (no temperature or seed sent) changed its answer on 2 of 90 cases across runs; GPT-6.1 Sol on 0; GPT-6
Luna on 7 (no sampling control is available at reasoning effort `none`). Luna's request bodies were verified
byte-identical between the two harnesses.

**Harness audit.** (1) The first pass scored Luna/Sol by their *stated* choice; the bundle takes the argmax of the
probabilities. Luna's stated choice contradicted its own probabilities in 13 of 840 choice answers. (2) The
`reason`-sentinel workaround is correct and now unit-tested both ways; the bundle defect (its local backend can never
answer a literal `reason` option) is unchanged. (3) Qwen's order-flip count is 0 by construction and is now flagged as
not comparable. (4) Token and cost accounting recompute to the cent. (5) p95 used banker's rounding and was one rank low
on the 30-case slices; the headline n = 90 values were unaffected. (6) "Automatic" was the study's rule, not the
bundle's; everything is now scored under the bundle's read-shortcut gate, with the CUA gate, the study rule and a
cutoff sweep alongside. An independent review then found and we fixed two blockers in the new code before the holdout
ran (a pairwise unit that dropped invalid cases, and `--append` deleting rows).

**Label audit** (`label-audit/`). Two blind reviewers (separate agents that saw only the cases and instructions)
re-labeled all 90 dev cases: Cohen's kappa 1.00 with each other and with the frozen labels, so no label is corrected.
`cua-18` (purchase) and `cua-19` (delete) are defensible but depend on a rule the instructions do not state (both
reviewers flagged them); `fresh-cua-09` (publish; the observation says it "sends externally", and sending is an
explicit trigger) and `search-11` (the size check runs after inference) are real failures. The holdout labels were
double-reviewed the same way before any judge saw them (kappa 1.00). All reviewers are Anthropic models.

**Failure RCA** (failure-mode matrix in the report). *Acted on a side effect* is the one class every judge shares; its
root cause is instruction wording (the dev instruction names writing and sending, not purchase or delete), shown by I1
removing all of Jev's side-effect errors on dev and I2 removing them for everyone. *Accepted wrong code* dominates small
local judges (10 of tev1 0.8B's 23 errors); its cost is amplified by policy, because the bundle acts on every yes/no
answer. *Injection following* is local-only on dev, but on the holdout Jev deferred when an injected note pushed it
toward `reason` (a safe failure) and Luna followed an injected "submit" with confidence. *Under-deferred* errors for
Luna trace partly to probability extraction: its stated probabilities often put the fallback second while its stated
choice is the fallback.

**Interventions** (pre-declared in [INTERVENTIONS.md](../../../evals/judge_bench/INTERVENTIONS.md) before measuring).
On dev (screen): I1 confirmed for Jev only; I2 confirmed for every applicable judge; I3 (a 0.90 gate on yes/no answers)
confirmed for Jev, nimble and Qwen3 8B but cost small judges more than 10 points of coverage. On the holdout
(preregistered): I2 confirmed for all 9 applicable judges; I1 confirmed for Luna (targeted errors 4 to 2), not for the
local judges, and not applicable to Jev (its side-effect picks fell below the 0.90 gate); I3 not confirmed.

**Latency RCA** (`latency/`). Cloud: server time is 95% (Luna) and 98% (Sol) of the median gap to Jev; the client adds
about 1 ms; TCP round trip is about 13 ms to both hosts; a fresh connection adds 30-35 ms for everyone. Priority tier cut
Luna's median by 32% in one 20-request window. Local: prefill dominates (decode is one token); cold starts cost 1.4-2.0 s;
Ollama serves one request at a time here (`NUM_PARALLEL` 1), so local throughput stays flat as requests in flight rise
from 1 to 8 while Jev scales to 43 requests/s. Ollama 0.35's prompt cache made repeated prompts look 4x faster, so every
probe uses a per-request nonce.

## Reproduce

```bash
set -a; . ~/.amplifier/keys.env; set +a
PYTHONPATH=src:. python3 evals/judges.py --split dev --reps 3                 # about 1 hour, about $0.50
PYTHONPATH=src:. python3 evals/judges.py --split holdout --budget-usd 3       # refuses unless the preregistration is committed
PYTHONPATH=src:. python3 evals/judges.py --replay docs/evidence/2026-09-30-judge-benchmark/holdout/requests.jsonl --out /tmp/x
PYTHONPATH=src:. python3 evals/judge_bench/report.py docs/evidence/2026-09-30-judge-benchmark
```

`tests/test_judge_replay.py` recomputes every committed `summary.json` here byte for byte from its `requests.jsonl`.
The dev run's raw rows came from commit `4cefdf2`; its summary is recomputed with the current scorer (the review fixes
changed summaries, not requests).

## Limits

Constructed text decisions, 90 dev and 63 holdout, labeled by Anthropic models. Not live browser tasks, tool
executions or production traffic. GPT-6 Luna and Sol probabilities are self-reported, so their calibration (ECE) is
not meaningful. Local latency is a property of this host at the time (load recorded per arm block in `run.json`). The
first-pass screens and this holdout were authored for this bundle's instructions; the side-effect rule is explicit in
the holdout's labeling guide but not in the judges' instructions, by design (it is the I1 treatment).

## Files

`dev/`, `holdout/`: `manifest.json` (cases, hash), `run.json` (commit, arms, prices, determinism, host load, Decisions
API probe), `requests.jsonl` (every request and answer), `summary.json` (all metrics, contrasts, decisions) ·
`firstpass-repro/`: the first pass plus three reruns of its harness · `label-audit/` · `latency/` · `changes.json` ·
`index.html` (generated by `evals/judge_bench/report.py`).
