import copy
import io
import json
import shutil
import tarfile
from dataclasses import asdict, replace
from pathlib import Path
import pytest
from zog.image_build.engine import ImageBuild
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import digest, inventory
from zog.image_build.licensing import expression, load, preserve, release_check, validate
from zog.image_build.metadata import Package, identity, load_package


@pytest.fixture
def fixture(tmp_path):
    state=tmp_path/'license-state'; cache=state/'image-build/sources';cache.mkdir(parents=True)
    archive=tmp_path/'source.tar'; text=b'Copyright Example. Permission to use, copy and distribute.\n'
    with tarfile.open(archive,'w') as t:
        member=tarfile.TarInfo('demo/LICENSE');member.size=len(text);t.addfile(member,io.BytesIO(text))
    sha=digest(archive);shutil.copyfile(archive,cache/sha)
    source=tmp_path/'source';(source/'src/demo').mkdir(parents=True);(source/'src/demo/LICENSE').write_bytes(text)
    output=tmp_path/'output';(output/'usr/bin').mkdir(parents=True);(output/'usr/bin/demo').write_text('program')
    record=dict(schema=1,package='demo',version='1',source=dict(url=archive.as_uri(),sha256=sha),status='reviewed',expression='MIT',scope='All files',evidence=[dict(path='demo/LICENSE',sha256=digest(source/'src/demo/LICENSE'),source_sha256=sha)],components=[],patches=[],notes=[])
    package=Package('demo', (dict(url=archive.as_uri(),sha256=sha,destination='src',archive=True),),(),(),{}, {},('usr/bin/demo',),{},licensing=record)
    return package,source,output,state


def publish(output,state):
    builder=ImageBuild(package_dir=state/'recipes',state_dir=state)
    return builder._publish(output,{'schema':2,'kind':'image','outputs':inventory(output)},'image',{})


def test_evidence_survives_cleanup_and_offline_gate(fixture):
    p,source,output,state=fixture
    receipt=preserve(p,source,output,state)
    before=inventory(output)
    assert preserve(p,source,output,state)==receipt
    assert inventory(output)==before
    shutil.rmtree(source);shutil.rmtree(state/'image-build/sources')
    selection=publish(output,state)
    result=release_check(selection.root.parent,state)
    assert result['eligible'] and not result['unresolved_files']
    (state/'image-build/release-inputs'/p.sources[0]['sha256']).unlink()
    assert not release_check(selection.root.parent,state)['eligible']


@pytest.mark.parametrize('change',['missing','changed','symlink','output-symlink','unexpected-output'])
def test_evidence_failures(fixture,tmp_path,change):
    p,source,output,state=fixture;notice=source/'src/demo/LICENSE'
    if change=='missing':notice.unlink()
    if change=='changed':notice.write_text('changed')
    if change=='symlink':notice.unlink();notice.symlink_to(tmp_path/'external')
    target=output/'usr/share/licenses/zog-packages/demo'
    if change=='output-symlink':
        target.mkdir(parents=True);(target/'texts').symlink_to(tmp_path)
    if change=='unexpected-output':
        target.mkdir(parents=True);(target/'unclaimed').write_text('unclaimed')
    with pytest.raises(ImageBuildError):preserve(p,source,output,state)


def test_inherited_files_and_incomplete_reviews_block_release(fixture):
    p,source,output,state=fixture
    p.licensing['components']=[dict(scope='runtime',expression='GPL-3.0-or-later WITH GCC-exception-3.1',status='declared',notes='Requires review')]
    preserve(p,source,output,state)
    (output/'seed-library').write_text('inherited')
    selection=publish(output,state);result=release_check(selection.root.parent,state)
    assert not result['eligible'] and result['unresolved_files']==['seed-library']
    assert any('review incomplete' in issue for issue in result['issues'])


def test_historical_generation_readable_but_unreviewed(fixture):
    _,_,output,state=fixture
    selection=publish(output,state)
    assert not release_check(selection.root.parent,state)['eligible']


@pytest.mark.parametrize('value',['MIT AND','MIT OR (GPL-3.0-only','Made-Up','MIT; x','MIT WITH Unknown','MIT OR OR ISC'])
def test_invalid_expressions(value):
    with pytest.raises(ImageBuildError):expression(value)


def test_inert_data_paths_and_fingerprints(fixture,tmp_path):
    p,*_=fixture
    path=tmp_path/'license.py';path.write_text("__import__('os').system('false')")
    with pytest.raises(ImageBuildError):load(path)
    for unsafe in ('../LICENSE','/LICENSE','a/../b','a//b'):
        r=copy.deepcopy(p.licensing);r['evidence'][0]['path']=unsafe
        with pytest.raises(ImageBuildError):validate(r)
    updated=copy.deepcopy(p.licensing);updated['notes'].append('Reviewed scope change')
    assert replace(p,licensing=updated).fingerprint!=p.fingerprint
    old=replace(p,licensing=None);data=asdict(old);data.pop('licensing');data.pop('test_dependencies'); data.pop('recipe_directory'); data.pop('source_provenance')
    assert old.fingerprint==identity(data)


