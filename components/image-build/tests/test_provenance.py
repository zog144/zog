"""Opt-in producer acceptance using real engine/runner, synthetic execution only."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pytest

pytest.importorskip("zog.build_record")
from zog.build_record import inspect
from zog.image_build import ImageBuild
from zog.image_build.errors import ImageBuildError
from zog.image_build.metadata import identity
from zog.image_build.provenance import Provenance
from zog.image_build.runner import BoxControlRunner, BuildExecutionResult

class Scenario:
    def __init__(self,tmp_path):
        self.root=tmp_path; self.calls=[]; self.fail=False; self.interrupt=False
        recipe=tmp_path/'package/fixture';recipe.mkdir(parents=True)
        payload=tmp_path/'payload';payload.write_bytes(b'controlled source')
        sources=[dict(url=payload.as_uri(),sha256=hashlib.sha256(payload.read_bytes()).hexdigest(),destination='payload',archive=False)]
        for name,data in {'sources.py':sources,'dependencies.py':{'build':[],'runtime':[]},
             'build.py':{'build':[['fixture','build']],'install':[['fixture','install']]},
             'produce-manifest.py':['usr/share/fixture']}.items(): (recipe/name).write_text(repr(data))
        self.original=tmp_path/'original-pin.py'
        monthly=dict(schema=1,date='2026-10-01',packages={'fixture':{'recipes':{'stage':sources}}})
        self.original.write_text(repr(monthly))
        selected=dict(schema=1,date='2026-10-01',monthly_identity=identity(monthly),
            packages={'fixture':{'sources':sources,'project':'fixture','recipe':'stage'}})
        (recipe.parent/'commit-pin.py').write_text(repr(selected))
        self.pin=Provenance.capture_pin(tmp_path/'state',self.original,repository='fixture:catalogue',revision='1'*40,repository_path='pins/2026-10-01/commit-pin.py')
        self.provenance=Provenance(tmp_path/'state',host_id='host-a',project_id='project-a',pin=self.pin)
        self.builder=self.reopen()
        seed=tmp_path/'seed';seed.mkdir();(seed/'fixture-seed').write_text('seed')
        self.seed=self.builder.import_bootstrap(seed,{'id':'fixture'})
    def execute(self,request):
        self.calls.append(request.command)
        if self.interrupt: raise OSError('controlled lost execution response')
        if request.command[-1]=='install':
            path=request.output/'usr/share/fixture';path.parent.mkdir(parents=True);path.write_text('accepted package output')
        return BuildExecutionResult('runtime','invocation-'+request.command[-1],7 if self.fail else 0,True,'fixture-journal')
    def reopen(self, retry_of=None):
        if retry_of is not None:
            self.provenance=Provenance(self.root/'state',host_id='host-a',project_id='project-a',pin=self.pin,retry_of=retry_of)
        return ImageBuild(package_dir=self.root/'package',state_dir=self.root/'state',runner=BoxControlRunner(execute=self.execute),provenance=self.provenance)
    def pipeline(self):
        return max((self.root/'state/image-build/pipelines').glob('*/pipeline.json'),key=lambda p:p.stat().st_mtime_ns)
    def binding(self,pipeline=None):
        data=json.loads((pipeline or self.pipeline()).read_text())
        attempt=next(iter(data['attempts'].values()))
        path=self.root/'state/image-build/attempts'/attempt/'packages/fixture/provenance.json'
        return path,json.loads(path.read_text())

def test_failed_retry_output_and_frozen_pin(tmp_path):
    s=Scenario(tmp_path);s.fail=True
    with pytest.raises(ImageBuildError): s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    old_pipeline=s.pipeline();path,failed=s.binding(old_pipeline)
    prior=s.provenance.store.get(failed['result'])
    assert prior['data']['outcome']=='failed' and not prior['data']['outputs']
    original_failure=path.read_bytes()
    s.builder.release_pipeline(old_pipeline.parent.name)
    s.fail=False;s.builder=s.reopen({'fixture':failed['result']})
    result=s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    _,accepted=s.binding()
    assert accepted['prepared']!=failed['prepared'] and path.read_bytes()==original_failure
    bundle=s.provenance.store.bundle([accepted['result']]);report=inspect(bundle)
    assert not report['missing_records']
    assert bundle['records'][accepted['prepared']]['data']['retry_of']==failed['result']
    assert bundle['records'][accepted['result']]['data']['outcome']=='succeeded'
    assert bundle['records'][accepted['output']]['data']['attempt']==accepted['prepared']
    assert (result.root/'usr/share/fixture').read_text()=='accepted package output'

def test_reopen_uses_captured_pin_and_same_preparation(tmp_path):
    s=Scenario(tmp_path);s.interrupt=True
    with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();path,prepared=s.binding()
    assert prepared['result'] is None
    s.original.write_text('changed current pin is not used during recovery')
    (s.root/'package/commit-pin.py').write_text('changed current materialized pin')
    s.interrupt=False;s.builder=s.reopen()
    s.builder.resume(pipeline.parent.name)
    completed=json.loads(path.read_text())
    assert completed['prepared']==prepared['prepared'] and completed['result'] is not None

@pytest.mark.parametrize('mode',['missing','tampered'])
def test_required_recipe_material_blocks_resume(tmp_path,mode):
    s=Scenario(tmp_path);s.interrupt=True
    with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();_,binding=s.binding()
    inputs=s.provenance.store.get(binding['inputs'])['data']
    artifact=s.provenance.root/'artifacts'/inputs['recipe']['digest'][7:]
    if mode=='missing':artifact.unlink()
    else:artifact.write_text('tampered')
    before=len(s.calls);s.interrupt=False
    with pytest.raises(ImageBuildError):s.builder.resume(pipeline.parent.name)
    assert len(s.calls)==before

def test_binding_write_failure_prevents_dispatch(tmp_path):
    s=Scenario(tmp_path)
    from zog.image_build.filesystem import write_json
    def fail(path,record):
        if Path(path).name=='provenance.json':raise OSError('controlled binding storage failure')
        return write_json(path,record)
    with patch('zog.image_build.provenance.write_json',side_effect=fail):
        with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    assert not s.calls

def test_finalization_write_failure_reuses_same_result(tmp_path):
    s=Scenario(tmp_path)
    from zog.image_build.filesystem import write_json
    def fail(path,record):
        if Path(path).name=='provenance.json' and record.get('result'):raise OSError('controlled final pointer failure')
        return write_json(path,record)
    with patch('zog.image_build.provenance.write_json',side_effect=fail):
        with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();path,binding=s.binding()
    intent=json.loads(path.with_name('provenance-finalizing.json').read_text())
    from zog.build_record import record_id
    expected=record_id(intent);before=len(s.calls)
    assert binding['result'] is None
    s.builder.resume(pipeline.parent.name)
    assert json.loads(path.read_text())['result']==expected and len(s.calls)==before

def test_source_tamper_blocks_before_dispatch(tmp_path):
    s=Scenario(tmp_path)
    from zog.image_build.provenance import _publish_artifact
    def intercept(root,**kw):
        source=kw.get('source')
        if source and source.parent.name=='sources':source.write_bytes(b'changed source')
        return _publish_artifact(root,**kw)
    with patch('zog.image_build.provenance._publish_artifact',side_effect=intercept):
        with pytest.raises(ImageBuildError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    assert not s.calls

def test_prepare_pointer_retry_reuses_original_start(tmp_path):
    s=Scenario(tmp_path)
    from zog.image_build.filesystem import write_json
    def fail(path,record):
        if Path(path).name=='provenance.json':raise OSError('controlled pointer failure')
        return write_json(path,record)
    with patch('zog.image_build.provenance.write_json',side_effect=fail):
        with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();attempt=next(iter(json.loads(pipeline.read_text())['attempts'].values()))
    preparing=s.root/'state/image-build/attempts'/attempt/'packages/fixture/provenance-preparing.json'
    from zog.build_record import record_id
    expected=record_id(json.loads(preparing.read_text()))
    s.builder.resume(pipeline.parent.name)
    _,binding=s.binding()
    assert binding['prepared']==expected


def test_trace_joins_real_engine_failure_and_retry(tmp_path):
    pytest.importorskip('build_trace')
    from build_trace import BuildTrace
    s=Scenario(tmp_path);s.fail=True
    with pytest.raises(ImageBuildError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();_,failed=s.binding()
    s.builder.release_pipeline(pipeline.parent.name)
    s.fail=False;s.builder=s.reopen({'fixture':failed['result']})
    s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    _,success=s.binding()
    trace=BuildTrace(s.root,host_id='host-a',record_project_id='project-a',record_store=s.provenance.store.directory)
    report=trace.provenance(success['build_id'],'fixture',limit=2)
    assert report['record_count']==7 and report['records']['has_more'] and report['missing_record_count']==0
    assert report['gap_count']>0 and report['artifact_verification']=='not-checked'
    comparison=trace.compare_provenance(failed['build_id'],success['build_id'],'fixture')
    assert comparison['same_inputs'] and comparison['different_attempt']
    command=trace.inspect_command(success['build_id'],'packages/fixture/build-0')
    assert command['provenance']['value']['build_record']['prepared']==success['prepared']

def test_legacy_output_does_not_gain_current_inputs(tmp_path):
    s=Scenario(tmp_path)
    ref=s.provenance.legacy_output('legacy',{'outputs':[{'path':'file','kind':'file','sha256':'0'*64}]})
    record=s.provenance.store.get(ref['output'])
    assert record['data']['attempt'] is None and ref['result'] is None and record['gaps']

def test_changed_retained_pipeline_recipe_blocks_recovery(tmp_path):
    s=Scenario(tmp_path);s.interrupt=True
    with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();(pipeline.parent/'package/fixture/build.py').write_text("{'build':[['changed']]}")
    before=len(s.calls);s.interrupt=False
    with pytest.raises(ImageBuildError):s.builder.resume(pipeline.parent.name)
    assert len(s.calls)==before

def test_provenance_cannot_be_disabled_during_recovery(tmp_path):
    s=Scenario(tmp_path);s.interrupt=True
    with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();before=len(s.calls)
    disabled=ImageBuild(package_dir=s.root/'package',state_dir=s.root/'state',runner=s.builder.runner)
    with pytest.raises(ImageBuildError):disabled.resume(pipeline.parent.name)
    assert len(s.calls)==before

def test_dependency_output_and_result_are_bound(tmp_path):
    import ast, shutil
    s=Scenario(tmp_path)
    dependency=tmp_path/'package/dependency'
    shutil.copytree(tmp_path/'package/fixture',dependency)
    (dependency/'build.py').write_text(repr({'build':[['dependency','build']],'install':[['dependency','install']]}))
    (dependency/'produce-manifest.py').write_text(repr(['usr/share/dependency']))
    (tmp_path/'package/fixture/dependencies.py').write_text(repr({'build':['dependency'],'runtime':['dependency']}))
    monthly=ast.literal_eval(s.original.read_text());monthly['packages']['dependency']=monthly['packages']['fixture']
    s.original.write_text(repr(monthly))
    selected=ast.literal_eval((tmp_path/'package/commit-pin.py').read_text())
    selected['monthly_identity']=identity(monthly)
    selected['packages']['dependency']={**selected['packages']['fixture'],'project':'dependency'}
    (tmp_path/'package/commit-pin.py').write_text(repr(selected))
    s.pin=Provenance.capture_pin(tmp_path/'state',s.original,repository='fixture:catalogue',revision='2'*40,repository_path='pins/2026-10-01/commit-pin.py')
    s.provenance=Provenance(tmp_path/'state',host_id='host-a',project_id='project-a',pin=s.pin)
    def execute(request):
        if request.command[0]=='dependency':
            path=request.output/'usr/share/dependency';path.parent.mkdir(parents=True,exist_ok=True);path.write_text('dependency output')
            return BuildExecutionResult('runtime','invocation-dependency',0,True,'journal')
        return s.execute(request)
    s.builder=s.reopen();s.builder.runner=BoxControlRunner(execute=execute)
    s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    _,binding=s.binding();bundle=s.provenance.store.bundle([binding['result']])
    inputs=bundle['records'][binding['inputs']]['data']
    assert len(inputs['dependencies'])==1
    dependency=inputs['dependencies'][0]
    assert bundle['records'][dependency['output']]['data']['package']=='dependency'
    assert bundle['records'][dependency['result']]['data']['outcome']=='succeeded'

def test_changed_runner_settings_block_recovery(tmp_path):
    s=Scenario(tmp_path);s.interrupt=True
    with pytest.raises(OSError):s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)
    pipeline=s.pipeline();before=len(s.calls)
    s.builder.runner.timeout+=1;s.interrupt=False
    with pytest.raises(ImageBuildError):s.builder.resume(pipeline.parent.name)
    assert len(s.calls)==before
