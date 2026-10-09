"""Offline record overlays and explicit, verified live STATE preparation."""
import hashlib
import os
from pathlib import Path
from .state_contract import CONFIG, StateError, canonical, digest, host_slots, require, validate
from .state_inspect import VerifiedState, _mount, accounts_match, directory, load_configuration, metadata
from .state_io import ensure_directory, lock, publish, raw


def transition(bundle, previous):
    validate(bundle)
    b = bundle['bootstrap']
    operation = bundle['installation']['operation']
    require(operation in ('fresh', 'upgrade', 'reinstall'), 'transition-not-supported', 'migration/recovery need a dedicated operation')
    if previous is None:
        require(operation == 'fresh' and b['mode'] == 'fresh' and b['initialization']['expected_fingerprint'] is None,
                'previous-records-required', 'only fresh publication may omit previous records')
        return
    validate(previous)
    require(operation in ('upgrade', 'reinstall'), 'transition-not-supported', 'fresh cannot replace an installation')
    old = previous['bootstrap']
    for field in ('installation_id', 'state', 'initialization', 'registries', 'control_authority'):
        require(canonical(b[field]) == canonical(old[field]), 'transition-conflict', field)
    require(b['mode'] in ('existing', old['mode']) and b['configuration_revision'] > old['configuration_revision'],
            'transition-conflict', 'mode/revision')
    require(bundle['installation']['record_id'] != previous['installation']['record_id'], 'transition-conflict', 'record ID must change')
    old_install = previous['installation']
    new_install = bundle['installation']
    selected = new_install['installer_recorded']['expected_slot']
    if 'host_slots' in old_install['installer_recorded']:
        require('host_slots' in new_install['installer_recorded'],
                'transition-conflict', 'known slot provenance cannot be dropped')
    if old_install['installer_recorded']['expected_slot'] != selected:
        require('host_slots' in new_install['installer_recorded'],
                'transition-conflict', 'slot switch must preserve both slot identities')
    old_slots, new_slots = host_slots(old_install), host_slots(new_install)
    for slot in ('HOST-A', 'HOST-B'):
        if slot != selected:
            require(canonical(new_slots[slot]) == canonical(old_slots[slot]),
                    'transition-conflict', 'inactive host slot provenance changed')


def stage_overlay(bundle, output, previous=None, ca_bytes=None, checkpoint=lambda _: None):
    """Create an offline overlay, never select a slot or modify a live /etc."""
    require(os.geteuid() == 0, 'root-required', 'offline ownership publication requires root')
    transition(bundle, previous)
    ca_bytes = ca_bytes or {}
    expected = {r['registry_id']: r['ca'] for r in bundle['bootstrap']['registries'] if r['ca'] is not None}
    require(set(ca_bytes) == set(expected), 'ca-set', 'provide exactly the referenced CA certificates')
    for name, value in ca_bytes.items():
        require(type(value) is bytes and len(value) <= 65536 and hashlib.sha256(value).hexdigest() == expected[name]['sha256'], 'ca-digest', name)
    output = Path(output).absolute()
    require(output.name not in ('', '.', '..'), 'unsafe-path', 'new overlay directory required')
    parent = directory(str(output.parent))
    root = None
    try:
        # Existing unrelated directories are never adopted as an overlay.
        try:
            os.mkdir(output.name, 0o700, dir_fd=parent); os.fsync(parent)
        except FileExistsError:
            check = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                metadata(check, 0, 0, 0o700)
                names = set(os.listdir(check))
                require(names <= {'.host-install.lock', 'overlay-intent.json', '.pending.overlay-intent.json', 'etc', '.pending-dir.etc'} and
                        ('overlay-intent.json' in names or '.pending.overlay-intent.json' in names or not names or names == {'.host-install.lock'}),
                        'overlay-conflict', 'unrelated output directory')
            finally: os.close(check)
        root = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        metadata(root, 0, 0, 0o700)
        with lock(root):
            intent = dict(schema=1, kind='zog-offline-overlay', bundle_sha256=digest(bundle),
                          previous_sha256=digest(previous) if previous is not None else None)
            publish(root, 'overlay-intent.json', canonical(intent), 0o444, checkpoint=checkpoint)
            opened = []
            fd = root
            try:
                for part in ('etc', 'zog', 'host-install'):
                    fd = ensure_directory(fd, part, 0, 0, 0o755, checkpoint); opened.append(fd)
                for name in ('accounts', 'installation'):
                    publish(fd, name + '.json', canonical(bundle[name]), 0o444, checkpoint=checkpoint)
                if ca_bytes:
                    ca = ensure_directory(fd, 'ca', 0, 0, 0o755, checkpoint)
                    try:
                        for name, value in ca_bytes.items(): publish(ca, name + '.pem', value, 0o444, checkpoint=checkpoint)
                    finally: os.close(ca)
                # Bootstrap's presence commits this coherent record set.
                publish(fd, 'bootstrap.json', canonical(bundle['bootstrap']), 0o444, checkpoint=checkpoint)
                os.fsync(root); os.fsync(parent)
            finally:
                for child in reversed(opened): os.close(child)
        return dict(status='offline-overlay-published', output=str(output), bundle_sha256=digest(bundle),
                    slot_selected=False, identity_created=False)
    finally:
        if root is not None: os.close(root)
        os.close(parent)


