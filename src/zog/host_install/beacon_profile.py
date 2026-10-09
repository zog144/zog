"""Explicit managed-beacon provisioning and offline systemd composition."""
import hashlib
import os
import re
from importlib.resources import files as resource_files
from pathlib import Path
from .state_contract import canonical, require
from .state_inspect import directory, inspect_live, metadata
from .state_initialize import operations
from .state_io import ensure_directory, lock, publish, raw

# Reviewed consumer templates; changes require interface review, not silent adoption.
CONSUMER_COMMIT = '9075748a98b1c8f679113544cdcd5c8bd9d84958'
CONSUMER_HASHES = {'host-discover-supervisor.socket': 'e2e07d9780f3e24fb32438779806d60d1948130970ac45938184cc2a05cd9db6', 'host-discover-supervisor@.service': '7e559dd696609c4787c9a2711165aa32c1be7ec011636dcd33d837114eecc22a', 'host-discover-beacon.service': '5c82b531eaf548074a2480354eb208496634ffa6b916320632311b71da9fb430'}


def prepare(context, volume, supervisor):
    require(os.geteuid() == 0, 'root-required', 'Explicit root provisioning required')
    require(volume == context.bundle['bootstrap']['state']['state_volume_id'], 'volume-confirmation', 'Exact STATE UUID required')
    # Observe before locking: the producer itself acquires the operations lock.
    observation = supervisor.wire.observe(context)
    require(not observation['recovery_hold'], 'recovery-required', 'Installer hold')
    value = canonical(dict(schema=1, kind='zog-beacon-provisioning', binding=supervisor.fixed(context, observation)))
    with operations(context) as fd, lock(fd, 'beacon-provision.lock'):
        intent = raw(fd, 'beacon-intent.json', links=(1, 2))
        completed = raw(fd, 'beacon-prepared.json', links=(1, 2))
        if completed is not None:
            require(intent == value and completed == value, 'beacon-provision-conflict', 'Provisioning binding changed')
            # Never prepare again once consumed, even if the ledger is missing.
            with supervisor.ledger(context) as (_, ledger):
                require(ledger['binding'] == supervisor.fixed(context, observation), 'beacon-provision-conflict', 'Ledger binding changed')
            publish(fd, 'beacon-prepared.json', value)
        else:
            # An absent receipt cannot adopt an already used journal/ledger.
            with supervisor.stopped_consumer(context):
                home = os.open('host-discover', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=context.fd)
                try:
                    control = os.open('control', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
                    try:
                        require(not os.listdir(control), 'beacon-existing-state', 'Initial provisioning cannot adopt an existing journal')
                    finally: os.close(control)
                finally: os.close(home)
                publish(fd, 'beacon-intent.json', value)
                supervisor.prepare(context, volume)
                publish(fd, 'beacon-prepared.json', value)
        context.recheck()
    return dict(status='beacon-profile-prepared', transport_enabled=False, control_authorized=False)


def prepare_live(volume):
    from zog.host_discover import supervisor
    with inspect_live() as context:
        return prepare(context, volume, supervisor)


def stage(discover_source, producer_source, output, executable_directory='/usr/bin'):
    """Root-owned resumable offline overlay; never enable services or touch STATE."""
    require(os.geteuid() == 0, 'root-required', 'Root-owned composition required')
    require(re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+', executable_directory) is not None,
            'executable-directory', 'Absolute simple directory required')
    files = {}
    for name, expected in CONSUMER_HASHES.items():
        data = (Path(discover_source)/'deployment'/name).read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected, 'consumer-template-changed', name)
        files[name] = data.decode()
    packaged = resource_files(__package__).joinpath('systemd')
    for name in ('host-install-admission.socket','host-install-admission@.service',
                 'host-install-identity.service','host-install-prepare.service'):
        data = packaged.joinpath(name).read_text()
        if producer_source is not None:
            checkout = (Path(producer_source)/'examples/systemd'/name).read_text()
            require(checkout == data, 'producer-template-changed', name)
        files[name] = data
    files['host-discover-beacon.service'] = files['host-discover-beacon.service'].replace('[Unit]\n',
        '[Unit]\nConflicts=host-discover.service host-discover-managed.service\nAfter=host-discover.service host-discover-managed.service\n', 1)
    # Keep both request processes alive until beacon finish during shutdown.
    # Accept=yes handlers cannot reliably be newly activated once stop jobs exist.
    for prefix, command in (('host-install-admission', 'state-admission-listen'),
                            ('host-discover-supervisor', 'serve-listen')):
        socket_name = prefix + '.socket'
        files[socket_name] = '\n'.join(line for line in files[socket_name].splitlines()
            if not line.startswith(('MaxConnections=', 'MaxConnectionsPerSource='))) + '\n'
        files[socket_name] = files[socket_name].replace('Accept=yes', 'Accept=no\nBacklog=8')
        service = files.pop(prefix + '@.service')
        service = '\n'.join(line for line in service.splitlines()
            if not line.startswith(('RuntimeMaxSec=', 'StandardInput='))) + '\n'
        service = service.replace('StandardOutput=socket', 'StandardOutput=journal')
        service = service.replace('state-admission-serve', command) if prefix == 'host-install-admission' else service.replace('supervisor serve', 'supervisor '+command)
        service = service.replace('[Service]\n', '[Service]\nSockets='+socket_name+'\n')
        files[prefix+'.service'] = service
    files['host-discover-beacon.service'] = files['host-discover-beacon.service'].replace('[Unit]\n',
        '[Unit]\nRequires=host-install-admission.service host-discover-supervisor.service\nAfter=host-install-admission.service host-discover-supervisor.service\n', 1)
    # SIGTERM must reach the beacon first: a cgroup-wide TERM can kill its
    # in-flight lsblk admission check before it can finish the protected run.
    # mixed retains cgroup-wide SIGKILL if graceful shutdown times out.
    files['host-discover-beacon.service'] = '\n'.join(
        line for line in files['host-discover-beacon.service'].splitlines()
        if not line.startswith(('KillMode=', 'TimeoutStopSec='))) + '\n'
    files['host-discover-beacon.service'] = files['host-discover-beacon.service'].replace(
        '[Service]\n', '[Service]\nKillMode=mixed\nTimeoutStopSec=90s\n', 1)
    files = {name: data.replace('/usr/bin/host-', executable_directory+'/host-').encode() for name,data in files.items()}
    manifest = canonical(dict(schema=1, kind='zog-managed-beacon-profile', consumer_template_commit=CONSUMER_COMMIT,
        executable_directory=executable_directory, files={n:hashlib.sha256(d).hexdigest() for n,d in files.items()},
        disabled_profiles=['host-discover.service','host-discover-managed.service'],
        enable=['host-discover-beacon.service'], supervisor_preparation='explicit-only'))
    output = Path(output).absolute()
    parent = directory(str(output.parent))
    root = None
    try:
        root = ensure_directory(parent, output.name, 0, 0, 0o700)
        with lock(root):
            require(set(os.listdir(root)) <= {'.host-install.lock','profile.json','.pending.profile.json','etc','.pending-dir.etc'},
                    'profile-conflict', 'Unexpected overlay contents')
            # Intent is immutable; files resume only with identical bytes.
            publish(root, 'profile.json', manifest, 0o444)
            opened = []; current = root
            try:
                for name in ('etc','systemd','system'):
                    current = ensure_directory(current,name,0,0,0o755); opened.append(current)
                for name,data in files.items(): publish(current,name,data,0o444)
            finally:
                for fd in reversed(opened): os.close(fd)
        return dict(status='beacon-profile-staged', output=str(output), services_enabled=False, state_modified=False)
    finally:
        if root is not None: os.close(root)
        os.close(parent)
