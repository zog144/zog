import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zog.build_trace import BuildTrace, TraceError
from zog.build_trace.model import response
from zog.build_trace.source import Snapshot

class Reader:
    def __init__(self): self.jobs, self.pages, self.calls = {}, {}, []
    def inspect(self, job): self.calls.append(job); return self.jobs.get(job)
    def logs(self, job, **kw):
        p = self.pages.get((job, kw['cursor']))
        if isinstance(p, Exception): raise p
        return p or dict(job_id=job, status='empty-history', entries=[], next_cursor=None)

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name); self.root = self.project/'state/image-build'; self.root.mkdir(parents=True)
        self.reader = Reader(); self.trace = BuildTrace(self.project, host_id='host-a', controller=self.reader)
        self.pipeline = 'a'*32; self.attempt = 'native-check-'+'b'*32; self.bid = 'attempt:'+self.attempt
        self.put('pipelines/'+self.pipeline+'/pipeline.json', dict(schema=1, pipeline_id=self.pipeline, attempts={'native-check':self.attempt}, status='pending', recipes=[{'path':'gcc/build.py','sha256':'old'}]))
        self.put('attempts/'+self.attempt+'/status.json', {'status':'pending'})
    def put(self, name, value):
        p=self.root/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(value)); return p
    def command(self, phase='build', index=0, *, outcome='success', completion=True, checkpoint=True, view=True, attempt=None, argv=None):
        attempt=attempt or self.attempt; stem=f'packages/gcc/{phase}-{index}'; base=f'attempts/{attempt}/{stem}'
        rid='r1-123-'+hashlib.md5(base.encode()).hexdigest()+'-'+'a'*64; job=hashlib.sha256(rid.encode()).hexdigest()[:32]
        req=dict(command=argv or ['/bin/sh','-c','echo build'],environment={'LANG':'C','PATH':'/usr/bin','CUSTOM':'private'},working_directory='/image-build/source',timeout_seconds=30,read_only_root=True,network_access=False)
        if view: self.put(base+'.view.json',dict(schema=1,attempt_id=attempt,pipeline_id=self.pipeline,stage_id='final',package='gcc',phase=phase,command_index=index,command=req['command'],checkpoint=f'{phase}-{index}.controller.json'))
        if checkpoint: self.put(base+'.controller.json',dict(request_id=rid,job_id=job,binding={'request':req,'configuration':{'resource_limits':{'memory-maximum-bytes':4096}}}))
        if completion: self.put(base+'.execution.json',dict(request=req,runtime_id='c'*32,invocation_id='d'*32,journal_reference='invocation',exit_code=0 if outcome=='success' else 7,cleanup_complete=True))
        self.reader.jobs[job]=dict(schema=1,entity='job:'+job,job_id=job,request_id=rid,request=req,state='completed' if completion else 'unknown',outcome=outcome,exit_code=0 if outcome=='success' else 7,invocation_id='d'*32,boot_id='e'*32)
        return stem,job
    def code(self, code, fn):
        with self.assertRaises(TraceError) as e: fn()
        self.assertEqual(e.exception.code,code)
    def test_success(self):
        c,j=self.command(); r=self.trace.inspect_command(self.bid,c)
        self.assertEqual(r['script']['value'],'echo build'); self.assertEqual(r['outcome']['value'],'success')
        self.assertEqual(r['child_commands']['origin'],'missing'); self.assertEqual(r['environment']['value']['CUSTOM']['origin'],'redacted')
    def test_nonzero_filters(self):
        self.command(outcome='nonzero-exit'); self.assertEqual(len(self.trace.list_builds(package='gcc',phase='build',status='nonzero-exit')['items']),1)
        self.assertEqual(self.trace.list_builds(package='other')['items'],[])
    def test_pre_job_failure(self):
        self.command(completion=False,checkpoint=False); self.put('attempts/'+self.attempt+'/status.json',{'status':'failed','error':'registration failed'})
        r=self.trace.inspect_build(self.bid); self.assertEqual(r['error']['value'],'registration failed')
        self.assertEqual(r['commands']['items'][0]['state'],'not-submitted-or-unrecorded'); self.assertIsNone(r['commands']['items'][0]['job_id']['value'])
    def test_pipeline_before_attempt(self):
        p='f'*32; self.put('pipelines/'+p+'/pipeline.json',dict(schema=1,pipeline_id=p,attempts={},status='pending',error='selection unavailable'))
        r=self.trace.inspect_build('pipeline:'+p); self.assertEqual(r['commands']['items'],[]); self.assertEqual(r['error']['value'],'selection unavailable')
    def test_unknown(self):
        c,j=self.command(outcome='unknown',completion=False); self.assertEqual(self.trace.inspect_command(self.bid,c)['outcome']['value'],'unknown')
        self.reader.jobs.clear(); self.assertEqual(self.trace.inspect_command(self.bid,c)['outcome']['value'],'unknown')
    def test_pruned_completion(self):
        c,j=self.command(outcome='nonzero-exit'); self.reader.jobs.clear(); r=self.trace.inspect_command(self.bid,c)
        self.assertEqual(r['outcome']['value'],'nonzero-exit'); self.assertEqual(r['controller_availability'],'missing-or-pruned')
    def test_offline(self):
        c,j=self.command(); t=BuildTrace(self.project,host_id='host-a'); self.assertEqual(t.inspect_command(self.bid,c)['outcome']['value'],'success'); self.assertEqual(t.logs(self.bid,c)['availability'],'not-configured')
    def test_legacy(self):
        c,j=self.command(view=False,checkpoint=False); r=self.trace.inspect_command(self.bid,c); self.assertIsNone(r['phase']); self.assertEqual(r['command']['value'][0],'/bin/sh')
    def test_numeric_order_and_pages(self):
        for p,i in [('install',0),('build',10),('build',2),('configure',0)]: self.command(p,i)
        a=self.trace.inspect_build(self.bid,limit=2)['commands']; b=self.trace.inspect_build(self.bid,limit=2,cursor=a['next_cursor'])['commands']
        self.assertEqual([c['id'] for c in a['items']+b['items']],['packages/gcc/configure-0','packages/gcc/build-2','packages/gcc/build-10','packages/gcc/install-0']); self.assertFalse(b['has_more'])
    def test_cursor_scope(self):
        self.command(); self.put('attempts/z/status.json',{'status':'failed'}); c=self.trace.list_builds(limit=1)['next_cursor']
        self.code('invalid-cursor',lambda: BuildTrace(self.project,host_id='host-b').list_builds(cursor=c))
        self.code('invalid-cursor',lambda: self.trace.list_builds(status='pending',cursor=c))
    def test_authorization_scope(self):
        c,j=self.command(); t=BuildTrace(self.project,host_id='host-a',controller=self.reader,allowed_build_ids=[])
        self.assertEqual(t.list_builds()['items'],[]); self.code('not-found',lambda:t.logs(self.bid,c)); self.assertEqual(self.reader.calls,[])
    def test_traversal(self):
        self.code('invalid-query',lambda:self.trace.inspect_build('attempt:../secret')); self.command(); self.code('not-found',lambda:self.trace.inspect_command(self.bid,'../../secret'))
    def test_symlink(self):
        p=self.root/('attempts/'+self.attempt+'/status.json'); p.unlink(); p.symlink_to('/etc/passwd'); self.code('source-unavailable',lambda:self.trace.inspect_build(self.bid))
    def test_concurrent_replace(self):
        s=Snapshot(self.root); name='attempts/'+self.attempt+'/status.json'; s.read(name); self.put('replacement.json',{'status':'complete'}).replace(self.root/name); self.code('concurrent-change',s.finish)
    def test_malformed_schema(self):
        (self.root/('attempts/'+self.attempt+'/status.json')).write_text('{'); self.code('invalid-record',lambda:self.trace.inspect_build(self.bid))
        self.put('attempts/'+self.attempt+'/status.json',{'status':'pending'}); self.put('pipelines/'+self.pipeline+'/pipeline.json',dict(schema=2,pipeline_id=self.pipeline)); self.code('unsupported-schema',self.trace.list_builds)
    def test_request_mismatch(self):
        c,j=self.command(); self.reader.jobs[j]['request']=dict(self.reader.jobs[j]['request'],command=['other']); self.code('integrity-error',lambda:self.trace.inspect_command(self.bid,c))
    def test_current_recipe_ignored_idempotent(self):
        self.command(); a=self.trace.inspect_build(self.bid); (self.project/'package').mkdir(); (self.project/'package/gcc.py').write_text('raise RuntimeError()'); self.assertEqual(a,self.trace.inspect_build(self.bid))
    def test_retry_compare(self):
        self.command(argv=['cc','old.c']); self.put('attempts/retry/status.json',{'status':'complete'}); self.command(attempt='retry',argv=['cc','new.c'])
        r=self.trace.compare(self.bid,'attempt:retry'); self.assertEqual(r['differences'][0]['before']['command'],['cc','old.c']); self.assertEqual(r['differences'][0]['after']['command'],['cc','new.c'])
    def test_reused(self):
        p='attempts/'+self.attempt+'/packages/gcc'; self.put(p+'/result.json',dict(inputs={'package':'recipe','toolchain':'toolchain','dependencies':{}},identity='artifact',outputs=[])); self.put(p+'/artifact-reuse.json',dict(origin_pipeline='old',identity='artifact'))
        r=self.trace.inspect_build(self.bid); self.assertEqual(r['commands']['items'],[]); self.assertEqual(r['packages'][0]['reuse']['origin'],'imported'); self.assertEqual(len(self.trace.list_builds(package='gcc')['items']),1)
    def test_log_pages_and_availability(self):
        c,j=self.command(); self.reader.pages[(j,None)]=dict(job_id=j,status='ok',entries=[{'message':'first'}],next_cursor='cursor',has_more=True); self.reader.pages[(j,'cursor')]=dict(job_id=j,status='ok',entries=[{'message':'second'}],next_cursor='next',has_more=False)
        self.assertEqual(self.trace.logs(self.bid,c)['next_cursor'],'cursor'); self.assertEqual(self.trace.logs(self.bid,c,cursor='cursor')['entries'][0]['message'],'second')
        self.reader.pages.clear(); self.assertEqual(self.trace.logs(self.bid,c)['availability'],'empty-or-expired')
        self.reader.pages[(j,'cursor')]=dict(job_id=j,status='cursor-unavailable',entries=[],next_cursor=None); self.assertEqual(self.trace.logs(self.bid,c,cursor='cursor')['availability'],'cursor-expired-or-unavailable')
        self.reader.pages[(j,None)]=OSError('sensitive'); self.assertEqual(self.trace.logs(self.bid,c)['availability'],'retrieval-failure')
    def test_log_scope(self):
        c,j=self.command(); self.reader.pages[(j,None)]=dict(job_id='wrong',entries=[],status='ok'); self.code('invalid-record',lambda:self.trace.logs(self.bid,c))
        self.reader.pages[(j,'bad')]=ValueError(); self.code('invalid-cursor',lambda:self.trace.logs(self.bid,c,cursor='bad'))
    def test_pending(self):
        c,j=self.command(completion=False); self.reader.jobs[j]['state']='running'; self.assertEqual(self.trace.logs(self.bid,c)['availability'],'pending-or-empty')
    def test_redaction(self):
        c,j=self.command(argv=['/bin/sh','-c','TOKEN=hidden-token curl --password hidden-password https://u:pw@host']); self.reader.pages[(j,None)]=dict(job_id=j,status='ok',entries=[{'message':'password=hidden-log <script>alert(1)</script>'}],next_cursor=None)
        s=json.dumps(self.trace.export(self.bid))+json.dumps(self.trace.logs(self.bid,c))
        for secret in ('hidden-token','hidden-password','u:pw','hidden-log','"private"'): self.assertNotIn(secret,s)
        self.assertIn('<script>',s)
    def test_bounds(self):
        for limit in (True,0,101): self.code('invalid-query',lambda:self.trace.list_builds(limit=limit))
        self.code('response-too-large',lambda:response('test',message='x'*(1024*1024))); self.command(index=0); self.command(index=1); self.code('export-too-large',lambda:self.trace.export(self.bid,command_limit=1))
    def test_cli(self):
        self.command(); args=[sys.executable,'-m','zog.build_trace','--project-root',str(self.project),'--host-id','host-a']
        r=subprocess.run(args+['list','--package','gcc'],capture_output=True,text=True); self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(json.loads(r.stdout)['kind'],'build-list')
        r=subprocess.run(args+['inspect','attempt:missing'],capture_output=True,text=True); self.assertEqual(r.returncode,4); self.assertEqual(json.loads(r.stdout)['error']['code'],'not-found')

    def test_failed_logs_preserve_cursor(self):
        c,j=self.command()
        self.reader.pages[(j,'anchor')]=dict(job_id=j,status='unavailable',entries=[{'message':'partial'}],next_cursor='unsafe',has_more=True)
        r=self.trace.logs(self.bid,c,cursor='anchor')
        self.assertEqual(r['entries'],[]); self.assertEqual(r['next_cursor'],'anchor'); self.assertFalse(r['has_more'])
    def test_malformed_shape_safe_library_error(self):
        c,j=self.command(); p=self.root/('attempts/'+self.attempt+'/'+c+'.controller.json')
        p.write_text('{"binding": []}')
        self.code('invalid-record',lambda:self.trace.inspect_command(self.bid,c))
    def test_inspection_writes_nothing(self):
        self.command()
        def tree(): return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        before=tree(); self.trace.list_builds(); self.trace.inspect_build(self.bid); self.trace.export(self.bid)
        self.assertEqual(before,tree())
    def test_long_plain_log_bounded_redaction(self):
        self.assertEqual(response('test',message='x'*200000)['message'],'x'*200000)

if __name__=='__main__': unittest.main()
