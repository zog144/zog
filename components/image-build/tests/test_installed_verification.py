"""Canonical installed-test reports using the real verification/publication paths."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
pytest.importorskip("zog.build_record")
from zog.build_record import audit_generation, canonical
from zog.image_build import ImageBuild
from zog.image_build import generation_provenance as gp, installed_verification as iv
from zog.image_build.developer.seed_build import verify as run_verification
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory, write_json
from zog.image_build.final_compiler import successful_execution
from zog.image_build.metadata import Package, identity
from zog.image_build.provenance import Provenance
from zog.image_build.runner import BoxControlRunner, BuildExecutionResult


def scenario(tmp_path, *, contract=True):
    root=tmp_path/'candidate';root.mkdir();(root/'payload').write_text('accepted bytes')
    monthly=tmp_path/'pin.py';monthly.write_text(repr({'date':'2026-10-01'}))
    state=tmp_path/'state'
    pin=Provenance.capture_pin(state,monthly,repository='fixture',revision='a'*40,repository_path='pins/pin.py')
    p=Provenance(state,host_id='host',project_id='project',pin=pin)
    record=dict(inputs={},outputs=inventory(root));record['identity']=identity(record)
    record.update(root=str(root),provenance=p.legacy_output('base',record))
    built={'base':record};definitions={'base':Package('base',(),(),(),{},{},(),{})}
    calls=[]
    def execute(request):
        calls.append(request)
        return BuildExecutionResult('build-job','invocation',0,True,'journal-reference')
    execute.configuration=lambda: {'fixture':'controller-policy'}
    builder=ImageBuild(package_dir=tmp_path/'recipes',state_dir=state,
        runner=BoxControlRunner(execute=execute),provenance=p)
    owner=dict(kind='image',architecture='fixture',verification_command='fixture-check',execution_policy=builder._policy())
    if contract:owner['verification_report_contract']=iv.CONTRACT
    attempt=state/'image-build/attempts/assembly'
    binding=gp.prepare(p,attempt,definitions,['base'],built,owner)
    check=state/'image-build/attempts/installed-check'
    run_verification(builder,check,root,[['/bin/bash','-eu','-c','fixture-check']],owner)
    execution=successful_execution(check)
    return SimpleNamespace(p=p,root=root,built=built,builder=builder,owner=owner,
        attempt=attempt,binding=binding,check=check,execution=execution,calls=calls)


def capture(s):
    return iv.capture(s.p,s.binding,s.root,s.owner,s.check,s.execution)


def test_report_export_and_replay_after_verification_workspace_cleanup(tmp_path):
    s=scenario(tmp_path);report=capture(s)
    assert not (s.check/'root').exists()
    pointer=gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])
    selected=s.builder._publish(s.root,s.owner,'image',dict(packages=s.built,
        build_record=pointer,verification_execution=s.execution))
    bundle=gp.verify(s.p,selected)
    expected=dict(schema_version=1,record=pointer['record'],generation_id=json.dumps(
        ['host','project',selected.generation],separators=(',',':')),packages=['base'])
    audit=audit_generation(bundle,expected,paths={a['digest']:s.p.root/'artifacts'/a['digest'][7:]
        for a in s.p.library.inspect(bundle)['artifacts']})
    assert audit['matches_expected_generation'] and not audit['inspection']['missing_records']
    assert all(a['status']=='verified' for a in audit['inspection']['artifact_verification'])
    assert not audit['passed']  # Legacy history remains explicit.
    assert bundle['records'][pointer['record']]['data']['verification']==[report]
    data=json.loads((s.p.root/'artifacts'/report['digest'][7:]).read_bytes())
    assert data['execution']['invocation_id']=='invocation'
    assert data['trace']=={'host_id':'host','build_id':'attempt:installed-check'}
    assert 'fixture-check' not in json.dumps(data) and 'logs' not in data
    before=canonical(bundle)
    run_verification(s.builder,s.check,s.root,[['/bin/bash','-eu','-c','fixture-check']],s.owner)
    assert capture(s)==report
    assert gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])==pointer
    assert canonical(gp.verify(s.p,selected))==before and len(s.calls)==1


@pytest.mark.parametrize('phase',['verification','finalizing','generation'])
def test_lost_write_response_preserves_report_and_attempt(tmp_path,monkeypatch,phase):
    s=scenario(tmp_path);report=capture(s);tripped=False
    def lost(path,value):
        nonlocal tripped
        write_json(path,value)
        if Path(path)==s.attempt/'assembly'/(phase+'.json') and not tripped:
            tripped=True;raise OSError('lost response')
    monkeypatch.setattr(gp,'write_json',lost)
    with pytest.raises(OSError,match='lost response'):
        gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])
    pointer=gp.finish(s.p,s.attempt,s.binding,s.root,verification=[capture(s)])
    assert pointer['prepared']==s.binding['prepared'] and len(s.calls)==1
    assert s.p.store.get(pointer['record'])['data']['verification']==[report]


@pytest.mark.parametrize('change',['candidate','commands','policy','invocation','failed','cleanup','output','request-root'])
def test_capture_rejects_changed_or_unsuccessful_evidence(tmp_path,change):
    s=scenario(tmp_path)
    if change=='candidate':(s.root/'payload').write_text('different root')
    elif change in ('commands','policy'):
        file=s.check/('prepared.json' if change=='commands' else 'verification.json')
        data=json.loads(file.read_text());data['commands' if change=='commands' else 'policy']='changed';write_json(file,data)
    elif change=='output':(s.check/'output/extra').write_text('changed')
    elif change=='invocation':s.execution['invocation_id']='other'
    else:
        if change=='failed':s.execution['exit_code']=1
        elif change=='cleanup':s.execution['cleanup_complete']=False
        else:s.execution['request']['root']='/different-root'
        write_json(s.check/'command-0.execution.json',s.execution)
    with pytest.raises(ImageBuildError):capture(s)
    assert not (s.attempt/'assembly/generation.json').exists()


@pytest.mark.parametrize('change',['missing','tampered','omitted','replaced','candidate'])
def test_finalization_rejects_lost_or_replaced_report(tmp_path,change):
    s=scenario(tmp_path);report=capture(s)
    pointer=gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])
    path=s.p.root/'artifacts'/report['digest'][7:];reports=[report]
    if change=='missing':path.unlink()
    elif change=='tampered':path.write_text('{}')
    elif change=='omitted':reports=[]
    elif change=='candidate':(s.root/'payload').write_text('changed after capture')
    else:
        s.execution['invocation_id']='different'
        write_json(s.check/'command-0.execution.json',s.execution)
        reports=[capture(s)]
    with pytest.raises((ImageBuildError,OSError)):
        gp.finish(s.p,s.attempt,s.binding,s.root,verification=reports)
    assert json.loads((s.attempt/'assembly/generation.json').read_text())==pointer


def test_legacy_contract_is_readable_and_cannot_gain_report(tmp_path):
    s=scenario(tmp_path,contract=False)
    pointer=gp.finish(s.p,s.attempt,s.binding,s.root)
    assert s.p.store.get(pointer['record'])['data']['verification']==[]
    with pytest.raises(ImageBuildError,match='not frozen'):capture(s)
    fake=s.p._bytes(iv.NAME,{'invented':'report'})
    with pytest.raises(ImageBuildError,match='retrofit'):
        gp.finish(s.p,s.attempt,s.binding,s.root,verification=[fake])
    assert gp.finish(s.p,s.attempt,s.binding,s.root)==pointer


def test_owner_execution_cannot_disagree_with_canonical_report(tmp_path):
    s=scenario(tmp_path);report=capture(s)
    pointer=gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])
    altered=dict(s.execution,invocation_id='wrong')
    with pytest.raises(ImageBuildError,match='owner execution differs'):
        s.builder._publish(s.root,s.owner,'image',dict(packages=s.built,
            build_record=pointer,verification_execution=altered))
    assert not (s.p.state/'image-build/generations'/s.binding['generation']).exists()


def test_candidate_change_between_report_validation_and_archive_blocks_finish(tmp_path,monkeypatch):
    s=scenario(tmp_path);report=capture(s)
    from zog.image_build import host_export
    original=host_export._payload
    def change(root,archive):
        (root/'payload').write_text('changed before serialization')
        return original(root,archive)
    monkeypatch.setattr(host_export,'_payload',change)
    with pytest.raises(ImageBuildError,match='subject differs'):
        gp.finish(s.p,s.attempt,s.binding,s.root,verification=[report])
    assert not (s.attempt/'assembly/generation.json').exists()
