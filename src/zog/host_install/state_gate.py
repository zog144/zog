"""Pure lifecycle policy over evidence supplied by trusted component adapters.

This module authenticates neither JSON nor station sessions and must not be
exposed as a caller-supplied authorization service. No key operations occur here.
"""
from .state_contract import fields, require, validate


def decide(bundle, evidence):
    validate(bundle)
    fields(evidence, 'mount_verified accounts_verified storage_probe identity authorization schemas recovery_hold station')
    for key in ('mount_verified', 'accounts_verified', 'recovery_hold'):
        require(type(evidence[key]) is bool, 'evidence-type', key)
    require(evidence['storage_probe'] in ('passed', 'failed', 'not-run'), 'evidence-type', 'storage_probe')
    identity = evidence['identity']
    fields(identity, 'status initialization_id candidates matches_expected')
    require(identity['status'] in ('complete', 'absent', 'prepared', 'incomplete', 'corrupt'), 'evidence-type', 'identity status')
    require(type(identity['candidates']) is int and identity['candidates'] >= 0 and type(identity['matches_expected']) is bool, 'evidence-type', 'identity fields')
    fields(evidence['schemas'], 'identity trust control controller')
    require(all(type(v) is int and v > 0 for v in evidence['schemas'].values()), 'evidence-type', 'schema versions')
    auth = evidence['authorization']
    fields(auth, 'verified_current_transaction installation_id state_volume_id initialization_id action')
    require(type(auth['verified_current_transaction']) is bool and auth['action'] in ('none', 'initialize', 'recover'), 'evidence-type', 'authorization')
    station = evidence['station']
    fields(station, 'status registry_id')
    require(station['status'] in ('fresh', 'cached', 'unavailable', 'stale-checkpoint', 'stale-trust'), 'evidence-type', 'station')
    def result(action, code, control=False):
        return dict(identity_action=action, code=code, control_allowed=control)
    if not evidence['mount_verified']: return result('block', 'mount-unverified')
    if not evidence['accounts_verified']: return result('block', 'account-mismatch')
    if evidence['storage_probe'] != 'passed': return result('block', 'storage-not-healthy')
    if any(v != 1 for v in evidence['schemas'].values()): return result('block', 'unsupported-state-schema')
    if identity['candidates'] > 1 or identity['status'] in ('incomplete', 'corrupt'):
        return result('block', 'identity-inconsistent')
    b = bundle['bootstrap']
    if not identity['matches_expected']: return result('block', 'identity-mismatch')
    if evidence['recovery_hold'] or b['mode'] in ('migration', 'recovery') or station['status'] in ('stale-checkpoint', 'stale-trust'):
        return result('recovery-only', 'reconciliation-required')
    if identity['status'] == 'complete':
        if identity['candidates'] != 1: return result('block', 'identity-inconsistent')
        if station['registry_id'] != b['control_authority']['registry_id']:
            return result('load-existing', 'wrong-control-registry')
        fresh = station['status'] == 'fresh'
        return result('load-existing', 'ready' if fresh else 'fresh-session-required', fresh)
    valid_auth = (auth['verified_current_transaction'] and auth['action'] == 'initialize' and
                  auth['installation_id'] == b['installation_id'] and
                  auth['state_volume_id'] == b['state']['state_volume_id'] and
                  auth['initialization_id'] == b['initialization']['authorization_id'] and b['mode'] == 'fresh')
    if not valid_auth: return result('block', 'initialization-not-authorized')
    if identity['status'] == 'prepared':
        if identity['candidates'] != 1 or identity['initialization_id'] != auth['initialization_id']:
            return result('block', 'prepared-identity-mismatch')
        return result('resume-prepared', 'same-transaction-only')
    if identity['candidates'] != 0: return result('block', 'identity-inconsistent')
    return result('initialize-once', 'explicit-transaction-only')
