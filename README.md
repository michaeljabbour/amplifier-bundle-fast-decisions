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
| Everyday coding tasks | 0.55–0.61× | 0.38–0.40× | Every task passed |
| Real bug fixes in large projects (SWE-bench Verified) | 1.00× | 0.98× | 13 of 20 fixed vs. 14 of 20 (same setup as standard) |

Compared with standard Amplifier on the same tasks, run at the same time. Ratios are geometric means of per-task
ratios. Everyday tasks: 12 tuning tasks (0.55× / 0.38×, one run each) and 8 unseen tasks run three times each
(0.61× / 0.40×). The unseen-task result met 5 of its 6 preregistered criteria; the significance test fell short
(p = 0.07), so it is not yet confirmed.

**These runs used an expensive default model (Claude Fable 5.1).** With Claude Opus 5.5 as your default, Sonnet is
about 1.3× faster at writing but reads cached conversation at a higher price, so expect mostly a speed gain:
short requests save a little, long ones can cost slightly more. `afast savings` (below) measures it on your own
work.

Full results: [report](docs/report/fast-decisions-report.html) (plain language) ·
[RESULTS-2026-09-24.md](docs/RESULTS-2026-09-24.md) · [study protocol](evals/STUDY-DESIGN.md) §18 ·
[raw summaries with checksums](docs/evidence/2026-09-24/).

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
   on the faster model moves the request to your usual model).
2. **Large projects always get your usual model.** In a folder with more than 300 files, the request runs exactly
   as standard Amplifier would, whatever the decision-maker says. On real bug fixes, starting on the cheaper model
   lost fixes (19 of 30 vs. 23 of 30) and switching up later did not recover them.
3. **Everything is recorded.** Each decision, who made it, and each model call's tokens and cost go to a local
   log (no prompts or file contents) that the dashboard and `afast savings` read.

Design detail: [docs/ORCHESTRATOR-PRIMARY.md](docs/ORCHESTRATOR-PRIMARY.md).

## Who decides

Measured on 90 real issues rated by human experts (SWE-bench Verified): how often each decision-maker picks the
harder of two issues, and how long it takes. 50% is a coin flip.

| Decision-maker | Picks the harder issue | Time per decision | Data leaves your machine |
|---|---|---|---|
| **Jev** (hosted by TypeSafe) · default | 83% | ~0.16 s | The first 2,500 characters of the request |
| Built-in rule · used without a key or if Jev fails | 60% | instant | No |
| Qwen 27B-class model on your Mac (Ollama `qwen:latest`) | 85% | ~2.45 s | No |
| Qwen3 8B on your Mac (Ollama `qwen3:8b`) | 72% | ~0.36 s | No |
| A 27B model on a shared hosted server (RunPod) | 85% | median 0.63 s; 1 in 4 took 5–22 s | To your server |

Switch in `~/.amplifier/settings.yaml` (no bundle edit):

```yaml
overrides:
  loop-fast-decisions:
    config:
      backend: none                 # built-in rule only; nothing leaves the machine
      allow_external_state: false
      # or a local model:  backend: ollama, model: "qwen3:8b", timeout_ms: 3000
```

On the 12 everyday tasks, Jev deciding ran at 0.61× time and 0.50× cost against 0.55× and 0.38× for the built-in
rule, because Jev kept 3 of 12 tasks on the usual model. Jev judges difficulty better; the rule was cheaper on a
set of all-easy tasks. Setup details: [docs/MODEL-SETUP.md](docs/MODEL-SETUP.md) · data paths:
[docs/PRIVACY.md](docs/PRIVACY.md).

## Also included

- **Savings estimate:** `afast savings [--since 7d] [--json]` and the dashboard's savings panel price and time each
  cheaper-model request as if your usual model had done it. Estimates, labeled as such; a negative number means
  routing cost more.
- **Quality grader:** `afast rubric requests.jsonl` scores answers against weighted yes/no questions using Jev.
- **Watch-only mode:** `behaviors/fast-decisions-shadow.yaml` records what would have been decided without
  changing anything.
- **Other assistants:** Claude Code, Codex and OpenCode can call the same decision service as a tool; it suggests,
  it doesn't change how they run ([docs/SMART-TOOL.md](docs/SMART-TOOL.md)).

## Limits

- Tested on one Apple-silicon Mac with the Anthropic provider. Other providers, models and machines may differ.
- The routing checks are confirmed end to end in the Amplifier command line, `amplifier-runtime serve` (the engine
  Studio uses) and the terminal app. Studio's window itself was not driven.
- A model set before a session starts (in settings or with `--model`) looks the same as your default, so it can
  still be routed; a model picked during the session is always respected.
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
