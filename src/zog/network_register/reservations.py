"""Audited allocation/release of names. Provider operations are reads only."""
from .contracts import NetworkError
from .ledger import digest, TERMINAL
from .models import canonical, resource_uuid, identifier, revision, below


class NameReservations:
    def __init__(self, engine):
        self.engine, self.ledger, self.store = engine, engine.ledger, engine.store

    def _local(self, binding, resource, name, action):
        operations = self.store.all('operation')
        if any(o['binding_id'] == binding.id and o['state'] not in TERMINAL for o in operations):
            raise NetworkError('conflict')
        key = digest([binding.id, resource])
        allocation = self.store.read('allocation', key)
        record = self.store.read('record', key)
        reservations = self.store.all('reservation')
        owned = [r for r in reservations if (r['binding_id'], r['resource_id']) == (binding.id, resource)]
        named = [r for r in reservations if r['name'] == name]
        if action == 'reserve':
            if owned or named or record not in (None, {'deleted': True}) or (allocation and allocation['state'] != 'released'):
                raise NetworkError('conflict')
        elif record != {'deleted': True} or owned != named or len(owned) != 1:
            raise NetworkError('conflict')
        previous = [o['plan']['desired_revision'] for o in operations
                    if o['binding_id'] == binding.id and o['plan']['resource_id'] == resource]
        return max([0, (allocation or {}).get('revision_floor', 0)] + previous) + 1

    def check(self, actor, owner_id, binding_id, resource_id, name, action, *, connection_revision, binding_revision):
        return self._run(actor, owner_id, binding_id, resource_id, name, action,
                         connection_revision, binding_revision, None)

    def change(self, actor, owner_id, binding_id, resource_id, name, action, request_id, *, connection_revision, binding_revision):
        identifier(request_id)
        return self._run(actor, owner_id, binding_id, resource_id, name, action,
                         connection_revision, binding_revision, request_id)

    def _run(self, actor, owner, binding_id, resource, name, action, cr, br, request):
        resource = resource_uuid(resource); name = canonical(name)
        revision(cr); revision(br)
        if action not in ('reserve', 'release'): raise NetworkError('validation')
        payload = digest([binding_id, resource, name, action, cr, br])
        receipt_key = digest([owner, request])
        with self.store.worker_lock():
            with self.store.transaction():
                c, b = self.ledger._context(binding_id)
                self.ledger._authorize(actor, owner, c, b, action)
                if request:
                    old = self.store.read('name-receipt', receipt_key)
                    if old:
                        if old['payload_hash'] != payload: raise NetworkError('conflict')
                        return old
                if c.status != 'ready' or b.status != 'ready' or (c.revision, b.revision) != (cr, br):
                    raise NetworkError('conflict')
                if not below(name, b.prefix) or '.' in name[:-(len(b.prefix) + 1)]:
                    raise NetworkError('validation')
                floor = self._local(b, resource, name, action)
            rows = self.engine._inventory(self.engine.provider_factory(c), c, b, resource)
            if self.engine._relevant(rows, name, b.zone_name): raise NetworkError('conflict')
            self.engine._gate(c, b, resource, None, 'inspect')
            with self.store.transaction():
                cc, bb = self.ledger._context(binding_id)
                self.ledger._authorize(actor, owner, cc, bb, action)
                if (cc, bb) != (c, b) or self._local(b, resource, name, action) != floor:
                    raise NetworkError('conflict')
                result = dict(owner_id=owner, binding_id=b.id, resource_id=resource, name=name,
                              action=action, revision_floor=floor, actor=actor,
                              at=self.ledger._now(), request_id=request, payload_hash=payload)
                if request:
                    if action == 'reserve':
                        self.store.write('reservation', digest(name), dict(name=name, binding_id=b.id, resource_id=resource))
                        self.store.write('record', digest([b.id, resource]), {'deleted': True})
                    else:
                        self.store.delete('reservation', digest(name))
                    self.store.write('allocation', digest([b.id, resource]), dict(name=name,
                        state='reserved' if action == 'reserve' else 'released', revision_floor=floor, request_id=request))
                    self.store.write('name-receipt', receipt_key, result)
                return result
