"""Thin CLI for the portable smart tool library."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import os

from . import __version__
from . import smart_tool as lib
from . import operations
from . import decide as decide_lib
from . import launch as launch_lib
from . import judge_backends


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog='amplifier-fast-decisions', add_help=False,
        description='Advisory local or Jev selection; no action execution.')
    parser.add_argument('-h', action='help', help='Show short usage')
    commands = parser.add_subparsers(dest='command', required=True)
    for name, (_, summary) in lib.CAPABILITIES.items():
        command = commands.add_parser(name, help=summary, add_help=False)
        command.add_argument('-h', action='help', help='Show short usage')
        if name == 'install-skill':
            command.add_argument('--host', required=True, choices=[*lib.SKILL_HOSTS, 'all'])
        if name in {'doctor', 'diagnose', 'measure'}:
            command.add_argument('--events', default=str(operations.DEFAULT_EVENTS))
            command.add_argument('--session')
        if name in {'doctor', 'diagnose'}:
            command.add_argument('--state-file', default=str(operations.DEFAULT_STATE))
            command.add_argument('--ollama-url', default='http://127.0.0.1:11434')
            command.add_argument('--model', default='qwen3:0.6b')
            command.add_argument('--offline', action='store_true')
        if name == 'compare':
            command.add_argument('--input', required=True, metavar='FILE')
        if name in {'search', 'cua'}:
            command.add_argument('--input', default='-', metavar='FILE')
            command.add_argument('--backend', choices=['laya', 'jev'], default='jev')
            command.add_argument('--laya-url')
            command.add_argument('--allow-external-state', action='store_true')
            command.add_argument('--timeout-ms', type=int, default=60000 if name == 'search' else 3000)
            if name == 'search':
                command.add_argument('--root', default='.')
            else:
                command.add_argument('--min-probability', type=float, default=.75)
        if name in {'decide', 'launch'}:
            command.add_argument('--task')
            command.add_argument('--host-model')
            command.add_argument('--workspace')
            command.add_argument('--user-model')
            command.add_argument('--decider', choices=decide_lib.deciders())
            command.add_argument('--cheap-model')
            command.add_argument('--allow-external-state', action=argparse.BooleanOptionalAction, default=None)
            command.add_argument('--no-settings', action='store_true')
        if name == 'decide':
            command.add_argument('--input', metavar='FILE')
        if name == 'launch':
            command.add_argument('--harness', required=True, choices=sorted(launch_lib.HARNESSES))
            command.add_argument('--dry-run', action='store_true')
            command.add_argument('harness_args', nargs='*')
        if name == 'select':
            command.add_argument('--input', default='-', metavar='FILE')
            command.add_argument('--backend', choices=[*judge_backends.names('select'), 'local'])
            command.add_argument('--allow-external-state', action=argparse.BooleanOptionalAction, default=None)
            command.add_argument('--model')
            command.add_argument('--ollama-url')
            command.add_argument('--laya-url')
            command.add_argument('--timeout-ms', type=int, default=None)
            command.add_argument('--events')
    if argv == ['--version']:
        print(__version__); return 0
    if argv == ['--help']:
        print(lib.skill()); return 0
    if len(argv) == 2 and argv[0] in lib.CAPABILITIES and argv[1] == '--help':
        print(lib.skill(argv[0])); return 0
    harness_args: list[str] = []
    if argv and argv[0] == 'launch' and '--' in argv:
        split = argv.index('--')
        argv, harness_args = argv[:split], argv[split + 1:]
    args = parser.parse_args(argv)
    if args.command == 'manifest':
        print(json.dumps(lib.manifest(), indent=2)); return 0
    if args.command == 'describe':
        print(json.dumps(lib.describe(), indent=2)); return 0
    if args.command in {'doctor', 'diagnose', 'measure', 'compare'}:
        try:
            if args.command in {'doctor', 'diagnose'}:
                result = operations.diagnose(events_dir=args.events, session_id=args.session,
                    state_file=args.state_file, ollama_url=args.ollama_url, model=args.model, probe=not args.offline)
            elif args.command == 'measure':
                result = operations.measure(args.events, session_id=args.session)
            else:
                path = Path(args.input).expanduser()
                if path.stat().st_size > 2_000_000:
                    raise ValueError('Comparison input exceeds 2 MB')
                result = operations.compare(json.loads(path.read_text(encoding='utf-8')), base_dir=path.resolve().parent)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f'Unable to produce report ({type(exc).__name__}); check input and capability --help.', file=sys.stderr)
            return 2
    if args.command in {'decide', 'launch'}:
        return _decide_or_launch(args, harness_args, parser)
    if args.command == 'install-skill':
        try:
            print(json.dumps(lib.install_skill(args.host), indent=2))
            return 0
        except (OSError, ValueError) as exc:
            print(f'Skill installation failed: {exc}', file=sys.stderr)
            return 1
    try:
        if args.input == '-':
            if sys.stdin.isatty():
                parser.error('Pipe JSON on stdin or use --input FILE; see select --help.')
            raw = sys.stdin.buffer.read(lib.MAX_INPUT_BYTES + 1)
        else:
            with Path(args.input).open('rb') as stream:
                raw = stream.read(lib.MAX_INPUT_BYTES + 1)
        if len(raw) > lib.MAX_INPUT_BYTES:
            raise ValueError('Request exceeds 16 KiB')
        payload = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        print('Expected readable UTF-8 JSON under 16 KiB. Use describe for the input contract.', file=sys.stderr)
        return 2
    if args.command in {'search', 'cua'}:
        try:
            options = dict(backend=args.backend, laya_url=args.laya_url,
                           allow_external_state=args.allow_external_state, timeout_ms=args.timeout_ms)
            if args.command == 'search':
                result = asyncio.run(lib.search(payload, root=args.root, **options))
                failed = result['status'] not in {'complete', 'incomplete'}
            else:
                result = asyncio.run(lib.cua(payload, min_probability=args.min_probability, **options))
                failed = result.get('reason') in {'judge_unavailable', 'external_state_not_enabled'}
            print(json.dumps(result, allow_nan=False))
            return 1 if failed else 0
        except (OSError, ValueError, TypeError, KeyError):
            print('Invalid input or configuration; see capability --help.', file=sys.stderr)
            return 2
    result = asyncio.run(lib.select(payload, model=args.model, ollama_url=args.ollama_url,
                                   laya_url=args.laya_url,
                                   backend=args.backend, allow_external_state=args.allow_external_state,
                                   timeout_ms=args.timeout_ms, events_dir=args.events))
    print(json.dumps(result.to_dict(), sort_keys=True))
    if not result.ok:
        print(result.remediation, file=sys.stderr)
    return 0 if result.ok else 1


def _decide_or_launch(args, harness_args: list[str], parser) -> int:
    """``decide`` prints the decision; ``launch`` decides and then replaces this process with the harness."""
    payload: dict = {}
    if args.command == 'decide' and args.input:
        try:
            raw = sys.stdin.buffer.read(lib.MAX_DECIDE_TASK_CHARS * 4) if args.input == '-' else Path(args.input).read_bytes()
            payload = json.loads(raw)
        except (OSError, ValueError, UnicodeError):
            print('Expected readable UTF-8 JSON. Use decide --help for the input contract.', file=sys.stderr)
            return 2
    task = args.task or payload.get('task')
    if args.command == 'launch':
        task = task or launch_lib.extract_task(args.harness, [*args.harness_args, *harness_args])
    if task is None:
        print('No task text: pass --task' + (' (an interactive launch has no prompt to decide on)' if args.command == 'launch' else ' or --input.'), file=sys.stderr)
        return 2
    payload = {**payload, 'task': task}
    host = args.host_model or payload.get('host_model') or os.getenv('AFAST_HOST_MODEL')
    if host:
        payload['host_model'] = host
    else:
        print('No host model: pass --host-model (or set AFAST_HOST_MODEL); the price gate needs it.', file=sys.stderr)
        return 2
    for key, value in (('workspace', args.workspace), ('user_model', args.user_model)):
        if value:
            payload[key] = value
    payload.setdefault('workspace', os.getcwd())
    result = asyncio.run(lib.decide(payload, decider=args.decider, allow_external_state=args.allow_external_state,
                                    cheap_model=args.cheap_model, use_settings=not args.no_settings))
    if args.command == 'decide':
        print(json.dumps(result, sort_keys=True))
        if not result['ok']:
            print(result['remediation'], file=sys.stderr)
        return 0 if result['ok'] else (2 if result['reason_code'] == 'unsupported_request' else 1)
    if not result['ok']:
        print(result['remediation'], file=sys.stderr)
        return 1
    decision = decide_lib.Decision(**{**{k: v for k, v in result.items() if k != 'ok'},
                                      'config_sources': tuple(result['config_sources'])})
    try:
        report = launch_lib.launch(args.harness, decision, [*args.harness_args, *harness_args], dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(launch_lib.report_json(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
