"""Additional DNS destinations, serialized with the existing central controller.

The legacy primary assignment remains API-compatible. Each additional destination
has independent immutable selection, durable ledger, intent, and retirement state.
"""
from dataclasses import asdict
from pathlib import Path
import re
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from zog.network_register.contracts import NetworkError
from zog.network_register.dns_authority import DnsAuthorityCollector
from zog.network_register.evidence import EvidenceGate
from zog.network_register.engine import DnsEngine
from zog.network_register.ledger import OperationLedger,TERMINAL
from zog.network_register.models import canonical
from zog.network_register.reservations import NameReservations
from zog.network_register.store import SqliteStateStore
from .dns_cutover import Authorization
from .dns_evidence import selection,RegistryEvidenceSource,RegistrySecretResolver,owner_authorized
from .dns_reconcile import controller_lock,serialize_assignment
from .dns_shared import reconcile_runtime
from .identity import locked
from .models import AdditionalDnsAssignment as Assignment,DnsDestination,Host,SecurityAudit,DnsAssignment,ProviderCredential


def authorize(destination,actor_id):
    owner=destination.selection['owner_user_id'];owner_authorized(owner)
    if actor_id is not None and actor_id!=owner:raise NetworkError('permission')


def ledger_path(root,relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts:raise NetworkError('validation')
    target=(root/p).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():raise NetworkError('storage')
    return target


def runtime(destination,root, *, collector=None,provider_factory=None,allow_phase=False):
    if not destination.enabled:raise NetworkError('permission')
    assignments=destination.assignments.all()
    if not allow_phase and assignments.exclude(phase='ready').exists():raise NetworkError('conflict')
    data=dict(destination.selection,host_ids=sorted(str(x) for x in assignments.values_list('host_id',flat=True)))
    selected=selection(data,allow_empty=True)
    class Source(RegistryEvidenceSource):
        def current(self):
            current=DnsDestination.objects.get(pk=destination.pk)
            if not current.enabled or current.selection!=destination.selection or current.ledger_path!=destination.ledger_path:
                raise NetworkError('conflict')
            return super().current()
    source=Source(selected,collector or DnsAuthorityCollector(),assignment_resolver=lambda r:Assignment.objects.get(binding=destination,host_id=r))
    gate=EvidenceGate(source)
    authority=gate.authority(selected.connection,selected.binding)
    class Cached:
        def authority(self,*_):return authority
    source.collector=Cached()
    store=SqliteStateStore(ledger_path(root,destination.ledger_path))
    ledger=OperationLedger(store,Authorization(source))
    with store.transaction():c,b=ledger._context(destination.pk)
    if c!=selected.connection or b!=selected.binding:raise NetworkError('conflict')
    return selected,source,DnsEngine(ledger,gate,RegistrySecretResolver(source),provider_factory=provider_factory)


def refresh(source,gate,resource):
    proposed=RegistryEvidenceSource(source.selected,source.collector,use_observed_address=True,assignment_resolver=source.assignment_resolver)
    c,b=source.selected.connection,source.selected.binding
    with locked():
        source.current()
        evidence=proposed.host(c.owner_id,b.id,resource)
        EvidenceGate(proposed).check(c,b,resource,evidence.desired,'publish' if evidence.publish_enabled else 'unpublish',evidence.desired_revision)
        row=source.assignment_resolver(resource)
        if row.phase!='ready':raise NetworkError('conflict')
        wanted=('present',evidence.desired.address) if evidence.desired else ('absent','')
        if (row.desired_action,row.desired_address)!=wanted:
            row.desired_action,row.desired_address=wanted;row.revision+=1
            row.save(update_fields=['desired_action','desired_address','revision'])
        return row,evidence.desired


def project(destination,resource,status, *, operation=None,record=None,revision=None):
    values=dict(status=status,last_attempt=timezone.now(),error='',error_code='')
    if operation:
        values.update(last_action=operation['state'],error_code=operation.get('last_error_code') or '')
        if operation['state']=='succeeded':values.update(last_action=operation['plan']['action'],last_change=timezone.now())
    if status in ('synchronized','unpublished'):
        values.update(last_success=timezone.now(),applied_revision=revision,record_id=record['record_id'] if record else '',observed_address=record['last_applied']['address'] if record else '')
    Assignment.objects.filter(binding=destination,host_id=resource).update(**values)


def reconcile_all(config,root, *, resource_ids=None,collector=None,provider_factory=None):
    outcomes={}
    for destination in DnsDestination.objects.filter(enabled=True).order_by('pk'):
        try:
            selected,source,engine=runtime(destination,root,collector=collector,provider_factory=provider_factory)
            targets=None if resource_ids is None else [r for r in resource_ids if r in selected.host_ids]
            if resource_ids is not None and not targets:continue
            result=reconcile_runtime(selected,source,engine,resource_ids=targets,refresh=refresh,
                projection=lambda resource,status,**kw:project(destination,resource,status,**kw))
            for k,v in result.items():outcomes[k]=outcomes.get(k,0)+v
        except (NetworkError,OSError,ValueError,ObjectDoesNotExist) as error:
            code=error.code if isinstance(error,NetworkError) else 'storage'
            destination.assignments.update(status='conflict' if code=='conflict' else 'waiting_verification',error_code=code,error='DNS destination requires verification.',last_attempt=timezone.now())
            outcomes['conflict' if code=='conflict' else 'provider_error']=outcomes.get('conflict' if code=='conflict' else 'provider_error',0)+1
    return outcomes


def configure(config,binding_id,host_id,action, *, actor_id,label=None,expected_revision=None,collector=None,provider_factory=None):
    """Reserve/enable/unpublish/release exactly one additional assignment.

    A reserving/releasing DB row fences the entire destination across crashes;
    repeating that action resumes its deterministic name receipt.
    """
    if action not in ('reserve','enable','unpublish','release','cancel'):raise NetworkError('validation')
    with controller_lock(config,modes=('shared',)) as root:
        destination=DnsDestination.objects.get(pk=binding_id);authorize(destination,actor_id)
        row=Assignment.objects.filter(binding=destination,host_id=host_id).first()
        if action=='reserve':
            if not isinstance(label,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label):raise NetworkError('validation')
            name=canonical(label+'.'+destination.selection['prefix'])
            if row is None:
                with locked():
                    host=Host.objects.get(pk=host_id)
                    if host.archived_at or host.provider!='aws':raise NetworkError('permission')
                    if DnsAssignment.objects.filter(name=name).exists():raise NetworkError('conflict')
                    row=Assignment.objects.create(binding=destination,host=host,name=name,owner_id='host-discover:'+str(host_id),phase='reserving',enabled=True,desired_action='present')
            if row.phase!='reserving' or row.name!=name:raise NetworkError('conflict')
        else:
            if row is None:raise NetworkError('not-found')
            if expected_revision!=row.revision:raise NetworkError('conflict')
        if action=='cancel':
            # Discard only a reservation whose durable ledger was never changed.
            # This recovery needs no healthy DNS or still-approved host.
            from zog.network_register.ledger import digest
            if row.phase!='reserving':raise NetworkError('conflict')
            store=SqliteStateStore(ledger_path(root,destination.ledger_path))
            with store.transaction():
                allocation=store.read('allocation',digest([destination.pk,str(host_id)]))
                record=store.read('record',digest([destination.pk,str(host_id)]))
                if (store.read('name-receipt',digest(['user:'+str(actor_id),'reserve:'+str(row.pk)]))
                        or (allocation and allocation['state']!='released')
                        or (record and not record.get('deleted'))
                        or any(o['plan']['resource_id']==str(host_id) and o['state'] not in TERMINAL for o in store.all('operation'))):
                    raise NetworkError('conflict')
            with locked():row.delete()
            return None
        selected,source,engine=runtime(destination,root,collector=collector,provider_factory=provider_factory,allow_phase=True)
        if destination.assignments.exclude(pk=row.pk).exclude(phase='ready').exists():raise NetworkError('conflict')
        c,b=selected.connection,selected.binding;actor=c.owner_id
        if action=='reserve':
            proposed=RegistryEvidenceSource(selected,source.collector,use_observed_address=True,assignment_resolver=source.assignment_resolver)
            h=proposed.host(actor,b.id,str(host_id));EvidenceGate(proposed).check(c,b,str(host_id),h.desired,'publish',h.desired_revision)
            receipt=NameReservations(engine).change(actor,actor,b.id,str(host_id),row.name,'reserve','reserve:'+str(row.pk),connection_revision=c.revision,binding_revision=b.revision)
            with locked():
                row.revision=receipt['revision_floor'];row.phase='ready';row.desired_address=h.desired.address;row.save()
        elif action=='release':
            if row.enabled or row.record_id or row.desired_action!='absent' or row.phase not in ('ready','releasing'):raise NetworkError('conflict')
            row.phase='releasing';row.save(update_fields=['phase'])
            NameReservations(engine).change(actor,actor,b.id,str(host_id),row.name,'release','release:'+str(row.pk),connection_revision=c.revision,binding_revision=b.revision)
            with locked():
                SecurityAudit.objects.create(actor=actor,action='dns-destination-release',host_id_text=str(host_id),details=dict(binding_id=b.id,name=row.name))
                row.delete()
            return None
        else:
            if row.phase!='ready':raise NetworkError('conflict')
            if action=='enable':
                if row.host.archived_at:raise NetworkError('permission')
                # A released allocation cannot be revived by a racing request.
                with engine.store.transaction():
                    from zog.network_register.ledger import digest
                    allocation=engine.store.read('allocation',digest([b.id,str(host_id)]))
                if allocation and allocation['state']!='reserved':raise NetworkError('conflict')
            with locked():
                row.enabled=action=='enable';row.revision+=1;row.status='pending';row.save(update_fields=['enabled','revision','status'])
        return serialize(row)


def serialize(row):
    provider=ProviderCredential.objects.filter(pk=row.binding.selection['credential_id']).values_list('provider',flat=True).first() or 'unknown'
    return dict(serialize_assignment(row),id=str(row.pk),binding_id=row.binding_id,phase=row.phase,
        prefix=row.binding.selection['prefix'],provider=provider,ttl=600 if provider=='porkbun' else 300)


def import_destination(config,data,relative_path, *, collector=None,provider_factory=None):
    """Import an existing owned ledger; performs reads only against the provider.

    Used for explicit installation/migration, never accepts browser-supplied paths.
    Requires all operations resolved and every selected host record proven equal.
    """
    from types import SimpleNamespace
    from zog.network_register.models import RecordSnapshot,below
    with controller_lock(config,modes=('shared',)) as root:
        selected=selection(data);c,b=selected.connection,selected.binding
        if DnsDestination.objects.filter(pk=b.id).exists():raise NetworkError('conflict')
        prefixes=[config['suffix']]+[v['prefix'] for v in DnsDestination.objects.values_list('selection',flat=True)]
        if any(p==b.prefix or below(p,b.prefix) or below(b.prefix,p) for p in prefixes):raise NetworkError('conflict')
        store=SqliteStateStore(ledger_path(root,relative_path))
        with store.transaction():
            if any(o['state'] not in TERMINAL for o in store.all('operation')):raise NetworkError('conflict')
            records=store.all('record')
            if any(r.get('deleted') or r.get('binding_id')!=b.id for r in records):raise NetworkError('conflict')
        if set(r['resource_id'] for r in records)!=set(selected.host_ids):raise NetworkError('conflict')
        proposed={r['resource_id']:SimpleNamespace(name=r['last_applied']['name'],enabled=True,revision=r['desired_revision'],desired_action='present',desired_address=r['last_applied']['address']) for r in records}
        source=RegistryEvidenceSource(selected,collector or DnsAuthorityCollector(),proposed_assignments=proposed)
        gate=EvidenceGate(source);authority=gate.authority(c,b)
        class Cached:
            def authority(self,*_):return authority
        source.collector=Cached()
        ledger=OperationLedger(store,Authorization(source));engine=DnsEngine(ledger,gate,RegistrySecretResolver(source),provider_factory=provider_factory)
        with store.transaction():oldc,oldb=ledger._context(b.id)
        if oldc!=c or oldb!=b:raise NetworkError('conflict')
        for record in records:
            r=record['resource_id'];desired=RecordSnapshot(**record['last_applied'])
            if engine.plan(c.owner_id,c.owner_id,b.id,r,desired,record['desired_revision']) is not None:raise NetworkError('conflict')
        with locked():
            for record in records:
                h=source.host(c.owner_id,b.id,record['resource_id']);gate.check(c,b,record['resource_id'],h.desired,'publish',h.desired_revision)
            destination=DnsDestination.objects.create(id=b.id,selection=data,ledger_path=relative_path,enabled=True)
            for record in records:
                Assignment.objects.create(binding=destination,host_id=record['resource_id'],name=record['last_applied']['name'],owner_id='host-discover:'+record['resource_id'],revision=record['desired_revision'],desired_action='present',desired_address=record['last_applied']['address'],applied_revision=record['desired_revision'],status='synchronized',record_id=record['record_id'],observed_address=record['last_applied']['address'],last_success=timezone.now())
            SecurityAudit.objects.create(actor=c.owner_id,action='dns-destination-import',details=dict(binding_id=b.id,hosts=list(selected.host_ids)))
        return dict(binding_id=b.id,hosts=list(selected.host_ids))
