"""Composition with real consumer supervisor; only mount/identity evidence is synthetic."""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from zog.host_install import beacon_profile as profile
from zog.host_install.state_contract import StateError
from zog.host_install.state_provision import prepare_tree
from test_state_provision import Context
from zog.host_discover import supervisor

@pytest.fixture
def environment(tmp_path):
    c=Context(tmp_path)
    prepare_tree(c,c.bundle['bootstrap']['state']['state_volume_id'])
    observation={'recovery_hold':False,'receipt':{'fingerprint':'a'*64}}
    with patch.object(supervisor.wire,'observe',return_value=observation):
        yield c,tmp_path,c.bundle['bootstrap']['state']['state_volume_id']
    c.close()

def test_explicit_preparation_retry_upgrade_and_missing_ledger(environment):
    c,root,volume=environment
    with pytest.raises(StateError):profile.prepare(c,'wrong',supervisor)
    profile.prepare(c,volume,supervisor)
    ledger=root/supervisor.NAME/'ledger.json';original=ledger.read_bytes()
    profile.prepare(c,volume,supervisor)
    c.bundle['bootstrap']['configuration_revision']+=1
    profile.prepare(c,volume,supervisor)
    assert ledger.read_bytes()==original
    ledger.unlink()
    with pytest.raises(StateError):profile.prepare(c,volume,supervisor)
    assert not ledger.exists()

def test_operated_ledger_preserved_and_corrupt_refused(environment):
    c,root,volume=environment;profile.prepare(c,volume,supervisor)
    ledger=root/supervisor.NAME/'ledger.json'
    value=json.loads(ledger.read_text());value['revision']=5;ledger.write_text(json.dumps(value))
    original=ledger.read_bytes();profile.prepare(c,volume,supervisor);assert ledger.read_bytes()==original
    ledger.write_text('broken')
    with pytest.raises(StateError):profile.prepare(c,volume,supervisor)

def test_incomplete_provision_retries_without_competing_state(environment):
    c,root,volume=environment;original=profile.publish
    def fail(fd,name,*a,**kw):
        if name=='beacon-prepared.json':raise OSError('interruption')
        return original(fd,name,*a,**kw)
    with patch.object(profile,'publish',side_effect=fail),pytest.raises(OSError):profile.prepare(c,volume,supervisor)
    ledger=root/supervisor.NAME/'ledger.json';before=ledger.read_bytes()
    profile.prepare(c,volume,supervisor);assert ledger.read_bytes()==before

def test_unrecorded_existing_journal_is_not_adopted(environment):
    c,root,volume=environment
    journal=root/'host-discover/control/managed.json';journal.write_text('{}');journal.chmod(0o600);os.chown(journal,970,970)
    with pytest.raises(StateError):profile.prepare(c,volume,supervisor)
    assert not (root/supervisor.NAME).exists()

def test_offline_profile_is_repeatable_exclusive_and_has_no_preparation(tmp_path):
    consumer=Path(os.environ['HOST_DISCOVER_SOURCE']);producer=Path(__file__).resolve().parents[1]
    out=tmp_path/'overlay';profile.stage(consumer,producer,out,'/opt/zog/bin')
    profile.stage(consumer,producer,out,'/opt/zog/bin')
    units=out/'etc/systemd/system';beacon=(units/'host-discover-beacon.service').read_text()
    assert 'Conflicts=host-discover.service host-discover-managed.service' in beacon
    assert 'KillMode=mixed\nTimeoutStopSec=90s\n' in beacon
    assert beacon.count('KillMode=') == beacon.count('TimeoutStopSec=') == 1
    assert 'ExecStart=/opt/zog/bin/host-discover --managed-beacon' in beacon
    assert not (out/'state').exists()
    for p in units.iterdir():
        assert 'beacon-prepare' not in p.read_text()
        assert 'supervisor prepare' not in p.read_text()
    with pytest.raises(StateError):profile.stage(consumer,producer,out,'/other/bin')
    with pytest.raises(StateError):profile.stage(consumer,producer,tmp_path/'bad','/bin\nExecStart=/bad')

def test_staged_profile_boot_graph(tmp_path):
    import subprocess
    consumer=Path(os.environ['HOST_DISCOVER_SOURCE']);producer=Path(__file__).resolve().parents[1]
    out=tmp_path/'overlay';profile.stage(consumer,producer,out)
    units=out/'etc/systemd/system'
    (units/'state.mount').write_text((producer/'examples/systemd/state.mount.in').read_text().replace('@STATE_PARTUUID@','11111111-1111-4111-8111-111111111111'))
    targets={'sysinit.target':'','sockets.target':'Before=basic.target\n',
        'basic.target':'Requires=sysinit.target sockets.target\nAfter=sysinit.target sockets.target\n',
        'multi-user.target':'Requires=basic.target\nAfter=basic.target\nWants=host-discover-beacon.service\n',
        'shutdown.target':'','local-fs.target':'','local-fs-pre.target':'','network-online.target':''}
    for name,body in targets.items():(units/name).write_text('[Unit]\nDefaultDependencies=no\n'+body)
    for name in ('host-install','host-discover','host-discover-supervisor'):
        exe=out/'usr/bin'/name;exe.parent.mkdir(parents=True,exist_ok=True);exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o755)
    (out/'etc/passwd').write_text('root:x:0:0::/root:/bin/sh\nhost-discover:x:970:970::/state/host-discover:/usr/sbin/nologin\n')
    (out/'etc/group').write_text('root:x:0:\nhost-discover:x:970:\narchive-consumers:x:972:\nhost-control:x:973:\n')
    command=['systemd-analyze','verify','--generators=no','--man=no','--root='+str(out),'multi-user.target']
    p=subprocess.run(command,capture_output=True,text=True)
    assert p.returncode==0 and 'ordering cycle' not in p.stderr.lower(),p.stderr
    socket=units/'host-discover-supervisor.socket';socket.chmod(0o644);socket.write_text(socket.read_text().replace('DefaultDependencies=no\n',''))
    p=subprocess.run(command,capture_output=True,text=True)
    assert 'ordering cycle' in p.stderr.lower(),p.stderr