def test_catalogue_and_every_stage_have_bound_records():
    root=Path(__file__).parents[1]/'project/package'
    projects=[p for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')]
    assert {'openssl', 'sqlite', 'readline'} <= {p.name for p in projects}
    for directory in projects:
        record=load(directory/'license.py')
        assert record['package']==directory.name and record['evidence']
        for stage in directory.glob('stages/*'):
            package=load_package(stage)
            expected=load(stage/'license.py') if (stage/'license.py').exists() else record
            assert package.licensing==expected
            assert expected['package']==record['package']
            if expected['version'] == record['version']:
                assert expected['source'] == record['source']
                assert all(item in expected['evidence'] for item in record['evidence'])
            else:
                # Explicit version overrides bind the actual stage archive.
                assert (stage/'license.py').exists()
                assert any(source['url'] == expected['source']['url'] and
                           source['sha256'] == expected['source']['sha256']
                           for source in package.sources)
                assert expected['evidence']
                assert all(item['source_sha256'] == expected['source']['sha256']
                           for item in expected['evidence'])


from test_source_build import prepared
from zog.image_build.artifacts import import_completed


def test_engine_composition_and_cache_bind_license_identity(prepared,fixture):
    builder,runner,_,toolchain=prepared
    package,source,output,state=fixture
    directory=builder.package_dir/'library'
    (directory/'sources.py').write_text(repr(list(package.sources)))
    from zog.image_build.metadata import literal
    pins=literal(builder.package_dir/'commit-pin.py')
    pins['packages']['library']['sources']=list(package.sources)
    (builder.package_dir/'commit-pin.py').write_text(repr(pins))
    record=copy.deepcopy(package.licensing);record['package']='library'
    (directory/'license.py').write_text(repr(record))
    first=builder.ensure(['library'],toolchain=toolchain)
    assert release_check(first.root.parent,builder.state)['eligible']
    pipeline=next(p for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json') if json.loads(p.read_text())['operation']=='image')
    builder.release_pipeline(pipeline.parent.name);import_completed(builder,pipeline.parent.name)
    count=len(runner.calls)
    record['notes'].append('Updated licensing review')
    (directory/'license.py').write_text(repr(record))
    second=builder.ensure(['library'],toolchain=toolchain)
    assert len(runner.calls)==count+3
    assert first.generation!=second.generation
    receipt=json.loads((second.root/'usr/share/licenses/zog-packages/library/record.json').read_text())
    assert receipt['record_identity']==identity(record)


def test_finalization_releases_before_notices_and_resumes_without_recompile(prepared,fixture,monkeypatch):
    import zog.image_build.licensing as licensing
    from zog.image_build.runner import BoxControlRunner, BuildExecutionResult
    builder,_,_,toolchain=prepared
    package,*_=fixture
    directory=builder.package_dir/'library'
    (directory/'sources.py').write_text(repr(list(package.sources)))
    from zog.image_build.metadata import literal
    pins=literal(builder.package_dir/'commit-pin.py')
    pins['packages']['library']['sources']=list(package.sources)
    (builder.package_dir/'commit-pin.py').write_text(repr(pins))
    record=copy.deepcopy(package.licensing);record['package']='library'
    (directory/'license.py').write_text(repr(record))
    calls=[];released=[];attempts=[]
    def execute(request):
        calls.append(request.command)
        if request.command[0]=='install':
            path=request.output/'usr/share/library';path.parent.mkdir(parents=True);path.write_text('library')
        return BuildExecutionResult('runtime','invocation',0,True,'journal')
    builder.runner=BoxControlRunner(execute)
    monkeypatch.setattr(builder,'_release_resources',lambda p:released.append(Path(p)))
    original=licensing.preserve
    def interrupted(p,source,output,state):
        assert output.parent in released
        assert calls[-1][0]=='install'
        attempts.append(output)
        if len(attempts)==1:raise OSError('interrupted notice preservation')
        return original(p,source,output,state)
    monkeypatch.setattr(licensing,'preserve',interrupted)
    with pytest.raises(OSError,match='interrupted notice'):
        builder.ensure(['library'],toolchain=toolchain)
    assert len(calls)==3
    pipeline=next(p for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json') if json.loads(p.read_text())['status']=='pending')
    result=builder.resume(pipeline.parent.name)
    assert len(calls)==3  # Saved controller completions, no repeated compilation.
    assert release_check(result.root.parent,builder.state)['eligible']


def test_unreleased_workspace_cannot_enter_notice_preservation(prepared,fixture,monkeypatch):
    import zog.image_build.licensing as licensing
    builder,_,_,toolchain=prepared
    package,*_=fixture
    directory=builder.package_dir/'library'
    (directory/'sources.py').write_text(repr(list(package.sources)))
    from zog.image_build.metadata import literal
    pins=literal(builder.package_dir/'commit-pin.py')
    pins['packages']['library']['sources']=list(package.sources)
    (builder.package_dir/'commit-pin.py').write_text(repr(pins))
    record=copy.deepcopy(package.licensing);record['package']='library'
    (directory/'license.py').write_text(repr(record))
    def blocked(_):raise ImageBuildError('process cleanup incomplete')
    monkeypatch.setattr(builder,'_release_resources',blocked)
    monkeypatch.setattr(licensing,'preserve',lambda *args:pytest.fail('unreleased workspace was modified'))
    with pytest.raises(ImageBuildError,match='cleanup incomplete'):
        builder.ensure(['library'],toolchain=toolchain)
    assert not list((builder.state/'image-build/attempts').glob('*/packages/library/result.json'))


def test_finalization_rejects_changed_installed_output(fixture):
    from zog.image_build.licensing import prepare_finalization
    package,source,output,state=fixture
    checkpoint=state/'finalization.json'
    prepare_finalization(package,output,checkpoint,{'recipe':package.fingerprint})
    preserve(package,source,output,state)
    prepare_finalization(package,output,checkpoint,{'recipe':package.fingerprint})
    (output/'usr/bin/demo').write_text('changed')
    with pytest.raises(ImageBuildError,match='outputs changed'):
        prepare_finalization(package,output,checkpoint,{'recipe':package.fingerprint})


def patched_fixture(fixture):
    p,source,output,state=fixture
    original=(source/'src/demo/LICENSE').read_bytes()
    patch=state/'image-build/sources/patch';patch.write_bytes(b'reviewed patch input')
    sha=digest(patch);patch.rename(patch.with_name(sha))
    spec=dict(url='https://example.test/fix.patch',sha256=sha,destination='patches/fix.patch',archive=False)
    (source/'src/demo/LICENSE').write_bytes(original+b'Updated source code\n')
    declaration=dict(id='fix',order=1,applies_to=dict(version='1',stage='final'),source=spec,
                     files=[dict(path='LICENSE',before_sha256=p.licensing['evidence'][0]['sha256'],after_sha256=digest(source/'src/demo/LICENSE'))])
    p=replace(p,sources=p.sources+(spec,),integration=dict(stage_id='final',patches=[declaration]))
    return p,source,output,state,original


def test_patched_evidence_preserves_original_and_records_transformation(fixture):
    p,source,output,state,original=patched_fixture(fixture)
    result=preserve(p,source,output,state)
    receipt=json.loads((output/result['receipt']).read_text())
    evidence=receipt['evidence'][0]
    assert (output/evidence['installed_path']).read_bytes()==original
    assert evidence['working_sha256']==digest(source/'src/demo/LICENSE')
    assert evidence['transformations'][0]['before_sha256']==evidence['sha256']
    assert preserve(p,source,output,state)==result
    assert receipt['unreviewed_sources']==[p.sources[1]['sha256']]


@pytest.mark.parametrize('fault',['working','before','patch','undeclared','scope','order','archive','path','duplicate'])
def test_patched_evidence_rejects_unbound_changes(fixture,fault):
    p,source,output,state,_=patched_fixture(fixture)
    patch=p.integration['patches'][0]
    if fault=='working':(source/'src/demo/LICENSE').write_text('unexplained modification')
    if fault=='before':patch['files'][0]['before_sha256']='0'*64
    if fault=='patch':(state/'image-build/sources'/p.sources[1]['sha256']).write_text('changed patch')
    if fault=='undeclared':p=replace(p,sources=p.sources[:1])
    if fault=='scope':patch['applies_to']['stage']='other'
    if fault=='order':patch['order']=0
    if fault=='archive':patch['source']=dict(p.sources[0])
    if fault=='path':patch['files'][0]['path']='../LICENSE'
    if fault=='duplicate':patch['files'].append(copy.deepcopy(patch['files'][0]))
    with pytest.raises(ImageBuildError):preserve(p,source,output,state)


def test_patched_evidence_requires_contiguous_ordered_chain(fixture):
    p,source,output,state,_=patched_fixture(fixture)
    first=p.integration['patches'][0]
    second=copy.deepcopy(first);second.update(id='second',order=2)
    second['files'][0]['before_sha256']=first['files'][0]['after_sha256']
    (source/'src/demo/LICENSE').write_text('second declared result')
    second['files'][0]['after_sha256']=digest(source/'src/demo/LICENSE')
    p.integration['patches'].append(second)
    result=preserve(p,source,output,state)
    receipt=json.loads((output/result['receipt']).read_text())
    assert len(receipt['evidence'][0]['transformations'])==2


def test_raw_notice_preserved_and_tampering_rejected(fixture):
    p,source,output,state=fixture
    notice=source/'NOTICE';notice.write_text('Raw upstream license notice')
    sha=digest(notice);shutil.copyfile(notice,state/'image-build/sources'/sha)
    spec=dict(url='https://example.invalid/NOTICE',sha256=sha,destination='NOTICE',archive=False)
    p=replace(p,sources=(*p.sources,spec),licensing=copy.deepcopy(p.licensing))
    p.licensing['evidence'].append(dict(path='NOTICE',sha256=sha,source_sha256=sha))
    receipt=preserve(p,source,output,state)
    assert (output/'usr/share/licenses/zog-packages/demo/texts'/sha/'NOTICE').read_text()==notice.read_text()
    notice.write_text('changed')
    with pytest.raises(ImageBuildError):preserve(p,source,output,state)


def test_raw_notice_cannot_name_another_path(fixture):
    p,source,output,state=fixture
    notice=source/'NOTICE';notice.write_text('Raw notice');sha=digest(notice)
    shutil.copyfile(notice,state/'image-build/sources'/sha)
    p=replace(p,sources=(*p.sources,dict(url='https://example.invalid/NOTICE',sha256=sha,destination='NOTICE',archive=False)),licensing=copy.deepcopy(p.licensing))
    p.licensing['evidence'].append(dict(path='elsewhere',sha256=sha,source_sha256=sha))
    with pytest.raises(ImageBuildError,match='must name the source file'):preserve(p,source,output,state)


def test_notice_readability_is_scoped_and_content_preserving(fixture):
    from zog.image_build.licensing import prepare_readability
    p, source, output, state = fixture
    notice = source/'src/demo/LICENSE'
    notice.chmod(0o640)
    unrelated = source/'src/demo/private-fixture'
    unrelated.write_text('unchanged fixture permissions')
    unrelated.chmod(0o600)
    before = notice.read_bytes()
    changes = prepare_readability(p, source)
    assert changes == [dict(path='src/demo/LICENSE', sha256=digest(notice),
                            before_mode=0o640, after_mode=0o644)]
    assert notice.read_bytes() == before
    assert unrelated.stat().st_mode & 0o777 == 0o600
    assert prepare_readability(p, source) == []
    assert preserve(p, source, output, state)


@pytest.mark.parametrize('change', ['changed', 'symlink', 'hardlink'])
def test_notice_readability_rejects_unsafe_evidence(fixture, change):
    from zog.image_build.licensing import prepare_readability
    import os
    p, source, _, _ = fixture
    notice = source/'src/demo/LICENSE'
    other = source/'src/demo/other'
    if change == 'changed':
        notice.write_text('altered')
    elif change == 'symlink':
        notice.rename(other)
        notice.symlink_to(other.name)
    else:
        os.link(notice, other)
    with pytest.raises(ImageBuildError):
        prepare_readability(p, source)


def test_notice_readable_after_distinct_build_uid_handoff(fixture):
    import os
    import subprocess
    import tempfile
    from zog.image_build.licensing import prepare_readability
    if os.geteuid() != 0:
        pytest.skip('real cross-UID access check requires root')
    p, original, _, _ = fixture
    with tempfile.TemporaryDirectory(prefix='zog-notice-access-') as name:
        root = Path(name)
        root.chmod(0o755)
        directory = root/'src/demo'
        directory.mkdir(parents=True)
        notice = directory/'LICENSE'
        notice.write_bytes((original/'src/demo/LICENSE').read_bytes())
        notice.chmod(0o640)
        other = directory/'private-fixture'
        other.write_text('private'); other.chmod(0o640)
        prepare_readability(p, root)
        # Model controller import followed by directory-only ownership return.
        try:
            os.chown(notice, 21001, 21001)
            os.chown(other, 21001, 21001)
        except OSError as error:
            import errno
            if error.errno in (errno.EINVAL, errno.EPERM):
                pytest.skip('execution environment cannot map distinct build UID')
            raise
        def reader():
            os.setgroups([]); os.setgid(65534); os.setuid(65534)
        result = subprocess.run(['python3', '-c',
            'from pathlib import Path; import sys; '
            'Path(sys.argv[1]).read_bytes()', str(notice)],
            preexec_fn=reader, capture_output=True)
        assert result.returncode == 0, result.stderr
        denied = subprocess.run(['python3', '-c',
            'from pathlib import Path; import sys; '
            'Path(sys.argv[1]).read_bytes()', str(other)],
            preexec_fn=reader, capture_output=True)
        assert denied.returncode != 0 and b'PermissionError' in denied.stderr
