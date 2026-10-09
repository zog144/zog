"""Generation closure, immutable reuse, and durable publication boundary fixtures."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
pytest.importorskip("zog.build_record")
from zog.build_record import Store, inspect, record_id, canonical
from zog.image_build import ImageBuild
from zog.image_build.artifacts import import_completed
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import write_json
from zog.image_build.metadata import identity
from zog.image_build.provenance import Provenance, _publish_artifact
from zog.image_build.runner import BoxControlRunner, BuildExecutionResult
from test_provenance import Scenario


def pair(tmp_path, *, runtime=True):
    s = Scenario(tmp_path)
    dep = tmp_path/'package/dependency'
    shutil.copytree(tmp_path/'package/fixture', dep)
    (dep/'build.py').write_text(repr({'build':[['dependency','build']], 'install':[['dependency','install']]}))
    (dep/'produce-manifest.py').write_text(repr(['usr/share/dependency']))
    (tmp_path/'package/fixture/dependencies.py').write_text(repr({'build':['dependency'], 'runtime':['dependency'] if runtime else []}))
    monthly = ast.literal_eval(s.original.read_text())
    monthly['packages']['dependency'] = monthly['packages']['fixture']
    s.original.write_text(repr(monthly))
    selected = ast.literal_eval((tmp_path/'package/commit-pin.py').read_text())
    selected['monthly_identity'] = identity(monthly)
    selected['packages']['dependency'] = {**selected['packages']['fixture'], 'project':'dependency'}
    (tmp_path/'package/commit-pin.py').write_text(repr(selected))
    s.pin = Provenance.capture_pin(tmp_path/'state', s.original, repository='fixture:catalogue', revision='2'*40, repository_path='pins/2026-10-01/commit-pin.py')
    s.provenance = Provenance(tmp_path/'state', host_id='host-a', project_id='project-a', pin=s.pin)
    s.builder = s.reopen()
    def execute(request):
        if request.command[0] == 'dependency':
            s.calls.append(request.command)
            if request.command[-1] == 'install':
                path = request.output/'usr/share/dependency'
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text('dependency output')
            return BuildExecutionResult('runtime','dependency',0,True,'journal')
        return s.execute(request)
    s.builder.runner = BoxControlRunner(execute=execute)
    return s


def run(s, targets=None):
    return s.builder.verify_seed(targets or ['fixture'], host_bootstrap=s.seed)


def assembly(s):
    pipeline = json.loads(s.pipeline().read_bytes())
    return s.root/'state/image-build/attempts'/next(iter(pipeline['attempts'].values()))/'assembly'


def test_capture_ignores_read_atime_but_detects_mutation(tmp_path):
    source = tmp_path/'source'; source.write_bytes(b'unchanged')
    os.utime(source, (time.time()-172800,time.time()-86400))
    asset = _publish_artifact(tmp_path/'store', source=source)
    assert asset['digest'] == 'sha256:'+hashlib.sha256(b'unchanged').hexdigest()
    original = os.fstat
    calls = 0
    def changed(fd):
        nonlocal calls
        info = original(fd); calls += 1
        fields = {key:getattr(info,key) for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode')}
        if calls == 2:
            fields['st_mtime_ns'] += 1
        return SimpleNamespace(**fields)
    with patch('zog.image_build.provenance.os.fstat', side_effect=changed):
        with pytest.raises(ImageBuildError, match='changed during capture'):
            _publish_artifact(tmp_path/'other', source=source)


def test_generation_export_is_independently_inspectable(tmp_path):
    s = pair(tmp_path, runtime=False); result = run(s)
    pointer = result.manifest['build_record']
    bundle = Store(s.provenance.store.directory).bundle([pointer['record']])
    report = inspect(bundle)
    assert not report['missing_records'] and not report['complete']  # Declared upstream/runtime gaps survive.
    subject = report['subjects'][0]
    assert [p['package'] for p in subject['packages']] == ['fixture']
    assert any(r['kind']=='package-output' and r['data']['package']=='dependency' for r in bundle['records'].values())
    assert all('logs' not in r['data'] for r in bundle['records'].values())
    # A separate interpreter can use only build-record, without producer/trace on its path.
    import zog.build_record as build_record
    env = dict(os.environ, PYTHONPATH=str(Path(build_record.__file__).resolve().parent.parent))
    exported = tmp_path/'bundle.json'; exported.write_bytes(canonical(bundle))
    process = subprocess.run([sys.executable,'-m','build_record','inspect',str(exported)],
                             cwd=tmp_path,env=env,text=True,capture_output=True)
    assert process.returncode == 3  # Explicit gaps, not missing graph or invalid records.
    assert json.loads(process.stdout)['subjects'][0]['generation_id'] == subject['generation_id']
    record = bundle['records'][pointer['record']]['data']
    archive = s.provenance.root/'artifacts'/record['artifact']['digest'][7:]
    assert archive.stat().st_size > 1000  # Actual USTAR bytes, not an inventory standing in for rootfs.
    assert s.provenance.generation_roots(output=subject['packages'][0]['output'])[0]['relation']=='installed'
    dependency = next(k for k,r in bundle['records'].items() if r['kind']=='package-output' and r['data']['package']=='dependency')
    assert s.provenance.generation_roots(output=dependency)[0]['relation']=='dependency-or-history'


@pytest.mark.parametrize('phase',['preparing','prepared','finalizing','generation','manifest','rename','index','status'])
def test_publication_interruption_retains_ids(tmp_path, phase):
    s = Scenario(tmp_path)
    import zog.image_build.generation_provenance as gp
    import zog.image_build.engine as engine
    real_rename = engine.os.rename
    tripped = False
    def interrupted_write(path, data):
        nonlocal tripped
        path = Path(path)
        hit = ((path.parent.name=='assembly' and path.name==phase+'.json')
               or (phase=='manifest' and path.name=='manifest.json' and 'publication' in path.parts)
               or (phase=='index' and 'generation-members' in path.parts)
               or (phase=='status' and path.name=='status.json' and data.get('status')=='complete'))
        if hit and not tripped:
            tripped = True
            # Simulate an accepted durable write with a lost caller response.
            write_json(path,data)
            raise OSError('controlled publication interruption')
        return write_json(path,data)
    def interrupted_rename(source, target):
        nonlocal tripped
        result = real_rename(source,target)
        if phase=='rename' and Path(target).parent.name=='generations' and not tripped:
            tripped = True; raise OSError('controlled rename response loss')
        return result
    with patch.object(gp,'write_json',side_effect=interrupted_write), patch.object(engine,'write_json',side_effect=interrupted_write), patch.object(engine.os,'rename',side_effect=interrupted_rename):
        with pytest.raises(OSError): run(s)
    assert tripped
    directory = assembly(s)
    prior = {p.name: p.read_bytes() for p in directory.glob('*.json')}
    before = len(s.calls)
    s.original.write_text('current pin changed')
    (s.root/'package/commit-pin.py').write_text('current recipe selection changed')
    result = s.builder.resume(s.pipeline().parent.name)
    assert len(s.calls)==before
    for name, value in prior.items():
        assert (directory/name).read_bytes()==value
    pointer=result.manifest['build_record']
    assert record_id(json.loads((directory/'preparing.json').read_bytes()))==pointer['prepared']
    assert record_id(json.loads((directory/'finalizing.json').read_bytes()))==pointer['result']
    assert s.provenance.generation_roots(attempt=pointer['prepared'])[0]['relation']=='assembly'


def test_cache_reuse_preserves_original_producer_for_two_generations(tmp_path):
    s=pair(tmp_path); first=run(s)
    original=first.manifest['packages']['dependency']['provenance']
    pid=s.pipeline().parent.name
    s.builder.release_pipeline(pid)
    imported=import_completed(s.builder,pid)
    assert len(imported['imported'])==2
    before=len(s.calls)
    second=run(s,['dependency'])
    assert len(s.calls)==before and first.generation!=second.generation
    assert second.manifest['packages']['dependency']['provenance']==original
    roots=s.provenance.generation_roots(output=original['output'])
    assert {r['generation'] for r in roots}=={first.generation,second.generation}
    result=s.provenance.store.get(original['result'])
    assert len(s.provenance.generation_roots(attempt=result['data']['attempt']))==2
    with pytest.raises(ImageBuildError,match='limit'):s.provenance.generation_roots(output=original['output'],limit=1)
    reuse=list((s.root/'state/image-build/attempts').rglob('artifact-reuse.json'))
    assert reuse and not reuse[0].with_name('provenance.json').exists()


@pytest.mark.parametrize('damage',['missing','swapped'])
def test_cache_known_binding_cannot_be_lost_or_swapped(tmp_path, damage):
    s=pair(tmp_path); first=run(s); pid=s.pipeline().parent.name
    s.builder.release_pipeline(pid); imported=import_completed(s.builder,pid)
    cached=next(x for x in imported['imported'] if x['package']=='dependency')
    path=s.root/'state/image-build/package-artifacts'/cached['artifact']/'record.json'
    data=json.loads(path.read_bytes())
    if damage=='missing':data['result'].pop('provenance')
    else:data['result']['provenance']=first.manifest['packages']['fixture']['provenance']
    write_json(path,data);before=len(s.calls)
    with pytest.raises(ImageBuildError):run(s,['dependency'])
    assert len(s.calls)==before


@pytest.mark.parametrize('route',['new-pipeline','completed-resume'])
@pytest.mark.parametrize('damage',['record','rootfs','pointer','package'])
def test_existing_generation_fast_paths_validate_provenance(tmp_path,route,damage):
    s=Scenario(tmp_path); result=run(s); pid=s.pipeline().parent.name
    pointer=result.manifest['build_record'];record=s.provenance.store.get(pointer['record'])
    if damage=='record':(s.provenance.store.directory/(pointer['record'][7:]+'.json')).unlink()
    elif damage=='rootfs':(s.provenance.root/'artifacts'/record['data']['artifact']['digest'][7:]).write_bytes(b'tamper')
    else:
        manifest=result.manifest
        if damage=='pointer':manifest.pop('build_record')
        else:manifest['packages']['fixture']['provenance']['output']=pointer['output']
        write_json(result.root.parent/'manifest.json',manifest)
    before=len(s.calls)
    with pytest.raises((ImageBuildError,ValueError)):
        if route=='new-pipeline':run(s)
        else:s.builder.resume(pid)
    assert len(s.calls)==before


def test_generation_reuse_keeps_original_story_and_repairs_index(tmp_path):
    s=Scenario(tmp_path); result=run(s); original=result.manifest['build_record']
    shutil.rmtree(s.provenance.root/'generation-members')
    before=len(s.calls)
    reused=run(s)
    assert reused.reused and reused.manifest['build_record']==original and len(s.calls)==before
    assert s.provenance.generation_roots(attempt=original['prepared'])
    assert not json.loads(s.pipeline().read_bytes())['attempts']


def test_reverse_index_cannot_invent_membership(tmp_path):
    s=Scenario(tmp_path); result=run(s); pointer=result.manifest['build_record']
    path=next((s.provenance.root/'generation-members/attempts'/pointer['prepared'][7:]).glob('*.json'))
    value=json.loads(path.read_bytes());value['relation']='installed';write_json(path,value)
    with pytest.raises(ImageBuildError,match='membership differs'):
        s.provenance.generation_roots(attempt=pointer['prepared'])


def test_frozen_assembly_rejects_changed_producing_inputs(tmp_path):
    s=Scenario(tmp_path)
    import zog.image_build.generation_provenance as gp
    with patch.object(gp,'finish',side_effect=OSError('before assembly completion')):
        with pytest.raises(OSError):run(s)
    directory=assembly(s); frozen=(directory/'prepared.json').read_bytes()
    # An accepted output's historical binding must not disappear on recovery.
    path,_=s.binding();path.unlink()
    before=len(s.calls)
    with pytest.raises(ImageBuildError,match='known package provenance pointer is missing'):
        s.builder.resume(s.pipeline().parent.name)
    assert (directory/'prepared.json').read_bytes()==frozen and len(s.calls)==before


def promoted_fixture(s):
    """Synthetic accepted toolchain descriptor, not real compiler acceptance."""
    import platform
    plain=ImageBuild(package_dir=s.root/'package',state_dir=s.root/'state',runner=s.builder.runner)
    return plain._publish(s.seed.root, dict(schema=2,kind='toolchain',stage=2,
                          architecture=platform.machine(),fixture='synthetic toolchain'),
                          'toolchain',dict(stage=2,self_hosted=True))


def test_ordinary_image_activation_recovers_same_generation(tmp_path):
    s=Scenario(tmp_path); toolchain=promoted_fixture(s)
    import zog.image_build.engine as engine
    original=engine.os.replace
    tripped=False
    def interrupt(source,target):
        nonlocal tripped
        result=original(source,target)
        if Path(target)==s.root/'state/image-build/active' and not tripped:
            tripped=True;raise OSError('lost activation response')
        return result
    with patch.object(engine.os,'replace',side_effect=interrupt):
        with pytest.raises(OSError):s.builder.ensure(['fixture'],toolchain=toolchain)
    assert tripped
    expected=json.loads((assembly(s)/'generation.json').read_bytes())
    before=len(s.calls)
    result=s.builder.resume(s.pipeline().parent.name)
    assert result.manifest['kind']=='image' and result.manifest['build_record']==expected
    assert (s.root/'state/image-build/active').resolve()==result.root.parent
    assert len(s.calls)==before


def test_legacy_generation_is_not_retrofitted(tmp_path):
    s=Scenario(tmp_path)
    unconfigured=ImageBuild(package_dir=s.root/'package',state_dir=s.root/'state',runner=s.builder.runner)
    old=unconfigured.verify_seed(['fixture'],host_bootstrap=s.seed)
    manifest=(old.root.parent/'manifest.json').read_bytes()
    before=len(s.calls)
    with pytest.raises(ImageBuildError,match='no canonical provenance'):run(s)
    assert len(s.calls)==before and (old.root.parent/'manifest.json').read_bytes()==manifest


def test_changed_assembly_policy_blocks_recovery(tmp_path):
    s=Scenario(tmp_path)
    import zog.image_build.generation_provenance as gp
    with patch.object(gp,'finish',side_effect=OSError('before assembly completion')):
        with pytest.raises(OSError):run(s)
    before=len(s.calls);prepared=(assembly(s)/'prepared.json').read_bytes()
    with patch.object(gp,'POLICY','changed-current-composition'):
        with pytest.raises(ImageBuildError,match='intent changed'):
            s.builder.resume(s.pipeline().parent.name)
    assert len(s.calls)==before and (assembly(s)/'prepared.json').read_bytes()==prepared


def test_direct_publication_rejects_a_different_producing_graph(tmp_path):
    s=Scenario(tmp_path); first=run(s)
    changed=dict(first.manifest['build_record'],build_id='attempt:other')
    with pytest.raises(ImageBuildError,match='different producing graph'):
        s.builder._publish(first.root,first.manifest['inputs'],first.manifest['kind'],
                           {'packages':first.manifest['packages'],'build_record':changed})


def test_failed_retry_history_reaches_generation(tmp_path):
    s=Scenario(tmp_path);s.fail=True
    with pytest.raises(ImageBuildError):run(s)
    pipeline=s.pipeline();_,failed=s.binding()
    s.builder.release_pipeline(pipeline.parent.name)
    s.fail=False;s.builder=s.reopen({'fixture':failed['result']})
    result=run(s)
    bundle=s.provenance.store.bundle([result.manifest['build_record']['record']])
    assert bundle['records'][failed['result']]['data']['outcome']=='failed'
    roots=s.provenance.generation_roots(attempt=failed['prepared'])
    assert roots[0]['relation']=='dependency-or-history'


def test_cached_bound_inventory_mismatch_is_rejected(tmp_path):
    s=pair(tmp_path);run(s);pid=s.pipeline().parent.name
    s.builder.release_pipeline(pid);imported=import_completed(s.builder,pid)
    cached=next(x for x in imported['imported'] if x['package']=='dependency')
    folder=s.root/'state/image-build/package-artifacts'/cached['artifact']
    (folder/'output/usr/share/dependency').write_text('changed output')
    data=json.loads((folder/'record.json').read_bytes())
    from zog.image_build.filesystem import inventory
    data['result']['outputs']=inventory(folder/'output')
    data['result']['identity']=identity({key:data['result'][key] for key in ('inputs','outputs')})
    write_json(folder/'record.json',data)
    before=len(s.calls)
    with pytest.raises(ImageBuildError,match='provenance inventory differs'):run(s,['dependency'])
    assert len(s.calls)==before


def test_configuration_versions_preserve_package_only_mode(tmp_path):
    s=Scenario(tmp_path)
    current=s.provenance.configuration()
    assert current['schema']==2 and current['generation_contract']=='rootfs-v1'
    assert Provenance.from_configuration(s.root/'state',current).configuration()==current
    old={k:v for k,v in current.items() if k!='generation_contract'};old['schema']=1
    restored=Provenance.from_configuration(s.root/'state',old)
    assert restored.configuration()==old and restored.generation_contract is None
    s.builder.provenance=restored
    result=run(s)
    assert 'build_record' not in result.manifest
    assert result.manifest['packages']['fixture']['provenance']['result']
    # Configurations cannot be silently upgraded on a saved pipeline.
    s.builder.provenance=s.provenance
    with pytest.raises(ImageBuildError,match='policy changed'):
        s.builder.resume(s.pipeline().parent.name)


def test_generation_policy_cannot_be_disabled_on_resume(tmp_path):
    s=Scenario(tmp_path);s.interrupt=True
    with pytest.raises(OSError):run(s)
    recorded=json.loads(s.pipeline().read_bytes())['policy']['provenance']
    s.builder.provenance=Provenance(s.root/'state',host_id='host-a',project_id='project-a',pin=s.pin,generation_contract=None)
    with pytest.raises(ImageBuildError,match='policy changed'):
        s.builder.resume(s.pipeline().parent.name)
    s.builder.provenance=Provenance.from_configuration(s.root/'state',recorded)
    s.interrupt=False
    assert s.builder.resume(s.pipeline().parent.name).manifest['build_record']['record']


@pytest.mark.parametrize('kind',['attempt-result','generation'])
def test_canonical_store_response_loss_replays_same_ids(tmp_path,kind):
    s=Scenario(tmp_path)
    original=s.provenance.store.put;recorded=[]
    def lose(record):
        key=original(record)
        if record['kind']==kind and (kind=='generation' or record['data']['summary'].startswith('image-build verified local rootfs')) and not recorded:
            recorded.append(key);raise OSError('canonical store response lost')
        return key
    with patch.object(s.provenance.store,'put',side_effect=lose):
        with pytest.raises(OSError):run(s)
    before=len(s.calls)
    result=s.builder.resume(s.pipeline().parent.name)
    assert result.manifest['build_record']['result' if kind=='attempt-result' else 'record']==recorded[0]
    assert len(s.calls)==before


def test_publication_copy_tamper_never_exposes_generation(tmp_path):
    s=Scenario(tmp_path)
    import zog.image_build.engine as engine
    original=engine.shutil.copytree
    def corrupt(source,target,*args,**kwargs):
        result=original(source,target,*args,**kwargs)
        path=Path(target)
        if path.name=='root' and path.parent.parent.name=='publication':
            (path/'usr/share/fixture').write_text('tampered copied generation')
        return result
    with patch.object(engine.shutil,'copytree',side_effect=corrupt):
        with pytest.raises(ImageBuildError,match='canonical inventory'):run(s)
    generations=list((s.root/'state/image-build/generations').iterdir())
    assert [p.name for p in generations]==[s.seed.generation]
    assert not (s.root/'state/image-build/active').exists()


def test_import_cannot_downgrade_missing_known_binding(tmp_path):
    s=Scenario(tmp_path);run(s);pid=s.pipeline().parent.name
    s.builder.release_pipeline(pid)
    pointer,_=s.binding();pointer.unlink()
    with pytest.raises(ImageBuildError,match='known package provenance pointer is missing'):
        import_completed(s.builder,pid)
