import concurrent.futures
import copy
import json
import os
from pathlib import Path
import stat
import uuid
import pytest
from zog.host_identify import initialization as init, storage
from zog.host_identify.signatures import fingerprint


@pytest.fixture
def setup(tmp_path):
    root=tmp_path/'identity';root.mkdir(mode=0o700)
    authorization={'schema':1,'kind':'zog-identity-initialization','authorization_id':str(uuid.uuid4()),
        'installation_id':str(uuid.uuid4()),'state_volume_id':str(uuid.uuid4()),
        'identity_directory':str(root),'account_profile':'zog-host-accounts-v1','expected_fingerprint':None}
    return root,authorization


def test_complete_retry_and_read_only_admission(setup):
    root,a=setup;r=init.prepare(root,a)
    before={p.name:p.read_bytes() for p in root.iterdir()}
    assert init.prepare(root,a)==r
    key=init.load_existing(root,r)
    assert fingerprint(key.public_key())==r['fingerprint']
    assert before=={p.name:p.read_bytes() for p in root.iterdir()}
    for p in root.iterdir():assert stat.S_IMODE(p.stat().st_mode)==0o600
    assert b'PRIVATE' not in init.encode(r)


def test_missing_key_never_regenerated(setup):
    root,a=setup;r=init.prepare(root,a);(root/'identity.pem').unlink()
    with pytest.raises(init.IdentityStateError):init.load_existing(root,r)
    assert not (root/'identity.pem').exists()
    with pytest.raises(PermissionError):storage.load_key(root)


def test_readonly_legacy_loader_does_not_create(setup):
    root,_=setup
    with pytest.raises(init.IdentityStateError):storage.load_existing_key(root)
    assert list(root.iterdir())==[]
    original=storage.load_key(root)
    assert fingerprint(storage.load_existing_key(root).public_key())==fingerprint(original.public_key())


@pytest.mark.parametrize('field',['authorization_id','installation_id','state_volume_id'])
def test_different_transaction_cannot_replace(setup,field):
    root,a=setup;init.prepare(root,a);old=(root/'identity.pem').read_bytes()
    changed=dict(a);changed[field]=str(uuid.uuid4())
    with pytest.raises(init.IdentityStateError):init.prepare(root,changed)
    assert (root/'identity.pem').read_bytes()==old


@pytest.mark.parametrize('name',['initialization.json','prepared-key.pem','receipt.json','identity.pem'])
def test_corruption_is_not_repaired_by_replacement(setup,name):
    root,a=setup;r=init.prepare(root,a);(root/name).write_bytes(b'corrupt')
    with pytest.raises((ValueError,TypeError)):init.prepare(root,a)
    with pytest.raises((ValueError,TypeError)):init.load_existing(root,r)
    assert (root/name).read_bytes()==b'corrupt'


def test_consumption_must_match_exact_public_receipt(setup):
    root,a=setup;r=init.prepare(root,a)
    for bad in [None,{},dict(r,fingerprint='other'),dict(r,installation_id=str(uuid.uuid4()))]:
        with pytest.raises(init.IdentityStateError):init.load_existing(root,bad)


@pytest.mark.parametrize('stop_after',['initialization.json','prepared-key.pem','receipt.json','publish-key.tmp'])
def test_interrupted_initialization(setup,monkeypatch,stop_after):
    root,a=setup;original=init.create
    def interrupted(fd,name,data):
        original(fd,name,data)
        if name==stop_after:raise OSError('simulated interruption')
    monkeypatch.setattr(init,'create',interrupted)
    with pytest.raises(OSError):init.prepare(root,a)
    staged=(root/'prepared-key.pem').read_bytes() if (root/'prepared-key.pem').exists() else None
    monkeypatch.setattr(init,'create',original)
    if staged is None:
        with pytest.raises(init.IdentityStateError):init.prepare(root,a)
        assert not (root/'identity.pem').exists()
    else:
        r=init.prepare(root,a)
        assert (root/'identity.pem').read_bytes()==staged
        init.load_existing(root,r)


def test_crash_between_link_and_unlink_resumes_same_inode(setup,monkeypatch):
    root,a=setup;unlink=os.unlink
    def fail(name,*args,**kwargs):
        if name=='publish-key.tmp':raise OSError('interrupted unlink')
        return unlink(name,*args,**kwargs)
    monkeypatch.setattr(os,'unlink',fail)
    with pytest.raises(OSError):init.prepare(root,a)
    assert (root/'identity.pem').stat().st_nlink==2
    previous=(root/'identity.pem').read_bytes()
    monkeypatch.setattr(os,'unlink',unlink)
    r=init.prepare(root,a)
    assert (root/'identity.pem').read_bytes()==previous
    assert (root/'identity.pem').stat().st_nlink==1
    init.load_existing(root,r)


def test_concurrent_initialization_preserves_lock_inode(setup):
    root,a=setup
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:init.prepare(root,a),range(12)))
    assert all(r==results[0] for r in results)
    inode=(root/'key.lock').stat().st_ino
    init.prepare(root,a)
    assert (root/'key.lock').stat().st_ino==inode


