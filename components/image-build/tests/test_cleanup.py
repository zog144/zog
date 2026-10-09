import json
import pytest
from zog.image_build.cleanup import package_workspace, completed_workspaces
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory, write_json
from test_source_build import prepared


def package(tmp_path):
    p=tmp_path/'package';p.mkdir()
    for n in ('root','source','output'):
        (p/n).mkdir();(p/n/'file').write_text(n)
    write_json(p/'result.json', {'outputs':inventory(p/'output'),'identity':'test'})
    write_json(p/'controller-resources.json', {'resource_id':'r'})
    write_json(p/'controller-released.json', {'resource_id':'r'})
    return p


def test_cleanup_preserves_outputs_evidence_and_external_symlink(tmp_path):
    p=package(tmp_path);outside=tmp_path/'outside';outside.mkdir();(outside/'keep').write_text('safe')
    (p/'source/link').symlink_to(outside)
    (p/'build.view.json').write_text('evidence')
    assert len(package_workspace(p,apply=False))==2
    assert (p/'source').exists()
    package_workspace(p)
    assert not (p/'root').exists() and not (p/'source').exists()
    assert (p/'output/file').read_text()=='output'
    assert (p/'build.view.json').read_text()=='evidence'
    assert (outside/'keep').exists()
    assert package_workspace(p)==[]


@pytest.mark.parametrize('fault',['unreleased','identity','output','symlink','mount'])
def test_cleanup_refuses_unsafe_state(tmp_path,monkeypatch,fault):
    p=package(tmp_path)
    if fault=='unreleased':(p/'controller-released.json').unlink()
    if fault=='identity':write_json(p/'controller-released.json',{'resource_id':'other'})
    if fault=='output':(p/'output/file').write_text('changed')
    if fault=='symlink':
        (p/'root').rename(p/'other');(p/'root').symlink_to(p/'other')
    if fault=='mount':monkeypatch.setattr('zog.image_build.cleanup.os.path.ismount',lambda _:True)
    with pytest.raises(ImageBuildError):package_workspace(p)
    assert (p/'source/file').exists()


def test_interrupted_cleanup_resumes(tmp_path,monkeypatch):
    import zog.image_build.cleanup as cleanup
    p=package(tmp_path);original=cleanup.discard_staging
    def interrupted(path):
        if path.name=='source':raise OSError('injected interruption')
        original(path)
    monkeypatch.setattr(cleanup,'discard_staging',interrupted)
    with pytest.raises(OSError):package_workspace(p)
    assert json.loads((p/'workspace-cleanup.json').read_text())['phase']=='removing'
    monkeypatch.setattr(cleanup,'discard_staging',original)
    package_workspace(p)
    assert json.loads((p/'workspace-cleanup.json').read_text())['phase']=='complete'


def test_published_pipeline_resume_after_cleanup(prepared):
    builder,runner,seed,toolchain=prepared
    result=builder.ensure(['consumer'],toolchain=toolchain)
    pipelines=list((builder.state/'image-build/pipelines').glob('*/pipeline.json'))
    count=len(runner.calls)
    report=completed_workspaces(builder,apply=True)
    assert report['paths']
    for path in pipelines:
        builder.resume(json.loads(path.read_text())['pipeline_id'])
    assert len(runner.calls)==count
    assert inventory(result.root)
    assert completed_workspaces(builder,apply=True)['paths']==[]


def test_pending_pipeline_retained(prepared):
    builder,runner,seed,toolchain=prepared
    runner.fail='compile'
    with pytest.raises(ImageBuildError):builder.ensure(['consumer'],toolchain=toolchain)
    pending=[p for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json') if json.loads(p.read_text())['status']=='pending'][0]
    record=json.loads(pending.read_text());attempt=next(iter(record['attempts'].values()))
    source=builder.state/'image-build/attempts'/attempt/'packages/library/source'
    assert source.exists()
    completed_workspaces(builder,apply=True)
    assert source.exists()


def test_completed_dependency_reused_after_later_failure(prepared):
    builder,runner,seed,toolchain=prepared
    original=runner.run
    def fail_consumer(root,source,output,arguments,environment,log):
        if arguments==['compile','consumer']:raise ImageBuildError('later package failed')
        return original(root,source,output,arguments,environment,log)
    runner.run=fail_consumer
    with pytest.raises(ImageBuildError):builder.ensure(['consumer'],toolchain=toolchain)
    path=next(p for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json') if json.loads(p.read_text())['status']=='pending')
    record=json.loads(path.read_text());attempt=next(iter(record['attempts'].values()))
    package=builder.state/'image-build/attempts'/attempt/'packages/library'
    assert not (package/'source').exists() and (package/'output').exists()
    before=sum(args==['compile','library'] for args,_ in runner.calls)
    runner.run=original
    builder.resume(record['pipeline_id'])
    assert sum(args==['compile','library'] for args,_ in runner.calls)==before
