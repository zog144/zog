"""Component-owned validation of persisted beacon binding/trust/session state."""
from zog.host_identify import signatures, managed
from zog.host_install.state_contract import fields, header, require, sha

SCHEMA = 1


def validate(value):
    header(value, 'zog-managed-journal', 'installation_id state_volume_id fingerprint registries replay')
    managed.identifier(value['installation_id']); managed.identifier(value['state_volume_id']); sha(value['fingerprint'])
    require(type(value['registries']) is dict and len(value['registries']) <= 32 and type(value['replay']) is list and len(value['replay']) <= 128, 'managed-journal-schema', 'Invalid bounded state')
    for rid, row in value['registries'].items():
        require(type(rid) is str and 1 <= len(rid) <= 64, 'managed-registry', 'Invalid registry name')
        fields(row, 'origin role host_id public_key previous pending')
        require(signatures.origin(row['origin']) == row['origin'] and row['origin'].startswith('https://'), 'managed-origin', 'Canonical HTTPS origin required')
        require(row['role'] in ('control', 'observation'), 'managed-role', 'Invalid role')
        if row['host_id'] is not None: managed.identifier(row['host_id'])
        if row['public_key'] is not None: signatures.public_key(row['public_key'])
        if row['previous'] is not None:
            fields(row['previous'], 'epoch checkpoint')
            require(type(row['previous']['epoch']) is int and row['previous']['epoch'] > 0, 'managed-epoch', 'Invalid epoch')
            managed.identifier(row['previous']['checkpoint'])
            require(row['host_id'] is not None and row['public_key'] is not None, 'managed-trust', 'Checkpoint without trust')
        else: require(row['public_key'] is None, 'managed-trust', 'Key without checkpoint')
        if row['pending'] is not None:
            p = row['pending']
            fields(p, 'version installation_id state_volume_id authority_id registry_id challenge previous boot_id')
            require(type(p['version']) is int and p['version'] == 1 and row['host_id'] is not None and p['registry_id'] == rid and p['previous'] == row['previous'], 'managed-pending', 'Invalid pending session')
            for k in ('installation_id', 'state_volume_id', 'authority_id', 'challenge', 'boot_id'): managed.identifier(p[k])
            require(all(p[k] == value[k] for k in ('installation_id','state_volume_id')), 'managed-pending', 'Wrong identity binding')
    seen = set()
    for row in value['replay']:
        fields(row, 'id expires status'); managed.identifier(row['id'])
        require(row['id'] not in seen and type(row['expires']) is int and row['status'] == 'prepared', 'managed-replay', 'Invalid replay entry')
        seen.add(row['id'])
    return value
