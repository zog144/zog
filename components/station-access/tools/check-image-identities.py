"""Build gate: run against a rootfs BEFORE publishing a reusable image."""
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('rootfs');a=p.parse_args();root=Path(a.rootfs)
for relative in ['var/lib/host-discover/identity','var/lib/host-discover/credentials','var/lib/station-access/archive-access-signing','var/lib/station-access/station-vault']:
    path=root/relative
    if path.is_symlink() or (path.exists() and any(path.iterdir())):
        raise SystemExit('Refusing reusable image containing identity/credential state: '+relative)
for relative in ['var/lib/station-access/FIRST-LOGIN.txt','opt/station-access/state/FIRST-LOGIN.txt']:
    if (root/relative).exists() or (root/relative).is_symlink():raise SystemExit('Refusing reusable image containing login export: '+relative)
print('Identity state excluded from reusable image')
