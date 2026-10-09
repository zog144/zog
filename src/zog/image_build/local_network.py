"""Explicit, offline name-service configuration for source build roots."""
from pathlib import Path
from .errors import ImageBuildError

FILES = {
    # Deterministic offline service fixture; not a complete IANA services database.
    'etc/services': 'http 80/tcp\nftp 21/tcp\ntelnet 23/tcp\nsmtp 25/tcp\n',
    'etc/hosts': '127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n',
    'etc/nsswitch.conf': ('passwd: files\ngroup: files\nshadow: files\n'
                         'hosts: files\nnetworks: files\nprotocols: files\n'
                         'services: files\nethers: files\nrpc: files\n'),
}


def install(root, files=FILES):
    root = Path(root)
    directory = root / 'etc'
    if directory.is_symlink():
        raise ImageBuildError('network configuration parent is a symlink')
    directory.mkdir(exist_ok=True)
    # Validate everything first; never replace unrelated or host-derived settings.
    for name, content in files.items():
        if name not in FILES:
            raise ImageBuildError('unsupported local network configuration')
        path = root / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_text() != content)):
            raise ImageBuildError('conflicting network configuration: ' + name)
    for name, content in files.items():
        path = root / name
        if not path.exists():
            path.write_text(content)
            path.chmod(0o644)
