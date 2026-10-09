"""Closed v1 STATE records. Digests bind records; they do not authenticate them."""
import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit
from . import InstallError

PROFILE = 'zog-host-accounts-v1'
CONFIG = '/etc/zog/host-install'
PATHS = {'mount_point': '/state', 'identity_directory': '/state/host-discover/identity',
         'trust_directory': '/state/host-discover/trust', 'control_directory': '/state/host-discover/control'}
ACCOUNTS = {'schema': 1, 'kind': 'zog-host-accounts', 'profile': PROFILE,
            'users': {'host-discover': {'uid': 970, 'gid': 970, 'groups': [972, 973]},
                      'box-control': {'uid': 971, 'gid': 971, 'groups': [972]}},
            'groups': {'host-discover': 970, 'box-control': 971,
                       'archive-consumers': 972, 'host-control': 973}}

class StateError(InstallError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


def require(value, code, message):
    if not value:
        raise StateError(code, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw):
    require(len(raw) <= 65536, 'record-size', 'record exceeds 64 KiB')
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate-field', key)
            out[key] = value
        return out
    def forbidden(value):
        raise StateError('invalid-number', str(value))
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=forbidden,
                          parse_constant=forbidden)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise StateError('invalid-json', str(exc)) from exc


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()),
            'record-fields', f'expected fields: {names}')


def integer(value):
    require(type(value) is int and value > 0, 'invalid-integer', 'positive integer required')


def identifier(value):
    try:
        require(type(value) is str and str(uuid.UUID(value)) == value,
                'invalid-uuid', 'canonical UUID required')
    except (ValueError, AttributeError) as exc:
        raise StateError('invalid-uuid', 'canonical UUID required') from exc


def sha(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value),
            'invalid-digest', 'lowercase SHA-256 required')


def header(value, kind, names):
    fields(value, 'schema kind ' + names)
    require(type(value['schema']) is int and value['schema'] == 1 and value['kind'] == kind,
            'unsupported-schema', kind)


def host_slots(installation):
    """Normalize optional A/B slot evidence without inventing an inactive slot."""
    r = installation['installer_recorded']
    raw = r.get('host_slots')
    if raw is None:
        return {
            'HOST-A': {'generation': r['expected_host_generation'], 'root_partuuid': r['root_partuuid']} if r['expected_slot'] == 'HOST-A' else None,
            'HOST-B': {'generation': r['expected_host_generation'], 'root_partuuid': r['root_partuuid']} if r['expected_slot'] == 'HOST-B' else None,
        }
    fields(raw, 'HOST-A HOST-B')
    result = {}
    partuuids = set()
    for slot in ('HOST-A', 'HOST-B'):
        row = raw[slot]
        if row is None:
            result[slot] = None
            continue
        fields(row, 'generation root_partuuid')
        require(type(row['generation']) is str and re.fullmatch('[A-Za-z0-9._-]{1,128}', row['generation']),
                'generation', 'invalid slot generation')
        identifier(row['root_partuuid'])
        require(row['root_partuuid'] not in partuuids, 'slot', 'slot PARTUUID reused')
        partuuids.add(row['root_partuuid'])
        result[slot] = {'generation': row['generation'], 'root_partuuid': row['root_partuuid']}
    selected = result[r['expected_slot']]
    require(selected is not None and
            selected['generation'] == r['expected_host_generation'] and
            selected['root_partuuid'] == r['root_partuuid'],
            'slot-binding', 'selected slot does not match installation record')
    return result


