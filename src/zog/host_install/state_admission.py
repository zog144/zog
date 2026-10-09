"""Read-only privileged ledger observation over a local authenticated connection.

An observation permits checking an existing identity, never network/control use.
The consumer must retain/recheck its own STATE and use host-identify load-existing.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import secrets
import socket
import stat
import struct

from .state_contract import StateError, canonical, decode, fields, header, require, sha
from .state_contract import digest
from .state_initialize import authorization, consumed, operations, receipt_valid, transaction
from .state_inspect import directory, inspect_live, metadata
from .state_io import raw
from .state_provision import prepared_layout

SOCKET = '/run/host-install/admission.sock'
TIMEOUT = 5
REQUEST_LIMIT = 4096
RESPONSE_LIMIT = 65536


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def bindings(context):
    s = os.fstat(context.fd)
    return dict(boot_id=boot_id(), bootstrap_sha256=digest(context.bundle['bootstrap']),
                marker_sha256=digest(context.bundle['marker']),
                state_device=f'{os.major(s.st_dev)}:{os.minor(s.st_dev)}', state_inode=s.st_ino)


@contextmanager
def read_lock(fd):
    # Never create a ledger or repair its lock in response to an admission query.
    handle = os.open('.host-install.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        metadata(handle, 0, 0, 0o600, False)
        require(os.fstat(handle).st_dev == os.fstat(fd).st_dev, 'nested-mount', 'operation lock')
        try: fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateError('operation-busy', 'installer operation in progress') from exc
        yield
    finally: os.close(handle)


def observe(context):
    """Trusted internal context; no key, directory, receipt or hold writes."""
    context.recheck()
    prepared_layout(context)
    with operations(context) as fd, read_lock(fd):
        names = set(os.listdir(fd))
        held = bool(names & {'recovery-hold.json', '.pending.recovery-hold.json'})
        receipt = None
        if not held:
            require(context.bundle['bootstrap']['mode'] in ('fresh', 'existing'),
                    'recovery-required', 'migration/recovery requires reconciliation')
            require(not names & {'.pending.identity-authorization.json', '.pending.identity-consumed.json'},
                    'operation-incomplete', 'coordinator must finish publication')
            require(raw(fd, 'identity-authorization.json') == canonical(transaction(context)),
                    'initialization-not-authorized', 'matching protected authorization required')
            record = consumed(fd, authorization(context.bundle))
            require(record is not None, 'consumption-unavailable', 'completed consumption required')
            # Admission accepts only fully reconciled single-link publications.
            require(os.stat('identity-consumed.json', dir_fd=fd, follow_symlinks=False).st_nlink == 1,
                    'operation-incomplete', 'consumption publication incomplete')
            receipt = record['receipt']
        context.recheck()
        return dict(status='recovery-required' if held else 'consumption-observed',
                    recovery_hold=held, receipt=receipt, bindings=bindings(context),
                    identity_action='block' if held else 'verify-existing',
                    control_authorized=False, transport_enabled=False)


def peer_uid(connection):
    return struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]


def receive(connection, limit):
    data = bytearray()
    while True:
        chunk = connection.recv(min(4096, limit + 1 - len(data)))
        if not chunk: return decode(bytes(data))
        data.extend(chunk)
        require(len(data) <= limit, 'message-size', 'local protocol limit exceeded')


def request_valid(request):
    header(request, 'zog-host-admission-request', 'nonce')
    sha(request['nonce'])
    return request['nonce']


def serve_connection(connection):
    """One request on a systemd-accepted socket; caller cannot select paths/actions."""
    require(os.geteuid() == 0, 'root-required', 'privileged observation requires root')
    connection.settimeout(TIMEOUT)
    require(peer_uid(connection) == 970, 'admission-peer', 'host-discover UID required')
    nonce = request_valid(receive(connection, REQUEST_LIMIT))
    response = dict(schema=1, kind='zog-host-admission-response', nonce=nonce)
    try:
        with inspect_live() as context:
            observation = observe(context)
        response.update(ok=True, observation=observation)
    except (StateError, OSError, ValueError) as exc:
        response.update(ok=False, code=exc.code if isinstance(exc, StateError) else 'admission-unavailable')
    connection.sendall(canonical(response))


def serve_stdin():
    # StandardInput=socket, Accept=yes; no listener creation or unlink operation.
    with socket.fromfd(0, socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        require(connection.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN) == socket.AF_UNIX and
                connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM,
                'admission-socket', 'local stream socket required')
        serve_connection(connection)
    return {'status': 'observation-served', 'control_authorized': False}


def validate_response(response, nonce, context):
    """Internal wire validation; a saved response is NOT an authenticated adapter."""
    require(type(response) is dict and type(response.get('ok')) is bool,
            'admission-response', 'invalid response')
    header(response, 'zog-host-admission-response', 'nonce ok ' + ('observation' if response['ok'] else 'code'))
    require(response['nonce'] == nonce, 'admission-nonce', 'response is not for this request')
    if not response['ok']:
        raise StateError('admission-refused', 'privileged observation refused')
    o = response['observation']
    fields(o, 'status recovery_hold receipt bindings identity_action control_authorized transport_enabled')
    require(type(o['recovery_hold']) is bool and o['control_authorized'] is False and o['transport_enabled'] is False,
            'admission-response', 'invalid capability claim')
    context.recheck()
    require(o['bindings'] == bindings(context), 'admission-binding', 'boot/configuration/STATE mismatch')
    if o['recovery_hold']:
        require(o['status'] == 'recovery-required' and o['identity_action'] == 'block' and o['receipt'] is None,
                'admission-response', 'invalid hold result')
    else:
        require(o['status'] == 'consumption-observed' and o['identity_action'] == 'verify-existing',
                'admission-response', 'invalid consumption result')
        receipt_valid(o['receipt'], authorization(context.bundle))
    return o


def request_live(context):
    """Consumer API: fresh peer-authenticated observation, never cached/file input.

