# Finding: the read-shortcut state can cut the actual task out of the judge's view

Found while building the trace split (2026-10-01). Not fixed here; reported for the bundle owners.

**What happens.** `state.build_state` (src/amplifier_fast_decisions/state.py:67-123) gives the task message at most
about half of `max_state_chars` and keeps its *beginning* (`text[:middle]`). SWE-bench-style prompts put several
hundred characters of operating rules first and the GitHub issue after them. In every logged SWE-bench session in
the trace pool the state budget was 2,048 characters (the five logged state numbers match the rebuild exactly), and
the task text that reached the judge ends after about 746 characters, inside the rules. The judge never saw the
issue.

**Where 2,048 comes from.** `Policy.max_state_chars` defaults to 12,000 (contracts.py:950). The CLI sets 2,048 when
the backend is `ollama` (cli.py:741), and the benchmark profiles that produced these sessions ran at 2,048 for every
judge (Jev, Laya and Ollama arms alike). Production profiles at the 12,000 default would keep far more of the task,
so how often this happens outside the benchmark is not measured here.

**Effect on this study.** Both blind reviewers flagged it independently: with no issue text, choosing between several
plausible file windows is often impossible, so many cases are correctly labeled `reason`. That is what the judge
really saw, so the cases are kept as they are; results on the trace split describe judges operating at a 2,048-char
budget with head-truncated tasks.

**Possible fixes (not evaluated).** Keep the head and the tail of a long task message; or strip known boilerplate
before budgeting; or raise the budget for backends that can afford it. Each would need its own measurement.
