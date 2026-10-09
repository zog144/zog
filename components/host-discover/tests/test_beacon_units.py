"""Composition boot graph, including the new root supervisor and consumer."""
import os
import shutil
import subprocess
from pathlib import Path
import pytest


def test_beacon_boot_graph(tmp_path):
    producer=(Path(os.environ['HOST_INSTALL_SOURCE'])/'src/zog/host_install/systemd' if os.environ.get('HOST_INSTALL_SOURCE') else Path(__import__('zog.host_install', fromlist=['__file__']).__file__).resolve().parent/'systemd')
    assert producer.is_dir(), 'Run with host-install source available for composition test'
    source=Path(__import__('zog.host_discover', fromlist=['__file__']).__file__).resolve().parent/'systemd'
    units=tmp_path/'etc/systemd/system';units.mkdir(parents=True)
    for path in producer.glob('*.service'):shutil.copyfile(path,units/path.name)
    shutil.copyfile(producer/'host-install-admission.socket',units/'host-install-admission.socket')
    for name in ('host-discover-supervisor.socket','host-discover-supervisor@.service','host-discover-beacon.service'):
        shutil.copyfile(source/name,units/name)
    (units/'state.mount').write_text((producer/'state.mount.in').read_text().replace('@STATE_PARTUUID@','11111111-1111-4111-8111-111111111111'))
    targets={'sysinit.target':'','sockets.target':'Before=basic.target\n','basic.target':'Requires=sysinit.target sockets.target\nAfter=sysinit.target sockets.target\n',
        'multi-user.target':'Requires=basic.target\nAfter=basic.target\nWants=host-discover-beacon.service\n',
        'shutdown.target':'','local-fs.target':'','local-fs-pre.target':'','network-online.target':''}
    for name,body in targets.items():(units/name).write_text('[Unit]\nDescription=Boot graph fixture\nDefaultDependencies=no\n'+body)
    for name in ('host-install','host-discover','host-discover-supervisor'):
        exe=tmp_path/'usr/bin'/name;exe.parent.mkdir(parents=True,exist_ok=True);exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o755)
    (tmp_path/'etc/passwd').write_text('root:x:0:0::/root:/bin/sh\nhost-discover:x:970:970::/state/host-discover:/usr/sbin/nologin\n')
    (tmp_path/'etc/group').write_text('root:x:0:\nhost-discover:x:970:\narchive-consumers:x:972:\nhost-control:x:973:\n')
    command=['systemd-analyze','verify','--generators=no','--man=no','--root='+str(tmp_path),'multi-user.target']
    p=subprocess.run(command,capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    assert 'ordering cycle' not in p.stderr.lower(),p.stderr
    socket=units/'host-discover-supervisor.socket';socket.write_text(socket.read_text().replace('DefaultDependencies=no\n',''))
    p=subprocess.run(command,capture_output=True,text=True)
    assert 'ordering cycle' in p.stderr.lower(),p.stderr