Call after consumer inspection/probe, before anchored identity loading. Recheck
again afterward. This observation is instantaneous; it is not a health lease.
"""
    require(os.geteuid() == 970 and os.getegid() == 970, 'admission-account', 'host-discover account required')
    context.recheck()
    parent = directory('/run/host-install')
    try:
        metadata(parent, 0, 0, 0o755)
        s = os.stat('admission.sock', dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISSOCK(s.st_mode) and (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) == (0, 970, 0o660),
                'admission-socket', 'unexpected socket ownership/mode')
        nonce = secrets.token_hex(32)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(TIMEOUT)
            connection.connect(f'/proc/self/fd/{parent}/admission.sock')
            require(peer_uid(connection) == 0, 'admission-peer', 'root server required')
            connection.sendall(canonical(dict(schema=1, kind='zog-host-admission-request', nonce=nonce)))
            connection.shutdown(socket.SHUT_WR)
            response = receive(connection, RESPONSE_LIMIT)
        return validate_response(response, nonce, context)
    finally: os.close(parent)


def serve_listener(handler=None):
    """Serve the one systemd-passed Unix listener until ordered service shutdown.

    Keeping the process alive lets the beacon finish without starting a new
    service inside an already queued shutdown transaction. Wire protocol is
    unchanged: one bounded request per peer-authenticated connection.
    """
    import signal
    require(os.geteuid() == 0, 'root-required', 'privileged listener requires root')
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1',
            'admission-activation', 'Exactly one systemd listener required')
    handler = handler or serve_connection
    def expired(*_): raise TimeoutError('local request deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    try:
        with socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            require(listener.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN) == socket.AF_UNIX and
                    listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM and
                    listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1,
                    'admission-activation', 'Local listening stream required')
            os.close(3)
            while True:
                connection, _ = listener.accept()
                with connection:
                    signal.setitimer(signal.ITIMER_REAL, 20)
                    try: handler(connection)
                    except (StateError, OSError, ValueError, KeyError, TypeError):
                        pass  # Refuse this connection; no protocol/state repair.
                    finally: signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
