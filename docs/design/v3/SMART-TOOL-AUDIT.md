# Smart Tool + harness-agnostic audit: fast-decisions @ origin/main 8e7faf3 (PR #62)
Read-only. No paid calls. Worktree ~/dev/fd-audit (removed after).

## Method / caveat
The microsoft/amplifier-smart-tools clone (HEAD 990d243) contains only spec/*.md (README, manifest, packaging,
structure, invocation, examples); NO conformance/ directory exists on main, and the installed smart-tool-creator
CLI exposes only manifest/init/add-smart-capability (no validate/check). So "conformance" below = manual check
against spec/manifest.md, packaging.md, structure.md, invocation.md. A kit run was NOT possible.
Ran: `amplifier-fast-decisions manifest|--help|select --help|diagnose --offline`, afast --help,
unittest tests.test_smart_tool (18 OK).

## Pass/fail
| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1a | smart-tool.json at dist root, keys manifest/cli_argv/deterministic_smoke | PASS | smart-tool.json:1-5; cli_argv resolves to [project.scripts] pyproject.toml:44 |
| 1b | Exactly one SMART_TOOL.md, shipped in package | PASS | src/amplifier_fast_decisions/SMART_TOOL.md; pyproject.toml:52 package-data |
| 1c | Frontmatter fields (format, name, version, description, use_cases, platforms, requires), version == pyproject | PASS | SMART_TOOL.md:2-33; version 0.1.0 both |
| 1d | --help renders skill_content, Skill directory, Repository, Capabilities [deterministic]/[model-backed], skill_resources, per-capability --help; -h terse | PASS | smart_cli.py:54-56; output verified |
| 1e | AI capability exists, model internal, caller gets result only | PASS (narrow) | select/search/cua, smart_tool.py:316,440,448 |
| 1f | Offline conformance kit run | NOT RUN | kit not in spec repo / creator CLI (see caveat) |
| 1g | Manifest not parsed-by-heading, <500 lines | PASS | 173 lines |
| 2a | Library API + thin CLI | PASS | smart_tool.py (select async); smart_cli.py 127 lines |
| 2b | `afast decide ...` exists | FAIL | afast subcommands: demo serve export doctor configure bench rubric efficiency savings hooks (cli.py:895-1042). No `decide`. Portable verb is `amplifier-fast-decisions select` |
| 2c | The PR #62 decision (start-tier simple/complex, price gate, effort tier) usable outside Amplifier | FAIL | Lives only in loop-fast-decisions orchestrator (behaviors/fast-decisions.yaml:27-110). smart tool = bounded read/list select, search, cua (SMART_TOOL.md:43-46 says it does not decide anything else). Claude Code only gets waste-guard hooks (claude_hook.py:1-25), not routing |
| 2d | Claude Code / Codex / OpenCode / Amplifier skill+evidence | PASS (weak) | install-skill smart_tool.py:56; skills/amplifier-fast-decisions/SKILL.md; docs/SMART-TOOL.md:78-86 table (2026-09-20, commit 56799fb, manifest+describe only, deterministic, no `select`) |
| 2e | Copilot CLI | FAIL | `copilot` only in HARNESSES telemetry tag (smart_tool.py:41); SKILL_HOSTS has no copilot (line 42); no doc, test, evidence |
| 2f | Evidence directory referenced exists | FAIL | docs/SMART-TOOL.md:86 cites "harness-smoke evidence directory"; none in tree (no docs/evidence/*smart*/harness*); only forge evidence for Amplifier (docs/evidence/2026-09-27/forge, 2026-09-29-forge) |
| 2g | Cross-OS CI | PASS | tests.yml:83-86 matrix ubuntu/macos/windows |
| 3a | behaviors/fast-decisions.yaml == registry yaml == docs table (price_gate, session, cheap medium, read_shortcut off, jev) | PASS | yaml:43-49,60-62,88-89; registry yaml:34-53,79-89; CONFIGURATION.md:12-27; tests/test_composition.py:100-113 (fast-decisions.yaml only) |
| 3b | Smart tool uses shipped defaults | N/A-by-design / DRIFT | Smart tool has hardcoded own defaults: score>=.90, margin>=.20 (smart_tool.py:407), timeout 10-500 ms hard cap, default 500 (smart_tool.py:352,318) vs shipped orchestrator timeout_ms 3000 (yaml:48); model jev-1.13.0 hardcoded (SMART_TOOL.md:86). No price gate / tier / effort concept. Separate config namespace FAST_DECISIONS_JUDGE, not shared with orchestrator |
| 3c | bundles/active.yaml & active-routing.yaml (used by `afast configure --mode active`, cli.py:671-700) carry PR #62 defaults | FAIL | bundles/active.yaml:28-33 backend ollama, timeout 500, no model_routing; active-routing.yaml:31-35 same. Test pins the OLD values (test_composition.py:384-399: ollama, 500, `assertNotIn model_routing`). `afast configure --mode active` therefore yields a config that contradicts "Jev judge/price gate/session scope" defaults |
| 4a | Judge backend choice documented | PARTIAL | runtime.py:356 accepts jev,deterministic,ollama,mlx,hosted/gateway,laya,anyjev,unavailable; smart tool select accepts laya,local/ollama,jev (SMART_TOOL.md:81); `configure --backend` only jev/deterministic/ollama (cli.py:928). Three different lists |
| 4b | Clef as selectable judge | FAIL | clef only in evals/judges.yaml, tests/test_judge_*.py, evidence/2026-10-04-clef-judges (post-hoc benchmark arm); not in runtime.py or smart tool |
| 4c | Host model / effort / gates | PARTIAL | Only editable by hand in YAML (by_tier docs CONFIGURATION.md:76-95; price_gate :140-185). start_model hardcoded claude-sonnet-5 (yaml:80). No CLI/env surface, no user settings overlay doc |
| 4d | `afast doctor` validates config | FAIL | doctor (cli.py:231-345) checks imports, price gate for 2 hardcoded hosts or AFAST_HOST_MODEL, TYPESAFE key presence, server probes. It never loads/validates the effective behavior config (no Policy.from_config), never reports chosen backend/judge, scope, effort, or smart-tool consent (FAST_DECISIONS_ALLOW_EXTERNAL_STATE). Smart `diagnose` (smart_tool via diagnose --offline) reports installation + telemetry only, not config |
| 5 | Config drift across yaml/docs/smart tool/tests | FAIL (see list) |

