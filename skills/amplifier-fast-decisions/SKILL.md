---
name: amplifier-fast-decisions
description: "Decide once, at the start of a coding session, which model and effort it should run on (cheaper model only when it is predicted to cost less and the task is small), then optionally launch Claude Code, Codex or Copilot CLI on that choice; also cheap typed decisions: pick one caller-supplied read/list target, search source, or propose a UI action. Use for: which model should I start this session on, cheaper model for an easy task, pick the effort level, route or stay, launch claude/codex/copilot with the right model. Not for arbitrary commands, executing actions, or mid-session model switches. The host keeps approval authority; uncertain decisions abstain."
---

# Fast decisions

Install, then check the setup (it never calls a model):

```bash
uv tool install 'amplifier-fast-decisions[local] @ git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main'
amplifier-fast-decisions doctor
```

`amplifier-fast-decisions --version` should print 0.3.0 or later. If a command below is
"not a valid choice" or `--version` is not recognised, an older copy is first on the PATH:
upgrade it with the install line above (add `--force`), then check again.

Then run `amplifier-fast-decisions --help` and follow it. It stays correct when the tool
changes. Each command has its own: `amplifier-fast-decisions <command> --help`.

**Main flows**

- `decide`: once, before a session starts, answers "run on the cheaper model at medium
  effort, or stay on the host model?" Returns a suggestion; you apply it.
- `launch --harness claude|codex|copilot`: runs `decide`, then starts that harness on the
  chosen model and effort. Add `--dry-run` to see the command without starting it.
- `select`: pick one target from a caller-validated read/list set, or abstain.
  `search` and `cua` follow the same shape (see `--help`).

**Consent.** `decide` and `launch` use the shipped rule decider R*: no model is asked, nothing
leaves the machine, no consent is needed. Opting in to a judge (`--decider jev`, or Cloudflare
Workers AI) and `select` need its API key and `--allow-external-state` (or the saved setting)
before any task text leaves the machine. Without consent they say so and fall back or change
nothing. `doctor` and `--dry-run` never call a model.
