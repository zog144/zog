"""Readable synthetic source archives exercise link containment and endpoints."""
import hashlib
import io
import os
import tarfile
from types import SimpleNamespace

import tempfile
import unittest
from pathlib import Path

from zog.image_build.errors import ImageBuildError
from zog.image_build.sources import stage


def extract(tmp_path, entries):
    cache = tmp_path / 'cache'
    cache.mkdir()
    payload = tmp_path / 'fixture.tar'
    with tarfile.open(payload, 'w') as archive:
        for name, kind, value in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if kind == 'directory' else 0o644
            if kind == 'file':
                data = value.encode()
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            else:
                member.type = {'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE,
                               'directory': tarfile.DIRTYPE}[kind]
                member.linkname = value
                archive.addfile(member)
    data = payload.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    (cache / sha).write_bytes(data)
    package = SimpleNamespace(sources=[{'url': 'https://example.invalid/fixture.tar',
        'sha256': sha, 'destination': 'upstream', 'archive': True}])
    stage(package, tmp_path / 'source', cache)
    return tmp_path / 'source' / 'upstream'


def check_kmod_contained_dangling_fixture(tmp_path):
    name = 'kmod/testsuite/rootfs-pristine/test-loaded/sys/module/btusb/drivers/usb:btusb'
    target = '../../../bus/usb/drivers/btusb'
    root = extract(tmp_path, [(name, 'symlink', target)])
    link = root / name
    assert link.is_symlink() and not link.exists()
    assert os.readlink(link) == target
    assert link.resolve().is_relative_to(root)


def check_dangling_chain_is_contained(tmp_path):
    root = extract(tmp_path, [('pkg/a', 'symlink', 'b'), ('pkg/b', 'symlink', 'missing')])
    assert os.readlink(root / 'pkg/a') == 'missing'
    assert os.readlink(root / 'pkg/b') == 'missing'


def check_symlink_to_implicit_directory(tmp_path):
    root = extract(tmp_path, [('pkg/alias', 'symlink', 'dir'), ('pkg/dir/file', 'file', 'data')])
    assert (root / 'pkg/alias/file').read_text() == 'data'


def check_hardlink_through_symlink_to_file(tmp_path):
    root = extract(tmp_path, [('pkg/hard', 'hardlink', 'pkg/sym'),
        ('pkg/sym', 'symlink', 'file'), ('pkg/file', 'file', 'data')])
    assert (root / 'pkg/hard').read_text() == 'data'
    assert not (root / 'pkg/hard').is_symlink()


INVALID_ENTRIES = [
    [('pkg/link', 'symlink', '../../outside')],
    [('pkg/link', 'symlink', '/outside')],
    [('pkg/a', 'symlink', 'b'), ('pkg/b', 'symlink', '../../outside')],
    [('pkg/a', 'symlink', 'b'), ('pkg/b', 'symlink', 'a')],
    [('pkg/a', 'symlink', 'a')],
    [('pkg/hard', 'hardlink', 'pkg/missing')],
    [('pkg/hard', 'hardlink', 'pkg/sym'), ('pkg/sym', 'symlink', 'missing')],
    [('pkg/hard', 'hardlink', 'pkg/dir'), ('pkg/dir', 'directory', '')],
    [('pkg/a', 'symlink', 'missing'), ('pkg/a/file', 'file', 'data')],
    [('pkg/a', 'symlink', 'missing'), ('pkg/b', 'symlink', 'a/file')],
    [('pkg/a', 'symlink', 'missing'), ('pkg/a', 'file', 'data')],
]

class SourceArchiveLinksTests(unittest.TestCase):
    def test_contained_links(self):
        for check in (check_kmod_contained_dangling_fixture,
                      check_dangling_chain_is_contained,
                      check_symlink_to_implicit_directory,
                      check_hardlink_through_symlink_to_file):
            with self.subTest(check=check.__name__), tempfile.TemporaryDirectory() as tmp:
                check(Path(tmp))

    def test_unsafe_or_invalid_links_rejected_before_extraction(self):
        for entries in INVALID_ENTRIES:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(ImageBuildError):
                    extract(root, entries)
                self.assertEqual(list((root / 'source/upstream').iterdir()), [])
