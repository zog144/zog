"""Single-writer Cloudflare/Porkbun planning and read-only outcome recovery.

Provider-applied is the only success claim. DNS propagation is not inferred.
No automatic mutation replay, adoption, migration, rename or registrar operations.
"""
import random
from .contracts import NetworkError, ProviderWriteWarning
from .models import Plan, RecordSnapshot, canonical, resource_uuid, below, revision, observation_name
from .ledger import TERMINAL
from .cloudflare import CloudflareDns
from .porkbun_dns import PorkbunDns


def record_name(value):
    # Inspection preserves unrelated wildcard records; writes never accept them.
    return observation_name(value)


def matches(row, snapshot, marker, record_id=None):
    return (row.get('id') == record_id if record_id else True) and (
        row.get('type') == 'A' and record_name(row.get('name')) == snapshot.name
        and row.get('content') == snapshot.address and type(row.get('ttl')) is int
        and row['ttl'] == snapshot.ttl and row.get('proxied') is False
        and row.get('comment') == marker)


class DnsEngine:
    def __init__(self, ledger, gate, secrets=None, transport=None, *, provider_factory=None,
                 jitter=None):
        self.ledger, self.store, self.gate = ledger, ledger.store, gate
        self.provider_factory = provider_factory or (lambda c: (CloudflareDns if c.provider == 'cloudflare' else PorkbunDns)(c, secrets, transport))
        self.jitter = jitter or (lambda: random.uniform(1, 60))

    def _gate(self, connection, binding, resource, desired, action, desired_revision=None):
        if self.gate.check(connection, binding, resource, desired, action, desired_revision) is not None:
            raise NetworkError('permission')

    def _context(self, actor, owner, binding_id, resource):
        c, b, record = self.ledger.context(actor, owner, binding_id, resource)
        if c.provider not in ('cloudflare', 'porkbun'): raise NetworkError('unsupported')
        return c, b, record

    def _inventory(self, provider, connection, binding, resource):
        self._gate(connection, binding, resource, None, 'inspect')
        zone = provider.get_zone(binding.zone_id)
        if (zone.get('id') != binding.zone_id or canonical(zone.get('name')) != binding.zone_name
                or zone.get('account', {}).get('id') != connection.account_ref or zone.get('status') != 'active'):
            raise NetworkError('conflict')
        rows, ids, cursors = [], set(), set()
        cursor = None
        for _ in range(1000):
            page = provider.list_records(binding.zone_id, cursor)
            for row in page.items:
                name = record_name(row.get('name'))
                if row.get('id') in ids or not row.get('id') or not isinstance(row.get('type'), str):
                    raise NetworkError('conflict')
                if name != binding.zone_name and not below(name, binding.zone_name): raise NetworkError('conflict')
                ids.add(row['id']); rows.append(row)
            if page.next_cursor is None: return rows
            if page.next_cursor in cursors: raise NetworkError('validation')
            cursor = page.next_cursor; cursors.add(cursor)
        raise NetworkError('validation')

    @staticmethod
    def _relevant(rows, name, zone_name):
        for row in rows:
            n = record_name(row.get('name'))
            if row['type'] in ('CNAME', 'DNAME', 'NS') and below(name, n) and (n != zone_name or row['type'] != 'NS'):
                raise NetworkError('conflict')
        return [r for r in rows if record_name(r.get('name')) == name and r['type'] in ('A', 'CNAME', 'DNAME', 'NS')]

    def _pause(self, actor, owner, binding):
        self.ledger.block_binding(actor, owner, binding.id, binding.revision)
        raise NetworkError('conflict')

    def plan(self, actor, owner_id, binding_id, resource_id, desired, desired_revision, *, delete=False):
        """Read-only provider planning. Drift durably blocks the local binding.

        desired=None requires delete=True. It is never inferred from stale hosts.
        Returns None for an already matching record or absent unpublished resource.
        """
        resource_id = resource_uuid(resource_id); revision(desired_revision)
        if type(delete) is not bool or (desired is None) != delete or (desired is not None and not isinstance(desired, RecordSnapshot)):
            raise ValueError('Supply desired A snapshot or explicit delete=True')
        with self.store.worker_lock():
            c, b, owned = self._context(actor, owner_id, binding_id, resource_id)
            if c.status != 'ready' or b.status != 'ready': raise NetworkError('permission')
            with self.store.transaction():
                if any(o['binding_id'] == b.id and o['state'] not in TERMINAL for o in self.store.all('operation')):
                    raise NetworkError('conflict')
            before = RecordSnapshot(**owned['last_applied']) if owned else None
            if desired is None and before is None: return None
            plan = Plan(owner_id, b.id, resource_id, c.revision, b.revision, desired_revision,
                'delete' if delete else 'update' if owned else 'create', before, desired,
                owned['record_id'] if owned else None)
            self.ledger._ready(c, b, plan)
            self._gate(c, b, resource_id, desired, 'unpublish' if delete else 'publish', desired_revision)
            try:
                rows = self._inventory(self.provider_factory(c), c, b, resource_id)
                relevant = self._relevant(rows, (desired or before).name, b.zone_name)
                if owned:
                    if not owned.get('marker') or len(relevant) != 1 or not matches(relevant[0], before, owned['marker'], owned['record_id']):
                        self._pause(actor, owner_id, b)
                elif relevant:
                    self._pause(actor, owner_id, b)
            except NetworkError as error:
                if error.code == 'conflict':
                    current = self.ledger.context(actor, owner_id, b.id, resource_id)[1]
                    if current.status != 'blocked': self.ledger.block_binding(actor, owner_id, current.id, current.revision)
                raise
            # Revalidate after network IO; return a plan pinned to the read scope.
            current_c, current_b, current_owned = self._context(actor, owner_id, b.id, resource_id)
            self.ledger._ready(current_c, current_b, plan)
            if current_owned != owned: raise NetworkError('conflict')
            return None if before == desired else plan

    def _step(self, actor, row, state, **kwargs):
        return self.ledger.transition(actor, row['owner_id'], row['request_id'], row['revision'], state, **kwargs)

    def _progress(self, actor, row, **kwargs):
        return self.ledger.progress(actor, row['owner_id'], row['request_id'], row['revision'], **kwargs)

    def _verify(self, actor, row, provider, c, b):
        plan = Plan.from_dict(row['plan'])
        # Counter is committed BEFORE the read so crashes cannot reset the budget.
        row = self._progress(actor, row, count_read=True)
        try:
            rows = self._inventory(provider, c, b, plan.resource_id)
            if plan.action == 'delete':
                if not any(r['id'] == plan.record_id for r in rows):
                    return self._step(actor, row, 'succeeded', proof='absent')
                current = next(r for r in rows if r['id'] == plan.record_id)
                if not matches(current, plan.before, row.get('before_marker'), plan.record_id):
                    return self._step(actor, row, 'conflict')
            else:
                relevant = self._relevant(rows, plan.after.name, b.zone_name)
                if len(relevant) == 1 and matches(relevant[0], plan.after, row['marker'], plan.record_id or row.get('response_record_id')):
                    return self._step(actor, row, 'succeeded', proof='matched', record_id=relevant[0]['id'])
                if relevant and not (len(relevant) == 1 and plan.before and matches(relevant[0], plan.before, row.get('before_marker'), plan.record_id)):
                    return self._step(actor, row, 'conflict')
            error = NetworkError('uncertain')
        except NetworkError as caught:
            if caught.code == 'conflict': return self._step(actor, row, 'conflict')
            error = caught
        # Empty create listing or unchanged update is NOT proof of nonapplication.
        if row['read_attempts'] >= 5 or error.code in ('authentication', 'permission', 'not-found', 'validation'):
            row = self._progress(actor, row, error_code=error.code)
            return self._step(actor, row, 'uncertain')
        delay = max(1, min(60, float(self.jitter())), error.retry_after or 0)
        return self._progress(actor, row, error_code=error.code, next_check_at=self.ledger._now() + delay)

    def apply(self, actor, owner_id, request_id, expected_revision):
        """Advance one operation; may return verifying with a persisted due time.

        A recovered dispatch is verification-only. This executor never automatically
        retries mutations, even when the response was a rate limit or an error.
        """
        with self.store.worker_lock():
            row = self.ledger.inspect_operation(actor, owner_id, request_id)
            if row['state'] in TERMINAL or row['state'] == 'conflict': return row
            if type(expected_revision) is not int or row['revision'] != expected_revision: raise NetworkError('conflict')
            plan = Plan.from_dict(row['plan'])
            c, b, owned = self._context(actor, owner_id, row['binding_id'], plan.resource_id)
            # Never resolve a replacement/revoked secret behind a saved operation.
            if c.status != 'ready' or c.credential_ref != row['credential_ref']:
                raise NetworkError('permission')
            provider = self.provider_factory(c)
            if row['state'] == 'prepared':
                if row.get('next_check_at') and self.ledger._now() < row['next_check_at']: return row
                if row.get('preflight_attempts', 0) >= 5: return self._step(actor, row, 'failed')
                self.ledger._ready(c, b, plan)
                self._gate(c, b, plan.resource_id, plan.after, 'unpublish' if plan.action == 'delete' else 'publish', plan.desired_revision)
                row = self._progress(actor, row, count_preflight=True)
                try:
                    rows = self._inventory(provider, c, b, plan.resource_id)
                    relevant = self._relevant(rows, (plan.after or plan.before).name, b.zone_name)
                    if plan.action == 'create':
                        if relevant: return self._step(actor, row, 'conflict')
                    elif (not row.get('before_marker') or len(relevant) != 1
                          or not matches(relevant[0], plan.before, row['before_marker'], plan.record_id)):
                        return self._step(actor, row, 'conflict')
                except NetworkError as error:
                    if error.code == 'conflict': return self._step(actor, row, 'conflict')
                    if error.code not in ('transient', 'rate-limit') or row['preflight_attempts'] >= 5:
                        row = self._progress(actor, row, error_code=error.code)
                        return self._step(actor, row, 'failed')
                    delay = max(1, min(60, float(self.jitter())), error.retry_after or 0)
                    return self._progress(actor, row, error_code=error.code, next_check_at=self.ledger._now() + delay)
                # Current authorization and external evidence are checked again
                # after provider reads, immediately before durable dispatch.
                c, b, _ = self._context(actor, owner_id, b.id, plan.resource_id)
                self._gate(c, b, plan.resource_id, plan.after, 'unpublish' if plan.action == 'delete' else 'publish', plan.desired_revision)
                row = self._step(actor, row, 'dispatching')
                try:
                    if plan.action == 'create':
                        response = provider.create_record(b.zone_id, plan.after, marker=row['marker'], idempotency_key=row['step_key'])
                    elif plan.action == 'update':
                        response = provider.update_record(b.zone_id, plan.record_id, plan.after, marker=row['marker'], idempotency_key=row['step_key'])
                    else:
                        provider.delete_record(b.zone_id, plan.record_id, idempotency_key=row['step_key'])
                    if plan.action != 'delete':
                        row = self._progress(actor, row, response_record_id=response['id'])
                except ProviderWriteWarning as error:
                    row = self._progress(actor, row, error_code='conflict', response_record_id=error.record_id)
                    row = self._step(actor, row, 'verifying')
                    return self._step(actor, row, 'conflict')
                except NetworkError as error:
                    row = self._progress(actor, row, error_code=error.code)
                    if error.code in ('authentication', 'permission', 'rate-limit'):
                        row = self._step(actor, row, 'verifying')
                        # Do not ignore a longer provider Retry-After.
                        if error.retry_after:
                            return self._progress(actor, row, error_code=error.code, next_check_at=self.ledger._now() + max(1, error.retry_after))
                # Unexpected exceptions deliberately leave dispatching durable.
                if row['state'] == 'dispatching': row = self._step(actor, row, 'verifying')
            elif row['state'] == 'dispatching':
                row = self._step(actor, row, 'verifying')
            elif row['state'] == 'uncertain':
                return row  # explicit operator recovery beyond bounded reads is deferred
            elif row['state'] != 'verifying':
                raise NetworkError('unsupported')
            if row.get('next_check_at') and self.ledger._now() < row['next_check_at']: return row
            if row.get('read_attempts', 0) >= 5: return self._step(actor, row, 'uncertain')
            return self._verify(actor, row, provider, c, b)

    def recheck(self, actor, owner_id, request_id, expected_revision):
        """Explicitly authorize another bounded, read-only uncertain-outcome check.

        This never changes the saved business payload or dispatches another write.
        """
        from .ledger import digest
        with self.store.worker_lock():
            with self.store.transaction():
                key=digest([owner_id,request_id]);row=self.store.read('operation',key)
                if row is None:raise NetworkError('not-found')
                c,b=self.ledger._context(row['binding_id'])
                self.ledger._authorize(actor,owner_id,c,b,'recover')
                if (type(expected_revision) is not int or row['revision']!=expected_revision or row['state']!='uncertain'
                        or c.status!='ready' or b.status not in ('ready','blocked') or c.credential_ref!=row['credential_ref']):
                    raise NetworkError('conflict')
                row.update(state='verifying',revision=row['revision']+1,read_attempts=0,next_check_at=None,
                           updated_at=self.ledger._now())
                row['events'].append(dict(state='verifying',actor=actor,at=row['updated_at'],reason='explicit-read-only-recheck'))
                self.store.write('operation',key,row)
                return row


    def recover_accepted(self, actor, owner_id, request_id, expected_revision):
        """Explicit read-only recovery of an accepted-write warning/conflict.

        Requires unchanged scope/intent, full authority evidence, exact provider
        ID/marker/content and no conflicting records. Does not send mutations.
        """
        with self.store.worker_lock():
            row=self.ledger.inspect_operation(actor,owner_id,request_id)
            if row['revision']!=expected_revision:raise NetworkError('conflict')
            if row['state']=='succeeded':return row
            if row['state']!='conflict' or not row.get('response_record_id'):raise NetworkError('conflict')
            plan=Plan.from_dict(row['plan'])
            if plan.after is None:raise NetworkError('unsupported')
            c,b,_=self._context(actor,owner_id,row['binding_id'],plan.resource_id)
            self.ledger._authorize(actor,owner_id,c,b,'recover')
            self.ledger._ready(c,b,plan)
            if c.credential_ref!=row['credential_ref']:raise NetworkError('conflict')
            self._gate(c,b,plan.resource_id,plan.after,'publish',plan.desired_revision)
            rows=self._inventory(self.provider_factory(c),c,b,plan.resource_id)
            relevant=self._relevant(rows,plan.after.name,b.zone_name)
            if len(relevant)!=1 or not matches(relevant[0],plan.after,row['marker'],row['response_record_id']):
                raise NetworkError('conflict')
            self._gate(c,b,plan.resource_id,plan.after,'publish',plan.desired_revision)
            return self.ledger.transition(actor,owner_id,request_id,expected_revision,'succeeded',
                proof='matched',record_id=row['response_record_id'])
