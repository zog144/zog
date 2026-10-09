"""Root-owned identity authorization/consumption; private key work runs as UID 970."""
from contextlib import contextmanager
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from .state_contract import PROFILE, StateError, canonical, decode, digest, fields, header, require, sha
from .state_inspect import directory, inspect_live, metadata
from .state_io import ensure_directory, lock, publish, raw
from .state_provision import prepared_layout


def authorization(bundle):
    b = bundle['bootstrap']
    return dict(schema=1, kind='zog-identity-initialization',
                authorization_id=b['initialization']['authorization_id'], installation_id=b['installation_id'],
                state_volume_id=b['state']['state_volume_id'], identity_directory=b['state']['identity_directory'],
                account_profile=PROFILE, expected_fingerprint=None)


def receipt_valid(receipt, auth):
    header(receipt, 'zog-identity-receipt', 'authorization_sha256 authorization_id installation_id state_volume_id fingerprint')
    # host-identify's format includes a final newline; host-install record
    # digests deliberately retain their already-published no-newline convention.
    expected = hashlib.sha256(canonical(auth) + b'\n').hexdigest()
    require(receipt['authorization_sha256'] == expected and
            all(receipt[k] == auth[k] for k in ('authorization_id', 'installation_id', 'state_volume_id')),
            'receipt-mismatch', 'receipt is not for this authorization')
    sha(receipt['fingerprint'])
    return receipt


@contextmanager
def operations(c):
    installer = os.open('host-install', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=c.fd)
    try:
        metadata(installer, 0, 0, 0o755)
        fd = os.open('operations', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=installer)
        try:
            metadata(fd, 0, 0, 0o700)
            require(os.fstat(fd).st_dev == os.fstat(c.fd).st_dev, 'nested-mount', 'operations')
            yield fd
        finally: os.close(fd)
    finally: os.close(installer)


def held(fd):
    names = set(os.listdir(fd))
    require(not names & {'recovery-hold.json', '.pending.recovery-hold.json'}, 'recovery-required', 'protected recovery hold exists')


def hold(fd, reason):
    value = canonical(dict(schema=1, kind='zog-identity-recovery-hold', reason=reason))
    # Never overwrite the first diagnostic or clear a hold implicitly.
    if raw(fd, 'recovery-hold.json') is None:
        publish(fd, 'recovery-hold.json', value)


def transaction(c):
    return dict(schema=1, kind='zog-host-identity-operation', authorization=authorization(c.bundle))