@pytest.mark.parametrize('name',['prepared-key.pem','identity.pem','receipt.json','key.lock'])
def test_symlink_rejected(setup,name):
    root,a=setup;(root/name).symlink_to(root/'missing')
    with pytest.raises((OSError,ValueError)):init.prepare(root,a)
    assert not (root/'missing').exists()


def test_foreign_key_and_unsafe_mode(setup):
    root,a=setup;storage.load_key(root)
    with pytest.raises(init.IdentityStateError):init.prepare(root,a)
    (root/'identity.pem').chmod(0o644)
    with pytest.raises(PermissionError):storage.load_existing_key(root)


def test_fsync_failure_never_admits(setup,monkeypatch):
    root,a=setup
    monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('fsync failed')))
    with pytest.raises(OSError):init.prepare(root,a)
    assert not (root/'identity.pem').exists()


def test_symlink_ancestor_and_wrong_schema(setup,tmp_path):
    root,a=setup;link=tmp_path/'linked';link.symlink_to(root,target_is_directory=True)
    with pytest.raises(OSError):init.prepare(link,dict(a,identity_directory=str(link)))
    with pytest.raises(init.IdentityStateError):init.prepare(root,dict(a,schema=2))
    assert list(root.iterdir())==[]


def test_legacy_read_loader_cannot_bypass_managed_receipt(setup):
    root,a=setup;init.prepare(root,a)
    with pytest.raises(PermissionError):storage.load_existing_key(root)


def test_prepared_identity_survives_new_process(setup):
    import subprocess,sys
    root,a=setup;r=init.prepare(root,a)
    result=subprocess.run([sys.executable,'-c',
        'import json,sys;from zog.host_identify.initialization import prepare;print(json.dumps(prepare(sys.argv[1],json.loads(sys.argv[2]))))',str(root),json.dumps(a)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==r
    assert 'PRIVATE' not in result.stdout+result.stderr


def test_no_generation_after_transaction_without_stage(setup):
    root,a=setup
    (root/'initialization.json').write_bytes(init.encode(a));(root/'initialization.json').chmod(0o600)
    with pytest.raises(init.IdentityStateError):init.prepare(root,a)
    assert not (root/'identity.pem').exists()


def test_conflicting_candidate_preserved(setup):
    root,a=setup;init.prepare(root,a)
    (root/'unexpected.pem').write_bytes(b'candidate')
    with pytest.raises(init.IdentityStateError):init.prepare(root,a)
    assert (root/'unexpected.pem').read_bytes()==b'candidate'


def test_broken_transaction_marker_cannot_use_legacy_loader(setup):
    root,_=setup;(root/'initialization.json').symlink_to(root/'absent')
    for loader in (storage.load_key,storage.load_existing_key):
        with pytest.raises(PermissionError):loader(root)
    assert not (root/'identity.pem').exists()


def test_legacy_creation_rechecks_after_waiting_for_initializer(setup,monkeypatch):
    root,a=setup;flock=storage.fcntl.flock
    def interleaved(fd,operation):
        flock(fd,operation)
        # Simulate a managed initializer which acquired/released this inode
        # after the legacy precheck but before its lock acquisition.
        (root/'initialization.json').write_bytes(init.encode(a))
        (root/'initialization.json').chmod(0o600)
    monkeypatch.setattr(storage.fcntl,'flock',interleaved)
    with pytest.raises(PermissionError):storage.load_key(root)
    assert not (root/'identity.pem').exists()


def test_existing_loader_rechecks_under_shared_lock(setup,monkeypatch):
    root,a=setup;storage.load_key(root);flock=storage.fcntl.flock
    def interleaved(fd,operation):
        flock(fd,operation)
        (root/'initialization.json').write_bytes(init.encode(a))
        (root/'initialization.json').chmod(0o600)
    monkeypatch.setattr(storage.fcntl,'flock',interleaved)
    with pytest.raises(PermissionError):storage.load_existing_key(root)


def test_descriptor_load_does_not_reopen_replaced_path(setup):
    root,a=setup;receipt=init.prepare(root,a)
    with init.directory_fd(root) as fd:
        moved=root.with_name('retained');root.rename(moved)
        root.mkdir(mode=0o700)
        other=init.prepare(root,a)
        assert other['fingerprint']!=receipt['fingerprint']
        key=init.load_existing_fd(fd,str(root),receipt)
        assert fingerprint(key.public_key())==receipt['fingerprint']
        os.fstat(fd)  # caller still owns descriptor


def test_descriptor_load_requires_consumption_before_private_read(setup,monkeypatch):
    root,a=setup;init.prepare(root,a)
    with init.directory_fd(root) as fd:
        monkeypatch.setattr(init,'read',lambda *a:pytest.fail('must not read key'))
        with pytest.raises(init.IdentityStateError):init.load_existing_fd(fd,str(root),None)


def test_descriptor_load_rejects_orphan_publication(setup):
    root,a=setup;receipt=init.prepare(root,a)
    (root/'publish-key.tmp').write_bytes(b'partial')
    with init.directory_fd(root) as fd:
        with pytest.raises(init.IdentityStateError):init.load_existing_fd(fd,str(root),receipt)
