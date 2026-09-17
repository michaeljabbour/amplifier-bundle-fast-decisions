from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from amplifier_fast_decisions.telemetry import Emitter, JsonlRecorder
from amplifier_fast_decisions.server import EventIndex, ViewerServer


def event(i=1):
    return {'schema_version':'1.0','event_id':str(i),'event':'fast_decisions:routed','session_id':'test',
            'parent_session_id':None,'turn_id':'turn','decision_id':'d'+str(i),'seq':i,
            'timestamp':'2026-09-16T21:00:00+00:00','monotonic_ns':i,'synthetic':False,
            'data':{'route':'fast','prompt':'MUST NOT PASS'}}


class EmitterTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_event_identity_to_hooks_and_recorder(self):
        events=[]
        class Hooks:
            async def emit(self,name,data):events.append(data)
        with tempfile.TemporaryDirectory() as tmp:
            recorder=JsonlRecorder(tmp,'session');emitter=Emitter('session',hooks=Hooks(),recorder=recorder)
            emitted=await emitter.emit('routed',{'route':'fast','prompt':'HIDDEN'})
            await asyncio.to_thread(recorder.close)
            logged=json.loads(recorder.path.read_text())
            self.assertEqual(logged,events[0]);self.assertEqual(logged,emitted)
            self.assertNotIn('HIDDEN',recorder.path.read_text())
            self.assertEqual(recorder.path.stat().st_mode&0o777,0o600)
    async def test_sequence_unique(self):
        emitter=Emitter('session')
        a=await emitter.emit('routed');b=await emitter.emit('routed')
        self.assertEqual((a['seq'],b['seq']),(1,2));self.assertNotEqual(a['event_id'],b['event_id'])
    async def test_hook_error_does_not_break_execution(self):
        class Hooks:
            async def emit(self,*args):raise RuntimeError('logger unavailable')
        emitter=Emitter('session',hooks=Hooks())
        await emitter.emit('routed')
        self.assertEqual(emitter.hook_errors,1)
    async def test_hook_cancellation_is_not_swallowed(self):
        class Hooks:
            async def emit(self,*args):raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await Emitter('session',hooks=Hooks()).emit('routed')
    async def test_closed_recorder_counts_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=JsonlRecorder(tmp,'test');await asyncio.to_thread(r.close);r.submit(event())
            self.assertEqual(r.dropped,1)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.file=self.root/'events.jsonl'
    def tearDown(self):self.temp.cleanup()
    def test_read_and_scrub(self):
        self.file.write_text(json.dumps(event())+'\n')
        data=EventIndex(self.root).get()
        self.assertEqual(len(data['events']),1)
        self.assertNotIn('prompt',data['events'][0]['data'])
    def test_incomplete_line_waits(self):
        text=json.dumps(event());self.file.write_text(text[:20])
        index=EventIndex(self.root);self.assertEqual(index.get()['events'],[])
        with self.file.open('a') as file:file.write(text[20:]+'\n')
        self.assertEqual(len(index.get()['events']),1)
    def test_duplicates_deduplicated(self):
        self.file.write_text((json.dumps(event())+'\n')*2)
        self.assertEqual(len(EventIndex(self.root).get()['events']),1)
    def test_bad_line_skipped(self):
        self.file.write_text('bad\n'+json.dumps(event())+'\n')
        index=EventIndex(self.root);data=index.get()
        self.assertEqual(data['invalid_lines'],1);self.assertEqual(len(data['events']),1)
    def test_capacity(self):
        self.file.write_text(''.join(json.dumps(event(i))+'\n' for i in range(10)))
        index=EventIndex(self.root,capacity=3);data=index.get()
        self.assertEqual(len(data['events']),3);self.assertEqual(data['retained'],3)
    def test_cursor_resume(self):
        self.file.write_text(''.join(json.dumps(event(i))+'\n' for i in range(3)))
        index=EventIndex(self.root);data=index.get(limit=2)
        second=index.get(after=data['cursor'])
        self.assertEqual(len(second['events']),1)
    def test_symlink_not_read(self):
        with tempfile.NamedTemporaryFile(mode='w',suffix='.jsonl') as secret:
            secret.write(json.dumps(event())+'\n');secret.flush()
            self.file.symlink_to(secret.name)
            self.assertEqual(EventIndex(self.root).get()['events'],[])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.server=ViewerServer(self.temp.name,0,'test-token')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def fetch(self,path='/',headers=None,method='GET'):
        req=urllib.request.Request(self.base+path,headers=headers or {},method=method)
        return urllib.request.urlopen(req,timeout=2)
    def test_loopback(self):self.assertEqual(self.server.server_address[0],'127.0.0.1')
    def test_page_served(self):
        with self.fetch() as response:self.assertIn(b'Decision Observatory',response.read())
    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.fetch('/api/events')
        self.assertEqual(e.exception.code,401)
    def test_valid_token(self):
        with self.fetch('/api/events',{'Authorization':'Bearer test-token'}) as response:self.assertEqual(response.status,200)
    def test_origin_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.fetch('/api/events',{'Authorization':'Bearer test-token','Origin':'https://evil.example'})
        self.assertEqual(e.exception.code,403)
    def test_bad_host_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.fetch('/',{'Host':'evil.example'})
        self.assertEqual(e.exception.code,403)
    def test_no_write_api(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.fetch('/api/config',{'Authorization':'Bearer test-token'},method='POST')
        self.assertEqual(e.exception.code,405)
    def test_traversal_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.fetch('/../pyproject.toml')
        self.assertEqual(e.exception.code,404)
    def test_security_headers(self):
        with self.fetch() as response:
            self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
            self.assertEqual(response.headers['Cache-Control'],'no-store')


if __name__=='__main__':unittest.main()
