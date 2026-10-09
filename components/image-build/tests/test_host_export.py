import json
import os
from pathlib import Path
import tarfile

import pytest

from zog.image_build import ImageBuild
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import write_json
from zog.image_build.host_export import export, verify, _tar_records
from zog.image_build.metadata import identity


@pytest.fixture
def generation(tmp_path):
    root = tmp_path/'seed'; (root/'usr/bin').mkdir(parents=True)
    (root/'usr/bin/bash').write_text('fixture only'); (root/'usr/bin/bash').chmod(0o755)
    (root/'bin').symlink_to('usr/bin')
    b = ImageBuild(package_dir=tmp_path/'recipes', state_dir=tmp_path/'state')
    return b.import_bootstrap(root, {'fixture': True}).root.parent


def evidence(): return {'packages': [], 'acceptance': []}


def rewrite(bundle, mutate):
    m = json.loads((bundle/'manifest.json').read_text()); mutate(m)
    m.pop('artifact_id'); m['artifact_id'] = identity(m)
    write_json(bundle/'manifest.json', m)
    return m['artifact_id']


def test_roundtrip_deterministic_and_honest(generation, tmp_path):
    original = (generation/'manifest.json').read_bytes()
    a = export(generation, tmp_path/'a', evidence())
    b = export(generation, tmp_path/'b', evidence())
    assert a == b
    assert verify(tmp_path/'a', a['artifact_id']) == a
    assert not a['readiness']['installable']
    assert a['readiness']['presence_checks']['shell']
    assert not a['readiness']['presence_checks']['pid1']
    assert not a['security']['verified_boot']
    assert a['generation']['kind'] == 'host-bootstrap'
    assert (generation/'manifest.json').read_bytes() == original
    assert all(r['uid'] == r['gid'] == 0 for r in a['rootfs']['entries'])


def test_payload_corruption_and_untrusted_manifest(generation, tmp_path):
    folder = tmp_path/'out'; m = export(generation, folder, evidence())
    with (folder/'rootfs.tar').open('r+b') as f: f.write(b'corrupt')
    with pytest.raises(ImageBuildError, match='hash/size'): verify(folder, m['artifact_id'])
    with pytest.raises(ImageBuildError, match='identity'): verify(folder, '0'*64)


@pytest.mark.parametrize('claim', ['readiness', 'security', 'generation'])
def test_rehashed_false_claim_rejected(generation, tmp_path, claim):
    folder = tmp_path/'out'; export(generation, folder, evidence())
    def mutate(m):
        if claim == 'readiness': m[claim]['installable'] = True
        elif claim == 'security': m[claim]['verified_boot'] = True
        else: m[claim]['outputs'] = []
    pin = rewrite(folder, mutate)
    with pytest.raises(ImageBuildError): verify(folder, pin)


def test_changed_generation_and_existing_destination(generation, tmp_path):
    out = tmp_path/'out'; export(generation, out, evidence())
    with pytest.raises(ImageBuildError, match='must be new'): export(generation, out, evidence())
    (generation/'root/usr/bin/bash').write_text('changed')
    with pytest.raises(ImageBuildError, match='outputs changed'): export(generation, tmp_path/'new', evidence())


def test_interrupted_export_has_no_published_result(generation, tmp_path, monkeypatch):
    from zog.image_build import host_export
    def broken(*args): raise OSError('simulated interruption')
    monkeypatch.setattr(host_export, '_write_tar', broken)
    with pytest.raises(OSError): export(generation, tmp_path/'out', evidence())
    assert not (tmp_path/'out').exists()
    assert not list(tmp_path.glob('.host-export-*'))


def test_metadata_and_known_secrets_rejected(generation, tmp_path):
    # Re-import each fixture so source manifest remains internally consistent.
    root = tmp_path/'secret'; (root/'etc').mkdir(parents=True)
    (root/'etc/machine-id').write_text('host-specific')
    b = ImageBuild(package_dir=tmp_path/'recipes', state_dir=tmp_path/'state2')
    g = b.import_bootstrap(root, {}).root.parent
    with pytest.raises(ImageBuildError, match='host-specific'): export(g, tmp_path/'out', evidence())
    p = generation/'root/usr/bin/bash'
    os.setxattr(p, 'user.test', b'evidence')
    with pytest.raises(ImageBuildError, match='extended attributes'): export(generation, tmp_path/'out', evidence())
    os.removexattr(p, 'user.test')
    os.link(p, tmp_path/'alias')
    with pytest.raises(ImageBuildError, match='hard links'): export(generation, tmp_path/'out', evidence())


@pytest.mark.parametrize('attack', ['traversal', 'absolute', 'duplicate', 'symlink-parent', 'device', 'hardlink', 'owner'])
def test_unsafe_tar_rejected(tmp_path, attack):
    path = tmp_path/'attack.tar'
    with tarfile.open(path, 'w') as t:
        m = tarfile.TarInfo('x')
        if attack == 'traversal': m.name = '../outside'
        if attack == 'absolute': m.name = '/outside'
        if attack == 'device': m.type = tarfile.CHRTYPE
        if attack == 'hardlink': m.type = tarfile.LNKTYPE; m.linkname = 'elsewhere'
        if attack == 'owner': m.uid = 42
        if attack == 'symlink-parent': m.type = tarfile.SYMTYPE; m.linkname = '/tmp'
        t.addfile(m)
        if attack == 'duplicate': t.addfile(m)
        if attack == 'symlink-parent': t.addfile(tarfile.TarInfo('x/escape'))
    with pytest.raises(ImageBuildError): _tar_records(path)
    assert not (tmp_path/'outside').exists()


