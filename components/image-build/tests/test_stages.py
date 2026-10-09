import io
from contextlib import nullcontext
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from zog.image_build.errors import ImageBuildError
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages, order
from zog.image_build.sources import stage
from zog.image_build.filesystem import digest
from zog.image_build.build_views import read_build_commands

ROOT=Path(__file__).parents[1]/'project'

def test_stage_graph_and_snapshot(tmp_path):
    plan=stage_recipes(ROOT/'bootstrap/lfs-cross.py',ROOT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    ordered=order(packages,plan['targets'])
    assert ordered.index('binutils-cross-initial') < ordered.index('gcc-cross-initial') < ordered.index('glibc-cross-initial')
    assert ordered.index('linux-api-headers') < ordered.index('glibc-cross-initial')
    assert packages['glibc-cross-initial'].output_trees==('sysroot',)
    p=tmp_path/'recipes/gcc-cross-initial/integration.py';p.write_text('{}')
    with pytest.raises(ImageBuildError,match='changed'):
        stage_recipes(ROOT/'bootstrap/lfs-cross.py',ROOT/'package',tmp_path/'recipes')

@pytest.mark.parametrize('link,child,accepted',[('target',False,True),('../../outside',False,False),('/etc/passwd',False,False),('target',True,False)])
def test_archive_links_are_bounded(tmp_path,link,child,accepted):
    archive=tmp_path/'a.tar'
    with tarfile.open(archive,'w') as t:
        item=tarfile.TarInfo('tree/target');item.size=1;t.addfile(item,io.BytesIO(b'x'))
        item=tarfile.TarInfo('tree/link');item.type=tarfile.SYMTYPE;item.linkname=link;t.addfile(item)
        if child:
            item=tarfile.TarInfo('tree/link/child');item.size=1;t.addfile(item,io.BytesIO(b'y'))
    package=SimpleNamespace(sources=[dict(url=archive.as_uri(),sha256=digest(archive),destination='src',archive=True)])
    if accepted:
        stage(package,tmp_path/'work',tmp_path/'cache')
        assert (tmp_path/'work/src/tree/link').read_bytes()==b'x'
    else:
        with pytest.raises(ImageBuildError):stage(package,tmp_path/'work',tmp_path/'cache')

def test_unsubmitted_view_is_visible_without_acceptance(tmp_path):
    p=tmp_path/'packages/gcc';p.mkdir(parents=True)
    (p/'build-0.view.json').write_text(json.dumps(dict(schema=1,checkpoint='build-0.controller.json',stage_id='cross-initial',package='gcc')))
    commands=read_build_commands(tmp_path)['commands']
    assert commands[0]['job_id'] is None
    assert commands[0]['stage_id']=='cross-initial'

def test_archive_link_target_cannot_traverse_another_link(tmp_path):
    archive=tmp_path/'links.tar'
    with tarfile.open(archive,'w') as t:
        directory=tarfile.TarInfo('tree/real');directory.type=tarfile.DIRTYPE;t.addfile(directory)
        file=tarfile.TarInfo('tree/real/file');file.size=1;t.addfile(file,io.BytesIO(b'x'))
        link=tarfile.TarInfo('tree/alias');link.type=tarfile.SYMTYPE;link.linkname='real';t.addfile(link)
        link=tarfile.TarInfo('tree/second');link.type=tarfile.SYMTYPE;link.linkname='alias/file';t.addfile(link)
    package=SimpleNamespace(sources=[dict(url=archive.as_uri(),sha256=digest(archive),destination='src',archive=True)])
    with pytest.raises(ImageBuildError):stage(package,tmp_path/'work',tmp_path/'cache')

def test_archive_link_parent_segments_are_normalized_before_creation(tmp_path):
    archive=tmp_path/'normalize.tar'
    with tarfile.open(archive,'w') as t:
        directory=tarfile.TarInfo('tree');directory.type=tarfile.DIRTYPE;t.addfile(directory)
        file=tarfile.TarInfo('outside');file.size=6;t.addfile(file,io.BytesIO(b'inside'))
        link=tarfile.TarInfo('tree/alias');link.type=tarfile.SYMTYPE;link.linkname='.';t.addfile(link)
        link=tarfile.TarInfo('tree/escape');link.type=tarfile.SYMTYPE;link.linkname='alias/../../outside';t.addfile(link)
    package=SimpleNamespace(sources=[dict(url=archive.as_uri(),sha256=digest(archive),destination='src',archive=True)])
    stage(package,tmp_path/'work',tmp_path/'cache')
    extracted=tmp_path/'work/src'
    assert (extracted/'tree/escape').resolve().is_relative_to(extracted)
    assert (extracted/'tree/escape').read_bytes()==b'inside'

@pytest.mark.parametrize('outcome,cleanup,accepted',[(None,False,False),('success',True,False),('unknown',True,True),('nonzero-exit',True,True)])
def test_explicit_restart_preserves_failed_stage_and_completed_dependencies(tmp_path,monkeypatch,outcome,cleanup,accepted):
    import zog.image_build.stages as stages
    from zog.image_build.box_control_adapter import BuildExecutionPending
    project=tmp_path/'project';state=project/'state';work=state/'image-build/cross-bootstrap';work.mkdir(parents=True)
    (work/'operation.json').write_text(json.dumps({'intent':{'policy':None,'recipes':[]}}))
    p=state/'image-build/pipelines'/('a'*32);p.mkdir(parents=True)
    (p/'pipeline.json').write_text(json.dumps(dict(pipeline_id='a'*32,status='pending',recipes=[],attempts={'seed-check':'attempt'})))
    attempt=state/'image-build/attempts/attempt';failed=attempt/'packages/glibc';failed.mkdir(parents=True)
    (failed/'build-0.controller.json').write_text(json.dumps({'request_id':('r1-1-'+'a'*32+'-'+'b'*64)}))
    (failed/'source.c').write_text('retained evidence')
    dependency=attempt/'packages/gcc';dependency.mkdir();(dependency/'result.json').write_text('verified receipt')
    job=dict(job_id='b'*32,request_id=('r1-1-'+'a'*32+'-'+'b'*64),state='running',outcome=outcome,process_cleanup_complete=cleanup,request=dict(build_root_id='root',source_workspace_id='source',output_workspace_id='output'))
    control=SimpleNamespace(refresh_build_job=lambda _:job,cancel_build_job=lambda _:job)
    released=[]
    builder=SimpleNamespace(locked=nullcontext,_policy=lambda:None,runner=SimpleNamespace(execute=SimpleNamespace(control=control)),_release_resources=lambda p:released.append(p))
    monkeypatch.setattr(stages,'configured_runner',lambda *a:None)
    monkeypatch.setattr(stages,'ImageBuild',lambda **kw:builder)
    if accepted:
        result=stages.restart_incomplete_stage(project,tmp_path/'config','glibc')
        assert not failed.exists()
        assert (attempt/result['retired_name']/'source.c').read_text()=='retained evidence'
        assert (dependency/'result.json').read_text()=='verified receipt'
        assert len(released)==1
        saved=json.loads((p/'pipeline.json').read_text());saved['status']='complete'
        (p/'pipeline.json').write_text(json.dumps(saved))
        assert stages.restart_incomplete_stage(project,tmp_path/'config','glibc')==result
    else:
        with pytest.raises((ImageBuildError,BuildExecutionPending)):
            stages.restart_incomplete_stage(project,tmp_path/'config','glibc')
        assert failed.exists() and not released

@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_archive_link_chain_is_order_independent(tmp_path, kind):
    archive=tmp_path/'chain.tar'
    with tarfile.open(archive,'w') as t:
        for name, target in [('first','second'),('second','target')]:
            item=tarfile.TarInfo('tree/'+name);item.type=kind
            item.linkname=target if kind==tarfile.SYMTYPE else 'tree/'+target
            t.addfile(item)
        item=tarfile.TarInfo('tree/target');item.size=1;t.addfile(item,io.BytesIO(b'x'))
    package=SimpleNamespace(sources=[dict(url=archive.as_uri(),sha256=digest(archive),destination='src',archive=True)])
    stage(package,tmp_path/'work',tmp_path/'cache')
    assert (tmp_path/'work/src/tree/first').read_bytes()==b'x'

@pytest.mark.parametrize('target', ['first','../../outside','/etc/passwd'])
def test_archive_invalid_chain_is_rejected_before_extraction(tmp_path,target):
    archive=tmp_path/'chain.tar'
    with tarfile.open(archive,'w') as t:
        item=tarfile.TarInfo('tree/regular');item.size=1;t.addfile(item,io.BytesIO(b'x'))
        for name, destination in [('first','second'),('second',target)]:
            item=tarfile.TarInfo('tree/'+name);item.type=tarfile.SYMTYPE;item.linkname=destination;t.addfile(item)
    package=SimpleNamespace(sources=[dict(url=archive.as_uri(),sha256=digest(archive),destination='src',archive=True)])
    with pytest.raises(ImageBuildError):stage(package,tmp_path/'work',tmp_path/'cache')
    assert not (tmp_path/'work/src/tree/regular').exists()


def test_final_binutils_requires_gprofng_configuration(tmp_path):
    stage_recipes(ROOT/'bootstrap/lfs-final-binutils.py', ROOT/'package', tmp_path/'recipes')
    package = load_packages(tmp_path/'recipes')['binutils-final']
    assert package.output_trees == ('usr', 'etc/gprofng.rc')
    assert 'etc/gprofng.rc' in package.outputs
