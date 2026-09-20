"""Portable, advisory workspace-action scoring. No specific coding-agent
harness (Claude Code, Codex, OpenCode, Amplifier, ...) is required.

The caller supplies bounded task/context data and eligible read/list targets.
This module consults the existing local model, returns a typed selection or
abstention, and records metadata. It never executes or reads a target.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from importlib import metadata, resources
import json
from pathlib import Path, PurePosixPath
import re
import time
from typing import Any
from uuid import uuid4

from .contracts import Candidate, DecisionRequest, SLOW
from .local_backend import OllamaBackend, PROBABILITY_KIND
from .privacy import scrub
from .telemetry import Emitter, JsonlRecorder

MAX_INPUT_BYTES = 16384
DEFAULT_EVENTS = Path.home() / '.amplifier' / 'fast-decisions' / 'events'
CAPABILITIES = {
    'manifest': ('deterministic', 'Read the installed tool manifest as JSON.'),
    'describe': ('deterministic', 'Describe the input schema, result and calling contract.'),
    'install-skill': ('deterministic', 'Install a minimal Agent Skill for selected local harnesses.'),
    'diagnose': ('deterministic', 'Inspect installation, session integration, local model and viewer health.'),
    'measure': ('deterministic', 'Count observed provider and tool executions across a session tree.'),
    'compare': ('deterministic', 'Compare matched baseline/enabled runs with explicit outcome checks.'),
    'select': ('model-backed', 'Suggest one caller-supplied read/list target, or abstain.'),
}

SKILL_HOSTS = {'codex': '.agents', 'claude': '.claude', 'amplifier': '.amplifier'}


def agent_skill() -> str:
    """Generate the minimal discovery skill from canonical manifest identity."""
    info = manifest()
    return ('---\n' + f'name: {json.dumps(info["name"])}\n'
            + f'description: {json.dumps(info["description"])}\n---\n\n'
            + 'Install the CLI if needed:\n\n```bash\n'
            + "uv tool install 'amplifier-fast-decisions[local] @ git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main'\n```\n\n"
            + f'Run `{info["name"]} --help` and follow its guidance. Confirm capability\n'
            + f'arguments with `{info["name"]} <capability> --help` before use.\n')


def install_skill(host: str, *, home: str | Path | None = None) -> dict[str, Any]:
    """Add a discovery skill, refusing changed existing files before any writes.

    Resolves/deduplicates symlinked host directories. Existing identical content
    is unchanged. ``home`` is a library seam for isolated installation/tests.
    No host configuration, approvals, or model services are modified.
    """
    if host not in {*SKILL_HOSTS, 'all'}:
        raise ValueError('Choose codex, claude, amplifier, or all.')
    base = Path(home).expanduser() if home is not None else Path.home()
    selected = list(SKILL_HOSTS) if host == 'all' else [host]
    name, content = manifest()['name'], agent_skill()
    destinations: dict[Path, list[str]] = {}
    for value in selected:
        target = (base / SKILL_HOSTS[value] / 'skills' / name / 'SKILL.md').resolve()
        destinations.setdefault(target, []).append(value)
    # Preflight *all* destinations before writing to any of them.
    for target in destinations:
        if target.exists():
            if not target.is_file() or target.read_text(encoding='utf-8') != content:
                raise ValueError(f'Existing skill differs; preserved {target}. Review it before installing.')
        for ancestor in target.parents:
            if ancestor.exists():
                if not ancestor.is_dir():
                    raise ValueError(f'Skill parent is not a directory: {ancestor}')
                break
    created: list[Path] = []
    rows = []
    try:
        for target, hosts in destinations.items():
            if target.exists():
                # Recheck after preflight in case another process changed it.
                if target.read_text(encoding='utf-8') != content:
                    raise ValueError(f'Existing skill changed; preserved {target}.')
                status = 'unchanged'
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('x', encoding='utf-8') as stream:
                    created.append(target)
                    stream.write(content)
                status = 'installed'
            rows.append({'hosts': hosts, 'path': str(target), 'status': status})
    except (OSError, ValueError):
        # Remove only this invocation's files, never pre-existing files.
        for target in created:
            try:
                if target.read_text(encoding='utf-8') == content:
                    target.unlink()
            except OSError:
                pass
        raise
    return {'host': host, 'skills': rows, 'installed': len(created),
            'message': 'Skill discovery only. Ensure the CLI is on PATH; refresh the harness skill catalog if needed.'}


def manifest() -> dict[str, Any]:
    """Read the single packaged manifest; importing the tool needs no model."""
    text = resources.files('amplifier_fast_decisions').joinpath('SMART_TOOL.md').read_text(encoding='utf-8')
    _, front, body = text.split('---', 2)
    return {**json.loads(front), 'body': body.strip()}


def describe() -> dict[str, Any]:
    """Return the JSON contract. Additional keys are rejected, not interpreted."""
    return {
        'name': manifest()['name'], 'capability': 'select', 'model_backed': True,
        'effect': 'advisory_only', 'executes_actions': False,
        'input_schema': {
            'type': 'object', 'additionalProperties': False,
            'required': ['task', 'candidates'],
            'properties': {
                'task': {'type': 'string', 'minLength': 1, 'maxLength': 1800},
                'context': {'type': 'string', 'maxLength': 1800},
                'session_id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,128}$'},
                'parent_session_id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,128}$'},
                'harness': {'type': 'string', 'enum': ['claude', 'codex', 'amplifier', 'other']},
                'candidates': {'type': 'array', 'minItems': 1, 'maxItems': 12,
                    'items': {'type': 'object', 'additionalProperties': False,
                        'required': ['id', 'operation', 'path'], 'properties': {
                            'id': {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]{0,63}$'},
                            'operation': {'enum': ['read', 'list']},
                            'path': {'type': 'string', 'minLength': 1, 'maxLength': 512}}}},
            },
        },
        'constraints': ['At most 1800 combined task/context characters.',
                       'Candidate IDs must be unique; reason is reserved.',
                       'Paths are relative, non-hidden, without parent traversal or backslashes.',
                       'The backend may abstain when the combined prompt exceeds its byte bound.'],
        'result': {'ok': 'false for invalid input, unavailable/invalid model, or telemetry failure',
                   'status': 'selected or abstain', 'choice': 'offered candidate ID or null',
                   'reason_code': 'machine-readable outcome', 'probabilities': 'uncalibrated token mass',
                   'duration_ms': 'scoring wall time; excludes CLI startup and recording shutdown',
                   'option_set_hash': 'order-sensitive hash of model-facing options and ID bindings; null if unavailable',
                   'confidence_kind': 'not_reported for the local token scorer; not empirical calibration',
                   'effect': 'advisory_only; no execution or savings established'},
        'exit_codes': {'0': 'selected or normal model/policy abstention', '1': 'failed capability',
                       '2': 'invalid command line or JSON'},
    }


def skill(capability: str | None = None) -> str:
    """Render installed Agent Skill guidance; both CLI and library use this."""
    info = manifest()
    if capability is not None and capability not in CAPABILITIES:
        raise ValueError('Unknown capability')
    name = info['name'] + (f'-{capability}' if capability else '')
    lines = [f'<skill_content name="{name}">', f'Skill directory: {Path(__file__).resolve().parent}']
    try:
        urls = metadata.metadata('amplifier-fast-decisions').get_all('Project-URL') or []
        repository = next((u.split(',', 1)[1].strip() for u in urls if u.lower().startswith('repository,')), None)
        if repository:
            lines.append(f'Repository: {repository}')
    except metadata.PackageNotFoundError:
        pass
    lines += ['Relative paths are relative to the skill directory.', '', f'# {name}', '']
    if capability is None:
        lines += [info['body'], '', '## Capabilities', '',
                  f'Each capability has a skill: `{info["name"]} <capability> --help`.']
        lines += [f'- `{key}` [{kind}] — {summary}' for key, (kind, summary) in CAPABILITIES.items()]
    elif capability in {'manifest', 'describe'}:
        lines += [CAPABILITIES[capability][1], 'Deterministic; no arguments or provider required.',
                  f'Example: `{info["name"]} {capability}`.',
                  'Result: one JSON object on stdout. Exit 0 on success; invalid flags exit 2.']
    elif capability in {'diagnose', 'measure', 'compare'}:
        lines += [
            CAPABILITIES[capability][1],
            'No inference or configuration changes. Results are JSON on stdout; errors on stderr.',
            'diagnose/measure: --events DIRECTORY_OR_JSONL and optional --session PARENT_ID (includes children).',
            'diagnose: optional --state-file FILE, --ollama-url LOOPBACK_ORIGIN, --model NAME, --offline.',
            'Without --offline, diagnose probes local Ollama and authenticated viewer health; no model call.',
            'compare: --input FILE in paired-runs-v1 format. Relative receipt paths resolve beside FILE.',
            'See docs/OPERATIONS.md for the schema, commands and evidence limits.',
            'Exit 0 means report produced; inspect statuses and eligibility, not only the exit code.',
            'Invalid input exits 2. Missing telemetry is unknown, not proof of zero activity.',
            'Library equivalents: operations.diagnose(), operations.measure(), operations.compare(payload, base_dir=...).',
        ]
    elif capability == 'install-skill':
        lines += [
            'Deterministic installation of a minimal discovery skill; no model is used.',
            'Required argument: --host codex|claude|amplifier|all.',
            'Example: amplifier-fast-decisions install-skill --host all',
            'Writes SKILL.md below ~/.agents/skills, ~/.claude/skills, or ~/.amplifier/skills.',
            'All destinations are checked first. Identical files are unchanged; modified existing files',
            'cause failure before any writes. Symlink aliases resolving to the same destination are deduplicated.',
            'Result: JSON paths, host names, and installed/unchanged status. Exit 0 on success,',
            '1 for a conflict/filesystem error, 2 for bad arguments. No force/overwrite option exists.',
            'The library equivalent is install_skill(host, home=None). Set home to isolate tests.',
            'No host settings, permissions, or provider pipelines are changed. Refresh skill discovery if needed.',
        ]
    else:
        lines += [
            'Model-backed advisory selection. Use only for an already bounded read/list choice.',
            'Arguments: --input FILE reads a UTF-8 JSON object; --input - reads stdin.',
            'Without --input, stdin must be piped; an interactive terminal fails without prompting.',
            '--model NAME defaults to qwen3:0.6b; --ollama-url ORIGIN defaults to http://127.0.0.1:11434.',
            '--timeout-ms INTEGER defaults to 500 (10–500); --events DIRECTORY sets the metadata recorder location.',
            'Use describe for the complete task/context/candidates/session/parent/harness input schema.',
            'Only task and optional context content are provided as observations. Candidate targets are data.',
            'Example: amplifier-fast-decisions select --input request.json --timeout-ms 500',
            'Result: one JSON object with ok, status, choice, reason_code, model, probabilities,',
            'probability_kind, confidence_kind, option_set_hash, duration_ms, session_id, parent_session_id, decision_id, effect and remediation.',
            'A selected choice is advisory. It grants no permission and executes nothing.',
            'Low scores and model abstention are normal results (exit 0). Invalid/unsupported input,',
            'unavailable/invalid model, or recording failure returns typed abstention with ok=false (exit 1).',
            'Bad command-line syntax or JSON exits 2. Diagnostics use stderr; results use stdout.',
            'Start Ollama, pull qwen3:0.6b, and warm the model before latency-sensitive calls.',
            'The call deadline includes model queue wait. It does not include process startup or telemetry flush.',
            'No provider key is required; there is no deterministic scoring fallback.',
            'For composition, call await select(payload) from amplifier_fast_decisions.smart_tool.',
        ]
    return '\n'.join(lines + ['', '<skill_resources><file>SMART_TOOL.md</file><file>smart_tool.py</file></skill_resources>', '</skill_content>'])


@dataclass(frozen=True)
class Selection:
    """Typed suggestion. ``ok=False`` is a failure, never a successful shortcut."""
    ok: bool
    status: str
    reason_code: str
    session_id: str
    parent_session_id: str | None
    decision_id: str
    choice: str | None = None
    model: str | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    probability_kind: str = PROBABILITY_KIND
    duration_ms: float = 0.0
    effect: str = 'advisory_only'
    remediation: str | None = None
    confidence_kind: str = 'not_reported'
    option_set_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validated(payload: Any) -> tuple[DecisionRequest, str, str | None, str]:
    if not isinstance(payload, dict) or set(payload) - {'task', 'context', 'candidates', 'session_id', 'parent_session_id', 'harness'}:
        raise ValueError('Unsupported request fields')
    if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > MAX_INPUT_BYTES:
        raise ValueError('Request too large')
    task, context = payload.get('task'), payload.get('context', '')
    if not isinstance(task, str) or not task.strip() or not isinstance(context, str) or len(task) + len(context) > 1800:
        raise ValueError('Task/context must be bounded strings')
    session = payload.get('session_id', 'portable-' + uuid4().hex)
    parent = payload.get('parent_session_id')
    if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', v) for v in [session] + ([parent] if parent is not None else [])) or parent == session:
        raise ValueError('Invalid session identity')
    harness = payload.get('harness', 'other')
    if harness not in {'claude', 'codex', 'amplifier', 'other'}:
        raise ValueError('Unsupported harness label')
    rows = payload.get('candidates')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise ValueError('Expected 1–12 candidates')
    candidates = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {'id', 'operation', 'path'}:
            raise ValueError('Expected id, operation and path only')
        path = row['path']
        if row['operation'] not in {'read', 'list'} or not isinstance(path, str) or not path or len(path) > 512:
            raise ValueError('Unsupported target')
        if '\\' in path or ':' in path or any(ord(c) < 32 for c in path) or PurePosixPath(path).is_absolute() or any(p.startswith('.') for p in path.split('/') if p != '.'):
            raise ValueError('Unsupported path')
        candidates.append(Candidate(row['id'], f'Candidate {i + 1}', 'fast_workspace', {'operation': row['operation'], 'path': path}, origin='portable_caller'))
    if len({c.id for c in candidates}) != len(candidates):
        raise ValueError('Duplicate candidate IDs')
    observations = [{'role': 'user', 'text': scrub(task, 1800)}]
    if context:
        observations.append({'role': 'tool', 'text': scrub(context, 1800)})
    return DecisionRequest(state={'observations': observations}, candidates=tuple(candidates)), session, parent, harness


async def select(payload: dict[str, Any], *, model: str = 'qwen3:0.6b',
                 ollama_url: str = 'http://127.0.0.1:11434', timeout_ms: int = 500,
                 events_dir: str | Path | None = None, _backend: Any = None) -> Selection:
    """Score bounded caller data without reading/executing targets.

    Uses native token probabilities, score >= .90 and margin >= .20. Optional
    context is content in payload, never a file reference. Missing model or bad
    output produces a failed typed abstention. Cancellation propagates normally.
    ``_backend`` is a private test seam; callers use the loopback Ollama backend.
    """
    session, parent, decision_id = 'portable-' + uuid4().hex, None, uuid4().hex
    try:
        request, session, parent, harness = _validated(payload)
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 10 <= timeout_ms <= 500:
            raise ValueError('Deadline must be 10–500 ms')
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', model):
            raise ValueError('Invalid model name')
        backend = _backend or OllamaBackend(model=model, url=ollama_url, timeout_ms=timeout_ms)
    except (ValueError, TypeError, OverflowError):
        return Selection(False, 'abstain', 'unsupported_request', session, parent, decision_id,
                         remediation='Use describe for bounded read/list input and a literal loopback endpoint.')
    recorder = None
    duration = 0.0
    try:
        recorder = JsonlRecorder(events_dir if events_dir is not None else DEFAULT_EVENTS, session)
        emitter = Emitter(session, parent_session_id=parent, recorder=recorder, synthetic=bool(getattr(backend, 'synthetic', False)))
        common = {'mode': 'advisory', 'backend': backend.name, 'event_source': 'portable-smart-tool',
                  'engine': harness, 'allow_external_state': False}
        await emitter.emit('requested', {**common, 'candidate_count': len(request.candidates),
            'candidates': [{'id': c.id, 'label': c.label} for c in request.candidates]}, decision_id=decision_id)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                response = await backend.ask(request)
            duration = (time.perf_counter() - started) * 1000
            decision = response.action
            decision.validate({c.id for c in request.candidates} | {SLOW})
            if decision.synthetic or decision.model != model or decision.probability_kind != PROBABILITY_KIND:
                raise ValueError('Unexpected model evidence')
            probability = decision.probabilities[decision.choice]
            margin = probability - max((p for k, p in decision.probabilities.items() if k != decision.choice), default=0)
            await emitter.emit('scored', {**common, 'model': decision.model, 'choice': decision.choice,
                'probabilities': decision.probabilities, 'probability_kind': decision.probability_kind,
                'confidence_kind': decision.confidence_kind, 'option_set_hash': decision.option_set_hash,
                'selected_probability': probability, 'margin': margin, 'duration_ms': duration,
                'latency_kind': 'decision_model_wall_time'}, decision_id=decision_id)
            selected = decision.choice != SLOW and probability >= .90 and margin >= .20
            reason = 'advisory_selected' if selected else ('model_abstained' if decision.choice == SLOW else 'selection_threshold')
            result = Selection(True, 'selected' if selected else 'abstain', reason, session, parent, decision_id,
                choice=decision.choice if selected else None, model=decision.model,
                probabilities=dict(decision.probabilities), duration_ms=duration,
                confidence_kind=decision.confidence_kind, option_set_hash=decision.option_set_hash)
        except asyncio.CancelledError:
            await emitter.emit('cancelled', {**common, 'reason_code': 'caller_cancelled'}, decision_id=decision_id)
            raise
        except Exception:
            duration = (time.perf_counter() - started) * 1000
            result = Selection(False, 'abstain', 'model_unavailable_or_invalid', session, parent, decision_id,
                duration_ms=duration, remediation='Start Ollama, pull and warm the configured model; verify native token-log-probability support and input bounds.')
        await emitter.emit('health', {**common, 'phase': 'advisory_result', 'status': result.status,
            'reason_code': result.reason_code, 'success': result.ok, 'duration_ms': duration}, decision_id=decision_id)
    except (OSError, ValueError):
        result = Selection(False, 'abstain', 'telemetry_unavailable', session, parent, decision_id,
                           remediation='Choose a writable --events directory outside the installed package.')
    finally:
        if _backend is None:
            await backend.close()
        if recorder is not None:
            await asyncio.to_thread(recorder.close)
    if recorder is not None and (recorder.error or recorder.dropped):
        return Selection(False, 'abstain', 'telemetry_unavailable', session, parent, decision_id,
                         duration_ms=duration, remediation='Check events storage and retry after recording is healthy.')
    return result
