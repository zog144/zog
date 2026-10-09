"""Explicit one-record Porkbun initialization, separate from reconciliation.

Parent delegation and host evidence remain mandatory. A provider-applied result
is not proof of authoritative DNS readiness. The caller must run the normal
AuthorityCollector/EvidenceGate after this operation before activating a binding.
"""
from .contracts import NetworkError
from .engine import DnsEngine
from .evidence import fresh
from .ledger import digest
from .models import RecordSnapshot
from .porkbun_dns import PorkbunDns
from .state import locked

PORKBUN_NAMESERVERS = tuple(sorted((
    'curitiba.ns.porkbun.com', 'fortaleza.ns.porkbun.com',
    'maceio.ns.porkbun.com', 'salvador.ns.porkbun.com')))


def initialize_porkbun_a(ledger, gate, collector, secrets, actor, connection,
                         binding, resource, desired, desired_revision, *, transport=None):
    """Create the first A record in an empty native Porkbun zone, at most once.

    Uses an already authorized ledger connection/binding and trusted host source.
    Exact inputs are pinned durably before preparation. Repeated calls recover
    the same operation; they never dispatch a second create, even after failure.
    Existing/nonempty zones, other providers, changed inputs and foreign NS fail.
    A returned `succeeded` means provider-applied only. Warnings retain the normal
    conflict outcome and must be inspected; do not blindly retry or erase state.
    """
    c,b=connection,binding
    if (c.provider!='porkbun' or b.zone_id!=b.zone_name
            or b.nameservers!=PORKBUN_NAMESERVERS
            or not isinstance(desired,RecordSnapshot)):
        raise NetworkError('permission')
    payload=dict(connection=c.id,binding=b.id,resource=resource,
                 desired=desired.__dict__,desired_revision=desired_revision,
                 connection_revision=c.revision,binding_revision=b.revision,
                 credential_ref=c.credential_ref)
    request='initialize:'+digest(payload)
    key=digest([c.owner_id,b.id])
    # This lock serializes initialization callers; engine worker locks still
    # serialize each dispatch with any other process using this ledger.
    with locked(ledger.store.path.parent/'initialization-lock'):
        current_c,current_b,owned=ledger.context(actor,c.owner_id,b.id,resource)
        if current_c!=c or current_b!=b:raise NetworkError('conflict')
        gate.check_host(c,b,resource,desired,'publish',desired_revision)
        stamp=collector.delegation(c,b)
        if not fresh(stamp,gate.clock()):raise NetworkError('permission')
        class InitializationGate:
            def check(self,cc,bb,rr,dd,action,revision):
                if cc!=c or bb!=b or rr!=resource or action not in ('inspect','publish'):
                    raise NetworkError('permission')
                if action=='publish' and (dd!=desired or revision!=desired_revision):
                    raise NetworkError('conflict')
                gate.check_host(c,b,resource,desired,'publish',desired_revision)
                if not fresh(stamp,gate.clock()):raise NetworkError('permission')
        class Provider(PorkbunDns):
            require_native_inventory=True
            def list_records(self,zone_id,cursor=None):
                page=super().list_records(zone_id,cursor)
                if len(page.items)>1 or any(r['name']!=desired.name or r['type']!='A' for r in page.items):
                    raise NetworkError('conflict')
                return page
            def get_zone(self,zone_id):
                if zone_id!=b.zone_name:raise NetworkError('permission')
                # Authenticated account membership; do not call normal preflight,
                # which depends on the child zone already answering NS queries.
                cursor=None;seen=set();found=[]
                for _ in range(1000):
                    page=self.list_zones(cursor)
                    found.extend(r for r in page.items if r['name']==zone_id)
                    if page.next_cursor is None:break
                    if page.next_cursor in seen:raise NetworkError('validation')
                    seen.add(page.next_cursor);cursor=page.next_cursor
                else:raise NetworkError('validation')
                if len(found)!=1:raise NetworkError('permission')
                return dict(id=zone_id,name=zone_id,account={'id':c.account_ref},status='active')
        provider=Provider(c,secrets,transport)
        engine=DnsEngine(ledger,InitializationGate(),provider_factory=lambda _:provider)
        with ledger.store.transaction():saved=ledger.store.read('initialization',key)
        if saved:
            if saved!=payload:raise NetworkError('conflict')
            try:operation=ledger.inspect_operation(actor,c.owner_id,request)
            except NetworkError as error:
                if error.code!='not-found':raise
                operation=None  # crash before prepare; no dispatch occurred
            if operation is not None:
                return engine.apply(actor,c.owner_id,request,operation['revision'])
        if owned:raise NetworkError('conflict')
        provider.get_zone(b.zone_id)
        if provider.list_records(b.zone_id).items:raise NetworkError('conflict')
        plan=engine.plan(actor,c.owner_id,b.id,resource,desired,desired_revision)
        if plan is None or plan.action!='create':raise NetworkError('conflict')
        with ledger.store.transaction():ledger.store.write('initialization',key,payload)
        row=ledger.prepare(actor,request,plan)
        return engine.apply(actor,c.owner_id,request,row['revision'])
