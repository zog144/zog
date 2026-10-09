"""Optional contract acceptance against installed companion source, no live jobs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zog.build_trace import BuildTrace, BoxControlReader

AVAILABLE = importlib.util.find_spec('zog.image_build') is not None and importlib.util.find_spec('zog.box_control') is not None

@unittest.skipUnless(AVAILABLE, 'requires supported image-build and box-control sources on PYTHONPATH')
class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
    def recipe(self):
        p = self.project/'package/fixture'; p.mkdir(parents=True)
        payload=p/'payload'; payload.write_text('fixture')
        records={'sources.py':[dict(url=payload.as_uri(),sha256=hashlib.sha256(b'fixture').hexdigest(),destination='payload',archive=False)],
                 'dependencies.py':{'build':[],'runtime':[]},'build.py':{'build':[['fixture','build']],'install':[['fixture','install']]},
                 'produce-manifest.py':['usr/share/fixture']}
        for name,value in records.items(): (p/name).write_text(repr(value))
        (p.parent/'commit-pin.py').write_text(repr({'schema':1,'date':'2026-10-01','packages':{'fixture':{'sources':records['sources.py']}}}))
        return p
    def test_real_engine_retains_inspectable_records_after_cleanup(self):
        from zog.image_build import ImageBuild
        from zog.image_build.runner import BoxControlRunner, BuildExecutionResult
        from zog.image_build.build_views import read_build_commands
        self.recipe(); seed=self.project/'seed'; seed.mkdir(); (seed/'seed').write_text('fixture')
        def execute(request):
            if request.command[-1]=='install':
                out=request.output/'usr/share/fixture'; out.parent.mkdir(parents=True); out.write_text('fixture')
            return BuildExecutionResult('runtime','invocation',0,True,'journal')
        builder=ImageBuild(package_dir=self.project/'package',state_dir=self.project/'state',runner=BoxControlRunner(execute=execute))
        selection=builder.import_bootstrap(seed,{'id':'synthetic-fixture'})
        builder.verify_seed(['fixture'],host_bootstrap=selection)
        attempt=next((self.project/'state/image-build/attempts').iterdir())
        self.assertFalse((attempt/'packages/fixture/source').exists())
        original=read_build_commands(attempt)['commands']
        trace=BuildTrace(self.project,host_id='fixture-host')
        inspected=trace.inspect_build('attempt:'+attempt.name)
        self.assertEqual([c['command']['value'] for c in inspected['commands']['items']], [c['command'] for c in original])
        self.assertTrue(all(c['outcome']['value']=='success' for c in inspected['commands']['items']))
        self.assertEqual(len(inspected['packages']),1)
        provenance=inspected['commands']['items'][0]['provenance']['value']
        self.assertIsNotNone(provenance['recipe_identity'])
        self.assertIsNotNone(provenance['pin_set_identity'])
        self.assertIsNotNone(inspected['packages'][0]['inputs']['value']['toolchain'])
    def test_real_runner_failure_keeps_nonzero_completion(self):
        from zog.image_build.runner import BoxControlRunner, BuildExecutionResult
        from zog.image_build.errors import ImageBuildError
        folder=self.project/'state/image-build/attempts/failed/packages/fixture'; folder.mkdir(parents=True)
        runner=BoxControlRunner(execute=lambda r: BuildExecutionResult('runtime','invocation',7,True,'journal'))
        with self.assertRaises(ImageBuildError): runner.run(folder/'root',folder/'source',folder/'output',['false'],{},folder/'build-0.log')
        c=BuildTrace(self.project,host_id='fixture').inspect_command('attempt:failed','packages/fixture/build-0')
        self.assertEqual(c['outcome']['value'],'nonzero-exit')
    def test_real_controller_and_journal_cursor_contract(self):
        from zog.box_control import BoxControl, Project
        from zog.root_control.journal import read_build_logs
        from test_trace import TraceTests
        fixture=TraceTests('test_success'); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        command,job=fixture.command()
        path=fixture.project/'state/build-job'; path.mkdir()
        (path/(job+'.json')).write_text(json.dumps(fixture.reader.jobs[job]))
        class Transport:
            def build_job_logs(self, **kwargs): return read_build_logs(**kwargs)
        control=BoxControl(Project(fixture.project),systemd_transport=Transport())
        trace=BuildTrace(fixture.project,host_id='fixture',controller=BoxControlReader(control))
        def row(cursor,message): return dict(__CURSOR=cursor,MESSAGE=message,_BOOT_ID='e'*32,_SYSTEMD_INVOCATION_ID='d'*32)
        with patch('zog.root_control.journal.run_bounded',return_value=[row('one','hello')]):
            first=trace.logs(fixture.bid,command)
        with patch('zog.root_control.journal.run_bounded',return_value=[row('one','hello'),row('two','world')]):
            second=trace.logs(fixture.bid,command,cursor=first['next_cursor'])
        self.assertEqual([x['message'] for x in second['entries']],['world'], (first, second))
        with patch('zog.root_control.journal.run_bounded',return_value=[]):
            expired=trace.logs(fixture.bid,command,cursor=first['next_cursor'])
        self.assertEqual(expired['availability'],'cursor-expired-or-unavailable')
        (path/(job+'.json')).unlink()
        self.assertEqual(trace.inspect_command(fixture.bid,command)['outcome']['value'],'success')

if __name__=='__main__': unittest.main()
