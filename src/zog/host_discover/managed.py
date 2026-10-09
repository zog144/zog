"""Retained STATE inspection and fault latch shared by managed transport.

The pure coordinator adapter remains available for synthetic gate tests. Runtime
verification consumes host-install's fresh authenticated socket API through admission.py.
"""
import os
from zog.host_install import state_inspect, state_probe, state_gate
from zog.host_install.state_contract import StateError, require, validate
from zog.host_identify import initialization


class CoordinatorUnavailable:
    def recovery_hold(self, context):
        raise StateError('recovery-hold-unavailable', 'Protected recovery state has no producer yet')

    def schemas(self, context):
        raise StateError('component-schemas-unavailable', 'Runtime component declarations unavailable')

    def consumption(self, context):
        raise StateError('consumption-unavailable', 'Independent privileged receipt unavailable')


class ManagedState:
    """Retain inspected STATE for one process admission attempt.

    fault_code is a process-lifetime latch, never a persistent healthy marker.
    This object cannot be re-entered, even after close. Nothing here enables
    enrollment, signing, credential renewal or command/legacy role dispatch.
    """
    def __init__(self):
        self.context = None
        self.fault_code = None
        self.started = False
        self._key = None

    def fail(self, code):
        self._key = None
        if self.fault_code is None:
            self.fault_code = code
        raise StateError(self.fault_code, 'Managed startup requires fresh admission')

    def __enter__(self):
        if self.started:
            self.fail('admission-already-attempted')
        self.started = True
        try:
            require(os.geteuid() == 970 and os.getegid() == 970 and
                    set(os.getgroups()) <= {970, 972, 973},
                    'probe-account', 'Managed startup must run as host-discover')
            self.context = state_inspect.inspect_live()
            validate(self.context.bundle)
            # Public probe repeats inspection in this namespace. Recheck our
            # retained context afterward to reject a mount switch between them.
            result = state_probe.probe_live()
            require(result.get('status') == 'probe-passed', 'storage-probe-failed', 'Probe did not pass')
            self.check()
            return self
        except (StateError, OSError) as exc:
            self.close()
            self.fail(getattr(exc, 'code', 'state-io-failure'))

    def check(self):
        if self.fault_code:
            self.fail(self.fault_code)
        try:
            require(self.context is not None, 'closed-inspection', 'No retained STATE')
            self.context.recheck()
        except (StateError, OSError) as exc:
            self.fail(getattr(exc, 'code', 'state-io-failure'))

    def close(self):
        self._key = None
        if self.context is not None:
            self.context.close()
            self.context = None

    def __exit__(self, kind, error, traceback):
        if error is not None and self.fault_code is None:
            self.fault_code = getattr(error, 'code', 'managed-state-failed')
        self.close()

    def _identity(self, receipt):
        """All identity reads remain relative to the verified STATE descriptor."""
        self.check()
        b = self.context.bundle['bootstrap']
        require(isinstance(receipt, dict), 'consumption-unavailable', 'Independent receipt required')
        for key, value in (('installation_id', b['installation_id']),
                           ('state_volume_id', b['state']['state_volume_id']),
                           ('authorization_id', b['initialization']['authorization_id'])):
            require(receipt.get(key) == value, 'consumption-mismatch', key)
        home = os.open('host-discover', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.context.fd)
        try:
            state_inspect.metadata(home, 970, 970, 0o700)
            fd = os.open('identity', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
            try:
                state_inspect.metadata(fd, 970, 970, 0o700)
                require(os.fstat(fd).st_dev == os.fstat(self.context.fd).st_dev, 'nested-mount', 'identity')
                self._key = initialization.load_existing_fd(fd, b['state']['identity_directory'], receipt)
                self.check()
            finally:
                os.close(fd)
        finally:
            os.close(home)
        expected = b['initialization']
        # Only the supervised beacon may defer UUID validation until its root-
        # checkpointed journal is loaded; it validates before any network call.
        # The narrow diagnostic still refuses without that protected binding.
        require(expected['expected_host_uuid'] is None or getattr(self, '_protected_uuid_pending', False), 'registry-binding-unavailable', 'Expected UUID requires protected binding')
        require(expected['expected_fingerprint'] is None or
                expected['expected_fingerprint'] == receipt['fingerprint'], 'identity-mismatch', 'Fingerprint mismatch')
        return dict(status='complete', initialization_id=receipt['authorization_id'],
                    candidates=1, matches_expected=True)

    def decision(self, coordinator=None):
        """Diagnostic only, including with trusted test coordinator adapters."""
        coordinator = coordinator or CoordinatorUnavailable()
        try:
            self.check()
            hold = coordinator.recovery_hold(self.context)
            require(type(hold) is bool, 'recovery-hold-unavailable', 'No authoritative recovery hold')
            schemas = coordinator.schemas(self.context)
            require(type(schemas) is dict and set(schemas) == {'identity','trust','control','controller'} and
                    all(type(v) is int and v == 1 for v in schemas.values()),
                    'unsupported-state-schema', 'Unsupported runtime component schema')
            # No initialize/resume path: those require a current privileged
            # boot-bound transaction, not installer mode=fresh or a saved report.
            identity = self._identity(coordinator.consumption(self.context))
            b = self.context.bundle['bootstrap']
            evidence = dict(mount_verified=True, accounts_verified=True, storage_probe='passed',
                identity=identity, schemas=schemas, recovery_hold=hold,
                authorization=dict(verified_current_transaction=False, action='none',
                    installation_id=b['installation_id'], state_volume_id=b['state']['state_volume_id'],
                    initialization_id=b['initialization']['authorization_id']),
                station=dict(status='unavailable', registry_id=b['control_authority']['registry_id']))
            self.check()
            result = state_gate.decide(self.context.bundle, evidence)
            return dict(result, live_admission=False, remote_control_enabled=False,
                        blockers=['anchored-registry-state-unavailable', 'fresh-session-required'])
        except Exception as exc:
            self.fail(getattr(exc, 'code', 'identity-state-invalid'))


def report():
    """Narrow identity verification; no journal creation or network admission."""
    from .admission import verify_existing
    try:
        with ManagedState() as state:
            result=verify_existing(state)
            return dict(status='existing-identity-verified',identity_action='verify-existing',
                        fingerprint=result['receipt']['fingerprint'],code='full-admission-pending',
                        live_admission=False,remote_control_enabled=False,
                        transport_enabled=False,control_authorized=False)
    except StateError as exc:
        return dict(status='blocked',identity_action='block',code=exc.code,
                    live_admission=False,remote_control_enabled=False,
                    transport_enabled=False,control_authorized=False)
