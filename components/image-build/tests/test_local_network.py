import pytest
from zog.image_build.local_network import install, FILES
from zog.image_build.errors import ImageBuildError


def test_explicit_local_files_and_idempotence(tmp_path):
    install(tmp_path);install(tmp_path)
    for name,content in FILES.items():
        assert (tmp_path/name).read_text()==content
        assert (tmp_path/name).stat().st_mode & 0o777 == 0o644
    assert 'hosts: files\n' in (tmp_path/'etc/nsswitch.conf').read_text()
    assert not (tmp_path/'etc/resolv.conf').exists()


def test_conflict_does_not_partially_write(tmp_path):
    (tmp_path/'etc').mkdir();(tmp_path/'etc/nsswitch.conf').write_text('hosts: dns\n')
    with pytest.raises(ImageBuildError):install(tmp_path)
    assert not (tmp_path/'etc/hosts').exists()
    assert (tmp_path/'etc/nsswitch.conf').read_text()=='hosts: dns\n'


def test_symlink_parent_and_target_rejected(tmp_path):
    outside=tmp_path/'outside';outside.mkdir();root=tmp_path/'root';root.mkdir()
    (root/'etc').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ImageBuildError):install(root)
    (root/'etc').unlink();(root/'etc').mkdir();(root/'etc/hosts').symlink_to(outside/'hosts')
    with pytest.raises(ImageBuildError):install(root)
    assert not (outside/'hosts').exists()


def test_offline_services_fixture(tmp_path):
    install(tmp_path)
    rows = dict(line.split() for line in (tmp_path/'etc/services').read_text().splitlines())
    assert rows == {'http': '80/tcp', 'ftp': '21/tcp', 'telnet': '23/tcp', 'smtp': '25/tcp'}
