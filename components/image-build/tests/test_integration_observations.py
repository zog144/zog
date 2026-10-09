import json
from pathlib import Path
import shutil
import subprocess

import pytest
from zog.image_build import integration_observations as io, verification_observations as vo
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory, write_json
from zog.image_build.metadata import identity


def generation(tmp_path):
    from test_installed_verification import scenario, capture
    from zog.image_build import generation_provenance as gp
    s=scenario(tmp_path)
    report=capture(s);pointer=gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])
    selected=s.builder._publish(s.root,s.owner,'image',dict(packages=s.built,
        build_record=pointer,verification_execution=s.execution))
    return s,selected


def test_generation_export_is_deterministic_and_bound(tmp_path):
    s,selected=generation(tmp_path)
    first=io.export_generation(s.p,selected)
    assert first==io.export_generation(s.p,selected)
    assert first['context']['generation_record']==selected.manifest['build_record']['record']
    assert first['verification']['checks'][0]['check_id']=='image-build/installed-trust/command/0'
    result=first['verification']['results'][0]
    assert result['outcome']=='PASS'
    assert result['subject']['generation_id']==first['context']['generation_id']
    assert result['execution']['invocation_id']=='invocation'
    assert any(g['reason']=='legacy-output-without-source-or-recipe' for g in first['gaps'])
    assert io.export_candidate(s.p,selected.generation)['results'][0]['id']==result['id']
    (selected.root/'payload').write_text('changed')
    with pytest.raises(ImageBuildError):io.export_generation(s.p,selected)


def test_report_fallback_does_not_invent_historical_capture(tmp_path):
    s,selected=generation(tmp_path)
    shutil.rmtree(s.p.root/'observation-index')
    result=io.export_generation(s.p,selected)['verification']['results'][0]
    assert result['evidence'][0]['kind']=='canonical-installed-report'
    assert result['timing']['started_at'] is None


def test_named_failure_capture_replay_and_unknown(tmp_path):
    from test_installed_verification import scenario
    s=scenario(tmp_path)
    prepared=json.loads((s.check/'prepared.json').read_text())
    failed=s.check.parent/'failed-check';failed.mkdir()
    raw=dict(s.execution,exit_code=2)
    raw['request']=dict(raw['request'],root=str((failed/'root').resolve()))
    write_json(failed/'command-0.execution.json',raw)
    a=vo.capture(s.builder,failed,prepared,0)
    assert a==vo.capture(s.builder,failed,prepared,0)
    results=io.export_candidate(s.p,s.binding['generation'])['results']
    assert {r['outcome'] for r in results}=={'PASS','FAIL'}
    assert len({r['check_id'] for r in results})==1
    raw['exit_code']=0;write_json(failed/'command-0.execution.json',raw)
    with pytest.raises(ImageBuildError,match='immutable'):vo.capture(s.builder,failed,prepared,0)
    unknown=s.check.parent/'unknown';unknown.mkdir()
    assert vo.capture(s.builder,unknown,prepared,0,RuntimeError('timeout waiting')) is None


def test_terminal_controller_error_is_distinct(tmp_path):
    from test_installed_verification import scenario
    from types import SimpleNamespace
    s=scenario(tmp_path);prepared=json.loads((s.check/'prepared.json').read_text())
    folder=s.check.parent/'error-check';folder.mkdir()
    write_json(folder/'command-0.controller.json',{'job_id':'job','request_id':'request'})
    error=SimpleNamespace(record={'state':'completed','outcome':'timeout','job_id':'job',
        'request_id':'request','invocation_id':'invocation-error','exit_code':None})
    descriptor=vo.capture(s.builder,folder,prepared,0,error)
    value=json.loads(io.artifact(s.p,descriptor))
    assert value['outcome']=='ERROR' and value['execution']['outcome']=='timeout'
    error.record['job_id']='wrong'
    with pytest.raises(ImageBuildError,match='identity'):vo.capture(s.builder,folder,prepared,0,error)


