import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from archive_decision_history import snapshot


class HistoryArchiveTests(unittest.TestCase):
    def test_private_metadata_snapshot_excludes_raw_content_and_counts_partial_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); events = base/'events'; events.mkdir(); dest = base/'history'
            event = {'schema_version':'1.0','event_id':'1','session_id':'session',
                     'event':'fast_decisions:scored','timestamp':'2026-09-18T00:00:00Z',
                     'data':{'model':'local-model','duration_ms':12,'prompt':'PRIVATE PROMPT',
                             'thinking':'PRIVATE REASONING','arguments':{'api_key':'PRIVATE KEY'}}}
            (events/'trace.jsonl').write_text(json.dumps(event)+'\n{"unfinished":')
            result = snapshot(dest, events, [])
            self.assertEqual(result['events'],1)
            self.assertEqual(result['skipped_lines'],1)
            text = (dest/'events.jsonl').read_text()
            self.assertNotIn('PRIVATE',text)
            self.assertEqual(json.loads(text)['data'],{'model':'local-model','duration_ms':12})
            if os.name != 'nt':
                self.assertEqual(dest.stat().st_mode & 0o777,0o700)
                self.assertEqual((dest/'events.jsonl').stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):snapshot(dest,events,[])