def open_volume():
    """Verified device/namespace context, before requiring a volume marker/tree."""
    require(os.geteuid() == 0, 'root-required', 'STATE provisioning requires root')
    bundle = load_configuration()
    accounts_match()
    mount = _mount(bundle)
    fd = directory('/state')
    context = VerifiedState(bundle, fd, mount)
    try:
        metadata(fd, 0, 0, 0o755)
        dev = os.fstat(fd).st_dev
        require(f'{os.major(dev)}:{os.minor(dev)}' == mount['device'], 'mount-changed', 'descriptor device mismatch')
        context.recheck()
        return context
    except BaseException:
        context.close()
        raise


def layout_record(bundle, kind):
    return canonical(dict(schema=1, kind=kind, marker_sha256=digest(bundle['marker'])))


def prepared_layout(c):
    require(raw(c.fd, '.zog-prepared.json', mode=0o444) == layout_record(c.bundle, 'zog-state-prepared'),
            'layout-not-prepared', 'durably completed STATE layout required')


def prepare_tree(c, initialize_volume=None, checkpoint=lambda _: None, *, service_ids=(970, 970, 971, 971)):
    """Internal trusted-context helper; service_ids override is only for fixtures."""
    b = c.bundle['bootstrap']
    c.recheck()
    marker = raw(c.fd, '.zog-state.json', mode=0o444, links=(1, 2))
    if marker is None:
        require(initialize_volume == b['state']['state_volume_id'] and b['mode'] == 'fresh',
                'volume-initialization-required', 'explicit volume ID required on a fresh unmarked filesystem')
        names = set(os.listdir(c.fd))
        require(names <= {'lost+found', '.host-install.lock', '.pending..zog-state.json',
                          '.zog-preparation.json', '.pending..zog-preparation.json'},
                'nonempty-unmarked-volume', 'refusing to adopt existing data')
        if 'lost+found' in names:
            lost = os.open('lost+found', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=c.fd)
            try:
                metadata(lost, 0, 0, 0o700)
                require(not os.listdir(lost) and os.fstat(lost).st_dev == os.fstat(c.fd).st_dev,
                        'nonempty-unmarked-volume', 'lost+found')
            finally: os.close(lost)
    else:
        require(marker == canonical(c.bundle['marker']), 'marker-mismatch', 'foreign or noncanonical marker')
        require(raw(c.fd, '.zog-preparation.json', mode=0o444, links=(1, 2)) ==
                layout_record(c.bundle, 'zog-state-preparation'), 'layout-not-authorized', 'missing preparation intent')
    with lock(c.fd):
        c.recheck()
        publish(c.fd, '.zog-preparation.json', layout_record(c.bundle, 'zog-state-preparation'), 0o444, checkpoint=checkpoint)
        publish(c.fd, '.zog-state.json', canonical(c.bundle['marker']), 0o444, checkpoint=checkpoint)
        done = raw(c.fd, '.zog-prepared.json', mode=0o444, links=(1, 2))
        if done is not None:
            require(done == layout_record(c.bundle, 'zog-state-prepared'), 'layout-conflict', 'completion mismatch')
        def component(parent, name, uid, gid, mode):
            if done is None: return ensure_directory(parent, name, uid, gid, mode, checkpoint)
            # A completed layout is verified, never reconstructed. Missing trust
            # or journal directories must not become new empty state on reboot.
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                metadata(child, uid, gid, mode)
                require(os.fstat(child).st_dev == os.fstat(c.fd).st_dev, 'nested-mount', name)
                return child
            except BaseException:
                os.close(child)
                raise
        installer = component(c.fd, 'host-install', 0, 0, 0o755)
        try:
            operations = component(installer, 'operations', 0, 0, 0o700)
            try:
                if done is None:
                    require(not set(os.listdir(operations)) & {'identity-authorization.json', 'identity-consumed.json'},
                            'layout-conflict', 'identity operation exists before layout completion')
            finally: os.close(operations)
            records = component(installer, 'installations', 0, 0, 0o755)
            try: publish(records, c.bundle['installation']['record_id'] + '.json', canonical(c.bundle['installation']), 0o444, checkpoint=checkpoint)
            finally: os.close(records)
        finally: os.close(installer)
        uid, gid, box_uid, box_gid = service_ids
        home = component(c.fd, 'host-discover', uid, gid, 0o700)
        try:
            for name in ('trust', 'control', 'registries', 'health'):
                child = component(home, name, uid, gid, 0o700); os.close(child)
        finally: os.close(home)
        box = component(c.fd, 'box-control', box_uid, box_gid, 0o700); os.close(box)
        c.recheck()
        publish(c.fd, '.zog-prepared.json', layout_record(c.bundle, 'zog-state-prepared'), 0o444, checkpoint=checkpoint)
        c.recheck()
    return dict(status='state-prepared', identity_created=False, control_authorized=False)


def prepare_live(initialize_volume=None):
    with open_volume() as c:
        return prepare_tree(c, initialize_volume)
