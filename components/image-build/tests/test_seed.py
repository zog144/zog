from pathlib import Path
import pytest
from zog.image_build.developer.seed import assemble_files
from zog.image_build.metadata import load_package
from zog.image_build.errors import ImageBuildError


def test_shallow_copy_does_not_import_unselected_files(tmp_path):
    host=tmp_path/'host';(host/'usr/bin').mkdir(parents=True)
    (host/'usr/bin/selected').write_text('tool')
    (host/'usr/bin/private').write_text('not selected')
    (host/'usr/bin/selected').chmod(0o4755)
    out=tmp_path/'seed'
    records=assemble_files({'/usr/bin':['layout'],'/usr/bin/selected':['test']},out,host)
    assert not (out/'usr/bin/private').exists()
    assert (out/'usr/bin/selected').stat().st_mode & 0o7777 == 0o755
    assert records['/usr/bin/selected']['original_mode'] == 0o4755
    assert not (out/'etc/shadow').exists()


def test_relative_symlink_target_is_copied(tmp_path):
    host=tmp_path/'host';(host/'usr/bin').mkdir(parents=True)
    (host/'usr/bin/tool').write_text('tool')
    (host/'usr/bin/alias').symlink_to('tool')
    out=tmp_path/'seed'
    assemble_files({'/usr/bin/alias':['test']},out,host)
    assert (out/'usr/bin/tool').read_text()=='tool'
    assert str((out/'usr/bin/alias').readlink())=='/usr/bin/tool'


def test_external_host_tree_rejected(tmp_path):
    host=tmp_path/'host';(host/'etc').mkdir(parents=True)
    (host/'etc/shadow').write_text('secret')
    with pytest.raises(ImageBuildError,match='outside allowed'):
        assemble_files({'/etc/shadow':['bad']},tmp_path/'seed',host)
    assert not (tmp_path/'seed/etc/shadow').exists()


def test_m4_stage_is_executable_but_catalogue_is_not():
    root=Path(__file__).parents[1]/'project/package/m4'
    p=load_package(root/'stages/native-seed')
    assert p.steps['test']
    assert p.sources[0]['sha256']=='f25c6ab51548a73a75558742fb031e0625d6485fe5f9155949d6486a2408ab66'
    with pytest.raises(ImageBuildError,match='catalogue-only'):
        load_package(root)


def test_verification_reuses_completion_and_rejects_output_drift(tmp_path):
    from types import SimpleNamespace
    from zog.image_build.developer.seed_build import verify
    root=tmp_path/'input'; root.mkdir(); (root/'tool').write_text('input')
    calls=[]
    def execute(root,source,output,command,environment,log):
        calls.append(command)
        (output/'answer').write_text('42')
    builder=SimpleNamespace(runner=SimpleNamespace(run=execute), _policy=lambda:{'uid':1000}, _release_resources=lambda p:None)
    folder=tmp_path/'attempt'; commands=[['tool']]
    verify(builder,folder,root,commands,'input-id')
    verify(builder,folder,root,commands,'input-id')
    assert len(calls)==1
    (folder/'output/answer').write_text('changed')
    with pytest.raises(ImageBuildError,match='outputs'):
        verify(builder,folder,root,commands,'input-id')


def test_prepare_refuses_reuse_after_catalogue_change(tmp_path,monkeypatch):
    import zog.image_build.developer.seed as seed
    catalogue=tmp_path/'catalogue';catalogue.mkdir();(catalogue/'input').write_text('original')
    host=tmp_path/'host';(host/'usr/bin').mkdir(parents=True);(host/'usr/bin/tool').write_text('tool')
    monkeypatch.setattr(seed,'discover',lambda _: {'files':{'/usr/bin/tool':['test']},'packages':[]})
    monkeypatch.setattr(seed,'command',lambda *a:'')
    original=seed.assemble_files
    monkeypatch.setattr(seed,'assemble_files',lambda files,destination,**kw:original(files,destination,host,**kw))
    seed.prepare(catalogue,tmp_path/'work')
    seed.prepare(catalogue,tmp_path/'work')
    (catalogue/'input').write_text('changed')
    with pytest.raises(ImageBuildError,match='inputs changed'):
        seed.prepare(catalogue,tmp_path/'work')


def test_source_extraction_preserves_release_timestamps(tmp_path):
    import io,tarfile,hashlib
    from types import SimpleNamespace
    from zog.image_build.sources import stage
    archive=tmp_path/'release.tar'
    with tarfile.open(archive,'w') as tar:
        for name,mtime in [('Makefile.in',1000000010),('Makefile.am',1000000000)]:
            entry=tarfile.TarInfo(name);entry.size=1;entry.mtime=mtime
            tar.addfile(entry,io.BytesIO(b'x'))
    package=SimpleNamespace(sources=[{'url':archive.as_uri(),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'destination':'src','archive':True}])
    stage(package,tmp_path/'source',tmp_path/'cache')
    assert (tmp_path/'source/src/Makefile.in').stat().st_mtime > (tmp_path/'source/src/Makefile.am').stat().st_mtime


def test_legacy_library_path_maps_into_canonical_usr(tmp_path):
    host=tmp_path/'host';(host/'usr/lib64').mkdir(parents=True)
    (host/'lib64').symlink_to('usr/lib64')
    (host/'usr/lib64/libgcc_s.so.1').write_text('runtime')
    out=tmp_path/'seed'
    records=assemble_files({'/lib64/libgcc_s.so.1':['rpm:libgcc'],'/lib64':['layout']},out,host)
    assert (out/'usr/lib64/libgcc_s.so.1').read_text()=='runtime'
    assert records['/lib64/libgcc_s.so.1']['path']=='/usr/lib64/libgcc_s.so.1'
