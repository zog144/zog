"""Source/patch provenance through the real owner, with synthetic execution."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
from zog.build_record import canonical, inspect
from zog.build_trace import BuildTrace
from zog.image_build.errors import ImageBuildError
from zog.image_build.metadata import identity, load_packages
from zog.image_build.provenance import Provenance
from zog.image_build.source_provenance import NAME, validate
from zog.image_build.stages import stage_recipes
from test_provenance import Scenario


def read_literal(path):
    return ast.literal_eval(path.read_text())


def declare(s, *, patches=0, kind='git', revision='a'*40):
    recipe=s.root/'package/fixture'
    sources=read_literal(recipe/'sources.py')
    declarations=[]
    for i in range(patches):
        path=s.root/f'patch-{i}';path.write_bytes(f'reviewed patch {i}'.encode())
        spec=dict(url=path.as_uri(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),destination=f'patches/{i}.patch',archive=False)
        sources.append(spec)
        declarations.append(dict(id=f'patch-{i}',order=i+1,source=spec,applies_to={'version':'1','stage':'final'},
                                 files=[dict(path='file',before_sha256=str(i)*64,after_sha256=str(i+1)*64)]))
    (recipe/'sources.py').write_text(repr(sources))
    (recipe/'integration.py').write_text(repr(dict(stage_id='final',patches=declarations,patches_complete=True)))
    if patches:
        licensing=dict(schema=1,package='fixture',version='1',source={k:sources[0][k] for k in ('url','sha256')},status='unresolved',expression=None,scope='Synthetic provenance fixture',evidence=[],components=[],patches=[],notes=['No licensing acceptance claimed.'])
        (recipe/'license.py').write_text(repr(licensing))
    value=dict(schema=1,sources=[dict(source=spec,upstream=[dict(repository='fixture:upstream',revision=revision,revision_type=kind)]) for spec in sources])
    (recipe/NAME).write_text(repr(value))
    monthly=read_literal(s.original);monthly['packages']['fixture']['recipes']['stage']=sources
    s.original.write_text(repr(monthly))
    selected=read_literal(recipe.parent/'commit-pin.py');selected['packages']['fixture']['sources']=sources
    selected['monthly_identity']=identity(monthly);(recipe.parent/'commit-pin.py').write_text(repr(selected))
    s.pin=Provenance.capture_pin(s.root/'state',s.original,repository='fixture:catalogue',revision='1'*40,repository_path='pins/2026-10-01/commit-pin.py')
    s.provenance=Provenance(s.root/'state',host_id='host-a',project_id='project-a',pin=s.pin)
    s.builder=s.reopen()
    return value


def run(s):
    return s.builder.verify_seed(['fixture'],host_bootstrap=s.seed)


def inputs(s):
    _,binding=s.binding()
    return s.provenance.store.get(binding['inputs'])['data']


def trace(s):
    return BuildTrace(s.root,host_id='host-a',record_project_id='project-a',record_store=s.provenance.store.directory)


def test_explicit_sources_and_ordered_patches_in_generation(tmp_path):
    s=Scenario(tmp_path);value=declare(s,patches=2);generation=run(s)
    data=inputs(s)
    assert [p['name'] for p in data['patches']]==['patches/0.patch','patches/1.patch']
    for ref,entry in zip(data['sources'],value['sources']):
        record=s.provenance.store.get(ref)
        assert not record['gaps']
        assert record['data']['archives'][0]['digest']=='sha256:'+entry['source']['sha256']
        assert record['data']['upstream']==[dict(repository='fixture:upstream',revision='a'*40)]
    assert len(data['sources'])==3
    bundle=s.provenance.store.bundle([generation.manifest['build_record']['record']]);report=inspect(bundle)
    assert not report['missing_records'] and not report['complete']
    assert not any('Patch classification' in gap or 'Upstream' in gap for r in bundle['records'].values() for gap in r['gaps'])
    recipe=json.loads((s.provenance.root/'artifacts'/data['recipe']['digest'][7:]).read_text())
    assert any(f['name']=='package/'+NAME for f in recipe['files'])
    view=trace(s).generation_summary(generation.generation)
    assert view['packages']['items'][0]['inputs']==s.binding()[1]['inputs']


@pytest.mark.parametrize('kind,revision',[('opaque','b'*64),('unknown',None)])
def test_non_git_revision_is_preserved_without_git_claim(tmp_path,kind,revision):
    s=Scenario(tmp_path);value=declare(s,kind=kind,revision=revision);run(s)
    data=inputs(s);record=s.provenance.store.get(data['sources'][0])
    assert record['data']['upstream']==[dict(repository='fixture:upstream',revision=None)] and record['gaps']
    recipe=json.loads((s.provenance.root/'artifacts'/data['recipe']['digest'][7:]).read_text())
    descriptor=next(f for f in recipe['files'] if f['name']=='package/'+NAME)
    assert ast.literal_eval((s.provenance.root/'artifacts'/descriptor['digest'][7:]).read_text())==value


def test_partial_declaration_keeps_source_specific_unknown(tmp_path):
    s=Scenario(tmp_path);value=declare(s,patches=1)
    value['sources'].pop();(s.root/'package/fixture'/NAME).write_text(repr(value));run(s)
    refs=inputs(s)['sources']
    assert not s.provenance.store.get(refs[0])['gaps']
    assert s.provenance.store.get(refs[1])['gaps']
    assert s.provenance.store.get(refs[1])['data']['upstream'][0]['revision'] is None


@pytest.mark.parametrize('damage',['hash','url','duplicate-source','short-git','unknown-value','type','schema','duplicate-repository'])
def test_bad_declaration_blocks_before_dispatch(tmp_path,damage):
    s=Scenario(tmp_path);value=declare(s)
    entry=value['sources'][0];u=entry['upstream'][0]
    if damage=='hash':entry['source']['sha256']='b'*64
    elif damage=='url':entry['source']['url']='https://other.invalid/source'
    elif damage=='duplicate-source':value['sources'].append(copy.deepcopy(entry))
    elif damage=='short-git':u['revision']='abc123'
    elif damage=='unknown-value':u['revision_type']='unknown'
    elif damage=='type':u['revision_type']='inferred-from-url'
    elif damage=='schema':value['schema']=True
    else:entry['upstream'].append(copy.deepcopy(u))
    (s.root/'package/fixture'/NAME).write_text(repr(value))
    with pytest.raises(ImageBuildError):run(s)
    assert not s.calls


def test_declaration_symlink_rejected(tmp_path):
    s=Scenario(tmp_path);declare(s)
    path=s.root/'package/fixture'/NAME;other=s.root/'declaration';path.rename(other);path.symlink_to(other)
    with pytest.raises(ImageBuildError,match='symlink'):run(s)
    assert not s.calls


def test_recovery_ignores_new_current_pin_recipe_and_upstream(tmp_path):
    s=Scenario(tmp_path);declare(s,patches=2);s.interrupt=True
    with pytest.raises(OSError):run(s)
    pipeline=s.pipeline();_,before=s.binding();captured=canonical(s.provenance.store.bundle([before['prepared']]))
    (s.root/'package/fixture'/NAME).write_text('new current upstream declaration')
    (s.root/'package/fixture/build.py').write_text('new current recipe')
    (s.root/'package/commit-pin.py').write_text('new monthly pin selection')
    s.original.write_text('new monthly pin bytes')
    (s.root/'patch-0').write_bytes(b'new upstream patch bytes')
    s.interrupt=False;s.builder=s.reopen();s.builder.resume(pipeline.parent.name)
    _,after=s.binding();assert after['prepared']==before['prepared'] and after['inputs']==before['inputs']
    assert canonical(s.provenance.store.bundle([before['prepared']]))==captured


@pytest.mark.parametrize('location',['artifact','staged','recipe','declaration'])
@pytest.mark.parametrize('damage',['missing','corrupt'])
def test_changed_required_material_blocks_recovery(tmp_path,location,damage):
    s=Scenario(tmp_path);declare(s,patches=1);s.interrupt=True
    with pytest.raises(OSError):run(s)
    pipeline=s.pipeline();binding_path,binding=s.binding();data=inputs(s)
    if location=='artifact':path=s.provenance.root/'artifacts'/data['patches'][0]['digest'][7:]
    elif location=='staged':path=binding_path.parent/'source/patches/0.patch'
    elif location=='recipe':path=pipeline.parent/'package/fixture/integration.py'
    else:path=pipeline.parent/'package/fixture'/NAME
    if damage=='missing':path.unlink()
    else:path.write_bytes(b'changed material')
    before=len(s.calls);s.interrupt=False
    with pytest.raises((ImageBuildError,OSError,ValueError)):s.builder.resume(pipeline.parent.name)
    assert len(s.calls)==before


@pytest.mark.parametrize('damage',['order','scope','source','boolean-order','missing-files','completeness'])
def test_patch_declarations_fail_before_dispatch(tmp_path,damage):
    s=Scenario(tmp_path);declare(s,patches=2)
    path=s.root/'package/fixture/integration.py';value=read_literal(path)
    patch=value['patches'][0]
    if damage=='order':value['patches'].reverse()
    elif damage=='scope':patch['applies_to']['version']='2'
    elif damage=='source':patch['source']['sha256']='b'*64
    elif damage=='boolean-order':patch['order']=True
    elif damage=='missing-files':patch['files']=[]
    else:value.pop('patches')
    path.write_text(repr(value))
    with pytest.raises(ImageBuildError):run(s)
    assert not s.calls


def test_partial_patch_classification_keeps_gap(tmp_path):
    s=Scenario(tmp_path);declare(s,patches=1)
    path=s.root/'package/fixture/integration.py';value=read_literal(path);value.pop('patches_complete');path.write_text(repr(value))
    run(s);data=inputs(s)
    assert len(data['patches'])==1
    assert any('not declared exhaustive' in gap for gap in s.provenance.store.get(s.binding()[1]['inputs'])['gaps'])


def test_comparison_reports_upstream_and_patch_order_without_rewriting_history(tmp_path):
    s=Scenario(tmp_path);declare(s,patches=2);first=run(s)
    old=s.provenance.store.bundle([first.manifest['build_record']['record']]);old_bytes=canonical(old)
    s.builder.release_pipeline(s.pipeline().parent.name)
    path=s.root/'package/fixture'/NAME;value=read_literal(path);value['sources'][0]['upstream'][0]['revision']='b'*40;path.write_text(repr(value))
    path=s.root/'package/fixture/integration.py';value=read_literal(path);value['patches'].reverse()
    for i,p in enumerate(value['patches'],1):p['order']=i
    path.write_text(repr(value));second=run(s)
    comparison=trace(s).compare_generations(first.generation,second.generation)
    row=comparison['packages']['items'][0]
    assert row['status']=='changed-inputs' and {'sources','patches'} <= set(row['changed_input_fields'])
    assert canonical(s.provenance.store.bundle(old['roots']))==old_bytes


def test_existing_unknown_record_is_not_retroactively_enriched(tmp_path):
    s=Scenario(tmp_path);first=run(s);old=s.provenance.store.bundle([first.manifest['build_record']['record']]);saved=canonical(old)
    s.builder.release_pipeline(s.pipeline().parent.name);declare(s);run(s)
    assert canonical(s.provenance.store.bundle(old['roots']))==saved
    sources=[r for r in old['records'].values() if r['kind']=='source-selection']
    assert sources[0]['data']['upstream'][0]['revision'] is None and sources[0]['gaps']


def test_catalogue_materialization_preserves_exact_declarations(tmp_path):
    root=Path(__file__).parents[1]/'project'
    destination=tmp_path/'recipes'
    stage_recipes(root/'bootstrap/python-libraries.py',root/'package',destination)
    packages=load_packages(destination)
    for name,kind in [('openssl','git'),('sqlite','opaque')]:
        assert (destination/(name+'-final')/NAME).read_bytes()==(root/'package'/name/NAME).read_bytes()
        assert packages[name+'-final'].source_provenance['sources'][0]['upstream'][0]['revision_type']==kind
    # A later declaration cannot alter an already materialized snapshot.
    path=destination/'openssl-final'/NAME;value=read_literal(path);value['sources'][0]['upstream'][0]['revision']='c'*40;path.write_text(repr(value));saved=path.read_bytes()
    with pytest.raises(ImageBuildError,match='recorded stage recipe changed'):
        stage_recipes(root/'bootstrap/python-libraries.py',root/'package',destination)
    assert path.read_bytes()==saved