def test_foreign_boot_provenance(generation, tmp_path):
    boot = tmp_path/'boot'; (boot/'modules/6.fixture').mkdir(parents=True)
    for p in ['kernel', 'initramfs', 'modules/6.fixture/test.ko']: (boot/p).write_text('fixture')
    architecture = json.loads((generation/'manifest.json').read_text())['inputs']['architecture']
    provenance = {'distribution':'amazon-linux', 'release':'2023', 'architecture':architecture,
                  'kernel_release':'6.fixture', 'packages':['kernel-6.fixture.amzn2023'],
                  'acquisition':'non-bootable test fixture'}
    m = export(generation, tmp_path/'out', evidence(), boot_tree=boot, boot_provenance=provenance)
    assert verify(tmp_path/'out', m['artifact_id']) == m
    assert m['boot_bundle']['origin'] == 'foreign'
    assert not m['boot_bundle']['verified_boot']
    provenance['kernel_release'] = 'wrong'
    with pytest.raises(ImageBuildError, match='matching module'): export(generation, tmp_path/'bad', evidence(), boot_tree=boot, boot_provenance=provenance)


def test_manifest_cannot_redirect_payload(generation, tmp_path):
    folder = tmp_path/'out'; export(generation, folder, evidence())
    pin = rewrite(folder, lambda m: m['rootfs'].update(file='../outside'))
    with pytest.raises(ImageBuildError): verify(folder, pin)


def test_sticky_directory_and_cli(generation, tmp_path, capsys):
    from zog.image_build.host_export import main
    import sys
    root = tmp_path/'sticky'; (root/'tmp').mkdir(parents=True); (root/'tmp').chmod(0o1777)
    b = ImageBuild(package_dir=tmp_path/'recipes', state_dir=tmp_path/'state3')
    g = b.import_bootstrap(root, {}).root.parent
    m = export(g, tmp_path/'bundle', evidence())
    assert m['rootfs']['entries'][0]['mode'] == 0o1777
    old = sys.argv
    try:
        sys.argv = ['host_export', 'verify', str(tmp_path/'bundle'), '--expected-id', m['artifact_id']]
        main()
    finally:
        sys.argv = old
    assert json.loads(capsys.readouterr().out)['readiness']['installable'] is False


def test_archive_comparison_uses_component_path_order(tmp_path):
    from zog.image_build.host_export import _payload,records
    root=tmp_path/'root'
    (root/'usr/include/asm').mkdir(parents=True)
    (root/'usr/include/asm-generic').mkdir()
    (root/'usr/include/asm/a.h').write_text('asm header')
    (root/'usr/include/asm-generic/a.h').write_text('generic header')
    (root/'usr/include/asm.h').write_text('sibling header')
    before=records(root)
    payload=_payload(root,tmp_path/'rootfs.tar')
    assert payload['entries']==before==records(root)
    assert _tar_records(tmp_path/'rootfs.tar')==before


def test_posix_backslash_names_roundtrip_without_unescaping(tmp_path):
    root = tmp_path/'literal-root'
    unit = r'usr/lib/systemd/system/system-systemd\x2dmute\x2dconsole.slice'
    literal = r'usr/lib/systemd/system/..\outside'
    (root/unit).parent.mkdir(parents=True)
    (root/unit).write_bytes(b'original fixture unit\n')
    (root/literal).write_bytes(b'literal POSIX name\n')
    link = r'usr/lib/systemd/system/alias\x2dunit.slice'
    (root/link).symlink_to(Path(unit).name)
    builder = ImageBuild(package_dir=tmp_path/'recipes', state_dir=tmp_path/'state')
    selected = builder.import_bootstrap(root, {'fixture': True})
    bundle = tmp_path/'bundle'
    manifest = export(selected.root.parent, bundle, evidence())
    assert verify(bundle, manifest['artifact_id']) == manifest
    with tarfile.open(bundle/'rootfs.tar', 'r:') as archive:
        assert archive.extractfile(unit).read() == b'original fixture unit\n'
        assert archive.extractfile(literal).read() == b'literal POSIX name\n'
        assert archive.getmember(link).linkname == Path(unit).name
        assert unit.replace(r'\x2d', '-') not in archive.getnames()
    assert export(selected.root.parent, tmp_path/'again', evidence()) == manifest


@pytest.mark.parametrize('name', ['', '/outside', '../outside', 'a/../b', 'a/./b',
                                   'a//b', 'a/', 'a\x00b', 'a\\name/../outside'])
def test_payload_paths_still_reject_posix_traversal(name):
    from zog.image_build.host_export import safe_payload_name
    with pytest.raises(ImageBuildError):
        safe_payload_name(name)


@pytest.mark.parametrize('attack', ['duplicate', 'symlink-parent'])
def test_backslash_archive_paths_retain_structural_checks(tmp_path, attack):
    path = tmp_path/'attack.tar'
    with tarfile.open(path, 'w', format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo(r'literal\x2dname')
        if attack == 'symlink-parent':
            member.type = tarfile.SYMTYPE
            member.linkname = '/tmp'
        archive.addfile(member)
        archive.addfile(member if attack == 'duplicate' else
                        tarfile.TarInfo(member.name+'/escape'))
    with pytest.raises(ImageBuildError, match='duplicate|symlink parent'):
        _tar_records(path)


def test_metadata_names_remain_restricted():
    from zog.image_build.host_export import safe_name
    with pytest.raises(ImageBuildError, match='invalid artifact path'):
        safe_name(r'6.fixture\release')
