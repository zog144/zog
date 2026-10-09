"""Durable operation preparation and transitions; deliberately no provider IO.

Trusted integrations supply authorization and validated provider observations.
The ledger is not a DNS executor and does not claim observations are authoritative.
"""
from dataclasses import asdict, replace
import hashlib
import json
import time
import uuid
from .contracts import NetworkError, StateStore, Authorizer, ERROR_CODES
from .models import Connection, ZoneBinding, Plan, ManagedRecord, identifier, below, timestamp


TERMINAL = frozenset({'succeeded', 'failed', 'cancelled'})
TRANSITIONS = {
    'prepared': {'dispatching', 'cancelled', 'conflict', 'failed'},
    'dispatching': {'verifying', 'uncertain'},
    'verifying': {'succeeded', 'retry-wait', 'conflict', 'uncertain'},
    'retry-wait': {'dispatching', 'cancelled', 'failed', 'conflict'},
    'uncertain': {'verifying'},
    'conflict': {'succeeded'}, 'succeeded': set(), 'failed': set(), 'cancelled': set(),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class OperationLedger:
    def __init__(self, store: StateStore, authorizer: Authorizer, clock=time.time):
        self.store, self.authorizer, self.clock = store, authorizer, clock

    def _now(self):
        value = self.clock(); timestamp(value); return value

    def _authorize(self, actor, owner, connection, binding, action):
        identifier(actor); identifier(owner)
        if connection.owner_id != owner or (binding and binding.owner_id != owner): raise NetworkError('permission')
        if self.authorizer.authorize(actor, owner, connection, binding, action) is not True:
            raise NetworkError('permission')

    def put_connection(self, actor, connection: Connection, expected_revision: int):
        if not isinstance(connection, Connection): raise ValueError('Expected Connection')
        with self.store.transaction():
            self._authorize(actor, connection.owner_id, connection, None, 'configure')
            old = self.store.read('connection', connection.id)
            self._cas(old, expected_revision, connection.revision)
            if old and any(old[k] != asdict(connection)[k] for k in ('owner_id', 'provider', 'account_ref')):
                raise NetworkError('conflict')
            self.store.write('connection', connection.id, asdict(connection))

    @staticmethod
    def _cas(old, expected, new):
        if type(expected) is not int or expected < 0 or expected != (old['revision'] if old else 0) or new != expected + 1:
            raise NetworkError('conflict')

    def put_binding(self, actor, binding: ZoneBinding, expected_revision: int):
        if not isinstance(binding, ZoneBinding): raise ValueError('Expected ZoneBinding')
        with self.store.transaction():
            connection = self._connection(binding.connection_id)
            self._authorize(actor, binding.owner_id, connection, binding, 'configure')
            old = self.store.read('binding', binding.id)
            self._cas(old, expected_revision, binding.revision)
            if old and any(old[k] != asdict(binding)[k] for k in ('owner_id', 'connection_id', 'zone_id', 'zone_name', 'prefix')):
                raise NetworkError('conflict')
            # A single owner of each namespace: overlapping prefixes are unsafe.
            for other in self.store.all('binding'):
                if other['id'] != binding.id and other['status'] != 'detached' and binding.status != 'detached':
                    a, b = other['prefix'], binding.prefix
                    if a == b or below(a, b) or below(b, a): raise NetworkError('conflict')
            self.store.write('binding', binding.id, asdict(binding))

    def _connection(self, key):
        row = self.store.read('connection', key)
        if row is None: raise NetworkError('not-found')
        return Connection(**row)

    def _context(self, binding_id):
        row = self.store.read('binding', binding_id)
        if row is None: raise NetworkError('not-found')
        binding = ZoneBinding(**row)
        return self._connection(binding.connection_id), binding

    def _ready(self, connection, binding, plan):
        if connection.status != 'ready' or binding.status != 'ready': raise NetworkError('permission')
        if (connection.revision, binding.revision) != (plan.connection_revision, plan.binding_revision):
            raise NetworkError('conflict')
        snapshot = plan.after or plan.before
        if not below(snapshot.name, binding.prefix): raise NetworkError('validation')
        # Canonical policy: a single host label directly beneath the managed prefix.
        if '.' in snapshot.name[:-(len(binding.prefix) + 1)]: raise NetworkError('validation')
        if plan.after and plan.after.ttl < (600 if connection.provider == 'porkbun' else 300):
            raise NetworkError('validation')

    def prepare(self, actor, request_id, plan: Plan):
        identifier(request_id)
        if not isinstance(plan, Plan): raise ValueError('Expected Plan')
        key = digest([plan.owner_id, request_id])
        payload_hash = digest(plan.to_dict())
        with self.store.transaction():
            connection, binding = self._context(plan.binding_id)
            self._authorize(actor, plan.owner_id, connection, binding, 'prepare')
            old = self.store.read('operation', key)
            if old:
                if old['payload_hash'] != payload_hash: raise NetworkError('conflict')
                return old
            self._ready(connection, binding, plan)
            allocation = self.store.read('allocation', digest([binding.id, plan.resource_id]))
            if allocation and (allocation['state'] != 'reserved'
                    or allocation['name'] != (plan.after or plan.before).name
                    or plan.desired_revision < allocation['revision_floor']):
                raise NetworkError('conflict')
            operations = self.store.all('operation')
            if any(o['binding_id'] == binding.id and o['state'] not in TERMINAL for o in operations):
                raise NetworkError('conflict')
            # Reserve names durably; deletion does not transfer ownership.
            name = (plan.after or plan.before).name
            for reservation in self.store.all('reservation'):
                if reservation['name'] == name and (reservation['binding_id'], reservation['resource_id']) != (binding.id, plan.resource_id):
                    raise NetworkError('conflict')
            previous = [o for o in operations if o['binding_id'] == binding.id and o['plan']['resource_id'] == plan.resource_id]
            if previous and plan.desired_revision <= max(o['plan']['desired_revision'] for o in previous):
                raise NetworkError('conflict')
            # Updates/deletes must be tied to a previously recorded exact owned ID.
            record_key = digest([binding.id, plan.resource_id])
            record = self.store.read('record', record_key)
            if record == {'deleted': True}: record = None
            if plan.action == 'create':
                if record is not None: raise NetworkError('conflict')
            elif record is None or record['record_id'] != plan.record_id or record['last_applied'] != asdict(plan.before):
                raise NetworkError('conflict')
            now = self._now(); operation_id = str(uuid.uuid4())
            row = dict(schema=1, id=operation_id, owner_id=plan.owner_id, request_id=request_id,
                       binding_id=binding.id, connection_id=connection.id, credential_ref=connection.credential_ref,
                       payload_hash=payload_hash, plan=plan.to_dict(), actor=actor, state='prepared', revision=1,
                       created_at=now, updated_at=now, retry_at=None, record_id=plan.record_id,
                       marker='zog-operation:' + operation_id, step_key=digest([operation_id, 'record']),
                       before_marker=record.get('marker') if record else None,
                       events=[dict(state='prepared', at=now, actor=actor)])
            self.store.write('reservation', digest(name), dict(name=name, binding_id=binding.id, resource_id=plan.resource_id))
            self.store.write('operation', key, row)
            return row

    def inspect_operation(self, actor, owner_id, request_id):
        identifier(owner_id); identifier(request_id)
        with self.store.transaction():
            row = self.store.read('operation', digest([owner_id, request_id]))
            if row is None: raise NetworkError('not-found')
            c, b = self._context(row['binding_id'])
            self._authorize(actor, owner_id, c, b, 'inspect')
            return row

    def transition(self, actor, owner_id, request_id, expected_revision, state, *,
                   proof=None, record_id=None, retry_at=None):
        """Trusted worker-only API; proofs assert a completed provider comparison.

        proof='matched' means exact intended record/marker/ID observed;
        'absent' means owned delete ID absent in an authorized lookup;
        'unapplied' means dispatch proven to have had no effect.
        Never expose this transition endpoint directly to browser clients.
        """
        identifier(owner_id); identifier(request_id)
        if proof not in (None, 'matched', 'absent', 'unapplied'): raise ValueError('Invalid proof')
        if record_id is not None: identifier(record_id)
        if retry_at is not None: timestamp(retry_at)
        with self.store.transaction():
            key = digest([owner_id, request_id]); row = self.store.read('operation', key)
            if row is None: raise NetworkError('not-found')
            c, b = self._context(row['binding_id'])
            self._authorize(actor, owner_id, c, b, 'transition')
            if type(expected_revision) is not int or row['revision'] != expected_revision or state not in TRANSITIONS[row['state']]:
                raise NetworkError('conflict')
            plan = Plan.from_dict(row['plan']); now = self._now()
            if state == 'dispatching':
                self._authorize(actor, owner_id, c, b, 'dispatch')
                self._ready(c, b, plan)
                if c.credential_ref != row['credential_ref']: raise NetworkError('conflict')
                if row['retry_at'] is not None and now < row['retry_at']: raise NetworkError('conflict')
            if state == 'retry-wait':
                if proof != 'unapplied' or retry_at is None or retry_at <= now: raise NetworkError('validation')
            elif retry_at is not None: raise NetworkError('validation')
            if row['state']=='conflict':
                # Only a proven accepted write can be resolved directly. Never
                # redispatch or resolve an unowned deletion this way.
                if (state!='succeeded' or proof!='matched' or plan.after is None
                        or not row.get('response_record_id') or record_id!=row['response_record_id']):
                    raise NetworkError('conflict')
                self._ready(c,b,plan)
                if c.credential_ref!=row['credential_ref']:raise NetworkError('conflict')
            if state == 'succeeded':
                if plan.action == 'delete':
                    if proof != 'absent' or record_id is not None: raise NetworkError('validation')
                    # Keep ownership history in operations and reservation.
                    self.store.write('record', digest([b.id, plan.resource_id]), {'deleted': True})
                else:
                    if proof != 'matched' or not record_id or (plan.record_id and plan.record_id != record_id):
                        raise NetworkError('validation')
                    managed = ManagedRecord(id=digest([b.id, plan.resource_id]), owner_id=owner_id,
                        binding_id=b.id, resource_id=plan.resource_id, record_id=record_id,
                        last_applied=plan.after, desired_revision=plan.desired_revision, observed_at=now,
                        marker=row['marker'])
                    self.store.write('record', managed.id, asdict(managed))
            elif record_id is not None: raise NetworkError('validation')
            row.update(state=state, revision=row['revision'] + 1, updated_at=now,
                       retry_at=retry_at, record_id=record_id or row['record_id'])
            row['events'].append(dict(state=state, at=now, actor=actor, proof=proof))
            self.store.write('operation', key, row)
            return row

    def context(self, actor, owner_id, binding_id, resource_id):
        """Detached current scope and ownership; no secrets are resolved."""
        from .models import resource_uuid
        resource_id = resource_uuid(resource_id)
        with self.store.transaction():
            c, b = self._context(binding_id)
            self._authorize(actor, owner_id, c, b, 'inspect')
            record = self.store.read('record', digest([b.id, resource_id]))
            return c, b, None if record == {'deleted': True} else record

    def block_binding(self, actor, owner_id, binding_id, expected_revision):
        with self.store.transaction():
            c, b = self._context(binding_id)
            self._authorize(actor, owner_id, c, b, 'configure')
            if b.revision != expected_revision: raise NetworkError('conflict')
            blocked = replace(b, status='blocked', revision=b.revision + 1)
            self.store.write('binding', b.id, asdict(blocked))

    def progress(self, actor, owner_id, request_id, expected_revision, *, error_code=None,
                 next_check_at=None, count_read=False, count_preflight=False, response_record_id=None):
        """Persist sanitized bounded-verification bookkeeping, never provider bodies."""
        if error_code is not None and error_code not in ERROR_CODES: raise ValueError('Invalid error code')
        if next_check_at is not None: timestamp(next_check_at)
        if type(count_read) is not bool: raise ValueError('Invalid counter flag')
        if type(count_preflight) is not bool: raise ValueError('Invalid counter flag')
        if response_record_id is not None: identifier(response_record_id)
        with self.store.transaction():
            key = digest([owner_id, request_id]); row = self.store.read('operation', key)
            if row is None: raise NetworkError('not-found')
            c, b = self._context(row['binding_id'])
            self._authorize(actor, owner_id, c, b, 'transition')
            if type(expected_revision) is not int or row['revision'] != expected_revision or row['state'] in TERMINAL or row['state'] == 'conflict':
                raise NetworkError('conflict')
            if count_preflight and row['state'] != 'prepared': raise NetworkError('conflict')
            if count_read and row['state'] != 'verifying': raise NetworkError('conflict')
            row.update(revision=row['revision'] + 1, updated_at=self._now(), last_error_code=error_code,
                       next_check_at=next_check_at, read_attempts=row.get('read_attempts', 0) + int(count_read),
                       preflight_attempts=row.get('preflight_attempts', 0) + int(count_preflight))
            if response_record_id is not None:
                if row['state'] != 'dispatching': raise NetworkError('conflict')
                row['response_record_id'] = response_record_id
            self.store.write('operation', key, row)
            return row
