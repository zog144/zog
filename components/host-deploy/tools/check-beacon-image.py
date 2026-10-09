"""Run before publishing a reusable rootfs/AMI; rejects installer-specific state."""
import argparse
from pathlib import Path
import runpy
import sys
p=argparse.ArgumentParser();p.add_argument('rootfs');a=p.parse_args();root=Path(a.rootfs)
for name in ('opt/host-discover/rollback','opt/host-discover/identity-owner.json','opt/host-discover/activation.json','etc/host-discover/configuration.json'):
    path=root/name
    if path.exists() or path.is_symlink():raise SystemExit('Host-specific state must not enter reusable image: '+name)
for path in (root/'opt/host-discover/releases').glob('*/configuration.json'):
    raise SystemExit('Host-specific staged configuration must not enter reusable image')
for path in (root/'opt/host-discover/releases').glob('*/request.json'):
    raise SystemExit('Host-specific installer request must not enter reusable image')
sys.argv=[sys.argv[0],a.rootfs]
runpy.run_path(str(Path(__file__).resolve().parents[1]/'host_deploy/beacon_bundle/tools/check-image-identities.py'),run_name='__main__')