def test_artifact_elf_and_script_interfaces_without_execution(tmp_path):
    from zog.image_build.artifact_observations import scan
    cc=shutil.which('cc');readelf=shutil.which('readelf')
    if not cc or not readelf:pytest.skip('ELF fixture compiler/tools absent')
    root=tmp_path/'root';root.mkdir()
    source=tmp_path/'fixture.c';source.write_text('int main(void){return 0;}\n')
    subprocess.run([cc,str(source),'-o',str(root/'program')],check=True)
    subprocess.run([cc,'-shared','-fPIC',str(source),'-Wl,-soname,libfixture.so.7','-o',str(root/'libfixture.so.7')],check=True)
    (root/'script').write_text('#!/usr/bin/env python3\nraise Exception("do not run")\n')
    (root/'bad').write_bytes(b'\x7fELFbroken')
    (root/'link').symlink_to('/outside')
    result=scan(root,inventory(root),{},readelf=readelf)
    rows={(r['relation'],r['target']['value']) for r in result['relationships']}
    assert ('provides-soname','libfixture.so.7') in rows
    assert ('needs-library','libc.so.6') in rows
    assert any(r[0]=='elf-interpreter' for r in rows)
    assert ('script-interpreter','/usr/bin/env') in rows
    assert not any(r['target']['value']=='python3' for r in result['relationships'])
    assert any(i['path']=='/bad' for i in result['issues'])
    missing=scan(root,inventory(root),{},readelf='missing-readelf-fixture')
    assert any(i['reason']=='readelf-unavailable' for i in missing['issues'])


def test_frozen_source_identity_and_dependency_projection(tmp_path):
    from types import SimpleNamespace
    import hashlib
    artifacts=tmp_path/'artifacts';artifacts.mkdir()
    def material(name,value):
        raw=repr(value).encode();digest=hashlib.sha256(raw).hexdigest();(artifacts/digest).write_bytes(raw)
        return {'name':name,'digest':'sha256:'+digest,'size':len(raw)}
    source={'url':'https://example.invalid/release.tar.xz','sha256':'a'*64,'destination':'upstream','archive':True}
    declaration={'schema':1,'sources':[{'source':source,'upstream':[{'repository':'https://example.invalid/repo','revision':'b'*40,'revision_type':'git'}]}]}
    files=[material('package/source-provenance.py',declaration),material('package/sources.py',[source]),
        material('package/dependencies.py',{'build':['compiler'],'runtime':['library'],'test':['fixture']}),
        material('package/integration.py',{'project':'example'})]
    raw=json.dumps({'files':files}).encode();digest=hashlib.sha256(raw).hexdigest();(artifacts/digest).write_bytes(raw)
    recipe={'name':'recipe','digest':'sha256:'+digest,'size':len(raw)}
    def rec(kind,**data):return {'kind':kind,'data':data,'gaps':[]}
    bundle={'records':{'out':rec('package-output',package='example-final',attempt='start'),
        'dep':rec('package-output',package='compiler',attempt=None),
        'start':rec('attempt-start',inputs='inputs'),
        'inputs':rec('build-inputs',recipe=recipe,sources=['source'],dependencies=[{'output':'dep'}]),
        'source':rec('source-selection',pin={'digest':'sha256:'+'c'*64},upstream=[],
                     archives=[{'name':'upstream','digest':'sha256:'+'a'*64,'size':1}])}}
    sources,relationships,gaps=io.source_and_package_facts(SimpleNamespace(root=tmp_path),bundle,
        {'example-final':{'provenance':{'output':'out'}}})
    assert sources[0]['upstream']==declaration['sources'][0]['upstream']
    assert sources[0]['downloads']==[source] and sources[0]['release_tags']==[]
    assert {r['relation'] for r in relationships}=={'declares-build-dependency','declares-runtime-dependency','declares-test-dependency','used-build-output'}
    (artifacts/recipe['digest'][7:]).write_text('changed')
    with pytest.raises(ImageBuildError,match='digest'):io.source_and_package_facts(SimpleNamespace(root=tmp_path),bundle,{'example-final':{'provenance':{'output':'out'}}})


