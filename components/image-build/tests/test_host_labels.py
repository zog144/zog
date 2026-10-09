import os
from pathlib import Path
import pytest
from zog.image_build import host_labels
from zog.image_build.filesystem import inventory
from zog.image_build.errors import ImageBuildError


def fixture(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'file').write_text('accepted bytes');(source/'file').chmod(0o444)
    (source/'link').symlink_to('file')
    return source, {'base':{'root':source,'identity':'fixed-output','outputs':inventory(source)}}


def test_omit_only_host_labels_preserve_input_and_recover(tmp_path,monkeypatch):
    source,built=fixture(tmp_path)
    original_list=os.listxattr;original_get=os.getxattr
    label=b'system_u:object_r:var_lib_t:s0\0'
    def labels(path,**kw):
        return ['security.selinux'] if Path(path)==source/'file' else original_list(path,**kw)
    monkeypatch.setattr(os,'listxattr',labels)
    monkeypatch.setattr(os,'getxattr',lambda path,name,**kw:label if Path(path)==source/'file' else original_get(path,name,**kw))
    frozen=host_labels.snapshot(built)
    attempt=tmp_path/'attempt';attempt.mkdir()
    root=host_labels.compose(attempt,built,['base'],frozen)
    assert inventory(root)==built['base']['outputs']
    assert os.listxattr(source/'file')==['security.selinux']
    assert os.listxattr(root/'file')==[]
    assert host_labels.compose(attempt,built,['base'],frozen)==root
    (root/'file').chmod(0o644);(root/'file').write_text('altered')
    with pytest.raises(ImageBuildError,match='composition changed'):
        host_labels.compose(attempt,built,['base'],frozen)


def test_unknown_attributes_rejected_before_composition(tmp_path,monkeypatch):
    source,built=fixture(tmp_path)
    monkeypatch.setattr(os,'listxattr',lambda *a,**k:['security.capability'])
    with pytest.raises(ImageBuildError,match='unhandled'):
        host_labels.snapshot(built)


def test_changed_host_labels_rejected(tmp_path,monkeypatch):
    source,built=fixture(tmp_path)
    frozen=host_labels.snapshot(built)
    monkeypatch.setattr(os,'listxattr',lambda *a,**k:['security.selinux'])
    monkeypatch.setattr(os,'getxattr',lambda *a,**k:b'changed')
    with pytest.raises(ImageBuildError,match='evidence changed'):
        host_labels.compose(tmp_path/'attempt',built,['base'],frozen)


def test_omission_material_is_in_canonical_assembly_closure(tmp_path):
    pytest.importorskip("zog.build_record")
    from zog.image_build.provenance import Provenance
    from zog.image_build.metadata import Package,identity
    from zog.image_build.generation_provenance import prepare,finish
    source,built=fixture(tmp_path)
    monthly=tmp_path/'commit-pin.py';monthly.write_text(repr({'date':'2026-10-01'}))
    pin=Provenance.capture_pin(tmp_path/'state',monthly,repository='fixture',revision='a'*40,repository_path='pins/commit-pin.py')
    p=Provenance(tmp_path/'state',host_id='host',project_id='project',pin=pin)
    built['base']['inputs']={}
    built['base']['identity']=identity({'inputs':{},'outputs':built['base']['outputs']})
    built['base']['provenance']=p.legacy_output('base',built['base'])
    definitions={'base':Package('base',(),(),(),{},{},(),{})}
    labels=host_labels.snapshot(built)
    material=p._bytes('host-label-omissions.json',labels)
    attempt=tmp_path/'attempt'
    binding=prepare(p,attempt,definitions,['base'],built,{'architecture':'fixture','composition_policy':host_labels.POLICY},composition_materials=[material])
    root=host_labels.compose(attempt,built,['base'],labels)
    pointer=finish(p,attempt,binding,root)
    bundle=p._verify([pointer['record']])
    inputs=bundle['records'][binding['inputs']]['data']
    assert material in inputs['materials']
    assert bundle['records'][pointer['record']]['data']['packages']==[built['base']['provenance']]


def test_application_mountpoints_are_bound_before_publication(tmp_path):
    from zog.image_build.host_labels import snapshot, compose
    from zog.image_build.filesystem import inventory
    from zog.image_build.errors import ImageBuildError
    import pytest
    root = tmp_path/'source'
    root.mkdir()
    (root/'etc').mkdir()
    (root/'etc/example').write_text('fixture')
    built = {'base': {'identity':'fixture', 'root':str(root), 'outputs':inventory(root)}}
    attempt = tmp_path/'attempt'
    attempt.mkdir()
    labels = snapshot(built)
    result = compose(attempt,built,['base'],labels,directories={'dev':0o755,'var/tmp':0o1777})
    assert (result/'var/tmp').stat().st_mode & 0o7777 == 0o1777
    assert not (root/'dev').exists()
    assert compose(attempt,built,['base'],labels,directories={'dev':0o755,'var/tmp':0o1777}) == result
    with pytest.raises(ImageBuildError,match='composition changed'):
        compose(attempt,built,['base'],labels,directories={'dev':0o700})
    with pytest.raises(ImageBuildError):
        compose(attempt,built,['base'],labels,directories={'../escape':0o755})
