# holdout-v3 smoke triage (S1, plain Sonnet, 1 session per scenario)

Read-only inputs: `~/dev/afast-paired/holdout-v3-smoke/` (60 sessions, 630 graded turns, 573 passed = mean turn-pass 0.912).
31 scenarios had at least one failed turn. Every failed turn was read (prompt, the agent's final message, the turn-N workspace
snapshot, the failing check, and for `cmd` / `go` / `pytest` checks the grader's own failure line) and classified:

* **GENUINE** - the agent made a real mistake the check correctly caught. Not touched.
* **DEFECT-prompt** - the prompt never states what the check requires (or states something the check contradicts). The prompt now says it.
* **DEFECT-check** - the check rejects a correct answer (format, order, wording, example choice the prompt left open). The check now accepts every correct answer.
* **CASCADE** - fails only because an earlier turn's output is carried forward (cumulative hidden tests / earlier file); no separate verdict.

Rules applied: never loosen a check so that a wrong answer passes (each loosened check was re-run through the scenario validator:
start state fails, reference passes, every wrong variant fails; two wrong variants that were not actually wrong were repaired),
never tune to the agent's wording, no model calls. All scenario code ran through `scripts/memguard.py` (`--cap-gb 4
--grader-timeout 300`), serial, `nice -n 10`, `memory_pressure` >= 50 % free.

**Re-grade.** `regrade_smoke.py <id>` re-grades each smoke turn snapshot (`turn-snapshots/tN.tar.gz` + the turn's final message) with
the new scenario file. A DEFECT-prompt fix cannot change the old outcome (the agent answered the old prompt), so those turns stay
failed in the re-grade; the table shows the effect of the check fixes only. Turn-pass over the 60 scenarios: **0.912 -> 0.961**
(per-scenario mean; 573/630 -> 603/630 turns). The agent's answers did not change; only the checks did.

## The five flagged scenarios

| scenario | smoke | re-grade | turn | verdict | evidence | fix |
|---|---|---|---|---|---|---|
| py-dotdsl | 6/12 | 6/12 | 4 | DEFECT-prompt | prompt showed `to_dot` lines as inline code with ONE leading space (`` ` foo="1";` ``); hidden test wants two. Agent emitted one space (`f' {key}="..."'`) | prompt: "every line between the braces is indented by exactly two spaces", examples shown with two spaces (kept from the interrupted attempt, verified) |
| | | | 5, 6, 8, 9, 11 | CASCADE | every later check re-runs `hidden_dot_test.py` (cumulative) | none |
| db-evolution | 8/13 | 8/13 | 2 | GENUINE | answered 005,009,010,011,012,003,004,006,007,008,002,013,001; "smallest ready id first" gives 005,009,004,010,... (004 is ready right after 009; 002 right after 006) | none |
| | | | 3 | DEFECT-prompt (+ cascade of 2) | "the apply order from the previous answer" while the check wants the correct order | "the correct apply order, by the rule in the previous question" |
| | | | 5 | GENUINE (cascade of 2) | `tables` lists ids in the agent's own wrong apply order; `conflicts`, `destructive` were right | none ("in apply order" is the rule of turn 2) |
| | | | 6, 7 | GENUINE (cascade of 2) | prompts say "the correct order"; agent reused its wrong one | none |
| onboarding-guide | 7/10 | 9/10 | 1 | GENUINE | "10 targets" but lists 11 names; the Makefile has 11 documented targets | none |
| | | | 6, 7 | DEFECT-check | prompt gives no row order; agent sorted alphabetically, every row text exact (`scripts/*`, `api/ ...`) | tables compared as sets of rows (order-free, content exact). Same latent defect in turn 5 (services) fixed too |
| jpointer-regress-review | 7/10 | 10/10 | 3 | DEFECT-check | `file_regex _RE_ARRAY_INDEX.fullmatch(` required; agent anchored the regex (`'^(?:0\|[1-9][0-9]*)$'`), hidden `test_index.py` passes | regex removed (hidden tests discriminate; wrong variant still fails). Same over-specific fix-shape regexes removed from turns 5, 6 (passed in smoke) |
| | | | 7 | DEFECT-check (grader) | the "put each merged change back" step used `perl` substitutions that only match one exact spelling of each fix, so any other correct fix made the grader's mutation a no-op and the check failed | hidden `_mutate.py` (ast based) swaps the merged `_RE_ARRAY_INDEX`+`get_part`, `unescape`, `contains` in whatever form the fix took; pytest must fail on each mutant |
| | | | 9 | DEFECT-check | REVIEW.md had to contain `fullmatch`; the agent's fix (anchors) is described correctly | `fullmatch\|anchor` |
| validators-regress-review | 8/11 | 8/11 | 3 | DEFECT-prompt | the exception rule (only ValueError/TypeError/UnicodeError convert) is not in the docstring or docs/install_and_use.md; prompt asked for it "as documented"; the agent correctly read the code (`except Exception`) | prompt states the intended rule and says the docs do not spell it out |
| | | | 4 | DEFECT-prompt + check | consequence of 3 (agent never saw a deviation in the except clause); check also demanded a `ZeroDivisionError` snippet | check: any non-converted exception class + a phrase saying it should propagate / is converted too broadly; reference passes, the agent's answer still fails (it never flagged the clause) |
| | | | 10 | DEFECT-prompt + check | REVIEW.md had to contain `818` (a number never requested), `RAISE_VALIDATION_ERROR=0` and `ZeroDivisionError` (inputs the prompt leaves open) | prompt: "the Summary states how many existing tests passed on the merged code"; env input = any non-`True` value; exception = any non-converted class |
| | | | 5-8 | latent DEFECT-check (passed) | `file_regex` demanded one spelling of each fix (`except (...) as exp:`, `== "True"`, `if message:` ..., `if k != 'func'`) | removed; hidden `test_exc.py` extended with TypeError and UnicodeError cases, and the turn-5 wrong variant (which omitted UnicodeError, a subclass of ValueError and therefore behaviourally identical) now omits TypeError |

## The other 26 scenarios with a failed turn

| scenario (smoke -> re-grade) | turn | verdict | evidence | fix |
|---|---|---|---|---|
| bank-recon (8/10 -> 8/10) | 3, 9 | DEFECT-prompt (9 cascades) | check wants integer counts for `matched`, `amount_mismatch`, `bank_only`, `ledger_only`; prompt said only "bank_only (refs only in the bank file)"; agent wrote lists (turn 9 says "one-sided counts") | prompt: "the integer counts ..." |
| black-pipeline-explain (12 -> 14) | 6 | DEFECT-check | answer showed the exploded list inside an indented markdown block; regex wanted `]` at column 0 | `\n\s*\]` |
| | 13 | DEFECT-check | required `class A`, `def g` (the reference's example names, not in the prompt) and the repr form `'a = 1\n\n\nb = 2'` or the words "two blank lines" (agent: "clamped down to 2") | any class/def names; repr, newline or "(two\|2) blank lines" / "clamped to 2" |
| cli-manual (8 -> 10) | 3 | DEFECT-check | prompt: "default value in backticks (`-` when there is none, `off` for flags ...)"; agent put `-`/`off` in backticks, grader wanted them bare (but a real default `-` of `--output` is in backticks) | `-` / `off` accepted bare or in backticks; real values still need backticks |
| | 9 | DEFECT-check | grader wanted literal `.B --dry-run`; agent wrote correct roff `.B \-\-dry-run` | `\-` normalised to `-` |
| click-flow-explain (9 -> 10) | 6 | DEFECT-check | precedence order `COMMANDLINE.{0,80}ENVIRONMENT.{0,80}DEFAULT_MAP` on one line; agent wrote a numbered list with longer text between | `(?s)` and 500 chars |
| config-reference (9 -> 9) | 6 | GENUINE | `x-env` table lists 6 of the 8 entries (missed `database.url`, `logging.level`) | none |
| | 9 | DEFECT-prompt | prompt never said how keys are written in the docs table; agent wrote bare keys and a script for that; the grader fixture uses backticked keys | turn 3 prompt: "key is the key name in backticks" |
| cssselect-xpath-explain (9 -> 10) | 3 | DEFECT-check | required the literal `self::a` (the reference's `prefix='self::'` example); agent explained `prefix` correctly with another example | `prefix` followed by an axis/prefix explanation |
| data-dictionary (9 -> 9) | 9 | DEFECT-prompt | "(all six value columns)" read as "only those six"; the check (and turn 2's "one row per CSV column") wants all nine | prompt says one row per CSV column: the three id/date columns and all six value columns |
| dateutil-calendar-review (8 -> 10) | 1 | DEFECT-check | required `relativedelta.py`, `rrule.py` ... with the `.py` suffix (only there so the prompt's own words could not satisfy the check) | one role keyword per module (arithmetic, recurrence, easter date, helper, parser, tzinfo, tarball/zoneinfo, shared base) |
| | 8 | DEFECT-check | `^def test_` min_count 4, prompt asks for tests that fail on "ANY ONE of the three diffs" | 3 |
| docs-corpus (9 -> 9) | 9 | DEFECT-prompt | the `index.md` pages the agent was told to create in turn 7 are section pages under turn 1's definition, so linking them removes all orphans; reference ignores them | prompt: original pages only, index.md neither counted nor a link source |
| faker-nonutf-cli (8 -> 8) | 7 | DEFECT-prompt | prompt refers to "the `_encode_for_output` helper"; no earlier prompt names it; agent called its helper `_safe_for_output` and said so | turn 1 prompt asks for `_encode_for_output(value: str, output: TextIO) -> str` in faker/cli.py |
| fleet-fuel (8 -> 9) | 4 | DEFECT-prompt | "rounded to 2 decimals" is ambiguous: float `round()` gave 15730.54, half-up gives 15730.57 (agent); 3 cents over 162 fills | rule stated everywhere (README, turn 4 prompt): rounded half up; reference computed with Decimal ROUND_HALF_UP (turn 4 expects 15730.57, monthly table recomputed) |
| go-bowling (11/14, unchanged) | 6 | GENUINE | `Roll(6)` after `5` in the tenth frame returns nil (hidden_errors: `tenth frame over ten`) | none |
| | 7, 10 | CASCADE of 6 | hidden_errors_test is cumulative | none |
| go-sublist-docs (8 -> 9) | 7 | DEFECT-check | `^// Contains .*empty` on one line; agent's multi-line doc comment mentions the empty list on a later `//` line | regex spans the comment block |
| gradebook (8 -> 9) | 1 | DEFECT-check | answer "10 students each in sections A, B, and C" (correct); regex wanted `A: 10` style | label-first, number-first or "N each in ... X" |
| honcho-process-review (7 -> 8) | 5 | DEFECT-check | required the example names `web-api`, `worker` (the prompt only says "a concrete two-line Procfile"); agent used `web-socket`, `clock-worker` | hyphen/dash or a hyphenated name before a colon |
| isodate-regress-review (9 -> 10) | 5 | DEFECT-check | required `Duration(days=-1)`, `'P1D'` and the identifier `tdelta`; agent demonstrated the same sign bug with `Duration(days=-5)` -> `'P5D'` and explained it as "only years/months are checked" | any `Duration(x=-n`, an unsigned `'P...'` output, `-P...` and the same root cause in other words |
| jsonpatch-ops-explain (8 -> 10) | 4 | DEFECT-check | `non-existent object 'z'` (key `z` chosen by the reference) | any quoted key |
| | 5 | DEFECT-check | required JSON spelling `"op": "remove"`; agent showed the Python repr `{'op': 'remove', ...}` | either quote style |
| lib-reference (9 -> 10) | 9 | DEFECT-check | module-summary rows compared in the reference's (non-alphabetical) order; prompt gives none | compared as a set of exact rows |
| pluggy-calls-explain (8 -> 8) | 3, 8 | DEFECT-prompt | checks need the marker strings `W before`, `C tryfirst`, `B`, `A`, `W after`; prompts only said "prints each plugin's marker" | both prompts list the markers |
| py-grep (15 -> 16) | 13 | DEFECT-check | required `_expand_flags`, `_line_matcher`, `_read_lines`; turn 11 only says "private helper functions (names starting with an underscore)" | at least three underscore-prefixed identifiers |
| py-linked-list-docs (8 -> 9) | 8 | DEFECT-check | regex `leaves? the original`; agent: "leaving the original list's nodes untouched" | "leaving", "untouched", "new list" variants |
| pyg-util-regress-review (10 -> 12) | 9 | DEFECT-check | `file_regex` demanded the fix text `if x and not x.startswith('-')][-1]`; agent's `x[0] != '-'` passes the hidden test | removed (hidden test discriminates) |
| | 11 | DEFECT-check | REVIEW.md had to contain `'True'`, `['a', 'b']`, `-w` (inputs the prompt leaves open; agent used `'YES'`, `['1 2']`, `perl -e`) | per-section checks: a list literal in get_list_opt, a mixed-case quoted value in get_bool_opt, a flag in shebang_matches. Reference wrong variant for turn 11 repaired (its `-q` example was equally correct) |
| release-fragments (8 -> 9) | 1 | DEFECT-check | "10 feature, 14 bugfix, 6 doc, 6 misc" (correct) vs regex label-first only | label-first or number-first |
| rich-text-split-explain (10 -> 11) | 4 | DEFECT-check | `Span(0, 5, 'bold')` with exact spaces; agent printed `Span(0,5,'bold')` | whitespace tolerant (also the turn 3 / turn 6 Span regexes) |
| schedule-semantics-review (8 -> 10) | 7 | DEFECT-check | REVIEW.md had to contain `2024-01-01` or `2024-01-08` (the reference's dates) | any ISO date or clock time or datetime( |
| | 8 | DEFECT-check | `^def test_` min_count 4 for three diffs | 3 |
| tomlkit-roundtrip-explain (9 -> 10) | 3 | DEFECT-check | required `# top` / `# inline`, comment texts of the reference's own sample document (the prompt says "a document with comments") | the word "comment" (+ existing preserved/untouched fact) |

## Not changed / follow-up

* 37 scenarios carry `file_regex` checks on source files (docstring/comment checks and some fix-shape regexes, e.g. isodate
  turn 6 `tduration\.tdelta < timedelta\(0\)`, falcon-regexconv, bottle-etag). None failed in the smoke; they were not edited. A
  later round could apply the jpointer / validators treatment (rely on hidden behaviour tests) to the fix-shape ones.
* The agent's old answers to DEFECT-prompt turns cannot be re-graded into passes; only a new run shows their effect.
* `PREREGISTRATION-holdout-v3.md` is untracked and still quotes the pre-triage panel sha256; it must be updated before it is committed.
