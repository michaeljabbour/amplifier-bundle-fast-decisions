"""Thin CLI for the portable smart tool library."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from . import smart_tool as lib


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog='amplifier-fast-decisions', add_help=False,
        description='Advisory local-model selection; no action execution.')
    parser.add_argument('-h', action='help', help='Show short usage')
    commands = parser.add_subparsers(dest='command', required=True)
    for name, (_, summary) in lib.CAPABILITIES.items():
        command = commands.add_parser(name, help=summary, add_help=False)
        command.add_argument('-h', action='help', help='Show short usage')
        if name == 'install-skill':
            command.add_argument('--host', required=True, choices=[*lib.SKILL_HOSTS, 'all'])
        if name == 'select':
            command.add_argument('--input', default='-', metavar='FILE')
            command.add_argument('--model', default='qwen3:0.6b')
            command.add_argument('--ollama-url', default='http://127.0.0.1:11434')
            command.add_argument('--timeout-ms', type=int, default=500)
            command.add_argument('--events')
    if argv == ['--help']:
        print(lib.skill()); return 0
    if len(argv) == 2 and argv[0] in lib.CAPABILITIES and argv[1] == '--help':
        print(lib.skill(argv[0])); return 0
    args = parser.parse_args(argv)
    if args.command == 'manifest':
        print(json.dumps(lib.manifest(), indent=2)); return 0
    if args.command == 'describe':
        print(json.dumps(lib.describe(), indent=2)); return 0
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
    result = asyncio.run(lib.select(payload, model=args.model, ollama_url=args.ollama_url,
                                   timeout_ms=args.timeout_ms, events_dir=args.events))
    print(json.dumps(result.to_dict(), sort_keys=True))
    if not result.ok:
        print(result.remediation, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