def authorize(c, requested_id, checkpoint=lambda _: None):
    """Explicit installer/operator action, never called automatically at boot."""
    b = c.bundle['bootstrap']
    require(b['mode'] == 'fresh' and b['initialization']['expected_fingerprint'] is None and
            requested_id == b['initialization']['authorization_id'], 'initialization-not-authorized', 'explicit matching fresh transaction required')
    c.recheck()
    prepared_layout(c)
    with operations(c) as fd, lock(fd):
        held(fd)
        value = canonical(transaction(c))
        existing = raw(fd, 'identity-authorization.json', links=(1, 2))
        if existing is not None:
            require(existing == value, 'authorization-conflict', 'another identity transaction exists')
        else:
            require(raw(fd, 'identity-consumed.json', links=(1, 2)) is None, 'recovery-required', 'consumption without authorization')
            home = os.open('host-discover', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=c.fd)
            try:
                try: identity = os.open('identity', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
                except FileNotFoundError: identity = None
                if identity is not None:
                    try: require(not os.listdir(identity), 'identity-already-present', 'refusing adoption or regeneration')
                    finally: os.close(identity)
            finally: os.close(home)
        c.recheck()
        publish(fd, 'identity-authorization.json', value, checkpoint=checkpoint)
        completion = consumed(fd, authorization(c.bundle))
        c.recheck()
    return dict(status='identity-transaction-authorized' if completion is None else 'identity-consumption-record-present', authorization_id=requested_id, control_authorized=False)


def consumed(fd, auth):
    value = raw(fd, 'identity-consumed.json', links=(1, 2))
    if value is None: return None
    record = decode(value)
    header(record, 'zog-host-identity-consumption', 'receipt')
    receipt_valid(record['receipt'], auth)
    return record


def coordinate(c, worker, checkpoint=lambda _: None, *, service_ids=(970, 970)):
    """Trusted helper; worker must probe/recheck and execute as the service UID.

No consumed transaction ever calls prepare, even if its key has disappeared.
The worker returns public metadata only; this process never handles key bytes.
"""
    c.recheck()
    prepared_layout(c)
    b = c.bundle['bootstrap']
    require(b['mode'] in ('fresh', 'existing'), 'recovery-required', 'migration/recovery mode cannot initialize')
    with operations(c) as fd, lock(fd):
        held(fd)
        expected = transaction(c)
        auth = expected['authorization']
        existing = raw(fd, 'identity-authorization.json', links=(1, 2))
        require(existing == canonical(expected), 'initialization-not-authorized', 'root-owned matching transaction required')
        publish(fd, 'identity-authorization.json', existing, checkpoint=checkpoint)
        completion = consumed(fd, auth)
        if completion is None:
            require(b['mode'] == 'fresh' and b['initialization']['expected_fingerprint'] is None,
                    'initialization-not-authorized', 'only explicit fresh transactions can prepare')
        try:
            c.recheck()
            if completion is None:
                home = os.open('host-discover', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=c.fd)
                try:
                    identity = ensure_directory(home, 'identity', *service_ids, 0o700, checkpoint)
                    os.close(identity)
                finally: os.close(home)
                result = worker('prepare', auth, None)
                receipt_valid(result, auth)
                checkpoint('identity-prepared')
                completion = dict(schema=1, kind='zog-host-identity-consumption', receipt=result)
            else:
                # Validate loaded identity before re-establishing a consumption barrier.
                result = worker('load-existing', auth, completion['receipt'])
                require(result == completion['receipt'], 'receipt-mismatch', 'loaded identity receipt mismatch')
            wanted = b['initialization']['expected_fingerprint']
            require(wanted is None or completion['receipt']['fingerprint'] == wanted, 'identity-mismatch', 'expected fingerprint mismatch')
            c.recheck()
            publish(fd, 'identity-consumed.json', canonical(completion), checkpoint=checkpoint)
            checkpoint('identity-consumed')
            # The independently consumed receipt must successfully load the same key.
            result = worker('load-existing', auth, completion['receipt'])
            require(result == completion['receipt'], 'receipt-mismatch', 'post-consumption load mismatch')
            c.recheck()
        except (OSError, StateError, subprocess.SubprocessError, ValueError):
            try: hold(fd, 'initialization-or-storage-failure')
            except (OSError, StateError): pass  # Original failure still propagates.
            raise
        return dict(status='identity-consumed-and-verified', receipt=completion['receipt'],
                    control_authorized=False, transport_enabled=False)


def worker_process(action, auth, receipt):
    """Use subprocess's credential setup, not a shell or root key loading."""
    request = dict(action=action, authorization=auth, receipt=receipt)
    result = subprocess.run([sys.executable, '-m', 'zog.host_install.identity_worker'], input=canonical(request),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                            user=970, group=970, extra_groups=[972, 973], close_fds=True,
                            cwd='/', env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
    require(result.returncode == 0, 'identity-worker-failed', 'service-account worker failed; recovery required')
    return decode(result.stdout)


def authorize_live(requested_id):
    require(os.geteuid() == 0, 'root-required', 'installer authorization requires root')
    with inspect_live() as c: return authorize(c, requested_id)


def clear_projection(fd):
    names = ('identity-consumed.json', '.pending.identity-consumed.json')
    found = []
    for name in names:
        if raw(fd, name, mode=0o444, links=(1, 2)) is not None: found.append(name)
    for name in found:
        stat = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.st_nlink == 2:
            require(len(found) == 2 and os.stat(found[0], dir_fd=fd, follow_symlinks=False).st_ino ==
                    os.stat(found[1], dir_fd=fd, follow_symlinks=False).st_ino,
                    'projection-conflict', 'unrecognized runtime hardlink')
    for name in found: os.unlink(name, dir_fd=fd)
    os.fsync(fd)


def publish_projection(fd, bundle, result, boot_id):
    from .state_contract import identifier
    identifier(boot_id)
    value = dict(schema=1, kind='zog-host-identity-projection', boot_id=boot_id,
                 bootstrap_sha256=digest(bundle['bootstrap']), marker_sha256=digest(bundle['marker']),
                 receipt=result['receipt'], control_authorized=False, transport_enabled=False)
    receipt_valid(value['receipt'], authorization(bundle))
    publish(fd, 'identity-consumed.json', canonical(value), 0o444)
    return value


def initialize_live():
    require(os.geteuid() == 0, 'root-required', 'installer coordinator requires root')
    run = directory('/run')
    fd = None
    try:
        metadata(run, 0, 0, 0o755)
        fd = ensure_directory(run, 'host-install', 0, 0, 0o755)
        with lock(fd):
            # No stale same-boot projection survives a failed new coordinator run.
            clear_projection(fd)
            with inspect_live() as c:
                result = coordinate(c, worker_process)
                publish_projection(fd, c.bundle, result, Path('/proc/sys/kernel/random/boot_id').read_text().strip())
                c.recheck()
            return result
    except BaseException:
        if fd is not None:
            try: clear_projection(fd)
            except (OSError, StateError): pass
        raise
    finally:
        if fd is not None: os.close(fd)
        os.close(run)