def test_real_canonical_source_projection_and_tag(tmp_path):
    from test_provenance import Scenario
    from test_source_provenance import declare, run
    s=Scenario(tmp_path);declare(s,kind='tag',revision='v1.2.3')
    selected=run(s);export=io.export_generation(s.provenance,selected)
    assert export['sources'][0]['release_tags']==[{'repository':'fixture:upstream','tag':'v1.2.3'}]
    assert export['sources'][0]['upstream'][0]['revision_type']=='tag'
    assert export['sources'][0]['archive']['digest'].startswith('sha256:')
    assert export['verification']['results']==[]
    assert any(g['reason']=='no-canonical-named-verification-report' for g in export['gaps'])
    assert_schema(export,'integration-observations-v1')


def assert_schema(value, name):
    """Check our published schema subset without adding a runtime dependency."""
    import re
    schema=json.loads((Path(__file__).parents[1]/'docs/schemas'/(name+'.schema.json')).read_text())
    def check(v,s):
        if 'const' in s:assert v==s['const']
        if 'enum' in s:assert v in s['enum']
        if 'type' in s:
            types=s['type'] if isinstance(s['type'],list) else [s['type']]
            kinds={'object':dict,'array':list,'string':str,'integer':int,'null':type(None)}
            assert any(type(v) is kinds[k] for k in types)
        if isinstance(v,dict):
            assert set(s.get('required',[]))<=set(v)
            if s.get('additionalProperties') is False:assert set(v)<=set(s['properties'])
            for key,child in s.get('properties',{}).items():
                if key in v:check(v[key],child)
        if isinstance(v,list):
            assert len(v)>=s.get('minItems',0)
            for x in v:check(x,s.get('items',{}))
        if isinstance(v,str):
            assert len(v)>=s.get('minLength',0)
            if 'pattern' in s:assert re.search(s['pattern'],v)
        if type(v) is int and 'minimum' in s:assert v>=s['minimum']
    check(value,schema)


def test_exported_generation_and_candidate_match_published_schemas(tmp_path):
    s,selected=generation(tmp_path)
    exported=io.export_generation(s.p,selected)
    assert_schema(exported,'integration-observations-v1')
    candidates=io.export_candidate(s.p,selected.generation)
    assert_schema(candidates,'candidate-verifications-v1')
    assert_schema(candidates['results'][0],'verification-observation-v1')


def test_failed_execution_is_automatically_captured(tmp_path):
    from test_installed_verification import scenario
    from zog.image_build.runner import BoxControlRunner,BuildExecutionResult
    from zog.image_build.developer.seed_build import verify
    s=scenario(tmp_path)
    def failure(request):return BuildExecutionResult('failed-job','failed-invocation',3,True,'failed-journal')
    failure.configuration=lambda:{'fixture':'controller-policy'}
    s.builder.runner=BoxControlRunner(execute=failure)
    with pytest.raises(ImageBuildError,match='status 3'):
        verify(s.builder,s.check.parent/'new-failed',s.root,[['/bin/bash','-eu','-c','fixture-check']],s.owner)
    results=io.export_candidate(s.p,s.binding['generation'])['results']
    failed=next(r for r in results if r['outcome']=='FAIL')
    assert failed['execution']['invocation_id']=='failed-invocation'
    assert_schema(failed,'verification-observation-v1')


def test_observation_timestamp_survives_lost_capture_response(tmp_path,monkeypatch):
    from test_installed_verification import scenario
    s=scenario(tmp_path);prepared=json.loads((s.check/'prepared.json').read_text())
    folder=s.check.parent/'interrupted-capture';folder.mkdir()
    raw=dict(s.execution,request=dict(s.execution['request'],root=str((folder/'root').resolve())))
    write_json(folder/'command-0.execution.json',raw)
    original=s.p._bytes;lost=[]
    def fail(name,value):
        result=original(name,value)
        if name=='verification-observation.json' and not lost:
            lost.append(result);raise OSError('lost artifact response')
        return result
    monkeypatch.setattr(s.p,'_bytes',fail)
    with pytest.raises(OSError):vo.capture(s.builder,folder,prepared,0)
    result=vo.capture(s.builder,folder,prepared,0)
    assert result==lost[0]
    assert json.loads(io.artifact(s.p,result))['timing']['observed_at'] is not None
