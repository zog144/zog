import json
import pytest
from test_source_build import prepared
from zog.image_build.artifacts import import_completed
from zog.image_build.errors import ImageBuildError


def accepted(builder):
    p=list((builder.state/'image-build/pipelines').glob('*/pipeline.json'))
    return next(f.parent.name for f in p if json.loads(f.read_text())['operation']=='image')


def test_released_completed_artifacts_reused_without_jobs(prepared):
    b,runner,_,toolchain=prepared
    first=b.ensure(['consumer'],toolchain=toolchain);pid=accepted(b)
    with pytest.raises(ImageBuildError,match='explicitly released'):import_completed(b,pid)
    b.release_pipeline(pid);report=import_completed(b,pid)
    assert {x['package'] for x in report['imported']}=={'library','consumer'}
    count=len(runner.calls)
    second=b.ensure(['library','consumer'],toolchain=toolchain)
    assert second.manifest['outputs']==first.manifest['outputs']
    assert len(list((b.state/'image-build/attempts').rglob('artifact-reuse.json')))==2
    assert len(runner.calls)==count


def test_corrupt_cached_output_is_rejected(prepared):
    b,runner,_,toolchain=prepared
    b.ensure(['consumer'],toolchain=toolchain);pid=accepted(b);b.release_pipeline(pid)
    report=import_completed(b,pid)
    item=next(x for x in report['imported'] if x['package']=='library')
    (b.state/'image-build/package-artifacts'/item['artifact']/'output/usr/share/library').write_text('changed')
    count=len(runner.calls)
    with pytest.raises(ImageBuildError,match='cached package outputs changed'):b.ensure(['library'],toolchain=toolchain)
    assert len(runner.calls)==count


def test_changed_recipe_rebuilds_only_changed_package(prepared):
    b,runner,_,toolchain=prepared
    b.ensure(['consumer'],toolchain=toolchain);pid=accepted(b);b.release_pipeline(pid);import_completed(b,pid)
    path=b.package_dir/'consumer/build.py'
    import ast
    steps=ast.literal_eval(path.read_text());steps['build']=[['compile','consumer','revised']];path.write_text(repr(steps))
    count=len(runner.calls);b.ensure(['consumer'],toolchain=toolchain)
    assert [args for args,_ in runner.calls[count:]]==[['compile','consumer','revised'],['test','consumer'],['install','consumer']]


def test_incomplete_package_is_not_imported(prepared):
    b,runner,_,toolchain=prepared
    runner.fail='test'
    with pytest.raises(ImageBuildError):b.ensure(['consumer'],toolchain=toolchain)
    pid=accepted(b);b.release_pipeline(pid)
    assert import_completed(b,pid)['imported']==[]


def test_policy_change_does_not_reuse_artifact(prepared,monkeypatch):
    b,runner,_,toolchain=prepared
    b.ensure(['consumer'],toolchain=toolchain);pid=accepted(b);b.release_pipeline(pid);import_completed(b,pid)
    monkeypatch.setattr(b,'_policy',lambda:{'changed':True})
    count=len(runner.calls);b.ensure(['library'],toolchain=toolchain)
    assert len(runner.calls)-count==3


def test_interrupted_restoration_resumes_without_compilation(prepared,monkeypatch):
    import zog.image_build.artifacts as artifacts
    b,runner,_,toolchain=prepared
    b.ensure(['consumer'],toolchain=toolchain);pid=accepted(b);b.release_pipeline(pid);import_completed(b,pid)
    original=artifacts.shutil.copytree
    def interrupted(source,destination,*args,**kwargs):
        if 'artifact-restoration' in str(destination):
            destination.mkdir(parents=True)
            (destination/'partial').write_text('partial')
            raise OSError('simulated interrupted artifact copy')
        return original(source,destination,*args,**kwargs)
    monkeypatch.setattr(artifacts.shutil,'copytree',interrupted)
    count=len(runner.calls)
    with pytest.raises(OSError,match='interrupted artifact copy'):b.ensure(['library'],toolchain=toolchain)
    pending=next(f.parent.name for f in (b.state/'image-build/pipelines').glob('*/pipeline.json') if json.loads(f.read_text())['status']=='pending')
    monkeypatch.setattr(artifacts.shutil,'copytree',original)
    assert (b.resume(pending).root/'usr/share/library').read_text()=='library'
    assert len(runner.calls)==count
