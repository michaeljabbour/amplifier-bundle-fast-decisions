"""Read-only, allowlisted projection of an explicitly selected local study."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import time


class StudyView:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        if not (self.directory / 'schedule.json').is_file():
            raise ValueError('Study directory must contain schedule.json')
        self._files = []
        self._scanned = 0
        self._summary = None
        self._summarized = 0

    def event_files(self):
        """Only real root-session receipts; omit test logs emitted inside runs."""
        if time.monotonic() - self._scanned < 2:
            return self._files
        files = []
        for run in sorted((self.directory / 'runs').glob('*')):
            if run.is_symlink() or (run / 'fd-events').is_symlink() or not (run / 'fd-events').is_dir():
                continue
            result = run / 'result.json'
            session_ids = set()
            try:
                if result.is_file():
                    session_ids.add(json.loads(result.read_text())['session_id'])
                else:
                    # Native CLI sessions already exist while a measured run is live.
                    slug = str(run / 'workspace').replace('/', '-')
                    sessions = Path.home() / '.amplifier/projects' / slug / 'sessions'
                    session_ids.update(p.parent.name for p in sessions.glob('*/metadata.json'))
            except (OSError, ValueError, KeyError):
                continue
            for path in (run / 'fd-events').glob('*.jsonl'):
                if not path.is_symlink():
                    files.extend((path, sid) for sid in session_ids
                                 if isinstance(sid, str) and path.name.startswith(sid + '-'))
        self._files, self._scanned = files, time.monotonic()
        return files

    def summary(self):
        if self._summary is not None and time.monotonic() - self._summarized < 5:
            return self._summary
        try:
            state = json.loads((self.directory / 'state.json').read_text())
            schedule = json.loads((self.directory / 'schedule.json').read_text())['jobs']
            expected = {j['job_id']: j for j in schedule}
            results = []
            for line in (self.directory / 'results.jsonl').read_text().splitlines(keepends=True):
                if not line.endswith('\n'):
                    continue  # Currently appending; retry on the next refresh.
                row = json.loads(line)
                if row.get('qualification') or row.get('job_id') not in expected:
                    continue
                if any(row.get(k) != v for k, v in expected[row['job_id']].items()):
                    raise ValueError('Assignment mismatch')
                results.append(row)
            if len({r['job_id'] for r in results}) != len(results):
                raise ValueError('Duplicate assignment')
            arms = []
            for harness in ['codex', 'amplifier']:
                for arm in ['baseline', 'fd-local', 'fd-jev']:
                    rows = [r for r in results if r['harness'] == harness and r['arm'] == arm]
                    arms.append({'harness': harness, 'arm': arm, 'completed': len(rows),
                                 'planned': sum(j['harness'] == harness and j['arm'] == arm for j in schedule),
                                 'passed': sum(bool(r['grade']['accepted']) for r in rows),
                                 'median_seconds': statistics.median(r['wall_seconds'] for r in rows) if rows else None,
                                 'fd_requests': sum(r['fd_event_counts'].get('fast_decisions:requested', 0) for r in rows)})
            report = {'available': True, 'status': state['status'], 'completed': len(results),
                      'planned': len(schedule), 'complete': state['status'] == 'complete' and len(results) == len(schedule),
                      'arms': arms, 'net_time_saved_seconds': None, 'poor_calls_prevented': None,
                      'note': 'Recorded outcomes, not a final performance verdict. Net time saved and poor calls prevented are not inferred from event counts.'}
        except (OSError, ValueError, KeyError, TypeError):
            report = {'available': False, 'status': 'unavailable', 'note': 'Study data is temporarily unavailable or inconsistent.'}
        self._summary, self._summarized = report, time.monotonic()
        return report
