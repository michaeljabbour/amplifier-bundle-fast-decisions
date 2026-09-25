# Fast Decisions

Fast Decisions makes Amplifier faster by asking one quick question at the start of every request: *is this easy
or hard?* Easy requests go to a faster, cheaper model (Claude Sonnet 5). Hard ones, and all work inside large
projects, stay on your usual model. The decision is made once per request, so the AI service's memory of the
conversation is never thrown away mid-request.

Experimental, MIT licensed. Not an official Microsoft or TypeSafe release, and no number here is a guarantee.
Approvals, permissions and tool execution are unchanged: Fast Decisions wraps Amplifier's standard loop rather
than replacing it.

## What it does (measured)

| Kind of work | Time | Cost | Quality |
|---|---|---|---|
| Everyday coding tasks, expensive default model (Claude Fable 5.1) | **0.42×** | **0.50×** | Every scored run passed (24 of 24 vs. 24 of 24) |
| Everyday coding tasks, Claude Opus 5.5 as default | 1.01× (no measurable gain) | 0.98× | Every scored run passed |
| Real bug fixes in large projects (SWE-bench Verified) | 1.00× | 0.98× | 13 of 20 fixed vs. 14 of 20 (same setup as standard) |

Everyday rows: the current default (Jev deciding, one decision per request) on 8 tasks never used for tuning, 3 runs
each, against standard Amplifier with the same default model. The Fable result passed all 6 criteria written down
before the run (faster on 8 of 8 tasks, sign test p = 0.008, 95% interval 0.35–0.50), but on a reused holdout, so it
is not a confirmation (see Limits); a re-run on a fresh 12-task split is pending. The Opus result failed the time
and sign-test criteria. On the 12 tuning tasks the default measured 0.56–0.57× / 0.46–0.48× (Fable) and 0.76–0.83× / 0.82–0.90× (Opus) in
two batches. Ratios are geometric means of per-task ratios. Everyday setups ran back to back in the same batch, always
in the same order (see Limits); bug-fix setups ran at the same time. One everyday run failed on infrastructure and was
retried; the retry is the counted result.

**Who benefits.** Easy requests go to Claude Sonnet 5, so the gain depends on your default model. With an expensive
default it is large. With Claude Opus 5.5 there was no measurable gain on the unseen tasks: the gain seen on the
tuning tasks did not transfer, and on the unseen tasks standard Amplifier on Opus already took 0.85× the time of
standard Amplifier on Sonnet, leaving little headroom. With Opus, keep Fast Decisions for the dashboard and savings view or turn model routing off. On small tasks most
of the gain is the faster model itself: against standard Amplifier switched to Sonnet, Fast Decisions took 0.91× the
time (95% interval 0.77–1.08) and 1.29× the cost on the unseen tasks. The dispatcher's job is keeping hard requests and large projects on your usual model.

Full results: [report](docs/report/fast-decisions-report.html) (plain language) ·
[RESULTS-2026-09-24.md](docs/RESULTS-2026-09-24.md) · [study protocol](evals/STUDY-DESIGN.md) §18 ·
evidence with checksums: [2026-09-24](docs/evidence/2026-09-24/), [2026-09-25](docs/evidence/2026-09-25/).

## Install

One command. It applies to the Amplifier command line, the Amplifier terminal app and Studio, because all three
read `~/.amplifier/settings.yaml`, and to every helper session they start:

```bash
amplifier bundle add --app "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=behaviors/fast-decisions.yaml"
```

- **Decision-maker:** add `TYPESAFE_API_KEY=...` to `~/.amplifier/keys.env` and Jev decides each request.
  Without a key, a built-in rule decides and nothing leaves your machine.
- **Upgrading from an earlier version:** run `amplifier update` once, and remove any older fast-decisions entry
  (`amplifier bundle remove --app <old-uri>`). Keep this entry last in your app list: later entries win.
- **Check it:** run a prompt, then
  `uvx --from git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions afast savings`.
  A dashboard also opens at the start of a session (`afast serve --stop` closes it).
- **Your choice wins:** picking a model yourself during a session keeps every request on that model (verified in
  the terminal app; Studio uses the same engine).
- **Turn it off:** remove the app entry. To keep it but stay fully local, see *Who decides* below.

## How it works

1. **One decision per request.** Before the first model call, the decision-maker judges the request easy or hard.
   That picks the model and thinking level for the whole request; nothing switches halfway (only a provider error
   on the faster model moves the rest of the request to your usual model; the failed call itself is not retried).
2. **Large projects always get your usual model.** When the session's folder holds more than 300 files (not counting
   .git, dependency, virtualenv and build folders), the request runs on your usual model and thinking level, whatever
   the decision-maker says. On real bug fixes, starting on the cheaper model
   lost fixes (19 of 30 vs. 23 of 30) and switching up later did not recover them.
3. **Everything is recorded.** Each decision, who made it, and each model call's tokens and cost go to a local
   log (no prompts or file contents) that the dashboard and `afast savings` read.

Design detail: [docs/ORCHESTRATOR-PRIMARY.md](docs/ORCHESTRATOR-PRIMARY.md).

## Who decides

