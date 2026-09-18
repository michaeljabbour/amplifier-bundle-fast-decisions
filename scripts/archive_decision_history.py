#!/usr/bin/env python3
"""Private metadata history snapshot. Never copies native prompt/reasoning logs.

Native full session histories already persist under ~/.amplifier/projects;
this indexes their locations and hashes, and archives allowlisted telemetry.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from amplifier_fast_decisions.privacy import safe_data


def snapshot(destination, events, evidence_roots):
    previous = os.umask(0o077)
    try:
        destination.mkdir(parents=True, exist_ok=False)
        sessions = {}
        invalid = 0
        count = 0
        with (destination / 'events.jsonl').open('w') as output:
            for path in sorted(events.glob('*.jsonl')):
                if path.is_symlink():
                    continue
                for line in path.read_text().splitlines():
                    try:
                        e = json.loads(line)
                        if e.get('schema_version') != '1.0' or not isinstance(e.get('data'), dict):
                            raise ValueError('Unsupported event')
                        clean = {k: e[k] for k in ('schema_version', 'event_id', 'session_id', 'parent_session_id', 'event', 'decision_id', 'timestamp', 'seq', 'synthetic') if k in e}
                        clean['data'] = safe_data(e['data'])
                        sid = clean['session_id']
                    except (ValueError, KeyError, TypeError):
                        invalid += 1
                        continue
                    output.write(json.dumps(clean) + '\n')
                    count += 1
                    item = sessions.setdefault(sid, {'session_id': sid, 'events': 0, 'first_at': clean['timestamp'], 'last_at': clean['timestamp'], 'event_types': Counter()})
                    item['events'] += 1
                    item['first_at'] = min(item['first_at'], clean['timestamp'])
                    item['last_at'] = max(item['last_at'], clean['timestamp'])
                    item['event_types'][clean['event']] += 1
        runs = []
        for root in evidence_roots:
            target = destination / root.name
            target.mkdir()
            for name in ('manifest.json', 'report.json', 'REPORT.md', 'ROOT-CAUSE.json', 'ROOT-CAUSE.md', 'OBSERVATIONS.md', 'analysis-provenance.json', 'cleanup.json', 'pilot-exclusion.json', 'forge-sessions.json'):
                path = root / name
                if path.is_file():
                    shutil.copyfile(path, target / name)
            for result in sorted(root.glob('*/result.json')):
                r = json.loads(result.read_text())
                run_dir = target / result.parent.name
                run_dir.mkdir()
                for name in ('result.json', 'receipts.jsonl', 'running.json', 'live-viewer.json', 'viewer-receipt-check.json', 'live-viewer.png'):
                    path = result.parent / name
                    if path.is_file():
                        shutil.copyfile(path, run_dir / name)
                workspace = result.parent / 'workspace'
                native = Path.home() / '.amplifier/projects' / str(workspace.resolve()).replace('/', '-') / 'sessions' / r['session_id']
                native_files = []
                for filename in ('events.jsonl', 'transcript.jsonl', 'metadata.json'):
                    path = native / filename
                    if path.is_file():
                        native_files.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'copied': False})
                runs.append({'run': result.parent.name, 'experiment': root.name, 'session_id': r['session_id'], 'deadline_hit': r['timed_out'], 'native_history_files': native_files, 'workspace': str(workspace)})
            archived_report = target / 'REPORT.md'
            if archived_report.exists():
                text = archived_report.read_text()
                for result in root.glob('*/result.json'):
                    relative = result.parent.name + '/workspace/solution.py'
                    text = text.replace('](' + relative + ')', '](' + str(root / relative) + ')')
                archived_report.write_text(text)
        manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'scope': 'metadata snapshot and native history index', 'events': count, 'sessions': list(sessions.values()), 'invalid_or_partial_lines_skipped': invalid, 'benchmark_runs': runs, 'full_native_content_copied': False}
        (destination / 'index.json').write_text(json.dumps(manifest, indent=2) + '\n')
        lines = ['# Fast-decisions session history', '', f'Private snapshot: {count} events across {len(sessions)} session IDs; {len(runs)} benchmark runs indexed.', '',
                 'The events snapshot contains allowlisted metadata. Full native conversation/provider logs remain at the locations and hashes in index.json. They were not duplicated or published because they can include system context and private model reasoning. This is not a full-content backup. Incomplete JSONL tail records, if any, are counted in index.json.', '',
                 'Future fast-decisions events already append to ~/.amplifier/fast-decisions/events. Viewer time-window limits do not delete those files. Re-run this helper for another snapshot.', '', '| Experiment / run | Session | Native history files |', '|---|---|---|']
        for r in runs:
            links = ' · '.join(f"[{Path(f['path']).name}]({f['path']})" for f in r['native_history_files'])
            lines.append(f"| {r['experiment']} / {r['run']} | `{r['session_id']}` | {links} |")
        (destination / 'INDEX.md').write_text('\n'.join(lines) + '\n')
        return {'destination': str(destination), 'events': count, 'sessions': len(sessions), 'benchmark_runs': len(runs), 'skipped_lines': invalid}
    finally:
        os.umask(previous)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--events', type=Path, default=Path.home()/'.amplifier/fast-decisions/events')
    parser.add_argument('--evidence', type=Path, action='append', default=[])
    args = parser.parse_args()
    print(json.dumps(snapshot(args.destination.expanduser(), args.events.expanduser(), args.evidence)))
