"""Read-validated activation/rotation and atomic local revocation/disconnect.

Vault storage and DNS/host collection stay in trusted application adapters. These
operations never create/delete provider assets or revoke a provider-side API key.
"""
from dataclasses import asdict, replace, dataclass
from .contracts import NetworkError
from .models import ZoneBinding, canonical, identifier, timestamp
from .ledger import TERMINAL, digest
from .cloudflare import CloudflareDns
from .porkbun_dns import PorkbunDns


@dataclass(frozen=True)
class ValidationReceipt:
    connection_id: str
    connection_revision: int
    credential_ref: str
    targets_hash: str
    valid_until: float


class ReadOnlyConnectionValidator:
    def __init__(self, authority_gate, secrets=None, transport=None, *, provider_factory=None):
        self.authority_gate=authority_gate
        self.factory=provider_factory or (lambda c:(CloudflareDns if c.provider=='cloudflare' else PorkbunDns)(c,secrets,transport))

    def validate(self, connection, bindings):
        provider=self.factory(connection)
        expiries=[]
        for binding in bindings:
            zone=provider.get_zone(binding.zone_id)
            if (zone.get('id')!=binding.zone_id or canonical(zone.get('name'))!=binding.zone_name
                    or zone.get('account',{}).get('id')!=connection.account_ref or zone.get('status')!='active'):
                raise NetworkError('conflict')
            # Validate target read access, not merely ping/token authentication.
            cursors=set();cursor=None;ids=set()
            for _ in range(1000):
                page=provider.list_records(binding.zone_id,cursor)
                for record in page.items:
                    rid=record.get('id')
                    if not isinstance(rid,str) or not rid or rid in ids:raise NetworkError('validation')
                    ids.add(rid)
                if page.next_cursor is None:break
                if page.next_cursor in cursors:raise NetworkError('validation')
                cursors.add(page.next_cursor);cursor=page.next_cursor
            else:raise NetworkError('validation')
            evidence=self.authority_gate.authority(connection,binding)
            expiries.extend([evidence.delegation_observed_at+300]+[v.observed_at+300 for v in evidence.answers])
        if not expiries:raise NetworkError('permission')
        return ValidationReceipt(connection.id,connection.revision,connection.credential_ref,
                                 digest([asdict(b) for b in bindings]),min(expiries))


class ConnectionLifecycle:
    def __init__(self, ledger, validator):
        self.ledger,self.store,self.validator=ledger,ledger.store,validator

    def _load(self, actor, owner, connection_id):
        connection=self.ledger._connection(connection_id)
        self.ledger._authorize(actor,owner,connection,None,'configure')
        bindings=[ZoneBinding(**v) for v in self.store.all('binding') if v['connection_id']==connection_id]
        return connection,bindings

    def _audit(self, actor, connection, action, old_revision):
        key=digest([connection.id,connection.revision,action])
        self.store.write('lifecycle-event',key,dict(owner_id=connection.owner_id,connection_id=connection.id,
            actor=actor,action=action,from_revision=old_revision,to_revision=connection.revision,at=self.ledger._now()))

    def _cancel_undispatched(self, actor, connection_id):
        for row in self.store.all('operation'):
            if row['connection_id']==connection_id and row['state'] in ('prepared','retry-wait'):
                now=self.ledger._now()
                row.update(state='cancelled',revision=row['revision']+1,updated_at=now,retry_at=None,next_check_at=None)
                row['events'].append(dict(state='cancelled',at=now,actor=actor,reason='connection-lifecycle'))
                self.store.write('operation',digest([row['owner_id'],row['request_id']]),row)

    def _validate_switch(self, actor, owner, connection_id, reference, expected_revision, *, rotating):
        identifier(reference)
        with self.store.worker_lock():
            with self.store.transaction():
                old,bindings=self._load(actor,owner,connection_id)
                if type(expected_revision) is not int or old.revision!=expected_revision:raise NetworkError('conflict')
                if old.status not in (('ready',) if rotating else ('unverified','action-required')):
                    raise NetworkError('permission')
                targets=[b for b in bindings if b.status!='detached']
                if not targets or len(targets)>256 or any(b.status=='blocked' or not b.nameservers for b in targets):
                    raise NetworkError('permission')
                for b in targets:self.ledger._authorize(actor,owner,old,b,'configure')
                if rotating and reference==old.credential_ref:raise NetworkError('validation')
                if any(o['connection_id']==connection_id and o['state'] not in TERMINAL|{'prepared','retry-wait'}
                       for o in self.store.all('operation')):
                    raise NetworkError('conflict')
                candidate=replace(old,credential_ref=reference,revision=old.revision+1,status='ready')
                started=self.ledger._now()
            # Potentially slow provider reads and fresh authority checks outside DB.
            # The old credential remains active until every target validates.
            receipt=self.validator.validate(candidate,tuple(targets))
            if not isinstance(receipt,ValidationReceipt) or (
                    receipt.connection_id,receipt.connection_revision,receipt.credential_ref,receipt.targets_hash)!=(
                    candidate.id,candidate.revision,candidate.credential_ref,digest([asdict(b) for b in targets])):
                raise NetworkError('permission')
            timestamp(receipt.valid_until)
            with self.store.transaction():
                current,current_bindings=self._load(actor,owner,connection_id)
                if current!=old or current_bindings!=bindings:raise NetworkError('conflict')
                now=self.ledger._now()
                if not 0<=now-started<=300 or now>receipt.valid_until:raise NetworkError('permission')
                if any(o['connection_id']==connection_id and o['state'] not in TERMINAL|{'prepared','retry-wait'}
                       for o in self.store.all('operation')):
                    raise NetworkError('conflict')
                for b in targets:self.ledger._authorize(actor,owner,current,b,'configure')
                # A revoke/disconnect can run while validation is in progress; CAS
                # above ensures it can never be undone by this completion.
                self.store.write('connection',connection_id,asdict(candidate))
                if not rotating:
                    for b in targets:
                        self.store.write('binding',b.id,asdict(replace(b,status='ready',revision=b.revision+1)))
                self._cancel_undispatched(actor,connection_id)
                self._audit(actor,candidate,'rotate' if rotating else 'activate',old.revision)
                return candidate

    def activate(self, actor, owner_id, connection_id, expected_revision):
        with self.store.transaction():
            connection,_=self._load(actor,owner_id,connection_id)
            reference=connection.credential_ref
        return self._validate_switch(actor,owner_id,connection_id,reference,expected_revision,rotating=False)

    def rotate(self, actor, owner_id, connection_id, credential_ref, expected_revision):
        return self._validate_switch(actor,owner_id,connection_id,credential_ref,expected_revision,rotating=True)

    def suspend(self, actor, owner_id, connection_id, expected_revision, *, disconnect=False):
        if type(disconnect) is not bool:raise ValueError('Expected disconnect flag')
        # Do not wait on the network worker lock: local revocation takes effect now.
        with self.store.transaction():
            old,bindings=self._load(actor,owner_id,connection_id)
            if type(expected_revision) is not int or old.revision!=expected_revision:raise NetworkError('conflict')
            changed=replace(old,status='disconnected' if disconnect else 'revoked',revision=old.revision+1)
            self.store.write('connection',connection_id,asdict(changed))
            for b in bindings:
                if b.status!='detached':
                    self.store.write('binding',b.id,asdict(replace(b,status='detached' if disconnect else 'blocked',revision=b.revision+1)))
            self._cancel_undispatched(actor,connection_id)
            self._audit(actor,changed,'disconnect' if disconnect else 'revoke',old.revision)
            return changed
