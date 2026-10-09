"""Scoped canonical-record joins; no controller or arbitrary artifact reads."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from zog.build_trace import BuildTrace, TraceError, InspectionLimits
from zog.build_trace.cli import main
from contextlib import redirect_stdout
import io

AVAILABLE=importlib.util.find_spec('zog.build_record') is not None

@unittest.skipUnless(AVAILABLE,'requires build-record')
class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        from zog.build_record import Store, make_record
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.state=self.root/'state/image-build';self.state.mkdir(parents=True)
        self.store=Store(self.state/'build-record/records')
        self.make=make_record
        self.trace=self.reader()
    def reader(self,**kw):
        return BuildTrace(self.root,host_id='host-a',record_project_id='project-a',record_store=self.store.directory,**kw)
    def asset(self,name,text):
        return dict(name=name,digest='sha256:'+hashlib.sha256(text.encode()).hexdigest(),size=len(text.encode()))
    def put(self,kind,data,gaps=None):
        return self.store.put(self.make(kind,data,gaps=gaps))
    def create(self,attempt,*,previous=None,source='source',recipe='recipe',outcome='succeeded'):
        package='fixture'
        selected=self.put('source-selection',dict(package=package,pin=dict(month='2026-10-01',repository='fixture:catalogue',revision='1'*40,path='pins/commit-pin.py',digest=self.asset('pin',source)['digest']),upstream=[dict(repository='fixture:upstream',revision='2'*40)],archives=[self.asset('source',source)]))
        inputs=self.put('build-inputs',dict(package=package,step='final',purpose='package',sources=[selected],recipe=self.asset('recipe',recipe),patches=[],target='fixture',options={'toolchain_generation':'fixture-seed'},environment={'LANG':'C'},materials=[self.asset('toolchain','seed')],dependencies=[]))
        owner_id=json.dumps(['host-a','project-a',attempt,package],separators=(',',':'))
        prepared=self.put('attempt-start',dict(attempt_id=owner_id,inputs=inputs,prepared_at='2026-10-02T12:00:00Z',retry_of=previous))
        output=self.put('package-output',dict(package=package,attempt=prepared,artifacts=[self.asset('output','output')])) if outcome=='succeeded' else None
        result=self.put('attempt-result',dict(attempt=prepared,outcome=outcome,finished_at='2026-10-02T12:01:00Z',jobs=[],traces=[dict(host_id='host-a',build_id='attempt:'+attempt)],outputs=[output] if output else [],summary='fixture'))
        binding=dict(schema=1,host_id='host-a',project_id='project-a',attempt_id=owner_id,build_id='attempt:'+attempt,package=package,prepared=prepared,inputs=inputs,result=result,output=output)
        path=self.state/'attempts'/attempt/'packages'/package/'provenance.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(binding))
        return binding,path
    def test_join_pages_read_only_and_cli(self):
        b,_=self.create('one')
        before={p:p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        page=self.trace.provenance('attempt:one','fixture',limit=2);ids=[]
        while True:
            ids += [r['id'] for r in page['records']['items']]
            if not page['records']['has_more']:break
            page=self.trace.provenance('attempt:one','fixture',limit=2,cursor=page['records']['next_cursor'])
        self.assertEqual(len(ids),5);self.assertEqual(len(set(ids)),5)
        self.assertEqual(page['artifact_verification'],'not-checked')
        self.assertEqual(before,{p:p.read_bytes() for p in self.state.rglob('*') if p.is_file()})
        out=io.StringIO()
        with redirect_stdout(out):
            code=main(['--project-root',str(self.root),'--host-id','host-a','--record-store',str(self.store.directory),'--record-project-id','project-a','provenance','attempt:one','fixture','--limit','2'])
        self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue())['kind'],'provenance')
    def test_explicit_retry_and_comparison(self):
        failed,_=self.create('failed',outcome='failed')
        accepted,_=self.create('retry',previous=failed['result'],source='changed-source',recipe='changed-recipe')
        result=self.trace.compare_provenance('attempt:failed','attempt:retry','fixture')
        self.assertTrue(result['different_attempt']);self.assertFalse(result['same_inputs'])
        self.assertEqual({c['field'] for c in result['changes']},{'sources','recipe'})
        page=self.trace.provenance('attempt:retry','fixture')
        starts=[r for r in page['records']['items'] if r['kind']=='attempt-start']
        self.assertTrue(any(r['data']['retry_of']==failed['result'] for r in starts))
    def test_missing_record_is_explicit(self):
        b,_=self.create('one');(self.store.directory/(b['inputs'][7:]+'.json')).unlink()
        page=self.trace.provenance('attempt:one','fixture')
        self.assertFalse(page['complete']);self.assertIn(b['inputs'],page['missing_records'])
        self.assertEqual(self.trace.compare_provenance('attempt:one','attempt:one','fixture')['availability'],'incomplete')
    def test_digest_mismatch_and_symlink(self):
        b,_=self.create('one');path=self.store.directory/(b['result'][7:]+'.json')
        raw=json.loads(path.read_bytes());raw['data']['summary']='changed';path.write_text(json.dumps(raw))
        with self.assertRaises(TraceError) as caught:self.trace.provenance('attempt:one','fixture')
        self.assertEqual(caught.exception.code,'integrity-error')
        path.unlink();path.symlink_to('/etc/passwd')
        with self.assertRaises(TraceError):self.trace.provenance('attempt:one','fixture')
    def test_scope_applies_to_retry_closure(self):
        failed,_=self.create('failed',outcome='failed');self.create('retry',previous=failed['result'])
        restricted=self.reader(allowed_build_ids=['attempt:retry'])
        with self.assertRaises(TraceError) as caught:restricted.provenance('attempt:retry','fixture')
        self.assertEqual(caught.exception.code,'not-found')
    def test_binding_and_cursor_scopes(self):
        b,path=self.create('one');self.create('two')
        page=self.trace.provenance('attempt:one','fixture',limit=1)
        with self.assertRaises(TraceError) as caught:self.trace.provenance('attempt:two','fixture',cursor=page['records']['next_cursor'])
        self.assertEqual(caught.exception.code,'invalid-cursor')
        b['project_id']='other';path.write_text(json.dumps(b))
        with self.assertRaises(TraceError) as caught:self.trace.provenance('attempt:one','fixture')
        self.assertEqual(caught.exception.code,'not-found')
    def test_budget_and_unconfigured_legacy(self):
        _,path=self.create('one')
        low=self.reader(provenance_limits=InspectionLimits(source_bytes=10))
        with self.assertRaises(TraceError) as caught:low.provenance('attempt:one','fixture')
        self.assertEqual(caught.exception.code,'source-too-large')
        path.unlink();self.assertEqual(self.trace.provenance('attempt:one','fixture')['availability'],'not-captured')
        with self.assertRaises(TraceError):BuildTrace(self.root,host_id='host-a').provenance('attempt:one','fixture')
    def test_duplicate_json_key_rejected(self):
        b,_=self.create('one');path=self.store.directory/(b['result'][7:]+'.json')
        value=path.read_text();path.write_text(value.replace('{','{"schema_version":1,',1))
        with self.assertRaises(TraceError) as caught:self.trace.provenance('attempt:one','fixture')
        self.assertEqual(caught.exception.code,'invalid-record')