Measured on 90 real issues rated by human experts (SWE-bench Verified): how often each decision-maker ranks an issue
rated an hour or more of work above one rated under 15 minutes (AUC), and how long it takes. 0.5 is a coin flip. Issues in
between were not included, so everyday accuracy will be lower. Re-run on 2026-09-25; figures reproduced.

| Decision-maker | Picks the harder issue (AUC) | Time per decision | Data leaves your machine |
|---|---|---|---|
| **Jev** (hosted by TypeSafe) · default | 0.83 | ~0.14–0.16 s | The first 2,500 characters of your latest message (for helper sessions, of the helper's instructions) |
| Built-in rule · used without a key or if Jev fails | 0.60 | instant | No |
| Large local Qwen model (Ollama `qwen:latest`, 27.4B parameters, 29 GB) | 0.85 | ~2.2–2.5 s | No |
| Qwen3 8B on your Mac (Ollama `qwen3:8b`) | 0.72 | ~0.36 s | No |
| Qwen3.8 27B on a shared hosted server (RunPod) | 0.85 | median ~0.6 s; 18–25% of calls took 5–24 s | To your server |

Switch in `~/.amplifier/settings.yaml` (no bundle edit):

```yaml
overrides:
  loop-fast-decisions:
    config:
      backend: none                 # built-in rule only; nothing leaves the machine
      allow_external_state: false
      # or a local model:  backend: ollama, model: "qwen3:8b", timeout_ms: 3000
```

The built-in rule alone (no key) measured 0.55× / 0.38× on the 12 tuning tasks and 0.61× / 0.40× on the 8 unseen
tasks (Fable default); its confirmation run met 5 of 6 criteria (p = 0.07). Jev judges difficulty better; the rule
was cheaper on a set of all-easy tasks because it kept fewer requests on the usual model. Setup details: [docs/MODEL-SETUP.md](docs/MODEL-SETUP.md) · data paths:
[docs/PRIVACY.md](docs/PRIVACY.md).

## Also included

- **Savings estimate:** `afast savings [--since 7d] [--json]` and the dashboard's savings panel price and time each
  cheaper-model request as if your usual model had done it, assuming your usual model would already have the
  conversation cached after the first request and charging the cache rebuild when a hard request follows an easy
  one. Estimates, labeled as such; a negative number means routing cost more.
- **Quality grader:** `afast rubric requests.jsonl` scores answers against weighted yes/no questions using Jev.
- **Watch-only mode:** `behaviors/fast-decisions-shadow.yaml` records what would have been decided without
  changing anything.
- **Other assistants:** Claude Code, Codex and OpenCode can call the same decision service as a tool; it suggests,
  it doesn't change how they run ([docs/SMART-TOOL.md](docs/SMART-TOOL.md)).

## Limits

- Tested on one Apple-silicon Mac with the Anthropic provider; routing only sends the faster model to Anthropic
  providers. Other providers, models and machines may differ.
- The routing checks are confirmed end to end in the Amplifier command line, `amplifier-runtime serve` (the engine
  Studio uses) and the terminal app. Studio's window itself was not driven.
- A model set before a session starts (in settings or with `--model`) looks the same as your default, so it can
  still be routed; a model picked during the session is always respected.
- **Reused holdout.** The 2026-09-25 unseen-task run used the same 8 tasks as the 2026-09-24 unseen-task run, and
  the current default was designed after that first run's results were seen. The study protocol
  ([evals/STUDY-DESIGN.md](evals/STUDY-DESIGN.md) §3, §8) spends a holdout once and requires a new split for a changed
  setup, so the Fable 0.42× result is not a confirmation. It is being re-run on a fresh 12-task split (`holdout2`;
  4 of its tasks are longer).
- **Fixed run order and shared cache.** In all three 2026-09-25 batches the setups ran in the same order every time:
  standard on the default model, standard on Sonnet, Fast Decisions, standard on Opus, Fast Decisions on Opus.
  Standard Amplifier always ran first. Runs also share the provider's prompt cache across setups (the first call of a
  run already shows large cache reads), so order can bias both time and cost. `evals/run.py` now shuffles the order
  per repetition (seeded, recorded in the manifest as `invocation.cell_order`; `--cell-order declared` restores the
  old order).
- **Served model per call not recorded.** Those runs did not record which model served each call, only per-batch
  counts (on the Opus unseen-task run, 18 of 24 requests were judged easy and started on Sonnet); the Opus
  conclusions rest on those counts. New runs record per-call requested model and effort and the provider-reported
  model and cost.
- Ten bug-fix issues and eight unseen everyday tasks are small samples. See
  [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) before relying on this in production.

## Development

```bash
uv pip install -e '.[test]'
python3 -m unittest discover -s tests -v     # test suite
python3 -m amplifier_fast_decisions doctor   # environment check
```

Evaluations: [evals/](evals/README.md) · metrics: [docs/BENCH.md](docs/BENCH.md) · events:
[docs/EVENTS.md](docs/EVENTS.md) · all settings: [docs/CONFIGURATION.md](docs/CONFIGURATION.md) · earlier studies
of the previous design: [docs/EVIDENCE.md](docs/EVIDENCE.md) · [CONTRIBUTING.md](CONTRIBUTING.md) ·
[SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