## Drift list (file:line)
1. bundles/active.yaml:28-33, active-routing.yaml:31-35 vs behaviors/fast-decisions.yaml:43-48 (backend, timeout, allow_external_state, no routing block). Test enshrines it (test_composition.py:384-399).
2. Timeouts: smart tool 500 ms max (smart_tool.py:352) vs shipped 3000 ms (yaml:48) vs CONFIGURATION.md:45 default 750 with no mention that shipped is 3000 in the "Library vs shipped" table (:14-27).
3. CONFIGURATION.md shipped-defaults table (:14-27) omits timeout_ms, allow_external_state, cheap_max_workspace_files 300, start_model.
4. Manifest requires list (SMART_TOOL.md:19-31) says Jev default; hook in same behavior is backend: deterministic (yaml:191) - fine but undocumented in smart tool docs.
5. Registry yaml vs fast-decisions.yaml tested only for the latter (test_composition.py:100-113); no parity test.
6. docs/SMART-TOOL.md:199-201 claims CI cross-OS (true, tests.yml:83) but :86 cites non-existent evidence dir; harness table dated 2026-09-20 predates PRs through #62 and only exercises manifest/describe.
7. Evidence reference in yaml:57 `docs/evidence/2026-10-05-effort-control/RESULT.md` exists; yaml:90/CONFIGURATION cite 2026-10-06-effort-control-fable too: OK.

## Prioritized fix list
P0  Decide the product line: is the "decision model" (start-tier + price gate + effort) a smart-tool capability? If yes, add library fn + `amplifier-fast-decisions decide` (and optional `afast decide` alias) that takes task text + host model and returns {tier, model, effort, reason} using the SAME Policy/price_gate/decision_scope code and behaviors/fast-decisions.yaml as source of defaults (load once; no second copy). Update SMART_TOOL.md use_cases/description accordingly. Otherwise state plainly in SMART_TOOL.md and README that the portable tool is read/list select only.
P0  Fix bundles/active.yaml + active-routing.yaml (or deprecate `afast configure --mode active`) and update test_composition.py:384-399; add parity test: behaviors/fast-decisions.yaml == fast-decisions-registry.yaml orchestrator config.
P1  Make `afast doctor` validate the effective config: load behavior/user settings, Policy.from_config, print backend, allow_external_state, decision_scope, price_gate result for the real host model, by_tier, read_shortcut, and warn on judge key/consent missing; make smart `diagnose` call the same function.
P1  Single backend vocabulary + one documented table (jev, laya, ollama/local, mlx, hosted, anyjev, deterministic); decide on Clef (add provider, or document as benchmark-only). Add a "How to configure" section in CONFIGURATION.md: judge, host model, effort, gates, with env/settings precedence.
P1  Replace/refresh harness evidence: commit a docs/evidence/<date>-smart-tool/ directory (the cited one is missing), re-run on current main including a model-backed `select` per harness, and add Copilot CLI (SKILL_HOSTS entry `copilot` -> ~/.copilot/skills or documented path, test, evidence) or remove it from claims.
P2  Obtain/run the real conformance kit when published (none on spec main today); add as CI job. Until then add a local test asserting spec rules (one manifest, version parity, cli_argv resolves, descriptor keys).
P2  Reconcile smart tool thresholds (.90/.20, 500 ms) with a shared config source or document them as intentionally independent in SMART_TOOL.md.
P2  Catalog: no tools/amplifier-fast-decisions/source.json PR evidenced; submit one to microsoft/amplifier-smart-tools-catalog after P0.