def validate(bundle):
    """Validate detached data only. This function never grants runtime readiness."""
    fields(bundle, 'bootstrap installation accounts marker')
    b, i, a, m = (bundle[k] for k in ('bootstrap', 'installation', 'accounts', 'marker'))
    # Canonical comparison deliberately distinguishes true from numeric 1.
    require(canonical(a) == canonical(ACCOUNTS), 'account-profile', 'unsupported fixed account mapping')
    header(m, 'zog-state-volume', 'installation_id state_volume_id partition_partuuid filesystem_uuid account_profile')
    for key in ('installation_id', 'state_volume_id', 'partition_partuuid', 'filesystem_uuid'):
        identifier(m[key])
    require(m['account_profile'] == PROFILE, 'account-profile', 'marker profile')
    header(i, 'zog-host-installation', 'record_id installation_id operation installer_recorded security')
    identifier(i['record_id']); identifier(i['installation_id'])
    require(i['operation'] in ('fresh', 'upgrade', 'reinstall', 'migration', 'recovery'), 'installation-mode', 'operation')
    r = i['installer_recorded']
    base = set('expected_artifact_id expected_host_generation expected_slot root_partuuid account_profile accounts_sha256 marker_sha256 foreign_boot_bundle state_schemas'.split())
    require(type(r) is dict and set(r) in (base, base | {'host_slots'}),
            'record-fields', 'unexpected installer_recorded fields')
    sha(r['expected_artifact_id']); identifier(r['root_partuuid'])
    require(type(r['expected_host_generation']) is str and re.fullmatch('[A-Za-z0-9._-]{1,128}', r['expected_host_generation']), 'generation', 'invalid generation')
    require(r['expected_slot'] in ('HOST-A', 'HOST-B'), 'slot', 'unsupported slot')
    host_slots(i)
    require(r['account_profile'] == PROFILE and r['accounts_sha256'] == digest(a) and r['marker_sha256'] == digest(m), 'record-binding', 'accounts/marker mismatch')
    f = r['foreign_boot_bundle']
    if f is not None:
        fields(f, 'kind provider record_reference record_sha256')
        require(f['kind'] == 'foreign' and type(f['provider']) is str and 0 < len(f['provider']) <= 128,
                'boot-provenance', 'invalid provider')
        identifier(f['record_reference']); sha(f['record_sha256'])
    require(canonical(r['state_schemas']) == canonical({'identity': 1, 'trust': 1, 'control': 1, 'controller': 1}), 'state-schema', 'v1 implementation accepts schema 1 only')
    require(i['security'] == {'secure_boot': 'not-assessed', 'measured_boot': 'not-assessed', 'remote_attestation': 'not-implemented'}, 'security-claim', 'unsupported security claim')
    header(b, 'zog-host-bootstrap', 'profile installation_id configuration_revision mode required_features state initialization registries control_authority installation_record')
    require(b['profile'] == 'state-contract-v1' and b['required_features'] == [], 'unsupported-feature', 'profile/features')
    integer(b['configuration_revision']); identifier(b['installation_id'])
    require(b['mode'] in ('fresh', 'existing', 'migration', 'recovery'), 'installation-mode', 'bootstrap mode')
    require(b['installation_id'] == i['installation_id'] == m['installation_id'], 'record-binding', 'installation mismatch')
    s = b['state']
    fields(s, 'mount_point identity_directory trust_directory control_directory filesystem_type partition_partuuid filesystem_uuid state_volume_id marker_sha256')
    require(all(s[k] == v for k, v in PATHS.items()) and s['filesystem_type'] == 'ext4', 'state-path', 'fixed STATE layout required')
    require(all(s[k] == m[k] for k in ('partition_partuuid', 'filesystem_uuid', 'state_volume_id')) and s['marker_sha256'] == digest(m), 'record-binding', 'STATE mismatch')
    ref = b['installation_record']
    fields(ref, 'path sha256')
    require(ref['path'] == CONFIG + '/installation.json' and ref['sha256'] == digest(i), 'record-binding', 'installation reference mismatch')
    init = b['initialization']
    fields(init, 'authorization_id policy expected_host_uuid expected_fingerprint')
    identifier(init['authorization_id'])
    require(init['policy'] == 'explicit-install-transaction', 'initialization-policy', 'explicit transaction required')
    require((init['expected_host_uuid'] is None) == (init['expected_fingerprint'] is None), 'identity-binding', 'UUID/fingerprint must be paired')
    if init['expected_host_uuid'] is not None:
        identifier(init['expected_host_uuid']); sha(init['expected_fingerprint'])
    if b['mode'] in ('migration', 'recovery'):
        require(init['expected_host_uuid'] is not None, 'identity-binding', 'recovery must name identity')
    regs = b['registries']
    require(type(regs) is list and 1 <= len(regs) <= 32, 'registry', 'registry list required')
    ids = set(); controls = []
    for reg in regs:
        fields(reg, 'registry_id origin role ca')
        rid = reg['registry_id']
        require(type(rid) is str and re.fullmatch('[a-z][a-z0-9-]{0,63}', rid) and rid not in ids, 'registry', 'duplicate/invalid registry ID')
        ids.add(rid)
        require(type(reg['origin']) is str, 'registry', 'HTTPS origin required')
        try:
            url = urlsplit(reg['origin'])
            require(url.scheme == 'https' and url.hostname and url.username is None and url.password is None and not url.query and not url.fragment and url.path in ('', '/') and not any(c.isspace() for c in reg['origin']), 'registry', 'HTTPS origin required')
            require(url.port is None or 0 < url.port < 65536, 'registry', 'invalid port')
        except ValueError as exc:
            raise StateError('registry', 'invalid origin') from exc
        require(reg['role'] in ('control', 'observation'), 'registry', 'invalid role')
        if reg['role'] == 'control': controls.append(rid)
        if reg['ca'] is not None:
            fields(reg['ca'], 'path sha256'); sha(reg['ca']['sha256'])
            require(reg['ca']['path'] == CONFIG + '/ca/' + rid + '.pem', 'ca-path', 'fixed CA path required')
    c = b['control_authority']
    fields(c, 'authority_id registry_id replacement new_session_every_process_start offline_commands')
    identifier(c['authority_id'])
    require(controls == [c['registry_id']] and c['replacement'] == 'explicit-approved-transition-only' and c['new_session_every_process_start'] is True and c['offline_commands'] is False, 'control-authority', 'one control authority and fresh sessions required')
    return bundle
