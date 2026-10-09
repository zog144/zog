"""Owner contract, interruption and historical diagnostic integration fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from test_trace import TraceTests as _Fixture
from zog.build_trace import BuildTrace

AVAILABLE = importlib.util.find_spec('zog.image_build') is not None

@unittest.skipUnless(AVAILABLE, 'requires image-build owner capture API')
class HardeningTests(unittest.TestCase):
    setUp = _Fixture.setUp
    put = _Fixture.put
    command = _Fixture.command
    code = _Fixture.code
    def identity(self, command, **kwargs):
        from zog.image_build.trace_records import capture_identity
        return capture_identity(self.root/f'attempts/{self.attempt}/{command}.log',
            attempt_id=self.attempt, command_id=command, package='gcc', stage_id='final',
            phase='build', command_index=0, pipeline_id=self.pipeline, **kwargs)

    def test_hardening_stable_identity_and_artifact_refs(self):
        c,j=self.command(); self.assertTrue(self.identity(c, provenance={'recipe_identity':'old'}))
        self.assertFalse(self.identity(c, provenance={'recipe_identity':'new'}))
        first=self.trace.inspect_command(self.bid,c)
        self.assertIn('build 0 · final', first['title'])
        self.assertEqual(first['provenance']['value']['recipe_identity'],'old')
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(first,BuildTrace(self.project,host_id='host-a',controller=self.reader).inspect_command(self.bid,c))
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertIn('completion',[e['kind'] for e in first['evidence']])

    def test_hardening_retained_reboot_unknown_no_replay(self):
        from zog.image_build.trace_records import capture_observation
        c,j=self.command(completion=False,outcome='unknown'); self.identity(c)
        raw=dict(self.reader.jobs[j],process_cleanup_complete=False,error='original outcome unknown after reboot')
        capture_observation(self.root/f'attempts/{self.attempt}/{c}.controller.json',raw)
        self.reader.jobs.clear()
        result=self.trace.inspect_command(self.bid,c)
        self.assertEqual(result['recovery']['status'],'blocked')
        self.assertEqual(result['failure_summary']['submission'],'established')
        self.assertEqual(result['outcome']['value'],'unknown')
        self.assertEqual(result['controller_availability'],'missing-or-pruned')
        self.assertFalse(result['recovery']['automatic_action'])
        self.assertIsNotNone(result['observed_at']['value'])

    def test_hardening_prepared_identity_does_not_prove_submission(self):
        c,j=self.command(completion=False); self.reader.jobs.clear()
        result=self.trace.inspect_command(self.bid,c)
        self.assertEqual(result['failure_summary']['submission'],'prepared-only')
        self.assertEqual(result['failure_summary']['execution'],'not-established')
        self.assertEqual(result['recovery']['status'],'unknown')

    def test_hardening_failure_independent_of_cleanup(self):
        from zog.image_build.trace_records import capture_observation
        c,j=self.command(completion=False,outcome='signal')
        raw=dict(self.reader.jobs[j],state='cleanup',outcome='signal',signal=9,exit_code=None,process_cleanup_complete=False)
        capture_observation(self.root/f'attempts/{self.attempt}/{c}.controller.json',raw)
        self.reader.jobs.clear()
        r=self.trace.inspect_command(self.bid,c)
        self.assertEqual(r['failure_summary']['status'],'failed')
        self.assertEqual(r['failure_summary']['signal']['value'],9)
        self.assertEqual(r['recovery']['status'],'pending')

    def test_hardening_import_diagnostic_and_explicit_retry(self):
        from zog.image_build.trace_records import import_diagnostic
        c,j=self.command(outcome='nonzero-exit'); old=self.trace.inspect_command(self.bid,c)
        raw=self.reader.jobs[j]
        log=self.root/'attempts/diagnostic/probe.log'
        links=[{'relation':'diagnostic-of','target':{'attempt_id':self.attempt,'command_id':c}}]
        self.assertTrue(import_diagnostic(log,attempt_id='diagnostic',command_id='probe',package='gcc',
            stage_id='diagnostic',phase='test',command_index=0,controller_record=raw,
            receipts=['attempts/diagnostic/exact-job.json'],relationships=links))
        result=self.trace.inspect_command('attempt:diagnostic','probe')
        self.assertEqual(result['relationships']['value'],links)
        self.assertEqual(result['category'],'diagnostic')
        self.assertEqual(result['provenance']['origin'],'imported')
        self.assertFalse(log.with_suffix('.controller.json').exists())
        self.assertFalse(log.with_suffix('.execution.json').exists())
        self.assertEqual(self.trace.inspect_command(self.bid,c),old)
        self.assertTrue(any(r['id']=='attempt:diagnostic' for r in self.trace.list_builds(package='gcc')['items']))
        self.assertEqual(self.trace.inspect_build('attempt:diagnostic')['retry_relationships']['value'][0]['relation'],'diagnostic-of')

    def test_hardening_pre_persistence_redaction(self):
        from zog.image_build.trace_records import capture_request, capture_observation
        c,j=self.command(); raw=self.reader.jobs[j]; log=self.root/f'attempts/{self.attempt}/{c}.log'
        request=dict(raw['request'],command=['bash','-c','TOKEN=hidden-one echo ok','--password','hidden-two'],environment={'PATH':'/bin','CUSTOM':'hidden-three'})
        self.assertTrue(capture_request(log,request))
        capture_observation(log.with_suffix('.controller.json'),dict(raw,error='password=hidden-four'))
        data=log.with_suffix('.summary.json').read_text()+log.with_suffix('.observation.json').read_text()
        for word in ('hidden-one','hidden-two','hidden-three','hidden-four'): self.assertNotIn(word,data)

    def test_hardening_conflicting_observation_fails_closed(self):
        from zog.image_build.trace_records import capture_observation
        c,j=self.command(); raw=dict(self.reader.jobs[j],job_id='f'*32)
        capture_observation(self.root/f'attempts/{self.attempt}/{c}.controller.json',raw)
        self.code('integrity-error',lambda:self.trace.inspect_command(self.bid,c))

    def test_hardening_completion_beats_stale_running_observation(self):
        from zog.image_build.trace_records import capture_observation
        c,j=self.command()
        raw=dict(self.reader.jobs[j],state='running',outcome=None,exit_code=None,process_cleanup_complete=False)
        capture_observation(self.root/f'attempts/{self.attempt}/{c}.controller.json',raw)
        self.reader.jobs.clear()
        result=self.trace.inspect_command(self.bid,c)
        self.assertEqual(result['outcome']['value'],'success')
        self.assertEqual(result['recovery']['status'],'complete')

    def test_hardening_import_cannot_rebind_job(self):
        from zog.image_build.trace_records import import_diagnostic
        c,j=self.command()
        args=dict(attempt_id='diagnostic',command_id='probe',package='gcc',stage_id='final',phase='test',command_index=0,
                  receipts=['attempts/diagnostic/job.json'])
        log=self.root/'attempts/diagnostic/probe.log'
        self.assertTrue(import_diagnostic(log,controller_record=self.reader.jobs[j],**args))
        old=log.with_suffix('.observation.json').read_bytes()
        request_id='r1-123-'+'b'*32+'-'+'c'*64
        raw=dict(self.reader.jobs[j],request_id=request_id,job_id=hashlib.sha256(request_id.encode()).hexdigest()[:32])
        self.assertFalse(import_diagnostic(log,controller_record=raw,**args))
        self.assertEqual(log.with_suffix('.observation.json').read_bytes(),old)

    def test_hardening_optional_capture_failure_does_not_fail_build(self):
        from zog.image_build.runner import BoxControlRunner, BuildExecutionResult
        from zog.image_build.trace_records import capture_request, MAX_BYTES
        log=self.root/'attempts/optional/build.log'
        with patch('zog.image_build.trace_records.write_json',side_effect=OSError('unavailable')):
            runner=BoxControlRunner(execute=lambda r:BuildExecutionResult('runtime','invocation',0,True,'journal'))
            runner.run(self.project,self.project,self.project,['true'],{},log)
        self.assertTrue(log.with_suffix('.execution.json').exists())
        self.assertFalse(capture_request(log,{'command':['x'*MAX_BYTES]}))

del _Fixture
